#!/usr/bin/env python3
"""Batch-prepare zbench tasks from mined candidates.

    batch_prepare.py [--since DATE] [--until DATE] [--limit N] [--fast-oracle]

Mines candidates (mine_candidates.predicate), groups them by env fingerprint so each
image builds ONCE before its group runs, then prepares each candidate sequentially
(prepare_task.py). Honors the exit trichotomy: 75 (infra) aborts the batch -- fix the
environment and re-run (already-judged candidates are skipped by the dedup ledger);
70 (script error) records the failure and continues; anything else judged the task.

Full (flake-gated) oracle by default; --fast-oracle only for development smoke.
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
from config import MIN_COMMIT_DATE, ZULIP_REPO  # noqa: E402
from env_fingerprint import fingerprint          # noqa: E402
from mine_candidates import mine                 # noqa: E402

TASKS = HERE / "tasks"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=MIN_COMMIT_DATE)
    ap.add_argument("--until", default=None)
    ap.add_argument("--limit", type=int, default=0, help="stop after N judged candidates")
    ap.add_argument("--fast-oracle", action="store_true")
    ap.add_argument("--redo-dropped", action="store_true",
                    help="also re-judge candidates previously dropped/invalid/held "
                         "(screens/pipeline changed); validated tasks always skipped")
    ap.add_argument("--repo", default=str(ZULIP_REPO))
    a = ap.parse_args()
    repo = Path(a.repo).expanduser()

    todo = []
    for c in mine(repo, a.since, a.until):
        d = TASKS / f"ZT-{c['sha12']}"
        if d.exists():                                  # judged already (the ledger)
            if not a.redo_dropped:
                continue
            try:
                st = json.loads((d / "meta.json").read_text()).get("curation_status")
            except (json.JSONDecodeError, OSError):
                st = None
            if st not in ("dropped", "invalid", "held"):
                continue
        todo.append((fingerprint(repo, c["parent"]), c))
    todo.sort(key=lambda t: t[0])                       # group by fingerprint
    if a.limit:
        todo = todo[:a.limit]
    print(f"batch: {len(todo)} unjudged candidates across "
          f"{len({fp for fp, _ in todo})} fingerprints", flush=True)

    outcomes: Counter = Counter()
    built: set[str] = set()
    for i, (fp, c) in enumerate(todo, 1):
        if fp not in built:
            print(f"[{i}/{len(todo)}] ensuring env image zbench-env:{fp} "
                  f"(base {c['parent'][:12]})", flush=True)
            b = subprocess.run(["bash", str(HERE / "scripts" / "build_env_image.sh"),
                                c["parent"], "--repo", str(repo)],
                               capture_output=True, text=True, timeout=3600)
            if b.returncode != 0:
                print(f"  IMAGE BUILD FAILED rc={b.returncode}: {b.stdout[-200:]} "
                      f"{b.stderr[-200:]}", flush=True)
                outcomes["image_build_failed"] += 1
                continue
            built.add(fp)
        cmd = [sys.executable, str(HERE / "prepare_task.py"), c["hash"], "--repo", str(repo)]
        if a.fast_oracle:
            cmd.append("--fast-oracle")
        if a.redo_dropped:
            cmd.append("--redo")
        print(f"[{i}/{len(todo)}] prepare ZT-{c['sha12']} ({c['lang']}, #{c['issue']}) "
              f"{c['subject'][:60]}", flush=True)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        line = (r.stdout.strip().splitlines() or ["?"])[-1]
        print(f"    -> {line}", flush=True)
        if r.returncode == 75:
            print(f"BATCH ABORT (infra): {r.stderr[-300:]}", flush=True)
            break
        outcomes["script_error" if r.returncode == 70 else line.split(":")[-1].split("(")[0].strip()] += 1

    print("\nbatch outcomes:", dict(outcomes), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
