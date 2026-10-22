"""zbench transforms -- PURE functions map -> map (W19 data-oriented decision).

No I/O, no DB, no classes. These build the persistence-shaped rows (AttemptRow /
EventRow) that `store.py` writes. The write itself (the schema.sql-guarded INSERT) lives
in store.py; here we only shape data. Ported from the old
`benchdb/writer.record_attempt` field mapping, MINUS try_number (W109).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from . import constants
from .types import AttemptRow, EventRow

# Stable namespace for deterministic evaluation ids, keyed WITHOUT try_number (W109).
# (Rebased for the Zulip retarget: the DB started fresh, so id continuity with the old
# fork was deliberately dropped.)
_EVAL_NS = uuid.uuid5(uuid.NAMESPACE_URL, "zbench/benchdb/attempt")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def task_of(instance_id: str) -> str:
    """`zbench_ZT-x` (or bare `ZT-x`) -> the bare task id used as the task soft-ref."""
    return constants.task_of(instance_id)


def evaluation_id(run_id: str, config_id: str, instance_id: str) -> str:
    """Deterministic attempt id from the identity (run_id, config_id, task_id). No try."""
    return str(uuid.uuid5(_EVAL_NS, f"{run_id}:{config_id}:{instance_id}"))


def bundle_dir(evaluation_id_: str) -> str:
    """Derive an attempt's evidence-blob dir from its id (was the stored bundle_dir col)."""
    return f"blobs/attempt/{evaluation_id_}"


def attempt_row(score: dict, *, evaluation_id_: str | None = None) -> AttemptRow:
    """Map a harness `score` map -> an AttemptRow (facts-only schema columns).

    Expected `score` keys (all the adapter/workflow already produce): run_id, agent_id,
    instance_id, tests_passed, status, attempt_outcome, cost_usd, timestamp,
    metrics{runtime_ms,total_duration_ms,input/output/cache_*_tokens}. Raises on the two
    identity keys; everything else is optional/nullable. Dropped vs the fork: try_number,
    phase, total_tokens, bundle_dir (derived).
    """
    run_id = score.get("run_id")
    config_id = score.get("agent_id")
    if not run_id or not config_id:
        raise ValueError("attempt_row: score needs run_id and agent_id")
    instance_id = score.get("instance_id", "")
    task_id = task_of(instance_id)
    metrics = score.get("metrics") if isinstance(score.get("metrics"), dict) else {}

    row: AttemptRow = {
        "evaluation_id": evaluation_id_ or score.get("evaluation_id")
                         or evaluation_id(run_id, config_id, instance_id),
        "run_id": run_id,
        "config_id": config_id,
        "task_id": task_id,
        "tests_passed": 1 if score.get("tests_passed") else 0,
        "finished_at": score.get("timestamp") or utc_now(),
    }
    # optional/nullable columns -- include only when present (keeps the map lean)
    _put(row, "status", score.get("status"))
    _put(row, "outcome", score.get("attempt_outcome"))
    _put(row, "cost_usd", score.get("cost_usd"))
    for k in ("runtime_ms", "total_duration_ms", "input_tokens", "output_tokens",
              "cache_read_tokens", "cache_write_tokens"):
        _put(row, k, metrics.get(k))
    _put(row, "total_tokens", canonical_total_tokens(metrics))
    _put(row, "turns", metrics.get("turns"))
    return row


# Components of the CANONICAL total. Every one of these is billed by
# tools/model_prices.cost_usd, so a total that omits any of them cannot be reconciled
# against the cost stored on the same row.
TOKEN_COMPONENTS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def canonical_total_tokens(metrics: dict) -> int | None:
    """input + output + cache_read + cache_write, or None when NOTHING was reported.

    Returns None (not 0) if no component is present, so "usage was never captured" stays
    distinguishable from "genuinely zero tokens". A harness-reported `total_tokens` is
    IGNORED in favour of the component sum: harnesses disagree about whether their own
    total includes cache, and the sum is the only definition that matches cost.
    """
    present = [metrics.get(k) for k in TOKEN_COMPONENTS if metrics.get(k) is not None]
    return sum(present) if present else None


def event_row(run_id: str, config_id: str, task_id: str, phase: str, *,
              evaluation_id_: str | None = None, ts: str | None = None,
              message: str | None = None, source: str = "harness",
              confidence: str = "high", data: dict | None = None) -> EventRow:
    """Build one attempt-lifecycle EventRow (schema.sql columns, minus try_number)."""
    row: EventRow = {
        "run_id": run_id, "config_id": config_id, "task_id": task_id,
        "ts": ts or utc_now(), "phase": phase,
        "source": source, "confidence": confidence,
    }
    _put(row, "evaluation_id", evaluation_id_)
    _put(row, "message", message)
    if data is not None:
        import json
        row["data_json"] = json.dumps(data, sort_keys=True)
    return row


def _put(d: dict, k: str, v: Any) -> None:
    """assoc a key only when it carries a value (None -> leave the column at its default)."""
    if v is not None:
        d[k] = v
