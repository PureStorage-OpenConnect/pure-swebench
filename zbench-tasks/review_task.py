#!/usr/bin/env python3
"""Human-review gate for the ranked board (Databricks 'evaluate each sample by hand').

Oracle VALID is a machine gate; a task can flip correctly and still be a poor benchmark
item -- a leaky problem statement, an under-specified goal, an incidental/renamey change
the screens missed. So a task enters the RANKED set (corpus.ranked_ids) only after a
human reviews its card + gold patches and signs off here.

    review_task.py <task_id>            # show the card + f2p/p2p, then prompt
    review_task.py <task_id> --approve  # stamp reviewed_by/reviewed_at (non-interactive)
    review_task.py <task_id> --reject "reason"   # mark reviewed-rejected (drops from ranked)
    review_task.py --list-pending       # oracle-validated tasks awaiting review

Sets meta.review.reviewed_by / reviewed_at / review_decision. Idempotent; re-approving
updates the stamp. Never touches curation_status (that stays the oracle verdict); the
ranked gate reads meta.review.reviewed_by.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from zbench import constants                       # noqa: E402

TASKS = HERE / "tasks"


def _meta_path(task_id: str) -> Path:
    return TASKS / task_id / "meta.json"


def list_pending() -> list[str]:
    out = []
    for mp in sorted(TASKS.glob("*/meta.json")):
        m = json.loads(mp.read_text())
        if m.get("curation_status") == "validated" and not (m.get("review") or {}).get("reviewed_by"):
            out.append(m["task_id"])
    return out


def show(task_id: str) -> dict:
    td = TASKS / task_id
    m = json.loads((_meta_path(task_id)).read_text())
    print(f"=== {task_id} :: {m.get('summary','')}")
    print(f"lang={m.get('lang')}  issue=#{m.get('issue')}  status={m.get('curation_status')}  "
          f"tier={(m.get('contamination') or {}).get('tier')}  complexity={m.get('complexity')}")
    print(f"fix: {(m.get('source') or {}).get('commit_url')}")
    print(f"f2p: {m.get('fail_to_pass')}")
    print(f"p2p: {m.get('pass_to_pass')}")
    card = td / "card.md"
    if card.exists():
        print("\n--- card.md ---")
        print(card.read_text())
    ps = td / "problem_statement.md"
    if ps.exists():
        print("--- problem_statement.md (agent-visible; check for leaks) ---")
        print(ps.read_text())
    return m


def stamp(task_id: str, decision: str, reviewer: str, note: str = "") -> None:
    mp = _meta_path(task_id)
    m = json.loads(mp.read_text())
    review = m.get("review") or {}
    review["reviewed_by"] = reviewer
    review["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    review["review_decision"] = decision          # "approved" | "rejected"
    if note:
        review["review_note"] = note
    m["review"] = review
    # a rejection keeps the oracle verdict but bumps curation_status out of the
    # candidate set so it never ranks and is visibly a human call.
    if decision == "rejected":
        m["curation_status"] = "held"
        m["reason_code"] = "human_review_rejected"
        m["reason"] = note or "rejected in human review"
    mp.write_text(json.dumps(m, indent=2) + "\n")
    print(f"{task_id}: {decision} by {reviewer}"
          + (f" -> curation_status=held" if decision == "rejected" else " (now ranked-eligible)"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("task_id", nargs="?")
    ap.add_argument("--approve", action="store_true")
    ap.add_argument("--reject", metavar="REASON")
    ap.add_argument("--list-pending", action="store_true")
    ap.add_argument("--reviewer", default=None, help="defaults to ZBENCH_OPERATOR / login user")
    a = ap.parse_args()

    if a.list_pending:
        pending = list_pending()
        print(f"{len(pending)} oracle-validated task(s) awaiting human review:")
        for t in pending:
            print(f"  {t}")
        return 0
    if not a.task_id:
        ap.error("need <task_id> (or --list-pending)")
    if not _meta_path(a.task_id).exists():
        sys.exit(f"no such task: {a.task_id}")

    reviewer = a.reviewer or constants.operator()
    if a.reject is not None:
        stamp(a.task_id, "rejected", reviewer, a.reject)
        return 0
    if a.approve:
        stamp(a.task_id, "approved", reviewer)
        return 0
    # interactive
    show(a.task_id)
    ans = input("\napprove for the ranked board? [y/N/reject <reason>] ").strip()
    if ans.lower() in ("y", "yes"):
        stamp(a.task_id, "approved", reviewer)
    elif ans.lower().startswith("reject"):
        stamp(a.task_id, "rejected", reviewer, ans[6:].strip() or "rejected in review")
    else:
        print("no change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
