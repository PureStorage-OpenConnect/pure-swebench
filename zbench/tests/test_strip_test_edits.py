#!/usr/bin/env python3
"""Test-blindness boundary tests: _strip_agent_test_edits with Zulip-shaped paths.

Run: python3 zbench/tests/test_strip_test_edits.py   (asserts; exit 0 = pass)
This is the security boundary of the whole benchmark: an agent edit to a test file,
a test helper, or a runner script that SURVIVES the strip is an exit-0 backdoor.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from zbench import workflow                      # noqa: E402


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _mk_zulip_shaped_repo() -> tuple[Path, str]:
    """A tiny repo with Zulip's layout: source, tests, test infra, runners."""
    repo = Path(tempfile.mkdtemp(prefix="zbench_strip_test_"))
    files = {
        "zerver/lib/actions.py": "def do_thing():\n    return 1\n",
        "zerver/tests/test_actions.py": "def test_thing():\n    assert True\n",
        "zerver/lib/test_classes.py": "class ZulipTestCase:\n    pass\n",
        "zerver/webhooks/foo/tests.py": "def test_hook():\n    assert True\n",
        "web/src/thing.ts": "export const x = 1;\n",
        "web/tests/thing.test.cjs": "assert.ok(true);\n",
        "tools/test-backend": "#!/bin/sh\necho real-runner\n",
        "tools/test-js-with-node": "#!/bin/sh\necho real-node-runner\n",
        "tools/ci/setup-backend": "#!/bin/sh\necho setup\n",
    }
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        if rel.startswith("tools/"):
            p.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, base


GOLD = """diff --git a/zerver/tests/test_actions.py b/zerver/tests/test_actions.py
--- a/zerver/tests/test_actions.py
+++ b/zerver/tests/test_actions.py
@@ -1,2 +1,3 @@
 def test_thing():
     assert True
+# gold marker
"""


def test_strip_reverts_test_and_runner_edits_keeps_source():
    repo, base = _mk_zulip_shaped_repo()
    # agent edits EVERYTHING: source (legit) + tests/helpers/runners (must revert)
    (repo / "zerver/lib/actions.py").write_text("def do_thing():\n    return 2\n")
    (repo / "web/src/thing.ts").write_text("export const x = 2;\n")
    (repo / "zerver/tests/test_actions.py").write_text("def test_thing():\n    assert 1 == 2\n")
    (repo / "zerver/lib/test_classes.py").write_text("class ZulipTestCase:\n    hacked = True\n")
    (repo / "zerver/webhooks/foo/tests.py").write_text("def test_hook():\n    pass  # gutted\n")
    (repo / "web/tests/thing.test.cjs").write_text("assert.ok(false);\n")
    (repo / "tools/test-backend").write_text("#!/bin/sh\nexit 0  # backdoor\n")
    (repo / "tools/test-js-with-node").write_text("#!/bin/sh\nexit 0\n")
    (repo / "tools/ci/setup-backend").write_text("#!/bin/sh\nexit 0\n")
    # agent also CREATES a new test file (must be deleted)
    newt = repo / "zerver/tests/test_planted.py"
    newt.write_text("def test_planted():\n    assert True\n")

    workflow._strip_agent_test_edits(repo, base, GOLD)

    # source edits survive
    assert "return 2" in (repo / "zerver/lib/actions.py").read_text()
    assert "x = 2" in (repo / "web/src/thing.ts").read_text()
    # every test/helper/runner edit is reverted to base
    assert "assert True" in (repo / "zerver/tests/test_actions.py").read_text()
    assert "hacked" not in (repo / "zerver/lib/test_classes.py").read_text()
    assert "gutted" not in (repo / "zerver/webhooks/foo/tests.py").read_text()
    assert "ok(true)" in (repo / "web/tests/thing.test.cjs").read_text()
    assert "backdoor" not in (repo / "tools/test-backend").read_text()
    assert "real-node-runner" in (repo / "tools/test-js-with-node").read_text()
    assert "echo setup" in (repo / "tools/ci/setup-backend").read_text()
    # planted test file is gone
    assert not newt.exists()


def test_strip_unlinks_agent_created_file_at_gold_path():
    repo, base = _mk_zulip_shaped_repo()
    gold_new = """diff --git a/zerver/tests/test_new_gold.py b/zerver/tests/test_new_gold.py
--- /dev/null
+++ b/zerver/tests/test_new_gold.py
@@ -0,0 +1,2 @@
+def test_gold():
+    assert True
"""
    # agent pre-creates a file exactly where the gold test will land
    planted = repo / "zerver/tests/test_new_gold.py"
    planted.write_text("def test_gold():\n    assert True  # poisoned lookalike\n")
    workflow._strip_agent_test_edits(repo, base, gold_new)
    assert not planted.exists(), "agent-created file at a gold path must be unlinked"


def test_runner_integrity_check_detects_tamper():
    repo, base = _mk_zulip_shaped_repo()
    (repo / "tools/test-backend").write_text("#!/bin/sh\nexit 0\n")
    tampered = workflow._runner_integrity_violations(repo, base)
    assert any("tools/test-backend" in t for t in tampered)
    workflow._strip_agent_test_edits(repo, base, GOLD)
    assert workflow._runner_integrity_violations(repo, base) == []


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"strip-test-edits: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
