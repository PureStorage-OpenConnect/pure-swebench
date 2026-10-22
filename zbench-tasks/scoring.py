#!/usr/bin/env python3
"""Shared zbench scoring + validity primitives -- the ONE implementation of the
validity/scoring model that METHODOLOGY.md defines.

Why this module exists: `backfill_scores.py` and `tools/bench_dashboard.py` used
to keep private copies of the exclusion logic and drifted. METHODOLOGY.md
declares a SINGLE validity model; this is its single home so a consumer cannot
diverge. Change the model here, not in a consumer.

SCORING EXCLUSION STORE: bench.db `run_exclusion` table. Attempts are immutable
facts; scoring exclusion is a MUTABLE OVERLAY of human decisions. Notes/comments/
hints live separately in `note` and never affect scoring. This module READS the
exclusion overlay -- it hardcodes NO agent names or task ids. Optional exclusion
class is encoded as a reason prefix like `[artifact:infra] ...`:
  * "contamination"  a specific RUN mined the answer from the environment
                     (git history etc.); keyed per (instance, agent, run_id).
  * "broken_config"  a cell whose config is broken (not a capability signal);
                     usually AGENT-LEVEL (every run of that agent).
  * "superseded"     an agent replaced by a better-configured equivalent;
                     AGENT-LEVEL.
An annotation is AGENT-LEVEL when it has an `agent` but no `instance` -> it
matches EVERY run of that agent (any instance/run_id), so it also covers future
runs. Otherwise it is PER-RUN, keyed (instance, agent, run_id[/run_ids]).

Older DBs used the `invalidation` table for both comments and scoring decisions;
W39 migrates those rows into `note` + `run_exclusion` and leaves `invalidation` as
legacy evidence. See METHODOLOGY.md §3 for the canonical schema the report server
(tools/benchdb_reader.py) also reads via the SQL anti-join.

The metric is BINARY resolve (hidden test passes). The old graded/partial-credit
"failure-rung ladder" was RETIRED 2026-07-27 -- see METHODOLOGY.md §5.
"""
import os
import re
import sqlite3
import sys
from collections import namedtuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))   # repo root: zbench importable
from zbench import constants

DB_PATH = Path(os.environ.get("ZBENCH_BENCHDB_DIR",
                              str(HERE.parent / "bench-db"))) / "bench.db"

# Invalidations overlay: .runs = {(instance_id, agent, run_id): {kind, reason}}
#                        .agents = {agent: {kind, reason}}  (every run of agent)
Invalidations = namedtuple("Invalidations", ["runs", "agents"])


def full_instance(x):
    """Normalize a task id to the stored instance form ('zbench_<task_id>').
    Accepts an instance id or a bare (opaque) task id; idempotent."""
    return constants.instance_of(str(x))


def load_invalidations(path=None, on_error="raise"):
    """Load the PERMANENT run-invalidity overlay from bench.db.
    Returns an Invalidations(runs, agents). W39 source of truth is `run_exclusion`:
    one row per excluded attempt. Legacy fallback reads `run_review` or
    `invalidation.status=accepted` only when newer tables are absent.

    FAIL-LOUD (finding #12): a MISSING db is the normal "nothing yet" state ->
    empty overlay. A db that EXISTS but is unreadable would SILENTLY DISABLE all
    invalidation, so we WARN and (unless on_error='warn') raise. `path` overrides
    the db location (default: the canonical bench.db)."""
    db = Path(path) if path else DB_PATH
    runs, agents = {}, {}
    if not db.exists():
        return Invalidations(runs, agents)
    try:
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        try:
            has_rx = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_exclusion'"
            ).fetchone() is not None
            if has_rx:
                rows = conn.execute(
                    """SELECT CASE WHEN rx.reason GLOB '[[]*[]]*' THEN substr(rx.reason,2,instr(rx.reason,']')-2)
                                  ELSE 'scoring_exclusion' END AS kind,
                              rx.reason, a.config_id, a.run_id, a.task_id
                       FROM run_exclusion rx JOIN attempt a USING(evaluation_id)"""
                ).fetchall()
            else:
                has_rr = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='run_review'"
                ).fetchone() is not None
                if has_rr:
                    rows = conn.execute(
                        """SELECT rr.invalid_kind AS kind, rr.reason, a.config_id, a.run_id, a.task_id
                           FROM run_review rr JOIN attempt a USING(evaluation_id)
                           WHERE rr.state='invalid'"""
                    ).fetchall()
                else:
                    has_status = any(r[1] == "status"
                                     for r in conn.execute("PRAGMA table_info(invalidation)"))
                    where = " WHERE status='accepted'" if has_status else ""
                    rows = conn.execute(
                        "SELECT kind, config_id, run_id, task_id, reason FROM invalidation" + where
                    ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        msg = (f"run_exclusion/run_review/invalidation store UNREADABLE ({db}): {e} -- exclusion DISABLED; "
               f"the board may silently include contaminated/broken runs")
        print("WARNING: " + msg, file=sys.stderr)
        if on_error != "warn":
            raise RuntimeError(msg)
        return Invalidations(runs, agents)
    for kind, config_id, run_id, task_id, reason in rows:
        if not config_id:
            continue
        agent = str(config_id)
        kind = kind or "contamination"
        reason = reason or kind
        fi = full_instance(task_id) if task_id else None
        runs[(fi, agent, str(run_id) if run_id is not None else None)] = {"kind": kind, "reason": reason}
    return Invalidations(runs, agents)


def invalidation_for(inv, instance, agent, run_id):
    """Return {kind, reason} if this (instance, agent, run_id) run is invalid,
    else None. Agent-level annotations win first (they cover all runs); then the
    per-run annotation. Tolerant of bare task ids vs full instance ids."""
    a = str(agent)
    if a in inv.agents:
        return inv.agents[a]
    return inv.runs.get((full_instance(instance), a, str(run_id)))


def is_invalid(inv, instance, agent, run_id):
    """True iff this run is invalid for ANY reason (contamination/broken/superseded)."""
    return invalidation_for(inv, instance, agent, run_id) is not None


# ============================================================================
# FAILURE-MODE TAXONOMY (W23) -- the SINGLE home of the classification logic.
# Consumers (tools/bench_dashboard.py, zbench-tasks/failure_modes.py, the post-run
# audit `post_run_audit.py`, run_coverage_matrix) MUST call classify_attempt so
# they classify identically by construction (same rule as aggregate_and_rank /
# the invalidation anti-join). METHODOLOGY.md is the prose definition.
#
# Classes (frozen enum):
#   resolved          hidden test passed (tests_passed)                 [capability]
#   miss              produced a patch, hidden test still failed         [capability]
#   no_patch_genuine  ran a fair budget, emitted no usable patch         [capability]
#   artifact:auth     CLI fast-fail (tiny runtime, no output) e.g. OAuth [ARTIFACT]
#   artifact:budget   no_patch that hit a SHORT (< canonical) budget wall[ARTIFACT]
#   artifact:infra    internal_error/worktree_error/workspace prep fail,   [ARTIFACT]
#                     OR a VERIFY-phase timeout (build+test exceeded the
#                     verify cap -- typically resource/distcc/ccache starvation
#                     under concurrent load, NOT the agent's fault; re-run),
#                     OR a provider_error (the model ENDPOINT threw 429/5xx/auth
#                     and the turn never completed -- the agent never got to try)
# (contamination is NOT derivable from attempt facts -- it is detected by the
# io_log scan in audit_contamination.py and lives only as an invalidation
# annotation; the dashboard shows it from that overlay, not from here.)
#
# ARTIFACT classes are NOT capability signal: the post-run audit writes them as
# PER-RUN invalidation annotations so the ranking anti-join drops them and the
# cell becomes a coverage gap that `run_coverage_matrix --fill` re-runs -- a
# PRECISE replacement for the blunt `--recount-nonfinal`.
AUTH_FASTFAIL_S = 90        # <= runtime (s) AND no output_tokens => CLI fast-fail
BUDGET_WALL_FRAC = 0.95     # runtime >= frac * configured budget => hit the wall
CANONICAL_BUDGET_S = 3000   # the matched budget; a wall hit AT canonical is a
                            # legit slow-fail (NOT an artifact) -> avoids re-run loops
CAPABILITY_CLASSES = ("resolved", "miss", "no_patch_genuine")
ARTIFACT_CLASSES = ("artifact:auth", "artifact:budget", "artifact:infra")


def _g(a, k):
    """Field access that tolerates a dict OR a sqlite3.Row."""
    try:
        return a[k]
    except (KeyError, IndexError):
        return None
    except Exception:
        return a.get(k) if hasattr(a, "get") else None


def agent_budget_map(agents_dir=None):
    """{agent_id: agent_timeout_s} from agents-meta.jsonl -- the per-cell budget that
    used to live in the (now-dropped) harness_config.timeout_s dim. Single source for the
    facts-only classifiers (failure_modes / validate_runs); None for agents without one."""
    import json
    p = Path(agents_dir or HERE) / "agents-meta.jsonl"
    out = {}
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            out[d.get("agent_id")] = d.get("agent_timeout_s")
    return out


def classify_attempt(a, budget_s=None):
    """Classify ONE attempt into the failure-mode taxonomy above. Pure function of
    the attempt facts + the cell's configured budget.

    `a`: mapping (dict or sqlite3.Row) with keys tests_passed, status, outcome,
         runtime_ms, total_duration_ms, output_tokens.
    `budget_s`: the cell's configured ZBENCH_AGENT_TIMEOUT == harness_config.timeout_s
         (seconds). None -> the budget-artifact class is disabled (falls through
         to no_patch_genuine), so a missing budget never mislabels a give-up.
    Returns one of CAPABILITY_CLASSES + ARTIFACT_CLASSES."""
    if _g(a, "tests_passed"):
        return "resolved"
    status = (_g(a, "status") or "")
    outcome = (_g(a, "outcome") or "")
    if status in ("internal_error", "worktree_error", "provider_error") \
            or outcome == "workspace_preparation_failed":
        return "artifact:infra"
    # VERIFY-phase timeout: the build+test exceeded the verify cap. This is an
    # infra artifact (a slow/starved C++ build under concurrent load), NOT a
    # capability miss -- a wrong patch fails the test FAST, it doesn't hang. So
    # auto-invalidate + re-run under lighter load (if it times out AGAIN in
    # isolation, that is a real signal to investigate the task/patch).
    if outcome == "verification_timeout" or status == "timeout":
        return "artifact:infra"
    if status == "no_patch_generated" or outcome == "candidate_missing":
        rt = (_g(a, "runtime_ms") or _g(a, "total_duration_ms") or 0) / 1000.0
        out = _g(a, "output_tokens")
        if rt <= AUTH_FASTFAIL_S and not out:
            return "artifact:auth"
        # budget artifact = hit the configured wall AND that wall is SHORTER than
        # canonical (a short-budget cutoff -- W14). A wall hit AT canonical is a
        # legit "too slow / stuck" fail, kept as no_patch_genuine (no re-run loop).
        if budget_s and rt >= BUDGET_WALL_FRAC * float(budget_s) and float(budget_s) < CANONICAL_BUDGET_S:
            return "artifact:budget"
        return "no_patch_genuine"
    return "miss"


def is_artifact_class(cls):
    """True iff a classify_attempt() result is a non-capability ARTIFACT (the
    classes the async validator PROPOSES for human review)."""
    return cls in ARTIFACT_CLASSES


# Setup / build-farm / host INFRA signatures visible ONLY in the verify log, not in
# the stored fact labels. classify_attempt() is a pure function of the fact row
# (status/outcome/runtime/tokens), so an infra failure that the workflow recorded as
# `tests_failed` (e.g. a workspace-prep failure that aborted BEFORE the tests ran)
# is invisible to it -> the validator's fact-only pass would call it "clean". This
# log-based detector lets the audit re-derive infra artifacts from the PRIMARY
# evidence (pb-verify.log), catching such mislabels. Keep in sync with the harness
# copy in `zbench/workflow.py::_SETUP_INFRA_SIGS`.
SETUP_INFRA_SIGS = (
    "unable to sync", "error during sync",
    "no space left on device", "out of diskspace", "index.lock",
    "could not resolve host", "temporary failure in name resolution",
    "connection timed out", "isolated fetch failed", "worktree add failed",
    "cannot connect to the docker daemon",
)


def looks_like_setup_infra_log(text):
    """True iff a verify-log excerpt shows a SETUP/INFRA failure (workspace prep,
    submodule sync, host, or build farm) rather than a genuine build/test failure."""
    t = (text or "").lower()
    return any(sig in t for sig in SETUP_INFRA_SIGS)


# --- Evidence-based no_patch classifier (W52) --------------------------------
# classify_attempt() is a pure function of the STORED FACT LABELS, so it cannot see
# WHY a no_patch happened -- and its budget rule trusts harness_config.timeout_s, which
# may NOT match the budget an OLD attempt actually ran under (the config was later
# bumped to 3000s, but the attempt was killed at the old 1800/2100/2700s cap). It also
# can't see an OUTPUT-TOKEN cap cutoff. This reads the AGENT bundle stderr (the PRIMARY
# evidence, like looks_like_setup_infra_log reads the verify log) to re-derive those.
# Deliberately CONSERVATIVE: an AT/above-canonical generation timeout is a legit
# slow-fail (W14) and is NOT flagged -- the fixed patch-capturing harness (pi 1621e1b /
# claude+pi 7bd61cd) now recovers a timed-out agent's working-tree edits, so a genuine
# no_patch there means genuinely no edits; flagging it would only cause re-run loops.
GEN_TIMEOUT_RE = re.compile(r"timed out after (\d+) seconds")
NO_CHANGE_SIGS = ("pi made no changes", "made no changes", "no changes were made")
OUTPUT_CAP_MIN = 60000      # output_tokens at/above this with a no-changes stderr =>
                            # the generation was cut off by the output-token cap before
                            # it produced an edit (e.g. 64000 exactly, thinking-high).


def classify_no_patch_evidence(stderr_text, output_tokens=None):
    """Evidence-based classifier for a `no_patch_generated` attempt. Returns
    (artifact_class, reason, evidence) when the AGENT stderr shows an ARTIFACT that
    the fact-only classify_attempt cannot see, else (None, None, None) for a genuine
    no_patch. Catches: (a) a SUB-canonical generation timeout kill (budget artifact
    the config-budget rule misses when the recorded budget was later changed); (b) an
    OUTPUT-TOKEN cap cutoff (model cut off mid-work before any edit)."""
    t = stderr_text or ""
    m = GEN_TIMEOUT_RE.search(t)
    if m:
        secs = int(m.group(1))
        if secs < CANONICAL_BUDGET_S:
            return ("artifact:budget",
                    f"agent killed by a sub-canonical generation timeout "
                    f"({secs}s < {CANONICAL_BUDGET_S}s canonical); any partial edits were "
                    f"discarded by the pre-1621e1b adapter -- re-run under the fixed harness",
                    f"stderr: timed out after {secs}s")
    lo = t.lower()
    if output_tokens and int(output_tokens) >= OUTPUT_CAP_MIN and any(s in lo for s in NO_CHANGE_SIGS):
        return ("artifact:budget",
                f"generation hit the output-token cap (~{int(output_tokens)} tokens) before "
                f"producing an edit",
                f"output_tokens={int(output_tokens)}; agent reported no changes")
    return (None, None, None)


def load_annotations(path=None, status=None, on_error="warn"):
    """Read annotations WITH their W23 lifecycle fields (status/source/confidence/
    evidence/produced_by) for SURFACING (the dashboard review queue + annotate.py),
    NOT for ranking (ranking uses load_invalidations, accepted-only). Optional
    `status` filter ('proposed'|'accepted'|'rejected'). Returns a list of dicts.
    Tolerates a pre-migration DB (no status/source columns -> synthesizes
    status='accepted', source='human')."""
    db = Path(path) if path else DB_PATH
    out = []
    if not db.exists():
        return out
    try:
        conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(invalidation)")}
            new = {"status", "source", "confidence", "evidence"} <= cols
            sel = ("id, kind, status, source, confidence, evidence, config_id, run_id, "
                   "task_id, reason, created_at, produced_by") if new else \
                  ("id, kind, 'accepted' AS status, 'human' AS source, NULL AS confidence, "
                   "NULL AS evidence, config_id, run_id, task_id, reason, created_at, produced_by")
            q = f"SELECT {sel} FROM invalidation"
            params = ()
            if status:
                if new:
                    q += " WHERE status=?"
                    params = (status,)
                elif status != "accepted":
                    return []  # pre-migration: everything is 'accepted'
            for r in conn.execute(q, params):
                out.append(dict(r))
        finally:
            conn.close()
    except Exception as e:
        msg = f"annotation read failed ({db}): {e}"
        print("WARNING: " + msg, file=sys.stderr)
        if on_error != "warn":
            raise
    return out
