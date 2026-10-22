# Using zbench as a template for your own codebase

Goal: turn **your repository's** fix history into a private benchmark of about 100
verifiable tasks, then score agents on it with the same harness. A private repo has a
real advantage: no model vendor trained on your fixes, so the contamination problem that
a public repo like Zulip has largely goes away.

Do the Zulip replication first ([`replicate-zbench.md`](replicate-zbench.md)). You will
need a working harness, Docker, and a feel for what a validated task looks like
(`zbench-tasks/tasks/ZT-472ca78bc26f/` is a full example) before adapting anything.

Standing design decisions (METHODOLOGY.md, CLAUDE.md): **verifiability is the sole
inclusion bar**; task type (bug / feature / refactor) and difficulty are not gates;
contamination tiers are advisory; target roughly **100 validated tasks**.

## 1. What is generic and what is Zulip-specific

The harness (`zbench/`), the scoring model, the slot/concurrency machinery, the
immutable-attempt store and the dashboards do not know what Zulip is. The Zulip coupling
is concentrated in a short list of places, below. Everything not listed should work
unchanged.

| Concern | File | What to change |
|---|---|---|
| Target repo, main ref, GitHub slug | `zbench-tasks/config.py` (`ZULIP_REPO` = `ZBENCH_TARGET_REPO`, `MAIN_REF`, `GITHUB_REPO`) | Set `ZBENCH_TARGET_REPO` to your clone; edit `MAIN_REF` (for example `origin/master`) and `GITHUB_REPO` (`org/repo`, used by `gh api` to fetch issues). |
| Which commits are candidates | `config.py` (`FIXES_RE`, `FIXES_PARTIAL_RE`) | Match your convention for "this commit closes issue N". If you track work in Jira or another tracker rather than GitHub issues, you must also replace the issue fetch in `prepare_task.py` (see section 5). |
| Which files are code vs tests, which language | `config.py` (`PY_APPS`, `classify_file`, `classify_support`, `_TEST_SUPPORT_RE`) | Rewrite `classify_file` to return `<lang>_test` / `<lang>_code` for your layout. The miner requires at least one test file and one code file in the same commit and a single language per task. |
| What counts as a dependency/environment change | `config.py` (`FP_FILES`, `is_dep_file`) | List the files whose contents define your build environment (lockfiles, toolchain pins, provisioning scripts). A fix that touches these is rejected (`dep_change`); their blob ids also form the image fingerprint. |
| Base image and provisioning | `config.py` (`CI_IMAGE` / `ZBENCH_CI_IMAGE`), `scripts/build_env_image.sh` | Replace the Zulip provisioning recipe with the steps that give you a clean, working test environment at an arbitrary historical commit. |
| How a test is run in the container | `scripts/inner_verify.sh`, `scripts/zbench_verify.sh` | Replace `tools/test-backend` / `tools/test-js-with-node` with your runners. Contract: exit 0 = pass, non-zero = fail. `zbench_verify.sh` also checks the cwd looks like the repo (`tools/test-backend` present); change that sanity check. |
| What an agent may not edit | `zbench/workflow.py` (`_TEST_PATHSPECS`, `_RUNNER_INTEGRITY_PATHS`) | List your test directories, test-support files and runners. This is a security boundary: edits to these paths are reverted before grading, and any residue under the runner paths aborts the attempt. |
| Test-target extraction | `prepare_task.py` (prompts `P_F2P`, and the `zerver/tests/test_*.py` pass-to-pass heuristic) and `oracle_validate.py` / `verdict.py` | Teach it your test IDs and your runner's output so it can tell "ran and failed" from "could not run". |
| LLM screen prompts | `prepare_task.py` (suitability, coupling, problem-statement rewrite) | Same shape; tune the wording and examples to your domain. |
| Size caps | `quality.py` (`MAX_CODE_FILES = 15`, `MAX_ADDED_CODE_LINES = 600`) | Adjust if your commits are naturally larger or smaller. |
| Excluded authors / AI trailers | `quality.py` (`excluded_author`, `has_ai_trailer`) | Add your bots and service accounts. |
| Model roster | `agents-*.jsonl` | Your own agent selection. |

Search for the strings `zulip`, `zerver`, `test-backend`, `/srv/zulip` across
`zbench-tasks/` and `zbench/workflow.py` when you are done; anything left is something you
missed.

## 2. Pointing the miner at your repo

```bash
git clone <your-repo-url> "$HOME/work/myrepo"                # FULL clone, not --depth
export ZBENCH_TARGET_REPO="$HOME/work/myrepo"
git -C "$ZBENCH_TARGET_REPO" fetch origin
export ZBENCH_MIN_COMMIT_DATE=2023-01-01                     # mining floor, see below
python3 zbench-tasks/mine_candidates.py --stats               # funnel only; no LLM, no writes
```

`mine_candidates.py` is a pure `git log` read. `--stats` prints the rejection funnel to
stderr (`commits`, `excluded_author`, `ai_generated`, `no_fixes_ref`, `partial_fix`,
`touches_migrations`, `dep_change`, `no_test_or_no_code`, `mixed_lang`, `candidate_*`).
**Read the funnel before anything else.** If `no_fixes_ref` swallows nearly everything,
your `FIXES_RE` does not match your commit convention; if candidates are suspiciously
many or few relative to what you know about the repo, the predicate is wrong, not the
repo. Options: `--since DATE`, `--until DATE`, and a positional repo path.

**Date window.** `ZBENCH_MIN_COMMIT_DATE` (default `2025-01-01`) is only an
infrastructure bound: old commits must still provision in your base image. Start with a
recent window (the last 6-12 months) where building the environment is easiest, then
reach back as your image recipe proves out. The migration and dependency rules in the miner
(`touches_migrations`, `is_dep_file`) are Django/npm-flavoured; revisit them for your stack.

## 3. Build the environment recipe first

This is usually the most time-consuming part, so do it **before** mining hundreds of
candidates:

1. Pick a base image close to your CI image.
2. Adapt `scripts/build_env_image.sh` until
   `bash zbench-tasks/scripts/build_env_image.sh <base_commit>` yields an image
   `zbench-env:<fingerprint>` in which your test runner works offline (`--network none`
   is how grading runs it). The script ends with "warm gates" that run one real test; keep
   an equivalent so a broken image fails at build time, not mid-grid.
3. Adapt `inner_verify.sh` / `zbench_verify.sh` to run specific test targets and return
   the runner's exit code.
4. Adapt `env_fingerprint.py` input (`FP_FILES`) so tasks whose base commits share an
   environment share one image. Without this you build one image per task.

Check on three old and three recent commits, with the real fix applied and not, that your
tests behave (pass with, fail without). Old commits have build quirks a fresh CI image
does not anticipate.

## 4. Prepare tasks and let the oracle judge them

```bash
python3 zbench-tasks/prepare_task.py <fix_sha> --fast-oracle     # first task: iterate quickly
python3 zbench-tasks/prepare_task.py <fix_sha>                   # real run (full flake-gated oracle)
python3 zbench-tasks/batch_prepare.py --since 2025-06-01 --until 2025-09-01 --limit 20
python3 zbench-tasks/corpus.py --status '*'                      # every judged candidate
```

`prepare_task.py` runs cheap deterministic gates first, the LLM screens next, and the heavy
oracle last: dedup and predicate re-check; scope gate; patch split into `gold_code`
(answer key, stored under `solutions/`) and `gold_test` (hidden verifier); deterministic
unsuitability filters; issue fetch (`gh api`, title and body only, never comments, which
leak); suitability and coupling screens; fail-to-pass and pass-to-pass extraction; an
issue-derived problem statement with deterministic leak strips; oracle. Exit codes: `0`
a record was written (read its `curation_status`), `75` infrastructure failure (retry;
nothing written), `70` script error (nothing written). `--no-oracle` writes a `held`
record; `--redo` rejudges. `batch_prepare.py` takes `--since`, `--until`, `--limit`,
`--fast-oracle`, `--redo-dropped`, `--repo`.

Never use `--fast-oracle` to promote a task into the corpus; it runs one pass per arm and
cannot rule out flakiness.

### The oracle contract

A task is **validated** iff, in its fingerprint-matched image:

- arm A (base commit + hidden test): the fail-to-pass targets **fail 2 of 2 times with a
  stable failure signature**, and the pass-to-pass targets are green;
- arm B (+ the real fix): fail-to-pass **pass 3 of 3 times**, pass-to-pass green.

Runner **output** is parsed (`verdict.py`), not just exit codes: a typo'd test target, an
import error before any test, or `Ran 0 tests` is "unenumerable", never counted as a flip.
Port the parsing for your runner's output; this is what keeps a broken enumeration from
reading as a success.

### Curation statuses

| status | meaning |
|---|---|
| `validated` | oracle passed, flake-gated. The usable bank. |
| `held` | prepared, oracle pending (`--no-oracle`). |
| `invalid` | oracle ran and the test did not flip (`oracle_base_passed`, `oracle_invalid`). |
| `dropped` | rejected during curation, with a reason code (`no_issue_ref`, `partial_fix`, `touches_migrations`, `dep_change`, `no_test`, `test_only`, `mixed_lang`, `out_of_scope`, `i18n_churn`, `revert`, `docs_only`, `issue_missing`, `issue_is_pr`, `sparse_issue`, `unsuitable`, `symbol_coupling`, `f2p_unenumerable`, `oracle_not_enumerable`). |

Every judged candidate, accepted or not, leaves a `meta.json` under
`zbench-tasks/tasks/ZT-<sha12>/`, so the funnel stays auditable and re-runs skip
candidates already judged.

## 5. Pitfalls

- **Flaky tests.** The 2x-fail / 3x-pass oracle plus a stable failure signature is the
  defence. If a large share of your candidates come back `invalid` with inconsistent
  signatures, your suite is flaky or order-dependent; fix isolation in the image (fresh
  database, fixed seeds, no network) before blaming the tasks. Reject, never hand-patch:
  a rejected candidate costs corpus size, a hand-patched one costs trust in every score.
- **Coupling screen (three-way).** `clean`: the test checks behaviour. `specifiable`: the
  test binds to a public name the issue does not mention, so that name is written into the
  brief as an "Interface requirements" section. `coupled`: the test binds to private
  internals; the task is dropped (`symbol_coupling`), because no agent could be expected to
  guess them. Expect this to drop a meaningful fraction; tune the prompt on your own
  examples and spot-check both what it kept and what it dropped.
- **Thin issues.** A sparse issue does not auto-drop: the brief may draw expected-behaviour
  evidence from the gold test diff, without ever revealing that tests exist. The commit
  message is never used (it explains why the fix is right, which hands over the answer).
- **No issue tracker discipline.** The pipeline assumes a linked GitHub issue. Without one,
  you must decide what the problem statement derives from (a ticket body, a PR
  description) and rewrite the fetch stage in `prepare_task.py`. Keep the rule: never the
  commit message or diff.
- **Contamination tiers.** Each task records when its fix became public against each
  model's training cutoff (`agents-meta.jsonl`; refresh with
  `python3 zbench-tasks/scripts/recompute_tiers.py`). For a **private** repo that was never
  public, tiers are moot; if any part of your history was ever public (open-sourced later,
  mirrored, or copied into public gists), keep the tiering. Tiers annotate the board; they
  are not a gate.
- **Your corpus is derived from your source code.** `gold_test.patch`, `gold_code.patch`
  and the problem statements contain your code. Do not publish the task corpus unless you
  mean to publish those fixes, and keep `solutions/` out of any agent-visible directory.
- **Curation LLM.** `config.py` pins the screening model through the `claude` CLI
  (`LLM_CMD`). Either have that CLI and credential on the mining host or edit `LLM_CMD`
  to your own headless, tool-less LLM command. The `ZBENCH_LLM=pi` alternative in
  `config.py` is wired to a specific provider name and is not portable; edit it before
  use.
- **Agents see the network.** Most CLI agents call a model API, so generation is not
  network-isolated (grading is, with `--network none`). For a private repo this is fine;
  say so plainly in anything you publish rather than claiming full isolation.
- **Human review.** The oracle proves a task is *gradeable*, not that it is a *good
  benchmark item*. When you first build your task bank, reading the brief and both patches
  for each task (or a large sample) is strongly recommended to verify the pipeline;
  `zbench-tasks/review_task.py` records the sign-off in `meta.review`. Once that initial
  pass is done, further review is optional. METHODOLOGY section 2 explains why.
- **Don't oversize.** The caps in `quality.py` (15 code files, 600 added lines) keep a task
  "small and single-purpose" by a gate rather than by an LLM's judgment.

## 6. Growing to about 100 validated tasks

1. Mine with `--stats` and fix the predicate until the funnel looks right.
2. Prepare ~10 tasks; read every brief and patch pair yourself.
3. Batch a window with `batch_prepare.py` (resumable; skips already-judged candidates),
   then widen the window backwards.
4. Track the yield with `python3 zbench-tasks/corpus.py --status '*'`. If the validated
   fraction is low, the cause is nearly always the environment recipe or test flakiness.
5. Build images (`prebuild_env_images.py`), register agents, fill the grid, and run the
   post-run review from the RUNBOOK. Keep `--tries` at 1 for the first pass.
6. Stop growing at roughly 100: large enough that a few contentious items do not swing
   the board, small enough that a human can read all of them.

## 7. Testing your changes

`tools/run_tests.sh` (all) and `tools/run_tests.sh static` (fast invariants). Tests that
pin Zulip-shaped behaviour (`zbench/tests/test_strip_test_edits.py`,
`test_classifiers.py`, `test_verdict.py`, `test_workflow.py`) are your regression net for
the isolation, classification and verdict logic; update their fixtures to your layout as
you adapt, rather than deleting them.
