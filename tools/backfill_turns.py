#!/usr/bin/env python3
"""Backfill the attempt.turns column from each attempt's durable transcript blob.

A "turn" = one model round-trip. It is captured live by the adapters now, but this tool is
the AUTHORITATIVE populator for history (and can be re-run after any batch, like
tools/backfill_tokens.py). The turn count is read PER HARNESS from its own transcript, so
the number means the same thing the harness itself reports:

  * claude  (blobs/attempt/<id>/rawcli.txt, stream-json): the final `result` event's
            `num_turns` -- Claude Code's own turn count.
  * pi      (blobs/attempt/<id>/session.jsonl): count of assistant messages that carry a
            `usage` block (one usage-bearing assistant message == one model round-trip).
  * pi      (rawcli.txt pi --mode json stream): count of assistant `message_end` events.
  * codex   (rawcli.txt): count of `turn.completed` events (fallback `turn.started`). A
            codex turn wraps many tool calls, so it is a COARSER unit than pi's per-message
            count -- compare turns WITHIN a harness, not across.

turns is a DISPLAY effort metric, never part of ranking. Idempotent; DRY-RUN by default
(pass --apply to write; --apply backs up the DB first).

Usage:
  tools/backfill_turns.py                    # dry-run, missing-only (turns IS NULL)
  tools/backfill_turns.py --apply            # write missing-only
  tools/backfill_turns.py --recompute-all    # dry-run, recount every attempt
  tools/backfill_turns.py --recompute-all --apply
"""
from __future__ import annotations

import argparse
import glob
import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
DEF_DB = DOCS / "bench-db" / "bench.db"


def _iter_json_lines(path: Path):
    with path.open(errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _turns_from_pi_session(path: Path) -> int | None:
    """pi native session: count assistant messages bearing usage (== model round-trips)."""
    n = 0
    for d in _iter_json_lines(path):
        m = d.get("message") if isinstance(d, dict) else None
        if isinstance(m, dict) and m.get("role") == "assistant" and m.get("usage"):
            n += 1
    return n or None


# codex wraps a WHOLE task in a single `turn`, so turn.* is always 1 -- useless as a
# round-trip count. Its model round-trips are the ACTION items it completes (one model
# response -> one command/tool call or a text message). Exclude planning + byproduct
# item types that are NOT a distinct model round-trip.
_CODEX_NON_TURN_ITEMS = {"todo_list", "file_change", "reasoning"}


def _turns_from_rawcli(path: Path) -> int | None:
    """Detect the stream dialect and count model round-trips: claude result.num_turns,
    codex action-item count (item.completed minus planning/byproduct), or pi-stream
    assistant message_end events."""
    claude_num_turns = None
    codex_items = codex_turn_events = 0
    pi_message_ends = 0
    for d in _iter_json_lines(path):
        if not isinstance(d, dict):
            continue
        t = d.get("type") or (d.get("msg") or {}).get("type")
        if t == "result" and d.get("num_turns") is not None:
            claude_num_turns = d.get("num_turns")          # claude stream-json
        elif t == "item.completed":                         # codex action item
            it = (d.get("item") or {}).get("type") if isinstance(d.get("item"), dict) else None
            if it not in _CODEX_NON_TURN_ITEMS:
                codex_items += 1
        elif t in ("turn.completed", "turn.started"):
            codex_turn_events += 1                          # codex (thread-level; fallback only)
        elif t == "message_end":
            msg = d.get("message") or {}
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                pi_message_ends += 1                        # pi --mode json stream
    if claude_num_turns is not None:
        return int(claude_num_turns)
    if codex_items:
        return codex_items
    if pi_message_ends:
        return pi_message_ends
    if codex_turn_events:                                   # a run that died before any item
        return codex_turn_events
    return None


def _turns_for(db_root: Path, evaluation_id: str) -> int | None:
    """Best transcript turn count for one attempt, or None if no transcript / not countable."""
    bundle = db_root / "blobs" / "attempt" / evaluation_id
    # pi native session first (richest); then any rawcli stream (claude / codex / pi-stream)
    sess = bundle / "session.jsonl"
    if sess.is_file():
        t = _turns_from_pi_session(sess)
        if t is not None:
            return t
    for raw in sorted(glob.glob(str(bundle / "*rawcli*"))) + sorted(glob.glob(str(bundle / "*session*.jsonl"))):
        t = _turns_from_rawcli(Path(raw))
        if t is not None:
            return t
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(DEF_DB))
    ap.add_argument("--apply", action="store_true", help="write updates (default: dry-run)")
    ap.add_argument("--recompute-all", action="store_true",
                    help="recount every attempt (default: only rows where turns IS NULL)")
    args = ap.parse_args()

    db = Path(args.db)
    db_root = db.resolve().parent
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    # make sure the column exists (a read tool never ALTERs; the writer normally does)
    acols = {r[1] for r in conn.execute("PRAGMA table_info(attempt)")}
    if "turns" not in acols:
        if not args.apply:
            print("attempt.turns column does not exist yet; --apply will add it.")
        else:
            conn.execute("ALTER TABLE attempt ADD COLUMN turns INTEGER")
            conn.commit()

    where = "" if args.recompute_all else "WHERE turns IS NULL"
    rows = conn.execute(
        f"SELECT evaluation_id, config_id, task_id, turns FROM attempt {where}").fetchall()

    to_write, no_transcript, unchanged = [], 0, 0
    for r in rows:
        t = _turns_for(db_root, r["evaluation_id"])
        if t is None:
            no_transcript += 1
            continue
        if r["turns"] is not None and int(r["turns"]) == int(t):
            unchanged += 1
            continue
        to_write.append((r, t))

    print(f"candidate attempts: {len(rows)}  (mode: {'recompute-all' if args.recompute_all else 'missing-only'})")
    print(f"  to write (counted):        {len(to_write)}")
    print(f"  already correct:           {unchanged}")
    print(f"  no countable transcript:   {no_transcript}")

    if not args.apply:
        print("\nDRY-RUN. Sample (first 12):")
        for r, t in to_write[:12]:
            print(f"  {r['config_id']:32} {r['task_id']:14} -> turns={t}")
        print("\nRe-run with --apply to write.")
        return 0

    import shutil
    from datetime import datetime, timezone
    bak = db.with_suffix(db.suffix + ".bak-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    shutil.copy2(db, bak)
    print(f"backed up DB -> {bak}")
    for r, t in to_write:
        conn.execute("UPDATE attempt SET turns=? WHERE evaluation_id=?", (int(t), r["evaluation_id"]))
    conn.commit()
    print(f"\nAPPLIED: wrote turns for {len(to_write)} attempts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
