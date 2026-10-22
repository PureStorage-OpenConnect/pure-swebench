# zbench eval runbook

> Currency: CURRENT. Current-number policy: dynamic; use the dashboard or
> `tools/readout_snapshot.py` for current board numbers.

This file tells you how to operate an established zbench install. The tasks come from the
open-source Zulip codebase. `AGENTS.md` is the router to all documents.

First time here? Start with the guides:

- [`docs/replicate-zbench.md`](docs/replicate-zbench.md): fresh machine to scored board,
  step by step, and how to compare with [`results/`](results/).
- [`docs/running-your-models.md`](docs/running-your-models.md): installing harnesses and
  registering agents.
- [`docs/on-prem-gpu-sizing.md`](docs/on-prem-gpu-sizing.md): sizing GPUs (H200, B300)
  for the open-weight models.
- [`docs/bring-your-own-codebase.md`](docs/bring-your-own-codebase.md): mining tasks from
  your own repository.

## Environment

- Work from the root of this repo.
- The live harness code is in `zbench/`.
- All runtime state and evidence are under `bench-db/`. This holds `bench.db`, `blobs/`,
  and `.runtime/{live,slots,cells,runs}`. It is created on first use and is not tracked.
- The target repo is a FULL local clone of github.com/zulip/zulip at `ZBENCH_TARGET_REPO`
  (default `~/work/zulip`).
- Worktrees and `git show <sha>:<path>` need git blobs. Fetch `origin/main` before you mine.
- Docker runs all provisioning containers and all verify containers. The base image is
  `zulip/ci:noble`.
- Load credentials from your `.env` (see `.env.example`) into the shell:
  `set -a; . ./.env; set +a`.

To run the tests:

```bash
tools/run_tests.sh          # all tests; self-running, no pytest
tools/run_tests.sh static   # fast invariants only
```

Run `tools/run_tests.sh static` before you commit.

## Credentials

Check every credential that your agent selection needs before a batch. Do not assume that
it is still valid.

| used by | check |
|---|---|
| `claude-cli-*` agents, and the curation/judge LLM when you mine or review | `claude --print --model claude-fable-5 "reply OK"` |
| `pi-anthropic-*` agents | `ANTHROPIC_API_KEY` exported, or `pi` logged in once with `/login` |
| `codex-openai-*`, `pi-openai-*` agents | `OPENAI_API_KEY` exported |
| mining new tasks (`prepare_task.py`) | `gh auth status` (issue fetch) |
| gated model downloads for self-hosting | `HF_TOKEN` |

`tools/run_eval.sh --go` runs a preflight for the agents you selected and exits 66 without
launching if one is missing. There are no other credentials. Mining reads only the git log.
Grading containers run with `--network none`.

Note: running `pi` under subscription OAuth bills as extra usage for each token; an API
key avoids that ambiguity.

## Env images (docker)

Provisioned images are grouped by fingerprint and named `zbench-env:<fp12>`. The
fingerprint is the sha256 of the git blob-ids of `config.FP_FILES` at the base commit. See
`zbench-tasks/env_fingerprint.py`. Tasks whose base commits share a fingerprint share one
image. Each image is approximately 4.8 GB.

To build one image:

```bash
bash zbench-tasks/scripts/build_env_image.sh <base_commit> [--repo P] [--force]
```

This script is idempotent. It exits 0 immediately if the image exists. Grading never
builds an image on demand. If an image is missing, the cell records an infra failure.

To pre-build every image that a corpus subset needs, do this step on a fresh machine. For
the shipped corpus this makes 80 images, uses approximately 375 GB, and takes
approximately 16 hours when built serially.

```bash
python3 zbench-tasks/scripts/prebuild_env_images.py            # plan only
python3 zbench-tasks/scripts/prebuild_env_images.py --limit 5 --go
```

For the full bring-up of a fresh machine, see
[`docs/replicate-zbench.md`](docs/replicate-zbench.md) sections 3-5.

The build sequence below is order-sensitive. Do not make it simpler.

1. Do a real git checkout into `zulip/ci:noble` with a depth-1 fetch by sha. Do not use
   `git archive`. The provision script needs a real git repository.
2. Run provision pass 1 (`tools/ci/setup-backend --skip-dev-db-build`). This installs the
   services with apt. Pass 1 can stop at configure-rabbitmq. This failure is expected.
   Continue to step 3.
3. Start postgresql, rabbitmq-server, redis-server, and memcached. Services installed with
   apt do not start automatically in a container. Pass 2 then completes.
4. Run the warm gates: one backend test class (approximately 5 s) and one node test file
   (approximately 3 s). This step writes the test-DB template into the image. It also
   proves that the image works.
5. Prune the caches. Then run `docker commit` with the labels `zbench.base`, `zbench.fp`,
   and `zbench.created`.

To collect unused images:

```bash
bash zbench-tasks/scripts/gc_env_images.sh [--dry-run] [--keep-days N]
```

This script keeps every fingerprint that a validated or held task uses. It deletes the
other images after 30 days. It also removes exited `zbench_*` containers.

## Corpus ops

```bash
python3 zbench-tasks/mine_candidates.py [--since DATE] [--stats]    # reads the git log only
python3 zbench-tasks/prepare_task.py <fix_sha> [--no-oracle] [--fast-oracle]
python3 zbench-tasks/corpus.py                                      # current corpus state
```

- For the predicate and the pipeline, see `zbench-tasks/README.md`. To adapt them to a
  different repository, see
  [`docs/bring-your-own-codebase.md`](docs/bring-your-own-codebase.md).
- Use the `--stats` funnel as a baseline when you mine: a large difference from a previous
  run over the same window means that the predicate is broken. It does not mean that the
  repository changed.
- `prepare_task.py` exit codes:
  - 75 = infra failure. Retry. The script wrote nothing.
  - 70 = script error. The script wrote nothing.
  - 0 = the script wrote one atomic task record. Read its `curation_status`.
- `--fast-oracle` does one oracle run for each arm. Use it for development only. Never use
  it to promote a task into the corpus.
- To run the oracle alone:

  ```bash
  python3 zbench-tasks/oracle_validate.py --task-dir DIR [--fast] [--json]
  ```

  Exit codes: 0 = VALID, 1 or 2 = INVALID, 3 = UNENUMERABLE, 70 = script error, 75 =
  infra failure. The run logs are under `/tmp/zbench_runs/`.

## Filling the grid

Fill the grid when a task validates, when you add an agent, or when you exclude a scored
attempt. The friendly front end is `tools/run_eval.sh` (see
[`docs/replicate-zbench.md`](docs/replicate-zbench.md) section 6); the underlying commands
are:

```bash
python3 zbench-tasks/run_coverage_matrix.py --fill --agents $(readlink -f zbench-tasks/agents-matrix.jsonl)
python3 tools/wait_for_cells.py --corpus --agents zbench-tasks/agents-matrix.jsonl --all
python3 zbench-tasks/run_coverage_matrix.py --report --agents $(readlink -f zbench-tasks/agents-matrix.jsonl)
```

Rules:

- Always give `--agents` an absolute path. The `$(readlink -f ...)` form is the canonical
  one.
- `--fill` is board-wide. It runs every missing cell of a validated task and a ranked
  agent. The slot pools limit the concurrency.
- Do not fill one task at a time.
- Do not wait for a slow provider. A slow provider marks itself `leaderboard_partial` and
  completes its cells later.
- Overlapping fills are safe. Each cell has a flock admission gate. A second launcher stops
  and reports `skipped_inflight`.
- Start `--fill` again whenever it exits while cells are still missing.
- To run a subset, use `--only` or `--exclude` with agent globs. To select a language, use
  `--backend-only` or `--web-only`.

### Provider rate limits

Hosted providers throttle in different ways, and a throttle must never be scored as a
capability miss.

- Some gateways do not report a throttle with an HTTP error status. They return `200` and
  then stop the SSE stream in the middle of the turn. Codex then reports
  `stream disconnected before completion: ... exceeded rate limit.` and exits 1.
- The codex adapter therefore widens the codex reconnect budget with
  `CODEX_STREAM_MAX_RETRIES` (default 10), runs codex again up to `CODEX_MAX_ATTEMPTS`
  times (default 3) with exponential backoff, and records the result as status
  `provider_error`, which maps to `artifact:infra`.
- Quotas are often per model and per minute. Concurrency across DIFFERENT models is free;
  concurrency on the SAME model causes the throttle. Give each rate-limited model its own
  cap-1 slot pool (see "Concurrency & slots") rather than one shared pool.
- Codex resends the whole conversation on every turn, so on a low token-per-minute quota a
  single task can take a long time. Task time is then approximately the total tokens
  divided by the per-minute quota.
- The pi adapter has no retry of its own. If you front pi with a gateway that returns hard
  `429`s, put the retry in the gateway or add a pi-side retry.

If you serve through your own OpenAI-compatible gateway or proxy, point the agent row at it
with `CODEX_BASE_URL` / a pi provider `baseUrl` (see `docs/running-your-models.md`).

#### codex needs the Responses API

Codex 0.125.0 speaks the Responses API only. It removed `wire_api = "chat"`. A backend that
registers only chat completions cannot be reached by codex without a translating proxy.
Self-hosted vLLM 0.24.0 serves `/v1/responses` with streaming and tools and needs no flag.
Note that vLLM answers an unknown model name with 404 and the body `The model ... does not
exist`, which is easy to misread as a missing route.

## Post-run review (canonical order)

1. `run_coverage_matrix.py --report`. Confirm the missing cells and the infra-limited
   cells.
2. `python3 zbench-tasks/failure_modes.py --ranked-only`. Show the non-resolve buckets.
3. `python3 tools/exclude_infra_artifacts.py`. This writes scoring exclusions. Run it only
   when you intend to review. `tools/infra_sweep_watchdog.sh` can loop it for the
   high-confidence cases only: terminal 429, timeout, stall, and auth. It never touches
   `tests_failed`, `resolved`, or contamination.
4. `python3 zbench-tasks/validate_runs.py`. This is an evidence review that writes notes
   only. It runs the rule-based classifier, the contamination judge (GIT_SIGNAL and
   NET_SIGNAL prefilter, two-channel LLM judge), and the patch-similarity judge on every
   RESOLVED attempt. Judge notes never exclude an attempt automatically. A human sets
   `run_exclusion`.
5. `python3 tools/backfill_tokens.py --apply` and `python3 tools/backfill_turns.py --apply`.
   These reconcile each attempt's tokens and turn count from its durable session/rawcli
   transcript blob (the harness captures both live, but a batch may miss some). Both are
   idempotent and back up the DB first. Add `--recompute-all` to correct stale rows.
6. `python3 tools/consistency_check.py` and `python3 tools/dashboard_smoke.py`. These are
   the final guards. They check the repo, doc, and data invariants, including
   `check_no_legacy_names` and `check_selfhosted_price` (which flags any self-hosted
   open-weight model with no public reference price yet). They also render the dashboard.

To compare your board with the published run, see
[`docs/replicate-zbench.md`](docs/replicate-zbench.md) section 11 and
[`results/`](results/).

## Dashboard

```bash
python3 tools/bench_dashboard.py
# optionally keep it running as a user service of your own (systemd, tmux, ...)
```

The dashboard binds `127.0.0.1:8787` by default. It is read-only and has no
authentication. To view it from another machine, use an SSH tunnel:

```bash
ssh -L 8787:127.0.0.1:8787 <your-host>
```

Use `--host 0.0.0.0` only on a trusted network. The read-only SQL console
(`tools/query_console.py`, port 8789) follows the same rules.

## Reasoning effort

Every ranked row pins its effort level. An unset knob means the vendor default. That
default is unrecorded and changes between versions. See METHODOLOGY section 3.

Each harness has one knob:

| harness | env in the agent row | flag it becomes | levels |
|---|---|---|---|
| pi | `PI_THINKING` | `--thinking <l>` | off, minimal, low, medium, high, xhigh |
| claude | `CLAUDE_EFFORT` | `--effort <l>` | low, medium, high, xhigh, max |
| codex | `CODEX_REASONING_EFFORT` | `-c model_reasoning_effort="<l>"` | none, minimal, low, medium, high, xhigh |

The current pin is `high` everywhere. This is the highest level that all three harnesses
express. All three values are captured in `attempt_provenance`. An invalid codex level
raises an error when the command is built. It never falls back silently.

A pinned level is not the same as an effective level. `agents-meta.jsonl` carries
`effort_evidence` for each agent:

- `honored`: the reasoning tokens scale measurably.
- `accepted`: the backend takes the setting, but the effect is unmeasured.
- `inert`: the backend takes the setting, but there is no effect and no reasoning-token
  accounting.
- `not_delivered`: the harness never puts the setting on the wire.
- `unverified`: not checked.

To re-probe an API-served model, run two levels and compare the reasoning-token usage. The
parameter has two different shapes, one for each API:

| API | request field | usage field to read |
|---|---|---|
| Chat Completions | `reasoning_effort: "high"` (flat) | `usage.completion_tokens_details.reasoning_tokens` |
| Responses | `reasoning: {"effort": "high"}` (nested) | `usage.output_tokens_details.reasoning_tokens` |

Both shapes separate low from high on the models we tested, but they do not return the
same counts for the same model and effort (up to approximately 2x on samples of n=1, which
can be ordinary sampling variance). Do not mix the two shapes in one comparison. Chat
Completions returns a dated snapshot in `model`; Responses returns the bare alias. Do not
key anything off the returned model string. Responses calls can be much slower than Chat
Completions calls for equivalent requests.

### Warning: codex does not deliver the effort setting

All codex rows are `not_delivered`. Do not compare codex rows against pi rows or claude
rows as if the effort were equal.

`-c model_reasoning_effort=<l>` passes the codex config validator, and an invalid level is
rejected, so the key is real. However, every codex row uses the custom-model-provider
setup (`CODEX_BASE_URL` and `wire_api="responses"`), and the outgoing Responses request
then carries `reasoning: null`. This was verified by sniffing the wire at several levels
and model names; the value was always null. This is a harness gap: codex speaks the
Responses API and the shape it must send (`reasoning: {"effort": ...}`) works on the
backends we tested, but codex never fills the field. Whether the built-in (non-custom)
provider path of codex delivers the setting is not determined.

### Self-hosted rows

**Cost:** a self-hosted open-weight model is priced at a PUBLIC-HOST per-token reference,
not a hardware amortisation. Prices live in `tools/prices/models_dev.json` and
`tools/prices/open_weight_hosted.json`. A model with no public reference yet reads as
`free*` (`cost_known=False`). `tools/price_search.py` looks for a public reference (run it
from cron or by hand; it dry-runs unless you pass `--apply`), or pin a rate by hand in
`open_weight_hosted.json`. `consistency_check` lists the un-priced models.

Self-hosted rows are deliberately unpinned until their serving stack is verified. vLLM
honors only what the model and the chat template implement. Check this before you pin.
`PI_THINKING` does not reach a vLLM backend, so shipped self-hosted rows are
`not_delivered`.

On a local vLLM, a model's effort can be real while `usage...reasoning_tokens` stays
null: vLLM reports reasoning as `message.reasoning_content`. Use the length of the
reasoning content when you probe a self-hosted backend.

Warning: a model at a high effort can spend its whole completion budget on reasoning and
return an empty answer, with `finish_reason=length` and no content. On a task this gives an
empty patch, which scores as a non-resolve. That is a `[broken_config]` artifact, not a
capability result. Check that a self-hosted model still answers at the pinned level before
you rank it.

## Warning: codex sends a web_search tool (UNRESOLVED)

Contamination control assumes that the web tools of the harness are off. See METHODOLOGY
section 5. codex-cli 0.125.0 attaches a `web_search` tool to every `exec` request. It could
not be disabled. All of the following still leave the tool in the request:

- `tools.web_search=false`
- `tools.web_search_request=false`
- `features.web_search_request=false`
- `--disable browser_use --disable in_app_browser`

Evidence: a local vLLM rejects the call with `400 tool type web_search not supported`;
hosted gateways can accept the declaration.

One point is not yet proven: whether an accepted declaration means that a search really
runs. Until this is settled, treat codex rows as contamination-unverified.
`agents-meta.jsonl` states this, instead of claiming `web_tools: disabled`. Options: strip
`tools[].type == "web_search"` in a proxy in front of the model, pin a codex version that
still honors a disable switch, or use the post-run contamination audit
(`validate_runs.py`, NET_SIGNAL) to catch it afterwards.

## Concurrency & slots

Admission uses decentralized `flock` slot pools under `bench-db/.runtime/slots/`. The
kernel is the coordinator. A slot frees itself when its holder stops. A cell holds `global`
from start to end. It holds a phase slot only during that phase.

| phase | slot | default cap |
|---|---|---|
| whole cell | `global` | 20 |
| worktree setup | `setup` | 4 |
| LLM generation | `provider:<X>` | per backend (`DEFAULT_CAPS`) |
| verify, py | `verify:backend` | 3 (each container runs postgres/redis/rabbitmq) |
| verify, web | `verify:frontend` | 4 |

The caps are declarative data. The defaults are in `DEFAULT_CAPS` in
`zbench/cells/slots.py`. You can override them in `bench-db/.runtime/slots/caps.json`, or
with the env variable `ZBENCH_SLOT_CAP_<pool>`. Use `__` in place of `:`. For a
self-hosted endpoint, lower its provider cap if its server starts preempting requests
(see `docs/on-prem-gpu-sizing.md`).

To inspect the live slots:

```bash
python3 -m zbench.cells.slots status
```

The pool is derived from facts. Generation uses the provider of the agent. Verify uses the
language of the task. Never hardcode a pool for one cell.

## Job liveness (is a run alive?)

Use `python3 tools/job_status.py`. Never use a bare `pgrep -f`. `pgrep` and `ps | grep`
match a substring of the caller's own shell command line. They therefore report "alive"
for a job that finished long ago.

`job_status.py` decides ALIVE, DONE, or STALE from real evidence (Linux only; it reads
`/proc`):

1. Real python processes read from `/proc/<pid>/cmdline`. These are
   `run_coverage_matrix`, `zbench.cells.run_cell`, prep, and oracle.
2. The freshness of the live-lease heartbeat under `bench-db/.runtime/live/<run>/`.
3. The last `attempt.finished_at` in `bench.db`.
4. The age of the last write to a `--fill` log, with `--log`.

It exits 0 only if something is alive.

### Warning: do not stop a cell that makes progress

The agent writes its turns to `session.jsonl` in the cell directory. It does not write them
to the celllog. The celllog is quiet during generation.

A slow backend can run for hours and still make progress. That state is `transcript
PROGRESSING`. If you stop the cell, you destroy real work. You also make the score of that
agent incorrect.

Investigate only when the transcript is idle for much longer than its write cadence. That
state is `transcript SILENT`, and the default limit is 30 minutes. Confirm the state before
you stop the cell. Judge liveness with `job_status.py`. Do not judge it by a quiet celllog
or by `pgrep`.

## Disk / docker hygiene

```bash
df -h ~
docker system df
bash zbench-tasks/scripts/gc_env_images.sh --dry-run
```

Env images use the most disk space, at approximately 4.8 GB for each fingerprint. Reclaim
the space with `gc_env_images.sh`. It respects the references from validated tasks and held
tasks.

Do not use `docker image prune -af`. That command deletes referenced env images and
`zulip/ci:noble`, and you must then build them again.

Keep `bench-db/blobs`. Evidence blobs are never a cleanup target.
