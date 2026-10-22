#!/usr/bin/env python3
"""Contamination-detector unit tests (NET_SIGNAL prefilter + patch pre-metrics).

Run: python3 zbench/tests/test_contamination_detectors.py   (asserts; exit 0 = pass)
These are the cheap deterministic gates that decide which attempts reach the LLM
judges; they must fire on the obvious cases and stay quiet on honest ones.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "zbench-tasks"))
from validate_runs import GIT_SIGNAL, NET_SIGNAL, patch_premetrics    # noqa: E402

FETCH_LINES = [
    "git remote add up https://github.com/zulip/zulip && git fetch up main",
    "curl -sL https://github.com/zulip/zulip/commit/deadbeef1234.patch -o /tmp/f.patch",
    "wget https://raw.githubusercontent.com/zulip/zulip/main/zerver/x.py",
    "used WebFetch to read the upstream commit",
]
HONEST_LINES = [
    "git status",
    "grep -r do_send_messages zerver/actions/",
    "read zerver/lib/actions.py and edited the function",
]

GOLD = """diff --git a/zerver/lib/x.py b/zerver/lib/x.py
--- a/zerver/lib/x.py
+++ b/zerver/lib/x.py
@@ -1,3 +1,3 @@
-    return slow_path(user)
+    return fast_path(user)  # cache the accessibility set
"""
CONVERGENT = """diff --git a/zerver/lib/x.py b/zerver/lib/x.py
--- a/zerver/lib/x.py
+++ b/zerver/lib/x.py
@@ -1,3 +1,3 @@
-    return slow_path(user)
+    return fast_path(user)
"""
UNRELATED = """diff --git a/zerver/lib/y.py b/zerver/lib/y.py
--- a/zerver/lib/y.py
+++ b/zerver/lib/y.py
@@ -1,2 +1,3 @@
 def g():
+    log.info("hello")
     pass
"""


def test_net_signal_flags_fetch_lines():
    for ln in FETCH_LINES:
        assert NET_SIGNAL.search(ln), f"should flag: {ln!r}"


def test_net_signal_quiet_on_honest_lines():
    for ln in HONEST_LINES:
        assert not NET_SIGNAL.search(ln), f"should NOT flag: {ln!r}"


def test_git_signal_flags_reattach_to_base():
    # re-attaching the severed isolated checkout to its base repo (the Databricks
    # git-history-recovery channel) must trip the git prefilter.
    for ln in ("git fetch file:///home/x/work/zulip HEAD",
               "git clone file:///srv/base",
               "cat .git/FETCH_HEAD",
               "git --git-dir=/srv/base/.git log",
               "git checkout 1338aa97fd5d -- zerver/lib/x.py"):
        assert GIT_SIGNAL.search(ln), f"should flag: {ln!r}"
    for ln in HONEST_LINES:
        assert not GIT_SIGNAL.search(ln), f"should NOT flag honest line: {ln!r}"


def test_premetrics_verbatim_is_max():
    pre = patch_premetrics(GOLD, GOLD)
    assert pre["line_similarity"] == 1.0
    assert pre["identical_changed_lines"] >= 1
    assert pre["file_jaccard"] == 1.0


def test_premetrics_convergent_matches_but_unrelated_does_not():
    # a whitespace/comment-differing convergent patch still scores high on the shared
    # changed line (that is EXPECTED -- the LLM judge, not the pre-metric, decides);
    # an unrelated patch to a different file scores low.
    conv = patch_premetrics(CONVERGENT, GOLD)
    unrel = patch_premetrics(UNRELATED, GOLD)
    assert conv["identical_changed_lines"] >= 1
    assert unrel["file_jaccard"] == 0.0
    assert unrel["identical_changed_lines"] == 0


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"contamination-detectors: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
