#!/usr/bin/env python3
"""One-off recovery for the Muse GEPA run after the 2026-10-24 GPU-driver crash.

The crash (12:01:09Z) cut short about 7 validation rollouts of Muse candidate 5, which
GEPA then scored as misses (11/20). Those attempts are excluded in the store, so
run_rollouts re-runs exactly the lost cells and returns the cached rest. If the
corrected validation score beats the recorded best, the summary's best_prompt is
switched to candidate 5 (the original summary is kept as summary.pre-recovery.json),
so eval_test.py tests the right prompt.
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rollout_runner import run_rollouts  # noqa: E402

AGENT = "pi-vllm-muse-glimmer-30b"
CAND = 5

run_dir = HERE / "runs" / AGENT
summ = json.load(open(run_dir / "summary.json"))
val = json.load(open(HERE / "tasks.json"))["train"]
res = run_rollouts(AGENT, summ["candidates"][CAND], val, f"gepa-{AGENT}-recover")
bad = [r["task_id"] for r in res if r.get("infra_failure")]
if bad:
    sys.exit(f"infra failures remain: {bad}")
score = sum(r["resolved"] for r in res)
best = round(summ["val_aggregate_scores"][summ["best_idx"]] * len(val))
print(f"candidate {CAND} corrected validation score {score}/{len(val)}; recorded best {best}/{len(val)} (idx {summ['best_idx']})")

shutil.copy(run_dir / "summary.json", run_dir / "summary.pre-recovery.json")
summ["val_aggregate_scores"][CAND] = score / len(val)
summ["recovery_note"] = (f"candidate {CAND} validation re-scored after GPU-driver crash: {score}/{len(val)}")
if score > best:
    summ["recovery_note"] += f"; it replaces idx {summ['best_idx']} as best"
    summ["best_idx"] = CAND
    summ["best_prompt"] = summ["candidates"][CAND]
json.dump(summ, open(run_dir / "summary.json", "w"), indent=1)
