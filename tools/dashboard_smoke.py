#!/usr/bin/env python3
"""Dashboard regression smoke checks.

Runs without a browser: imports bench_dashboard, renders representative pages, and
checks invariants that have regressed before. Task fixtures are resolved at runtime
from the corpus (the first two validated task ids) -- no hardcoded task ids.
Optionally also checks a live server with --base-url http://127.0.0.1:8787.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "zbench-tasks"))

import bench_dashboard as bd  # noqa: E402
import corpus  # noqa: E402


def fixture_task_ids() -> list[str]:
    """Runtime fixtures: the first two validated task ids from the corpus."""
    return [r["task_id"] for r in corpus.load_corpus("validated")][:2]


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def fetch(base: str, path: str) -> str:
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=10) as r:
        data = r.read()
    return data.decode("utf-8", errors="replace")


def direct_checks(t1: str, t2: str) -> list[str]:
    out: list[str] = []
    st = bd.dashboard_state()
    runs_payload = bd._runs_payload(st)
    pages = {
        "leaderboard": bd.render_html(st),
        "coverage": bd.render_coverage_page(),
        "runs": bd.render_runs_page(),
        "corpus": bd.render_corpus_page(),
        "agents": bd.render_agents_page(),
        "metrics": bd.render_metrics_page(),
        "download": bd.render_backup_page(),
        "task1": bd.render_task_page(t1),
        "task2": bd.render_task_page(t2),
    }
    agent = ((st.get("leaderboard") or st.get("leaderboard_partial") or [{}])[0]).get("agent_id")
    if agent:
        pages["agent"] = bd.render_agent_detail(agent)
    for name, html in pages.items():
        check(html.startswith("<!doctype html>"), f"{name}: not html")
        check("Traceback" not in html, f"{name}: traceback rendered")
        check("__RUNS_TABLE_JS__" not in html, f"{name}: unreplaced runs JS placeholder")
    check("statusFilters" in pages["corpus"] and "status=validated" in pages["corpus"],
          "corpus: missing curation-status filter controls")
    corpus_payload = bd._corpus_payload(st)
    statuses = {r.get("curation_status") for r in corpus_payload.get("tasks", [])}
    # every present status must be from the known vocabulary (a young corpus may only
    # have `validated` yet -- the batch adds held/invalid/dropped over time).
    check(statuses and statuses.issubset({"validated", "held", "invalid", "dropped"}),
          f"api/corpus: unexpected curation status(es) {statuses}")
    check("problem statement / initial prompt" in pages["task1"], "task: missing problem link")
    check("Task artifacts" in pages["task1"], "task: missing artifact card")
    check("gold test patch (oracle/spoiler)" in pages["task1"], "task: missing gold-test spoiler link")
    check(f"window.RUNS_OPTS={{\"task\": \"{t2}\"" in pages["task2"],
          "task: attempts table does not use shared runs renderer")
    check("tr.rowex td{text-decoration:line-through;color:var(--muted2)}" in pages["task2"],
          "task: detail pages lack rowex CSS")
    rows_t2 = [r for r in runs_payload.get("rows", []) if r.get("task") == t2]
    if rows_t2:
        rr = rows_t2[0]
        pages["run"] = bd.render_run_page(rr.get("run_id"), rr.get("agent"), rr.get("instance"))
        check(pages["run"].startswith("<!doctype html>"), "run: not html")
        check("Traceback" not in pages["run"], "run: traceback rendered")
    else:
        out.append(f"[skip] no attempt rows for {t2}; run-page smoke not exercised")
    if not any((r.get("status_obj") or {}).get("rank_effect") == "excluded"
               for r in runs_payload.get("rows", [])):
        out.append("[skip] no excluded rows in api/runs; exclusion rendering not exercised")
    out.append(f"direct render ok ({len(pages)} pages; {t2} rows={len(rows_t2)})")
    return out


def live_checks(base: str, t1: str, t2: str) -> list[str]:
    out: list[str] = []
    paths = ["/", "/runs", "/corpus", "/corpus?status=all", "/corpus?status=dropped", "/agents", "/download",
             f"/task?task={t1}", f"/task?task={t2}",
             f"/task_file?task={t1}&name=problem_statement.md"]
    for path in paths:
        body = fetch(base, path)
        check("Traceback" not in body, f"{path}: traceback")
        check("not found" not in body.lower() or path.endswith("problem_statement.md") is False,
              f"{path}: unexpected not found")
    task = fetch(base, f"/task?task={t2}")
    check(f"window.RUNS_OPTS={{\"task\": \"{t2}\"" in task, "live task: not using shared runs renderer")
    check("tr.rowex td{text-decoration:line-through;color:var(--muted2)}" in task, "live task: no rowex CSS")
    ps = fetch(base, f"/task_file?task={t1}&name=problem_statement.md")
    check(bool(ps.strip()) and "Traceback" not in ps, "live task_file: empty/broken problem statement")
    out.append(f"live ok ({base})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", help="also smoke a running dashboard, e.g. http://127.0.0.1:8787")
    args = ap.parse_args()
    fixtures = fixture_task_ids()
    if not fixtures:
        print("[skip] empty corpus -- smoke not exercised")
        return 0
    t1, t2 = (fixtures * 2)[:2]
    messages = direct_checks(t1, t2)
    if args.base_url:
        messages.extend(live_checks(args.base_url, t1, t2))
    for msg in messages:
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
