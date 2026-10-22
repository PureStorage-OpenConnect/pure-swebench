#!/usr/bin/env bash
# Build the vLLM serving virtualenv used by every LOCAL open-weight agent row.
#
# WHY THE VENV IS NOT IN THIS REPO: it is ~7.7 GB and vLLM pulls a CUDA torch on top;
# model weights are worse (~60 GB each). Neither belongs in git. This script is the
# reproducible recipe; the artifacts it produces are deliberately untracked (.gitignore
# -- .serving/, bench-db/). Set ZBENCH_SERVING_ROOT to keep them off a small root disk.
#
# Everything is overridable, so another site can point these at its own storage:
#   ZBENCH_SERVING_ROOT base dir for venvs + weights  (default <repo>/.serving)
#   ZBENCH_VLLM_VENV   where to build the venv        (default $ZBENCH_SERVING_ROOT/venvs/vllm)
#   ZBENCH_HF_HOME     HuggingFace cache for weights  (default $ZBENCH_SERVING_ROOT/hf-cache)
#   ZBENCH_UV          path to the `uv` binary       (default: whatever is on PATH)
#
# Usage:
#   bash tools/serving/setup_venv.sh              # build + verify the DEFAULT venv
#   bash tools/serving/setup_venv.sh --verify     # verify only, build nothing
#   bash tools/serving/setup_venv.sh --muse-fork  # build the SEPARATE Muse venv
set -u

# ALL paths derive from ONE knob so another site relocates everything at once.
# Default is repo-local (./.serving, gitignored) so a fresh clone works unconfigured.
# On a machine with a small root disk, point this at bulk storage -- weights are ~60 GB
# per model and the vLLM venv is ~7.7 GB:
#   export ZBENCH_SERVING_ROOT=/path/to/zbench-serving
ZBENCH_SERVING_ROOT=${ZBENCH_SERVING_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)/.serving}

# Muse Glimmer needs a vLLM that stock releases do not have: the native model
# implementation + the muse_glimmer tool/reasoning parsers (upstream PR #51655, not yet
# merged as of 2026-08-16). It is built into its OWN venv so a third-party build can
# never take down the models served by the default venv. When the PR lands in a release,
# delete this, rebuild the default venv, and set Muse's stack back to `venv`.
MUSE_VENV=${ZBENCH_MUSE_VENV:-$(dirname "${ZBENCH_VLLM_VENV:-$ZBENCH_SERVING_ROOT/venvs/vllm}")/vllm-muse}
MUSE_SRC=${ZBENCH_MUSE_SRC:-$ZBENCH_SERVING_ROOT/src/vllm-muse}
MUSE_REPO=${ZBENCH_MUSE_REPO:-https://github.com/xianbaoqian/vllm}
MUSE_BRANCH=${ZBENCH_MUSE_BRANCH:-tiezhen/new-model-support}
MUSE_PIN=${ZBENCH_MUSE_PIN:-c4dc585}   # verified-good commit; record it in agents-meta

VENV=${ZBENCH_VLLM_VENV:-$ZBENCH_SERVING_ROOT/venvs/vllm}
HF=${ZBENCH_HF_HOME:-$ZBENCH_SERVING_ROOT/hf-cache}
UV=${ZBENCH_UV:-$(command -v uv)}
PY=${ZBENCH_VLLM_PYTHON:-3.12}

verify() {
    local rc=0
    if [ ! -x "$VENV/bin/python" ]; then
        echo "  [FAIL] no python at $VENV/bin/python"; return 1
    fi
    echo "  venv     : $VENV"
    "$VENV/bin/python" - <<'EOF' || rc=1
import importlib
for mod in ("vllm", "transformers", "torch"):
    try:
        m = importlib.import_module(mod)
        print(f"  {mod:12s}: {getattr(m, '__version__', '?')}")
    except Exception as e:
        print(f"  {mod:12s}: MISSING ({type(e).__name__})"); raise SystemExit(1)
import torch
print(f"  cuda        : available={torch.cuda.is_available()} devices={torch.cuda.device_count()}")
EOF
    # `ninja` must be resolvable ON PATH, not merely installed: vLLM shells out to it
    # while compiling kernels during startup profiling. Launching vllm by ABSOLUTE path
    # (without the venv bin on PATH) makes the worker die with
    # "[Errno 2] No such file or directory: 'ninja'". serve_local.sh sets PATH for this.
    if [ -x "$VENV/bin/ninja" ]; then
        echo "  ninja       : $VENV/bin/ninja"
    else
        echo "  [FAIL] ninja missing -> vLLM workers will die during profiling"; rc=1
    fi
    echo "  hf cache : $HF ($(du -sh "$HF" 2>/dev/null | cut -f1 || echo 'absent'))"
    return $rc
}

if [ "${1:-}" = "--verify" ]; then
    echo "== verifying serving venv =="; verify; exit $?
fi

if [ "${1:-}" = "--muse-fork" ]; then
    command -v "$UV" >/dev/null 2>&1 || { echo "uv not found (set ZBENCH_UV)"; exit 1; }
    export UV_CACHE_DIR=${UV_CACHE_DIR:-$(dirname "$MUSE_VENV")/.uv-cache}
    export TMPDIR=${TMPDIR:-$(dirname "$MUSE_VENV")/.tmp}
    mkdir -p "$UV_CACHE_DIR" "$TMPDIR"
    echo "== Muse fork venv: $MUSE_VENV =="
    echo "   source: $MUSE_REPO @ $MUSE_BRANCH (pin $MUSE_PIN)"
    "$UV" venv --python "$PY" "$MUSE_VENV" || exit 1
    if [ ! -d "$MUSE_SRC/.git" ]; then
        git clone -b "$MUSE_BRANCH" "$MUSE_REPO" "$MUSE_SRC" || exit 1
    fi
    git -C "$MUSE_SRC" fetch --all --quiet 2>/dev/null
    git -C "$MUSE_SRC" checkout --quiet "$MUSE_PIN" 2>/dev/null \
        || echo "   [warn] pin $MUSE_PIN not found; staying on $MUSE_BRANCH HEAD"
    echo "   building at $(git -C "$MUSE_SRC" rev-parse --short HEAD)"
    # VLLM_USE_PRECOMPILED skips a full CUDA kernel build (minutes, not hours); the
    # cuda bin on PATH is for the JIT paths that still shell out to nvcc/ninja.
    VLLM_USE_PRECOMPILED=1 PATH="$MUSE_VENV/bin:/usr/local/cuda/bin:$PATH" \
        "$UV" pip install --python "$MUSE_VENV/bin/python" -e "$MUSE_SRC" ninja || exit 1
    echo "== verify =="
    "$MUSE_VENV/bin/python" - <<'EOF'
import vllm
from vllm.model_executor.models.registry import ModelRegistry as R
print("  vllm:", vllm.__version__)
ok = "MuseGlimmerForConditionalGeneration" in R.get_supported_archs()
print("  MuseGlimmerForConditionalGeneration registered:", ok)
raise SystemExit(0 if ok else 1)
EOF
    exit $?
fi

command -v "$UV" >/dev/null 2>&1 || { echo "uv not found (set ZBENCH_UV)"; exit 1; }

echo "== building serving venv at $VENV =="
mkdir -p "$(dirname "$VENV")" "$HF" || exit 1
# Keep uv's cache and tempdir OFF the small local disk too -- an unredirected build
# can put tens of GB under / and fill it.
export UV_CACHE_DIR=${UV_CACHE_DIR:-$(dirname "$VENV")/.uv-cache}
export TMPDIR=${TMPDIR:-$(dirname "$VENV")/.tmp}
mkdir -p "$UV_CACHE_DIR" "$TMPDIR"

"$UV" venv --python "$PY" "$VENV" || exit 1
# `ninja` is REQUIRED (see verify()). hf_transfer is deliberately NOT requested: the
# extra was removed in huggingface_hub 1.x ("does not have an extra named hf-transfer")
# and hf_xet replaces it. Setting HF_HUB_ENABLE_HF_TRANSFER=1 here would raise.
"$UV" pip install --python "$VENV/bin/python" vllm huggingface_hub ninja || exit 1

echo "== verify =="
verify
