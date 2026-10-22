#!/usr/bin/env bash
# HOST half of the verify -- this string IS a task's commands.tests entry:
#
#   bash "$ZBENCH_SCRIPTS/zbench_verify.sh" backend zerver.tests.test_x.Cls.test_m ...
#   bash "$ZBENCH_SCRIPTS/zbench_verify.sh" node web/tests/foo.test.cjs ...
#
# Contract with the harness (zbench/workflow.py): cwd = the patched worktree; exit 0
# = pass, non-zero = fail; env carries ZBENCH_SCRIPTS + ZBENCH_WORKTREE. Runs the
# targets inside the fingerprint-matched provisioned image with NO network, worktree
# mounted READ-ONLY (the container can never write root-owned files into the host
# tree). Exit: runner's code | 64 wrong cwd | 65 env image missing | 124 timeout.
set -u -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODE="${1:-}"; shift || true
[ "$MODE" = backend ] || [ "$MODE" = node ] || { echo "zbench_verify: mode must be backend|node" >&2; exit 64; }
[ $# -ge 1 ] || { echo "zbench_verify: no test targets" >&2; exit 64; }

# W69 defense: a wrong cwd must fail loudly here, never as a silent both-arms FAIL.
[ -x tools/test-backend ] || [ -f tools/test-backend ] \
  || { echo "zbench_verify: cwd $(pwd) is not a Zulip tree (tools/test-backend missing)" >&2; exit 64; }

# macOS ships no `timeout` (it's GNU coreutils); a bare rc=127 here would otherwise fall
# through to the generic "[tests_failed] FAIL_TO_PASS did not pass" classification below,
# silently misreporting a host-config gap as a real capability miss. Fail loudly instead.
command -v timeout >/dev/null 2>&1 \
  || { echo "zbench_verify: 'timeout' not found on PATH (macOS: brew install coreutils, then put" \
            "\$(brew --prefix coreutils)/libexec/gnubin on PATH)" >&2; exit 64; }

FP="$(python3 "$HERE/../env_fingerprint.py" --worktree "$PWD")" \
  || { echo "zbench_verify: fingerprint failed" >&2; exit 64; }
IMG="zbench-env:$FP"
docker image inspect "$IMG" >/dev/null 2>&1 \
  || { echo "zbench_verify: missing env image $IMG (run build_env_image.sh <base>)" >&2; exit 65; }

NAME="zbench_v_$(date +%s)_$$_$RANDOM"
trap 'docker kill "$NAME" >/dev/null 2>&1' EXIT

# Outer `timeout` kills only the docker CLIENT; the trap kills the container itself.
# Inner budget stays ~60s under the harness verify_timeout so THIS layer reports.
timeout -k 30 "${ZBENCH_VERIFY_TIMEOUT:-1140}" \
  docker run --rm --init --name "$NAME" \
    --network none \
    -e HOME=/home/github \
    -v "$PWD":/workdir:ro \
    -v "$HERE":/zbench:ro \
    "$IMG" bash /zbench/inner_verify.sh "$MODE" "$@"
rc=$?
[ $rc -eq 124 ] && echo "zbench_verify: TIMEOUT after ${ZBENCH_VERIFY_TIMEOUT:-1140}s" >&2
exit $rc
