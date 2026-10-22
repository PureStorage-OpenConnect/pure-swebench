"""zbench store -- the bench.db writer + liveness Lease (facts-only, W19).

Much smaller than the fork's writer: there are NO dimension tables to upsert (model +
harness_config are gone -> the `agent` temp table), so a write is just ensure-run +
INSERT the attempt fact (via transform.attempt_row) + an event + drop the lease. The
attempt map is LEAN (transform emits only present keys), so the dynamic INSERT/ON-CONFLICT
naturally leaves absent columns untouched. bench.db is the ONLY store -> failures RAISE.

`Lease` stays a real type (behavior + lifecycle: open -> heartbeat -> close, reap-if-stale);
everything else is plain functions over dicts. try_number is gone everywhere (identity =
run_id, config_id, task_id).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import constants, provenance, transform

logger = logging.getLogger("zbench.store")
_SCHEMA = Path(__file__).resolve().parent / "schema.sql"
_DEFAULT_HOME = Path(__file__).resolve().parent.parent / "bench-db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def benchdb_dir() -> Path:
    """Resolve the bench-db/ root: ZBENCH_BENCHDB_DIR override (tests), else the
    docs-tree default (../bench-db)."""
    override = os.environ.get("ZBENCH_BENCHDB_DIR")
    return Path(override).expanduser() if override else _DEFAULT_HOME


# --------------------------------------------------------------------------- #
# liveness lease (the one surviving TYPE: it has a lifecycle, not just data)
# --------------------------------------------------------------------------- #
class Lease:
    """Filesystem liveness lease: heartbeat + TTL under .runtime/live/<run>/. The reader
    infers RUNNING (fresh) / STALE (age>TTL) / DONE (gone + attempt row) from these files.
    FS-only (works even if the DB is busy). Identity = (run_id, config_id, task_id) -- no try."""

    def __init__(self, run_id: str, config_id: str, task_id: str,
                 root: Path | None = None, ttl_s: int = 900):
        self.run_id, self.config_id, self.task_id, self.ttl_s = run_id, config_id, task_id, ttl_s
        base = (root or benchdb_dir()) / ".runtime" / "live" / str(run_id)
        safe = f"{config_id}__{task_id}".replace("/", "_")
        self.path = base / f"{safe}.json"

    def _write(self, phase: str, started_at: str | None) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"run_id": self.run_id, "config_id": self.config_id, "task_id": self.task_id,
                       "phase": phase, "ttl_s": self.ttl_s, "heartbeat_at": _utc_now()}
            if started_at:
                payload["started_at"] = started_at
            elif self.path.exists():
                try:
                    payload["started_at"] = json.loads(self.path.read_text()).get("started_at")
                except Exception:
                    pass
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload)); tmp.replace(self.path)
        except Exception as exc:  # best-effort
            logger.debug("lease write failed: %s", exc)

    def open(self, phase: str = "starting") -> "Lease":
        self._write(phase, started_at=_utc_now()); return self

    def heartbeat(self, phase: str) -> None:
        self._write(phase, started_at=None)

    def close(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception as exc:
            logger.debug("lease close failed: %s", exc)

    def __enter__(self) -> "Lease":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()


def _lease_age_s(payload: dict) -> float | None:
    ts = payload.get("heartbeat_at") or payload.get("started_at")
    if not ts:
        return None
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()
    except Exception:
        return None


def reap_stale_leases(live_cell_keys: set[str] | None = None, *, root: Path | None = None,
                      min_age_s: int = 2 * 3600) -> list[Path]:
    """Delete ZOMBIE liveness leases (hard-kill leftovers). Reaped iff its cell is NOT
    holding a slot (per live_cell_keys, e.g. 'zbench_ZT-abc_agent') AND its heartbeat is
    older than min_age_s. live_cell_keys=None -> age gate only. Cell key = no try."""
    base = (root or benchdb_dir()) / ".runtime" / "live"
    if not base.is_dir():
        return []
    reaped: list[Path] = []
    for run_dir in base.iterdir():
        if not run_dir.is_dir():
            continue
        for lf in run_dir.glob("*.json"):
            try:
                payload = json.loads(lf.read_text() or "{}")
            except Exception:
                payload = {}
            age = _lease_age_s(payload)
            if age is None or age <= min_age_s:
                continue
            if live_cell_keys is not None:
                task_id, cfg = payload.get("task_id"), payload.get("config_id")
                key = constants.cell_key(task_id, cfg) if task_id and cfg else None
                if key and key in live_cell_keys:
                    continue
            try:
                lf.unlink(); reaped.append(lf)
            except Exception as exc:
                logger.debug("lease reap failed for %s: %s", lf, exc)
        try:
            if not any(run_dir.iterdir()):
                run_dir.rmdir()
        except Exception:
            pass
    return reaped


# --------------------------------------------------------------------------- #
# the writer (plain object over a connection; no dims to manage)
# --------------------------------------------------------------------------- #
class Store:
    """Opens/creates bench.db (WAL) and writes facts. bench.db is the only store."""

    def __init__(self, db_path: Path | None = None, *, busy_timeout_ms: int = 30000):
        self.dir = benchdb_dir()
        self.db_path = Path(db_path) if db_path else (self.dir / "bench.db")
        self.blobs_dir = self.dir / "blobs" / "attempt"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=busy_timeout_ms / 1000.0)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA.read_text())
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Idempotent column adds for pre-existing DBs (schema.sql CREATE TABLE IF NOT EXISTS
        will not ALTER an existing table). Best-effort: never fail a run over provenance."""
        try:
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(attempt_provenance)")}
            if "sanitized_config" not in cols:   # F6
                self.conn.execute("ALTER TABLE attempt_provenance ADD COLUMN sanitized_config TEXT")
            if "pi_config_sha256" in cols:       # F6: drop the superseded hash-only column
                self.conn.execute("ALTER TABLE attempt_provenance DROP COLUMN pi_config_sha256")
        except Exception:
            pass
        try:
            acols = {r[1] for r in self.conn.execute("PRAGMA table_info(attempt)")}
            if "total_tokens" not in acols:      # canonical billed-token total
                self.conn.execute("ALTER TABLE attempt ADD COLUMN total_tokens INTEGER")
            if "turns" not in acols:             # agentic turns (model round-trips) per attempt
                self.conn.execute("ALTER TABLE attempt ADD COLUMN turns INTEGER")
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- run --------------------------------------------------------------- #
    def insert_run(self, run_id: str, *, label: str | None = None,
                   plan=None, started_at: str | None = None) -> str:
        plan_json = plan if plan is None or isinstance(plan, str) else json.dumps(plan)
        self.conn.execute(
            """INSERT INTO run(run_id, label, started_at, plan) VALUES(?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET label=COALESCE(excluded.label, run.label),
                   started_at=COALESCE(run.started_at, excluded.started_at),
                   plan=COALESCE(excluded.plan, run.plan)""",
            (run_id, label, started_at or _utc_now(), plan_json))
        return run_id

    def _ensure_run(self, run_id: str) -> None:
        if not self.conn.execute("SELECT 1 FROM run WHERE run_id=?", (run_id,)).fetchone():
            self.insert_run(run_id)

    # -- the fact ---------------------------------------------------------- #
    def record_attempt(self, score: dict, *, evaluation_id: str | None = None,
                       evidence: dict | None = None, lease: "Lease | None" = None,
                       provenance_data: dict | None = None) -> str:
        """INSERT one attempt fact (transform.attempt_row) + write evidence + provenance +
        drop the lease. Idempotent on evaluation_id. config_id/task_id are soft-refs (no dim
        upsert)."""
        row = transform.attempt_row(score, evaluation_id_=evaluation_id)
        eval_id = row["evaluation_id"]
        self._ensure_run(row["run_id"])
        if provenance_data:
            evidence = dict(evidence or {})
            extra = dict(evidence.get("extra") or {})
            extra.setdefault("provenance.json", json.dumps(provenance_data, indent=2, sort_keys=True))
            evidence["extra"] = extra
        if evidence:
            self.write_evidence(eval_id, **evidence)   # writes blobs; path is DERIVED, not stored
        cols = list(row)
        ph = ",".join(f":{k}" for k in cols)
        upd = ",".join(f"{k}=excluded.{k}" for k in cols if k != "evaluation_id")
        self.conn.execute(
            f"INSERT INTO attempt({','.join(cols)}) VALUES({ph}) "
            f"ON CONFLICT(evaluation_id) DO UPDATE SET {upd}", row)
        if provenance_data:
            self.record_provenance(eval_id, provenance_data, commit=False)
        self.record_event(row["run_id"], row["config_id"], row["task_id"], "attempt_recorded",
                          evaluation_id=eval_id, ts=row["finished_at"],
                          message=str(score.get("status") or ""),
                          data={"status": score.get("status"), "outcome": score.get("attempt_outcome"),
                                "tests_passed": bool(score.get("tests_passed"))}, commit=False)
        self.conn.commit()
        if lease is not None:
            lease.close()
        return eval_id

    def record_provenance(self, evaluation_id: str, provenance_data: dict, *,
                          commit: bool = True) -> None:
        row = provenance.flatten_for_db(provenance_data)
        row["evaluation_id"] = evaluation_id
        cols = list(row)
        ph = ",".join(f":{k}" for k in cols)
        upd = ",".join(f"{k}=excluded.{k}" for k in cols if k != "evaluation_id")
        self.conn.execute(
            f"INSERT INTO attempt_provenance({','.join(cols)}) VALUES({ph}) "
            f"ON CONFLICT(evaluation_id) DO UPDATE SET {upd}", row)
        if commit:
            self.conn.commit()

    def record_event(self, run_id: str, config_id: str, task_id: str, phase: str, *,
                     evaluation_id: str | None = None, ts: str | None = None,
                     message: str | None = None, source: str = "harness",
                     confidence: str = "high", data: dict | None = None,
                     commit: bool = True) -> None:
        self._ensure_run(run_id)
        row = transform.event_row(run_id, config_id, task_id, phase, evaluation_id_=evaluation_id,
                                  ts=ts, message=message, source=source, confidence=confidence, data=data)
        cols = list(row)
        ph = ",".join(f":{k}" for k in cols)
        self.conn.execute(f"INSERT OR IGNORE INTO attempt_event({','.join(cols)}) VALUES({ph})", row)
        if commit:
            self.conn.commit()

    def attempt_exists(self, config_id: str, task_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM attempt WHERE config_id=? AND task_id=? LIMIT 1",
                                 (config_id, task_id)).fetchone() is not None

    def add_invalidation(self, kind: str, *, reason: str, config_id: str | None = None,
                         run_id: str | None = None, task_id: str | None = None,
                         produced_by: str | None = None, created_at: str | None = None) -> None:
        if run_id:
            self._ensure_run(run_id)
        self.conn.execute(
            """INSERT INTO invalidation(kind, config_id, run_id, task_id, reason, created_at, produced_by)
               VALUES(?,?,?,?,?,?,?)
               ON CONFLICT DO UPDATE SET reason=excluded.reason, produced_by=excluded.produced_by""",
            (kind, config_id, run_id, task_id, reason, created_at or _utc_now(), produced_by))
        self.conn.commit()

    # -- evidence blobs ---------------------------------------------------- #
    def _bundle_dir(self, evaluation_id: str) -> Path:
        d = self.blobs_dir / evaluation_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_evidence(self, evaluation_id: str, *, verify_log_text: str | None = None,
                       patch_text: str | None = None, stderr_text: str | None = None,
                       transcript_path=None, io_logs_cell: tuple | None = None,
                       cell_dir=None, extra: dict | None = None) -> str:
        """Write evidence into blobs/attempt/<evaluation_id>/ (the path is derived, not
        stored). New W116 path: copy the whole parent-owned cell_dir (stable names).
        Legacy fallback: io_logs_cell = (io_dir, agent, instance)."""
        d = self._bundle_dir(evaluation_id)
        try:
            if verify_log_text is not None:
                (d / "pb-verify.log").write_text(verify_log_text, encoding="utf-8")
            if patch_text is not None:
                (d / "patch.diff").write_text(patch_text, encoding="utf-8")
            if stderr_text is not None:
                (d / "stderr.txt").write_text(stderr_text, encoding="utf-8")
            if transcript_path and Path(transcript_path).expanduser().is_file():
                shutil.copy2(Path(transcript_path).expanduser(), d / "transcript.json")
            if cell_dir:
                self._copy_cell_dir(d, Path(cell_dir).expanduser())
            if io_logs_cell:
                self._copy_io_logs_cell(d, io_logs_cell)
            for name, text in (extra or {}).items():
                (d / name).write_text(text, encoding="utf-8")
        except Exception as exc:  # best-effort
            logger.debug("evidence write failed: %s", exc)
        try:
            return str(d.relative_to(self.dir))
        except ValueError:
            return str(d)

    def _copy_cell_dir(self, dest: Path, cell_dir: Path) -> None:
        """Copy the new W116 per-cell evidence directory into the attempt bundle."""
        if not cell_dir.is_dir():
            return
        for p in sorted(cell_dir.iterdir()):
            if not p.is_file():
                continue
            try:
                shutil.copy2(p, dest / p.name)
            except Exception:
                pass

    def _copy_io_logs_cell(self, dest: Path, io_logs_cell: tuple) -> None:
        """Legacy copy: one cell's agent transcripts from run-bucket io_logs. Ownership token = <instance>_<agent>."""
        io_dir, agent, instance = io_logs_cell
        io_dir = Path(io_dir)
        if not io_dir.is_dir():
            return
        pref = f"{agent}__{instance}__"
        wt = f"{instance}_{agent}"

        def _owns(p: Path) -> bool:
            try:
                with p.open("r", errors="replace") as fh:
                    return wt in fh.read(65536)
            except Exception:
                return False
        picks: list[Path] = []
        picks += sorted(io_dir.glob(f"{pref}*.json"))
        picks += sorted(io_dir.glob(f"{pref}verify__*.log"))
        picks += [p for p in sorted(io_dir.glob(f"*__{instance}__rawcli*.txt")) if _owns(p)]
        picks += [p for p in sorted(io_dir.glob("*rawcli_FAIL*.txt")) if _owns(p)]
        picks += [p for p in sorted(io_dir.glob(f"pi__{instance}__*__session__*.jsonl")) if _owns(p)]
        for p in picks:
            try:
                shutil.copy2(p, dest / p.name)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# module helpers (open -> act -> close); each its own short-lived connection
# --------------------------------------------------------------------------- #
def register_run(run_id: str, *, label: str | None = None, plan=None) -> None:
    """Insert the run row. No agent/dim registration (dims are file-authored temp tables)."""
    with Store() as s:
        s.insert_run(run_id, label=label, plan=plan)


def record_attempt(score: dict, *, evaluation_id: str | None = None,
                   evidence: dict | None = None, lease: "Lease | None" = None,
                   provenance_data: dict | None = None) -> str:
    with Store() as s:
        return s.record_attempt(score, evaluation_id=evaluation_id, evidence=evidence,
                                lease=lease, provenance_data=provenance_data)


def record_event(run_id: str, config_id: str, task_id: str, phase: str, *,
                 evaluation_id: str | None = None, ts: str | None = None,
                 message: str | None = None, source: str = "harness",
                 confidence: str = "high", data: dict | None = None) -> None:
    with Store() as s:
        s.record_event(run_id, config_id, task_id, phase, evaluation_id=evaluation_id, ts=ts,
                       message=message, source=source, confidence=confidence, data=data)


def attempt_exists(config_id: str, task_id: str) -> bool:
    with Store() as s:
        return s.attempt_exists(config_id, task_id)
