#!/usr/bin/env python3
"""GEPA v2 for one zbench pi agent: richer feedback, partial credit, repeated samples.

Changes against gepa_run.py (v1), from the 2026-10-24 diagnosis:
  A. Richer feedback. For every validation task the reflection LM also sees the reference
     fix (source part of the fix commit) and the hidden test diff, so it can compare the
     agent's patch with a correct one. The agent never sees them. The held-out tasks are
     disjoint from the validation tasks, so this cannot inflate the held-out score.
  B. Partial credit. score = 1 if resolved, else 0.5 * (fraction of fail_to_pass tests
     that pass). fail_to_pass tests fail on the base commit by construction, so credit
     means real progress.
  C. Repeated samples. Each (candidate, task) is run --samples times (independent
     rollouts, agent_id suffix -s<k>); the task score is the mean over samples. The
     minibatch default is 6. GEPA counts one metric call per (candidate, task), so the
     number of rollouts is about --samples x --budget.

Usage:
  gepa/.venv/bin/python gepa/gepa_run_v2.py --agent pi-anthropic-haiku-4-5 [--budget 240]
Resume: re-run the same command; GEPA restores state from gepa/runs-v2/<agent>.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gepa
from gepa.core.adapter import EvaluationBatch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gepa_run import COMPONENT, claude_reflection_lm  # noqa: E402
from rollout_runner import STORE, TASKS_DIR, _clip, _setup_environment, run_rollouts  # noqa: E402

REFLECTION_TEMPLATE = """I run a coding agent (the "pi" harness) on real bug-fix and feature tasks in the Zulip repository (Python/Django backend, JavaScript/TypeScript web frontend). The agent receives a task brief, explores and edits the checked-out repo with shell and file tools, and its final working-tree diff is graded by tests it never sees.

Facts about the agent's environment: the checkout has no Python virtualenv, no node_modules, no database and no `python` command (only `python3`), so the Zulip test runners (tools/test-backend, tools/test-js-with-node) cannot run there. The grading runs the tests in a separate, complete environment.

Below is the extra system-prompt text currently appended to the agent's default system prompt (empty means the agent ran with its default system prompt only):
```
<curr_param>
```

The following are examples of tasks given to the agent with this prompt. Each task was run several times independently. For each task you get the score over the runs, a REFERENCE SOLUTION (the real upstream fix and the hidden tests, shown to you only, never to the agent), and condensed traces of one or two runs with their patch and grading feedback:
```
<side_info>
```

Your task is to write a new, improved version of the appended system-prompt text.

Compare each agent patch with the reference solution and diagnose WHY the agent failed or succeeded: e.g. it misread the brief, missed a requirement or edge case, changed the wrong layer, broke existing behavior or existing tests, chose a different design than the codebase conventions imply, did not check its logic, used tools badly, looped, ran out of time or context, or produced no patch. Look for failure patterns that repeat across tasks and runs. Then write instructions that would change that behavior.

Rules:
- The new text must help on UNSEEN tasks from the same repository. Include generalizable working strategy and repository-wide knowledge (code layout, conventions, how to check work in this environment, common pitfalls). Do NOT include facts that only solve the specific tasks shown: no specific function names, file paths, strings or fixes taken from one task or its reference solution.
- Do NOT mention hidden tests, graders, reference solutions, or that the work is evaluated. Speak to the agent as an engineer fixing an issue.
- Keep what demonstrably worked in the current text; change or remove what did not.
- This text is for one specific model; tailor it to the failure patterns you see for this model.

Provide the new instructions within ``` blocks."""

# cells launched at once per sample (None = runner default, up to 12). Keep it near the provider
# slot cap: queued cells hold a global slot while they wait for a provider slot.
FANOUT = int(os.environ.get("GEPA_FANOUT") or 0) or None

TEST_PATH = re.compile(r"(^|/)(tests?|fixtures)/|\.test\.(c?js|ts)$|(^|/)test_[^/]*\.py$")


def _meta(task_id: str) -> dict:
    return json.loads((TASKS_DIR / task_id / "meta.json").read_text())


def reference_section(task_id: str, src_chars: int = 3500, test_chars: int = 2500) -> str:
    """Reference fix (non-test part of the fix commit) + hidden test diff, for the reflector only."""
    m = _meta(task_id)
    repo = os.environ["ZBENCH_TARGET_REPO"]
    files = subprocess.run(["git", "-C", repo, "diff", "--name-only", m["base_commit"], m["fix_commit"]],
                           capture_output=True, text=True).stdout.split()
    src_files = [f for f in files if not TEST_PATH.search(f)]
    src = subprocess.run(["git", "-C", repo, "diff", m["base_commit"], m["fix_commit"], "--", *src_files],
                         capture_output=True, text=True).stdout if src_files else ""
    test = (TASKS_DIR / task_id / "gold_test.patch").read_text(errors="replace")
    return ("--- REFERENCE FIX (upstream source change; not shown to the agent) ---\n"
            + (_clip(src, src_chars) if src.strip() else "(no non-test source change)")
            + "\n--- HIDDEN TESTS (diff; not shown to the agent) ---\n" + _clip(test, test_chars))


def partial_score(task_id: str, evaluation_id: str | None, resolved: int) -> float:
    """1.0 if resolved, else 0.5 * fraction of fail_to_pass units that pass in the verify log."""
    if resolved:
        return 1.0
    f2p = _meta(task_id).get("fail_to_pass") or []
    log_p = STORE / "blobs" / "attempt" / str(evaluation_id) / "pb-verify.log"
    if not f2p or not evaluation_id or not log_p.is_file():
        return 0.0
    log = log_p.read_text(errors="replace")
    ok = 0
    for unit in f2p:
        if unit.endswith((".cjs", ".js", ".ts")):          # node test file: its own section
            sec = re.search(r"=== zbench node file: " + re.escape(unit) + r" ===\n(.*?)(?=\n=== zbench node file:|\Z)",
                            log, re.S)
            ok += bool(sec and "Test(s) passed" in sec.group(1))
        else:                                              # backend test id
            if not re.search(r"^Ran \d+ tests?", log, re.M):
                continue                                   # import / setup crash: nothing ran
            failed = re.findall(r"^(?:FAIL|ERROR): \S+ \(([^)]+)\)", log, re.M)
            ok += not any(f == unit or f.startswith(unit + ".") or unit.startswith(f + ".") for f in failed)
    return 0.5 * ok / len(f2p)


class ZbenchPiAdapterV2:
    """DataInst = task_id. Score = mean partial score over `samples` independent rollouts."""

    propose_new_texts = None

    def __init__(self, base_agent: str, run_label: str, samples: int):
        self.base_agent, self.run_label, self.samples = base_agent, run_label, samples

    def evaluate(self, batch, candidate, capture_traces=False):
        batch = list(batch)
        with ThreadPoolExecutor(self.samples) as ex:
            futs = [ex.submit(run_rollouts, self.base_agent, candidate[COMPONENT], batch, self.run_label,
                              trace_chars=7000, sample=k, fanout=FANOUT) for k in range(1, self.samples + 1)]
            per_sample = [f.result() for f in futs]
        bad = [(r["agent_id"], r["task_id"]) for res in per_sample for r in res if r.get("infra_failure")]
        if bad:
            raise RuntimeError(f"infra failure on {bad}")
        outputs, scores, trajs = [], [], []
        for t in batch:
            runs = [next(r for r in res if r["task_id"] == t) for res in per_sample]
            for r in runs:
                r["score"] = partial_score(t, r["evaluation_id"], r["resolved"])
            sc = sum(r["score"] for r in runs) / len(runs)
            outputs.append({"task_id": t, "resolved": [r["resolved"] for r in runs],
                            "scores": [r["score"] for r in runs]})
            scores.append(sc)
            trajs.append({"task_id": t, "runs": runs, "score": sc})
        return EvaluationBatch(outputs=outputs, scores=scores, trajectories=trajs if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        items = []
        for tr in eval_batch.trajectories:
            runs = tr["runs"]
            fails = [r for r in runs if not r["resolved"]]
            wins = [r for r in runs if r["resolved"]]
            shown = (fails[:1] + wins[:1]) if fails and wins else (fails or wins)[:2]
            items.append({
                "Task": tr["task_id"],
                "Result": (f"{sum(r['resolved'] for r in runs)}/{len(runs)} runs resolved; "
                           f"partial-credit scores {[round(r['score'], 2) for r in runs]}"),
                "Reference solution": reference_section(tr["task_id"]),
                "Traces": "\n\n".join(f"[run {i + 1}: {'RESOLVED' if r['resolved'] else 'NOT RESOLVED'}]\n"
                                      + r.get("trace", "") for i, r in enumerate(shown)),
            })
        return {c: items for c in components_to_update}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--tasks", default=str(HERE / "tasks.json"))
    ap.add_argument("--budget", type=int, default=240, help="GEPA metric calls = (candidate, task) evaluations")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--minibatch", type=int, default=6)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--run-dir", default=None, help="default gepa/runs-v2/<agent>")
    args = ap.parse_args()

    _setup_environment()
    run_dir = Path(args.run_dir) if args.run_dir else HERE / "runs-v2" / args.agent
    run_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(run_dir / "driver.log"), logging.StreamHandler()])
    train = json.load(open(args.tasks))["train"]

    result = gepa.optimize(
        seed_candidate={COMPONENT: ""},
        trainset=train,
        valset=train,
        adapter=ZbenchPiAdapterV2(args.agent, f"gepa2-{args.agent}", args.samples),
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
        "agent": args.agent, "version": 2, "samples": args.samples, "minibatch": args.minibatch,
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
