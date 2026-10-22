#!/usr/bin/env python3
"""Event-based wait for zbench grid cells to finish (encodes inotify).

We launch cells (run_coverage_matrix --fill / run_cell) as detached background
jobs, then need to know when they're DONE. Polling with sleeps is wasteful and
`tail --pid` only works for child PIDs; this waits on the FILESYSTEM signal
instead: each finished cell lands an `attempt` row in bench.db (the single
store). We block on inotify events on the bench-db dir (bench.db + its -wal) and
the `.runtime/live` lease dir, and wake the instant a cell lands (falling back to
light polling if `inotifywait` is unavailable).

A cell counts as DONE if the required number of `attempt` rows exists for (config_id, task_id)
in bench.db.

DEFAULT = wait for the NEXT cell completion (the nearest subproblem), then return and
report which cell landed + its outcome. This lets the caller wake early, act (e.g. re-fire a
cheap infra artifact), do other work, and re-wait -- instead of one long block over the whole
batch. Pass --all to block until the
ENTIRE target set finishes (e.g. a fill -> report recipe).

Usage:
  # DEFAULT: return as soon as the next agent finishes <instance>; prints the landed cell
  wait_for_cells.py --instance zbench_ZT-x --agents zbench-tasks/agents-matrix.jsonl
  # wait for EVERY agent to finish <instance> (whole set)
  wait_for_cells.py --instance zbench_ZT-x --agents zbench-tasks/agents-matrix.jsonl --all
  # explicit agent, require 3 valid attempt rows, custom timeout (future pass@k)
  wait_for_cells.py --instance zbench_ZT-x --agent-id pi-foundry-fable-5 --attempts 3 --timeout 3600
  # whole validated corpus x an agents file, block until the fill is fully done
  wait_for_cells.py --corpus --agents zbench-tasks/agents-matrix.jsonl --all

Exit code: 0 when the next cell completes (default) or all target cells are DONE (--all);
2 on timeout (with a summary of what's still missing); 1 on usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import sqlite3

HERE = Path(__file__).resolve().parent
ZBENCH_TASKS = HERE.parent / "zbench-tasks"
DEF_DB = Path(os.environ.get("ZBENCH_BENCHDB_DIR",
                             str(HERE.parent / "bench-db"))) / "bench.db"
sys.path.insert(0, str(HERE.parent))
from zbench import constants  # noqa: E402


def _load_agent_ids(agents_file: str | None, agent_ids: list[str]) -> list[str]:
    ids = list(agent_ids)
    if agents_file:
        for line in Path(agents_file).read_text().splitlines():
            line = line.strip()
            if line:
                ids.append(json.loads(line)["agent_id"])
    # de-dup, preserve order
    seen, out = set(), []
    for a in ids:
        if a not in seen:
            seen.add(a); out.append(a)
    return out


def _load_instances(instance: str | None, corpus: bool) -> list[str]:
    if instance:
        return [constants.instance_of(instance)]
    if corpus:
        sys.path.insert(0, str(ZBENCH_TASKS))
        import corpus
        return [constants.instance_of(r["task_id"]) for r in corpus.load_corpus("validated")]
    return []


def _landed_counts(db_path: Path) -> dict[tuple[str, str], int]:
    """(agent_id, instance_id) -> number of attempt rows in bench.db."""
    out: dict[tuple[str, str], int] = {}
    if not db_path.exists():
        return out
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        for cid, task_id, n in conn.execute("SELECT config_id, task_id, COUNT(*) FROM attempt GROUP BY config_id, task_id"):
            out[(str(cid), constants.instance_of(str(task_id)))] = int(n)
    finally:
        conn.close()
    return out


def _missing(db_path, targets, required_attempts):
    landed = _landed_counts(db_path)
    return [(i, a) for (i, a) in targets if landed.get((a, i), 0) < required_attempts]


def _done_set(db_path, targets, required_attempts):
    landed = _landed_counts(db_path)
    return {(i, a) for (i, a) in targets if landed.get((a, i), 0) >= required_attempts}


# Non-capability outcomes worth re-firing before the wave ends (see Anti-idle triage).
INFRA_STATUSES = {"worktree_error", "repo_setup_failed", "internal_error",
                  "provider_error", "timeout", "no_patch_generated"}


def _report_landed(db_path, cells):
    """Print each newly-landed cell with its outcome so the wake is actionable."""
    if not cells or not Path(db_path).exists():
        return
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        for (inst, aid) in sorted(cells):
            task_id = constants.task_of(inst)
            row = conn.execute(
                "SELECT tests_passed, status, outcome FROM attempt "
                "WHERE config_id=? AND task_id=? ORDER BY finished_at DESC LIMIT 1",
                (aid, task_id)).fetchone()
            tp, status, outcome = row if row else (None, "?", "?")
            verdict = "RESOLVED" if tp == 1 else "not-resolved"
            infra = " [infra-artifact: re-fireable]" if status in INFRA_STATUSES else ""
            print(f"  landed: {inst} x {aid} -> {verdict} (status={status}, outcome={outcome}){infra}")
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--instance", help="instance id (zbench_<task_id> or bare <task_id>)")
    ap.add_argument("--corpus", action="store_true", help="all validated corpus instances (via corpus)")
    ap.add_argument("--agents", help="agents jsonl (each line has agent_id)")
    ap.add_argument("--agent-id", action="append", default=[], help="explicit agent_id (repeatable)")
    ap.add_argument("--all", dest="all_cells", action="store_true",
                    help="wait for the ENTIRE target set to finish (default: return on the next cell completion)")
    ap.add_argument("--attempts", type=int, default=1, help="attempt rows per cell to require (default 1)")
    ap.add_argument("--db", default=str(DEF_DB), help="bench.db (the single store)")
    ap.add_argument("--timeout", type=int, default=7200, help="max seconds to wait (default 7200)")
    ap.add_argument("--interval", type=int, default=30, help="max seconds between re-checks (event OR this cap)")
    args = ap.parse_args()

    db_path = Path(args.db)
    runtime_dir = db_path.parent / ".runtime" / "live"

    instances = _load_instances(args.instance, args.corpus)
    agents = _load_agent_ids(args.agents, args.agent_id)
    if not instances or not agents:
        print("error: need (--instance or --corpus) AND (--agents or --agent-id)", file=sys.stderr)
        return 1
    targets = [(i, a) for i in instances for a in agents]
    total = len(targets)

    watch_dirs = [str(db_path.parent)]
    runtime_dir.mkdir(parents=True, exist_ok=True)
    watch_dirs.append(str(runtime_dir))
    have_inotify = shutil.which("inotifywait") is not None
    if not have_inotify:
        print("[wait_for_cells] inotifywait not found -> light polling fallback", file=sys.stderr)

    deadline = time.time() + args.timeout
    baseline_done = _done_set(db_path, targets, args.attempts)
    last_missing = None
    while True:
        done_set = _done_set(db_path, targets, args.attempts)
        done = len(done_set)
        missing_n = total - done
        newly = done_set - baseline_done
        if last_missing != missing_n:
            print(f"[{time.strftime('%H:%M:%S')}] {done}/{total} cells done"
                  + (f"; waiting on {missing_n}" if missing_n else " -- COMPLETE"))
            last_missing = missing_n
        if missing_n == 0:
            _report_landed(db_path, newly)
            return 0
        if not args.all_cells and newly:
            # DEFAULT: the nearest subproblem finished -> return so the caller can act.
            print(f"[{time.strftime('%H:%M:%S')}] next cell(s) completed ({len(newly)}); returning")
            _report_landed(db_path, newly)
            return 0
        remaining = deadline - time.time()
        if remaining <= 0:
            missing = _missing(db_path, targets, args.attempts)
            print(f"TIMEOUT after {args.timeout}s; still missing {len(missing)}:", file=sys.stderr)
            for (i, a) in missing[:40]:
                print(f"  {i} x {a}", file=sys.stderr)
            return 2
        # NB: floor at 1s. `inotifywait -t 0` means WAIT FOREVER (not 0s), which
        # would hang past the deadline on a quiet directory.
        wait = max(1, int(min(args.interval, remaining)))
        if have_inotify:
            # block until a write/create event in the watched dirs, or `wait` secs
            # (inotifywait exits rc!=0 on its own timeout -- fine, we re-check).
            subprocess.run(["inotifywait", "-q", "-e", "create,close_write,modify,moved_to",
                            "-t", str(wait), *watch_dirs],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            time.sleep(min(5, wait))


if __name__ == "__main__":
    sys.exit(main())
