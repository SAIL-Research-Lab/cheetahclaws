"""Phone / second-device pairing for the web UI.

The desktop app runs ``cheetahclaws --web --no-auth`` and gates every page
behind a random *per-launch* token. That token changes on every launch, so a
phone that scanned it would lose access the next time the computer restarts
the app. Pairing adds a second, *persistent* secret:

* ``~/.cheetahclaws/web_pair_token`` (0600) — created on first use, accepted
  by the --no-auth gate only when the server runs with ``--lan``.
* The pairing page (``/pair``) shows it as a QR code inside a link such as
  ``http://192.168.1.20:8765/chat?token=<pair token>``. The phone opens the
  link once, the server swaps the token for a long-lived HttpOnly cookie.
* "Reset pairing" regenerates the file, which logs every paired device out.

In normal (password) mode no token is involved: the QR code is just the LAN
URL and the phone signs in with its account.
"""
from __future__ import annotations

import ipaddress
import os
import secrets
import socket
from pathlib import Path
from typing import Optional

PAIR_COOKIE_MAX_AGE = 365 * 24 * 3600  # paired devices stay signed in a year


def _pair_token_path() -> Path:
    return Path.home() / ".cheetahclaws" / "web_pair_token"


def _write_secret(path: Path, value: str) -> bool:
    """Write `value` to `path` with 0600 from the start. False on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(value)
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except OSError:
        return False


def load_or_create_pair_token() -> str:
    """Return the persistent pairing token, creating it on first use.

    $CHEETAHCLAWS_PAIR_TOKEN overrides the file (containers, tests). A file
    with group/other permissions is refused rather than trusted, the same rule
    as ``web_secret``. If the file can't be written the token lives for this
    process only — pairing still works until the next restart.
    """
    env = os.environ.get("CHEETAHCLAWS_PAIR_TOKEN", "").strip()
    if env:
        return env
    path = _pair_token_path()
    try:
        if path.exists():
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                raise RuntimeError(
                    f"{path} has insecure permissions {oct(mode)}. "
                    f"Run: chmod 600 '{path}' (or delete it to re-pair).")
            tok = path.read_text().strip()
            if len(tok) >= 32:
                return tok
    except RuntimeError:
        raise
    except OSError:
        pass
    tok = secrets.token_urlsafe(32)
    _write_secret(path, tok)
    return tok


def reset_pair_token() -> str:
    """Issue a new pairing token, invalidating every paired device."""
    tok = secrets.token_urlsafe(32)
    _write_secret(_pair_token_path(), tok)
    return tok


# ── Network addresses a phone can reach ─────────────────────────────────

_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale assigns from here


def _classify(ip: str) -> Optional[str]:
    """'lan' / 'tailscale' for addresses worth showing, else None."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version != 4 or addr.is_loopback or addr.is_link_local:
        return None
    if addr in _CGNAT:
        return "tailscale"
    if addr.is_private:
        return "lan"
    return None


def lan_addresses() -> list[dict]:
    """IPv4 addresses of this machine that another device could connect to.

    Uses the default-route trick (a UDP "connect" sends no packets) plus the
    host name's addresses, so it needs no third-party package. Ordered: the
    default-route LAN address first, then other LAN, then Tailscale.
    """
    found: list[str] = []

    def _add(ip: str) -> None:
        if ip and ip not in found:
            found.append(ip)

    for probe in ("192.168.0.1", "10.255.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 9))
            _add(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None,
                                       socket.AF_INET):
            _add(info[4][0])
    except OSError:
        pass

    out = []
    for ip in found:
        kind = _classify(ip)
        if kind:
            out.append({"ip": ip, "kind": kind})
    out.sort(key=lambda a: 0 if a["kind"] == "lan" else 1)
    return out


def device_urls(port: int, token: Optional[str]) -> list[dict]:
    """One connect link per reachable address."""
    q = f"?token={token}" if token else ""
    labels = {"lan": "Same Wi-Fi", "tailscale": "Tailscale (anywhere)"}
    return [{"label": labels[a["kind"]], "kind": a["kind"], "ip": a["ip"],
             "url": f"http://{a['ip']}:{port}/chat{q}"}
            for a in lan_addresses()]


# ── Web app manifest ────────────────────────────────────────────────────

def manifest(start_url: str = "/chat") -> dict:
    """The PWA manifest. `start_url` may carry the pairing token so an iOS
    home-screen app (which has its own cookie jar) signs itself in."""
    icons = "/static/icons"
    return {
        "id": "/chat",
        "name": "CheetahClaws",
        "short_name": "CheetahClaws",
        "description": "Your CheetahClaws agent, from any device.",
        "start_url": start_url,
        "scope": "/",
        "display": "standalone",
        "orientation": "any",
        "background_color": "#0b0f14",
        "theme_color": "#0b0f14",
        "icons": [
            {"src": f"{icons}/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": f"{icons}/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            {"src": f"{icons}/maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    }
