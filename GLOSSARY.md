# Glossary

> Plane: PRODUCT_PUBLIC. Currency: CURRENT. Owner: glossary. Current-number policy: none.

Plain-language definitions for terms used in the zbench docs and dashboard.

## Core concepts

- **zbench** - this benchmark: a SWE-bench-style eval on the open-source Zulip codebase.
- **Zulip** - the target open-source project (github.com/zulip/zulip, Python/Django +
  TypeScript); its commit discipline (tests required in the fix commit, `Fixes #N`) is
  what makes task mining possible.
- **Task** - one item in the test set: a real upstream bugfix turned into a coding
  challenge. Task id = `ZT-<sha12>` (first 12 hex of the fix commit; content-addressed,
  never shown to the agent). Instance id = `zbench_ZT-<sha12>`.
- **Candidate/task record** - one judged candidate under `zbench-tasks/tasks/ZT-*/`, with
  structured status and provenance in `meta.json`.
- **Corpus** - the active ranked task set: candidate/task records with
  `curation_status=validated`, derived by `zbench-tasks/corpus.py`.
- **Corpus epoch** - a pinned snapshot of the corpus that a ranked board is computed over;
  cross-epoch score comparisons are invalid because the task set changed.

## Task construction

- **Base commit** - the code state before the fix (the fix commit's parent), where the
  agent starts.
- **Gold code (`gold_code.patch`)** - the original human fix; the answer key. Stored in
  `zbench-tasks/solutions/<task_id>/`, NOT in the task dir, so it never sits beside the
  agent-visible brief. Resolve via `config.gold_code_path()`.
- **Gold test (`gold_test.patch`)** - the hidden tests from the same commit, used for
  grading; the model never sees them.
- **Problem statement** - the sanitized prompt given to the model: the linked GitHub
  issue's title + body only, with deterministic leak strips (fix SHA, `#N` references,
  github/zulip URLs).
- **fail_to_pass (f2p)** - the hidden test target(s) expected to fail at base and pass
  after the fix.
- **pass_to_pass (p2p)** - a small capped set of pre-existing test targets that must stay
  green; guards against fixes that break neighbors, required green in both oracle arms.
- **Oracle / flip** - the validity check: arm A (`base+gold_test`) FAILS f2p with a stable
  failure signature AND passes p2p; arm B (`+gold_code`) PASSES f2p and p2p. Only a
  flake-gated flip validates a task (`zbench-tasks/oracle_validate.py`).
- **UNENUMERABLE** - oracle outcome when the test could not run at all (bad target, import
  error, `Ran 0 tests`); deliberately distinct from INVALID so a typo never fakes a flip.
- **Held task** - promising task not yet oracle-validated.
- **Dropped / invalid task** - rejected in curation (`dropped`) or by the oracle (`invalid`).
- **Test coupling / symbol coupling** - bad hidden-test dependence on exact symbols or
  signatures introduced by the original fix. High coupling makes the task unfair.
- **Env fingerprint / env image** - `sha256` over the blob ids of Zulip's
  environment-defining files at base, first 12 hex; grading runs in the matching cached
  docker image `zbench-env:<fp12>` (built by `zbench-tasks/scripts/build_env_image.sh`).

## Running the eval

- **Model** - an AI model/weights family.
- **Harness** - wrapper/driver around a model, such as pi or claude CLI.
- **Agent / agent_id** - the ranked entity: model x harness x provider x thinking.
- **Cell** - one `(task, agent_id)` pair.
- **Attempt** - one execution of a cell. Attempts are immutable rows in `bench.db`.
- **Grid / matrix** - the full table of agents x tasks.
- **Hermetic** - isolated config/credentials/session so runs do not inherit ambient state.
- **Test-blind** - the model does not see the hidden gold tests; agent edits to test files
  and test runners are stripped before grading (runner-integrity checked).
- **Contamination tiers (A/B/C)** - per-task tiers from the fix's public date vs the agent
  cohort's training cutoffs: A = fix postdates all active cutoffs (+buffer) - the only
  ranked tier; B = postdates some; C = predates all (memorization probe). UNKNOWN until
  cutoffs are filled in `agents-meta.jsonl`. Rules and caveats: `METHODOLOGY.md`.

## Scoring and ranking

- **Resolved** - the agent's patch passed the hidden tests.
- **Unresolved** - it did not pass: no patch, apply/build failure, or behavior miss.
- **Binary resolve** - the only capability score: pass/fail, no partial credit.
- **Resolve rate** - fraction of common-set tasks an agent resolved; the primary ranking
  number.
- **pass@k** - future binary extension: give up to k attempts and count a task solved if
  any attempt passes.
- **Common set / n_common** - tasks counted in the leaderboard because all ranked agents
  have comparable valid coverage, after infra-limited drops.
- **Infra-limited** - a task/cell excluded from the common comparison because it is blocked
  by serving/quota/infra rather than model capability.
- **run_exclusion** - per-attempt scoring overlay row that excludes an immutable attempt
  from ranking while keeping the raw evidence; the ONLY scoring switch.
- **Pareto frontier** - the capability-vs-cost view: an agent is on the frontier iff no
  other agent is both better (within a practical-equivalence tolerance on resolve rate)
  and cheaper. A view over the same numbers, not a new score.
- **Difficulty spread / gradient** - deliberately mixing easy, medium, and hard tasks so
  models separate instead of all passing or all failing.

## Evidence and operations

- **bench.db** - SQLite store for attempts, runs, notes, scoring exclusions, and metadata.
- **Evidence blob** - per-attempt files under `bench-db/blobs/attempt/<evaluation_id>/`,
  including patch, verify log, transcript/session, and agent I/O.
- **Local GPU server** - a locally hosted GPU machine used for self-hosted open-weight model serving.
- **Foundry / Fireworks / Anthropic** - hosted provider paths used by pi/claude/codex agents.
