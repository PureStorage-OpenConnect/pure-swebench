# zbench

> Plane: INTERNAL_RUNBOOK. Currency: CURRENT. Owner: live-harness. Current-number policy: none.

The zbench eval harness, live on the facts-only single store `../bench-db/bench.db`.
All runtime staging and evidence live under `../bench-db/` (`blobs/`,
`.runtime/{live,slots,cells,runs}`); no operational path references any external
checkout. Tasks arrive from `../zbench-tasks/` only through the instance.jsonl
contract -- the harness never imports the corpus pipeline.

## One attempt (`workflow.py`)

1. History-isolated standalone checkout of the task's base commit (depth-1 fetch from
   the local Zulip clone; the agent cannot see the fix in git history).
2. Run the agent test-blind (problem statement + code only).
3. Apply the agent patch; strip ANY agent edits to tests, test infra, and the runners
   back to base (`_TEST_PATHSPECS`: `**/tests/**`, `**/tests.py`, `**/test_*.py`,
   `**/conftest.py`, `**/*.test.*`, `web/e2e-tests/**`, `tools/test-*`, `tools/ci/**`,
   `tools/lib/**`); apply the hidden gold_test.
4. Runner-integrity hash check (`_RUNNER_INTEGRITY_PATHS`): any diff or untracked file
   under the runners after the strip aborts the attempt as `internal_error` -- never
   resolve.
5. Verify via the task's `commands.tests` shell string
   (`bash "$ZBENCH_SCRIPTS/zbench_verify.sh" ...` -- a `--network none` container; the
   workflow injects `ZBENCH_SCRIPTS` + `ZBENCH_WORKTREE`). Exit code decides.
6. Classify + record the attempt fact and evidence bundle via `store`.

There is no unrelated-failure promotion: verify commands target specific test
classes/files, so every failure is related by construction.

## Current shape

- Data model: plain dicts at the edges; `schema.sql` is the persistence SoT.
- Identity: `(run_id, config_id, task_id)` for an attempt; name-shaped policy lives in
  `constants.py` (`INSTANCE_PREFIX`, `task_of`/`instance_of`, `tracker_url`,
  `operator`). Task ids are opaque to the harness (`ZT-<sha12>` by convention).
- Concurrency: `cells/run_cell.py` (self-admitting cells, flock slots + leases) and
  `cells/slots.py` pools (`setup` / `verify:backend` / `verify:frontend` /
  `provider:*`).
- Evidence: parent-owned per-cell dir copied into
  `bench-db/blobs/attempt/<evaluation_id>/` with stable names (`agent_io.json`,
  `session.jsonl` for pi, `rawcli.txt` for claude, `patch.diff`, `pb-verify.log`,
  `provenance.json`).

## Tests

One entry point: `tools/run_tests.sh` (self-running files, no pytest). Boundary-pinning:

- `tests/test_strip_test_edits.py` -- the test-blindness gate: agent edits to
  code+tests+runners+a new test file; only code edits survive, runners pristine.
- `tests/test_classifiers.py` -- build-err/infra signature truth table (a Django
  `FAILED (failures=1)` classifies as neither).
- `tests/test_verdict.py` -- runner-output parsing for `zbench-tasks/verdict.py`
  (PASS/FAIL/NOTRUN incl. `Ran 0 tests` -> NOTRUN).
- `tests/test_workflow.py` -- golden E2E incl. the `$ZBENCH_SCRIPTS` contract case.
- `tests/test_static_invariants.py` -- static repo/doc/schema invariants incl.
  `check_no_legacy_names`, imported from `tools/consistency_check.py` (one source of
  truth).
