"""End-to-end HTTP tests for the web UI API.

Spins the stdlib server up once per test session on a random port, then runs
each test against a freshly-truncated database. Uses httpx (already in deps)
for the client. No mocks — the server, DB, JWT, and bcrypt are all real.

Run with:  pytest tests/test_web_api.py -v
"""
from __future__ import annotations

import contextlib
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import pytest
import platform

if platform.system() == "Windows":
    pytest.skip("Web API tests are not supported on Windows due to PTY requirements", allow_module_level=True)

# Make the project root importable so `from web import ...` works
_PKG = Path(__file__).resolve().parent.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_ready(url: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code in (200, 503):
                return
        except httpx.HTTPError as exc:
            last_err = exc
        time.sleep(0.05)
    raise RuntimeError(f"server never became ready: {last_err}")


@pytest.fixture(scope="session")
def server_url() -> str:
    """Start the web server in a background thread for the test session."""
    tmpdir = tempfile.mkdtemp(prefix="cc_test_")
    db_path = os.path.join(tmpdir, "test.db")
    secret_path = os.path.join(tmpdir, "secret")
    # Set env BEFORE importing server so init reads the right paths
    os.environ["CHEETAHCLAWS_WEB_DB"] = db_path
    os.environ["CHEETAHCLAWS_WEB_SECRET"] = "test-secret-do-not-use-in-prod"
    os.environ["CHEETAHCLAWS_LOG_LEVEL"] = "WARNING"  # quiet during tests

    from cheetahclaws.web.server import start_web_server  # noqa: WPS433

    port = _free_port()
    threading.Thread(
        target=start_web_server,
        kwargs={"port": port, "host": "127.0.0.1", "no_auth": False},
        daemon=True,
    ).start()
    base = f"http://127.0.0.1:{port}"
    _wait_for_ready(f"{base}/health")
    return base


@pytest.fixture(autouse=True)
def fresh_db():
    """Truncate all tables between tests so each starts empty."""
    from cheetahclaws.web.db import init_db, _engine  # noqa: WPS433
    from cheetahclaws.web.models import Base
    init_db()
    # _engine is a module global set by init_db
    from cheetahclaws.web import db as _dbmod
    eng = _dbmod._engine
    assert eng is not None
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    # Also wipe the in-memory ChatSession cache so stale objects don't survive
    from cheetahclaws.web import api as _apimod
    _apimod._chat_sessions.clear()
    yield


@pytest.fixture(autouse=True)
def default_web_settings(monkeypatch):
    """Pin the security knobs to their defaults, whatever the developer's
    ~/.cheetahclaws/config.json says; tests flip individual keys."""
    from cheetahclaws.web import server as _srv
    monkeypatch.setattr(_srv, "_web_settings", {
        "allowed_origins": frozenset(),
        "open_registration": False,
        "public_metrics": False,
        "nonadmin_privileged": False,
        "require_launch_token": True,
    })
    yield _srv._web_settings


@pytest.fixture
def open_registration(default_web_settings):
    """Multi-user tests that self-register several accounts."""
    default_web_settings["open_registration"] = True


def _csrf_request_hook(request):
    """Echo the ccsrf cookie back as X-CSRF-Token on state-changing requests.

    Mirrors what the browser does via the patched window.fetch in
    web/static/js/csrf.js.
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    cookie_hdr = request.headers.get("cookie", "")
    for part in cookie_hdr.split(";"):
        part = part.strip()
        if part.startswith("ccsrf="):
            request.headers["X-CSRF-Token"] = part[len("ccsrf="):]
            return


def _client(base: str) -> httpx.Client:
    return httpx.Client(base_url=base, timeout=5.0, follow_redirects=False,
                        event_hooks={"request": [_csrf_request_hook]})


def _register(c: httpx.Client, username: str, password: str = "secret123"):
    return c.post("/api/auth/register",
                  json={"username": username, "password": password})


def _login(c: httpx.Client, username: str, password: str = "secret123"):
    return c.post("/api/auth/login",
                  json={"username": username, "password": password})


# ── Tests ────────────────────────────────────────────────────────────────


def test_health_returns_ok(server_url):
    with _client(server_url) as c:
        r = c.get("/health")
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["db"] == "ok"
        assert d["uptime_s"] >= 0


def test_metrics_prometheus_format(server_url):
    with _client(server_url) as c:
        _register(c, "alice")  # /metrics requires auth by default
        r = c.get("/metrics")
        assert r.status_code == 200
        body = r.text
        assert "cheetahclaws_uptime_seconds " in body
        assert "cheetahclaws_requests_total " in body
        assert "# TYPE cheetahclaws_requests_total counter" in body


def test_bootstrap_empty_then_after_register(server_url):
    with _client(server_url) as c:
        assert c.get("/api/auth/bootstrap").json() == {
            "has_users": False, "no_auth": False, "open_registration": True,
        }
        r = _register(c, "alice")
        assert r.status_code == 200
        assert c.get("/api/auth/bootstrap").json()["has_users"] is True


def test_first_user_is_admin_second_is_not(server_url, open_registration):
    with _client(server_url) as c:
        u1 = _register(c, "alice").json()["user"]
        # Different client so the cookie from register doesn't leak
        with _client(server_url) as c2:
            u2 = _register(c2, "bob").json()["user"]
        assert u1["is_admin"] is True
        assert u2["is_admin"] is False


def test_register_short_password_400(server_url):
    with _client(server_url) as c:
        r = c.post("/api/auth/register",
                   json={"username": "alice", "password": "12345"})
        assert r.status_code == 400


def test_register_duplicate_username_409(server_url, open_registration):
    with _client(server_url) as c:
        _register(c, "alice")
        with _client(server_url) as c2:
            r = _register(c2, "alice")
            assert r.status_code == 409


def test_login_wrong_password_401(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        with _client(server_url) as c2:
            r = _login(c2, "alice", "WRONG")
            assert r.status_code == 401


def test_whoami_without_cookie_401(server_url):
    with _client(server_url) as c:
        assert c.get("/api/auth/whoami").status_code == 401


def test_register_then_whoami(server_url):
    with _client(server_url) as c:
        _register(c, "alice")  # cookie persists in this client
        r = c.get("/api/auth/whoami")
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "alice"


def test_logout_clears_cookie(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        assert c.get("/api/auth/whoami").status_code == 200
        c.post("/api/auth/logout")
        # The Set-Cookie max-age=0 should clear the cookie in this client
        assert c.get("/api/auth/whoami").status_code == 401


def test_sessions_list_empty(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        r = c.get("/api/sessions")
        assert r.status_code == 200
        assert r.json() == {"sessions": []}


def test_create_session_via_prompt(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        r = c.post("/api/prompt",
                   json={"prompt": "", "session_id": ""})
        assert r.status_code == 200
        sid = r.json()["session_id"]
        assert len(sid) >= 8
        ls = c.get("/api/sessions").json()["sessions"]
        assert len(ls) == 1
        assert ls[0]["id"] == sid


def test_web_config_gets_and_updates_tool_profile(server_url):
    with _client(server_url) as c:
        _register(c, "profile-user")
        sid = c.post("/api/prompt", json={"prompt": "", "session_id": ""}).json()["session_id"]

        before = c.get(f"/api/config?sid={sid}")
        assert before.status_code == 200
        assert before.json()["tool_profile"] == "full"

        updated = c.patch(
            "/api/config", json={"session_id": sid, "config": {"tool_profile": "research"}},
        )
        assert updated.status_code == 200
        assert updated.json()["tool_profile"] == "research"
        assert c.get(f"/api/config?sid={sid}").json()["tool_profile"] == "research"

        invalid = c.patch(
            "/api/config", json={"session_id": sid, "config": {"tool_profile": "invalid"}},
        )
        assert invalid.status_code == 400


def test_rename_session(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = c.patch(f"/api/sessions/{sid}", json={"title": "My Project Notes"})
        assert r.status_code == 200
        assert r.json()["title"] == "My Project Notes"
        ls = c.get("/api/sessions").json()["sessions"]
        assert ls[0]["title"] == "My Project Notes"


def test_rename_requires_title(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = c.patch(f"/api/sessions/{sid}", json={"title": "  "})
        assert r.status_code == 400


def test_delete_session(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = c.request("DELETE", f"/api/sessions/{sid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert c.get("/api/sessions").json()["sessions"] == []


def test_export_session_markdown(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = c.get(f"/api/sessions/{sid}/export")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert sid in r.text
        assert "# " in r.text  # has a heading


def test_batch_delete_sessions(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sids = [
            c.post("/api/prompt",
                   json={"prompt": "", "session_id": ""}).json()["session_id"]
            for _ in range(3)
        ]
        # Delete first two
        r = c.post("/api/sessions/batch_delete", json={"ids": sids[:2]})
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 2
        assert body["failed"] == []
        assert body["requested"] == 2
        remaining = c.get("/api/sessions").json()["sessions"]
        assert {s["id"] for s in remaining} == {sids[2]}


def test_batch_delete_skips_other_users_sessions(server_url, open_registration):
    with _client(server_url) as ca:
        _register(ca, "alice")
        a_sid = ca.post("/api/prompt",
                        json={"prompt": "", "session_id": ""}
                        ).json()["session_id"]
    with _client(server_url) as cb:
        _register(cb, "bob")
        b_sid = cb.post("/api/prompt",
                        json={"prompt": "", "session_id": ""}
                        ).json()["session_id"]
        # Bob attempts to batch-delete Alice's session along with his own
        r = cb.post("/api/sessions/batch_delete",
                    json={"ids": [a_sid, b_sid]})
        assert r.status_code == 200
        body = r.json()
        assert body["deleted"] == 1     # only his own
        assert body["failed"] == [a_sid]
    # Alice's session still listed for Alice
    with _client(server_url) as ca:
        _login(ca, "alice")
        ls = ca.get("/api/sessions").json()["sessions"]
        assert any(s["id"] == a_sid for s in ls)


def test_batch_export_sessions_markdown(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sids = [
            c.post("/api/prompt",
                   json={"prompt": "", "session_id": ""}).json()["session_id"]
            for _ in range(2)
        ]
        c.patch(f"/api/sessions/{sids[0]}", json={"title": "First Topic"})
        c.patch(f"/api/sessions/{sids[1]}", json={"title": "Second Topic"})
        r = c.post("/api/sessions/batch_export", json={"ids": sids})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/markdown")
        assert "Chat Export" in r.text
        assert "First Topic" in r.text
        assert "Second Topic" in r.text
        for sid in sids:
            assert sid in r.text
        # Filename hints the session count
        cd = r.headers.get("content-disposition", "")
        assert "chats-2-sessions.md" in cd


def test_batch_export_empty_ids_returns_400(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        r = c.post("/api/sessions/batch_export", json={"ids": []})
        assert r.status_code == 400


def test_folder_create_list_rename_delete(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        # Create
        r = c.post("/api/folders", json={"name": "Trading"})
        assert r.status_code == 200
        f = r.json()
        assert f["name"] == "Trading"
        assert f["session_count"] == 0
        fid = f["id"]
        # List
        r = c.get("/api/folders")
        assert r.status_code == 200
        assert any(x["id"] == fid for x in r.json()["folders"])
        # Rename
        r = c.patch(f"/api/folders/{fid}", json={"name": "Crypto Trading"})
        assert r.status_code == 200
        assert r.json()["name"] == "Crypto Trading"
        # Delete
        r = c.request("DELETE", f"/api/folders/{fid}")
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert c.get("/api/folders").json()["folders"] == []


def test_folder_duplicate_name_409(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        c.post("/api/folders", json={"name": "Research"})
        r = c.post("/api/folders", json={"name": "Research"})
        assert r.status_code == 409


def test_move_session_to_folder(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        fid = c.post("/api/folders", json={"name": "Notes"}).json()["id"]
        # Move into folder
        r = c.patch(f"/api/sessions/{sid}/folder", json={"folder_id": fid})
        assert r.status_code == 200
        assert r.json()["folder_id"] == fid
        ls = c.get("/api/sessions").json()["sessions"]
        assert next(s for s in ls if s["id"] == sid)["folder_id"] == fid
        # Move out (back to ungrouped)
        r = c.patch(f"/api/sessions/{sid}/folder", json={"folder_id": None})
        assert r.status_code == 200
        assert r.json()["folder_id"] is None
        ls = c.get("/api/sessions").json()["sessions"]
        assert next(s for s in ls if s["id"] == sid)["folder_id"] is None


def test_delete_folder_preserves_sessions_as_ungrouped(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        fid = c.post("/api/folders", json={"name": "Temp"}).json()["id"]
        c.patch(f"/api/sessions/{sid}/folder", json={"folder_id": fid})
        # Delete folder
        r = c.request("DELETE", f"/api/folders/{fid}")
        assert r.status_code == 200
        # Session still listed, now ungrouped
        ls = c.get("/api/sessions").json()["sessions"]
        s = next(x for x in ls if x["id"] == sid)
        assert s["folder_id"] is None


def test_folder_cross_user_isolation(server_url, open_registration):
    with _client(server_url) as ca:
        _register(ca, "alice")
        a_fid = ca.post("/api/folders",
                        json={"name": "AlicePrivate"}).json()["id"]
        a_sid = ca.post("/api/prompt",
                        json={"prompt": "", "session_id": ""}
                        ).json()["session_id"]
    with _client(server_url) as cb:
        _register(cb, "bob")
        b_sid = cb.post("/api/prompt",
                        json={"prompt": "", "session_id": ""}
                        ).json()["session_id"]
        # Bob cannot see Alice's folder
        assert cb.get("/api/folders").json() == {"folders": []}
        # Bob cannot move his session into Alice's folder
        r = cb.patch(f"/api/sessions/{b_sid}/folder",
                     json={"folder_id": a_fid})
        assert r.status_code == 404
        # Bob cannot rename or delete Alice's folder
        assert cb.patch(f"/api/folders/{a_fid}",
                        json={"name": "BobOwned"}).status_code == 404
        assert cb.request("DELETE",
                          f"/api/folders/{a_fid}").json() == {"ok": False}
    # Alice's folder still intact
    with _client(server_url) as ca:
        _login(ca, "alice")
        folders = ca.get("/api/folders").json()["folders"]
        assert any(f["id"] == a_fid and f["name"] == "AlicePrivate"
                   for f in folders)


def test_session_list_includes_folder_id(server_url):
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        ls = c.get("/api/sessions").json()["sessions"]
        # New sessions are ungrouped
        s = next(x for x in ls if x["id"] == sid)
        assert "folder_id" in s
        assert s["folder_id"] is None


def test_reap_stale_chat_sessions_passes_user_id(server_url):
    """Regression for the daemon-thread crash where the reaper called
    remove_chat_session(sid) without user_id and the call raised
    TypeError on every cycle. Pre-fix this caused stale sessions to
    accumulate forever (the reaper thread died on first invocation)."""
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        # Force this session into the "stale + idle" state by rewinding
        # its last_active far enough that is_stale() returns True.
        from cheetahclaws.web import api as _apimod
        sess = _apimod._chat_sessions.get(sid)
        assert sess is not None, "session should be in the in-memory cache"
        import time as _time
        sess.last_active = _time.monotonic() - 1e9  # very old
        # Reaper must run cleanly — pre-fix this raised
        # TypeError: remove_chat_session() missing 1 required positional
        # argument: 'user_id'
        _apimod.reap_stale_chat_sessions()
        # And it must actually evict the session
        assert sid not in _apimod._chat_sessions


def test_cross_user_isolation(server_url, open_registration):
    with _client(server_url) as ca:
        _register(ca, "alice")
        sid = ca.post("/api/prompt",
                      json={"prompt": "", "session_id": ""}).json()["session_id"]
    with _client(server_url) as cb:
        _register(cb, "bob")
        # Bob can't see Alice's session in the list
        assert cb.get("/api/sessions").json() == {"sessions": []}
        # Bob can't fetch it directly
        assert cb.get(f"/api/sessions/{sid}").status_code == 404
        # Bob can't delete it (returns ok:false)
        assert cb.request("DELETE",
                          f"/api/sessions/{sid}").json() == {"ok": False}


def test_session_persists_in_db_after_cache_clear(server_url):
    """Session metadata survives even when in-memory cache is cleared
    (simulates a server restart while user is still logged in)."""
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        c.patch(f"/api/sessions/{sid}", json={"title": "Persistent Title"})
        # Clear in-memory cache (simulates restart)
        from cheetahclaws.web import api as _apimod
        _apimod._chat_sessions.clear()
        # Listing still works (DB-backed)
        ls = c.get("/api/sessions").json()["sessions"]
        assert len(ls) == 1
        assert ls[0]["title"] == "Persistent Title"
        # Detail fetch hydrates from DB
        d = c.get(f"/api/sessions/{sid}").json()
        assert d["title"] == "Persistent Title"


def test_auth_required_for_chat_endpoints(server_url):
    with _client(server_url) as c:
        # No cookie → all chat endpoints return 401
        assert c.get("/api/sessions").status_code == 401
        assert c.post("/api/prompt", json={}).status_code == 401
        assert c.get("/api/sessions/abc").status_code == 401
        assert c.get("/api/models").status_code == 401


def test_metrics_counters_increment(server_url, default_web_settings):
    default_web_settings["public_metrics"] = True
    with _client(server_url) as c:
        before = c.get("/metrics").text
        # Trigger a 401 and a successful registration
        c.get("/api/auth/whoami")  # 401
        _register(c, "alice")
        after = c.get("/metrics").text

        def _counter(text: str, name: str) -> int:
            for line in text.splitlines():
                if line.startswith(name + " "):
                    return int(line.split()[1])
            return -1

        assert _counter(after, "cheetahclaws_requests_total") > _counter(
            before, "cheetahclaws_requests_total")
        assert _counter(after, "cheetahclaws_requests_4xx") >= _counter(
            before, "cheetahclaws_requests_4xx") + 1
        assert _counter(after, "cheetahclaws_auth_registrations_total") >= 1


def test_cors_preflight_for_unknown_origin(server_url):
    """Preflight OPTIONS should respond 204 (server replies even without CORS)."""
    with _client(server_url) as c:
        r = c.request("OPTIONS", "/api/sessions",
                      headers={"Origin": "http://example.com",
                               "Access-Control-Request-Method": "GET"})
        assert r.status_code == 204


# ── Security: origin policy, registration, admin gating, metrics ────────


@pytest.fixture
def owner_config(monkeypatch):
    """Deterministic owner config (permission_mode=auto, no legacy escape
    hatch) regardless of the developer's ~/.cheetahclaws/config.json."""
    from cheetahclaws import config as _cfg
    real = _cfg.load_config

    def _fake():
        cfg = real()
        cfg["permission_mode"] = "auto"
        cfg["tool_profile"] = "full"
        cfg.pop("web_nonadmin_privileged", None)
        return cfg

    monkeypatch.setattr(_cfg, "load_config", _fake)
    return _fake


def _admin_and_member(server_url):
    """Register alice (admin) and have her create bob (member).

    Returns (alice_client, bob_client); caller closes them.
    """
    ca = _client(server_url)
    assert _register(ca, "alice").status_code == 200
    r = _register(ca, "bob")
    assert r.status_code == 200, r.text
    cb = _client(server_url)
    assert _login(cb, "bob").status_code == 200
    return ca, cb


@contextlib.contextmanager
def _closing(*clients):
    try:
        yield
    finally:
        for cl in clients:
            cl.close()


def _raw_ws_upgrade(server_url: str, path: str, origin: str) -> bytes:
    host_port = server_url.split("//", 1)[1]
    host, port = host_port.split(":")
    with socket.create_connection((host, int(port)), timeout=5) as s:
        s.sendall((
            f"GET {path} HTTP/1.1\r\nHost: {host_port}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n\r\n"
        ).encode())
        return s.recv(4096)


def test_registration_closed_after_first_user(server_url):
    with _client(server_url) as c:
        assert _register(c, "alice").json()["user"]["is_admin"] is True
    with _client(server_url) as c2:
        r = _register(c2, "mallory")
        assert r.status_code == 403
        assert "web_open_registration" in r.json()["error"]
        boot = c2.get("/api/auth/bootstrap").json()
        assert boot["has_users"] is True
        assert boot["open_registration"] is False


def test_admin_can_create_accounts_and_keeps_own_session(server_url):
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        # Alice is still alice — creating bob didn't swap her cookie.
        assert ca.get("/api/auth/whoami").json()["user"]["username"] == "alice"
        bob = cb.get("/api/auth/whoami").json()["user"]
        assert bob["username"] == "bob" and bob["is_admin"] is False
        # A non-admin can't create accounts either.
        assert _register(cb, "carol").status_code == 403


def test_open_registration_escape_hatch(server_url, open_registration):
    with _client(server_url) as c:
        _register(c, "alice")
    with _client(server_url) as c2:
        r = _register(c2, "bob")
        assert r.status_code == 200
        assert r.json()["user"]["is_admin"] is False


def test_metrics_requires_auth_by_default(server_url, default_web_settings):
    with _client(server_url) as c:
        assert c.get("/metrics").status_code == 401
        assert "web_public_metrics" in c.get("/metrics").json()["error"]
        _register(c, "alice")
        assert c.get("/metrics").status_code == 200
    default_web_settings["public_metrics"] = True
    with _client(server_url) as c:
        assert c.get("/metrics").status_code == 200


def test_health_is_public(server_url):
    # Docker HEALTHCHECK hits /health without any cookie.
    assert httpx.get(f"{server_url}/health").status_code == 200


def test_cross_origin_post_rejected(server_url):
    with _client(server_url) as c:
        r = c.post("/api/auth/login",
                   json={"username": "x", "password": "y"},
                   headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        assert "web_allowed_origins" in r.json()["error"]
        # Same-origin Origin passes the gate (then fails on credentials).
        r = c.post("/api/auth/login",
                   json={"username": "x", "password": "y"},
                   headers={"Origin": server_url})
        assert r.status_code == 401


def test_allowed_origins_config(server_url, default_web_settings):
    default_web_settings["allowed_origins"] = frozenset(
        {"https://ui.example.com"})
    with _client(server_url) as c:
        r = c.post("/api/auth/login",
                   json={"username": "x", "password": "y"},
                   headers={"Origin": "https://ui.example.com"})
        assert r.status_code == 401  # passed origin gate
        assert r.headers.get("access-control-allow-origin") == \
            "https://ui.example.com"


def test_cors_does_not_echo_foreign_origin(server_url):
    with _client(server_url) as c:
        r = c.get("/health", headers={"Origin": "http://evil.example"})
        assert "access-control-allow-origin" not in r.headers
        r = c.request("OPTIONS", "/api/sessions",
                      headers={"Origin": "http://evil.example",
                               "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in r.headers
        r = c.get("/health", headers={"Origin": server_url})
        assert r.headers.get("access-control-allow-origin") == server_url


@pytest.mark.parametrize("path", ["/ws", "/api/events"])
def test_cross_origin_websocket_rejected(server_url, path):
    resp = _raw_ws_upgrade(server_url, path, "http://evil.example")
    assert resp.startswith(b"HTTP/1.1 403")
    assert b"101 Switching" not in resp


def test_same_origin_websocket_still_upgrades(server_url):
    # /ws accepts the upgrade and then authenticates via the first frame.
    resp = _raw_ws_upgrade(server_url, "/ws", server_url)
    assert resp.startswith(b"HTTP/1.1 101")


def test_nonadmin_cannot_raise_permission_mode(server_url, owner_config):
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        sid = cb.post("/api/prompt",
                      json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = cb.patch("/api/config", json={
            "session_id": sid, "config": {"permission_mode": "accept-all"}})
        assert r.status_code == 403
        assert "web_nonadmin_privileged" in r.json()["error"]
        # Tightening is fine.
        r = cb.patch("/api/config", json={
            "session_id": sid, "config": {"permission_mode": "plan"}})
        assert r.status_code == 200
        assert r.json()["permission_mode"] == "plan"
        # Base URLs could redirect the owner's API keys — admin only.
        r = cb.patch("/api/config", json={
            "session_id": sid,
            "config": {"custom_base_url": "http://evil.example"}})
        assert r.status_code == 403

        a_sid = ca.post("/api/prompt",
                        json={"prompt": "", "session_id": ""}
                        ).json()["session_id"]
        r = ca.patch("/api/config", json={
            "session_id": a_sid, "config": {"permission_mode": "accept-all"}})
        assert r.status_code == 200
        assert r.json()["permission_mode"] == "accept-all"


def test_nonadmin_persisted_mode_is_clamped_on_hydrate(server_url,
                                                        owner_config):
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        sid = cb.post("/api/prompt",
                      json={"prompt": "", "session_id": ""}).json()["session_id"]
        bob_id = cb.get("/api/auth/whoami").json()["user"]["id"]
        # Simulate a session persisted before the privilege model existed.
        from cheetahclaws.web import db as _db, api as _apimod
        _db.repo.upsert_session(sid, bob_id, title="t",
                                config={"permission_mode": "accept-all"})
        _apimod._chat_sessions.clear()
        cfg = cb.get(f"/api/config?sid={sid}").json()
        assert cfg["permission_mode"] == "auto"


def test_nonadmin_privileged_slash_commands_refused(server_url, owner_config):
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        sid = cb.post("/api/prompt",
                      json={"prompt": "", "session_id": ""}).json()["session_id"]
        for cmd in ("/config", "/cwd /", "/plugin", "/mcp", "/telegram",
                    "/permissions accept-all"):
            r = cb.post("/api/prompt", json={"prompt": cmd, "session_id": sid})
            assert r.status_code == 200
            outs = " ".join(e["data"].get("output", "")
                            for e in r.json()["events"])
            assert "restricted to admin" in outs, (cmd, outs)


def test_nonadmin_escape_hatch(server_url, owner_config, monkeypatch):
    from cheetahclaws import config as _cfg

    def _legacy():
        cfg = owner_config()
        cfg["web_nonadmin_privileged"] = True
        return cfg

    monkeypatch.setattr(_cfg, "load_config", _legacy)
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        sid = cb.post("/api/prompt",
                      json={"prompt": "", "session_id": ""}).json()["session_id"]
        r = cb.patch("/api/config", json={
            "session_id": sid, "config": {"permission_mode": "accept-all"}})
        assert r.status_code == 200


def test_session_config_never_returns_secrets(server_url, monkeypatch):
    from cheetahclaws import config as _cfg
    real = _cfg.load_config
    secret = "sk-test-SUPERSECRET-0123456789"
    monkeypatch.setattr(_cfg, "load_config",
                        lambda: {**real(), "anthropic_api_key": secret,
                                 "telegram_token": "123456:ABCDEFGHIJK"})
    with _client(server_url) as c:
        _register(c, "alice")
        sid = c.post("/api/prompt",
                     json={"prompt": "", "session_id": ""}).json()["session_id"]
        for url in (f"/api/config?sid={sid}", f"/api/sessions/{sid}",
                    "/api/sessions", "/api/models"):
            body = c.get(url).text
            assert secret not in body, url
            assert "ABCDEFGHIJK" not in body, url


def test_lab_api_requires_auth(server_url):
    with _client(server_url) as c:
        assert c.get("/api/lab/runs").status_code == 401
        assert c.post("/api/lab/runs", json={}).status_code == 401


def test_lab_api_start_run_is_admin_only(server_url, owner_config):
    ca, cb = _admin_and_member(server_url)
    with _closing(ca, cb):
        r = cb.post("/api/lab/runs", json={"topic": "x"})
        assert r.status_code == 403
        assert "web_nonadmin_privileged" in r.json()["error"]
