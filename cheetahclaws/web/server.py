"""Lightweight web terminal server for CheetahClaws.

Spawns a CheetahClaws REPL in a PTY and bridges it to the browser.
Supports two transport modes on the same port:

  1. WebSocket (direct TCP connections)
  2. SSE + POST fallback (works through VS Code port forwarding
     and other HTTP-level proxies that break WebSocket upgrades)

Pure-stdlib — no Flask, no aiohttp, no external deps.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
try:
    import pty
except ImportError:
    pty = None
import secrets
import select
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

# ── Config ───────────────────────────────────────────────────────────────

DEFAULT_PORT = 8080


def _resolve_web_dir() -> Path:
    """Locate the directory containing chat.html, marked.min.js, static/, etc.

    Prefer ``importlib.resources.files("cheetahclaws.web")`` so the package's
    data files are found whichever way the package was installed (editable,
    non-editable wheel, zipapp, PEX). Fall back to ``Path(__file__).parent``
    for unusual layouts where the resource API can't return a real path.
    """
    try:
        from importlib.resources import files as _resource_files
        candidate = Path(str(_resource_files("cheetahclaws.web")))
        if candidate.is_dir():
            return candidate.resolve()
    except (ImportError, ModuleNotFoundError, TypeError,
            NotADirectoryError, FileNotFoundError):
        pass
    return Path(__file__).resolve().parent


_WEB_DIR = _resolve_web_dir()

_server_password: Optional[str] = None   # terminal (/) auth only
_server_no_auth = False
_server_cmd: list[str] = []
_chat_ui_ready = False  # set by _try_init_chat_auth after deps loaded

# --no-auth launch token. Even with auth disabled, the server only serves
# browsers that present this per-launch secret (via ?token= on the printed
# URL, which is exchanged for an HttpOnly cookie). Without it, any website
# the user visits could open ws://127.0.0.1:<port>/ws and drive the REPL.
# None = gate disabled (legacy behaviour, opt-in via config
# "web_no_auth_require_token": false).
_server_launch_token: Optional[str] = None
_LAUNCH_COOKIE = "cclaunch"

# --lan: devices on the network (phones) may connect. In --no-auth mode they
# present the persistent pairing token (web/pairing.py) instead of the
# per-launch token, so they stay paired across restarts. None = no pairing.
_server_pair_token: Optional[str] = None
_server_lan = False
_server_port = 0

# Security knobs read from ~/.cheetahclaws/config.json at startup (see
# _load_web_settings). Tests poke this dict directly.
_web_settings: dict = {
    # Extra origins (scheme://host[:port]) allowed to make cross-origin
    # requests / WS upgrades. Same-origin is always allowed.
    "allowed_origins": frozenset(),
    # After the first (admin) account exists, let anyone self-register.
    "open_registration": False,
    # Serve /metrics without auth (Prometheus scrapers).
    "public_metrics": False,
    # Let non-admin chat users run privileged commands / lab runs (legacy).
    "nonadmin_privileged": False,
    # --no-auth still demands the per-launch token (see above).
    "require_launch_token": True,
}

_register_lock = threading.Lock()

_MIME = {
    ".js": "application/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".ico": "image/vnd.microsoft.icon",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
}


def _generate_password() -> str:
    # 32 url-safe chars ≈ 190 bits of entropy — resistant to online brute force.
    return secrets.token_urlsafe(32)


class _BufferedSocket:
    """Thin wrapper that prepends leftover bytes from HTTP header parsing
    before delegating to the real socket.  Avoids monkey-patching sock.recv."""

    __slots__ = ("_sock", "_buf")

    def __init__(self, sock: socket.socket, extra: bytes = b""):
        self._sock = sock
        self._buf = extra

    def recv(self, n: int, _flags: int = 0) -> bytes:
        if self._buf:
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
            return chunk
        return self._sock.recv(n)

    def sendall(self, data: bytes) -> None:
        self._sock.sendall(data)

    def settimeout(self, t) -> None:
        self._sock.settimeout(t)

    def close(self) -> None:
        self._sock.close()


# ── PTY session registry (for SSE mode) ─────────────────────────────────

_sessions: dict[str, "_PtySession"] = {}
_sessions_lock = threading.Lock()


_SESSION_TIMEOUT = 30  # seconds before an unattached SSE session is reaped


class _PtySession:
    """A PTY session shared between SSE stream and POST input."""

    def __init__(self, owner_uid: Optional[int] = None):
        if not pty:
            raise RuntimeError("PTY is not supported on this platform")
        self.master_fd, slave_fd = pty.openpty()
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = "120"
        env["LINES"] = "30"
        env["CHEETAHCLAWS_WEB_TERMINAL"] = "1"
        self.proc = subprocess.Popen(
            _server_cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            env=env, preexec_fn=os.setsid,
        )
        os.close(slave_fd)
        self.lock = threading.Lock()
        self.closed = False
        self.created_at = time.monotonic()
        self.attached = False  # True once an SSE stream connects
        # owner_uid is None in password-only mode (all callers share the same
        # secret); when a JWT cookie is present the creator's uid is stored
        # here so subsequent /api/{stream,input,resize} calls can refuse a
        # different authenticated user who guesses the sid.
        self.owner_uid = owner_uid


    def write(self, data: bytes) -> None:
        if not self.closed:
            with self.lock:
                try:
                    os.write(self.master_fd, data)
                except OSError:
                    pass

    def resize(self, rows: int, cols: int) -> None:
        if self.closed:
            return
        try:
            import fcntl, termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            os.killpg(os.getpgid(self.proc.pid), signal.SIGWINCH)
        except (OSError, ProcessLookupError):
            pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _check_pty_owner(session: "_PtySession", cookie_str: str) -> bool:
    """Return True if the JWT-authenticated caller owns this session.

    Sessions created without a JWT cookie (password-only mode) have
    owner_uid=None and accept any authenticated caller. Sessions tagged
    with an owner_uid require the caller to present a JWT whose `sub`
    matches.
    """
    if session.owner_uid is None:
        return True
    return _jwt_user_id(cookie_str) == session.owner_uid


# ── HTML page ────────────────────────────────────────────────────────────

def _build_html(no_auth: bool = False) -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>CheetahClaws Web Terminal</title>
<link rel="icon" type="image/png" sizes="256x256" href="/static/favicon.png">
<link rel="icon" type="image/x-icon" sizes="any" href="/favicon.ico">
<link rel="apple-touch-icon" href="/static/favicon.png">
<link rel="stylesheet" href="/xterm.min.css">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0a0a0a; overflow:hidden; height:100vh; display:flex; flex-direction:column; }}
  #topbar {{
    background:#111; border-bottom:1px solid #222; padding:8px 16px;
    display:flex; align-items:center; justify-content:space-between;
    font-family:-apple-system,sans-serif; color:#888; font-size:13px;
  }}
  #topbar .logo {{ color:#22d3ee; font-weight:700; font-size:15px; }}
  #topbar .status {{ display:flex; align-items:center; gap:8px; }}
  #topbar .dot {{ width:8px; height:8px; border-radius:50%; background:#4ade80; }}
  #topbar .dot.disconnected {{ background:#f87171; }}
  #terminal {{ flex:1; }}
  #login {{
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:rgba(0,0,0,0.95); display:flex; align-items:center;
    justify-content:center; z-index:100; font-family:-apple-system,sans-serif;
  }}
  #login.hidden {{ display:none; }}
  #login form {{
    background:#111; border:1px solid #333; border-radius:12px;
    padding:2rem; width:320px; text-align:center;
  }}
  #login h2 {{ color:#22d3ee; margin-bottom:1rem; font-size:1.2rem; }}
  #login input {{
    width:100%; padding:10px; background:#1a1a1a; border:1px solid #333;
    border-radius:8px; color:#fff; font-size:1rem; margin-bottom:1rem;
    text-align:center; letter-spacing:2px;
  }}
  #login input:focus {{ outline:none; border-color:#22d3ee; }}
  #login button {{
    background:#22d3ee; color:#000; border:none; padding:10px 24px;
    border-radius:8px; font-weight:700; font-size:0.9rem; cursor:pointer; width:100%;
  }}
  #login .error {{ color:#f87171; font-size:0.85rem; margin-top:0.5rem; }}
</style>
</head>
<body>
<div id="login" class="{'hidden' if no_auth else ''}">
  <form onsubmit="doLogin(event)">
    <h2>CheetahClaws</h2>
    <input type="password" id="pwd" placeholder="Enter password" autofocus>
    <button type="submit">Connect</button>
    <div class="error" id="login-err"></div>
  </form>
</div>
<div id="topbar">
  <span class="logo">CheetahClaws Web Terminal</span>
  <span class="status">
    <span class="dot" id="status-dot"></span>
    <span id="status-text">connecting...</span>
  </span>
</div>
<div id="terminal"></div>
<script src="/static/js/csrf.js"></script>
<script src="/xterm.min.js"></script>
<script src="/addon-fit.min.js"></script>
<script src="/addon-web-links.min.js"></script>
<script>
const term = new window.Terminal({{
  cursorBlink: true, fontSize: 14,
  fontFamily: "'JetBrains Mono','Fira Code','Cascadia Code',monospace",
  theme: {{ background:'#0a0a0a', foreground:'#e4e4e7', cursor:'#22d3ee',
            selectionBackground:'rgba(34,211,238,0.3)' }},
}});
const fitAddon = new window.FitAddon.FitAddon();
term.loadAddon(fitAddon);
term.loadAddon(new window.WebLinksAddon.WebLinksAddon());
term.open(document.getElementById('terminal'));
fitAddon.fit();

let authToken = '';
let sessionId = '';
let mode = ''; // 'ws' or 'sse'
let _dataSub = null, _resizeSub = null;
function bindInput(dataFn, resizeFn) {{
  if (_dataSub) _dataSub.dispose();
  if (_resizeSub) _resizeSub.dispose();
  _dataSub = term.onData(dataFn);
  _resizeSub = term.onResize(resizeFn);
}}

function setStatus(connected, label) {{
  document.getElementById('status-dot').className = 'dot' + (connected ? '' : ' disconnected');
  document.getElementById('status-text').textContent = label || (connected ? 'connected' : 'disconnected');
}}

// ── SSE + POST fallback (works through any HTTP proxy) ──────────────

function connectSSE() {{
  mode = 'sse';
  term.clear();
  term.reset();
  setStatus(false, 'connecting (http)...');

  // Create PTY session (cookie carries auth)
  fetch('/api/session', {{
    method: 'POST',
    credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{cols: term.cols, rows: term.rows}})
  }})
  .then(r => r.json())
  .then(data => {{
    sessionId = data.session_id;

    // Open SSE stream for terminal output (cookie carries auth)
    const evtSource = new EventSource('/api/stream?sid=' + sessionId);
    evtSource.onopen = () => setStatus(true, 'connected (http)');
    evtSource.onmessage = (e) => {{
      // Data is base64-encoded binary
      const bytes = Uint8Array.from(atob(e.data), c => c.charCodeAt(0));
      term.write(bytes);
    }};
    evtSource.onerror = () => {{
      setStatus(false);
      evtSource.close();
      term.write('\\r\\n\\x1b[33m[disconnected — refresh to reconnect]\\x1b[0m\\r\\n');
    }};

    // Bind input (replaces any previous WS handlers)
    bindInput(
      d => fetch('/api/input', {{
        method: 'POST',
        credentials: 'same-origin',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{sid: sessionId, data: d}})
      }}).catch(() => {{}}),
      ({{cols, rows}}) => fetch('/api/resize', {{
        method: 'POST',
        credentials: 'same-origin',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{sid: sessionId, cols, rows}})
      }}).catch(() => {{}})
    );
  }})
  .catch(err => {{
    setStatus(false, 'connection failed');
    term.write('\\r\\n\\x1b[31m[failed to connect: ' + err.message + ']\\x1b[0m\\r\\n');
  }});
}}

// ── WebSocket (direct connections) ──────────────────────────────────

function connectWS() {{
  mode = 'ws';
  setStatus(false, 'connecting (ws)...');

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = proto + '//' + location.host + '/ws';
  const ws = new WebSocket(url);
  ws.binaryType = 'arraybuffer';

  let wsOpened = false;
  let wsAuthed = false;
  const wsTimeout = setTimeout(() => {{
    if (!wsOpened) ws.close();
  }}, 3000);

  ws.onopen = () => {{
    wsOpened = true;
    clearTimeout(wsTimeout);
    // First frame: authenticate (cookie may already suffice, but send
    // explicit auth in case cookie is not available — e.g. cross-origin).
    ws.send(JSON.stringify({{type:'auth', token:authToken}}));
    setStatus(true, 'connected (ws)');
    ws.send(JSON.stringify({{type:'resize', cols:term.cols, rows:term.rows}}));

    bindInput(
      d => {{ if (ws.readyState === 1) ws.send(d); }},
      ({{cols, rows}}) => {{ if (ws.readyState === 1) ws.send(JSON.stringify({{type:'resize', cols, rows}})); }}
    );
  }};
  ws.onmessage = (e) => {{
    if (e.data instanceof ArrayBuffer) term.write(new Uint8Array(e.data));
    else term.write(e.data);
  }};
  ws.onclose = () => {{
    clearTimeout(wsTimeout);
    if (!wsOpened) {{
      connectSSE();
    }} else {{
      setStatus(false);
      term.write('\\r\\n\\x1b[33m[disconnected — refresh to reconnect]\\x1b[0m\\r\\n');
    }}
  }};
  ws.onerror = () => {{ }};
}}

// ── Connect (try WebSocket first, fall back to SSE) ─────────────────

function connect() {{
  connectWS();
}}

window.addEventListener('resize', () => fitAddon.fit());

function doLogin(e) {{
  e.preventDefault();
  authToken = document.getElementById('pwd').value;
  const errEl = document.getElementById('login-err');
  errEl.textContent = '';
  // Authenticate via POST (sets HttpOnly cookie for subsequent requests)
  fetch('/api/auth', {{
    method: 'POST',
    credentials: 'same-origin',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{token: authToken}})
  }}).then(r => {{
    if (!r.ok) {{ errEl.textContent = 'Wrong password'; return; }}
    document.getElementById('login').classList.add('hidden');
    connect();
  }}).catch(() => {{ errEl.textContent = 'Connection error'; }});
}}

if (document.getElementById('login').classList.contains('hidden')) connect();
</script>
</body>
</html>"""


# ── Raw HTTP helpers ─────────────────────────────────────────────────────

def _recv_until(sock: socket.socket, sentinel: bytes, max_bytes: int = 65536) -> bytes:
    buf = b""
    while sentinel not in buf and len(buf) < max_bytes:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


_req_ctx = threading.local()


def _parse_origin_list(value) -> frozenset:
    """Normalise a config/env origin list (list or comma-separated str)."""
    if not value:
        return frozenset()
    if isinstance(value, str):
        value = value.split(",")
    out = set()
    for item in value:
        item = str(item).strip().lower().rstrip("/")
        if item:
            out.add(item)
    return frozenset(out)


def _host_port(netloc: str, scheme: str) -> Optional[tuple[str, int]]:
    """Parse 'host[:port]' into (host, port), defaulting port by scheme."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit("//" + netloc.strip().lower())
        host, port = u.hostname, u.port
    except ValueError:
        return None
    if not host:
        return None
    if port is None:
        port = 443 if scheme in ("https", "wss") else 80
    return host, port


def _origin_allowed(origin: str, headers: Optional[dict] = None) -> bool:
    """Is a browser request carrying this Origin allowed to talk to us?

    Allowed when the Origin header is absent (non-browser clients and
    same-origin GETs), names the same host:port the request was sent to
    (Host, or X-Forwarded-Host behind a reverse proxy — browsers cannot
    forge either on a cross-origin fetch/WebSocket), or is listed in
    ``web_allowed_origins`` / $CHEETAHCLAWS_WEB_ALLOWED_ORIGINS.
    """
    if not origin:
        return True
    norm = origin.strip().lower().rstrip("/")
    if norm in _web_settings.get("allowed_origins", ()):
        return True
    from urllib.parse import urlsplit
    try:
        u = urlsplit(norm)
    except ValueError:
        return False
    if u.scheme not in ("http", "https") or not u.netloc:
        return False  # includes the opaque "null" origin
    target = _host_port(u.netloc, u.scheme)
    if target is None:
        return False
    headers = headers or {}
    for hdr in (headers.get("host", ""), headers.get("x-forwarded-host", "")):
        for cand in hdr.split(","):
            if cand.strip() and _host_port(cand, u.scheme) == target:
                return True
    return False


def _origin_rejection_body(origin: str) -> bytes:
    return json.dumps({
        "error": (f"cross-origin request from {origin!r} rejected. If this "
                  f"origin is trusted, add it to \"web_allowed_origins\" in "
                  f"~/.cheetahclaws/config.json (or set "
                  f"CHEETAHCLAWS_WEB_ALLOWED_ORIGINS) and restart."),
    }).encode()


def _cors_origin(request_origin: str = "") -> str:
    """Return the origin to echo in Access-Control-Allow-Origin, or "".

    Only origins that pass `_origin_allowed` (same-origin or explicitly
    allow-listed) are echoed. Never emit '*' — responses are credentialed.
    """
    if request_origin and _origin_allowed(
            request_origin, getattr(_req_ctx, "headers", None)):
        return request_origin
    return ""


def _emit_access_log(status_code: int) -> None:
    """Log one line per HTTP response; updates counters. Idempotent per req."""
    if getattr(_req_ctx, "logged", False):
        return
    _req_ctx.logged = True
    try:
        from cheetahclaws.web.logging_setup import get_logger, incr
        start = getattr(_req_ctx, "start_ts", None)
        dur_ms = (int((time.monotonic() - start) * 1000)
                  if start is not None else 0)
        get_logger("server").info("req", extra={
            "method": getattr(_req_ctx, "method", "-"),
            "path": getattr(_req_ctx, "path", "-"),
            "status": status_code,
            "dur_ms": dur_ms,
            "user_id": getattr(_req_ctx, "user_id", None),
            "peer": getattr(_req_ctx, "peer", None),
        })
        incr("requests_total")
        if 400 <= status_code < 500:
            incr("requests_4xx")
        elif 500 <= status_code < 600:
            incr("requests_5xx")
    except Exception:  # noqa: BLE001
        pass  # never let logging break request handling


def _send_http(sock: socket.socket, status: str, content_type: str,
               body: bytes, extra_headers: str = "",
               request_origin: str = "") -> None:
    origin = _cors_origin(request_origin)
    cors = ""
    if origin:
        cors = (
            f"Access-Control-Allow-Origin: {origin}\r\n"
            f"Access-Control-Allow-Credentials: true\r\n"
            f"Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS\r\n"
            f"Access-Control-Allow-Headers: Content-Type, X-CSRF-Token\r\n"
            f"Vary: Origin\r\n"
        )
    # CSRF cookie set by the dispatch entry on a fresh connection — append
    # once so the very first GET response carries it.
    csrf_cookie = getattr(_req_ctx, "set_csrf", "") or ""
    if csrf_cookie:
        _req_ctx.set_csrf = ""  # only once per request
    header = (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"{cors}"
        f"{csrf_cookie}"
        f"Connection: close\r\n"
        f"{extra_headers}"
        f"\r\n"
    )
    sock.sendall(header.encode() + body)
    try:
        _emit_access_log(int(status.split()[0]))
    except (ValueError, IndexError):
        pass


def _pair_api(path: str, method: str, cookie: str) -> tuple[str, dict]:
    """GET /api/pair/info and POST /api/pair/reset → (status, json body)."""
    global _server_pair_token
    if not _pair_owner_ok(cookie):
        return "403 Forbidden", {
            "error": "Open this page on the computer running CheetahClaws "
                     "(or sign in as an admin)."}
    if path == "/api/pair/reset":
        if method != "POST":
            return "405 Method Not Allowed", {"error": "use POST"}
        if not (_server_no_auth and _server_lan):
            return "400 Bad Request", {"error": "pairing is not enabled"}
        from cheetahclaws.web.pairing import reset_pair_token
        _server_pair_token = reset_pair_token()
    elif method != "GET":
        return "405 Method Not Allowed", {"error": "use GET"}
    from cheetahclaws.web.pairing import device_urls
    token = _server_pair_token if _server_no_auth else None
    return "200 OK", {
        "lan": _server_lan,
        "mode": "token" if _server_no_auth else "login",
        "port": _server_port,
        "urls": device_urls(_server_port, token) if _server_lan else [],
    }


def _send_json(sock: socket.socket, obj: dict,
               request_origin: str = "") -> None:
    body = json.dumps(obj).encode()
    _send_http(sock, "200 OK", "application/json", body,
               request_origin=request_origin)


_CSRF_COOKIE_NAME = "ccsrf"


def _csrf_from_cookie(cookie_str: str) -> str:
    """Pull the CSRF token out of a Cookie header, or "" if absent."""
    if not cookie_str:
        return ""
    for part in cookie_str.split(";"):
        part = part.strip()
        if part.startswith(f"{_CSRF_COOKIE_NAME}="):
            from urllib.parse import unquote
            return unquote(part[len(_CSRF_COOKIE_NAME) + 1:])
    return ""


def _check_csrf(headers: dict, cookie_str: str) -> bool:
    """Double-submit cookie CSRF check.

    Passes if X-CSRF-Token header matches the ccsrf cookie. SameSite=Strict
    on the JWT cookie is the first-line defence; this is the second line.
    """
    cookie_tok = _csrf_from_cookie(cookie_str)
    if not cookie_tok:
        return False
    header_tok = headers.get("X-CSRF-Token") or headers.get("x-csrf-token") or ""
    if not header_tok:
        return False
    return hmac.compare_digest(cookie_tok, header_tok)


def _build_csrf_set_cookie() -> str:
    """Return a Set-Cookie header line for a fresh CSRF token.

    Non-HttpOnly so the JS client can read it and echo it back in the
    X-CSRF-Token header. SameSite=Strict so it never crosses origins.
    """
    token = secrets.token_urlsafe(24)
    return (
        f"Set-Cookie: {_CSRF_COOKIE_NAME}={token}; Path=/; SameSite=Strict; "
        f"Max-Age=86400\r\n"
    )


_CSRF_EXEMPT_PATHS = frozenset({
    # Login/register run BEFORE the user has a CSRF cookie; they establish
    # the session that will later carry one.
    "/api/auth/bootstrap",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
    # Legacy terminal password auth (POST /api/auth) — pre-JWT path.
    "/api/auth",
})


def _csrf_exempt(path: str) -> bool:
    return path in _CSRF_EXEMPT_PATHS


def _check_auth(query: str = "", body_token: str = "",
                cookie_str: str = "") -> bool:
    """Check terminal (/index.html) password auth — one-time generated pwd.

    Chat UI endpoints use JWT via `_jwt_user_id` instead; this helper only
    gates the PTY-terminal endpoints.

    In --no-auth mode the password is replaced by the per-launch token
    (see `_launch_token_ok`).
    """
    if _server_no_auth:
        return _launch_token_ok(query, body_token, cookie_str)
    token = body_token
    if not token and cookie_str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("cctoken="):
                from urllib.parse import unquote
                token = unquote(part[8:])
                break
    if not token:
        for param in query.split("&"):
            if param.startswith("token="):
                from urllib.parse import unquote
                token = unquote(param[6:])
    if not token or not _server_password:
        return False
    return hmac.compare_digest(token, _server_password)


def _cookie_value(cookie_str: str, name: str) -> str:
    if not cookie_str:
        return ""
    for part in cookie_str.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            from urllib.parse import unquote
            return unquote(part[len(name) + 1:])
    return ""


def _query_value(query: str, name: str) -> str:
    for param in (query or "").split("&"):
        if param.startswith(name + "="):
            from urllib.parse import unquote
            return unquote(param[len(name) + 1:])
    return ""


def _launch_token_ok(query: str = "", body_token: str = "",
                     cookie_str: str = "") -> bool:
    """--no-auth gate: does the caller hold the per-launch token?

    Accepted from the cclaunch cookie, a ?token= query param, or an explicit
    token (WS first frame / JSON body). Always True when the gate is off.
    """
    if _server_launch_token is None:
        return True
    for tok in (body_token, _cookie_value(cookie_str, _LAUNCH_COOKIE),
                _query_value(query, "token")):
        if tok and hmac.compare_digest(str(tok), _server_launch_token):
            return True
        if (tok and _server_pair_token
                and hmac.compare_digest(str(tok), _server_pair_token)):
            return True
    return False


def _is_pair_token(tok: str) -> bool:
    return bool(tok and _server_pair_token
                and hmac.compare_digest(str(tok), _server_pair_token))


def _pair_owner_ok(cookie_str: str) -> bool:
    """May this caller see / reset the pairing token?

    --no-auth: only the holder of the *launch* token (the desktop window or
    whoever ran the command), not an already-paired phone. Password mode:
    an admin account.
    """
    if _server_no_auth:
        if _server_launch_token is None:
            return True
        tok = _cookie_value(cookie_str, _LAUNCH_COOKIE)
        return bool(tok) and hmac.compare_digest(tok, _server_launch_token)
    return _is_admin(_jwt_user_id(cookie_str))


def _jwt_user_id(cookie_str: str) -> Optional[int]:
    """Return the chat-UI user id authenticated by the ccjwt cookie, or None.

    Also stamps the user id onto the per-request log context so access logs
    record who made the request. In --no-auth mode we return a synthetic id.
    """
    uid: Optional[int] = None
    if _server_no_auth:
        # Synthetic owner id — but only for callers holding the launch token.
        uid = 1 if _launch_token_ok(cookie_str=cookie_str) else None
    else:
        try:
            from cheetahclaws.web.auth import decode_token
        except ImportError:
            return None
        if not cookie_str:
            return None
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith("ccjwt="):
                from urllib.parse import unquote
                token = unquote(part[len("ccjwt="):])
                payload = decode_token(token)
                if not payload:
                    return None
                try:
                    uid = int(payload.get("sub", ""))
                except (TypeError, ValueError):
                    return None
                break
    if uid is not None:
        _req_ctx.user_id = uid
    return uid


_ADMIN_ONLY_MSG = ("This action is restricted to admin users. The server "
                   "owner can set \"web_nonadmin_privileged\": true in "
                   "~/.cheetahclaws/config.json to allow all users.")

_LAUNCH_GATED_PAGES = frozenset({"/", "/index.html", "/chat", "/lab",
                                 "/pair"})


def _launch_url_hint() -> str:
    return ("Open the URL printed in the terminal when the server started "
            "(it ends in ?token=...). To turn this check off entirely, set "
            "\"web_no_auth_require_token\": false in "
            "~/.cheetahclaws/config.json (not recommended: any website you "
            "visit could then reach this server).")


def _launch_gate(sock, path: str, query: str, cookie: str,
                 origin: str) -> bool:
    """--no-auth page gate. Returns True if a response was already sent.

    ``?token=<launch token>`` → 302 to the same page without the token plus
    an HttpOnly cookie, so the secret doesn't linger in the address bar or
    history. A valid cookie passes through. Anything else gets a 401 page.
    """
    from urllib.parse import quote
    q_tok = _query_value(query, "token")
    is_launch = bool(q_tok) and hmac.compare_digest(
        q_tok, _server_launch_token or "")
    is_pair = not is_launch and _is_pair_token(q_tok)
    if is_launch or is_pair:
        rest = "&".join(p for p in query.split("&")
                        if p and not p.startswith("token="))
        location = path + (f"?{rest}" if rest else "")
        # A paired device keeps its cookie across browser restarts; the
        # per-launch token is useless after this run, so it stays a
        # session cookie.
        max_age = ""
        if is_pair:
            from cheetahclaws.web.pairing import PAIR_COOKIE_MAX_AGE
            max_age = f" Max-Age={PAIR_COOKIE_MAX_AGE};"
        hdrs = (f"Location: {location}\r\n"
                f"Set-Cookie: {_LAUNCH_COOKIE}="
                f"{quote(q_tok)}; Path=/;{max_age} HttpOnly; "
                f"SameSite=Strict\r\n"
                f"Cache-Control: no-store\r\n"
                f"Referrer-Policy: no-referrer\r\n")
        _send_http(sock, "302 Found", "text/plain", b"", hdrs,
                   request_origin=origin)
        return True
    if _launch_token_ok(cookie_str=cookie):
        return False
    import html as _html
    pair_form = ""
    if _server_pair_token:
        # A phone that lost its cookie (or an iOS home-screen app, which has
        # its own cookie jar) can paste the pairing link here instead of
        # re-scanning. The script only extracts ?token= and reloads.
        pair_form = (
            "<form onsubmit=\"var v=this.t.value.trim(),m=v.match("
            "/[?&]token=([\\w-]+)/);location.search='?token='+"
            "encodeURIComponent(m?m[1]:v);return false\" "
            "style='margin-top:1.5rem'>"
            "<p>Pairing a phone? Paste the link from <b>Connect phone</b> "
            "on your computer:</p>"
            "<input name=t autocomplete=off placeholder='http://…/chat?token=…' "
            "style='box-sizing:border-box;width:100%;max-width:28rem;"
            "padding:.7rem;font-size:16px;margin-bottom:.6rem;"
            "border-radius:8px;border:1px solid #333;background:#111;"
            "color:#eee'> <button style='padding:.7rem 1.2rem;font-size:16px;"
            "border-radius:8px;border:0;background:#22d3ee'>Connect</button>"
            "</form>")
    body = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,"
            "initial-scale=1'>"
            "<title>CheetahClaws — access token required</title></head>"
            "<body style='font-family:sans-serif;background:#0a0a0a;"
            "color:#e4e4e7;padding:2rem'><h2>Access token required</h2>"
            f"<p>{_html.escape(_launch_url_hint())}</p>{pair_form}"
            "</body></html>")
    _send_http(sock, "401 Unauthorized", "text/html; charset=utf-8",
               body.encode(), request_origin=origin)
    return True


def _is_admin(uid: Optional[int]) -> bool:
    """True if `uid` is a chat-UI admin. The --no-auth owner is always admin."""
    if uid is None:
        return False
    if _server_no_auth:
        return True
    try:
        from cheetahclaws.web.db import init_db, repo as dbrepo
        init_db()
        user = dbrepo.get_user(uid)
    except Exception:  # noqa: BLE001
        return False
    return bool(user and user.get("is_admin"))


def _require_user(sock, cookie_str: str, origin: str) -> Optional[int]:
    """Return user_id or send 401 + close socket and return None."""
    uid = _jwt_user_id(cookie_str)
    if uid is None:
        _send_http(sock, "401 Unauthorized", "application/json",
                   b'{"error":"auth required"}', request_origin=origin)
        sock.close()
    return uid


# ── WebSocket frame helpers (RFC 6455) ───────────────────────────────────

def _ws_send(sock, data: bytes, opcode: int = 0x02,
             lock: Optional[threading.Lock] = None) -> None:
    length = len(data)
    if length < 126:
        hdr = bytes([0x80 | opcode, length])
    elif length < 65536:
        hdr = bytes([0x80 | opcode, 126]) + struct.pack("!H", length)
    else:
        hdr = bytes([0x80 | opcode, 127]) + struct.pack("!Q", length)
    payload = hdr + data
    if lock:
        with lock:
            sock.sendall(payload)
    else:
        sock.sendall(payload)


def _ws_recv(sock,
             lock: Optional[threading.Lock] = None) -> Optional[str | bytes]:
    def recv_exact(n: int) -> Optional[bytes]:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except (OSError, ConnectionResetError, TimeoutError):
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    # Loop instead of recursion to avoid stack overflow on
    # sustained ping/pong sequences.
    while True:
        head = recv_exact(2)
        if not head:
            return None

        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F

        if length == 126:
            ext = recv_exact(2)
            if not ext:
                return None
            length = struct.unpack("!H", ext)[0]
        elif length == 127:
            ext = recv_exact(8)
            if not ext:
                return None
            length = struct.unpack("!Q", ext)[0]

        if masked:
            mask = recv_exact(4)
            if not mask:
                return None
            raw = bytearray(recv_exact(length) or b"")
            for i in range(len(raw)):
                raw[i] ^= mask[i % 4]
            raw = bytes(raw)
        else:
            raw = recv_exact(length) or b""

        if opcode == 0x8:  # close
            try:
                _ws_send(sock, struct.pack("!H", 1000), opcode=0x08, lock=lock)
            except OSError:
                pass
            return None
        if opcode == 0x9:  # ping → pong
            try:
                _ws_send(sock, raw, opcode=0x0A, lock=lock)
            except OSError:
                pass
            continue  # read next frame
        if opcode == 0xA:  # pong — ignore, read next frame
            continue

        if opcode == 0x1:
            return raw.decode(errors="replace")
        return raw


# ── WebSocket ↔ PTY bridge ───────────────────────────────────────────────

def _handle_websocket(sock: socket.socket, extra: bytes,
                      pre_authed: bool = False) -> None:
    bsock = _BufferedSocket(sock, extra)
    send_lock = threading.Lock()

    # ── First-frame authentication ──────────────────────────────────
    # If not pre-authenticated via cookie/query, require the first WS
    # message to be JSON {"type":"auth","token":"..."}.
    if not pre_authed:
        msg = _ws_recv(bsock, lock=send_lock)
        if msg is None:
            return
        authed = False
        if isinstance(msg, str):
            try:
                obj = json.loads(msg)
                if obj.get("type") == "auth":
                    authed = _check_auth(body_token=obj.get("token", ""))
            except (json.JSONDecodeError, KeyError):
                pass
        if not authed:
            err = {"error": "auth required"}
            if _server_no_auth:
                err["hint"] = _launch_url_hint()
            try:
                _ws_send(bsock, json.dumps(err).encode(), opcode=0x01,
                         lock=send_lock)
                _ws_send(bsock, struct.pack("!H", 1008), opcode=0x08,
                         lock=send_lock)
            except OSError:
                pass
            return

    try:
        import pty
    except ImportError:
        pty = None
    if not pty:
        _send_http(bsock._sock, "501 Not Implemented", "application/json",
                   b'{"error":"PTY not supported on Windows"}')
        return
    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    env["COLUMNS"] = "120"
    env["LINES"] = "30"
    env["CHEETAHCLAWS_WEB_TERMINAL"] = "1"
    proc = subprocess.Popen(
        _server_cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        env=env, preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    def pty_to_ws():
        try:
            while True:
                r, _, _ = select.select([master_fd], [], [], 1.0)
                if not r:
                    if proc.poll() is not None:
                        break
                    continue
                data = os.read(master_fd, 16384)
                if not data:
                    break
                _ws_send(bsock, data, lock=send_lock)
        except (OSError, BrokenPipeError):
            pass

    reader_t = threading.Thread(target=pty_to_ws, daemon=True)
    reader_t.start()

    try:
        while True:
            msg = _ws_recv(bsock, lock=send_lock)
            if msg is None:
                break
            if isinstance(msg, str):
                try:
                    obj = json.loads(msg)
                    if obj.get("type") == "resize":
                        import fcntl, termios
                        rows, cols = int(obj["rows"]), int(obj["cols"])
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                        try:
                            os.killpg(os.getpgid(proc.pid), signal.SIGWINCH)
                        except (OSError, ProcessLookupError):
                            pass
                        continue
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass
                os.write(master_fd, msg.encode())
            elif isinstance(msg, bytes):
                os.write(master_fd, msg)
    except (OSError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        try:
            os.close(master_fd)
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        reader_t.join(timeout=2)


# ── SSE stream handler ──────────────────────────────────────────────────

def _handle_sse_stream(sock: socket.socket, sid: str,
                       request_origin: str = "") -> None:
    """Stream PTY output as Server-Sent Events."""
    with _sessions_lock:
        session = _sessions.get(sid)
    if not session or session.closed:
        _send_http(sock, "404 Not Found", "text/plain", b"session not found",
                   request_origin=request_origin)
        return

    # Send SSE headers (keep connection open)
    cors_origin = _cors_origin(request_origin)
    cors = ""
    if cors_origin:
        cors = (
            f"Access-Control-Allow-Origin: {cors_origin}\r\n"
            f"Access-Control-Allow-Credentials: true\r\n"
            f"Vary: Origin\r\n"
        )
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/event-stream\r\n"
        "Cache-Control: no-cache\r\n"
        "Connection: keep-alive\r\n"
        f"{cors}"
        "\r\n"
    )
    sock.sendall(header.encode())
    session.attached = True

    # Stream PTY output as SSE events
    try:
        while not session.closed:
            r, _, _ = select.select([session.master_fd], [], [], 1.0)
            if not r:
                # Send SSE comment as keepalive
                sock.sendall(b": keepalive\n\n")
                if session.proc.poll() is not None:
                    break
                continue
            data = os.read(session.master_fd, 16384)
            if not data:
                break
            # Encode as base64 for safe SSE transport
            b64 = base64.b64encode(data).decode()
            sse_msg = f"data: {b64}\n\n"
            sock.sendall(sse_msg.encode())
    except (OSError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        # Clean up session when stream ends
        session.close()
        with _sessions_lock:
            _sessions.pop(sid, None)


# ── Chat WebSocket handler (structured events) ─────────────────────────

def _handle_chat_websocket(sock: socket.socket, extra: bytes,
                            user_id: int) -> None:
    """Handle /api/events WebSocket: stream ChatEvents to browser.

    Auth is already verified at the HTTP layer before the WS upgrade.
    First frame from the client must be: {"session_id": "..."}
    """
    bsock = _BufferedSocket(sock, extra)
    send_lock = threading.Lock()

    # First frame: {session_id: "..."} to identify the chat session
    msg = _ws_recv(bsock, lock=send_lock)
    if msg is None:
        return
    session_id = ""
    if isinstance(msg, str):
        try:
            obj = json.loads(msg)
            session_id = obj.get("session_id", "")
        except (json.JSONDecodeError, KeyError):
            pass

    from cheetahclaws.web.api import get_chat_session
    from cheetahclaws.config import load_config
    chat_session = get_chat_session(session_id, user_id, load_config())
    if not chat_session:
        try:
            _ws_send(bsock, json.dumps({"error": "session not found"}).encode(),
                     opcode=0x01, lock=send_lock)
        except OSError:
            pass
        return

    # Subscribe to the session's event queue
    event_queue = chat_session.subscribe()

    # Reader thread: handle incoming WS messages (approve, prompt, etc.)
    reader_alive = threading.Event()
    reader_alive.set()

    def _ws_reader():
        try:
            while reader_alive.is_set():
                msg = _ws_recv(bsock, lock=send_lock)
                if msg is None:
                    reader_alive.clear()
                    break
                if isinstance(msg, str):
                    try:
                        obj = json.loads(msg)
                        msg_type = obj.get("type", "")
                        if msg_type == "approve":
                            chat_session.approve_permission(
                                obj.get("granted", False))
                        elif msg_type == "prompt":
                            chat_session.submit_prompt(
                                obj.get("prompt", ""))
                    except (json.JSONDecodeError, KeyError):
                        pass
        except (OSError, ConnectionResetError):
            reader_alive.clear()

    reader_t = threading.Thread(target=_ws_reader, daemon=True)
    reader_t.start()

    # Main loop: drain event queue → send to WS client
    try:
        while reader_alive.is_set():
            try:
                event = event_queue.get(timeout=30)
                payload = event.to_json().encode()
                _ws_send(bsock, payload, opcode=0x01, lock=send_lock)
            except Exception:
                # queue.Empty on timeout → send WS ping as keepalive
                try:
                    _ws_send(bsock, b"", opcode=0x09, lock=send_lock)
                except OSError:
                    break
    except (OSError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        reader_alive.clear()
        chat_session.unsubscribe(event_queue)
        reader_t.join(timeout=2)


# ── Connection handler ───────────────────────────────────────────────────

def _handle_connection(sock: socket.socket, addr: tuple) -> None:
    # Reset per-request logging context. Each connection = one request (HTTP/1.1
    # Connection: close), so thread-local is safe.
    _req_ctx.start_ts = time.monotonic()
    _req_ctx.method = "-"
    _req_ctx.path = "-"
    _req_ctx.user_id = None
    _req_ctx.peer = f"{addr[0]}:{addr[1]}" if addr else None
    _req_ctx.logged = False
    _req_ctx.set_csrf = ""
    _req_ctx.headers = {}
    try:
        sock.settimeout(30)
        raw = _recv_until(sock, b"\r\n\r\n")
        if not raw:
            sock.close()
            return

        header_end = raw.find(b"\r\n\r\n")
        header_bytes = raw[:header_end]
        extra = raw[header_end + 4:]

        header_str = header_bytes.decode(errors="replace")
        lines = header_str.split("\r\n")
        if not lines:
            sock.close()
            return

        request_line = lines[0]
        parts = request_line.split(" ")
        if len(parts) < 2:
            sock.close()
            return
        _req_ctx.method = parts[0]
        _req_ctx.path = parts[1].split("?", 1)[0]

        method, raw_path = parts[0], parts[1]
        path = raw_path.split("?")[0]
        query = raw_path.split("?", 1)[1] if "?" in raw_path else ""

        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        origin = headers.get("origin", "")
        cookie = headers.get("cookie", "")
        _req_ctx.headers = headers

        # Origin gate: a browser on another site must not be able to open a
        # WebSocket (PTY / chat events), attach to a PTY stream, or make
        # state-changing requests. WebSockets are exempt from CORS and, in
        # --no-auth mode, carry no credential — Origin is the only signal.
        is_upgrade = "upgrade" in headers.get("connection", "").lower()
        if ((method in ("POST", "PUT", "PATCH", "DELETE") or is_upgrade
                or path == "/api/stream")
                and not _origin_allowed(origin, headers)):
            try:
                from cheetahclaws.web.logging_setup import get_logger, incr
                incr("origin_rejected_total")
                get_logger("server").warning(
                    "origin_rejected", extra={"origin": origin, "path": path})
            except Exception:  # noqa: BLE001
                pass
            _send_http(sock, "403 Forbidden", "application/json",
                       _origin_rejection_body(origin))
            sock.close()
            return

        # CSRF: caller has no token yet → mint one and attach to every
        # response on this connection so the first GET / POST/PUT/PATCH /
        # DELETE cycle establishes the cookie. Subsequent state-changing
        # requests must echo the cookie in an X-CSRF-Token header.
        if not _csrf_from_cookie(cookie):
            _req_ctx.set_csrf = _build_csrf_set_cookie()

        # CSRF gate: state-changing methods must present matching
        # cookie+header. SameSite=Strict on the JWT cookie is the first
        # line of defence; this is the second. Exempts auth bootstrap
        # endpoints because the user has no cookie yet at that point.
        if (method in ("POST", "PUT", "PATCH", "DELETE")
                and not _csrf_exempt(path)
                and not _check_csrf(headers, cookie)):
            cors_origin = _cors_origin(origin)
            cors_hdrs = ""
            if cors_origin:
                cors_hdrs = (
                    f"Access-Control-Allow-Origin: {cors_origin}\r\n"
                    f"Access-Control-Allow-Credentials: true\r\n"
                    f"Vary: Origin\r\n"
                )
            _send_http(
                sock, "403 Forbidden", "application/json",
                b'{"error":"csrf token mismatch"}',
                extra_headers=cors_hdrs, request_origin=origin,
            )
            sock.close()
            return

        # Parse JSON body for POST requests
        body_str = ""
        body_json = {}
        if method in ("POST", "PATCH"):
            content_len = int(headers.get("content-length", 0))
            if content_len > 0:
                body_bytes = extra
                while len(body_bytes) < content_len:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    body_bytes += chunk
                body_str = body_bytes[:content_len].decode(errors="replace")
                try:
                    body_json = json.loads(body_str)
                except json.JSONDecodeError:
                    pass

        # ── CORS preflight ───────────────────────────────────────────
        if method == "OPTIONS":
            cors_origin = _cors_origin(origin)
            cors_hdrs = ""
            if cors_origin:
                cors_hdrs = (
                    f"Access-Control-Allow-Origin: {cors_origin}\r\n"
                    f"Access-Control-Allow-Credentials: true\r\n"
                    f"Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS\r\n"
                    f"Access-Control-Allow-Headers: Content-Type, X-CSRF-Token\r\n"
                    f"Vary: Origin\r\n"
                )
            _send_http(sock, "204 No Content", "text/plain", b"",
                       cors_hdrs)
            sock.close()
            return

        # ── Ops endpoints ────────────────────────────────────────────
        # /health is always public (container healthchecks, load balancers).
        # /metrics requires auth unless "web_public_metrics": true.

        if path == "/health" and method == "GET":
            db_ok = True
            db_err: Optional[str] = None
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                init_db()
                dbrepo.user_count()  # touches the DB
            except Exception as exc:  # noqa: BLE001
                db_ok = False
                db_err = str(exc)
            from cheetahclaws.web.logging_setup import uptime_seconds
            payload = {
                "ok": db_ok,
                "db": "ok" if db_ok else "error",
                "uptime_s": round(uptime_seconds(), 1),
            }
            if not db_ok:
                payload["db_err"] = db_err
            body = json.dumps(payload).encode()
            status = "200 OK" if db_ok else "503 Service Unavailable"
            _send_http(sock, status, "application/json", body,
                       request_origin=origin)
            sock.close()
            return

        if path == "/metrics" and method == "GET":
            if (not _web_settings.get("public_metrics")
                    and _jwt_user_id(cookie) is None
                    and not _check_auth(query, cookie_str=cookie)):
                _send_http(sock, "401 Unauthorized", "application/json",
                           json.dumps({"error": (
                               "auth required (set \"web_public_metrics\": "
                               "true in config to expose /metrics without "
                               "auth)")}).encode(),
                           request_origin=origin)
                sock.close()
                return
            # Prometheus text exposition format (v0.0.4)
            try:
                from cheetahclaws.web.logging_setup import snapshot, uptime_seconds
                counters = snapshot()
            except Exception:  # noqa: BLE001
                counters = {}
            extras: dict[str, int] = {}
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                init_db()
                extras["users_total"] = dbrepo.user_count()
            except Exception:  # noqa: BLE001
                pass
            lines: list[str] = []
            lines.append("# HELP cheetahclaws_uptime_seconds Server uptime")
            lines.append("# TYPE cheetahclaws_uptime_seconds gauge")
            lines.append(f"cheetahclaws_uptime_seconds "
                         f"{round(uptime_seconds(), 3)}")
            for k, v in {**counters, **extras}.items():
                lines.append(f"# HELP cheetahclaws_{k} {k}")
                lines.append(f"# TYPE cheetahclaws_{k} counter")
                lines.append(f"cheetahclaws_{k} {v}")
            body = ("\n".join(lines) + "\n").encode()
            _send_http(sock, "200 OK", "text/plain; version=0.0.4",
                       body, request_origin=origin)
            sock.close()
            return

        # ── --no-auth launch-token gate for HTML pages ──────────────
        if (method == "GET" and path in _LAUNCH_GATED_PAGES
                and _server_no_auth and _server_launch_token is not None):
            if _launch_gate(sock, path, query, cookie, origin):
                sock.close()
                return

        # ── Chat-UI auth (JWT-based, separate from terminal /api/auth) ──

        # GET /api/auth/bootstrap — does any user exist yet?
        if path == "/api/auth/bootstrap" and method == "GET":
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                init_db()
                has_users = dbrepo.user_count() > 0
            except Exception as exc:  # noqa: BLE001
                _send_json(sock, {"error": str(exc)}, request_origin=origin)
                sock.close()
                return
            _send_json(sock, {"has_users": has_users,
                              "no_auth": _server_no_auth,
                              "open_registration": bool(
                                  not has_users
                                  or _web_settings.get("open_registration"))},
                       request_origin=origin)
            sock.close()
            return

        # POST /api/auth/register — create user. The first user becomes admin;
        # after that only a signed-in admin may create accounts, unless
        # "web_open_registration": true restores open self-sign-up.
        if path == "/api/auth/register" and method == "POST":
            username = (body_json.get("username") or "").strip()
            password = body_json.get("password") or ""
            if len(username) < 2 or len(password) < 6:
                _send_http(sock, "400 Bad Request", "application/json",
                           b'{"error":"username >= 2 chars, password >= 6"}',
                           request_origin=origin)
                sock.close()
                return
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                from cheetahclaws.web.auth import hash_password, issue_token, build_cookie
                init_db()
                # Serialise so two racing first-visitors can't both become
                # admin, and the open/closed decision matches the insert.
                with _register_lock:
                    is_admin = dbrepo.user_count() == 0
                    by_admin = False
                    if not is_admin:
                        by_admin = _is_admin(_jwt_user_id(cookie))
                        if (not by_admin
                                and not _web_settings.get("open_registration")):
                            _send_http(
                                sock, "403 Forbidden", "application/json",
                                json.dumps({"error": (
                                    "Registration is closed. Ask an admin to "
                                    "create your account, or the server owner "
                                    "can set \"web_open_registration\": true "
                                    "in ~/.cheetahclaws/config.json to allow "
                                    "self-sign-up.")}).encode(),
                                request_origin=origin)
                            sock.close()
                            return
                    if dbrepo.get_user_by_username(username) is not None:
                        _send_http(sock, "409 Conflict", "application/json",
                                   b'{"error":"username taken"}',
                                   request_origin=origin)
                        sock.close()
                        return
                    user = dbrepo.create_user(username,
                                              hash_password(password),
                                              is_admin=is_admin)
                from cheetahclaws.web.logging_setup import get_logger, incr
                incr("auth_registrations_total")
                get_logger("auth").info("register", extra={
                    "username": user["username"], "user_id": user["id"],
                    "is_admin": is_admin, "by_admin": by_admin,
                })
                # An admin creating an account for someone else stays signed
                # in as themselves — don't swap their session cookie.
                extra = ("" if by_admin
                         else build_cookie(issue_token(user["id"],
                                                       user["username"])))
                _send_http(sock, "200 OK", "application/json",
                           json.dumps({"ok": True, "user": user}).encode(),
                           extra_headers=extra,
                           request_origin=origin)
            except Exception as exc:  # noqa: BLE001
                _send_http(sock, "500 Internal Server Error",
                           "application/json",
                           json.dumps({"error": str(exc)}).encode(),
                           request_origin=origin)
            sock.close()
            return

        # POST /api/auth/login — bcrypt verify → issue JWT cookie
        if path == "/api/auth/login" and method == "POST":
            username = (body_json.get("username") or "").strip()
            password = body_json.get("password") or ""
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                from cheetahclaws.web.auth import (verify_password, issue_token,
                                       build_cookie)
                init_db()
                rec = dbrepo.get_user_by_username(username)
                if not rec or not verify_password(password,
                                                   rec["password_hash"]):
                    from cheetahclaws.web.logging_setup import incr, get_logger
                    incr("auth_logins_failed")
                    get_logger("auth").warning("login_failed",
                                                extra={"username": username})
                    _send_http(sock, "401 Unauthorized", "application/json",
                               b'{"error":"invalid credentials"}',
                               request_origin=origin)
                    sock.close()
                    return
                token = issue_token(rec["id"], rec["username"])
                from cheetahclaws.web.logging_setup import incr, get_logger
                incr("auth_logins_total")
                get_logger("auth").info("login", extra={
                    "user_id": rec["id"], "username": rec["username"],
                })
                _send_http(sock, "200 OK", "application/json",
                           json.dumps({"ok": True,
                                       "user": {"id": rec["id"],
                                                "username": rec["username"],
                                                "is_admin": rec["is_admin"]}
                                       }).encode(),
                           extra_headers=build_cookie(token),
                           request_origin=origin)
            except Exception as exc:  # noqa: BLE001
                _send_http(sock, "500 Internal Server Error",
                           "application/json",
                           json.dumps({"error": str(exc)}).encode(),
                           request_origin=origin)
            sock.close()
            return

        # POST /api/auth/logout — clear cookie
        if path == "/api/auth/logout" and method == "POST":
            clear = ("Set-Cookie: ccjwt=; Path=/; HttpOnly; SameSite=Strict; "
                     "Max-Age=0\r\n")
            _send_http(sock, "200 OK", "application/json", b'{"ok":true}',
                       extra_headers=clear, request_origin=origin)
            sock.close()
            return

        # GET /api/auth/whoami — return current user
        if path == "/api/auth/whoami" and method == "GET":
            uid = _jwt_user_id(cookie)
            if uid is None:
                _send_http(sock, "401 Unauthorized", "application/json",
                           b'{"error":"not logged in"}',
                           request_origin=origin)
                sock.close()
                return
            try:
                from cheetahclaws.web.db import init_db, repo as dbrepo
                init_db()
                user = dbrepo.get_user(uid)
            except Exception:  # noqa: BLE001
                user = None
            if not user:
                _send_http(sock, "401 Unauthorized", "application/json",
                           b'{"error":"user missing"}',
                           request_origin=origin)
                sock.close()
                return
            _send_json(sock, {"user": user}, request_origin=origin)
            sock.close()
            return

        # ── POST /api/auth — login, set cookie ──────────────────────
        if path == "/api/auth" and method == "POST":
            if _check_auth(body_token=body_json.get("token", "")):
                from urllib.parse import quote
                set_cookie = (
                    f"Set-Cookie: cctoken={quote(_server_password or '')}; "
                    f"Path=/; HttpOnly; SameSite=Strict; Max-Age=86400\r\n"
                )
                body = b'{"ok":true}'
                _send_http(sock, "200 OK", "application/json", body,
                           extra_headers=set_cookie,
                           request_origin=origin)
            else:
                _send_http(sock, "401 Unauthorized", "application/json",
                           b'{"error":"bad password"}',
                           request_origin=origin)
            sock.close()
            return

        # ── WebSocket upgrade ────────────────────────────────────────
        if path == "/ws" and "upgrade" in headers.get("connection", "").lower():
            # Accept upgrade first; authenticate via first message.
            # Cookie auth is also accepted for convenience.
            pre_authed = _check_auth(query, cookie_str=cookie)

            ws_key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(
                hashlib.sha1(
                    (ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()
            ).decode()
            handshake = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            )
            sock.sendall(handshake.encode())
            sock.settimeout(None)
            _handle_websocket(sock, extra, pre_authed=pre_authed)
            try:
                sock.close()
            except OSError:
                pass
            return

        # ── SSE: Create session ──────────────────────────────────────
        if path == "/api/session" and method == "POST":
            if not _check_auth(query, body_json.get("token", ""),
                               cookie_str=cookie):
                _send_http(sock, "401 Unauthorized", "text/plain",
                           b"Unauthorized", request_origin=origin)
                sock.close()
                return

            sid = secrets.token_urlsafe(16)
            # Tag with JWT uid if one is present so /api/{stream,input,resize}
            # can reject other users who guess the sid.
            owner_uid = _jwt_user_id(cookie)
            session = _PtySession(owner_uid=owner_uid)
            cols = body_json.get("cols", 120)
            rows = body_json.get("rows", 30)
            session.resize(rows, cols)
            with _sessions_lock:
                _sessions[sid] = session
            _send_json(sock, {"session_id": sid}, request_origin=origin)
            sock.close()
            return

        # ── SSE: Stream output ───────────────────────────────────────
        if path == "/api/stream" and method == "GET":
            sid = ""
            for param in query.split("&"):
                if param.startswith("sid="):
                    sid = param[4:]
            if not _check_auth(query, cookie_str=cookie):
                _send_http(sock, "401 Unauthorized", "text/plain",
                           b"Unauthorized", request_origin=origin)
                sock.close()
                return
            with _sessions_lock:
                stream_sess = _sessions.get(sid)
            if stream_sess is not None and not _check_pty_owner(stream_sess, cookie):
                _send_http(sock, "403 Forbidden", "text/plain",
                           b"not session owner", request_origin=origin)
                sock.close()
                return

            sock.settimeout(None)  # Long-lived connection
            _handle_sse_stream(sock, sid, request_origin=origin)
            try:
                sock.close()
            except OSError:
                pass
            return

        # ── SSE: Terminal input ──────────────────────────────────────
        if path == "/api/input" and method == "POST":
            sid = body_json.get("sid", "")
            if not _check_auth(query, body_json.get("token", ""),
                               cookie_str=cookie):
                _send_http(sock, "401 Unauthorized", "text/plain",
                           b"Unauthorized", request_origin=origin)
                sock.close()
                return
            with _sessions_lock:
                session = _sessions.get(sid)
            if session and not _check_pty_owner(session, cookie):
                _send_http(sock, "403 Forbidden", "text/plain",
                           b"not session owner", request_origin=origin)
                sock.close()
                return
            if session:
                session.write(body_json.get("data", "").encode())
                _send_json(sock, {"ok": True}, request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"session not found", request_origin=origin)
            sock.close()
            return

        # ── SSE: Resize ──────────────────────────────────────────────
        if path == "/api/resize" and method == "POST":
            sid = body_json.get("sid", "")
            if not _check_auth(query, body_json.get("token", ""),
                               cookie_str=cookie):
                _send_http(sock, "401 Unauthorized", "text/plain",
                           b"Unauthorized", request_origin=origin)
                sock.close()
                return
            with _sessions_lock:
                session = _sessions.get(sid)
            if session and not _check_pty_owner(session, cookie):
                _send_http(sock, "403 Forbidden", "text/plain",
                           b"not session owner", request_origin=origin)
                sock.close()
                return
            if session:
                session.resize(body_json.get("rows", 30),
                               body_json.get("cols", 120))
                _send_json(sock, {"ok": True}, request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"session not found", request_origin=origin)
            sock.close()
            return

        # ── PWA manifest (public; carries the pair token only for a caller
        #    that already holds it, so a home-screen app can sign in) ────
        if path == "/manifest.webmanifest" and method == "GET":
            from cheetahclaws.web.pairing import manifest
            start = "/chat"
            held = _cookie_value(cookie, _LAUNCH_COOKIE)
            if _server_no_auth and _is_pair_token(held):
                from urllib.parse import quote
                start = f"/chat?token={quote(held)}"
            _send_http(sock, "200 OK", "application/manifest+json",
                       json.dumps(manifest(start)).encode(),
                       "Cache-Control: no-store\r\n", request_origin=origin)
            sock.close()
            return

        # ── Phone pairing ───────────────────────────────────────────
        if path == "/pair" and method == "GET":
            # Page is static; /api/pair/info enforces who may see the token.
            _send_http(sock, "200 OK", "text/html; charset=utf-8",
                       (_WEB_DIR / "pair.html").read_bytes(),
                       "Cache-Control: no-store\r\n"
                       "Referrer-Policy: no-referrer\r\n",
                       request_origin=origin)
            sock.close()
            return

        if path in ("/api/pair/info", "/api/pair/reset"):
            status, obj = _pair_api(path, method, cookie)
            _send_http(sock, status, "application/json",
                       json.dumps(obj).encode(),
                       "Cache-Control: no-store\r\n", request_origin=origin)
            sock.close()
            return

        # ── Chat UI page ────────────────────────────────────────────
        if path == "/chat" and method == "GET":
            # Serve chat.html always — it has its own login handling.
            # API endpoints enforce auth; the page itself is just static HTML.
            chat_path = _WEB_DIR / "chat.html"
            if chat_path.exists():
                body = chat_path.read_bytes()
                _send_http(sock, "200 OK", "text/html; charset=utf-8", body,
                           request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"chat.html not found", request_origin=origin)
            sock.close()
            return

        # ── Research lab UI page ────────────────────────────────────
        if path == "/lab" and method == "GET":
            lab_path = _WEB_DIR / "lab.html"
            if lab_path.exists():
                _send_http(sock, "200 OK", "text/html; charset=utf-8",
                           lab_path.read_bytes(), request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"lab.html not found", request_origin=origin)
            sock.close()
            return

        # ── /api/lab/* routes (research lab) ────────────────────────
        if path.startswith("/api/lab"):
            # Lab runs spend the owner's API budget and run experiments, so
            # require a signed-in user; starting/aborting runs is admin-only
            # unless "web_nonadmin_privileged": true.
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            if (method != "GET" and not _is_admin(uid)
                    and not _web_settings.get("nonadmin_privileged")):
                _send_http(sock, "403 Forbidden", "application/json",
                           json.dumps({"error": _ADMIN_ONLY_MSG}).encode(),
                           request_origin=origin)
                sock.close()
                return
            try:
                from cheetahclaws.web.lab_api import dispatch as _lab_dispatch
                from cheetahclaws.config import load_config as _load_cfg
                from urllib.parse import parse_qs
                q_dict = {k: v[0] for k, v in parse_qs(query).items()}
                status, ctype, raw = _lab_dispatch(
                    path, method, q_dict, body_json, _load_cfg())
                http_status = (
                    "200 OK" if status == 200 else
                    "400 Bad Request" if status == 400 else
                    "404 Not Found" if status == 404 else
                    "405 Method Not Allowed" if status == 405 else
                    f"{status} Server Error"
                )
                _send_http(sock, http_status, ctype, raw,
                           request_origin=origin)
            except Exception as exc:  # noqa: BLE001
                _send_json(sock, {"error": str(exc)}, request_origin=origin)
            sock.close()
            return

        # ── POST /api/prompt — submit prompt to chat session ────────
        if path == "/api/prompt" and method == "POST":
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            from cheetahclaws.web.api import create_chat_session, get_chat_session
            from cheetahclaws.config import load_config
            sid = body_json.get("session_id", "")
            chat_sess = (get_chat_session(sid, uid, load_config())
                         if sid else None)
            if not chat_sess:
                chat_sess = create_chat_session(load_config(), uid)
            prompt = body_json.get("prompt", "")
            if prompt and prompt.startswith("/"):
                # Check if client wants SSE streaming
                accept_hdr = headers.get("accept", "")
                wants_stream = "text/event-stream" in accept_hdr

                if wants_stream:
                    # SSE: keep connection open, stream events as they happen
                    cors_origin = _cors_origin(origin)
                    cors = ""
                    if cors_origin:
                        cors = (
                            f"Access-Control-Allow-Origin: {cors_origin}\r\n"
                            f"Access-Control-Allow-Credentials: true\r\n"
                            f"Vary: Origin\r\n"
                        )
                    sse_header = (
                        "HTTP/1.1 200 OK\r\n"
                        "Content-Type: text/event-stream\r\n"
                        "Cache-Control: no-cache\r\n"
                        "Connection: keep-alive\r\n"
                        f"{cors}"
                        "\r\n"
                    )
                    sock.sendall(sse_header.encode())
                    sock.settimeout(None)
                    # Stream session_id first
                    sock.sendall(f"data: {json.dumps({'type':'session','data':{'session_id':chat_sess.session_id}})}\n\n".encode())
                    def _sse_callback(evt_dict):
                        try:
                            sock.sendall(f"data: {json.dumps(evt_dict)}\n\n".encode())
                        except (OSError, BrokenPipeError):
                            pass
                    try:
                        chat_sess.handle_slash_stream(prompt, _sse_callback)
                    except (OSError, BrokenPipeError):
                        pass
                    finally:
                        # Send done marker
                        try:
                            sock.sendall(b"data: {\"type\":\"done\"}\n\n")
                        except (OSError, BrokenPipeError):
                            pass
                        try:
                            sock.close()
                        except OSError:
                            pass
                    return

                # Regular POST: return events inline
                events = chat_sess.handle_slash_sync(prompt)
                _send_json(sock, {
                    "session_id": chat_sess.session_id,
                    "events": events,
                }, request_origin=origin)
                sock.close()
                return
            accepted = True
            if prompt:
                accepted = chat_sess.submit_prompt(prompt)
            if not accepted:
                _send_http(sock, "409 Conflict", "application/json",
                           json.dumps({"error": "agent is busy",
                                       "session_id": chat_sess.session_id}).encode(),
                           request_origin=origin)
                sock.close()
                return
            _send_json(sock, {"session_id": chat_sess.session_id},
                       request_origin=origin)
            sock.close()
            return

        # ── WS /api/events — structured event stream ────────────────
        if path == "/api/events" and "upgrade" in headers.get("connection", "").lower():
            # JWT auth BEFORE upgrade — reject with 401, no WS handshake
            uid = _jwt_user_id(cookie)
            if uid is None:
                _send_http(sock, "401 Unauthorized", "text/plain",
                           b"Unauthorized", request_origin=origin)
                sock.close()
                return
            ws_key = headers.get("sec-websocket-key", "")
            accept = base64.b64encode(
                hashlib.sha1(
                    (ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
                ).digest()
            ).decode()
            handshake = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n"
                "\r\n"
            )
            sock.sendall(handshake.encode())
            sock.settimeout(None)
            _handle_chat_websocket(sock, extra, user_id=uid)
            try:
                sock.close()
            except OSError:
                pass
            return

        # ── POST /api/approve — respond to permission request ───────
        if path == "/api/approve" and method == "POST":
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            from cheetahclaws.web.api import get_chat_session
            from cheetahclaws.config import load_config
            sid = body_json.get("session_id", "")
            granted = body_json.get("granted", False)
            chat_sess = get_chat_session(sid, uid, load_config())
            if chat_sess:
                chat_sess.approve_permission(granted)
                _send_json(sock, {"ok": True}, request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"session not found", request_origin=origin)
            sock.close()
            return

        # ── /api/folders — list / create / rename / delete ──────────
        if path.startswith("/api/folders"):
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            from cheetahclaws.web.api import (list_folders, create_folder,
                                  rename_folder, remove_folder)
            parts_f = path.rstrip("/").split("/")
            # GET /api/folders
            if path == "/api/folders" and method == "GET":
                _send_json(sock, {"folders": list_folders(uid)},
                           request_origin=origin)
                sock.close()
                return
            # POST /api/folders  body: {name}
            if path == "/api/folders" and method == "POST":
                name = (body_json.get("name") or "").strip()
                if not name:
                    _send_http(sock, "400 Bad Request", "application/json",
                               b'{"error":"name required"}',
                               request_origin=origin)
                    sock.close()
                    return
                folder = create_folder(uid, name)
                if folder is None:
                    _send_http(sock, "409 Conflict", "application/json",
                               b'{"error":"folder name already exists"}',
                               request_origin=origin)
                else:
                    _send_json(sock, folder, request_origin=origin)
                sock.close()
                return
            # /api/folders/{id}
            if len(parts_f) == 4:
                try:
                    fid = int(parts_f[3])
                except ValueError:
                    _send_http(sock, "404 Not Found", "text/plain",
                               b"Not Found", request_origin=origin)
                    sock.close()
                    return
                if method == "PATCH":
                    name = (body_json.get("name") or "").strip()
                    if not name:
                        _send_http(sock, "400 Bad Request",
                                   "application/json",
                                   b'{"error":"name required"}',
                                   request_origin=origin)
                        sock.close()
                        return
                    ok = rename_folder(fid, uid, name)
                    if ok:
                        _send_json(sock, {"ok": True, "name": name[:120]},
                                   request_origin=origin)
                    else:
                        _send_http(sock, "404 Not Found",
                                   "application/json",
                                   b'{"error":"not found or duplicate name"}',
                                   request_origin=origin)
                    sock.close()
                    return
                if method == "DELETE":
                    ok = remove_folder(fid, uid)
                    _send_json(sock, {"ok": ok}, request_origin=origin)
                    sock.close()
                    return
            _send_http(sock, "404 Not Found", "text/plain", b"Not Found",
                       request_origin=origin)
            sock.close()
            return

        # ── /api/sessions — list / get / rename / delete / export ───
        if path.startswith("/api/sessions"):
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            from cheetahclaws.web.api import (list_chat_sessions, get_chat_session,
                                  rename_chat_session, remove_chat_session,
                                  export_chat_session_markdown,
                                  batch_remove_chat_sessions,
                                  batch_export_chat_sessions_markdown,
                                  move_session_to_folder)
            from cheetahclaws.config import load_config
            # POST /api/sessions/batch_delete  body: {ids: [...]}
            if path == "/api/sessions/batch_delete" and method == "POST":
                ids = body_json.get("ids") or []
                if not isinstance(ids, list):
                    _send_http(sock, "400 Bad Request", "application/json",
                               b'{"error":"ids must be a list"}',
                               request_origin=origin)
                    sock.close()
                    return
                result = batch_remove_chat_sessions(
                    [str(i) for i in ids], uid)
                _send_json(sock, result, request_origin=origin)
                sock.close()
                return
            # POST /api/sessions/batch_export  body: {ids: [...]}
            if path == "/api/sessions/batch_export" and method == "POST":
                ids = body_json.get("ids") or []
                if not isinstance(ids, list) or not ids:
                    _send_http(sock, "400 Bad Request", "application/json",
                               b'{"error":"ids must be a non-empty list"}',
                               request_origin=origin)
                    sock.close()
                    return
                md = batch_export_chat_sessions_markdown(
                    [str(i) for i in ids], uid)
                if md is None:
                    _send_http(sock, "404 Not Found", "text/plain",
                               b"no sessions found", request_origin=origin)
                else:
                    fname = f"chats-{len(ids)}-sessions.md"
                    cd = (f"Content-Disposition: attachment; "
                          f"filename=\"{fname}\"\r\n")
                    _send_http(sock, "200 OK",
                               "text/markdown; charset=utf-8",
                               md.encode("utf-8"),
                               extra_headers=cd, request_origin=origin)
                sock.close()
                return
            parts_path = path.rstrip("/").split("/")
            # GET /api/sessions
            if len(parts_path) == 3 and method == "GET":
                _send_json(sock, {"sessions": list_chat_sessions(uid)},
                           request_origin=origin)
                sock.close()
                return
            # /api/sessions/{id}
            if len(parts_path) == 4:
                sid = parts_path[3]
                if method == "GET":
                    chat_sess = get_chat_session(sid, uid, load_config())
                    if not chat_sess:
                        _send_http(sock, "404 Not Found", "text/plain",
                                   b"session not found", request_origin=origin)
                        sock.close()
                        return
                    _send_json(sock, {
                        "id": chat_sess.session_id,
                        "title": chat_sess.title,
                        "messages": chat_sess.get_messages(),
                        "config": chat_sess.get_safe_config(),
                        "busy": not chat_sess.is_idle(),
                    }, request_origin=origin)
                    sock.close()
                    return
                if method == "PATCH":
                    title = (body_json.get("title") or "").strip()
                    if not title:
                        _send_http(sock, "400 Bad Request", "application/json",
                                   b'{"error":"title required"}',
                                   request_origin=origin)
                        sock.close()
                        return
                    ok = rename_chat_session(sid, uid, title)
                    if ok:
                        _send_json(sock, {"ok": True, "title": title[:200]},
                                   request_origin=origin)
                    else:
                        _send_http(sock, "404 Not Found", "application/json",
                                   b'{"error":"not found"}',
                                   request_origin=origin)
                    sock.close()
                    return
                if method == "DELETE":
                    ok = remove_chat_session(sid, uid)
                    _send_json(sock, {"ok": ok}, request_origin=origin)
                    sock.close()
                    return
            # PATCH /api/sessions/{id}/folder  body: {folder_id: int|null}
            if (len(parts_path) == 5 and parts_path[4] == "folder"
                    and method == "PATCH"):
                sid = parts_path[3]
                fid_raw = body_json.get("folder_id", None)
                fid = None
                if fid_raw is not None:
                    try:
                        fid = int(fid_raw)
                    except (TypeError, ValueError):
                        _send_http(sock, "400 Bad Request",
                                   "application/json",
                                   b'{"error":"folder_id must be int or null"}',
                                   request_origin=origin)
                        sock.close()
                        return
                ok = move_session_to_folder(sid, uid, fid)
                if ok:
                    _send_json(sock, {"ok": True, "folder_id": fid},
                               request_origin=origin)
                else:
                    _send_http(sock, "404 Not Found", "application/json",
                               b'{"error":"session or folder not found"}',
                               request_origin=origin)
                sock.close()
                return
            # GET /api/sessions/{id}/export
            if (len(parts_path) == 5 and parts_path[4] == "export"
                    and method == "GET"):
                sid = parts_path[3]
                md = export_chat_session_markdown(sid, uid)
                if md is None:
                    _send_http(sock, "404 Not Found", "text/plain",
                               b"session not found", request_origin=origin)
                else:
                    fname = f"chat-{sid}.md"
                    cd = (f"Content-Disposition: attachment; "
                          f"filename=\"{fname}\"\r\n")
                    _send_http(sock, "200 OK", "text/markdown; charset=utf-8",
                               md.encode("utf-8"),
                               extra_headers=cd, request_origin=origin)
                sock.close()
                return
            _send_http(sock, "404 Not Found", "text/plain", b"Not Found",
                       request_origin=origin)
            sock.close()
            return

        # ── GET/PATCH /api/config — read/write session config ───────
        if path == "/api/config":
            uid = _require_user(sock, cookie, origin)
            if uid is None:
                return
            from cheetahclaws.web.api import get_chat_session
            from cheetahclaws.config import load_config
            sid = body_json.get("session_id", "") or \
                  (query.split("sid=")[1].split("&")[0]
                   if "sid=" in query else "")
            chat_sess = get_chat_session(sid, uid, load_config()) if sid else None
            if method == "GET" and chat_sess:
                _send_json(sock, chat_sess.get_safe_config(),
                           request_origin=origin)
            elif method == "PATCH" and chat_sess:
                try:
                    updated = chat_sess.update_config(body_json.get("config", {}))
                except PermissionError as exc:
                    _send_http(
                        sock, "403 Forbidden", "application/json",
                        json.dumps({"error": str(exc)}).encode(),
                        request_origin=origin,
                    )
                except ValueError as exc:
                    _send_http(
                        sock, "400 Bad Request", "application/json",
                        json.dumps({"error": str(exc)}).encode(),
                        request_origin=origin,
                    )
                else:
                    _send_json(sock, updated, request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain",
                           b"session not found", request_origin=origin)
            sock.close()
            return

        # ── GET /api/models — list available providers and models ────
        if path == "/api/models" and method == "GET":
            if _require_user(sock, cookie, origin) is None:
                return
            from cheetahclaws.web.api import get_available_models
            _send_json(sock, {"providers": get_available_models()},
                       request_origin=origin)
            sock.close()
            return

        # ── HTTP: serve page or static files ─────────────────────────
        if method != "GET":
            _send_http(sock, "405 Method Not Allowed", "text/plain",
                       b"Method Not Allowed", request_origin=origin)
            sock.close()
            return

        if path in ("/", "/index.html"):
            body = _build_html(no_auth=_server_no_auth).encode()
            _send_http(sock, "200 OK", "text/html; charset=utf-8", body,
                       request_origin=origin)
        else:
            fname = path.lstrip("/")
            fpath = _WEB_DIR / fname
            # Allow subdirectories (e.g. static/js/*.js) but guard against
            # path traversal: resolved target must stay inside _WEB_DIR, and
            # any segment WITHIN that subtree must not be a dotfile. Checking
            # only the relative parts avoids false-positives when the install
            # path itself contains a hidden component (e.g. /.venv/, /.local/).
            rel_parts: tuple[str, ...] = ()
            try:
                resolved = fpath.resolve()
                web_root = _WEB_DIR.resolve()
                safe = resolved.is_relative_to(web_root)
                if safe:
                    rel_parts = resolved.relative_to(web_root).parts
            except (OSError, ValueError):
                safe = False
            if (safe and fpath.is_file()
                    and not any(seg.startswith(".") for seg in rel_parts)):
                body = fpath.read_bytes()
                ctype = _MIME.get(fpath.suffix, "application/octet-stream")
                # Revalidate app code (JS/CSS/HTML) on every load so edits
                # show up without forcing users to hard-refresh. Cache assets
                # (images, fonts, libs) longer since they rarely change.
                is_app_code = fpath.suffix in (".js", ".css", ".html")
                cache_hdr = ("Cache-Control: no-cache, must-revalidate\r\n"
                             if is_app_code else
                             "Cache-Control: public, max-age=86400\r\n")
                # Weak ETag from mtime+size lets the browser 304 when unchanged
                try:
                    st = fpath.stat()
                    etag = f'W/"{int(st.st_mtime)}-{st.st_size}"'
                    cache_hdr += f"ETag: {etag}\r\n"
                except OSError:
                    etag = None
                # Honor If-None-Match → 304
                inm = headers.get("if-none-match", "")
                if etag and inm and inm.strip() == etag:
                    _send_http(sock, "304 Not Modified", ctype, b"",
                               cache_hdr, request_origin=origin)
                else:
                    _send_http(sock, "200 OK", ctype, body,
                               cache_hdr, request_origin=origin)
            else:
                _send_http(sock, "404 Not Found", "text/plain", b"Not Found",
                           request_origin=origin)

        sock.close()

    except (TimeoutError, ConnectionResetError, BrokenPipeError):
        pass  # normal for idle/dropped connections
    except Exception as exc:
        from cheetahclaws.web.logging_setup import get_logger
        get_logger("server").exception("connection handler crashed",
                                        extra={"peer": str(addr),
                                               "err": str(exc)})
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ── Entry point ──────────────────────────────────────────────────────────

def _reap_stale_sessions() -> None:
    """Periodically clean up leaked PTY sessions and stale chat sessions."""
    while True:
        time.sleep(10)
        # PTY sessions (SSE mode)
        now = time.monotonic()
        stale: list[str] = []
        with _sessions_lock:
            for sid, sess in _sessions.items():
                if not sess.attached and (now - sess.created_at) > _SESSION_TIMEOUT:
                    stale.append(sid)
                elif sess.proc.poll() is not None and sess.closed:
                    stale.append(sid)
            for sid in stale:
                sess = _sessions.pop(sid)
                sess.close()
        # Chat sessions (structured API)
        try:
            from cheetahclaws.web.api import reap_stale_chat_sessions
            reap_stale_chat_sessions()
        except ImportError:
            pass


def _load_web_settings(extra_origins=None) -> dict:
    """Read the web security knobs from config.json + environment."""
    try:
        from cheetahclaws.config import load_config
        cfg = load_config()
    except Exception:  # noqa: BLE001
        cfg = {}
    origins = (_parse_origin_list(cfg.get("web_allowed_origins"))
               | _parse_origin_list(
                   os.environ.get("CHEETAHCLAWS_WEB_ALLOWED_ORIGINS", ""))
               | _parse_origin_list(extra_origins))
    return {
        "allowed_origins": origins,
        "open_registration": bool(cfg.get("web_open_registration", False)),
        "public_metrics": bool(cfg.get("web_public_metrics", False)),
        "nonadmin_privileged": bool(cfg.get("web_nonadmin_privileged",
                                            False)),
        "require_launch_token": bool(cfg.get("web_no_auth_require_token",
                                             True)),
    }


def _bind_port(host: str, preferred: Optional[int]) -> tuple[socket.socket, int]:
    """Bind a listening socket. When `preferred` is None we try the default
    port first and fall back to an OS-chosen free port if it's taken — so
    `cheetahclaws --web` Just Works even when 8080 is in use. When the user
    passes an explicit port we bind it (or fail loudly) to respect intent."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if preferred is not None:
        # User-specified port — bind it or let the error propagate.
        srv.bind((host, preferred))
        return srv, preferred
    try:
        srv.bind((host, DEFAULT_PORT))
        return srv, DEFAULT_PORT
    except OSError as exc:
        if exc.errno not in (98, 48):  # EADDRINUSE on Linux / macOS
            srv.close()
            raise
        # Port 8080 was taken — ask the kernel for any free port.
        srv.bind((host, 0))
        return srv, srv.getsockname()[1]


def start_web_server(
    port: Optional[int] = None,
    host: str = "127.0.0.1",
    no_auth: bool = False,
    allowed_origins=None,
    lan: bool = False,
) -> None:
    """Run the web server (blocking).

    ``lan``: let other devices (phones) on the network connect — binds all
    interfaces and, in --no-auth mode, accepts the persistent pairing token
    from ``web/pairing.py``. Open ``/pair`` for the QR code.

    ``allowed_origins``: extra browser origins allowed to make cross-origin
    requests, on top of ``web_allowed_origins`` in config and the
    comma-separated $CHEETAHCLAWS_WEB_ALLOWED_ORIGINS.
    """
    global _server_password, _server_no_auth, _server_cmd
    global _server_launch_token, _server_pair_token, _server_lan, _server_port

    # Guard against recursive startup (e.g. shell alias maps
    # cheetahclaws → cheetahclaws --web)
    if os.environ.get("CHEETAHCLAWS_WEB_SERVER") == "1":
        print("\033[31mError: recursive --web launch detected. "
              "Check shell aliases.\033[0m", file=sys.stderr)
        sys.exit(1)
    os.environ["CHEETAHCLAWS_WEB_SERVER"] = "1"

    _server_password = None if no_auth else _generate_password()
    _server_no_auth = no_auth
    settings = _load_web_settings(allowed_origins)
    _web_settings.update(settings)
    # --no-auth still requires a per-launch secret unless explicitly
    # disabled — see the comment on _server_launch_token.
    _server_launch_token = (_generate_password()
                            if no_auth and settings["require_launch_token"]
                            else None)
    # A supervisor that fronts this server (CheetahClaws Cloud gives every
    # user a container) pins the token so it can authenticate its proxied
    # requests without scraping stdout. Too-short values are ignored.
    _pinned = os.environ.get("CHEETAHCLAWS_LAUNCH_TOKEN", "").strip()
    if _server_launch_token is not None and len(_pinned) >= 32:
        _server_launch_token = _pinned
    _server_lan = bool(lan)
    if lan and host in ("127.0.0.1", "localhost", "::1"):
        host = "0.0.0.0"
    if lan and no_auth:
        if _server_launch_token is None:
            # Without the launch gate there is nothing to pair against, and
            # an open LAN server would run anyone's commands. Refuse.
            print("\033[31mError: --lan with --no-auth needs the access-token "
                  "gate (web_no_auth_require_token must stay true).\033[0m",
                  file=sys.stderr)
            sys.exit(2)
        from cheetahclaws.web.pairing import load_or_create_pair_token
        _server_pair_token = load_or_create_pair_token()

    # Install structured logging first so later errors are captured correctly.
    try:
        from cheetahclaws.web.logging_setup import setup_logging, get_logger
        setup_logging()
        _log = get_logger("server")
    except ImportError:
        _log = None

    # Initialize chat-UI database (graceful fallback if deps missing)
    global _chat_ui_ready
    try:
        from cheetahclaws.web.db import init_db, repo as dbrepo
        init_db()
        _chat_ui_ready = True
        _chat_user_count = dbrepo.user_count()
    except ImportError as exc:
        if _log:
            _log.warning("chat_ui_disabled_missing_deps",
                         extra={"err": str(exc),
                                "hint": "pip install 'cheetahclaws[web]'"})
        else:
            print(f"\033[33m[web] Chat UI disabled — missing deps: {exc}.\n"
                  f"      Install with: pip install 'cheetahclaws[web]'\033[0m",
                  file=sys.stderr)
        _chat_user_count = 0
    except Exception as exc:  # noqa: BLE001
        if _log:
            _log.exception("db_init_failed", extra={"err": str(exc)})
        else:
            print(f"\033[33m[web] DB init failed: {exc}\033[0m", file=sys.stderr)
        _chat_user_count = 0

    cc_bin = shutil.which("cheetahclaws")
    if cc_bin:
        _server_cmd = [cc_bin]
    else:
        cc_script = Path(__file__).resolve().parent.parent / "cheetahclaws.py"
        _server_cmd = [sys.executable, str(cc_script)]

    # Start background reaper for orphaned SSE sessions
    threading.Thread(target=_reap_stale_sessions, daemon=True).start()

    srv, port = _bind_port(host, port)
    srv.listen(5)
    _server_port = port

    print(f"\n  \033[36mCheetahClaws Web Terminal\033[0m", flush=True)
    print(f"  \033[2m{'─' * 40}\033[0m", flush=True)
    # In --no-auth mode the printed URLs carry the launch token; opening one
    # swaps it for a cookie. The desktop sidecar parses it from this line.
    tok_q = f"?token={_server_launch_token}" if _server_launch_token else ""
    print(f"  Terminal: \033[1mhttp://localhost:{port}{'/' + tok_q if tok_q else ''}\033[0m",
          flush=True)
    print(f"  Chat UI:  \033[1mhttp://localhost:{port}/chat{tok_q}\033[0m",
          flush=True)
    if host == "0.0.0.0":
        print(f"  Host:     \033[33m0.0.0.0 (network accessible)\033[0m", flush=True)
    if lan:
        pair_q = f"?token={_server_launch_token}" if _server_launch_token else ""
        print(f"  Phone:    \033[1mhttp://localhost:{port}/pair{pair_q}\033[0m "
              f"\033[2m(open on this computer, scan the QR code)\033[0m",
              flush=True)
    if not no_auth:
        print(f"  Terminal pwd: \033[1;33m{_server_password}\033[0m  "
              f"\033[2m(for / index page only)\033[0m", flush=True)
        if _chat_ui_ready:
            if _chat_user_count == 0:
                print(f"  Chat UI:  \033[2;33mfirst visit will prompt you "
                      f"to register an admin account\033[0m", flush=True)
            else:
                print(f"  Chat UI:  \033[2m{_chat_user_count} user account"
                      f"{'s' if _chat_user_count != 1 else ''} registered"
                      f"\033[0m", flush=True)
    elif _server_launch_token:
        print(f"  Auth:     \033[33mdisabled\033[0m \033[2m(open the URLs "
              f"above — they carry a per-launch access token)\033[0m",
              flush=True)
    else:
        print(f"  Auth:     \033[31mdisabled, no launch token\033[0m "
              f"\033[2m(web_no_auth_require_token=false)\033[0m", flush=True)
    if _web_settings["allowed_origins"]:
        print(f"  Origins:  \033[2m"
              f"{', '.join(sorted(_web_settings['allowed_origins']))}"
              f"\033[0m", flush=True)
    print(f"  \033[2m{'─' * 40}\033[0m", flush=True)
    print(f"  \033[2mPress Ctrl+C to stop\033[0m\n", flush=True)

    if _log:
        _log.info("server_start", extra={"host": host, "port": port,
                                          "no_auth": no_auth})
    try:
        while True:
            client, addr = srv.accept()
            t = threading.Thread(target=_handle_connection, args=(client, addr),
                                 daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n\033[2mWeb terminal stopped.\033[0m", flush=True)
        if _log:
            _log.info("server_stop")
    finally:
        srv.close()
