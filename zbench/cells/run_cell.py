"""Run ONE isolated, self-admitting zbench cell (ported, dicts, no try_number).

Loads an InstanceSpec + AgentSpec, admits itself via flock slots, holds a liveness lease,
runs the test-blind patch attempt (workflow), and records the attempt fact + lifecycle
events via store. Idempotent: skips if an attempt already exists for (config_id, task_id).
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import constants, ingest, paths, provenance, store, workflow
from . import slots


def _task_of(instance_id: str) -> str:
    return constants.task_of(instance_id)


def _provider_pool(agent: dict) -> str:
    """Generation-slot pool for this agent. Explicit override first: an agent env carrying
    ZBENCH_PROVIDER_POOL=<name> pins the pool to provider:<name> regardless of harness --
    e.g. multiple codex agents sharing ONE localhost gateway-proxy base URL (Azure AI
    Foundry) keep their per-deployment serialized pools instead of collapsing into a single
    per-base-URL pool. Otherwise fall back to the harness-derived heuristics below."""
    cmd = agent.get("command") or ""
    env = agent.get("env") or {}
    pool = env.get("ZBENCH_PROVIDER_POOL")
    if pool:
        return f"provider:{pool}"
    if "claude_agent" in cmd:
        return "provider:claude-cli"
    if "codex_agent" in cmd:
        # a self-hosted endpoint (CODEX_BASE_URL) can serve only one model on the box at
        # a time -> its own serialized pool; OpenAI's API shares a parallelizable pool.
        base = env.get("CODEX_BASE_URL")
        return f"provider:codex-selfhost:{base}" if base else "provider:openai"
    prov = env.get("PI_PROVIDER")
    return f"provider:{prov}" if prov else "provider:unknown"


_VERIFY_POOL = {"py": "verify:backend", "python": "verify:backend", "web": "verify:frontend"}


def _build_pool(instance: dict) -> str:
    """Language-keyed verify pool: backend verifies run full service containers
    (postgres/redis/rabbitmq) and are capped tighter than frontend node runs."""
    md = instance.get("metadata") or {}
    lang = (md.get("language") or "py").lower()
    return _VERIFY_POOL.get(lang, "verify:backend")


def run_cell(instance: dict, agent: dict, base_repo_dir, *, run_id: str | None = None,
             wait: bool = True, timeout: float = 3600.0, force: bool = False) -> dict:
    """Run one cell (self-admitting). Returns the score map (or a skip/marker map)."""
    iid, aid = instance["instance_id"], agent["agent_id"]
    task_id = _task_of(iid)
    if not run_id:
        run_id = "cell-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
    cell_id = f"{iid}_{aid}"     # no try (W109)

    if not force and store.attempt_exists(aid, task_id):
        print(f"[skip] {cell_id}: attempt already in bench.db")
        return {"instance_id": iid, "agent_id": aid, "status": "skipped"}

    # Per-cell admission gate (W144): claim an exclusive flock for this (config_id, task_id)
    # BEFORE doing any work. If another live cell already holds it, a different --fill (or a
    # per-task grid) is already running this exact cell -> back off instead of duplicating it
    # (kills the "stacked-fill dup trap" at the source, so overlapping/board-wide fills are
    # SAFE and no longer need the fragile "one fill at a time" operator rule). Held for the
    # whole cell; released on fd close (incl. process death) in the finally below.
    _cell_fd = slots.try_claim_cell(aid, task_id)
    if _cell_fd is None:
        print(f"[skip] {cell_id}: another live cell is already running this (config,task_id)")
        return {"instance_id": iid, "agent_id": aid, "status": "skipped_inflight"}
    # Re-check under the lock: an attempt may have LANDED between the fast-path check above
    # and acquiring the gate (closes the completed-attempt race too).
    if not force and store.attempt_exists(aid, task_id):
        os.close(_cell_fd)
        print(f"[skip] {cell_id}: attempt landed while acquiring cell gate")
        return {"instance_id": iid, "agent_id": aid, "status": "skipped"}

    os.environ["ZBENCH_CELL_ID"] = cell_id
    os.environ.setdefault("ZBENCH_RUN_ID", run_id)
    # Pin data_dir absolute, then allocate one persistent per-cell evidence dir. The
    # worktree is disposable; this dir is the durable parent-owned capture area.
    os.environ["ZBENCH_DATA_DIR"] = str(paths.data_dir().resolve())
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    cdir = paths.cell_dir(agent_id=aid, instance_id=iid, run_id=run_id, stamp=stamp).resolve()
    os.environ["ZBENCH_CELL_DIR"] = str(cdir)
    os.environ["ZBENCH_SESSION_PATH"] = str(cdir / "session.jsonl")
    os.environ["ZBENCH_RAWCLI_PATH"] = str(cdir / "rawcli.txt")

    # PHASE-AWARE SLOTTING (W132): the whole cell holds ONLY `global` (total-cell cap). The
    # per-provider GENERATION slot and the local-CPU BUILD/VERIFY slot are acquired by the
    # workflow around only their phases (see ctx.gen_pool / ctx.build_pool), so a cell in
    # remote LLM generation holds only the provider slot (not the local-CPU build slot) and
    # cannot block other cells' build/verify.
    pools = ["global"]
    ctx = {"run_id": run_id, "evaluation_id": None,
           "gen_pool": _provider_pool(agent),
           "build_pool": _build_pool(instance),  # language-keyed verify slot
           "provenance": provenance.collect_attempt_provenance(agent)}

    store.register_run(run_id, label="run_cell")
    store.record_event(run_id, aid, task_id, "cell_started", message="cell process launched",
                       data={"instance_id": iid, "pools": pools})
    lease = store.Lease(run_id, aid, task_id).open("acquiring-slot")
    store.record_event(run_id, aid, task_id, "slot_wait_started", message="waiting for slots", data={"pools": pools})

    print(f"[cell] {cell_id}: acquiring {pools} ...", flush=True)
    rec = {"instance_id": iid, "agent_id": aid, "status": "internal_error"}
    # Background heartbeat: refresh the lease every 60s for the WHOLE run (agent gen + verify
    # can be tens of minutes with no phase transition). Without this the heartbeat is written
    # once and a LIVE slow cell looks minutes-stale, forcing a very lenient reader TTL that let
    # killed-run zombie leases read as RUNNING for ~2h. A fresh heartbeat lets the reader use a
    # tight staleness bound so zombies are detected within minutes.
    # Track the ACTUAL phase so the lease/dashboard don't show a cell that has `global` but is
    # BLOCKED waiting for its gen/build slot as "running". The workflow advances the phase via
    # ctx["set_phase"] (worktree-setup / waiting-gen / generating / waiting-verify / verifying).
    _hb_stop = threading.Event()
    _phase = {"v": "running"}
    def _heartbeat_loop():
        while not _hb_stop.wait(60):
            lease.heartbeat(_phase["v"])
    def _set_phase(ph):
        _phase["v"] = ph
        lease.heartbeat(ph)
    ctx["set_phase"] = _set_phase
    try:
        with slots.acquire(pools, wait=wait, timeout=timeout, meta={"cell": cell_id}):
            print(f"[cell] {cell_id}: RUNNING", flush=True)
            store.record_event(run_id, aid, task_id, "slots_acquired", message="slots acquired", data={"pools": pools})
            lease.heartbeat("running")
            threading.Thread(target=_heartbeat_loop, daemon=True).start()
            store.record_event(run_id, aid, task_id, "task_attempt_started", message="task attempt started")
            try:
                rec = workflow.run_patch_task_attempt(agent, instance, ctx, base_repo_dir) or rec
                store.record_event(run_id, aid, task_id, "task_attempt_finished",
                                   message=str(rec.get("status") or "finished"),
                                   data={"status": rec.get("status"), "attempt_outcome": rec.get("attempt_outcome")})
            except Exception as e:
                store.record_event(run_id, aid, task_id, "cell_error", message=repr(e))
                raise
    finally:
        _hb_stop.set()
        lease.close()
        try:
            os.close(_cell_fd)  # release the per-cell admission gate (W144)
        except OSError:
            pass
    print(f"[cell] {cell_id}: DONE status={rec.get('status')}")
    return rec


def _main(argv=None):
    # Self-narrate: surface the harness's phase logs (incl. the multi-minute, otherwise
    # SILENT containerized-verify phase) so a tailer of the run log never
    # has to guess liveness from pgrep/mtime. Authoritative liveness stays the lease +
    # attempt_event rows; this just makes the log self-explaining.
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Run one isolated, self-admitting zbench cell.")
    ap.add_argument("--instances", required=True, help="instance.jsonl (single)")
    ap.add_argument("--agents", required=True, help="agents jsonl (single or multi)")
    ap.add_argument("--agent-id", help="which agent_id (required if the file has >1)")
    ap.add_argument("--base-repo", required=True)
    ap.add_argument("--run-id", default=os.environ.get("ZBENCH_RUN_ID"))
    ap.add_argument("--no-wait", action="store_true", help="fail instead of waiting for a slot")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    instance = ingest.load_instance_file(args.instances)
    agents = ingest.load_agents(args.agents)
    if args.agent_id:
        agents = [a for a in agents if a["agent_id"] == args.agent_id]
    if len(agents) != 1:
        sys.exit(f"{args.agents}: need exactly one agent (got {len(agents)}); pass --agent-id")
    try:
        run_cell(instance, agents[0], args.base_repo, run_id=args.run_id,
                 wait=not args.no_wait, timeout=args.timeout, force=args.force)
    except slots.CapacityError as e:
        print(f"[no-capacity] {e}")
        sys.exit(75)  # EX_TEMPFAIL -- launcher may retry later


if __name__ == "__main__":
    _main()
