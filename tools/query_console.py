#!/usr/bin/env python3
"""Read-only SQL query console over bench.db (self-serve ad-hoc analysis).

A companion to the ranking board (bench_dashboard.py, :8787). The board is a
CURATED view; this is a free-query surface: type SQL, get a results table, export
CSV/JSON. It writes NOTHING to bench.db -- the connection is opened read-only
(mode=ro) AND `PRAGMA query_only=ON`, and only single read statements are allowed.

Reuses the dashboard's DB-access layer so the useful joins are pre-wired:
  * benchdb_reader._connect       -- bench.db opened read-only + TEMP dim DDL
  * benchdb_reader._load_task_temp / _load_agent_temp  -- fill TEMP task/agent dims
  * exclusions.NOT_EXCLUDED_SQL   -- the scoring anti-join (the `scored` flag)

On top of the raw tables it exposes two convenience views:
  * v_attempt -- attempt + agent + task + run, with `resolved` and `scored`
  * v_run     -- one row per run with n_attempts / n_resolved / cost

The only file this tool writes is a sidecar JSON of user-saved queries under
bench-db/.runtime/ -- never bench.db.

Run: python3 tools/query_console.py [--port 8789] [--host 127.0.0.1]
     [--benchdb PATH] [--tasks DIR]
Binds 127.0.0.1:8789 by default (read-only, no auth). For remote viewing prefer an
SSH tunnel: ssh -L 8789:127.0.0.1:8789 <host>.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "zbench-tasks"))

import benchdb_reader  # noqa: E402  reuse: read-only connect + TEMP dim loaders
import exclusions       # noqa: E402  reuse: scoring anti-join (the `scored` flag)
import ranking_view     # noqa: E402  reuse: the D1-D5 board core (v_board = the :8787 board)
try:
    import corpus       # noqa: E402  validated-corpus ids (restricts the common set)
except Exception:       # corpus optional; v_board still builds without the restriction
    corpus = None
from zbench import constants  # noqa: E402  instance_of() identity helper

# ---- defaults (override with flags / env) --------------------------------
DEFAULT_DB = Path(os.environ.get("ZBENCH_BENCHDB_DIR", str(ROOT / "bench-db"))) / "bench.db"
DEFAULT_TASKS = Path(os.environ.get("ZBENCH_TASKS", str(ROOT / "zbench-tasks" / "tasks")))
BENCHDB = str(DEFAULT_DB)
TASKS = DEFAULT_TASKS
SAVED_PATH = Path(DEFAULT_DB).parent / ".runtime" / "query_console_saved.json"

ROW_CAP = 5000        # max rows returned to the browser (fetch cap+1 to flag more)
TIMEOUT_S = 10.0      # wall-clock ceiling per query (progress-handler interrupt)

# statements we serve: a single read. First keyword must be one of these.
_ALLOWED_FIRST = {"select", "with", "explain", "pragma"}


# ---- built-in saved queries (the recurring analyses) ---------------------
# Each: {name, description, sql}. Shown read-only in the sidebar; user saves go to
# SAVED_PATH and are editable/deletable. All lean on the v_attempt / v_run views.
DEFAULT_QUERIES = [
    {
        "name": "Leaderboard (matches the :8787 board)",
        "description": ("The official ranked board: one row per agent, scored on the COMMON "
                        "task set (n = common_total), controls + under-covered agents removed. "
                        "Identical to the dashboard. Use v_board for board numbers."),
        "sql": (
            "SELECT rank, agent_id, model_name, provider,\n"
            "       resolve_rate, n, ROUND(cost_per_task, 3) AS cost_per_task\n"
            "FROM v_board\n"
            "WHERE ranked = 1\n"
            "ORDER BY rank;"
        ),
    },
    {
        "name": "Resolve rate per agent (RAW, not the board)",
        "description": ("Exploration only. AVG over each agent's OWN covered tasks (denominator "
                        "differs per agent), one row per config_id. This does NOT match the "
                        "board -- it ignores the common set + membership filters. See v_board."),
        "sql": (
            "WITH cell AS (\n"
            "  SELECT config_id, task_id, MAX(model_name) AS model_name,\n"
            "         AVG(resolved) AS cell_resolved\n"
            "  FROM v_attempt\n"
            "  WHERE scored = 1 AND model_name IS NOT NULL AND config_id NOT LIKE 'control-%'\n"
            "  GROUP BY config_id, task_id)   -- one row per agent x task (collapses retries)\n"
            "SELECT config_id, model_name,\n"
            "       ROUND(AVG(cell_resolved), 3) AS resolve_rate,\n"
            "       COUNT(*) AS n_tasks\n"
            "FROM cell\n"
            "GROUP BY config_id, model_name\n"
            "HAVING n_tasks >= 10\n"
            "ORDER BY resolve_rate DESC;"
        ),
    },
    {
        "name": "Cost per task by model",
        "description": "Total and average $/attempt per model (scored attempts).",
        "sql": (
            "SELECT model_name,\n"
            "       COUNT(*) AS n_attempts,\n"
            "       ROUND(SUM(cost_usd), 2) AS total_cost_usd,\n"
            "       ROUND(AVG(cost_usd), 4) AS avg_cost_usd\n"
            "FROM v_attempt\n"
            "WHERE scored = 1 AND cost_usd IS NOT NULL\n"
            "GROUP BY model_name\n"
            "ORDER BY total_cost_usd DESC;"
        ),
    },
    {
        "name": "Coverage (attempts per model x task)",
        "description": "How many scored attempts each model has per task. Gaps = 0.",
        "sql": (
            "SELECT model_name,\n"
            "       COUNT(DISTINCT task_id) AS tasks_covered,\n"
            "       COUNT(*) AS attempts\n"
            "FROM v_attempt\n"
            "WHERE scored = 1 AND model_name IS NOT NULL\n"
            "GROUP BY model_name\n"
            "ORDER BY tasks_covered DESC, attempts DESC;"
        ),
    },
    {
        "name": "No-patch triage",
        "description": "Attempts that produced no patch, by model and outcome.",
        "sql": (
            "SELECT model_name, outcome, status, COUNT(*) AS n\n"
            "FROM v_attempt\n"
            "WHERE outcome LIKE 'no_patch%' OR status LIKE 'no_patch%'\n"
            "GROUP BY model_name, outcome, status\n"
            "ORDER BY n DESC;"
        ),
    },
    {
        "name": "Tokens by model",
        "description": "Total input/output tokens and turns per model (scored).",
        "sql": (
            "SELECT model_name,\n"
            "       COUNT(*) AS n_attempts,\n"
            "       SUM(input_tokens)  AS input_tokens,\n"
            "       SUM(output_tokens) AS output_tokens,\n"
            "       ROUND(AVG(turns), 1) AS avg_turns\n"
            "FROM v_attempt\n"
            "WHERE scored = 1 AND model_name IS NOT NULL\n"
            "GROUP BY model_name\n"
            "ORDER BY output_tokens DESC;"
        ),
    },
    {
        "name": "Run summary",
        "description": "One row per run: attempts, resolved, cost. Newest first.",
        "sql": (
            "SELECT run_id, label, started_at, n_attempts, n_resolved,\n"
            "       ROUND(cost_usd, 2) AS cost_usd\n"
            "FROM v_run\n"
            "ORDER BY started_at DESC;"
        ),
    },
    {
        "name": "Hard tasks (low resolver count)",
        "description": "Resolve rate per task; surfaces 0-2 resolver tasks for review.",
        "sql": (
            "SELECT task_id, issue_type, component,\n"
            "       COUNT(DISTINCT CASE WHEN resolved = 1 THEN model_name END) AS n_models_resolved,\n"
            "       COUNT(DISTINCT model_name) AS n_models_tried,\n"
            "       ROUND(AVG(resolved), 3) AS resolve_rate\n"
            "FROM v_attempt\n"
            "WHERE scored = 1 AND model_name IS NOT NULL\n"
            "GROUP BY task_id, issue_type, component\n"
            "ORDER BY n_models_resolved ASC, resolve_rate ASC;"
        ),
    },
    {
        "name": "Excluded attempts by reason",
        "description": "Rows removed from scoring (run_exclusion), grouped by reason.",
        "sql": (
            "SELECT rx.reason, COUNT(*) AS n\n"
            "FROM run_exclusion rx\n"
            "GROUP BY rx.reason\n"
            "ORDER BY n DESC;"
        ),
    },
    {
        "name": "Recent attempts (last 50)",
        "description": "Most recently finished attempts across all runs.",
        "sql": (
            "SELECT finished_at, model_name, task_id, resolved, outcome,\n"
            "       ROUND(cost_usd, 4) AS cost_usd, run_id\n"
            "FROM v_attempt\n"
            "ORDER BY finished_at DESC\n"
            "LIMIT 50;"
        ),
    },
]


# ---- data dictionary (human-readable schema, rendered at /schema) ---------
# One entry per table/view: a paragraph on WHAT it captures + a one-sentence
# gloss per column. Sourced from zbench/schema.sql + the reader's TEMP dims. The
# /schema page cross-checks these against the live columns and flags any gap.
TABLE_DOCS = {
    "v_board": {
        "kind": "view",
        "desc": ("The official ranked leaderboard -- identical to the :8787 dashboard. Every "
                 "agent is scored on the shared COMMON task set (the tasks all fully-covered "
                 "agents have in common), one attempt per cell, with controls and under-covered "
                 "agents removed. Filter ranked=1 for the ranked board."),
        "columns": {
            "rank": "Board position, 1 = best; NULL for partial-coverage agents.",
            "agent_id": "The agent configuration id (one row per agent).",
            "model_name": "The underlying model (e.g. claude-opus-5, gpt-5.6).",
            "provider": "How the model was served (direct API, CLI OAuth, vLLM, ...).",
            "harness": "The agent harness/CLI wrapping the model (claude, pi, codex).",
            "resolve_rate": "Fraction of common-set tasks the agent resolved -- the primary ranking key.",
            "resolved": "Expected number of resolved tasks over the common set.",
            "n": "Number of common-set tasks scored for this agent (= common_total for ranked agents).",
            "cost_usd": "Total US-dollar cost over the common-set tasks.",
            "cost_per_task": "cost_usd divided by n -- the tie-breaker when resolve_rate ties.",
            "no_patch": "Common-set tasks where the agent produced no patch at all.",
            "miss": "Common-set tasks where the agent produced a patch but failed the test.",
            "total_tokens": "Total billed tokens over the common set.",
            "io_tokens": "Input + output tokens over the common set.",
            "turns": "Total agentic round-trips over the common set (effort metric, not ranked).",
            "coverage": "Total distinct tasks the agent attempted (can exceed n).",
            "common_total": "Size of the common task set -- the same value on every row.",
            "ranked": "1 if the agent is on the ranked board, 0 if partial-coverage / off-board.",
        },
    },
    "v_attempt": {
        "kind": "view",
        "desc": ("Convenience view for most analyses: every attempt joined to its agent, task, "
                 "and run metadata, plus a 'resolved' alias and a 'scored' flag. One row per "
                 "attempt."),
        "columns": {
            "evaluation_id": "Unique id of the attempt.",
            "run_id": "The run the attempt belongs to.",
            "config_id": "The agent configuration that made the attempt.",
            "task_id": "The task that was attempted.",
            "tests_passed": "1 if the hidden test passed after the patch, else 0.",
            "resolved": "Alias for tests_passed (1 = task resolved).",
            "status": "Short machine status (e.g. ok, no_patch_generated).",
            "outcome": "More detailed outcome label (e.g. completed, candidate_missing).",
            "cost_usd": "Estimated US-dollar cost of the attempt.",
            "finished_at": "ISO timestamp when the attempt finished.",
            "runtime_ms": "Milliseconds the agent spent generating the patch.",
            "total_duration_ms": "Milliseconds for the whole attempt including verification.",
            "input_tokens": "Prompt tokens sent to the model.",
            "output_tokens": "Completion tokens produced, including reasoning/thinking tokens.",
            "cache_read_tokens": "Tokens served from the prompt cache (cheaper).",
            "cache_write_tokens": "Tokens written into the prompt cache.",
            "total_tokens": "Canonical billed total = input + output + cache_read + cache_write.",
            "turns": "Agentic round-trips the harness took (effort metric, not ranked).",
            "model_name": "Underlying model, from the agent dimension.",
            "provider": "How the model was served, from the agent dimension.",
            "harness": "Agent harness/CLI, from the agent dimension.",
            "open_weight": "1 if the model is open-weight (self-hostable), else 0.",
            "curation_status": "Task usability: validated | held | invalid | dropped.",
            "issue_type": "Type of change the task represents (bug | feature | refactor).",
            "component": "Product area/component the task touches.",
            "difficulty": "Task difficulty label, if set.",
            "lang": "Programming language of the task.",
            "run_label": "Human-readable label of the run.",
            "run_started_at": "ISO timestamp when the run started.",
            "scored": "1 if the attempt counts toward scoring (no run_exclusion row), else 0.",
        },
    },
    "v_run": {
        "kind": "view",
        "desc": "One row per run with rolled-up totals.",
        "columns": {
            "run_id": "Unique id of the run.",
            "label": "Human-readable name for the run.",
            "started_at": "ISO timestamp when the run started.",
            "plan": "JSON describing what the run intended to execute.",
            "n_attempts": "Number of attempts in the run.",
            "n_resolved": "Number of those attempts that resolved their task.",
            "cost_usd": "Total US-dollar cost of the run.",
        },
    },
    "attempt": {
        "kind": "table",
        "desc": ("The core fact table: one row per attempt = one agent trying one task in one "
                 "run. Identity is (run_id, config_id, task_id). tests_passed = 1 means the task "
                 "is resolved. config_id and task_id are soft references to the agent/task "
                 "dimensions loaded from git files."),
        "columns": {
            "evaluation_id": "Unique id of the attempt (primary key).",
            "run_id": "The run this attempt belongs to (hard reference to run).",
            "config_id": "The agent configuration that made the attempt (joins to the agent dim).",
            "task_id": "The task that was attempted (joins to the task dim).",
            "tests_passed": "1 if the hidden test passed after the patch (resolved), else 0 -- the headline metric.",
            "status": "Short machine status of the attempt (e.g. ok, no_patch_generated).",
            "outcome": "More detailed outcome label (e.g. completed, candidate_missing).",
            "cost_usd": "Estimated US-dollar cost of the attempt (tokens priced by model).",
            "finished_at": "ISO timestamp when the attempt finished.",
            "runtime_ms": "Milliseconds the agent spent generating the patch.",
            "total_duration_ms": "Milliseconds for the whole attempt including verification.",
            "input_tokens": "Prompt tokens sent to the model.",
            "output_tokens": "Completion tokens the model produced, including reasoning tokens.",
            "cache_read_tokens": "Tokens served from the prompt cache (cheaper).",
            "cache_write_tokens": "Tokens written into the prompt cache.",
            "total_tokens": "Canonical billed total = input + output + cache_read + cache_write.",
            "turns": "Agentic round-trips the harness took (display-only, not ranked; NULL if no transcript).",
        },
    },
    "run": {
        "kind": "table",
        "desc": "One row per benchmark run -- a batch of attempts launched together.",
        "columns": {
            "run_id": "Unique id of the run (primary key).",
            "label": "Human-readable name for the run.",
            "started_at": "ISO timestamp when the run started.",
            "plan": "JSON describing what the run intended to execute.",
        },
    },
    "attempt_event": {
        "kind": "table",
        "desc": ("Timeline of lifecycle events for attempts -- timing and diagnostics behind the "
                 "dashboard's per-attempt view. Not a scoring store. Events logged before an "
                 "attempt row exists are keyed by run/config/task."),
        "columns": {
            "id": "Auto-increment row id.",
            "evaluation_id": "The attempt this event belongs to (empty before the attempt row exists).",
            "run_id": "The run the event occurred in.",
            "config_id": "The agent configuration for the event.",
            "task_id": "The task the event is about.",
            "ts": "ISO timestamp of the event.",
            "phase": "Pipeline phase the event marks (e.g. queued, running, scoring).",
            "message": "Free-text detail for the event.",
            "source": "Who recorded the event (harness | backfill | file_mtime | ...).",
            "confidence": "How reliable the record is (high | medium | low).",
            "data_json": "Full structured payload for the event as JSON.",
        },
    },
    "attempt_provenance": {
        "kind": "table",
        "desc": ("Best-effort record of the exact environment each attempt ran in, for "
                 "reproducibility and audit. One row per attempt."),
        "columns": {
            "evaluation_id": "The attempt this provenance describes (primary key).",
            "captured_at": "ISO timestamp when provenance was captured.",
            "harness_name": "Name of the evaluation harness.",
            "harness_git_commit": "Git commit of the harness at run time.",
            "harness_git_branch": "Git branch of the harness at run time.",
            "harness_git_dirty": "1 if the harness working tree had uncommitted changes.",
            "harness_git_status": "Text summary of the harness git status.",
            "harness_git_diff_sha256": "Hash of the harness uncommitted diff (fingerprints dirty state).",
            "python_version": "Python version that ran the harness.",
            "platform": "Operating-system / platform string.",
            "agent_cli_name": "Name of the agent CLI used (e.g. claude, pi, codex).",
            "agent_cli_version": "Version of that agent CLI.",
            "agent_command": "The command line used to invoke the agent.",
            "sanitized_config": "Secret-redacted copy of the agent config (settings + provider block + env).",
            "data_json": "Full nested provenance payload as JSON.",
        },
    },
    "run_exclusion": {
        "kind": "table",
        "desc": ("The ONLY table that changes scoring: each row removes one attempt from the "
                 "ranked board. The bracket prefix in the reason ([contamination], "
                 "[artifact:infra], [superseded], ...) drives how the exclusion is treated."),
        "columns": {
            "evaluation_id": "The attempt being excluded from scoring (primary key).",
            "reason": "Why it is excluded; the [prefix] sets the exclusion behaviour.",
            "decided_by": "Who decided the exclusion.",
            "decided_at": "ISO timestamp of the decision.",
        },
    },
    "invalidation": {
        "kind": "table",
        "desc": ("Human-reviewed annotations that can mark results invalid. Only rows with "
                 "status 'accepted' affect ranking; kind is an open string so new validators "
                 "need no schema change."),
        "columns": {
            "id": "Auto-increment row id.",
            "kind": "Open-ended category of the invalidation.",
            "status": "Whether it counts: proposed | accepted | rejected (only accepted affects ranking).",
            "source": "Who produced it: rule_based | llm_agent | human.",
            "confidence": "Confidence score of the annotation (0-1).",
            "evidence": "Supporting evidence text.",
            "config_id": "Agent this applies to, if scoped to one.",
            "run_id": "Run this applies to, if scoped to one.",
            "task_id": "Task this applies to, if scoped to one.",
            "reason": "Why the result is invalid.",
            "created_at": "ISO timestamp when the annotation was created.",
            "produced_by": "Identifier of the tool or person that produced it.",
        },
    },
    "note": {
        "kind": "table",
        "desc": "Free-text comments, hints, or evidence attached to a run, attempt, or task. Notes never affect scoring.",
        "columns": {
            "id": "Auto-increment row id.",
            "subject_type": "What the note is attached to (run | task | ...).",
            "subject_id": "Id of that subject (evaluation_id for a run/attempt note, task id for a task note).",
            "source": "Who wrote it (human by default).",
            "body": "The note text.",
            "evidence": "Optional supporting evidence.",
            "produced_by": "Tool or person that produced the note.",
            "confidence": "Optional confidence score.",
            "created_by": "Author identifier.",
            "created_at": "ISO timestamp when the note was created.",
            "updated_at": "ISO timestamp when the note was last edited.",
        },
    },
    "validation": {
        "kind": "table",
        "desc": "Record of which attempts an offline validator checked, and its result.",
        "columns": {
            "evaluation_id": "The attempt that was validated (primary key).",
            "validated_at": "ISO timestamp of validation.",
            "validator_version": "Version of the validator that ran.",
            "result": "Validator result text.",
        },
    },
    "agent": {
        "kind": "dim",
        "desc": ("Dimension loaded per request from agents-*.jsonl / agents-meta.jsonl (git "
                 "files -- the DB stores no copy). Maps an attempt's config_id to model, "
                 "provider, and harness. Join on attempt.config_id."),
        "columns": {
            "config_id": "Agent configuration id -- the join key to attempt.config_id.",
            "model_name": "The underlying model (e.g. claude-opus-5, gpt-5.6).",
            "provider": "How the model was served (direct API, CLI OAuth, vLLM, ...).",
            "harness": "The agent harness/CLI wrapping the model (claude, pi, codex).",
            "open_weight": "1 if the model is open-weight (self-hostable), else 0.",
            "timeout_s": "Per-attempt timeout in seconds configured for this agent.",
        },
    },
    "task": {
        "kind": "dim",
        "desc": ("Dimension loaded per request from each task's meta.json (git files -- the DB "
                 "stores no copy). Describes the coding task. Join on attempt.task_id."),
        "columns": {
            "task_id": "Task id (ZT-<sha>) -- the join key to attempt.task_id.",
            "lang": "Programming language of the task.",
            "component": "Product area/component the task touches.",
            "issue_type": "Type of change (bug | feature | refactor).",
            "base_commit": "The commit the agent starts from, before the fix.",
            "fix_commit": "The upstream commit that fixed the issue (the gold reference).",
            "difficulty": "Curator/heuristic difficulty label, if set.",
            "curation_status": "Whether the task is usable: validated | held | invalid | dropped.",
            "resolved_date": "Date the upstream fix landed.",
            "summary": "One-line description of the task.",
        },
    },
    "task_test": {
        "kind": "dim",
        "desc": ("Dimension: the hidden regression test function(s) that decide whether each "
                 "task is resolved. One row per (task, test)."),
        "columns": {
            "task_id": "Task the test belongs to.",
            "testfunc": "Fully-qualified name of the hidden test function.",
        },
    },
}


# ---- connection + views ---------------------------------------------------
def _open() -> sqlite3.Connection:
    """Fresh read-only connection with the TEMP dims + convenience views loaded.

    benchdb_reader._connect opens bench.db mode=ro and creates the TEMP dim DDL;
    we then fill the dims from the git files and add v_attempt / v_run. Every
    object we create is TEMP (separate temp db), so the read-only main db is
    untouched. `PRAGMA query_only=ON` is belt-and-suspenders on top of mode=ro.
    """
    conn = benchdb_reader._connect(Path(BENCHDB))
    # Load the TEMP dims + views FIRST (these write to the separate temp db), THEN
    # flip query_only=ON so the user's query cannot write anything. mode=ro already
    # protects the main db; this also blocks writes to the temp db.
    benchdb_reader._load_task_temp(conn, TASKS)
    benchdb_reader._load_agent_temp(conn, Path(TASKS).parent)  # agents-meta.jsonl lives in zbench-tasks/
    tot = benchdb_reader._total_tok_col(conn)   # 'a.total_tokens' or 'NULL AS total_tokens'
    trn = benchdb_reader._turns_col(conn)       # 'a.turns' or 'NULL AS turns'
    conn.executescript(f"""
CREATE TEMP VIEW v_attempt AS
SELECT a.evaluation_id, a.run_id, a.config_id, a.task_id,
       a.tests_passed, a.tests_passed AS resolved,
       a.status, a.outcome, a.cost_usd,
       a.finished_at, a.runtime_ms, a.total_duration_ms,
       a.input_tokens, a.output_tokens, a.cache_read_tokens, a.cache_write_tokens,
       {tot}, {trn},
       ag.model_name, ag.provider, ag.harness, ag.open_weight,
       t.curation_status, t.issue_type, t.component, t.difficulty, t.lang,
       r.label AS run_label, r.started_at AS run_started_at,
       CASE WHEN {exclusions.NOT_EXCLUDED_SQL} THEN 1 ELSE 0 END AS scored
FROM attempt a
LEFT JOIN agent ag ON a.config_id = ag.config_id
LEFT JOIN task  t  ON a.task_id  = t.task_id
LEFT JOIN run   r  ON a.run_id   = r.run_id;

CREATE TEMP VIEW v_run AS
SELECT r.run_id, r.label, r.started_at, r.plan,
       COUNT(a.evaluation_id) AS n_attempts,
       SUM(a.tests_passed)    AS n_resolved,
       SUM(a.cost_usd)        AS cost_usd
FROM run r LEFT JOIN attempt a ON a.run_id = r.run_id
GROUP BY r.run_id, r.label, r.started_at, r.plan;
""")
    _materialize_board(conn)              # v_board = the exact :8787 ranked board
    conn.execute("PRAGMA query_only=ON")  # belt-and-suspenders on top of mode=ro
    return conn


def _materialize_board(conn: sqlite3.Connection) -> None:
    """Materialize the dashboard's D1-D5 board into a TEMP table `v_board`.

    The ranked leaderboard is NOT a raw AVG over v_attempt -- it is one row per
    agent scored on the COMMON TASK SET (the tasks every fully-covered agent
    shares), one attempt per cell, controls + under-covered agents removed. That
    logic lives in ranking_view.aggregate_and_rank (Python), so we run the exact
    same call the reader uses (benchdb_reader.collect_state) and store the result
    here. `SELECT * FROM v_board WHERE ranked=1 ORDER BY rank` then equals :8787.
    """
    conn.executescript("""
CREATE TEMP TABLE v_board(
  rank INTEGER, agent_id TEXT, model_name TEXT, provider TEXT, harness TEXT,
  resolve_rate REAL, resolved REAL, n INTEGER, cost_usd REAL, cost_per_task REAL,
  no_patch INTEGER, miss INTEGER, total_tokens INTEGER, io_tokens INTEGER,
  turns INTEGER, coverage INTEGER, common_total INTEGER, ranked INTEGER);
""")
    try:
        agg_scores = benchdb_reader._board_scores(benchdb_reader._valid_scores(conn))
        contam = benchdb_reader._contam_pairs(conn)
        corpus_instances = None
        if corpus is not None:
            try:
                corpus_instances = {constants.instance_of(t)
                                    for t in corpus.validated_ids(tasks_dir=str(TASKS))}
            except Exception:
                corpus_instances = None
        agg = ranking_view.aggregate_and_rank(
            agg_scores, contam, corpus_instances=corpus_instances,
            infra_limited_pairs=benchdb_reader._infra_limited_pairs(conn))
        ncommon = agg.get("n_common")

        def _ins(r, ranked):
            n = r.get("n") or 0
            conn.execute(
                "INSERT INTO v_board VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("rank"), r.get("agent_id"), r.get("model_name"), r.get("provider"),
                 r.get("harness"), r.get("resolve_rate"), r.get("resolved"), n,
                 r.get("cost_usd"), (r["cost_usd"] / n) if (n and r.get("cost_usd") is not None) else None,
                 r.get("no_patch"), r.get("miss"), r.get("total_tokens"), r.get("io_tokens"),
                 r.get("turns"), r.get("coverage"), ncommon, ranked))

        for r in agg.get("leaderboard", []):
            _ins(r, 1)
        for r in agg.get("leaderboard_partial", []):
            _ins(r, 0)
    except Exception as e:  # noqa: BLE001 -- board is a bonus; console works without it
        print(f"[query_console] v_board unavailable: {type(e).__name__}: {e}", file=sys.stderr)


# ---- SQL guard ------------------------------------------------------------
_COMMENT_LINE = re.compile(r"--[^\n]*")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)


def _strip_comments(sql: str) -> str:
    return _COMMENT_BLOCK.sub(" ", _COMMENT_LINE.sub(" ", sql))


def _validate_sql(sql: str) -> str | None:
    """Return an error string if `sql` is not a single allowed read statement,
    else None. Defence in depth on top of mode=ro + query_only."""
    body = _strip_comments(sql).strip()
    if not body:
        return "empty query"
    # collapse a single trailing ';' then reject any further statement.
    stmts = [s for s in body.split(";") if s.strip()]
    if len(stmts) > 1:
        return "only one statement is allowed (found %d)" % len(stmts)
    first = stmts[0].strip().split(None, 1)[0].lower()
    if first not in _ALLOWED_FIRST:
        return f"only read queries are allowed (got '{first.upper()}'); use SELECT/WITH/EXPLAIN"
    if first == "pragma" and "=" in stmts[0]:
        return "only read-form PRAGMA is allowed (no 'PRAGMA x = y')"
    return None


def _run_query(sql: str) -> dict:
    err = _validate_sql(sql)
    if err:
        return {"error": err}
    t0 = time.monotonic()
    deadline = t0 + TIMEOUT_S

    def _interrupt():
        return 1 if time.monotonic() > deadline else 0

    conn = None
    try:
        conn = _open()
        conn.set_progress_handler(_interrupt, 100000)
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(ROW_CAP + 1)
        truncated = len(fetched) > ROW_CAP
        rows = [[_cell(v) for v in r] for r in fetched[:ROW_CAP]]
        return {
            "columns": cols,
            "rows": rows,
            "truncated": truncated,
            "row_count": len(rows),
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except sqlite3.OperationalError as e:
        msg = str(e)
        if "interrupted" in msg.lower():
            msg = f"query cancelled after {TIMEOUT_S:.0f}s (add a LIMIT or narrow it)"
        return {"error": msg}
    except Exception as e:  # noqa: BLE001 -- surface any sqlite error to the UI
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        if conn is not None:
            conn.close()


def _cell(v):
    """JSON-safe cell value. Blobs become a short placeholder, not raw bytes."""
    if isinstance(v, (bytes, bytearray, memoryview)):
        return f"<blob {len(bytes(v))} bytes>"
    return v


# ---- schema introspection -------------------------------------------------
def _schema() -> list[dict]:
    """Tables + the TEMP dims + the v_* views, each with its column list."""
    conn = _open()
    try:
        out = []
        seen = set()

        def add(name, kind):
            if name in seen or name.startswith("sqlite_"):
                return
            seen.add(name)
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
            if cols:
                out.append({"name": name, "kind": kind, "columns": cols})

        # convenience views first (what most queries use), then real tables, dims.
        for v in ("v_board", "v_attempt", "v_run"):
            add(v, "view")
        rows = conn.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name"
        ).fetchall()
        for name, typ in rows:
            add(name, typ)
        for dim in ("agent", "task", "task_test"):
            add(dim, "dim")
        return out
    finally:
        conn.close()


# ---- saved-query library (sidecar JSON; NEVER bench.db) -------------------
def _load_user_saved() -> list[dict]:
    if not SAVED_PATH.exists():
        return []
    try:
        data = json.loads(SAVED_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_user_saved(items: list[dict]) -> None:
    SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_PATH.write_text(json.dumps(items, indent=2))


def _saved_payload() -> dict:
    return {"builtin": DEFAULT_QUERIES, "user": _load_user_saved()}


def _saved_mutate(action: str, name: str, sql: str, description: str) -> dict:
    name = (name or "").strip()
    if not name:
        return {"error": "name is required"}
    if any(q["name"] == name for q in DEFAULT_QUERIES):
        return {"error": "that name is a built-in query; choose another name"}
    items = _load_user_saved()
    items = [q for q in items if q.get("name") != name]  # upsert / delete
    if action == "save":
        if not (sql or "").strip():
            return {"error": "sql is required"}
        items.append({"name": name, "description": description or "", "sql": sql})
    elif action != "delete":
        return {"error": f"unknown action '{action}'"}
    items.sort(key=lambda q: q["name"].lower())
    _write_user_saved(items)
    return {"ok": True, "user": items}


# ---- HTML page ------------------------------------------------------------
def _page() -> str:
    return PAGE_HTML


PAGE_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bench.db query console</title>
<style>
:root{--fg:#0f172a;--muted:#64748b;--muted2:#94a3b8;--accent:#2563eb;--border:#e2e8f0;
 --border2:#cbd5e1;--bg:#f8fafc;--line:#eef2f7;--thbg:#f1f5f9;--card:#fff;--ok:#16a34a;--bad:#dc2626}
@media (prefers-color-scheme:dark){:root{--fg:#e2e8f0;--muted:#94a3b8;--muted2:#64748b;
 --accent:#60a5fa;--border:#1e293b;--border2:#334155;--bg:#0b1220;--line:#152033;--thbg:#111c30;
 --card:#0f1a2e;--ok:#4ade80;--bad:#f87171}}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--fg);font-size:13px}
header{padding:8px 14px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:12px}
header h1{font-size:15px;margin:0}
header .sub{color:var(--muted);font-size:12px;margin-left:auto}
header nav{display:flex;gap:4px}
header nav a{font-size:13px;text-decoration:none;color:var(--accent);border:1px solid transparent;
 border-radius:4px;padding:2px 10px}
header nav a:hover{background:var(--line)}
header nav a.active{background:var(--accent);color:#fff}
.wrap{display:flex;height:calc(100vh - 39px)}
aside{width:280px;min-width:280px;border-right:1px solid var(--border);overflow:auto;padding:10px}
main{flex:1;display:flex;flex-direction:column;overflow:hidden}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:14px 0 6px}
h2:first-child{margin-top:0}
.q{padding:6px 8px;border:1px solid var(--border);border-radius:5px;margin-bottom:5px;cursor:pointer;background:var(--card)}
.q:hover{border-color:var(--accent)}
.q .nm{font-weight:600}
.q .ds{color:var(--muted);font-size:11px;margin-top:2px}
.q .del{float:right;color:var(--muted2);text-decoration:none;font-size:12px}
.q .del:hover{color:var(--bad)}
details.tbl{margin-bottom:4px}
details.tbl summary{cursor:pointer;font-family:ui-monospace,Menlo,monospace;font-size:12px;padding:2px 0}
details.tbl .cols{padding:2px 0 6px 14px}
.col{display:inline-block;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:var(--muted);
 border:1px solid var(--border);border-radius:3px;padding:0 4px;margin:2px 3px 0 0;cursor:pointer}
.col:hover{color:var(--accent);border-color:var(--accent)}
.kind{color:var(--muted2);font-size:10px;font-weight:400}
.editor{padding:10px;border-bottom:1px solid var(--border)}
textarea{width:100%;height:150px;font-family:ui-monospace,Menlo,monospace;font-size:13px;
 padding:8px;border:1px solid var(--border2);border-radius:5px;background:var(--card);color:var(--fg);resize:vertical}
.bar{display:flex;gap:8px;align-items:center;margin-top:6px;flex-wrap:wrap}
button{font:inherit;font-size:13px;border:1px solid var(--border2);background:var(--card);color:var(--accent);
 border-radius:4px;padding:4px 12px;cursor:pointer}
button:hover{background:var(--line)}
button.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
button.primary:hover{filter:brightness(1.08)}
.status{color:var(--muted);font-size:12px;margin-left:auto}
.results{flex:1;overflow:auto;padding:0}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{text-align:left;padding:4px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
th{background:var(--thbg);position:sticky;top:0;cursor:pointer;user-select:none}
th .ar{color:var(--muted2);font-size:10px;margin-left:3px}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:hover td{background:var(--line)}
.err{color:var(--bad);padding:12px;font-family:ui-monospace,Menlo,monospace;white-space:pre-wrap}
.null{color:var(--muted2);font-style:italic}
.note{padding:10px 14px;color:var(--muted);font-size:12px}
</style></head>
<body>
<header>
  <h1>bench.db query console</h1>
  <nav><a class="active" href="/">SQL Console</a><a href="/schema">Data dictionary</a></nav>
  <span class="sub">read-only &middot; single SELECT/WITH/EXPLAIN &middot; row cap 5000</span>
</header>
<div class="wrap">
  <aside>
    <h2>Saved queries</h2>
    <div id="saved"></div>
    <h2>Schema</h2>
    <div id="schema"></div>
  </aside>
  <main>
    <div class="editor">
      <textarea id="sql" placeholder="SELECT * FROM v_attempt LIMIT 20;"></textarea>
      <div class="bar">
        <button class="primary" onclick="run()">Run &nbsp;<span style="opacity:.7">&#8984;/Ctrl+Enter</span></button>
        <button onclick="saveCurrent()">Save current&hellip;</button>
        <button onclick="download('csv')">Download CSV</button>
        <button onclick="download('json')">Download JSON</button>
        <span class="status" id="status"></span>
      </div>
    </div>
    <div class="results" id="results">
      <div class="note">Pick a saved query on the left, or type SQL and press Run.
        Views <code>v_attempt</code> and <code>v_run</code> pre-join agent + task metadata.</div>
    </div>
  </main>
</div>
<script>
let LAST = null;      // last result {columns, rows}
let SORT = {col:-1, dir:1};

function esc(s){return String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}
function isNum(v){return typeof v === 'number';}

async function init(){
  const sc = await (await fetch('api/schema')).json();
  const sd = document.getElementById('schema');
  sd.innerHTML = sc.map(t=>{
    const cols = t.columns.map(c=>`<span class="col" onclick="insert('${c}')">${esc(c)}</span>`).join('');
    return `<details class="tbl"${t.kind==='view'?' open':''}><summary>${esc(t.name)} <span class="kind">${t.kind}</span></summary><div class="cols">${cols}</div></details>`;
  }).join('');
  await loadSaved();
}

async function loadSaved(){
  const s = await (await fetch('api/saved')).json();
  const el = document.getElementById('saved');
  const item = (q,builtin)=>`<div class="q" onclick="pick(this)" data-sql="${esc(q.sql)}">`
    + (builtin?'':`<a class="del" title="delete" onclick="event.stopPropagation();delSaved('${esc(q.name)}')">&times;</a>`)
    + `<div class="nm">${esc(q.name)}</div><div class="ds">${esc(q.description||'')}</div></div>`;
  el.innerHTML = (s.user||[]).map(q=>item(q,false)).join('')
    + (s.builtin||[]).map(q=>item(q,true)).join('');
}

function pick(div){document.getElementById('sql').value = div.getAttribute('data-sql'); run();}
function insert(text){
  const ta=document.getElementById('sql'), s=ta.selectionStart, e=ta.selectionEnd;
  ta.value = ta.value.slice(0,s)+text+ta.value.slice(e);
  ta.focus(); ta.selectionStart = ta.selectionEnd = s+text.length;
}

async function run(){
  const sql = document.getElementById('sql').value;
  const st = document.getElementById('status'); st.textContent='running…';
  const res = document.getElementById('results');
  let r;
  try{ r = await (await fetch('api/query',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({sql})})).json(); }
  catch(e){ st.textContent=''; res.innerHTML=`<div class="err">${esc(e)}</div>`; return; }
  if(r.error){ LAST=null; st.textContent=''; res.innerHTML=`<div class="err">${esc(r.error)}</div>`; return; }
  LAST=r; SORT={col:-1,dir:1};
  st.textContent = `${r.row_count} row${r.row_count===1?'':'s'} · ${r.elapsed_ms} ms` + (r.truncated?` · truncated at ${r.row_count}`:'');
  render();
}

function render(){
  const r=LAST, res=document.getElementById('results');
  if(!r){return;}
  if(!r.columns.length){res.innerHTML='<div class="note">(no columns)</div>';return;}
  let rows=r.rows.map((row,i)=>[i,row]);
  if(SORT.col>=0){
    rows.sort((a,b)=>{let x=a[1][SORT.col],y=b[1][SORT.col];
      if(x===null)return 1; if(y===null)return -1;
      if(isNum(x)&&isNum(y))return (x-y)*SORT.dir;
      return String(x).localeCompare(String(y))*SORT.dir;});
  }
  const numcol = r.columns.map((_,c)=>r.rows.every(rw=>rw[c]===null||isNum(rw[c])));
  const th=r.columns.map((c,i)=>{
    const ar = SORT.col===i?(SORT.dir>0?'▲':'▼'):'';
    return `<th class="${numcol[i]?'num':''}" onclick="sortBy(${i})">${esc(c)}<span class="ar">${ar}</span></th>`;
  }).join('');
  const body=rows.map(([_,row])=>'<tr>'+row.map((v,i)=>{
    if(v===null)return `<td class="${numcol[i]?'num ':''}"><span class="null">null</span></td>`;
    return `<td class="${numcol[i]?'num':''}">${esc(v)}</td>`;
  }).join('')+'</tr>').join('');
  res.innerHTML=`<table><thead><tr>${th}</tr></thead><tbody>${body}</tbody></table>`;
}

function sortBy(c){ if(SORT.col===c){SORT.dir*=-1;}else{SORT={col:c,dir:1};} render(); }

function download(fmt){
  if(!LAST||!LAST.columns.length){return;}
  let blob, name;
  if(fmt==='json'){
    const objs=LAST.rows.map(r=>Object.fromEntries(LAST.columns.map((c,i)=>[c,r[i]])));
    blob=new Blob([JSON.stringify(objs,null,2)],{type:'application/json'}); name='bench_query.json';
  }else{
    const q=s=>{s=s===null?'':String(s); return /[",\n]/.test(s)?'"'+s.replace(/"/g,'""')+'"':s;};
    const lines=[LAST.columns.map(q).join(',')].concat(LAST.rows.map(r=>r.map(q).join(',')));
    blob=new Blob([lines.join('\n')],{type:'text/csv'}); name='bench_query.csv';
  }
  const a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}

async function saveCurrent(){
  const sql=document.getElementById('sql').value.trim();
  if(!sql){alert('nothing to save');return;}
  const name=prompt('Save this query as:'); if(!name)return;
  const description=prompt('Short description (optional):')||'';
  const r=await (await fetch('api/saved',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({action:'save',name,sql,description})})).json();
  if(r.error){alert(r.error);return;} loadSaved();
}
async function delSaved(name){
  if(!confirm('Delete saved query "'+name+'"?'))return;
  await fetch('api/saved',{method:'POST',headers:{'content-type':'application/json'},
    body:JSON.stringify({action:'delete',name})});
  loadSaved();
}

document.getElementById('sql').addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();run();}
});
init();
</script>
</body></html>
"""


_DICT_CSS = """
:root{--fg:#0f172a;--muted:#64748b;--muted2:#94a3b8;--accent:#2563eb;--border:#e2e8f0;
 --border2:#cbd5e1;--bg:#f8fafc;--line:#eef2f7;--thbg:#f1f5f9;--card:#fff;--warn:#b45309}
@media (prefers-color-scheme:dark){:root{--fg:#e2e8f0;--muted:#94a3b8;--muted2:#64748b;
 --accent:#60a5fa;--border:#1e293b;--border2:#334155;--bg:#0b1220;--line:#152033;--thbg:#111c30;
 --card:#0f1a2e;--warn:#fbbf24}}
*{box-sizing:border-box}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:var(--bg);color:var(--fg);font-size:13px}
header{padding:8px 14px;border-bottom:1px solid var(--border);display:flex;align-items:baseline;gap:12px;
 position:sticky;top:0;background:var(--bg);z-index:5}
header h1{font-size:15px;margin:0}
header nav{display:flex;gap:4px}
header nav a{font-size:13px;text-decoration:none;color:var(--accent);border:1px solid transparent;
 border-radius:4px;padding:2px 10px}
header nav a:hover{background:var(--line)}
header nav a.active{background:var(--accent);color:#fff}
header .sub{color:var(--muted);font-size:12px;margin-left:auto}
.layout{display:flex}
.toc{width:200px;min-width:200px;position:sticky;top:41px;align-self:flex-start;height:calc(100vh - 41px);
 overflow:auto;border-right:1px solid var(--border);padding:12px}
.toc h2{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:12px 0 4px}
.toc h2:first-child{margin-top:0}
.toc a{display:block;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:var(--accent);
 text-decoration:none;padding:2px 0}
.toc a:hover{text-decoration:underline}
main{flex:1;padding:16px 22px;max-width:960px}
.intro{color:var(--muted);margin:0 0 18px;max-width:70ch}
section{margin-bottom:26px;scroll-margin-top:52px}
.tname{font-family:ui-monospace,Menlo,monospace;font-size:16px;font-weight:700}
.kind{font-size:10px;text-transform:uppercase;letter-spacing:.04em;border:1px solid var(--border2);
 border-radius:3px;padding:1px 6px;color:var(--muted);margin-left:8px;vertical-align:middle}
.desc{color:var(--fg);margin:6px 0 10px;max-width:75ch}
table{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--border);border-radius:6px;overflow:hidden}
th,td{text-align:left;padding:5px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--thbg);font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}
td.col{font-family:ui-monospace,Menlo,monospace;white-space:nowrap;color:var(--accent);width:1%}
tr:last-child td{border-bottom:none}
.undoc{color:var(--warn);font-style:italic}
"""


def _header_html(active: str) -> str:
    def a(href, label):
        cls = ' class="active"' if href == active else ""
        return f'<a{cls} href="{href}">{label}</a>'
    return (f"<header><h1>bench.db query console</h1>"
            f"<nav>{a('/', 'SQL Console')}{a('/schema', 'Data dictionary')}</nav>"
            f'<span class="sub">read-only view of bench.db</span></header>')


def _dict_page() -> str:
    """Human-readable data dictionary. Renders TABLE_DOCS, but pulls the LIVE column
    list from PRAGMA so a schema change shows up (extra columns flagged 'undocumented',
    and only columns that actually exist are shown)."""
    conn = _open()
    try:
        live_cols = {}
        for name in TABLE_DOCS:
            try:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({name})")]
            except Exception:
                cols = []
            live_cols[name] = cols
    finally:
        conn.close()

    kind_order = [("view", "Views (start here)"), ("table", "Stored tables"),
                  ("dim", "Dimensions (loaded from git files)")]
    esc = html.escape

    toc = []
    body = []
    for kind, heading in kind_order:
        names = [n for n, d in TABLE_DOCS.items() if d["kind"] == kind]
        if not names:
            continue
        toc.append(f"<h2>{esc(heading)}</h2>")
        for name in names:
            doc = TABLE_DOCS[name]
            toc.append(f'<a href="#{esc(name)}">{esc(name)}</a>')
            live = live_cols.get(name) or list(doc["columns"])
            rows = []
            for col in live:
                gloss = doc["columns"].get(col)
                cell = (esc(gloss) if gloss
                        else '<span class="undoc">(undocumented &mdash; ask the project owner to add it)</span>')
                rows.append(f'<tr><td class="col">{esc(col)}</td><td>{cell}</td></tr>')
            body.append(
                f'<section id="{esc(name)}"><div><span class="tname">{esc(name)}</span>'
                f'<span class="kind">{esc(kind)}</span></div>'
                f'<p class="desc">{esc(doc["desc"])}</p>'
                f'<table><thead><tr><th>column</th><th>what it holds</th></tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></section>')

    intro = ("Every table in bench.db, in plain language. bench.db stores machine FACTS and "
             "human annotations only; the agent and task DIMENSIONS are loaded per query from "
             "git-tracked files. Views (v_*) pre-join those for you.")
    return (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
            f"<meta name=viewport content='width=device-width, initial-scale=1'>"
            f"<title>bench.db data dictionary</title><style>{_DICT_CSS}</style></head><body>"
            f"{_header_html('/schema')}"
            f'<div class="layout"><aside class="toc">{"".join(toc)}</aside>'
            f'<main><p class="intro">{esc(intro)}</p>{"".join(body)}</main></div>'
            f"</body></html>")


# ---- HTTP server ----------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "zbench-query-console/1.0"

    def log_message(self, *a):  # quiet: no per-request stderr spam
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, default=str), "application/json")

    def _body_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path in ("/", "/index.html"):
                self._send(200, _page())
            elif path == "/schema":
                self._send(200, _dict_page())
            elif path == "/api/schema":
                self._json(200, _schema())
            elif path == "/api/saved":
                self._json(200, _saved_payload())
            else:
                self._send(404, "<h1>404</h1>")
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/query":
                self._json(200, _run_query(self._body_json().get("sql", "")))
            elif path == "/api/saved":
                b = self._body_json()
                self._json(200, _saved_mutate(
                    b.get("action", ""), b.get("name", ""),
                    b.get("sql", ""), b.get("description", "")))
            else:
                self._send(404, "<h1>404</h1>")
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    global BENCHDB, TASKS, SAVED_PATH
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8789)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1; use an SSH tunnel for remote)")
    ap.add_argument("--benchdb", default=str(DEFAULT_DB), help="path to bench.db")
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS), help="task dirs (for curation/agent dims)")
    args = ap.parse_args()

    BENCHDB = args.benchdb
    TASKS = Path(args.tasks)
    SAVED_PATH = Path(BENCHDB).parent / ".runtime" / "query_console_saved.json"

    # fail fast + prove the wiring before we bind.
    try:
        c = _open()
        n = c.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]
        c.close()
    except Exception as e:  # noqa: BLE001
        print(f"[query_console] cannot open {BENCHDB}: {e}", file=sys.stderr)
        sys.exit(1)

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[query_console] read-only SQL console on http://{args.host}:{args.port}/  "
          f"({n} attempts in {BENCHDB})")
    print(f"[query_console] remote: ssh -L {args.port}:127.0.0.1:{args.port} <host>")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
