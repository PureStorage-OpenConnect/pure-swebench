#!/usr/bin/env python3
"""GEPA rollout runner: run the zbench benchmark for ONE pi agent with an extra appended
system prompt on a list of tasks; return per-task results plus a compact reflection trace.

    from rollout_runner import run_rollouts           # gepa/ on sys.path (see NOTE below)
    results = run_rollouts("pi-anthropic-haiku-4-5", "Locate code with grep first.",
                           ["ZT-856dcb1e6053"], run_label="gen3")

NOTE: do NOT add an __init__.py / import this as `gepa.rollout_runner`: the directory name
collides with the PyPI `gepa` package. Put this directory on sys.path (or run the file).

How it works:
  * candidate agent_id = "<base>--g<sha8(prompt)>" ("<base>--seed" for an empty prompt).
    Its env is a byte-for-byte copy of the base row in zbench-tasks/agents-matrix.jsonl plus
    PI_APPEND_SYSTEM_PROMPT (pi_agent.py turns that into `--append-system-prompt`).
  * the (candidate, task) cell is cached by the harness's own identity key
    (config_id=agent_id, task_id) in the PRIVATE store gepa/store/bench.db.
  * cells are launched with zbench-tasks/run_coverage_matrix.py --fill (the supported path);
    we then read the attempt rows + evidence blobs from the private store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # pure-swebench checkout
GEPA_DIR = ROOT / "gepa"
STORE = GEPA_DIR / "store"                               # private bench.db + blobs + runtime
DB_PATH = STORE / "bench.db"
MATRIX = ROOT / "zbench-tasks" / "agents-matrix.jsonl"
AGENTS_DIR = STORE / "agents"                            # one private agents jsonl per candidate
PROMPTS_DIR = STORE / "prompts"                          # prompt text per candidate (reference)
LOGS_DIR = STORE / "driver_logs"
TASKS_DIR = ROOT / "zbench-tasks" / "tasks"
OPENAI_KEY_FILE = Path(os.environ.get(
    "GEPA_OPENAI_KEY_FILE", "/mnt/data/robert-scripts/purebench/bench-db/.runtime/openai.key"))

BASE_AGENTS = ("pi-vllm-qwen3.6-27b", "pi-vllm-gemma-4-31b", "pi-vllm-muse-glimmer-30b",
               "pi-anthropic-haiku-4-5", "pi-openai-gpt-5.6-luna", "pi-anthropic-haiku-5-5",
               "pi-vllm-gpt-oss-120b", "pi-openai-gpt-5.6-sol")


# --------------------------------------------------------------------------- environment
def _setup_environment() -> None:
    """Point every harness path at the private store. Idempotent.

    run_coverage_matrix.py HARD-CODES the runtime dirs of its cells to
    <repo>/bench-db/.runtime (ZBENCH_DATA_DIR / ZBENCH_SLOTS_DIR) and ignores our env, so we
    make <repo>/bench-db a symlink to gepa/store: then bench.db, blobs/, .runtime/{slots,
    cells,live,runs} all live under gepa/store, and the repo never touches purebench."""
    STORE.mkdir(parents=True, exist_ok=True)
    link = ROOT / "bench-db"
    if link.is_symlink():
        if link.resolve() != STORE.resolve():
            raise RuntimeError(f"{link} is a symlink to {link.resolve()}, expected {STORE}")
    elif link.exists():
        raise RuntimeError(f"{link} exists and is not a symlink to {STORE}; refusing to mix stores")
    else:
        try:
            link.symlink_to(STORE.resolve())
        except FileExistsError:          # another concurrent caller won the race
            pass
    os.environ["ZBENCH_BENCHDB_DIR"] = str(STORE)                 # store.py: bench.db + blobs + leases
    os.environ["ZBENCH_DATA_DIR"] = str(STORE / ".runtime")        # same value run_coverage_matrix forces
    os.environ["ZBENCH_SLOTS_DIR"] = str(STORE / ".runtime" / "slots")
    os.environ.setdefault("ZBENCH_WORKTREE_DIR", str(STORE / "worktrees"))
    os.environ.setdefault("ZBENCH_TARGET_REPO", str(Path("~/work/zulip").expanduser()))
    for d in (AGENTS_DIR, PROMPTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # NEVER let a stray env var send writes to the operational store
    assert "purebench" not in os.environ["ZBENCH_BENCHDB_DIR"]


def _ensure_credentials(base_row: dict) -> None:
    prov = (base_row.get("env") or {}).get("PI_PROVIDER", "")
    if prov == "openai-direct" and not os.environ.get("OPENAI_API_KEY"):
        if not OPENAI_KEY_FILE.is_file():
            raise RuntimeError(f"OPENAI_API_KEY unset and {OPENAI_KEY_FILE} missing")
        os.environ["OPENAI_API_KEY"] = OPENAI_KEY_FILE.read_text().strip()
    # anthropic: pi's own OAuth (~/.pi/agent/auth.json) or ANTHROPIC_API_KEY; nothing to do.


# --------------------------------------------------------------------------- candidates
def prompt_hash(prompt: str) -> str:
    return hashlib.sha256((prompt or "").strip().encode("utf-8")).hexdigest()[:8]


def candidate_id(base_agent_id: str, append_prompt: str, sample: int = 1) -> str:
    """sample k > 1 is an independent repeat of the same (prompt, task) cell: its own agent_id
    (suffix -s<k>), so the per-cell cache keeps one attempt per sample."""
    p = (append_prompt or "").strip()
    aid = f"{base_agent_id}--seed" if not p else f"{base_agent_id}--g{prompt_hash(p)}"
    return aid if sample == 1 else f"{aid}-s{sample}"


def _load_base_row(base_agent_id: str) -> dict:
    for line in MATRIX.read_text().splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if row["agent_id"] == base_agent_id:
                return row
    raise KeyError(f"{base_agent_id} not in {MATRIX}")


def ensure_candidate_agent(base_agent_id: str, append_prompt: str, sample: int = 1) -> tuple[str, Path, dict]:
    """Write the private one-row agents jsonl for this candidate. Returns (agent_id, path, row)."""
    base = _load_base_row(base_agent_id)
    p = (append_prompt or "").strip()
    aid = candidate_id(base_agent_id, p, sample)
    row = json.loads(json.dumps(base))            # deep copy: env copied exactly
    row["agent_id"] = aid
    row.setdefault("env", {})
    row["env"].pop("PI_APPEND_SYSTEM_PROMPT", None)
    if p:
        row["env"]["PI_APPEND_SYSTEM_PROMPT"] = p
    path = AGENTS_DIR / f"{aid}.jsonl"
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(row) + "\n")
    tmp.replace(path)
    (PROMPTS_DIR / f"{aid}.txt").write_text(p + "\n")
    return aid, path, row


# --------------------------------------------------------------------------- DB access
def _connect_ro() -> sqlite3.Connection | None:
    if not DB_PATH.exists():
        return None
    c = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _latest_attempts(agent_id: str, task_ids: list[str]) -> dict[str, dict]:
    """Latest NON-excluded attempt per task (the same exclusion semantics --fill uses)."""
    c = _connect_ro()
    if c is None:
        return {}
    try:
        has_rx = c.execute("SELECT 1 FROM sqlite_master WHERE name='run_exclusion'").fetchone()
        q = ("SELECT a.* FROM attempt a WHERE a.config_id=?" +
             (" AND NOT EXISTS (SELECT 1 FROM run_exclusion rx WHERE rx.evaluation_id=a.evaluation_id)"
              if has_rx else "") + " ORDER BY a.finished_at ASC")
        out = {}
        for r in c.execute(q, (agent_id,)):
            if r["task_id"] in task_ids:
                out[r["task_id"]] = dict(r)       # ascending -> last wins
        return out
    finally:
        c.close()


def is_valid_attempt(r: dict) -> bool:
    """A cached cell is reusable iff it carries a CAPABILITY signal (not an infra artifact).

    valid:   ok, tests_failed, patch_apply_failed, timeout (verify), and no_patch_generated
             when the model really worked (output tokens, or ran >= 5 min).
    invalid: provider_error, internal_error, worktree_error, repo_setup_failed, and a
             no_patch_generated that burned no tokens in < 5 min (dead auth / endpoint)."""
    st = r.get("status")
    if st in ("ok", "tests_failed", "patch_apply_failed", "timeout"):
        return True
    if st == "no_patch_generated":
        return (bool(r.get("output_tokens")) or (r.get("runtime_ms") or 0) >= 300_000
                or _session_output_tokens(r.get("evaluation_id")) > 0)
    return False


def _session_output_tokens(evaluation_id) -> int:
    """Output tokens summed from the pi session file. A no-patch row carries no token columns
    (the adapter records usage only with a patch), e.g. Haiku 5.5 spending its whole
    max_tokens on thinking and making no edit: a real model failure, not an infra artifact."""
    p = STORE / "blobs" / "attempt" / str(evaluation_id) / "session.jsonl"
    if not evaluation_id or not p.is_file():
        return 0
    n = 0
    for line in p.open(errors="replace"):
        try:
            n += ((json.loads(line).get("message") or {}).get("usage") or {}).get("output") or 0
        except (json.JSONDecodeError, AttributeError):
            pass
    return n


def _exclude_attempt(evaluation_id: str, reason: str) -> None:
    """Mark an infra-artifact attempt excluded in the PRIVATE db so --fill re-plans the cell."""
    c = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        c.execute("PRAGMA busy_timeout=60000")
        c.execute("INSERT OR IGNORE INTO run_exclusion(evaluation_id, reason, decided_by) VALUES(?,?,?)",
                  (evaluation_id, "[artifact:infra] gepa-runner: " + reason, "gepa-runner"))
        c.commit()
    finally:
        c.close()


def _cell_in_flight(agent_id: str, task_id: str) -> bool:
    """True iff another live process holds the per-cell flock (any caller, any driver)."""
    sys.path.insert(0, str(ROOT))
    from zbench.cells import slots
    fd = slots.try_claim_cell(agent_id, task_id)
    if fd is None:
        return True
    os.close(fd)
    return False


# --------------------------------------------------------------------------- cost
def _cost(agent_base: str, r: dict) -> tuple[float | None, str]:
    """pi-reported cost when > 0 (anthropic reports it); else tokens x pinned price table
    (tools/model_prices.py; OpenAI via pi reports 0, vLLM reports 0)."""
    rep = r.get("cost_usd")
    if not (r.get("input_tokens") or r.get("output_tokens")):
        return None, "no tokens"
    if rep:
        return float(rep), "reported"
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import model_prices
        c = model_prices.cost_usd(agent_base, r.get("input_tokens") or 0, r.get("output_tokens") or 0,
                                  r.get("cache_read_tokens") or 0, r.get("cache_write_tokens") or 0)
        if c is not None:
            return round(c, 6), "computed(token x list price)"
    except Exception:
        pass
    return None, "unpriced"


# --------------------------------------------------------------------------- trace digest
_ANSI = re.compile(r"\x1b?\[[0-9;]*m")
_WT = re.compile(r"(?:/[^\s\"'`]*?/)?zbench_wt_[^/\s\"'`]+/")


def _clean(s: str) -> str:
    return _WT.sub("", _ANSI.sub("", s or ""))


def _clip(s: str, n: int, tail: bool = False) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    if n < 40:
        return s[:n]
    if tail:
        return s[:n // 2] + " ...[cut]... " + s[-(n // 2):]
    return s[:n] + " ...[cut]"


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _fmt_call(name: str, args: dict, n: int) -> str:
    # Models can send malformed tool arguments (e.g. `edits` as a string); those are
    # exactly the cases the reflector should see, so fall back to the raw JSON.
    try:
        return _fmt_call_strict(name, args, n)
    except (AttributeError, TypeError, KeyError):
        return f"{name} (malformed args): " + _clip(_one_line(json.dumps(args, default=str)), n)


def _fmt_call_strict(name: str, args: dict, n: int) -> str:
    args = args or {}
    if name == "bash":
        return "bash: " + _clip(_one_line(_clean(args.get("command", ""))), n)
    if name == "read":
        extra = "".join(f" {k}={args[k]}" for k in ("offset", "limit") if k in args)
        return "read: " + _clean(str(args.get("path", ""))) + extra
    if name == "write":
        return f"write: {_clean(str(args.get('path','')))} ({len(args.get('content') or '')} chars)"
    if name == "edit":
        parts = []
        for e in (args.get("edits") or [])[:3]:
            parts.append("-" + _clip(_one_line(e.get("oldText", "")), n // 3) +
                         " +" + _clip(_one_line(e.get("newText", "")), n // 2))
        more = f" (+{len(args['edits'])-3} more)" if len(args.get("edits") or []) > 3 else ""
        return f"edit: {_clean(str(args.get('path','')))} " + " | ".join(parts) + more
    return f"{name}: " + _clip(_one_line(json.dumps(args)), n)


def _parse_session(path: Path) -> list[dict]:
    """-> steps: {think, say, calls:[{name,args,result,err}], stop, error}"""
    steps, by_id = [], {}
    if not path.is_file():
        return steps
    first_user_seen = False
    for line in path.read_text(errors="replace").splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") != "message":
            continue
        m = d["message"]
        role = m.get("role")
        if role == "user":
            if first_user_seen:       # compaction-continue nudges etc.
                steps.append({"think": "", "say": "[user/harness message] " +
                              _clip(_one_line("".join(b.get("text", "") for b in m.get("content", []) if isinstance(b, dict))), 200),
                              "calls": []})
            first_user_seen = True
        elif role == "assistant":
            st = {"think": "", "say": "", "calls": [], "stop": m.get("stopReason"),
                  "error": m.get("errorMessage")}
            for b in m.get("content", []):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "thinking" and b.get("thinking"):
                    st["think"] += b["thinking"] + " "
                elif b.get("type") == "text" and b.get("text"):
                    st["say"] += b["text"] + " "
                elif b.get("type") == "toolCall":
                    call = {"name": b.get("name"), "args": b.get("arguments") or {}, "result": None, "err": False}
                    st["calls"].append(call)
                    by_id[b.get("id")] = call
            steps.append(st)
        elif role == "toolResult":
            call = by_id.get(m.get("toolCallId"))
            if call is not None:
                call["result"] = "".join(b.get("text", "") for b in m.get("content", []) if isinstance(b, dict))
                call["err"] = bool(m.get("isError"))
    return steps


def _render_step(i: int, st: dict, lv: dict) -> str:
    out = []
    head = f"[{i}]"
    if st["think"].strip() and lv["think"]:
        out.append(f"{head} think: " + _clip(_one_line(_clean(st["think"])), lv["think"]))
        head = "   "
    if st["say"].strip() and lv["say"]:
        out.append(f"{head} say: " + _clip(_one_line(_clean(st["say"])), lv["say"]))
        head = "   "
    for c in st["calls"]:
        out.append(f"{head} > " + _fmt_call(c["name"], c["args"], lv["arg"]))
        head = "   "
        if c["result"] is not None and lv["res"]:
            res = _one_line(_clean(c["result"]))
            out.append("      <" + ("ERR " if c["err"] else " ") + _clip(res, lv["res"], tail=True))
    if st.get("error"):
        out.append(f"      !! turn error: {_clip(_one_line(st['error']), 200)}")
    return "\n".join(out) if out else f"{head} (empty turn)"


def condense_transcript(session: Path, budget: int) -> str:
    steps = _parse_session(session)
    if not steps:
        return "(no transcript captured)"
    n = len(steps)
    TAIL = {"think": 420, "say": 700, "arg": 260, "res": 520}
    HEAD = {"think": 220, "say": 200, "arg": 180, "res": 200}
    MID = {"think": 90, "say": 90, "arg": 110, "res": 70}

    def build(scale: float, keep_mid: int, tail_n: int, head_n: int) -> str:
        tail_n = min(n, tail_n)
        head_n = min(max(n - tail_n, 0), head_n)
        mid = list(range(head_n, n - tail_n))

        def sc(lv):
            return {k: int(v * scale) for k, v in lv.items()}
        lines = [_render_step(i, steps[i], sc(HEAD)) for i in range(head_n)]
        if mid:
            if keep_mid >= len(mid):
                chosen = mid
            elif keep_mid <= 0:
                chosen = []
            else:   # evenly spaced sample of the middle
                chosen = [mid[int(j * len(mid) / keep_mid)] for j in range(keep_mid)]
            for i in chosen:
                lines.append(_render_step(i, steps[i], sc(MID)))
            if len(mid) - len(chosen):
                lines.append(f"   ... [{len(mid) - len(chosen)} middle step(s) omitted] ...")
        lines += [_render_step(i, steps[i], sc(TAIL)) for i in range(n - tail_n, n)]
        return "\n".join(lines)

    # (scale, middle steps kept, tail steps, head steps): shrink the START first, keep the END
    ladder = ((1.0, 999, 14, 5), (1.0, 12, 14, 5), (0.8, 8, 12, 4), (0.6, 5, 10, 3), (0.5, 3, 8, 3),
              (0.4, 0, 8, 2), (0.3, 0, 6, 2), (0.25, 0, 5, 1), (0.2, 0, 4, 1))
    txt = ""
    for scale, keep, tail_n, head_n in ladder:
        txt = build(scale, keep, tail_n, head_n)
        if len(txt) <= budget:
            return f"({n} assistant turns)\n" + txt
    # last resort: drop the start, keep the end
    return f"({n} assistant turns)\n   ...[start cut]...\n" + txt[-budget:]


def _grading_section(row: dict, blob: Path | None, instance: dict, budget: int) -> str:
    st, oc = row.get("status"), row.get("outcome")
    verdict = "RESOLVED (hidden tests pass)" if row.get("tests_passed") else "NOT RESOLVED"
    lines = [f"{verdict}; status={st}; outcome={oc}"]
    md = (instance or {}).get("metadata") or {}
    f2p = md.get("fail_to_pass") or []
    if st == "no_patch_generated":
        lines.append("The agent finished without leaving any change in the repository (empty patch).")
    sess = (blob / "session.jsonl") if blob else None
    errs = [x["error"] for x in _parse_session(sess) if x.get("error")] if sess else []
    if errs:
        lines.append("Model endpoint error in transcript: " + _clip(_one_line(errs[-1]), 200))
    log = (blob / "pb-verify.log").read_text(errors="replace") if blob and (blob / "pb-verify.log").is_file() else ""
    if log:
        # drop the "AGENT PATCH:" header; keep from the first verify command on
        k = log.find("\n$ ")
        body = _clean(log[k + 1:] if k >= 0 else log)
        failed = []
        for m in re.finditer(r"^(FAIL|ERROR): (\S+) \(([^)]+)\)", body, re.M):
            nm = m.group(3)
            if nm not in failed:
                failed.append(nm)
        summ = re.findall(r"^(Ran \d+ tests? in [\d.]+s|FAILED \([^)]*\)|OK)\s*$", body, re.M)
        if failed:
            lines.append(f"Failed hidden tests ({len(failed)}): " + "; ".join(failed[:8]))
        if f2p and not row.get("tests_passed"):
            lines.append(f"(fail_to_pass set has {len(f2p)} test(s))")
        if summ:
            lines.append("Runner summary: " + " / ".join(summ[-2:]))
        # error excerpt: first failing block (traceback + assertion diff), else tail of the log
        m = re.search(r"^(FAIL|ERROR): .*?$", body, re.M)
        if m:
            exc = body[m.start():]
            exc = re.split(r"\n-{20,}\nRan \d+", exc)[0]
        else:
            exc = body[-1500:]
        room = max(budget - sum(len(x) + 1 for x in lines) - 20, 300)
        lines.append("Error excerpt:\n" + _clip("\n".join(l for l in exc.splitlines() if l.strip()), room, tail=False))
    elif st not in ("no_patch_generated",):
        lines.append("(no verify log captured)")
    return "\n".join(lines)


def build_trace(row: dict, instance: dict, max_chars: int = 12000) -> str:
    ev = row["evaluation_id"]
    blob = STORE / "blobs" / "attempt" / ev
    blob = blob if blob.is_dir() else None
    brief = _clean((instance or {}).get("problem_statement", "")).strip()
    patch = ""
    if blob and (blob / "patch.diff").is_file():
        patch = (blob / "patch.diff").read_text(errors="replace")
    # patch section: diffstat + head
    if patch.strip():
        files = re.findall(r"^diff --git a/(\S+) b/", patch, re.M)
        add = sum(1 for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++"))
        dele = sum(1 for l in patch.splitlines() if l.startswith("-") and not l.startswith("---"))
        patch_txt = f"{len(files)} file(s), +{add}/-{dele}: {', '.join(files[:8])}\n" + _clip(patch, 2300)
    else:
        patch_txt = "(empty / not produced)"
    cost = row.get("_cost")
    head = (f"=== {row['task_id']} | agent {row['config_id']} | "
            f"{'RESOLVED' if row.get('tests_passed') else 'NOT RESOLVED'} ({row.get('status')}) | "
            f"turns={row.get('turns')} | out_tok={row.get('output_tokens')} | "
            f"cost={'$%.3f' % cost if cost is not None else 'n/a'} | "
            f"{(row.get('total_duration_ms') or 0)/60000:.1f} min ===")
    brief_txt = _clip(brief, 2400, tail=True)
    grading = _grading_section(row, blob, instance, 2300)
    sess = (blob / "session.jsonl") if blob else Path("/nonexistent")
    overhead = len(head) + len(brief_txt) + len(patch_txt) + len(grading) + 200
    tr_budget = max(2500, max_chars - overhead)
    transcript = condense_transcript(sess, tr_budget)
    parts = [head,
             "--- TASK BRIEF (problem statement given to the agent) ---\n" + brief_txt,
             "--- AGENT TRANSCRIPT (condensed; [i]=assistant turn, '>' tool call, '<' tool result; end of run kept fuller) ---\n" + transcript,
             "--- FINAL PATCH ---\n" + patch_txt,
             "--- GRADING FEEDBACK (hidden tests) ---\n" + grading]
    out = "\n".join(parts)
    if len(out) > max_chars:     # last resort: squeeze the transcript
        over = len(out) - max_chars
        transcript = transcript[: max(len(transcript) - over - 60, 400)] + "\n...[cut]"
        parts[2] = "--- AGENT TRANSCRIPT (condensed) ---\n" + transcript
        out = "\n".join(parts)[:max_chars]
    return out


# --------------------------------------------------------------------------- the driver
def _launch_fill(agent_id: str, agents_file: Path, task_ids: list[str], label: str,
                 fanout: int, attempt_no: int) -> tuple[int, str]:
    run_id = f"gepa-{re.sub(r'[^A-Za-z0-9._-]+', '_', label)[:40]}-{uuid.uuid4().hex[:6]}"
    log = LOGS_DIR / f"{run_id}.driver.out"
    cmd = [sys.executable, str(ROOT / "zbench-tasks" / "run_coverage_matrix.py"), "--fill",
           "--agents", str(agents_file), "--only", agent_id,
           "--task-ids", ",".join(task_ids), "--db", str(DB_PATH),
           "--run-id", run_id, "--fanout", str(fanout),
           "--repo", os.environ["ZBENCH_TARGET_REPO"], "--rerun-infra"]
    with open(log, "w") as lf:
        lf.write("# " + " ".join(cmd) + "\n")
        lf.flush()
        rc = subprocess.call(cmd, cwd=str(ROOT), stdout=lf, stderr=subprocess.STDOUT, env=dict(os.environ))
    return rc, run_id


def _load_instance(task_id: str) -> dict:
    p = TASKS_DIR / task_id / "instance.jsonl"
    try:
        return json.loads(p.read_text().splitlines()[0])
    except Exception:
        return {}


def run_rollouts(base_agent_id: str, append_prompt: str, task_ids: list[str], run_label: str = "gepa",
                 *, fanout: int | None = None, max_infra_retries: int = 2, poll_s: float = 20.0,
                 timeout_s: float | None = None, include_trace: bool = True,
                 trace_chars: int = 12000, verbose: bool = True, sample: int = 1) -> list[dict]:
    """Run (or fetch from cache) one rollout per task for agent `base_agent_id` with
    `append_prompt` appended to pi's system prompt ("" = baseline/seed). Blocks until every
    cell has a valid attempt (or infra retries are exhausted). Thread-safe; any number of
    concurrent calls (same or different candidates) are fine: per-cell flocks dedupe work.

    Returns a list (same order as task_ids) of dicts:
      task_id, agent_id, base_agent_id, prompt_hash, resolved (0/1), status, outcome,
      evaluation_id, cost_usd, cost_source, tokens{input,output,cache_read,cache_write,total},
      turns, minutes, cached (True = attempt existed before this call), infra_failure (True =
      no valid attempt after retries; resolved=0 is NOT a capability signal, drop/redo it),
      trace (compact digest, <= trace_chars)."""
    _setup_environment()
    task_ids = list(dict.fromkeys(task_ids))
    agent_id, agents_file, row = ensure_candidate_agent(base_agent_id, append_prompt, sample)
    _ensure_credentials(row)
    t0 = time.time()
    log = (lambda m: print(f"[rollout {agent_id}] {m}", file=sys.stderr, flush=True)) if verbose else (lambda m: None)

    pre = _latest_attempts(agent_id, task_ids)
    cached = {t for t, r in pre.items() if is_valid_attempt(r)}
    launches = {t: 0 for t in task_ids}
    log(f"{len(cached)}/{len(task_ids)} cell(s) cached")

    while True:
        cur = _latest_attempts(agent_id, task_ids)
        pending = [t for t in task_ids if not (t in cur and is_valid_attempt(cur[t]))]
        if not pending:
            break
        if timeout_s and time.time() - t0 > timeout_s:
            log("timeout waiting for cells"); break
        busy = [t for t in pending if _cell_in_flight(agent_id, t)]
        todo = [t for t in pending if t not in busy and launches[t] <= max_infra_retries]
        if todo:
            for t in todo:     # invalid leftovers must be excluded so --fill re-plans the cell
                if t in cur and not is_valid_attempt(cur[t]):
                    _exclude_attempt(cur[t]["evaluation_id"], str(cur[t].get("status")))
                launches[t] += 1
            fo = fanout or min(max(len(todo), 1), 12)
            log(f"launching {len(todo)} cell(s) fanout={fo} (busy elsewhere: {len(busy)})")
            rc, run_id = _launch_fill(agent_id, agents_file, todo, run_label, fo, max(launches.values()))
            log(f"driver {run_id} rc={rc}")
        elif busy:
            time.sleep(poll_s)       # another caller is running these cells; wait for them
        else:
            break                    # nothing in flight, retries exhausted

    final = _latest_attempts(agent_id, task_ids)
    results = []
    for t in task_ids:
        r = final.get(t)
        if r is None:
            results.append({"task_id": t, "agent_id": agent_id, "base_agent_id": base_agent_id,
                            "prompt_hash": prompt_hash(append_prompt), "resolved": 0, "status": "missing",
                            "outcome": None, "evaluation_id": None, "cost_usd": None, "tokens": {},
                            "turns": None, "minutes": None, "cached": False, "infra_failure": True,
                            "trace": "(no attempt recorded; see gepa/store/driver_logs)"})
            continue
        cost, csrc = _cost(base_agent_id, r)
        r["_cost"] = cost
        valid = is_valid_attempt(r)
        res = {"task_id": t, "agent_id": agent_id, "base_agent_id": base_agent_id,
               "prompt_hash": prompt_hash(append_prompt),
               "resolved": int(bool(r["tests_passed"])), "status": r["status"], "outcome": r["outcome"],
               "evaluation_id": r["evaluation_id"], "cost_usd": cost, "cost_source": csrc,
               "tokens": {"input": r.get("input_tokens"), "output": r.get("output_tokens"),
                          "cache_read": r.get("cache_read_tokens"), "cache_write": r.get("cache_write_tokens"),
                          "total": r.get("total_tokens")},
               "turns": r.get("turns"),
               "minutes": round((r.get("total_duration_ms") or 0) / 60000, 2),
               "cached": t in cached, "infra_failure": not valid}
        if not valid:
            blob = STORE / "blobs" / "attempt" / r["evaluation_id"] / "session.jsonl"
            errs = [x["error"] for x in _parse_session(blob) if x.get("error")]
            res["infra_error"] = errs[-1] if errs else r.get("status")
        if include_trace:
            res["trace"] = build_trace(r, _load_instance(t), trace_chars)
        results.append(res)
    log(f"done in {(time.time()-t0)/60:.1f} min: resolved "
        f"{sum(x['resolved'] for x in results)}/{len(results)}")
    return results


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Run GEPA rollouts for one pi agent + appended prompt.")
    ap.add_argument("--base", required=True, choices=BASE_AGENTS + ("",), help="base agent_id from agents-matrix.jsonl")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--prompt", default="", help="text appended to pi's system prompt ('' = seed)")
    g.add_argument("--prompt-file", help="read the appended prompt from this file")
    ap.add_argument("--tasks", required=True, help="comma-separated task ids (ZT-...)")
    ap.add_argument("--label", default="gepa")
    ap.add_argument("--fanout", type=int, default=None)
    ap.add_argument("--no-trace", action="store_true")
    ap.add_argument("--json-out", help="write full results JSON here (else a summary is printed)")
    ap.add_argument("--print-trace", action="store_true")
    a = ap.parse_args(argv)
    prompt = Path(a.prompt_file).read_text() if a.prompt_file else a.prompt
    res = run_rollouts(a.base, prompt, [t.strip() for t in a.tasks.split(",") if t.strip()], a.label,
                       fanout=a.fanout, include_trace=not a.no_trace)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(res, indent=1))
    for r in res:
        print(json.dumps({k: v for k, v in r.items() if k != "trace"}))
        if a.print_trace and r.get("trace"):
            print(r["trace"])


if __name__ == "__main__":
    main()
