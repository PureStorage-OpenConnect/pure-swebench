"""zbench agent client: spawn an adapter subprocess (JSON in/out), dict-based (W19).

The parent side of the adapter protocol: build the augmented prompt + repo tree, spawn the
adapter (`agent['command']`) with the AgentSpec env, feed it the input JSON on stdin, read
its emitted output JSON (patches + token_usage). Returns the plain output MAP (not a
class). Ports the fork's client.invoke_agent minus the run-tracking JSONL events (bucket C
-- lifecycle events are recorded by run_cell/workflow via store.record_event).
"""
from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import time
from pathlib import Path

from ..io_logging import log_agent_io

logger = logging.getLogger("zbench.agents.client")

_TREE_EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".cache", ".tox",
                      ".pytest_cache", ".mypy_cache", ".ruff_cache", "var",
                      "zulip-py3-venv", ".venv", "static/generated", "staticfiles"}


def get_repo_tree(repo_root: Path, depth: int = 3, max_chars: int = 4000) -> str:
    """A directory tree of the repo for agent spatial context (empty string on failure)."""
    try:
        exclude = []
        for d in _TREE_EXCLUDE_DIRS:
            exclude += ["-not", "-path", f"./{d}*"]
        r = subprocess.run(["find", ".", "-maxdepth", str(depth), "-type", "d", *exclude],
                           capture_output=True, text=True, timeout=15, cwd=str(repo_root))
        tree = r.stdout.strip()
        return tree[:max_chars] + "\n... (truncated)" if len(tree) > max_chars else tree
    except Exception as e:
        logger.warning("Failed to generate repo tree: %s", e)
        return ""


def augment_problem_with_repo_context(problem_statement: str, repo_root: Path, repo_tree: str) -> str:
    if not repo_tree:
        return problem_statement
    return (f"REPOSITORY CONTEXT:\nThe repository is located at: {repo_root}\n"
            f"Before making any changes, explore the relevant source files to fully "
            f"understand the codebase structure and the problem.\n\n"
            f"Directory structure:\n{repo_tree}\n\n---\n\n") + problem_statement


def invoke_agent(agent: dict, instance: dict, repo_root: Path, *,
                 run_id: str | None = None, evaluation_id: str | None = None) -> dict | None:
    """Spawn the adapter for `agent` on `instance` in `repo_root`; return its output map
    {instance_id, agent_id, patches:[...], token_usage:{...}} or None on failure."""
    md = instance.get("metadata") or {}
    languages = instance.get("languages") or md.get("languages") or ["py"]
    repo_tree = get_repo_tree(repo_root)
    augmented = augment_problem_with_repo_context(instance["problem_statement"], repo_root, repo_tree)
    logger.info("Augmented problem (%d chars tree, %d total)", len(repo_tree), len(augmented))

    agent_input = {
        "instance_id": instance["instance_id"],
        "repo_root": str(repo_root.absolute()),
        "problem_statement": augmented,
        "languages": languages,
        "context": md.get("context"),
    }

    env = os.environ.copy()
    env.update(agent.get("env") or {})
    # the adapter runs as `python3 -m zbench.agents.*`; guarantee the zbench package
    # root is importable in the child regardless of how run_cell itself was launched
    # (cwd-on-sys.path does NOT propagate via env to a subprocess).
    _pkg_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = _pkg_root + os.pathsep + env.get("PYTHONPATH", "")
    if run_id:
        env["ZBENCH_RUN_ID"] = run_id
    if evaluation_id:
        env["ZBENCH_EVALUATION_ID"] = evaluation_id
    # The PARENT allocates the ABSOLUTE evidence/session path and hands it to the child.
    # New W116 layout: run_cell sets ZBENCH_CELL_DIR and stable child paths under it.
    # Fallback: direct/adhoc invocation without run_cell gets the grandfathered io_logs name.
    _cell_dir = env.get("ZBENCH_CELL_DIR")
    if _cell_dir:
        env.setdefault("ZBENCH_SESSION_PATH", str((Path(_cell_dir) / "session.jsonl").resolve()))
        env.setdefault("ZBENCH_RAWCLI_PATH", str((Path(_cell_dir) / "rawcli.txt").resolve()))
    else:
        from datetime import datetime, timezone
        from ..paths import io_logs_dir, safe
        _bucket = run_id or os.environ.get("ZBENCH_RUN_ID") or "adhoc"
        _stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        _sess = (io_logs_dir(_bucket) /
                 f"pi__{safe(instance['instance_id'])}__{safe(evaluation_id or 'noeval')}__session__{_stamp}.jsonl")
        env["ZBENCH_SESSION_PATH"] = str(_sess.resolve())
    cwd = agent.get("working_dir") or str(repo_root)
    timeout = agent.get("timeout_sec") or 900

    logger.info("Invoking agent %s for %s", agent["agent_id"], instance["instance_id"])
    try:
        _t0 = time.perf_counter()
        result = subprocess.run(shlex.split(agent["command"]), input=json.dumps(agent_input),
                                text=True, capture_output=True, timeout=timeout, cwd=cwd, env=env)
        gen_ms = int((time.perf_counter() - _t0) * 1000)
    except subprocess.TimeoutExpired:
        logger.error("Agent %s timed out after %ss", agent["agent_id"], timeout)
        return None
    except Exception as e:
        logger.error("Unexpected error invoking %s: %s", agent["agent_id"], e)
        return None

    log_agent_io(agent=agent, instance=instance, agent_input=agent_input,
                 returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                 run_id=run_id, evaluation_id=evaluation_id,
                 task_type=md.get("task_type", "development/patches"), generation_ms=gen_ms)

    if result.returncode != 0:
        logger.error("Agent %s failed (rc=%s)\nstderr: %s",
                     agent["agent_id"], result.returncode, result.stderr[:1000])
        return None
    if result.stderr:
        logger.info("Agent %s stderr: %s", agent["agent_id"], result.stderr[:1000])
    try:
        out = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse agent output JSON: %s\nstdout: %s", e, result.stdout[:500])
        return None
    n = len(out.get("patches") or [])
    logger.info("Agent %s produced %d patch(es)", agent["agent_id"], n)
    if n == 0:
        logger.warning("Agent %s produced 0 patches (see stderr above)", agent["agent_id"])
    # attach the measured generation wall-clock for the score metrics
    out.setdefault("_generation_ms", gen_ms)
    return out


def get_patches(agent: dict, instance: dict, repo_root: Path) -> list[dict]:
    out = invoke_agent(agent, instance, repo_root)
    return (out or {}).get("patches", []) if out else []
