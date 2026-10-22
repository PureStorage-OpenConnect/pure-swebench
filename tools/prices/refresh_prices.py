#!/usr/bin/env python3
"""Regenerate the pinned models.dev price snapshot for our agents' models.

We adopt models.dev as the SOURCE and FORMAT of pricing data. Rather than hand-
transcribe rates (which drops fields -- cache_write, tiers -- and drifts), this
pulls models.dev api.json and writes each of our models' HOME-provider cost object
VERBATIM into `models_dev.json` (committed, pinned, with provenance). Refresh:

    curl -s https://models.dev/api.json -o /tmp/models_dev.json
    python3 tools/prices/refresh_prices.py /tmp/models_dev.json

Pinning records WHICH prices produced a leaderboard number and lets us re-price
against a different snapshot ("what would it cost at new prices?").
"""
from __future__ import annotations
import json, sys, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "models_dev.json"

# our model key -> (models.dev provider id, model id under that provider's `models`)
HOME = {
    "claude-opus-5":     ("anthropic", "claude-opus-5"),
    "claude-opus-4-8":   ("anthropic", "claude-opus-4-8"),
    "claude-opus-4-7":   ("anthropic", "claude-opus-4-7"),
    "claude-opus-4-6":   ("anthropic", "claude-opus-4-6"),
    "claude-sonnet-4-6": ("anthropic", "claude-sonnet-4-6"),
    "claude-fable-5":    ("anthropic", "claude-fable-5"),
    "claude-haiku-4-5":  ("anthropic", "claude-haiku-4-5"),
    "gpt-5.5":           ("openai", "gpt-5.5"),
    "deepseek-v4-pro":   ("fireworks-ai", "accounts/fireworks/models/deepseek-v4-pro"),
    "deepseek-v4-flash": ("fireworks-ai", "accounts/fireworks/models/deepseek-v4-flash"),
    "kimi-k3":           ("moonshotai", "kimi-k3"),
    "kimi-k2.6":         ("moonshotai", "kimi-k2.6"),
    "glm-5.2":           ("zhipuai", "glm-5.2"),
}
# self-hosted (local GPU server): no models.dev home price -> a manual REFERENCE list price.
MANUAL = {
    "qwen3-coder": {"cost": {"input": 0.13, "output": 0.5, "cache_read": 0, "cache_write": 0},
                    "home": "(local self-hosted; reference list price, not a home-provider quote)"},
}


def main(argv=None):
    argv = argv or sys.argv[1:]
    src = Path(argv[0]) if argv else Path("/tmp/models_dev.json")
    d = json.load(open(src))
    models = {}
    missing = []
    for key, (pid, mid) in HOME.items():
        m = ((d.get(pid) or {}).get("models") or {}).get(mid)
        if not m or "cost" not in m:
            missing.append(key); continue
        models[key] = {"home": f"{pid}/{mid}", "cost": m["cost"]}
    for key, v in MANUAL.items():
        models[key] = v
    if missing:
        print(f"WARNING: no models.dev cost for: {missing}", file=sys.stderr)
    out = {
        "provenance": {
            "source": "https://models.dev/api.json",
            "pulled": datetime.date.today().isoformat(),
            "note": "home-provider list cost per model, verbatim; qwen3-coder is a local self-hosted "
                    "reference. cache_write here is the 5-min ephemeral rate (1.25x input); 1-hour "
                    "cache write is 2x input (1.6x this value) -- applied by the harness's cache TTL.",
        },
        "models": models,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {OUT} ({len(models)} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
