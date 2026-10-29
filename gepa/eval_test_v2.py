#!/usr/bin/env python3
"""Held-out evaluation for GEPA v2: seed vs v1 best vs v2 best, `--samples` runs per task.

Every arm runs each test task --samples times (sample 1 of seed and v1 best is usually
cached from the v1 evaluation). The primary metric is resolved (0/1), averaged per task
over the samples. Arms are compared with a paired sign-flip permutation test on the
per-task mean differences (Monte Carlo, two-sided).
Writes gepa/runs-v2/<agent>/test_eval.json.

Usage: gepa/.venv/bin/python gepa/eval_test_v2.py --agent pi-anthropic-haiku-4-5
"""
import argparse
import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rollout_runner import run_rollouts  # noqa: E402


def sign_flip_p(d: list[float], n_perm: int = 200_000, seed: int = 0) -> float:
    obs = abs(sum(d))
    rng = random.Random(seed)
    nz = [x for x in d if x]
    hits = sum(abs(sum(x if rng.random() < 0.5 else -x for x in nz)) >= obs - 1e-12 for _ in range(n_perm))
    return (hits + 1) / (n_perm + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--run-dir", default=None, help="default gepa/runs-v2/<agent>")
    ap.add_argument("--extra-arm", action="append", default=[], metavar="NAME=RUN_DIR",
                    help="also test the best prompt of another v2 run (repeatable)")
    args = ap.parse_args()
    out_dir = Path(args.run_dir) if args.run_dir else HERE / "runs-v2" / args.agent
    test = json.load(open(HERE / "tasks.json"))["test"]
    arms = {"seed": ""}
    v1 = HERE / "runs" / args.agent / "summary.json"
    if v1.is_file():                                       # agents added after v1 have no v1 arm
        arms["v1_best"] = json.load(open(v1))["best_prompt"]
    arms["v2_best"] = json.load(open(out_dir / "summary.json"))["best_prompt"]
    for spec in args.extra_arm:
        name, d = spec.split("=", 1)
        arms[name] = json.load(open(Path(d) / "summary.json"))["best_prompt"]

    jobs = [(a, k) for a in arms for k in range(1, args.samples + 1)]
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {j: ex.submit(run_rollouts, args.agent, arms[j[0]], test, f"gepa2-test-{args.agent}",
                             include_trace=False, sample=j[1],
                             fanout=int(os.environ.get("GEPA_FANOUT") or 0) or None) for j in jobs}
        res = {j: f.result() for j, f in futs.items()}

    out = {"agent": args.agent, "tasks": test, "samples": args.samples, "arms": {}}
    mean = {}
    for a in arms:
        cells = {t: [] for t in test}
        for k in range(1, args.samples + 1):
            for r in res[(a, k)]:
                cells[r["task_id"]].append({f: r.get(f) for f in ("resolved", "status", "infra_failure",
                                                                   "cost_usd", "turns", "evaluation_id")})
        valid = {t: [c for c in v if not c["infra_failure"]] for t, v in cells.items()}
        mean[a] = {t: (sum(c["resolved"] for c in v) / len(v) if v else None) for t, v in valid.items()}
        n_ok = sum(len(v) for v in valid.values())
        out["arms"][a] = {"cells": cells,
                          "resolved": f"{sum(c['resolved'] for v in valid.values() for c in v)}/{n_ok}",
                          "mean_rate": round(sum(x for x in mean[a].values() if x is not None) /
                                             sum(x is not None for x in mean[a].values()), 4),
                          "cost_usd": round(sum(c["cost_usd"] or 0 for v in cells.values() for c in v), 2)}
    out["comparisons"] = {}
    pairs = [("v2_best", "seed"), ("v1_best", "seed"), ("v2_best", "v1_best")]
    pairs += [p for n in arms if n not in ("seed", "v1_best", "v2_best") for p in ((n, "seed"), ("v2_best", n))]
    pairs = [(a, b) for a, b in pairs if a in arms and b in arms]
    for a, b in pairs:
        d = [mean[a][t] - mean[b][t] for t in test if mean[a][t] is not None and mean[b][t] is not None]
        out["comparisons"][f"{a} - {b}"] = {"mean_diff": round(sum(d) / len(d), 4), "n_tasks": len(d),
                                            "tasks_up": sum(x > 0 for x in d), "tasks_down": sum(x < 0 for x in d),
                                            "p_sign_flip": round(sign_flip_p(d), 4)}
    json.dump(out, open(out_dir / "test_eval.json", "w"), indent=1)
    print(json.dumps({a: {k: v for k, v in out["arms"][a].items() if k != "cells"} for a in arms}))
    print(json.dumps(out["comparisons"], indent=1))


if __name__ == "__main__":
    main()
