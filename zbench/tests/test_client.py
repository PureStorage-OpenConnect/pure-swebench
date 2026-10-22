#!/usr/bin/env python3
"""zbench client test: invoke_agent spawns a STUB adapter (no model) and parses its
output -- the full parent<->adapter round-trip, dict-based. Run: python3 .../test_client.py
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


def _stub_adapter() -> Path:
    p = Path(tempfile.mkdtemp()) / "stub_adapter.py"
    p.write_text(
        "import sys; sys.path.insert(0, %r)\n"
        "import os\n"
        "from pathlib import Path\n"
        "from zbench.agents.base_agent import emit_agent_output, read_agent_input\n"
        "d = read_agent_input()\n"
        "assert 'REPOSITORY CONTEXT' in d['problem_statement']\n"      # parent augmented it
        "sess = Path(os.environ['ZBENCH_SESSION_PATH'])\n"
        "assert sess.is_absolute()\n"
        "assert str(sess).startswith(str(Path(os.environ['ZBENCH_DATA_DIR']).resolve()))\n"
        "assert Path.cwd() == Path(d['repo_root'])\n"                # child cwd is the worktree/repo
        "emit_agent_output(d['instance_id'], 'stub',\n"
        "  ['--- a/f.c\\n+++ b/f.c\\n@@ -1 +1 @@\\n-int x;\\n+int y;'],\n"
        "  input_tokens=200, output_tokens=80, cost_usd=0.02)\n" % str(ROOT))
    return p


def test_invoke_agent_roundtrip():
    os.environ["ZBENCH_DATA_DIR"] = tempfile.mkdtemp()
    cell_dir = Path(os.environ["ZBENCH_DATA_DIR"]) / "cells" / "stub-cell"
    os.environ["ZBENCH_CELL_DIR"] = str(cell_dir)
    from zbench.agents import client
    repo = Path(tempfile.mkdtemp()); subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f.c").write_text("int x;\n")
    agent = {"agent_id": "stub", "command": f"{sys.executable} {_stub_adapter()}",
             "env": {"PI_MODEL": "m", "PI_PROVIDER": "p"}, "timeout_sec": 60}
    instance = {"instance_id": "zbench_ZT-1", "repo": "r", "commit": "c",
                "problem_statement": "fix the bug",
                "metadata": {"languages": ["py"], "task_type": "development/patches"}}
    out = client.invoke_agent(agent, instance, repo, run_id="r1", evaluation_id="e1")
    assert out is not None
    assert len(out["patches"]) == 1 and "int y" in out["patches"][0]["patch_text"]
    assert out["token_usage"] == {"input_tokens": 200, "output_tokens": 80, "cost_usd": 0.02}
    assert out["_generation_ms"] >= 0
    rec = cell_dir / "agent_io.json"
    assert json.load(open(rec))["model_name"] == "m"


def test_failed_adapter_returns_none():
    from zbench.agents import client
    repo = Path(tempfile.mkdtemp()); subprocess.run(["git", "init", "-q", str(repo)], check=True)
    agent = {"agent_id": "boom", "command": f"{sys.executable} -c \"import sys;sys.exit(3)\"",
             "env": {}, "timeout_sec": 60}
    instance = {"instance_id": "zbench_ZT-1", "repo": "r", "commit": "c",
                "problem_statement": "x", "metadata": {}}
    assert client.invoke_agent(agent, instance, repo) is None      # nonzero rc -> None


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"client: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
