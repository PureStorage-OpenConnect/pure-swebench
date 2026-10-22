#!/usr/bin/env python3
"""Oracle verdict from a zbench_verify.sh log: PASS | FAIL | NOTRUN | UNKNOWN.

Exit codes cannot distinguish "ran and failed" (the flip signal the oracle needs)
from "could not run" (bad target, symbol-coupled gold test failing at import, missing
env image) -- that distinction lives here, parsed from the runner's authoritative
output. NOTRUN must never be read as a base-FAIL: the oracle maps it to
UNENUMERABLE, not INVALID/VALID (the false-flip defense).

Output shapes are empirically pinned (2026-08-13, zulip/ci:noble):
  backend PASS   "Running zerver.tests.x.Cls.test_m" per test + "Ran 5 tests in Xs" + "OK"
  backend FAIL   "FAIL: test_m (...)" / "ERROR: test_m (...)" + "FAILED (failures=1)"
  backend NOTRUN "ModuleNotFoundError: No module named 'zerver.tests.x'" (via
                 zerver/lib/test_runner.py check_import_error), no "Ran N" line;
                 or ImportError traceback before any test ran; or "Ran 0 tests"
  node PASS      "Test(s) passed. SUCCESS!" (ANSI-colored)
  node NOTRUN    "Cannot find web/tests/foo.test.cjs (...)"
  wrapper NOTRUN "zbench_verify: missing env image ..." (exit 65) / wrong-cwd (64)

Usage: verdict.py <log> --rc N --mode backend|node [--target T ...]
Prints the verdict; exits 0 (PASS) / 1 (FAIL) / 3 (NOTRUN) / 4 (UNKNOWN).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.M)
_RUNNING_RE = re.compile(r"^Running (\S+)$", re.M)
_RESULT_RE = re.compile(r"^(FAIL|ERROR): (\S+)", re.M)
_NOTRUN_SIGS = (
    "zbench_verify: missing env image",
    "zbench_verify: cwd",                      # wrong-cwd hard fail (exit 64)
    "inner_verify: base mismatch",
    "inner_verify: /workdir not mounted",
)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text or "")


def backend_verdict(text: str, rc: int, targets: list[str]) -> str:
    text = strip_ansi(text)
    if any(s in text for s in _NOTRUN_SIGS):
        return "NOTRUN"
    ran = _RAN_RE.search(text)
    ran_n = int(ran.group(1)) if ran else None
    if ran_n == 0:
        return "NOTRUN"
    failures = _RESULT_RE.findall(text)
    if ran_n is None:
        # No test summary at all: the runner died before running anything --
        # bad dotted target (ModuleNotFoundError via check_import_error) or a
        # symbol-coupled gold test that cannot even import at base.
        if "ModuleNotFoundError" in text or "ImportError" in text or "Traceback" in text:
            return "NOTRUN"
        return "UNKNOWN"
    if failures:
        # Targeted run: any FAIL/ERROR is the flip signal. (ERROR counts -- an
        # added test that *raises* at base is still a failing test.)
        return "FAIL"
    if "FAILED (" in text:
        return "FAIL"
    if rc == 0 and re.search(r"^OK\b", text, re.M):
        # Guard against the target resolving to something unrelated: every
        # requested target must appear (as a prefix) among the executed tests.
        if targets:
            executed = _RUNNING_RE.findall(text)
            for t in targets:
                if not any(e == t or e.startswith(t + ".") for e in executed):
                    return "NOTRUN"
        return "PASS"
    return "UNKNOWN"


def node_verdict(text: str, rc: int, targets: list[str]) -> str:
    text = strip_ansi(text)
    if any(s in text for s in _NOTRUN_SIGS):
        return "NOTRUN"
    if re.search(r"^Cannot find ", text, re.M):
        return "NOTRUN"
    if "Test(s) passed. SUCCESS!" in text and rc == 0:
        return "PASS"
    if rc != 0:
        return "FAIL"
    return "UNKNOWN"


def verdict(text: str, rc: int, mode: str, targets: list[str] | None = None) -> str:
    targets = targets or []
    if rc == 124:                                # wrapper timeout
        return "FAIL"
    if rc in (64, 65):                           # wrapper setup errors
        return "NOTRUN"
    v = backend_verdict(text, rc, targets) if mode == "backend" else node_verdict(text, rc, targets)
    if v == "UNKNOWN":
        v = "PASS" if rc == 0 else "UNKNOWN"     # rc==0 with odd output = pass; rc!=0 stays UNKNOWN
    return v


_EXIT = {"PASS": 0, "FAIL": 1, "NOTRUN": 3, "UNKNOWN": 4}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="zbench_verify output file")
    ap.add_argument("--rc", type=int, required=True, help="zbench_verify exit code")
    ap.add_argument("--mode", choices=("backend", "node"), required=True)
    ap.add_argument("--target", action="append", default=[], help="fail_to_pass target (repeatable)")
    a = ap.parse_args()
    v = verdict(Path(a.log).read_text(errors="replace"), a.rc, a.mode, a.target)
    print(v)
    return _EXIT[v]


if __name__ == "__main__":
    raise SystemExit(main())
