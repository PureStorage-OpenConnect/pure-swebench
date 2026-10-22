#!/usr/bin/env python3
"""Build-time tests for the 2D capability-vs-cost Pareto frontier (W142).

ranking_view.pareto_frontier((key, cost, capability)) marks the NON-DOMINATED agents:
cost = $/task (lower better), capability = common-set resolve rate (higher better).
B dominates A iff B is <= on cost AND >= on capability AND strictly better on one axis.

Run: python3 zbench/tests/test_pareto.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ranking_view as rv  # noqa: E402


def test_strict_domination():
    # B is more expensive with equal capability -> dominated by A.
    f, dom = rv.pareto_frontier([("A", 1.0, 0.7), ("B", 2.0, 0.7)])
    assert f == {"A"}, f
    assert dom == {"B": ["A"]}, dom


def test_cheaper_and_better_dominates():
    # deepseek-like (cheaper AND more capable) dominates a haiku-like point.
    f, dom = rv.pareto_frontier([("cheap_good", 0.29, 0.62), ("pricey_worse", 0.36, 0.49)])
    assert f == {"cheap_good"}, f
    assert dom["pricey_worse"] == ["cheap_good"], dom


def test_ties_both_on_frontier():
    # Identical points co-dominate -> neither is strictly better -> both stay on the frontier.
    f, dom = rv.pareto_frontier([("A", 1.0, 0.7), ("D", 1.0, 0.7)])
    assert f == {"A", "D"}, f
    assert dom == {}, dom


def test_staircase_frontier():
    # A monotone capability/cost staircase: every point is non-dominated;
    # one interior point that is worse on both axes is dropped.
    pts = [
        ("top", 1.77, 0.739),
        ("mid", 1.60, 0.725),
        ("cheap", 1.07, 0.710),
        ("cheapest", 0.29, 0.623),
        ("dominated", 3.00, 0.500),  # pricier AND less capable than every staircase point
    ]
    f, dom = rv.pareto_frontier(pts)
    assert f == {"top", "mid", "cheap", "cheapest"}, f
    assert "dominated" in dom, dom


def test_empty_and_singleton():
    assert rv.pareto_frontier([]) == (set(), {})
    f, dom = rv.pareto_frontier([("solo", 1.0, 0.5)])
    assert f == {"solo"} and dom == {}, (f, dom)


# --- W145: capability tolerance (practical equivalence) ------------------------------------

def test_tolerance_folds_pricier_near_equal():
    # cheaper agent within tolerance of a pricier one -> pricier is folded (cheaper wins).
    pts = [("cheap", 1.0, 0.70), ("pricey", 2.0, 0.715)]
    f, dom = rv.pareto_frontier(pts, tolerance=0.02)
    assert f == {"cheap"}, f
    assert dom["pricey"] == ["cheap"], dom  # folded into the cheaper equivalent
    # with no tolerance BOTH are on the exact frontier (staircase).
    assert rv.pareto_frontier(pts, tolerance=0.0)[0] == {"cheap", "pricey"}


def test_tolerance_no_chaining_keeps_genuinely_better():
    # The chaining trap: $1/70%, $2/71.5%, $3/73% at eps=2%. Pairwise-eps would collapse to
    # {cheap}; the exact-then-thin method must keep the genuinely-better (>2%) top point.
    pts = [("cheap", 1.0, 0.70), ("mid", 2.0, 0.715), ("top", 3.0, 0.73)]
    f, dom = rv.pareto_frontier(pts, tolerance=0.02)
    assert f == {"cheap", "top"}, f
    assert dom["mid"] == ["cheap"], dom


def test_tolerance_boundary_is_inclusive_gain():
    # a gain of exactly the tolerance is a MEANINGFUL step (kept), not folded.
    pts = [("a", 1.0, 0.70), ("b", 2.0, 0.72)]  # +2.0 pts == tolerance
    f, _ = rv.pareto_frontier(pts, tolerance=0.02)
    assert f == {"a", "b"}, f


def test_tolerance_monotonic_shrinks_frontier():
    # increasing tolerance can only REMOVE points from the exact frontier, never add.
    pts = [("a", 1.0, 0.70), ("b", 2.0, 0.715), ("c", 3.0, 0.73)]
    exact = rv.pareto_frontier(pts, 0.0)[0]
    for tol in (0.01, 0.02, 0.05, 0.5):
        f = rv.pareto_frontier(pts, tol)[0]
        assert f <= exact, (tol, f, exact)


def test_resolve_tolerance_env(monkeypatch=None):
    import os
    # explicit override wins; env is the fallback; default otherwise.
    assert rv.resolve_pareto_tolerance(0.05) == 0.05
    old = os.environ.get("ZBENCH_PARETO_TOLERANCE")
    try:
        os.environ["ZBENCH_PARETO_TOLERANCE"] = "0.03"
        assert rv.resolve_pareto_tolerance() == 0.03
        assert rv.resolve_pareto_tolerance(0.01) == 0.01  # explicit still wins
    finally:
        if old is None:
            os.environ.pop("ZBENCH_PARETO_TOLERANCE", None)
        else:
            os.environ["ZBENCH_PARETO_TOLERANCE"] = old
    assert rv.resolve_pareto_tolerance() == rv.DEFAULT_PARETO_TOLERANCE


def test_partials_participate_when_included(monkeypatch=None):
    # W147: the frontier computation is agnostic to ranked-vs-partial -- it just takes points. So
    # the dashboard's participating view (ranked + partials) is exactly pareto_frontier over the
    # combined set: a cheaper-AND-better partial dominates a ranked agent and lands on the frontier.
    ranked = [("ranked-A", 2.0, 60.0)]
    partial = [("partial-CHEAPGOOD", 0.5, 62.0)]
    # ranked-only: A is the sole (trivially non-dominated) frontier point
    f_ranked, _ = rv.pareto_frontier(ranked, 0.0)
    assert f_ranked == {"ranked-A"}
    # participating (ranked + partial): the partial dominates A
    f_both, dom = rv.pareto_frontier(ranked + partial, 0.0)
    assert "partial-CHEAPGOOD" in f_both, f_both
    assert "ranked-A" in dom and "partial-CHEAPGOOD" in dom["ranked-A"], dom


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn(); print(f"  [PASS] {fn.__name__}")
    print("pareto: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
