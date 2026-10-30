"""Security tests for the web server: origin policy helpers, the --no-auth
launch token, and secret redaction.

The --no-auth tests run the server in a subprocess (with an isolated HOME)
because server state is module-global and tests/test_web_api.py already
runs an authenticated server in-process.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

if platform.system() == "Windows":
    pytest.skip("web server tests need PTY support", allow_module_level=True)

httpx = pytest.importorskip("httpx")

_ROOT = Path(__file__).resolve().parent.parent


# ── Origin policy (pure helpers) ─────────────────────────────────────────


@pytest.fixture
def srv(monkeypatch):
    from cheetahclaws.web import server as _srv
    monkeypatch.setattr(_srv, "_web_settings", {
        "allowed_origins": frozenset(), "open_registration": False,
        "public_metrics": False, "nonadmin_privileged": False,
    })
    return _srv


@pytest.mark.parametrize("origin,headers,ok", [
    ("", {"host": "127.0.0.1:8080"}, True),                       # non-browser
    ("http://127.0.0.1:8080", {"host": "127.0.0.1:8080"}, True),  # same origin
    ("http://LOCALHOST:8080/", {"host": "localhost:8080"}, True),
    ("http://127.0.0.1:9999", {"host": "127.0.0.1:8080"}, False),  # other port
    ("http://evil.example", {"host": "127.0.0.1:8080"}, False),
    ("null", {"host": "127.0.0.1:8080"}, False),                   # sandboxed
    ("file://", {"host": "127.0.0.1:8080"}, False),
    ("https://claws.example.com", {"host": "claws.example.com"}, True),
    ("https://claws.example.com", {"host": "claws.example.com:443"}, True),
    ("http://claws.example.com", {"host": "claws.example.com:443"}, False),
    # Reverse proxy that rewrites Host but forwards the original.
    ("https://claws.example.com",
     {"host": "127.0.0.1:8080", "x-forwarded-host": "claws.example.com"},
     True),
    ("http://[::1]:8080", {"host": "[::1]:8080"}, True),
])
def test_origin_allowed(srv, origin, headers, ok):
    assert srv._origin_allowed(origin, headers) is ok


def test_origin_allowlist(srv):
    srv._web_settings["allowed_origins"] = srv._parse_origin_list(
        "https://ui.example.com/ , http://Other.example:3000")
    h = {"host": "127.0.0.1:8080"}
    assert srv._origin_allowed("https://ui.example.com", h)
    assert srv._origin_allowed("http://other.example:3000", h)
    assert not srv._origin_allowed("https://ui.example.com:8443", h)


def test_cors_origin_only_echoes_allowed(srv):
    srv._req_ctx.headers = {"host": "127.0.0.1:8080"}
    try:
        assert srv._cors_origin("http://evil.example") == ""
        assert srv._cors_origin("http://127.0.0.1:8080") == \
            "http://127.0.0.1:8080"
    finally:
        srv._req_ctx.headers = {}


def test_load_web_settings_merges_env_and_kwarg(srv, monkeypatch):
    monkeypatch.setenv("CHEETAHCLAWS_WEB_ALLOWED_ORIGINS",
                       "https://a.example,https://b.example")
    s = srv._load_web_settings(["https://c.example"])
    assert {"https://a.example", "https://b.example",
            "https://c.example"} <= s["allowed_origins"]


def test_launch_token_check(srv, monkeypatch):
    monkeypatch.setattr(srv, "_server_no_auth", True)
    monkeypatch.setattr(srv, "_server_launch_token", "tok123")
    assert not srv._check_auth()
    assert not srv._check_auth(body_token="nope")
    assert srv._check_auth(body_token="tok123")
    assert srv._check_auth(query="a=1&token=tok123")
    assert srv._check_auth(cookie_str="x=1; cclaunch=tok123")
    assert srv._jwt_user_id("cclaunch=tok123") == 1
    assert srv._jwt_user_id("") is None
    # Gate disabled (web_no_auth_require_token: false) → legacy open mode.
    monkeypatch.setattr(srv, "_server_launch_token", None)
    assert srv._check_auth()
    assert srv._jwt_user_id("") == 1


def test_pty_session_has_io_methods():
    # Regression: write/resize/close were accidentally nested inside
    # _check_pty_owner, so the SSE terminal fallback crashed.
    from cheetahclaws.web.server import _PtySession
    for name in ("write", "resize", "close"):
        assert callable(getattr(_PtySession, name, None)), name


def test_redact_secrets():
    from cheetahclaws.web.api import _redact_secrets
    cfg = {"anthropic_api_key": "sk-ant-abcdefgh1234",
           "telegram_token": "999:XYZXYZXYZ", "model": "claude-x",
           "short_api_key": "abc"}
    out = _redact_secrets(
        "key=sk-ant-abcdefgh1234 tg=999:XYZXYZXYZ model=claude-x abc", cfg)
    assert "sk-ant" not in out and "XYZXYZ" not in out
    assert "claude-x" in out and out.endswith("abc")


# ── --no-auth launch token, end to end ────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_noauth(tmp_path: Path, config: dict | None = None):
    home = tmp_path / "home"
    (home / ".cheetahclaws").mkdir(parents=True)
    if config is not None:
        (home / ".cheetahclaws" / "config.json").write_text(json.dumps(config))
    env = {k: v for k, v in os.environ.items()
           if k != "CHEETAHCLAWS_WEB_SERVER"}
    env.update({
        "HOME": str(home),
        "PYTHONPATH": str(_ROOT),
        "CHEETAHCLAWS_WEB_DB": str(tmp_path / "web.db"),
        "CHEETAHCLAWS_WEB_SECRET": "test-secret-do-not-use-in-prod-xx",
        "CHEETAHCLAWS_LOG_LEVEL": "WARNING",
        "PYTHONUNBUFFERED": "1",
    })
    port = _free_port()
    code = ("from cheetahclaws.web.server import start_web_server; "
            f"start_web_server(port={port}, host='127.0.0.1', no_auth=True)")
    proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    deadline = time.monotonic() + 30
    ready = None
    seen = []
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        seen.append(line)
        m = re.search(r"http://localhost:(\d+)/chat(?:\?token=([\w-]+))?",
                      line)
        if m:
            ready = m
            break
    if ready is None:
        proc.kill()
        raise RuntimeError("server not ready:\n" + "".join(seen))
    return proc, f"http://127.0.0.1:{ready.group(1)}", ready.group(2)


@pytest.fixture
def noauth_server(tmp_path):
    proc, base, token = _start_noauth(tmp_path)
    yield base, token
    proc.kill()
    proc.wait(timeout=5)


def test_noauth_requires_launch_token(noauth_server):
    base, token = noauth_server
    assert token and len(token) >= 32
    with httpx.Client(base_url=base, follow_redirects=False,
                      timeout=5) as c:
        assert c.get("/health").status_code == 200
        r = c.get("/chat")
        assert r.status_code == 401
        assert "web_no_auth_require_token" in r.text
        assert c.get("/").status_code == 401
        assert c.get("/chat?token=wrong").status_code == 401
        assert c.get("/api/sessions").status_code == 401

        r = c.get(f"/chat?token={token}")
        assert r.status_code == 302
        assert r.headers["location"] == "/chat"
        assert "cclaunch=" in r.headers["set-cookie"]
        assert "HttpOnly" in r.headers["set-cookie"]
        # The client now carries the cookie.
        assert c.get("/chat").status_code == 200
        assert c.get("/").status_code == 200
        assert c.get("/api/sessions").status_code == 200


def test_noauth_ws_without_token_is_refused(noauth_server):
    base, token = noauth_server
    host_port = base.split("//", 1)[1]
    host, port = host_port.split(":")

    def _upgrade(origin: str, cookie: str = "") -> socket.socket:
        s = socket.create_connection((host, int(port)), timeout=5)
        s.sendall((
            f"GET /ws HTTP/1.1\r\nHost: {host_port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n"
            + (f"Cookie: {cookie}\r\n" if cookie else "") + "\r\n"
        ).encode())
        return s

    # A foreign website is rejected before the handshake.
    with _upgrade("http://evil.example") as s:
        assert s.recv(4096).startswith(b"HTTP/1.1 403")

    # Same origin but no token: first-frame auth fails, no PTY.
    with _upgrade(base) as s:
        assert s.recv(4096).startswith(b"HTTP/1.1 101")
        # masked text frame: {"type":"auth","token":""}
        payload = b'{"type":"auth","token":""}'
        mask = b"\x00\x00\x00\x00"
        s.sendall(bytes([0x81, 0x80 | len(payload)]) + mask + payload)
        data = s.recv(4096)
        assert b"auth required" in data


def test_noauth_token_gate_can_be_disabled(tmp_path):
    proc, base, token = _start_noauth(
        tmp_path, config={"web_no_auth_require_token": False})
    try:
        assert token is None
        assert httpx.get(f"{base}/chat", timeout=5).status_code == 200
    finally:
        proc.kill()
        proc.wait(timeout=5)
