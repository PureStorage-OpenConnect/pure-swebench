#!/usr/bin/env python3
"""Render agent transcripts using pi's (MIT) client-side export renderer.

We reuse pi's vendored export template (tools/vendor_pi_export/) and produce the
`sessionData` JSON it expects ({header, entries, leafId, ...}) ourselves -- so
there is NO pi CLI / Node dependency at serve time. Three inputs are supported,
all mapped to pi session `entries`:

  1. pi NATIVE session  (data/io_logs/<run>/pi__*__session__*.jsonl) -- lines
     already ARE entries; load as-is (trivial, lossless).
  2. pi --mode json stream (legacy pi__*rawcli*.txt) -- near 1:1 transcode.
  3. claude stream-json (claude__*rawcli*.txt) -- moderate transcode.

Format is auto-detected from the first JSON line.

CLI:  python3 transcript_view.py <input.jsonl|txt> [out.html]
Lib:  html = render_file(path)     # returns a self-contained HTML string
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor_pi_export"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _iter_json_lines(path):
    with open(path, "r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _now():
    return datetime.now(timezone.utc).isoformat()


_PI_STREAM_MARKERS = {"agent_start", "turn_start", "message_start", "message_update",
                      "message_end", "turn_end", "tool_execution_start",
                      "tool_execution_update", "tool_execution_end", "agent_end",
                      "agent_settled"}
_CLAUDE_MARKERS = {"assistant", "user", "result", "system"}


def detect_format(path, scan=60):
    """Return 'pi_session' | 'pi_stream' | 'claude_stream' | 'unknown'.

    A pi NATIVE session and a pi ``--mode json`` STREAM both start with
    ``{type:session, version:3}``, so we must scan beyond line 1: the stream
    carries message_start/update/tool_execution_* events, the native session
    carries ``type:"message"`` entries.
    """
    types = []
    has_message_entry = False
    for i, e in enumerate(_iter_json_lines(path)):
        t = e.get("type")
        types.append(t)
        if t == "message" and isinstance(e.get("message"), dict):
            has_message_entry = True
        if i + 1 >= scan:
            break
    tset = set(types)
    if tset & _PI_STREAM_MARKERS:
        return "pi_stream"
    if has_message_entry and (types[:1] == ["session"] or "message" in tset):
        return "pi_session"
    if tset & _CLAUDE_MARKERS:
        return "claude_stream"
    return "unknown"


def _chain(entries):
    """Assign a linear id/parentId chain to a list of message dicts."""
    prev = None
    for e in entries:
        e.setdefault("id", uuid.uuid4().hex)
        e["parentId"] = prev
        e.setdefault("timestamp", _now())
        prev = e["id"]
    return entries[-1]["id"] if entries else None


# --------------------------------------------------------------------------
# loaders / transcoders -> pi sessionData
# --------------------------------------------------------------------------
def load_pi_session(path):
    """Native pi session file: lines are already entries. Lossless."""
    header, entries = None, []
    for e in _iter_json_lines(path):
        if e.get("type") == "session" and header is None:
            header = e
        else:
            entries.append(e)
    leaf = None
    for e in entries:
        if e.get("type") == "message":
            leaf = e.get("id", leaf)
    if header is None:
        header = {"type": "session", "version": 3, "id": uuid.uuid4().hex,
                  "timestamp": _now(), "cwd": ""}
    return {"header": header, "entries": entries, "leafId": leaf}


def transcode_pi_stream(path):
    """pi --mode json event stream -> pi entries (use *_end complete events)."""
    entries = []
    tool_names = {}
    for e in _iter_json_lines(path):
        t = e.get("type")
        if t == "message_end":
            m = e.get("message") or {}
            role = m.get("role")
            if role in ("user", "assistant"):
                entries.append({"type": "message", "message": m})
                for b in (m.get("content") or []):
                    if isinstance(b, dict) and b.get("type") == "toolCall":
                        tool_names[b.get("id")] = b.get("name")
        elif t == "tool_execution_end":
            cid = e.get("toolCallId")
            entries.append({"type": "message", "message": {
                "role": "toolResult", "toolCallId": cid,
                "toolName": e.get("toolName") or tool_names.get(cid, ""),
                "content": (e.get("result") or {}).get("content")
                           or [{"type": "text", "text": json.dumps(e.get("result"))}],
                "isError": bool((e.get("result") or {}).get("isError")),
            }})
    leaf = _chain(entries)
    return {"header": {"type": "session", "version": 3, "id": uuid.uuid4().hex,
                       "timestamp": _now(), "cwd": ""},
            "entries": entries, "leafId": leaf}


def transcode_claude_stream(path):
    """claude --output-format stream-json -> pi entries.

    assistant.content: text/thinking/tool_use  -> text/thinking/toolCall
    user.content:      tool_result             -> role:toolResult entries
    """
    entries = []
    for e in _iter_json_lines(path):
        t = e.get("type")
        if t == "assistant":
            m = e.get("message") or {}
            blocks = []
            for b in (m.get("content") or []):
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    blocks.append({"type": "text", "text": b.get("text", "")})
                elif bt == "thinking":
                    blocks.append({"type": "thinking", "thinking": b.get("thinking", ""),
                                   "thinkingSignature": b.get("signature", "")})
                elif bt == "tool_use":
                    blocks.append({"type": "toolCall", "id": b.get("id"),
                                   "name": b.get("name"), "arguments": b.get("input") or {}})
            if blocks:
                entries.append({"type": "message", "message": {
                    "role": "assistant", "content": blocks,
                    "model": m.get("model"), "usage": m.get("usage")}})
        elif t == "user":
            m = e.get("message") or {}
            content = m.get("content")
            # user turns are either the initial prompt (str/text) or tool_result blocks
            if isinstance(content, str):
                entries.append({"type": "message", "message": {
                    "role": "user", "content": [{"type": "text", "text": content}]}})
            else:
                for b in (content or []):
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        c = b.get("content")
                        if isinstance(c, str):
                            c = [{"type": "text", "text": c}]
                        elif isinstance(c, list):
                            c = [{"type": "text", "text": x.get("text", "")} if isinstance(x, dict) else
                                 {"type": "text", "text": str(x)} for x in c]
                        else:
                            c = [{"type": "text", "text": str(c)}]
                        entries.append({"type": "message", "message": {
                            "role": "toolResult", "toolCallId": b.get("tool_use_id"),
                            "toolName": "", "content": c,
                            "isError": bool(b.get("is_error"))}})
                    elif b.get("type") == "text":
                        entries.append({"type": "message", "message": {
                            "role": "user", "content": [{"type": "text", "text": b.get("text", "")}]}})
    leaf = _chain(entries)
    return {"header": {"type": "session", "version": 3, "id": uuid.uuid4().hex,
                       "timestamp": _now(), "cwd": ""},
            "entries": entries, "leafId": leaf}


def build_session_data(path):
    fmt = detect_format(path)
    if fmt == "pi_session":
        return fmt, load_pi_session(path)
    if fmt == "pi_stream":
        return fmt, transcode_pi_stream(path)
    if fmt == "claude_stream":
        return fmt, transcode_claude_stream(path)
    raise ValueError(f"unrecognized transcript format for {path}")


# --------------------------------------------------------------------------
# render (fill vendored pi template)
# --------------------------------------------------------------------------
def render_html(session_data):
    tpl = (VENDOR / "template.html").read_text()
    css = (VENDOR / "template.rendered.css").read_text()
    js = (VENDOR / "template.js").read_text()
    marked = (VENDOR / "vendor" / "marked.min.js").read_text()
    hljs = (VENDOR / "vendor" / "highlight.min.js").read_text()
    b64 = base64.b64encode(json.dumps(session_data).encode()).decode()
    # order matters: JS/marked/hljs may contain '{{...}}'-like text? they don't,
    # but do CSS first then the big blobs, replacing each placeholder once.
    out = tpl.replace("{{CSS}}", css)
    out = out.replace("{{SESSION_DATA}}", b64)
    out = out.replace("{{MARKED_JS}}", marked)
    out = out.replace("{{HIGHLIGHT_JS}}", hljs)
    out = out.replace("{{JS}}", js)
    return out


def render_file(path):
    fmt, sd = build_session_data(path)
    return render_html(sd)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    inp = sys.argv[1]
    fmt, sd = build_session_data(inp)
    html = render_html(sd)
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/transcript.html"
    Path(out).write_text(html)
    print(f"format={fmt}  entries={len(sd['entries'])}  leafId={sd['leafId']}")
    print(f"wrote {out} ({len(html):,} bytes)")
