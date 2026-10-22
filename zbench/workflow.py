"""zbench test-blind patch evaluation -- the verify/score core (ported, dicts).

One attempt: history-isolated per-cell checkout -> run the agent (test-blind) -> apply its
patch -> strip any agent test edits + apply the hidden gold_test -> verify via the task's
commands (containerized test-backend / test-js-with-node) -> classify -> record the
attempt fact + evidence via store. AgentConfig/Instance/ScoreRecord are dicts now; the small deps
(apply_patch / worktree_lock / status map) are folded in; try_number is gone; cost is the
provider-reported value (else NULL -> computed at read time). bench.db is the only store.
"""
from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import constants, store
from .agents.client import invoke_agent
from .cells import slots

logger = logging.getLogger("zbench.workflow")


def _phase_slot(pool: str | None, *, timeout: float = 21600.0):
    """Phase-scoped slot (W132 phase-aware slotting): hold `pool` only for THIS phase.
    generation -> provider slot (rate-limit gate); build/verify -> heavy slot (local-CPU
    gate). None -> no gating (e.g. light Go build). Waits for the slot (does not fail-fast)."""
    return slots.acquire([pool], wait=True, timeout=timeout) if pool else contextlib.nullcontext()

WORK_BRANCH = "zbench-work"

# ---- folded-in small deps -------------------------------------------------------
@contextlib.contextmanager
def worktree_lock(base_repo: Path, timeout: int = 300):
    """Exclusive lock on git worktree metadata ops (parallel cells share the base repo)."""
    lock_dir = base_repo / ".git"
    if not lock_dir.is_dir():
        try:
            common = subprocess.run(["git", "-C", str(base_repo), "rev-parse", "--git-common-dir"],
                                    capture_output=True, text=True).stdout.strip()
            lock_dir = (Path(common) if Path(common).is_absolute() else base_repo / common) if common else base_repo
        except Exception:
            lock_dir = base_repo
    lock_file = lock_dir / "worktree_creation.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    f = None
    try:
        f = open(lock_file, "w")
        start = time.time()
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except OSError as exc:
                if time.time() - start > timeout:
                    raise TimeoutError(f"worktree lock not acquired in {timeout}s") from exc
                time.sleep(0.1)
        yield
    finally:
        if f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            f.close()


def apply_patch(patch_text: str, repo_dir: Path, reverse: bool = False) -> tuple[bool, str, str]:
    """Apply a unified diff to a git checkout via `git apply`."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as h:
        h.write(patch_text); pf = Path(h.name)
    try:
        cmd = ["git", "apply", "--verbose", "--binary"] + (["--reverse"] if reverse else []) + [str(pf)]
        r = subprocess.run(cmd, cwd=str(repo_dir), capture_output=True, text=True)
        return r.returncode == 0, r.stdout, r.stderr
    finally:
        pf.unlink(missing_ok=True)


_STATUS_TO_OUTCOME = {
    "ok": "completed", "patch_apply_failed": "candidate_application_failed",
    "tests_failed": "verification_tests_failed", "timeout": "verification_timeout",
    "internal_error": "internal_error", "worktree_error": "workspace_preparation_failed",
    "no_patch_generated": "candidate_missing", "repo_setup_failed": "workspace_preparation_failed",
    # provider_error = the MODEL ENDPOINT refused/dropped the request (429, throttled
    # stream, 5xx, auth). The cell produced no capability signal, so it is an infra
    # artifact and a re-run candidate -- never a "the agent could not solve it" miss.
    "provider_error": "internal_error",
}


def map_status_to_attempt_outcome(status: str) -> str:
    return _STATUS_TO_OUTCOME.get(status, "internal_error")


# ---- failure classification (pure string analysis) ------------------------------
# "The agent's patch doesn't even load" signals: Python import/syntax, TS compile, node
# module resolution. A plain test failure (FAILED (failures=1), AssertionError) must
# match NEITHER list -- it is a real miss, not an artifact.
_BUILD_ERR_SIGS = ("syntaxerror", "indentationerror", "taberror", "modulenotfounderror",
                   "cannot import name", "importerror", "error ts", "cannot find module",
                   "failed to compile", "webpack compilation")
_SETUP_INFRA_SIGS = ("no space left on device", "out of diskspace", "index.lock",
                     "could not resolve host", "temporary failure in name resolution",
                     "connection timed out", "isolated fetch failed", "worktree add failed",
                     "cannot connect to the docker daemon", "error response from daemon",
                     "pull access denied", "no such image", "oci runtime error",
                     "psql: error", "missing env image", "provision failed")


_NO_TESTS_SIGS = ("ran 0 tests", "no tests ran", "no tests found",
                  "collected 0 items", "found 0 test")


def _ran_zero_tests(t: str) -> bool:
    return any(s in (t or "").lower() for s in _NO_TESTS_SIGS)


def _looks_like_build_error(t: str) -> bool:
    return any(s in (t or "").lower() for s in _BUILD_ERR_SIGS)


def _looks_like_setup_infra(t: str) -> bool:
    return any(s in (t or "").lower() for s in _SETUP_INFRA_SIGS)


def _gold_test_target_paths(gold_text: str) -> list[str]:
    paths = set()
    for ln in gold_text.splitlines():
        if ln.startswith("+++ b/"):
            paths.add(ln[len("+++ b/"):].strip())
        elif ln.startswith("diff --git a/") and " b/" in ln:
            paths.add(ln.split(" b/", 1)[1].strip())
    paths.discard("/dev/null")
    return sorted(paths)


def _first_line(text: str, sigs) -> str:
    for ln in (text or "").splitlines():
        if any(s in ln.lower() for s in sigs):
            return ln.strip()[:200]
    s = (text or "").strip()
    return s.splitlines()[-1][:200] if s else ""


# ---- isolated checkout ----------------------------------------------------------
def _worktree_root(base_repo_dir: Path) -> Path:
    configured = os.environ.get("ZBENCH_WORKTREE_DIR")
    root = Path(configured).expanduser() if configured else base_repo_dir.parent / "zbench_worktrees"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _set_checkout_identity(wt: Path) -> None:
    for k, v in (("user.email", "zbench@zbench.local"), ("user.name", "zbench"),
                 ("advice.detachedHead", "false"), ("commit.gpgsign", "false")):
        subprocess.run(["git", "-C", str(wt), "config", k, v], capture_output=True, text=True)


def _make_isolated_checkout(base_repo_dir: Path, base_commit: str, tag: str) -> Path:
    """History-isolated per-cell checkout: a standalone depth-1 single-commit repo with
    ONLY base_commit (no descendants/review refs/origin) so the gold fix is unreachable
    from git history (finding #23)."""
    wt = _worktree_root(base_repo_dir) / f"zbench_wt_{tag}"
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    wt.mkdir(parents=True)
    tmp_ref = f"refs/zbenchiso/{tag}-{uuid.uuid4().hex[:8]}"
    src = f"file://{base_repo_dir}"
    try:
        subprocess.run(["git", "init", "-q", str(wt)], check=True, capture_output=True, text=True)
        with worktree_lock(base_repo_dir):
            subprocess.run(["git", "-C", str(base_repo_dir), "update-ref", tmp_ref, base_commit],
                           check=True, capture_output=True, text=True)
        try:
            fe = subprocess.run(["git", "-C", str(wt), "fetch", "-q", "--depth", "1", "--no-tags",
                                 src, f"{tmp_ref}:refs/isobase"], capture_output=True, text=True)
        finally:
            with worktree_lock(base_repo_dir):
                subprocess.run(["git", "-C", str(base_repo_dir), "update-ref", "-d", tmp_ref],
                               capture_output=True, text=True)
        if fe.returncode != 0:
            raise RuntimeError(f"isolated fetch failed at {base_commit}: {fe.stderr[:300]}")
        co = subprocess.run(["git", "-C", str(wt), "checkout", "-q", "-b", WORK_BRANCH, "refs/isobase"],
                            capture_output=True, text=True)
        if co.returncode != 0:
            raise RuntimeError(f"isolated checkout failed at {base_commit}: {co.stderr[:300]}")
        _set_checkout_identity(wt)
        subprocess.run(["git", "-C", str(wt), "update-ref", "-d", "refs/isobase"], capture_output=True, text=True)
    except Exception:
        shutil.rmtree(wt, ignore_errors=True)
        raise
    return wt


def _make_worktree(base_repo_dir: Path, base_commit: str, tag: str) -> Path:
    """History-isolated depth-1 checkout by default; ZBENCH_ISOLATED_CHECKOUT=0 -> legacy shared
    git worktree (fast but leaks history)."""
    if os.environ.get("ZBENCH_ISOLATED_CHECKOUT", "1").lower() not in ("0", "false", "no"):
        return _make_isolated_checkout(base_repo_dir, base_commit, tag)
    wt = _worktree_root(base_repo_dir) / f"zbench_wt_{tag}"
    wt_branch = f"zbench-work/{tag}"
    with worktree_lock(base_repo_dir):
        subprocess.run(["git", "-C", str(base_repo_dir), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(base_repo_dir), "worktree", "prune"], capture_output=True, text=True)
        subprocess.run(["git", "-C", str(base_repo_dir), "branch", "-D", wt_branch], capture_output=True, text=True)
        res = subprocess.run(["git", "-C", str(base_repo_dir), "worktree", "add", "-q", "-B", wt_branch,
                              str(wt), base_commit], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"worktree add failed at {base_commit}: {res.stderr[:300]}")
    _set_checkout_identity(wt)
    return wt


def _remove_worktree(base_repo_dir: Path, wt: Path) -> None:
    if (wt / ".git").is_dir():                      # isolated: standalone repo
        shutil.rmtree(wt, ignore_errors=True)
        return
    tag = wt.name[len("zbench_wt_"):] if wt.name.startswith("zbench_wt_") else wt.name
    with worktree_lock(base_repo_dir):
        subprocess.run(["git", "-C", str(base_repo_dir), "worktree", "remove", "--force", str(wt)],
                       capture_output=True, text=True)
        subprocess.run(["git", "-C", str(base_repo_dir), "worktree", "prune"], capture_output=True, text=True)
        subprocess.run(["git", "-C", str(base_repo_dir), "branch", "-D", f"zbench-work/{tag}"],
                       capture_output=True, text=True)


def _resolve_gold_patch(gold_ref: str | None, metadata: dict) -> str:
    if not gold_ref:
        raise RuntimeError("instance metadata missing gold_test_patch")
    if gold_ref.lstrip().startswith(("diff --git", "--- ")):
        return gold_ref
    for c in [Path(gold_ref)] + ([Path(metadata["gold_test_patch_dir"]) / gold_ref]
                                 if metadata.get("gold_test_patch_dir") else []):
        c = c.expanduser()
        if c.is_file():
            return c.read_text(encoding="utf-8")
    raise RuntimeError(f"gold_test_patch not found: {gold_ref}")


# Zulip-shaped protected pathspecs: tests, test infrastructure, and the runners the
# grading commands execute FROM THE WORKTREE. An agent edit to any of these that
# survived to verify time would be an exit-0 backdoor, so all are reverted to base.
_TEST_PATHSPECS = [
    ":(glob)**/tests/**",         # zerver/tests/, corporate/tests/, web/tests/, ...
    ":(glob)**/tests.py",         # zerver/webhooks/<name>/tests.py
    ":(glob)**/test_*.py",        # test modules + zerver/lib/test_{classes,helpers,...}.py
    ":(glob)**/conftest.py",
    ":(glob)**/*.test.*",         # web *.test.{ts,js,cjs,mjs}
    ":(glob)web/e2e-tests/**",
    ":(glob)tools/test-*",        # the runners themselves (tools/test-backend, ...)
    ":(glob)tools/ci/**",
    ":(glob)tools/lib/**",
]

# Paths whose integrity is asserted (hash-compared to base) right before verify runs --
# belt and suspenders over the checkout-revert above. Any diff or untracked file here
# means the strip failed; grading must abort as internal_error, never resolve.
_RUNNER_INTEGRITY_PATHS = ["tools/test-backend", "tools/test-js-with-node",
                           "tools/ci", "tools/lib"]


def _strip_agent_test_edits(wt: Path, base_commit: str, gold_text: str) -> list[str]:
    """Test-blind hygiene: revert ANY agent edits to test files before applying gold_test
    (agents must not influence/collide-with/add tests). Preserves agent SOURCE edits."""
    notes = []
    for spec in _TEST_PATHSPECS:
        subprocess.run(["git", "-C", str(wt), "checkout", base_commit, "--", spec], capture_output=True, text=True)
        subprocess.run(["git", "-C", str(wt), "clean", "-fdq", "--", spec], capture_output=True, text=True)
    notes.append(f"reset test/runner files ({len(_TEST_PATHSPECS)} pathspecs) -> base")
    for p in _gold_test_target_paths(gold_text):
        rc = subprocess.run(["git", "-C", str(wt), "checkout", base_commit, "--", p],
                            capture_output=True, text=True).returncode
        fp = wt / p
        if rc != 0 and fp.exists():
            try:
                fp.unlink(); notes.append(f"removed agent-created {p}")
            except OSError:
                pass
    return notes


def _runner_integrity_violations(wt: Path, base_commit: str) -> list[str]:
    """Paths in _RUNNER_INTEGRITY_PATHS that differ from base (modified OR untracked).
    Empty list = runners are pristine."""
    bad: set[str] = set()
    diff = subprocess.run(["git", "-C", str(wt), "diff", "--name-only", base_commit,
                           "--", *_RUNNER_INTEGRITY_PATHS], capture_output=True, text=True)
    bad.update(ln.strip() for ln in diff.stdout.splitlines() if ln.strip())
    untracked = subprocess.run(["git", "-C", str(wt), "ls-files", "--others", "--exclude-standard",
                                "--", *_RUNNER_INTEGRITY_PATHS], capture_output=True, text=True)
    bad.update(ln.strip() for ln in untracked.stdout.splitlines() if ln.strip())
    return sorted(bad)


# ---- score + record -------------------------------------------------------------
def _score(instance: dict, agent: dict, ctx: dict, *, passed: bool, status: str, error=None,
           agent_output: dict | None = None, generation_ms=None, verify_ms=None,
           verify_log_text=None) -> dict:
    """Build the score MAP + write the attempt fact + evidence via store. Returns the map."""
    md = instance.get("metadata") or {}
    tu = (agent_output or {}).get("token_usage") or {}
    total_ms = ((generation_ms or 0) + (verify_ms or 0)) or None
    score = {
        "run_id": ctx.get("run_id"), "evaluation_id": ctx.get("evaluation_id"),
        "instance_id": instance["instance_id"], "agent_id": agent["agent_id"],
        "tests_passed": bool(passed), "status": status,
        "attempt_outcome": "completed" if status == "ok" else map_status_to_attempt_outcome(status),
        "cost_usd": tu.get("cost_usd"),           # provider-reported; else NULL -> computed at read
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error_message": error, "task_type": md.get("task_type", "zbench/patch"),
        "metrics": {
            "runtime_ms": generation_ms, "total_duration_ms": total_ms,
            "input_tokens": tu.get("input_tokens"), "output_tokens": tu.get("output_tokens"),
            "total_tokens": tu.get("total_tokens"), "cache_read_tokens": tu.get("cache_read_tokens"),
            "cache_write_tokens": tu.get("cache_write_tokens"),
            "turns": tu.get("turns"),   # agentic model round-trips (display metric)
        },
    }
    patch_text = None
    if agent_output and agent_output.get("patches"):
        patch_text = "\n".join(p.get("patch_text") for p in agent_output["patches"]
                               if (p.get("patch_text") or "").strip())
    evidence: dict = {}
    if verify_log_text is not None:
        evidence["verify_log_text"] = verify_log_text
    if patch_text:
        evidence["patch_text"] = patch_text
    # W116: new cells stage all durable agent evidence in one parent-owned cell dir
    # (agent_io.json/session.jsonl/rawcli.txt), then the store copies the dir into the
    # attempt bundle. Legacy io_logs fallback is kept for adhoc/old direct callers.
    if os.environ.get("ZBENCH_CELL_DIR"):
        evidence["cell_dir"] = os.environ["ZBENCH_CELL_DIR"]
    else:
        from .paths import io_logs_dir
        bucket = ctx.get("run_id") or os.environ.get("ZBENCH_RUN_ID") or "adhoc"
        evidence["io_logs_cell"] = (str(io_logs_dir(bucket)), agent["agent_id"], instance["instance_id"])
    store.record_attempt(score, evaluation_id=ctx.get("evaluation_id"), evidence=evidence,
                         provenance_data=ctx.get("provenance"))
    return score


def run_patch_task_attempt(agent: dict, instance: dict, ctx: dict, base_repo_dir) -> dict:
    """Test-blind patch evaluation for one attempt. Returns the score map."""
    md = instance.get("metadata") or {}
    commands = md.get("commands", {})
    build_cmds = commands.get("build", []) or []
    test_cmds = commands.get("tests", []) or []
    base_commit = instance["commit"]
    verify_timeout = int(md.get("verify_timeout_sec", 2400))
    sp = ctx.get("set_phase") or (lambda *_: None)   # advance the lease phase for observability

    if base_repo_dir is None:
        return _score(instance, agent, ctx, passed=False, status="repo_setup_failed",
                      error="no base_repo_dir provided")
    base_repo_dir = Path(base_repo_dir)
    tag = f"{instance['instance_id']}_{agent['agent_id']}"     # no try (W109)

    try:
        # Worktree setup (git checkout of a large repo, sometimes dep clones) is a LOCAL-CPU
        # phase for both langs, so it takes the `heavy` slot (W132: setup + verify are local;
        # generation is remote). Released before generation.
        sp("worktree-setup")
        with _phase_slot("setup"):
            wt = _make_worktree(base_repo_dir, base_commit, tag)
    except Exception as exc:
        logger.error("worktree setup failed: %s", exc)
        return _score(instance, agent, ctx, passed=False, status="worktree_error", error=str(exc))

    try:
        gen_start = time.perf_counter()
        sp("waiting-gen")
        with _phase_slot(ctx.get("gen_pool")):          # GENERATION: provider slot only (not heavy)
            sp("generating")
            out = invoke_agent(agent, instance, wt, run_id=ctx.get("run_id"), evaluation_id=ctx.get("evaluation_id"))
        generation_ms = int((time.perf_counter() - gen_start) * 1000)
        _task = constants.task_of(instance["instance_id"])
        patches = (out or {}).get("patches") or []
        patch_chars = sum(len(p.get("patch_text") or p.get("patch") or "") for p in patches)
        if out is None or not patches:
            # An adapter may report WHY it produced nothing. A provider failure (endpoint
            # threw 429/5xx/auth) is an infra artifact, not a capability miss, so it gets
            # its own status; anything else stays the ordinary "the agent gave up".
            failure = (out or {}).get("failure") or {}
            provider_failed = failure.get("kind") == "provider_error"
            _msg = failure.get("message") or "agent produced no patch"
            store.record_event(ctx.get("run_id"), agent["agent_id"], _task, "patch_missing",
                               message=("provider failure: " + _msg) if provider_failed
                                       else "agent produced no patch",
                               data={"patch_count": 0, "patch_chars": 0, **({"failure": failure} if failure else {})})
            return _score(instance, agent, ctx, passed=False,
                          status="provider_error" if provider_failed else "no_patch_generated",
                          error=_msg, agent_output=out, generation_ms=generation_ms)

        store.record_event(ctx.get("run_id"), agent["agent_id"], _task, "patch_extracted",
                           message=f"{len(patches)} patch(es), {patch_chars} chars",
                           data={"patch_count": len(patches), "patch_chars": patch_chars})
        for p in patches:
            if not (p.get("patch_text") or "").strip():
                continue
            ok, _o, err = apply_patch(p["patch_text"], wt)
            if not ok:
                return _score(instance, agent, ctx, passed=False, status="patch_apply_failed",
                              error=f"agent patch apply failed: {err[:300]}",
                              agent_output=out, generation_ms=generation_ms)

        try:
            gold_text = _resolve_gold_patch(md.get("gold_test_patch"), md)
        except Exception as exc:
            return _score(instance, agent, ctx, passed=False, status="internal_error",
                          error=f"gold_test resolve: {exc}", agent_output=out, generation_ms=generation_ms)
        strip_notes = _strip_agent_test_edits(wt, base_commit, gold_text)
        ok, _o, err = apply_patch(gold_text, wt)
        if not ok:
            return _score(instance, agent, ctx, passed=False, status="internal_error",
                          error=f"gold_test apply failed (agent may have touched tests): {err[:300]}",
                          agent_output=out, generation_ms=generation_ms)
        tampered = _runner_integrity_violations(wt, base_commit)
        if tampered:
            return _score(instance, agent, ctx, passed=False, status="internal_error",
                          error=f"runner integrity violated after strip (never resolve): {tampered[:5]}",
                          agent_output=out, generation_ms=generation_ms)

        # Record an observable phase marker: the containerized verify is minutes-long
        # and SILENT (writes nothing to the agent session), so without this event a
        # watcher can't tell 'verifying' from 'dead'. attempt_event = the timeline.
        store.record_event(ctx.get("run_id"), agent["agent_id"], _task, "verify_started",
                           message=f"verify: {len(build_cmds + test_cmds)} cmd(s) (may take minutes)",
                           data={"commands": build_cmds + test_cmds})
        logger.info("zbench verify phase: %d command(s) (may take several minutes; silent)",
                    len(build_cmds + test_cmds))
        # Verify commands reference the corpus scripts dir portably via $ZBENCH_SCRIPTS
        # (never absolute authoring-machine paths -- the old corpus's landmine).
        verify_env = {**os.environ,
                      "ZBENCH_SCRIPTS": os.environ.get("ZBENCH_SCRIPTS")
                      or str(Path(__file__).resolve().parents[1] / "zbench-tasks" / "scripts"),
                      "ZBENCH_WORKTREE": str(wt)}
        v_start = time.perf_counter()
        vlog_parts, resolved, fail_output, timed_out = [], True, "", False
        sp("waiting-verify")
        with _phase_slot(ctx.get("build_pool")):        # VERIFY: local-CPU/container slot
            sp("verifying")
            for cmd in (build_cmds + test_cmds):
                logger.info("zbench verify: %s", cmd)
                try:
                    r = subprocess.run(cmd, cwd=str(wt), shell=True, capture_output=True,
                                       text=True, timeout=verify_timeout, env=verify_env)
                except subprocess.TimeoutExpired:
                    vlog_parts.append(f"$ {cmd}\n[TIMEOUT after {verify_timeout}s]")
                    resolved, timed_out = False, True
                    break
                vlog_parts.append(f"$ {cmd}\n(rc={r.returncode})\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")
                if r.returncode != 0:
                    resolved = False
                    fail_output = (r.stdout or "") + "\n" + (r.stderr or "")
                    break
        verify_ms = int((time.perf_counter() - v_start) * 1000)
        header = []
        if out.get("patches"):
            header.append("AGENT PATCH:\n" + "\n".join(p.get("patch_text", "") for p in out["patches"]))
        if strip_notes:
            header.append("STRIPPED AGENT TEST EDITS:\n" + "\n".join(strip_notes))
        full_verify_log = "\n\n".join(header + vlog_parts)

        # Grade-time NOTRUN guard: a rc==0 verify that ran ZERO tests must never score as
        # a pass (a target that silently collected nothing looks green by exit code alone).
        # Mode-agnostic -- keys on the runner's own "ran 0 tests" output.
        if resolved and _ran_zero_tests(full_verify_log):
            resolved = False
            status, error = "tests_failed", "[notrun] verify ran zero tests (target collected nothing)"
        elif resolved:
            status, error = "ok", None
        elif timed_out:
            status, error = "timeout", f"verify timed out after {verify_timeout}s"
        else:
            # NOTE: the Go-era "unrelated failing package" promotion was deliberately
            # retired with the whole-tree pb verifies: zbench commands target specific
            # test classes/files, so every failure is related by construction and a
            # non-zero exit is never promoted to a pass.
            full_verify = "\n".join(vlog_parts)
            if _looks_like_setup_infra(full_verify) or _looks_like_setup_infra(fail_output):
                status, error = "repo_setup_failed", f"[infra:setup] {_first_line(fail_output or full_verify, _SETUP_INFRA_SIGS)}"
            elif _looks_like_build_error(fail_output):
                status, error = "tests_failed", f"[build_failed] {_first_line(fail_output, _BUILD_ERR_SIGS)}"
            else:
                status, error = "tests_failed", "[tests_failed] FAIL_TO_PASS did not pass"
        score = _score(instance, agent, ctx, passed=resolved, status=status, error=error,
                       agent_output=out, generation_ms=generation_ms, verify_ms=verify_ms,
                       verify_log_text=full_verify_log)
        logger.info("zbench %s / %s -> %s%s", instance["instance_id"], agent["agent_id"],
                    "RESOLVED" if resolved else "unresolved", "" if resolved else f" ({error})")
        return score
    finally:
        _remove_worktree(base_repo_dir, wt)
