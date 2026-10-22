"""zbench filesystem paths.

W116 evidence layout: every new cell gets a per-cell staging dir under
`data_dir()/cells/<agent>__<instance>__<run>__<timestamp>/`. The agent cwd remains the
isolated worktree; the parent hands the child absolute paths under this dir
(`session.jsonl`, `rawcli.txt`) and the store copies the cell dir into the terminal attempt
bundle at `bench-db/blobs/attempt/<evaluation_id>/` when the attempt lands.

data_dir = ZBENCH_DATA_DIR override, else `<bench-db>/.runtime`. Production launchers
set ZBENCH_DATA_DIR explicitly; the default keeps all transient staging under bench-db
and independent of the launch cwd. Legacy readers still understand old `io_logs/<run>/`
names within that root.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def safe(value) -> str:
    return _SANITIZE.sub("_", str(value))[:120]


def data_dir() -> Path:
    d = os.environ.get("ZBENCH_DATA_DIR")
    if d:
        return Path(d).expanduser()
    from .store import benchdb_dir
    return benchdb_dir() / ".runtime"


def io_logs_dir(bucket: str) -> Path:
    """Legacy run-bucket staging dir (grandfathered for old data/tools)."""
    d = data_dir() / "io_logs" / safe(bucket)
    d.mkdir(parents=True, exist_ok=True)
    return d


def cell_dir(*, agent_id: str, instance_id: str, run_id: str, stamp: str) -> Path:
    """Persistent per-cell evidence dir: {data_dir}/cells/{agent}_{task}_{run}_{time}."""
    d = data_dir() / "cells" / f"{safe(agent_id)}__{safe(instance_id)}__{safe(run_id)}__{safe(stamp)}"
    d.mkdir(parents=True, exist_ok=True)
    return d
