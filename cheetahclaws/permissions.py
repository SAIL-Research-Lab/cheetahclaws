"""permissions.py — persistent permission grants and autonomous mode.

Two escape hatches from "approve every single tool call", both of which
survive a restart (the session-scoped grants on
:class:`~cheetahclaws.runtime.RuntimeContext` do not):

``always_allow``  a list of permission *signatures* ("Bash:rm",
                  "Edit:/repo/app.py") the user has approved for good.
                  Answering ``!`` at a prompt appends one.  Narrow: a grant
                  covers exactly the command or file it was given for.

``auto_approve``  full autonomy — every tool call runs without asking, the
                  way ``--accept-all`` does, except it is remembered across
                  sessions so a task never stops to ask again.  The Bash
                  hard-denylist (tools/shell.py) still refuses host-
                  destroying commands, and ``manual``/``plan`` permission
                  modes still win over it.

Both live in ``~/.cheetahclaws/config.json`` and are written through
:func:`cheetahclaws.config.save_config`.
"""
from __future__ import annotations

from typing import Iterable


# ── Persistent per-signature grants ───────────────────────────────────────

def saved_signatures(config: dict) -> set[str]:
    """The signatures the user granted permanently. Never raises."""
    raw = config.get("always_allow") or []
    if isinstance(raw, str):          # tolerate a hand-edited scalar
        raw = [raw]
    try:
        return {str(s) for s in raw if str(s).strip()}
    except TypeError:
        return set()


def is_always_allowed(signature: str, config: dict) -> bool:
    return bool(signature) and signature in saved_signatures(config)


def remember_signature(signature: str, config: dict) -> bool:
    """Persist ``signature`` to the always-allow list.

    Returns True when it was newly added. The config write is best-effort:
    a read-only HOME still gets the grant for the running session.
    """
    if not signature:
        return False
    sigs = saved_signatures(config)
    if signature in sigs:
        return False
    config["always_allow"] = sorted(sigs | {signature})
    _save(config)
    return True


def forget_signature(signature: str, config: dict) -> bool:
    """Drop one saved grant. Returns True when something was removed."""
    sigs = saved_signatures(config)
    if signature not in sigs:
        return False
    config["always_allow"] = sorted(sigs - {signature})
    _save(config)
    return True


def forget_all(config: dict) -> int:
    """Drop every saved grant; returns how many were removed."""
    n = len(saved_signatures(config))
    config["always_allow"] = []
    _save(config)
    return n


def extend_signatures(signatures: Iterable[str], config: dict) -> int:
    """Bulk-add grants (used by ``/permissions allow a b c``)."""
    added = 0
    for s in signatures:
        if remember_signature(s, config):
            added += 1
    return added


# ── Autonomous mode ───────────────────────────────────────────────────────

# Session-only twin of ``auto_approve``. The leading underscore is what keeps
# it out of the saved config (save_config strips ``_``-prefixed keys), so the
# ``--auto`` launch flag can't leak autonomy into every future session via an
# unrelated ``save_config`` call made later in the same run.
_SESSION_KEY = "_auto_approve_session"


def auto_approve_on(config: dict) -> bool:
    """True when tool calls should run without asking. A session-scoped
    setting (the ``--auto`` flag, or ``/auto off`` inside such a session)
    overrides the persisted one."""
    if _SESSION_KEY in config:
        return bool(config[_SESSION_KEY])
    return bool(config.get("auto_approve"))


def set_auto_approve(on: bool, config: dict, *, persist: bool = True) -> None:
    """Turn full autonomy on/off.

    ``persist=False`` is for the ``--auto`` launch flag, which should govern
    exactly the session it was passed to and not rewrite the user's config.
    """
    if persist:
        config["auto_approve"] = bool(on)
        config.pop(_SESSION_KEY, None)
        _save(config)
    else:
        config[_SESSION_KEY] = bool(on)


def _save(config: dict) -> None:
    try:
        from cheetahclaws.config import save_config
        save_config(config)
    except Exception:
        pass   # a failed write only costs persistence, not the grant
