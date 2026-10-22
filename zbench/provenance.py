"""Runtime provenance capture for zbench attempts.

This records the benchmark code version and the outer agent CLI version used for a
cell. It is intentionally best-effort: provenance should never make a scored run fail.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- pi/claude tooling-config provenance (F6) --------------------------------- #
# Reproducibility needs the CONFIG that actually drives the agent, not just its CLI
# version: pi's ~/.pi/agent/settings.json (retry/timeout policy -- changed mid-benchmark
# in W56) and the used provider/model block from models.json (baseUrl/api/ctx/maxTokens).
# Everything captured here is REDACTED (never store tokens or token-minting commands).

_SECRET_KEY_RE = re.compile(r"(key|token|secret|password|authorization|credential|bearer)", re.I)
_PI_ENV_ALLOW = ("PI_PROVIDER", "PI_MODEL", "PI_THINKING", "PI_REASONING", "PI_MAX_TOKENS",
                 "ZBENCH_AGENT_TIMEOUT")
_CLAUDE_ENV_ALLOW = ("CLAUDE_MODEL_NAME", "CLAUDE_EFFORT", "ZBENCH_CLAUDE_MAX_TURNS",
                     "ZBENCH_AGENT_TIMEOUT")
# Non-secret codex knobs. CODEX_API_KEY is deliberately absent (secret); CODEX_BASE_URL
# is an endpoint, not a credential, and identifies WHICH backend served the run.
_CODEX_ENV_ALLOW = ("CODEX_MODEL_NAME", "CODEX_REASONING_EFFORT", "CODEX_WIRE_API",
                    "CODEX_BASE_URL", "CODEX_EXEC_ARGS", "ZBENCH_AGENT_TIMEOUT")


def _redact(obj):
    """Return a copy with secret-looking KEYS masked and any leading-'!' string (a
    token-minting shell command, e.g. models.json apiKey) replaced. Non-destructive."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = "<redacted>" if isinstance(k, str) and _SECRET_KEY_RE.search(k) else _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str) and obj.startswith("!"):
        return "<redacted-command>"
    return obj


def _pi_home() -> Path:
    for env in ("PI_AGENT_DIR", "PI_CONFIG_DIR"):
        v = os.environ.get(env)
        if v:
            return Path(v)
    return Path(os.path.expanduser("~/.pi/agent"))


def _sha(obj) -> str | None:
    try:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    except Exception:
        return None


def pi_config_provenance(agent: dict) -> dict:
    """REDACTED snapshot + sha256 of the pi config this cell actually uses: settings.json
    (retry/timeout) + the PI_PROVIDER block from models.json (narrowed to PI_MODEL) + an
    allowlist of non-secret pi env values. Best-effort: never raises."""
    env = (agent.get("env") or {})
    provider, model = env.get("PI_PROVIDER"), env.get("PI_MODEL")
    home = _pi_home()
    out = {"kind": "pi", "available": False, "pi_home": str(home), "provider": provider,
           "model": model, "pi_env": {k: env[k] for k in _PI_ENV_ALLOW if k in env}}
    try:
        sp = home / "settings.json"
        if sp.exists():
            out["settings"] = _redact(json.loads(sp.read_text()))
            out["settings_path"] = str(sp)
        mp = home / "models.json"
        if mp.exists():
            m = json.loads(mp.read_text())
            provs = m.get("providers") if isinstance(m, dict) and isinstance(m.get("providers"), dict) else m
            block = provs.get(provider) if isinstance(provs, dict) else None
            if isinstance(block, dict):
                red = _redact(block)
                if model and isinstance(red.get("models"), list):
                    sel = [mm for mm in red["models"] if isinstance(mm, dict) and mm.get("id") == model]
                    red["models"] = sel or red["models"]
                out["provider_block"] = red
                out["models_path"] = str(mp)
        out["available"] = bool(out.get("settings") or out.get("provider_block"))
    except Exception as exc:
        out["error"] = repr(exc)
    out["sha256"] = _sha({"settings": out.get("settings"),
                          "provider_block": out.get("provider_block"), "pi_env": out.get("pi_env")})
    return out


def claude_config_provenance(agent: dict) -> dict:
    """Secret-safe claude-cli config provenance: the non-secret env allowlist only. The
    per-cell CLAUDE_CONFIG_DIR holds OAuth credentials and is deliberately NOT snapshotted."""
    env = (agent.get("env") or {})
    out = {"kind": "claude", "available": True,
           "claude_env": {k: env[k] for k in _CLAUDE_ENV_ALLOW if k in env},
           "note": "CLAUDE_CONFIG_DIR holds OAuth creds; not snapshotted (secret-safe)."}
    out["sha256"] = _sha(out.get("claude_env"))
    return out


def codex_config_provenance(agent: dict) -> dict:
    """Secret-safe codex config provenance: the non-secret env allowlist only. Codex has
    no repo-side config file of its own here (~/.codex/config.toml is the user's); every
    setting zbench drives is passed per-run as `-c` overrides built from this env."""
    env = (agent.get("env") or {})
    out = {"kind": "codex", "available": True,
           "codex_env": {k: env[k] for k in _CODEX_ENV_ALLOW if k in env},
           "note": "CODEX_API_KEY is a secret and is never snapshotted."}
    out["sha256"] = _sha(out.get("codex_env"))
    return out


def tooling_config_provenance(cli_name, agent: dict) -> dict:
    if cli_name == "pi":
        return pi_config_provenance(agent)
    if cli_name == "claude":
        return claude_config_provenance(agent)
    if cli_name == "codex":
        return codex_config_provenance(agent)
    return {"kind": cli_name, "available": False, "sha256": None}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: float = 5.0) -> dict:
    """Run a small provenance command and return a JSON-serializable result."""
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout)
        return {
            "command": cmd,
            "returncode": r.returncode,
            "stdout": (r.stdout or "").strip(),
            "stderr": (r.stderr or "").strip(),
            "ok": r.returncode == 0,
        }
    except Exception as exc:
        return {"command": cmd, "ok": False, "error": repr(exc)}


def _git_root(start: Path) -> Path | None:
    r = _run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if r.get("ok") and r.get("stdout"):
        return Path(str(r["stdout"]))
    return None


def git_provenance(start: Path | None = None) -> dict:
    """Best-effort git identity + dirty state for the harness checkout."""
    start = start or Path(__file__).resolve()
    root = _git_root(start)
    if root is None:
        return {"available": False, "start": str(start)}

    head = _run(["git", "rev-parse", "HEAD"], cwd=root)
    branch = _run(["git", "branch", "--show-current"], cwd=root)
    status = _run(["git", "status", "--porcelain=v1"], cwd=root)
    diff = _run(["git", "diff", "--binary"], cwd=root, timeout=10.0)
    diff_text = diff.get("stdout") if diff.get("ok") else ""
    status_text = status.get("stdout") if status.get("ok") else ""
    dirty = bool(status_text)

    out = {
        "available": True,
        "root": str(root),
        "commit": head.get("stdout") if head.get("ok") else None,
        "branch": branch.get("stdout") if branch.get("ok") else None,
        "dirty": dirty,
        "status_porcelain": status_text,
    }
    if diff_text:
        out["diff_sha256"] = hashlib.sha256(str(diff_text).encode("utf-8")).hexdigest()
        out["diff_bytes"] = len(str(diff_text).encode("utf-8"))
    elif dirty:
        # Untracked-only dirty trees have no `git diff` content but still matter.
        out["diff_sha256"] = None
        out["diff_bytes"] = 0
    return out


def _cli_version_for_agent(agent: dict) -> tuple[str | None, dict | None]:
    command = agent.get("command") or ""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    command_text = " ".join(parts)
    if "pi_agent" in command_text:
        return "pi", _run(["pi", "--version"])
    if "claude_agent" in command_text:
        return "claude", _run(["claude", "--version"])
    if "codex_agent" in command_text:
        return "codex", _run(["codex", "--version"])
    return None, None


def collect_attempt_provenance(agent: dict) -> dict:
    """Collect run-time provenance for one attempt/cell.

    The returned shape is intentionally nested and extensible; store.py projects the
    commonly queried columns into `attempt_provenance` and also persists the full JSON
    into the attempt evidence bundle.
    """
    cli_name, cli_version = _cli_version_for_agent(agent)
    return {
        "schema_version": 2,
        "captured_at": utc_now(),
        "harness": {
            "name": "zbench",
            "git": git_provenance(Path(__file__).resolve()),
            "python_version": sys.version.replace("\n", " "),
            "platform": platform.platform(),
        },
        "agent": {
            "agent_id": agent.get("agent_id"),
            "command": agent.get("command"),
            "timeout_sec": agent.get("timeout_sec"),
            "env_keys": sorted((agent.get("env") or {}).keys()),
            "cli": {"name": cli_name, "version_probe": cli_version},
            # F6: the REDACTED pi/claude config that drives behavior + its sha256.
            "config": tooling_config_provenance(cli_name, agent),
        },
    }


def flatten_for_db(prov: dict) -> dict:
    """Project provenance JSON to the stable attempt_provenance columns."""
    harness = prov.get("harness") if isinstance(prov, dict) else {}
    git = harness.get("git") if isinstance(harness, dict) else {}
    agent = prov.get("agent") if isinstance(prov, dict) else {}
    cli = agent.get("cli") if isinstance(agent, dict) else {}
    probe = cli.get("version_probe") if isinstance(cli, dict) else {}
    version = None
    if isinstance(probe, dict) and probe.get("ok"):
        version = (probe.get("stdout") or probe.get("stderr") or "").strip() or None
    config = agent.get("config") if isinstance(agent, dict) else None
    # F6: project the REDACTED (secret-safe) config itself, not just a hash -- directly
    # inspectable/queryable; GROUP BY it for equality. It carries its own `sha256` field.
    sanitized_config = json.dumps(config, sort_keys=True) if isinstance(config, dict) else None
    return {
        "captured_at": prov.get("captured_at") or utc_now(),
        "harness_name": harness.get("name") if isinstance(harness, dict) else None,
        "harness_git_commit": git.get("commit") if isinstance(git, dict) else None,
        "harness_git_branch": git.get("branch") if isinstance(git, dict) else None,
        "harness_git_dirty": (1 if git.get("dirty") else 0) if isinstance(git, dict) and git.get("dirty") is not None else None,
        "harness_git_status": git.get("status_porcelain") if isinstance(git, dict) else None,
        "harness_git_diff_sha256": git.get("diff_sha256") if isinstance(git, dict) else None,
        "python_version": harness.get("python_version") if isinstance(harness, dict) else None,
        "platform": harness.get("platform") if isinstance(harness, dict) else None,
        "agent_cli_name": cli.get("name") if isinstance(cli, dict) else None,
        "agent_cli_version": version,
        "agent_command": agent.get("command") if isinstance(agent, dict) else None,
        "sanitized_config": sanitized_config,
        "data_json": json.dumps(prov, sort_keys=True),
    }
