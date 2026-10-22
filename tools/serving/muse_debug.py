#!/usr/bin/env python3
"""Muse-Glimmer-30B: does the model work OUTSIDE vLLM?

This is the decisive test. vLLM serves Muse through its GENERIC Transformers
fallback (it has no native implementation), and that fallback appears not to honour
the model's per-layer rope (`layer_rope_theta`) or `final_logit_softcapping`.

If THIS script produces clean text, the weights are fine and the bug is in vLLM's
fallback -> the fix is a vLLM model implementation or a --tool-parser-plugin route.
If THIS script also produces garbage, the problem is the weights/config themselves
and no serving stack will help.

Run:
  HF_HOME="$ZBENCH_SERVING_ROOT/hf-cache" \
    "$ZBENCH_SERVING_ROOT/venvs/vllm/bin/python" tools/serving/muse_debug.py
Needs one free GPU. Check with `nvidia-smi` first; a GPU is free if you stop the
vLLM server on :8014.
"""
import os
from pathlib import Path

import torch

MODEL_ID = "meta-models/Muse-Glimmer-30B"
os.environ.setdefault(
    "HF_HOME",
    os.environ.get("ZBENCH_HF_HOME")
    or str(Path(os.environ.get("ZBENCH_SERVING_ROOT",
                               Path(__file__).resolve().parents[2] / ".serving")) / "hf-cache"),
)

from transformers import AutoConfig, AutoProcessor, AutoModelForMultimodalLM

cfg = AutoConfig.from_pretrained(MODEL_ID)
tc = getattr(cfg, "text_config", None)
print("== config ==")
print("  architectures      :", getattr(cfg, "architectures", None))
print("  model_type         :", getattr(cfg, "model_type", None))
for attr in ("layer_rope_theta", "final_logit_softcapping", "layer_types", "head_dim"):
    v = getattr(tc, attr, "ABSENT") if tc is not None else "no text_config"
    if isinstance(v, list):
        v = f"list(len={len(v)}, distinct={sorted(set(map(str, v)))[:4]})"
    print(f"  {attr:19s}:", v)

print("\n== loading (transformers direct, no vLLM) ==")
processor = AutoProcessor.from_pretrained(MODEL_ID)
model = AutoModelForMultimodalLM.from_pretrained(MODEL_ID, dtype="auto", device_map="auto")
model.eval()

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Reply with exactly the word PONG and nothing else."},
]
inputs = processor.apply_chat_template(
    messages, tokenize=True, return_dict=True, return_tensors="pt",
    add_generation_prompt=True, enable_thinking=False,
).to(model.device)
in_len = inputs["input_ids"].shape[-1]

with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=32, do_sample=False)

text = processor.decode(out[0][in_len:], skip_special_tokens=False)
print("\n== raw generation ==")
print(repr(text))
try:
    print("\n== parse_response ==")
    print(processor.parse_response(text))
except Exception as e:
    print("  parse_response failed:", type(e).__name__, e)

print("\nVERDICT: clean text here => vLLM fallback is the bug.")
print("         garbage here too => weights/config problem, no stack will fix it.")
