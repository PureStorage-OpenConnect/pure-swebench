#!/usr/bin/env python3
"""job_status.py -- authoritative liveness for zbench pipeline jobs (W138).

WHY: a bare `pgrep -f "run_coverage_matrix.py --fill"` (and friends) has repeatedly
FALSE-POSITIVED on the agent's OWN shell command containing that string, so a job looked
ALIVE when it was long DONE -- burning us with wrong hand-off notes and a spare that sat
ungridded. This tool decides ALIVE / DONE / STALE from REAL evidence, never a substring
match against a shell command line:

  (a) PROCESSES: real python procs running `run_coverage_matrix` / `zbench.cells.run_cell`
      / `auto_prepare_task` / `oracle_validate`, read from /proc/<pid>/cmdline. We require
      argv[0] to be a python interpreter AND the marker to appear in the SCRIPT/MODULE args
      -- so a `/bin/bash -c '...run_coverage_matrix...'` (the pgrep trap) is NOT counted.
      The caller's own pid and its ancestor chain are excluded.
  (b) LEASES: live heartbeat files under bench-db/.runtime/live/<run>/*.json; a lease is
      FRESH if its heartbeat age <= ttl (900s), STALE if older (a killed run's zombie lease).
  (c) DB: the most-recent attempt.finished_at for the run in bench.db.
  (d) LOG: the --fill log's last-write age + launch/done tallies (best-effort, if given).

Verdict:
  ALIVE  -- >=1 matching process OR >=1 FRESH lease for the run.
  STALE  -- lease files exist but ALL are older than ttl AND no matching process (zombie).
  DONE   -- no matching process, no fresh lease (leases gone or none), work has landed.

Usage:
  tools/job_status.py                 # all pipeline jobs on this host
  tools/job_status.py <run-id>        # scope to one run (e.g. cov-20260808T191351Z-d3079c)
  tools/job_status.py <substr>        # scope to runs whose id contains <substr>
  tools/job_status.py --log <path>    # also fold in a --fill log's last-write + tallies
  tools/job_status.py --json          # machine-readable

Exit code: 0 if any job ALIVE, 1 if none alive (DONE/STALE/absent) -- so scripts can gate on it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH_ROOT = HERE.parent
sys.path.insert(0, str(BENCH_ROOT))
from zbench import constants  # noqa: E402

LIVE_DIR = BENCH_ROOT / "bench-db" / ".runtime" / "live"
CELLS_DIR = BENCH_ROOT / "bench-db" / ".runtime" / "cells"
DB_PATH = BENCH_ROOT / "bench-db" / "bench.db"
DEFAULT_TTL_S = 900
# A running cell's pi agent streams to session.jsonl (NOT the celllog, which is quiet during
# generation). If session.jsonl was written recently the cell is PROGRESSING even if slow
# (e.g. a slow local backend at minutes/turn). Only treat a cell as SILENT/suspect if its
# transcript has been idle much longer than this. DO NOT kill a PROGRESSING cell.
SESSION_SILENT_S = 1800  # 30 min of no transcript write = investigate before any kill

# Marker -> the ACTUAL python entrypoint (script path fragment or `-m module`) we look for
# in argv[1:]. Substring match against the joined script/module args only.
PROC_MARKERS = (
    "run_coverage_matrix",
    "zbench.cells.run_cell",
    "run_cell.py",
    "auto_prepare_task",
    "oracle_validate",
)


def _now() -> float:
    return time.time()


def _read_cmdline(pid: int) -> list[str]:
    try:
        raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except Exception:
        return []
    return [a.decode("utf-8", "replace") for a in raw.split(b"\x00") if a]


def _ppid(pid: int) -> int | None:
    try:
        for line in (Path("/proc") / str(pid) / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except Exception:
        return None
    return None


def _ancestors(pid: int) -> set[int]:
    """The caller's own pid + its full ancestor chain (so we never count ourselves)."""
    chain: set[int] = set()
    cur: int | None = pid
    for _ in range(64):
        if cur is None or cur in chain or cur <= 0:
            break
        chain.add(cur)
        cur = _ppid(cur)
    return chain


def _is_python(argv: list[str]) -> bool:
    if not argv:
        return False
    return os.path.basename(argv[0]).startswith("python")


def find_procs(run_filter: str | None) -> list[dict]:
    """Real python pipeline procs. Excludes the caller's own pid/ancestors and any process
    whose marker only appears in a NON-python (shell) command -- the pgrep false positive."""
    exclude = _ancestors(os.getpid())
    out: list[dict] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in exclude:
            continue
        argv = _read_cmdline(pid)
        if not _is_python(argv):
            continue  # <-- kills the `/bin/bash -c '...run_coverage_matrix...'` false positive
        script_args = " ".join(argv[1:])
        marker = next((m for m in PROC_MARKERS if m in script_args), None)
        if not marker:
            continue
        # extract --run-id / --agent-id if present (for scoping + lease<->proc correlation)
        m = re.search(r"--run-id[= ]([^\s]+)", script_args)
        rid = m.group(1) if m else None
        am = re.search(r"--agent-id[= ]([^\s]+)", script_args)
        aid = am.group(1) if am else None
        if run_filter and not (
            (rid and run_filter in rid) or (run_filter in script_args)
        ):
            continue
        out.append({"pid": pid, "marker": marker, "run_id": rid, "agent_id": aid,
                    "cmd": (argv[0] + " " + script_args)[:200]})
    return out


def _lease_age(payload: dict) -> float | None:
    ts = payload.get("heartbeat_at") or payload.get("started_at")
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def scan_leases(run_filter: str | None) -> dict[str, list[dict]]:
    """run_id -> list of {config_id, task_id, age_s, ttl_s, fresh}."""
    by_run: dict[str, list[dict]] = {}
    if not LIVE_DIR.is_dir():
        return by_run
    for run_dir in sorted(LIVE_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        rid = run_dir.name
        if run_filter and run_filter not in rid:
            continue
        leases = []
        for lf in sorted(run_dir.glob("*.json")):
            try:
                p = json.loads(lf.read_text() or "{}")
            except Exception:
                p = {}
            age = _lease_age(p)
            ttl = int(p.get("ttl_s", DEFAULT_TTL_S) or DEFAULT_TTL_S)
            sess_age, sess_lines = _session_progress(rid, p.get("config_id"), p.get("task_id"))
            leases.append({
                "config_id": p.get("config_id"),
                "task_id": p.get("task_id"),
                "phase": p.get("phase"),
                "age_s": age,
                "ttl_s": ttl,
                "fresh": (age is not None and age <= ttl),
                "session_age_s": sess_age,      # secs since the pi transcript last grew (None if none)
                "session_lines": sess_lines,
                # progressing = transcript grew recently -> the agent IS working (maybe slowly).
                "progressing": (sess_age is not None and sess_age <= SESSION_SILENT_S),
            })
        if leases:
            by_run[rid] = leases
    return by_run


def _session_progress(run_id: str, config_id: str | None, task_id: str | None):
    """Locate a running cell's pi session.jsonl and return (secs_since_last_write, n_lines).
    The pi agent streams turns here even while the celllog is silent, so this is the true
    'is the agent making progress' signal. Returns (None, None) if not found (e.g. claude
    cells, which use rawcli, or a cell that hasn't created a session yet)."""
    if not (config_id and task_id and CELLS_DIR.is_dir()):
        return (None, None)
    iid = constants.instance_of(str(task_id))
    best = None
    for d in CELLS_DIR.glob(f"{config_id}__{iid}__{run_id}__*"):
        sj = d / "session.jsonl"
        if sj.exists() and (best is None or sj.stat().st_mtime > best.stat().st_mtime):
            best = sj
    if best is None:
        return (None, None)
    try:
        age = _now() - best.stat().st_mtime
        n = sum(1 for _ in best.open(errors="replace"))
        return (round(age, 1), n)
    except Exception:
        return (None, None)


def db_last_finished(run_filter: str | None) -> dict[str, dict]:
    """run_id -> {last_finished_at, n_attempts} from bench.db."""
    out: dict[str, dict] = {}
    if not DB_PATH.exists():
        return out
    try:
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    except Exception:
        return out
    try:
        q = "SELECT run_id, COUNT(*) n, MAX(finished_at) last FROM attempt"
        args: tuple = ()
        if run_filter:
            q += " WHERE run_id LIKE ?"
            args = (f"%{run_filter}%",)
        q += " GROUP BY run_id"
        for rid, n, last in db.execute(q, args).fetchall():
            out[rid] = {"n_attempts": n, "last_finished_at": last}
    except Exception:
        pass
    finally:
        db.close()
    return out


def log_summary(log_path: Path) -> dict | None:
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text(errors="replace")
    except Exception:
        return None
    launches = len(re.findall(r"\[launch\]\s+\S+", text))
    dones = len(re.findall(r"\[done rc=", text))
    age = _now() - log_path.stat().st_mtime
    return {"path": str(log_path), "launches": launches, "dones": dones, "last_write_age_s": round(age, 1)}


def _fmt_age(s: float | None) -> str:
    if s is None:
        return "?"
    if s < 90:
        return f"{s:.0f}s"
    if s < 5400:
        return f"{s/60:.1f}m"
    return f"{s/3600:.1f}h"


def main() -> int:
    ap = argparse.ArgumentParser(description="Authoritative liveness for zbench pipeline jobs (W138).")
    ap.add_argument("run", nargs="?", default=None, help="run-id or substring to scope to")
    ap.add_argument("--log", default=None, help="a --fill log path to fold in (last-write + tallies)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--all", action="store_true", help="also list historical DONE runs from the DB (default: only live/lease-bearing runs)")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL_S, help=f"lease freshness bound (default {DEFAULT_TTL_S}s)")
    args = ap.parse_args()

    procs = find_procs(args.run)
    leases = scan_leases(args.run)
    dbinfo = db_last_finished(args.run)
    loginfo = log_summary(Path(args.log)) if args.log else None

    # Aggregate the set of run_ids to report. By default focus on liveness -- runs that have
    # a live lease or a matching process (plus DB context for those). Enumerating ALL
    # historical DB runs is opt-in (--all) or when a specific run filter is given.
    live_run_ids: set[str] = set(leases)
    for p in procs:
        if p.get("run_id"):
            live_run_ids.add(p["run_id"])
    if args.all or args.run:
        run_ids: set[str] = live_run_ids | set(dbinfo)
    else:
        run_ids = live_run_ids

    # Procs whose run-id we couldn't attribute to a known run (e.g. the orchestrator itself,
    # or an auto_prepare_task that carries no --run-id) still prove liveness -- bucket them
    # under a synthetic "(no run-id)" entry so they are never silently dropped.
    attributed = set(run_ids)
    unattributed = [p for p in procs if p.get("run_id") not in attributed]
    ordered_runs: list = sorted(run_ids)
    if unattributed:
        ordered_runs.append(None)

    any_alive = False
    report: list[dict] = []
    for rid in ordered_runs:
        rprocs = unattributed if rid is None else [p for p in procs if p.get("run_id") == rid]
        rleases = leases.get(rid, []) if rid else []
        # A cell blocked WAITING for a slot does not heartbeat (run_cell starts the heartbeat
        # loop only after slots are acquired), so its lease looks old though the process is
        # alive. Correlate lease.config_id to a live run_cell --agent-id for this run: a lease
        # backed by a live proc is WAITING (alive), not a STALE zombie.
        live_agents = {p.get("agent_id") for p in rprocs if p.get("agent_id")}
        for l in rleases:
            if l["fresh"]:
                l["state"] = "FRESH"
            elif l.get("config_id") in live_agents:
                l["state"] = "WAITING"  # alive, blocked on a slot; heartbeat not yet started
            else:
                l["state"] = "STALE"    # old heartbeat AND no live proc -> zombie
        fresh = [l for l in rleases if l["state"] == "FRESH"]
        waiting = [l for l in rleases if l["state"] == "WAITING"]
        stale = [l for l in rleases if l["state"] == "STALE"]
        alive = bool(rprocs) or bool(fresh) or bool(waiting)
        if alive:
            verdict = "ALIVE"
        elif stale and not rprocs:
            verdict = "STALE"
        else:
            verdict = "DONE"
        any_alive = any_alive or alive
        report.append({
            "run_id": rid, "verdict": verdict,
            "n_procs": len(rprocs), "n_fresh_leases": len(fresh),
            "n_waiting_leases": len(waiting), "n_stale_leases": len(stale),
            "db": dbinfo.get(rid),
            "procs": rprocs, "leases": rleases,
        })

    if args.json:
        print(json.dumps({"any_alive": any_alive, "runs": report, "log": loginfo}, indent=2, default=str))
        return 0 if any_alive else 1

    if not report and not procs:
        print("No pipeline jobs found (no matching python procs, no live leases).")
        if loginfo:
            print(f"  log: {loginfo['path']} last-write {_fmt_age(loginfo['last_write_age_s'])} ago; "
                  f"launches={loginfo['launches']} dones={loginfo['dones']}")
        return 1

    for r in report:
        rid = r["run_id"] or "(no run-id)"
        print(f"[{r['verdict']}] {rid}")
        print(f"    procs={r['n_procs']}  fresh_leases={r['n_fresh_leases']}  "
              f"waiting_leases={r['n_waiting_leases']}  stale_leases={r['n_stale_leases']}")
        for p in r["procs"]:
            print(f"      proc pid={p['pid']} {p['marker']} :: {p['cmd']}")
        for l in r["leases"]:
            prog = ""
            if l.get("session_age_s") is not None:
                tag = "PROGRESSING" if l.get("progressing") else "SILENT(investigate,do NOT kill blindly)"
                prog = f" | transcript {tag}: {l['session_lines']} turns, last write {_fmt_age(l['session_age_s'])} ago"
            print(f"      lease {l['state']} {l['config_id']} x {l['task_id']} phase={l['phase']} "
                  f"age={_fmt_age(l['age_s'])} (ttl {l['ttl_s']}s){prog}")
        if r["db"]:
            print(f"      db: {r['db']['n_attempts']} attempts, last_finished_at={r['db']['last_finished_at']}")
        if r["verdict"] == "STALE":
            print(f"      -> zombie lease(s); no live process. Safe to `rm -rf {LIVE_DIR}/{rid}` "
                  f"(only if truly no process for this run).")
    if loginfo:
        print(f"  log: {loginfo['path']} last-write {_fmt_age(loginfo['last_write_age_s'])} ago; "
              f"launches={loginfo['launches']} dones={loginfo['dones']}")

    print(f"\nany_alive={any_alive}")
    return 0 if any_alive else 1


if __name__ == "__main__":
    sys.exit(main())
