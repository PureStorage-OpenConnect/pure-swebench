#!/usr/bin/env python3
"""zbench workflow test: a FULL test-blind attempt end-to-end, NO pb / NO model.

Uses a tiny local git 'base repo', a stub adapter (real capture_git_patch), an inline
gold_test, and a local shell verify command -- exercising the entire verify/score core
(isolated checkout -> agent -> apply patch -> strip test edits -> gold_test -> verify ->
classify -> store.record_attempt) that otherwise needs pb. Run: python3 .../test_workflow.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

GOLD = ("diff --git a/test_marker b/test_marker\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/test_marker\n@@ -0,0 +1 @@\n+marker\n")


def _base_repo() -> tuple[Path, str]:
    repo = Path(tempfile.mkdtemp())
    g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    g("config", "user.email", "t@t"); g("config", "user.name", "t")
    (repo / "f.txt").write_text("BUG\n")
    g("add", "-A"); g("commit", "-q", "-m", "base")
    return repo, g("rev-parse", "HEAD").stdout.strip()


def _stub(fix: bool) -> Path:
    """A stub adapter: edits f.txt via the real capture_git_patch, emits the diff."""
    val = "FIXED" if fix else "STILL-BUG"
    p = Path(tempfile.mkdtemp()) / "stub.py"
    p.write_text(
        "import sys; sys.path.insert(0, %r)\n"
        "from zbench.agents.patch_capture import capture_git_patch\n"
        "from zbench.agents.base_agent import emit_agent_output, read_agent_input\n"
        "d = read_agent_input(); wt = d['repo_root']\n"
        "def run():\n"
        "    open(wt + '/f.txt', 'w').write(%r + '\\n'); return {'output_tokens': 3}\n"
        "patch, usage = capture_git_patch(wt, run)\n"
        "emit_agent_output(d['instance_id'], 'stub', [patch], **usage)\n" % (str(ROOT), val))
    return p


def _run(fix: bool, tests: list | None = None) -> dict:
    env_dir = tempfile.mkdtemp()
    os.environ["ZBENCH_BENCHDB_DIR"] = env_dir + "/bench-db"
    os.environ["ZBENCH_DATA_DIR"] = env_dir + "/data"
    os.environ["ZBENCH_SLOTS_DIR"] = env_dir + "/slots"
    os.environ["ZBENCH_WORKTREE_DIR"] = env_dir + "/wt"
    import importlib
    import zbench.store as store; importlib.reload(store)
    import zbench.workflow as workflow; importlib.reload(workflow)
    repo, commit = _base_repo()
    agent = {"agent_id": "stub", "command": f"{sys.executable} {_stub(fix)}", "env": {"PI_PROVIDER": "azure-foundry"}, "timeout_sec": 60}
    instance = {"instance_id": "zbench_ZT-TEST", "repo": "x", "commit": commit,
                "problem_statement": "make f.txt say FIXED",
                "metadata": {"language": "py", "task_type": "zbench/patch", "gold_test_patch": GOLD,
                             "commands": {"build": [], "tests": tests or ["grep -q FIXED f.txt"]},
                             "verify_timeout_sec": 60}}
    return workflow.run_patch_task_attempt(agent, instance, {"run_id": "r1", "evaluation_id": None}, repo)


def test_verify_env_exposes_zbench_scripts():
    """The $ZBENCH_SCRIPTS / $ZBENCH_WORKTREE injection contract: commands.tests strings
    reference corpus scripts portably, never via absolute authoring-machine paths."""
    scripts = Path(tempfile.mkdtemp(prefix="zbench_scripts_"))
    (scripts / "echo_ok.sh").write_text("#!/bin/sh\ntest -d \"$ZBENCH_WORKTREE\" && grep -q FIXED \"$ZBENCH_WORKTREE/f.txt\"\n")
    os.environ["ZBENCH_SCRIPTS"] = str(scripts)
    try:
        score = _run(fix=True, tests=['bash "$ZBENCH_SCRIPTS/echo_ok.sh"'])
        assert score["tests_passed"] is True and score["status"] == "ok", score
    finally:
        del os.environ["ZBENCH_SCRIPTS"]


def test_full_attempt_resolves_when_fixed():
    score = _run(fix=True)
    assert score["tests_passed"] is True and score["status"] == "ok", score
    # the attempt fact + evidence landed in the store
    import sqlite3
    db = os.environ["ZBENCH_BENCHDB_DIR"] + "/bench.db"
    row = sqlite3.connect(db).execute("SELECT tests_passed, outcome, output_tokens FROM attempt").fetchone()
    assert row == (1, "completed", 3), row
    bp = Path(os.environ["ZBENCH_BENCHDB_DIR"]) / "blobs" / "attempt"
    assert any((d / "pb-verify.log").exists() for d in bp.iterdir()), "verify-log evidence written"


def test_full_attempt_misses_when_not_fixed():
    score = _run(fix=False)
    assert score["tests_passed"] is False and score["status"] == "tests_failed", score


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn(); print(f"  [PASS] {fn.__name__}")
    print("workflow: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
