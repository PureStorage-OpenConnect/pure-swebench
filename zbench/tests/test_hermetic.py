#!/usr/bin/env python3
"""Regression tests for hermetic adapter setup (old-harness parity).

Run: python3 zbench/tests/test_hermetic.py   (asserts; exit 0 = pass)
Self-running like the rest of the suite -- no pytest fixtures. Each test saves and
restores the env keys it touches so the suite stays order-independent.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_KEYS = ("ZBENCH_HERMETIC", "ZBENCH_CELL_ID", "ZBENCH_RUN_ID", "CLAUDE_CONFIG_DIR")


def _snapshot() -> dict:
    return {k: os.environ.get(k) for k in _KEYS}


def _restore(snap: dict) -> None:
    for k, v in snap.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_claude_hermetic_env_sets_isolated_config():
    from zbench import hermetic

    snap = _snapshot()
    try:
        os.environ["ZBENCH_HERMETIC"] = "1"
        os.environ["ZBENCH_CELL_ID"] = "cell-for-test"
        os.environ.pop("CLAUDE_CONFIG_DIR", None)

        cfg = hermetic.ensure_claude_hermetic_env()
        assert cfg
        assert os.environ["CLAUDE_CONFIG_DIR"] == cfg
        p = Path(cfg)
        assert p.name == "cell-for-test"
        assert "zbench_hermetic" in str(p)
        assert p.is_dir()
    finally:
        _restore(snap)


def test_claude_hermetic_env_optout():
    from zbench import hermetic

    snap = _snapshot()
    try:
        os.environ["ZBENCH_HERMETIC"] = "0"
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        assert hermetic.ensure_claude_hermetic_env() is None
        assert "CLAUDE_CONFIG_DIR" not in os.environ
    finally:
        _restore(snap)


def test_bucket_falls_back_to_run_id_then_adhoc():
    from zbench import hermetic

    snap = _snapshot()
    try:
        os.environ["ZBENCH_HERMETIC"] = "1"
        os.environ.pop("ZBENCH_CELL_ID", None)
        os.environ["ZBENCH_RUN_ID"] = "run-bucket-test"
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        cfg = hermetic.ensure_claude_hermetic_env()
        assert cfg and Path(cfg).name == "run-bucket-test"

        os.environ.pop("ZBENCH_RUN_ID", None)
        os.environ.pop("CLAUDE_CONFIG_DIR", None)
        cfg = hermetic.ensure_claude_hermetic_env()
        assert cfg and Path(cfg).name == "adhoc"
    finally:
        _restore(snap)


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"hermetic: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
