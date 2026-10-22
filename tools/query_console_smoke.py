#!/usr/bin/env python3
"""Query-console regression smoke checks (no browser needed).

Imports query_console, exercises the in-process query path, and asserts the
read-only invariants that must never regress:
  * the convenience views load and the agent/task joins populate,
  * every built-in saved query runs,
  * write / multi-statement / ATTACH / PRAGMA-write queries are refused,
  * a refused write does NOT change the attempt row count.

Optionally also smokes a running server with --base-url http://127.0.0.1:8789.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import query_console as qc  # noqa: E402


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def direct_checks() -> list[str]:
    out: list[str] = []

    # 1. views load + joins populate (model_name comes from the agent dim).
    n0 = qc._run_query("SELECT COUNT(*) AS n FROM attempt")["rows"][0][0]
    check(isinstance(n0, int) and n0 > 0, "attempt count not positive")
    joined = qc._run_query(
        "SELECT COUNT(*) FROM v_attempt WHERE model_name IS NOT NULL")["rows"][0][0]
    check(joined > 0, "agent join produced no model_name rows (wrong tasks dir?)")
    check("scored" in qc._run_query("SELECT * FROM v_attempt LIMIT 1")["columns"],
          "v_attempt is missing the 'scored' flag")

    # 2. every built-in query runs without error.
    for q in qc.DEFAULT_QUERIES:
        r = qc._run_query(q["sql"])
        check("error" not in r, f"built-in query failed: {q['name']}: {r.get('error')}")
    out.append(f"direct: {len(qc.DEFAULT_QUERIES)} built-in queries ok, {joined} joined rows")

    # 3. writes / multi-statement / ATTACH / PRAGMA-write are refused.
    for bad in ("DELETE FROM attempt",
                "UPDATE attempt SET cost_usd=0",
                "SELECT 1; DROP TABLE run",
                "ATTACH DATABASE 'x' AS y",
                "PRAGMA journal_mode=WAL",
                "CREATE TABLE t(x)"):
        check("error" in qc._run_query(bad), f"dangerous query was NOT refused: {bad}")

    # 4. a refused write did not change the row count.
    n1 = qc._run_query("SELECT COUNT(*) AS n FROM attempt")["rows"][0][0]
    check(n0 == n1, f"attempt count changed after write attempts ({n0} -> {n1})")
    out.append("direct: read-only guard holds (count unchanged)")

    # 5. data dictionary renders + every live column is documented (no drift).
    check("<title>bench.db data dictionary</title>" in qc._dict_page(), "dict page did not render")
    conn = qc._open()
    try:
        for name, doc in qc.TABLE_DOCS.items():
            live = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
            check(bool(live), f"documented table missing from db: {name}")
            undocumented = [c for c in live if c not in doc["columns"]]
            stale = [c for c in doc["columns"] if c not in live]
            check(not undocumented, f"{name}: columns need a description: {undocumented}")
            check(not stale, f"{name}: docs describe non-existent columns: {stale}")
    finally:
        conn.close()
    out.append(f"direct: data dictionary covers {len(qc.TABLE_DOCS)} tables, no column drift")
    return out


def fetch(base: str, path: str, body: dict | None = None) -> dict:
    url = base.rstrip("/") + path
    if body is None:
        req = urllib.request.Request(url)
    else:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def live_checks(base: str) -> list[str]:
    schema = fetch(base, "/api/schema")
    check(any(t["name"] == "v_attempt" for t in schema), "live: v_attempt missing from schema")
    saved = fetch(base, "/api/saved")
    check(len(saved.get("builtin", [])) == len(qc.DEFAULT_QUERIES), "live: builtin count mismatch")
    q = fetch(base, "/api/query", {"sql": "SELECT COUNT(*) FROM attempt"})
    check(q.get("rows") and q["rows"][0][0] > 0, "live: count query empty")
    bad = fetch(base, "/api/query", {"sql": "DELETE FROM attempt"})
    check("error" in bad, "live: write not refused")
    with urllib.request.urlopen(base.rstrip("/") + "/schema", timeout=10) as r:
        page = r.read().decode()
    check("data dictionary" in page and 'href="/"' in page, "live: /schema page broken")
    return [f"live ok ({base})"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="also smoke a running server, e.g. http://127.0.0.1:8789")
    args = ap.parse_args()
    messages = direct_checks()
    if args.base_url:
        messages.extend(live_checks(args.base_url))
    for msg in messages:
        print(msg)
    print("query_console smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
