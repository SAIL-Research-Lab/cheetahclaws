"""WebFetch SSRF guard: private / loopback / link-local / metadata
destinations are refused on every hop unless explicitly allowed."""
from __future__ import annotations

import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cheetahclaws.kernel.tools.fetch_tool import is_private_ip, resolve_host_ips
from cheetahclaws.tools import web as web_mod
from cheetahclaws.tools.web import _webfetch


def _fake_httpx(monkeypatch, responses, calls):
    it = iter(responses)

    def stream(*args, **kwargs):
        calls.append(args[1])
        return next(it)

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(stream=stream))


class _Resp:
    def __init__(self, status=200, location=None, body=b"ok", url=""):
        self.status_code = status
        self.headers = {"content-type": "text/plain"}
        if location:
            self.headers["location"] = location
        self.encoding = "utf-8"
        self.url = url
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def raise_for_status(self):
        return None

    def iter_raw(self):
        yield self._body


def _dns(monkeypatch, table):
    monkeypatch.setattr(web_mod, "_resolve_host_ips",
                        lambda host: table.get(host) or resolve_host_ips(host))


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://100.100.100.200/latest/meta-data/",
    "http://0.0.0.0/",
])
def test_private_destinations_are_refused(monkeypatch, url):
    calls = []
    _fake_httpx(monkeypatch, [_Resp()], calls)
    monkeypatch.delenv("CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE", raising=False)
    out = _webfetch(url)
    assert out.startswith("Error: WebFetch refused")
    assert "webfetch_allow_private" in out          # tells the user the way out
    assert calls == []                               # nothing was sent


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/admin",
    "http://localhost/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
])
def test_loopback_allowed_by_default_but_can_be_disabled(monkeypatch, url):
    calls = []
    _fake_httpx(monkeypatch, [_Resp(body=b"dev")], calls)
    monkeypatch.delenv("CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE", raising=False)
    monkeypatch.delenv("CHEETAHCLAWS_WEBFETCH_ALLOW_LOOPBACK", raising=False)
    _dns(monkeypatch, {"localhost": ["127.0.0.1", "::1"]})
    assert _webfetch(url) == "dev"
    out = _webfetch(url, config={"webfetch_allow_loopback": False})
    assert out.startswith("Error: WebFetch refused")
    monkeypatch.setenv("CHEETAHCLAWS_WEBFETCH_ALLOW_LOOPBACK", "0")
    assert _webfetch(url).startswith("Error: WebFetch refused")
    assert len(calls) == 1


def test_redirect_from_public_into_loopback_is_refused(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [
        _Resp(302, "http://127.0.0.1:6379/", url="https://public.example/x"),
        _Resp(body=b"LOCAL"),
    ], calls)
    _dns(monkeypatch, {"public.example": ["93.184.216.34"]})
    out = _webfetch("https://public.example/x")
    assert out.startswith("Error: WebFetch refused a redirect")
    assert calls == ["https://public.example/x"]


def test_loopback_may_redirect_within_loopback_only(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [
        _Resp(302, "/login", url="http://127.0.0.1:3000/"),
        _Resp(body=b"page"),
    ], calls)
    assert _webfetch("http://127.0.0.1:3000/") == "page"
    calls.clear()
    _fake_httpx(monkeypatch, [
        _Resp(302, "http://10.0.0.5/", url="http://127.0.0.1:3000/"),
        _Resp(body=b"LAN"),
    ], calls)
    assert _webfetch("http://127.0.0.1:3000/").startswith("Error: WebFetch refused")


def test_a_name_with_any_private_answer_is_refused(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [_Resp()], calls)
    _dns(monkeypatch, {"rebind.example": ["93.184.216.34", "127.0.0.1"]})
    assert _webfetch("https://rebind.example/").startswith("Error: WebFetch refused")
    assert calls == []


def test_redirect_into_a_private_address_is_refused(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [
        _Resp(302, "http://169.254.169.254/latest/meta-data/",
              url="https://public.example/start"),
        _Resp(body=b"SECRET"),
    ], calls)
    _dns(monkeypatch, {"public.example": ["93.184.216.34"]})
    out = _webfetch("https://public.example/start")
    assert out.startswith("Error: WebFetch refused")
    assert "SECRET" not in out
    assert calls == ["https://public.example/start"]


def test_public_destinations_still_work(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [_Resp(body=b"hello")], calls)
    _dns(monkeypatch, {"public.example": ["93.184.216.34"]})
    assert _webfetch("https://public.example/") == "hello"


def test_non_http_schemes_are_refused(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [_Resp()], calls)
    assert _webfetch("file:///etc/passwd").startswith("Error: WebFetch only fetches http(s)")
    assert calls == []


def test_allow_private_escape_hatch(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [_Resp(body=b"internal"), _Resp(body=b"env")], calls)
    assert _webfetch("http://127.0.0.1:9/", config={"webfetch_allow_private": True}) == "internal"
    monkeypatch.setenv("CHEETAHCLAWS_WEBFETCH_ALLOW_PRIVATE", "1")
    assert _webfetch("http://127.0.0.1:9/") == "env"


def test_host_allowlist_escape_hatch(monkeypatch):
    calls = []
    _fake_httpx(monkeypatch, [_Resp(body=b"wiki"), _Resp(body=b"sub")], calls)
    _dns(monkeypatch, {"wiki.corp": ["10.1.2.3"], "a.internal.example": ["10.9.9.9"],
                       "other.corp": ["10.1.2.4"]})
    cfg = {"webfetch_allowed_hosts": ["wiki.corp", ".internal.example"]}
    assert _webfetch("http://wiki.corp/page", config=cfg) == "wiki"
    assert _webfetch("http://a.internal.example/", config=cfg) == "sub"
    assert _webfetch("http://other.corp/", config=cfg).startswith("Error: WebFetch refused")


def test_real_async_transport_is_guarded_too():
    """The production httpx AsyncClient path enforces the same check."""
    pytest.importorskip("httpx")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"hi")

        def log_message(self, *_a):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        off = {"webfetch_allow_loopback": False}
        assert _webfetch(url, config=off).startswith("Error: WebFetch refused")
        assert _webfetch(url) == "hi"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("ip,expected", [
    ("::ffff:127.0.0.1", True),
    ("::ffff:8.8.8.8", False),
    ("100.64.0.1", True),
    ("fe80::1%eth0", True),
    ("93.184.216.34", False),
])
def test_shared_ip_classifier(ip, expected):
    assert is_private_ip(ip) is expected
