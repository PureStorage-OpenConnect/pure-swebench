#!/usr/bin/env python3
"""Failure-classification truth table for the Zulip retarget.

Run: python3 zbench/tests/test_classifiers.py   (asserts; exit 0 = pass)
Pins the two string classifiers that route non-zero verifies into
repo_setup_failed / build_failed / tests_failed. A plain test failure must
classify as NEITHER build error NOR infra -- it is a real miss.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from zbench import workflow                      # noqa: E402

BUILD_ERR_SAMPLES = [
    'File "zerver/lib/actions.py", line 12\n    def do(:\nSyntaxError: invalid syntax',
    "ModuleNotFoundError: No module named 'zerver.lib.gone'",
    "ImportError: cannot import name 'do_thing' from 'zerver.lib.actions'",
    "IndentationError: unexpected indent",
    "web/src/thing.ts(4,10): error TS2345: Argument of type 'string'",
    "Error: Cannot find module './gone'",
]

INFRA_SAMPLES = [
    "fatal: could not resolve host: github.com",
    "docker: Error response from daemon: No such image: zbench-env:abc",
    "docker: error response from daemon: pull access denied for zbench-env",
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
    "psql: error: connection to server on socket failed: Connection refused",
    "zbench: missing env image zbench-env:deadbeef (run build_env_image.sh)",
    "isolated fetch failed at abc123: fatal: unable to access",
    "no space left on device",
]

PLAIN_FAILURE_SAMPLES = [
    # a real Django test failure -- must be NEITHER build nor infra
    ("FAIL: test_thing (zerver.tests.test_actions.ActionTest.test_thing)\n"
     "AssertionError: 1 != 2\n----------------------------------------\n"
     "Ran 5 tests in 0.028s\n\nFAILED (failures=1)"),
    # a Django ERROR result (raising test) -- still a real failure, not infra
    ("ERROR: test_thing (zerver.tests.test_actions.ActionTest.test_thing)\n"
     "ValueError: boom\nFAILED (errors=1)"),
    # node test assertion failure
    "AssertionError [ERR_ASSERTION]: Expected values to be strictly equal\nTest(s) failed.",
]


def test_build_error_signatures():
    for s in BUILD_ERR_SAMPLES:
        assert workflow._looks_like_build_error(s), f"should classify as build error: {s[:60]!r}"
        assert not workflow._looks_like_setup_infra(s), f"build error misread as infra: {s[:60]!r}"


def test_infra_signatures():
    for s in INFRA_SAMPLES:
        assert workflow._looks_like_setup_infra(s), f"should classify as infra: {s[:60]!r}"


def test_plain_test_failures_are_neither():
    for s in PLAIN_FAILURE_SAMPLES:
        assert not workflow._looks_like_build_error(s), f"real failure misread as build: {s[:60]!r}"
        assert not workflow._looks_like_setup_infra(s), f"real failure misread as infra: {s[:60]!r}"


def test_zero_tests_guard():
    # a rc==0 verify that ran no tests must be catchable (never a pass)
    for s in ("Ran 0 tests in 0.000s\nNO TESTS RAN", "collected 0 items", "found 0 test files"):
        assert workflow._ran_zero_tests(s), f"should flag zero-tests: {s[:40]!r}"
    for s in ("Ran 5 tests in 0.02s\nOK", "collected 12 items"):
        assert not workflow._ran_zero_tests(s), f"should NOT flag: {s[:40]!r}"


def test_go_era_signatures_are_gone():
    """The Go/C++/pb vocabulary must not linger (it would misclassify Zulip output)."""
    for dead in ("ninja", "declared and not used", "undeclared identifier"):
        assert not any(dead in sig for sig in workflow._BUILD_ERR_SIGS), dead
        assert not any(dead in sig for sig in workflow._SETUP_INFRA_SIGS), dead
    # and the unrelated-failure promotion machinery is really deleted
    for gone in ("_parse_failing_pkgs", "_agent_pkgs", "_gold_test_pkgs", "_pkg_of", "_MODULE_ROOT"):
        assert not hasattr(workflow, gone), f"{gone} should be deleted with the Go promotion"


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"classifiers: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
