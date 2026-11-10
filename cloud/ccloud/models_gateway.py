"""Metered, OpenAI-compatible model gateway ("our model service").

A sandbox in platform mode runs CheetahClaws with
    CUSTOM_BASE_URL = <gateway>/internal/v1
    CUSTOM_API_KEY  = ccu_<uid>_<hmac>      (per user, derived from CC_SECRET)
so every model call lands here. We authenticate the user, refuse when the
balance is exhausted, forward to the upstream provider with *our* key, stream
the reply straight through, read the token usage from the final chunk and
deduct the cost.

The catalog (models.json) maps public model ids to upstreams and to the
per-1M-token prices the user pays.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .db import Database
from .security import parse_model_token
from .settings import Settings

log = logging.getLogger("ccloud.models")


def _err(status: int, message: str, code: str = "error") -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": code, "code": code}},
                        status_code=status)


def cost_micro(model: dict, in_tok: int, out_tok: int) -> int:
    """USD-per-1M-token prices × tokens = micro-dollars, rounded up."""
    raw = in_tok * float(model.get("price_in", 0)) + out_tok * float(model.get("price_out", 0))
    return int(raw) + (1 if raw % 1 else 0)


class UsageScanner:
    """Watches an OpenAI SSE stream for the usage block (and counts output
    characters in case the upstream never reports usage)."""

    def __init__(self) -> None:
        self._buf = b""
        self.usage: Optional[dict] = None
        self.out_chars = 0

    def feed(self, chunk: bytes) -> None:
        self._buf += chunk
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                continue
            try:
                obj = json.loads(data)
            except ValueError:
                continue
            if obj.get("usage"):
                self.usage = obj["usage"]
            for ch in obj.get("choices") or []:
                delta = ch.get("delta") or {}
                self.out_chars += len(delta.get("content") or "")
                for tc in delta.get("tool_calls") or []:
                    self.out_chars += len(((tc.get("function") or {}).get("arguments")) or "")


def build_router(settings: Settings, db: Database,
                 transport: Optional[httpx.AsyncBaseTransport] = None) -> APIRouter:
    router = APIRouter(prefix="/internal/v1")
    client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(600, connect=15))

    def catalog() -> dict[str, dict]:
        return {m["id"]: m for m in settings.load_models()}

    def auth(request: Request) -> Optional[int]:
        h = request.headers.get("authorization", "")
        token = h[7:].strip() if h.lower().startswith("bearer ") else ""
        uid = parse_model_token(settings.secret, token) if token else None
        return uid if uid is not None and db.get_user(uid) else None

    @router.get("/models")
    async def list_models(request: Request):
        if auth(request) is None:
            return _err(401, "invalid API key", "invalid_api_key")
        return {"object": "list", "data": [
            {"id": m["id"], "object": "model", "owned_by": "cheetahclaws-cloud",
             "context_window": m.get("context"), "max_model_len": m.get("context")}
            for m in catalog().values()]}

    @router.post("/chat/completions")
    async def chat_completions(request: Request):
        uid = auth(request)
        if uid is None:
            return _err(401, "invalid API key", "invalid_api_key")
        user = db.get_user(uid)
        if user.balance_micro <= 0:
            return _err(402, "You're out of CheetahClaws credits. Top up on your "
                        f"account page ({settings.public_url}/_cc/account), or switch "
                        "to your own API key there.", "insufficient_quota")
        try:
            body = await request.json()
        except ValueError:
            return _err(400, "body must be JSON")
        model = catalog().get(str(body.get("model", "")))
        if not model:
            return _err(404, f"unknown model {body.get('model')!r}; available: "
                        + ", ".join(catalog()), "model_not_found")
        key = os.environ.get(model.get("key_env", ""), "")
        if not key:
            log.error("model %s: upstream key env %s is not set", model["id"], model.get("key_env"))
            return _err(503, f"model {model['id']} is temporarily unavailable", "unavailable")

        body["model"] = model.get("upstream_model", model["id"])
        stream = bool(body.get("stream"))
        if stream:
            body["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
        prompt_chars = len(json.dumps(body.get("messages", [])))
        url = model["upstream_base"].rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if model.get("extra_headers"):
            headers.update(model["extra_headers"])

        def settle(usage: Optional[dict], out_chars: int) -> None:
            if usage:
                in_tok = int(usage.get("prompt_tokens") or 0)
                out_tok = int(usage.get("completion_tokens") or 0)
            else:   # upstream didn't report — estimate (~4 chars/token)
                in_tok, out_tok = prompt_chars // 4, out_chars // 4
            c = cost_micro(model, in_tok, out_tok)
            bal = db.charge(uid, model["id"], in_tok, out_tok, c)
            log.info("charged uid=%s model=%s in=%s out=%s cost_micro=%s balance=%s",
                     uid, model["id"], in_tok, out_tok, c, bal)

        req = client.build_request("POST", url, json=body, headers=headers)
        try:
            resp = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            return _err(502, f"upstream error: {e}", "upstream_error")

        if resp.status_code != 200:
            content = await resp.aread()
            await resp.aclose()
            return JSONResponse(_safe_json(content), status_code=resp.status_code)

        if not stream:
            content = await resp.aread()
            await resp.aclose()
            data = _safe_json(content)
            usage = data.get("usage") if isinstance(data, dict) else None
            out_chars = 0
            if not usage and isinstance(data, dict):
                for ch in data.get("choices") or []:
                    out_chars += len(((ch.get("message") or {}).get("content")) or "")
            settle(usage, out_chars)
            data["model"] = model["id"]
            return JSONResponse(data)

        scanner = UsageScanner()

        async def relay():
            try:
                async for chunk in resp.aiter_raw():
                    scanner.feed(chunk)
                    yield chunk
            finally:
                await resp.aclose()
                settle(scanner.usage, scanner.out_chars)

        return StreamingResponse(relay(), status_code=200,
                                 media_type=resp.headers.get("content-type", "text/event-stream"),
                                 headers={"Cache-Control": "no-cache"})

    router.client = client  # type: ignore[attr-defined]  (closed on shutdown)
    return router


def _safe_json(content: bytes):
    try:
        return json.loads(content)
    except ValueError:
        return {"error": {"message": content.decode(errors="replace")[:500]}}
