"""Shared agent patch capture (ported from the fork): run the agent in a repo checkout
and recover its diff -- COMMITTED or uncommitted -- against a baseline sha.

Diffing the pre-agent baseline (not HEAD) is the key correctness point: agents frequently
`git commit`, which advances HEAD, so `git diff HEAD` would be empty and the committed fix
lost. The single shared implementation (pi + claude both route through it) fixed a class
of silent patch-loss bugs (finding #26).
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

LOGGER = logging.getLogger(__name__)

# A fixed local identity so neither our snapshot commit NOR the agent's own `git commit`
# fails with "Please tell me who you are" on an identity-less checkout.
_GIT_ID = ["-c", "user.email=zbench@zbench.local", "-c", "user.name=zbench"]


def _git(args, cwd: Path, check: bool = False):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def capture_git_patch(repo_root, run_agent: Callable[[], dict | None], *,
                      logger: logging.Logger = LOGGER) -> tuple[str, dict]:
    """Run `run_agent()` in `repo_root` and return (patch_text, token_usage).

    `run_agent`: zero-arg callable that invokes the agent CLI in repo_root and returns a
    token-usage dict (or None). It MAY raise (timeout/CLI error); any patch it already
    left (committed or not) is still recovered, and the error is surfaced only when NO
    patch was produced. Raises if the agent made no changes.
    """
    repo_root = Path(repo_root).resolve()
    if not repo_root.exists():
        raise RuntimeError(f"Repository root does not exist: {repo_root}")
    if not (repo_root / ".git").exists():
        _git(["init"], repo_root, check=True)
        _git(["add", "."], repo_root, check=True)
        _git([*_GIT_ID, "commit", "-m", "Initial"], repo_root, check=True)

    # Snapshot any pre-existing working-tree state so the agent's diff is isolated.
    _git(["add", "-A"], repo_root, check=True)
    if _git(["diff", "--cached", "--quiet"], repo_root).returncode != 0:
        _git([*_GIT_ID, "commit", "-m", "pre-agent"], repo_root, check=True)

    # Baseline AFTER the pre-agent commit, BEFORE running the agent -> captures committed
    # AND uncommitted edits.
    base_head = _git(["rev-parse", "HEAD"], repo_root, check=True).stdout.strip()

    token_usage: dict = {}
    run_error: Exception | None = None
    try:
        token_usage = run_agent() or {}
    except Exception as e:  # recover any patch first
        run_error = e

    # Stage everything first: `git diff <base>` alone ignores UNTRACKED files, so an
    # agent that creates a new file without committing would silently lose it.
    _git(["add", "-A"], repo_root)
    # `--binary` so a patch that adds/changes a BINARY asset (svg/png/icon) carries its
    # content, not a "Binary files differ" stub that later fails `git apply`. Matches the
    # provenance capture in zbench/provenance.py; without it, any asset-adding patch is
    # silently unappliable and mis-scored as patch_apply_failed.
    diff = _git(["diff", "--binary", base_head], repo_root)
    if diff.returncode != 0:
        raise RuntimeError(f"Failed to generate diff: {diff.stderr}")
    patch_text = diff.stdout
    logger.info("agent git diff length: %s chars", len(patch_text))

    _git(["reset", "--hard", base_head], repo_root)  # harness applies the patch itself

    if patch_text.strip():
        if run_error is not None:
            logger.warning("agent exited with %r but left a patch; using the patch", run_error)
        return patch_text, token_usage
    if run_error is not None:
        raise run_error
    raise RuntimeError("agent made no changes")
