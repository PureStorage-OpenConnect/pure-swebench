#!/usr/bin/env python3
"""Triage every NO-PATCH attempt and decide which ones deserve a second chance.

A "no-patch" attempt is one the harness recorded with outcome=candidate_missing
(status no_patch_generated): the agent ran but no usable git diff came back. The
harness already splits these two ways in scoring.classify_attempt:

    artifact:auth     CLI fast-fail (<=90s, no output tokens) -> missing key/OAuth.
                      Already re-runnable via --fill; but a re-run REPRODUCES the
                      fast-fail until the driver-shell credential is fixed.
    no_patch_genuine  ran a fair budget, emitted no usable patch. The harness
                      deliberately does NOT re-run these (avoids re-run loops).

The project owner's observation ("some just stopped without ever really completing") is a
claim that part of the `no_patch_genuine` bucket is NOT a real give-up. This tool
reads each genuine attempt's TRANSCRIPT TAIL (the pi/claude session.jsonl, located
from the agent bundle stderr) and sub-classifies the terminal state:

    explored_no_edit  transcript ends mid-exploration, no edit tool ever called
                      -> CUT OFF before it started editing. RE-RUN candidate.
    prose_no_edit     final message DESCRIBES a finished patch (or emits raw
                      tool-call/harmony tokens as text) but no edit landed
                      -> tool-call/patch-capture gap. FIX HARNESS, then re-run.
    edited_but_lost   an edit tool WAS called and the model claims success, yet
                      git diff is empty (revert / wrong cwd / parser drop)
                      -> FIX HARNESS. A plain re-run likely repeats it.
    giveup            final message says it could not solve the task
                      -> GENUINE capability zero. Leave it.
    codex_rollout_err codex threw `failed to record rollout items` -> infra,
                      mislabeled as no-patch. RE-RUN (infra artifact).
    no_session        transcript not found -> inspect by hand.

Each bucket maps to one ACTION: rerun | fix-harness | fix-config | leave.

Usage:
    audit_no_patch.py                     # summary + per-cell listing
    audit_no_patch.py --action rerun      # only cells whose action is `rerun`
    audit_no_patch.py --out FILE.json     # write the per-cell classification
    audit_no_patch.py --mark-rerun explored_no_edit,codex_rollout_err
                                          # DRY-RUN: show the run_exclusion rows
    audit_no_patch.py --mark-rerun ... --apply
                                          # write them, so --fill re-runs the cells
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DB = os.path.join(REPO, "bench-db", "bench.db")
BLOBS = os.path.join(REPO, "bench-db", "blobs", "attempt")
MATRIX = os.path.join(REPO, "zbench-tasks", "agents-matrix.jsonl")
sys.path.insert(0, os.path.join(REPO, "zbench-tasks"))
sys.path.insert(0, REPO)
import scoring as S  # SINGLE-HOME no-patch classifier; do NOT re-implement it here


def _live_agents():
    """agent_ids still in the runnable matrix. A config_id NOT here was retired
    (e.g. the Foundry 429-throttle pause) -> `--fill` cannot reach it, so a re-run
    is impossible. We must NOT recommend retrying it."""
    live = set()
    if os.path.exists(MATRIX):
        for line in open(MATRIX, errors="replace"):
            line = line.strip()
            if not line:
                continue
            try:
                live.add(json.loads(line).get("agent_id"))
            except ValueError:
                pass
    return live

# tail sub-class -> the recommended action for that cell
ACTION = {
    "explored_no_edit": "rerun",       # cut off before editing; a re-run may land a patch
    "codex_rollout_err": "rerun",      # codex infra error, mislabeled no-patch
    "prose_no_edit": "fix-harness",    # tool-call/patch-capture gap (model "finished")
    "edited_but_lost": "fix-harness",  # edit ran, diff empty -> revert/cwd/parser drop
    "giveup": "leave",                 # genuine capability zero
    "no_session": "leave",             # cannot judge without the transcript
    "auth_fastfail": "fix-config",     # missing driver-shell key -> fix, THEN re-run
}

_GIVEUP = ("unable to", "cannot ", "could not fix", "couldn't", "no changes needed",
           "not able to", "i was unable", "cannot complete", "give up")
_CLAIM = ("implemented", "updated ", "added ", "applied", "the fix", "```diff",
          "```patch", "here is the", "modified", "successfully")
_EDIT_TOOL = ('"str_replace', '"edit"', '"write"', "apply_patch", "create_file",
              '"replace_string', "str_replace_editor")


# outcomes that mean "a patch was produced" (resolved OR a graded miss). A cell with
# ANY such attempt no longer needs a re-run -- an OLD no_patch there is SUPERSEDED.
PATCH_OUTCOMES = ("completed", "verification_tests_failed")


def _rows():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM attempt WHERE outcome='candidate_missing' "
            "OR status='no_patch_generated'")]
        excl = {r[0] for r in con.execute("SELECT evaluation_id FROM run_exclusion")}
        # cells (config_id, task_id) that ALREADY have a patch-producing attempt in
        # some run -> their no_patch rows are stale, NOT a coverage gap. Count cells,
        # not raw attempts, so a cell fixed by a later re-run is not re-flagged.
        covered = {(r["config_id"], r["task_id"]) for r in con.execute(
            "SELECT config_id, task_id FROM attempt WHERE outcome IN "
            f"({','.join('?' * len(PATCH_OUTCOMES))})", PATCH_OUTCOMES)}
        return rows, excl, covered
    finally:
        con.close()


def _io(ev):
    fp = os.path.join(BLOBS, ev, "agent_io.json")
    if not os.path.exists(fp):
        return {}
    try:
        return json.load(open(fp, errors="replace"))
    except (OSError, ValueError):
        return {}


def _session_path(io):
    """The pi/claude adapters log `session=/.../session.jsonl` to stderr."""
    for txt in (io.get("stderr") or "", json.dumps(io.get("agent_env") or {})):
        m = re.search(r"session=(\S+session\.jsonl)", txt)
        if m:
            return m.group(1)
    return None


def _tail_class(io):
    """Sub-classify a genuine no-patch by its transcript terminal state."""
    if "failed to record rollout items" in (io.get("stderr") or ""):
        return "codex_rollout_err", ""
    sp = _session_path(io)
    if not sp or not os.path.exists(sp):
        return "no_session", ""
    try:
        recs = [json.loads(l) for l in open(sp, errors="replace") if l.strip()]
    except (OSError, ValueError):
        return "no_session", ""
    edited = any(t in json.dumps(recs).lower() for t in _EDIT_TOOL)
    last = ""
    for r in reversed(recs):
        if r.get("type") != "message":
            continue
        m = r.get("message", {})
        if m.get("role") == "assistant":
            for c in (m.get("content") or []):
                if c.get("type") == "text" and c.get("text"):
                    last = c["text"]
                    break
            if last:
                break
    lo = last.lower()
    if edited:
        sig = "edited_but_lost"
    elif any(s in lo for s in _GIVEUP):
        sig = "giveup"
    elif any(s in lo for s in _CLAIM):
        sig = "prose_no_edit"
    else:
        sig = "explored_no_edit"
    return sig, last[:90].replace("\n", " ")


def audit():
    rows, excl, covered = _rows()
    budget = S.agent_budget_map()
    live = _live_agents()
    out = []
    for r in rows:
        cls = S.classify_attempt(r, budget.get(r["config_id"]))
        io = _io(r["evaluation_id"])
        # evidence pass can promote a genuine to an artifact (sub-canonical timeout /
        # output-cap) that the fact-only pass cannot see.
        ev_cls, ev_reason, _ = S.classify_no_patch_evidence(
            io.get("stderr") or "", r.get("output_tokens"))
        if cls == "artifact:auth":
            sub, tail = "auth_fastfail", ""
        elif ev_cls:
            sub, tail = "evidence:" + ev_cls.split(":")[1], ev_reason
        elif cls == "no_patch_genuine":
            sub, tail = _tail_class(io)
        else:
            sub, tail = cls.replace(":", "_"), ""     # artifact:budget / :infra
        action = ACTION.get(sub, "rerun" if sub.startswith(("evidence", "artifact"))
                            else "leave")
        # a retired/paused model cannot be re-run at all -> override the action so
        # the tool never tells you to retry an unreachable endpoint.
        reachable = r["config_id"] in live
        if not reachable and action in ("rerun", "fix-harness", "fix-config"):
            action = "blocked-unreachable"
        out.append({
            "evaluation_id": r["evaluation_id"], "config_id": r["config_id"],
            "task_id": r["task_id"], "run_id": r["run_id"], "class": cls,
            "subclass": sub, "action": action,
            "turns": r.get("turns"),
            "secs": int((r.get("total_duration_ms") or 0) / 1000),
            "excluded": r["evaluation_id"] in excl, "tail": tail,
            "reachable": reachable,
            # a later attempt for this cell already produced a patch -> this
            # no_patch is historical, the cell does NOT still need a re-run.
            "superseded": (r["config_id"], r["task_id"]) in covered,
        })
    return out


def _summary(res):
    print(f"NO-PATCH attempts: {len(res)}\n")
    print("By sub-class (-> action):")
    by = Counter(x["subclass"] for x in res)
    for k, n in by.most_common():
        exc = sum(1 for x in res if x["subclass"] == k and x["excluded"])
        print(f"  {n:>4}  {k:<18} -> {ACTION.get(k, '?'):<11}"
              f"  ({exc} already excluded/re-runnable)")
    print("\nBy action:")
    for k, n in Counter(x["action"] for x in res).most_common():
        print(f"  {n:>4}  {k}")


def _list(res):
    for x in sorted(res, key=lambda r: (r["action"], r["config_id"], r["task_id"])):
        flag = " [excl]" if x["excluded"] else ""
        flag += "" if x["reachable"] else " [unreachable]"
        print(f"  [{x['action']:<19}] {x['subclass']:<18} {x['config_id']:<28} "
              f"{x['task_id']}  t={x['turns'] or 0:>3} {x['secs']:>5}s "
              f"{x['evaluation_id'][:8]}{flag}")
        if x["tail"]:
            print(f"               tail: {x['tail']}")


def _mark_rerun(res, buckets, apply, only=None):
    # never flag an unreachable model (a re-run cannot reach it) or a cell that
    # already has an exclusion row (--fill will re-run it as-is). `only` is a
    # comma-list of config_id globs -> flag only those agents (e.g. the ones whose
    # credential/route is currently healthy).
    import fnmatch
    pats = [p.strip() for p in only.split(",")] if only else None

    def keep(cid):
        return not pats or any(fnmatch.fnmatch(cid, p) for p in pats)
    res = [x for x in res if keep(x["config_id"])]
    skipped = [x for x in res if x["subclass"] in buckets and not x["reachable"]]
    want = [x for x in res if x["subclass"] in buckets and not x["excluded"]
            and x["reachable"]]
    print(f"\n--mark-rerun {','.join(sorted(buckets))}: {len(want)} cell(s) to flag "
          f"({'APPLY' if apply else 'DRY-RUN'})")
    if skipped:
        print(f"  (skipped {len(skipped)} unreachable cell(s) -- retired/paused model)")
    for x in want:
        print(f"  + {x['config_id']:<28} {x['task_id']}  {x['evaluation_id'][:8]}")
    if not apply or not want:
        if not apply:
            print("  (dry-run — re-run with --apply to write run_exclusion rows)")
        return
    con = sqlite3.connect(DB)
    try:
        for x in want:
            con.execute(
                "INSERT OR IGNORE INTO run_exclusion"
                "(evaluation_id,reason,decided_by,decided_at) "
                "VALUES(?,?,?,datetime('now'))",
                (x["evaluation_id"], f"second-chance:{x['subclass']}",
                 "audit_no_patch"))
        con.commit()
    finally:
        con.close()
    print(f"  wrote {len(want)} run_exclusion row(s). "
          f"Now run: run_coverage_matrix.py --fill")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--action", help="list only cells with this action "
                    "(rerun|fix-harness|fix-config|leave)")
    ap.add_argument("--out", help="write per-cell JSON classification here")
    ap.add_argument("--mark-rerun", help="comma-list of sub-classes to flag for "
                    "re-run via run_exclusion (dry-run unless --apply)")
    ap.add_argument("--only", help="comma-list of config_id globs; with --mark-rerun, "
                    "flag only these agents (e.g. 'claude-cli-*')")
    ap.add_argument("--apply", action="store_true", help="actually write the rows")
    ap.add_argument("--include-superseded", action="store_true",
                    help="also show no_patch cells a later re-run already fixed "
                    "(default: hide them -- they are not a coverage gap)")
    args = ap.parse_args()

    res = audit()
    if args.out:                       # JSON keeps EVERY row (with the flags)
        json.dump(res, open(args.out, "w"), indent=2)
        print(f"wrote {len(res)} rows -> {args.out}", file=sys.stderr)

    hidden = sum(1 for x in res if x["superseded"])
    if not args.include_superseded:
        res = [x for x in res if not x["superseded"]]

    if args.mark_rerun:
        _mark_rerun(res, set(args.mark_rerun.split(",")), args.apply, args.only)
        return
    if args.action:
        res = [x for x in res if x["action"] == args.action]
        _list(res)
        return
    _summary(res)
    if not args.include_superseded and hidden:
        print(f"\n(hid {hidden} no_patch cell(s) a later re-run already fixed; "
              f"--include-superseded to show them)")
    print()
    _list(res)


if __name__ == "__main__":
    main()
