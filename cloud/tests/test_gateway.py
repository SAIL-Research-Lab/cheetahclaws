"""Unit tests for the CheetahClaws Cloud gateway (no Docker, no network).

    cd cloud && python -m pytest tests -q
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from ccloud.app import create_app
from ccloud.billing import verify_signature
from ccloud.db import MICRO
from ccloud.models_gateway import cost_micro
from ccloud.proxy import upstream_cookie
from ccloud.sandbox import SandboxManager
from ccloud.security import (KeyBox, launch_token, model_token,
                             parse_model_token)
from ccloud.settings import Settings

SECRET = "s" * 48
MODELS = {"models": [
    {"id": "fast", "label": "Fast", "upstream_base": "https://up.example/v1",
     "upstream_model": "up-fast", "key_env": "UP_KEY", "price_in": 1.0,
     "price_out": 2.0, "context": 64000},
    {"id": "nokey", "label": "No key", "upstream_base": "https://up.example/v1",
     "upstream_model": "x", "key_env": "MISSING_KEY_ENV", "price_in": 1, "price_out": 1},
]}


# ── fakes ────────────────────────────────────────────────────────────────

class FakeDocker:
    def __init__(self):
        self.removed: list[str] = []

    async def remove(self, name):
        self.removed.append(name)


class FakeSandbox:
    """Stands in for SandboxManager: no containers, fixed address."""

    def __init__(self):
        self.docker = FakeDocker()
        self.running: set[int] = set()
        self.destroyed: list[int] = []
        self.started: list[int] = []

    name = staticmethod(SandboxManager.name)

    async def ensure_running(self, user):
        self.running.add(user.id)
        self.started.append(user.id)
        return "http://sandbox.test"

    async def status(self, uid):
        return "running" if uid in self.running else "none"

    async def destroy(self, uid):
        self.destroyed.append(uid)
        self.running.discard(uid)

    def touch(self, uid):
        pass

    async def reap_idle(self):
        return []

    async def close(self):
        pass


def streamed(status, data: bytes, headers) -> httpx.Response:
    """A response whose body is a real stream, like one from the network
    (httpx marks `content=`/`json=` bodies as already consumed)."""
    return httpx.Response(status, stream=httpx.ByteStream(data), headers=headers)


def sandbox_handler(request: httpx.Request) -> httpx.Response:
    """Echo what the sandbox received, so tests can inspect forwarding."""
    return streamed(200, json.dumps({
        "path": request.url.path, "query": request.url.query.decode(),
        "cookie": request.headers.get("cookie", ""),
        "xfh": request.headers.get("x-forwarded-host", ""),
        "method": request.method, "body": request.content.decode(),
    }).encode(), [("content-type", "application/json"),
                  ("set-cookie", "ccsrf=abc; Path=/"), ("set-cookie", "other=1; Path=/")])


class Upstream:
    """Fake model provider."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"body": body, "auth": request.headers.get("authorization")})
        if body.get("stream"):
            chunks = [
                {"choices": [{"delta": {"content": "Hel"}}]},
                {"choices": [{"delta": {"content": "lo"}}]},
                {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 500}},
            ]
            sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
            return streamed(200, sse.encode(), {"content-type": "text/event-stream"})
        return httpx.Response(200, json={
            "id": "x", "model": body["model"],
            "choices": [{"message": {"role": "assistant", "content": "hi"}}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 1000}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    models = tmp_path / "models.json"
    models.write_text(json.dumps(MODELS))
    monkeypatch.setenv("UP_KEY", "sk-upstream")
    monkeypatch.delenv("MISSING_KEY_ENV", raising=False)
    s = Settings(public_url="http://testserver", secret=SECRET,
                 fernet_key=Fernet.generate_key().decode(),
                 db_url=f"sqlite:///{tmp_path}/t.db", models_file=str(models),
                 signup_credit_usd=1.0, stripe_secret="sk_test_x",
                 stripe_webhook_secret="whsec_test", topup_packs_usd=[5.0, 20.0])
    upstream = Upstream()
    sb = FakeSandbox()

    def stripe(request):
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.stripe.test/cs_1"})

    app = create_app(s, sandbox=sb, upstream_transport=httpx.MockTransport(upstream),
                     sandbox_transport=httpx.MockTransport(sandbox_handler),
                     stripe_transport=httpx.MockTransport(stripe), reaper=False)
    with TestClient(app) as client:
        yield client, app, sb, upstream, s


def signup(client, email="a@example.com", pw="password123"):
    r = client.post("/_cc/api/register", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return client.app.state.db.get_user_by_email(email)


# ── accounts ─────────────────────────────────────────────────────────────

def test_register_login_logout(env):
    client, *_ = env
    user = signup(client)
    me = client.get("/_cc/api/me").json()
    assert me["email"] == "a@example.com" and me["balance_usd"] == 1.0
    assert me["model_mode"] == "platform" and me["platform_model"] == "fast"
    assert "password_hash" not in json.dumps(me)
    assert client.post("/_cc/api/register", json={"email": "A@example.com",
                       "password": "password123"}).status_code == 409
    client.post("/_cc/api/logout", json={})
    assert client.get("/_cc/api/me").status_code == 401
    assert client.post("/_cc/api/login", json={"email": "a@example.com",
                       "password": "wrong-pass"}).status_code == 401
    assert client.post("/_cc/api/login", json={"email": "a@example.com",
                       "password": "password123"}).status_code == 200
    assert client.get("/_cc/api/me").json()["email"] == user.email


@pytest.mark.parametrize("body,code", [
    ({"email": "nope", "password": "password123"}, 400),
    ({"email": "b@example.com", "password": "short"}, 400),
])
def test_register_validation(env, body, code):
    client, *_ = env
    assert client.post("/_cc/api/register", json=body).status_code == code


def test_posts_require_json(env):
    client, *_ = env
    r = client.post("/_cc/api/login", data={"email": "a@example.com", "password": "x"})
    assert r.status_code == 400   # form posts (cross-site CSRF shape) refused


def test_unauthenticated_requests(env):
    client, *_ = env
    r = client.get("/chat", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/_cc/login?next=/chat"
    assert client.get("/api/sessions").status_code == 401
    assert client.get("/", follow_redirects=False).headers["location"] == "/_cc/login"


# ── proxy ────────────────────────────────────────────────────────────────

def test_cold_start_redirects_html_to_start_page(env):
    client, _app, sb, *_ = env
    signup(client)
    r = client.get("/chat", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/_cc/start?next=/chat"
    assert client.post("/_cc/api/workspace/start", json={}).json() == {"ok": True}
    r = client.get("/chat", headers={"accept": "text/html"})
    assert r.status_code == 200 and r.json()["path"] == "/chat"


def test_proxy_injects_launch_token_and_strips_session(env):
    client, _app, _sb, _up, s = env
    user = signup(client)
    client.cookies.set("ccsrf", "tok")
    client.cookies.set("cclaunch", "forged-by-browser")
    r = client.post("/api/prompt?x=1", json={"prompt": "hi"})
    seen = r.json()
    assert seen["path"] == "/api/prompt" and seen["query"] == "x=1"
    assert seen["method"] == "POST" and json.loads(seen["body"]) == {"prompt": "hi"}
    assert f"cclaunch={launch_token(SECRET, user.id)}" in seen["cookie"]
    assert "forged-by-browser" not in seen["cookie"]
    assert "ccsess" not in seen["cookie"] and "ccsrf=tok" in seen["cookie"]
    assert seen["xfh"] == "testserver"
    # Both upstream Set-Cookie headers reach the browser.
    assert len(r.headers.get_list("set-cookie")) == 2


def test_upstream_cookie_filter():
    out = upstream_cookie("ccsess=S; cclaunch=X; ccsrf=C; a=b", "TOK")
    assert out == "ccsrf=C; a=b; cclaunch=TOK"


def test_platform_routes_never_proxied(env):
    client, *_ = env
    signup(client)
    client.post("/_cc/api/workspace/start", json={})
    for path in ("/_cc/api/does-not-exist", "/internal/v2/anything"):
        r = client.get(path)
        assert r.status_code == 404 and "path" not in r.json(), path   # not echoed by sandbox


# ── model settings / BYOK ────────────────────────────────────────────────

def test_byok_key_is_encrypted_and_injected(env):
    client, app, sb, _up, s = env
    user = signup(client)
    r = client.post("/_cc/api/settings", json={
        "model_mode": "byok", "byok_provider": "anthropic",
        "byok_model": "claude-sonnet-4-6", "byok_key": "sk-ant-secret-123456"})
    assert r.status_code == 200, r.text
    assert sb.docker.removed == [f"cc-u{user.id}"]        # workspace restarts
    row = app.state.db.get_user(user.id)
    assert "sk-ant-secret" not in row.byok_key_enc and row.settings_rev == user.settings_rev + 1
    me = client.get("/_cc/api/me").json()
    assert me["model_mode"] == "byok" and me["byok_key_masked"] == "sk-a…3456"
    mgr = SandboxManager(s, app.state.db, KeyBox(s.fernet_key), docker=FakeDocker())
    envs, model = mgr.model_setup(row)
    assert envs == {"ANTHROPIC_API_KEY": "sk-ant-secret-123456"}
    assert model == "anthropic/claude-sonnet-4-6"
    # Blank key with the same provider keeps the stored key.
    assert client.post("/_cc/api/settings", json={
        "model_mode": "byok", "byok_provider": "anthropic",
        "byok_model": "claude-opus-4-6", "byok_key": ""}).status_code == 200
    assert mgr.model_setup(app.state.db.get_user(user.id))[0]["ANTHROPIC_API_KEY"] == "sk-ant-secret-123456"


@pytest.mark.parametrize("body", [
    {"model_mode": "byok", "byok_provider": "evil", "byok_model": "m", "byok_key": "k"},
    {"model_mode": "byok", "byok_provider": "openai", "byok_model": "gpt-5", "byok_key": ""},
    {"model_mode": "byok", "byok_provider": "custom", "byok_model": "m", "byok_key": "k",
     "byok_base_url": "file:///etc/passwd"},
    {"model_mode": "platform", "platform_model": "not-in-catalog"},
    {"model_mode": "sideways"},
])
def test_settings_validation(env, body):
    client, *_ = env
    signup(client)
    assert client.post("/_cc/api/settings", json=body).status_code == 400


def test_platform_mode_points_sandbox_at_gateway(env):
    client, app, _sb, _up, s = env
    user = signup(client)
    mgr = SandboxManager(s, app.state.db, KeyBox(s.fernet_key), docker=FakeDocker())
    envs, model = mgr.model_setup(user)
    assert model == "custom/fast"
    assert envs["CUSTOM_BASE_URL"].endswith("/internal/v1")
    assert parse_model_token(SECRET, envs["CUSTOM_API_KEY"]) == user.id
    spec = mgr._spec(user)
    assert spec["HostConfig"]["CapDrop"] == ["ALL"]
    assert "no-new-privileges" in spec["HostConfig"]["SecurityOpt"]
    assert any(e.startswith("CHEETAHCLAWS_LAUNCH_TOKEN=") for e in spec["Env"])
    assert spec["Labels"]["cc.rev"] == str(user.settings_rev)


# ── metered model gateway ────────────────────────────────────────────────

def _auth(uid):
    return {"Authorization": f"Bearer {model_token(SECRET, uid)}"}


def test_model_gateway_auth_and_listing(env):
    client, *_ = env
    user = signup(client)
    assert client.get("/internal/v1/models").status_code == 401
    assert client.get("/internal/v1/models", headers={
        "Authorization": f"Bearer ccu_{user.id}_forged"}).status_code == 401
    ids = [m["id"] for m in client.get("/internal/v1/models", headers=_auth(user.id)).json()["data"]]
    assert ids == ["fast", "nokey"]


def test_non_stream_call_is_charged_exactly(env):
    client, app, _sb, up, _s = env
    user = signup(client)
    r = client.post("/internal/v1/chat/completions", headers=_auth(user.id),
                    json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 200 and r.json()["model"] == "fast"
    assert up.calls[0]["body"]["model"] == "up-fast"
    assert up.calls[0]["auth"] == "Bearer sk-upstream"
    # 2000 in × $1/M + 1000 out × $2/M = $0.004
    assert app.state.db.get_user(user.id).balance_micro == MICRO - 4000
    usage = client.get("/_cc/api/usage").json()["usage"][0]
    assert usage["input_tokens"] == 2000 and usage["cost_usd"] == 0.004


def test_stream_call_relays_and_charges(env):
    client, app, _sb, up, _s = env
    user = signup(client)
    with client.stream("POST", "/internal/v1/chat/completions", headers=_auth(user.id),
                       json={"model": "fast", "stream": True,
                             "messages": [{"role": "user", "content": "hi"}]}) as r:
        text = "".join(r.iter_text())
    assert '"Hel"' in text and "[DONE]" in text
    assert up.calls[0]["body"]["stream_options"] == {"include_usage": True}
    # 1000 × 1 + 500 × 2 = 2000 micro
    assert app.state.db.get_user(user.id).balance_micro == MICRO - 2000


def test_out_of_credit_is_refused_before_upstream(env):
    client, app, _sb, up, _s = env
    user = signup(client)
    app.state.db.update_user(user.id, balance_micro=0)
    r = client.post("/internal/v1/chat/completions", headers=_auth(user.id),
                    json={"model": "fast", "messages": []})
    assert r.status_code == 402 and "out of CheetahClaws credits" in r.json()["error"]["message"]
    assert up.calls == []


def test_unknown_or_unconfigured_model(env):
    client, *_ = env
    user = signup(client)
    assert client.post("/internal/v1/chat/completions", headers=_auth(user.id),
                       json={"model": "nope", "messages": []}).status_code == 404
    assert client.post("/internal/v1/chat/completions", headers=_auth(user.id),
                       json={"model": "nokey", "messages": []}).status_code == 503


def test_cost_rounds_up():
    assert cost_micro({"price_in": 0.14, "price_out": 0}, 1, 0) == 1
    assert cost_micro({"price_in": 1, "price_out": 2}, 0, 0) == 0


# ── billing ──────────────────────────────────────────────────────────────

def _stripe_event(uid, session_id="cs_1", credit=5 * MICRO, amount_total=500):
    return json.dumps({"type": "checkout.session.completed", "data": {"object": {
        "id": session_id, "payment_status": "paid", "amount_total": amount_total,
        "metadata": {"user_id": str(uid), "credit_micro": str(credit)}}}}).encode()


def _sign(payload, secret="whsec_test", ts=None):
    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def test_topup_checkout_and_webhook(env):
    client, app, *_ = env
    user = signup(client)
    assert client.post("/_cc/api/topup", json={"amount_usd": 5}).json()["url"].startswith("https://checkout")
    assert client.post("/_cc/api/topup", json={"amount_usd": 7}).status_code == 400
    payload = _stripe_event(user.id)
    assert client.post("/_cc/stripe/webhook", content=payload,
                       headers={"stripe-signature": "t=1,v1=bad"}).status_code == 400
    r = client.post("/_cc/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert r.json()["result"] == "credited"
    r = client.post("/_cc/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert r.json()["result"] == "duplicate"
    assert app.state.db.get_user(user.id).balance_micro == 6 * MICRO


def test_webhook_never_credits_more_than_paid(env):
    client, app, *_ = env
    user = signup(client)
    payload = _stripe_event(user.id, "cs_2", credit=100 * MICRO, amount_total=500)
    client.post("/_cc/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert app.state.db.get_user(user.id).balance_micro == 6 * MICRO


def test_signature_tolerance():
    p = b"{}"
    assert verify_signature(p, _sign(p, "k", ts=1000), "k", now=1100)
    assert not verify_signature(p, _sign(p, "k", ts=1000), "k", now=2000)


# ── account deletion ─────────────────────────────────────────────────────

def test_delete_account(env):
    client, app, sb, *_ = env
    user = signup(client)
    payload = _stripe_event(user.id, "cs_9")
    client.post("/_cc/stripe/webhook", content=payload, headers={"stripe-signature": _sign(payload)})
    assert client.post("/_cc/api/delete", json={"password": "wrong-password"}).status_code == 403
    assert client.post("/_cc/api/delete", json={"password": "password123"}).json() == {"ok": True}
    assert sb.destroyed == [user.id]
    assert app.state.db.get_user(user.id) is None
    assert client.get("/_cc/api/me").status_code == 401
    # The same email can sign up again from scratch.
    signup(client)


# ── idle reaper (SandboxManager with a fake Docker) ──────────────────────

class ReaperDocker:
    def __init__(self, uids):
        self.uids, self.stopped = uids, []

    async def list(self, label):
        return [{"State": "running", "Labels": {"cc.user": str(u)}} for u in self.uids]

    async def inspect(self, name):
        return {"State": {"Running": True}, "Config": {"Labels": {"cc.user": name[4:]}},
                "NetworkSettings": {}}

    async def stop(self, name, timeout=10):
        self.stopped.append(name)


def test_reaper_grace_busy_and_idle(tmp_path):
    s = Settings(secret=SECRET, fernet_key=Fernet.generate_key().decode(),
                 db_url=f"sqlite:///{tmp_path}/r.db", sandbox_idle_minutes=1)
    from ccloud.db import Database
    docker = ReaperDocker([1, 2])
    mgr = SandboxManager(s, Database(s.db_url), KeyBox(s.fernet_key), docker=docker)

    async def busy(uid, base):
        return uid == 2
    mgr._busy = busy

    async def run():
        assert await mgr.reap_idle() == []            # first sighting: clock starts
        mgr._last_seen = {1: time.time() - 120, 2: time.time() - 120}
        return await mgr.reap_idle()
    assert asyncio.run(run()) == [1]                   # 2 is mid-task, kept
    assert docker.stopped == ["cc-u1"]
