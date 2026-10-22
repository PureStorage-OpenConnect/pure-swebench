#!/usr/bin/env bash
# =============================================================================
# run_eval.sh -- friendly command line for running the zbench eval.
#
# WHAT THIS DOES
#   Picks WHICH MODELS (via --model / --harness / --agent) and WHICH QUESTIONS
#   (via --smoke / --tasks / --task-ids) to run, then hands the selection to the
#   real grid runner (zbench-tasks/run_coverage_matrix.py), which launches each
#   (model x question) cell, throttles parallelism, and records every attempt in
#   bench-db/ (scores in bench.db, full evidence per attempt under blobs/).
#
#   SAFE BY DEFAULT: without --go this only PRINTS the plan (which models, which
#   questions, how many cells would run). Add --go to actually launch.
#
# EXAMPLES
#   tools/run_eval.sh --list                          # what models/harnesses exist
#   tools/run_eval.sh --smoke --model claude-opus-5 --harness claude-cli
#                                                     # plan: 1 question, 1 agent
#   tools/run_eval.sh --smoke --model claude-opus-5 --harness claude-cli --go
#                                                     # ...and actually run it
#   tools/run_eval.sh --tasks 10 --model all --harness pi --go
#                                                     # 10 questions, every pi agent
#   tools/run_eval.sh --model gpt-5.5,claude-fable-5 --go
#                                                     # full corpus, 2 models, all harnesses
#   tools/run_eval.sh --go                            # EVERYTHING: all models x all questions
#   tools/run_eval.sh --report                        # coverage/results table for a selection
#
# VOCABULARY
#   model   = the LLM itself (claude-opus-5, gpt-5.5, FW-Kimi-K3, ...)
#   harness = the agent scaffold driving the model: pi | claude-cli | codex
#   agent   = one (model x harness x provider) combination = one agent_id
#             (e.g. claude-cli-fable-5 = claude-fable-5 driven by the claude CLI)
#   The runnable agents are the rows of zbench-tasks/agents-matrix.jsonl.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"          # repo root
MATRIX="$HERE/zbench-tasks/agents-matrix.jsonl"   # runnable agents (the cohort)
META="$HERE/zbench-tasks/agents-meta.jsonl"       # model metadata per agent

# ---------------------------- defaults / flag parsing -----------------------
MODELS="all"; HARNESSES="all"; AGENT_GLOBS=""     # which agents
TASK_LIMIT=0; TASK_IDS=""; LANG_FLAG=""           # which questions
TRIES=1; FANOUT=6; RUN_ID=""                      # run shape
GO=0; LIST=0; REPORT=0                            # actions

usage() { sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --model)      MODELS="$2"; shift 2 ;;
    --harness)    HARNESSES="$2"; shift 2 ;;
    --agent)      AGENT_GLOBS="$2"; shift 2 ;;         # raw agent_id globs (escape hatch)
    --smoke)      TASK_LIMIT=1; shift ;;               # exactly 1 question
    --tasks)      TASK_LIMIT="$2"; shift 2 ;;          # first N questions (stable order)
    --task-ids)   TASK_IDS="$2"; shift 2 ;;            # explicit ids/globs, e.g. 'ZT-13*'
    --backend-only|--web-only) LANG_FLAG="$1"; shift ;;
    --tries)      TRIES="$2"; shift 2 ;;               # attempts per cell (pass@k)
    --fanout)     FANOUT="$2"; shift 2 ;;              # max parallel cells
    --run-id)     RUN_ID="$2"; shift 2 ;;              # name this run (default: auto)
    --go)         GO=1; shift ;;                       # actually launch (else: plan only)
    --list)       LIST=1; shift ;;
    --report)     REPORT=1; shift ;;                   # coverage/results for the selection
    -h|--help)    usage 0 ;;
    *) echo "run_eval.sh: unknown flag $1 (see --help)"; exit 64 ;;
  esac
done

# ------------------- resolve --model/--harness -> agent_ids -----------------
# agents-matrix.jsonl is the source of truth for WHAT CAN RUN; agents-meta.jsonl
# tells us each agent's model + harness so we can filter by them. The result is
# an exact agent_id list handed to the grid runner as --only.
resolve_agents() {
  python3 - "$MATRIX" "$META" "$MODELS" "$HARNESSES" "$AGENT_GLOBS" <<'PY'
import json, sys, fnmatch
matrix_p, meta_p, models, harnesses, agent_globs = sys.argv[1:6]
runnable = [json.loads(l)["agent_id"] for l in open(matrix_p) if l.strip()]
meta = {m["agent_id"]: m for l in open(meta_p) if l.strip() for m in [json.loads(l)]}

def harness_of(aid):                       # harness is encoded in the agent_id prefix
    return ("claude-cli" if aid.startswith("claude-cli-")
            else "codex" if aid.startswith("codex-")
            else "pi" if aid.startswith("pi-") else "?")

def want(aid):
    m = meta.get(aid, {})
    if m.get("retired"):
        return False
    if agent_globs:                        # raw globs override model/harness filters
        return any(fnmatch.fnmatch(aid, g.strip()) for g in agent_globs.split(","))
    ok_h = harnesses == "all" or harness_of(aid) in [h.strip() for h in harnesses.split(",")]
    ok_m = models == "all" or any(
        fnmatch.fnmatch(str(m.get("model", "")).lower(), g.strip().lower())
        for g in models.split(","))
    return ok_h and ok_m

sel = [a for a in runnable if want(a)]
for a in sel:
    m = meta.get(a, {})
    print(f"{a}\t{m.get('model','?')}\t{harness_of(a)}")
PY
}

if [ "$LIST" -eq 1 ]; then
  # --list: show every runnable agent with its model and harness, then exit.
  echo "runnable agents (zbench-tasks/agents-matrix.jsonl):"
  printf "  %-28s %-26s %s\n" "AGENT_ID" "MODEL" "HARNESS"
  MODELS=all HARNESSES=all AGENT_GLOBS="" resolve_agents | awk -F'\t' '{printf "  %-28s %-26s %s\n",$1,$2,$3}'
  echo
  echo "questions: $(grep -l '"curation_status": "validated"' "$HERE"/zbench-tasks/tasks/*/meta.json | wc -l) validated tasks (python3 zbench-tasks/corpus.py for the list)"
  exit 0
fi

SELECTED="$(resolve_agents)"
[ -n "$SELECTED" ] || { echo "run_eval.sh: no agents match --model='$MODELS' --harness='$HARNESSES' --agent='$AGENT_GLOBS' (try --list)"; exit 65; }
ONLY="$(echo "$SELECTED" | cut -f1 | paste -sd, -)"   # exact ids double as globs

# ------------------------- credential preflight -----------------------------
# Only checked when actually launching (--go); each harness needs different auth.
preflight() {
  local bad=0
  # Needed by EVERY run, whatever the agent selection: grading is dockerized and
  # every worktree is cut from the target clone. A fresh machine lacks both, and
  # without this check every cell just parks as an infra failure.
  docker info >/dev/null 2>&1 \
    || { echo "PREFLIGHT: docker daemon not reachable (grading runs in containers)"; bad=1; }
  local repo="${ZBENCH_TARGET_REPO:-$HOME/work/zulip}"
  [ -d "$repo/.git" ] \
    || { echo "PREFLIGHT: no Zulip clone at $repo (set ZBENCH_TARGET_REPO; see docs/running-your-models.md section 1)"; bad=1; }
  if echo "$ONLY" | grep -q "claude-cli-"; then
    command -v claude >/dev/null || { echo "PREFLIGHT: 'claude' CLI not found (needed by claude-cli-* agents)"; bad=1; }
  fi
  if echo "$ONLY" | grep -qE "foundry"; then
    [ -n "${GATEWAY_URL:-}" ] || { echo "PREFLIGHT: GATEWAY_URL not exported (needed by *-foundry-* agents; see RUNBOOK.md)"; bad=1; }
    az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv >/dev/null 2>&1 \
      || { echo "PREFLIGHT: 'az' has no live token (az login) (needed by *-foundry-* agents)"; bad=1; }
  fi
  # pi on the DIRECT Anthropic API (pi-anthropic-*). pi-foundry-* goes through the
  # gateway proxy instead and needs no Anthropic credential. An empty ~/.pi/agent/auth.json
  # ("{}") is the unauthenticated state -- pi then exits asking for /login, which would
  # otherwise burn a whole fill before anyone noticed.
  if echo "$ONLY" | grep -q "pi-anthropic-"; then
    command -v pi >/dev/null || { echo "PREFLIGHT: 'pi' CLI not found (needed by pi-anthropic-* agents)"; bad=1; }
    if [ -z "${ANTHROPIC_API_KEY:-}${ANTHROPIC_OAUTH_TOKEN:-}" ] \
       && [ "$(wc -c < "$HOME/.pi/agent/auth.json" 2>/dev/null || echo 0)" -lt 10 ]; then
      echo "PREFLIGHT: pi has no Anthropic credential (run 'pi' and type /login, or export ANTHROPIC_API_KEY); needed by pi-anthropic-* agents"
      bad=1
    fi
  fi
  # Direct-OpenAI rows (codex-openai-* / pi-openai-*) authenticate with OPENAI_API_KEY from
  # the LAUNCHER env, which every cell inherits. The key is not in the repo and not in any
  # agent row: source it at launch, e.g.
  #   set -a; . ~/.config/zbench/openai.env; set +a
  # Without this check a whole fill would start and every cell would die on auth.
  if echo "$ONLY" | grep -q -- "-openai-"; then
    [ -n "${OPENAI_API_KEY:-}" ] \
      || { echo "PREFLIGHT: OPENAI_API_KEY not exported (needed by *-openai-* rows); source your key file first, e.g. 'set -a; . ~/.config/zbench/openai.env; set +a'"; bad=1; }
  fi
  if echo "$ONLY" | grep -qE "vllm|local"; then
    echo "PREFLIGHT NOTE: locally-served agents selected (vllm/local) -- make sure their model servers are up."
  fi
  return $bad
}

# --------------------------- build the runner call --------------------------
RUNNER=(python3 "$HERE/zbench-tasks/run_coverage_matrix.py"
        --agents "$MATRIX" --only "$ONLY" --tries "$TRIES" --fanout "$FANOUT")
[ "$TASK_LIMIT" -gt 0 ] && RUNNER+=(--task-limit "$TASK_LIMIT")
[ -n "$TASK_IDS" ]      && RUNNER+=(--task-ids "$TASK_IDS")
[ -n "$LANG_FLAG" ]     && RUNNER+=("$LANG_FLAG")
[ -n "$RUN_ID" ]        && RUNNER+=(--run-id "$RUN_ID")

if [ "$REPORT" -eq 1 ]; then
  # --report: coverage/results table for this selection; runs nothing.
  exec "${RUNNER[@]}" --report
fi

echo "== selection =="
printf "  %-28s %-26s %s\n" "AGENT_ID" "MODEL" "HARNESS"
echo "$SELECTED" | awk -F'\t' '{printf "  %-28s %-26s %s\n",$1,$2,$3}'
case "$TASK_LIMIT/$TASK_IDS" in
  0/) echo "  questions: FULL validated corpus${LANG_FLAG:+ ($LANG_FLAG)}" ;;
  *)  echo "  questions: ${TASK_IDS:-first $TASK_LIMIT}${LANG_FLAG:+ ($LANG_FLAG)}" ;;
esac
echo

if [ "$GO" -eq 0 ]; then
  # Plan only: ask the runner what it WOULD do (also shows already-covered cells).
  "${RUNNER[@]}" --fill --dry-run
  echo
  echo "(plan only -- re-run with --go to launch)"
  exit 0
fi

preflight || { echo "run_eval.sh: preflight failed -- fix the items above (see RUNBOOK.md, docs/running-your-models.md)"; exit 66; }

# Launch. The runner self-throttles (slot pools), dedups against bench.db (cells
# already covered are skipped), and is safe to re-run if interrupted -- relaunching
# continues where it left off.
"${RUNNER[@]}" --fill
echo
echo "== attempts recorded in bench-db/ =="
echo "results table:   tools/run_eval.sh --report ${MODELS:+--model $MODELS} ${HARNESSES:+--harness $HARNESSES}"
echo "watch dashboard: python3 tools/bench_dashboard.py  ->  http://127.0.0.1:8787/"
echo "per-attempt evidence: bench-db/blobs/attempt/<id>/ (brief, transcript, patch, test log)"
