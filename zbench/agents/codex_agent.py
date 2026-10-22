"""zbench adapter for the OpenAI ``codex`` CLI (patch tasks only).

Codex is an agentic coding CLI: run headlessly in the sealed worktree, it edits files
directly; we capture the git diff via the shared patch_capture (same mechanism as the
claude adapter). Because Codex speaks the OpenAI API, this ONE adapter drives BOTH
proprietary OpenAI models (ChatGPT / GPT-*) AND any OpenAI-compatible endpoint --
including an open-weight model you self-host with vLLM/SGLang -- by pointing Codex at a
custom base URL. That makes it the pi-free path for open-weight models.

Env knobs (per-cell in agents-*.jsonl `env`):
  CODEX_MODEL_NAME   -> --model (e.g. gpt-5.5, or a served open-weight model name)
  CODEX_BASE_URL     -> OpenAI-compatible base URL (self-hosted vLLM, e.g.
                        http://127.0.0.1:8000/v1). Unset -> OpenAI's API.
  CODEX_API_KEY      -> key for that endpoint (falls back to OPENAI_API_KEY; a served
                        vLLM usually accepts any non-empty token).
  CODEX_WIRE_API     -> "chat" | "responses". Only takes effect when CODEX_BASE_URL is
                        ALSO set: the pair is turned into `-c` config overrides that
                        define + select a custom codex model provider (see
                        _custom_provider_overrides), because codex's DEFAULT OpenAI
                        provider speaks the "responses" wire API while plain
                        OpenAI-compatible gateways/vLLM only speak "chat". Unset -> no
                        overrides, codex default behavior (fully backward compatible).
                        CAVEAT (verified on codex-cli 0.125.0): wire_api="chat" was
                        REMOVED upstream (config load fails: '`wire_api = "chat"` is no
                        longer supported', github.com/openai/codex/discussions/7782).
                        On >=0.125 use "responses" and put a responses->chat translating
                        proxy in front of chat-only backends (e.g.
                        tools/foundry_gateway_proxy.py for Azure AI Foundry); "chat"
                        remains supported here for older pinned codex installs.
  CODEX_REASONING_EFFORT -> `-c model_reasoning_effort=<level>`: none | minimal | low |
                        medium | high | xhigh (codex-cli 0.125.0). Codex exposes effort
                        as a CONFIG key, not a flag. Unset -> codex's default, which is
                        unrecorded and version-dependent; ranked rows must pin it.
  CODEX_EXEC_ARGS    -> OVERRIDE the exec flags entirely (space-split) if your installed
                        codex version differs from the default below. The default targets
                        a recent `codex exec` (headless, approvals+sandbox bypassed).
  CODEX_STREAM_MAX_RETRIES / CODEX_REQUEST_MAX_RETRIES / CODEX_STREAM_IDLE_TIMEOUT_MS
                     -> codex's OWN per-provider retry budget (`model_providers.zbench.*`,
                        so they apply only when the custom provider is used, i.e. when
                        CODEX_BASE_URL + CODEX_WIRE_API are both set). Defaults here are
                        raised above codex's stock values because the stock stream budget
                        (~45s) is shorter than a per-minute Azure/Fireworks quota window,
                        so a single throttled turn otherwise kills the whole run.
  CODEX_MAX_ATTEMPTS -> how many times to run codex when it dies on a RETRYABLE provider
                        failure (429 / rate limit / dropped stream / 5xx). Default 3.
                        Codex's own in-process retry gives up in seconds, which is far
                        too fast for a per-deployment Azure/Fireworks quota; see
                        _RETRYABLE_SIGS.
  CODEX_RETRY_BACKOFF_S -> first backoff in seconds (doubles per attempt). Default 20.
  ZBENCH_AGENT_TIMEOUT -> wall-clock cap for ALL attempts together (default 1800s).

NOTE: Codex CLI flags change between releases. If a run fails with an unknown-flag error,
set CODEX_EXEC_ARGS to your version's headless invocation (see docs/running-your-models.md).

NOTE: avoid pointing CODEX_HOME at a directory under /tmp. codex then refuses to create
its helper binaries ("Refusing to create helper binaries under temporary dir") -- harmless
under the bypass sandbox we use (verified: a /tmp CODEX_HOME still completes a turn rc=0,
and apply_patch is handled in-process), but the warning is printed BEFORE any real error,
so it masks the true failure in short stderr excerpts. It WOULD matter under a real
sandbox policy, which needs codex-linux-sandbox. Leaving CODEX_HOME unset is best: codex
then uses ~/.codex, which also holds its auth.
"""
import json
import os
import subprocess
import time
from pathlib import Path

from .base_agent import (ProviderError, classify_provider_failure, emit_agent_output,
                         get_agent_logger, read_agent_input)
from .patch_capture import capture_git_patch

LOGGER = get_agent_logger("codex")

# Default headless invocation for a recent codex CLI. `exec` = non-interactive; the
# bypass flag = act without approval prompts (the claude --dangerously-skip-permissions
# analogue); --skip-git-repo-check because the sealed worktree is a bare init repo.
_DEFAULT_EXEC_ARGS = ("exec --skip-git-repo-check "
                      "--dangerously-bypass-approvals-and-sandbox --json")


def _int_knob(name: str, default: int) -> int:
    """A non-negative integer env override. A junk value must FAIL LOUD: silently falling
    back would leave the run's retry budget unrecorded and version-dependent."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not an integer") from None
    if val < 0:
        raise ValueError(f"{name}={raw!r} must be >= 0")
    return val


def _custom_provider_overrides() -> list:
    """`-c` config overrides defining + selecting a custom codex model provider, emitted
    ONLY when both CODEX_BASE_URL and CODEX_WIRE_API are set (either alone -> no overrides;
    base-URL-only keeps the legacy env-var path in _codex_env). Values are TOML-quoted --
    codex parses the value portion of `-c key=value` as TOML (raw-string fallback exists,
    but quoting is deterministic); quotes are literal argv chars, we exec without a shell.
    Both forms verified against codex-cli 0.125.0. env_key=OPENAI_API_KEY means codex
    reads the key from the env we already export in _codex_env."""
    base = os.environ.get("CODEX_BASE_URL")
    wire = os.environ.get("CODEX_WIRE_API")
    if not (base and wire):
        return []
    return [
        "-c", 'model_providers.zbench.name="zbench"',
        "-c", f'model_providers.zbench.base_url="{base}"',
        "-c", 'model_providers.zbench.env_key="OPENAI_API_KEY"',
        "-c", f'model_providers.zbench.wire_api="{wire}"',
        # Codex's stock reconnect budget (5 stream retries over ~45s) is shorter than a
        # per-minute Azure/Fireworks token quota window, so ONE throttled turn kills the
        # whole run. These keys exist on the model_providers struct in codex-cli 0.125.0
        # and only take effect on a CUSTOM provider, which is exactly the gateway case.
        "-c", f'model_providers.zbench.stream_max_retries={_int_knob("CODEX_STREAM_MAX_RETRIES", 10)}',
        "-c", f'model_providers.zbench.request_max_retries={_int_knob("CODEX_REQUEST_MAX_RETRIES", 8)}',
        "-c", f'model_providers.zbench.stream_idle_timeout_ms={_int_knob("CODEX_STREAM_IDLE_TIMEOUT_MS", 300000)}',
        "-c", 'model_provider="zbench"',
    ]


# Accepted by codex-cli 0.125.0 (probed: an unknown value is rejected at config load
# with "expected one of ..."). Codex has no --effort flag; effort is a config override.
_EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh")


def _reasoning_effort_override() -> list:
    """`-c model_reasoning_effort=...` from CODEX_REASONING_EFFORT.

    Unset => codex's own default, which is NOT recorded anywhere and can shift under a
    CLI upgrade -- so ranked agent rows should always pin it explicitly (METHODOLOGY
    sec.3, cross-agent parity of stopping conditions). An unknown value raises here
    rather than silently falling back: a typo'd level would otherwise score as a
    capability result at the wrong effort."""
    eff = (os.environ.get("CODEX_REASONING_EFFORT") or "").strip()
    if not eff:
        return []
    if eff not in _EFFORT_LEVELS:
        raise ValueError(f"CODEX_REASONING_EFFORT={eff!r} invalid; "
                         f"expected one of {', '.join(_EFFORT_LEVELS)}")
    return ["-c", f'model_reasoning_effort="{eff}"']


def _build_codex_cmd(problem: str) -> list:
    args = os.environ.get("CODEX_EXEC_ARGS", _DEFAULT_EXEC_ARGS).split()
    cmd = ["codex", *args]
    cmd += _custom_provider_overrides()     # CODEX_BASE_URL + CODEX_WIRE_API (or nothing)
    cmd += _reasoning_effort_override()     # CODEX_REASONING_EFFORT (or nothing)
    if os.environ.get("CODEX_MODEL_NAME"):
        cmd += ["--model", os.environ["CODEX_MODEL_NAME"]]
    cmd.append(problem)                     # prompt is the trailing positional arg
    return cmd


def _codex_env() -> dict:
    """Env for the codex subprocess: point it at a custom OpenAI-compatible endpoint if
    CODEX_BASE_URL is set (self-hosted open-weight), else OpenAI's default."""
    env = os.environ.copy()
    base = os.environ.get("CODEX_BASE_URL")
    if base:
        env["OPENAI_BASE_URL"] = base
        env["OPENAI_API_BASE"] = base       # older SDKs read this name
    key = os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if key:
        env["OPENAI_API_KEY"] = key
    return env


# codex item.completed types that are NOT a distinct model round-trip (planning + the diff
# byproduct of an apply_patch command + standalone reasoning). Everything else -- an
# agent_message or a command/tool call -- is one model response.
_CODEX_NON_TURN_ITEMS = {"todo_list", "file_change", "reasoning"}


def _parse_usage(stream: str) -> dict:
    """Best-effort token usage from codex --json JSONL. Codex's event schema varies by
    version; we scan for any object carrying a usage/token_count block and take the last
    (cumulative) one. Missing usage -> empty (cost is then computed at read time only if
    tokens exist; document this limitation per model)."""
    usage = {}
    action_items = turn_events = 0
    for line in stream.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        u = None
        if isinstance(ev, dict):
            etype = ev.get("type") or (ev.get("msg") or {}).get("type")
            if etype == "item.completed":
                itype = (ev.get("item") or {}).get("type") if isinstance(ev.get("item"), dict) else None
                if itype not in _CODEX_NON_TURN_ITEMS:
                    action_items += 1
            elif etype in ("turn.started", "turn.completed"):
                turn_events += 1
            u = ev.get("usage") or ev.get("token_usage") or (ev.get("msg") or {}).get("usage")
        if isinstance(u, dict):
            it = u.get("input_tokens") or u.get("prompt_tokens") or u.get("input")
            ot = u.get("output_tokens") or u.get("completion_tokens") or u.get("output")
            cr = u.get("cached_input_tokens") or u.get("cache_read_tokens")
            if it is not None or ot is not None:
                it, ot, cr = (it or 0), (ot or 0), (cr or 0)
                # OpenAI/codex report input_tokens INCLUSIVE of the cached prefix
                # (cached_tokens is a subset of input_tokens). zbench's convention --
                # matching pi and Anthropic -- is input_tokens = NON-cached only, with
                # cache_read counted separately. Subtract so model_prices.cost_usd does
                # not double-charge the cached tokens (once at the input rate, again at
                # the cache_read rate). max() guards a future schema that already splits.
                non_cached_in = max(0, it - cr)
                usage = {"input_tokens": non_cached_in, "output_tokens": ot,
                         "cache_read_tokens": cr,
                         "total_tokens": non_cached_in + ot + cr}
    # codex wraps a whole task in ONE thread `turn`, so turn.* is always 1. Its model
    # round-trips are the ACTION items it completes (one model response -> one command/tool
    # call or a text message); exclude planning/byproduct items. Fall back to turn events
    # only for a run that died before any item completed.
    turns = action_items or turn_events
    if turns:
        usage["turns"] = turns
    return usage


# The endpoint-failure vocabulary is shared with every other adapter (base_agent), so a
# throttle cannot be infra here and a capability miss on pi. Observed codex dialects that
# the shared signatures cover: Azure OpenAI drops the SSE stream mid-turn ("stream
# disconnected before completion: ... have exceeded rate limit."), Fireworks-on-Foundry
# returns a hard 429 ("exceeded retry limit, last status: 429 Too Many Requests").
CodexProviderError = ProviderError       # local name kept: it reads better at call sites


def _terminal_error(stream: str) -> str | None:
    """The FATAL message from codex's `--json` event stream, or None if the turn ended
    cleanly. Codex reports provider failures as events on STDOUT and still prints only
    incidental noise on stderr, so stderr alone cannot tell a throttle from a give-up.

    `turn.failed` is the authoritative terminal event; bare `error` events are also
    emitted for each intermediate retry ("Reconnecting... 3/5"), so they are used only
    as a fallback when no turn.failed arrived."""
    failed_msg = None
    last_error = None
    for line in stream.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "turn.failed":
            err = ev.get("error")
            failed_msg = (err.get("message") if isinstance(err, dict) else None) or str(err or "")
        elif ev.get("type") == "error":
            last_error = ev.get("message") or last_error
    return failed_msg or last_error


def _provider_error(message: str) -> CodexProviderError | None:
    """Classify a terminal codex message. Returns None when the message does not look
    like a provider failure at all (then it is a codex/harness problem, not the endpoint)."""
    return classify_provider_failure(message)


def _warn_bad_codex_home() -> None:
    """codex refuses to install helper binaries under a /tmp CODEX_HOME and prints that
    warning FIRST, ahead of the real error. Harmless under our bypass sandbox, but it
    masks the true failure in stderr excerpts -- so say so once, at our own log level."""
    home = os.environ.get("CODEX_HOME")
    try:
        bad = bool(home) and Path(home).resolve().is_relative_to(Path("/tmp"))
    except (OSError, ValueError):
        bad = False
    if bad:
        LOGGER.warning("CODEX_HOME=%s is under /tmp; codex refuses to create helper binaries "
                       "there. Not fatal here, but its warning masks real errors in stderr "
                       "excerpts, and a real sandbox policy would break. Prefer unsetting it.",
                       home)


def call_codex(problem: str, repo_root: Path, stream_path: str | None = None) -> tuple[str, dict]:
    repo_root = Path(repo_root).resolve()
    cmd = _build_codex_cmd(problem)
    budget = int(os.environ.get("ZBENCH_AGENT_TIMEOUT", "1800"))
    max_attempts = max(1, int(os.environ.get("CODEX_MAX_ATTEMPTS", "3")))
    backoff = float(os.environ.get("CODEX_RETRY_BACKOFF_S", "20"))
    _warn_bad_codex_home()
    deadline = time.monotonic() + budget

    def _once(timeout: float) -> dict:
        """One codex invocation. Raises CodexProviderError when the ENDPOINT failed."""
        try:
            # stdin=DEVNULL is REQUIRED, not tidiness. `codex exec` reads stdin to EOF
            # before it starts the turn even when the prompt is a positional arg, so an
            # inherited open pipe HANGS the run to the timeout, and inherited DATA is
            # appended to the prompt as "<stdin>...</stdin>" -- silent contamination of a
            # benchmark task. Both reproduced on codex-cli 0.125.0.
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=timeout, cwd=str(repo_root), env=_codex_env())
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"codex CLI timed out after {int(timeout)}s") from e
        except FileNotFoundError as e:
            raise RuntimeError("codex CLI not found (npm i -g @openai/codex)") from e
        if stream_path:
            try:
                Path(stream_path).parent.mkdir(parents=True, exist_ok=True)
                Path(stream_path).write_text((r.stdout or "") + "\n--- stderr ---\n" + (r.stderr or ""),
                                             encoding="utf-8")
            except Exception:
                pass
        # The real reason lives in the --json event stream, NOT in stderr: stderr carries
        # only incidental noise (a CODEX_HOME warning, a rollout-recorder message) that
        # would otherwise be reported as if it were the failure.
        fatal = _terminal_error(r.stdout or "")
        if fatal:
            perr = _provider_error(fatal)
            if perr is not None:
                raise perr
            raise RuntimeError(f"codex turn failed: {fatal}")
        if r.returncode != 0:
            LOGGER.error("codex stderr: %s", (r.stderr or "")[-500:])
            raise RuntimeError(f"codex CLI failed (rc={r.returncode}): {(r.stderr or '')[-300:]}")
        usage = _parse_usage(r.stdout)
        if usage:
            LOGGER.info("codex usage: %s", usage)
        return usage

    def _run() -> dict:
        """Retry the RETRYABLE provider failures with exponential backoff. Codex's own
        reconnect gives up in seconds, which never outlasts a per-deployment quota
        window; without this a throttled cell is thrown away as a model failure."""
        wait = backoff
        last: CodexProviderError | None = None
        for attempt in range(1, max_attempts + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return _once(remaining)
            except CodexProviderError as e:
                last = e
                if not e.retryable or attempt == max_attempts:
                    raise
                remaining = deadline - time.monotonic()
                if remaining <= wait:
                    LOGGER.error("codex provider failure with no budget left to retry: %s", e)
                    raise
                LOGGER.warning("codex provider failure (attempt %d/%d), retrying in %.0fs: %s",
                               attempt, max_attempts, wait, e)
                time.sleep(wait)
                wait *= 2
        raise last or RuntimeError(f"codex CLI exhausted its {budget}s budget")

    return capture_git_patch(repo_root, _run)


def main():
    data = read_agent_input()
    instance_id = data["instance_id"]
    problem = data["problem_statement"]
    repo_root = Path(data["repo_root"])
    stream_path = os.environ.get("ZBENCH_RAWCLI_PATH")
    try:
        patch_text, token_usage = call_codex(problem, repo_root, stream_path=stream_path)
        emit_agent_output(instance_id, "codex", [patch_text], **token_usage)
    except CodexProviderError as e:
        # The endpoint failed, so this cell carries NO capability signal. Tell the parent
        # explicitly; an empty patch list alone is indistinguishable from a give-up.
        LOGGER.error("Provider failure for %s (retryable=%s): %s", instance_id, e.retryable, e)
        emit_agent_output(instance_id, "codex", [],
                          failure={"kind": "provider_error", "retryable": e.retryable,
                                   "message": str(e)[:500]})
    except Exception as e:
        LOGGER.exception("Error generating patch for %s: %s", instance_id, e)
        emit_agent_output(instance_id, "codex", [])


if __name__ == "__main__":
    main()
