# zbench results export (snapshot 2026-10-20)

Produced by Everpure, Inc. (formerly Pure Storage) from the zbench result stores. zbench is a
SWE-bench-style harness: each task is a real fix from the open-source Zulip repository, shown to the
agent as a problem statement; a hidden regression test decides the outcome. An agent patch is
**resolved** only if the hidden test fails on the base commit and passes after the patch.

## Files
- `LEADERBOARD.md` / `leaderboard.csv` - the headline table: model name, harness, tasks resolved / attempted, rate. Start here.
- `per_model_summary.csv` - one row per active, ranked agent plus one supplementary row. Columns:
  `source_store` (`primary` or `supplementary`), model/family/harness/open_weight, `board_rank`,
  tasks scored and resolved over all validated tasks the agent has a valid attempt on, the
  common-set score (`common_set_attempted`, `common_set_resolved`, `common_set_resolve_rate`),
  computed cost and token totals, turns/task and wall-clock minutes/task.
- `per_task_results.csv` - long format, one row per (task, agent) with a valid attempt.
  `resolved` is the per-task pass rate over valid attempts (0 or 1 in practice). `attempts_valid`
  counts attempts that survive scoring exclusions; `attempts_total` also counts attempts excluded as
  infrastructure artifacts or superseded briefs (and re-run). `board_outcome` is resolved / no_patch /
  miss. `in_common_set` is 1 if the task is in the primary store's common task set. Per-task cost is
  the harness-reported figure (`cost_reported_usd`); the summary uses the canonical computed price.
- `sample_transcripts/` - sanitized attempt bundles, named `harness_model_outcome`: resolved and
  unresolved examples for a Claude Code agent, a Codex agent and a Pi agent on a self-hosted
  open-weight model (all primary store), plus one supplementary-store example. Each has
  `transcript.jsonl` (agent event stream), `patch.diff`, `pb-verify.log`, `agent_io.json`,
  `provenance.json`. Long tool outputs are cut at 3,000 characters and very long streams keep the
  first 80 and last 20 events (marked). Paths, hostnames, emails, IPs and credentials were scrubbed.

## Two stores
- **Primary**: the multi-agent result store. All ranked agents here share one common task set
  (`common_set_size` column) and are scored on it. Ranking is by common-set resolve rate (desc), then
  computed cost per task (asc).
- **Supplementary**: `claude-cli-glm-5.3-flash-litellm` was run separately, on a different provider
  endpoint, in its own store. It is NOT part of the ranked agent matrix. Its common set differs
  slightly from the primary one (same size, but three tasks on each side differ because task maturity
  and infra-limited drops are computed per store). Its `common_set_*` columns are computed against the
  primary common set (so `common_set_attempted` can be below `common_set_size`); its cost/token/turn
  columns come from its own store's common set. Do not rank it against the primary agents without
  that caveat. Its `open_weight` flag is from the public model card (MIT-licensed weights); the exact
  served build behind the endpoint alias is unverified.

## How numbers are computed (code, relative to the zbench repo)
- Valid attempts: every attempt without a `run_exclusion` row (`zbench-tasks/exclusions.py`,
  `tools/benchdb_reader.py`).
- Tasks: `curation_status == validated` (`zbench-tasks/corpus.py`).
- Common set, ranking and Pareto frontier: `tools/ranking_view.py::aggregate_and_rank`
  (METHODOLOGY.md section 6).
- Cost: tokens x public list price (`tools/model_prices.py`), a uniform computed figure, not a vendor
  bill. For self-hosted open-weight models it is a public-host reference price, so it is not the
  actual cost of running them. `cost_is_list_priced=False` means no reference price exists yet and the
  cost shows as 0.
- Turns: harness-defined; compare only within a harness.
- Control agents (gold patch, empty patch, etc.), retired agents and replay runs are excluded.

## Caveats
- Customer reruns will differ from these numbers because of model sampling randomness, serving
  hardware and provider differences, rate limits and timeouts, and environment image builds.
- Small N: a 1-2 task difference is not a decisive gap. Contamination tiers (possible overlap with
  public Zulip history in training data) are advisory and are not applied here.
