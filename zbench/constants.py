"""zbench identity constants + tiny helpers -- the single home for name-shaped policy.

Everything that turns a task id into another form (instance id, slot key, tracker URL)
lives here so the format is defined exactly once. Task ids are OPAQUE strings to the
harness (`ZT-<sha12>` by convention, set by the corpus pipeline); nothing in zbench/
may assume an inner structure beyond "no slashes".
"""
from __future__ import annotations

import getpass
import os

INSTANCE_PREFIX = "zbench_"          # instance_id = INSTANCE_PREFIX + task_id
WORK_BRANCH = "zbench-work"          # throwaway branch inside the isolated checkout
WORKTREE_PREFIX = "zbench_wt_"       # per-attempt worktree dir prefix
GIT_IDENT_EMAIL = "zbench@zbench.local"
GIT_IDENT_NAME = "zbench"
TARGET_REPO_URL = "https://github.com/zulip/zulip"


def task_of(instance_id: str) -> str:
    """`zbench_ZT-x` (or already-bare `ZT-x`) -> the bare task id (idempotent)."""
    return instance_id[len(INSTANCE_PREFIX):] if instance_id.startswith(INSTANCE_PREFIX) \
        else instance_id


def instance_of(task_id: str) -> str:
    """Bare task id -> instance id (idempotent)."""
    return task_id if task_id.startswith(INSTANCE_PREFIX) else INSTANCE_PREFIX + task_id


def cell_key(task_id: str, config_id: str) -> str:
    """The liveness/slot cell key for (task, agent config). One format, everywhere."""
    return f"{INSTANCE_PREFIX}{task_id}_{config_id}"


def tracker_url(meta: dict) -> str:
    """Best upstream link for a task: PR > issue > fix commit > repo root."""
    src = meta.get("source") or {}
    if src.get("issue_url"):
        return src["issue_url"]
    if src.get("commit_url"):
        return src["commit_url"]
    if meta.get("issue"):
        return f"{TARGET_REPO_URL}/issues/{meta['issue']}"
    if meta.get("fix_commit"):
        return f"{TARGET_REPO_URL}/commit/{meta['fix_commit']}"
    return TARGET_REPO_URL


def operator() -> str:
    """Who is annotating/excluding: ZBENCH_OPERATOR env, else the login user."""
    return os.environ.get("ZBENCH_OPERATOR") or getpass.getuser()
