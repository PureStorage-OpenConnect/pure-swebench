#!/usr/bin/env python3
"""Hard-task tracker: list validated tasks that NO model or only 1-2 models resolve.

Such a task is a curation-review candidate. Like ZT-5e51b7d33cfd (held 2026-08-17),
"every strong model fails identically" often means the task is ill-defined in its
folder (brief missing an interface requirement, or scope too broad for one pass) and
needs more scaffolding -- not that the models are weak.

A resolve = an attempt with tests_passed=1. Coverage/attempt counting uses the LATEST
attempt per (task, agent). Control harnesses (control-*) are excluded. provider_error
is infra and is NOT counted as a real attempt (it would understate difficulty).

Usage:
  python3 tools/hard_tasks.py                 # default: <=2 resolvers, >=6 real attempts
  python3 tools/hard_tasks.py --max-resolvers 0   # only the "nobody solves it" tasks
  python3 tools/hard_tasks.py --min-attempts 4 --md > zbench-tasks/HARD_TASKS.md
"""
import argparse, json, sqlite3, sys
from pathlib import Path

INFRA_STATUS = {"provider_error", "timeout", "stalled", "auth_error"}
ROOT = Path(__file__).resolve().parent.parent


def meta_for(task_id):
    p = ROOT / "zbench-tasks" / "tasks" / task_id / "meta.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "bench-db" / "bench.db"))
    ap.add_argument("--max-resolvers", type=int, default=2,
                    help="flag tasks with at most this many distinct resolving agents")
    ap.add_argument("--min-attempts", type=int, default=6,
                    help="require at least this many real (non-infra) agent attempts for signal")
    ap.add_argument("--md", action="store_true", help="emit a Markdown table")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT task_id, config_id, tests_passed, status, finished_at "
        "FROM attempt WHERE config_id NOT LIKE 'control%' ORDER BY finished_at"
    ).fetchall()

    # latest attempt per (task, agent)
    latest = {}
    for r in rows:
        latest[(r["task_id"], r["config_id"])] = r

    per_task = {}
    for (task, agent), r in latest.items():
        d = per_task.setdefault(task, {"real": set(), "resolvers": set(), "infra": set(), "nopatch": set()})
        if r["status"] in INFRA_STATUS:
            d["infra"].add(agent)
            continue
        d["real"].add(agent)
        if r["tests_passed"]:
            d["resolvers"].add(agent)
        if r["status"] == "no_patch_generated":
            d["nopatch"].add(agent)

    flagged = []
    for task, d in per_task.items():
        na, nr = len(d["real"]), len(d["resolvers"])
        if na >= args.min_attempts and nr <= args.max_resolvers:
            m = meta_for(task)
            flagged.append({
                "task": task, "lang": m.get("lang", "?"),
                "resolvers": nr, "attempts": na,
                "nopatch": len(d["nopatch"]), "infra": len(d["infra"]),
                "status": m.get("curation_status", "?"),
                "summary": (m.get("summary", "") or "")[:64],
            })
    flagged.sort(key=lambda x: (x["resolvers"], -x["attempts"], x["task"]))

    if args.md:
        print("# Hard-task review queue\n")
        print(f"Tasks with <= {args.max_resolvers} resolving models out of >= {args.min_attempts} "
              "real attempts. Review the task folder for scope/brief problems.\n")
        print("| task | lang | resolve | no_patch | infra | curation | summary |")
        print("|---|---|---|---|---|---|---|")
        for f in flagged:
            print(f"| {f['task']} | {f['lang']} | {f['resolvers']}/{f['attempts']} | "
                  f"{f['nopatch']} | {f['infra']} | {f['status']} | {f['summary']} |")
    else:
        print(f"HARD-TASK REVIEW QUEUE  (<= {args.max_resolvers} resolvers, >= {args.min_attempts} real attempts)")
        print(f"{'task':16} {'L':3} {'resolve':8} {'nopatch':7} {'infra':5} {'curation':10} summary")
        for f in flagged:
            print(f"{f['task']:16} {f['lang']:3} {str(f['resolvers'])+'/'+str(f['attempts']):8} "
                  f"{f['nopatch']:<7} {f['infra']:<5} {f['status']:10} {f['summary']}")
        print(f"\n{len(flagged)} task(s) flagged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
