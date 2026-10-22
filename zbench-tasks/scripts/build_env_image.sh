#!/usr/bin/env bash
# Build (idempotently) the provisioned env image for a Zulip base commit.
#
#   build_env_image.sh <base_commit> [--repo PATH] [--force]
#
# Image: zbench-env:<fp12> where fp = env_fingerprint.py of FP_FILES at base.
# Recipe proven 2026-08-13 (Phase 0b): zulip/ci:noble + real git checkout (git
# archive is NOT enough -- provision refuses a non-repo) + services started BEFORE
# setup-backend (configure-rabbitmq waits on a running rabbitmq-server).
# Exit: 0 image ready | 75 infra (docker/network) | 70 script error.
set -u -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TASKS_DIR="$(dirname "$HERE")"
CI_IMAGE="${ZBENCH_CI_IMAGE:-zulip/ci:noble}"

BASE="" ; REPO="" ; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --repo)  REPO="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    *)       BASE="$1"; shift ;;
  esac
done
[ -n "$BASE" ] || { echo "usage: build_env_image.sh <base_commit> [--repo PATH] [--force]" >&2; exit 70; }
REPO="${REPO:-${ZBENCH_TARGET_REPO:-$HOME/work/zulip}}"
REPO="$(eval echo "$REPO")"
[ -d "$REPO/.git" ] || { echo "build_env_image: no git repo at $REPO (set ZBENCH_TARGET_REPO)" >&2; exit 70; }

BASE_FULL="$(git -C "$REPO" rev-parse --verify "${BASE}^{commit}" 2>/dev/null)" \
  || { echo "build_env_image: unknown commit $BASE in $REPO" >&2; exit 70; }
FP="$(python3 "$TASKS_DIR/env_fingerprint.py" "$BASE_FULL" --repo "$REPO")" || exit 70
IMG="zbench-env:$FP"

if [ "$FORCE" -eq 0 ] && docker image inspect "$IMG" >/dev/null 2>&1; then
  echo "$IMG already built"
  exit 0
fi

NAME="zbench_build_$FP"
docker rm -f "$NAME" >/dev/null 2>&1
trap 'docker rm -f "$NAME" >/dev/null 2>&1' EXIT

docker run -d --name "$NAME" -e HOME=/home/github \
  -v "$REPO":/mnt/zulip-src:ro "$CI_IMAGE" sleep infinity >/dev/null \
  || { echo "build_env_image: docker run failed (daemon? image pull?)" >&2; exit 75; }

# COREPACK_INTEGRITY_KEYS=0: npm rotated its registry signing keys in Jan 2025; the
# corepack pinned by older bases only trusts the old key and fails `pnpm install`
# with "Cannot find matching keyid". Verification is disabled INSIDE the build/env
# container only (infra workaround, unrelated to the code under test).
step() { echo "== $1"; shift; docker exec -e HOME=/home/github -e COREPACK_INTEGRITY_KEYS=0 "$@" || return 1; }

step "checkout $BASE_FULL" "$NAME" bash -c "
  set -e
  git config --global --add safe.directory /mnt/zulip-src/.git
  sudo mkdir -p /srv/zulip && sudo chown github:github /srv/zulip
  cd /srv/zulip
  git init -q -b main
  git fetch -q --depth 1 --no-tags file:///mnt/zulip-src $BASE_FULL
  git checkout -q -B main FETCH_HEAD
  git config user.email zbench@zbench.local && git config user.name zbench
" || { echo "build_env_image: checkout failed" >&2; exit 75; }

# Bitrot shim for old bases (BUILD-TIME checkout only -- verification always uses a
# fresh checkout of the real tree): provision exports PYTHONWARNINGS=error, and the
# LATEST setuptools (fetched fresh by pip build isolation) now emits deprecation
# warnings old sdist pins never saw -> pip install dies. Soften to 'default' for the
# provision run.
step "bitrot shim: PYTHONWARNINGS" -w /srv/zulip "$NAME" bash -c "
  grep -rl 'PYTHONWARNINGS=error' tools/ scripts/ 2>/dev/null \
    | xargs -r sed -i 's/PYTHONWARNINGS=error/PYTHONWARNINGS=default/g'; true
" || true

# The raw zulip/ci image does NOT ship postgres/rabbitmq/redis/memcached -- the
# first provision run apt-installs them, then dies at configure-rabbitmq because
# apt-installed services don't auto-start inside containers. So: tolerate a first
# provision failure, start the (now installed) services, provision again.
echo "== provision pass 1 (package install; configure-rabbitmq failure tolerated)"
docker exec -e HOME=/home/github -e COREPACK_INTEGRITY_KEYS=0 -w /srv/zulip "$NAME" \
  ./tools/ci/setup-backend --skip-dev-db-build >/tmp/zbench_provision1_$FP.log 2>&1
P1_RC=$?

step "start services" "$NAME" bash -c "
  sudo service postgresql start && sudo service rabbitmq-server start \
  && sudo service redis-server start && sudo service memcached start
" || { echo "build_env_image: service start failed (see /tmp/zbench_provision1_$FP.log)" >&2; exit 75; }

if [ "$P1_RC" -ne 0 ]; then
  step "provision pass 2 (services up)" -w /srv/zulip "$NAME" \
    ./tools/ci/setup-backend --skip-dev-db-build \
    || { echo "build_env_image: provision failed" >&2; exit 75; }
fi

step "warm gate: backend test class" -w /srv/zulip "$NAME" bash -c "
  source tools/ci/activate-venv && ./tools/test-backend zerver.tests.test_timestamp
" || { echo "build_env_image: warm backend test failed -- env not usable" >&2; exit 75; }

step "warm gate: node test file" -w /srv/zulip "$NAME" bash -c "
  source tools/ci/activate-venv && ./tools/test-js-with-node web/tests/people.test.cjs
" || { echo "build_env_image: warm node test failed -- env not usable" >&2; exit 75; }

step "prune caches" "$NAME" bash -c "
  sudo service postgresql stop; sudo service rabbitmq-server stop
  sudo service redis-server stop; sudo service memcached stop
  uv cache clean >/dev/null 2>&1 || true
  pnpm store prune >/dev/null 2>&1 || true
  sudo rm -rf /home/github/.cache/uv /tmp/* 2>/dev/null || true
" || true

docker commit \
  --change 'CMD ["/bin/bash"]' \
  --change 'ENV COREPACK_INTEGRITY_KEYS=0' \
  --change "LABEL zbench.base=$BASE_FULL zbench.fp=$FP zbench.created=$(date -u +%F)" \
  "$NAME" "$IMG" >/dev/null || { echo "build_env_image: docker commit failed" >&2; exit 75; }

echo "$IMG built (base $BASE_FULL)"
