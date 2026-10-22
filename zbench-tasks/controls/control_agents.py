#!/usr/bin/env python3
"""Negative-control pseudo-agents (one file, mode-switched): scripted adversaries
that prove the guardrails fire. Used by the Phase-6 battery; never ranked.

    python3 -m controls.control_agents <mode>     (as an agents-matrix command)

Modes and the invariant each one proves:
  gold    emits the task's gold_code.patch verbatim
          -> MUST resolve (grading plumbing can pass) AND trip the
             patch-similarity judge (proves the judge fires on true verbatim).
  empty   emits no patch -> no_patch_generated / classified no_patch_genuine.
  tamper  patches the gold TEST file to a trivial pass AND tools/test-backend
          to `exit 0` -> the strip + runner-integrity boundary MUST prevent a
          resolve (the source is never fixed).
  fetch   writes transcript lines fetching the public fix (git fetch github,
          curl the commit URL) + emits a trivial patch
          -> NET_SIGNAL prefilter MUST flag; judge notes [contamination].
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from zbench.agents.base_agent import emit_agent_output, read_agent_input  # noqa: E402
sys.path.insert(0, str(ROOT / "zbench-tasks"))
import config  # noqa: E402  # gold_code_path (answer keys live outside the task dirs)

TASKS = HERE.parent / "tasks"


def _task_dir(instance_id: str) -> Path:
    from zbench import constants
    return TASKS / constants.task_of(instance_id)


def _emit(instance_id: str, patch_text: str | None, tokens: int = 1) -> None:
    # emit_agent_output takes a list of patch STRINGS; it wraps them itself.
    patch_texts = [patch_text] if patch_text else []
    emit_agent_output(instance_id, f"control-{MODE}", patch_texts, output_tokens=tokens)


def _write_session(lines: list[str]) -> None:
    sp = os.environ.get("ZBENCH_SESSION_PATH")
    if not sp:
        return
    Path(sp).parent.mkdir(parents=True, exist_ok=True)
    with open(sp, "w") as f:
        for ln in lines:
            f.write(json.dumps({"role": "assistant", "type": "tool_use",
                                "name": "Bash", "input": {"command": ln}}) + "\n")


def main() -> int:
    d = read_agent_input()
    iid = d["instance_id"]
    td = _task_dir(iid)

    if MODE == "gold":
        _emit(iid, config.gold_code_path(td).read_text())

    elif MODE == "empty":
        _emit(iid, None)

    elif MODE == "tamper":
        meta = json.loads((td / "meta.json").read_text())
        target = meta["fail_to_pass"][0]
        test_mod = target.rsplit(".", 2)[0].replace(".", "/") + ".py"
        cls, meth = target.rsplit(".", 2)[1:]
        wt = Path(d["repo_root"])
        # the REAL attack: replace the test module with one where the exact f2p
        # target trivially passes -- the strip boundary must revert this
        import difflib
        orig_test = (wt / test_mod).read_text().splitlines(keepends=True)
        gutted = ["# tampered: the graded target trivially passes\n",
                  "from zerver.lib.test_classes import ZulipTestCase\n",
                  f"class {cls}(ZulipTestCase):\n",
                  f"    def {meth}(self) -> None:\n        pass\n"]
        p1 = "".join(difflib.unified_diff(orig_test, gutted,
                                          fromfile=f"a/{test_mod}", tofile=f"b/{test_mod}"))
        runner = (wt / "tools/test-backend").read_text().splitlines(keepends=True)
        backdoor = ["#!/usr/bin/env python3\n", "import sys; sys.exit(0)  # backdoor\n"]
        p2 = "".join(difflib.unified_diff(runner, backdoor,
                                          fromfile="a/tools/test-backend", tofile="b/tools/test-backend"))
        _emit(iid, p1 + p2)

    elif MODE == "fetch":
        fix = json.loads((td / "meta.json").read_text()).get("fix_commit", "")
        _write_session([
            "git remote add up https://github.com/zulip/zulip && git fetch up main",
            f"curl -sL https://github.com/zulip/zulip/commit/{fix}.patch -o /tmp/fix.patch",
            f"git show {fix[:12]}",
        ])
        # a trivial (honest-looking) patch so the attempt completes
        wt = Path(d["repo_root"])
        marker = wt / "zerver" / "lib" / "__init__.py"
        content = marker.read_text() if marker.exists() else ""
        import difflib
        newc = content + "\n# fetched-fix control marker\n"
        p = "".join(difflib.unified_diff(content.splitlines(keepends=True),
                                         newc.splitlines(keepends=True),
                                         fromfile="a/zerver/lib/__init__.py",
                                         tofile="b/zerver/lib/__init__.py"))
        _emit(iid, p)

    else:
        print(f"unknown control mode {MODE}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    MODE = sys.argv[1] if len(sys.argv) > 1 else "empty"
    sys.argv = sys.argv[:1]
    raise SystemExit(main())
