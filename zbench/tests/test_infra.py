#!/usr/bin/env python3
"""zbench infra tests: flock slots + patch capture. No pb needed.
Run: python3 zbench/tests/test_infra.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from zbench import constants  # noqa: E402


def test_slots_acquire_release_status():
    os.environ["ZBENCH_SLOTS_DIR"] = tempfile.mkdtemp()
    os.environ["ZBENCH_SLOT_CAP_global"] = "2"
    from zbench.cells import slots
    assert slots.cap_for("global") == 2
    with slots.acquire(["global"], meta={"cell": constants.cell_key("ZT-1", "a")}):
        st = slots.status()["global"]
        assert st["held"] == 1 and st["free"] == 1
        assert constants.cell_key("ZT-1", "a") in slots.live_cell_keys()
    # released on exit
    assert slots.status()["global"]["held"] == 0
    assert slots.live_cell_keys() == set()


def test_slots_capacity_blocks():
    os.environ["ZBENCH_SLOTS_DIR"] = tempfile.mkdtemp()
    os.environ["ZBENCH_SLOT_CAP_heavy"] = "1"
    from zbench.cells import slots
    with slots.acquire(["heavy"]):
        # second acquire with wait=False must fail (cap 1, already held)
        try:
            with slots.acquire(["heavy"], wait=False):
                assert False, "should have hit CapacityError"
        except slots.CapacityError:
            pass


def test_patch_capture_recovers_committed_diff():
    from zbench.agents.patch_capture import capture_git_patch
    repo = Path(tempfile.mkdtemp())
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "f.txt").write_text("base\n")

    def agent():
        # agent EDITS then COMMITs (advances HEAD -> `git diff HEAD` would be empty)
        (repo / "f.txt").write_text("fixed\n")
        subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=a",
                        "-C", str(repo), "commit", "-am", "fix"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=a",
                        "-C", str(repo), "commit", "-am", "fix"], capture_output=True)
        return {"output_tokens": 5}

    patch, usage = capture_git_patch(repo, agent)
    assert "fixed" in patch and "-base" in patch, patch     # committed edit recovered
    assert usage == {"output_tokens": 5}
    assert (repo / "f.txt").read_text() == "base\n"          # workspace reset to baseline


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"infra: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
