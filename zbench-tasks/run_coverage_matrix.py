#!/usr/bin/env python3
"""zbench coverage-matrix orchestrator (the BENCHMARK side of METHODOLOGY.md).

Clean separation of concerns:
  * BENCH (this tool)  -> EVEN COVERAGE: run the full agents x corpus grid
    so every ranked agent attempts the same tasks. D1 (rank on a COMMON task set)
    is only meaningful if models actually ran the same tasks -- that is an
    orchestration concern, and it is the ONE ranking-relevant thing the bench must
    get right. Each cell writes its ground truth (binary resolve, tokens, cost,
    gen-time) as an `attempt` row in bench.db (the single store).
  * REPORT SERVER (separate) -> the D1-D5 RANKING VIEW (common-set restriction,
    per-agent_id grouping, per-task aggregation, cost columns, tie handling,
    sorting). This tool does NOT rank; it only ensures the data exists evenly.

Single sources of truth:
  * tasks/<task_id>/meta.json -- judged candidate/task records. The active benchmark
    corpus is DERIVED from these via corpus.load_corpus()
    (curation_status=="validated"). No separate corpus list to maintain.
  * agents-matrix.jsonl    -- the ranked agent set (agent_id = model x harness x provider x thinking)

Coverage = at least one VALID attempt row exists for (config_id, task_id) in
bench.db. W39: a run_exclusion row means that attempt does NOT satisfy coverage,
so `--fill` naturally refills cells whose only attempts were excluded from scoring.
A cell is also MISSING if (with --recount-nonfinal) its row is a
non-capability artifact (no_patch from expired-OAuth / generation timeout) that we
want to re-run. By default truly-absent or review-invalid-only cells are filled.

Usage:
  run_coverage_matrix.py --report                 # coverage matrix + common-set size + gaps
  run_coverage_matrix.py --fill [--backend-only|--web-only] [--dry-run]
  run_coverage_matrix.py --fill --tries 3         # require 3 valid attempts per cell (future pass@k)

Fill strategy: one self-admitting `run_cell` PROCESS per missing cell (the only
engine), throttled by the flock slot pools; each cell writes its attempt to
bench.db. Light langs launch first (warm), heavy-build langs (C++) last.
"""
import argparse, fnmatch, json, os, sqlite3, subprocess, sys, time, uuid
from pathlib import Path

import corpus

HERE = Path(__file__).resolve().parent
DEF_DB = str(HERE.parent / "bench-db" / "bench.db")   # the single store
DEF_REPO = str(Path(os.environ.get("ZBENCH_TARGET_REPO", "~/work/zulip")).expanduser())
DEF_CWD = str(HERE.parent)   # run_cell subprocess cwd = the docs repo (zbench importable)
NONFINAL = {"no_patch_generated", "provider_error"}  # candidates for --recount-nonfinal re-runs

# Per-language run profile -- EXTENSIBLE: `lang` is an open string (go, cpp, and
# future rust/python/...). Any lang not listed falls through to "_default"
# (light build, run last-of-light). A "heavy" build (local compile / RAM-bound,
# e.g. C++ distcc-fallback) gets fewer concurrent workers and is scheduled last
# so it doesn't starve the cheap/warm langs. To add a language, add a profile
# here (or rely on the default); nothing else in the pipeline is lang-specific.
LANG_PROFILE = {
    "web": {"heavy": False, "order": 0, "label": "Web"},   # node tests: light containers
    "py":  {"heavy": True,  "order": 1, "label": "Py"},    # backend: full-service containers
    "_default": {"heavy": True, "order": 1, "label": "?"},
}


def lang_profile(lang):
    return LANG_PROFILE.get(lang, LANG_PROFILE["_default"])


# Launch-order hack (2026-08-06): some agents run on slow backends (the locally served
# open-weight models) whose per-cell generation dominates a fill's wall-clock; launched
# late they become the end-of-batch long pole everyone waits on. Launch them FIRST *within
# each task* so their long cells start immediately. Per-task (not global) front-loading is
# deliberate: the local provider pools are single-slot, so cramming ALL local cells ahead of the
# fast ones would just fill the fanout with slot-waiters and starve the other pools; putting
# them first within each task starts the local chain at t=0 and keeps it fed while fast cells
# fill the remaining fanout. Detected by agent_id substring; extend as new slow backends land.
SLOW_AGENT_MARKERS = ("-local-",)


def _agent_launch_tier(aid):
    """0 = slow backend (launch first within a task); 1 = normal."""
    return 0 if any(m in aid for m in SLOW_AGENT_MARKERS) else 1


def _resolve_agents_path(ap, raw):
    """Resolve --agents to a single absolute path, trying cwd- then HERE-relative, and
    error LOUDLY if it does not exist -- instead of silently launching cells that all
    FileNotFound. Prevents the dual-resolution path-doubling bug (relative --agents such as
    'zbench-tasks/agents-matrix.jsonl' from the repo root used to become
    'zbench-tasks/zbench-tasks/agents-matrix.jsonl' in the run_cell child)."""
    p = Path(raw)
    cands = [p] if p.is_absolute() else [Path.cwd() / p, HERE / p]
    for c in cands:
        if c.is_file():
            return str(c.resolve())
    tried = "\n  ".join(str(c) for c in cands)
    ap.error(f"--agents file not found: {raw!r}\n  tried:\n  {tried}")


def _filter_agents(agents, only, exclude):
    """D3: keep agents whose agent_id matches --only globs, then drop --exclude globs."""
    import fnmatch
    def match(aid, spec):
        return any(fnmatch.fnmatch(aid, p.strip()) for p in spec.split(",") if p.strip())
    if only:
        agents = [a for a in agents if match(a["agent_id"], only)]
    if exclude:
        agents = [a for a in agents if not match(a["agent_id"], exclude)]
    return agents


def load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def load_corpus(args):
    rows = corpus.load_corpus(status=args.status)
    if args.web_only:
        rows = [r for r in rows if r["lang"] == "web"]
    if args.backend_only:
        rows = [r for r in rows if r["lang"] == "py"]
    # Task subsetting for smoke/scale testing (tools/run_eval.sh): --task-ids keeps
    # matching ids (globs OK); --task-limit truncates AFTER all other filters, on the
    # already-sorted id order, so "first 10" is stable across invocations.
    if getattr(args, "task_ids", None):
        pats = [p.strip() for p in args.task_ids.split(",") if p.strip()]
        rows = [r for r in rows if any(fnmatch.fnmatch(r["task_id"], p) for p in pats)]
    if getattr(args, "task_limit", 0):
        rows = rows[:args.task_limit]
    missing = [r["task_id"] for r in rows if not r["instance"]]
    if missing:
        print(f"WARNING: {len(missing)} corpus task(s) lack instance.jsonl (cannot run): "
              + ", ".join(missing), file=sys.stderr)
        rows = [r for r in rows if r["instance"]]
    return rows


def load_coverage(db_path):
    """Return {(agent_id, task_id): [status,...]} from bench.db (the single store).
    Coverage = at least one NON-invalid attempt row exists for the cell.
    W39 run_exclusion rows are human scoring decisions; excluded attempts should
    become coverage gaps so a later --fill can replace them."""
    cov = {}
    if not os.path.exists(db_path):
        return cov
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        has_rx = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_exclusion'"
        ).fetchone() is not None
        if has_rx:
            q = """
                SELECT a.config_id, a.task_id, a.status
                FROM attempt a
                WHERE NOT EXISTS (
                  SELECT 1 FROM run_exclusion rx
                  WHERE rx.evaluation_id=a.evaluation_id)
            """
        else:
            q = "SELECT config_id, task_id, status FROM attempt"
        for cid, task_id, status in conn.execute(q):
            cov.setdefault((cid, task_id), []).append(status)
    finally:
        conn.close()
    return cov


# Infra exclusions come in two flavors and MUST NOT share one "parked" bucket (W-frontier A2).
# A ONE-OFF transient failure (a single expired-OAuth cell, a single transient 429, a killed
# process) should be RE-RUN automatically by --fill, so it must count as MISSING. A PERSISTENT
# infra limit (e.g. an agent x task cell that keeps hitting the Foundry per-model TPM 429 cap
# across re-runs) should stay PARKED so --fill does not loop forever on an unwinnable cell. We
# tell them apart by how many times the cell has ALREADY failed on infra: once its infra-excluded
# attempts pile up to PERSISTENT_INFRA_THRESHOLD or more, the condition has NOT cleared across
# re-runs and the cell is treated as a permanent (parked) limit.
PERSISTENT_INFRA_THRESHOLD = 2


def load_infra_limited(db_path, rerun_infra=False):
    """Return (permanent, transient) sets of (agent_id, task_id) cells whose every attempt is
    scoring-excluded and at least one exclusion is [artifact:infra].
      - permanent: infra failures persisted across >= PERSISTENT_INFRA_THRESHOLD attempts ->
        PARKED, kept OUT of --fill so it does not loop forever (e.g. a 429-capped cell).
      - transient: a single/one-off infra failure (expired OAuth, one transient 429, a killed
        process) -> RE-RUNNABLE; callers treat it as MISSING so --fill re-runs it automatically.
    With rerun_infra=True, nothing is parked (every infra cell is treated as transient) -- an
    escape hatch to force a re-run of a persistent-infra cell after the limit is believed cleared."""
    permanent, transient = set(), set()
    if not os.path.exists(db_path):
        return permanent, transient
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_exclusion'").fetchone():
            return permanent, transient
        for cid, task_id, infra_n in conn.execute(
            """SELECT a.config_id, a.task_id,
                      SUM(CASE WHEN rx.reason LIKE '[artifact:infra]%' THEN 1 ELSE 0 END) AS infra_n
               FROM attempt a LEFT JOIN run_exclusion rx USING(evaluation_id)
               WHERE a.config_id IS NOT NULL
               GROUP BY a.config_id, a.task_id
               HAVING SUM(CASE WHEN rx.evaluation_id IS NULL THEN 1 ELSE 0 END)=0
                  AND SUM(CASE WHEN rx.reason LIKE '[artifact:infra]%' THEN 1 ELSE 0 END)>0"""):
            cell = (cid, task_id)
            if (not rerun_infra) and infra_n >= PERSISTENT_INFRA_THRESHOLD:
                permanent.add(cell)
            else:
                transient.add(cell)
    finally:
        conn.close()
    return permanent, transient


def missing_cells(corpus, agents, cov, tries, recount_nonfinal, parked=None):
    """Yield (task_id, agent_id) needing a (re)run to reach `tries` valid attempts.
    `parked` is the PERMANENT infra-limited set only; transient infra cells are NOT skipped
    (their attempts are all excluded, so they read as coverage gaps -> MISSING -> --fill)."""
    parked = parked or set()
    out = []
    for row in corpus:
        task_id = row["task_id"]
        for ag in agents:
            aid = ag["agent_id"]
            if (aid, task_id) in parked:
                continue
            got = cov.get((aid, task_id), [])
            valid = sum(1 for st in got if not (recount_nonfinal and st in NONFINAL))
            if valid < tries:
                out.append((task_id, aid))
    return out


def report(corpus, agents, cov, tries, recount_nonfinal, permanent=None, transient=None):
    permanent = permanent or set()
    transient = transient or set()
    aids = [a["agent_id"] for a in agents]
    task_ids = [r["task_id"] for r in corpus]
    w = max(len(a) for a in aids) + 2
    cw = max([7] + [len(t) + 2 for t in task_ids])   # task ids are opaque, size to fit
    hdr = "agent".ljust(w) + "".join(t.rjust(cw) for t in task_ids) + "   filled"
    print(hdr)
    print("-" * len(hdr))
    per_agent_tasks = {}
    for aid in aids:
        cells = ""
        filled = 0
        tasks_attempted = set()
        for t in task_ids:
            got = cov.get((aid, t), [])
            parked = (aid, t) in permanent
            has = any(v is not None for v in got)
            if has:
                tasks_attempted.add(t)
                filled += 1
            cells += (("I" if parked else "Y") if has else ("I" if parked else ".")).rjust(cw)
        per_agent_tasks[aid] = tasks_attempted
        print(aid.ljust(w) + cells + f"   {filled}/{len(task_ids)}")
    # D1 common set = tasks attempted by EVERY ranked agent
    common = set(task_ids)
    for aid in aids:
        common &= per_agent_tasks[aid]
    print()
    print(f"Ranked agents: {len(aids)} | corpus tasks: {len(task_ids)}")
    print(f"D1 COMMON SET (attempted by ALL {len(aids)} agents): {len(common)}/{len(task_ids)}")
    if len(common) < len(task_ids):
        gap = sorted(set(task_ids) - common)
        print(f"  tasks NOT in common set: {', '.join(gap)}")
    miss = missing_cells(corpus, agents, cov, tries, recount_nonfinal, permanent)
    parked_cells = sorted((t, a) for (a, t) in permanent
                          if a in aids and t in task_ids)
    transient_cells = sorted((t, a) for (a, t) in transient
                             if a in aids and t in task_ids)
    print(f"MISSING cells (need run, tries={tries}): {len(miss)}")
    if miss:
        by_task = {}
        for p, a in miss:
            by_task.setdefault(p, []).append(a)
        for p in sorted(by_task):
            print(f"  {p}: {', '.join(by_task[p])}")
    print(f"INFRA-LIMITED cells (PERMANENT, parked, not fillable): {len(parked_cells)}")
    if parked_cells:
        by_task = {}
        for p, a in parked_cells:
            by_task.setdefault(p, []).append(a)
        for p in sorted(by_task):
            print(f"  {p}: {', '.join(by_task[p])}")
    print(f"INFRA-TRANSIENT cells (re-runnable -> counted as MISSING; --fill re-runs): {len(transient_cells)}")
    if transient_cells:
        by_task = {}
        for p, a in transient_cells:
            by_task.setdefault(p, []).append(a)
        for p in sorted(by_task):
            print(f"  {p}: {', '.join(by_task[p])}")
    return miss


def fill_cells(corpus, agents, miss, args):
    """Decentralized fill: spawn one self-admitting `run_cell` PROCESS per missing
    cell. Each cell throttles itself via the flock slot pools (global + provider
    [+ heavy]), so there is NO central coordinator -- we just keep a bounded number
    of launches in flight (--fanout) to avoid a pile of slot-waiting procs. Any
    other launcher (human, agent, CI) can run concurrently against the same pools."""
    # Self-heal zombie liveness leases on every fill invocation: a cell hard-killed
    # (disk-full, OOM, SIGKILL, a killed launcher) leaves its .runtime/live lease
    # behind, which the dashboard then shows as a perpetual STALE row. Reap leases that
    # are silent past the STALE threshold AND not currently holding a flock slot (a
    # live cell holds its slot for its whole run, so this never touches a long-but-live
    # build). Runs even when nothing is missing so a stale-only state still gets cleaned.
    try:
        sys.path.insert(0, str(HERE.parent))   # zbench lives in the docs tree
        from zbench.store import reap_stale_leases
        from zbench.cells.slots import live_cell_keys
        _reaped = reap_stale_leases(live_cell_keys())
        if _reaped:
            print(f"reaped {len(_reaped)} zombie liveness lease(s)")
    except Exception as _e:
        print(f"(lease reap skipped: {_e})")
    if not miss:
        print("No missing cells -- coverage is already even. Nothing to run.")
        return 0
    corpus_by_task = {r["task_id"]: r for r in corpus}
    # single-agent file per agent_id (run_cell selects by --agent-id from a file).
    # args.agents is already canonicalized to an absolute path in main() -- use it as-is.
    # (Historically this re-resolved (HERE / args.agents), which DIFFERED from the parent's
    # cwd-relative load and doubled a relative path like 'zbench-tasks/agents-matrix.jsonl' into
    # 'zbench-tasks/zbench-tasks/...', so every cell died FileNotFound while the parent 'succeeded'.)
    agents_file = args.agents
    run_id = args.run_id or ("cov-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:6])
    # DURABLE per-run dir (survives reboot); no /tmp. Driver log + each cell's
    # stdout land here alongside the durable io_logs/scores/cells the workflow writes.
    run_dir = HERE.parent / "bench-db" / ".runtime" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    # order light langs first (warm), heavy last; within a task, SLOW (local) agents first so the
    # long-pole cells start immediately -- purely launch order; slots do the real limiting.
    order = sorted(miss, key=lambda pa: (lang_profile(corpus_by_task[pa[0]]["lang"])["order"],
                                         pa[0], _agent_launch_tier(pa[1]), pa[1]))
    print(f"Filling {len(order)} cell(s) via run_cell (run_id={run_id}, fanout={args.fanout}); "
          f"slots enforce caps. dry_run={args.dry_run}")
    inflight = []  # list[(Popen, cell_str)]
    rc_all = 0

    def _reap(block):
        nonlocal rc_all
        still = []
        for p, cs in inflight:
            if p.poll() is None:
                still.append((p, cs))
            else:
                rc = p.returncode
                rc_all |= (0 if rc in (0, 75) else rc)  # 75 = temp no-capacity, not a failure
                if rc == 75:
                    # slot-wait gave up (should be RARE now that --slot-timeout is 6h).
                    # Flag LOUDLY so a dropped cell isn't silently lost -- re-run it with
                    # a single launcher (a fresh --fill picks it up as still-missing).
                    print(f"  [done rc=75 -- SLOT-WAIT GAVE UP, cell NOT run, re-fill later] {cs}")
                else:
                    print(f"  [done rc={rc}] {cs}")
        inflight[:] = still
        if block and inflight:
            time.sleep(2)

    driver_log = run_dir / "driver.log"
    print(f"  durable run dir: {run_dir} (driver.log + per-cell *.celllog)")
    for task_id, aid in order:
        row = corpus_by_task[task_id]
        cell = f"{row['task_id']} x {aid}"
        cmd = [
            "python3", "-m", "zbench.cells.run_cell",
            # zbench run_cell derives the instance-id from the --instances file (no
            # --instance-id arg, unlike the fork's run_cell).
            "--instances", row["instance"],
            "--agents", agents_file, "--agent-id", aid,
            "--base-repo", args.repo, "--run-id", run_id,
            "--timeout", str(args.slot_timeout),
            # W39: a cell may be "missing" because the only existing attempt is
            # excluded from scoring. run_cell's own idempotency is attempt-exists
            # based, so force is required for these coverage-gap replacements;
            # absent cells are unaffected.
            "--force",
        ]
        if args.dry_run:
            print("  [dry-run]", " ".join(cmd))
            continue
        while len(inflight) >= args.fanout:
            _reap(block=True)
        print(f"  [launch] {cell}")
        # each cell's stdout -> durable per-cell log under the run dir (no /tmp)
        clog = open(run_dir / f"{task_id}__{aid}.celllog", "w")
        with open(driver_log, "a") as dl:
            dl.write(f"launch {cell} -> {clog.name}\n")
        # zbench lives in the docs tree; run_cell (cwd = the pb checkout, for pb/venv on
        # PATH) + the agent subprocess it spawns both need it importable -> PYTHONPATH.
        _cell_env = dict(os.environ)
        _cell_env["PYTHONPATH"] = str(HERE.parent) + os.pathsep + _cell_env.get("PYTHONPATH", "")
        # Pin runtime staging to bench-db/.runtime so no live artifact depends on cwd.
        _cell_env["ZBENCH_DATA_DIR"] = str((HERE.parent / "bench-db" / ".runtime").resolve())
        _cell_env["ZBENCH_SLOTS_DIR"] = str((HERE.parent / "bench-db" / ".runtime" / "slots").resolve())
        inflight.append((subprocess.Popen(cmd, cwd=args.cwd, stdout=clog,
                                          stderr=subprocess.STDOUT, env=_cell_env), cell))
    while inflight:
        _reap(block=True)
    # VALIDATION IS OFF THE CRITICAL PATH (W23, 2026-07-28). We no longer run the
    # contamination audit inline here: validation is an ON-DEMAND, non-blocking job
    # (`validate_runs.py`) whose findings are PROPOSED annotations a human reviews.
    # A fill just lands attempts; nothing waits on validation, and not-yet-validated
    # runs never block coverage/ranking. (Was: inline audit_contamination.py, which
    # both slowed fills and hard-flagged false positives -- e.g. a code comment
    # containing "cherry-picked".) Run `python3 validate_runs.py` when you want to
    # (re)validate; `--no-audit` is kept as a no-op alias for back-compat.
    return rc_all


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", action="store_true", help="print coverage matrix + gaps (default if no action)")
    ap.add_argument("--fill", action="store_true", help="run missing cells for even coverage")
    ap.add_argument("--dry-run", action="store_true", help="with --fill, plan only")
    ap.add_argument("--backend-only", action="store_true")
    ap.add_argument("--web-only", action="store_true")
    ap.add_argument("--status", default="validated",
                    help='curation_status to rank over (default validated); "*" for all')
    ap.add_argument("--fanout", type=int, default=6,
                    help="max run_cell launches kept in flight (slots still enforce real caps)")
    ap.add_argument("--slot-timeout", type=int, default=21600,
                    help="seconds each cell waits for its slots before giving up (rc=75). "
                         "Default 6h >> run_cell's 3600s default: a deep heavy=2 C++ queue "
                         "(e.g. two launchers x many cells) can leave a back-of-queue cell "
                         "waiting >1h; the old 3600s made it give up (rc=75) and the launcher "
                         "does not retry -> cells were silently dropped.")
    ap.add_argument("--run-id", default=None, help="run_id bucket for the grid launch")
    ap.add_argument("--no-audit", action="store_true",
                    help="skip the post-fill automatic contamination audit (default: run it)")
    ap.add_argument("--tries", type=int, default=1, help="required valid attempts per cell (pass@k)")
    ap.add_argument("--recount-nonfinal", action="store_true",
                    help="treat no_patch (auth/timeout artifacts) as missing -> re-run")
    ap.add_argument("--rerun-infra", action="store_true",
                    help="treat PERSISTENT infra-limited cells as re-runnable too (nothing parked); "
                         "escape hatch to force a re-fill of a persistent-cap cell "
                         "after the underlying limit is believed cleared")
    ap.add_argument("--agents", default=str(HERE / "agents-matrix.jsonl"))
    # DEDUP_REVIEW D3: express subsets at CALL TIME instead of hand-written agents-*.jsonl.
    # run_cell still reads the full --agents file and picks each agent by --agent-id, so
    # filtering only changes which agents this orchestrator iterates.
    ap.add_argument("--task-ids", help="comma-separated task_id globs to KEEP (e.g. 'ZT-13*,ZT-472*')")
    ap.add_argument("--task-limit", type=int, default=0,
                    help="keep only the first N tasks (stable id order) -- smoke/scale testing")
    ap.add_argument("--only", help="comma-separated agent_id globs to KEEP (e.g. 'pi-foundry-*')")
    ap.add_argument("--exclude", help="comma-separated agent_id globs to DROP (e.g. 'pi-local-*,pi-foundry-glm-5.2')")
    ap.add_argument("--db", default=DEF_DB, help="bench.db (the single store)")
    ap.add_argument("--repo", default=DEF_REPO, help="target repo worktree root")
    ap.add_argument("--cwd", default=DEF_CWD, help="working directory for run_cell subprocesses")
    # concurrency caps by verify weight (see LANG_PROFILE).
    ap.add_argument("--light-workers", dest="light_workers", type=int, default=3,
                    help="concurrent workers for light-verify langs (web node tests)")
    ap.add_argument("--heavy-workers", dest="heavy_workers", type=int, default=2,
                    help="concurrent workers for heavy-verify langs (py backend containers)")
    args = ap.parse_args()
    # Canonicalize --agents to ONE absolute path shared by BOTH the parent report
    # (load_jsonl below) and the child run_cell subprocesses (fill_cells). These used to
    # resolve the same arg differently (cwd-relative here vs HERE-relative in fill_cells),
    # so a relative --agents doubled its prefix in the child and every cell FileNotFound'd
    # while the parent 'succeeded'. Resolve once, try cwd- then HERE-relative, and FAIL FAST.
    args.agents = _resolve_agents_path(ap, args.agents)

    corpus = load_corpus(args)
    agents = _filter_agents(load_jsonl(args.agents), args.only, args.exclude)
    cov = load_coverage(args.db)
    permanent, transient = load_infra_limited(args.db, rerun_infra=args.rerun_infra)

    miss = report(corpus, agents, cov, args.tries, args.recount_nonfinal, permanent, transient)
    if args.fill:
        sys.exit(fill_cells(corpus, agents, miss, args))


if __name__ == "__main__":
    main()
