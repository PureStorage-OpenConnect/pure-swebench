#!/usr/bin/env python3
"""codex adapter command construction + cell provider-pool routing tests (no model, no
codex binary needed -- pure command/pool computation).
Run: python3 zbench/tests/test_codex_adapter.py
"""
from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ZBENCH_DATA_DIR", tempfile.mkdtemp())

_KNOBS = ("CODEX_EXEC_ARGS", "CODEX_MODEL_NAME", "CODEX_BASE_URL", "CODEX_WIRE_API",
          "CODEX_REASONING_EFFORT", "CODEX_STREAM_MAX_RETRIES", "CODEX_REQUEST_MAX_RETRIES",
          "CODEX_STREAM_IDLE_TIMEOUT_MS")


@contextlib.contextmanager
def _env(**kv):
    """Set exactly the given codex knobs (all others cleared); restore on exit."""
    saved = {k: os.environ.get(k) for k in _KNOBS}
    try:
        for k in _KNOBS:
            os.environ.pop(k, None)
        for k, v in kv.items():
            os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---- codex command construction (CODEX_WIRE_API -> -c custom-provider overrides) ----

def test_codex_cmd_default_no_overrides():
    """Unset CODEX_WIRE_API -> no -c overrides at all (fully backward compatible)."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env():
        cmd = _build_codex_cmd("fix it")
    assert cmd[0] == "codex" and cmd[1] == "exec" and cmd[-1] == "fix it"
    assert "-c" not in cmd and not any("model_provider" in a for a in cmd)


def test_codex_cmd_base_url_only_no_overrides():
    """CODEX_BASE_URL alone keeps the legacy env-var path: still no -c overrides."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://127.0.0.1:8000/v1"):
        cmd = _build_codex_cmd("p")
    assert "-c" not in cmd


def test_codex_cmd_wire_api_alone_no_overrides():
    """CODEX_WIRE_API without CODEX_BASE_URL is inert (nothing to point a provider at)."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_WIRE_API="chat"):
        cmd = _build_codex_cmd("p")
    assert "-c" not in cmd


def test_codex_cmd_wire_api_overrides_present():
    """Both set -> the provider -c overrides appear (TOML-quoted values, verified against
    codex-cli 0.125.0), model flag + trailing prompt preserved. The retry-budget keys sit
    between wire_api and the provider selection."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://127.0.0.1:9099/v1", CODEX_WIRE_API="chat",
              CODEX_MODEL_NAME="fw-deepseek-v4-flash"):
        cmd = _build_codex_cmd("fix it")
    pairs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-c"]
    assert pairs == [
        'model_providers.zbench.name="zbench"',
        'model_providers.zbench.base_url="http://127.0.0.1:9099/v1"',
        'model_providers.zbench.env_key="OPENAI_API_KEY"',
        'model_providers.zbench.wire_api="chat"',
        "model_providers.zbench.stream_max_retries=10",
        "model_providers.zbench.request_max_retries=8",
        "model_providers.zbench.stream_idle_timeout_ms=300000",
        'model_provider="zbench"',
    ]
    assert cmd[cmd.index("--model") + 1] == "fw-deepseek-v4-flash"
    assert cmd[-1] == "fix it"
    # overrides come after the exec args, before --model
    assert cmd.index("-c") > cmd.index("exec") and cmd.index("-c") < cmd.index("--model")


def test_codex_cmd_wire_api_responses_value_passthrough():
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://127.0.0.1:9099/v1", CODEX_WIRE_API="responses"):
        cmd = _build_codex_cmd("p")
    assert 'model_providers.zbench.wire_api="responses"' in cmd


def test_codex_cmd_exec_args_override_kept_with_wire_api():
    """CODEX_EXEC_ARGS still replaces the exec flags entirely; -c overrides ride along."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_EXEC_ARGS="exec --full-auto",
              CODEX_BASE_URL="http://h:1/v1", CODEX_WIRE_API="responses"):
        cmd = _build_codex_cmd("p")
    assert cmd[:3] == ["codex", "exec", "--full-auto"]
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd  # default args replaced
    assert 'model_provider="zbench"' in cmd and cmd[-1] == "p"


# ---- run_cell._provider_pool (generation-slot routing) ----

def test_provider_pool_zbench_override_wins_regardless_of_harness():
    from zbench.cells.run_cell import _provider_pool
    for agent in (
        {"command": "python3 -m zbench.agents.codex_agent",
         "env": {"CODEX_BASE_URL": "http://127.0.0.1:9099/v1",
                 "ZBENCH_PROVIDER_POOL": "azure-foundry-fireworks-kimi"}},
        {"command": "python3 -m zbench.agents.claude_agent",
         "env": {"ZBENCH_PROVIDER_POOL": "azure-foundry-fireworks-kimi"}},
        {"command": "python3 -m zbench.agents.pi_agent",
         "env": {"PI_PROVIDER": "anthropic",
                 "ZBENCH_PROVIDER_POOL": "azure-foundry-fireworks-kimi"}},
    ):
        assert _provider_pool(agent) == "provider:azure-foundry-fireworks-kimi", agent


def test_provider_pool_existing_fallbacks_unchanged():
    from zbench.cells.run_cell import _provider_pool
    assert _provider_pool({"command": "python3 -m zbench.agents.claude_agent",
                           "env": {}}) == "provider:claude-cli"
    assert _provider_pool({"command": "python3 -m zbench.agents.codex_agent",
                           "env": {}}) == "provider:openai"
    assert _provider_pool({"command": "python3 -m zbench.agents.codex_agent",
                           "env": {"CODEX_BASE_URL": "http://127.0.0.1:8000/v1"}}) \
        == "provider:codex-selfhost:http://127.0.0.1:8000/v1"
    assert _provider_pool({"command": "python3 -m zbench.agents.pi_agent",
                           "env": {"PI_PROVIDER": "azure-foundry"}}) == "provider:azure-foundry"
    assert _provider_pool({"command": "something-else", "env": {}}) == "provider:unknown"


def test_provider_pool_empty_override_ignored():
    """An empty ZBENCH_PROVIDER_POOL value falls through to the heuristics (no
    'provider:' pool with an empty name)."""
    from zbench.cells.run_cell import _provider_pool
    assert _provider_pool({"command": "python3 -m zbench.agents.claude_agent",
                           "env": {"ZBENCH_PROVIDER_POOL": ""}}) == "provider:claude-cli"


def test_flash_pool_capped_serialized():
    """The FW-DeepSeek-V4-Flash deployment pool exists and is serialized (cap 1), like
    its Fireworks-on-Foundry siblings (429 self-throttling)."""
    from zbench.cells.slots import DEFAULT_CAPS
    assert DEFAULT_CAPS.get("provider:azure-foundry-fireworks-flash") == 1


# ---- reasoning effort (CODEX_REASONING_EFFORT -> -c model_reasoning_effort) ----

def test_effort_unset_emits_nothing():
    """No CODEX_REASONING_EFFORT -> no effort override (backward compatible)."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env():
        cmd = _build_codex_cmd("p")
    assert not any("model_reasoning_effort" in a for a in cmd)


def test_effort_emits_toml_quoted_override():
    """Pinned level becomes a TOML-quoted -c override, adjacent to its -c flag."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_REASONING_EFFORT="high"):
        cmd = _build_codex_cmd("p")
    assert 'model_reasoning_effort="high"' in cmd
    assert cmd[cmd.index('model_reasoning_effort="high"') - 1] == "-c"


def test_effort_coexists_with_provider_overrides():
    """Effort and the custom-provider overrides are independent; both appear."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://127.0.0.1:8788/openai/v1", CODEX_WIRE_API="responses",
              CODEX_REASONING_EFFORT="xhigh"):
        cmd = _build_codex_cmd("p")
    assert 'model_provider="zbench"' in cmd
    assert 'model_reasoning_effort="xhigh"' in cmd


def test_effort_invalid_raises():
    """A typo'd level must FAIL LOUD, never silently fall back to the vendor default --
    a wrong-effort run would otherwise be scored as a capability result."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_REASONING_EFFORT="hihg"):
        try:
            _build_codex_cmd("p")
        except ValueError as e:
            assert "hihg" in str(e)
        else:
            raise AssertionError("invalid effort level did not raise")


def test_effort_recorded_in_provenance():
    """The pinned level must reach attempt provenance, and the API key must not."""
    from zbench.provenance import tooling_config_provenance
    agent = {"env": {"CODEX_MODEL_NAME": "m", "CODEX_REASONING_EFFORT": "high",
                     "CODEX_API_KEY": "secret-value"}}
    out = tooling_config_provenance("codex", agent)
    assert out["codex_env"]["CODEX_REASONING_EFFORT"] == "high"
    assert "CODEX_API_KEY" not in out["codex_env"]
    assert out["sha256"]


# ---- codex's own per-provider retry budget ----

def test_retry_budget_overrides_emitted_with_custom_provider():
    """The gateway case must widen codex's stream/request retry budget past its stock
    ~45s, which is shorter than a per-minute Azure/Fireworks quota window."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://127.0.0.1:8788/openai/v1", CODEX_WIRE_API="responses"):
        cmd = _build_codex_cmd("p")
    assert "model_providers.zbench.stream_max_retries=10" in cmd
    assert "model_providers.zbench.request_max_retries=8" in cmd
    assert "model_providers.zbench.stream_idle_timeout_ms=300000" in cmd
    for key in ("stream_max_retries", "request_max_retries", "stream_idle_timeout_ms"):
        arg = next(a for a in cmd if key in a)
        assert cmd[cmd.index(arg) - 1] == "-c"


def test_retry_budget_overridable_and_absent_without_custom_provider():
    """Values are tunable per agent row; and without a custom provider codex has no
    provider block to attach them to, so nothing is emitted (backward compatible)."""
    from zbench.agents.codex_agent import _build_codex_cmd
    with _env(CODEX_BASE_URL="http://h:1/v1", CODEX_WIRE_API="responses",
              CODEX_STREAM_MAX_RETRIES="25"):
        cmd = _build_codex_cmd("p")
    assert "model_providers.zbench.stream_max_retries=25" in cmd
    with _env():
        assert not any("max_retries" in a for a in _build_codex_cmd("p"))


def test_retry_budget_rejects_junk():
    """A typo must not silently restore the too-short stock budget."""
    from zbench.agents.codex_agent import _build_codex_cmd
    for bad in ("ten", "-1"):
        with _env(CODEX_BASE_URL="http://h:1/v1", CODEX_WIRE_API="responses",
                  CODEX_STREAM_MAX_RETRIES=bad):
            try:
                _build_codex_cmd("p")
            except ValueError as e:
                assert "CODEX_STREAM_MAX_RETRIES" in str(e)
            else:
                raise AssertionError(f"invalid retry budget {bad!r} did not raise")


def test_codex_subprocess_closes_stdin():
    """`codex exec` reads stdin to EOF before starting the turn: an inherited open pipe
    hangs the run, and inherited DATA is appended to the prompt (task contamination)."""
    import inspect
    from zbench.agents import codex_agent
    src = inspect.getsource(codex_agent.call_codex)
    assert "stdin=subprocess.DEVNULL" in src


# ---- provider-failure detection (codex --json turn.failed -> artifact:infra) ----
# Regression guard for the 2026-08-15 sweeps: 14/14 codex cells died on a Foundry 429 and
# every one was stored as a capability miss, because the adapter read only rc and the head
# of stderr (which held an unrelated CODEX_HOME warning).

_RATE_LIMIT_STREAM = "\n".join([
    '{"type": "thread.started", "thread_id": "01a00904-f90e-72e2-be0e-60f8f63fc098"}',
    '{"type": "turn.started"}',
    '{"type": "error", "message": "Reconnecting... 1/5 (stream disconnected before completion: '
    'Your requests to gpt-5.5 for gpt-5.5 in eastus2 have exceeded rate limit.)"}',
    '{"type": "turn.failed", "error": {"message": "stream disconnected before completion: '
    'Your requests to gpt-5.5 for gpt-5.5 in eastus2 have exceeded rate limit."}}',
])

_FIREWORKS_429_STREAM = (
    '{"type": "turn.failed", "error": {"message": "exceeded retry limit, '
    'last status: 429 Too Many Requests"}}')


def test_terminal_error_prefers_turn_failed_over_reconnect_noise():
    """`error` events are emitted per reconnect attempt; only turn.failed is terminal."""
    from zbench.agents.codex_agent import _terminal_error
    msg = _terminal_error(_RATE_LIMIT_STREAM)
    assert msg.startswith("stream disconnected before completion")
    assert "Reconnecting" not in msg


def test_terminal_error_none_on_clean_stream():
    """A completed turn must not be reported as a failure."""
    from zbench.agents.codex_agent import _terminal_error
    clean = ('{"type": "thread.started", "thread_id": "t"}\n'
             '{"type": "item.completed", "item": {"id": "i", "type": "agent_message", "text": "done"}}\n'
             '{"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 2}}')
    assert _terminal_error(clean) is None
    assert _terminal_error("") is None


def test_terminal_error_ignores_unparsable_lines():
    """Non-JSON banner lines in the stream must not break the scan."""
    from zbench.agents.codex_agent import _terminal_error
    noisy = "some banner\n{not json}\n" + _FIREWORKS_429_STREAM
    assert "429" in _terminal_error(noisy)


def test_rate_limit_is_retryable_provider_error():
    """Both observed 429 dialects classify as retryable provider failures."""
    from zbench.agents.codex_agent import _provider_error, _terminal_error
    for stream in (_RATE_LIMIT_STREAM, _FIREWORKS_429_STREAM):
        err = _provider_error(_terminal_error(stream))
        assert err is not None and err.retryable, stream


def test_auth_and_missing_model_are_fatal_not_retryable():
    """Retrying a 401/404 only burns the cell budget."""
    from zbench.agents.codex_agent import _provider_error
    for msg in ("401 Unauthorized", "DeploymentNotFound: FW-DeepSeek-V4-Flash",
                "404 model_not_found"):
        err = _provider_error(msg)
        assert err is not None and not err.retryable, msg
    # codex's own harmless "thread ... not found" must never make a throttle look fatal
    mixed = ("stream disconnected before completion: exceeded rate limit "
             "(thread 01a0 not found)")
    err = _provider_error(mixed)
    assert err is not None and err.retryable, mixed


def test_non_provider_failure_is_not_classified_as_provider_error():
    """A codex/harness fault must stay a plain error, so it is not excused as infra."""
    from zbench.agents.codex_agent import _provider_error
    assert _provider_error("unknown flag: --json") is None
    assert _provider_error("") is None


def test_provider_error_status_maps_to_infra_artifact():
    """provider_error must never score as a capability miss (METHODOLOGY sec.3)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "zb_scoring", ROOT / "zbench-tasks" / "scoring.py")
    S = importlib.util.module_from_spec(spec)
    sys.modules["zb_scoring"] = S
    spec.loader.exec_module(S)
    row = {"tests_passed": 0, "status": "provider_error", "outcome": "internal_error",
           "runtime_ms": 175600, "total_duration_ms": 175600, "output_tokens": None}
    assert S.classify_attempt(row, 3000) == "artifact:infra"
    assert S.is_artifact_class("artifact:infra")
    # the same runtime under the OLD status is a capability miss -- that is the bug
    assert S.classify_attempt({**row, "status": "no_patch_generated",
                               "outcome": "candidate_missing"}, 3000) == "no_patch_genuine"


def test_provider_error_is_rerunnable_everywhere():
    """Every status vocabulary that gates re-runs must know the new status."""
    import importlib.util
    for path, attr in ((ROOT / "zbench-tasks" / "run_coverage_matrix.py", "NONFINAL"),
                       (ROOT / "tools" / "wait_for_cells.py", "INFRA_STATUSES")):
        src = path.read_text()
        assert "provider_error" in src.split(attr, 1)[1][:200], f"{path.name}:{attr}"
    from zbench.workflow import map_status_to_attempt_outcome
    assert map_status_to_attempt_outcome("provider_error") == "internal_error"


def test_emit_agent_output_carries_failure_channel():
    """The adapter->parent wire format must transport the failure reason."""
    import io
    import json as _json
    from contextlib import redirect_stdout
    from zbench.agents.base_agent import emit_agent_output
    buf = io.StringIO()
    with redirect_stdout(buf):
        emit_agent_output("iid", "codex", [],
                          failure={"kind": "provider_error", "retryable": True, "message": "429"})
    out = _json.loads(buf.getvalue())
    assert out["patches"] == [] and out["failure"]["kind"] == "provider_error"
    assert "token_usage" not in out   # `failure` must not leak into the usage map

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        emit_agent_output("iid", "codex", ["diff --git a b"], input_tokens=5)
    ok = _json.loads(buf2.getvalue())
    assert "failure" not in ok and ok["token_usage"]["input_tokens"] == 5


def test_workflow_maps_provider_failure_to_provider_error_status():
    """A no-patch output carrying failure.kind=provider_error must not be scored as a
    give-up; without the failure channel the same shape stays no_patch_generated."""
    import inspect
    from zbench import workflow
    src = inspect.getsource(workflow.run_patch_task_attempt)
    assert 'failure.get("kind") == "provider_error"' in src
    assert 'status="provider_error" if provider_failed else "no_patch_generated"' in src


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"codex-adapter: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
