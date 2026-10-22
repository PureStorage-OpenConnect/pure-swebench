#!/usr/bin/env python3
"""Build-time tests for the static code/doc/schema invariants.

Each test asserts that the corresponding check in `tools/consistency_check.py` surfaces no
ERROR-severity issue (WARN/INFO are advisory and do not fail the build). The check functions
are imported (one source of truth); `consistency_check.py` runs the same functions as the
batch linter over the full corpus. No pb / DB-mutation needed.

Run: python3 zbench/tests/test_static_invariants.py   (or: tools/run_tests.sh static)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import consistency_check as cc  # noqa: E402


def _errors(issues):
    """ERROR-severity issues only (WARN/INFO are advisory, not build failures)."""
    return [i for i in (issues or []) if i and i[0] == "ERROR"]


def _assert_no_error(check_fn):
    errs = _errors(check_fn())
    assert not errs, f"{check_fn.__name__} reported ERROR(s):\n" + "\n".join(
        f"  - {fld}: {msg}" for _sev, fld, msg in errs
    )


# --- static invariants ---

def test_single_store():
    """No live tool reads a retired file store; bench.db is the single store."""
    _assert_no_error(cc.check_single_store)


def test_no_old_checkout_refs():
    """No operational file references the retired upstream checkout path (decoupling)."""
    _assert_no_error(cc.check_no_old_checkout_refs)


def test_doc_code_refs():
    """Current-truth docs do not reference nonexistent code paths."""
    _assert_no_error(cc.check_doc_code_refs)


def test_dashboard_icons():
    """Dashboard icon design-system regression guard (one icon language)."""
    _assert_no_error(cc.check_dashboard_icons)


def test_event_stage_mapping():
    """Every emitted attempt_event phase maps to a dashboard visual stage."""
    _assert_no_error(cc.check_event_stage_mapping)


def test_agent_matrix_schema():
    """agents-matrix.jsonl parses and the ranked/fill cohort is single-sourced (no ERROR)."""
    _assert_no_error(cc.check_agent_matrix)


def test_invalidation_store_model():
    """Validity-overlay model is intact (run_exclusion is the switch; no ERROR)."""
    _assert_no_error(cc.check_invalidation_store)


def test_price_fields():
    """Every model we run has all its models.dev cost fields priced by model_prices (no silent gap)."""
    _assert_no_error(cc.check_price_fields)


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"static_invariants: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
