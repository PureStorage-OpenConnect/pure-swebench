#!/usr/bin/env python3
"""zbench data-layer tests (ingest + transform + schema). No pb/DB-of-record needed.

Run: python3 zbench/tests/test_data_layer.py   (asserts; exit 0 = pass)
Locks the W19 data-oriented invariants: strict edge validation, the reality-corrected
shapes, pure transforms, and that dropping try_number loses no information.

Fresh-clone-safe: the identity test runs on a synthetic fixture; corpus/DB-backed
passes run additionally only when those artifacts exist locally.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from zbench import constants, ingest, transform          # noqa: E402

TASKS = ROOT / "zbench-tasks" / "tasks"
SCHEMA = (ROOT / "zbench" / "schema.sql").read_text()
DB = ROOT / "bench-db" / "bench.db"

# Synthetic attempts: two same-cell rows in different runs plus one distinct cell --
# enough to prove (run_id, config_id, task_id) is a lossless identity without try_number.
_FIXTURE_ATTEMPTS = [
    {"run_id": "r1", "agent_id": "agent-a", "instance_id": "zbench_T-1",
     "tests_passed": True, "status": "ok", "attempt_outcome": "completed",
     "cost_usd": 0.01, "timestamp": "2026-01-01T00:00:00+00:00",
     "metrics": {"input_tokens": 10, "output_tokens": 20}},
    {"run_id": "r2", "agent_id": "agent-a", "instance_id": "zbench_T-1",
     "tests_passed": False, "status": "tests_failed",
     "attempt_outcome": "verification_tests_failed",
     "cost_usd": 0.02, "timestamp": "2026-01-02T00:00:00+00:00",
     "metrics": {"input_tokens": 11, "output_tokens": 21}},
    {"run_id": "r1", "agent_id": "agent-b", "instance_id": "zbench_T-2",
     "tests_passed": False, "status": "no_patch_generated",
     "attempt_outcome": "candidate_missing",
     "cost_usd": None, "timestamp": "2026-01-03T00:00:00+00:00",
     "metrics": {"input_tokens": 12, "output_tokens": 22}},
]


def _fresh_db() -> sqlite3.Connection:
    c = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    c.executescript(SCHEMA)
    return c


def _insert_attempts(c: sqlite3.Connection, scores: list[dict]) -> int:
    seen_runs: set[str] = set()
    for score in scores:
        row = transform.attempt_row(score)
        if row["run_id"] not in seen_runs:
            c.execute("INSERT OR IGNORE INTO run(run_id) VALUES(?)", (row["run_id"],))
            seen_runs.add(row["run_id"])
        ph = ",".join(f":{k}" for k in row)
        c.execute(f"INSERT OR IGNORE INTO attempt({','.join(row)}) VALUES({ph})", row)
    return c.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]


def test_ingest_strict_rejects():
    for bad in ({"agent_id": "x", "command": "y", "typo": 1}, {"agent_id": "x"}):
        try:
            ingest.load_agent(bad); assert False, f"should reject {bad}"
        except ingest.IngestError:
            pass
    # missing base_commit / lang -> reject; and a str fail_to_pass is accepted
    try:
        ingest.load_task({"task_id": "P", "lang": "py"}); assert False
    except ingest.IngestError:
        pass
    assert ingest.load_task({"task_id": "P", "base_commit": "c", "lang": "py",
                             "fail_to_pass": "T"})["fail_to_pass"] == "T"


def test_ingest_all_real_files():
    """Strict-ingest every real corpus artifact -- skips cleanly on a fresh clone."""
    specs = [f for f in (ROOT / "zbench-tasks").glob("agents-*.jsonl") if "agents-meta" not in f.name]
    if specs:
        n = sum(len(ingest.load_agents(f)) for f in specs)
        assert n > 0
    else:
        print("  [skip] no agents-*.jsonl files present")

    metas = [ingest.load_task_file(f) for f in TASKS.glob("*/meta.json")] if TASKS.is_dir() else []
    if not metas:
        print("  [skip] empty task corpus (fresh clone) -- corpus ingest not exercised")
        return
    # `resolved`, when present, is a DATE string (not a bool) -- the corrected shape
    for m in metas:
        assert m.get("resolved") is None or isinstance(m["resolved"], str)
    # test_target resolves from whichever field a runnable task carries
    runnable = [m for m in metas if m.get("fail_to_pass_testfuncs") or m.get("fail_to_pass")]
    assert all(ingest.test_target(m) for m in runnable)
    # instance.jsonl (the RUN input) ingests strictly on every task that has one
    insts = [ingest.load_instance_file(f) for f in TASKS.glob("*/instance.jsonl")]
    for i in insts:
        assert i["instance_id"] == transform.task_of(i["instance_id"]) or \
            i["instance_id"].startswith(constants.INSTANCE_PREFIX)
        assert i["problem_statement"]


def test_schema_facts_only():
    """Dropped columns and dim tables stay gone (schema-level, no data needed)."""
    c = _fresh_db()
    acols = [x[1] for x in c.execute("PRAGMA table_info(attempt)").fetchall()]
    for dead in ("try_number", "phase", "bundle_dir"):
        assert dead not in acols, f"attempt still has {dead}"
    # total_tokens was originally dropped as "not cleanly derivable", then REINSTATED
    # 2026-08-15 as a required reporting metric with one canonical definition
    # (transform.canonical_total_tokens). It is a stored fact again, on purpose.
    assert "total_tokens" in acols, "attempt lost the canonical total_tokens column"
    tbls = {t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not (tbls & {"model", "harness_config"}), "dim tables still present"


def test_total_tokens_is_canonical_and_billed():
    """total_tokens == in+out+cache_read+cache_write (every component cost bills), and
    stays NULL -- not 0 -- when no usage was captured, so "never measured" and "genuinely
    zero" remain distinguishable."""
    row = transform.attempt_row({
        "run_id": "r", "agent_id": "a", "instance_id": "i", "tests_passed": True,
        "timestamp": "2026-01-01T00:00:00Z",
        "metrics": {"input_tokens": 100, "output_tokens": 50,
                    "cache_read_tokens": 20, "cache_write_tokens": 10}})
    assert row["total_tokens"] == 180, row.get("total_tokens")
    bare = transform.attempt_row({
        "run_id": "r", "agent_id": "a", "instance_id": "i2", "tests_passed": False,
        "timestamp": "2026-01-01T00:00:00Z", "metrics": {}})
    assert "total_tokens" not in bare, "no-usage attempt must leave total_tokens NULL"


def test_transform_and_identity_no_try():
    """(run_id, config_id, task_id) is a lossless identity -- proven on a synthetic fixture."""
    c = _fresh_db()
    inserted = _insert_attempts(c, _FIXTURE_ATTEMPTS)
    assert inserted == len(_FIXTURE_ATTEMPTS), \
        f"{inserted} != {len(_FIXTURE_ATTEMPTS)} -- identity collision without try_number!"
    # deterministic id: same identity -> same evaluation_id (UPSERT, not dup)
    dup = transform.attempt_row(_FIXTURE_ATTEMPTS[0])
    again = transform.attempt_row(dict(_FIXTURE_ATTEMPTS[0], tests_passed=False))
    assert dup["evaluation_id"] == again["evaluation_id"]
    # derived bundle_dir points at the preserved-id blob path
    assert transform.bundle_dir(dup["evaluation_id"]).startswith("blobs/attempt/")
    # task_id soft-ref is the bare task id
    assert dup["task_id"] == "T-1"


def test_identity_on_live_db_if_present():
    """Replay the full live DB through the transform -- only when bench.db exists."""
    if not DB.exists():
        print("  [skip] no live bench-db/bench.db (fresh clone)")
        return
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT run_id, config_id AS agent_id, task_id AS instance_id, tests_passed, "
        "status, outcome AS attempt_outcome, cost_usd, finished_at AS timestamp, "
        "input_tokens, output_tokens FROM attempt").fetchall()
    if not rows:
        print("  [skip] live DB has no attempts")
        return
    scores = []
    for r in rows:
        d = dict(r); d["metrics"] = {k: d.pop(k) for k in ("input_tokens", "output_tokens")}
        scores.append(d)
    c = _fresh_db()
    inserted = _insert_attempts(c, scores)
    assert inserted == len(rows), f"{inserted} != {len(rows)} -- try_number carried info!"


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"data-layer: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
