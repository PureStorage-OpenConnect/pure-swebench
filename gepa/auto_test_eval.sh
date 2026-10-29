#!/usr/bin/env bash
# Wait for each agent's GEPA summary.json, then run its held-out test evaluation.
cd "$(dirname "$0")/.."
for a in "$@"; do (
  while [ ! -f gepa/runs/$a/summary.json ]; do sleep 120; done
  env "ZBENCH_SLOT_CAP_provider__vllm-qwen3.6-27b=2" 'ZBENCH_SLOT_CAP_provider__vllm-gemma-4-31b=3' 'ZBENCH_SLOT_CAP_provider__vllm-muse-glimmer=3' \
    gepa/.venv/bin/python gepa/eval_test.py --agent $a > gepa/runs/$a/test_eval.log 2>&1
) & done; wait
