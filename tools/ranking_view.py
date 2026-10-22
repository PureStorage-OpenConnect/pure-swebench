#!/usr/bin/env python3
"""Shared D1-D5 ranking transform for the zbench dashboard/readers.

This module intentionally has no HTTP/UI dependencies. `benchdb_reader` builds the
valid execution rows from `bench.db`, then calls `aggregate_and_rank()` here; the
web dashboard only renders the returned state.
"""
from __future__ import annotations

import collections
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root -> zbench package
from zbench.constants import task_of  # noqa: E402  # identity helper (strip instance prefix)

OUTCOME_RANK = {"resolved": 3, "miss": 2, "no_patch": 1}

# W145: practical-equivalence band on the CAPABILITY axis (resolve rate, 0..1 scale;
# 0.02 = 2 percentage points). Two capabilities within this band are treated as EQUAL, so a
# cheaper agent within the band of a pricier one dominates it (cheaper wins when practically
# equivalent). Override at runtime with env ZBENCH_PARETO_TOLERANCE (no code change needed).
DEFAULT_PARETO_TOLERANCE = 0.02


def resolve_pareto_tolerance(override=None):
    """Effective capability tolerance: explicit `override`, else env ZBENCH_PARETO_TOLERANCE,
    else DEFAULT_PARETO_TOLERANCE. Clamped to >= 0."""
    if override is not None:
        try:
            return max(0.0, float(override))
        except (TypeError, ValueError):
            pass
    env = os.environ.get("ZBENCH_PARETO_TOLERANCE")
    if env:
        try:
            return max(0.0, float(env))
        except ValueError:
            pass
    return DEFAULT_PARETO_TOLERANCE


def pareto_frontier(points, tolerance=0.0):
    """2D Pareto frontier for capability-vs-cost (W142) with optional capability tolerance (W145).

    `points` = list of (key, cost, capability) triples: cost is $/task (LOWER is better),
    capability is the common-set resolve rate 0..1 (HIGHER is better). Returns
    (frontier_keys:set, dominated_by:dict[key -> [keys that dominate it]]).

    EXACT domination (tolerance=0): B dominates A iff B.cost <= A.cost AND B.cap >= A.cap AND
    B is STRICTLY better on at least one axis. A point is on the frontier iff no other point
    dominates it. Ties (identical cost AND cap) co-dominate -> both stay on the frontier.

    TOLERANCE (tolerance>0): a practical-equivalence band on capability -- two capabilities
    within `tolerance` are treated as EQUAL, so a CHEAPER agent within the band of a pricier
    one dominates it ("cheaper wins when practically equivalent"). Implemented by computing the
    EXACT frontier, then THINNING it cheapest-first: keep a point only if its capability exceeds
    the last KEPT point's by >= tolerance, else fold it into that cheaper, practically-equivalent
    point (recorded in dominated_by). Thinning the exact frontier -- rather than a pairwise
    epsilon-dominance rule -- deliberately AVOIDS the chaining artifact where a run of
    within-tolerance neighbors would transitively fold away a genuinely-better point (e.g.
    $1/70%, $2/71.5%, $3/73% at eps=2% correctly yields {70%, 73%}, not {70%})."""
    frontier, dominated_by = set(), {}
    for ka, ca, pa in points:
        doms = []
        for kb, cb, pb in points:
            if kb == ka:
                continue
            if cb <= ca and pb >= pa and (cb < ca or pb > pa):
                doms.append(kb)
        if doms:
            dominated_by[ka] = doms
        else:
            frontier.add(ka)
    if tolerance <= 0:
        return frontier, dominated_by
    # Thin the exact frontier by the capability tolerance, cheapest-first. On the exact
    # frontier cost is strictly increasing (equal-cost lower-cap points are already dominated),
    # so this walk is well-defined; -cap in the sort key is only a defensive tiebreak.
    fpts = sorted((p for p in points if p[0] in frontier), key=lambda p: (p[1], -p[2]))
    kept, last_cap = [], None
    for k, _c, cap in fpts:
        if not kept or (cap - last_cap) >= tolerance:
            kept.append(k)
            last_cap = cap
        else:
            # practically equivalent to (and pricier than) the last KEPT, cheaper point
            dominated_by[k] = [kept[-1]]
    return set(kept), dominated_by

def _harness(agent_id):
    """Infer the harness/CLI from an agent_id prefix (pi, claude-code, codex, ...)."""
    a = (agent_id or "").lower()
    if a.startswith("pi-") or a == "pi":
        return "pi"
    if a.startswith("claude"):
        return "claude-code"
    for h in ("codex", "cursor", "gemini", "auggie"):
        if a.startswith(h):
            return h
    return "other"

def _outcome_of(s):
    """resolved | no_patch | miss -- the COARSE DISPLAY trichotomy for the board/matrix.

    DEDUP_REVIEW D8 (investigated 2026-08-02): this is intentionally NOT unified with
    `scoring.classify_attempt` (the canonical, finer failure-mode taxonomy). They
    AGREE on all 682/705 attempts; the only 23 divergences are internal_error / verify-
    timeout rows that scoring calls `artifact:infra` and this calls `miss` -- and ALL
    23 are already scoring-EXCLUDED, so they never reach the leaderboard (board-invariant).
    Delegating would be LOSSY: the 3-way display can't hold `artifact:*`, and collapsing
    infra->no_patch is MORE misleading than the current benign miss on an excluded cell.
    So: keep the coarse display fn here; the canonical classifier stays scoring."""
    if s.get("tests_passed"):
        return "resolved"
    if s.get("status") == "no_patch_generated" or s.get("attempt_outcome") == "candidate_missing":
        return "no_patch"
    return "miss"

def aggregate_and_rank(agg_scores, contam_pairs, corpus_instances=None,
                       infra_limited_pairs=None, pareto_tolerance=None):
    """The ranking core (METHODOLOGY.md), shared by the file reader and
    the SQL (bench.db) reader so both produce identical boards by construction.

    `agg_scores` = the already-VALID execution records (invalid cells dropped by
    the caller's invalidation overlay); each record is one execution. Shape used:
    agent_id, instance_id, tests_passed, status, attempt_outcome, model_name,
    provider, cost_usd, metrics{total_tokens,runtime_ms,total_duration_ms}.
    `contam_pairs` = {(instance_id, agent_id)} contaminated with NO clean re-run
    (kept as invalid placeholder cells so the common set is honest).

    Returns the pieces collect_state() assembles into the state dict."""
    inst_stats = {}    # task_id -> {n, resolved, resolvers} (task 'eval' column)
    per_agent = {}     # agent_id -> {..., inst: {iid: {runs, passes, miss, np, ...}}}
    for s in agg_scores:
        aid = s.get("agent_id")
        iid = s.get("instance_id") or ""
        task_id = task_of(iid)
        o = _outcome_of(s)
        m = s.get("metrics") or {}
        ts_ = inst_stats.setdefault(task_id, {"n": 0, "resolved": 0, "resolvers": []})
        ts_["n"] += 1
        if o == "resolved":
            ts_["resolved"] += 1
            ts_["resolvers"].append(aid)
        a = per_agent.setdefault(aid, {
            "agent_id": aid, "model_name": s.get("model_name"),
            "provider": s.get("provider"), "harness": _harness(aid), "inst": {}})
        ic = a["inst"].setdefault(iid, {"runs": 0, "passes": 0, "miss": 0, "np": 0,
                                        "cost": 0.0, "tok": 0, "gen": 0, "wall": 0, "inv": False,
                                        "in_tok": 0, "out_tok": 0, "cache_tok": 0,
                                        "cache_write_tok": 0, "turns": 0})
        ic["runs"] += 1
        if o == "resolved":
            ic["passes"] += 1
        elif o == "no_patch":
            ic["np"] += 1
        else:
            ic["miss"] += 1
        ic["cost"] += float(s.get("cost_usd") or 0)
        ic["tok"] += int(m.get("total_tokens") or 0)
        ic["in_tok"] += int(m.get("input_tokens") or 0)
        ic["out_tok"] += int(m.get("output_tokens") or 0)
        ic["cache_tok"] += int(m.get("cache_read_tokens") or 0)
        ic["cache_write_tok"] += int(m.get("cache_write_tokens") or 0)
        ic["turns"] += int(m.get("turns") or 0)
        ic["gen"] += int(m.get("runtime_ms") or m.get("total_duration_ms") or 0)
        # TIME PER TASK = wall clock for the whole attempt (generation + verify).
        # "gen" above is generation only and understates a slow/timed-out verify.
        ic["wall"] += int(m.get("total_duration_ms") or m.get("runtime_ms") or 0)

    # A contaminated (instance, agent) with NO surviving clean re-run has no valid
    # cell -> keep the task in that agent's COVERAGE as an invalid placeholder so
    # the task stays in the common set for the HONEST agents (the cheater earns
    # nothing). If a clean re-run exists, the cell above is valid and counts.
    for (iid_, aid_) in contam_pairs:
        a = per_agent.get(aid_)
        if a is not None and iid_ not in a["inst"]:
            a["inst"][iid_] = {"runs": 0, "passes": 0, "miss": 0, "np": 0,
                               "cost": 0.0, "tok": 0, "gen": 0, "wall": 0, "inv": True,
                               "in_tok": 0, "out_tok": 0, "cache_tok": 0,
                               "cache_write_tok": 0, "turns": 0}

    # per-task x per-AGENT outcome matrix (compact task table) + agent axis. We do
    # NOT aggregate by model: one model can be run by several agents (harness x
    # provider x thinking), so a model column would fold distinct configs together
    # and a cell click would show multiple agents. The axis is agent_id (one
    # column per ranked config); clicking a cell drills to that exact agent.
    _orank = OUTCOME_RANK
    inst_agent = {}
    agent_seen, agent_resolved = {}, {}
    for s in agg_scores:
        iid = s.get("instance_id") or ""
        task_id_ = task_of(iid)
        aid = s.get("agent_id") or "(unknown)"
        o = _outcome_of(s)
        cur = inst_agent.setdefault(task_id_, {}).get(aid)
        if cur is None or _orank.get(o, 0) > _orank.get(cur, 0):
            inst_agent[task_id_][aid] = o
        agent_seen.setdefault(aid, set()).add(task_id_)
        if o == "resolved":
            agent_resolved.setdefault(aid, set()).add(task_id_)
    agent_axis = sorted(agent_seen, key=lambda aa: (-len(agent_resolved.get(aa, ())), aa))

    # --- LEADERBOARD (METHODOLOGY.md) -----------------------------
    # Per model x harness (agent_id, D2), on the COMMON task set (D1). ANCHOR the
    # common set on the MAXIMALLY-covered agents (the corpus) so a partial /
    # mid-grid agent can NOT shrink it, then RANK only agents that attempted the
    # ENTIRE common set. (Old rule -- cohort = coverage >= 50% of max, common =
    # intersection over that cohort -- let a mid-grid agent at ~52% BOTH join the
    # cohort AND collapse the common set: e.g. gridding kimi to 12/23 dropped the
    # board from /23 to /12. Decoupling anchor from cohort fixes that.)
    cov = {aid: set(a["inst"]) for aid, a in per_agent.items()}
    # Restrict the common-set universe to the VALIDATED CORPUS when known, so
    # non-corpus attempts (e.g. an exploratory task 417667) can't inflate it and
    # only real corpus tasks anchor the board.
    if corpus_instances is not None:
        universe = set(corpus_instances)
        covU = {aid: (v & universe) for aid, v in cov.items()}
    else:
        covU = cov
    # MATURE-TASK GUARD (symmetric to the mid-grid-AGENT guard above). A task that
    # is validated but only just added -- gridded to a HANDFUL of agents -- must NOT
    # collapse the board: without this, the 2-3 agents that raced ahead on the new
    # task become the max-coverage anchor, the common set jumps to include it, and
    # every other (fully-gridded) agent drops off. (Observed: validating task 474206
    # dropped the board to the 2 agents that had already run it.) Fix: the common-set
    # universe is only the MATURE corpus tasks -- those covered by a supermajority of
    # the SUBSTANTIALLY-covered agents -- so a fresh task is ignored until it is
    # broadly gridded, then rejoins automatically.
    _maxc = max((len(v) for v in covU.values()), default=0)
    # substantially-covered agents (>=50% of max) define task maturity; this drops
    # sparse non-ranked agents (local 1-task, local-qwen 2-task) from skewing it.
    _subst = [v for v in covU.values() if _maxc and len(v) >= 0.5 * _maxc]
    _task_cov = collections.Counter()  # W111: kept for the immature-coverage reason
    _thresh = 0
    if _subst:
        _task_cov = collections.Counter(t for v in _subst for t in v)
        _thresh = math.ceil(0.8 * len(_subst))  # supermajority of substantial agents
        mature = {t for t, c in _task_cov.items() if c >= _thresh}
    else:
        mature = set().union(*covU.values()) if covU else set()
    mature_pre_infra = set(mature)  # W111: snapshot BEFORE the infra-limited drop (membership reasons)
    # INFRA-LIMITED TASK DROP: a task UNSCOREABLE for an agent purely due to
    # infrastructure (all attempts excluded [artifact:infra], zero valid -- e.g.
    # task 462413 perpetual 429 for glm under the TPM cap; or a local self-hosted TIMEOUT)
    # should drop from the common set ONLY when that agent is OTHERWISE-COMPLETE -- i.e.
    # it would cover the ENTIRE common set but for its infra-limited task(s) (glm missing
    # ONLY 462413). Keeping the task would wrongly relegate that otherwise-complete agent
    # to leaderboard_partial. But a MID-GRID PARTIAL agent (many tasks simply unattempted,
    # e.g. the local models still gridding) must NOT shrink the RANKED common set just
    # because it timed out on some tasks -- those tasks stay fair comparison points for the
    # fully-covering cohort, and the partial agent is ranked on its own set regardless.
    # (Using a loose ">=50% coverage" gate here wrongly let a mid-grid agent's infra
    # timeouts collapse n_common; the otherwise-complete test is the correct guard.)
    _infra_drop_reason = {}  # W111: iid -> the agent whose infra-limit dropped it (D1b)
    if infra_limited_pairs:
        _infra_by_aid = collections.defaultdict(set)
        for _iid, _aid in infra_limited_pairs:
            _infra_by_aid[_aid].add(_iid)
        _drop = set()
        for _aid, _iids in _infra_by_aid.items():
            # otherwise-complete: covers all of `mature` except its own infra tasks
            if (mature - _iids).issubset(covU.get(_aid, set())):
                _dropped = _iids & mature
                _drop |= _dropped
                for _di in _dropped:
                    _infra_drop_reason.setdefault(_di, _aid)
        mature = mature - _drop
    covM = {aid: (v & mature) for aid, v in covU.items()}
    max_cov = max((len(v) for v in covM.values()), default=0)
    anchor = [aid for aid, v in covM.items() if len(v) == max_cov]
    common = set.intersection(*(covM[a] for a in anchor)) if anchor else set()
    # ranked cohort = agents covering the WHOLE common set; partial agents (incl.
    # an in-progress grid, local qwen 2/17) are listed separately, not ranked.
    cohort = [aid for aid, v in covM.items() if common and common.issubset(v)]

    # W111: per-task common-set membership, recomputed ON DEMAND (no persisted flag).
    # A task is IN iff it survived the maturity + infra-limited gates AND every anchor
    # agent covered it (== it landed in `common`). For OUT tasks, record a SELF-EXPLAINING
    # reason so the UI can say WHY (immature coverage / D1b infra-limited / anchor gap).
    _univ = (set(universe) if corpus_instances is not None
             else (set().union(*covU.values()) if covU else set()))
    common_membership = {}
    for _iid in _univ:
        _task_id = task_of(_iid)
        if _iid in common:
            common_membership[_task_id] = {"in": True, "kind": "in", "reason": None}
        elif _iid in _infra_drop_reason:
            common_membership[_task_id] = {
                "in": False, "kind": "infra",
                "reason": (f"out of the common set: infra-limited for {_infra_drop_reason[_iid]} "
                           f"[D1b] -- the other agents' results are kept")}
        elif _iid not in mature_pre_infra:
            _c = _task_cov.get(_iid, 0)
            _ns = len(_subst)
            common_membership[_task_id] = {
                "in": False, "kind": "immature",
                "reason": (f"out of the common set: immature coverage -- only {_c}/{_ns} "
                           f"broadly-gridded agents have run it (need {_thresh}); rejoins once gridded"
                           if _ns else "out of the common set: immature coverage")}
        else:
            common_membership[_task_id] = {
                "in": False, "kind": "anchor-gap",
                "reason": "out of the common set: not covered by every anchor agent"}

    def _agent_cost(aid, valid):
        # W137: CANONICAL cost = COMPUTE from captured tokens x the pinned models.dev price for this
        # agent's model, TTL-aware (claude-code 1h cache-write, pi 5m). Uniform for ALL agents ->
        # re-priceable (swap the pinned snapshot to re-cost) and apples-to-apples. The harness-reported
        # cost (attempt.cost_usd: Anthropic real bill / pi's own calc) is kept as a CROSS-CHECK
        # (_agent_cost_reported), not the canonical number. Fall back to harness-reported only when the
        # model has no list price (unknown to the table).
        try:
            import model_prices
            c = model_prices.cost_usd(aid,
                                      sum(x["in_tok"] for x in valid),
                                      sum(x["out_tok"] for x in valid),
                                      sum(x["cache_tok"] for x in valid),
                                      sum(x.get("cache_write_tok", 0) for x in valid))
            if c is not None:
                return c
        except Exception:
            pass
        return sum(c["cost"] for c in valid)

    def _agent_cost_known(aid, valid):
        """True iff the cost is REAL rather than an unpriced model collapsing to 0.

        Without this a self-hosted open-weight agent (no list price, no harness-reported
        cost) is indistinguishable from a genuinely free one, and it would silently win
        any cost-ranked comparison."""
        try:
            import model_prices
            if model_prices.cost_usd(aid, 1, 1, 0, 0) is not None:
                return True
        except Exception:
            pass
        return sum(c["cost"] for c in valid) > 0

    def _agent_cost_reported(valid):
        # harness-reported cost (cross-check vs the computed canonical); 0 for Foundry/local.
        return sum(c["cost"] for c in valid)

    def _agent_row(aid, task_set):
        a = per_agent[aid]
        cells = [a["inst"][i] for i in task_set if i in a["inst"]]
        valid = [c for c in cells if c["runs"] > 0]          # >=1 valid execution
        inv = sum(1 for c in cells if c["runs"] == 0)        # contaminated, no clean re-run
        # per-cell PASS RATE (passes/runs); sum over the common set = "expected
        # resolves" (integer today, fractional once cells have multiple runs).
        resolved = sum(c["passes"] / c["runs"] for c in valid)
        miss = sum(1 for c in valid if c["passes"] == 0 and c["miss"] > 0)
        nopatch = sum(1 for c in valid if c["passes"] == 0 and c["miss"] == 0)
        n = len(valid)  # denominator excludes discarded (contaminated-no-rerun) cells
        row = {
            "agent_id": aid, "model_name": a["model_name"], "provider": a["provider"],
            "harness": a["harness"], "resolved": resolved, "n": n,
            "resolve_rate": (resolved / n) if n else 0.0, "miss": miss, "no_patch": nopatch,
            "invalid": inv,
            "cost_usd": _agent_cost(aid, valid), "cost_reported": _agent_cost_reported(valid),
            "cost_known": _agent_cost_known(aid, valid),
            "total_tokens": sum(c["tok"] for c in valid),
            "io_tokens": sum(c["in_tok"] + c["out_tok"] for c in valid),
            "in_tokens": sum(c["in_tok"] for c in valid),
            # output tokens are the provider's completion count, which BILLS reasoning/
            # thinking tokens as output -- so this already encompasses reasoning tokens.
            "out_tokens": sum(c["out_tok"] for c in valid),
            "cache_tokens": sum(c["cache_tok"] for c in valid),
            "cache_write_tokens": sum(c.get("cache_write_tok", 0) for c in valid),
            "gen_ms": sum(c["gen"] for c in valid),
            "wall_ms": sum(c["wall"] for c in valid), "coverage": len(a["inst"]),
            # agentic TURNS (model round-trips) the harness took, summed over the common set;
            # avg turns/task = turns / n_turns. Display-only effort metric, NOT ranked. Per
            # harness's own definition (claude num_turns / pi assistant-msgs / codex turns),
            # so compare WITHIN a harness, not across.
            "turns": sum(c.get("turns", 0) for c in valid),
            # W95: count of cells that actually HAVE a token / gen record -- the average
            # per-task denominators EXCLUDE unrecoverable (missing/0) records rather than
            # counting them as 0 (which would drag the average down).
            "n_tok": sum(1 for c in valid if (c["in_tok"] + c["out_tok"]) > 0),
            "n_gen": sum(1 for c in valid if c["gen"] > 0),
            "n_wall": sum(1 for c in valid if c["wall"] > 0),
            "n_turns": sum(1 for c in valid if c.get("turns", 0) > 0),
        }
        return row

    # RANK ORDER (standing decision, project owner 2026-08-17): resolve RATE desc, then
    # cost-per-task asc. Cost is now part of the rank, not just display order within a
    # tie -- a cheaper agent at the same pass rate ranks higher. Rate (not the raw
    # resolve count) is the primary key so partial-coverage cohorts stay comparable.
    #
    # Self-hosted open-weight models are priced at a public host's per-token reference
    # (model_prices, project owner 2026-08-18) -- apples-to-apples with a cloud API bill -- so
    # they no longer win cost ties by a $0 construction. A local model still reads as
    # free* (cost_known=False, $/task 0 for ordering) ONLY when no public reference price
    # exists for it yet (its open_weight_hosted.json entry is 'needs_price').
    def _cost_per_task(r):
        return (r["cost_usd"] / r["n"]) if r["n"] else 0.0

    leaderboard = sorted((_agent_row(aid, common) for aid in cohort),
                         key=lambda r: (-(r["resolve_rate"] or 0.0), _cost_per_task(r),
                                        r["agent_id"]))
    # Ties share a rank only when BOTH keys match (same rate AND same $/task); the
    # next rank then skips, keeping standard competition numbering.
    prev, rk = None, 0
    for i, r in enumerate(leaderboard, 1):
        key = (round(r["resolve_rate"] or 0.0, 12), round(_cost_per_task(r), 12))
        if key != prev:
            rk, prev = i, key
        r["rank"] = rk
        r["cost_per_task"] = _cost_per_task(r)
    _rank_counts = collections.Counter(r["rank"] for r in leaderboard)
    for r in leaderboard:
        r["rank_shared"] = _rank_counts[r["rank"]] > 1
    # W142/W145: 2D capability-vs-cost Pareto frontier. Axes = canonical uniform computed $/task
    # (cost_usd/n, W137 -- apples-to-apples across harnesses) vs common-set resolve rate, with a
    # practical-equivalence tolerance on capability (W145). Annotate each ranked row so the
    # readout + dashboard render it without recomputing.
    _tol = resolve_pareto_tolerance(pareto_tolerance)
    _pf_pts = [(r["agent_id"], (r["cost_usd"] / r["n"]) if r["n"] else 0.0,
               r.get("resolve_rate") or 0.0) for r in leaderboard]
    _exact_frontier, _ = pareto_frontier(_pf_pts, tolerance=0.0)
    _frontier, _dom_by = pareto_frontier(_pf_pts, tolerance=_tol)
    for r in leaderboard:
        aid = r["agent_id"]
        r["on_frontier"] = aid in _frontier
        r["dominated_by"] = _dom_by.get(aid, [])
        # on the EXACT frontier but folded by the tolerance = practically equivalent to a
        # cheaper frontier agent (distinct from strictly dominated).
        r["eps_equivalent"] = (aid in _exact_frontier) and (aid not in _frontier)
    # Partial agents are ranked on their OWN set -- but that set must be the CORPUS-restricted
    # coverage (covU), NOT raw `cov[aid]`: raw coverage includes stray non-corpus attempts (e.g. an
    # exploratory task 417667) that would inflate `n` and produce the nonsensical "attempted 51 tasks
    # (fewer than the 48-task common set)" message. Also annotate WHY each is partial = which common-set
    # tasks it is missing (that is the real reason, not a smaller attempt count).
    def _partial_row(aid):
        own = covU.get(aid, cov.get(aid, set()))
        r = _agent_row(aid, own)
        _covered = common & covU.get(aid, set())
        r["common_covered"] = len(_covered)
        r["common_total"] = len(common)
        r["missing_common"] = sorted(task_of(i) for i in (common - _covered))
        return r
    leaderboard_partial = sorted(
        (_partial_row(aid) for aid in per_agent if aid not in cohort),
        key=lambda r: (-r["resolved"], r["cost_usd"]))

    return {
        "per_agent": per_agent, "inst_stats": inst_stats, "inst_agent": inst_agent,
        "agent_axis": agent_axis, "leaderboard": leaderboard,
        "leaderboard_partial": leaderboard_partial, "n_common": len(common),
        "common_membership": common_membership,  # W111: per-task in/out + reason
        "pareto_tolerance": _tol,  # W145: capability equivalence band actually applied
    }
