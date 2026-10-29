#!/usr/bin/env python3
"""GEPA prompt optimization for one zbench pi agent.

GEPA (Agrawal et al. 2025, arXiv:2507.19457) evolves the text of a prompt by
reflection: it runs the agent on a small minibatch of tasks, shows the traces and
grading feedback to a reflection LLM, takes the rewritten prompt it proposes, and
keeps it only if it beats its parent on the same minibatch. Accepted candidates are
scored on the full Pareto (validation) set, and the next parent is sampled from the
per-task Pareto front, which keeps diverse strategies alive.

Here the optimized component is ONE text: the extra system prompt that pi appends
to its default system prompt (env PI_APPEND_SYSTEM_PROMPT). Everything else about
the agent row (model, provider, thinking level, timeouts) is copied unchanged, so
the seed candidate (empty append) IS the baseline configuration.

Rollouts go through gepa/rollout_runner.py into the GEPA-private store (gepa/store), never
the main bench.db. Reflection uses Claude Opus 5.5 through the headless claude CLI.

Usage:
  gepa/.venv/bin/python gepa/gepa_run.py --agent pi-vllm-qwen3.6-27b [--budget 100]
Resume: re-run the same command; GEPA restores state from the run dir.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import gepa
from gepa.core.adapter import EvaluationBatch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from rollout_runner import run_rollouts  # noqa: E402

COMPONENT = "append_system_prompt"
REFLECTION_MODEL = "claude-opus-5-5"

# Default GEPA template, adapted for this setting: the reflector must write
# instructions that transfer to UNSEEN tasks in the same repo, so it may encode
# repo-wide knowledge and working strategy but not task-specific answers. The
# benchmark contract also forbids telling the agent that hidden tests exist.
REFLECTION_TEMPLATE = """I run a coding agent (the "pi" harness) on real bug-fix and feature tasks in the Zulip repository (Python/Django backend, JavaScript/TypeScript web frontend). The agent receives a task brief, explores and edits the checked-out repo with shell and file tools, and its final working-tree diff is graded by tests it never sees.

Below is the extra system-prompt text currently appended to the agent's default system prompt (empty means the agent ran with its default system prompt only):
```
<curr_param>
```

The following are examples of tasks given to the agent with this prompt, a condensed trace of what the agent did, its final patch, and the grading feedback:
```
<side_info>
```

Your task is to write a new, improved version of the appended system-prompt text.

Read the traces and feedback carefully. Diagnose WHY the agent failed or succeeded: e.g. it misread the brief, stopped before finishing, edited the wrong layer, broke existing behavior, did not run or could not run checks, used tools badly, looped, ran out of time or context, or produced no patch. Then write instructions that would change that behavior.

Rules:
- The new text must help on UNSEEN tasks from the same repository. Include generalizable working strategy and repository-wide knowledge (code layout, conventions, how to run checks in this environment, common pitfalls). Do NOT include facts that only solve the specific tasks shown (no specific function names, file paths, or fixes that are particular to one shown task).
- Do NOT mention hidden tests, graders, or that the work is evaluated. Speak to the agent as an engineer fixing an issue.
- Keep what demonstrably worked in the current text; change or remove what did not.
- This text is for one specific model; tailor it to the failure patterns you see for this model.
- Be concise: at most about 600 words. Long prompts consume the agent's context.

Provide the new instructions within ``` blocks."""


def claude_reflection_lm(prompt) -> str:
    """Reflection LM: Claude Opus 5.5 via the headless claude CLI, no tools."""
    if not isinstance(prompt, str):
        prompt = "\n\n".join(m.get("content", "") for m in prompt)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID")}
    with tempfile.TemporaryDirectory() as cwd:
        for attempt in range(3):
            p = subprocess.run(
                ["claude", "-p", "--model", REFLECTION_MODEL, "--output-format", "json",
                 "--no-session-persistence",
                 "--disallowedTools", "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Agent,NotebookEdit"],
                input=prompt, capture_output=True, text=True, cwd=cwd, env=env, timeout=1200)
            try:
                out = json.loads(p.stdout)
                if not out.get("is_error") and out.get("result"):
                    logging.info("reflection ok: cost=$%.3f", out.get("total_cost_usd") or 0)
                    return out["result"]
            except json.JSONDecodeError:
                pass
            logging.warning("reflection attempt %d failed: rc=%s %s", attempt, p.returncode,
                            (p.stderr or p.stdout)[-500:])
    raise RuntimeError("reflection LM failed 3 times")


class ZbenchPiAdapter:
    """GEPA adapter: DataInst = task_id, score = resolved (0/1)."""

    propose_new_texts = None   # use GEPA's default reflective proposer (with REFLECTION_TEMPLATE)

    def __init__(self, base_agent: str, run_label: str):
        self.base_agent = base_agent
        self.run_label = run_label

    def evaluate(self, batch, candidate, capture_traces=False):
        res = run_rollouts(self.base_agent, candidate[COMPONENT], list(batch), self.run_label)
        # An infra failure (dead auth, provider outage) says nothing about the prompt. Raise
        # so GEPA drops this iteration instead of scoring the task as a model miss.
        bad = [r["task_id"] for r in res if r.get("infra_failure")]
        if bad:
            raise RuntimeError(f"infra failure on {bad}: {res[0].get('infra_error')}")
        by_task = {r["task_id"]: r for r in res}
        outputs, scores, trajs = [], [], []
        for t in batch:
            r = by_task.get(t) or {"task_id": t, "resolved": 0, "outcome": "missing",
                                   "trace": "No result was recorded for this rollout."}
            outputs.append({k: r.get(k) for k in ("task_id", "resolved", "outcome", "evaluation_id",
                                                  "cost_usd", "turns")})
            scores.append(float(r.get("resolved") or 0))
            trajs.append(r)
        return EvaluationBatch(outputs=outputs, scores=scores,
                               trajectories=trajs if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        items = []
        for r, s in zip(eval_batch.trajectories, eval_batch.scores):
            items.append({
                "Task": r["task_id"],
                "Result": "RESOLVED" if s >= 1 else f"NOT RESOLVED (outcome: {r.get('outcome')})",
                "Agent trace, patch and feedback": r.get("trace", ""),
            })
        return {c: items for c in components_to_update}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True, help="base agent_id from agents-matrix.jsonl")
    ap.add_argument("--tasks", default=str(HERE / "tasks.json"))
    ap.add_argument("--budget", type=int, default=100, help="max rollouts counted by GEPA (cached ones included)")
    ap.add_argument("--minibatch", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    run_dir = HERE / "runs" / args.agent
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(run_dir / "driver.log"), logging.StreamHandler()])
    train = json.load(open(args.tasks))["train"]

    result = gepa.optimize(
        seed_candidate={COMPONENT: ""},
        trainset=train,
        valset=train,            # 10 tasks: feedback minibatches and Pareto set; held-out test is separate
        adapter=ZbenchPiAdapter(args.agent, f"gepa-{args.agent}"),
        reflection_lm=claude_reflection_lm,
        reflection_prompt_template=REFLECTION_TEMPLATE,
        candidate_selection_strategy="pareto",
        reflection_minibatch_size=args.minibatch,
        max_metric_calls=args.budget,
        run_dir=str(run_dir),
        seed=args.seed,
        raise_on_exception=False,
        display_progress_bar=False,
    )
    summary = {
        "agent": args.agent,
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
