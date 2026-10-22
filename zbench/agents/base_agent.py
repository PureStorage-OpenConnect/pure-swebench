"""zbench agent-side base (the adapter<->parent IPC protocol), patch-tasks only.

Drastically slimmer than the fork's base_agent: zbench does ONE task type (code
patch), so all the terminal/analysis/translation/auggie surface (bucket C) is gone. An
adapter reads its input on stdin, runs the model CLI, captures a git diff via
patch_capture, and emits a JSON output map (patches + token_usage) on stdout; the parent
(agents.client) reads it. The full raw CLI stream is persisted durably to io_logs for the
dashboard, keyed + timestamped so nothing is overwritten.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..paths import io_logs_dir, safe

ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


class AgentError(RuntimeError):
    """Exception that carries token usage from a failed agent invocation."""

    def __init__(self, message: str, **usage):
        super().__init__(message)
        for k in ("input_tokens", "output_tokens", "total_tokens",
                  "cache_read_tokens", "cache_write_tokens", "cost_usd"):
            setattr(self, k, usage.get(k))


class ProviderError(RuntimeError):
    """The run ended because the MODEL ENDPOINT refused or dropped the request.

    This is an infrastructure fact, not a capability fact: the model never got to finish
    the turn. The harness must not score it as "the agent could not solve the task"
    (METHODOLOGY sec.3, run-invalid vs task-invalid). `retryable` marks the transient
    subset (throttling / dropped stream / 5xx) that another attempt can clear.

    Shared by every adapter: the classifier below is the SINGLE definition of what counts
    as an endpoint failure, so a throttle cannot be infra on one harness and a capability
    miss on another (the pi-vs-codex split measured on run foundry-py10, 2026-08-17)."""

    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


# Substrings that mark a TRANSIENT endpoint failure another attempt can clear.
PROVIDER_RETRYABLE_SIGS = (
    "rate limit", "rate_limit", "429", "too many requests", "quota",
    "stream disconnected", "connection reset", "connection closed", "timed out",
    "temporarily unavailable", "overloaded", "server_error", "internal server error",
    "500 ", "502", "503", "504",
)

# Substrings that mark a PERMANENT provider/config failure -- retrying only burns budget.
# Checked BEFORE PROVIDER_RETRYABLE_SIGS, so keep every entry specific: a loose word here
# (a bare "not found" would match codex's harmless "thread ... not found") turns a
# recoverable throttle into a give-up.
PROVIDER_FATAL_SIGS = (
    "401", "403", "unauthorized", "invalid api key", "authentication",
    "404", "deploymentnotfound", "model_not_found", "not_found_error", "unsupported",
    # A missing key/credential in the driver env is an INFRA/config failure, not a
    # capability give-up. Without this the codex CLI's "Missing environment variable:
    # OPENAI_API_KEY" fell through to a generic no_patch and got double-counted (W150).
    "missing environment variable", "missing api key", "api key is required",
)


def classify_provider_failure(message: str) -> ProviderError | None:
    """Classify a terminal adapter message. Returns None when the message does not look
    like a provider failure at all (then it is a harness problem, not the endpoint)."""
    low = (message or "").lower()
    if any(s in low for s in PROVIDER_FATAL_SIGS):
        return ProviderError(message, retryable=False)
    if any(s in low for s in PROVIDER_RETRYABLE_SIGS):
        return ProviderError(message, retryable=True)
    return None


def strip_ansi_codes(text: str) -> str:
    return ANSI_ESCAPE_PATTERN.sub("", text)


# Credentials a provider error or config echo can splice into the CLI stream. A gateway/
# litellm 429 body carries "api_key: <key>"; Authorization headers carry "Bearer <token>";
# vendor keys look like "sk-..." . These must never reach a durable transcript blob or a
# log line. Value-only masking; the surrounding text (and the "429"/"rate limit" tokens the
# failure classifier keys on) is preserved.
_SECRET_SUBS = [
    (re.compile(r'(api[_-]?key["\s]*[:=]\s*)([A-Za-z0-9._\-]{12,})', re.I), r"\1REDACTED"),
    (re.compile(r'(\bbearer\s+)([A-Za-z0-9._\-]{12,})', re.I), r"\1REDACTED"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9._\-]{16,}"), "REDACTED"),
    (re.compile(r"\bsk-[A-Za-z0-9._\-]{16,}"), "REDACTED"),
]


def redact_secrets(text: str | None) -> str | None:
    """Mask credentials that a provider error can splice into the CLI stream, so a throttle
    never leaks a key into a durable rawcli blob or a log. Best-effort, value-only."""
    if not text:
        return text
    for pat, repl in _SECRET_SUBS:
        text = pat.sub(repl, text)
    return text


class _Ctx(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra.setdefault("run_id", os.environ.get("ZBENCH_RUN_ID", "-"))
        extra.setdefault("evaluation_id", os.environ.get("ZBENCH_EVALUATION_ID", "-"))
        return msg, kwargs


def get_agent_logger(agent_id: str) -> logging.LoggerAdapter:
    """A stderr logger with run/evaluation context for an adapter CLI."""
    logger = logging.getLogger(f"zbench.agent.{agent_id}")
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] run_id=%(run_id)s "
            "evaluation_id=%(evaluation_id)s %(message)s",
            defaults={"run_id": "-", "evaluation_id": "-"}))
        logger.addHandler(h); logger.setLevel(logging.INFO); logger.propagate = False
    return _Ctx(logger, {})


def read_agent_input() -> dict[str, Any]:
    return json.load(sys.stdin)


def _build_token_usage(**fields) -> dict | None:
    keep = ("input_tokens", "output_tokens", "total_tokens",
            "cache_read_tokens", "cache_write_tokens", "cost_usd", "credits",
            "turns")   # turns = agentic model round-trips (display metric, not billed)
    usage = {k: fields[k] for k in keep if fields.get(k) is not None}
    return usage or None


def _emit_output(out: dict, raw_cli_output: str | None = None) -> None:
    """Write the standardized JSON to stdout + persist the raw CLI stream to io_logs."""
    if raw_cli_output:
        try:
            explicit = os.environ.get("ZBENCH_RAWCLI_PATH")
            if explicit:
                p = Path(explicit); p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(raw_cli_output, encoding="utf-8")
            else:
                bucket = os.environ.get("ZBENCH_RUN_ID") or "adhoc"
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                fn = f"{safe(out.get('agent_id', 'unknown'))}__{safe(out.get('instance_id', 'unknown'))}__rawcli__{stamp}.txt"
                (io_logs_dir(bucket) / fn).write_text(raw_cli_output, encoding="utf-8")
        except Exception:
            pass  # best-effort
    json.dump(out, sys.stdout)


def _finalize_and_emit(out: dict, **kwargs) -> None:
    raw = kwargs.pop("_raw_cli_output", None) or kwargs.pop("raw_cli_output", None)
    # `failure` is the adapter's channel for "this run carries no capability signal"
    # (e.g. the model endpoint refused the request). Without it an empty patch list is
    # indistinguishable from an agent that simply gave up -- see workflow.run_patch_task_attempt.
    failure = kwargs.pop("failure", None)
    if failure:
        out["failure"] = failure
    tu = _build_token_usage(**kwargs) if kwargs else None
    if tu:
        out["token_usage"] = tu
    _emit_output(out, raw)


def emit_agent_output(instance_id: str, agent_id: str, patch_texts: list[str], **kwargs) -> None:
    """Emit the adapter's patch output (unified diffs + token_usage) to stdout.

    `failure={"kind": ..., "message": ..., "retryable": ...}` marks a run that failed for
    a NON-capability reason; the parent maps it to a `provider_error` attempt status."""
    patches = [
        {"instance_id": instance_id, "patch_id": f"patch-{i:04d}",
         "patch_format": "unified_diff", "patch_text": p, "metadata": {}}
        for i, p in enumerate(patch_texts, start=1)
    ]
    _finalize_and_emit({"instance_id": instance_id, "agent_id": agent_id, "patches": patches}, **kwargs)
