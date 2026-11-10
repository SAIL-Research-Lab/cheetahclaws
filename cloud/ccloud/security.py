"""Passwords, session cookies, encrypted API keys, derived per-user tokens."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

SESSION_COOKIE = "ccsess"
SESSION_TTL = 30 * 24 * 3600


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt()).decode()


def check_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_session(uid: int, secret: str, rev: int = 0) -> str:
    now = int(time.time())
    return jwt.encode({"sub": str(uid), "iat": now, "exp": now + SESSION_TTL},
                      secret, algorithm="HS256")


def read_session(token: str, secret: str) -> Optional[int]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


class KeyBox:
    """Encrypts users' own provider API keys at rest."""

    def __init__(self, key: str):
        self._f = Fernet(key.encode() if isinstance(key, str) else key)

    def seal(self, plaintext: str) -> str:
        return self._f.encrypt(plaintext.encode()).decode() if plaintext else ""

    def open(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._f.decrypt(token.encode()).decode()
        except InvalidToken:
            return ""


def _derive(secret: str, purpose: str, uid: int) -> str:
    return hmac.new(secret.encode(), f"{purpose}:{uid}".encode(),
                    hashlib.sha256).hexdigest()


def launch_token(secret: str, uid: int) -> str:
    """The sandbox's pinned web token (CHEETAHCLAWS_LAUNCH_TOKEN). Only the
    gateway knows it; it injects it into proxied requests."""
    return _derive(secret, "launch", uid)


def model_token(secret: str, uid: int) -> str:
    """Bearer key the user's sandbox uses for our model gateway."""
    return f"ccu_{uid}_{_derive(secret, 'model', uid)[:40]}"


def parse_model_token(secret: str, token: str) -> Optional[int]:
    try:
        prefix, uid_s, _sig = token.split("_", 2)
        uid = int(uid_s)
    except ValueError:
        return None
    if prefix != "ccu":
        return None
    return uid if hmac.compare_digest(token, model_token(secret, uid)) else None


def mask_key(key: str) -> str:
    if not key:
        return ""
    return key[:4] + "…" + key[-4:] if len(key) > 12 else "…" + key[-2:]
