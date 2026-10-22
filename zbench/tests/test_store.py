#!/usr/bin/env python3
"""zbench store tests (writer + Lease + reap). Scratch DB, no pb needed.
Run: python3 zbench/tests/test_store.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from zbench import constants  # noqa: E402

SCORE = {
    "run_id": "r1", "agent_id": "pi-foundry-opus-4-8", "instance_id": "zbench_ZT-1",
    "tests_passed": True, "status": "resolved", "attempt_outcome": "resolved",
    "cost_usd": 0.5, "timestamp": "2026-08-04T00:00:00Z",
    "metrics": {"runtime_ms": 1000, "input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 9},
}


def _fresh():
    os.environ["ZBENCH_BENCHDB_DIR"] = tempfile.mkdtemp()
    from zbench import store  # imported AFTER the env override
    return store


def test_write_idempotent_and_lean():
    store = _fresh()
    s = store.Store()
    ev = s.record_attempt(SCORE)
    r = s.conn.execute("SELECT tests_passed, status, cost_usd, input_tokens FROM attempt "
                       "WHERE evaluation_id=?", (ev,)).fetchone()
    assert r == (1, "resolved", 0.5, 100)
    # re-record same identity -> same id, one row (ON CONFLICT update)
    assert s.record_attempt(SCORE) == ev
    assert s.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 1
    assert s.attempt_exists("pi-foundry-opus-4-8", "ZT-1")
    assert not s.attempt_exists("pi-foundry-opus-4-8", "ZT-999")


def test_lease_lifecycle_evidence_and_provenance():
    store = _fresh()
    from zbench import transform
    s = store.Store()
    lease = store.Lease("r1", "a", "ZT-1").open("running")
    assert lease.path.exists()
    prov = {
        "captured_at": "2026-08-06T00:00:00Z",
        "harness": {"name": "zbench", "git": {"commit": "abc", "branch": "main", "dirty": False},
                    "python_version": "py", "platform": "plat"},
        "agent": {"command": "python3 -m zbench.agents.pi_agent",
                  "cli": {"name": "pi", "version_probe": {"ok": True, "stdout": "0.81.1"}}},
    }
    ev = s.record_attempt(SCORE, evidence={"verify_log_text": "PASS", "patch_text": "d"},
                          lease=lease, provenance_data=prov)
    assert not lease.path.exists()                      # closed on record
    bp = Path(s.dir) / transform.bundle_dir(ev)         # derived, not stored
    assert (bp / "pb-verify.log").exists() and (bp / "patch.diff").exists()
    assert json.loads((bp / "provenance.json").read_text())["harness"]["name"] == "zbench"
    row = s.conn.execute("SELECT harness_name, harness_git_commit, agent_cli_name, agent_cli_version "
                         "FROM attempt_provenance WHERE evaluation_id=?", (ev,)).fetchone()
    assert row == ("zbench", "abc", "pi", "0.81.1")


def test_reap_stale():
    store = _fresh()
    s = store.Store()
    stale = store.Lease("r2", "a", "ZT-2").open("x")
    p = json.loads(stale.path.read_text()); p["heartbeat_at"] = "2020-01-01T00:00:00+00:00"
    stale.path.write_text(json.dumps(p))
    assert len(store.reap_stale_leases(live_cell_keys=set())) == 1
    # a live slot protects its lease from reaping
    live = store.Lease("r3", "a", "ZT-3").open("x")
    p = json.loads(live.path.read_text()); p["heartbeat_at"] = "2020-01-01T00:00:00+00:00"
    live.path.write_text(json.dumps(p))
    assert store.reap_stale_leases(live_cell_keys={constants.cell_key("ZT-3", "a")}) == []


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"store: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
