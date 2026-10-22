# AGENTS.md - zbench (benchmark / business logic)

> Plane: BENCHMARK (public to the eval's consumers). Currency: CURRENT. Owner: benchmark-maintainers.
> Current-number policy: dynamic; use the dashboard / `tools/readout_snapshot.py` for board numbers.

This repo is the **zbench benchmark**: a SWE-bench-style eval on the open-source
[Zulip](https://github.com/zulip/zulip) codebase - harness, task corpus, scored data (db + blobs),
local dashboard, and methodology.

## Topic router

| I need to know about... | Open |
|---|---|
| detailed ops: env images, model backends, common commands, grid fill, post-run review | `RUNBOOK.md` |
| methodology: task validity, contamination tiers, run exclusions, ranking rules, caveats | `METHODOLOGY.md` |
| current board / leaderboard / numbers | dashboard `http://127.0.0.1:8787/`, or `tools/readout_snapshot.py`, or `tools/benchdb_reader.py` |
| live harness internals / schema / evidence layout / cell runner | `zbench/README.md` |
| task corpus / mining / curation / a specific ZT task | `zbench-tasks/README.md` -> `zbench-tasks/tasks/ZT-*/` |
| dashboard/reader/wait/linter tooling | `tools/README.md` |
| dashboard UI conventions | `UI_DESIGN.md` |
| terms / jargon | `GLOSSARY.md` |

## Project summary

Build a SWE-bench-style eval from Zulip's upstream bugfix commits (`Fixes #N` + tests in the same
commit), then score model x harness x provider x thinking configurations, including open-weight
and self-hosted candidates. Tasks are test-blind; grading runs the hidden gold tests in
`--network none` docker containers (`zbench-env:<fp12>`, fingerprint-cached).

Core data paths:

- Attempts/evidence/scoring overlay: `bench-db/bench.db` + `bench-db/blobs/attempt/<eval>/`.
- Schema: `zbench/schema.sql`.
- Candidate/task records: `zbench-tasks/tasks/ZT-<sha12>/meta.json`; validated corpus derived by `zbench-tasks/corpus.py`.
- Active ranked/fill cohort: `zbench-tasks/agents-matrix.jsonl`.
- Agent metadata incl. training cutoffs (`training_cutoff`/`cutoff_source`/`cutoff_confidence`, `web_tools`): `zbench-tasks/agents-meta.jsonl`.

## Source-of-truth map

| Doc / artifact | Owns |
|---|---|
| `RUNBOOK.md` | operational runbook: env images, model backends, fill/review commands |
| `METHODOLOGY.md` | validity, contamination model, scoring/ranking, data durability, caveats |
| local dashboard | current board and drill-downs over `bench.db` |
| `zbench/README.md` + `zbench/schema.sql` | live harness shape and persistence schema |
| `zbench-tasks/README.md` | task corpus, mining, curation workflow |
| `tools/README.md` | dashboard/reader/wait/linter/transcript tools |
| `UI_DESIGN.md` | dashboard design system |
| `GLOSSARY.md` | plain-language terms |

## Invariants to remember

- Tasks, not bugs; binary resolve only.
- A task is ranked only when `curation_status == "validated"` after oracle validation:
  `base+gold_test` FAILS the f2p targets (stable signature), `base+gold_test+gold_code` PASSES,
  and `pass_to_pass` is green in BOTH arms. A could-not-run is UNENUMERABLE, never a flip.
- Attempts are immutable; scoring exclusions are overlay rows (`run_exclusion`), the only
  scoring switch.
- The ranked board is contamination tier A only (fix postdates every active agent's training
  cutoff + buffer); an agent without a filled `training_cutoff` cannot be ranked. Tier B/C are
  exploratory/probe. Caveats (generation is not network-isolated; vendor cutoffs are claims)
  are printed, never hidden - see `METHODOLOGY.md`.
- Test-blindness is a security boundary: agent edits to tests AND to the runners
  (`tools/test-*`, `tools/ci/**`, `tools/lib/**`) are stripped before verify, and a
  runner-integrity hash check turns tampering into `internal_error`, never a resolve.
- Current docs describe the steady-state model; put historical struggles and retired approaches
  in git history, not runbooks.
- Link, do not restate; retire temporary review drafts after their accepted items land.
- Never post externally (GitHub issues/PRs, upstream Zulip, any tracker) without explicit user
  approval.
