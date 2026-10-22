"""zbench adapter for the ``claude`` Code CLI (patch tasks only).

claude edits files directly; we capture the git diff (committed OR uncommitted) via the
shared patch_capture. Hermetic by default (isolated CLAUDE_CONFIG_DIR + ambient-free
flags, see hermetic.py). The stream-json stdout is TEEd LIVE to io_logs so a running cell
has a tailable transcript (claude has no native session file) -- that file IS the durable
rawcli. Env: CLAUDE_MODEL_NAME, CLAUDE_EFFORT, ZBENCH_CLAUDE_MAX_TURNS, ZBENCH_AGENT_TIMEOUT,
ZBENCH_HERMETIC.
"""
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .base_agent import (ProviderError, classify_provider_failure,
                         emit_agent_output, get_agent_logger, read_agent_input,
                         redact_secrets)
from .patch_capture import capture_git_patch
from ..hermetic import claude_hermetic_flags, is_hermetic
from ..paths import io_logs_dir

LOGGER = get_agent_logger("claude")


def _build_claude_cmd() -> list:
    """Base claude CLI command (model/effort/hermetic flags).

    Turn cap: a `--max-turns` cap is applied ONLY if ZBENCH_CLAUDE_MAX_TURNS is set to a positive
    int. Unset / 0 / 'none' / 'unlimited' / 'off' => NO --max-turns, i.e. UNCAPPED, matching the
    pi agent (which has no turn cap); both harnesses are then bounded only by the shared
    ZBENCH_AGENT_TIMEOUT wall-clock. Rationale: a hard cap (historically 50, then 120) truncated
    claude runs mid-work and scored them as non-resolves -- an asymmetric-config artifact that
    penalized claude vs pi. Keep stopping conditions equal across agents. See METHODOLOGY.md
    sec.3 (cross-agent parity of stopping conditions)."""
    # CLAUDE_BIN overrides the executable (default "claude"). Set it to a claude-compatible
    # wrapper build to route model *slots* (opus/haiku/fable) through your own gateway.
    # Unset for every direct-Anthropic row, so their command is byte-for-byte unchanged.
    cmd = [os.environ.get("CLAUDE_BIN") or "claude", "--print",
           "--dangerously-skip-permissions", "--verbose",
           "--output-format", "stream-json"]
    _raw = os.environ.get("ZBENCH_CLAUDE_MAX_TURNS", "").strip().lower()
    if _raw and _raw not in {"0", "none", "unlimited", "off"}:
        try:
            _n = int(_raw)
            if _n > 0:
                cmd += ["--max-turns", str(_n)]
        except ValueError:
            pass
    if is_hermetic():
        cmd.extend(claude_hermetic_flags())
    if os.environ.get("CLAUDE_MODEL_NAME"):
        cmd += ["--model", os.environ["CLAUDE_MODEL_NAME"]]
    if os.environ.get("CLAUDE_EFFORT"):
        cmd += ["--effort", os.environ["CLAUDE_EFFORT"]]
    return cmd


class _Res:
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _run_claude_streaming(cmd, cwd, timeout, stream_path) -> _Res:
    """Run claude, TEEing stdout to `stream_path` LIVE (line-buffered) + accumulating it
    for parsing. The live file IS the durable rawcli. Raises subprocess.TimeoutExpired."""
    Path(stream_path).parent.mkdir(parents=True, exist_ok=True)
    buf, err_buf = [], []
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, errors="replace")
    f = open(stream_path, "w", buffering=1, errors="replace")

    def _pump_out():
        for line in proc.stdout:
            buf.append(line)              # unredacted: parsing reads only structured fields
            try:
                f.write(redact_secrets(line))   # durable rawcli blob must carry no secrets
            except Exception:
                pass

    def _pump_err():
        for line in proc.stderr:
            err_buf.append(line)

    to = threading.Thread(target=_pump_out, daemon=True); te = threading.Thread(target=_pump_err, daemon=True)
    to.start(); te.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill(); proc.wait(); to.join(timeout=5); te.join(timeout=5); f.flush(); f.close()
        raise
    to.join(timeout=10); te.join(timeout=10); f.flush(); f.close()
    return _Res(proc.returncode, "".join(buf), "".join(err_buf))


def _parse_claude_stream_json(stream_output: str) -> tuple[str, dict]:
    """Parse claude --output-format stream-json (JSONL); the final 'result' event carries
    aggregated usage + total_cost_usd (accurate). Falls back to legacy single-JSON."""
    for line in stream_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            u = event.get("usage", {})
            it, ot = u.get("input_tokens", 0), u.get("output_tokens", 0)
            cr, cw = u.get("cache_read_input_tokens", 0), u.get("cache_creation_input_tokens", 0)
            tu = {"input_tokens": it, "output_tokens": ot, "cache_read_tokens": cr,
                  "cache_write_tokens": cw, "total_tokens": it + ot + cr + cw}
            if event.get("total_cost_usd") is not None:
                tu["cost_usd"] = event["total_cost_usd"]
            # Surface the terminal result subtype so a cap/error termination is never silently
            # scored as a genuine capability outcome. subtype == 'error_max_turns' means the run
            # hit --max-turns and was truncated (an artifact once caps are asymmetric); it should
            # be excluded + re-run, not counted. See METHODOLOGY.md sec.3.
            tu["result_subtype"] = event.get("subtype")
            tu["is_error"] = bool(event.get("is_error", False))
            tu["num_turns"] = event.get("num_turns")
            tu["turns"] = event.get("num_turns")   # canonical turn metric (base_agent whitelist)
            tu["_raw_cli_output"] = redact_secrets(stream_output)   # non-streaming persist path
            return event.get("result", ""), tu
    try:
        data = json.loads(stream_output)
        u = data.get("usage", {})
        if u:
            it, ot = u.get("input_tokens", 0), u.get("output_tokens", 0)
            return data.get("result", ""), {"input_tokens": it, "output_tokens": ot, "total_tokens": it + ot}
        return data.get("result", ""), {}
    except (json.JSONDecodeError, KeyError, TypeError):
        return stream_output, {}


def call_claude(problem: str, repo_root: Path, stream_path: str | None = None) -> tuple[str, dict]:
    """Run claude in the repo checkout + capture the git diff via the shared capture.

    Token accounting survives a LATE endpoint failure: usage is parsed from the stream on a
    non-zero exit too (e.g. a gateway 429 that arrives AFTER the fix was already written),
    and the patch left on disk is still recovered by capture_git_patch. A retryable provider
    failure that left NO patch is retried up to CLAUDE_MAX_ATTEMPTS with backoff (parity with
    the codex adapter's throttle handling); a non-retryable one is raised at once."""
    repo_root = Path(repo_root).resolve()
    cmd = [*_build_claude_cmd(), "-p", problem]
    patch_timeout = int(os.environ.get("ZBENCH_AGENT_TIMEOUT", "1800"))
    # Retry budget for a retryable provider failure (throttle / dropped stream / 5xx) that
    # left NO patch. Governed by a total SLEEP budget, not a fixed count, so a cell can wait
    # out a sustained gateway saturation (a shared key's max_parallel_requests cap)
    # instead of giving up in ~15s. A 429 is rejected fast, so the budget is mostly backoff,
    # not runtime, and stays well under the cell timeout. Tunable per row via env; the
    # gateway-routed rows may raise CLAUDE_PROVIDER_RETRY_MAX_WAIT for a contended shared key.
    max_attempts = max(1, int(os.environ.get("CLAUDE_MAX_ATTEMPTS", "30")))          # safety cap
    retry_max_wait = float(os.environ.get("CLAUDE_PROVIDER_RETRY_MAX_WAIT", "300"))   # total sleep budget (s)
    retry_backoff_cap = float(os.environ.get("CLAUDE_PROVIDER_RETRY_BACKOFF_CAP", "60"))

    def _attempt() -> tuple[str, dict]:
        holder: dict = {"usage": {}}

        def _run() -> dict:
            try:
                if stream_path:
                    result = _run_claude_streaming(cmd, str(repo_root), patch_timeout, stream_path)
                else:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=patch_timeout, cwd=str(repo_root))
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"Claude CLI timed out after {patch_timeout}s") from e
            except FileNotFoundError as e:
                raise RuntimeError("Claude CLI not found (npm i -g @anthropic/claude-code)") from e
            # Parse usage from the stream on SUCCESS *or* failure and stash it in `holder`,
            # so a late error still records tokens even when _run raises and the patch is
            # recovered downstream.
            result_text, token_usage = _parse_claude_stream_json(result.stdout)
            if token_usage and stream_path:
                token_usage.pop("_raw_cli_output", None)   # the streamed file is the durable rawcli
            holder["usage"] = token_usage or {}
            if result.returncode != 0:
                try:  # persist the raw stream on failure (real cause is in the result event)
                    bucket = os.environ.get("ZBENCH_RUN_ID") or "adhoc"
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                    (io_logs_dir(bucket) / f"claude__rawcli_FAIL__{stamp}.txt").write_text(
                        redact_secrets((result.stdout or "") + "\n----- stderr -----\n"
                                       + (result.stderr or "")), encoding="utf-8")
                except Exception:
                    pass
                # redact before it reaches the log OR the classifier (a 429 body carries the key)
                detail = redact_secrets(f"{result_text} {result.stderr or ''}".strip())
                LOGGER.error("Claude rc=%s: %s", result.returncode, detail[:300])
                pe = classify_provider_failure(detail)   # 429 / dropped stream / 5xx -> ProviderError
                if pe is not None:
                    raise pe
                raise RuntimeError(f"Claude CLI failed (rc={result.returncode}): {detail[:200]}")
            if token_usage:
                LOGGER.info("Claude usage: %s", token_usage)
            return token_usage

        patch_text, tu = capture_git_patch(repo_root, _run)
        # capture_git_patch returns tu={} when it recovers a patch AFTER _run raised; fall
        # back to the usage parsed just before the error so tokens are never lost.
        return patch_text, (tu or holder["usage"])

    waited = 0.0
    for attempt in range(1, max_attempts + 1):
        try:
            return _attempt()
        except ProviderError as pe:
            if not pe.retryable or attempt == max_attempts:
                raise
            backoff = min(retry_backoff_cap, 5 * 2 ** (attempt - 1), retry_max_wait - waited)
            if backoff <= 0:            # total sleep budget spent -> stop retrying
                raise
            LOGGER.warning("Claude provider error (attempt %d, waited %.0f/%.0fs), retry in %.0fs: %s",
                           attempt, waited, retry_max_wait, backoff, str(pe)[:160])
            time.sleep(backoff)
            waited += backoff
    raise RuntimeError("call_claude: exhausted retries without returning")  # unreachable


def main():
    data = read_agent_input()
    instance_id = data["instance_id"]
    problem = data["problem_statement"]
    repo_root = Path(data["repo_root"])
    # Hermetic by default: isolate CLAUDE_CONFIG_DIR (seeded with creds only) so ambient
    # skills/subagents/MCP/user-memory don't leak into the measured run. MUST run before the
    # claude CLI is invoked. (ZBENCH_HERMETIC=0 opts out.) Ported from the old harness --
    # the flags alone (claude_hermetic_flags) do NOT isolate the config dir.
    from ..hermetic import ensure_claude_hermetic_env
    _cfg = ensure_claude_hermetic_env()
    LOGGER.info("claude hermetic=%s config_dir=%s", is_hermetic(), _cfg)
    # live transcript destination (claude has no native session file) -> tailable rawcli.
    # The parent hands us ZBENCH_RAWCLI_PATH under the per-cell evidence dir.
    stream_path = os.environ.get("ZBENCH_RAWCLI_PATH")
    if not stream_path:
        try:
            bucket = os.environ.get("ZBENCH_RUN_ID") or "adhoc"
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            stream_path = str(io_logs_dir(bucket) / f"claude__{instance_id}__rawcli__{stamp}.txt")
        except Exception:
            stream_path = None
    try:
        patch_text, token_usage = call_claude(problem, repo_root, stream_path=stream_path)
        emit_agent_output(instance_id, "claude", [patch_text], **token_usage)
    except ProviderError as pe:
        # Endpoint refused/dropped the request and no patch was produced -> infra, not a
        # capability miss. The failure channel maps this to a provider_error attempt status.
        LOGGER.error("provider error for %s: %s", instance_id, str(pe)[:300])
        emit_agent_output(instance_id, "claude", [],
                          failure={"kind": "provider_error", "message": str(pe)[:500],
                                   "retryable": pe.retryable})
    except Exception as e:
        LOGGER.exception("Error generating patch for %s: %s", instance_id, e)
        emit_agent_output(instance_id, "claude", [])


if __name__ == "__main__":
    main()
