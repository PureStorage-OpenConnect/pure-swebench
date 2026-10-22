"""Hermetic-run helpers (ported from the fork): claude isolation + flags.

Keeps each cell's claude run ambient-free (isolated CLAUDE_CONFIG_DIR seeded with only
credentials; skills/subagents/MCP/user-memory from the real ~/.claude are absent).
Best-effort: any failure leaves the environment untouched (the agent still runs, native).
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_FALSEY = {"0", "false", "no", "off"}


def is_hermetic() -> bool:
    """True unless ZBENCH_HERMETIC is explicitly set to a falsey value."""
    return os.environ.get("ZBENCH_HERMETIC", "1").strip().lower() not in _FALSEY


def claude_hermetic_flags() -> list[str]:
    """CLI flags for a minimal, ambient-free claude run (auth-safe).
    (--bare is intentionally NOT used; it breaks auth in this CLI build.)"""
    return [
        "--disable-slash-commands",           # disable all skills
        "--no-session-persistence",           # no session reuse across attempts
        "--exclude-dynamic-system-prompt-sections",  # drop per-machine sections
    ]


def ensure_claude_hermetic_env() -> str | None:
    """Point CLAUDE_CONFIG_DIR at an isolated dir seeded with only credentials. Returns
    the config dir path, or None when hermetic mode is off."""
    if not is_hermetic():
        return None
    try:
        # Isolated PER CELL (ZBENCH_CELL_ID) so concurrent claude cells never share a
        # CLAUDE_CONFIG_DIR; fall back to the run bucket, then "adhoc".
        bucket = (os.environ.get("ZBENCH_CELL_ID")
                  or os.environ.get("ZBENCH_RUN_ID") or "adhoc")
        cfg = Path(tempfile.gettempdir()) / "zbench_hermetic" / "claude" / bucket
        cfg.mkdir(parents=True, exist_ok=True)
        src = Path.home() / ".claude" / ".credentials.json"
        if src.exists():
            shutil.copy2(src, cfg / ".credentials.json")
        else:
            logger.warning("hermetic: no ~/.claude/.credentials.json to seed; auth may fail")
        # Rows that set CLAUDE_BIN (a custom claude-compatible wrapper) may need the user's
        # settings.json (hooks / model-slot routing) in the isolated config dir. Gated on
        # CLAUDE_BIN so the default `claude` rows stay ambient-free.
        if os.environ.get("CLAUDE_BIN"):
            settings_src = Path.home() / ".claude" / "settings.json"
            if settings_src.exists():
                shutil.copy2(settings_src, cfg / "settings.json")
        os.environ["CLAUDE_CONFIG_DIR"] = str(cfg)
        return str(cfg)
    except Exception as exc:
        logger.warning("hermetic: failed to set up isolated claude config: %s", exc)
        return None
