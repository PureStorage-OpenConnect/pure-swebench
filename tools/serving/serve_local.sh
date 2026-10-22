#!/usr/bin/env bash
# Start / stop / inspect the LOCAL open-weight model servers described by models.conf.
#
# Every server is launched DETACHED (nohup + disown, so PPID becomes 1). A server
# started from an interactive shell or an agent's background task dies with that
# session; we lost a running model that way. Check with `ps -o ppid= -p <pid>` -> 1.
#
# Usage:
#   bash tools/serving/serve_local.sh start [alias ...]   # default: every enabled row
#   bash tools/serving/serve_local.sh stop  [alias ...]
#   bash tools/serving/serve_local.sh status
#   bash tools/serving/serve_local.sh check [alias ...]   # prove TOOL CALLING works
#
# Env overrides: ZBENCH_SERVING_ROOT (one knob for all paths), ZBENCH_VLLM_VENV,
#                ZBENCH_HF_HOME, ZBENCH_SERVING_LOGS, ZBENCH_VLLM_IMAGE,
#                ZBENCH_GPU_UTIL, ZBENCH_SERVING_CONF
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
CONF=${ZBENCH_SERVING_CONF:-$HERE/models.conf}
# ALL paths derive from ONE knob so another site relocates everything at once.
# Default is repo-local (./.serving, gitignored) so a fresh clone works unconfigured.
# On a machine with a small root disk, point this at bulk storage -- weights are ~60 GB
# per model and the vLLM venv is ~7.7 GB:
#   export ZBENCH_SERVING_ROOT=/path/to/zbench-serving
ZBENCH_SERVING_ROOT=${ZBENCH_SERVING_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)/.serving}
VENV=${ZBENCH_VLLM_VENV:-$ZBENCH_SERVING_ROOT/venvs/vllm}
HF=${ZBENCH_HF_HOME:-$ZBENCH_SERVING_ROOT/hf-cache}
LOGS=${ZBENCH_SERVING_LOGS:-$ZBENCH_SERVING_ROOT/logs}
IMAGE=${ZBENCH_VLLM_IMAGE:-vllm/vllm-openai:latest}
UTIL=${ZBENCH_GPU_UTIL:-0.92}

mkdir -p "$LOGS"

rows() {   # alias|repo|stack|gpus|port|tp|max_len|extra   (comments/blanks stripped)
    grep -vE '^\s*(#|$)' "$CONF"
}

select_rows() {   # optional alias filter
    if [ "$#" -eq 0 ]; then rows; return; fi
    local want=" $* "
    rows | while IFS='|' read -r a rest; do
        case "$want" in *" $a "*) echo "$a|$rest";; esac
    done
}

start_one() {
    local alias=$1 repo=$2 stack=$3 gpus=$4 port=$5 tp=$6 maxlen=$7 extra=$8
    local log="$LOGS/$alias.log"
    if curl -sf -m 3 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
        echo "  [skip] $alias already healthy on :$port"; return 0
    fi
    echo "  [start] $alias  stack=$stack gpus=$gpus port=$port tp=$tp -> $log"
    if [ "$stack" = "docker" ]; then
        # Gemma 4 needs vLLM 0.21.x: on 0.27.1 transformers 5.15 refuses a global
        # `head_dim` read (the model is heterogeneous per layer), and forcing it past
        # that loads weights of the wrong shape. See README "Why two stacks".
        docker rm -f "zbench-$alias" >/dev/null 2>&1
        nohup docker run --rm --name "zbench-$alias" \
            --gpus "\"device=$gpus\"" --shm-size 32g -p "$port:8000" \
            -v "$HF:/root/.cache/huggingface" \
            "$IMAGE" --model "$repo" --served-model-name "$alias" \
            --tensor-parallel-size "$tp" --gpu-memory-utilization "$UTIL" \
            --max-model-len "$maxlen" $extra \
            > "$log" 2>&1 < /dev/null &
        disown
    else
        # `venv` uses the default build; `venv:<name>` uses a SIBLING venv dir, for a
        # model that needs a different vLLM (Muse needs an unmerged branch).
        local mvenv="$VENV"
        case "$stack" in
            venv:/*) mvenv="${stack#venv:}" ;;
            venv:*)  mvenv="$(dirname "$VENV")/${stack#venv:}" ;;
        esac
        if [ ! -x "$mvenv/bin/vllm" ]; then
            echo "  [FAIL] $alias: no vllm at $mvenv/bin/vllm (build it first)"; return 1
        fi
        # PATH must contain the venv bin: vLLM shells out to `ninja` during startup
        # profiling and dies with "No such file or directory: 'ninja'" without it.
        # /usr/local/cuda/bin is there for source builds whose JIT needs nvcc.
        nohup env PATH="$mvenv/bin:/usr/local/cuda/bin:$PATH" CUDA_VISIBLE_DEVICES="$gpus" HF_HOME="$HF" \
            "$mvenv/bin/vllm" serve "$repo" --served-model-name "$alias" \
            --host 127.0.0.1 --port "$port" \
            --tensor-parallel-size "$tp" --gpu-memory-utilization "$UTIL" \
            --max-model-len "$maxlen" $extra \
            > "$log" 2>&1 < /dev/null &
        disown
    fi
}

stop_one() {
    local alias=$1 stack=$3 port=$5
    if [ "$stack" = "docker" ]; then
        docker rm -f "zbench-$alias" >/dev/null 2>&1 && echo "  [stop] $alias (container)" && return
        # A server started by hand does NOT carry our name (the running Gemma was
        # `gemma4`). Falling through to the port kill would shoot the host-side
        # docker-proxy and leave the container up with a dead port, so find the
        # container BY PUBLISHED PORT before touching any pid.
        local cid; cid=$(docker ps -q --filter "publish=$port" 2>/dev/null | head -1)
        if [ -n "$cid" ]; then
            local cname; cname=$(docker inspect -f '{{.Name}}' "$cid" 2>/dev/null | sed 's|^/||')
            docker rm -f "$cid" >/dev/null 2>&1 \
                && echo "  [stop] $alias (container $cname on :$port)" && return
        fi
        echo "  [--]   $alias: no container on :$port"; return
    fi
    # Kill by PORT, never `pkill -f <model>`: -f matches the caller's OWN command line,
    # so `pkill -f Muse-Glimmer` happily kills the shell that ran it.
    local pids; pids=$(lsof -ti ":$port" 2>/dev/null)
    if [ -n "$pids" ]; then kill $pids 2>/dev/null && echo "  [stop] $alias (pid $pids)"
    else echo "  [--]   $alias not running on :$port"; fi
}

cmd_status() {
    printf "  %-28s %-7s %-6s %-8s %s\n" ALIAS PORT STACK STATE GPUS
    rows | while IFS='|' read -r a repo stack gpus port tp maxlen extra; do
        local state; state=$(curl -sf -m 3 "http://127.0.0.1:$port/health" >/dev/null 2>&1 && echo READY || echo DOWN)
        printf "  %-28s %-7s %-6s %-8s %s\n" "$a" "$port" "$stack" "$state" "$gpus"
    done
}

# A server answering /health is NOT proof it is usable: the harnesses need TOOL CALLS.
# This sends a real tools request and asserts finish_reason=tool_calls.
cmd_check() {
    select_rows "$@" | while IFS='|' read -r a repo stack gpus port tp maxlen extra; do
        printf "  %-28s " "$a"
        curl -sS -m 180 -X POST "http://127.0.0.1:$port/v1/chat/completions" \
            -H 'Content-Type: application/json' -d "{
              \"model\":\"$a\",\"max_tokens\":300,\"temperature\":0,
              \"messages\":[{\"role\":\"user\",\"content\":\"Use the Write tool to write hello into /tmp/x.txt. Call the tool.\"}],
              \"tools\":[{\"type\":\"function\",\"function\":{\"name\":\"Write\",\"parameters\":{\"type\":\"object\",\"properties\":{\"file_path\":{\"type\":\"string\"},\"content\":{\"type\":\"string\"}},\"required\":[\"file_path\",\"content\"]}}}],
              \"tool_choice\":\"auto\"}" 2>/dev/null | python3 -c "
import json,sys
raw=sys.stdin.read()
try: d=json.loads(raw)
except Exception: print('UNREACHABLE'); raise SystemExit
if d.get('error'): print('ERROR:', str(d['error'].get('message'))[:90]); raise SystemExit
ch=(d.get('choices') or [{}])[0]; m=ch.get('message') or {}
print('TOOL CALL OK' if m.get('tool_calls') else f\"NO TOOL CALL (finish={ch.get('finish_reason')})\")
"
    done
}

case "${1:-status}" in
    start)  shift; select_rows "$@" | while IFS='|' read -r a b c d e f g h; do start_one "$a" "$b" "$c" "$d" "$e" "$f" "$g" "$h"; done
            echo "  (loading takes minutes; poll: bash $0 status)" ;;
    stop)   shift; select_rows "$@" | while IFS='|' read -r a b c d e f g h; do stop_one "$a" "$b" "$c" "$d" "$e"; done ;;
    status) cmd_status ;;
    check)  shift; cmd_check "$@" ;;
    *)      echo "usage: $0 {start|stop|status|check} [alias ...]"; exit 2 ;;
esac
