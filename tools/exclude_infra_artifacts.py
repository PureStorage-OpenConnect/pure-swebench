#!/usr/bin/env python3
"""Sweep + EXCLUDE provider/infra artifacts (esp. 429 rate-limit) from scoring.

Why this exists (W56): the cloud open-weight gateway (Fireworks/AI-Foundry) 429s
even a single agent (Foundry per-model TPM/RPM caps). A 429 shows up two
ways, and BOTH must be excluded or they silently count as a capability 0:
  1. TERMINAL 429 -- the last assistant event is stopReason=error with a 429 body.
  2. STALL/TIMEOUT -- a 429 storm leaves pi hung; the agent goes silent and only
     dies at ZBENCH_AGENT_TIMEOUT. The last logged event is a normal toolUse, so the
     naive terminal-error rule MISSES it. We flag no_patch/incomplete that has >=1
     429 AND (near-timeout duration OR a large silent gap between the last session
     event and finished_at).

`validate_runs.py` DETECTS these as [artifact:infra] NOTES but by W39 design does
NOT touch scoring; this tool converts the machine judgement into real run_exclusion
rows (row exists => excluded from scoring AND re-runnable via --fill). Idempotent.

Usage:
  python3 tools/exclude_infra_artifacts.py [--agent <config_id> ...] [--dry-run]
  (no --agent => all agents)
"""
import argparse, datetime, glob, json, os, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "zbench-tasks"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import exclusions  # DEDUP_REVIEW D1: shared reason builders
import scoring as S  # SINGLE-HOME failure-mode detector (classify_attempt); do NOT re-implement
from zbench import constants

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "bench-db" / "bench.db"
BLOBS = HERE.parent / "bench-db" / "blobs" / "attempt"   # per-attempt evidence bundles
TIMEOUT_MS = int(os.environ.get("ZBENCH_AGENT_TIMEOUT_MS", "4800000"))  # fireworks cells
STALL_GAP_SEC = 300      # >5 min silent gap after last event = a stall
NEAR_TIMEOUT = 0.95      # duration >= 95% of the agent timeout = a timeout kill
STORM_429 = 8            # >=8 rate-limit error-turns = a 429 STORM that degraded the run even if it
                         # didn't end terminal-429 or stall (mid-run storm -> the model burns turns/
                         # context fighting 429s and limps to a length/give-up end). Well above the
                         # 1-2 transient 429s pi's backoff absorbs cleanly.


def _parse(ts):
    if not ts:
        return None
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _session_facts(eid):
    """Return (n429, ended_terminal_error, last_ts) from the attempt's bundle session log
    (bench-db/blobs/attempt/<eid>/session.jsonl)."""
    f = BLOBS / eid / "session.jsonl"
    if not f.is_file():
        return 0, False, None
    evs = [json.loads(l) for l in open(f)]
    asst = [e for e in evs if e.get("message", {}).get("role") == "assistant"]
    n429 = sum(1 for e in asst if "429" in (e["message"].get("errorMessage") or ""))
    term = bool(asst) and asst[-1]["message"].get("stopReason") == "error"
    ets = [t for t in (_parse(e.get("timestamp")) for e in evs) if t]
    return n429, term, (ets[-1] if ets else None)


def sweep(conn, agents, dry):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.row_factory = sqlite3.Row
    q = ("select a.evaluation_id, a.config_id, a.task_id, a.run_id, a.status, a.outcome, "
         "a.tests_passed, a.runtime_ms, a.total_duration_ms, a.output_tokens, a.finished_at "
         "from attempt a where a.status in ('no_patch_generated','provider_error','error','incomplete') "
         "and not exists(select 1 from run_exclusion x where x.evaluation_id=a.evaluation_id)")
    rows = conn.execute(q).fetchall()
    excl = 0
    for r in rows:
        eid, cid, task_id = r["evaluation_id"], r["config_id"], r["task_id"]
        if agents and cid not in agents:
            continue
        reasons = []
        # (A) SINGLE-HOME fact-based classification (scoring.classify_attempt). Catches
        #     artifact:auth (dead OAuth: tiny runtime + no output) / artifact:infra WITHOUT a
        #     parallel heuristic here -- this is the fix for the auth gap + no duplicate detector.
        #     budget_s=None disables artifact:budget (needs the real per-cell budget -- future).
        cls = S.classify_attempt(r, None)
        if S.is_artifact_class(cls):
            reasons.append(cls)
        # (B) transcript-aware 429-stall the fact-only classifier CANNOT see (a 429 storm that
        #     leaves pi silent looks like a mid-budget give-up).
        n429, term, last = _session_facts(eid)
        gap = None
        finp = _parse(r["finished_at"])
        if last and finp:
            gap = (finp - last).total_seconds()
        if term and n429:
            reasons.append("terminal-429")
        elif n429 and gap is not None and gap > STALL_GAP_SEC:
            reasons.append(f"stall-gap={int(gap)}s;429x{n429}")
        elif n429 >= STORM_429:
            reasons.append(f"429-storm;429x{n429}")
        dur = r["total_duration_ms"]
        if dur and dur >= TIMEOUT_MS * NEAR_TIMEOUT and not any("timeout" in x for x in reasons):
            reasons.append(f"timeout~{int(dur/1000)}s")
        if not reasons:
            continue
        rs = ";".join(reasons)
        print(f"  {'[dry] ' if dry else ''}EXCLUDE {cid} {task_id} ({r['status']}) :: {rs}")
        if not dry:
            conn.execute(
                "INSERT INTO run_exclusion(evaluation_id,reason,decided_by,decided_at) VALUES(?,?,?,?)",
                # D1: reason reflects the ACTUALLY-DETECTED class/signature (rs).
                (eid, exclusions.infra(rs), constants.operator(), now))
            excl += 1
    if not dry:
        conn.commit()
    print(f"{'[dry] would exclude' if dry else 'excluded'}: "
          f"{sum(1 for _ in [r for r in rows]) if False else excl if not dry else '(dry)'}")
    return excl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", action="append", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args()
    conn = sqlite3.connect(a.db)
    try:
        n = sweep(conn, set(a.agent) if a.agent else None, a.dry_run)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
