#!/usr/bin/env python3
"""Held-out evaluation for the retry-with-feedback GEPA runs (gepa_run_retry.py).

Arms: seed (empty prompt), accuracy (runs-retry/<agent> best), cost (runs-retry-cost/<agent>
best); each arm runs every test task --samples times, up to 3 feedback rounds per run.
Per run we read the per-round verdicts (attempts.json), so one run gives both
  resolve@1  = solved in round 1 (the standard one-shot benchmark), and
  resolve@3  = solved in any round (the retry setting).
Cost = all rounds (tiered per request for Haiku 5.5 on pi; else the reported cost).
Comparisons: paired sign-flip test on per-task means; cost = geometric mean of per-task
cost ratios with a bootstrap 95% CI over tasks.
Writes gepa/runs-retry/<agent>/test_eval.json.

Usage: gepa/.venv/bin/python gepa/eval_test_retry.py --agent pi-anthropic-haiku-5-5-retry3
"""
import argparse
import json
import math
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from eval_test_v2 import sign_flip_p  # noqa: E402
from gepa_run_retry import gepa_run_cost  # noqa: E402  (also registers the retry tier)
from rollout_runner import STORE, run_rollouts  # noqa: E402


def rounds_of(evaluation_id) -> list[dict]:
    p = STORE / "blobs" / "attempt" / str(evaluation_id) / "attempts.json"
    try:
        return json.loads(p.read_text())["rounds"]
    except Exception:
        return []


def geo_ratio_ci(pairs, n_boot=10_000, seed=0):
    """pairs = [(a, b)] per task -> geometric mean of a/b and a bootstrap 95% CI over tasks."""
    logs = [math.log(a / b) for a, b in pairs if a and b]
    if not logs:
        return None, None, None
    rng = random.Random(seed)
    boots = sorted(sum(rng.choice(logs) for _ in logs) / len(logs) for _ in range(n_boot))
    return (math.exp(sum(logs) / len(logs)), math.exp(boots[int(0.025 * n_boot)]),
            math.exp(boots[int(0.975 * n_boot)]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--arms", default="seed,accuracy,cost", help="subset of seed,accuracy,cost")
    args = ap.parse_args()
    out_dir = HERE / "runs-retry" / args.agent
    out_dir.mkdir(parents=True, exist_ok=True)
    test = json.load(open(HERE / "tasks.json"))["test"]
    src = {"seed": None, "accuracy": HERE / "runs-retry" / args.agent,
           "cost": HERE / "runs-retry-cost" / args.agent}
    arms = {}
    for a in args.arms.split(","):
        arms[a] = "" if src[a] is None else json.load(open(src[a] / "summary.json"))["best_prompt"]

    jobs = [(a, k) for a in arms for k in range(1, args.samples + 1)]
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {j: ex.submit(run_rollouts, args.agent, arms[j[0]], test, f"gepa-retry-test-{args.agent}",
                             include_trace=False, sample=j[1],
                             fanout=int(os.environ.get("GEPA_FANOUT") or 0) or None) for j in jobs}
        res = {j: f.result() for j, f in futs.items()}

    out = {"agent": args.agent, "tasks": test, "samples": args.samples, "arms": {}, "comparisons": {}}
    per = {}     # arm -> task -> {"r1": [..], "r3": [..], "cost": [..], "rounds": [..]}
    for a in arms:
        per[a] = {t: {"r1": [], "r3": [], "cost": [], "rounds": []} for t in test}
        cells = {t: [] for t in test}
        for k in range(1, args.samples + 1):
            for r in res[(a, k)]:
                rd = rounds_of(r["evaluation_id"]) if r.get("evaluation_id") else []
                cost = gepa_run_cost.session_cost(args.agent, r.get("evaluation_id"), r.get("cost_usd"))
                c = {"resolved": r["resolved"], "status": r["status"], "infra_failure": r["infra_failure"],
                     "evaluation_id": r.get("evaluation_id"), "cost": cost, "turns": r.get("turns"),
                     "rounds": [x.get("status") if not x.get("resolved") else "RESOLVED" for x in rd]}
                cells[r["task_id"]].append(c)
                if r["infra_failure"]:
                    continue
                d = per[a][r["task_id"]]
                d["r3"].append(r["resolved"])
                d["r1"].append(int(bool(rd and rd[0].get("resolved"))) if rd else r["resolved"])
                d["rounds"].append(len(rd) or 1)
                if cost is not None:
                    d["cost"].append(cost)
        n = sum(len(v["r3"]) for v in per[a].values())

        def rate(key):
            return round(sum(sum(v[key]) for v in per[a].values()) / n, 4) if n else None
        out["arms"][a] = {"cells": cells, "n_runs": n, "resolve@1": rate("r1"), "resolve@3": rate("r3"),
                          "mean_rounds": round(sum(sum(v["rounds"]) for v in per[a].values()) / n, 3) if n else None,
                          "mean_cost_per_run": round(sum(sum(v["cost"]) for v in per[a].values()) /
                                                     max(1, sum(len(v["cost"]) for v in per[a].values())), 4),
                          "prompt_words": len(arms[a].split())}

    def tmean(a, t, key):
        v = per[a][t][key]
        return sum(v) / len(v) if v else None

    for a in arms:      # within-arm: what the retries add
        d = [tmean(a, t, "r3") - tmean(a, t, "r1") for t in test if tmean(a, t, "r3") is not None]
        out["comparisons"][f"{a}: resolve@3 - resolve@1"] = {"mean_diff": round(sum(d) / len(d), 4), "n_tasks": len(d)}
    for a in [x for x in arms if x != "seed"]:
        if "seed" not in arms:
            break
        for key in ("r3", "r1"):
            d = [tmean(a, t, key) - tmean("seed", t, key) for t in test
                 if tmean(a, t, key) is not None and tmean("seed", t, key) is not None]
            out["comparisons"][f"{a} - seed ({'resolve@3' if key == 'r3' else 'resolve@1'})"] = {
                "mean_diff": round(sum(d) / len(d), 4), "n_tasks": len(d),
                "tasks_up": sum(x > 0 for x in d), "tasks_down": sum(x < 0 for x in d),
                "p_sign_flip": round(sign_flip_p(d), 4)}
        pairs = [(tmean(a, t, "cost"), tmean("seed", t, "cost")) for t in test]
        g, lo, hi = geo_ratio_ci([p for p in pairs if None not in p])
        out["comparisons"][f"{a} / seed cost ratio"] = {"geo_mean": g and round(g, 3), "ci95": [lo and round(lo, 3), hi and round(hi, 3)]}
    json.dump(out, open(out_dir / "test_eval.json", "w"), indent=1)
    print(json.dumps({a: {k: v for k, v in out["arms"][a].items() if k != "cells"} for a in arms}, indent=1))
    print(json.dumps(out["comparisons"], indent=1))


if __name__ == "__main__":
    main()
