#!/usr/bin/env python3
"""pi adapter provider-failure classification tests (no model, no pi binary needed --
the pi session jsonl is the only input).
Run: python3 zbench/tests/test_pi_adapter.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ZBENCH_DATA_DIR", tempfile.mkdtemp())

# A pi --session transcript: pi records the endpoint failure ON THE TURN and exits 0, so
# only the session can tell a throttle from a give-up. Shape copied from a real cell
# (bench-db/.runtime/cells/pi-foundry-glm-5.2__...__foundry-py10, 2026-08-17).
_THROTTLED_SESSION = [
    {"type": "session"},
    {"type": "message", "message": {"role": "user", "content": "fix it"}},
    {"type": "message", "message": {"role": "assistant", "content": [],
                                    "stopReason": "toolUse"}},
    {"type": "message", "message": {
        "role": "assistant", "content": [], "stopReason": "error",
        "errorMessage": "429 Your requests to FW-GLM-5.2 for FW-GLM-5.2 in eastus2 "
                        "have exceeded rate limit."}},
    {"type": "message", "message": {
        "role": "assistant", "content": [], "stopReason": "error",
        "errorMessage": "429 Your requests to FW-GLM-5.2 for FW-GLM-5.2 in eastus2 "
                        "have exceeded rate limit."}},
]

_GAVE_UP_SESSION = [
    {"type": "session"},
    {"type": "message", "message": {"role": "user", "content": "fix it"}},
    {"type": "message", "message": {"role": "assistant",
                                    "content": [{"type": "text", "text": "I am done."}],
                                    "stopReason": "stop"}},
]


def _session_file(records: list[dict]) -> str:
    path = Path(tempfile.mkdtemp()) / "session.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return str(path)


def test_throttled_turns_are_read_off_the_session():
    from zbench.agents.pi_agent import _session_turn_errors
    errs = _session_turn_errors(_session_file(_THROTTLED_SESSION))
    assert len(errs) == 2, errs
    assert all("429" in e for e in errs), errs


def test_clean_session_reports_no_turn_errors():
    from zbench.agents.pi_agent import _session_turn_errors
    assert _session_turn_errors(_session_file(_GAVE_UP_SESSION)) == []
    assert _session_turn_errors(None) == []
    assert _session_turn_errors("/no/such/session.jsonl") == []


def test_throttle_classifies_as_retryable_provider_error():
    """A 429-killed pi run is infra, not a capability miss (METHODOLOGY sec.3)."""
    from zbench.agents.pi_agent import _provider_error
    perr = _provider_error(_session_file(_THROTTLED_SESSION))
    assert perr is not None and perr.retryable, perr
    assert "429" in str(perr) and "errored turn" in str(perr), str(perr)


def test_give_up_is_not_excused_as_infra():
    """An agent that simply produced no patch must STAY a capability miss."""
    from zbench.agents.pi_agent import _provider_error
    assert _provider_error(_session_file(_GAVE_UP_SESSION)) is None
    assert _provider_error(None) is None


def test_cli_crash_message_is_classified_too():
    """When pi exits non-zero the reason arrives as an exception string, not a turn."""
    from zbench.agents.pi_agent import _provider_error
    clean = _session_file(_GAVE_UP_SESSION)
    perr = _provider_error(clean, extra="pi CLI failed (rc=1): 503 Service Unavailable")
    assert perr is not None and perr.retryable, perr
    assert _provider_error(clean, extra="pi CLI failed (rc=2): Unknown option --nope") is None


def test_fatal_provider_failure_is_not_retryable():
    from zbench.agents.pi_agent import _provider_error
    session = _session_file([{"type": "message", "message": {
        "role": "assistant", "content": [], "stopReason": "error",
        "errorMessage": "404 DeploymentNotFound: FW-DeepSeek-V4-Flash"}}])
    perr = _provider_error(session)
    assert perr is not None and not perr.retryable, perr


def test_main_emits_provider_error_only_when_the_patch_is_empty():
    """The emitted output carries failure.kind=provider_error, which the parent maps to a
    provider_error attempt status. A patch outranks the errors: it is a real signal."""
    from zbench.agents.base_agent import emit_agent_output
    from zbench.agents.pi_agent import _provider_error
    session = _session_file(_THROTTLED_SESSION)

    buf = io.StringIO()
    with redirect_stdout(buf):
        perr = _provider_error(session)
        emit_agent_output("iid", "pi", [], failure={
            "kind": "provider_error", "retryable": perr.retryable, "message": str(perr)[:500]})
    out = json.loads(buf.getvalue())
    assert out["failure"]["kind"] == "provider_error" and out["failure"]["retryable"]
    assert out["patches"] == []

    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        emit_agent_output("iid", "pi", ["diff --git a b"], input_tokens=7)
    ok = json.loads(buf2.getvalue())
    assert "failure" not in ok and ok["token_usage"]["input_tokens"] == 7


def test_pi_and_codex_share_one_failure_vocabulary():
    """One definition of an endpoint failure: a throttle cannot be infra on codex and a
    capability miss on pi (the split measured on run foundry-py10)."""
    from zbench.agents import codex_agent, pi_agent
    from zbench.agents.base_agent import classify_provider_failure
    assert codex_agent._provider_error("429 exceeded rate limit").retryable
    assert classify_provider_failure("429 exceeded rate limit").retryable
    for mod in (codex_agent, pi_agent):
        src = Path(mod.__file__).read_text()
        assert "_RETRYABLE_SIGS = (" not in src, f"{mod.__name__} re-declared the signatures"


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"pi-adapter: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
