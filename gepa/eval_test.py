#!/usr/bin/env python3
"""Held-out evaluation of a finished GEPA run.

Runs the seed prompt (empty append = baseline config) and GEPA's best prompt on the
"test" tasks of gepa/tasks.json, both fresh in the GEPA store, and writes
gepa/runs/<agent>/test_eval.json. The seed is re-run (not taken from the main board)
so both arms share the same serving stack, date, and runner; the board baseline is
added for reference.

Usage: python3 gepa/eval_test.py --agent pi-openai-gpt-5.6-luna
"""
import argparse
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rollout_runner import run_rollouts  # noqa: E402

MAIN_DB = "/mnt/data/robert-scripts/purebench/bench-db/bench.db"


def board_baseline(agent: str, tasks: list[str]) -> dict:
    db = sqlite3.connect(f"file:{MAIN_DB}?mode=ro", uri=True)
    rows = db.execute(
        f"select task_id, max(tests_passed) from attempt where config_id=? and task_id in "
        f"({','.join('?' * len(tasks))}) and evaluation_id not in "
        f"(select evaluation_id from run_exclusion) group by task_id", [agent, *tasks]).fetchall()
    return dict(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    args = ap.parse_args()
    run_dir = HERE / "runs" / args.agent
    best = json.load(open(run_dir / "summary.json"))["best_prompt"]
    test = json.load(open(HERE / "tasks.json"))["test"]

    arms = {"seed": "", "gepa_best": best}
    with ThreadPoolExecutor(len(arms)) as ex:
        futs = {k: ex.submit(run_rollouts, args.agent, p, test, f"gepa-test-{args.agent}")
                for k, p in arms.items()}
        res = {k: f.result() for k, f in futs.items()}

    out = {"agent": args.agent, "tasks": test, "board_baseline": board_baseline(args.agent, test)}
    for k, rows in res.items():
        out[k] = {r["task_id"]: {f: r.get(f) for f in ("resolved", "outcome", "infra_failure",
                                                        "cost_usd", "turns", "evaluation_id")}
                  for r in rows}
    for k in ("seed", "gepa_best"):
        valid = [v for v in out[k].values() if not v["infra_failure"]]
        out[f"{k}_resolved"] = f"{sum(v['resolved'] for v in valid)}/{len(valid)}"
    out["board_baseline_resolved"] = f"{sum(out['board_baseline'].values())}/{len(out['board_baseline'])}"
    json.dump(out, open(run_dir / "test_eval.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k.endswith("_resolved")}))


if __name__ == "__main__":
    main()
