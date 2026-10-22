#!/usr/bin/env python3
"""Verdict-parser truth table (oracle false-flip defense).

Run: python3 zbench/tests/test_verdict.py   (asserts; exit 0 = pass)
Samples mirror empirically captured runner output (2026-08-13, zulip/ci:noble).
The load-bearing rule: NOTRUN (couldn't run) is never conflated with FAIL (ran and
failed) -- conflating them turns a typo'd target into a fake oracle flip.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "zbench-tasks"))
from verdict import verdict                     # noqa: E402

PASS_LOG = """Running zerver.tests.test_timestamp.TestTimestamp.test_enforce_UTC
Running zerver.tests.test_timestamp.TestTimestamp.test_datetime_to_global_time
----------------------------------------------------------------------
Ran 5 tests in 0.028s

OK
Destroying test database for alias 'default'...
Found 5 test(s).
"""

FAIL_LOG = """Running zerver.tests.test_actions.ActionTest.test_thing
FAIL: test_thing (zerver.tests.test_actions.ActionTest.test_thing)
AssertionError: 1 != 2
----------------------------------------------------------------------
Ran 3 tests in 0.5s

FAILED (failures=1)
"""

ERROR_LOG = """Running zerver.tests.test_actions.ActionTest.test_thing
ERROR: test_thing (zerver.tests.test_actions.ActionTest.test_thing)
ValueError: boom
Ran 1 test in 0.1s

FAILED (errors=1)
"""

BOGUS_TARGET_LOG = """  File "/srv/zulip/zerver/lib/test_runner.py", line 241, in check_import_error
    __import__(test_name)
ModuleNotFoundError: No module named 'zerver.tests.test_nonexistent_module'
"""

COUPLED_IMPORT_LOG = """Traceback (most recent call last):
  File "/srv/zulip/zerver/tests/test_new.py", line 3, in <module>
    from zerver.lib.actions import symbol_only_the_fix_adds
ImportError: cannot import name 'symbol_only_the_fix_adds' from 'zerver.lib.actions'
"""

RAN_ZERO_LOG = "Ran 0 tests in 0.000s\n\nNO TESTS RAN\n"

MISSING_IMAGE_LOG = "zbench_verify: missing env image zbench-env:deadbeef (run build_env_image.sh)\n"

NODE_PASS_LOG = "Starting node tests...\n\n\x1b[32mTest(s) passed. SUCCESS!\x1b[0m\n"
NODE_FAIL_LOG = "AssertionError [ERR_ASSERTION]: Expected values to be strictly equal\n"
NODE_MISSING_LOG = "Using /srv/zulip/.venv\nCannot find web/tests/zbench_nonexistent.test.cjs (/srv/zulip/web/tests/zbench_nonexistent.test.cjs)\n"

T = ["zerver.tests.test_timestamp.TestTimestamp"]


def test_backend_pass():
    assert verdict(PASS_LOG, 0, "backend", T) == "PASS"


def test_backend_fail_and_error_both_flip():
    assert verdict(FAIL_LOG, 1, "backend") == "FAIL"
    assert verdict(ERROR_LOG, 1, "backend") == "FAIL"


def test_backend_notrun_shapes():
    assert verdict(BOGUS_TARGET_LOG, 1, "backend") == "NOTRUN"
    assert verdict(COUPLED_IMPORT_LOG, 1, "backend") == "NOTRUN"
    assert verdict(RAN_ZERO_LOG, 1, "backend") == "NOTRUN"
    assert verdict(MISSING_IMAGE_LOG, 65, "backend") == "NOTRUN"


def test_backend_target_mismatch_is_notrun():
    # OK run, but the requested target never appears among executed tests -> the
    # command resolved to something else entirely; must not count as PASS.
    assert verdict(PASS_LOG, 0, "backend", ["zerver.tests.test_other.C.test_x"]) == "NOTRUN"


def test_backend_wrapper_timeout_is_fail():
    assert verdict("anything", 124, "backend") == "FAIL"


def test_node_shapes():
    assert verdict(NODE_PASS_LOG, 0, "node") == "PASS"
    assert verdict(NODE_FAIL_LOG, 1, "node") == "FAIL"
    assert verdict(NODE_MISSING_LOG, 1, "node") == "NOTRUN"


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"verdict: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
