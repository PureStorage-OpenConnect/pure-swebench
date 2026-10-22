#!/usr/bin/env python3
"""Mine Zulip bugfix commits that can become zbench tasks. Pure git-log read; no
network, no credentials.

A candidate is a non-merge commit on MAIN_REF such that ALL of:
  1. its message carries a FULL issue reference (`Fixes #N` / `Fixes: #N`) --
     `Fixes part of #N` is rejected (the issue over-describes the hidden test);
  2. it touches >= 1 test file AND >= 1 code file (config.classify_file);
  3. it is single-language: py or web (mixed dropped in v1);
  4. it touches no `**/migrations/**` file;
  5. it touches no dependency-manifest file (config.is_dep_file) -- the grading
     image is fingerprinted at base and must stay valid for the patched tree.

Programmatic: mine(repo, revrange) yields candidate dicts.
CLI: mine_candidates.py [REPO] [--since DATE] [--until DATE] [--stats]

Also excludes bot/service-account and AI-generated (Co-Authored-By: Claude/GPT/...)
commits (quality.excluded_author / has_ai_trailer) -- see docs/benchmark-best-practices.md.

Measured baseline (2026-08-13): the Fixes-#+tests+code predicate matches ~133 commits
since 2026-01-01 before the author/migrations/dep/mixed screens; a large divergence from
that order of magnitude means the predicate broke.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quality  # noqa: E402
from config import (FIXES_PARTIAL_RE, FIXES_RE, MAIN_REF, MIN_COMMIT_DATE,  # noqa: E402
                    ZULIP_REPO, classify_file, is_dep_file, touches_migrations)

_FIELD, _REC = "\x1f", "\x1e"


def _log(repo: Path, since: str, until: str | None):
    fmt = f"%H{_FIELD}%cs{_FIELD}%an{_FIELD}%ae{_FIELD}%s{_FIELD}%B{_REC}"
    cmd = ["git", "-C", str(repo), "log", MAIN_REF, "--no-merges",
           f"--since={since}", f"--format={fmt}"]
    if until:
        cmd.append(f"--until={until}")
    head = subprocess.run(cmd, capture_output=True, text=True)
    if head.returncode != 0:
        sys.exit(f"mine: git log failed in {repo}: {head.stderr.strip()[:200]}")
    return head.stdout


def _files_of(repo: Path, sha: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(repo), "diff-tree", "--no-commit-id",
                        "--name-only", "-r", sha], capture_output=True, text=True)
    return [f for f in r.stdout.splitlines() if f.strip()]


def mine(repo: Path | None = None, since: str | None = None, until: str | None = None,
         stats: Counter | None = None):
    """Yield candidate dicts: {hash, sha12, parent, date, issue, lang,
    code_files, test_files, subject}."""
    repo = Path(repo or ZULIP_REPO).expanduser()
    since = since or MIN_COMMIT_DATE
    stats = stats if stats is not None else Counter()
    for rec in _log(repo, since, until).split(_REC):
        rec = rec.strip("\n")
        if not rec.strip():
            continue
        sha, date, aname, aemail, subject, body = (rec.split(_FIELD, 5) + [""] * 6)[:6]
        sha = sha.strip()
        stats["commits"] += 1
        # Author provenance (Databricks: exclude bots / service accounts / AI-generated).
        # Zulip's own devs use Claude, so Co-Authored-By: Claude trailers are common and
        # a real contamination vector -- exclude them.
        areason = quality.excluded_author(aname, aemail)
        if areason:
            stats["excluded_author"] += 1
            continue
        if quality.has_ai_trailer(subject + "\n" + body):
            stats["ai_generated"] += 1
            continue
        m = FIXES_RE.search(subject + "\n" + body)
        if not m:
            stats["no_fixes_ref"] += 1
            continue
        if FIXES_PARTIAL_RE.search(subject + "\n" + body):
            stats["partial_fix"] += 1
            continue
        files = _files_of(repo, sha)
        if touches_migrations(files):
            stats["touches_migrations"] += 1
            continue
        if any(is_dep_file(f) for f in files):
            stats["dep_change"] += 1
            continue
        kinds = {f: classify_file(f) for f in files}
        tests = [f for f, k in kinds.items() if k in ("py_test", "web_test")]
        code = [f for f, k in kinds.items() if k in ("py_code", "web_code")]
        if not tests or not code:
            stats["no_test_or_no_code"] += 1
            continue
        langs = {k.split("_")[0] for k in kinds.values() if k}
        if langs == {"py"}:
            lang = "py"
        elif langs == {"web"}:
            lang = "web"
        else:
            stats["mixed_lang"] += 1
            continue
        parent = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{sha}^"],
                                capture_output=True, text=True).stdout.strip()
        stats[f"candidate_{lang}"] += 1
        yield {"hash": sha, "sha12": sha[:12], "parent": parent, "date": date,
               "issue": int(m.group(1)), "lang": lang,
               "code_files": sorted(code), "test_files": sorted(tests),
               "subject": subject.strip(),
               "author": {"name": aname, "email": aemail, "date": date}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default=str(ZULIP_REPO))
    ap.add_argument("--since", default=MIN_COMMIT_DATE)
    ap.add_argument("--until", default=None)
    ap.add_argument("--stats", action="store_true", help="print the rejection funnel to stderr")
    a = ap.parse_args()
    stats: Counter = Counter()
    n = 0
    for c in mine(Path(a.repo), a.since, a.until, stats):
        n += 1
        print(f"{c['sha12']}  {c['date']}  #{c['issue']:<6} {c['lang']:3} "
              f"{len(c['code_files'])}c/{len(c['test_files'])}t  {c['subject'][:70]}")
    print(f"total: {n} candidates", file=sys.stderr)
    if a.stats:
        for k, v in stats.most_common():
            print(f"  {k}: {v}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
