#!/usr/bin/env python3
"""Show the final patch, verify log, and transcript path for one attempt.

An attempt is one (agent, task, run) cell. The DB (bench-db/bench.db) stores the
score and metrics; the patch and the raw model logs live on disk. The canonical
landed store is bench-db/blobs/attempt/<evaluation_id>/, which holds:
    patch.diff        the model's final patch (unified diff)
    pb-verify.log     the verification run (why the hidden test passed/failed)
    session.jsonl     the full pi transcript   (pi/vllm harnesses)
    rawcli.txt        the full claude/codex transcript
    agent_io.json     the raw agent stdout/stderr and command
    provenance.json   harness + git provenance
In-flight cells that have not landed yet live under bench-db/.runtime/cells/;
this tool falls back to that staging dir when no blob bundle exists.

Usage:
    show_attempt.py --eval <evaluation_id>
    show_attempt.py <config_id> <task_id> [run_id]
    show_attempt.py --agent <config_id> --task <task_id> [--run <run_id>]

Options:
    --patch-only   Print only the unified diff (for piping into `git apply`).
    --verify       Also print the pb-verify.log (the test result).
    --log          Also print the full raw model transcript (large).
    --json         Emit a JSON object with all paths + patch text.

The module also exposes db_attempt(), attempt_dir(), resolve_attempt(),
read_patch(), raw_log_path(), and verify_log_path() for reuse by other tools.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sqlite3
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(REPO_ROOT, "bench-db", "bench.db")
BLOBS_ROOT = os.path.join(REPO_ROOT, "bench-db", "blobs", "attempt")
CELLS_ROOT = os.path.join(REPO_ROOT, "bench-db", ".runtime", "cells")

_ATTEMPT_COLS = (
    "evaluation_id, run_id, config_id, task_id, tests_passed, status, outcome, "
    "cost_usd, finished_at, runtime_ms, input_tokens, output_tokens, "
    "total_tokens, turns")


def _norm_task(task_id: str) -> str:
    """Return the bare ZT-<sha> form (strip a leading zbench_ if present)."""
    t = task_id.strip()
    if t.startswith("zbench_"):
        t = t[len("zbench_"):]
    return t


def db_attempt(evaluation_id: str | None = None,
               config_id: str | None = None,
               task_id: str | None = None,
               run_id: str | None = None) -> dict | None:
    """Look up one attempt row by evaluation_id, or by (config,task[,run]).

    With no run_id and more than one match, the most recent by finished_at wins.
    Returns a dict of the row, or None.
    """
    if not os.path.exists(DB_PATH):
        return None
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if evaluation_id:
            row = con.execute(
                f"SELECT {_ATTEMPT_COLS} FROM attempt WHERE evaluation_id=?",
                (evaluation_id,)).fetchone()
            return dict(row) if row else None
        where, params = ["config_id=?", "task_id=?"], [config_id, _norm_task(task_id or "")]
        if run_id:
            where.append("run_id=?")
            params.append(run_id)
        rows = con.execute(
            f"SELECT {_ATTEMPT_COLS} FROM attempt WHERE {' AND '.join(where)} "
            "ORDER BY finished_at DESC", params).fetchall()
        return dict(rows[0]) if rows else None
    finally:
        con.close()


def attempt_dir(evaluation_id: str) -> str | None:
    """Return the canonical blob bundle dir for an evaluation_id, or None."""
    d = os.path.join(BLOBS_ROOT, evaluation_id)
    return d if os.path.isdir(d) else None


def _cells_dir(config_id: str, task_id: str, run_id: str | None) -> str | None:
    """Fall back to the in-flight staging dir under .runtime/cells/."""
    task = _norm_task(task_id)
    run = run_id if run_id else "*"
    matches = sorted(glob.glob(
        os.path.join(CELLS_ROOT, f"{config_id}__zbench_{task}__{run}__*")))
    return matches[-1] if matches else None


def resolve_attempt(evaluation_id: str | None = None,
                    config_id: str | None = None,
                    task_id: str | None = None,
                    run_id: str | None = None) -> tuple[dict | None, str | None, str]:
    """Resolve an attempt to (db_row, dir, source).

    source is 'blob' (landed bundle), 'cells' (in-flight staging), or 'none'.
    """
    row = db_attempt(evaluation_id, config_id, task_id, run_id)
    ev = (row or {}).get("evaluation_id") or evaluation_id
    if ev:
        d = attempt_dir(ev)
        if d:
            return row, d, "blob"
    cfg = (row or {}).get("config_id") or config_id
    task = (row or {}).get("task_id") or task_id
    run = (row or {}).get("run_id") or run_id
    if cfg and task:
        d = _cells_dir(cfg, task, run)
        if d:
            return row, d, "cells"
    return row, None, "none"


def read_patch(cell_dir: str) -> str:
    """Return the final patch text: patch.diff if present, else from agent_io.json."""
    pd = os.path.join(cell_dir, "patch.diff")
    if os.path.exists(pd):
        try:
            return open(pd).read()
        except OSError:
            pass
    f = os.path.join(cell_dir, "agent_io.json")
    if not os.path.exists(f):
        return ""
    try:
        j = json.load(open(f))
    except (ValueError, OSError):
        return ""
    so = j.get("stdout")
    if isinstance(so, str):
        try:
            so = json.loads(so)
        except ValueError:
            so = None
    patches = so.get("patches", []) if isinstance(so, dict) else []
    return patches[0].get("patch_text", "") if patches else ""


def _find(cell_dir: str, names: tuple[str, ...]) -> str | None:
    for name in names:
        p = os.path.join(cell_dir, name)
        if os.path.exists(p):
            return p
    return None


def raw_log_path(cell_dir: str) -> str | None:
    """Return the full model transcript path (session.jsonl or rawcli.txt)."""
    return _find(cell_dir, ("session.jsonl", "rawcli.txt"))


def verify_log_path(cell_dir: str) -> str | None:
    """Return the verification log path (pb-verify.log)."""
    return _find(cell_dir, ("pb-verify.log",))


def _resolve_args(args) -> tuple[str | None, str | None, str | None, str | None]:
    """Turn CLI args into (evaluation_id, config_id, task_id, run_id)."""
    if args.eval:
        return args.eval, None, None, None
    config = args.agent or args.config_pos
    task = args.task or args.task_pos
    run = args.run or args.run_pos
    if not (config and task):
        sys.exit("error: give --eval, or a config_id and task_id")
    return None, config, _norm_task(task), run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config_pos", nargs="?", help="config_id (agent)")
    ap.add_argument("task_pos", nargs="?", help="task_id (ZT-... or zbench_ZT-...)")
    ap.add_argument("run_pos", nargs="?", help="run_id (optional)")
    ap.add_argument("--eval", help="evaluation_id")
    ap.add_argument("--agent", "--config", dest="agent", help="config_id (agent)")
    ap.add_argument("--task", help="task_id")
    ap.add_argument("--run", help="run_id")
    ap.add_argument("--patch-only", action="store_true", help="print only the diff")
    ap.add_argument("--verify", action="store_true", help="also print pb-verify.log")
    ap.add_argument("--log", action="store_true", help="also print the raw transcript")
    ap.add_argument("--json", action="store_true", help="emit a JSON object")
    args = ap.parse_args()

    ev, config, task, run = _resolve_args(args)
    row, cell_dir, source = resolve_attempt(ev, config, task, run)
    if not cell_dir:
        who = ev or f"{config} / {task} / {run or '*'}"
        sys.exit(f"error: no landed bundle or cell dir for {who}")

    patch_text = read_patch(cell_dir)
    log_path = raw_log_path(cell_dir)
    vlog_path = verify_log_path(cell_dir)

    if args.patch_only:
        sys.stdout.write(patch_text)
        return

    if args.json:
        print(json.dumps({
            "config_id": (row or {}).get("config_id", config),
            "task_id": (row or {}).get("task_id", task),
            "run_id": (row or {}).get("run_id", run),
            "evaluation_id": (row or {}).get("evaluation_id", ev),
            "tests_passed": (row or {}).get("tests_passed"),
            "outcome": (row or {}).get("outcome"),
            "source": source,
            "dir": cell_dir,
            "patch_diff": os.path.join(cell_dir, "patch.diff"),
            "verify_log": vlog_path,
            "transcript": log_path,
            "n_chars_patch": len(patch_text),
            "patch_text": patch_text,
        }, indent=2))
        return

    def kv(k, v):
        print(f"  {k:<14} {v}")

    print("=" * 72)
    print(f"ATTEMPT  {(row or {}).get('config_id', config)}  x  {(row or {}).get('task_id', task)}")
    print("=" * 72)
    if row:
        resolved = "RESOLVED" if row["tests_passed"] else "FAILED"
        kv("result", f"{resolved}  (outcome={row['outcome']}, status={row['status']})")
        kv("run_id", row["run_id"])
        kv("evaluation_id", row["evaluation_id"])
        kv("cost_usd", row["cost_usd"])
        kv("tokens", f"in={row['input_tokens']} out={row['output_tokens']} "
                     f"total={row['total_tokens']} turns={row['turns']}")
    else:
        kv("result", "(no DB row — reading disk only)")
    kv("source", source)
    kv("bundle_dir", cell_dir)
    kv("verify_log", vlog_path or "(none)")
    kv("transcript", log_path or "(none)")
    print("-" * 72)
    if patch_text.strip():
        print(f"FINAL PATCH  ({len(patch_text)} chars)")
        print("-" * 72)
        print(patch_text)
    else:
        print("FINAL PATCH  (none — the agent produced no patch)")
    if args.verify and vlog_path:
        print("-" * 72)
        print(f"VERIFY LOG  {vlog_path}")
        print("-" * 72)
        with open(vlog_path) as fh:
            sys.stdout.write(fh.read())
    if args.log and log_path:
        print("-" * 72)
        print(f"RAW TRANSCRIPT  {log_path}")
        print("-" * 72)
        with open(log_path) as fh:
            sys.stdout.write(fh.read())


if __name__ == "__main__":
    main()
