#!/usr/bin/env python3
"""W102/W108: reconcile per-attempt token counts with the durable session blob.

pi's per-message `message.usage = {input, output, cacheRead, cacheWrite, totalTokens,
cost}` is PER-TURN, not cumulative (verified: a turn's totalTokens == that turn's
input+output+cacheRead). So an attempt's TRUE totals are the SUM over assistant turns.
The old harness (and the original W102 backfill) stored only the LAST turn's snapshot,
which badly UNDERCOUNTS a multi-turn agentic run (observed 56-turn run: summed output
14125 vs last-turn 407, ~35x). W108 moved the harness + this tool to SUMMED semantics,
matching zbench-tasks/pi_session_tokens.summarize_session (one mapping, runtime==analyzer).

This reads each attempt's `*session*.jsonl` (in its derived blob bundle
`blobs/attempt/<evaluation_id>`) and writes the SUMMED input/output/cache fields plus
summed provider cost when the session has `usage.cost.total`. Two modes:
  * default        -- backfill only attempts with MISSING tokens (NULL/0) [W102].
  * --recompute-all -- also CORRECT stale non-null rows that still hold the old
                      last-turn snapshot [W108 migration]; writes only rows that change.
Idempotent; DRY-RUN by default (pass --apply to write; --apply backs up the DB first).
For Foundry/local sessions that have no provider cost, cost is recomputed from tokens via
models.dev at query time. For direct-pi/Anthropic sessions that do include provider cost,
write the summed cost too; otherwise stale pre-W108 rows keep only the last-turn cost and
make $/task look far too low. Only pi attempts have a `*session*.jsonl` (claude uses its
own accurate rawcli stream), so this is pi-scoped.

Usage:
  tools/backfill_tokens.py                       # dry-run, missing-only
  tools/backfill_tokens.py --apply               # write missing-only
  tools/backfill_tokens.py --recompute-all       # dry-run, incl. stale rows
  tools/backfill_tokens.py --recompute-all --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
DEF_DB = DOCS / "bench-db" / "bench.db"


def _sum_usage(session_path: Path):
    """SUM per-turn `message.usage` over the assistant turns -> the attempt totals (W108).
    pi usage is per-turn, so the true totals are the sum (NOT the last snapshot). Mirrors
    zbench-tasks/pi_session_tokens.summarize_session. Returns a usage-shaped dict
    {totalTokens, input, output, cacheRead, cacheWrite} or None if no usage-bearing turn."""
    agg = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0,
           "cost_usd": 0.0}
    saw = saw_cost = False
    with session_path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            m = d.get("message") if isinstance(d, dict) else None
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            u = m.get("usage") or {}
            if not u:
                continue
            saw = True
            agg["input"] += u.get("input") or 0
            agg["output"] += u.get("output") or 0
            agg["cacheRead"] += u.get("cacheRead") or 0
            agg["cacheWrite"] += u.get("cacheWrite") or 0
            agg["totalTokens"] += u.get("totalTokens") or 0
            cost = u.get("cost")
            if isinstance(cost, dict) and cost.get("total") is not None:
                agg["cost_usd"] += float(cost.get("total") or 0.0)
                saw_cost = True
    # "no real usage" if every field summed to 0 (some providers emit all-zero usage
    # entries, e.g. deepseek-v4-pro via Foundry) -- treat as unrecoverable, not a 0-write.
    token_sum = sum(agg[k] for k in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"))
    if not saw or not token_sum:
        return None
    if not saw_cost:
        agg.pop("cost_usd", None)
    return agg


def _session_for(db_root: Path, bundle_dir: str):
    if not bundle_dir:
        return None
    hits = sorted(glob.glob(str(db_root / bundle_dir / "*session*.jsonl")))
    return Path(hits[0]) if hits else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEF_DB))
    ap.add_argument("--apply", action="store_true", help="write updates (default: dry-run)")
    ap.add_argument("--recompute-all", action="store_true",
                    help="also correct stale non-null rows still holding the old last-turn "
                         "snapshot (W108 migration); default = missing-only backfill")
    args = ap.parse_args()

    db = Path(args.db)
    db_root = db.resolve().parent
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    if args.recompute_all:
        rows = conn.execute(
            "SELECT evaluation_id, config_id, task_id, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost_usd FROM attempt"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT evaluation_id, config_id, task_id, input_tokens, output_tokens, "
            "cache_read_tokens, cache_write_tokens, cost_usd FROM attempt "
            "WHERE COALESCE(input_tokens,0)+COALESCE(output_tokens,0)+COALESCE(cache_read_tokens,0)=0"
        ).fetchall()

    recoverable, no_session, no_usage, unchanged = [], 0, 0, 0
    for r in rows:
        bundle_dir = f"blobs/attempt/{r['evaluation_id']}"
        sp = _session_for(db_root, bundle_dir)
        if not sp:
            no_session += 1
            continue
        u = _sum_usage(sp)
        if not u:
            no_usage += 1
            continue
        # skip rows already equal to the summed totals (idempotent; -> quiet re-runs)
        same_tokens = (int(u.get("input") or 0) == int(r["input_tokens"] or 0)
                       and int(u.get("output") or 0) == int(r["output_tokens"] or 0)
                       and int(u.get("cacheRead") or 0) == int(r["cache_read_tokens"] or 0)
                       and int(u.get("cacheWrite") or 0) == int(r["cache_write_tokens"] or 0))
        same_cost = ("cost_usd" not in u or abs(float(u["cost_usd"] or 0.0) - float(r["cost_usd"] or 0.0)) < 1e-9)
        if same_tokens and same_cost:
            unchanged += 1
            continue
        recoverable.append((r, u))

    print(f"candidate attempts: {len(rows)}  (mode: {'recompute-all' if args.recompute_all else 'missing-only'})")
    print(f"  to write (summed != stored):     {len(recoverable)}")
    print(f"  already correct (unchanged):     {unchanged}")
    print(f"  session present, no usage:       {no_usage}")
    print(f"  no session blob:                 {no_session}")

    if not args.apply:
        print("\nDRY-RUN. Sample of what would be written (first 10):")
        for r, u in recoverable[:10]:
            print(f"  {r['config_id']:24} {r['task_id']:12} -> total={u.get('totalTokens')} "
                  f"in={u.get('input')} out={u.get('output')} "
                  f"cr={u.get('cacheRead')} cw={u.get('cacheWrite')} "
                  f"cost={u.get('cost_usd', 'n/a')}")
        print("\nRe-run with --apply to write.")
        return 0

    # back up the DB before mutating (single-store safety)
    import shutil
    from datetime import datetime, timezone
    bak = db.with_suffix(db.suffix + ".bak-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(db, bak)
    print(f"backed up DB -> {bak}")
    n = 0
    for r, u in recoverable:
        if "cost_usd" in u:
            conn.execute(
                "UPDATE attempt SET input_tokens=?, output_tokens=?, cache_read_tokens=?, "
                "cache_write_tokens=?, cost_usd=? WHERE evaluation_id=?",
                (int(u.get("input") or 0), int(u.get("output") or 0),
                 int(u.get("cacheRead") or 0), int(u.get("cacheWrite") or 0),
                 float(u.get("cost_usd") or 0.0), r["evaluation_id"]))
        else:
            conn.execute(
                "UPDATE attempt SET input_tokens=?, output_tokens=?, cache_read_tokens=?, "
                "cache_write_tokens=? WHERE evaluation_id=?",
                (int(u.get("input") or 0), int(u.get("output") or 0),
                 int(u.get("cacheRead") or 0), int(u.get("cacheWrite") or 0), r["evaluation_id"]))
        n += 1
    conn.commit()
    print(f"\nAPPLIED: backfilled {n} attempts from their session snapshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
