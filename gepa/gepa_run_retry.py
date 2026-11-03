#!/usr/bin/env python3
"""GEPA for the retry-with-feedback setting (Robert, 2026-10-29).

The agent rows *-retry3 (zbench-tasks/agents-matrix.jsonl) set ZBENCH_MAX_ATTEMPTS=3: when a
round does not resolve the task, the SAME conversation continues in the SAME worktree with
a short user message that says only that the problem is not fixed yet (zbench/workflow.py).
A run is resolved if any of its 3 rounds resolves the task; the attempt row is the final
round, and attempts.json in the evidence has the per-round verdicts.

Everything else is gepa_run_v2.py (reference solution for the reflector, partial credit,
3 samples, minibatch 6, budget 240) and, with --objective cost, gepa_run_cost.py (score =
partial - 0.1 * min(cost / seed_cost, 3); the cost of a run includes every round). The
reflection template also tells the reflector about the rounds.

Usage:
  gepa/.venv/bin/python gepa/gepa_run_retry.py --agent pi-anthropic-haiku-5-5-retry3 --objective accuracy
  gepa/.venv/bin/python gepa/gepa_run_retry.py --agent pi-anthropic-haiku-5-5-retry3 --objective cost
Writes gepa/runs-retry/<agent> (accuracy) or gepa/runs-retry-cost/<agent> (cost).
Resume: re-run the same command. Held-out: eval_test_retry.py --agent <agent>.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # pure-swebench root: zbench package

import gepa

import gepa_run_cost
from gepa_run import COMPONENT, claude_reflection_lm
from gepa_run_cost import COST_TEMPLATE, ZbenchPiAdapterCost, seed_costs
from gepa_run_v2 import HERE, REFLECTION_TEMPLATE, ZbenchPiAdapterV2
from rollout_runner import _setup_environment
from zbench.workflow import _FEEDBACK_NO_CHANGE, _FEEDBACK_NOT_FIXED  # noqa: E402

# Haiku 5.5 long-context tier applies to the retry row too
gepa_run_cost.TIERS["pi-anthropic-haiku-5-5-retry3"] = gepa_run_cost.TIERS["pi-anthropic-haiku-5-5"]

RETRY_TEXT = f"""

ROUNDS. Each run is one conversation of up to 3 rounds. When the agent finishes a round, its change is checked; if the problem is not fixed, the agent receives this message and continues in the same conversation, with its previous change still in the repository:
  "{_FEEDBACK_NOT_FIXED}"
(or, if it changed nothing: "{_FEEDBACK_NO_CHANGE}"). The message never says what is wrong. A run counts as solved if any round solves the task. The transcripts show the rounds ("[user/harness message]" lines), and the grading feedback lists the verdict of each round. Look at how the agent uses the later rounds: whether it re-examines its assumptions and the brief, or only repeats or slightly varies the same change. Instructions about what to do after such a message are in scope."""

PROMPT_END = "\n\nProvide the new instructions within ``` blocks."


def template(objective: str, agent: str) -> str:
    t = (COST_TEMPLATE if objective == "cost" else REFLECTION_TEMPLATE).replace(PROMPT_END, RETRY_TEXT + PROMPT_END)
    if "haiku-5-5" not in agent:      # the long-context price tier is a Haiku 5.5 fact
        t = t.replace(" A call whose context is larger than 100K tokens costs 5x more per token.", "")
    if agent.startswith("claude-cli-"):
        t = t.replace('a coding agent (the "pi" harness)', "a coding agent (the Claude Code CLI harness)")
    assert RETRY_TEXT in t
    return t


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--objective", choices=("accuracy", "cost"), required=True)
    ap.add_argument("--tasks", default=str(HERE / "tasks.json"))
    ap.add_argument("--budget", type=int, default=240)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--minibatch", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cost-weight", type=float, default=gepa_run_cost.COST_WEIGHT)
    ap.add_argument("--run-dir", default=None)
    args = ap.parse_args()
    gepa_run_cost.COST_WEIGHT = args.cost_weight

    _setup_environment()
    sub = "runs-retry-cost" if args.objective == "cost" else "runs-retry"
    run_dir = Path(args.run_dir) if args.run_dir else HERE / sub / args.agent
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(run_dir / "driver.log"), logging.StreamHandler()])
    train = json.load(open(args.tasks))["train"]
    label = f"gepa-retry-{args.agent}"
    if args.objective == "cost":
        sc = seed_costs(args.agent, train, args.samples)
        json.dump(sc, open(run_dir / "seed_costs.json", "w"), indent=1)
        logging.info("seed cost per task: mean $%.3f over %d tasks", sum(sc.values()) / len(sc), len(sc))
        adapter = ZbenchPiAdapterCost(args.agent, label, args.samples, sc)
    else:
        adapter = ZbenchPiAdapterV2(args.agent, label, args.samples)

    result = gepa.optimize(
        seed_candidate={COMPONENT: ""},
        trainset=train,
        valset=train,
        adapter=adapter,
        reflection_lm=claude_reflection_lm,
        reflection_prompt_template=template(args.objective, args.agent),
        candidate_selection_strategy="pareto",
        reflection_minibatch_size=args.minibatch,
        max_metric_calls=args.budget,
        run_dir=str(run_dir),
        seed=args.seed,
        raise_on_exception=False,
        display_progress_bar=False,
    )
    summary = {
        "agent": args.agent, "version": f"retry-{args.objective}", "samples": args.samples,
        "minibatch": args.minibatch,
        **({"cost_weight": gepa_run_cost.COST_WEIGHT, "cost_cap": gepa_run_cost.COST_CAP} if args.objective == "cost" else {}),
        "candidates": [c[COMPONENT] for c in result.candidates],
        "val_aggregate_scores": result.val_aggregate_scores,
        "parents": result.parents,
        "best_idx": result.best_idx,
        "best_prompt": result.best_candidate[COMPONENT],
        "total_metric_calls": result.total_metric_calls,
    }
    json.dump(summary, open(run_dir / "summary.json", "w"), indent=1)
    logging.info("done: best idx %s val %.3f", result.best_idx, result.val_aggregate_scores[result.best_idx])


if __name__ == "__main__":
    main()
