#!/usr/bin/env python3
"""Audit every failed attempt and decide whether the failure is a TRUE failure.

A "failure" is any attempt with tests_passed=0. Not every failure is the model's
fault. This tool reads each failed attempt's patch and verify log from the blob
store and assigns a failure_class:

    infra          provider/internal error   -> NOT a model failure (harness)
    no_patch       agent produced no patch    -> not a solve attempt
    apply_failed   patch would not apply       -> malformed output
    broken_task    hidden test fails even for control-gold -> BROKEN TASK, not model
    true_failure   control-gold passes, model patch ran, hidden test failed

Two overlays add suspicion to a true_failure (a reviewer should look):
    zero_resolver  no non-control agent EVER resolved this task (ill-defined?)
    covers_gold    the model's changed code lines are a superset of the gold fix
                   yet it was graded fail -> possible mis-grade / over-specific test

Verify-log signature for true_failures:
    assertion      FAILED (failures=N)      -> behaviour mismatch (usual true fail)
    error          FAILED (errors=N)        -> test errored (import/setup/broken patch)
    js_module      node MODULE_NOT_FOUND    -> frontend test could not load a module
    timeout / other

Usage:
    audit_failures.py                 # full summary
    audit_failures.py --suspects      # only the cells a reviewer should re-check
    audit_failures.py --task ZT-...   # one task across all agents
    audit_failures.py --out FILE.json # also write the per-cell classification
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(REPO, "bench-db", "bench.db")
BLOBS = os.path.join(REPO, "bench-db", "blobs", "attempt")
SOLUTIONS = os.path.join(REPO, "zbench-tasks", "solutions")

CONTROL = {"control-gold", "control-empty", "control-tamper", "control-fetch", "replay"}


def _rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(
            "SELECT evaluation_id, config_id, task_id, run_id, tests_passed, "
            "status, outcome FROM attempt")]
    finally:
        con.close()


def _code_lines(diff_text):
    """Set of (file, +/-, content) for real code changes; ignores headers/context
    and doc/version-only files, so two solutions of the same fix compare equal."""
    out, cur = set(), None
    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            m = re.search(r" b/(\S+)", line)
            cur = m.group(1) if m else None
        elif line.startswith(("+++", "---", "index ", "@@", "new file", "deleted",
                              "similarity", "rename", "Binary")):
            continue
        elif cur and line[:1] in "+-":
            out.add((cur, line[0], line[1:].strip()))
    return out


def _is_code(path):
    return not (path.endswith(".md") or path.endswith("version.py")
                or path.startswith("api_docs/"))


def _gold_code_lines(task_id):
    fp = os.path.join(SOLUTIONS, task_id, "gold_code.patch")
    if not os.path.exists(fp):
        return None
    try:
        return _code_lines(open(fp, errors="replace").read())
    except OSError:
        return None


def _bundle(ev):
    d = os.path.join(BLOBS, ev)
    return d if os.path.isdir(d) else None


def _patch(ev):
    d = _bundle(ev)
    if not d:
        return ""
    pd = os.path.join(d, "patch.diff")
    if os.path.exists(pd):
        try:
            return open(pd, errors="replace").read()
        except OSError:
            return ""
    return ""


def _verify_sig(ev):
    d = _bundle(ev)
    if not d:
        return "no_log"
    fp = os.path.join(d, "pb-verify.log")
    if not os.path.exists(fp):
        return "no_log"
    try:
        txt = open(fp, errors="replace").read()
    except OSError:
        return "no_log"
    if "MODULE_NOT_FOUND" in txt:
        return "js_module"
    if re.search(r"TimeoutExpired|timed out|Timeout", txt):
        return "timeout"
    m = re.findall(r"FAILED \(([^)]*)\)", txt)
    if m:
        last = m[-1]
        has_f = "failures=" in last
        has_e = "errors=" in last
        if has_f and not has_e:
            return "assertion"
        if has_e and not has_f:
            return "error"
        return "assertion+error"
    return "other"


def audit():
    rows = _rows()
    # per-task facts
    gold_pass, gold_seen = {}, set()
    resolvers = defaultdict(set)
    for r in rows:
        t = r["task_id"]
        if r["config_id"] == "control-gold":
            gold_seen.add(t)
            if r["tests_passed"]:
                gold_pass[t] = True
            else:
                gold_pass.setdefault(t, False)
        if r["config_id"] not in CONTROL and r["tests_passed"]:
            resolvers[t].add(r["config_id"])

    results = []
    for r in rows:
        if r["tests_passed"]:
            continue
        t, ev = r["task_id"], r["evaluation_id"]
        out = r["outcome"]
        cls, sig, covers = None, None, False
        if out == "internal_error":
            cls = "infra"
        elif out == "candidate_missing":
            cls = "no_patch"
        elif out == "candidate_application_failed":
            cls = "apply_failed"
        else:  # verification_tests_failed
            if gold_seen and gold_pass.get(t) is False:
                cls = "broken_task"
            else:
                cls = "true_failure"
            sig = _verify_sig(ev)
            gold = _gold_code_lines(t)
            if gold:
                mine = {x for x in _code_lines(_patch(ev)) if _is_code(x[0])}
                goldc = {x for x in gold if _is_code(x[0])}
                if goldc and goldc <= mine:
                    covers = True
        results.append({
            "evaluation_id": ev, "config_id": r["config_id"], "task_id": t,
            "run_id": r["run_id"], "outcome": out, "failure_class": cls,
            "verify_sig": sig, "zero_resolver": (r["config_id"] not in CONTROL
                                                 and not resolvers.get(t)),
            "covers_gold": covers,
        })
    return results, resolvers, gold_pass, gold_seen


def _print_summary(results, resolvers, gold_pass, gold_seen):
    non_ctrl = [x for x in results if x["config_id"] not in CONTROL]
    print(f"TOTAL failed attempts: {len(results)}  "
          f"(non-control: {len(non_ctrl)})\n")

    print("By failure_class (non-control agents):")
    cc = Counter(x["failure_class"] for x in non_ctrl)
    labels = {
        "infra": "provider/infra error  -> NOT a model failure",
        "no_patch": "no patch produced     -> not a solve attempt",
        "apply_failed": "patch did not apply   -> malformed output",
        "broken_task": "BROKEN TASK (gold also fails) -> NOT a model failure",
        "true_failure": "true failure (gold passes, test failed)",
    }
    for k in ("true_failure", "broken_task", "no_patch", "infra", "apply_failed"):
        if cc.get(k):
            print(f"  {cc[k]:>4}  {k:<13} {labels[k]}")

    tf = [x for x in non_ctrl if x["failure_class"] == "true_failure"]
    print(f"\nVerify signature within {len(tf)} true_failures:")
    for k, n in Counter(x["verify_sig"] for x in tf).most_common():
        note = {"assertion": "clean behaviour mismatch (expected true-fail shape)",
                "error": "test errored (import/setup/broken patch)",
                "js_module": "frontend module load error",
                "timeout": "verify timed out",
                "no_log": "no verify log in bundle"}.get(k, "")
        print(f"  {n:>4}  {k:<14} {note}")

    broken = sorted({x["task_id"] for x in results
                     if x["failure_class"] == "broken_task"})
    print(f"\nBroken tasks (control-gold fails) : {len(broken)}")
    for t in broken:
        print(f"  {t}")

    # zero-resolver tasks (no non-control agent ever resolved)
    all_tasks = {x["task_id"] for x in results}
    zero = sorted(t for t in all_tasks if not resolvers.get(t) and t in gold_seen)
    print(f"\nZero-resolver tasks (0 agents resolved, gold ran): {len(zero)}")
    for t in zero:
        gp = "gold PASSES" if gold_pass.get(t) else "gold FAILS (broken)"
        print(f"  {t}  [{gp}]")

    covers = [x for x in non_ctrl if x["covers_gold"]]
    print(f"\nMis-grade suspects (patch covers the gold fix yet failed): {len(covers)}")
    for x in covers[:40]:
        print(f"  {x['config_id']:<34} {x['task_id']}  ({x['verify_sig']})")
    if len(covers) > 40:
        print(f"  ... and {len(covers) - 40} more")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suspects", action="store_true",
                    help="list only cells a reviewer should re-check")
    ap.add_argument("--task", help="restrict to one task_id")
    ap.add_argument("--out", help="write per-cell JSON classification here")
    args = ap.parse_args()

    results, resolvers, gold_pass, gold_seen = audit()
    if args.task:
        results = [x for x in results if x["task_id"] == args.task]

    if args.out:
        json.dump(results, open(args.out, "w"), indent=2)
        print(f"wrote {len(results)} rows -> {args.out}", file=sys.stderr)

    if args.suspects:
        sus = [x for x in results if x["config_id"] not in CONTROL and (
            x["failure_class"] == "broken_task" or x["covers_gold"]
            or (x["failure_class"] == "true_failure" and x["zero_resolver"]))]
        print(f"{len(sus)} suspect cell(s) — re-check these before trusting the fail:\n")
        for x in sorted(sus, key=lambda r: (r["task_id"], r["config_id"])):
            tag = ("broken_task" if x["failure_class"] == "broken_task"
                   else "covers_gold" if x["covers_gold"]
                   else "zero_resolver")
            print(f"  [{tag:<12}] {x['config_id']:<34} {x['task_id']}  "
                  f"({x['verify_sig']})  eval={x['evaluation_id'][:8]}")
        return

    _print_summary(results, resolvers, gold_pass, gold_seen)


if __name__ == "__main__":
    main()
