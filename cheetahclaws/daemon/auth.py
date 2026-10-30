"""auth.py — Local auth: peer-cred (Linux/macOS) for Unix sockets, bearer token for TCP.

Defaults per RFC §3 (with the audit-log default-on flip we asked for in the review):

- Unix socket: peer-credential check; same-UID accepted, different-UID rejected.
  Uses SO_PEERCRED on Linux and getpeereid() on macOS/BSD.
- TCP: 32-byte random token at ~/.cheetahclaws/daemon_token (mode 0600).
- Audit log default ON for both transports.
- Brute-force throttle: 3 fails / 10s from one peer → 60s lockout.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import json
import os
import secrets
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# struct ucred on Linux: pid_t pid, uid_t uid, gid_t gid (3x int32)
_UCRED_FMT = "iII"
_UCRED_SIZE = struct.calcsize(_UCRED_FMT)


_libc = None


def _get_libc():
    global _libc
    if _libc is not None:
        return _libc
    try:
        path = ctypes.util.find_library("c")
        if path is None:
            return None
        _libc = ctypes.CDLL(path, use_errno=True)
        # int getpeereid(int s, uid_t *euid, gid_t *egid);
        _libc.getpeereid.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        _libc.getpeereid.restype = ctypes.c_int
    except Exception:
        _libc = None
    return _libc


def _peer_uid_getpeereid(sock: socket.socket) -> Optional[int]:
    """macOS / *BSD: getpeereid(2). Returns None on error."""
    libc = _get_libc()
    if libc is None or not hasattr(libc, "getpeereid"):
        return None
    try:
        uid = ctypes.c_uint32(0)
        gid = ctypes.c_uint32(0)
        if libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return int(uid.value)
    except Exception:
        return None
    return None

THROTTLE_WINDOW_S = 10.0
THROTTLE_FAIL_LIMIT = 3
THROTTLE_LOCKOUT_S = 60.0


@dataclass(frozen=True)
class AuthInfo:
    transport: str        # "unix" | "tcp"
    peer_uid: Optional[int]
    peer_addr: str        # ip:port for tcp, "uid:<n>" for unix


class AuthError(Exception):
    """Base for auth failures (used by handler to translate to HTTP code)."""


class Unauthenticated(AuthError):
    pass


class RateLimited(AuthError):
    pass


def get_peer_uid(sock: socket.socket) -> Optional[int]:
    """Return the uid of the peer on the other side of a Unix socket.

    Linux: SO_PEERCRED. macOS / FreeBSD: getpeereid(2). Returns None on
    error or on an unsupported platform.
    """
    plat = sys.platform
    if plat.startswith("linux"):
        try:
            SO_PEERCRED = getattr(socket, "SO_PEERCRED", 17)
            creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, _UCRED_SIZE)
            _pid, uid, _gid = struct.unpack(_UCRED_FMT, creds)
            return uid
        except (OSError, AttributeError):
            return None
    if plat == "darwin" or "bsd" in plat:
        return _peer_uid_getpeereid(sock)
    return None


# ── Token storage ────────────────────────────────────────────────────────────


def _write_token_file(token_path: Path, token: str, *, exclusive: bool) -> None:
    """Write ``token`` so the file is 0600 from the moment it exists.

    ``write_text`` + ``chmod`` left a window where the token sat on disk with
    the umask's (usually 0644) permissions. ``exclusive`` creates the final
    path with O_EXCL (raises FileExistsError if another process won the race);
    otherwise a 0600 temp file is renamed over the old token atomically.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    target = token_path if exclusive else token_path.with_name(
        f".{token_path.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(str(target), flags, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(token)
    except BaseException:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    if not exclusive:
        os.replace(target, token_path)


def load_or_create_token(token_path: Path) -> str:
    if token_path.exists():
        try:   # tighten a token left 0644 by an older build
            if token_path.stat().st_mode & 0o077:
                os.chmod(token_path, 0o600)
        except OSError:
            pass
        return token_path.read_text().strip()
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        _write_token_file(token_path, token, exclusive=True)
    except FileExistsError:
        # Another process created it between exists() and open(): use theirs.
        return token_path.read_text().strip()
    return token


def rotate_token(token_path: Path) -> str:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    _write_token_file(token_path, token, exclusive=False)
    return token


# ── Audit log ───────────────────────────────────────────────────────────────


class AuditLog:
    def __init__(self, path: Path, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()
        if enabled:
            path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, **fields) -> None:
        if not self.enabled:
            return
        fields.setdefault("ts", time.time())
        line = json.dumps(fields, separators=(",", ":")) + "\n"
        with self._lock:
            with open(self.path, "a") as f:
                f.write(line)


# ── Brute-force throttle ─────────────────────────────────────────────────────


class Throttle:
    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, peer: str) -> None:
        now = time.time()
        with self._lock:
            until = self._locked_until.get(peer)
            if until and until > now:
                raise RateLimited(f"locked for {int(until - now)}s")

    def record_failure(self, peer: str) -> None:
        now = time.time()
        with self._lock:
            arr = self._fails.setdefault(peer, [])
            arr.append(now)
            cutoff = now - THROTTLE_WINDOW_S
            self._fails[peer] = [t for t in arr if t >= cutoff]
            if len(self._fails[peer]) >= THROTTLE_FAIL_LIMIT:
                self._locked_until[peer] = now + THROTTLE_LOCKOUT_S
                self._fails[peer] = []


# ── Auth gate (called from request handler) ─────────────────────────────────


class AuthGate:
    def __init__(
        self,
        transport: str,
        *,
        token: Optional[str] = None,
        expected_uid: Optional[int] = None,
        audit: Optional[AuditLog] = None,
    ) -> None:
        assert transport in ("unix", "tcp")
        self.transport = transport
        self.token = token
        self.expected_uid = expected_uid
        self.audit = audit
        self.throttle = Throttle()

    def authenticate(
        self,
        sock: socket.socket,
        client_address,
        headers,
    ) -> AuthInfo:
        peer_repr = self._peer_repr(sock, client_address)
        try:
            self.throttle.check(peer_repr)
        except RateLimited as e:
            self._audit("rate_limited", peer=peer_repr, reason=str(e))
            raise

        if self.transport == "unix":
            uid = get_peer_uid(sock)
            if self.expected_uid is not None and uid != self.expected_uid:
                self.throttle.record_failure(peer_repr)
                self._audit("denied", peer=peer_repr, reason="uid_mismatch", uid=uid)
                raise Unauthenticated(f"peer uid {uid} != {self.expected_uid}")
            self._audit("ok", peer=peer_repr, uid=uid)
            return AuthInfo("unix", uid, f"uid:{uid}")

        # TCP
        auth_header = headers.get("Authorization", "") or ""
        if not auth_header.startswith("Bearer "):
            self.throttle.record_failure(peer_repr)
            self._audit("denied", peer=peer_repr, reason="no_token")
            raise Unauthenticated("missing bearer token")
        presented = auth_header[len("Bearer "):].strip()
        if not secrets.compare_digest(presented, self.token or ""):
            self.throttle.record_failure(peer_repr)
            self._audit("denied", peer=peer_repr, reason="wrong_token")
            raise Unauthenticated("invalid token")
        self._audit("ok", peer=peer_repr)
        return AuthInfo("tcp", None, peer_repr)

    def _peer_repr(self, sock, client_address) -> str:
        if self.transport == "unix":
            uid = get_peer_uid(sock)
            return f"uid:{uid}"
        try:
            return f"{client_address[0]}:{client_address[1]}"
        except Exception:
            return "tcp:?"

    def _audit(self, outcome: str, **fields) -> None:
        if self.audit:
            self.audit.write(transport=self.transport, outcome=outcome, **fields)
