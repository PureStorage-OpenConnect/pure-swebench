#!/usr/bin/env python3
"""Cost-aware GEPA (v2 + cost objective) for one zbench pi agent.

Same as gepa_run_v2.py (reference solution for the reflector, partial credit, 3 samples),
plus a cost term in the score:

  score = partial_credit - COST_WEIGHT * min(cost / seed_cost, COST_CAP)

seed_cost = mean cost of the seed prompt (empty) on the same task over the same samples,
so the term is a per-task cost ratio (1.0 = same cost as the seed). With weight 0.1, a
prompt that halves the cost of every task gains 0.05, i.e. 1/20 of a resolve. Resolve
stays the main objective; cost breaks ties between prompts that resolve the same.

Cost = per-request cost from the pi session file, with the provider's long-context tier
(Haiku 5.5: prompts > 100K tokens cost 5x). pi itself prices every request at the
<= 100K rate. For models without a tier table the pi/price-table cost is used.
The reflector sees the cost of each run and the seed cost, and the template tells it
the cost objective.

Usage:
  gepa/.venv/bin/python gepa/gepa_run_cost.py --agent pi-anthropic-haiku-5-5 [--budget 240]
Writes gepa/runs-cost/<agent>. Held-out: eval_test_v2.py --run-dir gepa/runs-cost/<agent>.
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import gepa

from gepa_run import COMPONENT, claude_reflection_lm
from gepa_run_v2 import FANOUT, REFLECTION_TEMPLATE, HERE, ZbenchPiAdapterV2
from rollout_runner import STORE, _setup_environment, run_rollouts

COST_WEIGHT = 0.1
COST_CAP = 3.0

# $/M tokens: (prompt-size threshold, {tier: (input, output, cache_read, cache_write)})
TIERS = {
    "pi-anthropic-haiku-5-5": (100_000, {"low": (0.10, 0.50, 0.01, 0.125),
                                         "high": (0.50, 2.50, 0.05, 0.625)}),
}

COST_TEXT = """

COST OBJECTIVE. Besides solving the task, the agent should also solve it CHEAPLY. Each run shows its cost in USD and the cost of the same task with the default prompt (empty appended text). Cost grows with the number of model calls (turns), the size of the context that is re-sent on each call (files read, long command outputs, a long system prompt), and the output/thinking tokens. A call whose context is larger than 100K tokens costs 5x more per token. Priority order: (1) do not lose solved tasks, (2) reduce cost. Good cost levers are: read only the parts of files that are needed (grep/sed -n ranges, not whole large files), keep command outputs short (head/tail, quiet flags), avoid repeated exploration and re-reading, stop when the change is complete and checked, and keep the appended text itself short enough that it does not add much context to every call. Do not tell the agent about cost, money or budgets explicitly; express it as efficient working habits."""

COST_TEMPLATE = REFLECTION_TEMPLATE.replace(
    "\n\nProvide the new instructions within ``` blocks.",
    COST_TEXT + "\n\nProvide the new instructions within ``` blocks.")
assert COST_TEMPLATE != REFLECTION_TEMPLATE


def session_cost(base_agent: str, evaluation_id: str | None, fallback: float | None) -> float | None:
    """Per-request tiered cost from the pi session file; fallback when no tier table/session."""
    tier = TIERS.get(base_agent)
    p = STORE / "blobs" / "attempt" / str(evaluation_id) / "session.jsonl"
    if not tier or not evaluation_id or not p.is_file():
        return fallback
    thr, prices = tier
    tot, seen = 0.0, False
    for line in p.open(errors="replace"):
        try:
            u = (json.loads(line).get("message") or {}).get("usage")
        except json.JSONDecodeError:
            continue
        if not u:
            continue
        seen = True
        i, o, cr, cw = (u.get(k) or 0 for k in ("input", "output", "cacheRead", "cacheWrite"))
        pi, po, pr, pw = prices["high" if i + cr + cw > thr else "low"]
        tot += (i * pi + o * po + cr * pr + cw * pw) / 1e6
    return tot if seen else fallback


class ZbenchPiAdapterCost(ZbenchPiAdapterV2):
    def __init__(self, base_agent, run_label, samples, seed_cost: dict[str, float]):
        super().__init__(base_agent, run_label, samples)
        self.seed_cost = seed_cost

    def evaluate(self, batch, candidate, capture_traces=False):
        eb = super().evaluate(batch, candidate, capture_traces=True)
        scores, trajs = [], []
        for out, tr in zip(eb.outputs, eb.trajectories):
            t = tr["task_id"]
            costs = [session_cost(self.base_agent, r["evaluation_id"], r.get("cost_usd")) for r in tr["runs"]]
            for r, c in zip(tr["runs"], costs):
                r["tiered_cost"] = c
            known = [c for c in costs if c is not None]
            mean_c = sum(known) / len(known) if known else None
            ratio = min(mean_c / self.seed_cost[t], COST_CAP) if mean_c is not None and self.seed_cost.get(t) else 1.0
            sc = tr["score"] - COST_WEIGHT * ratio
            out.update(cost=mean_c, cost_ratio=round(ratio, 3), partial=tr["score"])
            tr.update(cost=mean_c, cost_ratio=ratio, partial=tr["score"], score=sc)
            scores.append(sc)
            trajs.append(tr)
        return type(eb)(outputs=eb.outputs, scores=scores, trajectories=trajs if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        ds = super().make_reflective_dataset(candidate, eval_batch, components_to_update)
        for c in components_to_update:
            for item, tr in zip(ds[c], eval_batch.trajectories):
                costs = ", ".join("n/a" if r["tiered_cost"] is None else f"${r['tiered_cost']:.3f}" for r in tr["runs"])
                item["Cost"] = (f"cost per run [{costs}]; default-prompt mean ${self.seed_cost.get(tr['task_id'], 0):.3f}; "
                                f"ratio to default {tr['cost_ratio']:.2f}")
        return ds


def seed_costs(agent: str, tasks: list[str], samples: int) -> dict[str, float]:
    """Mean tiered cost of the seed prompt per task (cells usually cached from the v2 run)."""
    per = {t: [] for t in tasks}
    for k in range(1, samples + 1):
        for r in run_rollouts(agent, "", tasks, f"gepa-cost-{agent}", include_trace=False, sample=k, fanout=FANOUT):
            c = session_cost(agent, r["evaluation_id"], r.get("cost_usd"))
            if c is not None and not r.get("infra_failure"):
                per[r["task_id"]].append(c)
    return {t: sum(v) / len(v) for t, v in per.items() if v}


def main():
    global COST_WEIGHT
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--tasks", default=str(HERE / "tasks.json"))
    ap.add_argument("--budget", type=int, default=240)
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--minibatch", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cost-weight", type=float, default=COST_WEIGHT)
    ap.add_argument("--run-dir", default=None, help="default gepa/runs-cost/<agent>")
    args = ap.parse_args()
    COST_WEIGHT = args.cost_weight

    _setup_environment()
    run_dir = Path(args.run_dir) if args.run_dir else HERE / "runs-cost" / args.agent
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(run_dir / "driver.log"), logging.StreamHandler()])
    train = json.load(open(args.tasks))["train"]
    sc = seed_costs(args.agent, train, args.samples)
    json.dump(sc, open(run_dir / "seed_costs.json", "w"), indent=1)
    logging.info("seed cost per task: mean $%.3f over %d tasks", sum(sc.values()) / len(sc), len(sc))

    result = gepa.optimize(
        seed_candidate={COMPONENT: ""},
        trainset=train,
        valset=train,
        adapter=ZbenchPiAdapterCost(args.agent, f"gepa-cost-{args.agent}", args.samples, sc),
        reflection_lm=claude_reflection_lm,
        reflection_prompt_template=COST_TEMPLATE,
        candidate_selection_strategy="pareto",
        reflection_minibatch_size=args.minibatch,
        max_metric_calls=args.budget,
        run_dir=str(run_dir),
        seed=args.seed,
        raise_on_exception=False,
        display_progress_bar=False,
    )
    summary = {
        "agent": args.agent, "version": "cost", "samples": args.samples, "minibatch": args.minibatch,
        "cost_weight": COST_WEIGHT, "cost_cap": COST_CAP,
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
