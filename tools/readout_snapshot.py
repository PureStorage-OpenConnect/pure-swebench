#!/usr/bin/env python3
"""Emit the current readout results snapshot as Markdown.

This is the single cheap way to regenerate the result block to hand-paste into PROJECT_REPORT.md
(the point-in-time stakeholder report -- there is no live-refresh contract):

  python3 tools/readout_snapshot.py > /tmp/current-results.md

The output is intentionally a snapshot: paste it with the generated_at timestamp and git
hash rather than hand-maintaining board numbers in prose.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "zbench-tasks"))

import benchdb_reader  # noqa: E402
import corpus  # noqa: E402


def _git_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _money(x: float | int | None) -> str:
    if x is None:
        return "n/a"
    x = float(x)
    if x >= 0.10:
        return f"${x:.2f}"
    if x >= 0.01:
        return f"${x:.3f}"
    if x >= 0.001:
        return f"${x:.4f}"
    return f"${x:.5f}"


def _mins(ms: float | int | None) -> str:
    if not ms:
        return "n/a"
    return f"{float(ms) / 60000:.1f}m"


def main() -> int:
    st = benchdb_reader.collect_state()
    # NB: bind to a NEW name -- `corpus = corpus.load_corpus(...)` shadowed the imported
    # module and raised UnboundLocalError, so this whole readout was dead.
    corpus_rows = corpus.load_corpus("validated")
    n_py = sum(1 for r in corpus_rows if r.get("lang") == "py")
    n_web = len(corpus_rows) - n_py
    out_tasks = [t for t in st.get("tasks", [])
                 if t.get("curation_status") == "validated"
                 and not (t.get("common_set") or {}).get("in", False)]

    print(f"Generated: `{st.get('generated_at')}`")
    print(f"Source: `bench-db/bench.db` + `zbench-tasks/tasks/*/meta.json`; git `{_git_hash()}`")
    print(f"Corpus: **{len(corpus_rows)} validated tasks** ({n_py} py / {n_web} web)")
    print(f"Ranked cohort: **{len(st.get('leaderboard', []))} agents**")
    print(f"Common set: **{st.get('n_common')} tasks**")
    if out_tasks:
        bits = []
        for t in sorted(out_tasks, key=lambda x: x.get("task_id", "")):
            cs = t.get("common_set") or {}
            reason = cs.get("reason") or cs.get("kind") or "out"
            bits.append(f"`{t.get('task_id')}` ({reason})")
        print("Common-set exclusions: " + "; ".join(bits))
    else:
        print("Common-set exclusions: none")
    print()
    # The four required metrics: pass rate, $/task, total tokens/task, time/task.
    # "total tok" is the CANONICAL billed total (in+out+cache_read+cache_write) and
    # "time/task" is wall clock (generation + verify), NOT generation alone.
    print("| Rank | PF | Agent | Resolved | Rate | list $/task | total tok/task | i/o tok/task | cache tok/task | turns/task | time/task |")
    print("|---:|:--:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in st.get("leaderboard", []):
        n = r.get("n") or 0
        ntok = r.get("n_tok") or n or 1
        ngen = r.get("n_gen") or n or 1
        nwall = r.get("n_wall") or n or 1
        nturns = r.get("n_turns") or 0
        turns_c = f"{(r.get('turns') or 0) / nturns:.0f}" if nturns else "—"
        resolved = r.get("resolved") or 0
        resolved_s = f"{resolved:.0f}" if abs(resolved - round(resolved)) < 1e-9 else f"{resolved:.1f}"
        rank = f"{r.get('rank')}{'=' if r.get('rank_shared') else ''}"
        pf = "*" if r.get("on_frontier") else ("~" if r.get("eps_equivalent") else "")
        print("| {rank} | {pf} | `{agent}` | {resolved}/{n} | {rate:.1f}% | {cost} | {tot:,.0f} | {io:,.0f} | {cache:,.0f} | {turns} | {gen} |".format(
            rank=rank,
            pf=pf,
            agent=r.get("agent_id"),
            resolved=resolved_s,
            n=n,
            rate=100 * (r.get("resolve_rate") or 0),
            turns=turns_c,
            # cost_known=False => an open-weight model with no PUBLIC REFERENCE price yet
            # (its open_weight_hosted.json entry is 'needs_price'). Render "free*", never a
            # bare $0: the asterisk marks "no reference price found yet", not "no cost".
            cost=(_money((r.get("cost_usd") or 0) / n) if (n and r.get("cost_known", True))
                  else "free\\*"),
            tot=(r.get("total_tokens") or 0) / ntok,
            io=(r.get("io_tokens") or 0) / ntok,
            cache=(r.get("cache_tokens") or 0) / ntok,
            gen=_mins((r.get("wall_ms") or 0) / nwall if nwall else None),
        ))
    lb = st.get("leaderboard", [])
    frontier = [r.get("agent_id") for r in lb if r.get("on_frontier")]
    equiv = [r.get("agent_id") for r in lb if r.get("eps_equivalent")]
    tol = st.get("pareto_tolerance") or 0.0
    print()
    print("Rank order: pass rate (desc), then cost per task (asc).")
    if any(not r.get("cost_known", True) for r in lb):
        print("\\* `free` = an open-weight model with NO public host reference price yet, so it "
              "has no per-token $/task. Open-weight models that DO have a public reference "
              "(prices/models_dev.json or prices/open_weight_hosted.json) show a real $/task "
              "priced at what a host would charge for those weights -- apples-to-apples with a "
              "cloud API bill (see METHODOLOGY). tools/price_search.py re-checks daily; read "
              "`free*` as \"no reference price found yet\", not \"no cost\".")
    print()
    print("PF = Pareto frontier on capability (resolve rate) vs cost (canonical computed "
          f"$/task). Capabilities within {tol * 100:.0f} percentage points are treated as "
          "practically EQUAL, so the cheaper agent wins. `*` = on the frontier; `~` = "
          "practically equivalent to a cheaper frontier agent (folded); blank = dominated.")
    if frontier:
        print("Frontier agents: " + ", ".join(f"`{a}`" for a in frontier))
    if equiv:
        print("Practically equivalent (folded into a cheaper agent): "
              + ", ".join(f"`{a}`" for a in equiv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
