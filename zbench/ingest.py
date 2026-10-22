"""zbench ingest -- the STRICT edge validators (W19 data-oriented decision).

Two entry points where external maps become trusted maps:
  * load_agent(m)  <- one `agents-*.jsonl` line   -> AgentSpec
  * load_task(m)   <- one `tasks/<task_id>/meta.json` -> TaskSpec

Strict at the edge: required keys must be present + right-typed, unknown keys are
REJECTED (a typo shouldn't pass silently), values are coerced where unambiguous. Between
the edges everything is a plain map -- no classes, no framework. Returns are the same
dicts (TypedDict-shaped); we validate, we don't wrap.

The persistence edge (bench.db writes) is validated separately by schema.sql (NOT
NULL / CHECK / FK) -- that is the OTHER edge; this file is ingest only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .types import AgentSpec, InstanceSpec, TaskSpec


class IngestError(ValueError):
    """A map failed edge validation (missing/typo'd/mistyped key)."""


def _check(m: Any, *, what: str, required: dict[str, type], optional: dict[str, type]) -> dict:
    """Strict field check: `m` is a dict; every required key present + typed; every
    present key is known (required|optional) + typed. Returns `m` unchanged on success."""
    if not isinstance(m, dict):
        raise IngestError(f"{what}: expected an object, got {type(m).__name__}")
    known = {**required, **optional}
    unknown = set(m) - set(known)
    if unknown:
        raise IngestError(f"{what}: unknown key(s) {sorted(unknown)} (known: {sorted(known)})")
    for k in required:
        if m.get(k) is None:
            raise IngestError(f"{what}: missing required key '{k}'")
    for k, v in m.items():
        if v is not None and not isinstance(v, known[k]):
            want = known[k]
            wname = want.__name__ if isinstance(want, type) else "|".join(t.__name__ for t in want)
            raise IngestError(f"{what}: key '{k}' must be {wname}, got {type(v).__name__}")
    return m


def load_agent(m: dict) -> AgentSpec:
    """Validate one agents-*.jsonl map -> AgentSpec (dict)."""
    _check(m, what="agent",
           required={"agent_id": str, "command": str},
           optional={"timeout_sec": int, "env": dict, "working_dir": str, "metadata": dict})
    return m  # already the AgentSpec shape


def load_agents(path: str | Path) -> list[AgentSpec]:
    """Read + validate an agents-*.jsonl file (one AgentSpec per non-blank line)."""
    out: list[AgentSpec] = []
    for i, line in enumerate(Path(path).read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(load_agent(json.loads(line)))
        except (json.JSONDecodeError, IngestError) as e:
            raise IngestError(f"{path}:{i}: {e}") from e
    return out


def load_instance(m: dict) -> InstanceSpec:
    """Validate one tasks/<task_id>/instance.jsonl map -> InstanceSpec (the RUN input)."""
    _check(m, what="instance",
           required={"instance_id": str, "repo": str, "commit": str, "problem_statement": str},
           optional={"languages": list, "metadata": dict})
    return m


def load_instance_file(path: str | Path) -> InstanceSpec:
    """Read + validate a single-line instance.jsonl -> InstanceSpec."""
    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip()]
    if len(lines) != 1:
        raise IngestError(f"{path}: expected 1 instance line, got {len(lines)}")
    try:
        return load_instance(json.loads(lines[0]))
    except (json.JSONDecodeError, IngestError) as e:
        raise IngestError(f"{path}: {e}") from e


def load_task(m: dict) -> TaskSpec:
    """Validate one tasks/<task_id>/meta.json map -> TaskSpec (dict).

    Required = the universal identity/base keys {task_id, base_commit, lang}. The TEST TARGET
    (fail_to_pass_testfuncs | fail_to_pass | test_file) is OPTIONAL here on purpose: it's a
    RUNNABILITY precondition the run path asserts (via test_target()), not a file-shape
    invariant -- 16/68 task files legitimately lack fail_to_pass_testfuncs (older format)."""
    _check(m, what="task",
           required={"task_id": str, "base_commit": str, "lang": str},
           optional={"fix_commit": str, "component": str, "type": str, "summary": str,
                     "testing_trailer": str, "curation_status": str, "resolved": str,
                     "review": dict, "test_file": str,
                     # per-task verify cap override (workflow.py; default 2400s).
                     "verify_timeout_sec": int,
                     "fail_to_pass_testfuncs": list, "fail_to_pass": (str, list),
                     "pass_to_pass": list,
                     # zulip task provenance: issue number + env-image identity +
                     # contamination-tier record (see METHODOLOGY contamination model).
                     "issue": int, "env_fingerprint": str, "env_image_digest": str,
                     "contamination": dict, "flake_check": dict,
                     # quality gates (Databricks best practices): complexity tag,
                     # author provenance, bot/service/AI-author flag.
                     "complexity": dict, "author_flagged": str,
                     # verifiability-first curation (METHODOLOGY section 2, 2026-08-14):
                     # public names the brief hands the solver + statement provenance.
                     "interface_requirements": list, "statement_inputs": dict,
                     # candidate-record metadata; advisory for corpus pages,
                     # ignored by the run path but part of the meta.json schema.
                     "verdict": str, "reason": str, "reason_code": str, "curation_stage": str,
                     "source": dict, "evidence": list,
                     # task author provenance: {name,email,date,source}; advisory.
                     "author": dict,
                     # curation correction record: {date,by,reason}; advisory.
                     "rebrief": dict})
    ftp = m.get("fail_to_pass_testfuncs")
    if ftp is not None and not all(isinstance(t, str) for t in ftp):
        raise IngestError(f"task {m.get('task_id')}: fail_to_pass_testfuncs must be a list of str")
    return m


def test_target(task: TaskSpec) -> list[str]:
    """Resolve the verify target from whichever field a task carries (run-path precondition,
    not an ingest gate). Prefers fail_to_pass_testfuncs, then fail_to_pass (str|list)."""
    ftp = task.get("fail_to_pass_testfuncs")
    if ftp:
        return list(ftp)
    fp = task.get("fail_to_pass")
    if isinstance(fp, str):
        return [fp]
    if isinstance(fp, list):
        return list(fp)
    raise IngestError(f"task {task.get('task_id')}: no test target "
                      f"(fail_to_pass_testfuncs / fail_to_pass) -- not runnable")


def load_task_file(path: str | Path) -> TaskSpec:
    """Read + validate a meta.json file -> TaskSpec."""
    try:
        return load_task(json.loads(Path(path).read_text()))
    except (json.JSONDecodeError, IngestError) as e:
        raise IngestError(f"{path}: {e}") from e
