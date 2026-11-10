"""Reverse proxy from the public gateway to a user's sandbox (HTTP, SSE, WS).

The browser never talks to a sandbox directly and never holds its token:
the gateway authenticates the platform session, then forwards the request
with the sandbox's launch token as the ``cclaunch`` cookie. The platform
session cookie is stripped so it never reaches the (agent-controlled)
sandbox. ``X-Forwarded-Host`` carries the public host, which is what the
sandbox's cross-origin check compares the browser's Origin against.
"""
from __future__ import annotations

import asyncio
from http.cookies import SimpleCookie
from typing import Optional

import httpx
import websockets
from fastapi import Request, WebSocket
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

from .sandbox import LAUNCH_COOKIE
from .security import SESSION_COOKIE

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
              "te", "trailers", "transfer-encoding", "upgrade", "host"}
_PRIVATE_COOKIES = {SESSION_COOKIE, LAUNCH_COOKIE}


def upstream_cookie(raw: str, token: str) -> str:
    """The browser's cookies minus platform secrets, plus the sandbox token."""
    jar = SimpleCookie()
    try:
        jar.load(raw or "")
    except Exception:  # noqa: BLE001 — a malformed header just drops cookies
        jar = SimpleCookie()
    parts = [f"{k}={m.value}" for k, m in jar.items() if k not in _PRIVATE_COOKIES]
    parts.append(f"{LAUNCH_COOKIE}={token}")
    return "; ".join(parts)


def forward_headers(headers, token: str, public_host: str, proto: str) -> dict:
    out = {k: v for k, v in headers.items()
           if k.lower() not in HOP_BY_HOP and k.lower() not in ("cookie", "content-length")
           and not k.lower().startswith("x-forwarded-")}
    out["cookie"] = upstream_cookie(headers.get("cookie", ""), token)
    out["x-forwarded-host"] = public_host
    out["x-forwarded-proto"] = proto
    return out


async def proxy_http(request: Request, base: str, token: str,
                     client: httpx.AsyncClient) -> StreamingResponse:
    url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
    headers = forward_headers(request.headers, token, request.headers.get("host", ""),
                              request.url.scheme)
    body = await request.body()
    req = client.build_request(request.method, url, headers=headers, content=body)
    resp = await client.send(req, stream=True)
    out = StreamingResponse(resp.aiter_raw(), status_code=resp.status_code,
                            background=BackgroundTask(resp.aclose))
    out.raw_headers = [
        (k.encode("latin-1"), v.encode("latin-1"))
        for k, v in resp.headers.multi_items()
        if k.lower() not in HOP_BY_HOP
    ]
    if "text/event-stream" in resp.headers.get("content-type", ""):
        out.raw_headers.append((b"x-accel-buffering", b"no"))
    return out


async def proxy_ws(ws: WebSocket, base: str, token: str) -> None:
    path = ws.url.path + (f"?{ws.url.query}" if ws.url.query else "")
    url = base.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + path
    headers = {"Cookie": upstream_cookie(ws.headers.get("cookie", ""), token),
               "X-Forwarded-Host": ws.headers.get("host", ""),
               "X-Forwarded-Proto": "https" if ws.url.scheme == "wss" else "http"}
    origin: Optional[str] = ws.headers.get("origin")
    try:
        upstream = await websockets.connect(url, additional_headers=headers,
                                            origin=origin, max_size=None,
                                            compression=None, open_timeout=30)
    except Exception:  # noqa: BLE001
        await ws.close(code=1011)
        return
    await ws.accept()

    async def client_to_up():
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await upstream.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])
        finally:
            await upstream.close()

    async def up_to_client():
        try:
            async for data in upstream:
                if isinstance(data, str):
                    await ws.send_text(data)
                else:
                    await ws.send_bytes(data)
        finally:
            try:
                await ws.close()
            except RuntimeError:
                pass

    tasks = [asyncio.create_task(client_to_up()), asyncio.create_task(up_to_client())]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
