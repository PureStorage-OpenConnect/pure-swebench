# zbench

SWE-bench-style coding eval harness. Tasks are mined from real Zulip fix commits
(github.com/zulip/zulip, full local clone at `$ZBENCH_TARGET_REPO`, default
`~/work/zulip`). Each task = problem statement + hidden regression test; an agent's
patch **resolves** the task iff the hidden test fails on the base commit and passes
after the patch (verified in docker, flake-gated). Owner: the project owner (a data scientist, not
an SWE — when reporting, use simple direct language and explain jargon).

## Read these first
- `METHODOLOGY.md` — the design contract (oracle invariant, curation, contamination
  model, ranking rules). Standing decisions live here.
- `RUNBOOK.md` — how to operate. Tests: `tools/run_tests.sh` (self-running, no pytest).
- `GLOSSARY.md`, `AGENTS.md` — terms and agent-harness configs.

## Key paths
- `zbench-tasks/tasks/ZT-<sha12>/` — one dir per judged candidate; `meta.json` carries
  `curation_status` (validated | held | invalid | dropped) + reasons. The usable bank
  is DERIVED: validated = oracle-passed. `corpus.py` prints the corpus.
- `zbench-tasks/prepare_task.py` — commit → judged task (screens, brief, oracle).
- `zbench-tasks/batch_prepare.py` — mine + prepare a whole date window.
- `zbench-tasks/agents-meta.jsonl` — model roster + training cutoffs (all filled,
  sourced; see METHODOLOGY §5).
- `zbench-tasks/scripts/recompute_tiers.py` — refresh contamination tiers.
- `bench-db/bench.db` — scores/evidence store. `bench-db/.runtime/` — logs, scratch.

## Standing decisions (2026-08-14, project owner)
- **Verifiability is the sole inclusion bar; target ~100 validated tasks.** Task type
  (bug/feature/refactor) and difficulty are not gates.
- **Contamination tiers are advisory, not a gate** (boards keep all validated tasks,
  tier-annotated; enterprise-template rationale — METHODOLOGY §5).
- Coupling screen is three-way: clean | specifiable (public names written into the
  brief as "Interface requirements") | coupled (test binds to private internals →
  drop).
- Thin GitHub issues do not auto-drop; briefs may draw expected-behavior evidence from
  the gold test diff (never revealing tests exist).
- Mining floor `2025-01-01` (infra bound only); size caps 15 files / 600 added lines.
