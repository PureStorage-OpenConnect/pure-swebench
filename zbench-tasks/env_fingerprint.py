#!/usr/bin/env python3
"""Provision fingerprint of a Zulip tree: sha256 over the git blob-ids of FP_FILES.

Usage:
  env_fingerprint.py <base_commit> [--repo PATH]     # from a rev in the target clone
  env_fingerprint.py --worktree DIR                  # from a checkout's HEAD (the
                                                     # isolated worktree: HEAD IS base)

Prints 12 hex chars. Tasks whose base commits share a fingerprint share one
provisioned docker image (zbench-env:<fp>).
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import FP_FILES, ZULIP_REPO  # noqa: E402


def fingerprint(repo: Path, rev: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), "ls-tree", rev, "--", *FP_FILES],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"env_fingerprint: git ls-tree failed in {repo} at {rev}: {r.stderr.strip()}")
    if not r.stdout.strip():
        sys.exit(f"env_fingerprint: no FP_FILES found at {rev} in {repo} -- wrong repo?")
    return hashlib.sha256(r.stdout.encode()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base_commit", nargs="?", help="rev in the target clone")
    ap.add_argument("--repo", default=str(ZULIP_REPO))
    ap.add_argument("--worktree", help="fingerprint a checkout's HEAD instead")
    a = ap.parse_args()
    if a.worktree:
        print(fingerprint(Path(a.worktree), "HEAD"))
    elif a.base_commit:
        print(fingerprint(Path(a.repo).expanduser(), a.base_commit))
    else:
        ap.error("need <base_commit> or --worktree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
