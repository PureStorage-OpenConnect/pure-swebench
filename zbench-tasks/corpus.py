#!/usr/bin/env python3
"""Single source of truth for zbench candidate/task records.

`tasks/<task_id>/` is the canonical record set for judged candidates. Each directory
has a `meta.json` with a normalized `curation_status`:
  * validated = oracle-sound; active ranked benchmark corpus
  * held      = plausible candidate; review/oracle/scope still pending
  * invalid   = oracle checked and did not satisfy FAIL@base/PASS@fix
  * dropped   = rejected in curation (coupling/feature/refactor/plumbing/etc.)

The active corpus is DERIVED as `curation_status == "validated"`; there is no
separate corpus list to hand-maintain.
"""
import json, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"


def load_corpus(status="validated", tasks_dir=None):
    """Return the corpus as a list of dicts, sorted by task id.

    status: filter by curation_status. "validated" (default) = the ranked corpus.
            Pass "*" / None for all candidate/task records (each dict carries its status).
    Each row: {task_id, id, lang, instance (abs path or None),
               summary, status}.
    """
    tdir = Path(tasks_dir) if tasks_dir else TASKS
    rows = []
    for d in sorted(os.listdir(tdir)):
        # a task record = any directory with a meta.json (task ids are opaque)
        mp = tdir / d / "meta.json"
        if not mp.exists():
            continue
        m = json.loads(mp.read_text())
        st = m.get("curation_status")
        if status not in (None, "*") and st != status:
            continue
        lang = m.get("lang") or "py"          # py (backend) | web (node tests)
        inst = tdir / d / "instance.jsonl"
        review = m.get("review") or {}
        rows.append({
            "task_id": d,
            "id": d,
            "lang": lang,
            "instance": str(inst) if inst.exists() else None,
            "summary": (m.get("summary") or "")[:100],
            "status": st,
            # human-review gate (Databricks best practice): oracle VALID is a machine
            # gate; the RANKED board additionally requires a human sign-off. Absent =
            # unreviewed (a directional candidate), never silently ranked.
            "reviewed": bool(review.get("reviewed_by")),
            "complexity": m.get("complexity"),
        })
    return rows


def validated_ids(tasks_dir=None):
    """Sorted task ids of the oracle-validated corpus (the CANDIDATE set: machine
    gate only, may include unreviewed tasks)."""
    return [r["id"] for r in load_corpus("validated", tasks_dir)]


def ranked_ids(tasks_dir=None):
    """Sorted task ids eligible for the RANKED board: oracle-validated AND
    human-reviewed. Empty until a reviewer signs off (see review_task.py). This is the
    Databricks 'evaluate each sample by hand' gate -- a task can flip correctly and
    still be a bad benchmark item (leaky statement, under-specified, incidental)."""
    return [r["id"] for r in load_corpus("validated", tasks_dir) if r["reviewed"]]


def ids_by_lang(lang, status="validated", tasks_dir=None):
    return {r["id"] for r in load_corpus(status, tasks_dir) if r["lang"] == lang}


if __name__ == "__main__":
    import argparse, collections
    ap = argparse.ArgumentParser(description="Show the derived zbench corpus.")
    ap.add_argument("--status", default="validated", help='curation_status filter, or "*" for all')
    args = ap.parse_args()
    rows = load_corpus(args.status)
    dist = collections.Counter(r["status"] for r in load_corpus("*"))
    print(f"curation_status distribution (all candidate/task records): {dict(dist)}")
    by_lang = collections.Counter(r["lang"] for r in rows)
    print(f"\n{args.status} corpus: {len(rows)} tasks "
          f"({', '.join(f'{n} {l}' for l, n in sorted(by_lang.items()))})")
    for r in rows:
        inst = "inst" if r["instance"] else "NO-INST"
        print(f"  {r['task_id']:16} {r['lang']:3} [{inst}] {r['summary'][:60]}")
