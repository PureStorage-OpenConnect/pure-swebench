#!/usr/bin/env bash
# IN-CONTAINER half of the verify: transfer the worktree's PATCH DELTA onto the
# provisioned tree, then run the targeted test command.
#
#   inner_verify.sh <backend|node> <target...>
#
# Invoked only by zbench_verify.sh inside zbench-env:<fp> with /workdir (the patched
# worktree, READ-ONLY) and /zbench (this scripts dir, ro) mounted.
#
# The image's /srv/zulip and the worktree's HEAD are the SAME base commit, so the
# exact delta is: (a) `git diff --binary HEAD` of the worktree (tracked modifications
# and deletions -- read-only-safe), plus (b) untracked non-ignored files (patch-added
# files show up as untracked). This is precise where a tree-level rsync --delete is
# not: it can never clobber provision artifacts (dev-secrets.conf, .venv, compiled
# locale .mo files) that live untracked inside the provisioned tree.
# Exit: test runner's exit code; 64 usage/setup.
set -u -o pipefail

MODE="${1:-}"; shift || true
[ "$MODE" = backend ] || [ "$MODE" = node ] || { echo "inner_verify: mode must be backend|node" >&2; exit 64; }
[ $# -ge 1 ] || { echo "inner_verify: no test targets" >&2; exit 64; }
[ -d /workdir ] || { echo "inner_verify: /workdir not mounted" >&2; exit 64; }

sudo service postgresql start >/dev/null 2>&1
sudo service rabbitmq-server start >/dev/null 2>&1
sudo service redis-server start >/dev/null 2>&1
sudo service memcached start >/dev/null 2>&1

# both forms: bare path (git -C /workdir ...) and .git suffix (fetch-from-path)
git config --global --add safe.directory /workdir 2>/dev/null
git config --global --add safe.directory /workdir/.git 2>/dev/null
git config --global --add safe.directory /srv/zulip 2>/dev/null

wt_head="$(git -C /workdir rev-parse HEAD)" || { echo "inner_verify: /workdir is not a git checkout" >&2; exit 64; }
img_head="$(git -C /srv/zulip rev-parse HEAD)" || exit 64
if [ "$wt_head" != "$img_head" ]; then
  # Fingerprint grouping: ONE provisioned image serves EVERY base commit whose
  # FP_FILES blobs match (that is the whole point). The image tree was committed at
  # some sibling base; move it to THIS task's base first -- the worktree itself is a
  # repo containing that commit, so fetch from the read-only mount. checkout -f
  # updates tracked files only; untracked provision artifacts survive. The zbench
  # wrapper already matched the fingerprint, so provision stays valid; migration
  # drift between sibling bases is handled by test-backend's own template rebuild.
  git -C /srv/zulip fetch -q --depth 1 --update-shallow /workdir HEAD \
    || { echo "inner_verify: fetch of worktree base $wt_head failed" >&2; exit 64; }
  git -C /srv/zulip checkout -qf FETCH_HEAD \
    || { echo "inner_verify: checkout of worktree base failed" >&2; exit 64; }
fi

# (a) tracked delta (modifications + deletions), read-only against /workdir
delta=/tmp/zbench_delta.patch
git -C /workdir diff --binary HEAD > "$delta" || { echo "inner_verify: diff failed" >&2; exit 64; }
if [ -s "$delta" ]; then
  git -C /srv/zulip apply --whitespace=nowarn "$delta" \
    || { echo "inner_verify: delta apply failed" >&2; exit 64; }
fi

# (b) untracked non-ignored files (patch-/agent-added); copy preserving paths
git -C /workdir ls-files --others --exclude-standard -z \
  | (cd /workdir && xargs -0 -r cp --parents -t /srv/zulip --) \
  || { echo "inner_verify: untracked copy failed" >&2; exit 64; }

cd /srv/zulip || exit 64
source tools/ci/activate-venv || { echo "inner_verify: activate-venv failed" >&2; exit 64; }

if [ "$MODE" = backend ]; then
  exec ./tools/test-backend "$@"
else
  # Bug C (2026-08-20): run each node test FILE in its OWN node process. Zulip's node
  # runner loads every given file into ONE shared module registry, so an ESM mock
  # (mock_esm) taken in one file can leak into another and throw
  # "It is too late to mock ...", failing behaviorally-correct patches -- and even the
  # gold fix (the "flaky gold" on multi-file node tasks). Per-file isolation removes the
  # cross-file leak; all files must pass. Matches the split-invocation replay path that
  # graded green. Backend (Django) already isolates per test, so it is unchanged.
  node_rc=0
  for target in "$@"; do
    echo "=== zbench node file: $target ==="
    if ! ./tools/test-js-with-node "$target"; then
      node_rc=1
    fi
  done
  exit "$node_rc"
fi
