#!/usr/bin/env python3
"""Unit tests for scoring.classify_attempt (W23 taxonomy boundaries).
Run: python3 test_classify_attempt.py  (exit 0 = all pass)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring as S


def A(**kw):
    d = {"tests_passed": 0, "status": None, "outcome": None,
         "runtime_ms": None, "total_duration_ms": None, "output_tokens": None}
    d.update(kw)
    return d


CASES = [
    # (label, attempt, budget_s, expected)
    ("resolved", A(tests_passed=1, status="ok"), 3000, "resolved"),
    ("miss (tests_failed)", A(status="tests_failed", outcome="verification_tests_failed"), 3000, "miss"),
    ("miss (produced, unknown status)", A(status="ok", outcome="completed"), 3000, "miss"),
    ("infra internal_error", A(status="internal_error"), 3000, "artifact:infra"),
    ("infra worktree_error", A(status="worktree_error"), 3000, "artifact:infra"),
    ("infra workspace prep", A(status="ok", outcome="workspace_preparation_failed"), 3000, "artifact:infra"),
    ("auth fast-fail (5s, no out)", A(status="no_patch_generated", runtime_ms=5000), 3000, "artifact:auth"),
    ("auth boundary (90s, no out)", A(status="no_patch_generated", runtime_ms=90000), 3000, "artifact:auth"),
    ("NOT auth (91s, no out)", A(status="no_patch_generated", runtime_ms=91000), 3000, "no_patch_genuine"),
    ("NOT auth (5s, has out)", A(status="no_patch_generated", runtime_ms=5000, output_tokens=120), 3000, "no_patch_genuine"),
    ("budget artifact (1750/1800)", A(status="no_patch_generated", runtime_ms=1750000), 1800, "artifact:budget"),
    ("NOT budget at canonical (2950/3000)", A(status="no_patch_generated", runtime_ms=2950000), 3000, "no_patch_genuine"),
    ("genuine give-up (500s/3000)", A(status="no_patch_generated", runtime_ms=500000), 3000, "no_patch_genuine"),
    ("budget disabled (None) -> genuine", A(status="no_patch_generated", runtime_ms=1750000), None, "no_patch_genuine"),
    ("candidate_missing outcome == no_patch", A(outcome="candidate_missing", runtime_ms=4000), 3000, "artifact:auth"),
    ("total_duration_ms fallback for auth", A(status="no_patch_generated", total_duration_ms=3000), 3000, "artifact:auth"),
    # verify-phase timeout: build+test exceeded the verify cap -> infra artifact, NOT a miss
    ("verify timeout (outcome)", A(status="timeout", outcome="verification_timeout", runtime_ms=262000, total_duration_ms=2662000), 3000, "artifact:infra"),
    ("verify timeout (status only)", A(status="timeout"), 3000, "artifact:infra"),
]


def main():
    fails = 0
    for label, a, budget, exp in CASES:
        got = S.classify_attempt(a, budget)
        ok = got == exp
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label:42s} -> {got}" + ("" if ok else f"  (expected {exp})"))
    # is_artifact_class sanity
    assert S.is_artifact_class("artifact:auth") and not S.is_artifact_class("miss"), "is_artifact_class wrong"
    # sqlite3.Row compatibility
    import sqlite3
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT 1 AS tests_passed, 'ok' AS status, NULL AS outcome, "
                       "NULL AS runtime_ms, NULL AS total_duration_ms, NULL AS output_tokens").fetchone()
    assert S.classify_attempt(row, 3000) == "resolved", "sqlite3.Row path failed"
    print("  PASS  sqlite3.Row compatibility + is_artifact_class")

    # W52: evidence-based no_patch classifier (reads agent stderr / output tokens)
    npe = [
        ("sub-canonical timeout kill -> artifact:budget",
         ("...Command '[pi ...]' timed out after 2700 seconds", None), "artifact:budget"),
        ("at-canonical timeout -> genuine (NOT flagged)",
         ("...timed out after 3000 seconds", None), None),
        ("above-canonical timeout -> genuine (NOT flagged)",
         ("...timed out after 3600 seconds", None), None),
        ("output-token cap + no changes -> artifact:budget",
         ("pi made no changes", 64000), "artifact:budget"),
        ("few output tokens + no changes -> genuine no_patch",
         ("pi made no changes", 1200), None),
        ("clean no-signal stderr -> genuine no_patch",
         ("Starting pi agent ... Running pi ...", None), None),
    ]
    for label, (serr, otoks), exp in npe:
        got, reason, ev = S.classify_no_patch_evidence(serr, otoks)
        ok = got == exp
        fails += not ok
        print(f"  {'PASS' if ok else 'FAIL'}  {label:52s} -> {got}" + ("" if ok else f"  (expected {exp})"))

    print(f"\n{'ALL PASS' if not fails else str(fails)+' FAILED'} ({len(CASES)+len(npe)} cases)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
