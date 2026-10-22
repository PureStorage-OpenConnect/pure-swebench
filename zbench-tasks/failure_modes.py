#!/usr/bin/env python3
"""Failure-mode catalog generator: bucket every non-resolved `attempt` in bench.db
by why it did not resolve, and surface the invalidation / re-run candidates
(latest-for-cell artifacts: auth fast-fail, old-budget, infra). This is the LIVE
source for the failure taxonomy (the task-invalid vs run-invalid theory lives in
../METHODOLOGY.md section 3).

Read-only over bench.db.

Usage: python3 failure_modes.py [--db PATH] [--ranked-only]
The ranked-agent set + validated corpus come from the SAME sources the board uses
(agents-matrix.jsonl + meta.json curation_status=validated), so "ranked x corpus"
filtering matches the leaderboard.
"""
from __future__ import annotations
import argparse
import collections
import json
import os
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring as S  # shared classifier (SoT) -- W23

DEFAULT_DB = Path(os.environ.get(
    "ZBENCH_BENCHDB_DIR",
    str(HERE.parent / "bench-db"))) / "bench.db"


def _ranked_agents():
    f = HERE / "agents-matrix.jsonl"
    out = set()
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line:
                out.add(json.loads(line)["agent_id"])
    return out


def _validated_corpus():
    out = set()
    for meta in (HERE / "tasks").glob("*/meta.json"):
        try:
            m = json.loads(meta.read_text())
        except Exception:
            continue
        if m.get("curation_status") == "validated":
            out.add(m.get("task_id") or meta.parent.name)
    return out


def _rt_s(r):
    ms = r["runtime_ms"] or r["total_duration_ms"] or 0
    return ms / 1000.0


# Classification delegates to the shared SoT (scoring.classify_attempt).
ARTIFACTS = set(S.ARTIFACT_CLASSES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--ranked-only", action="store_true",
                    help="restrict candidate list to ranked agents x validated corpus")
    a = ap.parse_args()
    db = Path(a.db)
    if not db.exists():
        sys.exit(f"no bench.db at {db}")
    conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # facts-only: no harness_config dim -> budget comes from agents-meta.jsonl.
    rows = list(conn.execute(
        "SELECT a.config_id, a.task_id, a.run_id, a.status, a.outcome, a.tests_passed, "
        "a.runtime_ms, a.total_duration_ms, a.output_tokens, a.finished_at, "
        "rx.evaluation_id IS NOT NULL AS excluded "
        "FROM attempt a LEFT JOIN run_exclusion rx USING(evaluation_id)"))
    conn.close()
    _budget = S.agent_budget_map()

    cells = collections.defaultdict(list)
    for r in rows:
        cells[(r["config_id"], r["task_id"])].append(r)

    def latest(key):
        return sorted(cells[key], key=lambda r: str(r["finished_at"]))[-1]

    ranked = _ranked_agents()
    corpus = _validated_corpus()
    print(f"bench.db: {db}")
    print(f"attempts: {len(rows)} | cells: {len(cells)} | "
          f"ranked agents: {len(ranked)} | validated corpus: {len(corpus)}\n")

    counts = collections.Counter()
    candidates = []
    for r in rows:
        key = (r["config_id"], r["task_id"])
        is_latest = latest(key)["finished_at"] == r["finished_at"]
        cls = S.classify_attempt(r, _budget.get(r["config_id"]))
        counts[cls] += 1
        if cls in ARTIFACTS and is_latest and not r["excluded"]:
            ranked_hit = (r["config_id"] in ranked) and (r["task_id"] in corpus)
            if a.ranked_only and not ranked_hit:
                continue
            candidates.append((cls, r, ranked_hit))

    print("=== bucket counts (all attempts) ===")
    for k, v in counts.most_common():
        print(f"  {v:4d}  {k}")

    print("\n=== invalidation / re-run candidates (latest-for-cell artifacts) ===")
    candidates.sort(key=lambda t: (not t[2], t[0], t[1]["task_id"], t[1]["config_id"]))
    for cls, r, ranked_hit in candidates:
        tag = "RANKEDxCORPUS" if ranked_hit else "(non-ranked/non-corpus)"
        print(f"  [{tag:22s}] {cls:15s} {r['config_id']:24s} {r['task_id']:14s} "
              f"rt={_rt_s(r):6.0f}s run={r['run_id']}")
    print(f"\n  {sum(1 for c in candidates if c[2])} ranked x corpus candidates; "
          f"{len(candidates)} total shown")


if __name__ == "__main__":
    main()
