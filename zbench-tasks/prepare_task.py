#!/usr/bin/env python3
"""One command: turn a mined Zulip fix commit into a judged zbench task candidate.

    prepare_task.py <fix_sha> [--repo P] [--tasks-dir P] [--no-oracle] [--fast-oracle]

Pipeline (fail-fast: cheap deterministic gates -> LLM calls -> heavy oracle last):
  1  dedup (tasks/ZT-<sha12>/ exists -> abort)
  2  resolve + re-check the mining predicate (defense against stale input)
  3  scope gate: date >= MIN_COMMIT_DATE and ancestor of origin/main
  3b contamination tier from agents-meta.jsonl training cutoffs (A/B/C)
  4  patch split via `git diff parent fix -- <paths>` (path partition; NO commit
     message in patch headers -- the old `git show` leak)
  5  deterministic unsuitability pre-filters (i18n churn, renames, API-changelog
     lockstep, docs-only)
  6  GitHub issue fetch (`gh api`) -- title+body ONLY; missing/PR-ref -> drop (thin OK)
  7  LLM screens (pinned model): suitability (verifiability-first) -> coupling
     (clean | specifiable -> interface contract into the brief | coupled -> drop)
  8  fail_to_pass extraction: deterministic AST-first; LLM fallback re-verified
  9  pass_to_pass selection: test files of gold_code's modules (capped)
  10 LLM problem statement from ISSUE + expected-behavior evidence (gold test diff) +
     interface contract (commit message forbidden) + leak guard
  11 oracle (oracle_validate.py; flake-gated flip + P2P in both arms)

Error trichotomy (ported): InfraError -> exit 75, write NOTHING; ScriptError ->
exit 70, write nothing; a terminal Verdict -> the task dir is written atomically
(staging tempdir -> os.rename).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import quality  # noqa: E402
from config import (SOLUTIONS_DIR, CUTOFF_BUFFER_DAYS, FIXES_PARTIAL_RE, FIXES_RE, GITHUB_REPO,  # noqa: E402
                    MAIN_REF, MIN_COMMIT_DATE, PI_CMD, ZULIP_REPO, classify_file,
                    classify_support, is_dep_file, touches_migrations)

TASKS_DIR_DEFAULT = HERE / "tasks"
AGENTS_META = HERE / "agents-meta.jsonl"
P2P_CAP = 2
MIN_STATEMENT = 200

INFRA_SIGNS = ("not logged in", "oauth", "token expired", "rate limit",
               "cannot connect to the docker daemon", "no space left on device",
               "permission denied (publickey)", "quota exceeded", "api rate limit",
               "unable to access 'https://github", "bad credentials", "connection reset")


class InfraError(Exception):
    """Transient environment problem: exit 75, write nothing, safe to retry."""


class ScriptError(Exception):
    """Pipeline bug or needs-a-human: exit 70, write nothing."""


class Verdict(Exception):
    """Terminal curation outcome: a task record IS written."""
    def __init__(self, status: str, reason_code: str, reason: str):
        super().__init__(reason)
        self.status, self.reason_code, self.reason = status, reason_code, reason


def scan_infra(text: str) -> None:
    low = (text or "").lower()
    for s in INFRA_SIGNS:
        if s in low:
            raise InfraError(f"infra signature {s!r} in output")
    if re.search(r"(?<![0-9a-f])429(?![0-9a-f])", low):   # word-bounded: not a hex sha
        raise InfraError("429 rate limit in output")


def git(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=timeout)


# ---- LLM plumbing (pinned model; JSON out) ---------------------------------------
def pi_json(prompt: str, timeout: int = 240) -> dict:
    import tempfile as _tf
    r = subprocess.run([*PI_CMD, prompt], capture_output=True, text=True, timeout=timeout,
                       cwd=_tf.gettempdir())
    scan_infra(r.stderr)
    if r.returncode != 0:
        raise InfraError(f"pi exited {r.returncode}: {r.stderr[-300:]}")
    return _extract_json(r.stdout)


def _extract_json(text: str) -> dict:
    m = re.search(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        m = re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise ScriptError(f"no JSON in LLM output: {text[:200]!r}")
    return json.loads(m.group(1))


# ---- prompts (static constants; git gives free versioning) ------------------------
P_SUIT = """You screen candidate tasks for a SWE-bench-style coding benchmark built from
the open-source Zulip codebase (Python/Django backend + TypeScript web client). The bar
is VERIFIABILITY, not task type: bug fixes, new features, and behavior-affecting
refactors are all GOOD tasks as long as (a) they are a real engineering workflow someone
would plausibly be assigned, and (b) the hidden test grades an observable outcome
deterministically. Judge ONLY from the data below; reply with JSON
{"verdict": "keep"|"drop", "task_type": "...", "reason": "..."}.

DROP only what cannot be graded on outcome: pure rename/move with no behavior change (a
test cannot fail-before/pass-after); revert; i18n/translation string churn;
docs/help-center only; type-annotation-only; dependency bump; test-only change;
the test asserts API_FEATURE_LEVEL, exact changelog/api-docs wording, or OpenAPI
schema lockstep bookkeeping; the test asserts migration internals; the change is
time/version-gated (asserts on wall-clock windows or ZULIP_VERSION); CSS-only visual
polish observable only via real browser layout.

Do NOT drop a task for being a new feature, for adding new settings/APIs/UI surface, or
for a thin issue -- naming and spec gaps are handled by later stages.

ALSO DROP brittle tests that grade format over behavior: a hidden test that pins an
EXACT long output string, a whole rendered-HTML/JSON snapshot, or otherwise depends on
non-deterministic or incidental formatting rather than the observable behavior the fix
changes. (We reject such tasks rather than rewrite the upstream test.)

COMMIT SUBJECT: {subject}
ISSUE TITLE: {issue_title}
ISSUE LABELS: {labels}
DIFFSTAT: {diffstat}
CODE DIFF (truncated):
{code_diff}
TEST DIFF (the hidden grader -- judge its brittleness) (truncated):
{test_diff}
"""

P_COUP = """You check a benchmark task for SOLUTION COUPLING between its hidden test and
its reference fix, for the Zulip codebase. The concern: the test must not force a solver
to GUESS names or choices only the original author knew. Classify into one of three
verdicts; reply JSON
{"verdict": "clean"|"specifiable"|"coupled", "required_contract": ["..."], "reason": "..."}.

clean: the test checks behavior through interfaces that ALREADY EXIST at the base commit
(pre-existing APIs, user-visible outcomes). required_contract is [].

specifiable: the test binds to NEW names, but ONLY contract surface that a ticket
or design spec would legitimately dictate: a settings name, an API request/response
field, a function or module intended as public API, a CLI flag, a DOM id for a new UI
element, a user-facing message, or an operator-facing log/error phrase (tickets
routinely pin log wording for monitoring/alerting). List EVERY such name the test needs, with its meaning,
in required_contract (e.g. "the send-message API response gains a string field
`message_url`: absolute URL of the sent message"). Rule of thumb: if the solver were
handed these requirements in the brief, the test would grade correctness, not
name-guessing. Include units/sentinel semantics where the test asserts them. Phrase every
required_contract item as a PRODUCT requirement: never mention tests, stubs, mocks, or
test helpers (say "callers of X must ..." rather than "the test stubs X").

coupled: the test binds to INTERNAL implementation choices no reasonable spec would
dictate: private helper names or call signatures, mock/stub targets of internals,
internal data-structure field names, internal module layout the fix invents. This
cannot be cured by a brief; the task is dropped.

TEST DIFF (truncated):
{test_diff}
CODE DIFF (truncated):
{code_diff}
"""

P_F2P = """From this test diff for the Zulip codebase, name the test targets that the
change introduces or modifies, as dotted paths for `tools/test-backend`:
zerver.tests.test_module.ClassName.test_method (one per added/modified test method).
Reply JSON {"tests": ["..."], "reason": "..."}.

TEST DIFF:
{test_diff}
"""

P_PROB = """Write the work brief (problem statement) for a coding task on the open-source
Zulip codebase. An engineer receives ONLY your brief and a checkout of the code (no
issue number, no links, no git history). Reply JSON
{"sufficient": true|false, "problem_statement": "<markdown>", "why": "..."}.

Sources (combine; the issue may be thin or empty):
- The GitHub issue below.
- EXPECTED-BEHAVIOR EVIDENCE: the diff of the project's own regression test for this
  change. Use it ONLY to infer the observable behavior the change must produce, and
  write that as product requirements. Never reveal that this evidence is a test.
- INTERFACE REQUIREMENTS: names the implementation must expose (may be empty). Include
  every one in the brief under a heading "## Interface requirements". Keep names and
  semantics exact, but REPHRASE any item as a product requirement where needed -- the
  no-test-mention rule below overrides verbatim inclusion.

Rules:
- Describe the current behavior and the required behavior concretely enough that two
  engineers working independently would build compatible things.
- NEVER mention: issue/PR numbers, URLs, commit hashes or messages, author names,
  that a fix exists, or that tests exist or what they check ("the API must return X",
  never "the test expects X").
- Do not paste code from any fix. Quoting error output from the ISSUE is fine.
- Reply {"sufficient": false, "why": "..."} ONLY if even with all sources you cannot
  state a determinate, checkable outcome.

ISSUE TITLE: {issue_title}
ISSUE BODY:
{issue_body}
EXPECTED-BEHAVIOR EVIDENCE (truncated):
{test_diff}
INTERFACE REQUIREMENTS:
{contract}
"""

_TRUNC = {"code_diff": 8000, "test_diff": 9000, "issue_body": 6000}


def _fmt(template: str, **kw) -> str:
    # NOT str.format(): the templates contain literal JSON braces. Replace only
    # the known {placeholder} tokens.
    for k, v in kw.items():
        v = str(v)
        cap = _TRUNC.get(k)
        if cap and len(v) > cap:
            v = v[:cap] + "\n[...truncated...]"
        template = template.replace("{" + k + "}", v)
    return template


# ---- contamination tier ------------------------------------------------------------
def cohort_cutoff() -> tuple[str, list[str]]:
    """(max training_cutoff over active agents, agents missing a cutoff). Fail-loud
    upstream if the miss-list is non-empty and tiering is required."""
    cutoffs, missing = [], []
    if not AGENTS_META.exists():
        return "", ["<no agents-meta.jsonl>"]
    for line in AGENTS_META.read_text().splitlines():
        if not line.strip():
            continue
        a = json.loads(line)
        if a.get("status") == "RETIRED" or a.get("retired"):
            continue
        c = a.get("training_cutoff")
        (cutoffs if c else missing).append(c or a.get("agent_id", "?"))
    return (max(cutoffs) if cutoffs else "", missing)


def contamination_block(fix_date: str, issue_created: str | None) -> dict:
    cutoff, missing = cohort_cutoff()
    block = {"fix_public_at": fix_date, "fix_visibility_basis": "committer_date",
             "issue_created_at": issue_created,
             "cohort_cutoff_used": cutoff or None,
             "cutoff_buffer_days": CUTOFF_BUFFER_DAYS,
             "tier_computed_at": date.today().isoformat()}
    if not cutoff:
        block["tier"] = "UNKNOWN"
        block["tier_note"] = f"no training cutoffs recorded ({missing[:3]}...)"
        return block
    gate = (datetime.fromisoformat(cutoff) + timedelta(days=CUTOFF_BUFFER_DAYS)).date().isoformat()
    block["tier"] = "A" if fix_date > gate else "B"
    if issue_created and issue_created[:10] <= cutoff:
        block["issue_pre_cutoff"] = True
    return block


# ---- issue fetch -------------------------------------------------------------------
def fetch_issue(n: int) -> dict:
    r = subprocess.run(["gh", "api", f"repos/{GITHUB_REPO}/issues/{n}"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        if "404" in r.stderr or "Not Found" in r.stderr:
            raise Verdict("dropped", "issue_missing", f"issue #{n} 404s")
        scan_infra(r.stderr)
        raise InfraError(f"gh api issue {n} failed: {r.stderr[:200]}")
    issue = json.loads(r.stdout)
    if "pull_request" in issue:
        raise Verdict("dropped", "issue_is_pr", f"#{n} is a PR, not an issue")
    return issue


def issue_prose(body: str) -> str:
    body = re.sub(r"<!--.*?-->", "", body or "", flags=re.S)      # template boilerplate
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)              # images
    body = re.sub(r"https?://\S+", "", body)                      # links
    return body.strip()


# ---- f2p extraction ----------------------------------------------------------------
def extract_f2p_py(repo: Path, fix: str, test_files: list[str], test_diff: str) -> list[str]:
    added = set(re.findall(r"^\+\s*def (test_\w+)\(", test_diff, re.M))
    # modified-but-not-added tests: the @@ hunk context names the enclosing def
    added |= set(re.findall(r"^@@ .* def (test_\w+)\(", test_diff, re.M))
    targets = []
    for tf in test_files:
        if not tf.endswith(".py"):
            continue
        src = git(repo, "show", f"{fix}:{tf}").stdout
        mod = tf[:-3].replace("/", ".")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in added:
                        targets.append(f"{mod}.{node.name}.{item.name}")
    return sorted(set(targets))


def verify_f2p_against_ast(repo: Path, fix: str, targets: list[str]) -> list[str]:
    """Keep only targets whose module.Class.method actually exists at the fix commit."""
    ok = []
    for t in targets:
        parts = t.split(".")
        if len(parts) < 4:
            continue
        mod, cls, meth = ".".join(parts[:-2]), parts[-2], parts[-1]
        path = mod.replace(".", "/") + ".py"
        src = git(repo, "show", f"{fix}:{path}").stdout
        if not src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                if any(isinstance(i, ast.FunctionDef) and i.name == meth for i in node.body):
                    ok.append(t)
    return sorted(set(ok))


# ---- p2p selection -----------------------------------------------------------------
def select_p2p(repo: Path, base: str, code_files: list[str], lang: str,
               f2p: list[str]) -> list[str]:
    """Test modules of the code modules gold_code touches (existing at BASE), capped.
    Excludes any module already covered by f2p."""
    f2p_mods = {t.rsplit(".", 2)[0] for t in f2p if t.count(".") >= 2}
    out = []
    if lang == "py":
        for cf in code_files:
            stem = Path(cf).stem
            for cand in (f"zerver/tests/test_{stem}.py",):
                mod = cand[:-3].replace("/", ".")
                if mod in f2p_mods or mod in out:
                    continue
                if git(repo, "cat-file", "-e", f"{base}:{cand}").returncode == 0:
                    out.append(mod)
    else:
        f2p_files = set(f2p)                      # web f2p is a list of test file paths
        for cf in code_files:
            stem = Path(cf).stem.split(".")[0]
            cand = f"web/tests/{stem}.test.cjs"
            # a P2P file must NOT be an f2p file -- the gold_test patch adds the failing
            # test to the f2p file, so running it as P2P at base+gold_test would fail.
            if cand in f2p_files or cand in out:
                continue
            if git(repo, "cat-file", "-e", f"{base}:{cand}").returncode == 0:
                out.append(cand)
    return out[:P2P_CAP]


# ---- deterministic unsuitability pre-filters ---------------------------------------
def prefilter(files: list[str], code_files: list[str], subject: str) -> None:
    non_locale = [f for f in code_files if not f.startswith("locale/")]
    if not non_locale:
        raise Verdict("dropped", "i18n_churn", "code changes are locale/ only")
    if re.match(r"(?i)revert ", subject):
        raise Verdict("dropped", "revert", "revert commit")
    if any(f.startswith(("api_docs/", "help/")) for f in code_files) and \
       all(f.startswith(("api_docs/", "help/")) for f in code_files):
        raise Verdict("dropped", "docs_only", "docs-only change")


# ---- sanitization ------------------------------------------------------------------
def sanitize(statement: str, fix: str, issue_n: int) -> str:
    for sha in (fix, fix[:12], fix[:8]):
        statement = statement.replace(sha, "")
    statement = re.sub(r"(?i)\b(fixes|closes|resolves)?[: ]*#\d+\b", "", statement)
    statement = re.sub(r"https?://\S*(github\.com|zulip\.com|zulipchat\.com)\S*", "", statement)
    statement = statement.replace(f"#{issue_n}", "")
    if len(statement.strip()) < MIN_STATEMENT:
        raise ScriptError(f"problem statement shrank below {MIN_STATEMENT} chars after leak strip")
    return statement.strip()


# ---- artifact writers --------------------------------------------------------------
def write_instance(staging: Path, meta: dict, statement: str) -> None:
    mode = "backend" if meta["lang"] == "py" else "node"
    # Run fail_to_pass and pass_to_pass in SEPARATE verify commands (each is its own
    # zbench_verify.sh container = its own test-runner process), mirroring how
    # oracle_validate.py runs the two arms. A single combined process shares the node
    # require-cache / test-DB across files, so an f2p file that imports a module a p2p
    # file later mock_esm()s trips "too late to mock" and fails a P2P even for the gold
    # patch (the ZT-0e8d5603ef8d bug). Separate commands isolate the caches.
    def _verify_cmd(files):
        return (f'bash "${{ZBENCH_SCRIPTS:?export zbench-tasks/scripts dir}}"'
                f'/zbench_verify.sh {mode} {" ".join(files)}')
    test_cmds = [_verify_cmd(meta["fail_to_pass"])]
    if meta.get("pass_to_pass"):
        test_cmds.append(_verify_cmd(meta["pass_to_pass"]))
    inst = {
        "instance_id": f"zbench_{meta['task_id']}",
        "repo": GITHUB_REPO,
        "commit": meta["base_commit"],
        "problem_statement": statement,
        "languages": [meta["lang"]],
        "metadata": {
            "task_type": "zbench/patch",
            "language": meta["lang"],
            "issue": meta["issue"],
            "env_fingerprint": meta["env_fingerprint"],
            # inline text: portable, and _resolve_gold_patch already supports it
            "gold_test_patch": (staging / "gold_test.patch").read_text(),
            "fail_to_pass": meta["fail_to_pass"],
            "pass_to_pass": meta.get("pass_to_pass", []),
            "commands": {"build": [], "tests": test_cmds},
            "verify_timeout_sec": 1200,
        },
    }
    (staging / "instance.jsonl").write_text(json.dumps(inst) + "\n")


def write_card(staging: Path, meta: dict, screens: dict) -> None:
    lines = [f"# {meta['task_id']} -- {meta['summary']}", "",
             f"- lang: {meta['lang']}   issue: #{meta['issue']}   tier: "
             f"{meta.get('contamination', {}).get('tier', '?')}",
             f"- fix: {meta['source']['commit_url']}",
             f"- f2p: {', '.join(meta['fail_to_pass'])}",
             f"- p2p: {', '.join(meta.get('pass_to_pass', [])) or '(none)'}", ""]
    for name, res in screens.items():
        lines.append(f"## screen: {name}")
        lines.append(json.dumps(res, indent=2))
        lines.append("")
    (staging / "card.md").write_text("\n".join(lines))


# ---- the pipeline ------------------------------------------------------------------
def _promote(staging: Path, final: Path, task_id: str) -> None:
    """Publish a staged task dir, moving the ANSWER KEY out to zbench-tasks/solutions/.

    The oracle runs against `staging` and needs gold_code.patch in place, so the split
    happens here, at publish time, not at write time. config.gold_code_path() resolves
    either layout, so a corpus prepared before the split still validates.
    """
    gold = staging / "gold_code.patch"
    if gold.exists():
        dest = SOLUTIONS_DIR / task_id
        dest.mkdir(parents=True, exist_ok=True)
        os.replace(gold, dest / "gold_code.patch")
    os.rename(staging, final)


def prepare(fix_sha: str, repo: Path, tasks_dir: Path, run_oracle: bool,
            fast_oracle: bool, redo: bool = False) -> dict:
    r = git(repo, "rev-parse", "--verify", f"{fix_sha}^{{commit}}")
    if r.returncode != 0:
        raise ScriptError(f"unknown commit {fix_sha} in {repo}")
    fix = r.stdout.strip()
    task_id = f"ZT-{fix[:12]}"
    final = tasks_dir / task_id
    if final.exists():
        # --redo re-judges dropped/invalid candidates (screens/pipeline changed);
        # validated tasks are NEVER clobbered.
        prev_status = None
        if (final / "meta.json").exists():
            try:
                prev_status = json.loads((final / "meta.json").read_text()).get("curation_status")
            except (json.JSONDecodeError, OSError):
                pass
        if redo and prev_status in ("dropped", "invalid", "held"):
            shutil.rmtree(final)
        else:
            raise ScriptError(f"{final} already exists (status={prev_status}; "
                              "use --redo to re-judge dropped/invalid)")

    subject = git(repo, "log", "-1", "--format=%s", fix).stdout.strip()
    body = git(repo, "log", "-1", "--format=%B", fix).stdout
    fix_date = git(repo, "log", "-1", "--format=%cs", fix).stdout.strip()
    base = git(repo, "rev-parse", f"{fix}^").stdout.strip()

    # Staging exists from here on, so EVERY judged candidate leaves a record
    # (meta-only stub on drops) -- the ledger that lets batch runs skip re-judging.
    staging = Path(tempfile.mkdtemp(prefix=f"prep-{task_id}-", dir=str(tasks_dir)))
    screens: dict = {}
    lang, issue_n = "?", 0
    try:
        # 2: re-check the mining predicate
        # author provenance (defense-in-depth; mining already filters, but prepare_task
        # may be called directly): no bots / service accounts / AI-generated commits.
        aname, aemail = (git(repo, "show", "-s", "--format=%an%x1f%ae", fix).stdout.strip()
                         .split("\x1f") + ["", ""])[:2]
        if quality.excluded_author(aname, aemail):
            raise Verdict("dropped", "excluded_author", f"{aname} <{aemail}> is a bot/service account")
        if quality.has_ai_trailer(subject + "\n" + body):
            raise Verdict("dropped", "ai_generated", "commit has an AI co-author/generated trailer")
        m = FIXES_RE.search(subject + "\n" + body)
        if not m:
            raise Verdict("dropped", "no_issue_ref", "commit has no full `Fixes #N`")
        if FIXES_PARTIAL_RE.search(subject + "\n" + body):
            raise Verdict("dropped", "partial_fix", "`Fixes part of` -- issue over-describes")
        issue_n = int(m.group(1))
        files = [f for f in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
                                fix).stdout.splitlines() if f.strip()]
        if touches_migrations(files):
            raise Verdict("dropped", "touches_migrations", "fix touches migrations")
        if any(is_dep_file(f) for f in files):
            raise Verdict("dropped", "dep_change", "fix touches provision fingerprint files")
        kinds = {f: classify_file(f) for f in files}
        test_files = sorted(f for f, k in kinds.items() if k in ("py_test", "web_test"))
        code_files = sorted(f for f, k in kinds.items() if k in ("py_code", "web_code"))
        if not test_files:
            raise Verdict("dropped", "no_test", "no test file in the fix commit")
        if not code_files:
            raise Verdict("dropped", "test_only", "no code file in the fix commit")
        langs = {k.split("_")[0] for k in kinds.values() if k}
        if langs not in ({"py"}, {"web"}):
            raise Verdict("dropped", "mixed_lang", f"languages {sorted(langs)}")
        lang = langs.pop()

        # 3: scope gate
        if fix_date < MIN_COMMIT_DATE:
            raise Verdict("dropped", "out_of_scope", f"{fix_date} predates floor {MIN_COMMIT_DATE}")
        if git(repo, "merge-base", "--is-ancestor", fix, MAIN_REF).returncode != 0:
            raise Verdict("dropped", "out_of_scope", f"not an ancestor of {MAIN_REF}")

        prefilter(files, code_files, subject)

        # 6: issue (title+body only; thin issues allowed -- the brief can draw on
        # expected-behavior evidence from the gold test, see stage 10)
        issue = fetch_issue(issue_n)
        prose = issue_prose(issue.get("body") or "")

        # 4: patch split (headerless diffs). Test-support files (webhook fixtures, node
        # test helpers) ride with gold_test -- the hidden test cannot run without them.
        support_files = sorted(f for f in files if classify_support(f))
        code_diff = git(repo, "diff", base, fix, "--", *code_files, timeout=300).stdout
        test_diff = git(repo, "diff", base, fix, "--", *test_files, *support_files,
                        timeout=300).stdout
        (staging / "gold_code.patch").write_text(code_diff)
        (staging / "gold_test.patch").write_text(test_diff)

        # 5: deterministic scope gate ("few modules") -- before the expensive LLM screens
        sv = quality.scope_violation(code_files, code_diff)
        if sv:
            raise Verdict("dropped", "out_of_scope", sv)
        cx = quality.complexity(code_diff, f2p_count=len(test_files))

        diffstat = git(repo, "diff", "--stat", base, fix).stdout.splitlines()[-1].strip()
        labels = [lb["name"] for lb in issue.get("labels", [])]

        # 7: LLM screens -- the suitability screen now sees the actual TEST diff too, so it
        # can flag exact-string / snapshot / non-deterministic assertions (brittle-test
        # screen, Databricks best practice), not just the code diff.
        suit = pi_json(_fmt(P_SUIT, subject=subject, issue_title=issue.get("title", ""),
                            labels=labels, diffstat=diffstat, code_diff=code_diff,
                            test_diff=test_diff))
        screens["suitability"] = suit
        if suit.get("verdict") != "keep":
            raise Verdict("dropped", "unsuitable", suit.get("reason", "LLM screen"))
        coup = pi_json(_fmt(P_COUP, test_diff=test_diff, code_diff=code_diff))
        screens["coupling"] = coup
        if coup.get("verdict") not in ("clean", "specifiable"):
            raise Verdict("dropped", "symbol_coupling", coup.get("reason", "coupled test"))
        # specifiable: the test binds to new PUBLIC names; the brief must hand the solver
        # that contract (stage 10) so the test grades correctness, not name-guessing.
        contract = [str(c) for c in coup.get("required_contract") or []]
        if coup.get("verdict") == "specifiable" and not contract:
            raise Verdict("dropped", "symbol_coupling",
                          "specifiable but empty required_contract -- cannot brief the solver")

        # 8: f2p
        if lang == "py":
            f2p = extract_f2p_py(repo, fix, test_files, test_diff)
            if not f2p:
                llm = pi_json(_fmt(P_F2P, test_diff=test_diff))
                f2p = verify_f2p_against_ast(repo, fix, llm.get("tests", []))
                screens["f2p_llm_fallback"] = llm
            if not f2p:
                raise Verdict("dropped", "f2p_unenumerable", "no extractable test targets")
        else:
            f2p = test_files                      # node: file granularity

        # 9: p2p
        p2p = select_p2p(repo, base, code_files, lang, f2p)

        # env fingerprint
        fp = subprocess.run([sys.executable, str(HERE / "env_fingerprint.py"), base,
                             "--repo", str(repo)], capture_output=True, text=True)
        if fp.returncode != 0:
            raise ScriptError(f"env_fingerprint failed: {fp.stderr[:200]}")

        # 10: problem statement (issue + expected-behavior evidence + interface contract)
        prob = pi_json(_fmt(P_PROB, issue_title=issue.get("title", ""), issue_body=prose,
                            test_diff=test_diff,
                            contract="\n".join(f"- {c}" for c in contract) or "(none)"),
                       timeout=300)
        screens["statement"] = {k: prob.get(k) for k in ("sufficient", "why")}
        if not prob.get("sufficient", True) or not prob.get("problem_statement"):
            raise Verdict("dropped", "insufficient_spec",
                          f"no determinate outcome statable: {prob.get('why', '')[:120]}")
        statement = sanitize(prob["problem_statement"], fix, issue_n)
        if contract and "## Interface requirements" not in statement:
            # fallback append (LLM omitted the heading): raw contract items may carry
            # test-machinery wording the LLM path would have rephrased -- skip those.
            safe = [c for c in contract
                    if not re.search(r"\b(test|tests|stub|stubs|mock|mocks)\b", c, re.I)]
            if safe:
                statement += ("\n\n## Interface requirements\n"
                              + "\n".join(f"- {c}" for c in safe))

        meta = {
            "task_id": task_id, "curation_status": "held", "curation_stage": "auto_prepared",
            "verdict": "pending_oracle", "reason_code": "pending_oracle", "reason": "",
            "summary": subject, "type": "bug" if "bug" in [l.lower() for l in labels] else
                       ("feature" if any("feature" in l.lower() or "enhancement" in l.lower()
                                         for l in labels) else "other"),
            "lang": lang, "issue": issue_n,
            "fix_commit": fix, "base_commit": base,
            "env_fingerprint": fp.stdout.strip(),
            "fail_to_pass": f2p, "pass_to_pass": p2p,
            "complexity": cx,
            "interface_requirements": contract,
            "statement_inputs": {"issue_prose_chars": len(prose),
                                 "coupling_verdict": coup.get("verdict")},
            "author": {"name": aname, "email": aemail, "date": fix_date},
            "contamination": contamination_block(fix_date, issue.get("created_at")),
            "source": {"commit_url": f"https://github.com/{GITHUB_REPO}/commit/{fix}",
                       "issue_url": f"https://github.com/{GITHUB_REPO}/issues/{issue_n}"},
        }
        (staging / "problem_statement.md").write_text(statement + "\n")
        write_instance(staging, meta, statement)
        write_card(staging, meta, screens)

        # 11: oracle
        if run_oracle:
            (staging / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
            cmd = [sys.executable, str(HERE / "oracle_validate.py"), "--task-dir", str(staging),
                   "--repo", str(repo), "--json"]
            if fast_oracle:
                cmd.append("--fast")
            orc = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
            if orc.returncode == 75:
                raise InfraError(f"oracle infra: {orc.stderr[-300:]}")
            if orc.returncode == 70:
                raise ScriptError(f"oracle error: {orc.stderr[-300:]}")
            try:
                ores = json.loads(orc.stdout)
            except json.JSONDecodeError:
                raise ScriptError(f"oracle output unparseable: {orc.stdout[:200]}")
            meta["review"] = {"oracle": ores}
            if ores["verdict"] == "VALID":
                meta.update(curation_status="validated", curation_stage="oracle_validated",
                            verdict="validated", reason_code="oracle_validated",
                            reason="flip + P2P green (flake-gated)",
                            flake_check=ores.get("flake_check"))
            elif ores["verdict"] == "UNENUMERABLE":
                meta.update(curation_status="dropped", verdict="dropped",
                            reason_code="oracle_not_enumerable", reason=ores.get("why", ""))
            else:
                meta.update(curation_status="invalid", verdict="invalid",
                            reason_code="oracle_base_passed" if ores.get("code") == 2
                            else "oracle_invalid", reason=ores.get("why", ""))
        (staging / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        _promote(staging, final, task_id)
        return meta
    except Verdict as v:
        # terminal drop: record the judgment (meta-only stub; gold patches kept if split)
        meta = {"task_id": task_id, "curation_status": v.status, "curation_stage": "auto_prepared",
                "verdict": v.status, "reason_code": v.reason_code, "reason": v.reason,
                "summary": subject, "lang": lang, "issue": issue_n,
                "fix_commit": fix, "base_commit": base,
                "source": {"commit_url": f"https://github.com/{GITHUB_REPO}/commit/{fix}",
                           "issue_url": f"https://github.com/{GITHUB_REPO}/issues/{issue_n}"}}
        for f in staging.iterdir():
            if f.name not in ("gold_code.patch", "gold_test.patch"):
                f.unlink()
        (staging / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        _promote(staging, final, task_id)
        return meta
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("fix_sha")
    ap.add_argument("--repo", default=str(ZULIP_REPO))
    ap.add_argument("--tasks-dir", default=str(TASKS_DIR_DEFAULT))
    ap.add_argument("--no-oracle", action="store_true")
    ap.add_argument("--fast-oracle", action="store_true", help="1 oracle run per arm (dev only)")
    ap.add_argument("--redo", action="store_true",
                    help="re-judge an existing dropped/invalid/held candidate (never validated)")
    a = ap.parse_args()
    tasks_dir = Path(a.tasks_dir)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    try:
        meta = prepare(a.fix_sha, Path(a.repo).expanduser(), tasks_dir,
                       run_oracle=not a.no_oracle, fast_oracle=a.fast_oracle, redo=a.redo)
    except InfraError as exc:
        print(f"INFRA: {exc}", file=sys.stderr)
        return 75
    except ScriptError as exc:
        print(f"SCRIPT-ERROR: {exc}", file=sys.stderr)
        return 70
    print(f"{meta['task_id']}: {meta['curation_status']} ({meta.get('reason_code', '')}) "
          f"tier={meta.get('contamination', {}).get('tier', '-')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
