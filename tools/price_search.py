#!/usr/bin/env python3
"""Daily search for a PUBLIC per-token price for the open-weight models we self-host that
have none yet (open_weight_hosted.json entries with status=='needs_price').

Standing decision, project owner 2026-08-18: an on-prem open-weight model is costed at what a public
host WOULD charge to serve the same weights; a model with no public reference reads as free*
until one appears, and we re-check every day. This script is that daily check.

Sources (public, no auth):
  * OpenRouter model catalog  https://openrouter.ai/api/v1/models  -- per-token prompt/completion
    (+ input_cache_read) for hundreds of hosted open models. Prices are USD PER TOKEN; we x1e6
    to the per-1,000,000-token convention this repo (and models.dev) use.
  * models.dev                https://models.dev/api.json          -- the snapshot refresh_prices.py
    already pins from; cost is already per-1M.

For each needs_price model it normalises the key (lowercase, alnum-only) and looks for a model
whose id/slug CONTAINS that key (so a fictional/absent build simply never matches and stays
needs_price -- no fabricated price). On a hit it rewrites the entry: status='pinned', a cost
object, reference_host, source_url, fetched_at=today. It always stamps last_checked=today so the
registry shows the search ran. DRY-RUN by default; pass --apply to write.

Usage:
  tools/price_search.py                 # dry-run: show what a price would be pinned to
  tools/price_search.py --apply         # write open_weight_hosted.json
  tools/price_search.py --apply --quiet # for cron (only prints on a change)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REG_PATH = HERE / "prices" / "open_weight_hosted.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
MODELSDEV_URL = "https://models.dev/api.json"
_UA = {"User-Agent": "zbench-price-search/1.0"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _get_json(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------- #
# per-source lookups: return (cost_obj_per_1M, host_label, source_url) or None
# --------------------------------------------------------------------------- #
def _from_openrouter(catalog, key_norm: str):
    for m in (catalog or {}).get("data", []) or []:
        mid = m.get("id") or m.get("canonical_slug") or ""
        if key_norm and key_norm in _norm(mid):
            pr = m.get("pricing") or {}
            try:
                pin = float(pr.get("prompt")) * 1e6
                pout = float(pr.get("completion")) * 1e6
            except (TypeError, ValueError):
                continue
            if pin <= 0 and pout <= 0:
                continue   # a $0 "free" tier is not a reference cost
            try:
                pcache = float(pr.get("input_cache_read")) * 1e6
            except (TypeError, ValueError):
                pcache = pin
            cost = {"input": round(pin, 6), "output": round(pout, 6),
                    "cache_read": round(pcache, 6), "cache_write": 0}
            return cost, f"openrouter:{mid}", f"https://openrouter.ai/{mid}"
    return None


def _from_modelsdev(catalog, key_norm: str):
    models = (catalog or {}).get("models") or catalog or {}
    if isinstance(models, dict):
        items = models.items()
    else:
        items = [(m.get("id", ""), m) for m in models]
    for mid, m in items:
        if not isinstance(m, dict):
            continue
        hay = _norm(f"{mid}{m.get('name','')}")
        if key_norm and key_norm in hay:
            cost = m.get("cost") or {}
            if cost.get("input") is None and cost.get("output") is None:
                continue
            out = {"input": cost.get("input"), "output": cost.get("output"),
                   "cache_read": cost.get("cache_read", cost.get("input")),
                   "cache_write": cost.get("cache_write", 0)}
            return out, f"models.dev:{mid}", "https://models.dev/"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the registry (default: dry-run)")
    ap.add_argument("--quiet", action="store_true", help="print only when something changes (cron)")
    args = ap.parse_args()

    reg = json.loads(REG_PATH.read_text())
    models = reg.get("models", {})
    needs = [k for k, v in models.items() if (v or {}).get("status") == "needs_price"]
    if not needs:
        if not args.quiet:
            print("No 'needs_price' models; nothing to search.")
        return 0

    # fetch sources once (best-effort; a source that is down just yields no hit)
    openrouter = modelsdev = None
    try:
        openrouter = _get_json(OPENROUTER_URL)
    except Exception as e:
        print(f"WARN: OpenRouter fetch failed: {e}", file=sys.stderr)
    try:
        modelsdev = _get_json(MODELSDEV_URL)
    except Exception as e:
        print(f"WARN: models.dev fetch failed: {e}", file=sys.stderr)

    today = date.today().isoformat()
    pinned, still_missing = [], []
    for key in needs:
        kn = _norm(key)
        hit = _from_openrouter(openrouter, kn) or _from_modelsdev(modelsdev, kn)
        entry = models[key]
        entry["last_checked"] = today
        if hit:
            cost, host, url = hit
            entry.update({"status": "pinned", "cost": cost, "reference_host": host,
                          "source_url": url, "fetched_at": today})
            entry["note"] = f"auto-pinned by price_search.py on {today} from {host}."
            pinned.append((key, host, cost))
        else:
            still_missing.append(key)

    if pinned or not args.quiet:
        print(f"price_search {today}: checked {len(needs)} un-priced model(s).")
        for key, host, cost in pinned:
            print(f"  PINNED  {key:30} <- {host}  ${cost['input']}/{cost['output']} per 1M in/out")
        for key in still_missing:
            print(f"  none    {key:30} (still no public reference; will re-check)")

    if not args.apply:
        if pinned:
            print("\nDRY-RUN: re-run with --apply to write these prices into the registry.")
        return 0

    REG_PATH.write_text(json.dumps(reg, indent=2) + "\n")
    if pinned:
        print(f"\nAPPLIED: pinned {len(pinned)} price(s) into {REG_PATH.name}. "
              f"Re-run the board to pick them up.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
