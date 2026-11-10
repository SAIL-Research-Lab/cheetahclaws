"""End-to-end test without Docker: real gateway + real CheetahClaws servers.

Per-user sandboxes are local `python -m cheetahclaws --web --no-auth`
processes instead of containers (test-only stand-in — no isolation, never use
this in production). Everything else is the real thing: gateway over HTTP,
the HTTP/SSE/WebSocket proxy, the CheetahClaws server and agent loop, the
metered model gateway and an OpenAI-compatible mock upstream.

    CC_E2E=local python -m pytest tests/e2e_local.py -q -s       (from cloud/)
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

if os.environ.get("CC_E2E") != "local":
    pytest.skip("set CC_E2E=local to run", allow_module_level=True)

import httpx
import uvicorn
import websockets
from cryptography.fernet import Fernet

from ccloud.app import create_app
from ccloud.db import Database
from ccloud.sandbox import SandboxManager
from ccloud.security import KeyBox, launch_token
from ccloud.settings import Settings

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} not up")


class _Procs:
    """Stands in for the Docker API calls the app makes directly."""

    def __init__(self, owner):
        self.owner = owner

    async def remove(self, name):
        self.owner.kill(int(name[4:]))


class LocalProcessSandbox:
    """SandboxManager look-alike that runs each user's CheetahClaws as a
    local process with its own HOME."""

    def __init__(self, s: Settings, db: Database, root: Path):
        self.real = SandboxManager(s, db, KeyBox(s.fernet_key), docker=object())
        self.s, self.db, self.root = s, db, root
        self.procs: dict[int, tuple[subprocess.Popen, int]] = {}
        self.docker = _Procs(self)
        self.starts = 0

    name = staticmethod(SandboxManager.name)

    def kill(self, uid):
        p = self.procs.pop(uid, None)
        if p:
            p[0].kill()
            p[0].wait(timeout=10)

    async def ensure_running(self, user):
        p = self.procs.get(user.id)
        if p and p[0].poll() is None:
            return f"http://127.0.0.1:{p[1]}"
        home = self.root / f"u{user.id}"
        cfg_dir = home / ".cheetahclaws"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        env_vars, model = self.real.model_setup(user)
        cfg_file = cfg_dir / "config.json"
        cfg = json.loads(cfg_file.read_text()) if cfg_file.exists() else {}
        if cfg.get("cloud_rev") != user.settings_rev:
            cfg.update({"model": model, "cloud_rev": user.settings_rev, "auto_approve": True})
            cfg_file.write_text(json.dumps(cfg))
        port = free_port()
        env = {k: v for k, v in os.environ.items()
               if not k.endswith("_API_KEY") and k not in ("CHEETAHCLAWS_WEB_SERVER", "CUSTOM_BASE_URL")}
        env.update(env_vars)
        env.update({"HOME": str(home), "PYTHONPATH": str(REPO),
                    "CHEETAHCLAWS_LAUNCH_TOKEN": launch_token(self.s.secret, user.id),
                    "CHEETAHCLAWS_WEB_DB": str(home / "web.db"),
                    "CHEETAHCLAWS_LOG_LEVEL": "WARNING", "PYTHONUNBUFFERED": "1"})
        proc = subprocess.Popen(
            [sys.executable, "-m", "cheetahclaws", "--web", "--no-auth",
             "--host", "127.0.0.1", "--port", str(port)],
            env=env, cwd=str(home), stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.procs[user.id] = (proc, port)
        self.starts += 1
        await asyncio.to_thread(wait_http, f"http://127.0.0.1:{port}/health")
        return f"http://127.0.0.1:{port}"

    async def status(self, uid):
        p = self.procs.get(uid)
        return "running" if p and p[0].poll() is None else "none"

    async def destroy(self, uid):
        self.kill(uid)

    def touch(self, uid):
        pass

    async def reap_idle(self):
        return []

    async def close(self):
        for uid in list(self.procs):
            self.kill(uid)


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cloud")
    mock_port, gw_port = free_port(), free_port()
    mock = subprocess.Popen([sys.executable, str(HERE / "mock_llm.py"), str(mock_port)])
    (tmp / "models.json").write_text(json.dumps({"models": [{
        "id": "mock", "label": "Mock", "upstream_base": f"http://127.0.0.1:{mock_port}/v1",
        "upstream_model": "mock-1", "key_env": "CC_E2E_MOCK_KEY",
        "price_in": 1.0, "price_out": 4.0, "context": 32000}]}))
    os.environ["CC_E2E_MOCK_KEY"] = "sk-mock"
    s = Settings(public_url=f"http://127.0.0.1:{gw_port}", secret="e2e-" + "x" * 44,
                 fernet_key=Fernet.generate_key().decode(), db_url=f"sqlite:///{tmp}/cloud.db",
                 models_file=str(tmp / "models.json"), signup_credit_usd=1.0,
                 internal_url=f"http://127.0.0.1:{gw_port}")
    db_holder = {}

    def make_app():
        app = create_app(s, sandbox=None, reaper=False)
        return app

    app = create_app(s, sandbox=LocalProcessSandbox(s, Database(s.db_url), tmp / "homes"),
                     reaper=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=gw_port,
                                           log_level="warning", ws="websockets"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    wait_http(f"http://127.0.0.1:{gw_port}/health")
    wait_http(f"http://127.0.0.1:{mock_port}/v1/models")
    yield f"http://127.0.0.1:{gw_port}", app
    server.should_exit = True
    t.join(timeout=10)
    mock.kill()


def _wait_reply(c, sid, timeout=90):
    deadline = time.time() + timeout
    sess = {}
    while time.time() < deadline:
        sess = c.get(f"/api/sessions/{sid}").json()
        msgs = [m for m in sess.get("messages", []) if m.get("role") == "assistant"]
        if msgs and not sess.get("busy"):
            return json.dumps(msgs[-1])
        time.sleep(0.5)
    raise AssertionError(f"no reply: {sess}")


def test_full_flow(stack):
    base, app = stack
    sb = app.state.sandbox
    c = httpx.Client(base_url=base, timeout=120, follow_redirects=False)

    # Sign up; the login page and account page are served.
    assert "Create account" in c.get("/_cc/login").text
    assert c.post("/_cc/api/register", json={"email": "e2e@example.com",
                  "password": "password123"}).status_code == 200
    assert c.get("/_cc/account").status_code == 200

    # Cold start → start page → workspace up → the full chat UI via the proxy.
    r = c.get("/chat", headers={"accept": "text/html"})
    assert r.headers["location"] == "/_cc/start?next=/chat"
    t0 = time.time()
    assert c.post("/_cc/api/workspace/start", json={}).status_code == 200
    print(f"\n   workspace start: {time.time() - t0:.1f}s")
    r = c.get("/chat", headers={"accept": "text/html"})
    assert r.status_code == 200 and 'id="prompt-input"' in r.text
    assert "cloud-account-btn" in r.text            # the chat UI's account button
    assert c.get("/_cc/api/me").json()["balance_usd"] == 1.0

    # Real prompt: CheetahClaws agent → our metered gateway → mock upstream.
    c.get("/api/sessions")                         # sandbox sets its CSRF cookie
    r = c.post("/api/prompt", json={"prompt": "Say hello"},
               headers={"X-CSRF-Token": c.cookies.get("ccsrf"), "Origin": base})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert "Hello from the mock model" in _wait_reply(c, sid)
    me = c.get("/_cc/api/me").json()
    usage = c.get("/_cc/api/usage").json()["usage"]
    assert usage and usage[0]["model"] == "mock"
    calls = len(usage)
    # Each call: 1200 in × $1/M + 300 out × $4/M = $0.0024
    assert abs(me["balance_usd"] - (1 - 0.0024 * calls)) < 1e-6, (me, usage)
    print(f"   billed {calls} model call(s); balance ${me['balance_usd']}")

    # WebSocket through the proxy: the chat event stream accepts a session.
    async def ws_check():
        uri = base.replace("http://", "ws://") + "/api/events"
        cookie = "; ".join(f"{k}={v}" for k, v in c.cookies.items())
        async with websockets.connect(uri, additional_headers={"Cookie": cookie},
                                      origin=base) as ws:
            await ws.send(json.dumps({"session_id": sid}))
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                return "ok" if msg is not None else "none"
            except asyncio.TimeoutError:
                return "open"                       # connected, nothing to replay
    assert asyncio.run(ws_check()) in ("ok", "open")

    # Out of credits: the agent gets a clear error, nothing is forwarded.
    app.state.db.update_user(1, balance_micro=0)
    r = c.post("/api/prompt", json={"prompt": "again", "session_id": sid},
               headers={"X-CSRF-Token": c.cookies.get("ccsrf"), "Origin": base})
    assert r.status_code == 200
    time.sleep(2)
    deadline = time.time() + 60
    while time.time() < deadline and c.get(f"/api/sessions/{sid}").json().get("busy"):
        time.sleep(0.5)
    assert len(c.get("/_cc/api/usage").json()["usage"]) == calls   # no new charge
    tail = json.dumps(c.get(f"/api/sessions/{sid}").json().get("messages", [])[-2:])
    assert "out of CheetahClaws credits" in tail      # the user is told why

    # Switch to own key: sandbox restarts with it; chats are kept.
    starts = sb.starts
    assert c.post("/_cc/api/settings", json={
        "model_mode": "byok", "byok_provider": "deepseek", "byok_model": "deepseek-chat",
        "byok_key": "sk-user-own"}).status_code == 200
    assert c.post("/_cc/api/workspace/start", json={}).status_code == 200
    assert sb.starts == starts + 1
    cfg = json.loads((sb.root / "u1" / ".cheetahclaws" / "config.json").read_text())
    assert cfg["model"] == "deepseek/deepseek-chat"
    assert any(x["id"] == sid for x in c.get("/api/sessions").json()["sessions"])

    # Delete account.
    assert c.post("/_cc/api/delete", json={"password": "password123"}).status_code == 200
    assert c.get("/_cc/api/me").status_code == 401
    assert 1 not in sb.procs
