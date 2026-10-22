#!/usr/bin/env python3
"""Human-review gate: the ranked set requires a reviewer stamp on top of oracle-valid.

Run: python3 zbench/tests/test_review_gate.py   (asserts; exit 0 = pass)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "zbench-tasks"))
import corpus  # noqa: E402


def _mk(tmp: Path, task_id: str, status: str, reviewed_by=None) -> None:
    d = tmp / task_id
    d.mkdir(parents=True)
    meta = {"task_id": task_id, "curation_status": status, "lang": "py", "base_commit": "x"}
    if reviewed_by:
        meta["review"] = {"reviewed_by": reviewed_by, "review_decision": "approved"}
    (d / "meta.json").write_text(json.dumps(meta))


def test_ranked_requires_review():
    tmp = Path(tempfile.mkdtemp())
    _mk(tmp, "ZT-aaa", "validated", reviewed_by="alice")   # oracle-valid + reviewed
    _mk(tmp, "ZT-bbb", "validated")                        # oracle-valid, UNreviewed
    _mk(tmp, "ZT-ccc", "held")                             # not even oracle-valid

    validated = set(corpus.validated_ids(tasks_dir=tmp))
    ranked = set(corpus.ranked_ids(tasks_dir=tmp))

    # candidate set = every oracle-valid task (reviewed or not)
    assert validated == {"ZT-aaa", "ZT-bbb"}, validated
    # ranked set = oracle-valid AND reviewed only
    assert ranked == {"ZT-aaa"}, ranked
    assert "ZT-bbb" not in ranked, "unreviewed task must not rank"


def test_reviewed_flag_in_rows():
    tmp = Path(tempfile.mkdtemp())
    _mk(tmp, "ZT-aaa", "validated", reviewed_by="alice")
    _mk(tmp, "ZT-bbb", "validated")
    rows = {r["id"]: r for r in corpus.load_corpus("validated", tasks_dir=tmp)}
    assert rows["ZT-aaa"]["reviewed"] is True
    assert rows["ZT-bbb"]["reviewed"] is False


def main() -> int:
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
    print(f"review-gate: {len(fns)}/{len(fns)} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
