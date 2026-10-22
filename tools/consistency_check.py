#!/usr/bin/env python3
"""Creds-free consistency linter for the zbench task corpus.

Checks each tasks/<task_id>/ folder for provenance drift between the machine-readable
meta.json (the source of truth the dashboard + tooling consume) and the
human-written card.md, plus structural gaps. Reports issues grouped by severity;
exits non-zero if any ERROR-level issue is found (handy for curation / CI).

Usage:
  python3 consistency_check.py [--tasks DIR] [--quiet]

Source-of-truth model: meta.json is authoritative for machine-consumed fields;
card.md is the human narrative. Most cards do NOT restate the coupling/solution-
path verdicts with '##' headers -- that is EXPECTED (meta is the primary store),
so it is NOT flagged. We only flag genuine drift/gaps.

Checks:
  ERROR  meta.json missing / invalid JSON
  ERROR  card.md missing
  ERROR  card <-> meta contradiction (coupling / solution-path / suitability
         leading verdict disagree)
  WARN   meta.review value is TODO/blank while the card HAS a value (stale meta)
  INFO   review field still TODO in meta and absent from card (not yet curated)

Repo-level checks (run once, not per task):
  WARN   a CURRENT-TRUTH doc states an "N validated" corpus count that disagrees
         with the canonical count derived from tasks/*/meta.json (finding #1)
  ERROR  a scoring tool re-declares EXCLUDE_AGENTS instead of sharing the
         canonical scoring.EXCLUDE_AGENTS (the drift that hid a retired
         agent from the exclusion set -- finding #10)
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # docs project root
ZBENCH_TASKS = ROOT / "zbench-tasks"
sys.path.insert(0, str(ZBENCH_TASKS))
DEF_TASKS = str(ZBENCH_TASKS / "tasks")

# CURRENT-TRUTH docs whose stated corpus count must track the live corpus.
_CURRENT_TRUTH_DOCS = [
    "METHODOLOGY.md",
    "AGENTS.md", "RUNBOOK.md",
]
# (PROJECT_REPORT.md is deliberately EXCLUDED: it is a POINT_IN_TIME snapshot with
# hand-frozen dated numbers, not a live-tracking doc -- so its counts must NOT be corpus-count-linted.)
# (the old leaderboard doc was removed 2026-07-30 -- the live dashboard is the canonical
# board now, with copy-as-markdown; the corpus count is derived from tasks/*/meta.json
# via corpus.py.)
# Only match statements that ASSERT the current corpus SIZE, to avoid false hits
# on task ids ("ZT-4609f0ab12cd validated"), ranges/targets ("15-20 validated"), or
# dated progress deltas. Two shapes: "...corpus... N validated" and "N validated
# zbench task(s)". N is 1-2 digits (a corpus count, never part of a task id).
_CORPUS_COUNT_PATS = [
    re.compile(r"[Cc]orpus(?![^.\n]*(?:target|~))[^.\n]{0,30}?(?<![-~\d])(\d{1,2})\s+validated\b"),
    re.compile(r"(?<![-~\d])(\d{1,2})\s+validated\s+zbench\s+tasks?\b"),
]


def check_corpus_count():
    """WARN if a current-truth doc asserts a corpus size that disagrees with
    tasks/*/meta.json (finding #1)."""
    issues = []
    try:
        import corpus
        canonical = len(corpus.validated_ids())
    except Exception as e:
        return [("WARN", "corpus-count", f"could not derive canonical count: {e}")]
    for name in _CURRENT_TRUTH_DOCS:
        p = ROOT / name
        if not p.exists():
            continue
        text = p.read_text(errors="replace")
        for pat in _CORPUS_COUNT_PATS:
            for m in pat.finditer(text):
                n = int(m.group(1))
                if n != canonical:
                    issues.append(("WARN", "corpus-count",
                                   f"{name} asserts '{m.group(0).strip()}' but canonical is "
                                   f"{canonical} (derive/link instead of restating)"))
    return issues


def check_invalidation_store():
    """Guard the validity-overlay model.

    W23 used accepted invalidation annotations as the scoring overlay. W37/W39 split
    comments/hints (`note`) from human scoring exclusions (`run_exclusion`). Keep the
    old anti-hardcoded-agent guard, but validate the new tables/migrated decisions
    instead of requiring agent-level invalidation overlays."""
    import re as _re
    issues = []
    # (1) no tool may re-introduce a hardcoded exclusion set
    for name, path in {"scoring.py": ZBENCH_TASKS / "scoring.py",
                       "bench_dashboard.py": ROOT / "tools" / "bench_dashboard.py"}.items():
        if path.exists() and _re.search(r"^\s*_?EXCLUDE_AGENTS\s*=", path.read_text(), _re.M):
            issues.append(("ERROR", "invalidation-store",
                           f"{name} reintroduced a hardcoded EXCLUDE_AGENTS set -- "
                           f"use agent-level annotations in the invalidation store instead"))
    # (2) W39 tables should exist and legacy broken/superseded decisions should have
    # been expanded into per-attempt run_exclusion rows.
    import sqlite3
    db = ROOT / "bench-db" / "bench.db"
    if not db.exists():
        return issues
    try:
        c = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("note", "run_exclusion"):
            if t not in tables:
                issues.append(("WARN", "validity-store", f"missing notes/exclusion table {t}; use the migrated facts-only bench.db"))
        if "run_exclusion" in tables:
            for agent, kind in (("claude-cli-haiku-4-5", "broken_config"),
                                ("claude-hermetic-fable", "superseded")):
                n = c.execute(
                    """SELECT COUNT(*) FROM run_exclusion rx JOIN attempt a USING(evaluation_id)
                       WHERE a.config_id=? AND rx.reason LIKE ?""",
                    (agent, f"[{kind}]%"),
                ).fetchone()[0]
                if n == 0:
                    issues.append(("WARN", "validity-store",
                                   f"no migrated run_exclusion decisions for {agent} prefix=[{kind}]"))
    except Exception as e:
        issues.append(("WARN", "validity-store", f"could not inspect W37 validity store: {e}"))
    finally:
        try:
            c.close()
        except Exception:
            pass
    return issues

def check_token_backfill():
    """W102: flag attempts whose tokens are missing in bench.db but RECOVERABLE from their
    session blob (db-vs-session drift -> self-healing via tools/backfill_tokens.py).
    Legitimately-missing (no session / no usage: no_patch, infra, pre-capture) are NOT
    flagged. Reuses backfill_tokens' extractors (one parser, no dup)."""
    import sqlite3
    issues = []
    db = ROOT / "bench-db" / "bench.db"
    if not db.exists():
        return issues
    try:
        import backfill_tokens
        db_root = db.resolve().parent
        c = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        # facts-only: no total_tokens/bundle_dir columns -> derive the token total from
        # in+out+cache_read, and the blob dir from the evaluation_id.
        rows = c.execute(
            "SELECT evaluation_id FROM attempt WHERE "
            "COALESCE(input_tokens,0)+COALESCE(output_tokens,0)+COALESCE(cache_read_tokens,0)=0"
        ).fetchall()
        c.close()
        recoverable = sum(1 for r in rows
                          for sp in [backfill_tokens._session_for(db_root, f"blobs/attempt/{r['evaluation_id']}")]
                          if sp and backfill_tokens._sum_usage(sp))
        if recoverable:
            issues.append(("WARN", "token-accounting",
                           f"{recoverable} attempt(s) have missing tokens in bench.db but a "
                           f"RECOVERABLE session snapshot -- run tools/backfill_tokens.py --apply"))
    except Exception as e:
        issues.append(("WARN", "token-accounting", f"could not run token-backfill check: {e}"))
    return issues


def _jsonl(path: Path):
    out = []
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def check_agent_matrix():
    """Single source guard for the active ranked/fill cohort.

    `agents-matrix.jsonl` is the execution source of truth for the active ranked cohort;
    `agents-meta.jsonl` is metadata only. This catches the W117/DeepSeek-Flash bug where an
    agent with near-full board coverage lived only in a sidecar shard and therefore was not
    filled for a new task.
    """
    issues = []
    matrix_p = ZBENCH_TASKS / "agents-matrix.jsonl"
    meta_p = ZBENCH_TASKS / "agents-meta.jsonl"
    try:
        matrix = _jsonl(matrix_p)
        meta = _jsonl(meta_p)
    except Exception as e:
        return [("ERROR", "agent-matrix", f"could not parse agents jsonl: {e}")]
    mids = [r.get("agent_id") for r in matrix]
    mset = set(mids)
    dup = sorted({x for x in mids if mids.count(x) > 1})
    if dup:
        issues.append(("ERROR", "agent-matrix", f"duplicate agent_id(s) in agents-matrix: {dup}"))
    meta_ids = {r.get("agent_id") for r in meta}
    missing_meta = sorted(mset - meta_ids)
    if missing_meta:
        issues.append(("ERROR", "agent-matrix", f"agents-matrix ids missing from agents-meta: {missing_meta}"))

    # Retired sidecar subsets (agents-fireworks/local/glm) should not come back;
    # use --only/--exclude selectors against agents-matrix.jsonl instead.
    for retired in ("agents-fireworks.jsonl", "agents-local-ds4f.jsonl", "agents-local-qwen-only.jsonl",
                    "agents-glm-only.jsonl", "agents-glm-462413.jsonl", "agents-local.jsonl"):
        if (ZBENCH_TASKS / retired).exists():
            issues.append(("WARN", "agent-matrix", f"retired agent subset file still exists: {retired}; use agents-matrix + selectors"))

    # DB-based catch: an agent with coverage close to the validated corpus is de facto active.
    db = ROOT / "bench-db" / "bench.db"
    if db.exists():
        import sqlite3
        try:
            import corpus
            n_valid = len(corpus.load_corpus("validated"))
            threshold = max(1, int(0.8 * n_valid))
            conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
            rows = conn.execute(
                """SELECT config_id, COUNT(DISTINCT task_id) AS n
                   FROM attempt a
                   WHERE config_id IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM run_exclusion rx WHERE rx.evaluation_id=a.evaluation_id)
                   GROUP BY config_id""").fetchall()
            conn.close()
            # control-* are Phase-6 negative-control fixtures (zbench-tasks/controls/):
            # they run through the real harness to prove the guardrails but are never
            # ranked, so they are legitimately absent from agents-matrix.
            high = sorted((cid, n) for cid, n in rows
                          if n >= threshold and cid not in mset and not cid.startswith("control-"))
            if high:
                issues.append(("ERROR", "agent-matrix",
                               f"high-coverage active agent(s) missing from agents-matrix (threshold {threshold}/{n_valid}): {high}"))
        except Exception as e:
            issues.append(("WARN", "agent-matrix", f"could not run DB coverage guard: {e}"))
    return issues


def check_single_store():
    """Eradication guard (single-store cutover 2026-07-28): no LIVE tool may read the
    retired file stores -- bench.db is the single store. ERROR if a live tool still
    references scores.jsonl / events.jsonl / contamination_audit / data/cells.
    Exempt: this linter (which names the patterns to forbid them)."""
    issues = []
    forbidden = ["scores.jsonl", "events.jsonl", "contamination_audit", "data/cells"]
    exempt = {"consistency_check.py"}
    for base in (ZBENCH_TASKS, ROOT / "tools"):
        for py in sorted(base.glob("*.py")):
            if py.name in exempt:
                continue
            text = py.read_text(errors="replace")
            for pat in forbidden:
                if pat in text:
                    issues.append(("ERROR", "single-store",
                                   f"{py.name} references retired store '{pat}' -- "
                                   f"bench.db is the single store (read via benchdb_reader "
                                   f"/ scoring / _benchdb_attempts)"))
    return issues


# meta.review key -> card.md header regex
_REVIEW_FIELDS = {
    "suitability": r'^##\s*Suitability:\s*(.+)$',
    "test_coupling_risk": r'^##\s*Test coupling[^:]*:\s*(.+)$',
    "solution_path_specificity": r'^##\s*Solution-path specificity:\s*(.+)$',
}
_BLANK = {None, "", "TODO"}


def _card_grab(text, pattern):
    m = re.search(pattern, text, re.I | re.M)
    return m.group(1).strip() if m else None


def _verdict(v):
    """Leading token used for contradiction comparison (LOW / MED-HIGH / KEEP...)."""
    return (str(v).split(" (")[0].split()[0].upper()) if v else ""


def check_task(td: Path):
    """Return list of (severity, field, message) for one task dir."""
    issues = []
    metap, cardp = td / "meta.json", td / "card.md"

    meta = None
    if not metap.exists():
        issues.append(("ERROR", "meta.json", "missing meta.json"))
    else:
        try:
            meta = json.loads(metap.read_text())
        except json.JSONDecodeError as e:
            issues.append(("ERROR", "meta.json", f"invalid JSON: {e}"))
            meta = None

    if meta is None:
        return issues

    status = (meta.get("curation_status") or "").strip()
    valid_statuses = {"validated", "held", "invalid", "dropped"}
    if status not in valid_statuses:
        issues.append(("ERROR", "curation_status", f"missing/invalid curation_status {status!r}"))
    if not meta.get("reason"):
        issues.append(("WARN", "reason", "missing short curation/disposition reason in meta.json"))
    if not meta.get("reason_code"):
        issues.append(("WARN", "reason_code", "missing normalized reason_code in meta.json"))

    # gold_code.patch is the ANSWER KEY: it lives in zbench-tasks/solutions/<id>/, not in
    # the task dir (zbench-tasks/config.py). _artifact() resolves either layout so a
    # corpus prepared before the split still passes this check.
    def _artifact(name):
        if name == "gold_code.patch":
            split = td.parent.parent / "solutions" / td.name / name
            return split if split.exists() else (td / name)
        return td / name

    artifact_names = ["card.md", "problem_statement.md", "instance.jsonl", "gold_code.patch", "gold_test.patch"]
    required_validated = ["card.md", "instance.jsonl", "gold_code.patch", "gold_test.patch"]
    has_any_artifact = any(_artifact(n).exists() for n in artifact_names)
    has_required_validated = all(_artifact(n).exists() for n in required_validated)
    if status == "validated" and not has_required_validated:
        missing = [n for n in required_validated if not _artifact(n).exists()]
        issues.append(("ERROR", "task-artifacts", "validated task missing " + ", ".join(missing)))
    if status in {"held", "invalid"} and has_any_artifact and not cardp.exists():
        issues.append(("WARN", "card.md", f"{status} prepped candidate has artifacts but no card.md"))
    if status in {"invalid", "dropped"} and not (meta.get("evidence") or meta.get("source")):
        issues.append(("WARN", "evidence", f"{status} candidate should cite source/evidence provenance"))

    card = cardp.read_text() if cardp.exists() else ""
    review = meta.get("review", {}) or {}

    if not card:
        return issues

    # review fields: only flag genuine drift.
    #  - both set + disagree            -> ERROR (contradiction)
    #  - card set but meta TODO/blank   -> WARN  (stale meta; backfill from card)
    #  - meta set, card has no header   -> OK    (normal; meta is the primary store)
    #  - neither set                    -> INFO  (not yet curated)
    for mk, pat in _REVIEW_FIELDS.items():
        mv = review.get(mk)
        cv = _card_grab(card, pat)
        m_set, c_set = mv not in _BLANK, bool(cv)
        if m_set and c_set and _verdict(mv) != _verdict(cv):
            issues.append(("ERROR", mk, f"contradiction: meta={mv!r} vs card={cv!r}"))
        elif c_set and not m_set:
            issues.append(("WARN", mk, f"meta is {mv!r} but card says {cv!r} -> backfill meta from card"))
        elif not m_set and not c_set:
            issues.append(("INFO", mk, "not yet curated"))

    # --- stale-content checks (W17): narrative that big cycle-changes can stale ---
    status = (meta.get("curation_status") or "").strip()
    oracle = str((review.get("oracle") or "")).upper()
    blob = (card or "") + "\n" + json.dumps(meta)
    if card and "BLOCKED on C++ verifier" in card:
        issues.append(("WARN", "stale-card", "card says 'BLOCKED on C++ verifier' -- "
                       "the C++ runtests verifier exists (W1/W16); update the note"))
    if "graded_leaderboard" in blob or "failure-rung" in blob.lower():
        issues.append(("WARN", "stale-card", "references the RETIRED graded/rung board "
                       "(graded_leaderboard.py); binary resolve is the sole metric now"))
    if status == "validated" and (not oracle or "PENDING" in oracle or not oracle.startswith("VALID")):
        issues.append(("WARN", "stale-meta", f"curation_status=validated but review.oracle "
                       f"does not affirm VALID (got {oracle[:30]!r}); an oracle-sound task "
                       f"should record its FAIL@base/PASS@fix verdict"))

    return issues


def check_dashboard_icons():
    """Dashboard design-system regression guard (SoT: bench_dashboard.py): ONE icon language
    (Material Design inline-SVG via icon()/mdi()). No emoji / geometric-char / entity
    GLYPHS as icons. Flag if any migrated icon-glyph reappears in bench_dashboard.py
    (outside python comments). Permitted: \u2713 / \u26a0 transient button microcopy in
    JS string literals; typographic entities (&mdash; &middot; &rarr; &ndash; ...)."""
    dash = Path(__file__).resolve().parent / "bench_dashboard.py"
    if not dash.exists():
        return []
    # HTML numeric entities for the emoji/dingbat icons we migrated to MDI.
    banned_entities = ["&#9989;", "&#10060;", "&#9888;", "&#9940;", "&#8635;",
                       "&#11123;", "&#9881;", "&#8856;", "&#9680;", "&#9203;",
                       "&#9201;", "&#10067;", "&#65039;",
                       "&#128203;", "&#8681;",  # W82: clipboard + down-arrow (-> MDI)
                       "&#128221;"]             # W119: memo/notes emoji (-> MDI note/edit)
    # raw emoji / pictographic codepoints that must not be used as icons.
    banned_chars = ["\u2699", "\u23f3", "\u2705", "\u274c", "\u2620", "\u267b",
                    "\u2b73", "\u2698", "\ufe0f", "\U0001f4cb", "\U0001f4dd", "\u2b07"]
    issues = []
    for i, line in enumerate(dash.read_text().splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # python comment
        hit = [g for g in banned_entities if g in line] + [
            repr(g) for g in banned_chars if g in line]
        if hit:
            issues.append(("WARN", "dashboard-icons",
                           f"bench_dashboard.py:{i} uses non-MDI icon glyph(s) {hit} "
                           f"-- use icon()/mdi() (one icon language; see the "
                           f"design-system header in bench_dashboard.py)"))
    return issues


def check_reduction_hygiene():
    """Warn on the reduction-bloat classes that are cheap to validate mechanically:
    retired current-truth paths, exact duplicate large artifacts, and a frontier that
    starts accumulating DONE narrative again. Keep this conservative; prose judgment
    stays human-owned."""
    import hashlib
    issues = []

    # Current-truth docs/comments must not point at retired paths or status models.
    current = [ROOT / p for p in ("AGENTS.md", "METHODOLOGY.md", "PROJECT_REPORT.md",
                                  "RUNBOOK.md", "tools/README.md",
                                  "tools/bench_dashboard.py", "tools/benchdb_reader.py")]
    for p in current:
        if not p.exists():
            continue
        txt = p.read_text(errors="replace")
        if ("pure" + "bench/benchdb/schema.sql") in txt:
            issues.append(("WARN", "reduction-hygiene",
                           f"{p.relative_to(ROOT)} references a retired schema path; use zbench/schema.sql"))
        if "corpus_status" in txt or "non-corpus-retired" in txt or "disposition.md" in txt:
            issues.append(("WARN", "candidate-records",
                           f"{p.relative_to(ROOT)} references retired candidate status wording; use curation_status/task meta"))

    retired_mining = [
        "candidate-verdicts.md", "brian-area-candidates-2026-07-30.md",
        "funnel_2026-07-30.md", "w28-cpp-candidate-triage-2026-07-29.md",
        "triage-clean-hydrogen-2026-07-30.txt", "funnel_analysis.py",
        "mined-2026-07-28.tsv", "mined-2026-07-28-w28-hftl-ublk.tsv",
        "mined-2026-08-02.tsv", "mined-2026-08-02.err",
        "mined-2026-08-05.tsv", "mined-2026-08-05.err",
    ]
    for rel in retired_mining:
        if (ZBENCH_TASKS / "mining-runs" / rel).exists():
            issues.append(("WARN", "mining-history",
                           f"retired mining provenance remains in working tree: mining-runs/{rel}; status belongs in tasks/<task_id>/meta.json"))
    # TSV candidate SOURCES are retired entirely -- discovery reads git live (mine_candidates.mine()).
    # Flag any cached candidate TSV reappearing (mining-runs snapshots or curated shortlists).
    stale_tsv = list((ZBENCH_TASKS / "mining-runs").glob("*.tsv")) + list(ZBENCH_TASKS.glob("curated_*_shortlist.tsv"))
    for p in stale_tsv:
        issues.append(("WARN", "mining-history",
                       f"candidate TSV reappeared ({p.relative_to(ROOT)}); discovery is a live git read -- "
                       f"no cached TSV. Remove it; candidate status lives in tasks/<task_id>/meta.json"))
    if list((ZBENCH_TASKS / "tasks").glob("*/disposition.md")):
        issues.append(("WARN", "candidate-records", "disposition.md files found; curation status/reason belongs in meta.json"))

    # Exact duplicate tracked non-code artifacts over 100KB are usually stale aliases.
    try:
        import subprocess
        files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        by_hash = {}
        for rel in files:
            p = ROOT / rel
            if not p.is_file() or p.suffix in {".py", ".js", ".css", ".html"}:
                continue
            if p.stat().st_size < 100_000:
                continue
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            by_hash.setdefault(h, []).append(rel)
        for group in by_hash.values():
            if len(group) > 1:
                issues.append(("WARN", "duplicate-artifact", "exact duplicate large tracked files: " + ", ".join(sorted(group))))
    except Exception as e:
        issues.append(("WARN", "duplicate-artifact", f"could not scan duplicate artifacts: {e}"))

    return issues


def _dashboard_event_stage_keys():
    path = ROOT / "tools" / "bench_dashboard.py"
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "EVENT_STAGE":
                    return set(ast.literal_eval(node.value).keys())
    return set()


def _source_record_event_phases():
    phases = set()
    for path in (ROOT / "zbench").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or len(node.args) < 4:
                continue
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
            if name == "record_event" and isinstance(node.args[3], ast.Constant) and isinstance(node.args[3].value, str):
                phases.add(node.args[3].value)
    return phases


def check_event_stage_mapping():
    """Every current attempt_event phase emitted by zbench must map to a visual
    pipeline stage. Otherwise the /run page dumps chronological middle events into
    the trailing 'other events' box (the verify_started vs verification_started bug)."""
    issues = []
    mapped = _dashboard_event_stage_keys()
    emitted = _source_record_event_phases()
    db = ROOT / "bench-db" / "bench.db"
    if db.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
            emitted |= {r[0] for r in conn.execute("SELECT DISTINCT phase FROM attempt_event") if r[0]}
            conn.close()
        except Exception as e:
            issues.append(("WARN", "event-stage", f"could not inspect attempt_event phases: {e}"))
    unmapped = sorted(p for p in emitted if p not in mapped and not str(p).startswith("legacy:"))
    if unmapped:
        issues.append(("ERROR", "event-stage",
                       "attempt_event phase(s) lack dashboard pipeline mapping: " + ", ".join(unmapped)))
    return issues


def check_doc_tiers():
    """Current top-level/hub docs should declare their plane/currency/owner header so
    prose checks can stay metadata-driven instead of guessing a doc's audience."""
    docs = ["AGENTS.md", "RUNBOOK.md", "PROJECT_REPORT.md", "METHODOLOGY.md",
            "GLOSSARY.md", "UI_DESIGN.md",
            "tools/README.md", "zbench-tasks/README.md", "zbench/README.md"]
    issues = []
    for name in docs:
        p = ROOT / name
        if not p.exists():
            issues.append(("WARN", "doc-tier", f"expected current doc missing: {name}"))
            continue
        head = "\n".join(p.read_text(errors="replace").splitlines()[:6])
        if "Plane:" not in head or "Currency:" not in head or "Owner:" not in head:
            issues.append(("WARN", "doc-tier", f"{name} lacks Plane/Currency/Owner header"))
    return issues


# Needles are assembled from fragments so this file does not itself spell them out.
_LEGACY_NAME_RE = re.compile(
    "|".join(["pure" + "storage", "pure" + "route", "pure" + "-forks", "ral" + "varez",
              "d" + "gx", "pure" + "bench", "case" + "cade-auto"]), re.I)


def check_no_legacy_names():
    """The rename-completeness invariant: the retarget from the original private codebase
    to Zulip must never regress. NO tracked text file may contain a legacy internal name.
    Zero hits, no allowlist (this file exempts only itself: it carries the needles)."""
    issues = []
    exts = (".py", ".sh", ".md", ".sql", ".jsonl", ".puml", ".json")
    SKIP = {".git", ".venv", "node_modules", "__pycache__", "blobs", ".runtime",
            "bench-db", ".pytest_cache"}
    EXEMPT_FILES = {"consistency_check.py",   # this guard's own needle list
                    "test_classifiers.py"}    # asserts these needles are ABSENT from the sigs
    # Honor .gitignore: the invariant is about TRACKED source (see docstring), so an
    # untracked, git-ignored artifact dropped in the tree (e.g. a vendored install.sh whose
    # gateway URL carries a legacy substring) must not trip it. `ls-files --others --ignored`
    # lists ONLY untracked+ignored paths; tracked files are always still scanned.
    ignored: set = set()
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--others", "--ignored", "--exclude-standard"],
            capture_output=True, text=True, check=False).stdout
        ignored = {(ROOT / ln).resolve() for ln in out.splitlines() if ln.strip()}
    except Exception:
        pass
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP]
        for f in fn:
            if not f.endswith(exts) or f in EXEMPT_FILES:
                continue
            p = Path(dp) / f
            if p.resolve() in ignored:
                continue
            try:
                for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    m = _LEGACY_NAME_RE.search(line)
                    if m:
                        issues.append(("ERROR", "legacy-name",
                                       f"{p.relative_to(ROOT)}:{i} contains legacy name "
                                       f"{m.group(0)!r} -- the Zulip retarget must not regress"))
                        break                     # one report per file is enough
            except Exception:
                pass
    return issues


def check_no_old_checkout_refs():
    """Superseded by check_no_legacy_names (kept as an alias so existing callers and
    test_static_invariants keep working)."""
    return check_no_legacy_names()


def check_doc_code_refs():
    """Stale-reference guard (SURFACE, don't decide): a current-truth doc must not
    cite a code artifact (*.py/*.jsonl/*.sql) that no longer exists anywhere in the
    repo or the harness checkout. A stale path can REGRESS implementation -- an agent
    may "fix" code to match a doc that names a dead file. WARN-only: it flags the
    doc-vs-code drift for a human to adjudicate which side is right."""
    # spec-like docs only.
    docs = ["METHODOLOGY.md", "PROJECT_REPORT.md", "AGENTS.md", "RUNBOOK.md",
            "tools/README.md", "zbench-tasks/README.md", "zbench/README.md"]
    roots = [ROOT]
    SKIP = {".git", ".venv", "node_modules", "__pycache__", "blobs", ".runtime",
            "bench-db", ".pytest_cache"}
    have = set()
    for root in roots:
        if not root.exists():
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP]
            for f in fn:
                if f.endswith((".py", ".jsonl", ".sql")):
                    have.add(f)
    # retired stores + per-attempt runtime evidence artifacts (not source files)
    SKIP_REFS = {"scores.jsonl", "events.jsonl", "session.jsonl", "rawcli.jsonl"}
    pat = re.compile(r"`([\w./-]+\.(?:py|jsonl|sql))`")
    issues = []
    for name in docs:
        p = ROOT / name
        if not p.exists():
            continue
        seen = set()
        for m in pat.finditer(p.read_text(errors="replace")):
            ref = m.group(1)
            if "*" in ref:
                continue
            base = ref.rsplit("/", 1)[-1]
            if base in seen or base in SKIP_REFS:
                continue
            seen.add(base)
            if base not in have:
                issues.append(("WARN", "stale-ref",
                               f"{name} cites `{ref}` but no file named {base} exists in "
                               f"the repo or harness checkout -- stale reference? "
                               f"(reconcile doc vs code before trusting the doc)"))
    return issues


def check_price_fields():
    """W137: every model we USE must have all of its models.dev cost fields priced by model_prices
    (else we silently under/over-count -- e.g. the cache_write omission). Allowlisted fields
    (tiers/context_over_200k) are known-unactionable with aggregate per-attempt tokens. ERROR on an
    unpriced field on a model we actually run."""
    issues = []
    try:
        import model_prices as mp
        agents = _jsonl(ZBENCH_TASKS / "agents-matrix.jsonl")
        used = {k for a in agents for k in [mp.price_key(a.get("agent_id", ""))] if k}
        for k in sorted(used):
            gap = mp.unpriced_cost_fields(k)
            if gap:
                issues.append(("ERROR", "price_fields",
                               f"{k}: models.dev cost has field(s) {sorted(gap)} that cost_usd() does "
                               f"not price (add them or allowlist as unactionable)"))
    except Exception as e:
        issues.append(("WARN", "price_fields", f"could not check ({e})"))
    return issues


def check_selfhosted_price():
    """2026-08-18: every self-hosted OPEN-WEIGHT model we RUN should resolve to a public-host
    reference price (models_dev.json / open_weight_hosted.json), else it reads as free* and wins
    cost ties by construction. A model with no public reference yet is a WARN (tools/price_search.py
    re-checks daily and fills it). Replaces the removed capex-amortization arch check."""
    issues = []
    try:
        import model_prices as mp
        meta_model = {d.get("agent_id"): d.get("model")
                      for d in _jsonl(ZBENCH_TASKS / "agents-meta.jsonl") if d.get("agent_id")}
        seen = set()
        for a in _jsonl(ZBENCH_TASKS / "agents-matrix.jsonl"):
            aid = a.get("agent_id", "")
            if not mp.is_self_hosted(aid):
                continue
            model = meta_model.get(aid)
            if model in seen:
                continue
            seen.add(model)
            if mp.price_key(aid) is None:
                issues.append(("WARN", "selfhosted_price",
                               f"{aid}: self-hosted model '{model}' has no public reference price yet "
                               f"-> reads as free*. price_search.py re-checks daily; or pin a rate in "
                               f"prices/open_weight_hosted.json."))
    except Exception as e:
        issues.append(("WARN", "selfhosted_price", f"could not check ({e})"))
    return issues


# W137(a): EXPLAINED cross-check divergences. The canonical cost is OUR models.dev, TTL-aware
# computation; the harness cost is only an independent reference. It reconciles to ~0% for
# opus-5 / fable / haiku / pi-anthropic (which validates our calc), but claude-code's SELF-REPORTED
# cost for the OLDER opus ids is a client-side estimate off a higher internal price table (verified
# 2026-08-10: models.dev lists all opus generations at one flat rate, opus-5 reconciles, the older
# ones ran contemporaneously yet diverge, and no token-capture gap exists -- 0 zero-token attempts).
# So these are a harness-reference quirk, not a bug in our number. Allowlisted -> INFO (kept VISIBLE,
# not suppressed) as long as the divergence stays within the observed band; a NEW agent, or one of
# these exceeding its cap, still WARNs (guards a real regression).
_CROSSCHECK_EXPLAINED = {
    # config_id: (max_expected_dev, reason)
    "claude-cli-opus-4-6": (0.35, "claude-code self-reported estimate off a higher internal price table for older opus"),
    "claude-cli-opus-4-7": (0.15, "claude-code self-reported estimate off a higher internal price table for older opus"),
    "claude-cli-opus-4-8": (0.18, "claude-code self-reported estimate off a higher internal price table for older opus"),
}


def check_cost_crosscheck():
    """W137: for agents that carry a harness-reported cost (direct-Anthropic: claude-cli / pi-anthropic),
    the computed (models.dev, TTL-aware) cost must match within tolerance -- this calibrates the same
    calc used for the un-referenced Foundry/local agents. Post the TTL fix the residual is ~0-1% and
    validates our calc on opus-5/fable/haiku/pi-anthropic; the older-opus divergence is an EXPLAINED
    harness-side estimate quirk (see _CROSSCHECK_EXPLAINED) reported as INFO. Unexplained drift >5% WARNs."""
    import sqlite3
    TOL = 0.05
    issues = []
    db = ROOT / "bench-db" / "bench.db"
    if not db.exists():
        return issues
    try:
        import model_prices as mp
        c = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
        rows = c.execute(
            "SELECT a.config_id, SUM(a.input_tokens), SUM(a.output_tokens), "
            "SUM(a.cache_read_tokens), SUM(a.cache_write_tokens), SUM(a.cost_usd) "
            "FROM attempt a LEFT JOIN run_exclusion x ON x.evaluation_id=a.evaluation_id "
            "WHERE x.evaluation_id IS NULL AND a.cost_usd>0 "
            "AND (a.config_id LIKE 'claude-cli-%' OR a.config_id LIKE 'pi-anthropic-%') "
            "GROUP BY a.config_id").fetchall()
        c.close()
        for cid, it, ot, cr, cw, rep in rows:
            comp = mp.cost_usd(cid, it, ot, cr, cw)
            if comp is None or not rep:
                continue
            dev = abs(comp - rep) / rep
            if dev <= TOL:
                continue
            cap, reason = _CROSSCHECK_EXPLAINED.get(cid, (None, None))
            if cap is not None and dev <= cap:
                issues.append(("INFO", "cost_crosscheck",
                               f"{cid}: computed ${comp:.2f} vs harness ${rep:.2f} "
                               f"({dev*100:.0f}% -- explained: {reason}; canonical = computed)"))
            else:
                extra = "" if cap is None else f" -- EXCEEDS explained band {cap*100:.0f}%"
                issues.append(("WARN", "cost_crosscheck",
                               f"{cid}: computed ${comp:.2f} vs harness ${rep:.2f} "
                               f"({dev*100:.0f}% > {TOL*100:.0f}%{extra} -- unexplained; investigate)"))
    except Exception as e:
        issues.append(("WARN", "cost_crosscheck", f"could not check ({e})"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=DEF_TASKS)
    ap.add_argument("--quiet", action="store_true", help="suppress INFO lines")
    args = ap.parse_args()
    root = Path(args.tasks)
    # task dirs are prefix-agnostic: a task record = a directory containing meta.json
    tasks = sorted(p.parent for p in root.glob("*/meta.json"))
    if not tasks:
        print(f"no tasks under {root}")
        return 2

    sev_rank = {"ERROR": 0, "WARN": 1, "INFO": 2}
    icon = {"ERROR": "\u274c", "WARN": "\u26a0\ufe0f", "INFO": "\u2022"}
    counts = {"ERROR": 0, "WARN": 0, "INFO": 0}
    tasks_with_issues = 0

    # repo-level checks (once, not per task)
    repo_issues = (check_corpus_count() + check_invalidation_store()
                   + check_agent_matrix() + check_single_store() + check_dashboard_icons()
                   + check_reduction_hygiene() + check_event_stage_mapping()
                   + check_doc_tiers() + check_doc_code_refs() + check_token_backfill()
                   + check_no_old_checkout_refs() + check_price_fields() + check_cost_crosscheck()
                   + check_selfhosted_price())
    if args.quiet:
        repo_issues = [i for i in repo_issues if i[0] != "INFO"]
    if repo_issues:
        print("\n[repo-level]")
        for sev, fld, msg in sorted(repo_issues, key=lambda i: sev_rank[i[0]]):
            counts[sev] += 1
            print(f"  {icon[sev]} [{sev}] {fld}: {msg}")

    for td in tasks:
        issues = check_task(td)
        if args.quiet:
            issues = [i for i in issues if i[0] != "INFO"]
        for sev, *_ in issues:
            counts[sev] += 1
        shown = [i for i in issues if not (args.quiet and i[0] == "INFO")]
        if shown:
            tasks_with_issues += 1
            print(f"\n{td.name}")
            for sev, fld, msg in sorted(shown, key=lambda i: sev_rank[i[0]]):
                print(f"  {icon[sev]} [{sev}] {fld}: {msg}")

    print(f"\n{'='*60}")
    print(f"{len(tasks)} tasks | {tasks_with_issues} with issues | "
          f"{counts['ERROR']} ERROR, {counts['WARN']} WARN, {counts['INFO']} INFO")
    return 1 if counts["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main())
