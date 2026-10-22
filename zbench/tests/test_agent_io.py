#!/usr/bin/env python3
"""zbench agent<->parent IPC + io_logging tests (dict-based, no model needed).
Run: python3 zbench/tests/test_agent_io.py
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def test_adapter_emit_parse_roundtrip():
    """An adapter subprocess emits patch JSON on stdout; the parent parses it (the real
    IPC), raw CLI is persisted to io_logs."""
    env = {**os.environ, "ZBENCH_DATA_DIR": tempfile.mkdtemp(), "ZBENCH_RUN_ID": "r1"}
    stub = ("import sys; sys.path.insert(0, %r);"
            "from zbench.agents.base_agent import emit_agent_output, read_agent_input;"
            "d=read_agent_input();"
            "emit_agent_output(d['instance_id'],'pi',['--- a\\n+++ b'],"
            "input_tokens=100,output_tokens=50,cost_usd=0.01,_raw_cli_output='RAW')" % str(ROOT))
    r = subprocess.run([sys.executable, "-c", stub],
                       input=json.dumps({"instance_id": "zbench_ZT-1", "problem_statement": "p"}),
                       text=True, capture_output=True, env=env)
    out = json.loads(r.stdout)
    assert out["agent_id"] == "pi" and len(out["patches"]) == 1
    assert out["patches"][0]["patch_format"] == "unified_diff"
    assert out["token_usage"] == {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}
    raw = glob.glob(os.path.join(env["ZBENCH_DATA_DIR"], "io_logs", "r1", "*rawcli*.txt"))
    assert raw and open(raw[0]).read() == "RAW"


def test_raw_cli_prefers_stable_cell_dir_path():
    env = {**os.environ, "ZBENCH_DATA_DIR": tempfile.mkdtemp(), "ZBENCH_RUN_ID": "r1"}
    cell = Path(env["ZBENCH_DATA_DIR"]) / "cells" / "cell1"
    env["ZBENCH_CELL_DIR"] = str(cell)
    env["ZBENCH_RAWCLI_PATH"] = str(cell / "rawcli.txt")
    stub = ("import sys; sys.path.insert(0, %r);"
            "from zbench.agents.base_agent import emit_agent_output, read_agent_input;"
            "d=read_agent_input();"
            "emit_agent_output(d['instance_id'],'claude',['--- a\\n+++ b'],_raw_cli_output='RAW')" % str(ROOT))
    r = subprocess.run([sys.executable, "-c", stub],
                       input=json.dumps({"instance_id": "zbench_ZT-1", "problem_statement": "p"}),
                       text=True, capture_output=True, env=env)
    assert r.returncode == 0, r.stderr
    assert (cell / "rawcli.txt").read_text() == "RAW"
    assert not glob.glob(os.path.join(env["ZBENCH_DATA_DIR"], "io_logs", "r1", "*rawcli*.txt"))


def test_io_logging_dict_no_try():
    os.environ["ZBENCH_DATA_DIR"] = tempfile.mkdtemp()
    os.environ.pop("ZBENCH_CELL_DIR", None)
    from zbench import io_logging
    io_logging.log_agent_io(
        agent={"agent_id": "pi-x", "command": "c",
               "env": {"PI_MODEL": "claude-opus-4-8", "PI_PROVIDER": "azure-foundry"}},
        instance={"instance_id": "zbench_ZT-1", "metadata": {"task_type": "zbench/patch"}},
        agent_input={"x": 1}, returncode=0, stdout="o", stderr="", run_id="r1", generation_ms=1234)
    rec = glob.glob(os.path.join(os.environ["ZBENCH_DATA_DIR"], "io_logs", "r1", "pi-x__*.json"))
    d = json.load(open(rec[0]))
    assert d["model_name"] == "claude-opus-4-8" and d["provider"] == "azure-foundry"
    assert d["generation_ms"] == 1234 and "try_number" not in d


def test_io_logging_prefers_stable_cell_dir():
    os.environ["ZBENCH_DATA_DIR"] = tempfile.mkdtemp()
    cell = Path(os.environ["ZBENCH_DATA_DIR"]) / "cells" / "cell2"
    os.environ["ZBENCH_CELL_DIR"] = str(cell)
    from zbench import io_logging
    io_logging.log_agent_io(
        agent={"agent_id": "pi-x", "command": "c", "env": {"PI_MODEL": "m", "PI_PROVIDER": "p"}},
        instance={"instance_id": "zbench_ZT-1", "metadata": {}},
        agent_input={"x": 1}, returncode=0, stdout="o", stderr="", run_id="r1")
    assert (cell / "agent_io.json").is_file()
    d = json.load(open(cell / "agent_io.json"))
    assert d["agent_id"] == "pi-x" and d["instance_id"] == "zbench_ZT-1"


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"agent-io: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
