"""Phone pairing (--lan) and installable-app (PWA) endpoints of the web UI.

The server runs in a subprocess with an isolated HOME, like the --no-auth
tests in test_web_security.py, because server state is module-global.
"""
from __future__ import annotations

import json
import os
import platform
import re
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

if platform.system() == "Windows":
    pytest.skip("web server tests need PTY support", allow_module_level=True)

httpx = pytest.importorskip("httpx")

_ROOT = Path(__file__).resolve().parent.parent


# ── pure helpers ─────────────────────────────────────────────────────────


def test_pair_token_persisted_0600(tmp_path, monkeypatch):
    from cheetahclaws.web import pairing
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CHEETAHCLAWS_PAIR_TOKEN", raising=False)
    monkeypatch.setattr(pairing.Path, "home", lambda: tmp_path)
    tok = pairing.load_or_create_pair_token()
    path = tmp_path / ".cheetahclaws" / "web_pair_token"
    assert len(tok) >= 32 and path.read_text() == tok
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert pairing.load_or_create_pair_token() == tok      # stable
    new = pairing.reset_pair_token()
    assert new != tok and pairing.load_or_create_pair_token() == new


def test_pair_token_refuses_world_readable(tmp_path, monkeypatch):
    from cheetahclaws.web import pairing
    monkeypatch.delenv("CHEETAHCLAWS_PAIR_TOKEN", raising=False)
    monkeypatch.setattr(pairing.Path, "home", lambda: tmp_path)
    path = tmp_path / ".cheetahclaws" / "web_pair_token"
    path.parent.mkdir(parents=True)
    path.write_text("x" * 40)
    path.chmod(0o644)
    with pytest.raises(RuntimeError, match="chmod 600"):
        pairing.load_or_create_pair_token()


@pytest.mark.parametrize("ip,kind", [
    ("192.168.1.20", "lan"), ("10.0.0.5", "lan"), ("172.16.3.4", "lan"),
    ("100.101.102.103", "tailscale"),
    ("127.0.0.1", None), ("169.254.1.1", None), ("8.8.8.8", None),
    ("not-an-ip", None),
])
def test_classify_addresses(ip, kind):
    from cheetahclaws.web.pairing import _classify
    assert _classify(ip) == kind


def test_device_urls_carry_token(monkeypatch):
    from cheetahclaws.web import pairing
    monkeypatch.setattr(pairing, "lan_addresses", lambda: [
        {"ip": "192.168.1.20", "kind": "lan"},
        {"ip": "100.64.0.9", "kind": "tailscale"}])
    urls = pairing.device_urls(8765, "TOK")
    assert urls[0]["url"] == "http://192.168.1.20:8765/chat?token=TOK"
    assert urls[1]["label"].startswith("Tailscale")
    assert pairing.device_urls(8765, None)[0]["url"].endswith("/chat")


def test_manifest_is_installable():
    from cheetahclaws.web.pairing import manifest
    m = manifest()
    assert m["display"] == "standalone" and m["start_url"] == "/chat"
    sizes = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i["purpose"] == "maskable" for i in m["icons"])
    web = _ROOT / "cheetahclaws" / "web"
    for icon in m["icons"]:
        assert (web / icon["src"].lstrip("/")).is_file(), icon["src"]


# ── end to end ───────────────────────────────────────────────────────────


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start(tmp_path: Path, *, lan: bool, pair_token: str | None = None):
    home = tmp_path / "home"
    (home / ".cheetahclaws").mkdir(parents=True)
    if pair_token:
        p = home / ".cheetahclaws" / "web_pair_token"
        p.write_text(pair_token)
        p.chmod(0o600)
    env = {k: v for k, v in os.environ.items()
           if k not in ("CHEETAHCLAWS_WEB_SERVER", "CHEETAHCLAWS_PAIR_TOKEN")}
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
            f"start_web_server(port={port}, host='127.0.0.1', no_auth=True, "
            f"lan={lan!r})")
    proc = subprocess.Popen([sys.executable, "-c", code], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    deadline = time.monotonic() + 30
    seen, launch = [], None
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            break
        seen.append(line)
        m = re.search(r"localhost:\d+/chat\?token=([\w-]+)", line)
        if m:
            launch = m.group(1)
        if launch and (not lan or "/pair" in line):
            break
    if launch is None:
        proc.kill()
        raise RuntimeError("server not ready:\n" + "".join(seen))
    pair = None
    tok_file = home / ".cheetahclaws" / "web_pair_token"
    if tok_file.exists():
        pair = tok_file.read_text().strip()
    return proc, f"http://127.0.0.1:{port}", launch, pair, "".join(seen)


@pytest.fixture
def lan_server(tmp_path):
    proc, base, launch, pair, banner = _start(tmp_path, lan=True)
    yield base, launch, pair, banner
    proc.kill()
    proc.wait(timeout=5)


def _client(base):
    return httpx.Client(base_url=base, follow_redirects=False, timeout=10)


def test_lan_banner_prints_pair_url(lan_server):
    base, launch, pair, banner = lan_server
    assert pair and len(pair) >= 32 and pair != launch
    assert f"/pair?token={launch}" in banner
    assert pair not in banner          # the persistent secret is never logged


def test_pair_token_signs_phone_in_persistently(lan_server):
    base, launch, pair, _ = lan_server
    with _client(base) as phone:
        assert phone.get("/chat").status_code == 401
        r = phone.get(f"/chat?token={pair}")
        assert r.status_code == 302 and r.headers["location"] == "/chat"
        cookie = [h for h in r.headers.get_list("set-cookie")
                  if h.startswith("cclaunch=")][0]
        assert "Max-Age=31536000" in cookie and "HttpOnly" in cookie
        assert phone.get("/chat").status_code == 200
        assert phone.get("/api/sessions").status_code == 200
        # …but a phone may not read or rotate the pairing secret.
        assert phone.get("/api/pair/info").status_code == 403


def test_launch_token_cookie_is_session_only(lan_server):
    base, launch, _, _ = lan_server
    with _client(base) as c:
        r = c.get(f"/chat?token={launch}")
        assert r.status_code == 302
        launch_cookie = [h for h in r.headers.get_list("set-cookie")
                         if h.startswith("cclaunch=")]
        assert launch_cookie and "Max-Age" not in launch_cookie[0]


def test_401_page_offers_paste_box(lan_server):
    base, *_ = lan_server
    with _client(base) as c:
        r = c.get("/chat")
        assert r.status_code == 401 and "Paste the link" in r.text


def test_pair_info_and_reset(lan_server):
    base, launch, pair, _ = lan_server
    with _client(base) as owner, _client(base) as phone:
        assert owner.get("/api/pair/info").status_code == 403
        assert owner.get(f"/pair?token={launch}").status_code == 302
        r = owner.get("/pair")
        assert r.status_code == 200 and "Connect a phone" in r.text
        info = owner.get("/api/pair/info").json()
        assert info["lan"] is True and info["mode"] == "token"
        for u in info["urls"]:
            assert u["url"].endswith(f"/chat?token={pair}")

        assert phone.get(f"/chat?token={pair}").status_code == 302
        assert phone.get("/chat").status_code == 200

        # Reset needs the CSRF double-submit like every other POST.
        assert owner.post("/api/pair/reset").status_code == 403
        csrf = owner.cookies.get("ccsrf")
        assert csrf
        r = owner.post("/api/pair/reset", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        # The old pairing is dead: the phone's cookie no longer works.
        assert phone.get("/chat").status_code == 401
        assert phone.get(f"/chat?token={pair}").status_code == 401


def test_manifest_start_url_only_for_paired_phone(lan_server):
    base, launch, pair, _ = lan_server
    with _client(base) as anon:
        r = anon.get("/manifest.webmanifest")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/manifest+json")
        assert r.json()["start_url"] == "/chat"
    with _client(base) as owner:
        owner.get(f"/chat?token={launch}")
        assert owner.get("/manifest.webmanifest").json()["start_url"] == "/chat"
    with _client(base) as phone:
        phone.get(f"/chat?token={pair}")
        m = phone.get("/manifest.webmanifest")
        assert m.json()["start_url"] == f"/chat?token={pair}"
        assert "no-store" in m.headers.get("cache-control", "")


def test_pwa_assets_served(lan_server):
    base, *_ = lan_server
    with _client(base) as c:
        sw = c.get("/sw.js")
        assert sw.status_code == 200 and "offline.html" in sw.text
        assert c.get("/offline.html").status_code == 200
        assert c.get("/static/icons/icon-512.png").headers[
            "content-type"] == "image/png"
        assert c.get("/static/js/vendor/qrcode.js").status_code == 200


def test_pair_token_ignored_without_lan(tmp_path):
    proc, base, launch, pair, _ = _start(
        tmp_path, lan=False, pair_token="p" * 43)
    try:
        with _client(base) as c:
            assert c.get(f"/chat?token={'p' * 43}").status_code == 401
            c.get(f"/chat?token={launch}")
            info = c.get("/api/pair/info").json()
            assert info["lan"] is False and info["urls"] == []
    finally:
        proc.kill()
        proc.wait(timeout=5)
