"""Durable per-invocation agent<->harness record (ported to dicts, W19).

Takes plain AgentSpec + InstanceSpec maps (not classes) and writes one JSON record per
agent invocation into the run's io_logs dir. Best-effort -- never breaks a run. No
try_number (W109). store.write_evidence later copies the owning cell's records into the
attempt's blob bundle.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from pathlib import Path

from .paths import io_logs_dir, safe

logger = logging.getLogger("zbench.io_logging")


def _model_provider(agent: dict) -> tuple[str | None, str | None]:
    env = agent.get("env") or {}
    model = (env.get("PI_MODEL") or env.get("CLAUDE_MODEL_NAME") or env.get("CURSOR_MODEL_NAME")
             or env.get("CODEX_MODEL_NAME") or env.get("GEMINI_MODEL_NAME"))
    return model, env.get("PI_PROVIDER")


def log_agent_io(*, agent: dict, instance: dict, agent_input, returncode: int | None,
                 stdout: str | None, stderr: str | None, run_id: str | None = None,
                 evaluation_id: str | None = None, task_type: str | None = None,
                 parsed_output=None, generation_ms: int | None = None) -> None:
    try:
        bucket = run_id or os.environ.get("ZBENCH_RUN_ID") or "adhoc"
        cell = os.environ.get("ZBENCH_CELL_DIR")
        out_dir = Path(cell) if cell else io_logs_dir(bucket)
        out_dir.mkdir(parents=True, exist_ok=True)
        model, provider = _model_provider(agent)
        md = instance.get("metadata") or {}
        now = datetime.now(timezone.utc)
        stamp = now.strftime("%Y%m%dT%H%M%S%fZ")   # legacy name guarantees no overwrite
        fname = "agent_io.json" if cell else f"{safe(agent['agent_id'])}__{safe(instance['instance_id'])}__{stamp}.json"
        record = {
            "timestamp": now.isoformat(),
            "run_id": None if bucket == "adhoc" else bucket,
            "evaluation_id": evaluation_id,
            "agent_id": agent["agent_id"],
            "instance_id": instance["instance_id"],
            "task_type": task_type or md.get("task_type"),
            "model_name": model, "provider": provider,
            "command": agent.get("command"),
            "timeout_sec": agent.get("timeout_sec"),
            "generation_ms": generation_ms,
            "agent_env": dict(agent.get("env") or {}),
            "agent_input": agent_input,
            "returncode": returncode, "stdout": stdout, "stderr": stderr,
            "parsed_output": parsed_output,
        }
        (out_dir / fname).write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    except Exception as exc:  # never break a run because logging failed
        logger.warning("io_logging failed for %s/%s: %s",
                       agent.get("agent_id", "?"), instance.get("instance_id", "?"), exc)
