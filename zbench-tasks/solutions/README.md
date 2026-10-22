# Reference solutions (answer keys)

One directory per judged candidate, holding a single file:

```
zbench-tasks/solutions/ZT-<sha12>/gold_code.patch
```

`gold_code.patch` is the **human fix** from the upstream commit -- the answer. It is kept
here rather than inside `zbench-tasks/tasks/ZT-<sha12>/` so that the answer key is never
adjacent to the material an agent is meant to read.

## Why the split exists

Runtime test-blindness never depended on it. A solving agent works in a checkout of the
*target* repository, not in this one, and any edit it makes to a test file is reverted to
base before the hidden test is applied (`zbench/workflow.py`). That is the real boundary.

This split is defence in depth for a different case: somebody clones this repo and points
a coding agent at it with filesystem access. Under the old layout the answer sat in the
same directory as the brief. Now a consumer can also drop the whole tree:

```bash
rm -rf zbench-tasks/solutions        # tasks still run; the oracle can no longer re-validate
```

## What still needs these files

The answer key is required to *build* and *check* a task, never to solve one:

| consumer | why it needs gold_code |
|---|---|
| `oracle_validate.py` | arm B is `base + gold_test + gold_code`; without it a task cannot validate |
| `quality.py` (via `prepare_task`, `backfill_quality`) | complexity and scope gates measure the fix |
| `validate_runs.py` | patch-similarity judge compares a resolved attempt against the fix |
| `controls/control_agents.py` | the `gold` control agent emits it verbatim (upper-bound sanity check) |
| dashboard | renders it behind a `reference/spoiler` label |

Every one of them resolves the path through `config.gold_code_path()`, which prefers this
tree and falls back to the legacy in-task location. A corpus prepared before the split
therefore still validates without migration.

## Adapting this to your own corpus

`ZBENCH_SOLUTIONS_DIR` relocates the tree. Point it outside the repository if you want the
answer keys off the clone entirely:

```bash
export ZBENCH_SOLUTIONS_DIR=/secure/elsewhere/zbench-solutions
```

Nothing agent-facing reads this variable, and no task artifact references a path inside it.
