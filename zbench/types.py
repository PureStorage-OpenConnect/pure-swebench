"""zbench data shapes -- TypedDicts, NOT classes (W19 data-oriented decision).

These are the ONLY declared shapes. They are dicts at runtime (`assoc`/merge/filter
just work); the TypedDict is purely a type-checker/editor affordance. There is no
`to_dict`/`from_dict` ceremony and no behavior here -- validation lives at the two edges
(`ingest.py`), transformations are pure functions (`transform.py`), and the persistence
edge is guarded by `schema.sql`. The only things that stay real *types* (behavior +
lifecycle) are `Lease` and the slot gate -- those are NOT here.

3.10-safe required/optional split: a required-fields base + a `total=False` subclass for
the optional (nullable) fields (avoids typing.Required, which is 3.11+).

Provenance of each shape:
  * AgentSpec  <- ingest of `agents-*.jsonl`   (one agent config line)
  * TaskSpec   <- ingest of `tasks/<task_id>/meta.json`
  * AttemptRow <- the `attempt` table in schema.sql (persistence), minus try_number
  * EventRow   <- the `attempt_event` table in schema.sql, minus try_number
"""
from __future__ import annotations

from typing import TypedDict


# --- INGEST edge: agents-*.jsonl -------------------------------------------------
class AgentSpecRequired(TypedDict):
    agent_id: str          # human-readable model x harness id (== config_id)
    command: str           # CLI to invoke the adapter, e.g. "python3 -m zbench.agents.pi_agent"


class AgentSpec(AgentSpecRequired, total=False):
    timeout_sec: int
    env: dict[str, str]    # adapter env (PI_PROVIDER / PI_MODEL / ZBENCH_AGENT_TIMEOUT / ...)
    working_dir: str
    metadata: dict[str, object]


# --- INGEST edge: tasks/<task_id>/instance.jsonl (the RUN input, distinct from meta.json) --
class InstanceSpecRequired(TypedDict):
    instance_id: str       # zbench_ZT-<sha12> (the run/worktree id; -> task_id via strip)
    repo: str              # e.g. zulip/zulip
    commit: str            # the checkout commit (== base_commit)
    problem_statement: str  # the prompt handed to the agent


class InstanceSpec(InstanceSpecRequired, total=False):
    languages: list[str]
    metadata: dict[str, object]  # task_type/language/component/env_fingerprint/
                                 # fail_to_pass/pass_to_pass/commands/verify_timeout_sec/...


# --- INGEST edge: tasks/<task_id>/meta.json -----------------------------------------
class TaskSpecRequired(TypedDict):
    task_id: str                          # ZT-<sha12> (the task id; advisory soft-ref in the DB)
    base_commit: str                   # the fix parent -> the isolated checkout base
    lang: str                          # py | web -> the verify runner


class TaskSpec(TaskSpecRequired, total=False):
    # test target -- OPTIONAL at ingest (a runnability precondition, resolved by
    # ingest.test_target(); 16/68 files lack fail_to_pass_testfuncs, older format):
    fail_to_pass_testfuncs: list[str]  # modern target test(s) the fix must flip
    fail_to_pass: object               # older target: str OR list[str]
    test_file: str                     # older: the test file
    fix_commit: str
    component: str
    type: str                          # upstream issue type (bug/feature/other)
    summary: str
    testing_trailer: str
    curation_status: str              # validated | held | dropped | invalid
    resolved: str                      # upstream resolution DATE (ISO), not a bool
    review: dict[str, object]          # curation notes (coupling/solution-path/suitability)
    verdict: str                       # candidate-screen verdict (legacy/advisory)
    reason: str                        # short curation reason for held/invalid/dropped
    reason_code: str                   # normalized reason category
    curation_stage: str                # mining / screen / oracle / ...
    source: dict[str, object]          # mining/source provenance
    evidence: list[object]             # local evidence/log pointers


# --- PERSISTENCE edge: the `attempt` table (schema.sql), minus try_number ---------
class AttemptRowRequired(TypedDict):
    evaluation_id: str     # PK (uuid)
    run_id: str            # FK -> run
    config_id: str         # FK -> harness_config (== agent_id)
    task_id: str              # advisory soft-ref to the file task
    tests_passed: int      # 0/1 == "resolved" (the metric)
    finished_at: str       # ISO ts (NOT NULL in schema)


class AttemptRow(AttemptRowRequired, total=False):
    status: str
    outcome: str
    cost_usd: float
    runtime_ms: int
    total_duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    # CANONICAL billed total (transform.canonical_total_tokens): input + output +
    # cache_read + cache_write. Reinstated 2026-08-15 -- it IS cleanly derivable, and
    # leaving each reader to derive its own produced three disagreeing definitions.
    total_tokens: int
    # agentic turns (model round-trips) the harness took on this attempt (display-only,
    # not ranked). claude = result.num_turns; pi/codex = assistant-response count.
    turns: int
    # dropped vs the fork: phase (const 'scoring'),
    # bundle_dir (= blobs/attempt/<evaluation_id>/, derived on read via transform.bundle_dir)


# --- PERSISTENCE edge: the `attempt_event` table (schema.sql), minus try_number ---
class EventRowRequired(TypedDict):
    run_id: str
    config_id: str
    task_id: str
    ts: str
    phase: str


class EventRow(EventRowRequired, total=False):
    evaluation_id: str     # filled once the attempt row exists
    message: str
    source: str            # harness | backfill | file_mtime | ...   (default 'harness')
    confidence: str        # high | medium | low                     (default 'high')
    data_json: str


# Attempt identity (W109): (run_id, config_id, task_id). No stored ordinal; if a "try N"
# is ever needed it is derived -> row_number() over (partition by config_id,task_id
# order by finished_at). try_number is GONE from both the shapes and schema.sql.
