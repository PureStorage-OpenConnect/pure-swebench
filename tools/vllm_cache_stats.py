#!/usr/bin/env python3
"""Record each self-hosted vLLM model's PREFIX-CACHE HIT RATE from its server log.

WHY (project owner 2026-08-19): vLLM 0.27 does NOT report cached_tokens per request
(the OpenAI usage object returns prompt_tokens_details=null), so the harness stores
cache_read_tokens=0 for every local cell and model_prices bills 100% of the prompt at
the full input rate -- overstating local $/task for cache-friendly models. vLLM DOES,
however, log an aggregate "Prefix cache hit rate: X%" line. For the scale of testing we
run, the per-task cached fraction is ~constant, so this ONE rate per model is a good
approximation: model_prices reclassifies hit_rate x input as cache_read (Option A).

This tool scans the serving logs and writes tools/prices/vllm_cache_hit.json. Re-run it
whenever the servers have processed a representative batch (the logged rate is a running
average since server start, so run it AFTER a fill, not at cold start).

  python3 tools/vllm_cache_stats.py            # write the json
  python3 tools/vllm_cache_stats.py --print     # also print the table

Models with a hybrid / linear-attention architecture (Mamba, Gated DeltaNet) run with
enable_prefix_caching=False -- there is no KV prefix to reuse, so hit_rate is 0.0 and NO
discount is applied (correct).
"""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_CONF = Path(os.environ.get("ZBENCH_SERVING_CONF", _HERE / "serving" / "models.conf"))
_OUT = _HERE / "prices" / "vllm_cache_hit.json"

_HIT_RE = re.compile(r"Prefix cache hit rate:\s*([0-9.]+)%")
_PC_RE = re.compile(r"enable_prefix_caching=(True|False)")


def _logs_dir() -> Path:
    """Resolve the serving logs dir the same way serve_local.sh does."""
    for cand in (
        os.environ.get("ZBENCH_SERVING_LOGS"),
        (os.environ.get("ZBENCH_SERVING_ROOT", "") + "/logs") if os.environ.get("ZBENCH_SERVING_ROOT") else None,
        str(_ROOT / ".serving" / "logs"),
    ):
        if cand and Path(cand).is_dir():
            return Path(cand)
    return _ROOT / ".serving" / "logs"


def _aliases() -> list[str]:
    if not _CONF.exists():
        return []
    out = []
    for line in _CONF.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line.split("|", 1)[0].strip())
    return out


def collect() -> dict:
    logs = _logs_dir()
    models = {}
    for alias in _aliases():
        log = logs / f"{alias}.log"
        if not log.exists():
            models[alias] = {"hit_rate": None, "prefix_caching": None, "note": "no log found"}
            continue
        text = log.read_text(errors="replace")
        hits = _HIT_RE.findall(text)
        pc = _PC_RE.findall(text)
        prefix_on = (pc[-1] == "True") if pc else None
        # LAST logged rate = cumulative average up to now (dominated by this run when the
        # server was started fresh for it). Percent -> fraction 0..1.
        rate = (float(hits[-1]) / 100.0) if hits else None
        if prefix_on is False:
            rate = 0.0  # hybrid/linear-attn model: no prefix cache exists
        models[alias] = {
            "hit_rate": rate,
            "prefix_caching": prefix_on,
            "source_log": f".serving/logs/{log.name}",
        }
    return models


def main() -> int:
    models = collect()
    doc = {
        "_doc": ("Approx PREFIX-CACHE HIT RATE per self-hosted vLLM model, from the "
                 "'Prefix cache hit rate' line in each server log. model_prices uses it to "
                 "reclassify hit_rate x input as cache_read for self-hosted models whose "
                 "usage does not report cached_tokens (vLLM 0.27). Regenerate with "
                 "tools/vllm_cache_stats.py AFTER a representative batch. See its docstring."),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "models": models,
    }
    _OUT.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"wrote {_OUT}")
    if "--print" in sys.argv:
        for a, v in models.items():
            hr = v.get("hit_rate")
            print(f"  {a:32} hit_rate={hr if hr is not None else '-'}  prefix_caching={v.get('prefix_caching')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
