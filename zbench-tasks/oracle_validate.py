#!/usr/bin/env python3
"""Oracle validation for a zbench task: the flip invariant, flake-gated.

A task is VALID iff, in the fingerprint-matched env image:
  arm A (base + gold_test):             fail_to_pass FAILS (x FAIL_RUNS, same
                                        failure signature) and pass_to_pass PASSES
  arm B (base + gold_test + gold_code): fail_to_pass PASSES (x PASS_RUNS) and
                                        pass_to_pass PASSES

Exit codes: 0 VALID | 1 INVALID (no flip) | 2 INVALID (passes at base)
          | 3 UNENUMERABLE (target could not run -- NEVER read as a flip)
          | 70 script error | 75 infra error.

The worktree is a STANDALONE isolated checkout (zbench.workflow._make_isolated_
checkout), not `git worktree add`: a linked worktree's .git is a pointer file to a
host path that does not exist inside the verify container.

Usage: oracle_validate.py --task-dir DIR [--repo P] [--fast] [--keep] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import config                                        # noqa: E402  (arm B: config.gold_code_path)
from config import ZULIP_REPO                       # noqa: E402
from verdict import strip_ansi, verdict             # noqa: E402
from zbench.workflow import _make_isolated_checkout  # noqa: E402

LOG_DIR = Path("/tmp/zbench_runs")
_RESULT_RE = re.compile(r"^(?:FAIL|ERROR): (\S+)", re.M)


class Infra(Exception):
    pass


def _run_verify(wt: Path, mode: str, targets: list[str], log_path: Path) -> tuple[str, int, str]:
    """One containerized verify. Returns (verdict, rc, log_text)."""
    cmd = ["bash", str(HERE / "scripts" / "zbench_verify.sh"),
           "backend" if mode == "py" else "node", *targets]
    env = {**os.environ, "ZBENCH_SCRIPTS": str(HERE / "scripts")}
    r = subprocess.run(cmd, cwd=str(wt), capture_output=True, text=True,
                       timeout=1800, env=env)
    text = (r.stdout or "") + "\n" + (r.stderr or "")
    log_path.write_text(text)
    v = verdict(text, r.returncode, "backend" if mode == "py" else "node", targets)
    return v, r.returncode, text


def _fail_signature(text: str) -> tuple:
    """The set of failing test names -- two runs 'fail the same way' iff equal."""
    return tuple(sorted(set(_RESULT_RE.findall(strip_ansi(text)))))


def _apply(wt: Path, patch_file: Path) -> None:
    r = subprocess.run(["git", "-C", str(wt), "apply", "--verbose", str(patch_file)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git apply {patch_file.name} failed: {r.stderr[:400]}")


def validate(task_dir: Path, repo: Path, fail_runs: int, pass_runs: int,
             keep: bool = False) -> dict:
    task_dir = Path(task_dir).resolve()   # git -C <wt> apply resolves paths inside wt
    meta = json.loads((task_dir / "meta.json").read_text())
    task_id = meta["task_id"]
    lang = meta["lang"]
    f2p = meta.get("fail_to_pass") or []
    p2p = meta.get("pass_to_pass") or []
    if isinstance(f2p, str):
        f2p = [f2p]
    if not f2p:
        return {"verdict": "UNENUMERABLE", "why": "no fail_to_pass targets"}
    base = meta["base_commit"]
    LOG_DIR.mkdir(exist_ok=True)

    # env image (idempotent; slow only on first build for a fingerprint)
    b = subprocess.run(["bash", str(HERE / "scripts" / "build_env_image.sh"), base,
                        "--repo", str(repo)], capture_output=True, text=True, timeout=3600)
    if b.returncode != 0:
        raise Infra(f"build_env_image failed (rc={b.returncode}): {b.stdout[-300:]} {b.stderr[-300:]}")

    wt = _make_isolated_checkout(Path(repo), base, f"oracle_{task_id}")
    result: dict = {"task_id": task_id, "arms": {}}
    try:
        # ---- arm A: base + gold_test ----
        _apply(wt, task_dir / "gold_test.patch")
        sigs, arm_a = [], []
        for i in range(fail_runs):
            v, rc, text = _run_verify(wt, lang, f2p, LOG_DIR / f"{task_id}_A{i}.log")
            arm_a.append(v)
            sigs.append(_fail_signature(text))
            if v == "NOTRUN":
                result.update(verdict="UNENUMERABLE",
                              why=f"arm A run {i}: target could not run (see {task_id}_A{i}.log)")
                return result
            if v == "PASS":
                result.update(verdict="INVALID", code=2,
                              why=f"gold_test PASSES at base (arm A run {i}) -- no flip")
                return result
        if len(set(sigs)) > 1:
            result.update(verdict="UNENUMERABLE",
                          why=f"arm A failure signature unstable across {fail_runs} runs: {sigs}")
            return result
        result["arms"]["A_f2p"] = arm_a
        result["fail_signature"] = list(sigs[0])
        if p2p:
            v, rc, text = _run_verify(wt, lang, p2p, LOG_DIR / f"{task_id}_A_p2p.log")
            result["arms"]["A_p2p"] = [v]
            if v != "PASS":
                result.update(verdict="UNENUMERABLE" if v == "NOTRUN" else "INVALID", code=1,
                              why=f"pass_to_pass not green at base+gold_test ({v}) -- pre-red P2P")
                return result

        # ---- arm B: + gold_code ----
        _apply(wt, config.gold_code_path(task_dir))
        arm_b = []
        for i in range(pass_runs):
            v, rc, text = _run_verify(wt, lang, f2p, LOG_DIR / f"{task_id}_B{i}.log")
            arm_b.append(v)
            if v == "NOTRUN":
                result.update(verdict="UNENUMERABLE",
                              why=f"arm B run {i}: target could not run")
                return result
            if v != "PASS":
                result.update(verdict="INVALID", code=1,
                              why=f"gold fix does not make the test pass (arm B run {i}: {v})")
                return result
        result["arms"]["B_f2p"] = arm_b
        if p2p:
            v, rc, text = _run_verify(wt, lang, p2p, LOG_DIR / f"{task_id}_B_p2p.log")
            result["arms"]["B_p2p"] = [v]
            if v != "PASS":
                result.update(verdict="INVALID", code=1,
                              why=f"pass_to_pass regressed by gold fix ({v})")
                return result

        result.update(verdict="VALID",
                      flake_check={"fail_runs": fail_runs, "pass_runs": pass_runs,
                                   "signature_stable": True})
        return result
    finally:
        if not keep:
            shutil.rmtree(wt, ignore_errors=True)


_EXIT = {"VALID": 0, "INVALID": 1, "UNENUMERABLE": 3}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-dir", required=True)
    ap.add_argument("--repo", default=str(ZULIP_REPO))
    ap.add_argument("--fast", action="store_true", help="1 run per arm (development only)")
    ap.add_argument("--keep", action="store_true", help="keep the oracle worktree")
    ap.add_argument("--json", action="store_true", help="print the full result map")
    a = ap.parse_args()
    t0 = time.time()
    try:
        res = validate(Path(a.task_dir), Path(a.repo).expanduser(),
                       fail_runs=1 if a.fast else 2, pass_runs=1 if a.fast else 3,
                       keep=a.keep)
    except Infra as exc:
        print(f"ORACLE=INFRA {exc}", file=sys.stderr)
        return 75
    except Exception as exc:
        print(f"ORACLE=ERROR {exc}", file=sys.stderr)
        return 70
    res["elapsed_s"] = round(time.time() - t0, 1)
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"ORACLE={res['verdict']} {res.get('why', '')} ({res['elapsed_s']}s)")
    return _EXIT.get(res["verdict"], res.get("code", 1))


if __name__ == "__main__":
    raise SystemExit(main())
