#!/usr/bin/env bash
# GC zbench-env images: keep every fingerprint referenced by a validated/held task's
# meta.json; delete unreferenced images older than KEEP_DAYS (label zbench.created).
#
#   gc_env_images.sh [--dry-run] [--keep-days N]
set -u -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TASKS="$(dirname "$HERE")/tasks"
DRY=0; KEEP_DAYS=30
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --keep-days) KEEP_DAYS="$2"; shift 2 ;;
    *) echo "usage: gc_env_images.sh [--dry-run] [--keep-days N]" >&2; exit 64 ;;
  esac
done

referenced="$(python3 - "$TASKS" <<'EOF'
import json, sys
from pathlib import Path
tasks = Path(sys.argv[1])
fps = set()
if tasks.is_dir():
    for meta in tasks.glob("*/meta.json"):
        try:
            m = json.loads(meta.read_text())
        except Exception:
            continue
        if m.get("curation_status") in ("validated", "held") and m.get("env_fingerprint"):
            fps.add(m["env_fingerprint"])
print("\n".join(sorted(fps)))
EOF
)"

echo "== docker system df (before)"; docker system df | head -3
cutoff="$(date -u -d "-$KEEP_DAYS days" +%s 2>/dev/null || date -u +%s)"
docker image ls --filter reference='zbench-env:*' --format '{{.Repository}}:{{.Tag}}' | while read -r img; do
  fp="${img#zbench-env:}"
  if echo "$referenced" | grep -qx "$fp"; then
    echo "keep  $img (referenced by a validated/held task)"
    continue
  fi
  created="$(docker image inspect "$img" --format '{{index .Config.Labels "zbench.created"}}' 2>/dev/null)"
  created_s="$(date -u -d "${created:-1970-01-01}" +%s 2>/dev/null || echo 0)"
  if [ "$created_s" -gt "$cutoff" ]; then
    echo "keep  $img (younger than ${KEEP_DAYS}d)"
    continue
  fi
  if [ "$DRY" -eq 1 ]; then
    echo "WOULD DELETE $img"
  else
    echo "delete $img"
    docker image rm "$img" >/dev/null || echo "  (in use? skipped)"
  fi
done
# reap any stranded verify/build containers
docker ps -a --filter name='zbench_' --filter status=exited -q | xargs -r docker rm >/dev/null
echo "== docker system df (after)"; docker system df | head -3
