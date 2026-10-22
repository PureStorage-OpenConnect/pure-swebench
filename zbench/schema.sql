-- zbench bench.db persistent schema (facts-only).
--
-- INVARIANT (W19): bench.db persists MACHINE FACTS + annotations ONLY. Every
-- human-authored DIMENSION is a git-tracked file loaded as a TEMP table per query
-- (the file is the single source; the DB never persists a copy). So `model` +
-- `harness_config` are GONE -- model/provider/harness come from the `agent` temp table
-- (agents-*.jsonl + agents-meta.jsonl), exactly like `task`/`task_test` come from
-- meta.json. config_id + task_id are therefore ADVISORY (soft) refs, like the fork's
-- task(task_id) already was; only run_id and evaluation_id are hard FKs (they are facts).
--
-- Simplifications baked in vs the fork (all evidence-backed as dead/constant/derivable):
--   * try_number REMOVED (always 1; identity = run_id,config_id,task_id)   [W109]
--   * attempt.phase REMOVED (always 'scoring')
--   * attempt.bundle_dir REMOVED (= blobs/attempt/<evaluation_id>; derived on read)
--   * model + harness_config tables REMOVED (dims -> the `agent` temp table)
-- Applied idempotently by the writer (CREATE TABLE IF NOT EXISTS).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS run(
  run_id     TEXT PRIMARY KEY,
  label      TEXT,
  started_at TEXT,
  plan       TEXT);                          -- plan = JSON

-- the fact: one grain = one attempt ----------------------------------------
-- identity = (run_id, config_id, task_id); no stored try ordinal (W109). config_id +
-- task_id are advisory (soft) refs to the `agent`/`task` temp tables. bundle_dir is
-- NOT stored -> derived as blobs/attempt/<evaluation_id>/.
CREATE TABLE IF NOT EXISTS attempt(
  evaluation_id      TEXT PRIMARY KEY,
  run_id             TEXT NOT NULL REFERENCES run,  -- enforced (run is a fact)
  config_id          TEXT NOT NULL,                 -- advisory soft-ref (-> agent temp table)
  task_id               TEXT NOT NULL,                 -- advisory soft-ref (-> task temp table)
  tests_passed       INTEGER NOT NULL,       -- 0/1 == "resolved" (the metric)
  status             TEXT,
  outcome            TEXT,
  cost_usd           REAL,
  finished_at        TEXT NOT NULL,
  runtime_ms         INTEGER,
  total_duration_ms  INTEGER,
  input_tokens       INTEGER,
  output_tokens      INTEGER,
  cache_read_tokens  INTEGER,
  cache_write_tokens INTEGER,
  -- CANONICAL total = input + output + cache_read + cache_write (every BILLED component,
  -- matching what model_prices.cost_usd charges for). Stored, not re-derived per reader:
  -- three call sites previously each derived their own total and all three omitted
  -- cache_write, so "total tokens" disagreed with the cost built from the same row.
  total_tokens       INTEGER,
  -- number of agentic TURNS (model round-trips) the harness took on this attempt: claude =
  -- its result.num_turns; pi/codex = count of assistant model responses. A harness-effort
  -- metric (display only, NOT ranked). NULL when no transcript was captured. Populated live
  -- from token_usage and authoritatively by tools/backfill_turns.py.
  turns              INTEGER,
  UNIQUE(run_id, config_id, task_id));

CREATE INDEX IF NOT EXISTS attempt_by_cell ON attempt(config_id, task_id);
CREATE INDEX IF NOT EXISTS attempt_by_run  ON attempt(run_id);

-- attempt lifecycle/provenance events --------------------------------------
-- Not a scoring store: structured timing/provenance for /run timelines + live
-- diagnostics. Events before an attempt row exists are keyed by run/config/task_id;
-- once evaluation_id is known it may be filled in too.
CREATE TABLE IF NOT EXISTS attempt_event(
  id            INTEGER PRIMARY KEY,
  evaluation_id TEXT REFERENCES attempt(evaluation_id),
  run_id        TEXT NOT NULL REFERENCES run,
  config_id     TEXT NOT NULL,               -- advisory soft-ref (-> agent temp table)
  task_id          TEXT NOT NULL,
  ts            TEXT NOT NULL,
  phase         TEXT NOT NULL,
  message       TEXT,
  source        TEXT NOT NULL DEFAULT 'harness', -- harness | backfill | file_mtime | ...
  confidence    TEXT NOT NULL DEFAULT 'high',    -- high | medium | low
  data_json     TEXT,
  UNIQUE(run_id, config_id, task_id, phase, ts, source)
);
CREATE INDEX IF NOT EXISTS attempt_event_cell_idx ON attempt_event(run_id, config_id, task_id, ts);
CREATE INDEX IF NOT EXISTS attempt_event_eval_idx ON attempt_event(evaluation_id, ts);

-- best-effort runtime provenance for reproducibility -----------------------
-- One row per attempt, captured by the harness at run time. The projected columns
-- make common audit questions cheap; data_json preserves the full nested payload.
CREATE TABLE IF NOT EXISTS attempt_provenance(
  evaluation_id            TEXT PRIMARY KEY REFERENCES attempt(evaluation_id),
  captured_at              TEXT NOT NULL,
  harness_name             TEXT,
  harness_git_commit       TEXT,
  harness_git_branch       TEXT,
  harness_git_dirty        INTEGER,
  harness_git_status       TEXT,
  harness_git_diff_sha256  TEXT,
  python_version           TEXT,
  platform                 TEXT,
  agent_cli_name           TEXT,
  agent_cli_version        TEXT,
  agent_command            TEXT,
  sanitized_config         TEXT,   -- F6: REDACTED pi/claude config (settings+provider block+env, secret-safe); carries its own sha256
  data_json                TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS attempt_provenance_harness_idx
  ON attempt_provenance(harness_name, harness_git_commit);
CREATE INDEX IF NOT EXISTS attempt_provenance_cli_idx
  ON attempt_provenance(agent_cli_name, agent_cli_version);

-- persistent annotation table: invalidation (a DB edit, not curation) -------
-- W23: annotations are ASYNC + human-reviewed. `status` gates whether an annotation
-- affects ranking (ONLY 'accepted' does). `kind` is an OPEN string so new validators
-- need no schema change.
CREATE TABLE IF NOT EXISTS invalidation(
  id         INTEGER PRIMARY KEY,
  kind       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'accepted' CHECK(status IN('proposed','accepted','rejected')),
  source     TEXT NOT NULL DEFAULT 'human'    CHECK(source IN('rule_based','llm_agent','human')),
  confidence REAL,
  evidence   TEXT,
  config_id  TEXT,                           -- advisory soft-ref (-> agent temp table)
  run_id     TEXT REFERENCES run,
  task_id       TEXT,
  reason     TEXT NOT NULL,
  created_at TEXT,
  produced_by TEXT);

CREATE UNIQUE INDEX IF NOT EXISTS invalidation_uniq
  ON invalidation(kind, IFNULL(config_id,''), IFNULL(run_id,''), IFNULL(task_id,''));

-- notes: comments / hints / evidence attached to a subject (NEVER affect scoring) --
CREATE TABLE IF NOT EXISTS note(
  id           INTEGER PRIMARY KEY,
  subject_type TEXT NOT NULL,              -- run | task | legacy_invalidation | ...
  subject_id   TEXT NOT NULL,              -- evaluation_id for run, the task id for task
  source       TEXT NOT NULL DEFAULT 'human',
  body         TEXT NOT NULL,
  evidence     TEXT,
  produced_by  TEXT,
  confidence   REAL,
  created_by   TEXT,
  created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS note_subject_idx ON note(subject_type, subject_id);

-- human-controlled run scoring exclusions (the ONLY table that affects scoring) --
CREATE TABLE IF NOT EXISTS run_exclusion(
  evaluation_id TEXT PRIMARY KEY REFERENCES attempt(evaluation_id),
  reason        TEXT NOT NULL,
  decided_by    TEXT NOT NULL,
  decided_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS run_exclusion_decided_idx ON run_exclusion(decided_at);

-- validation metadata: which attempt was validated, by which validator VERSION ----
CREATE TABLE IF NOT EXISTS validation(
  evaluation_id     TEXT PRIMARY KEY REFERENCES attempt(evaluation_id),
  validated_at      TEXT NOT NULL,
  validator_version TEXT NOT NULL,
  result            TEXT);

-- query-time TEMP tables (reader loads from git-tracked files each request; the file is
-- the single source, the DB persists no copy). The shared definitions, kept as comments:
--   CREATE TEMP TABLE task(         -- from zbench-tasks/tasks/<task_id>/meta.json
--     task_id TEXT PRIMARY KEY, lang TEXT NOT NULL, component TEXT, issue_type TEXT,
--     base_commit TEXT, fix_commit TEXT, difficulty TEXT,
--     curation_status TEXT NOT NULL, resolved_date TEXT, summary TEXT);
--   CREATE TEMP TABLE task_test(     -- from meta.json fail_to_pass_testfuncs
--     task_id TEXT, testfunc TEXT, PRIMARY KEY(task_id, testfunc));
--   CREATE TEMP TABLE agent(        -- from agents-*.jsonl (env) + agents-meta.jsonl
--     config_id TEXT PRIMARY KEY,   -- == attempt.config_id (the soft-ref target)
--     model_name TEXT, provider TEXT, harness TEXT, open_weight INTEGER,
--     timeout_s INTEGER);           -- joined for the leaderboard's model/provider/weight cols
-- NOTE (reader port): agents-meta.jsonl must cover RETIRED config_ids too (the dims used
-- to be a historical registry); rows whose config_id has no agent-file entry get NULL
-- model/provider (best-effort) -- keep agents-meta.jsonl comprehensive.
