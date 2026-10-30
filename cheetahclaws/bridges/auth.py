"""Shared sender authorization for the messaging bridges.

Every bridge (Telegram, WeChat, QQ, Slack) can reach privileged actions —
``!shell`` commands, interactive PTYs, ``/`` slash commands and agent turns
that run tools — so each inbound message must come from someone the owner
has approved. This module is the single place that decides that.

Config keys (per bridge, ``<bridge>`` ∈ telegram / wechat / qq / slack):

  ``<bridge>_allowed_users``     list of sender ids allowed to drive the bot.
  ``<bridge>_allow_all_senders`` escape hatch: True restores the pre-allowlist
                                 behaviour (anyone who can message the bot).

Backward compatibility: when ``<bridge>_allowed_users`` is empty, the first
sender seen in a **1:1 private chat** is bound as the owner and persisted to
config (logged loudly). Group members are never auto-bound; they get a reply
explaining how the owner can add them.

Telegram additionally keeps its original check: the message must come from
the configured ``telegram_chat_id``.
"""
from __future__ import annotations

import sys
import threading
import time

from cheetahclaws import logging_utils as _log

BRIDGES = ("telegram", "wechat", "qq", "slack")

_lock = threading.Lock()
_last_refusal: dict[tuple[str, str], float] = {}
_REFUSAL_INTERVAL_S = 600.0   # reply to a refused sender at most every 10 min


def allowlist_key(bridge: str) -> str:
    return f"{bridge}_allowed_users"


def allowed_users(bridge: str, config: dict | None) -> list[str]:
    """Return the configured allowlist as a list of strings.

    Accepts a JSON list or a comma-separated string (``/config`` users tend
    to type the latter).
    """
    raw = (config or {}).get(allowlist_key(bridge))
    if not raw:
        return []
    if isinstance(raw, str):
        items = raw.split(",")
    elif isinstance(raw, (list, tuple, set)):
        items = list(raw)
    else:
        items = [raw]
    return [str(x).strip() for x in items if str(x).strip()]


def _persist(config: dict) -> None:
    try:
        from cheetahclaws.config import save_config
        save_config(config)
    except Exception as exc:   # read-only HOME etc. — keep the in-memory binding
        _log.warn("bridge_auth_persist_failed", error=str(exc)[:200])


def _seed_from_legacy(bridge: str, config: dict) -> list[str]:
    """Owner ids recorded by older builds that predate the allowlist."""
    if bridge == "wechat":
        uid = str(config.get("wechat_self_uid") or "").strip()
        if uid:
            return [uid]
    return []


def is_authorized(bridge: str, sender_id, chat_id=None, config: dict | None = None,
                  *, is_private: bool = False) -> bool:
    """Return True if ``sender_id`` may drive ``bridge``.

    ``is_private`` must be True only for a 1:1 conversation with the bot; it
    enables the first-contact owner auto-bind when no allowlist is set.
    Unauthorized senders must not reach shell / slash / agent dispatch.
    """
    config = config if config is not None else {}
    sender = str(sender_id or "").strip()

    # Telegram: the original chat_id pin still applies on top of the allowlist.
    if bridge == "telegram":
        expected = config.get("telegram_chat_id")
        if expected not in (None, "", 0) and str(chat_id) != str(expected):
            return False

    if config.get(f"{bridge}_allow_all_senders"):
        return True
    if not sender:
        return False

    with _lock:
        allow = allowed_users(bridge, config)
        if not allow:
            legacy = _seed_from_legacy(bridge, config)
            if legacy:
                config[allowlist_key(bridge)] = allow = legacy
                _persist(config)
        if allow:
            return sender in allow
        if not is_private:
            return False
        # First contact in a private chat with no allowlist → bind the owner.
        config[allowlist_key(bridge)] = [sender]
        _persist(config)
    msg = (f"[{bridge}] No {allowlist_key(bridge)} configured — bound the first "
           f"private-chat sender '{sender}' as owner. Only this account can run "
           f"commands now; add others with "
           f"/config {allowlist_key(bridge)}=[\"{sender}\",\"<id>\"]")
    print(msg, file=sys.stderr, flush=True)
    _log.warn("bridge_owner_auto_bound", bridge=bridge, sender=sender)
    return True


def refusal_text(bridge: str, sender_id) -> str:
    key = allowlist_key(bridge)
    return (f"⛔ Not authorized (sender id: {sender_id}). The bot owner can allow "
            f"you with: /config {key}=[...,\"{sender_id}\"]  "
            f"(or set {bridge}_allow_all_senders=true to allow everyone).")


def should_reply_refusal(bridge: str, sender_id) -> bool:
    """Throttle refusal replies so a busy group chat isn't spammed."""
    k = (bridge, str(sender_id))
    now = time.monotonic()
    with _lock:
        last = _last_refusal.get(k)
        if last is not None and now - last < _REFUSAL_INTERVAL_S:
            return False
        _last_refusal[k] = now
    return True


def log_refusal(bridge: str, sender_id, chat_id=None) -> None:
    _log.warn("bridge_sender_refused", bridge=bridge,
              sender=str(sender_id)[:64], chat=str(chat_id)[:64])
