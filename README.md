# zbench

**zbench turns a codebase's own commit history into a coding-agent benchmark.** It mines
real, merged bugfix commits from a project's git log, strips each one down to a test-blind
coding task (problem statement plus a hidden regression test), and scores any combination
of model x harness x provider by whether its patch makes the hidden test pass: the same
test the original human fix had to pass. Grading is by test exit code, never by an LLM
judge.

Built by Everpure, Inc. (formerly Pure Storage).

This repository is a working demonstration on the open-source
[Zulip](https://github.com/zulip/zulip) codebase: 120 validated tasks and a scored
leaderboard harness covering Claude, GPT and open-weight models across three agent harnesses.
It is also deliberately **a template**: every repo-specific piece (the mining predicate,
the Docker provisioning recipe, the test-runner shell-out) is isolated in a few files, so
the same pipeline can be pointed at a different codebase, including a private one. That
is the point: public benchmarks leak into training data, so the most durable way to
evaluate coding agents on work that looks like *your* work is to build the eval from your
own repository's fix history.

## What is in the repo

| Path | What it is |
|---|---|
| [`zbench-tasks/`](zbench-tasks/) | Mining and curation pipeline, plus the task corpus (`tasks/ZT-<sha12>/`), answer keys (`solutions/`), and the agent roster (`agents-*.jsonl`) |
| [`zbench/`](zbench/) | The harness: runs one agent against one task, grades it in Docker, records the result |
| [`tools/`](tools/) | `run_eval.sh` (the CLI entry point), dashboard, query console, review utilities, local-model serving scripts (`tools/serving/`), price tables (`tools/prices/`) |
| [`results/`](results/) | Our published run: per-model and per-task CSVs and sample transcripts |
| [`docs/`](docs/) | The guides below, the best-practices cross-check, an architecture diagram |
| `bench-db/` | Runtime only: `bench.db` (scores) and evidence blobs. Created on first run; not tracked. |
| [`METHODOLOGY.md`](METHODOLOGY.md) | The design contract: oracle invariant, contamination model, ranking rules |
| [`RUNBOOK.md`](RUNBOOK.md) | Day-to-day operations |
| [`GLOSSARY.md`](GLOSSARY.md), [`AGENTS.md`](AGENTS.md) | Plain-language terms; router to every document |

## Guides

| I want to... | Read |
|---|---|
| Reproduce the published numbers end to end | [`docs/replicate-zbench.md`](docs/replicate-zbench.md) |
| Install a harness, add a model, wire up a self-hosted endpoint | [`docs/running-your-models.md`](docs/running-your-models.md) |
| Size GPUs (H200 / B300) for the open-weight models | [`docs/on-prem-gpu-sizing.md`](docs/on-prem-gpu-sizing.md) |
| Build a benchmark from my own repository | [`docs/bring-your-own-codebase.md`](docs/bring-your-own-codebase.md) |
| Operate an established install | [`RUNBOOK.md`](RUNBOOK.md) |
| Understand the design principles | [`docs/benchmark-best-practices.md`](docs/benchmark-best-practices.md), [`METHODOLOGY.md`](METHODOLOGY.md) |

## How a task is built

```
real commit  -->  split into (test, fix)  -->  problem statement from the linked issue
                                                        |
                          hidden regression test <------+
                                   |
                   agent sees: problem statement + checkout at the commit BEFORE the fix
                   agent does NOT see: the fix, the test, the commit message, git history
                                   |
                          agent produces a patch
                                   |
        apply patch -> strip any agent edits to test files/runners -> run the hidden test
                                   |
                          exit 0 = resolved, else not
```

Each task starts as a single commit that closes a tracked issue (`Fixes #N`), ships a code
change **and** a test change together, and is small and single-purpose enough to state as a
spec. The commit is split into `gold_code` (the fix, the answer key) and `gold_test` (the
hidden verifier). The problem statement comes **only** from the linked issue, never the
commit message. An **oracle** proves the task is fair before it is scored: the hidden test
must fail at the base commit and pass with the real fix, each outcome repeated to rule out
flakiness. A task that does not flip is rejected, not fixed up.

Grading runs in a network-isolated Docker container. The agent's edits to test files are
reverted before the hidden test runs, and the working checkout is history-sealed (a fresh
`git init` containing only the base commit). Full contract: [`METHODOLOGY.md`](METHODOLOGY.md).

## Quickstart

The task corpus ships in this repo. You supply a Zulip clone and build the Docker images
tasks are graded in (large and machine-specific, so not shipped). Requirements: Linux
x86-64 (recommended), Docker, Python 3.10+, git, about 500 GB free disk for the full grid.

```bash
cp .env.example .env && $EDITOR .env && set -a; . ./.env; set +a   # your API keys

git clone https://github.com/zulip/zulip.git ~/work/zulip           # FULL clone, not shallow
export ZBENCH_TARGET_REPO=~/work/zulip
docker pull zulip/ci:noble

tools/run_tests.sh static                                           # sanity-check the repo
python3 zbench-tasks/corpus.py | head -5                            # the shipped corpus
python3 zbench-tasks/scripts/prebuild_env_images.py                 # PLAN: disk and time needed
python3 zbench-tasks/scripts/prebuild_env_images.py --limit 5 --go  # build enough for a smoke test

tools/run_eval.sh --list                                            # runnable agents
tools/run_eval.sh --smoke --model claude-opus-5 --harness claude-cli --go   # one real task
python3 tools/bench_dashboard.py                                    # board at http://127.0.0.1:8787/
```

Without `--go`, `tools/run_eval.sh` only prints its plan.

## Replicate our numbers

**Headline results:** [`results/LEADERBOARD.md`](results/LEADERBOARD.md): model, harness, and tasks resolved out of the 107-task shared set.

Our results export (per agent: resolve rate, cost, tokens, turns, wall-clock) is in
[`results/`](results/) (see its README for which agents it currently covers): `per_model_summary.csv`, `per_task_results.csv` (one row per agent
x task), and `sample_transcripts/`. To reproduce it with your own API keys and GPUs:

1. Follow [`docs/replicate-zbench.md`](docs/replicate-zbench.md): prerequisites, the Zulip
   clone and base-commit check, `.env`, building the grading images, an oracle sanity
   check, running each harness (`claude`, `codex`, `pi`), and optionally the five
   open-weight models on your GPUs ([`docs/on-prem-gpu-sizing.md`](docs/on-prem-gpu-sizing.md)).
2. Produce your board (`tools/bench_dashboard.py`, `tools/query_console.py`,
   `tools/readout_snapshot.py`).
3. Diff it against `results/per_model_summary.csv` with the script in section 11 of the
   guide. One attempt per task has a standard error of around 5 percentage points at
   100 tasks, so expect agreement within noise, not to the digit.

Agent runs on frontier models cost real money. Check the cost columns in `results/` and
start with `--smoke` and `--tasks 5`.

## Use as a template for your codebase

Nothing in the harness (`zbench/`), the scoring model, or the dashboards is
Zulip-specific. The coupling is in `zbench-tasks/`:

| Concern | Where |
|---|---|
| Which commits are candidate tasks | `zbench-tasks/config.py` (`FIXES_RE`, `classify_file`, ...) |
| What defines the grading environment | `zbench-tasks/config.py` (`FP_FILES`) |
| How to provision an environment at a historical commit | `zbench-tasks/scripts/build_env_image.sh` |
| How to run a hidden test (exit 0 = pass) | `zbench-tasks/scripts/zbench_verify.sh`, `inner_verify.sh` |
| What the agent may not edit | `zbench/workflow.py` (`_TEST_PATHSPECS`, `_RUNNER_INTEGRITY_PATHS`) |
| LLM screen prompts, size caps | `zbench-tasks/prepare_task.py`, `zbench-tasks/quality.py` |

The recommended order: get the environment recipe working first (it is usually the
slowest part), check the mining funnel with `mine_candidates.py --stats`, prepare ten tasks
and read every one, then batch up to about 100 validated tasks. The full walkthrough,
including the flakiness gate, the three-way coupling screen, contamination tiers and
curation statuses, is [`docs/bring-your-own-codebase.md`](docs/bring-your-own-codebase.md).

If your repo is private, no vendor's training data contains your fixes, so the
contamination gate that matters for a public repo is close to moot. That is a genuine
advantage over any public benchmark.

### Best practices, in brief

- Grade with the real test, never an LLM judge. (LLMs are fine for *curation*, not for
  deciding whether an attempt is correct.)
- Derive the problem statement from the issue, never the commit message or diff; strip fix
  SHAs, issue numbers and repo URLs deterministically.
- Seal the working copy's history, keep the hidden test hidden, and hash-check the runner.
- Validate every task before it counts (fail before, pass after, repeated); reject rather
  than hand-patch.
- Add human review on top of the mechanical gate.
- Treat model x harness x provider as one identity; pin reasoning effort for every agent;
  report cost per task and keep cost, latency and capability as separate axes.
- Be honest about what is not isolated: most CLI agents call a model API, so generation has
  network access even though grading does not.

Sourcing and detail: [`docs/benchmark-best-practices.md`](docs/benchmark-best-practices.md).

## License

zbench is licensed under the [Apache License 2.0](LICENSE).

The task corpus (`zbench-tasks/tasks/`, `zbench-tasks/solutions/`) is not original content:
each task's `gold_test.patch` and `gold_code.patch` are literal excerpts of real Zulip
source, and each `problem_statement.md` is derived from a real Zulip GitHub issue. That
content is Zulip's, redistributed under Zulip's own Apache-2.0 license. See
[`NOTICE`](NOTICE).

If you use this as a template against **your own codebase**, your generated corpus is
derived from *your* source, under *your* terms. Do not publish a corpus generated from a
private repo unless you intend those fixes to become public; if you publish one derived
from another open-source project, replace the `NOTICE` attribution; and before pushing a
fork, search it for environment-specific strings that accumulated while you wired things
up (internal hostnames, gateway URLs, credential-shaped strings).
