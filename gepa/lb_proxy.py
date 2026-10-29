#!/usr/bin/env python3
"""Least-connections reverse proxy for vLLM replicas (aiohttp, streaming).

Defaults serve qwen3.6-27b; env LB_BACKENDS (comma list), LB_PORT and LB_LOG override them."""
import asyncio, itertools, logging, os, sys, time
import aiohttp
from aiohttp import web

BACKENDS = os.environ.get("LB_BACKENDS", "127.0.0.1:8011,127.0.0.1:8015").split(",")
LISTEN = ("127.0.0.1", int(os.environ.get("LB_PORT", "8016")))
LOG = os.environ.get("LB_LOG", "/mnt/data/robert-scripts/logs/qwen-lb.log")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailers", "transfer-encoding", "upgrade", "host", "content-length"}

inflight = {b: 0 for b in BACKENDS}
rr = itertools.count()
log = logging.getLogger("lb")


def order():
    # fewest in-flight first; ties broken round robin
    n = next(rr)
    idx = {b: (i - n) % len(BACKENDS) for i, b in enumerate(BACKENDS)}
    return sorted(BACKENDS, key=lambda b: (inflight[b], idx[b]))


async def handle(req: web.Request):
    t0 = time.time()
    body = await req.read()
    hdrs = {k: v for k, v in req.headers.items() if k.lower() not in HOP}
    sess = req.app["sess"]
    last_err = None
    for b in order():
        url = f"http://{b}{req.rel_url}"
        inflight[b] += 1
        resp = None
        try:
            try:
                up = await sess.request(req.method, url, headers=hdrs, data=body,
                                        allow_redirects=False)
            except (aiohttp.ClientConnectorError, ConnectionRefusedError) as e:
                last_err = e
                log.info("%s %s %s refused %.2fs", b, req.method, req.path, time.time() - t0)
                continue
            try:
                rh = {k: v for k, v in up.headers.items() if k.lower() not in HOP}
                resp = web.StreamResponse(status=up.status, reason=up.reason, headers=rh)
                await resp.prepare(req)
                async for chunk in up.content.iter_any():
                    await resp.write(chunk)
                await resp.write_eof()
                log.info("%s %s %s %d %.2fs", b, req.method, req.path, up.status, time.time() - t0)
            except Exception as e:
                log.info("%s %s %s ERR(%s) %.2fs", b, req.method, req.path, repr(e), time.time() - t0)
            finally:
                up.release()
            return resp
        finally:
            inflight[b] -= 1
    log.info("- %s %s 502 all-backends-down %.2fs", req.method, req.path, time.time() - t0)
    return web.Response(status=502, text=f"all backends unreachable: {last_err}")


async def init():
    app = web.Application(client_max_size=1024 ** 3)
    to = aiohttp.ClientTimeout(total=None, connect=30, sock_connect=30, sock_read=None)
    app["sess"] = aiohttp.ClientSession(
        timeout=to, auto_decompress=False,
        connector=aiohttp.TCPConnector(limit=0, keepalive_timeout=30))
    app.router.add_route("*", "/{tail:.*}", handle)
    async def close(app): await app["sess"].close()
    app.on_cleanup.append(close)
    return app


if __name__ == "__main__":
    logging.basicConfig(filename=LOG, level=logging.INFO,
                        format="%(asctime)s %(message)s")
    web.run_app(init(), host=LISTEN[0], port=LISTEN[1], access_log=None, print=None)
