#!/usr/bin/env python3
"""Localhost proxy so OpenAI-compatible clients can reach the Azure AI Foundry gateway.

Two problems this solves:
  1. AUTH -- the gateway wants an Azure AD bearer token that expires hourly; tools like
     the codex CLI only know how to send one static api key. The proxy re-mints the
     token via `az account get-access-token` whenever it is <10 min from expiry and
     injects it on every forwarded request.
  2. WIRE API -- codex CLI >= ~0.12x removed chat-completions support entirely
     (github.com/openai/codex/discussions/7782): it can only speak the Responses wire
     API (POST <base_url>/responses, streaming SSE). The fireworks route only speaks
     chat completions, so there POST /fireworks/[v1/]responses is TRANSLATED into a
     chat/completions call and the reply re-emitted as Responses-API SSE events (or a
     Responses JSON object when the client did not ask to stream). The openai route
     serves the Responses API natively at /openai/v1/responses, so POST
     /openai/[v1/]responses passes straight through (SSE untouched, no api-version) --
     required for gpt-5.3-codex, which rejects chat completions entirely. Every other
     path is a plain passthrough.

Gateway facts (verified live 2026-08-14): fireworks chat completions take
api-version=2024-05-01-preview; openai chat completions are served at
/openai/v1/chat/completions -- the v1 is part of the UPSTREAM PATH (flat
/openai/chat/completions is 404 whatever the api-version; the query param is optional
there, "v1" accepted); /openai/v1/responses needs no api-version.
FW-DeepSeek-V4-Flash is not deployed (404 DeploymentNotFound).

How to run:
  export GATEWAY_URL=https://<your-foundry-gateway>          # required
  python3 tools/foundry_gateway_proxy.py                     # serve on 127.0.0.1:8788
  # codex CLI (Responses wire API; fireworks is translated, openai is native):
  #   OPENAI_API_KEY=unused codex exec -m FW-DeepSeek-V4-Pro \
  #     -c model_provider=zbench -c model_providers.zbench.name=zbench \
  #     -c 'model_providers.zbench.base_url="http://127.0.0.1:8788/fireworks/v1"' \
  #     -c model_providers.zbench.env_key=OPENAI_API_KEY \
  #     -c 'model_providers.zbench.wire_api="responses"' "your prompt"
  #   (gpt models: base_url="http://127.0.0.1:8788/openai/v1", -m gpt-5.6-sol etc.)
  # curl sanity check (plain passthrough path):
  #   curl -s http://127.0.0.1:8788/fireworks/v1/chat/completions -d '{...}'
  python3 tools/foundry_gateway_proxy.py --smoke             # probe gateway models
  python3 tools/foundry_gateway_proxy.py --self-test         # offline pipe test
  python3 tools/foundry_gateway_proxy.py --e2e-test          # offline test w/ real codex

URL mapping: /<route>/v1/<rest> and /<route>/<rest> (route in ROUTES) both proxy to
$GATEWAY_URL/<prefix>/<rest>?api-version=<ver> (prefix per UPSTREAM_PREFIX: fireworks
-> fireworks, openai -> openai/v1), except <rest> == "responses": on routes
in NATIVE_RESPONSES it passes through to the native upstream path (no api-version),
elsewhere it is translated to $GATEWAY_URL/<route>/chat/completions. The client's
Authorization header (if any) is replaced with a fresh gateway token.

Env knobs:
  GATEWAY_URL                          gateway base URL (required except offline tests)
  ZBENCH_FOUNDRY_TOKEN_CMD             override the az token command (space-split)
  ZBENCH_FOUNDRY_API_VERSION_<ROUTE>   per-route api-version override
                                       (defaults: fireworks 2024-05-01-preview, openai v1)
  ZBENCH_FOUNDRY_READ_TIMEOUT          upstream read timeout, seconds (default 1800)
  ZBENCH_FOUNDRY_429_RETRIES           throttle retries per upstream call (default 20)
  ZBENCH_FOUNDRY_429_MAX_WAIT          total seconds a call may spend waiting out 429s
                                       (default 1200)
"""
import argparse
import json
import os
import random
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_API_VERSIONS = {"fireworks": "2024-05-01-preview", "openai": "v1"}
DEFAULT_TOKEN_CMD = ("az account get-access-token "
                     "--resource https://cognitiveservices.azure.com -o json")
REFRESH_MARGIN_S = 600          # re-mint when <10 min of token life remains

# route -> models the gateway serves there (FW-DeepSeek-V4-Flash kept although 404
# NOT DEPLOYED as of 2026-08-14 -- it documents the deployment gap in --smoke).
MODELS: dict[str, list[str]] = {
    "fireworks": ["FW-DeepSeek-V4-Pro", "FW-Kimi-K3", "FW-GLM-5.2",
                  "FW-DeepSeek-V4-Flash"],
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2",
               "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"],
}
ROUTES = tuple(MODELS)
# Upstream path prefix per route. On the openai side the "v1" is part of the GATEWAY
# path (verified live: flat /openai/chat/completions is 404; /openai/v1/... works).
UPSTREAM_PREFIX = {"fireworks": "fireworks", "openai": "openai/v1"}
# Routes whose gateway serves the Responses API natively: route -> upstream path
# (hit with NO api-version param). Other routes get the Responses->chat translation.
NATIVE_RESPONSES = {"openai": "openai/v1/responses"}
# Models that must be probed via the native Responses API (they reject chat).
SMOKE_VIA_RESPONSES = {"gpt-5.3-codex"}


def api_version_for(route: str) -> str:
    return os.environ.get(f"ZBENCH_FOUNDRY_API_VERSION_{route.upper()}",
                          DEFAULT_API_VERSIONS[route])


def read_timeout() -> float:
    return float(os.environ.get("ZBENCH_FOUNDRY_READ_TIMEOUT", "1800"))


# ------------------------------------------------------------- throttle (429) retry
# The gateway meters each MODEL per minute (token and request buckets). One agent turn
# re-sends its whole growing context, so even a SINGLE cell can exhaust a model's bucket
# mid-run: measured 2026-08-17 on run foundry-py10, where 21 of 33 pi cells died on
# `429 ... exceeded rate limit` and were recorded as no_patch_generated -- a throttle
# scored as a capability miss, which METHODOLOGY forbids. The codex adapter retries on its
# own; pi has no retry at all. Absorbing the 429 HERE fixes every client at once: a
# throttled call waits out the bucket instead of surfacing an error to the harness.
# Budget raised 2026-08-18 (240s/8 -> 1200s/20): a single pi run saturates its own
# per-model bucket turn after turn, so the proxy must be able to pace it through many
# 60s refills within one call. 1200s stays under ZBENCH_FOUNDRY_READ_TIMEOUT (1800s) and
# well under the pi cells' ZBENCH_AGENT_TIMEOUT (9000s), so no outer timeout fires first.
def throttle_retries() -> int:
    return int(os.environ.get("ZBENCH_FOUNDRY_429_RETRIES", "20"))


def throttle_max_wait() -> float:
    return float(os.environ.get("ZBENCH_FOUNDRY_429_MAX_WAIT", "1200"))


def _throttle_sleep_s(headers, attempt: int) -> float:
    """Seconds to wait before retry `attempt` (1-based): the LARGER of the gateway's
    Retry-After hint and our own exponential backoff (4, 8, 16, ... 60 before jitter), then
    jittered so concurrent cells on one deployment do not re-collide on the same second.
    Escalates roughly 4, 9, 18, 30, then holds at the 60s cap -- each late retry waits out
    one full per-minute bucket refill, and the ZBENCH_FOUNDRY_429_MAX_WAIT budget (default
    1200s over 20 retries) lets one call span many refills while a run drains its bucket.

    Taking the max is deliberate. Measured 2026-08-17 on the live gateway: a saturated
    deployment answers `Retry-After: 1` over and over, so honouring the hint alone spent
    all 8 retries in ~8s and still relayed the 429 -- while the per-minute bucket needs up
    to a MINUTE to refill. The hint is therefore a floor, never a ceiling. (It is still
    honoured when it asks for LONGER than our backoff, e.g. the observed 36s and 51s.)"""
    backoff = min(60.0, 4.0 * (2 ** (attempt - 1)))
    hint = 0.0
    if headers is not None:
        hdr = headers.get("Retry-After") or headers.get("retry-after")
        if hdr:
            try:
                hint = min(120.0, float(str(hdr).strip()))
            except ValueError:
                hint = 0.0
    return max(backoff, hint) * random.uniform(0.9, 1.2)


def _throttled(status: int) -> bool:
    return status == 429


def require_gateway_url() -> str:
    url = os.environ.get("GATEWAY_URL", "").strip()
    if not url:
        sys.exit("error: GATEWAY_URL is not set. Export the Foundry gateway base URL, "
                 "e.g.  export GATEWAY_URL=https://<your-gateway-host>  and rerun.")
    return url.rstrip("/")


class TokenError(RuntimeError):
    """az token minting failed; message carries the stderr snippet for the client."""


class TokenManager:
    """Mint-and-cache Azure AD bearer tokens. Thread-safe; never lets an az failure
    escape as anything but TokenError (the proxy turns that into a 502)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def get(self) -> str:
        with self._lock:
            if self._token and time.time() < self._expires_at - REFRESH_MARGIN_S:
                return self._token
            self._token, self._expires_at = self._mint()
            return self._token

    @staticmethod
    def _mint() -> tuple[str, float]:
        cmd = shlex.split(os.environ.get("ZBENCH_FOUNDRY_TOKEN_CMD", DEFAULT_TOKEN_CMD))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise TokenError(f"token command failed to run: {e}") from e
        if r.returncode != 0:
            raise TokenError(f"az exited {r.returncode}: {(r.stderr or '').strip()[:300]}")
        try:
            data = json.loads(r.stdout)
            token = data["accessToken"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise TokenError(f"unparseable token JSON: {r.stdout.strip()[:200]}") from e
        return token, _parse_expiry(data)


def _parse_expiry(data: dict) -> float:
    """Epoch seconds from az output: prefer `expires_on` (epoch, int or str), fall
    back to `expiresOn` (local-time string, several formats). Unparseable -> assume
    30 min so we still refresh sanely."""
    raw = data.get("expires_on")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    raw = data.get("expiresOn")
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).timestamp()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(raw).timestamp()
        except ValueError:
            pass
    return time.time() + 1800


# ------------------------------------------------------------ upstream helpers

def _log_request_fields(url: str, body: bytes | None) -> None:
    """ZBENCH_FOUNDRY_LOG_FIELDS=1 -> record WHICH knobs the client sent (never the content).

    Exists to answer one recurring question with evidence instead of inference: does the
    harness actually deliver reasoning effort to the model? agents-meta claims effort for
    each row, and a claim of "honored" has to be checkable. Logs field NAMES plus the
    reasoning knobs only -- no messages, no tokens, no Authorization header."""
    if os.environ.get("ZBENCH_FOUNDRY_LOG_FIELDS") != "1" or not body:
        return
    try:
        d = json.loads(body)
    except Exception:
        return
    if not isinstance(d, dict):
        return
    print(f"[fields] model={d.get('model')!r} reasoning_effort={d.get('reasoning_effort')!r} "
          f"reasoning={d.get('reasoning')!r} thinking={d.get('thinking')!r} "
          f"max_completion_tokens={d.get('max_completion_tokens')!r} "
          f"max_tokens={d.get('max_tokens')!r} keys={sorted(d.keys())} url={url.rsplit('/',1)[-1]}",
          flush=True)


def _upstream_request_ex(method: str, url: str, body: bytes | None, content_type: str | None,
                         token: str, timeout: float) -> tuple[int, object, bytes]:
    """As _upstream_request, but also returns the response HEADERS (Retry-After)."""
    _log_request_fields(url, body if method == "POST" else None)
    req = urllib.request.Request(url, data=body if method == "POST" else None,
                                 method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _ctype_of(headers, default: str = "application/json") -> str:
    return headers.get("Content-Type", default) if headers is not None else default


def _upstream_request(method: str, url: str, body: bytes | None, content_type: str | None,
                      token: str, timeout: float) -> tuple[int, str, bytes]:
    """One forwarded call, body fully read. HTTP error statuses are returned (relayed
    to the client), not raised; transport errors (URLError) propagate to the caller."""
    status, headers, payload = _upstream_request_ex(method, url, body, content_type,
                                                   token, timeout)
    return status, _ctype_of(headers), payload


def _upstream_request_retrying(method: str, url: str, body: bytes | None,
                               content_type: str | None, token: str,
                               timeout: float) -> tuple[int, str, bytes]:
    """_upstream_request that waits out gateway throttles instead of relaying them. A 429
    still outliving the retry budget is relayed unchanged, so the client sees the truth."""
    attempt = 0
    deadline = time.monotonic() + throttle_max_wait()
    while True:
        status, headers, payload = _upstream_request_ex(method, url, body, content_type,
                                                       token, timeout)
        if not _throttled(status):
            return status, _ctype_of(headers), payload
        attempt += 1
        wait = _throttle_sleep_s(headers, attempt)
        if attempt > throttle_retries() or time.monotonic() + wait > deadline:
            print(f"[proxy] 429 not cleared after {attempt} attempt(s); relaying to client"
                  f" -- {url}", flush=True)
            return status, _ctype_of(headers), payload
        print(f"[proxy] 429 upstream; waiting {wait:.1f}s then retry "
              f"{attempt}/{throttle_retries()} -- {url}", flush=True)
        time.sleep(wait)


def _urlopen_retrying(make_request, timeout: float, what: str):
    """urlopen that waits out gateway throttles. `make_request` builds a FRESH Request per
    attempt. Non-429 HTTPErrors and transport errors propagate, so each caller keeps its
    own fallback (e.g. the 400/501 'upstream rejects stream=true' path)."""
    attempt = 0
    deadline = time.monotonic() + throttle_max_wait()
    while True:
        try:
            return urllib.request.urlopen(make_request(), timeout=timeout)
        except urllib.error.HTTPError as e:
            attempt += 1
            wait = _throttle_sleep_s(e.headers, attempt)
            if (not _throttled(e.code) or attempt > throttle_retries()
                    or time.monotonic() + wait > deadline):
                raise
            e.read()                       # drain so the connection is released
            e.close()
            print(f"[proxy] 429 upstream; waiting {wait:.1f}s then retry "
                  f"{attempt}/{throttle_retries()} -- {what}", flush=True)
            time.sleep(wait)


def _open_upstream_stream(url: str, body: bytes, token: str, timeout: float):
    """POST expecting an SSE stream back; returns the open response object. Waits out 429s;
    other HTTPError/URLError propagate -- the caller decides whether to fall back or relay."""
    def _req():
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream")
        return req
    return _urlopen_retrying(_req, timeout, url)


def _iter_sse_json(fp):
    """Yield the JSON payload of each `data:` line of an SSE stream until [DONE]/EOF."""
    for raw in fp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            return
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


# ------------------------------------- Responses API <-> chat completions translation

def _responses_to_chat(req: dict) -> dict:
    """Responses-API request body (what codex sends) -> chat/completions body.
    Responses-only fields (reasoning, store, include, prompt_cache_key, ...) are
    dropped; non-function tool types (local_shell, web_search) are dropped silently."""
    messages: list[dict] = []
    if req.get("instructions"):
        messages.append({"role": "system", "content": req["instructions"]})
    for item in req.get("input") or []:
        if isinstance(item, str):
            messages.append({"role": "user", "content": item})
            continue
        itype = item.get("type", "message")
        if itype == "message":
            content = item.get("content")
            if isinstance(content, str):
                text = content
            else:
                text = "".join(c.get("text", "") for c in content or []
                               if isinstance(c, dict)
                               and c.get("type") in ("input_text", "output_text", "text"))
            role = item.get("role", "user")
            messages.append({"role": "system" if role == "developer" else role,
                             "content": text})
        elif itype == "function_call":
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": item.get("call_id") or item.get("id"), "type": "function",
                 "function": {"name": item.get("name"),
                              "arguments": item.get("arguments") or ""}}]})
        elif itype == "function_call_output":
            out = item.get("output")
            messages.append({"role": "tool", "tool_call_id": item.get("call_id"),
                             "content": out if isinstance(out, str) else json.dumps(out)})
        # reasoning / anything else: no chat-completions equivalent, skip
    chat: dict = {"model": req.get("model"), "messages": messages}
    tools = [{"type": "function",
              "function": {k: v for k, v in (("name", t.get("name")),
                                             ("description", t.get("description")),
                                             ("parameters", t.get("parameters")))
                           if v is not None}}
             for t in req.get("tools") or [] if t.get("type") == "function"]
    if tools:
        chat["tools"] = tools
    for key in ("temperature", "top_p", "parallel_tool_calls"):
        if key in req:
            chat[key] = req[key]
    if isinstance(req.get("tool_choice"), str):
        chat["tool_choice"] = req["tool_choice"]
    if req.get("max_output_tokens") is not None:
        chat["max_tokens"] = req["max_output_tokens"]
    return chat


def _map_usage(chat_usage: dict | None) -> dict:
    u = chat_usage or {}
    pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return {"input_tokens": pt, "input_tokens_details": {"cached_tokens": cached},
            "output_tokens": ct, "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": u.get("total_tokens", pt + ct)}


class _ResponsesEmitter:
    """Builds Responses-API output items from chat-completions deltas and, when given
    a wfile, writes the corresponding SSE event sequence (flushed per event, so codex
    sees liveness during long generations). wfile=None -> collect only, for the
    non-streaming JSON reply."""

    def __init__(self, wfile, model: str) -> None:
        self._w = wfile
        self.model = model
        self.rid = "resp_" + uuid.uuid4().hex[:24]
        self.output: list[dict] = []
        self._cur: dict | None = None       # open output item
        self._text: list[str] = []          # text fragments of the open message
        self._args: list[str] = []          # argument fragments of the open call
        self._tool_index: int | None = None  # chat-side tool_calls index of open call

    def _event(self, etype: str, data: dict) -> None:
        if self._w is None:
            return
        payload = json.dumps({"type": etype, **data})
        self._w.write(f"event: {etype}\ndata: {payload}\n\n".encode())
        self._w.flush()

    def created(self) -> None:
        self._event("response.created", {"response": {
            "id": self.rid, "object": "response", "status": "in_progress",
            "model": self.model, "output": []}})

    def text_delta(self, text: str) -> None:
        if not (self._cur and self._cur["type"] == "message"):
            self._close_item()
            idx = len(self.output)
            self._cur = {"id": f"msg_{idx}", "type": "message", "role": "assistant",
                         "status": "in_progress", "content": []}
            self._text = []
            self._event("response.output_item.added",
                        {"output_index": idx, "item": self._cur})
            self._event("response.content_part.added",
                        {"item_id": self._cur["id"], "output_index": idx,
                         "content_index": 0, "part": {"type": "output_text", "text": ""}})
        self._text.append(text)
        self._event("response.output_text.delta",
                    {"item_id": self._cur["id"], "output_index": len(self.output),
                     "content_index": 0, "delta": text})

    def tool_delta(self, tc: dict) -> None:
        """One chat-side tool_calls delta: {"index", "id"?, "function": {"name"?,
        "arguments"?}}. A new index opens a new function_call item."""
        idx, fn = tc.get("index", 0), tc.get("function") or {}
        if not (self._cur and self._cur["type"] == "function_call"
                and self._tool_index == idx):
            self._close_item()
            self._tool_index = idx
            oidx = len(self.output)
            self._cur = {"id": f"fc_{oidx}", "type": "function_call",
                         "call_id": tc.get("id") or "call_" + uuid.uuid4().hex[:12],
                         "name": fn.get("name") or "", "arguments": "",
                         "status": "in_progress"}
            self._args = []
            self._event("response.output_item.added",
                        {"output_index": oidx, "item": self._cur})
        if fn.get("name") and not self._cur["name"]:
            self._cur["name"] = fn["name"]          # name sometimes trails the id chunk
        if fn.get("arguments"):
            self._args.append(fn["arguments"])
            self._event("response.function_call_arguments.delta",
                        {"item_id": self._cur["id"], "output_index": len(self.output),
                         "delta": fn["arguments"]})

    def _close_item(self) -> None:
        if not self._cur:
            return
        idx = len(self.output)
        if self._cur["type"] == "message":
            text = "".join(self._text)
            self._event("response.output_text.done",
                        {"item_id": self._cur["id"], "output_index": idx,
                         "content_index": 0, "text": text})
            self._event("response.content_part.done",
                        {"item_id": self._cur["id"], "output_index": idx,
                         "content_index": 0,
                         "part": {"type": "output_text", "text": text}})
            self._cur["content"] = [{"type": "output_text", "text": text}]
        else:
            args = "".join(self._args)
            self._event("response.function_call_arguments.done",
                        {"item_id": self._cur["id"], "output_index": idx,
                         "arguments": args})
            self._cur["arguments"] = args
        self._cur["status"] = "completed"
        self._event("response.output_item.done", {"output_index": idx, "item": self._cur})
        self.output.append(self._cur)
        self._cur, self._tool_index = None, None

    def feed_chat_message(self, msg: dict) -> None:
        """Feed a complete (non-streamed) chat message through the same item builder."""
        if msg.get("content"):
            self.text_delta(msg["content"])
        for i, tc in enumerate(msg.get("tool_calls") or []):
            self.tool_delta({"index": i, "id": tc.get("id"),
                             "function": tc.get("function") or {}})

    def complete(self, chat_usage: dict | None) -> dict:
        self._close_item()
        resp = {"id": self.rid, "object": "response", "status": "completed",
                "model": self.model, "output": self.output,
                "usage": _map_usage(chat_usage)}
        self._event("response.completed", {"response": resp})
        return resp


# ---------------------------------------------------------------- proxy server

class ProxyHandler(BaseHTTPRequestHandler):
    gateway_url: str = ""           # set by serve()/tests before use
    tokens: TokenManager

    def do_GET(self) -> None:
        self._proxy("GET")

    def do_POST(self) -> None:
        self._proxy("POST")

    def _proxy(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        split = _split_route(parsed.path)
        if split is None:
            self._send_json(404, {"error": {"message":
                f"unknown route in {parsed.path!r}; expected /<route>/... with route "
                f"in {list(ROUTES)}", "type": "not_found"}})
            return
        route, rest = split
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        if method == "POST" and rest == ["responses"]:
            if route in NATIVE_RESPONSES:
                self._serve_native_responses(route, body or b"{}")
            else:
                self._serve_responses(route, body or b"{}")
            return
        try:
            token = self.tokens.get()
        except TokenError as e:
            self._send_json(502, {"error": {"message": f"token mint failed: {e}",
                                            "type": "bad_gateway"}})
            return
        target = ("/" + "/".join([UPSTREAM_PREFIX[route], *rest])
                  + "?" + _merged_query(route, parsed.query))
        try:
            status, ctype, payload = _upstream_request_retrying(
                method, self.gateway_url + target, body,
                self.headers.get("Content-Type"), token, read_timeout())
        except urllib.error.URLError as e:
            self._send_json(502, {"error": {"message": f"upstream unreachable: {e.reason}",
                                            "type": "bad_gateway"}})
            return
        self._relay(status, ctype, payload)

    def _serve_native_responses(self, route: str, body: bytes) -> None:
        """The gateway speaks the Responses API natively on this route: pure
        passthrough to its upstream path (no api-version), SSE relayed untouched."""
        try:
            token = self.tokens.get()
        except TokenError as e:
            self._send_json(502, {"error": {"message": f"token mint failed: {e}",
                                            "type": "bad_gateway"}})
            return
        url = f"{self.gateway_url}/{NATIVE_RESPONSES[route]}"
        ctype_in = self.headers.get("Content-Type") or "application/json"
        accept_in = self.headers.get("Accept")

        def _req():
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Authorization", f"Bearer {token}")
            req.add_header("Content-Type", ctype_in)
            if accept_in:
                req.add_header("Accept", accept_in)
            return req
        try:
            up = _urlopen_retrying(_req, read_timeout(), url)
        except urllib.error.HTTPError as e:
            self._relay(e.code, e.headers.get("Content-Type", "application/json"),
                        e.read())
            return
        except urllib.error.URLError as e:
            self._send_json(502, {"error": {"message": f"upstream unreachable: {e.reason}",
                                            "type": "bad_gateway"}})
            return
        with up:
            self.send_response(up.status)
            self.send_header("Content-Type",
                             up.headers.get("Content-Type", "application/json"))
            self.end_headers()
            try:
                while True:                 # read1 = per-chunk, keeps SSE live
                    chunk = up.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass                        # client hung up mid-stream

    def _serve_responses(self, route: str, body: bytes) -> None:
        """Translate a Responses-API request into an upstream chat/completions call and
        re-emit the reply as Responses SSE events (or JSON when stream not requested)."""
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "request body is not JSON",
                                            "type": "invalid_request_error"}})
            return
        try:
            token = self.tokens.get()
        except TokenError as e:
            self._send_json(502, {"error": {"message": f"token mint failed: {e}",
                                            "type": "bad_gateway"}})
            return
        chat = _responses_to_chat(req)
        stream = bool(req.get("stream"))
        url = (f"{self.gateway_url}/{UPSTREAM_PREFIX[route]}/chat/completions?"
               + urllib.parse.urlencode({"api-version": api_version_for(route)}))
        try:
            if stream:
                self._responses_streaming(url, chat, token)
            else:
                self._responses_from_full_chat(url, chat, token, sse=False)
        except urllib.error.URLError as e:
            self._send_json(502, {"error": {"message": f"upstream unreachable: {e.reason}",
                                            "type": "bad_gateway"}})
        except (BrokenPipeError, ConnectionResetError):
            pass                                    # client hung up mid-stream

    def _responses_streaming(self, url: str, chat: dict, token: str) -> None:
        up_body = dict(chat, stream=True, stream_options={"include_usage": True})
        try:
            up = _open_upstream_stream(url, json.dumps(up_body).encode(), token,
                                       read_timeout())
        except urllib.error.HTTPError as e:
            if e.code in (400, 501):                # upstream rejects stream=true
                self._responses_from_full_chat(url, chat, token, sse=True)
            else:
                self._relay(e.code, e.headers.get("Content-Type", "application/json"),
                            e.read())
            return
        with up:
            self._start_sse()
            em = _ResponsesEmitter(self.wfile, chat.get("model") or "")
            em.created()
            usage = None
            for chunk in _iter_sse_json(up):
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        em.text_delta(delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        em.tool_delta(tc)
            em.complete(usage)

    def _responses_from_full_chat(self, url: str, chat: dict, token: str,
                                  sse: bool) -> None:
        """Non-streaming upstream call; reply as SSE events (all at once) or JSON."""
        status, ctype, payload = _upstream_request_retrying(
            "POST", url, json.dumps(chat).encode(), "application/json", token,
            read_timeout())
        if status != 200:
            self._relay(status, ctype, payload)
            return
        try:
            data = json.loads(payload)
            msg = (data.get("choices") or [{}])[0].get("message") or {}
        except (json.JSONDecodeError, AttributeError, IndexError):
            self._send_json(502, {"error": {"message":
                f"unparseable upstream chat completion: {payload[:200]!r}",
                "type": "bad_gateway"}})
            return
        if sse:
            self._start_sse()
            em = _ResponsesEmitter(self.wfile, chat.get("model") or "")
            em.created()
            em.feed_chat_message(msg)
            em.complete(data.get("usage"))
        else:
            em = _ResponsesEmitter(None, chat.get("model") or "")
            em.feed_chat_message(msg)
            self._send_json(200, em.complete(data.get("usage")))

    def _start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _relay(self, status: int, ctype: str, payload: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, obj: dict) -> None:
        self._relay(status, "application/json", json.dumps(obj).encode())

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[proxy] %s\n" % (fmt % args))


def _split_route(path: str) -> tuple[str, list[str]] | None:
    """/<route>/v1/<rest> or /<route>/<rest> -> (route, rest segments), else None."""
    parts = [p for p in path.split("/") if p]
    if not parts or parts[0] not in ROUTES:
        return None
    rest = parts[1:]
    if rest and rest[0] == "v1":                # OpenAI-SDK clients prepend /v1
        rest = rest[1:]
    return parts[0], rest


def _merged_query(route: str, query: str) -> str:
    """Client query params preserved; api-version added only if absent."""
    params = urllib.parse.parse_qsl(query, keep_blank_values=True)
    if not any(k == "api-version" for k, _ in params):
        params.append(("api-version", api_version_for(route)))
    return urllib.parse.urlencode(params)


def serve(host: str, port: int) -> None:
    ProxyHandler.gateway_url = require_gateway_url()
    ProxyHandler.tokens = TokenManager()
    server = ThreadingHTTPServer((host, port), ProxyHandler)
    print(f"foundry proxy on http://{host}:{port} -> {ProxyHandler.gateway_url}\n"
          f"routes: " + ", ".join(f"/{r}/v1/* and /{r}/*" for r in ROUTES)
          + "  (POST .../responses is translated to chat completions)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------- smoke mode

def _smoke_bodies(model: str) -> list[dict]:
    base = {"model": model,
            "messages": [{"role": "user", "content": "Reply with the single word: ok"}]}
    return [{**base, "max_tokens": 16},             # some backends 400 on max_tokens...
            {**base, "max_completion_tokens": 16}]  # ...and want this newer name


def _probe(gateway_url: str, route: str, model: str, token: str) -> tuple[int, str, str]:
    """Probe one model. Returns (status, path used, snippet). Chat-unsupported models
    (SMOKE_VIA_RESPONSES) go through the native Responses path; chat probes retry
    with max_completion_tokens when max_tokens gets a 400."""
    timeout = min(read_timeout(), 120)
    if route in NATIVE_RESPONSES and model in SMOKE_VIA_RESPONSES:
        path = NATIVE_RESPONSES[route]
        body = {"model": model, "input": "Reply with the single word: ok",
                "max_output_tokens": 16}
        try:
            status, _, payload = _upstream_request(
                "POST", f"{gateway_url}/{path}", json.dumps(body).encode(),
                "application/json", token, timeout)
        except urllib.error.URLError as e:
            return 0, path, f"unreachable: {e.reason}"
        return status, path, payload.decode("utf-8", "replace").strip()
    path = f"{UPSTREAM_PREFIX[route]}/chat/completions"
    url = (f"{gateway_url}/{path}?"
           + urllib.parse.urlencode({"api-version": api_version_for(route)}))
    status, snippet = 0, ""
    for body in _smoke_bodies(model):
        try:
            status, _, payload = _upstream_request(
                "POST", url, json.dumps(body).encode(), "application/json",
                token, timeout)
        except urllib.error.URLError as e:
            return 0, path, f"unreachable: {e.reason}"
        snippet = payload.decode("utf-8", "replace").strip()
        if status != 400:
            break                           # only 400 warrants the param-name retry
    return status, path, snippet


def _verdict(status: int) -> str:
    if status == 200:
        return "AVAILABLE"
    if status == 404:
        return "NOT DEPLOYED"
    if status in (401, 403):
        return "AUTH ERROR"
    if status == 400:
        return "BAD REQUEST"
    if status == 429:
        return "RATE LIMITED"
    if status == 0:
        return "UNREACHABLE"
    return f"HTTP {status}"


def smoke(models_filter: str | None) -> int:
    gateway_url = require_gateway_url()
    wanted = {m.strip().lower() for m in models_filter.split(",")} if models_filter else None
    try:
        token = TokenManager().get()
    except TokenError as e:
        sys.exit(f"error: cannot mint gateway token: {e}")
    rows, all_ok = [], True
    for route, models in MODELS.items():
        for model in models:
            if wanted and model.lower() not in wanted:
                continue
            status, path, snippet = _probe(gateway_url, route, model, token)
            verdict = _verdict(status)
            all_ok &= (verdict == "AVAILABLE")
            rows.append((model, path, str(status), verdict,
                         snippet[:80] + ("..." if len(snippet) > 80 else "")))
    if not rows:
        sys.exit(f"error: --models filter {models_filter!r} matched nothing in MODELS")
    header = ("model", "path", "http", "verdict", "response")
    widths = [max(len(r[i]) for r in rows + [header]) for i in range(4)]
    for r in [header] + rows:
        print("  ".join(str(r[i]).ljust(widths[i]) for i in range(4)) + "  " + r[4])
    return 0 if all_ok else 1


# ------------------------------------------------------- offline test scaffolding

class _MockUpstream(BaseHTTPRequestHandler):
    """Stands in for the gateway: records each request; native /openai/v1/responses
    gets canned Responses SSE bytes; chat paths answer chat-completions SSE when the
    request asked to stream (tool-call variant when the body mentions USE_TOOL), a
    canned chat-completion JSON otherwise."""
    seen: list[dict] = []
    native_sse = (b'event: response.created\ndata: {"type":"response.created"}\n\n'
                  b'event: response.completed\ndata: {"type":"response.completed"}\n\n')
    canned = json.dumps({"id": "mock", "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "ok"},
         "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}}).encode()
    stream_text_parts = ["Hel", "lo"]
    _tool_chunks = [
        {"choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
            {"index": 0, "id": "call_abc", "type": "function",
             "function": {"name": "shell", "arguments": ""}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "{\"cmd\":"}}]}}]},
        {"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "\"ls\"}"}}]}}]},
        {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
         "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}},
    ]

    throttle_next: int = 0          # answer this many upcoming requests with 429
    throttle_retry_after: str = "1"  # Retry-After the mock advertises with its 429

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode()
        _MockUpstream.seen.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": raw})
        if _MockUpstream.throttle_next > 0:
            _MockUpstream.throttle_next -= 1
            payload = json.dumps({"error": {"code": "429", "message":
                                            "Requests to the model have exceeded rate limit."}}).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", _MockUpstream.throttle_retry_after)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.split("?", 1)[0] == "/openai/v1/responses":
            self._relay_bytes("text/event-stream", self.native_sse)
            return
        try:
            wants_stream = bool(json.loads(raw or "{}").get("stream"))
        except json.JSONDecodeError:
            wants_stream = False
        if not wants_stream:
            self._relay_bytes("application/json", self.canned)
            return
        if "USE_TOOL" in raw:
            chunks = self._tool_chunks
        else:
            chunks = [{"choices": [{"index": 0,
                                    "delta": {"role": "assistant", "content": p}}]}
                      for p in self.stream_text_parts]
            chunks.append({"choices": [{"index": 0, "delta": {},
                                        "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 5, "completion_tokens": 2,
                                     "total_tokens": 7}})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for c in chunks:
            self.wfile.write(b"data: " + json.dumps(c).encode() + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")

    def _relay_bytes(self, ctype: str, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        pass


def _start_offline_stack() -> tuple[ThreadingHTTPServer, ThreadingHTTPServer, str]:
    """Mock gateway + proxy pointed at it, token command stubbed. Returns
    (mock_server, proxy_server, proxy_base_url)."""
    fake = json.dumps({"accessToken": "fake-token", "expires_on": "9999999999"})
    os.environ["ZBENCH_FOUNDRY_TOKEN_CMD"] = "echo " + shlex.quote(fake)
    mock = ThreadingHTTPServer(("127.0.0.1", 0), _MockUpstream)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    os.environ["GATEWAY_URL"] = f"http://127.0.0.1:{mock.server_address[1]}"
    ProxyHandler.gateway_url = require_gateway_url()
    ProxyHandler.tokens = TokenManager()
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), ProxyHandler)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return mock, proxy, f"http://127.0.0.1:{proxy.server_address[1]}"


def _post(url: str, body: bytes, headers: dict) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, dict(resp.headers), resp.read()


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        etype, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                etype = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        if etype is not None:
            events.append((etype, data))
    return events


def self_test() -> int:
    mock, proxy, base = _start_offline_stack()
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  {'PASS' if cond else 'FAIL'}  {name}"
              + (f"  [{detail}]" if detail and not cond else ""))
        if not cond:
            failures.append(name)

    # --- passthrough behavior ---
    body = json.dumps({"model": "FW-Kimi-K3", "messages": []})
    status, _, relayed = _post(f"{base}/fireworks/v1/chat/completions", body.encode(),
                               {"Content-Type": "application/json",
                                "Authorization": "Bearer client-junk-key"})
    s = _MockUpstream.seen[-1]
    path, query = s["path"].split("?", 1)
    check("v1 path mapped", path == "/fireworks/chat/completions", s["path"])
    check("api-version appended",
          ("api-version", api_version_for("fireworks"))
          in urllib.parse.parse_qsl(query), query)
    check("Authorization injected (client's replaced)",
          s["authorization"] == "Bearer fake-token", str(s["authorization"]))
    check("body passed through", s["body"] == body, s["body"])
    check("content-type forwarded", s["content_type"] == "application/json",
          str(s["content_type"]))
    check("upstream response relayed", status == 200 and relayed == _MockUpstream.canned)

    _post(f"{base}/openai/chat/completions", b"{}", {})
    o_path, o_query = _MockUpstream.seen[-1]["path"].split("?", 1)
    check("openai chat mapped under upstream v1 prefix",
          o_path == "/openai/v1/chat/completions", _MockUpstream.seen[-1]["path"])
    check("openai chat default api-version is v1",
          ("api-version", "v1") in urllib.parse.parse_qsl(o_query), o_query)

    try:
        _post(f"{base}/nonsense/chat/completions", b"{}", {})
        check("unknown route rejected", False)
    except urllib.error.HTTPError as e:
        check("unknown route rejected", e.code == 404, str(e.code))

    # --- responses translation: request side + streamed text ---
    resp_req = {
        "model": "FW-Test", "stream": True, "instructions": "SYS",
        "input": [
            {"type": "message", "role": "user",
             "content": [{"type": "input_text", "text": "hi"}]},
            {"type": "function_call", "name": "shell", "arguments": "{}",
             "call_id": "call_1"},
            {"type": "function_call_output", "call_id": "call_1", "output": "files"},
            {"type": "reasoning", "summary": []},
        ],
        "tools": [
            {"type": "function", "name": "shell", "description": "run",
             "parameters": {"type": "object"}, "strict": False},
            {"type": "local_shell"},
        ],
        "temperature": 0.2, "store": False, "include": [],
    }
    status, hdrs, raw = _post(f"{base}/fireworks/v1/responses",
                              json.dumps(resp_req).encode(),
                              {"Content-Type": "application/json"})
    s = _MockUpstream.seen[-1]
    check("responses mapped to chat/completions",
          s["path"].split("?")[0] == "/fireworks/chat/completions", s["path"])
    sent = json.loads(s["body"])
    msgs = sent["messages"]
    check("instructions -> system message",
          msgs[0] == {"role": "system", "content": "SYS"})
    check("input message -> user message", msgs[1] == {"role": "user", "content": "hi"})
    check("function_call -> assistant tool_calls",
          msgs[2].get("tool_calls", [{}])[0].get("id") == "call_1"
          and msgs[2]["tool_calls"][0]["function"]["name"] == "shell",
          json.dumps(msgs[2]))
    check("function_call_output -> tool message",
          msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "files"})
    check("reasoning item skipped (and responses-only fields dropped)",
          len(msgs) == 4 and "store" not in sent and "include" not in sent)
    check("tools mapped, non-function dropped",
          sent.get("tools") == [{"type": "function", "function": {
              "name": "shell", "description": "run",
              "parameters": {"type": "object"}}}], json.dumps(sent.get("tools")))
    check("stream requested upstream", sent.get("stream") is True)
    check("temperature forwarded", sent.get("temperature") == 0.2)

    check("SSE content-type",
          (hdrs.get("Content-Type") or "").startswith("text/event-stream"),
          str(hdrs.get("Content-Type")))
    events = _parse_sse(raw.decode())
    types = [t for t, _ in events]
    for expected in ("response.created", "response.output_item.added",
                     "response.content_part.added", "response.output_text.delta",
                     "response.output_text.done", "response.content_part.done",
                     "response.output_item.done", "response.completed"):
        check(f"event {expected} emitted", expected in types)
    deltas = [d["delta"] for t, d in events if t == "response.output_text.delta"]
    check("text deltas relayed", deltas == ["Hel", "lo"], str(deltas))
    done = [d for t, d in events if t == "response.completed"][-1]["response"]
    check("completed carries output text",
          done["output"][0]["content"][0]["text"] == "Hello", json.dumps(done["output"]))
    check("usage mapped (prompt->input, completion->output)",
          done["usage"]["input_tokens"] == 5 and done["usage"]["output_tokens"] == 2,
          json.dumps(done["usage"]))

    # --- responses translation: streamed tool call ---
    tool_req = {"model": "FW-Test", "stream": True,
                "input": [{"type": "message", "role": "user",
                           "content": [{"type": "input_text", "text": "USE_TOOL"}]}]}
    _, _, raw = _post(f"{base}/fireworks/v1/responses", json.dumps(tool_req).encode(),
                      {"Content-Type": "application/json"})
    events = _parse_sse(raw.decode())
    types = [t for t, _ in events]
    check("fn-call arguments deltas emitted",
          "response.function_call_arguments.delta" in types
          and "response.function_call_arguments.done" in types)
    done = [d for t, d in events if t == "response.completed"][-1]["response"]
    item = done["output"][0]
    check("fn-call item assembled",
          item["type"] == "function_call" and item["call_id"] == "call_abc"
          and item["name"] == "shell" and item["arguments"] == '{"cmd":"ls"}',
          json.dumps(item))

    # --- responses translation: non-streaming JSON reply ---
    status, _, raw = _post(f"{base}/fireworks/v1/responses",
                           json.dumps({"model": "FW-Test", "input": "hi"}).encode(),
                           {"Content-Type": "application/json"})
    obj = json.loads(raw)
    check("non-stream responses JSON",
          status == 200 and obj.get("object") == "response"
          and obj["output"][0]["content"][0]["text"] == "ok"
          and obj["usage"]["input_tokens"] == 3, raw.decode()[:120])

    # --- openai route: native Responses passthrough (no translation) ---
    native_body = json.dumps({"model": "gpt-5.3-codex", "input": "hi", "stream": True})
    status, hdrs, raw = _post(f"{base}/openai/v1/responses", native_body.encode(),
                              {"Content-Type": "application/json",
                               "Authorization": "Bearer client-junk-key"})
    s = _MockUpstream.seen[-1]
    check("native responses path passed through (no api-version)",
          s["path"] == "/openai/v1/responses", s["path"])
    check("native responses auth injected",
          s["authorization"] == "Bearer fake-token", str(s["authorization"]))
    check("native responses body untouched", s["body"] == native_body, s["body"])
    check("native responses SSE relayed verbatim",
          status == 200 and raw == _MockUpstream.native_sse
          and (hdrs.get("Content-Type") or "").startswith("text/event-stream"),
          raw.decode()[:120])

    # --- throttle (429) absorption: a metered gateway must not surface as a dead turn ---
    def _post_status(url: str, body: bytes) -> int:
        """POST returning the STATUS even when it is an error (urlopen raises on 4xx)."""
        try:
            st, _, _ = _post(url, body, {"Content-Type": "application/json"})
            return st
        except urllib.error.HTTPError as e:
            e.read()
            return e.code

    os.environ["ZBENCH_FOUNDRY_429_RETRIES"] = "3"
    _MockUpstream.throttle_next = 2
    before = len(_MockUpstream.seen)
    st = _post_status(f"{base}/fireworks/v1/chat/completions",
                      json.dumps({"model": "FW-Kimi-K3", "messages": []}).encode())
    check("passthrough waits out 429s and returns the real answer", st == 200, f"status={st}")
    check("throttled call retried until it cleared",
          len(_MockUpstream.seen) - before == 3, f"attempts={len(_MockUpstream.seen) - before}")

    _MockUpstream.throttle_next = 1
    before = len(_MockUpstream.seen)
    st = _post_status(f"{base}/openai/v1/responses",
                      json.dumps({"model": "gpt-5.6-sol", "input": "hi"}).encode())
    check("native responses path waits out a 429", st == 200, f"status={st}")
    check("native responses retried once",
          len(_MockUpstream.seen) - before == 2, f"attempts={len(_MockUpstream.seen) - before}")

    # A throttle that outlives the budget must be RELAYED, never disguised as success:
    # the harness has to be able to record it as an infra failure.
    os.environ["ZBENCH_FOUNDRY_429_RETRIES"] = "1"
    _MockUpstream.throttle_next = 5
    st = _post_status(f"{base}/fireworks/v1/chat/completions",
                      json.dumps({"model": "FW-Kimi-K3", "messages": []}).encode())
    check("unclearable 429 is relayed to the client", st == 429, f"status={st}")
    _MockUpstream.throttle_next = 0
    os.environ.pop("ZBENCH_FOUNDRY_429_RETRIES", None)

    proxy.shutdown()
    mock.shutdown()
    print("self-test: " + ("PASS" if not failures else f"FAIL ({', '.join(failures)})"))
    return 0 if not failures else 1


def e2e_test() -> int:
    """Acceptance test: the REAL codex CLI (Responses wire API) drives the proxy, which
    drives the mock chat-completions gateway. Fully offline."""
    codex = shutil.which("codex")
    if not codex:
        print("e2e-test: SKIP -- codex binary not on PATH (npm i -g @openai/codex)")
        return 0
    mock, proxy, base = _start_offline_stack()
    _MockUpstream.stream_text_parts = ["PROXY_", "E2E_OK"]
    home = tempfile.mkdtemp(prefix="foundry_e2e_codex_home_")
    work = tempfile.mkdtemp(prefix="foundry_e2e_work_")
    env = dict(os.environ, CODEX_HOME=home, OPENAI_API_KEY="proxy-handles-real-auth")
    cmd = [codex, "exec", "--skip-git-repo-check",
           "-c", "model_provider=zbench",
           "-c", 'model_providers.zbench.name="zbench"',
           "-c", f'model_providers.zbench.base_url="{base}/fireworks/v1"',
           "-c", 'model_providers.zbench.env_key="OPENAI_API_KEY"',
           "-c", 'model_providers.zbench.wire_api="responses"',
           "-m", "FW-Test", "Say the magic word."]
    print("e2e-test: codex", " ".join(cmd[1:]))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           cwd=work, env=env)
    except subprocess.TimeoutExpired:
        print("e2e-test: FAIL -- codex timed out (proxy stream likely malformed)")
        proxy.shutdown(), mock.shutdown()
        return 1
    proxy.shutdown()
    mock.shutdown()
    out = (r.stdout or "") + (r.stderr or "")
    ok = r.returncode == 0 and "PROXY_E2E_OK" in out
    print(f"codex exit code: {r.returncode}")
    print("--- codex output (tail) ---")
    print("\n".join(out.strip().splitlines()[-12:]))
    print("e2e-test: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--smoke", action="store_true",
                    help="probe the gateway's models directly (no server)")
    ap.add_argument("--models", default=None,
                    help="comma-separated model names to limit --smoke to")
    ap.add_argument("--self-test", action="store_true",
                    help="offline end-to-end test against a mock upstream")
    ap.add_argument("--e2e-test", action="store_true",
                    help="offline acceptance test driving the proxy with the real codex CLI")
    args = ap.parse_args()
    if args.self_test:
        sys.exit(self_test())
    if args.e2e_test:
        sys.exit(e2e_test())
    if args.smoke:
        sys.exit(smoke(args.models))
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
