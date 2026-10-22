# Replicating zbench end to end

This is the copy-pasteable path from a fresh machine to a scored leaderboard on the
shipped zbench tasks, using your own API keys and (optionally) your own GPUs, and then
comparing against the numbers in [`../results/`](../results/).

zbench is built by Everpure, Inc. (formerly Pure Storage). The tasks are mined from the
open-source [Zulip](https://github.com/zulip/zulip) repository.

Companion docs: [`running-your-models.md`](running-your-models.md) (harness and model
reference), [`on-prem-gpu-sizing.md`](on-prem-gpu-sizing.md) (self-hosting),
[`../RUNBOOK.md`](../RUNBOOK.md) (day-2 operations), [`../METHODOLOGY.md`](../METHODOLOGY.md)
(why the numbers mean what they mean).

Every command below was checked against the scripts in this repository (flag names, file
paths). Where a step depends on a third-party tool whose behavior we cannot guarantee
(npm packages, vendor CLIs, GPU drivers), it is marked **[not verified here]**.

---

## 0. What you are signing up for

- **Time.** Building the grading images is the long pole: the shipped corpus needs about
  80 distinct images, roughly 12 minutes each when built serially (about 16 hours total).
  You can start with a handful (section 5) and widen later. Model runs then take
  minutes per task per agent, many in parallel.
- **Disk.** About 4.7 GB per grading image, about 375 GB for all 80, plus the Zulip clone
  and run evidence. Plan for **at least 500 GB free**.
- **Money.** Agent runs on frontier models cost real dollars: `results/per_model_summary.csv`
  has per-task cost columns for every agent, so look at them before you launch a full
  grid, and begin with `--smoke` (1 task) and `--tasks 5`.
- **Nondeterminism.** An agent run is one sample from a stochastic system. Do not expect to
  reproduce a resolve rate to the digit (section 11 explains how to judge a comparison).

## 1. Prerequisites

| need | detail |
|---|---|
| OS | Linux x86-64 recommended (the grading images are x86-64 Linux containers; `tools/job_status.py` reads `/proc`). macOS is possible for the host scripts but not what we ran: `zbench_verify.sh` needs GNU `timeout` (`brew install coreutils`), and x86-64 images on Apple Silicon run under emulation **[not verified here]**. |
| Docker | A recent Docker Engine; the daemon must be reachable by your user (`docker info`). Grading and image builds run entirely in containers. |
| Python | 3.10 or newer for the harness and tools (the code uses `X | None` annotations); 3.12 for the vLLM serving venv (`setup_venv.sh` default). The harness itself uses only the standard library; it has no `requirements.txt` to install. |
| git | A full (non-shallow) clone of the target repo, section 3. |
| Node 20+ | Only for the `claude`, `codex` and `pi` CLIs. |
| coreutils / lsof | `timeout` (used by `zbench_verify.sh`), `lsof` (used by `serve_local.sh stop`). |
| `gh` (GitHub CLI) | Only if you **mine new tasks** (it fetches issue text). Not needed to run the shipped tasks. |
| GPUs | Only if you self-host open-weight models. NVIDIA driver plus the NVIDIA Container Toolkit (for the Docker-served model) plus `uv` for the vLLM venv. See [`on-prem-gpu-sizing.md`](on-prem-gpu-sizing.md). |
| Credentials | `ANTHROPIC_API_KEY` for the Claude agents, `OPENAI_API_KEY` for the GPT agents, an optional `HF_TOKEN` for gated model downloads. Nothing else; mining a corpus additionally needs the curation LLM (section 12). |

## 2. Get zbench and configure the environment

```bash
git clone <this-repository-url> zbench
cd zbench
cp .env.example .env
$EDITOR .env                  # set only what the agents you will run need
set -a; . ./.env; set +a      # load it into THIS shell (the harness does not read .env itself)
tools/run_tests.sh static     # fast repo / schema / doc invariants; should pass
```

Re-run `set -a; . ./.env; set +a` in every new shell. The launchers inherit your
environment, and each run cell passes it on to the agent; no key is ever written into an
agent row or into the repository.

## 3. Clone the target repo at the range the tasks need

The tasks reference base commits from **2025-01-02 through 2026-08-10** (the dates of
the fix commits). Each grading worktree is a depth-1 fetch of a task's base commit from
your local clone, so the clone must contain all of them. A **full clone** is the simple
way and is required (a `--depth` clone will not resolve most of them):

```bash
git clone https://github.com/zulip/zulip.git "$HOME/work/zulip"
export ZBENCH_TARGET_REPO="$HOME/work/zulip"          # also put this in .env
git -C "$ZBENCH_TARGET_REPO" fetch origin main
```

Verify that every validated task's base commit is present (prints nothing and exits 0 if
all are):

```bash
python3 - <<'PY'
import glob, json, os, subprocess, sys
repo = os.path.expanduser(os.environ["ZBENCH_TARGET_REPO"])
bad = []
for p in sorted(glob.glob("zbench-tasks/tasks/ZT-*/meta.json")):
    m = json.load(open(p))
    if m.get("curation_status") != "validated":
        continue
    if subprocess.run(["git", "-C", repo, "cat-file", "-e", m["base_commit"] + "^{commit}"],
                      capture_output=True).returncode:
        bad.append((m["task_id"], m["base_commit"]))
print(f"{len(bad)} missing base commits", *bad[:10], sep="\n  ")
sys.exit(1 if bad else 0)
PY
```

If a task's commit is missing, `git -C "$ZBENCH_TARGET_REPO" fetch origin` and retry. If
the upstream history has been rewritten or the commit is otherwise unreachable, that task
cannot be replicated; report it rather than dropping it silently.

## 4. Confirm the corpus

```bash
python3 zbench-tasks/corpus.py | head -5       # validated corpus size and py/web split
tools/run_eval.sh --list                       # runnable agents + validated task count
```

The corpus ships in the repository (`zbench-tasks/tasks/ZT-*/`). The answer keys live
separately in `zbench-tasks/solutions/` and are used only by the oracle, never shown to an
agent.

## 5. Base image and grading images (the long step)

```bash
docker pull zulip/ci:noble                      # the base every grading image is built from
python3 zbench-tasks/scripts/prebuild_env_images.py              # PLAN only: images needed, disk, time
python3 zbench-tasks/scripts/prebuild_env_images.py --limit 5 --go    # enough for a smoke test
```

Later, build the rest (resumable; images that exist are skipped):

```bash
python3 zbench-tasks/scripts/prebuild_env_images.py --go
# or by slice:
python3 zbench-tasks/scripts/prebuild_env_images.py --backend-only --go
python3 zbench-tasks/scripts/prebuild_env_images.py --task-ids 'ZT-13*' --go
```

Grading never builds an image on demand. A missing image makes the cell an infrastructure
failure, not a score. Images are named `zbench-env:<fingerprint>`; many tasks share one.
Never run `docker image prune -af` (it deletes them). Reclaim space safely with
`bash zbench-tasks/scripts/gc_env_images.sh --dry-run`.

### 5.1 Prove your grading environment reproduces the oracle

Before spending money on models, check that one task flips the way the shipped records say:
the hidden test must **fail** on the base commit and **pass** with the real fix.

```bash
python3 zbench-tasks/oracle_validate.py --task-dir zbench-tasks/tasks/ZT-472ca78bc26f --fast
echo "exit=$?"        # 0 = VALID
```

`--fast` runs one run per arm (development use); omit it for the full, flake-gated check
(about 2 minutes to several, per task). Exit codes: 0 valid, 1/2 invalid, 3
unenumerable, 70 script error, 75 infrastructure failure (retry). An infrastructure
failure here usually means the grading image for that task is not built yet.

## 6. Run each harness

`tools/run_eval.sh` is the front end. **Without `--go` it only prints the plan.** The
cohort is the 21 rows of `zbench-tasks/agents-matrix.jsonl`; `--list` shows them.

```bash
tools/run_eval.sh --smoke --model claude-opus-5 --harness claude-cli          # plan: 1 task, 1 agent
tools/run_eval.sh --smoke --model claude-opus-5 --harness claude-cli --go     # run it
```

`--go` runs a preflight first (Docker reachable, target clone present, the CLI and
credential each selected agent needs) and exits 66 without launching if one is missing.
Install each harness first (see [`running-your-models.md`](running-your-models.md)
section 2: `claude`, `codex`, `pi`; **[not verified here]**, as these are third-party
npm packages whose flags change between releases).

| Harness | Agents | Credential | Command (add `--go` to launch) |
|---|---|---|---|
| `claude` CLI | `claude-cli-*` (Claude family) | `claude login` or `ANTHROPIC_API_KEY` | `tools/run_eval.sh --harness claude-cli` |
| `codex` | `codex-openai-*` (GPT-5.6 family) | `OPENAI_API_KEY` | `tools/run_eval.sh --harness codex` |
| `pi`, hosted | `pi-anthropic-*`, `pi-openai-*` | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | `tools/run_eval.sh --agent 'pi-anthropic-*,pi-openai-*'` |
| `pi`, self-hosted | `pi-vllm-*` (five open-weight models) | none (your endpoint) | section 7 |

Useful selectors (all read from the argument parser in `tools/run_eval.sh`): `--model <glob,...>`,
`--harness claude-cli|pi|codex`, `--agent <agent_id globs>`, `--tasks N` (first N
tasks), `--task-ids 'ZT-13*'`, `--backend-only` / `--web-only`, `--tries K` (attempts per
cell), `--fanout N` (max parallel cells, default 6), `--run-id NAME`, `--report`.

A typical widening sequence for one harness:

```bash
tools/run_eval.sh --smoke --harness claude-cli --model claude-haiku-4-5 --go   # cheapest model, 1 task
tools/run_eval.sh --tasks 5 --harness claude-cli --model claude-haiku-4-5 --go
tools/run_eval.sh --harness claude-cli --go                                    # full corpus, all Claude agents
```

The launcher self-throttles with per-pool concurrency caps (RUNBOOK "Concurrency &
slots") and skips cells already recorded in `bench.db`, so re-running the same command
resumes an interrupted fill.

## 7. Self-hosted open-weight models on your GPUs

Read [`on-prem-gpu-sizing.md`](on-prem-gpu-sizing.md) first to size your node. Then:

```bash
export ZBENCH_SERVING_ROOT=/path/to/bulk/storage       # ~300 GB for venvs + weights
bash tools/serving/setup_venv.sh                       # vLLM venv (needs `uv` on PATH)
bash tools/serving/setup_venv.sh --verify              # confirms vllm, torch, ninja, CUDA
$EDITOR tools/serving/models.conf                      # set gpus / port / tp for YOUR hardware
bash tools/serving/serve_local.sh start qwen3.6-27b    # one alias at a time
bash tools/serving/serve_local.sh status               # wait for READY
bash tools/serving/serve_local.sh check qwen3.6-27b    # must print TOOL CALL OK
```

Add the matching pi provider block (`running-your-models.md` section 4.3), then:

```bash
tools/run_eval.sh --smoke --agent 'pi-vllm-qwen3.6-27b' --go
tools/run_eval.sh --agent 'pi-vllm-qwen3.6-27b' --go
bash tools/serving/serve_local.sh stop qwen3.6-27b
```

Repeat for `gpt-oss-120b`, `nemotron-3.5-lightning-30b`, `gemma-4-31b` and
`muse-glimmer-30b` (the last two need the special builds described in
`tools/serving/README.md`). Serve one model at a time unless your GPUs have room to
co-host (see the sizing guide, section 5).

## 8. Where results go (the "ingest" step)

There is no separate import. Every attempt is written to the SQLite store
`bench-db/bench.db` (created on first use from `zbench/schema.sql`) by the harness as it
runs, with its evidence (brief, transcript, patch, test log) under `bench-db/blobs/`.
(`zbench/ingest.py` is the *input* validator for agent and task files, not a results
importer.) Attempts are immutable facts; exclusions and notes are layered on top.

Watch a fill:

```bash
python3 tools/job_status.py                                  # ALIVE / DONE / STALE from real evidence
python3 tools/wait_for_cells.py --corpus --agents zbench-tasks/agents-matrix.jsonl --all
python3 zbench-tasks/run_coverage_matrix.py --report --agents "$(readlink -f zbench-tasks/agents-matrix.jsonl)"
```

Do not stop a cell just because its log is quiet; the agent writes progress to its
session transcript (RUNBOOK "Job liveness").

## 9. Post-run review (before you trust a number)

Run the canonical review cycle in RUNBOOK "Post-run review":

```bash
python3 zbench-tasks/failure_modes.py --ranked-only      # non-resolve buckets
python3 tools/exclude_infra_artifacts.py                 # WRITES scoring exclusions for infra failures; run only when you intend to review them
python3 zbench-tasks/validate_runs.py                    # contamination + patch-similarity evidence (notes only)
python3 tools/backfill_tokens.py --apply
python3 tools/backfill_turns.py --apply
python3 tools/consistency_check.py && python3 tools/dashboard_smoke.py
```

`exclude_infra_artifacts.py` and the backfills write to `bench.db` (the backfills back it
up first); run them deliberately.

## 10. Produce the board

```bash
python3 tools/bench_dashboard.py            # leaderboard + drill-down at http://127.0.0.1:8787/
python3 tools/query_console.py              # read-only SQL console at http://127.0.0.1:8789/
python3 tools/readout_snapshot.py > my-results.md    # Markdown snapshot of the board
```

The dashboard has no authentication and binds `127.0.0.1`; use an SSH tunnel to view it
from another machine. In the query console, `v_board` **is** the ranked board (the same
numbers as the dashboard), so for ad-hoc analysis start from it.

## 11. Compare against `results/`

[`../results/`](../results/) holds our run: `per_model_summary.csv` (one row per agent,
including `resolve_rate`, `common_set_resolve_rate`, cost and token columns),
`per_task_results.csv` (one row per agent x task, with `resolved`), and
`sample_transcripts/`. See [`../results/README.md`](../results/README.md) for column
definitions.

Pull your board from the console's JSON API and diff it:

```bash
python3 tools/query_console.py & QC=$!      # leaves it on :8789
sleep 3
python3 - <<'PY'
import csv, json, math, urllib.request
sql = "SELECT agent_id, resolve_rate, n FROM v_board"
req = urllib.request.Request("http://127.0.0.1:8789/api/query",
        data=json.dumps({"sql": sql}).encode(), headers={"Content-Type": "application/json"})
res = json.load(urllib.request.urlopen(req))
mine = {r[0]: (float(r[1]), int(r[2])) for r in res["rows"] if r[1] is not None}
ref = {r["agent_id"]: float(r["common_set_resolve_rate"] or 0)
       for r in csv.DictReader(open("results/per_model_summary.csv"))}
print(f"{'agent':40s} {'mine':>6s} {'ours':>6s} {'diff':>7s}  within 2 SE?")
for a in sorted(mine):
    if a not in ref: continue
    p, n = mine[a]; q = ref[a]
    se = math.sqrt(max(p*(1-p), 0.01) / n + max(q*(1-q), 0.01) / n)   # two independent proportions
    print(f"{a:40s} {p:6.3f} {q:6.3f} {p-q:+7.3f}  {'yes' if abs(p-q) <= 2*se else 'NO'}")
PY
kill $QC
```

How to read the comparison:

- **Compare like with like.** Our `common_set_resolve_rate` is over the tasks all
  fully-covered agents share; yours is over *your* common set. If you ran fewer agents or
  tasks, the sets differ. For a strict comparison use `per_task_results.csv` and restrict
  both sides to the same task ids.
- **Expect noise.** With about 100 tasks and one attempt per cell, the standard error on a
  resolve rate is about 5 percentage points near 50%. Differences inside roughly 2 SE
  (10 points) are not evidence of a problem; **ranking order among close agents will
  shuffle.** Use `--tries 3` if you want to average out sampling noise.
- **Things that legitimately move numbers:** model snapshots changing behind an alias,
  vendor-side throttling (recorded as infrastructure, not capability), different
  engine/quantization on self-hosted rows, different harness versions (codex and pi change
  flags often), and the unpinned reasoning effort on self-hosted rows.
- **A large, systematic gap** (for example every agent near zero) is almost always an
  environment problem: missing grading images, a clone missing base commits, or an
  unreachable endpoint. Check section 5.1 and the failure buckets from
  `failure_modes.py` before suspecting the models.

## 12. What you do not need for replication

Mining and curating **new** tasks needs the curation LLM (`ZBENCH_LLM`, pinned to a Claude
model via the `claude` CLI) and `gh`. Running the shipped tasks needs neither. To build a
corpus from your own repository, see [`bring-your-own-codebase.md`](bring-your-own-codebase.md).
