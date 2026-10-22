#!/usr/bin/env python3
"""SQL reader for the report server (bench.db is the single store; schema SoT:
`zbench/schema.sql`).

`collect_state()` is SQL over the facts-only store:

  * ONE read-only open of bench.db (no --checkout / no data/ tree walk),
  * the run_exclusion scoring ANTI-JOIN done in SQL (persistent bench.db table),
  * `task` + `task_test` loaded from the git files into in-memory TEMP tables
    per request (always current, no sync), then joined,
  * /batch liveness read from `.runtime/live/<run>/` (no event-log replay).

The ranking transform lives in `tools/ranking_view.py` so the SQL reader and the
web renderer share the same D1-D5 board logic without importing each other.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
DEFAULT_DB = DOCS / "bench-db" / "bench.db"
DEFAULT_TASKS = DOCS / "zbench-tasks" / "tasks"
DEFAULT_RUNTIME = DOCS / "bench-db" / ".runtime"

# reuse the shared ranking core (single source; no dashboard import)
sys.path.insert(0, str(HERE))
import ranking_view  # noqa: E402

sys.path.insert(0, str(DOCS / "zbench-tasks"))
import exclusions  # noqa: E402  # D1/D7: shared exclusion vocabulary + anti-join

sys.path.insert(0, str(DOCS))
from zbench import constants  # noqa: E402  # identity helpers (instance_of / task_of)

# A heartbeat older than this = STALE (zombie). run_cell now background-heartbeats every 60s for
# the whole run (agent gen + verify), so a LIVE cell is never more than ~60s stale -> this can match
# the lease's own ttl_s (900s) instead of the old lenient 2h that let killed-run zombie leases read
# as RUNNING for hours. (In-flight cells launched by a pre-heartbeat-thread run_cell may briefly show
# STALE during a long phase until they land; that is cosmetic and self-heals as new cells replace them.)
_LEASE_STALE_SEC = 900


# ---- board membership policy (2026-08-17, project owner) -------------------------
# Two agent classes must never appear on the ranked board or the Pareto frontier:
#   * control-* -- Phase-6 control fixtures (zbench-tasks/controls/). control-gold
#     applies the GOLD patch, so it is a 100%-resolve, $0-cost point that DOMINATES
#     the partials-participate frontier by construction. Controls prove the harness
#     guardrails; they are never a model under comparison (see consistency_check).
#   * under-covered agents -- an agent with fewer than MIN_BOARD_TASKS clean tasks
#     has too little signal to compare, and (being cheap+partial) also distorts the
#     participating frontier.
# The bar is DYNAMIC (clean distinct-task coverage): a dropped agent re-enters the
# board automatically once it reaches the bar -- no attempt data is deleted, only the
# board VIEW is filtered. Override the bar with env ZBENCH_MIN_BOARD_TASKS.
MIN_BOARD_TASKS = int(os.environ.get("ZBENCH_MIN_BOARD_TASKS", "10"))


def _is_control_agent(agent_id: str | None) -> bool:
    return bool(agent_id) and agent_id.startswith("control-")


def _retired_agents() -> set[str]:
    """Agent ids marked `retired` in agents-meta.jsonl. Dropped from the board VIEW
    only -- historical attempt data is kept (run_exclusion untouched); the row just
    never ranks or plots. `retired` is truthy as either True or a reason string."""
    out: set[str] = set()
    p = HERE.parent / "zbench-tasks" / "agents-meta.jsonl"
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("retired"):
                out.add(d.get("agent_id"))
    except Exception:
        pass
    return out


def _board_scores(agg_scores: list[dict], min_tasks: int = MIN_BOARD_TASKS) -> list[dict]:
    """Drop rows for agents that must never appear on the board: control-* fixtures,
    agents `retired` in agents-meta, and agents below the clean-coverage bar. Coverage
    is counted on the ALREADY-VALID rows (run_exclusion applied upstream), so it is
    clean distinct-task coverage."""
    cov: dict[str, set] = {}
    for s in agg_scores:
        cov.setdefault(s.get("agent_id"), set()).add(s.get("instance_id"))
    retired = _retired_agents()
    keep = {a for a, t in cov.items()
            if not _is_control_agent(a) and a not in retired and len(t) >= min_tasks}
    return [s for s in agg_scores if s.get("agent_id") in keep]


# ---- query-time TEMP tables (loaded from the git files per request) -------
_TEMP_DDL = """
CREATE TEMP TABLE task(
  task_id TEXT PRIMARY KEY, lang TEXT, component TEXT, issue_type TEXT,
  base_commit TEXT, fix_commit TEXT, difficulty TEXT,
  curation_status TEXT, resolved_date TEXT, summary TEXT);
CREATE TEMP TABLE task_test(
  task_id TEXT, testfunc TEXT, PRIMARY KEY(task_id, testfunc));
CREATE TEMP TABLE agent(
  config_id TEXT PRIMARY KEY, model_name TEXT, provider TEXT, harness TEXT,
  open_weight INTEGER, timeout_s INTEGER);
"""


def _total_tokens(r) -> int:
    """CANONICAL billed total for one attempt row: prefer the stored `total_tokens`,
    else sum the components (in + out + cache_read + cache_write).

    The fallback keeps rows written before the column existed comparable with new ones.
    cache_write is INCLUDED because model_prices bills it -- omitting it (as three call
    sites used to) made "total tokens" irreconcilable with the cost on the same row.
    """
    def _get(key):
        try:
            return r[key]
        except (KeyError, IndexError):   # column not in this query's SELECT list
            return None
    stored = _get("total_tokens")
    if stored is not None:
        return int(stored)
    return sum(int(_get(k) or 0) for k in
               ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open bench.db READ-ONLY (writes nothing) and load the task TEMP tables."""
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.executescript(_TEMP_DDL)
    return conn


def _load_task_temp(conn: sqlite3.Connection, tasks_dir: Path) -> dict:
    """Load task meta + tests into TEMP tables (query-time model, §4/§6). Returns
    the raw meta dicts keyed by task_id for the display-only extras the schema drops
    (review block, card/instance presence) -- the same fields the file reader
    surfaces from meta.json."""
    metas = {}
    for td in sorted(p for p in Path(tasks_dir).glob("*") if (p / "meta.json").is_file()):
        mp = td / "meta.json"
        meta = {}
        if mp.exists():
            try:
                meta = json.loads(mp.read_text())
            except Exception:
                meta = {}
        task_id = td.name
        meta["_has_card"] = (td / "card.md").exists()
        meta["_has_instance"] = (td / "instance.jsonl").exists()
        metas[task_id] = meta
        conn.execute(
            "INSERT OR REPLACE INTO task(task_id,lang,component,issue_type,base_commit,"
            "fix_commit,difficulty,curation_status,resolved_date,summary) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, meta.get("lang"), meta.get("component"), meta.get("type"),
             meta.get("base_commit"), meta.get("fix_commit"), meta.get("difficulty"),
             meta.get("curation_status"), meta.get("resolved"), meta.get("summary")))
        for tf in (meta.get("gold_test") or meta.get("test_functions") or []):
            if isinstance(tf, str):
                conn.execute("INSERT OR IGNORE INTO task_test(task_id,testfunc) VALUES(?,?)",
                             (task_id, tf))
    return metas


def _load_agent_temp(conn: sqlite3.Connection, tasks_root: Path) -> None:
    """Load the file-authored agent dim into the TEMP `agent` table from agents-meta.jsonl
    (facts-only: replaces the removed model/harness_config; the file is the single source)."""
    p = Path(tasks_root) / "agents-meta.jsonl"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO agent(config_id,model_name,provider,harness,open_weight,timeout_s) "
            "VALUES(?,?,?,?,?,?)",
            (d.get("agent_id"), d.get("model"), d.get("provider"), d.get("harness"),
             1 if d.get("open_weight") else 0, d.get("agent_timeout_s")))


# ---- the ANTI-JOIN: valid executions as file-shaped records ---------------
def _total_tok_col(conn: sqlite3.Connection) -> str:
    """`a.total_tokens` when the column exists, else a NULL stand-in.

    Readers open bench.db READ-ONLY and cannot run the ALTER themselves, so a database
    written before total_tokens existed must still load; _total_tokens() then falls back
    to summing the components.
    """
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(attempt)")}
    except Exception:
        cols = set()
    return "a.total_tokens" if "total_tokens" in cols else "NULL AS total_tokens"


def _turns_col(conn: sqlite3.Connection) -> str:
    """`a.turns` when the column exists, else a NULL stand-in (read-only DB written before
    the turns column existed must still load)."""
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(attempt)")}
    except Exception:
        cols = set()
    return "a.turns" if "turns" in cols else "NULL AS turns"


def _valid_attempts_sql(conn: sqlite3.Connection) -> str:
    return f"""
SELECT a.evaluation_id, a.task_id, a.run_id,
       a.tests_passed, a.status, a.outcome AS attempt_outcome,
       a.cost_usd, a.finished_at,
       a.runtime_ms, a.total_duration_ms, a.output_tokens,
       a.input_tokens, a.cache_read_tokens, a.cache_write_tokens, {_total_tok_col(conn)},
       {_turns_col(conn)},
       a.config_id, ag.model_name AS model_name, ag.provider AS provider
FROM attempt a
LEFT JOIN agent ag ON a.config_id = ag.config_id   -- facts-only: dims are the file-authored temp table
WHERE {exclusions.NOT_EXCLUDED_SQL}  -- D7: shared anti-join (row exists => excluded)
"""


def _valid_scores(conn: sqlite3.Connection) -> list[dict]:
    """Every VALID execution as a record shaped like the file store's score rows,
    so ranking_view.aggregate_and_rank() consumes it unchanged."""
    out = []
    for r in conn.execute(_valid_attempts_sql(conn)):
        out.append({
            "agent_id": r["config_id"],
            "instance_id": constants.instance_of(r["task_id"]),
            "run_id": r["run_id"],
            "tests_passed": bool(r["tests_passed"]),
            "status": r["status"],
            "attempt_outcome": r["attempt_outcome"],
            "model_name": r["model_name"],
            "provider": r["provider"],
            "cost_usd": r["cost_usd"],
            "timestamp": r["finished_at"],
            "metrics": {
                # CANONICAL total (in+out+cacheR+cacheW) is stored by transform.attempt_row.
                # Fall back to the component sum for rows written before that column existed --
                # same formula, so old and new rows are directly comparable.
                "total_tokens": _total_tokens(r),
                "output_tokens": r["output_tokens"],
                "input_tokens": r["input_tokens"],
                "cache_read_tokens": r["cache_read_tokens"],
                "cache_write_tokens": r["cache_write_tokens"],
                "runtime_ms": r["runtime_ms"],
                "total_duration_ms": r["total_duration_ms"],
                "turns": r["turns"],
            },
        })
    return out


def _contam_pairs(conn: sqlite3.Connection) -> set:
    """(instance_id, agent_id) that are contamination-annotated -- passed to the
    ranking core, which keeps them as invalid placeholders ONLY when the agent
    has no surviving clean re-run of that instance (so a cheater earns nothing
    but the task stays in the honest agents' common set)."""
    pairs = set()
    for r in conn.execute(
        """SELECT DISTINCT a.config_id, a.task_id
           FROM run_exclusion rx JOIN attempt a USING(evaluation_id)
           WHERE rx.reason LIKE '[contamination]%'
             AND a.config_id IS NOT NULL"""):
        pairs.add((constants.instance_of(r["task_id"]), r["config_id"]))
    return pairs


def _infra_limited_pairs(conn: sqlite3.Connection) -> set:
    """(instance_id, agent_id) where the agent has attempts on the task but NO valid
    attempt (all excluded) AND at least one exclusion is [artifact:infra]. Such a task
    is UNSCOREABLE for that agent due to infrastructure (e.g. the per-model TPM rate cap ->
    perpetual terminal-429), NOT capability -- the ranking core drops it from the COMMON
    SET rather than relegating the agent to leaderboard_partial. Distinct from
    contamination (kept as a placeholder)."""
    pairs = set()
    for r in conn.execute(
        """SELECT a.config_id, a.task_id,
                  SUM(CASE WHEN rx.evaluation_id IS NULL THEN 1 ELSE 0 END) AS valid_cnt,
                  SUM(CASE WHEN rx.reason LIKE '[artifact:infra]%' THEN 1 ELSE 0 END) AS infra_cnt
           FROM attempt a
           LEFT JOIN run_exclusion rx ON rx.evaluation_id = a.evaluation_id
           WHERE a.config_id IS NOT NULL
           GROUP BY a.config_id, a.task_id
           HAVING valid_cnt = 0 AND infra_cnt > 0"""):
        pairs.add((constants.instance_of(r["task_id"]), r["config_id"]))
    return pairs


def _excluded_agents(conn: sqlite3.Connection) -> list[str]:
    """Agents dropped from ranking by an AGENT-LEVEL annotation (run/instance NULL)
    that actually have attempts -- the transparency footnote."""
    rows = conn.execute(
        "SELECT DISTINCT i.config_id FROM invalidation i "
        "WHERE i.config_id IS NOT NULL AND i.run_id IS NULL AND i.task_id IS NULL "
        "  AND EXISTS(SELECT 1 FROM attempt a WHERE a.config_id=i.config_id)"
    ).fetchall()
    return sorted(r["config_id"] for r in rows)


# ---- liveness from .runtime/live (replaces event-log replay) --------------
def _lease_state(runtime_dir: Path) -> dict:
    """run_id -> {cell_key: lease dict} from .runtime/live/<run>/<cell>.json.
    A lease is a heartbeat file; missing dir = no live cells for that run."""
    live = Path(runtime_dir) / "live"
    out: dict[str, dict] = {}
    if not live.is_dir():
        return out
    for rd in live.iterdir():
        if not rd.is_dir():
            continue
        cells = {}
        for f in rd.glob("*.json"):
            try:
                cells[f.stem] = json.loads(f.read_text())
            except Exception:
                cells[f.stem] = {}
        if cells:
            out[rd.name] = cells
    return out


def _age(ts):
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def _runs_section(conn: sqlite3.Connection, leases: dict) -> list[dict]:
    """Reconstruct the Runs listing WITHOUT an event log (§6): landed rows come
    from `attempt`, live/stale rows from the `.runtime/live` leases, pending rows
    from `run.plan`. state precedence: lease (RUNNING/STALE) overrides a landed
    fact only when the fact has not been written yet."""
    # landed attempts grouped by run
    by_run: dict[str, list] = {}
    for r in conn.execute(
        "SELECT a.evaluation_id, a.run_id, a.config_id, a.task_id, a.tests_passed, "
        "a.status, a.outcome, a.finished_at, a.runtime_ms, a.total_duration_ms, "
        "a.input_tokens, a.output_tokens, a.cache_read_tokens, a.cache_write_tokens, "
        f"{_total_tok_col(conn)}, {_turns_col(conn)}, "
        "ag.model_name AS model_name, ag.provider AS provider "
        "FROM attempt a LEFT JOIN agent ag ON a.config_id=ag.config_id"
    ):
        by_run.setdefault(r["run_id"], []).append(r)

    run_meta = {r["run_id"]: dict(r) for r in conn.execute(
        "SELECT run_id, label, started_at, plan FROM run")}

    runs = []
    seen = set()
    # order by LAST ACTIVITY across ALL runs (landed attempts, lease heartbeats,
    # and run.started_at), with ACTIVE runs (a fresh lease) pinned first -- so a
    # just-launched run that hasn't landed an attempt yet still shows at the TOP
    # ("newest first"), not buried after every completed run.
    def _recency(rid):
        ts = [str(a["finished_at"] or "") for a in by_run.get(rid, [])]
        for lease in leases.get(rid, {}).values():
            ts.append(str(lease.get("heartbeat_at") or lease.get("started_at") or ""))
        ts.append(str((run_meta.get(rid, {}) or {}).get("started_at") or ""))
        return max(ts, default="")
    def _active(rid):
        return any((_age(l.get("heartbeat_at") or l.get("started_at")) or 0) <= _LEASE_STALE_SEC
                   for l in leases.get(rid, {}).values())
    all_rids = set(by_run) | set(run_meta) | set(leases)
    order = sorted(all_rids, key=lambda rid: (_active(rid), _recency(rid)), reverse=True)
    for rid in order:
        if rid in seen:
            continue
        seen.add(rid)
        meta = run_meta.get(rid, {})
        plan = {}
        if meta and meta.get("plan"):
            try:
                plan = json.loads(meta["plan"])
            except Exception:
                plan = {}
        run_leases = leases.get(rid, {})
        # Skip runs with NOTHING to show: no landed attempts AND no live lease.
        # (A genuinely running/pending run always holds a .runtime/live lease, since
        # run_cell opens one at launch.) This drops dead/empty historical run rows
        # -- e.g. plan-only rows created by migration/audit -- that would otherwise
        # render as misleading "0/0 running" entries.
        if not by_run.get(rid) and not run_leases:
            continue
        landed_keys = set()
        rows = []
        for a in sorted(by_run.get(rid, []),
                        key=lambda x: (x["task_id"] or "", x["config_id"] or "")):
            key = f'{a["config_id"]}__{a["task_id"]}'   # no try (W109); matches store.Lease key
            landed_keys.add(key)
            o = ranking_view._outcome_of({"tests_passed": a["tests_passed"], "status": a["status"],
                                          "attempt_outcome": a["outcome"]})
            rows.append({
                "evaluation_id": a["evaluation_id"],
                "agent_id": a["config_id"], "instance_id": constants.instance_of(a["task_id"]),
                "task_id": a["task_id"],  # W100: bare id carried natively for DISPLAY (no strip)
                "try": 1, "state": "DONE", "phase": "scored",
                "ended": a["finished_at"], "scored": True, "outcome_cls": o,
                "status": a["status"], "tests_passed": a["tests_passed"],
                "model_name": a["model_name"], "provider": a["provider"],
                "runtime_ms": a["runtime_ms"] or a["total_duration_ms"],
                # expose BOTH so the UI can show true wall-clock (gen+verify), not
                # just generation -- a slow/timed-out verify lives in total_duration_ms.
                "gen_ms": a["runtime_ms"],
                "total_duration_ms": a["total_duration_ms"],
                "turns": a["turns"],
                "total_tokens": _total_tokens(a),
            })
        # live/stale cells (lease present, no landed fact yet)
        n_running = n_stale = 0
        for key, lease in run_leases.items():
            if key in landed_keys:
                continue
            hb = lease.get("heartbeat_at") or lease.get("started_at")
            stale = (_age(hb) or 0) > _LEASE_STALE_SEC
            state = "STALE" if stale else "RUNNING"
            if stale:
                n_stale += 1
            else:
                n_running += 1
            # the lease stores `task_id` (e.g. ZT-<sha12>), not instance_id; derive
            # the instance id so the live row's instance/tracker cell isn't blank.
            _task_id = lease.get("task_id")
            rows.append({
                "agent_id": lease.get("config_id") or key.split("__")[0],
                "instance_id": lease.get("instance_id") or (constants.instance_of(_task_id) if _task_id else None),
                "task_id": _task_id,  # W100: bare id for display
                "try": 1, "state": state,
                "phase": lease.get("phase") or "generating",
                "started": lease.get("started_at"),
                "elapsed_s": _age(lease.get("started_at")), "scored": False,
            })
        runs.append({
            "run_id": rid, "started": meta.get("started_at"),
            "last_event": max((str(r["finished_at"] or "") for r in by_run.get(rid, [])),
                              default=meta.get("started_at")),
            "planning": plan, "n_attempts": len(rows), "n_running": n_running,
            "n_stale": n_stale, "rows_from_scores": bool(by_run.get(rid)),
            "active": n_running > 0, "rows": rows, "io_logs": None,
        })
    return runs


def collect_state(db_path: Path = DEFAULT_DB, tasks_dir: Path = DEFAULT_TASKS,
                  runtime_dir: Path = DEFAULT_RUNTIME) -> dict:
    """The SQL equivalent of bench_dashboard.collect_state()."""
    conn = _connect(db_path)
    try:
        metas = _load_task_temp(conn, tasks_dir)
        _load_agent_temp(conn, Path(tasks_dir).parent)   # facts-only: file-authored agent dim

        agg_scores = _valid_scores(conn)
        # Board policy: control-* fixtures + under-covered agents never rank or plot
        # on the frontier (see MIN_BOARD_TASKS above). Applied before aggregation so
        # the filter reaches leaderboard, partial list, agent_axis, and BOTH Pareto
        # variants consistently.
        agg_scores = _board_scores(agg_scores)
        contam_pairs = _contam_pairs(conn)
        # validated-corpus instance ids -> restrict the common set to real corpus
        # tasks (so non-corpus attempts / mid-grid partials can't distort it).
        corpus_instances = None
        try:
            import corpus
            corpus_instances = {constants.instance_of(tid) for tid in
                                corpus.validated_ids(tasks_dir=str(tasks_dir))}
        except Exception:
            corpus_instances = None
        agg = ranking_view.aggregate_and_rank(agg_scores, contam_pairs,
                                              corpus_instances=corpus_instances,
                                              infra_limited_pairs=_infra_limited_pairs(conn))

        # corpus set + normalized status/lang via corpus (single source),
        # exactly like the file reader; join outcome stats from the ranking core.
        corpus = {}
        try:
            import corpus
            corpus = {r["task_id"]: r for r in
                      corpus.load_corpus("*", tasks_dir=str(tasks_dir))}
        except Exception:
            corpus = {}

        tasks = []
        for task_id in sorted(metas):
            meta = metas[task_id]
            crow = corpus.get(task_id, {})
            tasks.append({
                "task_id": task_id,
                "has_card": meta.get("_has_card", False),
                "has_instance": meta.get("_has_instance", False),
                "curation_status": crow.get("status") or meta.get("curation_status"),
                "curation_stage": meta.get("curation_stage"),
                "reason_code": meta.get("reason_code"),
                "reason": meta.get("reason"),
                "lang": crow.get("lang") or meta.get("lang"),
                "summary": meta.get("summary"),
                "component": meta.get("component"),
                "type": meta.get("type"),
                "author": meta.get("author"),  # A3: git author of the gold-patch fix_commit
                "review": meta.get("review", {}),
                "base_commit": meta.get("base_commit"),
                "fix_commit": meta.get("fix_commit"),
                "stats": agg["inst_stats"].get(task_id),
                "agent_outcomes": agg["inst_agent"].get(task_id, {}),
                # W111: per-task common-set membership (in/out + reason), recomputed
                # on demand by aggregate_and_rank; None for non-corpus/unknown tasks.
                "common_set": agg.get("common_membership", {}).get(task_id),
            })

        # header counts: dedup contamination-clean attempts by (config,task_id,try),
        # mirroring the file reader's `scores` / n_scores. W39: contamination state
        # lives in human-controlled run_exclusion reason prefix, not annotation notes.
        clean = conn.execute("""
            SELECT a.config_id, a.task_id, a.run_id, a.finished_at
            FROM attempt a WHERE NOT EXISTS(
              SELECT 1 FROM run_exclusion rx
              WHERE rx.evaluation_id=a.evaluation_id
                AND rx.reason LIKE '[contamination]%')
        """).fetchall()
        dedup = {}
        for r in clean:
            k = (r["config_id"], r["task_id"])   # no try (W109)
            if k not in dedup or str(r["finished_at"] or "") >= str(dedup[k]["finished_at"] or ""):
                dedup[k] = r
        n_scores = len(dedup)
        n_runs_scored = len({r["run_id"] for r in dedup.values() if r["run_id"]})

        n_excluded = conn.execute(
            "SELECT COUNT(*) FROM run_exclusion WHERE reason LIKE '[contamination]%'").fetchone()[0]

        leases = _lease_state(runtime_dir)
        runs = _runs_section(conn, leases)
        active_locks = []
        for rid, cells in leases.items():
            for key, lease in cells.items():
                if (_age(lease.get("heartbeat_at") or lease.get("started_at")) or 0) <= _LEASE_STALE_SEC:
                    active_locks.append({"agent_id": lease.get("config_id") or key.split("__")[0],
                                         "mtime": lease.get("heartbeat_at") or lease.get("started_at")})

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "checkout": str(Path(db_path).resolve()),   # now: the DB path (§6)
            "tasks_dir": str(tasks_dir),
            "active_locks": active_locks,
            "runs": runs,
            "tasks": tasks,
            "leaderboard": agg["leaderboard"],
            "leaderboard_partial": agg["leaderboard_partial"],
            "n_common": agg["n_common"],
            "pareto_tolerance": agg.get("pareto_tolerance", 0.0),
            "n_excluded": n_excluded,
            "excluded_agents": _excluded_agents(conn),
            "agent_axis": agg["agent_axis"],
            "n_scores": n_scores,
            "n_backfilled": 0,   # not tracked in bench.db (provenance lives in blobs)
            "n_runs_scored": n_runs_scored,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    a = ap.parse_args()
    st = collect_state(a.db, a.tasks, a.runtime)
    print(json.dumps({k: v for k, v in st.items() if k not in ("runs", "tasks")},
                     indent=2, default=str))
    print(f"\nruns={len(st['runs'])} tasks={len(st['tasks'])} "
          f"leaderboard={len(st['leaderboard'])} n_common={st['n_common']}")
