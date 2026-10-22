"""zbench corpus-pipeline config -- every Zulip-specific tunable in one place.

The harness (zbench/) never imports this; it reaches the pipeline only through the
instance.jsonl contract (commands.tests shell strings + $ZBENCH_SCRIPTS).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# --- target repo -------------------------------------------------------------------
# A FULL local clone (worktrees + `git show <sha>:<path>` need blobs).
ZULIP_REPO = Path(os.environ.get("ZBENCH_TARGET_REPO", "~/work/zulip")).expanduser()
MAIN_REF = "origin/main"
GITHUB_REPO = "zulip/zulip"

# --- reference solutions (answer keys) live OUTSIDE the task dirs -------------------
# `gold_code.patch` is the human fix: the answer. It used to sit inside
# zbench-tasks/tasks/<id>/ next to the agent-visible brief, which put the answer key in
# the same directory a solver could read if it ever walked this repo. The oracle and the
# quality gates still need it, so it moved to a sibling tree that nothing agent-facing
# points at, and that a consumer can delete or skip cloning wholesale:
#
#     zbench-tasks/tasks/<id>/      brief, card, instance, gold_test  (shippable)
#     zbench-tasks/solutions/<id>/  gold_code.patch                   (answer key)
#
# Runtime blindness never depended on this -- the agent works in a Zulip worktree,
# not in this repo (zbench/workflow.py), and test files are reverted before grading.
# This is defence in depth for anyone who clones the repo and runs an agent inside it.
TASKS_DIR = Path(os.environ.get("ZBENCH_TASKS_DIR", Path(__file__).resolve().parent / "tasks"))
SOLUTIONS_DIR = Path(os.environ.get("ZBENCH_SOLUTIONS_DIR",
                                    Path(__file__).resolve().parent / "solutions"))


def gold_code_path(task_id_or_dir, solutions_dir=None) -> Path:
    """Resolve a task's gold_code.patch.

    Accepts a task id ("ZT-abc123456789") or a path to its task directory. Prefers the
    split location; falls back to the legacy in-task path so a corpus prepared before
    the split still validates. Returns the split path when neither exists, so callers
    that WRITE get the new layout.
    """
    p = Path(task_id_or_dir)
    task_dir = p if p.parent != Path(".") else TASKS_DIR / p.name
    split = Path(solutions_dir or SOLUTIONS_DIR) / p.name / "gold_code.patch"
    if split.exists():
        return split
    legacy = task_dir / "gold_code.patch"
    return legacy if legacy.exists() else split


# --- mining floor --------------------------------------------------------------------
# Only commits at/after this date are mined. NOT a contamination gate: tiers are
# advisory (METHODOLOGY section 5, standing decision 2026-08-14) and the corpus goal is
# ~100 verifiable tasks, so mining reaches back in time. The floor is purely an infra
# bound -- old bases must still provision inside zulip/ci:noble; push it further back
# once image builds for older bases prove out.
MIN_COMMIT_DATE = os.environ.get("ZBENCH_MIN_COMMIT_DATE", "2025-01-01")
CUTOFF_BUFFER_DAYS = int(os.environ.get("ZBENCH_CUTOFF_BUFFER_DAYS", "30"))

# --- execution environment ---------------------------------------------------------
CI_IMAGE = os.environ.get("ZBENCH_CI_IMAGE", "zulip/ci:noble")
ENV_IMAGE_PREFIX = "zbench-env"          # images tagged zbench-env:<fp12>
# Files whose blob-ids at the base commit define the provision fingerprint. A task
# whose FIX touches any of these is rejected at mining (reason dep_change) -- the
# grading image is built at base and must stay valid for the patched tree.
FP_FILES = ["uv.lock", "pnpm-lock.yaml", "package.json", "web/package.json",
            "tools/provision", "tools/lib/provision.py", "tools/lib/provision_inner.py",
            "tools/ci/setup-backend", "version.py"]

# --- curation LLM (pinned -- reproducibility; matches validate_runs' judge model) ---
# Backend is host-dependent: `pi` exists only where it is installed, the claude CLI everywhere.
# Both pin the same model. Headless, tool-less, context-less in either case.
_LLM_BACKEND = os.environ.get("ZBENCH_LLM", "claude")
if _LLM_BACKEND == "pi":
    LLM_CMD = ["pi", "-p", "--provider", os.environ.get("ZBENCH_PI_PROVIDER", "azure-foundry"), "--model", "claude-fable-5",
               "--no-session", "--no-skills", "--no-prompt-templates",
               "--no-extensions", "--no-context-files", "--no-tools"]
else:
    LLM_CMD = ["claude", "--print", "--model", "claude-fable-5",
               "--disable-slash-commands", "--no-session-persistence"]
PI_CMD = LLM_CMD  # back-compat alias

# --- mining predicate---------------------------------------------------------------
# Full fixes only: `Fixes: #N.` / `Fixes #N` (Zulip commit discipline). `Fixes part
# of #N` is rejected in v1 -- a partial fix means the issue over-describes what the
# hidden test checks.
FIXES_RE = re.compile(r"(?im)^\s*fixes[: ]\s*#(\d+)\b")
FIXES_PARTIAL_RE = re.compile(r"(?im)^\s*fixes\s+part\s+of\b")

PY_APPS = ("zerver/", "corporate/", "analytics/", "zilencer/", "confirmation/", "zproject/")
PUPPETEER_PREFIX = "web/e2e-tests/"
_WEB_TEST_RE = re.compile(r"web/tests/.*\.test\.(ts|js|cjs|mjs)$")
_PY_TEST_RE = re.compile(r"(zerver|corporate|analytics|zilencer)/tests/")
_WEB_CODE_RE = re.compile(r"web/(src|shared|templates)/.*\.(ts|js|cjs|mjs|hbs)$")


def classify_file(p: str) -> str | None:
    """'py_test' | 'py_code' | 'web_test' | 'web_code' | None (out of scope)."""
    if p.startswith(PUPPETEER_PREFIX):
        return None
    if _PY_TEST_RE.match(p) or (p.startswith(PY_APPS) and p.endswith("/tests.py")):
        return "py_test"
    if p.startswith(PY_APPS) and p.endswith(".py"):
        return None if "/migrations/" in p else "py_code"
    if _WEB_TEST_RE.match(p):
        return "web_test"
    if _WEB_CODE_RE.match(p):
        return "web_code"
    return None


def is_dep_file(p: str) -> bool:
    return p in FP_FILES or p.startswith("requirements/") or p == "pyproject.toml"


def touches_migrations(files) -> bool:
    return any("/migrations/" in f for f in files)


# Test-support files (fixtures, node test-helper libs): not code, not runnable test
# targets, but the hidden test cannot RUN without them -- they ride with gold_test.
# Missing them caused false oracle rejections (and would cause false grading failures):
# ZT-59d5d29ed857 (webhook fixture json), ZT-0e8d5603ef8d (web/tests/lib helpers).
# (zerver/tests/fixtures/** already classifies as py_test via _PY_TEST_RE.)
_TEST_SUPPORT_RE = re.compile(
    r"^(?:(?:zerver|corporate|analytics|zilencer)/webhooks/.*/fixtures/"
    r"|web/tests/)")


def classify_support(p: str) -> bool:
    """True for a test-support file: included in the gold_test patch split only."""
    return classify_file(p) is None and bool(_TEST_SUPPORT_RE.match(p))
