# zbench eval methodology

> Plane: PRODUCT_PUBLIC. Currency: CURRENT. Owner: methodology. Current-number policy:
> dynamic only; current board/corpus numbers come from the dashboard or `tools/readout_snapshot.py`.

This is the single home for the eval's validity and ranking rules: what we measure,
what counts as a valid task/run, how we rank agents, and why the result is trustworthy.
Operational runbooks live in `RUNBOOK.md`, `tools/README.md`, `zbench-tasks/README.md`, and
`zbench/README.md`.

## 1. Unit of work and pipeline

- **Task:** one real past Zulip fix -- a mainline commit closing a GitHub issue, with its
  tests in the same commit -- turned into a coding challenge. Task ids are
  `ZT-<sha12 of the fix commit>` (content-addressed; never shown to the agent).
- **Agent:** one model x harness x provider x thinking configuration (`agent_id`). Do not
  collapse across harnesses or providers.
- **Cell:** one `(task, agent_id)` pair.
- **Attempt:** one execution of a cell, preserved immutably in `bench-db/bench.db` and
  identified by `evaluation_id` / `run_id`.

Pipeline:

1. **Mine** candidates from the local Zulip clone's git history
   (`zbench-tasks/mine_candidates.py`): non-merge mainline commit with a full `Fixes #N`,
   at least one test and one code file in the same commit, single-language (`py` | `web`),
   no migrations, no dependency-manifest changes.
2. **Prepare** (`zbench-tasks/prepare_task.py`): dedup and predicate re-check, date +
   mainline scope gate, contamination-tier record (section 5), headerless patch split of
   the real fix (`gold_code`) from the hidden verifier (`gold_test`), pinned-LLM screens
   (suitability -- verifiability-first; coupling -- three-way, below), problem statement
   from the linked GitHub issue plus expected-behavior evidence from the gold test diff
   plus any interface contract (commit message forbidden) with deterministic leak strips,
   f2p/p2p target extraction. Every judged candidate is an atomic record under
   `zbench-tasks/tasks/ZT-*/`.
3. **Oracle-validate** the task in its fingerprint-matched docker image (section 2).
4. **Run the grid** through `zbench.cells.run_cell` / `run_coverage_matrix.py`.
5. **Aggregate and rank** over the immutable attempt rows plus the scoring-exclusion overlay.

## 2. Task validity: the oracle invariant

Each candidate directory's `meta.json` carries `curation_status in {validated, invalid, held, dropped}`.
`validated` is the machine gate (the oracle flip below) and is what the board ranks on;
each task's contamination tier (section 5) rides along as an annotation, not a filter.
Human review (below) is **strongly recommended when a task bank is first built** and
optional afterwards; `zbench-tasks/corpus.py` `ranked_ids` returns the reviewed subset for
teams that want to publish on reviewed tasks only.

**Human-review gate.** The oracle proves a task mechanically flips; it does not prove the
task is a *good benchmark item*. A commit can flip correctly and still ship a leaky problem
statement, an under-specified goal, or an incidental change the screens missed. Following
the practice that automated task construction needs hand review (Databricks; see
[`docs/benchmark-best-practices.md`](docs/benchmark-best-practices.md)), a reviewer reads
the card + gold patches + the agent-visible problem statement and signs off with
`review_task.py`, stamping `meta.review.reviewed_by`.

**When to review.** Review is strongly recommended to verify tasks *initially*: when you
first stand up a task bank (or point the miner at a new codebase), hand-review the
validated tasks, or at least a large sample, to confirm the screens, briefs and oracle are
producing good items. Once that initial pass has shown the pipeline is trustworthy, review
of further tasks is optional; the oracle gate alone decides inclusion. (The shipped zbench
board ranks on all oracle-validated tasks; no per-task review stamps are recorded.) We *reject* brittle
(exact-string / non-deterministic) tests rather than rewrite them, keeping the upstream test
as-is at the cost of a smaller corpus.

A task is `validated` (`zbench-tasks/oracle_validate.py`) iff, in the fingerprint-matched
env image:

- **arm A** (`base + gold_test`) **fails** `fail_to_pass` -- twice, with a stable failure
  signature -- and **passes** `pass_to_pass`, and
- **arm B** (`base + gold_test + gold_code`) **passes** `fail_to_pass` -- three times --
  and **passes** `pass_to_pass`.

Refinements on the bare flip:

- **P2P in both arms.** `pass_to_pass` (a capped set of neighboring test targets) must be
  green in BOTH arms, so a task whose surroundings are already red cannot validate, and a
  gold fix that breaks its neighbors cannot either.
- **Flake gate.** The repeat counts (fail arm 2x same signature, pass arm 3x) reject flaky
  flips; counts and signature stability are recorded in `meta.flake_check`.
- **f2p semantics.** `fail_to_pass` is the fix commit's added/modified test set. A member
  test MAY already pass at base; the stable failure signature records which tests actually
  flip (see `ZT-472ca78bc26f`: three f2p targets, two in the signature).
- **NOTRUN is never a flip.** A target that could not run -- bad dotted target, import
  error before any test, `Ran 0 tests` -- is `UNENUMERABLE`, never `INVALID`.
  `zbench-tasks/verdict.py` parses runner output because exit codes cannot distinguish
  ran-and-failed from could-not-run.
- **Env pinning.** The oracle runs in `zbench-env:<env_fingerprint>`; the validated image
  digest is pinned on the task (`env_image_digest`), and grading is comparable only inside
  that digest.

If the hidden test passes at base, the task cannot distinguish a real fix from no fix and is
not ranked.

**Standing decision (2026-08-14): VERIFIABILITY is the sole inclusion bar; target ~100
validated tasks.** Task type is not a gate -- bug fixes, features, and behavior-affecting
refactors all qualify if they are a real engineering workflow and the hidden test grades a
deterministic, observable outcome. Difficulty is not a gate either (the corpus may span
trivial through difficult; `complexity.bucket` records it). We still reject what cannot be
graded on outcome: behavior-free refactors/renames, reverts, i18n/locale churn,
changelog/feature-level-verbatim tests, and brittle exact-snapshot tests (deterministic
pre-filters plus the pinned-LLM screens in `prepare_task.py`).

**Symbol coupling is three-way.** A hidden test that binds to names the fix introduces is
judged by whether a spec could legitimately hand the solver those names:
- `clean` -- the test uses only pre-existing interfaces. Nothing to add.
- `specifiable` -- the test binds to new PUBLIC contract surface (a setting name, an API
  field, a public function, a DOM id, a user-facing message). The required names and
  semantics are written into the problem statement as "Interface requirements", so the
  test grades correctness, not name-guessing. Recorded on the task
  (`interface_requirements`).
- `coupled` -- the test binds to internal implementation choices no reasonable spec would
  dictate (private helpers, mock targets, internal field names, exact log wording).
  Dropped: passing would require knowledge a human engineer would not have.

Thin issues no longer auto-drop: the problem statement may draw expected-behavior evidence
from the gold test diff, phrased as product requirements (never revealing that tests
exist). A task drops (`insufficient_spec`) only when no determinate, checkable outcome can
be stated from all sources combined.

When several valid fixes are possible but the hidden test accepts only the reference-fix
behavior, interpret a pass as "matches the reference behavior," not as "the only correct fix."
Record that solution-path specificity on the task card.

## 3. Run validity: immutable attempts plus scoring exclusions

A task-invalid result removes the task from the ranked corpus. A run-invalid result excludes
only a specific attempt; the task and other agents' attempts remain intact.

Rules:

- Attempts are immutable facts. Never delete or rewrite an outcome to make the board nicer.
- Corrections are an overlay. `run_exclusion` is the current scoring anti-join: if a row exists
  for an `evaluation_id`, that attempt is excluded from ranking; otherwise it is included.
- `note` and legacy `invalidation` rows are evidence/comments, not the ranking switch.
- Evidence blobs under `bench-db/blobs/attempt/<evaluation_id>/` are preserved.

Typical exclusion reasons:

- `[contamination]` - the agent found the answer in the environment (future git history) or
  fetched it from the public internet instead of solving the task (section 4).
- `[artifact:infra]` - auth/provider/build/serving/disk failure rather than model capability.
  This includes the `provider_error` attempt status: the model endpoint refused or dropped
  the request (429 / throttled stream / 5xx / auth), so the agent never finished a turn.
  Note a throttled gateway may answer `200` and then kill the stream mid-turn, so an
  adapter must read its CLI's own event stream, not just the process exit code, to tell a
  throttle from a give-up.
- `[artifact:harness]` - benchmark/harness bug such as known patch-loss windows.
- `[broken_config]` / `[superseded]` - obsolete or incomparable configuration.

A `no_patch` caused by a matched turn/step/time budget on a hard task is normally a valid
capability outcome, not an exclusion. The boundary is whether the benchmark/environment failed
or silently lost a real patch.

**Cross-agent parity of stopping conditions.** The "matched budget" rule above assumes the
budget is EQUAL across agents. Capability-affecting knobs -- turn/step caps, timeouts,
context/token budgets, tool access, retries -- must be equalized so agents run under equivalent
stopping conditions; differing configs are fine, but none may silently handicap one agent's
chance to finish. A run that terminates because of an ASYMMETRIC knob is a `[broken_config]`
artifact (exclude + re-run), NOT a valid capability outcome. (Concrete precedent: an early
claude `--max-turns` cap the pi harness did not have -- incident + remediation in project
history; board caveat in the readout.)

**Reasoning effort is such a knob, and every ranked row must PIN it.** Each harness exposes
it differently -- pi `--thinking`, claude `--effort`, codex `-c model_reasoning_effort` -- and
an unset knob is not "neutral": it is the vendor's default, which is unrecorded, differs
between vendors, and can change under a CLI upgrade, silently splitting a corpus across two
settings. Ranked rows therefore state the level explicitly. The vocabularies differ per
harness and only `low`/`medium`/`high`/`xhigh` are common to all three (claude alone has
`max`; pi/codex alone have `off`/`none`/`minimal`), so the pinned level must come from that
common set. Current pin: `high` -- chosen because most rows already ran there, NOT because it
is the ceiling; `xhigh` is also expressible everywhere.

Pinning makes effort DECLARED, not equal: `high` drives a thinking-token budget on Anthropic
models and OpenAI's `reasoning_effort` on GPT models -- different mechanisms. The defensible
claim is "every agent ran at its harness's `high` setting, recorded per attempt", NOT "all
agents received equal thinking". Nor does accepting the parameter imply honoring it: probing
the Foundry backends (2026-08-15) found the gpt-5.x family scales reasoning tokens with the
level while the Fireworks-hosted open-weight deployments accept it with no reasoning-token
accounting and no measurable effect. Worse, a HARNESS can drop the setting: codex accepts
`model_reasoning_effort` in config but sends `reasoning: null` on the wire for every
custom-provider row, so all codex agents are currently effort-uncontrolled regardless of what
their rows say. `agents-meta.jsonl` records this per agent as `effort` + `effort_evidence`
(honored | accepted | inert | not_delivered | unverified); only `honored` supports reading a
result as an effort-controlled comparison.

## 4. Isolation and test blindness

- The model never sees `gold_test`; the hidden test is applied only during verification.
- Before `gold_test` is applied, ANY agent edit to the protected pathspecs is reverted to
  base: the test trees (`**/tests/**`, `**/tests.py`, `**/test_*.py`, `**/conftest.py`,
  `**/*.test.*`, `web/e2e-tests/**`) AND the runners grading executes from the worktree
  (`tools/test-*`, `tools/ci/**`, `tools/lib/**`) -- an unreverted runner edit would be an
  exit-0 backdoor (`zbench/workflow.py::_TEST_PATHSPECS`). A runner-integrity hash check
  after the strip aborts grading as `internal_error` -- never resolve -- on any residual
  difference.
- Verification runs in a `--network none` container with the worktree mounted read-only
  (`zbench-tasks/scripts/zbench_verify.sh`): a determinism boundary and an
  anti-exfiltration boundary.
- Each run uses isolated model/CLI config (`CLAUDE_CONFIG_DIR`, pi session/config controls).
- Each worktree contains only the base commit, with no future fix reachable through git
  history. Suspicious contamination is handled by evidence review plus `run_exclusion`.
- Web tools (fetch/search) are disabled in every agent config, recorded per agent in
  `zbench-tasks/agents-meta.jsonl` (`web_tools`); an enabled config is `[broken_config]`.

**Generation-network stance.** Generation -- the agent's solve phase -- is NOT
network-isolated. That caveat is printed with every board, never hidden. The layered
defense: (0) web tools disabled per above; (1) transcript audit -- `validate_runs.py`
NET_SIGNAL needles (github/raw/commit URLs, curl/wget/clone, structured web-tool call names,
the task's stripped fix SHA or issue number appearing anywhere) feeding a two-channel LLM
judge (environment mining vs network fetch); (2) a patch-similarity judge on every RESOLVED
attempt -- deterministic pre-metrics plus LLM judging of entropy-bearing matches with the
public gold fix, tier-aware (section 5); (3) prompt-level prohibition, which converts a
detected fetch into an unambiguous `[contamination]`. An egress proxy is future work. Judge
notes never auto-exclude; a human sets `run_exclusion` (section 3 governance unchanged).

## 5. Contamination model (public repo)

Zulip is public and in every vendor's training data, so task recency is the only real
contamination defense, and the **best practice** is to rank only on tier-A tasks (fixes
newer than every cohort model's training cutoff plus buffer).

**Standing decision (2026-08-14): the tier is advisory, not a gate.** Boards keep every
validated task regardless of tier. Rationale: zbench is a template for evals over
enterprise/private codebases, where the target repo is in no vendor's training data and the
recency gate is moot; enforcing it on the public-Zulip demonstration corpus would shrink it
to near zero (frontier models ship monthly, with cutoffs at or past the newest available
fix -- under the 2026-08 cohort the strict gate leaves 0 of 14 validated tasks). The
contamination caveat is therefore DISCLOSED rather than gated: every board carries per-task
tiers and the pre-vs-post-cutoff resolve-rate split (below). A leakage-sensitive consumer
filters to tier A themselves.

**Tiers**, computed per task from `fix_public_at` (committer date of the fix) against the
active cohort's training cutoffs:

- **Tier A** -- fix postdates the cohort MAX cutoff plus a buffer (`cutoff_buffer_days`,
  default 30). Rankable.
- **Tier B** -- fix postdates only some cutoffs, or falls inside the buffer. Exploratory.
- **Tier C** -- fix predates all cutoffs. Probe/calibration only (known-memorizable).

The tier is a corpus-level annotation rather than a per-(model, task) mask: masking would
hand each agent a different task set and break the common-task-set rule (D1, section 6).

Mechanics:

- **Frozen inputs, recomputable tier.** `prepare_task.py` freezes the inputs in
  `meta.contamination{}` (`fix_public_at`, `issue_created_at`, `cohort_cutoff_used`,
  `cutoff_buffer_days`, `tier_computed_at`); the tier is recomputable from them whenever
  the cohort or a cutoff changes (`zbench-tasks/scripts/recompute_tiers.py`). Boards are
  pinned to a corpus epoch -- the task set and tier annotations they ranked over -- and
  **cross-epoch comparisons are invalid**.
- **Cutoff source of truth.** `agents-meta.jsonl` fields `training_cutoff` /
  `cutoff_source` / `cutoff_confidence`. An agent without a cutoff CANNOT be ranked -- the
  pipeline fails loud, and tiers stay `UNKNOWN` until cutoffs exist. Filled 2026-08-14 from
  vendor model cards (`cutoff_confidence: vendor_stated`); vendors that publish no cutoff
  (Moonshot, DeepSeek, Zhipu) carry their model's release date as a conservative upper
  bound (`cutoff_confidence: release_date_upper_bound`).
- **Two date dimensions.** The fix date is gated; the issue-created date is NOT (we hand
  the agent the problem statement anyway). `issue_created_at` / `issue_pre_cutoff` are
  recorded as diagnostics, and the pre-vs-post-cutoff resolve-rate split is reported as a
  leakage diagnostic. An issue-thread solution-leak scan (pre-cutoff code in comments,
  linked PRs) is planned; a confirmed leak caps the task at tier B.
- **Tier-aware judge semantics.** For the patch-similarity judge (section 4): a
  verbatim/entropy-bearing match with the gold fix on a **tier A** task implies a runtime
  fetch or a wrong cutoff (exclusion + task review); the same match on **tier C** is
  expected memorization and calibrates the detector.

## 6. Measurement and ranking

The sole capability metric is **binary resolve**: the hidden test passes or it does not.
The ranked corpus is the validated set (section 2; human review recommended initially, optional after), tier-annotated (section 5).

**Standing decision (2026-08-17, project owner): EVERY model we run appears on the board.**
Board membership is no longer gated on a sourced `training_cutoff` (the section 5 gate),
because researching a cutoff per model would materially shrink what we can test. The
cutoff field stays in `agents-meta.jsonl` and is still filled when a vendor states one --
it is now an annotation for contamination reading, not an admission requirement. A row
with `cutoff_confidence: missing` is ranked like any other and prints the gap.

**Standing decision (2026-08-17, project owner): rank order is pass rate (desc), then
cost per task (asc).** Cost is part of the rank, not merely display order inside a tie:
at equal pass rate the cheaper agent ranks higher. Pass *rate* rather than raw resolve
count is the primary key so cohorts with different coverage stay comparable. Ties share a
rank only when both keys match.

**Standing decision (2026-08-18, project owner; supersedes + removes the earlier hardware-amortisation
model W150): self-hosted open-weight models are priced at a PUBLIC-HOST per-token reference,
not by capex amortisation and not `free*`/$0.** The `$/task` on the board is now ONE formula
for everyone -- captured tokens (input + output + cache_read + cache_write) x a list price --
so an on-prem model and a cloud model are directly comparable per token. The list price for a
self-hosted open-weight model is what a public host would charge to serve the same weights:
- most open models already resolve to a host in `tools/prices/models_dev.json` (Fireworks for
  DeepSeek, Moonshot for Kimi, Zhipu for GLM, a reference list price for Qwen3-Coder);
- the truly local vLLM/local models carry a hand-authored reference in
  `tools/prices/open_weight_hosted.json` (e.g. `gpt-oss-120b` at the Fireworks/Together rate).
- `model_prices.price_key()` no longer short-circuits self-hosted markers to `None`; each model
  resolves to ITS OWN reference key (specific build keys are matched before broad catch-alls, so
  `pi-vllm-qwen3.6-27b` cannot collide with the `qwen3-coder` rate).

A self-hosted open-weight model with NO public reference yet (its `open_weight_hosted.json`
entry is `needs_price`) still renders `free*` and `cost_known=False`; read `free*` as "no
reference price found yet", not "no cost". `consistency_check` warns for each such model, and
`tools/price_search.py` re-checks daily and fills a price in when one appears.

Ranking decisions:

1. **Common task set.** Rank on tasks attempted by every ranked agent. Comparing different task
   subsets is not meaningful.
2. **Infra-limited task drop (D1b).** If a task is unscoreable for an otherwise-covered agent
   purely due to infra/serving limits, drop that task from the common set and report the caveat.
3. **Rank per `agent_id`.** A model through pi vs claude CLI vs another provider is a different
   ranked entity.
4. **Per-task aggregation.** For each `(agent, task)`, reduce non-excluded valid attempts to a
   pass rate: `valid passes / valid runs`. Sum those pass rates over the common set.
5. **Cost/latency/tokens/turns are separate columns.** They are not folded into capability score.
   **Turns/task (2026-08-18)** = the agentic model round-trips a harness took, averaged over the
   common set (a display effort metric, NOT ranked). It is read from each attempt's transcript
   PER HARNESS's own definition -- claude `result.num_turns`; pi = assistant-response messages;
   codex = completed action items (one command/tool call or message; codex wraps a whole task in
   a single thread-`turn`, so `turn.*` is not used). The definitions differ, so compare turns
   WITHIN a harness, not across. Stored in `attempt.turns` (live capture + `tools/backfill_turns.py`).
6. **Small gaps are soft ties.** Show counts (`resolved/common`) and use standard competition
   ranks; at small N, 1-2 tasks are not a decisive difference.
7. **No difficulty weighting for now.** The task x agent matrix stays visible so the difficulty
   mix is inspectable, but the primary score is unweighted binary resolve.
8. **Pareto frontier (capability vs cost).** Capability is a single number, but agents differ
   wildly in price, so the leaderboard also reports the 2D **Pareto frontier**: capability =
   common-set resolve rate (higher better) vs cost = the canonical uniform *computed* $/task
   (`cost_usd/n`, W137 pricing -- apples-to-apples across harnesses, NOT a harness-reported
   bill). An agent is **on the frontier** (non-dominated) iff no other agent
   is both cheaper AND at least as capable; it is **dominated** iff some agent beats it on one
   axis and ties-or-beats it on the other. Ties (identical cost and rate) co-dominate and both
   stay on the frontier. This is a VIEW over the same numbers, not a new score -- capability is
   still the primary ranking; the frontier just makes the cost/capability trade-off explicit
   (e.g. a cheap open-weight model that is not the most capable can still be non-dominated).
   Self-hosted local agents legitimately sit at very-low-cost / mid-capability -- no special
   handling is needed in 2D because their cost genuinely is tiny. A 3D variant that adds
   latency (time/task) is intentionally deferred: local serving speed is hardware-bound and
   apples-to-oranges vs hosted providers, so it would need its own caveat.
   **Practical-equivalence tolerance (W145).** At small N a 1-2 task capability gap is noise,
   so the frontier applies a tolerance band on the capability axis (default 2 percentage
   points; `ranking_view.DEFAULT_PARETO_TOLERANCE`, override via env `ZBENCH_PARETO_TOLERANCE`).
   Two resolve rates within the band are treated as EQUAL, so a CHEAPER agent within the band
   of a pricier one dominates it ("cheaper wins when practically equivalent"). It is computed
   by taking the EXACT frontier and THINNING it cheapest-first -- keep a point only if its
   capability exceeds the last kept point's by at least the tolerance, else fold it into that
   cheaper equivalent. Thinning the exact frontier (rather than a pairwise epsilon-dominance
   rule) is deliberate: it avoids a CHAINING artifact where a run of within-tolerance neighbors
   would transitively fold away a genuinely-better point (e.g. $1/70%, $2/71.5%, $3/73% at 2%
   correctly keeps {70%, 73%}, not just {70%}). Folded agents are reported as "practically
   equivalent" (readout `~`, dashboard faded dot), distinct from strictly dominated (blank /
   hollow). Bigger tolerance can only shrink the frontier, never re-add a dominated agent.
   Tolerance applies to capability only -- cost differences are always treated as real.
   **Partial-coverage agents in the frontier (W147).** The CANONICAL frontier (readout `PF`
   column, METHODOLOGY numbers) is **ranked-agents-only** -- computed over the common set, so
   every point is apples-to-apples. Partial-coverage agents (relegated because they are missing
   common-set tasks, e.g. a still-gridding local agent) are ranked on their OWN, smaller task set,
   so their resolve rate is NOT directly comparable. On the DASHBOARD only, the "show
   partial-coverage agents" checkbox controls an interactive view: when checked, partials
   PARTICIPATE in the frontier (plotted as diamonds colored by their resulting tier -- a partial
   can land on, fold into, or dominate the frontier using its own-set rate); when unchecked, they
   are hidden and the frontier is ranked-only. The participating view is EXPLORATORY (own-set
   rate is not apples-to-apples), which is why it is opt-in and never the canonical/readout
   number. The `pareto_frontier()` computation itself is unchanged -- only the point set fed to
   it differs (ranked, or ranked+partial).

Current implementation: `tools/benchdb_reader.py` builds the valid attempt view, and
`tools/ranking_view.py` performs the D1-D7 aggregation (including `pareto_frontier()`, which
annotates each ranked row with `on_frontier` / `dominated_by`) used by the dashboard and the
`readout_snapshot.py` `PF` column (both ranked-only). The dashboard additionally renders a
partials-participating variant of the Pareto scatter, swapped in by the "show partial-coverage
agents" checkbox (`tools/bench_dashboard.py`, W147).

## 7. Data durability

Source-of-truth state:

- `bench-db/bench.db` - attempts, runs, attempt provenance, notes, scoring exclusions,
  validation metadata.
- `bench-db/blobs/attempt/<evaluation_id>/` - transcript/log/patch/provenance evidence.
- `zbench-tasks/tasks/<ZT-*>/meta.json` - candidate/task curation status, contamination
  record, oracle evidence, and metadata.
- `zbench-tasks/agents-matrix.jsonl` + `zbench-tasks/agents-meta.jsonl` - active cohort and
  model metadata, including training cutoffs and `web_tools` state.
- `zbench/schema.sql` - persistence schema.

`bench.db` is the single store for scores, evidence, events, and audit state; build readers
against it. `/tmp` is for live/debug scratch only, not required evidence.

## 8. Correctness checklist

- [ ] Task oracle-validated: flake-gated flip (fail arm 2x stable signature, pass arm 3x),
      P2P green in both arms, in the pinned env image.
- [ ] Hidden test is behavioral; any new public names it binds to are handed to the solver
      as Interface requirements (three-way coupling screen, section 2).
- [ ] Problem statement is issue-only (title + body) and sanitized: fix SHA (three lengths),
      issue/PR refs, GitHub/Zulip URLs stripped.
- [ ] Contamination tier recorded and shown on the board (advisory -- section 5); every
      ranked agent has a sourced training cutoff.
- [ ] Per-cell checkout is history-isolated.
- [ ] Agent config/creds are hermetic; web tools disabled.
- [ ] Agent test/runner edits are stripped before hidden-test verification; runner-integrity
      hash verified.
- [ ] Verification containers are `--network none` with a read-only worktree mount.
- [ ] Scoring exclusions are per-attempt overlay rows, not mutations/deletions.
- [ ] Board ranks per agent_id on the common set.
- [ ] Cost, tokens, and latency are shown separately.

## 9. Known caveats and standing decisions

- Items are tasks, not necessarily bugs.
- Public repo: contamination is disclosed, not gated (standing decision 2026-08-14,
  section 5) -- boards keep all validated tasks, tier-annotated. For a leakage-sensitive
  ranking, filter to tier A; that pool grows weekly for free as Zulip merges fixes.
- Vendor training cutoffs are claims, not proofs; for open-weight models, host-side
  fine-tuning is unverifiable.
- Generation is not network-isolated (section 4); the layered audits detect, they do not
  prevent. An egress proxy is future work.
- Paraphrased memorization is undetectable: the similarity judge catches entropy-bearing
  verbatim matches, not re-derivations.
- Issue-thread leakage is reviewed, not airtight.
- Sanitization shifts absolute difficulty: the issue-only, leak-stripped statement is not
  the information the original fixer had. Scores are comparative within one corpus epoch;
  cross-epoch comparisons are invalid.
- Corpus is still small and directional.
- Exclusions are for benchmark/infra artifacts, not for genuine model behavior.
- Multi-judge / human review can be added later from saved patches/logs; it is not the
  primary scoring signal today.
- Pass@k is a future binary extension once the single-try corpus is stable.
