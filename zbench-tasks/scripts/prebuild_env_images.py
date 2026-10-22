#!/usr/bin/env python3
"""Pre-build the docker env images a corpus subset needs, before any eval runs.

Grading NEVER builds an image on demand -- `zbench/workflow.py` treats a missing
`zbench-env:<fp>` as an infra failure and parks the cell. The corpus pipeline
(prepare_task / batch_prepare / oracle_validate) builds images as a side effect of
judging new candidates, so on the machine that mined the corpus they already exist.
A FRESH machine that clones this repo gets the task records but NO images -- this
script closes that gap.

Tasks are grouped by env fingerprint (many tasks share one image), so the build count
is far below the task count. Safe by default: prints the plan and exits; `--go` builds.

  prebuild_env_images.py                      # plan for the whole validated corpus
  prebuild_env_images.py --limit 5 --go       # build enough for a 5-task run
  prebuild_env_images.py --backend-only --go  # python tasks only

Exit: 0 all present/built | 70 script error | 75 one or more builds hit infra.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS_DIR = HERE.parent
sys.path.insert(0, str(TASKS_DIR))

import config  # noqa: E402  (needs the sys.path insert above)
from corpus import load_corpus  # noqa: E402

# Observed on this box (2026-08-15): 120 images, 4.39-4.93 GB each.
EST_GB_PER_IMAGE = 4.7
EST_MIN_PER_BUILD = 12


def _plan(status, task_ids, lang, limit):
    """-> (rows, groups) where groups is [(fp, base_commit, [task_id, ...]), ...]."""
    rows = load_corpus(status)
    if lang:
        rows = [r for r in rows if r["lang"] == lang]
    if task_ids:
        globs = [g.strip() for g in task_ids.split(",") if g.strip()]
        rows = [r for r in rows if any(fnmatch.fnmatch(r["id"], g) for g in globs)]
    if limit:
        rows = rows[:limit]

    groups: dict[str, dict] = {}
    for r in rows:
        m = json.loads((TASKS_DIR / "tasks" / r["id"] / "meta.json").read_text())
        fp, base = m.get("env_fingerprint"), m.get("base_commit")
        if not fp or not base:
            print(f"  !! {r['id']}: meta.json lacks env_fingerprint/base_commit -- skipped")
            continue
        g = groups.setdefault(fp, {"fp": fp, "base": base, "tasks": []})
        g["tasks"].append(r["id"])
    return rows, [(g["fp"], g["base"], g["tasks"]) for g in
                  sorted(groups.values(), key=lambda g: -len(g["tasks"]))]


def _have_image(fp: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", f"{config.ENV_IMAGE_PREFIX}:{fp}"],
                          capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", default="validated", help="curation_status filter (default: validated)")
    ap.add_argument("--task-ids", help="comma-separated task-id globs, e.g. 'ZT-13*'")
    ap.add_argument("--limit", type=int, default=0, help="first N tasks (stable order)")
    ap.add_argument("--backend-only", action="store_true", help="python tasks only")
    ap.add_argument("--web-only", action="store_true", help="web tasks only")
    ap.add_argument("--repo", default=str(config.ZULIP_REPO), help="target Zulip clone")
    ap.add_argument("--go", action="store_true", help="actually build (default: plan only)")
    a = ap.parse_args()

    if a.backend_only and a.web_only:
        print("--backend-only and --web-only are mutually exclusive", file=sys.stderr)
        return 70
    lang = "py" if a.backend_only else ("web" if a.web_only else None)

    repo = Path(a.repo).expanduser()
    if not (repo / ".git").is_dir():
        print(f"no git clone at {repo} -- set ZBENCH_TARGET_REPO or pass --repo", file=sys.stderr)
        return 70

    rows, groups = _plan(a.status, a.task_ids, lang, a.limit)
    if not groups:
        print("no tasks matched the selection -- nothing to build")
        return 0

    missing = [g for g in groups if not _have_image(g[0])]
    have = len(groups) - len(missing)
    free_gb = shutil.disk_usage(repo).free / 1e9
    need_gb = len(missing) * EST_GB_PER_IMAGE

    print("== env image plan ==")
    print(f"  tasks selected      : {len(rows)}")
    print(f"  distinct fingerprints: {len(groups)}  (already built: {have} | to build: {len(missing)})")
    print(f"  estimated disk       : {need_gb:.0f} GB   (free now: {free_gb:.0f} GB)")
    print(f"  estimated time       : {len(missing) * EST_MIN_PER_BUILD / 60:.1f} h serial "
          f"(~{EST_MIN_PER_BUILD} min/image)")
    if need_gb > free_gb:
        print(f"  !! WARNING: estimate exceeds free disk. Build a subset (--limit / --task-ids),\n"
              f"     or reclaim with zbench-tasks/scripts/gc_env_images.sh")
    for fp, base, tasks in missing:
        print(f"    {fp}  base {base[:12]}  covers {len(tasks)} task(s)")

    if not a.go:
        print("\n(plan only -- re-run with --go to build)")
        return 0
    if not missing:
        print("\nall images already present -- nothing to do")
        return 0

    failed = []
    for i, (fp, base, tasks) in enumerate(missing, 1):
        print(f"\n[{i}/{len(missing)}] building {config.ENV_IMAGE_PREFIX}:{fp} "
              f"(base {base[:12]}, {len(tasks)} task(s))", flush=True)
        try:
            # Output streams live (a build is ~12 min); 3600 s is the same per-image
            # ceiling batch_prepare.py uses.
            rc = subprocess.run(["bash", str(HERE / "build_env_image.sh"), base,
                                 "--repo", str(repo)], timeout=3600).returncode
        except subprocess.TimeoutExpired:
            rc = 75
            print("  TIMED OUT after 3600s")
        if rc != 0:
            print(f"  FAILED rc={rc} for fp {fp} (base {base[:12]})")
            failed.append((fp, rc))

    built = len(missing) - len(failed)
    print(f"\n== done: {built} built, {len(failed)} failed ==")
    for fp, rc in failed:
        print(f"  {fp}: rc={rc}")
    return 75 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
