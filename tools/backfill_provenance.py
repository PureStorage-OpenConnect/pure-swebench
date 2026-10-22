#!/usr/bin/env python3
"""Best-effort backfill for attempt_provenance.

This does NOT reconstruct exact historical CLI versions. It infers the harness git
commit from attempt timestamps + git history and records that as medium-confidence
provenance. Exact `pi --version` / `claude --version` is only captured for future runs
by zbench itself.

Usage:
  python3 tools/backfill_provenance.py --dry-run
  python3 tools/backfill_provenance.py --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "bench-db" / "bench.db"
SCHEMA = ROOT / "zbench" / "schema.sql"


def _run(cmd: list[str], *, cwd: Path, timeout: float = 10.0) -> str | None:
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip() if r.returncode == 0 else None
    except Exception:
        return None


def _commit_before(ts: str, pathspecs: list[str] | None = None) -> str | None:
    cmd = ["git", "log", "-1", f"--before={ts}", "--format=%H"]
    if pathspecs:
        cmd += ["--", *pathspecs]
    return _run(cmd, cwd=ROOT)


def _short(commit: str | None) -> str | None:
    return commit[:7] if commit else None


def _agent_command(bundle: Path) -> str | None:
    p = bundle / "agent_io.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text()).get("command")
    except Exception:
        return None


def _agent_cli_name(config_id: str, command: str | None) -> str | None:
    text = " ".join([config_id or "", command or ""])
    if "pi" in text and "claude-cli" not in config_id:
        return "pi"
    if "claude" in text:
        return "claude"
    return None


def _infer_harness(finished_at: str, command: str | None) -> tuple[str, str | None, str | None, str]:
    # zbench-era rows: infer the harness git commit from this repo's history.
    if (command and "zbench" in command) or finished_at >= "2026-08-04T06:00:00":
        commit = _commit_before(finished_at, ["zbench", "tools/benchdb_reader.py", "zbench-tasks/run_coverage_matrix.py"])
        return "zbench", commit, "main", "command" if command and "zbench" in command else "timestamp_cutover"
    # Pre-cutover rows were imported from the retired fork; its exact commit is not
    # reconstructable from current (decoupled) state and we intentionally do not read
    # old locations.
    return "pre-zbench", None, None, "historical_import"


def _prov(eid: str, run_id: str, config_id: str, task_id: str, finished_at: str) -> dict:
    bundle = ROOT / "bench-db" / "blobs" / "attempt" / eid
    command = _agent_command(bundle)
    hname, commit, branch, inferred_by = _infer_harness(finished_at, command)
    cli_name = _agent_cli_name(config_id, command)
    return {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "harness": {
            "name": hname,
            "git": {
                "available": bool(commit),
                "root": str(ROOT) if commit else None,
                "commit": commit,
                "branch": branch,
                # Unknown historically: do not pretend to know dirty state.
                "dirty": None,
                "status_porcelain": None,
            },
            "python_version": None,
            "platform": None,
        },
        "agent": {
            "agent_id": config_id,
            "command": command,
            "cli": {"name": cli_name, "version_probe": None},
        },
        "backfill": {
            "source": "tools/backfill_provenance.py",
            "confidence": "medium" if commit else "low",
            "inferred_by": inferred_by,
            "attempt_finished_at": finished_at,
            "run_id": run_id,
            "task_id": task_id,
            "notes": "Historical CLI versions and dirty-tree state were not captured and are not recoverable from current evidence.",
        },
    }


def _flatten(prov: dict) -> dict:
    from zbench.provenance import flatten_for_db
    return flatten_for_db(prov)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write attempt_provenance rows")
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text())
    rows = con.execute(
        """SELECT a.evaluation_id, a.run_id, a.config_id, a.task_id, a.finished_at
             FROM attempt a
             LEFT JOIN attempt_provenance p USING(evaluation_id)
            WHERE p.evaluation_id IS NULL
            ORDER BY a.finished_at"""
    ).fetchall()
    if args.limit:
        rows = rows[:args.limit]

    out = []
    for eid, run_id, config_id, task_id, finished_at in rows:
        prov = _prov(eid, run_id, config_id, task_id, finished_at)
        flat = _flatten(prov)
        flat["evaluation_id"] = eid
        out.append((flat, prov))

    by = {}
    for flat, _ in out:
        key = (flat.get("harness_name"), _short(flat.get("harness_git_commit")), flat.get("agent_cli_name"))
        by[key] = by.get(key, 0) + 1
    print(f"missing provenance rows: {len(rows)}")
    for key, n in sorted(by.items(), key=lambda kv: (str(kv[0]), kv[1])):
        print(f"  {key}: {n}")

    if not args.apply:
        print("dry-run only; pass --apply to write")
        return 0

    backup = DB.with_suffix(DB.suffix + ".bak-provenance-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(DB, backup)
    cols = ["evaluation_id", "captured_at", "harness_name", "harness_git_commit",
            "harness_git_branch", "harness_git_dirty", "harness_git_status",
            "harness_git_diff_sha256", "python_version", "platform", "agent_cli_name",
            "agent_cli_version", "agent_command", "data_json"]
    ph = ",".join(f":{c}" for c in cols)
    upd = ",".join(f"{c}=excluded.{c}" for c in cols if c != "evaluation_id")
    with con:
        for flat, _prov_json in out:
            con.execute(
                f"INSERT INTO attempt_provenance({','.join(cols)}) VALUES({ph}) "
                f"ON CONFLICT(evaluation_id) DO UPDATE SET {upd}", flat)
    print(f"wrote {len(out)} rows; backup: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
