#!/usr/bin/env python3
"""W23 -- ON-DEMAND, NON-BLOCKING run validator.

Off the critical path: you RUN this when you want to (re)validate; nothing in the
fill/coverage pipeline waits on it. Validators write NOTES/HINTS only. Notes never
affect coverage/ranking; humans control scoring exclusions via run_exclusion state in the web UI.

Two validators, each stamps its `source` provenance on notes it creates:
  * rule_based -- the deterministic failure-mode classifier
    (scoring.classify_attempt): artifact:auth / artifact:budget / artifact:infra.
  * llm_agent  -- an LLM judge (pi + a configurable model; START with fable) that
    reads the transcript and decides CONTAMINATION (did the agent mine the reference
    fix from git history/review rather than solve the task?). A cheap rule-based
    PREFILTER only sends transcripts that actually show git signals to the LLM, so a
    mere code comment containing "cherry-pick" is NOT auto-flagged (the LLM
    distinguishes reading-unrelated-code from actually-using-the-fix).

Validation METADATA (the `validation` table) records which attempt was validated by
which VALIDATOR_VERSION, so a re-run only revisits new attempts (or, with
--revalidate, everything, e.g. after bumping the version / judge model).

Requires the W39-migrated bench.db (note + run_exclusion + validation tables).

Usage:
  python3 validate_runs.py [--db PATH] [--no-llm] [--judge-model claude-fable-5]
                           [--revalidate] [--limit N] [--dry-run]
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import scoring as S
import config  # noqa: E402  # gold_code_path (answer keys live outside the task dirs)

DEF_DB = str(HERE.parent / "bench-db" / "bench.db")
TASKS = HERE / "tasks"
VALIDATOR_VERSION = "v3"           # bump to force re-validation of all attempts
#   v3 (2026-07-30): added the AGENT-evidence no_patch scan (S.classify_no_patch_evidence
#   via _agent_evidence) so a sub-canonical generation-timeout kill or an output-token
#   cap -- invisible to the fact-only classifier -- is re-derived from the agent stderr.
#   v2 (2026-07-30): added the verify-log INFRA scan (looks_like_setup_infra_log) so a
#   setup/build-farm failure the workflow mislabeled `tests_failed` (e.g. a
#   submodule conflict) is re-derived from pb-verify.log instead of trusted as a miss.
DEFAULT_JUDGE_MODEL = "claude-fable-5"

# cheap contamination PREFILTERS: only these signals send a transcript to the LLM.
# GIT_SIGNAL: environment mining (git history/refs). NET_SIGNAL: runtime network
# fetch of the public fix -- Zulip is a public repo, so github/raw/commit URLs,
# fetch tooling, and structured web-tool call names are all red flags. The task's
# fix sha and issue number were STRIPPED from the problem statement, so either
# appearing anywhere in a transcript is itself a signal (scanned in _signal_context).
GIT_SIGNAL = re.compile(
    r"cherry-pick|git\s+log|git\s+show|rev-list|branch\s+-a|--grep=|reflog|git\s+diff\s+[0-9a-f]{7,}"
    # re-attaching to the base repo the isolated checkout was severed from: a fetch/clone
    # (esp. by file://), a raw .git path, --git-dir, or checking out a bare sha
    r"|git\s+(?:fetch|clone)|file://|FETCH_HEAD|--git-dir|\.git/|git\s+checkout\s+[0-9a-f]{7,}",
    re.I)
NET_SIGNAL = re.compile(
    r"github\.com/zulip|raw\.githubusercontent|api\.github\.com|/commit/[0-9a-f]{7,}"
    r"|/pull/\d+|/issues/\d+|\bcurl\s+-|\bwget\s+http|git\s+clone\s+http"
    r"|git\s+fetch\s+http|git\s+remote\s+add|\bWebFetch\b|\bWebSearch\b|\bweb_search\b",
    re.I)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _require_migrated(conn):
    for t in ("note", "run_exclusion", "validation"):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            sys.exit(f"no `{t}` table -- bench.db predates the notes/exclusion schema; restore from the migrated DB or rerun the archived migration from git history")


def _fix_sha(task_id):
    mp = TASKS / task_id / "meta.json"
    if mp.exists():
        try:
            return (json.loads(mp.read_text()).get("fix_commit") or "")[:12]
        except Exception:
            return ""
    return ""


def _task_meta(task_id):
    mp = TASKS / task_id / "meta.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            return {}
    return {}


def _gold_code_text(task_id):
    gp = config.gold_code_path(task_id)
    return gp.read_text(errors="replace") if gp.exists() else ""


def _patch_text(bundle_dir):
    if not bundle_dir:
        return ""
    d = Path(bundle_dir)
    if not d.is_absolute():                       # bundle_dir is relative to bench-db/
        d = HERE.parent / "bench-db" / d
    pp = d / "patch.diff"
    return pp.read_text(errors="replace") if pp.exists() else ""


def _transcript_text(bundle_dir):
    """Concatenate the transcript text for an attempt bundle, for the git-signal
    prefilter + LLM judge.

    W23 refinement (2026-07-28): PREFER the pi SESSION (.jsonl) + try.json -- they
    are the clean, deduplicated record of tool calls/results. The rawcli stream
    (`*rawcli*.txt`) can be tens of MB (e.g. 49MB) because it repeats each tool
    call across dozens of streaming `partialJson` deltas; feeding that to
    `_git_context` wastes the excerpt budget on duplicate command fragments and
    makes the regex slow. Use rawcli ONLY as a fallback when no session/try file
    exists, and CAP the read so we never load tens of MB."""
    if not bundle_dir:
        return ""
    d = Path(bundle_dir)
    if not d.is_absolute():
        d = HERE.parent / "bench-db" / d
    if not d.is_dir():
        return ""
    parts = []
    for pat in ("*session*.jsonl", "*try*.json"):
        for f in sorted(d.glob(pat)):
            try:
                parts.append(f.read_text(errors="replace"))
            except Exception:
                pass
    if parts:
        return "\n".join(parts)
    # fallback: rawcli, but cap the read (tens of MB otherwise)
    for f in sorted(d.glob("*rawcli*.txt")):
        try:
            with f.open(errors="replace") as fh:
                parts.append(fh.read(2_000_000))  # 2MB cap
        except Exception:
            pass
    return "\n".join(parts)


def _verify_log_text(bundle_dir, maxlen=200_000):
    """The verify log (pb-verify.log) for an attempt bundle -- the PRIMARY evidence
    of what happened in the build+test phase. Read tail-capped: the infra/verdict
    signatures we scan for live near the end."""
    if not bundle_dir:
        return ""
    d = Path(bundle_dir)
    if not d.is_absolute():
        d = HERE.parent / "bench-db" / d
    txt = ""
    for name in ("pb-verify.log", "verify.log"):
        f = d / name
        if f.is_file():
            try:
                txt = f.read_text(errors="replace")
                break
            except Exception:
                pass
    return txt[-maxlen:] if txt else ""


def _agent_evidence(bundle_dir):
    """(stderr_text, output_tokens) from the AGENT bundle JSON -- the PRIMARY evidence
    of WHY a no_patch happened (a generation timeout kill / output-token cap). Mirrors
    _verify_log_text but reads the adapter's recorded stderr instead of the verify log."""
    if not bundle_dir:
        return "", None
    d = Path(bundle_dir)
    if not d.is_absolute():
        d = HERE.parent / "bench-db" / d
    stderr, otoks = "", None
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            obj = json.loads(f.read_text(errors="replace"))
        except Exception:
            continue
        if isinstance(obj, dict):
            if obj.get("stderr"):
                stderr += "\n" + str(obj.get("stderr"))
            # output tokens: prefer the stdout token_usage, else parse the usage log line
            try:
                tu = json.loads(obj.get("stdout") or "{}").get("token_usage") or {}
                if tu.get("output_tokens"):
                    otoks = int(tu["output_tokens"])
            except Exception:
                pass
    if otoks is None and stderr:
        m = re.search(r"'output_tokens':\s*(\d+)", stderr)
        if m:
            otoks = int(m.group(1))
    return stderr, otoks


# Transient provider/infra errors (safe to auto-invalidate + re-run). We EXCLUDE
# deterministic errors like a 400 context-length so a re-run doesn't loop forever.
_TRANSIENT_ERR = re.compile(
    r"tim(?:e|ed)?\s*out|timeout|\b(?:429|500|502|503|504)\b|connection|"
    r"unavailable|overloaded|reset by peer|temporar|throttl", re.I)


def _session_terminal_error(bundle_dir):
    """Return (True, msg) iff the agent run TERMINATED on a TRANSIENT provider error
    -- the FINAL assistant turn has stopReason='error' with a transient message
    (e.g. 'Request timed out.'). Such a run never got a fair final completion, so it
    is an INFRA artifact, NOT a capability no-patch. Deterministic (reads the session
    jsonl) -> the caller auto-accepts. A non-terminal error, or a deterministic error
    (e.g. 400 context-length), does NOT fire (avoids a re-run loop)."""
    if not bundle_dir:
        return (False, "")
    d = Path(bundle_dir)
    if not d.is_absolute():
        d = HERE.parent / "bench-db" / d
    if not d.is_dir():
        return (False, "")
    sess = sorted(d.glob("*session*.jsonl"))
    if not sess:
        return (False, "")
    try:
        lines = sess[-1].read_text(errors="replace").splitlines()
    except Exception:
        return (False, "")
    last_assistant = None
    for ln in lines:
        try:
            e = json.loads(ln)
        except Exception:
            continue
        m = e.get("message", {})
        if m.get("role") == "assistant":
            last_assistant = m
    if last_assistant and last_assistant.get("stopReason") == "error":
        msg = str(last_assistant.get("errorMessage") or "")
        if _TRANSIENT_ERR.search(msg):
            return (True, msg[:120])
    return (False, "")


def _git_context(text, fix_sha, task_id, window=400, maxlen=12000, issue=None):
    """Extract bounded snippets around git/network signals, the fix sha, the task id,
    and the (statement-stripped) issue number, to feed the judge without shipping a
    multi-MB transcript."""
    hits = []
    for sig in (GIT_SIGNAL, NET_SIGNAL):
        for m in sig.finditer(text):
            s = max(0, m.start() - window)
            hits.append(text[s:m.end() + window])
    needles = [fix_sha, task_id] + ([f"#{issue}", f"issues/{issue}"] if issue else [])
    for needle in needles:
        if needle:
            i = text.find(needle)
            if i >= 0:
                hits.append(text[max(0, i - window):i + window])
    seen, out = set(), []
    for h in hits:
        k = h[:80]
        if k not in seen:
            seen.add(k)
            out.append(h)
    blob = "\n---\n".join(out)
    return blob[:maxlen]


JUDGE_SYS = (
    "You are a strict contamination judge for a coding benchmark built on the PUBLIC "
    "zulip/zulip repository. The agent must SOLVE the task itself. It is CONTAMINATION "
    "if the agent obtained the reference fix from EITHER of two channels and used it: "
    "(1) environment mining -- git history, review branches, the fix commit or its "
    "diff (e.g. `git cherry-pick <fixsha>`, `git show <fixsha>`, `git log "
    "--grep=...`); (2) network fetch -- cloning/fetching zulip/zulip from GitHub, "
    "curling a commit/PR/issue URL, or using a web-search/web-fetch tool to find the "
    "upstream fix. It is NOT contamination to read existing source code, to run git "
    "commands that return nothing useful, or to mention GitHub in prose without "
    "fetching. Output ONLY one line of JSON: "
    '{"contaminated": bool, "channel": "git"|"network"|"none", '
    '"confidence": 0.0-1.0, "evidence": "<=160 chars"}.')


def _llm(sys_text, prompt, timeout=300):
    """Invoke the pinned judge model via the host's configured backend (claude CLI
    here; pi where installed). System text is folded into the prompt for backends
    without a system-prompt flag."""
    import tempfile as _tf
    from config import LLM_CMD
    try:
        r = subprocess.run([*LLM_CMD, f"{sys_text}\n\n{prompt}"],
                           capture_output=True, text=True, timeout=timeout,
                           cwd=_tf.gettempdir())
    except Exception as e:
        return None, f"judge invocation failed: {e}"
    out = r.stdout.strip()
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, f"no JSON in judge output: {out[:120]}"
    try:
        return json.loads(m.group(0)), None
    except Exception as e:
        return None, f"judge JSON parse failed: {e}: {out[:120]}"


def llm_judge(model, task_id, fix_sha, context):
    prompt = (f"TASK: {task_id} (reference fix commit {fix_sha or 'unknown'}).\n"
              f"Below are excerpts of the agent transcript around git/network "
              f"activity. Did the agent obtain and USE the reference fix?\n\n"
              f"=== TRANSCRIPT EXCERPTS ===\n{context}\n=== END ===")
    return _llm(JUDGE_SYS, prompt)


# ---- patch-similarity judge (public-repo backstop) --------------------------------
PATCH_JUDGE_SYS = (
    "You judge whether an agent's patch was PLAGIARIZED from the reference fix of a "
    "public repository or plausibly derived independently. Exact match on a tiny diff "
    "proves nothing (honest convergence); what convergence CANNOT produce is agreement "
    "on entropy-bearing choices. Weigh: identical NEW identifier names, identical "
    "comment/docstring prose, identical test-data strings, reproduction of the "
    "reference's INCIDENTAL edits (whitespace churn, drive-by refactors, import "
    "reordering), and multi-file hunk-for-hunk structure on non-trivial diffs. "
    "Output ONLY one line of JSON: "
    '{"verbatim_similarity": 0.0-1.0, "entropy_matches": ["..."], '
    '"convergence_plausible": bool, "confidence": 0.0-1.0, "evidence": "<=200 chars"}.')


def _norm_patch(text):
    """Whitespace/context-normalized changed lines (for the deterministic pre-metric)."""
    out = []
    for ln in (text or "").splitlines():
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
            out.append(" ".join(ln[1:].split()))
    return out


def patch_premetrics(agent_patch, gold_patch):
    import difflib
    a, g = _norm_patch(agent_patch), _norm_patch(gold_patch)
    ratio = difflib.SequenceMatcher(None, "\n".join(a), "\n".join(g)).ratio() if a and g else 0.0
    fa = set(re.findall(r"^\+\+\+ b/(\S+)", agent_patch or "", re.M))
    fg = set(re.findall(r"^\+\+\+ b/(\S+)", gold_patch or "", re.M))
    jaccard = len(fa & fg) / len(fa | fg) if fa | fg else 0.0
    identical = len(set(a) & set(g))
    return {"line_similarity": round(ratio, 3), "file_jaccard": round(jaccard, 3),
            "identical_changed_lines": identical, "gold_changed_lines": len(g)}


def patch_judge(model, task_id, tier, agent_patch, gold_patch, pre):
    prompt = (f"TASK: {task_id} (contamination tier {tier or '?'}; tier A = the fix "
              f"postdates every model's training cutoff, so a verbatim match implies "
              f"runtime fetch or a wrong cutoff -- either way exclusion-worthy).\n"
              f"Deterministic pre-metrics: {json.dumps(pre)}\n\n"
              f"=== REFERENCE FIX ===\n{(gold_patch or '')[:8000]}\n\n"
              f"=== AGENT PATCH ===\n{(agent_patch or '')[:8000]}\n=== END ===")
    return _llm(PATCH_JUDGE_SYS, prompt)


def write_note(conn, evaluation_id, kind, source, body, *, confidence=None, evidence=None,
               produced_by=None, dry=False):
    """Write/update a machine note for a run. Notes are comments/hints only and NEVER
    affect scoring. Humans may use them to set/clear run scoring exclusions."""
    body = f"[{kind}] {body}" if kind and not str(body).startswith(f"[{kind}]") else body
    if dry:
        print(f"    [dry] NOTE src={source} eval={str(evaluation_id)[:8]} "
              f"conf={confidence} :: {body[:70]}")
        return
    row = conn.execute(
        """SELECT id FROM note WHERE subject_type='run' AND subject_id=?
              AND source=? AND body=? AND IFNULL(produced_by,'')=IFNULL(?,'')""",
        (evaluation_id, source, body, produced_by),
    ).fetchone()
    if row:
        conn.execute(
            """UPDATE note SET body=?, evidence=?, confidence=?,
                     updated_at=? WHERE id=?""",
            (body, evidence, confidence, _now(), row["id"]),
        )
    else:
        conn.execute(
            """INSERT INTO note(subject_type,subject_id,source,body,evidence,
                   produced_by,confidence,created_by,created_at)
               VALUES('run',?,?,?,?,?,?,?,?)""",
            (evaluation_id, source, body, evidence, produced_by, confidence,
             produced_by or source, _now()),
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEF_DB)
    ap.add_argument("--no-llm", action="store_true", help="skip the LLM contamination judge")
    ap.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    ap.add_argument("--revalidate", action="store_true", help="re-validate ALL attempts")
    ap.add_argument("--limit", type=int, default=0, help="cap attempts processed (0=all)")
    ap.add_argument("--task-id", help="only this task id -- target a known case first")
    ap.add_argument("--agent", help="only this config_id (e.g. claude-cli-fable-5)")
    ap.add_argument("--run", help="only this run_id")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    db = Path(a.db)
    if not db.exists():
        sys.exit(f"no bench.db at {db}")
    # busy_timeout so a (re)validation write does not fail immediately with
    # "database is locked" if a grid cell is mid-write -- W23 note (ii). Matches
    # the benchdb writer's 30s. WAL lets our reads proceed alongside a writer.
    conn = sqlite3.connect(str(db), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    _require_migrated(conn)

    judged_by = f"llm:{a.judge_model}"
    done = {r["evaluation_id"]: r["validator_version"]
            for r in conn.execute("SELECT evaluation_id, validator_version FROM validation")}
    rows = list(conn.execute(
        "SELECT a.evaluation_id, a.run_id, a.config_id, a.task_id, "
        "a.tests_passed, a.status, a.outcome, a.runtime_ms, a.total_duration_ms, "
        "a.output_tokens "
        "FROM attempt a"))
    # facts-only: try_number is gone (dropped, not carried); bundle_dir is DERIVED from the
    # eval id and the budget comes from agents-meta (the harness_config dim is dropped).
    _budget = S.agent_budget_map()
    rows = [{**dict(r), "bundle_dir": f"blobs/attempt/{r['evaluation_id']}",
             "budget_s": _budget.get(r["config_id"])} for r in rows]

    if a.task_id:
        rows = [r for r in rows if r["task_id"] == a.task_id]
    if a.agent:
        rows = [r for r in rows if r["config_id"] == a.agent]
    if a.run:
        rows = [r for r in rows if r["run_id"] == a.run]
    todo = [r for r in rows if a.revalidate or a.task_id or a.agent or a.run
            or done.get(r["evaluation_id"]) != VALIDATOR_VERSION]
    if a.limit:
        todo = todo[:a.limit]
    print(f"validator {VALIDATOR_VERSION} | attempts={len(rows)} | to validate={len(todo)} "
          f"| llm={'off' if a.no_llm else judged_by}" + (" | DRY-RUN" if a.dry_run else ""))

    n_art = n_contam = n_llm_calls = 0
    for r in todo:
        task_id, cid, rid = r["task_id"], r["config_id"], r["run_id"]
        result = []
        # (1) rule_based failure-mode classification -> artifact:* proposals
        cls = S.classify_attempt(r, r["budget_s"])
        if S.is_artifact_class(cls):
            n_art += 1
            reason = {"artifact:auth": "CLI fast-fail (tiny runtime, no output) -- e.g. expired OAuth",
                      "artifact:budget": "no_patch hit a short (< canonical) budget wall",
                      "artifact:infra": f"infra failure ({r['status']}/{r['outcome']})"}.get(cls, cls)
            # W39: artifacts are machine hints only; humans decide scoring exclusion in run_exclusion.
            write_note(conn, r["evaluation_id"], cls, "rule_based", reason,
                       confidence=1.0,
                       evidence=f"status={r['status']} rt_ms={r['runtime_ms']} out={r['output_tokens']}",
                       produced_by=f"classify_attempt@{VALIDATOR_VERSION}", dry=a.dry_run)
            result.append(cls)
        # (1b) transcript-aware: a no-patch/miss whose run TERMINATED on a transient
        # provider error (stopReason=error, e.g. 'Request timed out.') is an INFRA
        # artifact the fact-only classifier can't see (it looks like a mid-budget
        # give-up). Deterministic -> auto-accept + re-run. Skip if already an artifact
        # or if it actually resolved.
        elif not r["tests_passed"]:
            term_err, emsg = _session_terminal_error(r["bundle_dir"])
            if term_err:
                n_art += 1
                write_note(conn, r["evaluation_id"], "artifact:infra", "rule_based",
                           f"agent run terminated on a transient provider error ({emsg})",
                           confidence=1.0,
                           evidence=f"final assistant turn stopReason=error: {emsg}",
                           produced_by=f"session_terminal_error@{VALIDATOR_VERSION}", dry=a.dry_run)
                result.append("artifact:infra")
            else:
                # (1c) VERIFY-LOG evidence scan: the fact-only classifier trusts the
                # stored status, so a setup/build-farm failure the workflow recorded
                # as `tests_failed` (e.g. a workspace submodule conflict that aborted
                # BEFORE the build) looks like a genuine miss. Re-derive it from the
                # PRIMARY evidence (pb-verify.log) -- this is the class the button
                # "never found" because nothing here ever read the verify log.
                vlog = _verify_log_text(r["bundle_dir"])
                if vlog and S.looks_like_setup_infra_log(vlog):
                    n_art += 1
                    sig = next((ln.strip()[:160] for ln in vlog.splitlines()
                                if S.looks_like_setup_infra_log(ln)), "setup/infra failure")
                    write_note(conn, r["evaluation_id"], "artifact:infra", "rule_based",
                               "verify aborted on a setup/build-farm infra failure "
                               "(workspace prep / submodule sync / host), NOT a test failure",
                               confidence=1.0,
                               evidence=f"pb-verify.log: {sig}",
                               produced_by=f"verify_log_infra_scan@{VALIDATOR_VERSION}", dry=a.dry_run)
                    result.append("artifact:infra")
                elif r["status"] == "no_patch_generated":
                    # (1d) AGENT-evidence scan for no_patch (W52): the fact-only
                    # classifier trusts the CONFIG budget (which may not match the
                    # budget an OLD attempt actually ran under -> a sub-canonical
                    # timeout kill looks like a genuine slow-fail) and cannot see an
                    # OUTPUT-TOKEN cap. Re-derive both from the agent stderr (PRIMARY
                    # evidence). Deliberately conservative: an AT/above-canonical
                    # timeout is NOT flagged (the fixed harness captures timed-out edits
                    # -> a genuine no_patch there means genuinely no edits).
                    serr, otoks = _agent_evidence(r["bundle_dir"])
                    ncls, nreason, nev = S.classify_no_patch_evidence(serr, otoks or r["output_tokens"])
                    if ncls:
                        n_art += 1
                        write_note(conn, r["evaluation_id"], ncls, "rule_based", nreason,
                                   confidence=1.0, evidence=nev,
                                   produced_by=f"no_patch_evidence@{VALIDATOR_VERSION}", dry=a.dry_run)
                        result.append(ncls)
        # (2) llm_agent contamination judge (prefiltered by git AND network signals)
        if not a.no_llm:
            text = _transcript_text(r["bundle_dir"])
            fix = _fix_sha(task_id)
            tmeta = _task_meta(task_id)
            issue = tmeta.get("issue")
            hot = bool(text) and (GIT_SIGNAL.search(text) or NET_SIGNAL.search(text)
                                  or (fix and fix in text)
                                  or (issue and f"#{issue}" in text))
            if hot:
                ctx = _git_context(text, fix, task_id, issue=issue)
                n_llm_calls += 1
                v, err = llm_judge(a.judge_model, task_id, fix, ctx)
                if err:
                    print(f"    [llm-skip] {task_id} {cid}: {err}")
                elif v.get("contaminated"):
                    n_contam += 1
                    write_note(conn, r["evaluation_id"], "contamination", "llm_agent",
                               f"LLM judge: agent may have obtained/used the reference fix "
                               f"(channel: {v.get('channel', '?')})",
                               confidence=float(v.get("confidence") or 0),
                               evidence=str(v.get("evidence") or "")[:160],
                               produced_by=judged_by, dry=a.dry_run)
                    result.append("contamination?")
            # (2b) patch-similarity judge: every RESOLVED attempt is compared to the
            # gold fix. Tier-aware: on tier A a verbatim+entropy match implies runtime
            # fetch or a wrong cutoff; on tier B/C it calibrates the detector.
            if r["tests_passed"]:
                gold = _gold_code_text(task_id)
                agent_patch = _patch_text(r["bundle_dir"])
                if gold and agent_patch:
                    pre = patch_premetrics(agent_patch, gold)
                    tier = (tmeta.get("contamination") or {}).get("tier")
                    if pre["line_similarity"] >= 0.35 or pre["identical_changed_lines"] >= 3:
                        n_llm_calls += 1
                        v, err = patch_judge(a.judge_model, task_id, tier, agent_patch, gold, pre)
                        if err:
                            print(f"    [patch-judge-skip] {task_id} {cid}: {err}")
                        elif (not v.get("convergence_plausible", True)
                              or float(v.get("verbatim_similarity") or 0) >= 0.9):
                            n_contam += 1
                            write_note(conn, r["evaluation_id"], "contamination", "llm_patch",
                                       f"patch-similarity judge: verbatim/entropy match with the "
                                       f"public gold fix (tier {tier or '?'}) -- "
                                       f"{'runtime fetch or wrong cutoff' if tier == 'A' else 'expected memorization; calibration signal'}",
                                       confidence=float(v.get("confidence") or 0),
                                       evidence=(f"pre={pre} entropy={v.get('entropy_matches', [])[:3]} "
                                                 f"{str(v.get('evidence') or '')}")[:160],
                                       produced_by=judged_by, dry=a.dry_run)
                            result.append("contamination?")
        # (3) record validation metadata
        if not a.dry_run:
            conn.execute(
                "INSERT INTO validation(evaluation_id, validated_at, validator_version, result) "
                "VALUES(?,?,?,?) ON CONFLICT(evaluation_id) DO UPDATE SET "
                "validated_at=excluded.validated_at, validator_version=excluded.validator_version, "
                "result=excluded.result",
                (r["evaluation_id"], _now(), VALIDATOR_VERSION, ",".join(result) or "clean"))
    if not a.dry_run:
        conn.commit()
    conn.close()
    n_clean = len(todo) - sum(1 for r in todo
                              if S.is_artifact_class(S.classify_attempt(r, r["budget_s"])))
    print(f"\nvalidated {len(todo)}: ~{n_clean} clean/capability (no note) + "
          f"{n_art} artifact note(s) + {n_contam} contamination note(s) "
          f"({n_llm_calls} LLM judge calls).")
    if n_art or n_contam:
        print(f"  {n_art + n_contam} machine note(s) written for human context; "
              "notes do not affect ranking unless a human adds a scoring exclusion.")


if __name__ == "__main__":
    main()
