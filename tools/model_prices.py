#!/usr/bin/env python3
"""W58: model price table + cost computation for the leaderboard.

WHY (Brian Gold, 2026-07-31): the leaderboard's $/task is EMPTY for every
Foundry-gateway + local agent -- those APIs don't return a cost field, and the
harness stored whatever the provider gave (nothing). Only direct-Anthropic
(claude-cli-*, pi-anthropic-*) reports cost. FIX: compute cost ourselves from the
captured token counts x a price table. Prices are the canonical home-provider list
prices from https://models.dev/ (the DB pi + opencode use), USD per 1M tokens.

Provenance: extracted 2026-07-31 from `curl https://models.dev/api.json`. Refresh: re-pull api.json and re-read the home-provider cost for
each model (anthropic / openai / deepseek->fireworks-ai / zhipuai / moonshotai).

Note (see W58): the raw `total_tokens` is dominated by cache-read, which is counted
very differently per harness (claude-cli reports cumulative per-turn cache-read in the
MILLIONS; the pi/Foundry path far less). So this module returns BOTH a full cost
(incl. cache_read + cache_write) AND a cache-independent cost (input+output only) for
apples-to-apples comparison.
"""
from __future__ import annotations

import json
from pathlib import Path

# Pricing DATA + FORMAT = models.dev, pinned in tools/prices/models_dev.json (generate with
# tools/prices/refresh_prices.py). We do NOT hand-transcribe rates. `cache_write` there is the 5-min
# ephemeral rate (1.25x input); the 1-hour cache write is 2x input (= 1.6x this value) and is applied
# by the HARNESS's cache TTL (see cost_usd(cache_ttl=...)). PRICES exposes the model-key -> cost object
# (models.dev shape) for backward compatibility.
_SNAPSHOT_PATH = Path(__file__).resolve().parent / "prices" / "models_dev.json"
_SNAPSHOT = json.loads(_SNAPSHOT_PATH.read_text())
PRICES = {k: v["cost"] for k, v in _SNAPSHOT["models"].items()}

# Hosted REFERENCE prices for open-weight models we serve on our OWN hardware (vLLM /
# local). Standing decision, project owner 2026-08-18 (supersedes + removes the capex-amortization
# cost model): an on-prem open-weight model is costed at what a PUBLIC HOST would charge to
# serve the same weights per token, so on-prem vs cloud is one apples-to-apples per-token
# comparison. Entries live in prices/open_weight_hosted.json (hand-authored; refreshed daily
# by tools/price_search.py). Only status=='pinned' entries with a non-null cost are merged
# into PRICES -- a 'needs_price' model stays UN-PRICED (renders free*) until a public
# reference appears. The model KEY doubles as the agent-name substring pattern (below), so a
# serving agent (e.g. pi-vllm-gpt-oss-120b) resolves to its own reference price.
_OPEN_WEIGHT_PATH = Path(__file__).resolve().parent / "prices" / "open_weight_hosted.json"
try:
    _OPEN_WEIGHT = json.loads(_OPEN_WEIGHT_PATH.read_text()).get("models", {})
except (OSError, json.JSONDecodeError):
    _OPEN_WEIGHT = {}
# order longest-key-first so a specific build (qwen3.6-27b) is matched before a shorter one
_OPEN_WEIGHT_KEYS = sorted(_OPEN_WEIGHT, key=len, reverse=True)
for _k in _OPEN_WEIGHT_KEYS:
    _entry = _OPEN_WEIGHT[_k] or {}
    if _entry.get("status") == "pinned" and _entry.get("cost"):
        PRICES[_k] = _entry["cost"]

# Approx PREFIX-CACHE HIT RATE per self-hosted vLLM model (tools/vllm_cache_stats.py reads it
# from the server logs). vLLM 0.27 does NOT report cached_tokens per request
# (prompt_tokens_details=null), so the harness stores cache_read_tokens=0 and the whole prompt
# would bill at the full input rate -- overstating local $/task. Option A (project owner 2026-08-19):
# reclassify hit_rate x input as cache_read (see split_self_hosted_cache). Hybrid / linear-attn
# models (Mamba, Gated DeltaNet) run with prefix caching OFF, so their hit_rate is 0 (no discount).
_VLLM_CACHE_PATH = Path(__file__).resolve().parent / "prices" / "vllm_cache_hit.json"
try:
    _VLLM_CACHE = json.loads(_VLLM_CACHE_PATH.read_text()).get("models", {})
except (OSError, json.JSONDecodeError):
    _VLLM_CACHE = {}
_VLLM_CACHE_KEYS = sorted(_VLLM_CACHE, key=len, reverse=True)  # longest key first (specific build wins)

# cost fields cost_usd() knows how to price; anything else on a used model's models.dev cost object is
# an UNPRICED gap the guard test should surface (allowlisted ones are known/accepted-as-unactionable).
SUPPORTED_COST_FIELDS = {"input", "output", "cache_read", "cache_write"}
_ALLOWLIST_UNPRICED = {"tiers", "context_over_200k"}  # per-REQUEST context tiering; not applicable to aggregate tokens

# 1-hour cache write costs 2x input vs the 5-min 1.25x input -> a 1.6x multiple on the models.dev
# (5-min) cache_write value. Reads are TTL-independent.
_TTL_CACHE_WRITE_MULT = {"5m": 1.0, "1h": 1.6}


def harness_cache_ttl(agent_or_model: str) -> str:
    """Cache TTL the HARNESS sets on its cache_control (not a model property). claude-code writes
    1-hour cache (verified from the API cache_creation split); pi writes 5-minute. Default 5m."""
    s = (agent_or_model or "").lower()
    if s.startswith("claude-cli") or "claude-hermetic" in s or "claude-code" in s:
        return "1h"
    return "5m"


def unpriced_cost_fields(model_key: str) -> set:
    """models.dev cost keys on this model that cost_usd() does NOT price (minus the known allowlist)."""
    cost = (_SNAPSHOT["models"].get(model_key) or {}).get("cost", {})
    return set(cost) - SUPPORTED_COST_FIELDS - _ALLOWLIST_UNPRICED

# Ordered (substring -> price key): FIRST match wins, so put the more specific
# ids first (opus-4-8 before opus). Matches against an agent config_id or a raw
# model name (case-insensitive), covering our pi-foundry-* / claude-cli-* /
# pi-anthropic-* / pi-local-* / *-hermetic-* naming.
_PATTERNS = [
    ("opus-4-8", "claude-opus-4-8"),
    ("opus-4-7", "claude-opus-4-7"),
    ("opus-4-6", "claude-opus-4-6"),
    ("opus-5", "claude-opus-5"),
    ("sonnet-4-6", "claude-sonnet-4-6"),
    ("haiku-4-5", "claude-haiku-4-5"),
    ("haiku", "claude-haiku-4-5"),
    ("fable", "claude-fable-5"),
    ("gpt-5.6-sol", "gpt-5.6-sol"),
    ("gpt-5.6-terra", "gpt-5.6-terra"),
    ("gpt-5.6-luna", "gpt-5.6-luna"),
    ("gpt-5.5", "gpt-5.5"),
    ("deepseek-v4-flash", "deepseek-v4-flash"),
    ("deepseek-v4-pro", "deepseek-v4-pro"),
    ("deepseek", "deepseek-v4-pro"),
    ("kimi-k3", "kimi-k3"),
    ("kimi-k2.6", "kimi-k2.6"),
    ("kimi-k2p6", "kimi-k2.6"),
    ("kimi", "kimi-k2.6"),
    ("glm-5.2", "glm-5.2"),
    ("glm", "glm-5.2"),
    ("qwen3-coder", "qwen3-coder"),
    ("qwen", "qwen3-coder"),
]

# Open-weight self-hosted models are matched by their registry KEY as the substring
# (pi-vllm-gpt-oss-120b -> gpt-oss-120b). These go FIRST (longest key first) so a specific
# build (qwen3.6-27b) wins BEFORE the broad catch-alls above -- without this,
# `pi-vllm-qwen3.6-27b` would collide with `("qwen","qwen3-coder")` and bill the wrong
# model's rate. price_key() then only returns a key that is actually PRICED, so a
# 'needs_price' registry model still resolves to None (free*) until its price is filled in.
_ALL_PATTERNS = [(k, k) for k in _OPEN_WEIGHT_KEYS] + _PATTERNS


# A SELF-HOSTED agent serves open weights on our OWN hardware. Standing decision, project owner
# 2026-08-18: it is costed at a PUBLIC HOST's per-token reference price (open_weight_hosted.json
# / models_dev.json), NOT free and NOT a capex amortization -- so on-prem vs cloud compare
# per-token. is_self_hosted() is kept as a descriptive flag (hosting label / display); it no
# longer forces the price to None. A local model reads as free* ONLY when no public reference
# price exists for it yet (its registry entry is 'needs_price').
_SELF_HOSTED_MARKERS = ("-vllm-", "-local-", "-ollama-", "vllm-local")


def is_self_hosted(agent_or_model: str) -> bool:
    """True iff this agent serves the model on our own hardware (vLLM/local)."""
    s = (agent_or_model or "").lower()
    return any(m in s for m in _SELF_HOSTED_MARKERS)


def vllm_cache_hit_rate(agent_or_model: str) -> float | None:
    """Approx prefix-cache HIT fraction (0..1) for a self-hosted model, or None if unknown.
    Sourced from tools/prices/vllm_cache_hit.json (regenerate with tools/vllm_cache_stats.py)."""
    s = (agent_or_model or "").lower()
    for k in _VLLM_CACHE_KEYS:
        if k in s:
            return (_VLLM_CACHE[k] or {}).get("hit_rate")
    return None


def split_self_hosted_cache(agent_or_model: str, input_tokens, cache_read_tokens):
    """APPROXIMATE cached tokens for a self-hosted model that reports NO cache_read.

    vLLM 0.27 does not return cached_tokens per request, so the harness stores
    cache_read_tokens=0 and the whole prompt would bill at the full input rate. When a
    prefix-cache hit rate is known for the model (vllm_cache_hit.json), reclassify
    hit_rate x input as cache_read (Option A, project owner 2026-08-19). Returns
    (input_adj, cache_read_adj); a NO-OP when the model already has a measured
    cache_read, is not self-hosted, or has no known hit rate. Callers that DISPLAY the
    token split (dashboard) should call this too, so tokens and cost stay consistent."""
    it = input_tokens or 0
    cr = cache_read_tokens or 0
    if cr or not is_self_hosted(agent_or_model):
        return it, cr
    hr = vllm_cache_hit_rate(agent_or_model)
    if not hr:
        return it, cr
    cached = int(round(it * hr))
    return it - cached, cached


def price_key(agent_or_model: str) -> str | None:
    """Resolve an agent config_id or model name to a PRICES key (or None).

    Returns None when either no pattern matches OR the matched model has no price yet (an
    open-weight model whose registry entry is still 'needs_price'); both render as free*.
    """
    s = (agent_or_model or "").lower()
    for pat, key in _ALL_PATTERNS:
        if pat in s:
            return key if key in PRICES else None
    return None


def cost_usd(agent_or_model: str, input_tokens=0, output_tokens=0, cache_read_tokens=0,
             cache_write_tokens=0, *, include_cache=True, cache_ttl=None) -> float | None:
    """Compute USD cost from token counts x the pinned models.dev price for this agent's model.
    Returns None if the model is unknown (e.g. a truly local model with no list price).
    include_cache=False gives the cache-independent (input+output) cost for apples-to-apples;
    include_cache=True adds cache_read + cache_write. cache_write is priced at the harness's cache
    TTL: 5-min (models.dev value, 1.25x input) or 1-hour (2x input = 1.6x that). cache_ttl defaults
    to harness_cache_ttl(agent) so callers get the right rate without knowing the harness."""
    k = price_key(agent_or_model)
    if not k:
        return None
    p = PRICES[k]
    # Self-hosted models report no per-request cached_tokens (vLLM 0.27) -> approximate the
    # cached fraction from the logged prefix-cache hit rate so the prompt is not billed 100%
    # at the input rate. No-op for cloud models (measured cache) and 0-hit-rate models.
    input_tokens, cache_read_tokens = split_self_hosted_cache(agent_or_model, input_tokens, cache_read_tokens)
    ttl = cache_ttl or harness_cache_ttl(agent_or_model)
    cw_rate = p.get("cache_write", 0) * _TTL_CACHE_WRITE_MULT.get(ttl, 1.0)
    tok = lambda x: (x or 0)
    c = tok(input_tokens) * p["input"] + tok(output_tokens) * p["output"]
    if include_cache:
        c += tok(cache_read_tokens) * p.get("cache_read", 0)
        c += tok(cache_write_tokens) * cw_rate
    return c / 1_000_000.0


def _main():
    """Demo/verify: recompute per-agent avg cost from bench.db token counts."""
    import sqlite3
    from pathlib import Path
    db = Path(__file__).resolve().parent.parent / "bench-db" / "bench.db"
    c = sqlite3.connect(str(db))
    rows = c.execute("""select config_id, avg(input_tokens), avg(output_tokens),
                        avg(cache_read_tokens), avg(cache_write_tokens), avg(cost_usd), count(*)
                        from attempt group by config_id order by config_id""").fetchall()
    print(f"{'agent':34}{'key':18}{'calc$full':>11}{'calc$io':>10}{'reported$':>11}")
    for cid, ai, ao, ac, aw, rep, n in rows:
        k = price_key(cid) or "-"
        full = cost_usd(cid, ai, ao, ac, aw)
        io = cost_usd(cid, ai, ao, 0)
        fs = f"{full:.4f}" if full is not None else "-"
        ios = f"{io:.4f}" if io is not None else "-"
        rs = f"{rep:.4f}" if rep is not None else "-"
        print(f"{cid:34}{k:18}{fs:>11}{ios:>10}{rs:>11}")
    c.close()


if __name__ == "__main__":
    _main()
