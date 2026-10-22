# Tools runbook

> Plane: INTERNAL_RUNBOOK. Currency: CURRENT. Owner: tools. Current-number policy: dynamic.

The dashboard is a read-mostly operations UI over `bench.db`: it does not mutate attempt
facts or ranking logic, but explicit note/exclusion endpoints do write human annotations.

## Mental model

| Thing | Source of truth | Writer |
|---|---|---|
| attempts / run facts | `bench-db/bench.db` `attempt`, `run`, `attempt_event` | `zbench` |
| attempt provenance | `bench-db/bench.db` `attempt_provenance` + evidence `provenance.json` | `zbench` / best-effort backfill |
| evidence | `bench-db/blobs/attempt/<eval>/` | `zbench` |
| scoring exclusions | `bench-db/bench.db` `run_exclusion` | human/offline review |
| notes / legacy annotations | `bench-db/bench.db` `note`, `invalidation` | human/tools |
| tasks | `zbench-tasks/tasks/<task_id>/meta.json` | curation |
| liveness | `bench-db/.runtime/live/` + slots | `zbench.cells` |

The old append-file stores were migrated into `bench.db`; do not build new readers against
them. Ranking rules live in `METHODOLOGY.md`; the shared ranking transform is
`ranking_view.py`.

## Main tools

- `bench_dashboard.py` - HTTP dashboard (`/`, `/runs`, `/task`, `/run`, `/corpus`, `/agents`).
- `benchdb_reader.py` - read-only SQL state collector for the board.
- `ranking_view.py` - D1-D7 ranking transform shared by reader/dashboard.
- `readout_snapshot.py` - Markdown result snapshot for reports/hand-offs.
- `job_status.py` - authoritative pipeline-job liveness (see `RUNBOOK.md` "Job liveness").
- `wait_for_cells.py` - event-based wait for grid cells. Default returns on the NEXT cell
  completion (reports the landed cell + outcome); `--all` blocks until the whole target set finishes.
- `consistency_check.py` - repo/doc/data guardrails.
- `dashboard_smoke.py` - render/live dashboard regression smoke checks.
- `transcript_view.py` + `vendor_pi_export/` - pi-style rich transcript rendering.
- `model_prices.py` - list-price token cost table.
- `backfill_tokens.py` - reconcile pi token/cost totals from durable sessions.
- `backfill_provenance.py` - best-effort historical harness commit provenance; future rows are captured at run time.
- `exclude_infra_artifacts.py`, `zbench-tasks/validate_runs.py` - offline post-run review/exclusion helpers.

## Dashboard service

```bash
systemctl --user status bench-dashboard
systemctl --user restart bench-dashboard
```

Foreground:

```bash
python3 tools/bench_dashboard.py [--port 8787] [--benchdb bench-db/bench.db] [--runtime DIR] [--tasks DIR]
```

Binds `127.0.0.1:8787` by default (read-only, no auth). For remote viewing prefer an
SSH tunnel (`ssh -L 8787:127.0.0.1:8787 <host>`); `--host 0.0.0.0` only on a trusted
network.

## Query console (`:8789`)

A self-serve, **read-only** SQL surface over `bench.db` for ad-hoc analysis --
complementary to the curated board above. Type SQL, get a sortable table, export
CSV/JSON, and pick from a library of built-in queries (leaderboard, cost/task,
coverage, no-patch triage, tokens, hard tasks, run summary...).

Runs as a systemd **user** service (`bench-query-console`, linger enabled so it
survives logout/reboot):

```bash
systemctl --user status bench-query-console
systemctl --user restart bench-query-console
```

Foreground:

```bash
python3 tools/query_console.py [--port 8789] [--benchdb bench-db/bench.db] [--tasks DIR]
```

Binds `127.0.0.1:8789` (SSH tunnel: `ssh -L 8789:127.0.0.1:8789 <host>`). The DB is
opened `mode=ro` **and** `PRAGMA query_only=ON`; only a single `SELECT`/`WITH`/`EXPLAIN`
statement is accepted (writes, multi-statement, `ATTACH`, and `PRAGMA`-writes are
refused). Two convenience views pre-join the agent + task metadata:

- `v_attempt` -- `attempt` + agent (`model_name`, `provider`, `open_weight`) + task
  (`curation_status`, `issue_type`, `component`) + run, with `resolved` and a `scored`
  flag (the scoring anti-join). Most queries start here.
- `v_run` -- one row per run: `n_attempts`, `n_resolved`, `cost_usd`.

Two pages (top nav): **SQL Console** (`/`) and a **Data dictionary** (`/schema`) that
describes every table and each column in plain language (rendered from `TABLE_DOCS`;
the smoke test fails if a column is added without a description).

User-saved queries persist to `bench-db/.runtime/query_console_saved.json` -- the only
file this tool writes; it never touches `bench.db`. Smoke test:
`python3 tools/query_console_smoke.py`.

## Post-run review

The canonical ordered post-run review workflow lives in [`RUNBOOK.md`](../RUNBOOK.md)
("Post-run review"). It is not restated here. The write-capable helpers it references have
per-tool safety notes -- run only with explicit review intent:

- `tools/exclude_infra_artifacts.py` writes scoring exclusions; run only with explicit review/intent.
- `zbench-tasks/validate_runs.py` is optional offline evidence review. It is intentionally not a dashboard button.
- `tools/backfill_tokens.py --recompute-all --apply` mutates token/cost fields; it backs up `bench.db` first.
- `tools/backfill_provenance.py --apply` mutates `attempt_provenance`; it backs up `bench.db` first. Historical CLI versions are not recoverable.

## Dashboard endpoints

| route | purpose |
|---|---|
| `/` | leaderboard + task x agent matrix |
| `/runs?agent=&task=&status=` | per-attempt log; excluded attempts remain visible |
| `/task?task=` | canonical task page with problem/card/upstream-source link/attempts/notes |
| `/run?run=&agent=&instance=` | one attempt: pipeline, metrics, patch, transcript/log links, scoring exclusion, notes |
| `/corpus` | corpus/task matrix |
| `/agents` | agent model cards and notes |
| `/rich?bundle=&name=` | rich transcript |
| `/logs`, `/logfile` | evidence blobs |
| `/api/state`, `/api/runs`, `/api/corpus`, `/api/agents` | JSON APIs |

## Vendor policy

`vendor_pi_export/` is one pinned copy of pi's MIT export renderer. Update by replacing
files in place and updating `vendor_pi_export/PROVENANCE.md`; do not add parallel copies.
