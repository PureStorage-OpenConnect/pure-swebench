"""flock-based slot pools for decentralized concurrency admission (ported from the fork).

Capacity is enforced by the OS: each pool is a directory of N slot files; a process
claims a slot by a NON-BLOCKING exclusive flock on one of them. Atomic cap (no
check-then-act race), crash-safe (the kernel releases the flock the instant the holder
dies -> no stale-slot reaping, no pid-reuse hazard), decentralized (no coordinator).

PHASE-AWARE slotting (W132): a cell does NOT hold all its pools for its whole life. It holds
`global` (total-cell cap) end-to-end, and the workflow acquires the OTHER pools per phase --
the per-provider GENERATION slot only around LLM generation, and a local-CPU BUILD slot
(`heavy` for C++, `build:go` for Go) only around worktree-setup + verify. So a cell in remote
generation does not tie up a local-CPU slot. Each `acquire()` call still grabs its pools
all-or-nothing with jittered backoff (never deadlocks; consistent order global->gen->build).
Single-host only (flock is per-kernel). Cell keys carry no try ordinal (W109).
"""
from __future__ import annotations

import contextlib
import errno
import fcntl
import json
import os
import random
import time
from pathlib import Path

from zbench import constants

# Default per-pool capacities. Override via <slots_dir>/caps.json or env
# ZBENCH_SLOT_CAP_<pool> (use '__' for ':' e.g. ZBENCH_SLOT_CAP_provider__anthropic=5).
# Two INDEPENDENT dimensions (W132 phase-aware slotting):
#  * provider:<X> = GENERATION concurrency, sized to each backend's capacity. Held ONLY
#    during the LLM-generation phase (workflow._phase_slot), so remote generation never
#    ties up a local-CPU slot. Hosted APIs take many concurrent; each locally served model is
#    single-slot (the local GPU server serves one at a time).
#  * heavy = BUILD/VERIFY local-CPU concurrency (the pb build + verify test-run, and prep
#    oracles). Held ONLY during build/verify. This is the real RAM/CPU gate.
#  * global = total cells in-progress on the VM (held whole-cell); set high -- the real
#    gates are provider (gen) + heavy (build).
DEFAULT_CAPS = {
    "global": 20,
    "setup": 4,             # worktree setup (depth-1 fetch of the zulip tree; disk/CPU)
    "verify:backend": 3,    # test-backend containers (each runs postgres/redis/rabbitmq)
    "verify:frontend": 4,   # test-js-with-node containers (lighter)
    # -- generation (per provider) --
    "provider:claude-cli": 10,
    "provider:anthropic": 10,
    "provider:azure-foundry": 8,
    # (The Foundry ChatGPT gateway pools -- azure-foundry-openai and the per-model gpt-5.*
    # cap-1 buckets -- were removed 2026-08-17 with the Foundry GPT rows; ChatGPT models run
    # only through provider:openai-direct now.)
    # Hosted Fireworks-on-Foundry deployments throttle (429) at LOW concurrency -- observed
    # 2026-08-10 that even 2 concurrent generations against one model deployment (e.g.
    # FW-GLM-5.2) self-throttle. Each model is its own deployment/slot pool, so serialize
    # per model (cap 1) + rely on pi's 429 retry/backoff; raise only if a deployment's real
    # serving concurrency is confirmed higher. (moonshot/Kimi-K2.6 is a separate backend, left
    # higher pending its own evidence.)
    "provider:azure-foundry-fireworks-deepseek": 1,
    "provider:azure-foundry-fireworks-flash": 1,   # FW-DeepSeek-V4-Flash deployment
    "provider:azure-foundry-fireworks-glm": 1,
    "provider:azure-foundry-fireworks-kimi": 1,
    "provider:azure-foundry-moonshot": 6,
    # Direct OpenAI API (codex-openai-* / any future pi-openai-*): rate limits are far
    # above the Foundry gateway's per-model bucket. Nothing to serialise here; the cap
    # just bounds local fan-out.
    "provider:openai-direct": 6,
    "provider:local-llama": 1,
    "provider:local-ollama": 1,
}


class CapacityError(RuntimeError):
    """Raised when slots can't be acquired within the wait window (--no-wait / timeout)."""


def _san(pool: str) -> str:
    return pool.replace(":", "__").replace("/", "_")


def slots_root() -> Path:
    """ZBENCH_SLOTS_DIR override, else <bench-db>/.runtime/slots (co-located with leases)."""
    r = os.environ.get("ZBENCH_SLOTS_DIR")
    if r:
        return Path(r)
    from ..store import benchdb_dir
    return benchdb_dir() / ".runtime" / "slots"


def load_caps() -> dict[str, int]:
    caps = dict(DEFAULT_CAPS)
    f = slots_root() / "caps.json"
    if f.exists():
        try:
            caps.update({k: int(v) for k, v in json.loads(f.read_text()).items()})
        except Exception:
            pass
    prefix = "ZBENCH_SLOT_CAP_"
    for k, v in os.environ.items():
        if k.startswith(prefix):
            try:
                caps[k[len(prefix):].replace("__", ":")] = int(v)
            except ValueError:
                pass
    return caps


def cap_for(pool: str) -> int:
    return load_caps().get(pool, 1)


def _try_claim_one(pool: str, meta: dict) -> tuple[int, Path] | None:
    """Try to grab one free slot of `pool` (non-blocking). Return (fd, path) or None."""
    size = cap_for(pool)
    d = slots_root() / _san(pool)
    d.mkdir(parents=True, exist_ok=True)
    for i in range(size):
        fp = d / f"slot{i}"
        fd = os.open(fp, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(fd)
            if e.errno in (errno.EWOULDBLOCK, errno.EACCES, errno.EAGAIN):
                continue  # held by someone else
            raise
        try:
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps({**meta, "pool": pool, "slot": i,
                                     "pid": os.getpid(), "ts": time.time()}).encode())
        except OSError:
            pass
        return fd, fp
    return None


@contextlib.contextmanager
def acquire(pools: list[str], *, wait: bool = True, timeout: float = 3600.0,
            meta: dict | None = None):
    """Acquire one slot from EACH pool (all-or-nothing, with backoff). Releases all on
    exit (and automatically if the process dies, via fd close)."""
    meta = meta or {}
    deadline = time.time() + timeout
    while True:
        held: list[tuple[int, Path]] = []
        ok = True
        for pool in pools:
            claim = _try_claim_one(pool, meta)
            if claim is None:
                ok = False
                break
            held.append(claim)
        if ok:
            try:
                yield [fp for _fd, fp in held]
            finally:
                for fd, _fp in held:
                    try:
                        os.close(fd)  # releases the flock
                    except OSError:
                        pass
            return
        for fd, _fp in held:            # couldn't get all -> release partials, back off
            try:
                os.close(fd)
            except OSError:
                pass
        if not wait or time.time() >= deadline:
            raise CapacityError(f"no capacity for pool '{pool}' (wait={wait})")
        time.sleep(0.5 + random.random() * 0.75)


def status() -> dict:
    """Inspect pools: which slots are HELD (flock busy) + their meta (we never keep it)."""
    out = {}
    for pool, size in load_caps().items():
        d = slots_root() / _san(pool)
        held, free = [], 0
        for i in range(size):
            fp = d / f"slot{i}"
            if not fp.exists():
                free += 1
                continue
            fd = os.open(fp, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fd, fcntl.LOCK_UN)
                free += 1
            except OSError:
                try:
                    held.append(json.loads(fp.read_text() or "{}"))
                except Exception:
                    held.append({"slot": i, "pool": pool})
            finally:
                os.close(fd)
        out[pool] = {"size": size, "held": len(held), "free": free, "holders": held}
    return out


def try_claim_cell(config_id: str, task_id: str) -> int | None:
    """Non-blocking EXCLUSIVE flock per (config_id, task_id). Returns an open fd (HOLD it for
    the whole cell; closing releases) or None if another LIVE cell already holds it.

    This is the per-cell admission gate that makes OVERLAPPING / board-wide `--fill`s safe:
    a second launcher for a cell that is already in-flight backs off here instead of
    duplicating the work (the historical "stacked-fill dup trap"). It is race-free (atomic
    flock), independent of the per-provider capacity slots, and auto-releases if the process
    dies (fd close). A cell that has already LANDED an attempt is deduped separately by
    store.attempt_exists; this lock only guards the in-flight window."""
    d = slots_root() / "celllock"
    d.mkdir(parents=True, exist_ok=True)
    safe = f"{config_id}__{task_id}".replace("/", "_")
    fp = d / f"{safe}.lock"
    fd = os.open(fp, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        os.close(fd)
        if e.errno in (errno.EWOULDBLOCK, errno.EACCES, errno.EAGAIN):
            return None  # another live cell holds this (config_id, task_id)
        raise
    try:
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps({"config_id": config_id, "task_id": task_id,
                                 "pid": os.getpid(), "ts": time.time()}).encode())
    except OSError:
        pass
    return fd


def live_cell_keys() -> set[str]:
    """Cell keys (slot `cell` meta) currently holding a flock slot = genuinely executing.
    Authoritative liveness signal for reaping stale leases."""
    keys: set[str] = set()
    for s in status().values():
        for h in s.get("holders", []):
            c = h.get("cell")
            if c:
                keys.add(str(c))
    return keys


def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Inspect / manage cell slot pools.")
    ap.add_argument("cmd", nargs="?", default="status", choices=["status", "caps", "reap"])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-age-s", type=int, default=2 * 3600)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "caps":
        print(json.dumps(load_caps(), indent=2)); return
    if args.cmd == "reap":
        from ..store import reap_stale_leases, benchdb_dir
        live = live_cell_keys()
        if args.dry_run:
            base = benchdb_dir() / ".runtime" / "live"
            found = []
            for lf in sorted(base.glob("*/*.json")) if base.is_dir() else []:
                try:
                    p = json.loads(lf.read_text() or "{}")
                except Exception:
                    p = {}
                ck = constants.cell_key(p.get("task_id", ""), p.get("config_id", ""))  # no try (W109)
                found.append((lf, ck in live))
            print(f"[dry-run] {len(found)} lease(s); live-held marked *:")
            for lf, islive in found:
                print(f"  {'*' if islive else ' '} {lf}")
            return
        reaped = reap_stale_leases(live, min_age_s=args.min_age_s)
        print(f"reaped {len(reaped)} zombie lease(s):")
        for p in reaped:
            print(f"  {p}")
        return
    st = status()
    if args.json:
        print(json.dumps(st, indent=2)); return
    print(f"slots dir: {slots_root()}")
    for pool, s in st.items():
        bar = "#" * s["held"] + "." * s["free"]
        print(f"  {pool:28s} [{bar}] {s['held']}/{s['size']} held")
        for h in s["holders"]:
            print(f"      - {h.get('cell', h.get('pid'))} (pid {h.get('pid')})")


if __name__ == "__main__":
    _main()
