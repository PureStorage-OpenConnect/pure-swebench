#!/usr/bin/env python3
"""Backfill the deterministic quality fields (complexity, author, scope) onto existing
tasks, so the corpus built before these gates is consistent with tasks built after.

    backfill_quality.py [--repo P] [--apply]

Without --apply: dry-run report only. With --apply: writes meta.json in place --
- adds meta.complexity (quality.complexity from gold_code.patch + f2p count)
- adds meta.author {name,email,date} from the fix commit, and meta.author_flagged +
  a review note if the author is a bot/service account or the message has an AI trailer
- flags (does NOT auto-drop) validated tasks that violate the scope gate, so a human
  sees them in review rather than silently keeping an oversized task.

Only touches existing dirs (safe alongside a running batch, which only creates new ones).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import quality  # noqa: E402
from config import ZULIP_REPO  # noqa: E402

TASKS = HERE / "tasks"


def _author(repo: Path, sha: str) -> dict:
    r = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%an%x1f%ae%x1f%aI", sha],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    name, email, date = (r.stdout.strip().split("\x1f") + ["", "", ""])[:3]
    return {"name": name, "email": email, "date": date}


def _message(repo: Path, sha: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%B", sha],
                          capture_output=True, text=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ZULIP_REPO))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo).expanduser()

    buckets: Counter = Counter()
    flagged_authors, scope_flags = [], []
    n = 0
    for mp in sorted(TASKS.glob("*/meta.json")):
        m = json.loads(mp.read_text())
        td = mp.parent
        gp = config.gold_code_path(td)
        if not gp.exists():
            continue                                    # meta-only drop stub
        n += 1
        gold = gp.read_text(errors="replace")
        f2p = len(m.get("fail_to_pass") or [])
        cx = quality.complexity(gold, f2p)
        m["complexity"] = cx
        buckets[cx["bucket"]] += 1

        sha = m.get("fix_commit")
        if sha:
            m["author"] = _author(repo, sha)
            reason = quality.excluded_author(m["author"].get("name", ""), m["author"].get("email", ""))
            if not reason and quality.has_ai_trailer(_message(repo, sha)):
                reason = "ai_generated_trailer"
            if reason:
                m["author_flagged"] = reason
                flagged_authors.append((m["task_id"], reason, m.get("curation_status")))
                # consistency with the new mining policy: a bot/service/AI-authored commit
                # is NOT an eligible task. Demote it out of the candidate/ranked corpus
                # (it slipped in before the author filter existed).
                if m.get("curation_status") in ("validated", "held"):
                    m["curation_status"] = "dropped"
                    m["reason_code"] = reason
                    m["reason"] = f"author provenance: {reason} (retro-excluded)"

        # scope: flag validated tasks that violate the gate (for human review; don't auto-drop)
        code_files = [f for f in _touched(repo, sha) if _is_code(f)] if sha else []
        sv = quality.scope_violation(code_files, gold) if code_files else None
        if sv and m.get("curation_status") == "validated":
            m.setdefault("review", {})["scope_warning"] = sv
            scope_flags.append((m["task_id"], sv))

        if a.apply:
            mp.write_text(json.dumps(m, indent=2) + "\n")

    print(f"{'APPLIED' if a.apply else 'DRY-RUN'} over {n} tasks with gold patches")
    print(f"complexity buckets: {dict(buckets)}")
    print(f"author-flagged (bot/service/AI): {len(flagged_authors)}")
    for t, r, st in flagged_authors:
        print(f"  {t}  {r}  (status={st})")
    print(f"scope-warned validated tasks: {len(scope_flags)}")
    for t, sv in scope_flags:
        print(f"  {t}  {sv}")
    return 0


def _touched(repo: Path, sha: str) -> list:
    return [f for f in subprocess.run(
        ["git", "-C", str(repo), "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        capture_output=True, text=True).stdout.splitlines() if f.strip()]


def _is_code(p: str) -> bool:
    from config import classify_file
    return classify_file(p) in ("py_code", "web_code")


if __name__ == "__main__":
    raise SystemExit(main())
