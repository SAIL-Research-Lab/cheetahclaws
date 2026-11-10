"""CheetahClaws Cloud gateway.

Public routes
  /_cc/login, /_cc/account, /_cc/start     platform pages
  /_cc/api/*                                account / settings / billing JSON API
  /_cc/stripe/webhook                       Stripe → credits
  /health                                   gateway liveness
  everything else                           → the signed-in user's own sandbox
                                              (the full CheetahClaws web UI)
Internal (blocked at the reverse proxy; sandboxes only)
  /internal/v1/*                            metered OpenAI-compatible models

Run:  uvicorn --factory ccloud.app:factory --host 0.0.0.0 --port 8000 --proxy-headers
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import billing
from .db import MICRO, Database, User
from .models_gateway import build_router
from .proxy import proxy_http, proxy_ws
from .sandbox import BYOK_PROVIDERS, SandboxManager
from .security import (SESSION_COOKIE, SESSION_TTL, KeyBox, check_password,
                       hash_password, launch_token, make_session, mask_key,
                       read_session)
from .settings import Settings, settings as default_settings

log = logging.getLogger("ccloud")
STATIC = Path(__file__).resolve().parent / "static"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple, deque] = defaultdict(deque)

    def allow(self, bucket: str, key: str, limit: int, window: float) -> bool:
        q = self._hits[(bucket, key)]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def create_app(s: Optional[Settings] = None, *, sandbox: Optional[SandboxManager] = None,
               upstream_transport: Optional[httpx.AsyncBaseTransport] = None,
               sandbox_transport: Optional[httpx.AsyncBaseTransport] = None,
               stripe_transport: Optional[httpx.AsyncBaseTransport] = None,
               reaper: bool = True) -> FastAPI:
    s = s or default_settings
    s.validate()
    db = Database(s.db_url)
    keybox = KeyBox(s.fernet_key)
    sb = sandbox or SandboxManager(s, db, keybox)
    limiter = RateLimiter()
    proxy_client = httpx.AsyncClient(transport=sandbox_transport,
                                     timeout=httpx.Timeout(None, connect=15))
    models_router = build_router(s, db, transport=upstream_transport)
    # uid → (base_url, settings_rev, checked_at): skip Docker round-trips on
    # the many small requests a chat page makes.
    targets: dict[int, tuple[str, int, float]] = {}

    async def reap_loop():
        while True:
            await asyncio.sleep(60)
            try:
                for uid in await sb.reap_idle():
                    targets.pop(uid, None)
            except Exception:  # noqa: BLE001
                log.exception("idle reaper failed")

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(reap_loop()) if reaper else None
        yield
        if task:
            task.cancel()
        await proxy_client.aclose()
        await models_router.client.aclose()
        await sb.close()

    app = FastAPI(title="CheetahClaws Cloud", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db, app.state.sandbox, app.state.settings = db, sb, s
    app.include_router(models_router)
    app.mount("/_cc/static", StaticFiles(directory=STATIC), name="ccstatic")

    # ── helpers ──────────────────────────────────────────────────────────
    def current_user(request) -> Optional[User]:
        uid = read_session(request.cookies.get(SESSION_COOKIE, ""), s.secret)
        return db.get_user(uid) if uid is not None else None

    def set_session(resp: Response, uid: int) -> None:
        resp.set_cookie(SESSION_COOKIE, make_session(uid, s.secret), max_age=SESSION_TTL,
                        httponly=True, secure=s.secure_cookies, samesite="lax", path="/")

    def err(status: int, msg: str) -> JSONResponse:
        return JSONResponse({"error": msg}, status_code=status)

    def client_ip(request) -> str:
        return request.client.host if request.client else "?"

    def page(name: str) -> FileResponse:
        return FileResponse(STATIC / name, headers={"Cache-Control": "no-store"})

    def catalog_public() -> list[dict]:
        return [{"id": m["id"], "label": m.get("label", m["id"]),
                 "price_in": m.get("price_in"), "price_out": m.get("price_out"),
                 "context": m.get("context")} for m in s.load_models()]

    async def json_body(request) -> Optional[dict]:
        # JSON-only POSTs: a cross-site <form> can't send application/json
        # without a CORS preflight we never grant (CSRF defence on top of
        # the SameSite=Lax session cookie).
        if "application/json" not in request.headers.get("content-type", ""):
            return None
        try:
            data = await request.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    # ── pages ────────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"ok": True}

    @app.get("/")
    async def root(request: Request):
        if current_user(request):
            return RedirectResponse("/chat", 302)
        return RedirectResponse("/_cc/login", 302)

    @app.get("/_cc/login")
    async def login_page():
        return page("login.html")

    @app.get("/_cc/account")
    async def account_page(request: Request):
        if not current_user(request):
            return RedirectResponse("/_cc/login?next=/_cc/account", 302)
        return page("account.html")

    @app.get("/_cc/start")
    async def start_page(request: Request):
        if not current_user(request):
            return RedirectResponse("/_cc/login", 302)
        return page("start.html")

    # ── auth ─────────────────────────────────────────────────────────────
    @app.post("/_cc/api/register")
    async def register(request: Request):
        data = await json_body(request)
        if data is None:
            return err(400, "expected a JSON body")
        if not s.registration_open:
            return err(403, "registration is closed")
        if not limiter.allow("register", client_ip(request), 5, 3600):
            return err(429, "too many sign-ups from this network — try again later")
        email = str(data.get("email", "")).strip().lower()
        pw = str(data.get("password", ""))
        if not EMAIL_RE.match(email):
            return err(400, "please enter a valid email address")
        if len(pw) < 8:
            return err(400, "password must be at least 8 characters")
        if db.get_user_by_email(email):
            return err(409, "an account with this email already exists — sign in instead")
        models = s.load_models()
        user = db.create_user(email, hash_password(pw),
                              int(round(s.signup_credit_usd * MICRO)),
                              models[0]["id"] if models else "")
        resp = JSONResponse({"ok": True})
        set_session(resp, user.id)
        return resp

    @app.post("/_cc/api/login")
    async def login(request: Request):
        data = await json_body(request)
        if data is None:
            return err(400, "expected a JSON body")
        if not limiter.allow("login", client_ip(request), 20, 600):
            return err(429, "too many attempts — wait a few minutes")
        user = db.get_user_by_email(str(data.get("email", "")).strip().lower())
        if not user or not check_password(str(data.get("password", "")), user.password_hash):
            return err(401, "wrong email or password")
        resp = JSONResponse({"ok": True})
        set_session(resp, user.id)
        return resp

    @app.post("/_cc/api/logout")
    async def logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    # ── account ──────────────────────────────────────────────────────────
    @app.get("/_cc/api/me")
    async def me(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        return {
            "email": user.email,
            "balance_usd": round(user.balance_micro / MICRO, 4),
            "model_mode": user.model_mode,
            "platform_model": user.platform_model,
            "byok_provider": user.byok_provider,
            "byok_model": user.byok_model,
            "byok_base_url": user.byok_base_url,
            "byok_key_masked": mask_key(keybox.open(user.byok_key_enc)),
            "models": catalog_public(),
            "providers": list(BYOK_PROVIDERS),
            "workspace": await sb.status(user.id),
            "payments_enabled": bool(s.stripe_secret),
            "topup_packs_usd": s.topup_packs_usd,
        }

    @app.get("/_cc/api/usage")
    async def usage(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        return {"usage": [{"ts": u.ts, "model": u.model, "input_tokens": u.input_tokens,
                           "output_tokens": u.output_tokens,
                           "cost_usd": round(u.cost_micro / MICRO, 6)}
                          for u in db.recent_usage(user.id)]}

    @app.post("/_cc/api/settings")
    async def save_settings(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        data = await json_body(request)
        if data is None:
            return err(400, "expected a JSON body")
        mode = data.get("model_mode")
        fields: dict = {}
        if mode == "platform":
            model = str(data.get("platform_model") or user.platform_model)
            if model not in {m["id"] for m in s.load_models()}:
                return err(400, "unknown model")
            fields = {"model_mode": "platform", "platform_model": model}
        elif mode == "byok":
            prov = str(data.get("byok_provider", ""))
            if prov not in BYOK_PROVIDERS:
                return err(400, "unsupported provider")
            model = str(data.get("byok_model", "")).strip()
            if not model:
                return err(400, "enter the model to use, e.g. claude-sonnet-4-6")
            key = str(data.get("byok_key", "")).strip()
            same_provider = prov == user.byok_provider and user.byok_key_enc
            if not key and not same_provider:
                return err(400, "enter your API key")
            base_url = str(data.get("byok_base_url", "")).strip()
            if prov == "custom" and not re.match(r"^https?://", base_url):
                return err(400, "enter the endpoint URL, e.g. https://api.example.com/v1")
            fields = {"model_mode": "byok", "byok_provider": prov, "byok_model": model,
                      "byok_base_url": base_url if prov == "custom" else ""}
            if key:
                fields["byok_key_enc"] = keybox.seal(key)
        else:
            return err(400, "model_mode must be 'platform' or 'byok'")
        db.update_user(user.id, bump_rev=True, **fields)
        # The workspace picks the new model up on its next start; restart now
        # (running tasks stop — the page warns about this).
        targets.pop(user.id, None)
        try:
            await sb.docker.remove(sb.name(user.id))
        except Exception:  # noqa: BLE001
            log.exception("could not remove sandbox after settings change")
        return {"ok": True}

    @app.post("/_cc/api/workspace/start")
    async def workspace_start(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        try:
            base = await sb.ensure_running(user)
        except Exception as e:  # noqa: BLE001
            log.exception("sandbox start failed for uid=%s", user.id)
            return err(503, f"couldn't start your workspace: {e}")
        targets[user.id] = (base, user.settings_rev, time.monotonic())
        return {"ok": True}

    @app.post("/_cc/api/topup")
    async def topup(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        data = await json_body(request)
        if data is None:
            return err(400, "expected a JSON body")
        try:
            url = await billing.create_checkout(s, user.id, user.email,
                                                float(data.get("amount_usd", 0)),
                                                transport=stripe_transport)
        except (billing.BillingError, ValueError) as e:
            return err(400, str(e))
        return {"url": url}

    @app.post("/_cc/stripe/webhook")
    async def stripe_webhook(request: Request):
        status, msg = billing.handle_webhook(s, db, await request.body(),
                                             request.headers.get("stripe-signature", ""))
        return JSONResponse({"result": msg}, status_code=status)

    @app.post("/_cc/api/delete")
    async def delete_account(request: Request):
        user = current_user(request)
        if not user:
            return err(401, "not signed in")
        data = await json_body(request)
        if data is None or not check_password(str(data.get("password", "")), user.password_hash):
            return err(403, "password is incorrect")
        try:
            await sb.destroy(user.id)
        except Exception:  # noqa: BLE001
            log.exception("sandbox cleanup failed for uid=%s", user.id)
            return err(500, "couldn't delete your workspace — please try again")
        targets.pop(user.id, None)
        db.delete_user(user.id)
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE, path="/")
        return resp

    # ── everything else: the user's own CheetahClaws ─────────────────────
    async def resolve_target(user: User) -> str:
        cached = targets.get(user.id)
        if cached and cached[1] == user.settings_rev and time.monotonic() - cached[2] < 20:
            sb.touch(user.id)
            return cached[0]
        base = await sb.ensure_running(user)
        targets[user.id] = (base, user.settings_rev, time.monotonic())
        return base

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def to_sandbox(path: str, request: Request):
        if path.startswith(("_cc/", "internal/")):
            return err(404, "not found")
        user = current_user(request)
        wants_html = request.method == "GET" and "text/html" in request.headers.get("accept", "")
        if not user:
            if wants_html:
                return RedirectResponse(f"/_cc/login?next=/{path}", 302)
            return err(401, "not signed in")
        if wants_html and user.id not in targets and await sb.status(user.id) != "running":
            # Cold start takes a few seconds — show progress, not a hung tab.
            return RedirectResponse(f"/_cc/start?next=/{path}", 302)
        try:
            base = await resolve_target(user)
        except Exception as e:  # noqa: BLE001
            log.exception("sandbox unavailable for uid=%s", user.id)
            return err(503, f"your workspace is unavailable: {e}")
        try:
            return await proxy_http(request, base, launch_token(s.secret, user.id), proxy_client)
        except httpx.HTTPError:
            targets.pop(user.id, None)
            return err(502, "your workspace didn't respond — reload to retry")

    @app.websocket("/{path:path}")
    async def to_sandbox_ws(ws: WebSocket, path: str):
        user = current_user(ws)
        if not user:
            await ws.close(code=4401)
            return
        try:
            base = await resolve_target(user)
        except Exception:  # noqa: BLE001
            await ws.close(code=1011)
            return
        await proxy_ws(ws, base, launch_token(s.secret, user.id))

    return app


def factory() -> FastAPI:
    """Entry point for `uvicorn --factory ccloud.app:factory`."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()
