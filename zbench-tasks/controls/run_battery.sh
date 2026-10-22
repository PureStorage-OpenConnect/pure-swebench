#!/usr/bin/env bash
# The Phase-6 negative-control battery: run each scripted adversary through the REAL
# harness (run_cell) against a validated task and assert the guardrail fired.
#
#   bash zbench-tasks/controls/run_battery.sh [TASK_ID]
#
# Asserted invariants:
#   control-gold    resolves (tests_passed=1)  -- grading plumbing can pass
#   control-empty   no_patch (candidate_missing), tests_passed=0
#   control-tamper  does NOT resolve           -- strip + runner integrity held
#   control-fetch   completes; transcript carries NET_SIGNAL needles (judged later
#                   by validate_runs.py --no-llm prefilter check)
set -u -o pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TASK="${1:-ZT-1338aa97fd5d}"
INST="$ROOT/zbench-tasks/tasks/$TASK/instance.jsonl"
[ -f "$INST" ] || { echo "battery: no instance.jsonl for $TASK" >&2; exit 64; }

AGENTS="$(mktemp --suffix=.jsonl)"
for mode in gold empty tamper fetch; do
  printf '{"agent_id": "control-%s", "command": "%s %s/control_agents.py %s", "timeout_sec": 600, "env": {}}\n' \
    "$mode" "$(command -v python3)" "$HERE" "$mode"
done > "$AGENTS"

export ZBENCH_SCRIPTS="$ROOT/zbench-tasks/scripts"
RUN="battery-$(date -u +%Y%m%dT%H%M%SZ)"
cd "$ROOT"
fails=0
for mode in gold empty tamper fetch; do
  echo "== control-$mode =="
  python3 -m zbench.cells.run_cell --instances "$INST" --agents "$AGENTS" \
    --agent-id "control-$mode" --base-repo "${ZBENCH_TARGET_REPO:-$HOME/work/zulip}" \
    --run-id "$RUN" --force 2>&1 | tail -2
done

echo
echo "== battery verdicts (bench.db) =="
python3 - "$RUN" <<'EOF'
import json, sqlite3, sys
from pathlib import Path
run = sys.argv[1]
db = Path("bench-db/bench.db")
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
    "SELECT config_id, tests_passed, status, outcome FROM attempt WHERE run_id=?", (run,))}
ok = True
def check(cid, cond, want):
    global ok
    got = rows.get(cid)
    verdict = "PASS" if (got and cond(got)) else "FAIL"
    if verdict == "FAIL":
        ok = False
    print(f"  [{verdict}] {cid}: {got} (want: {want})")
check("control-gold",   lambda g: g[0] == 1,                        "resolves")
check("control-empty",  lambda g: g[0] == 0 and g[2] == "candidate_missing", "no_patch")
check("control-tamper", lambda g: g[0] == 0,                        "MUST NOT resolve")
check("control-fetch",  lambda g: g[0] is not None,                 "completes (judged later)")
sys.exit(0 if ok else 1)
EOF
rc=$?
rm -f "$AGENTS"
exit $rc
