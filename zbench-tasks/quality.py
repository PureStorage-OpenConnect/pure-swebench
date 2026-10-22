"""Task-quality gates distilled from the Databricks coding-agent benchmark write-up:
author provenance (no bots / service accounts / AI-generated), scope ("few modules"),
and a complexity tag. Pure functions over data already in hand -- no network, no LLM.

Imported by the mining/prep pipeline AND by backfill_quality.py (which applies these to
the existing corpus). See docs/benchmark-best-practices.md.
"""
from __future__ import annotations

import re

# --- author / bot / service-account / AI-generated exclusion ------------------------
# The blog excludes bot commits, service accounts, and fully AI-generated changes. Our
# mining predicate (Fixes #N + code + test) catches most incidentally; this makes it a
# real filter. Matched against committer/author name AND email.
_BOT_AUTHOR_RE = re.compile(
    r"\[bot\]|dependabot|renovate|transifex|weblate|crowdin|greenkeeper"
    r"|github-actions|actions@github\.com|noreply@github\.com|snyk-bot|imgbot|pre-commit-ci",
    re.I)
# AI-assistant trailers / markers in the commit message.
_AI_TRAILER_RE = re.compile(
    # specific assistant names only -- deliberately NOT a bare "ai" (a human named "Ai"
    # would false-positive). "generated with/by <tool>" and the robot emoji cover the rest.
    r"(?im)^\s*co-authored-by:.*(claude|chatgpt|gpt-[0-9]|openai|copilot|cursor|devin|codex|aider|anthropic)"
    r"|generated (?:with|by)\s+\[?(?:claude|gpt|copilot|cursor|codex|chatgpt|anthropic)"
    r"|\U0001F916 generated",   # robot emoji "Generated ..."
)


def excluded_author(name: str, email: str) -> str | None:
    """Reason string if this author/committer should be excluded, else None."""
    blob = f"{name or ''} {email or ''}"
    if _BOT_AUTHOR_RE.search(blob):
        return "bot_or_service_account"
    return None


def has_ai_trailer(message: str) -> bool:
    return bool(_AI_TRAILER_RE.search(message or ""))


# --- scope ("confined to a few modules") --------------------------------------------
# Sanity ceiling only, NOT a difficulty gate (standing decision 2026-08-14: difficulty
# spread is welcome -- trivial through difficult -- as long as the outcome is verifiable).
# The ceiling exists to keep single-commit tasks reviewable and oracle runs bounded.
MAX_CODE_FILES = 15
MAX_ADDED_CODE_LINES = 600


def _added_lines(patch_text: str) -> int:
    return sum(1 for l in (patch_text or "").splitlines()
               if l.startswith("+") and not l.startswith("+++"))


def _files_touched(patch_text: str) -> int:
    return len(re.findall(r"^\+\+\+ b/", patch_text or "", re.M))


def _hunks(patch_text: str) -> int:
    return len(re.findall(r"^@@ ", patch_text or "", re.M))


def scope_violation(code_files: list, gold_code_patch: str) -> str | None:
    """Reason string if the change is too large to be a clean 'few modules' task."""
    n_files = len(code_files)
    added = _added_lines(gold_code_patch)
    if n_files > MAX_CODE_FILES:
        return f"scope: {n_files} code files > {MAX_CODE_FILES}"
    if added > MAX_ADDED_CODE_LINES:
        return f"scope: {added} added code lines > {MAX_ADDED_CODE_LINES}"
    return None


# --- complexity tag (~25% low / 60% medium / 15% high, per the blog) ----------------
def complexity(gold_code_patch: str, f2p_count: int = 0) -> dict:
    """A cheap, deterministic complexity record + low/med/high bucket. Thresholds
    calibrated to the corpus diffstat distribution (median 27 added / 2 files)."""
    added = _added_lines(gold_code_patch)
    files = _files_touched(gold_code_patch)
    hunks = _hunks(gold_code_patch)
    if added <= 15 and files <= 2:
        bucket = "low"
    elif added > 80 or files > 5 or hunks > 10:
        bucket = "high"
    else:
        bucket = "medium"
    return {"bucket": bucket, "added_lines": added, "files": files,
            "hunks": hunks, "f2p_count": f2p_count}
