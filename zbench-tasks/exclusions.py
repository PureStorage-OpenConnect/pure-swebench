"""Single source of truth for the scoring-exclusion vocabulary (DEDUP_REVIEW D1).

Before this module the "is this attempt excluded / what KIND / build the reason
string" logic was re-implemented across several files (bench_dashboard, benchdb_reader,
consistency_check, exclude_infra_artifacts, harness_reliability_sweep,
scoring, validate_runs, run_coverage_matrix) as ad-hoc `reason LIKE '[...]%'` SQL
and hand-built reason strings. That divergence produced a real bug (the infra-exclusion
tool hard-coded a "429 / Foundry" reason that was WRONG for the local self-hosted
timeouts). Everything about exclusion PREFIXES now lives here.

Model: an attempt is excluded from scoring iff a `run_exclusion` row exists for its
`evaluation_id`. The row's `reason` carries a bracketed KIND prefix:
    [contamination] ...          -> the attempt saw/used the hidden test (cheating)
    [artifact:infra] ...         -> infra/serving failure (429, timeout, disk, auth)
    [artifact:harness] ...       -> a harness/adapter bug (e.g. patch-loss)
    [broken_config] / [superseded] ... -> obsolete config / replaced by a re-run
An empty/absent prefix = a plain human exclusion (kind "scoring").
"""
from __future__ import annotations

import re

# --- the KIND vocabulary (bracketed reason prefixes) -----------------------
CONTAMINATION = "contamination"
ARTIFACT_INFRA = "artifact:infra"
ARTIFACT_HARNESS = "artifact:harness"
BROKEN_CONFIG = "broken_config"
SUPERSEDED = "superseded"

# SQL LIKE patterns (single source; use in the anti-joins instead of retyping).
CONTAM_LIKE = "[contamination]%"
INFRA_LIKE = "[artifact:infra]%"

# The scoring anti-join predicate (DEDUP_REVIEW D7): an attempt aliased `a` is INCLUDED
# in scoring iff NO run_exclusion row exists for it. Drop into a WHERE clause instead of
# retyping `NOT EXISTS (SELECT 1 FROM run_exclusion ...)` across the readers.
NOT_EXCLUDED_SQL = ("NOT EXISTS (SELECT 1 FROM run_exclusion rx "
                    "WHERE rx.evaluation_id = a.evaluation_id)")

_PREFIX_RE = re.compile(r"^\[([^\]]+)\]")


def parse_prefix(reason):
    """The bracketed kind, e.g. 'artifact:infra' / 'contamination', or None.
    Canonical parse (was re.match(r'^\\[([^\\]]+)\\]') copied in the dashboard)."""
    if not reason:
        return None
    m = _PREFIX_RE.match(reason)
    return m.group(1) if m else None


def subkind(reason):
    """The part after the colon, upper-cased for display (INFRA / HARNESS / SCORING)."""
    p = parse_prefix(reason)
    return (p.split(":")[-1].upper() if p else "SCORING")


def is_contamination(reason):
    return (parse_prefix(reason) or "") == CONTAMINATION


def is_infra(reason):
    return (parse_prefix(reason) or "") == ARTIFACT_INFRA


# --- reason BUILDERS (single source; was hand-built + divergent per tool) ---
def reason(kind, detail=""):
    """`[kind] detail` (the canonical reason-string shape)."""
    detail = (detail or "").strip()
    return f"[{kind}] {detail}".rstrip()


def infra(detail):
    """An [artifact:infra] exclusion reason (429 / timeout / disk / auth / serving)."""
    return reason(ARTIFACT_INFRA, detail)


def contamination(detail):
    return reason(CONTAMINATION, detail)


def harness(detail):
    return reason(ARTIFACT_HARNESS, detail)


# --- DB predicate helpers (optional; keep the SQL anti-joins consistent) ----
def excluded_ids(conn):
    """Set of evaluation_ids with ANY scoring exclusion."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='run_exclusion'").fetchone():
        return set()
    return {r[0] for r in conn.execute("SELECT evaluation_id FROM run_exclusion")}


def contamination_evalids(conn):
    """Set of evaluation_ids excluded specifically for contamination."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='run_exclusion'").fetchone():
        return set()
    return {r[0] for r in conn.execute(
        "SELECT evaluation_id FROM run_exclusion WHERE reason LIKE ?", (CONTAM_LIKE,))}
