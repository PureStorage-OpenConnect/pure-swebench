# Benchmark best practices (and anti-patterns)

> Plane: METHODOLOGY. Currency: CURRENT. Owner: benchmark-maintainers.

Distilled from Databricks' write-up on benchmarking coding agents against their private
multi-million-line codebase (["Benchmarking Coding Agents on a Databricks
Multi-Million-Line Codebase"](https://www.databricks.com/blog/benchmarking-coding-agents-databricks-multi-million-line-codebase)),
cross-checked against what zbench actually does (adversarial code audit, 2026-08-13).

The blog independently arrived at nearly the same recipe zbench uses, which is a useful
external validation. This doc records the practices, where zbench already follows them,
and the handful of real divergences — with what we changed and what we deliberately did
not. Each item links to code so it stays honest as the code moves.

Items marked ⏳ are decided and land in the mining/prep code once the in-progress corpus
batch finishes (editing files its subprocesses import mid-run would race them); everything
else is already in place. The ⏳ changes are also backfilled onto the existing corpus where
they are deterministic (complexity, author, scope).

## DO

**Source tasks from real, merged, mainline changes.** A busy repo already is the dataset.
zbench mines non-merge commits on `origin/main` that close a GitHub issue and carry both
a code and a test change (`zbench-tasks/mine_candidates.py`, predicate in
`zbench-tasks/config.py`). *Nuance:* our unit is a single commit gated on `Fixes #N`,
which is narrower than "any merged PR" — it biases toward issue-tracked bugfixes. That is
a deliberate spec choice (the issue is our sanitized problem-statement source), not an
oversight.

**Strip the solution from the prompt.** The blog rewrites PR descriptions to state the
problem and goal, *"removing explanations of why a bug fix is the right one, since that
makes the task too easy."* zbench derives the problem statement from the linked GitHub
issue only (never the commit message, which explains the *why*), and applies a
deterministic leak strip for the fix SHA, issue/PR numbers, and GitHub/CZO URLs
(`prepare_task.py` `P_PROB` + `sanitize`).

**Grade with tests, never with an LLM.** The blog is blunt: *"We did not use an LLM judge
to evaluate correctness, since we've found that this rewards sounding right over being
right."* This is zbench's hardest line. Grading is the exit code of the hidden test run
(`zbench/workflow.py`); the oracle's VALID/INVALID/UNENUMERABLE verdict is deterministic
output parsing (`zbench-tasks/verdict.py`). LLMs appear **only** in curation (suitability,
coupling, problem-statement rewriting) and in **audit** (contamination judges that write
notes) — and every LLM curation output is re-verified mechanically before it can matter
(f2p targets are AST-checked; the oracle flip is the real gate).

**Keep the test hidden until grading.** The agent never sees the gold test, its target
names, or the fail-to-pass list — its input is the problem statement plus a checkout
(`zbench/agents/client.py`). The gold test is applied only after the agent finishes.

**Seal the working copy's git history.** The blog's costliest bug: *"the 'correct'
implementation was still recoverable in the Git history of the worktree!"* Their fix:
*"we sealed git history … we cut the working copy off from the repository entirely."*
zbench's isolated checkout is exactly this — a fresh `git init` repo containing only the
base commit, fetched depth-1 with no tags, no origin remote, and no ref that reaches the
fix (`zbench/workflow.py` `_make_isolated_checkout`). *We went further where it's cheap:*
the contamination transcript audit now also flags an agent trying to re-attach a remote or
fetch by `file://` (`validate_runs.py` `GIT_SIGNAL`/`NET_SIGNAL`).

**Cost per task, not per token.** *"Token costs are often a poor indicator of overall task
costs, due to variance in reasoning efficiency amongst models."* zbench's Pareto cost axis
is `cost_usd / n` = $/task (`tools/ranking_view.py`, `tools/model_prices.py`).

**Treat the harness as a first-class axis, separate from the model.** The blog found the
same model at the same thinking effort cost >2x more through one harness than another, at
equal quality (Pi sent ~3x less context per turn). zbench's `agent_id` is
model × harness × provider × thinking and is never collapsed to "the model"
(`METHODOLOGY.md` §1, `ranking_view.py`). *Gap we're closing:* we assert this axis but
don't yet **measure** per-turn context — see "Measure, don't assert, harness efficiency"
below.

**Rank on thematic tiers, not decimal places.** *"Specific results being a couple points
off can often even out."* zbench's Pareto frontier uses a practical-equivalence tolerance
(2 pp default) so near-ties don't create false ordering (`ranking_view.py`).

**Assume public tasks leak, and defend it.** *"The tasks are public, so the solutions leak
into training data over time."* Because Zulip is public (unlike Databricks' private repo),
this is our *primary* threat, not a footnote. Defenses: recency-tiered ranking (tier A =
fix postdates every model's training cutoff), a network-fetch transcript audit, and a
tier-aware patch-similarity judge (`METHODOLOGY.md` §5). We state plainly what is **not**
sealed (generation-time network) rather than implying it is.

## DON'T

**Don't let an LLM decide correctness.** (See above — it rewards plausible over correct.)
zbench keeps LLMs strictly out of the grading path.

**Don't trust a public benchmark to represent your codebase.** The blog built its own
because *"the results weren't representative for our codebase, which spans 10+ languages."*
That is the entire reason zbench exists as a Zulip-specific eval rather than a SWE-bench
score. The flip side: a Zulip eval represents Zulip — Python/Django + a TS web client —
and nothing more; don't over-generalize its numbers.

**Don't ship exact-string / snapshot tests as the grader.** Brittle tests fail on
non-deterministic output and reward format-matching. The blog *rewrites* such tests to
grade behavior. zbench does not rewrite upstream tests (that would forfeit the "real
merged test" provenance); instead it **rejects** brittle tasks — via the coupling screen,
an exact-string/API-changelog screen (⏳ strengthened to feed the actual test diff to the
screen), and a flake gate (fail arm must fail 2× with a stable signature, pass arm 3×,
`oracle_validate.py`). Reject-not-rewrite yields a smaller but provenance-clean corpus;
that trade is deliberate and documented.

**Don't include bot, service-account, or AI-generated commits.** ⏳ The blog excludes all
three. zbench originally caught them only *incidentally* (dependabot trips the dep-file
gate; translation bots produce no code+test pair). We close this with an explicit
author/committer denylist and a co-author/generated-trailer scan in mining — a real filter
rather than a coincidence — and backfill an author check onto existing tasks.

**Don't let task scope sprawl.** ⏳ The blog keeps changes *"confined to a few modules."*
zbench adds a deterministic scope gate (max code files / max added-diff) alongside the
migrations and dependency gates, so "small and isolated" is guaranteed, not left to LLM
judgment.

**Don't skip human review.** This is the blog's one *non-negotiable*: *"We evaluated each
sample by hand"* because scripted/AI-generated task construction contained errors needing
correction. zbench is heavily automated, so this is our sharpest divergence. Our response:
the oracle's mechanical flip is a strong *first* gate, but it is **not** a substitute for
review — a task can flip correctly and still be a bad benchmark item (leaky statement,
under-specified, incidental). So human review (`review_task.py`, which stamps
`meta.review`) is **strongly recommended when a task bank is first built**, to verify that
the pipeline produces good items; after that initial verification it is optional, and the
board ranks on oracle-`validated` tasks (`corpus.py` `ranked_ids` gives the reviewed subset
if you want to publish on reviewed tasks only).

**Don't seal grading but leave generation open, and pretend otherwise.** zbench's grading
containers are `--network none`; generation is not network-isolated (the agents are model
CLIs that need their APIs). We do not claim generation is sealed — we disclose it and lean
on tier-A recency + the fetch audit, with a filesystem/egress sandbox listed as the
honest next step.

## Known limitations we are NOT (yet) fixing, and why

- **No build-graph regression set.** Databricks uses Bazel to run *every* test that depends
  on the touched files. Zulip has no such precise dependency graph, so zbench approximates
  with a bounded pass-to-pass set (test modules of the touched code, capped). This is a
  weaker regression guard; recorded here rather than hidden.
- **Language skew.** The corpus is Python-heavy (Zulip is). We report the py/web split
  rather than enforce a quota; treat web numbers as directional until the web corpus grows.
- **Generation network sandbox.** Egress proxy + filesystem namespace for the generation
  step is future work; until then the network-fetch defense is detection, not prevention.
- **Training cutoffs.** Tier-A ranking needs per-model `training_cutoff` in
  `agents-meta.jsonl`; these are unfilled (`"missing"`) and must be sourced from vendor
  model cards before any ranked board is published. The pipeline fails loud on a missing
  cutoff by design.

## Measure, don't assert, harness efficiency

The blog's headline harness finding (same model, >2× cost, ~3× context/turn) is only
visible if you record per-turn context. zbench should persist `num_turns` and expose a
context-per-turn column (`(input + cache_read) / num_turns`) so the harness axis can be
*measured*, not just declared. Tracked as a follow-up (schema + writer + reader change).
