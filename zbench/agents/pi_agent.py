"""zbench adapter for the ``pi`` coding-agent CLI (patch tasks only).

pi is invoked as a subprocess in non-interactive mode; model access is delegated to pi's
own provider config (e.g. azure-foundry), so this adapter needs no API keys.

HERMETIC BY DEFAULT: every call disables pi's ambient context (no AGENTS.md/CLAUDE.md,
skills, prompt templates, extensions, persisted session) so the benchmark measures a
controlled model x harness x prompt x skill combo. Anything that should influence a run
is injected via the env knobs and recorded.

Env knobs (per-cell in agents-*.jsonl `env`): PI_PROVIDER, PI_MODEL, PI_THINKING,
PI_SYSTEM_PROMPT, PI_APPEND_SYSTEM_PROMPT, PI_SKILL, PI_INCLUDE_CONTEXT_FILES,
PI_EXTRA_ARGS, ZBENCH_AGENT_TIMEOUT.
"""
import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .base_agent import (ProviderError, classify_provider_failure, emit_agent_output,
                         get_agent_logger, read_agent_input)
from .patch_capture import capture_git_patch
from ..paths import io_logs_dir

LOGGER = get_agent_logger("pi")

DEFAULT_PROVIDER = os.environ.get("PI_PROVIDER", "azure-foundry")
DEFAULT_MODEL = os.environ.get("PI_MODEL", "claude-opus-4-8")


def _truthy(val: str | None) -> bool:
    return bool(val) and val.strip().lower() in {"1", "true", "yes", "on"}


def _session_path(instance_id: str | None) -> str | None:
    """The absolute pi --session path for this cell. The PARENT (harness) allocates it and
    passes ZBENCH_SESSION_PATH -- the child must NOT derive it from its own cwd (which is
    the ephemeral worktree; a cwd-derived session would be wiped on teardown -> lost transcript).
    Fresh+unique per cell -> nothing to load -> hermetic. None -> caller falls back to --no-session.

    Fallback (adhoc/direct invocation without the harness): derive from the stable data_dir."""
    explicit = os.environ.get("ZBENCH_SESSION_PATH")
    if explicit:
        try:
            Path(explicit).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return explicit
    try:
        bucket = os.environ.get("ZBENCH_RUN_ID") or "adhoc"
        eval_id = os.environ.get("ZBENCH_EVALUATION_ID") or "noeval"
        inst = instance_id or "unknown"
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = io_logs_dir(bucket) / f"pi__{inst}__{eval_id}__session__{stamp}.jsonl"
        return str(path.resolve())
    except Exception:
        return None


def _pi_base_cmd(*, with_tools: bool, session_path: str | None = None) -> list[str]:
    """Build the hermetic base pi command (without the trailing prompt)."""
    cmd = ["pi", "-p"]
    cmd += (["--session", session_path] if session_path else ["--no-session"])
    cmd += ["--no-skills", "--no-prompt-templates", "--no-extensions",
            "--mode", "json", "--provider", DEFAULT_PROVIDER, "--model", DEFAULT_MODEL]
    if not _truthy(os.environ.get("PI_INCLUDE_CONTEXT_FILES")):
        cmd.append("--no-context-files")
    if os.environ.get("PI_THINKING"):
        cmd += ["--thinking", os.environ["PI_THINKING"]]
    if os.environ.get("PI_SYSTEM_PROMPT"):
        cmd += ["--system-prompt", os.environ["PI_SYSTEM_PROMPT"]]
    if os.environ.get("PI_APPEND_SYSTEM_PROMPT"):
        cmd += ["--append-system-prompt", os.environ["PI_APPEND_SYSTEM_PROMPT"]]
    if os.environ.get("PI_SKILL"):
        cmd += ["--skill", os.environ["PI_SKILL"]]
    # pi >= 0.73 has no "tools on" flag: built-in tools (read/bash/edit/write) are ON by
    # default, and a bare "-a" is a fatal "Unknown option" parse error. Only the OFF case
    # needs a flag.
    if not with_tools:
        cmd.append("--no-tools")
    if os.environ.get("PI_EXTRA_ARGS"):
        cmd += shlex.split(os.environ["PI_EXTRA_ARGS"])
    return cmd


def _usage_to_tokens(usage: dict) -> dict:
    """Map a pi `message.usage` snapshot to the zbench token_usage shape (single source
    for the stream parse + the session sum)."""
    if not usage:
        return {}
    tu = {"input_tokens": usage.get("input"), "output_tokens": usage.get("output"),
          "cache_read_tokens": usage.get("cacheRead"), "cache_write_tokens": usage.get("cacheWrite"),
          "total_tokens": usage.get("totalTokens")}
    cost = usage.get("cost")
    if isinstance(cost, dict) and cost.get("total") is not None:
        tu["cost_usd"] = cost["total"]
    return {k: v for k, v in tu.items() if v is not None}


def _parse_pi_json(stdout: str) -> tuple[str, dict]:
    """Parse pi ``--mode json`` JSONL -> (assistant_text, last-snapshot token_usage)."""
    final_text = delta_text = ""
    usage: dict = {}
    turns = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        etype = event.get("type")
        if etype == "message_update":
            ame = event.get("assistantMessageEvent", {})
            if ame.get("type") == "text_delta":
                delta_text += ame.get("delta", "")
            partial = ame.get("partial") or {}
            if isinstance(partial, dict) and partial.get("role") == "assistant" and partial.get("usage"):
                usage = partial["usage"]
        if etype == "message_end":
            msg = event.get("message", {})
            if msg.get("role") == "assistant":
                turns += 1   # one assistant message_end == one model round-trip
                text = "".join(b.get("text", "") for b in msg.get("content", [])
                               if isinstance(b, dict) and b.get("type") == "text")
                if text:
                    final_text = text
                if msg.get("usage"):
                    usage = msg["usage"]
    tu = _usage_to_tokens(usage)
    if turns:
        tu["turns"] = turns
    return (final_text or delta_text), tu


def _usage_from_session(session_path: str | None) -> dict:
    """Token/cost from the durable --session jsonl -- the SINGLE SOURCE (W108). pi's
    per-message usage is PER-TURN, so the true totals are the SUM over assistant turns,
    NOT the last snapshot (last-turn output undercounts a multi-turn run ~35x). Mirrors
    zbench-tasks/pi_session_tokens.summarize_session. Never raises."""
    if not session_path or not os.path.exists(session_path):
        return {}
    agg = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0}
    cost_total = 0.0
    turns = 0
    saw_usage = saw_cost = False
    try:
        with open(session_path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                m = d.get("message") if isinstance(d, dict) else None
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                u = m.get("usage") or {}
                if not u:
                    continue
                saw_usage = True
                turns += 1   # one usage-bearing assistant message == one model round-trip
                for k in ("input", "output", "cacheRead", "cacheWrite", "totalTokens"):
                    agg[k] += u.get(k) or 0
                cost = u.get("cost")
                if isinstance(cost, dict) and cost.get("total") is not None:
                    cost_total += cost["total"]; saw_cost = True
    except Exception:
        return {}
    if not saw_usage or not any(agg.values()):
        return {}
    if saw_cost:
        agg["cost"] = {"total": cost_total}
    tu = _usage_to_tokens(agg)
    tu["turns"] = turns
    return tu


def _session_turn_errors(session_path: str | None) -> list[str]:
    """The `errorMessage` of every assistant turn that ended with stopReason=="error".

    pi does NOT fail its process when a turn dies on the endpoint: it records the error on
    the turn, stops the loop, and exits 0. So the process exit code cannot tell a throttle
    from a give-up -- the session is the only witness. Measured 2026-08-17 (run
    foundry-py10): 21 pi cells ended on repeated
    `429 ... exceeded rate limit` yet were recorded as no_patch_generated, i.e. scored as
    capability misses. Never raises."""
    if not session_path or not os.path.exists(session_path):
        return []
    errs: list[str] = []
    try:
        with open(session_path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                m = d.get("message") if isinstance(d, dict) else None
                if not isinstance(m, dict) or m.get("role") != "assistant":
                    continue
                if m.get("stopReason") == "error" and m.get("errorMessage"):
                    errs.append(str(m["errorMessage"]))
    except Exception:
        return errs
    return errs


def _provider_error(session_path: str | None, extra: str = "") -> ProviderError | None:
    """Endpoint failure that ended THIS run, or None when the run ended for its own
    reasons. Only the turn errors and any CLI stderr are consulted -- never the patch."""
    errs = _session_turn_errors(session_path)
    for msg in ([extra] if extra else []) + list(reversed(errs)):
        perr = classify_provider_failure(msg)
        if perr is not None:
            note = f" ({len(errs)} errored turn(s))" if errs else ""
            return ProviderError(f"{msg}{note}", retryable=perr.retryable)
    return None


# Continue-after-compaction (W150). In non-interactive `pi -p`, an OVERFLOW auto-compaction
# (context hit contextWindow-reserveTokens) compacts the history and then the process EXITS
# rc=0 -- it does NOT auto-retry the aborted turn the way interactive overflow-recovery does.
# The session's LAST entry is then a `compaction` and, for a long exploration that hadn't
# edited yet, capture_git_patch sees no diff -> `candidate_missing`, which the infra sweep
# excludes as a (mislabeled) `timeout~Xs` artifact. That systematically drops the HARDER,
# more context-hungry tasks and SKEWS the score upward. Fix: detect a compaction-terminal
# and RE-INVOKE pi with the SAME --session (which reloads the compaction summary as context)
# and a continue nudge, looping until pi settles on a non-compaction entry, or we run out of
# the per-cell wall-clock budget, or we hit PI_MAX_COMPACTION_CONTINUES. Token/cost accounting
# is unaffected: _usage_from_session sums the whole (single) session file across all invocations.
_CONTINUE_PROMPT = (
    "Your conversation context was automatically compacted to free space; a structured summary "
    "of the work so far is now at the top of the context (Goal / Progress / Next Steps / "
    "Critical Context). Continue the task from exactly where you left off -- do NOT restart the "
    "analysis from scratch. Make the necessary code changes to implement the fix and finish."
)


def _session_last_entry_type(session_path: str | None) -> str | None:
    """Type of the LAST non-empty JSONL entry in the session (None if unreadable/empty).
    A trailing `compaction` means pi stopped right after an overflow compaction (terminal)."""
    if not session_path or not os.path.exists(session_path):
        return None
    last = None
    try:
        with open(session_path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if isinstance(d, dict) and d.get("type"):
                    last = d["type"]
    except Exception:
        return None
    return last


def _run_pi(prompt: str, *, with_tools: bool, cwd: str | None, timeout: int,
            instance_id: str | None = None,
            session_path: str | None = None) -> tuple[str, dict]:
    session_path = session_path or _session_path(instance_id)
    max_continues = int(os.environ.get("PI_MAX_COMPACTION_CONTINUES", "10"))
    deadline = time.monotonic() + timeout
    cur_prompt = prompt
    text = ""
    stream_usage: dict = {}
    continues = 0
    for attempt in range(max_continues + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 30:
            LOGGER.warning("pi continue-loop: wall-clock budget exhausted (remaining=%.0fs)", remaining)
            break
        cmd = [*_pi_base_cmd(with_tools=with_tools, session_path=session_path), cur_prompt]
        LOGGER.info("Running pi: provider=%s model=%s tools=%s session=%s continue=%d",
                    DEFAULT_PROVIDER, DEFAULT_MODEL, with_tools, session_path or "<none>", attempt)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=remaining, cwd=cwd)
        if result.returncode != 0:
            LOGGER.error("pi stderr: %s", result.stderr[:500])
            raise RuntimeError(f"pi CLI failed (rc={result.returncode}): {result.stderr[:300]}")
        call_text, call_usage = _parse_pi_json(result.stdout)
        if call_text:
            text = call_text
        if call_usage:
            stream_usage = call_usage
        # Continue ONLY if pi stopped right after an overflow compaction (terminal compaction).
        # A normally-settled agent's last entry is an assistant message, not a compaction.
        if _session_last_entry_type(session_path) != "compaction":
            break
        continues += 1
        cur_prompt = _CONTINUE_PROMPT
        LOGGER.info("pi ended on a compaction (context overflow); continuing the run (continue #%d)", continues)
    else:
        LOGGER.warning("pi continue-loop hit PI_MAX_COMPACTION_CONTINUES=%d", max_continues)
    if continues:
        LOGGER.info("pi settled after %d compaction-continue(s)", continues)
    token_usage = _usage_from_session(session_path)  # W108: session is the single source (sums all invocations)
    if token_usage:
        LOGGER.info("pi usage (summed from session): %s", token_usage)
    else:
        token_usage = stream_usage
        if token_usage:
            LOGGER.info("pi usage (stream fallback; session unavailable): %s", token_usage)
    token_usage = dict(token_usage) if token_usage else {}
    return text, token_usage


def call_pi_for_patch(problem: str, repo_root, instance_id: str | None = None,
                      session_path: str | None = None) -> tuple[str, dict, str | None]:
    """Run pi with tools inside the repo checkout and capture the git diff (committed OR
    uncommitted) via the shared adapter-agnostic capture. Returns the session path too --
    main() needs it to tell an endpoint failure from a genuine give-up."""
    repo_root = Path(repo_root).resolve()
    patch_timeout = int(os.environ.get("ZBENCH_AGENT_TIMEOUT", "1800"))
    session_path = session_path or _session_path(instance_id)   # resolved ONCE

    def _run() -> dict:
        _, token_usage = _run_pi(problem, with_tools=True, cwd=str(repo_root),
                                 timeout=patch_timeout, instance_id=instance_id,
                                 session_path=session_path)
        return token_usage
    patch_text, usage = capture_git_patch(repo_root, _run)
    return patch_text, usage, session_path


def main():
    data = read_agent_input()
    instance_id = data["instance_id"]
    problem = data["problem_statement"]
    LOGGER.info("Starting pi agent instance_id=%s provider=%s model=%s",
                instance_id, DEFAULT_PROVIDER, DEFAULT_MODEL)
    # Resolved HERE so the failure path below still knows where the transcript is (the
    # fallback branch of _session_path is timestamped, so it must not be computed twice).
    session_path = _session_path(instance_id)
    try:
        patch_text, usage, session_path = call_pi_for_patch(
            problem, Path(data["repo_root"]), instance_id, session_path=session_path)
        # A patch means the run carries a capability signal, whatever errored on the way.
        # An EMPTY patch is ambiguous, so ask the session which it was: an endpoint failure
        # (infra, must not be scored) or the agent giving up (a real miss).
        perr = _provider_error(session_path) if not (patch_text or "").strip() else None
        if perr is not None:
            LOGGER.error("Provider failure for %s (retryable=%s): %s",
                         instance_id, perr.retryable, perr)
            emit_agent_output(instance_id, "pi", [],
                              failure={"kind": "provider_error", "retryable": perr.retryable,
                                       "message": str(perr)[:500]}, **usage)
            return
        emit_agent_output(instance_id, "pi", [patch_text], **usage)
    except Exception as e:
        LOGGER.exception("Patch task failed for %s: %s", instance_id, e)
        perr = _provider_error(session_path, extra=str(e))
        if perr is not None:
            emit_agent_output(instance_id, "pi", [],
                              failure={"kind": "provider_error", "retryable": perr.retryable,
                                       "message": str(perr)[:500]})
            return
        emit_agent_output(instance_id, "pi", [])


if __name__ == "__main__":
    main()
