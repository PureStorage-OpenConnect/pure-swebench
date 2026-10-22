#!/usr/bin/env bash
# W56 infra-exclusion auto-sweep. The 429/timeout/stall no_patch cells are excluded
# by tools/exclude_infra_artifacts.py, but that was a MANUAL step -- so a freshly-
# finished 429 no_patch lingered un-excluded on the dashboard until the next manual
# sweep (which kept getting interrupted). This runs the sweep every INTERVAL so those
# high-confidence, deterministic infra artifacts get excluded within minutes of
# completing. It ONLY touches no_patch/error/incomplete cells that END ON A TERMINAL
# 429 or hit a stall/timeout (never tests_failed/resolved, never contamination -- those
# stay human-controlled). Idempotent. Stop: kill $(cat /tmp/zbench_runs/infra_sweep.pid).
# AGENTS empty = ALL agents. It USED to sweep only the 3 Foundry 429-prone agents, which is why
# claude-cli OAuth-expired no_patch cells silently lingered un-excluded (the 2026-08-06 auth gap).
# Detection is now high-confidence (delegated to classify_attempt), so sweeping all agents is safe
# and necessary -- auth expiry hits claude-cli, not Foundry.
set -u
INTERVAL=${INTERVAL:-180}
AGENTS=${AGENTS:-""}   # empty => all agents
LOG=${LOG:-/tmp/zbench_runs/infra_sweep.log}
mkdir -p "$(dirname "$LOG")"
cd "$(dirname "$0")/.." || exit 1
echo $$ > /tmp/zbench_runs/infra_sweep.pid
args=""; for a in $AGENTS; do args="$args --agent $a"; done
echo "[infra_sweep] start $(date -u +%FT%TZ) INTERVAL=${INTERVAL}s agents=[$AGENTS]" >> "$LOG"
while true; do
  out=$(python3 tools/exclude_infra_artifacts.py $args 2>&1)
  if echo "$out" | grep -q "EXCLUDE "; then
    echo "[infra_sweep] $(date -u +%FT%TZ)" >> "$LOG"
    echo "$out" | grep "EXCLUDE " >> "$LOG"
  fi
  sleep "$INTERVAL"
done
