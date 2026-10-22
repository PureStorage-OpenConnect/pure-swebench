# Running zbench on your own models and harnesses

How to point the eval at the models you care about: hosted frontier models through their
vendor APIs, and open-weight models served on your own GPUs. For the complete
start-to-finish replication of the published numbers, follow
[`replicate-zbench.md`](replicate-zbench.md); this guide is the reference for the
model-and-harness part of it.

Concepts: a **harness** is the agent scaffold (the CLI that reads the problem, edits files,
iterates); a **model** is what the harness talks to. zbench pairs them as one `agent_id`
= model x harness x provider. The eval never scores an LLM completion directly: the
harness produces a patch, and the hidden test grades it.

Everything credential-shaped comes from environment variables. Copy `.env.example` to
`.env`, fill in only what the agents you select need, and load it into your shell with
`set -a; . ./.env; set +a`. Nothing in the repo stores a key, and the harness never
needs one in an agent row.

---

## 1. Prerequisites and bring-up

The machine setup (Docker, Python, a full clone of the target repo, the base image, the
per-task grading images) is the same for every model and is documented step by step in
[`replicate-zbench.md`](replicate-zbench.md) sections 1-5. Short form:

```bash
git clone https://github.com/zulip/zulip.git "$HOME/work/zulip"   # full clone, not --depth
export ZBENCH_TARGET_REPO="$HOME/work/zulip"
docker pull zulip/ci:noble
tools/run_tests.sh static
python3 zbench-tasks/scripts/prebuild_env_images.py            # prints the disk/time plan
python3 zbench-tasks/scripts/prebuild_env_images.py --limit 5 --go
tools/run_eval.sh --list
```

### Env vars worth knowing

| var | default | why |
|---|---|---|
| `ZBENCH_TARGET_REPO` | `~/work/zulip` | the target-repo clone; the one you almost always need |
| `ZBENCH_CI_IMAGE` | `zulip/ci:noble` | base image for env builds |
| `ZBENCH_MIN_COMMIT_DATE` | `2025-01-01` | mining floor (corpus growth only) |
| `ZBENCH_AGENT_TIMEOUT` | per-agent row | wall-clock cap per attempt; keep equal across harnesses for a fair comparison |
| `ZBENCH_SLOT_CAP_<pool>` | see `DEFAULT_CAPS` in `zbench/cells/slots.py` | concurrency caps (`__` stands in for `:`) |
| `ZBENCH_LLM` | `claude` | backend for curation/judge LLM calls (corpus growth only) |
| `ZBENCH_SERVING_ROOT` | `<repo>/.serving` | where serving venvs, weights and logs live (see section 4) |
| `ANTHROPIC_API_KEY` | unset | Claude models via `claude` / `pi` |
| `OPENAI_API_KEY` | unset | GPT models via `codex` / `pi` |

Everything else (`ZBENCH_DATA_DIR`, `ZBENCH_BENCHDB_DIR`, `ZBENCH_CELL_*`, ...) is set by
the launchers per run; do not set them by hand.

---

## 2. Installing the harnesses

You need only the harnesses for the agents you select. `tools/run_eval.sh --go` runs a
preflight and exits 66 (launching nothing) if a selected agent's CLI or credential is
missing.

### 2.1 Node.js

```bash
# Node 20+ (nvm shown; any install works)
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
nvm install 20
```

### 2.2 `claude` (Claude models only)

```bash
npm i -g @anthropic-ai/claude-code
claude login                            # OAuth; or: export ANTHROPIC_API_KEY=<your key>
claude --print --model claude-fable-5 "reply OK"    # smoke test
```

Adapter: `zbench/agents/claude_agent.py`. The model is chosen per agent through
`CLAUDE_MODEL_NAME`. The harness runs the CLI with an isolated config directory
(`zbench/hermetic.py`) so ambient skills, MCP servers and memory do not leak into a
measured run; it seeds that directory with `~/.claude/.credentials.json` if present
(`ZBENCH_HERMETIC=0` opts out). The claude CLI sends requests to Anthropic's API, which
rejects non-Claude model ids; use `pi` for cross-vendor comparisons.

### 2.3 `codex` (GPT models, and any Responses-API-compatible endpoint)

```bash
npm i -g @openai/codex
codex --version
export OPENAI_API_KEY=<your key>
```

Adapter: `zbench/agents/codex_agent.py`. Per-agent env:

| env | meaning |
|---|---|
| `CODEX_MODEL_NAME` | `--model` (for example `gpt-5.6-sol`, or your served open-weight name) |
| `CODEX_BASE_URL` | OpenAI-compatible base URL; shipped rows use `https://api.openai.com/v1`. For a self-hosted vLLM: `http://<your-gpu-host>:<port>/v1` |
| `CODEX_API_KEY` | key for that endpoint (a local vLLM accepts any non-empty token) |
| `CODEX_WIRE_API` | `chat` or `responses`; configures a custom codex model provider via `-c` overrides |
| `CODEX_EXEC_ARGS` | override the exec flags if your codex version differs from the adapter default |
| `CODEX_STREAM_MAX_RETRIES` | codex's SSE reconnect budget (default here 10) |
| `CODEX_REQUEST_MAX_RETRIES` | codex's HTTP retry budget (default here 8) |
| `CODEX_STREAM_IDLE_TIMEOUT_MS` | how long codex waits on a silent stream (default here 300000) |
| `CODEX_MAX_ATTEMPTS` | how many whole codex runs the adapter tries after a retryable provider failure (default 3) |
| `CODEX_RETRY_BACKOFF_S` | first backoff between those attempts; doubles each time (default 20) |

Things that bite:

- **Codex needs a Responses-API endpoint.** codex 0.125.0 removed `wire_api = "chat"`.
  A chat-completions-only backend needs a translating proxy. vLLM 0.24.0 serves
  `/v1/responses` with streaming and tools and needs no flag. Beware: vLLM answers an
  unknown model name with a 404 whose body is `The model ... does not exist`, which looks
  like a missing route; a truly absent route says `{"detail":"Not Found"}`.
- **Codex flag drift.** If a run fails with an unknown-flag error, set `CODEX_EXEC_ARGS`
  to your version's headless invocation (`codex exec --help`). The adapter default is
  `codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox --json`.
- **Rate limits do not always look like HTTP errors.** Some gateways accept a request with
  a 200 and then kill the stream mid-turn when you exceed a per-minute token quota. The
  adapter widens codex's reconnect budget, retries the whole run with backoff, and records
  a provider failure as status `provider_error` (counted as infrastructure, never as a
  capability miss). Codex resends its whole conversation every turn, so on a
  low-quota key wall-clock is set by the quota, not by model speed.
- **Do not set `CODEX_HOME` under `/tmp`**; codex then refuses to create helper binaries
  and the warning masks the real error.
- **Codex does not deliver the reasoning-effort setting** on the custom-provider path
  (see RUNBOOK "Reasoning effort"), and **attaches a `web_search` tool** it could not be
  told to drop (RUNBOOK "codex sends a web_search tool"). Treat codex rows as
  effort-uncontrolled and contamination-unverified when you compare them.

### 2.4 `pi`

`pi` is an open-source minimalist coding agent
([badlogic/pi-mono](https://github.com/badlogic/pi-mono)). Install the
`@mariozechner/pi-coding-agent` package (the repo's results used 0.73.1). Note that the
npm package `@mariozechner/pi` is a different tool.

```bash
npm i -g --prefix ~/.local @mariozechner/pi-coding-agent
pi --version
```

pi reads each **provider's** endpoint and credential from its own config
(`~/.pi/agent/models.json`); an agent row selects one with `PI_PROVIDER`. Anthropic and
OpenAI providers can use API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) or pi's
interactive `/login`. Adapter: `zbench/agents/pi_agent.py` (hermetic by default: no
context files, skills, extensions or persisted session; built-in file/shell tools are on).

A provider block for a self-hosted endpoint has this shape (see section 4.3; confirm the
field names against your pi version's documentation, as pi's config format is pi's, not
zbench's):

```json
{
  "providers": {
    "vllm-qwen3.6-27b": {
      "api": "openai-completions",
      "baseUrl": "http://<your-gpu-host>:8011/v1",
      "apiKey": "local",
      "models": [{"id": "qwen3.6-27b"}]
    }
  }
}
```

`api` selects the wire protocol: `openai-completions` or `openai-responses`.

---

## 3. Which harness runs which model

| Model family | Type | claude | codex | pi |
|---|---|:--:|:--:|:--:|
| Claude (Opus / Sonnet / Fable / Haiku) | hosted, proprietary | native | no | `anthropic` provider |
| GPT-5.6 family | hosted, proprietary | no | native | OpenAI provider |
| Open-weight (gpt-oss, Qwen, Nemotron, Gemma, Muse) | self-hosted | no | via your vLLM base URL (Responses API) | one provider per vLLM port |

`claude` runs Claude only. `codex` and `pi` are model-agnostic. The runnable cohort is
`zbench-tasks/agents-matrix.jsonl` (what `tools/run_eval.sh` selects from);
`zbench-tasks/agents-custom.jsonl` is a scratch file of additional rows you can adapt.
`agents-meta.jsonl` carries per-agent metadata (training cutoff, engine, quantization,
effort evidence); `run_eval.sh` hides rows marked `retired` there.

---

## 4. Self-hosting the open-weight models

### 4.1 Size your hardware first

How many GPUs each model needs, the memory arithmetic, KV-cache headroom, and launch
templates are in [`on-prem-gpu-sizing.md`](on-prem-gpu-sizing.md) (written for NVIDIA H200
and B300). Read it before editing the serving table. The rule of thumb: **serve one model
at a time unless the memory arithmetic shows every model fits on disjoint GPUs.**

### 4.2 Serving scripts

The scripts live in `tools/serving/` and are documented in
[`../tools/serving/README.md`](../tools/serving/README.md):

```bash
export ZBENCH_SERVING_ROOT=/path/to/bulk/storage     # venvs + weights + logs (~300 GB)
export HF_TOKEN=<your Hugging Face token>            # only for gated model repos
bash tools/serving/setup_venv.sh                     # needs `uv` on PATH
bash tools/serving/setup_venv.sh --muse-fork         # only if you serve Muse Glimmer
# Edit tools/serving/models.conf for YOUR GPUs first (gpus, port, tp columns).
bash tools/serving/serve_local.sh start <alias>      # or no alias = every row
bash tools/serving/serve_local.sh status             # poll until READY
bash tools/serving/serve_local.sh check <alias>      # proves tool calling works
```

`models.conf` is a **reference** configuration; its GPU indices, ports and TP sizes are
the machine-specific part (section 3.4 of the sizing guide gives an 8-GPU example).
Weights are downloaded into `$ZBENCH_HF_HOME` (default under the serving root); you must
have fetched them there before `start` (for example with
`huggingface-cli download <repo>` and `HF_HOME` pointed at that directory; do not set
`HF_HUB_ENABLE_HF_TRANSFER`, see the serving README for why).

### 4.3 Wire a served model into the harness

A running server is not yet a benchmark row. For each served model:

1. Add a pi provider block (section 2.4) per port. The shipped `pi-vllm-*` rows expect
   provider names `vllm-gpt-oss-120b` (port 8010), `vllm-qwen3.6-27b` (8011),
   `vllm-nemotron-3.5` (8012), `vllm-gemma-4-31b` (8013) and `vllm-muse-glimmer`
   (8014), each with `baseUrl` `http://<your-gpu-host>:<port>/v1`.
2. Make sure the agent row's `PI_MODEL` (or `CODEX_MODEL_NAME`) equals the server's
   `--served-model-name` (the `alias` column in `models.conf`).
3. Record engine, quantization and GPU count in `agents-meta.jsonl`; a score from a model
   on a different engine version reflects the engine as well as the model.

Smoke it: `tools/run_eval.sh --smoke --agent 'pi-vllm-qwen3.6-27b' --go`.

---

## 5. Register the agents you add

The five shipped families of rows (`pi-anthropic-*`, `claude-cli-*`, `pi-vllm-*`,
`codex-openai-*`, `pi-openai-*`) are already in `agents-matrix.jsonl`. To add your own:

1. **An agent row** in `zbench-tasks/agents-matrix.jsonl`:
   `{"agent_id", "command", "timeout_sec", "env": {...}}`. The loader
   (`zbench/ingest.py`) rejects unknown keys, so a typo fails loudly. Copy a neighbouring
   row for the same harness and change `agent_id` and the model env.
2. **A metadata row** in `agents-meta.jsonl` with `agent_id`, `model`, `provider`,
   `hosting`, `open_weight`, `ctx_window`, and, for contamination tiering,
   `training_cutoff` + `cutoff_source` + `cutoff_confidence` from the vendor's model card
   (tiers are advisory, not a gate: METHODOLOGY section 5). Then refresh tiers with
   `python3 zbench-tasks/scripts/recompute_tiers.py`.
3. **A price** so the cost-per-task axis resolves: `tools/prices/models_dev.json`
   (`tools/prices/refresh_prices.py` regenerates it from a models.dev snapshot) or, for a
   self-hosted open-weight model, `tools/prices/open_weight_hosted.json`. A self-hosted
   model is priced at a **public-host per-token reference rate**, not a hardware
   amortisation, so on-prem and hosted rows compare per token. A model with no pinned
   price reads as `free*`.
4. **A pinned reasoning effort** in the agent row. Never leave it unset: the vendor
   default is unrecorded and drifts.

   | harness | env key | levels |
   |---|---|---|
   | pi | `PI_THINKING` | off, minimal, low, medium, high, xhigh |
   | claude | `CLAUDE_EFFORT` | low, medium, high, xhigh, max |
   | codex | `CODEX_REASONING_EFFORT` | none, minimal, low, medium, high, xhigh |

   The shipped cohort pins `high`. Setting it is not proof the backend honors it; probe
   two levels and compare reasoning tokens (RUNBOOK "Reasoning effort"), then record the
   result as `effort_evidence` in `agents-meta.jsonl`.

---

## 6. Run the eval

```bash
export ZBENCH_TARGET_REPO="$HOME/work/zulip"
set -a; . ./.env; set +a

# plan only (no --go): shows agents, task count, already-covered cells
tools/run_eval.sh --harness claude-cli

# hosted models: run any time
tools/run_eval.sh --harness claude-cli --go
tools/run_eval.sh --harness codex --go

# open-weight: one served model at a time
bash tools/serving/serve_local.sh start qwen3.6-27b
tools/run_eval.sh --agent 'pi-vllm-qwen3.6-27b' --go
bash tools/serving/serve_local.sh stop qwen3.6-27b

# progress + coverage report
tools/run_eval.sh --report
```

Each concurrency pool (provider, setup, verify) has a cap; the launcher self-throttles and
is safe to re-run, because cells already recorded are skipped. Tune any pool without
editing code via `bench-db/.runtime/slots/caps.json` or `ZBENCH_SLOT_CAP_<pool>`.

Post-run review: see [`../RUNBOOK.md`](../RUNBOOK.md) "Post-run review".

---

## 7. Gotchas

- **Candidate vs ranked corpus.** The oracle makes a task `validated`; METHODOLOGY section
  2 additionally calls for human review (`zbench-tasks/review_task.py`) before a result is
  published as a ranking. You can run on the validated set immediately.
- **Training cutoffs** feed the contamination tier, which is advisory. Fill them from
  vendor model cards for any model you add.
- **Cost axis.** Self-hosted open-weight rows are costed at a public per-token reference
  rate (section 5 item 3), not at your hardware cost; if you want a GPU-hour-based number
  you must compute it yourself from wall-clock.
- **One model at a time** per GPU set unless the arithmetic in
  [`on-prem-gpu-sizing.md`](on-prem-gpu-sizing.md) says otherwise.
- **Fair-comparison hygiene.** Keep stopping conditions equal across harnesses
  (`ZBENCH_AGENT_TIMEOUT`) and turn OFF built-in web/search tools in each harness: the
  tasks come from a public repo and an agent could fetch the upstream fix (METHODOLOGY
  section 5; the post-run contamination audit flags it, but prevention is better).
- **Provider throttling** is recorded as infrastructure, not capability. After a run,
  `tools/exclude_infra_artifacts.py` (RUNBOOK) lets you exclude such attempts from
  scoring under human review.
