# zbench task corpus and curation

> Plane: INTERNAL_RUNBOOK. Currency: CURRENT. Owner: task-corpus. Current-number policy:
> dynamic; use `python3 zbench-tasks/corpus.py`.

This subtree owns task mining, curation, oracle validation, and task metadata for the
zbench target repo (github.com/zulip/zulip). The previous internal-codebase
incarnation's pipeline is in git history.

## Task dir anatomy

`tasks/<task_id>/` (task_id = `ZT-<sha12 of fix commit>`; content-addressed, opaque to
the harness) is the canonical record for EVERY judged candidate. See
`tasks/ZT-472ca78bc26f/` for the full validated shape.

- `meta.json` -- curation SoT: `task_id`, `curation_status`, `reason_code`/`reason`,
  `summary`, `type` (bug|feature|other, from issue labels), `lang` (py|web), `issue`,
  `fix_commit`/`base_commit`, `env_fingerprint`, `fail_to_pass`/`pass_to_pass`,
  `contamination{fix_public_at, issue_created_at, cohort_cutoff_used,
  cutoff_buffer_days, tier, ...}` (see `METHODOLOGY.md`), `source{commit_url,
  issue_url}`, plus `flake_check` and `review.oracle` evidence once validated.
- `problem_statement.md` -- issue-derived, sanitized; the ONLY narrative the agent sees.
- `gold_test.patch` -- the hidden verifier; headerless `git diff parent..fix` path
  split (no commit message anywhere). Applied only at grading time.
- `gold_code.patch` -- the same kind of split for the FIX, but stored OUTSIDE the task
  dir, in `zbench-tasks/solutions/<task_id>/` (see `solutions/README.md`). It is the
  answer key; keeping it out of the agent-visible directory is defence in depth.
  Resolve it with `config.gold_code_path()`, never by joining the task dir -- the helper
  also handles a corpus prepared before the split.
- `instance.jsonl` -- the harness contract: `instance_id = zbench_<task_id>`,
  `commit = base`, inline `metadata.gold_test_patch` TEXT (portable; no
  authoring-machine paths), and `commands.tests` = one shell string:
  `bash "${ZBENCH_SCRIPTS:?}/zbench_verify.sh" backend|node <f2p...> <p2p...>`.
  `fix_commit` is deliberately NOT in instance metadata (public-repo leak).
- `card.md` -- reviewer card (shape: `TASK_CARD_TEMPLATE.md`).

Dropped/invalid candidates keep a meta-only stub (+ gold patches when the split ran):
the ledger that lets batch runs skip re-judging.

Active corpus membership is derived only from `curation_status == "validated"`.
Check current state: `python3 zbench-tasks/corpus.py [--status '*']`.

Status values (reason codes in parentheses):

- `validated` -- oracle-sound (`oracle_validated`): flip + P2P green, flake-gated.
- `held` -- prepped, oracle pending (`pending_oracle`, e.g. `--no-oracle`).
- `invalid` -- oracle ran, no flip (`oracle_base_passed`, `oracle_invalid`).
- `dropped` -- rejected during curation: `no_issue_ref`, `partial_fix`,
  `touches_migrations`, `dep_change`, `no_test`, `test_only`, `mixed_lang`,
  `out_of_scope`, `i18n_churn`, `revert`, `docs_only`, `issue_missing`, `issue_is_pr`,
  `sparse_issue`, `unsuitable`, `symbol_coupling`, `f2p_unenumerable`,
  `oracle_not_enumerable`.

## Add a task (`prepare_task.py` -- THE way)

```bash
python3 zbench-tasks/mine_candidates.py --stats           # discovery: pure git-log read
python3 zbench-tasks/prepare_task.py <fix_sha> [--no-oracle] [--fast-oracle]
```

Mining predicate (`config.py`; re-checked at prep): non-merge commit on `origin/main`
with a FULL `Fixes #N` (`Fixes part of` rejected) + >=1 test file + >=1 code file,
single-language py|web, no `**/migrations/**`, no dependency-manifest changes (they
would mutate the env fingerprint).

`prepare_task.py` stages (cheap deterministic gates -> LLM -> heavy oracle last):

1. dedup (existing `tasks/ZT-<sha12>/` aborts) + predicate re-check;
2. scope gate: commit date >= `ZBENCH_MIN_COMMIT_DATE` (default 2025-01-01) and
   ancestor of `origin/main`; contamination-tier block from `agents-meta.jsonl`
   training cutoffs;
3. headerless patch split; deterministic unsuitability pre-filters (i18n churn,
   revert, docs-only);
4. GitHub issue fetch via `gh api` -- title+body ONLY (comments are leak vectors);
   sparse issue -> `dropped/sparse_issue`, never a fallback;
5. pinned-LLM screens (`ZBENCH_LLM=claude|pi`, model claude-fable-5): suitability,
   then coupling;
6. fail_to_pass: AST-first extraction from gold_test (LLM fallback re-verified
   against the AST; web = file granularity); pass_to_pass: test modules of the code
   modules gold_code touches, capped at 2;
7. issue-only problem statement (commit message forbidden) + deterministic leak
   strips (fix sha at 3 lengths, `#N` refs, github/zulip URLs);
8. oracle (below).

Exit 75 = infra, NOTHING written (retry). Exit 70 = script error, nothing written.
Otherwise a task record is written atomically (staging tempdir -> rename).

## Oracle contract (`oracle_validate.py` + `verdict.py`)

VALID iff, in the fingerprint-matched env image (`zbench-env:<fp12>`; built by
`scripts/build_env_image.sh`):

- arm A (base + gold_test): f2p FAILS 2x with a STABLE failure signature AND p2p green;
- arm B (+ gold_code): f2p PASSES 3x AND p2p green.

`verdict.py` parses the runner OUTPUT -- exit codes cannot distinguish ran-and-failed
(the flip signal) from could-not-run. NOTRUN (typo'd target, import error before any
test, `Ran 0 tests`) is UNENUMERABLE, never INVALID: a broken enumeration must not
read as a flip. Exit: 0 VALID | 1/2 INVALID | 3 UNENUMERABLE | 70 script | 75 infra.
`--fast` = 1 run per arm, development only.

The verify path is shared with grading: `scripts/zbench_verify.sh` IS a task's
`commands.tests` string. It fingerprints the worktree itself, then runs
`scripts/inner_verify.sh` in a `--network none` container with the worktree mounted
READ-ONLY; the patch delta transfers via `git diff --binary HEAD` + untracked-file
copy (a tree-level rsync was rejected: it clobbered provision artifacts). Wrapper
exits: 64 wrong cwd | 65 missing env image | 124 timeout.

## Fill after validated task changes

Canonical fill + review workflow: [`RUNBOOK.md`](../RUNBOOK.md) ("Filling the grid" /
"Post-run review"). Gridding is separate from curation -- fill after validation.

## Important files

- `config.py` -- every Zulip-specific tunable: target repo, mining predicate,
  `FP_FILES`, pinned curation LLM. The harness never imports it.
- `mine_candidates.py`, `prepare_task.py`, `oracle_validate.py`, `verdict.py`,
  `env_fingerprint.py` -- the pipeline (above).
- `scripts/` -- `build_env_image.sh`, `zbench_verify.sh`, `inner_verify.sh`,
  `gc_env_images.sh`.
- `corpus.py` -- derives candidate/task sets from per-directory `meta.json`.
- `run_coverage_matrix.py` -- validated-corpus coverage report/fill launcher.
- `failure_modes.py` -- non-resolve buckets for ranked corpus attempts.
- `validate_runs.py` -- notes-only judges: contamination (GIT_SIGNAL/NET_SIGNAL
  prefilter -> two-channel LLM judge) + patch-similarity on every RESOLVED attempt
  (see `METHODOLOGY.md`).
- `agents-matrix.jsonl` -- active ranked/fill cohort. `agents-meta.jsonl` -- model
  metadata incl. `training_cutoff`/`cutoff_source`/`cutoff_confidence` + `web_tools`.
  Cutoffs MUST be filled from vendor model cards before ranking; until then the
  contamination tier stays UNKNOWN (and is recomputable).
- `TASK_CARD_TEMPLATE.md` -- the card shape `prepare_task.write_card` emits.
