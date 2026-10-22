#!/usr/bin/env python3
"""Recompute every task's contamination block from agents-meta.jsonl cutoffs.

METHODOLOGY section 5: tiers are recomputable whenever the cohort or a training
cutoff changes. This walks tasks/*/meta.json, re-derives fix_public_at from the
fix commit's committer date (the recorded visibility basis), preserves any
previously fetched issue_created_at, and rewrites meta.contamination via the
same contamination_block() prepare_task uses at curation time.

    recompute_tiers.py [--dry-run]

Exits 1 (without writing anything) if any active agent still lacks a
training_cutoff -- the fail-loud rule from METHODOLOGY: tiers stay UNKNOWN
rather than being computed from a partial cohort.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from config import ZULIP_REPO  # noqa: E402
from prepare_task import cohort_cutoff, contamination_block  # noqa: E402

TASKS = HERE / "tasks"


def committer_date(sha: str) -> str:
    r = subprocess.run(["git", "-C", str(ZULIP_REPO), "show", "-s", "--format=%cs", sha],
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cutoff, missing = cohort_cutoff()
    if missing:
        print(f"FATAL: {len(missing)} active agents lack a training_cutoff: {missing}")
        print("Fill agents-meta.jsonl (training_cutoff/cutoff_source/cutoff_confidence) first.")
        return 1
    print(f"cohort max cutoff: {cutoff}")

    counts: Counter[tuple[str, str]] = Counter()
    for mp in sorted(TASKS.glob("*/meta.json")):
        m = json.loads(mp.read_text())
        if not m.get("fix_commit"):
            continue
        old = m.get("contamination") or {}
        block = contamination_block(committer_date(m["fix_commit"]), old.get("issue_created_at"))
        m["contamination"] = block
        counts[(m.get("curation_status", "?"), block["tier"])] += 1
        print(f"{m['task_id']}  {m.get('curation_status', '?'):9s}  "
              f"fix={block['fix_public_at']}  tier={block['tier']}")
        if not args.dry_run:
            mp.write_text(json.dumps(m, indent=2) + "\n")

    print("\nstatus x tier:")
    for (status, tier), n in sorted(counts.items()):
        print(f"  {status:9s} {tier}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
