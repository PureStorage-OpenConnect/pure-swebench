#!/usr/bin/env bash
# One entry point for the zbench test suite (no pytest needed -- each test file
# self-runs via `python3 <file>`).
#
# test_static_invariants.py runs the static repo/doc/schema invariants as build-time
# tests (the same checks the batch `consistency_check.py` linter runs). Run before committing.
#
# Usage:
#   tools/run_tests.sh              # run all test files
#   tools/run_tests.sh static       # run only test_static_invariants.py (fast, no pb/DB)
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ "${1:-}" = "static" ]; then
  files=(zbench/tests/test_static_invariants.py)
else
  files=(zbench/tests/test_*.py)
fi

fail=0
for f in "${files[@]}"; do
  [ -f "$f" ] || continue
  echo "== $f =="
  if python3 "$f"; then
    :
  else
    echo "  [FAIL] $f"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "ALL TESTS PASS"
else
  echo "SOME TESTS FAILED"
fi
exit "$fail"
