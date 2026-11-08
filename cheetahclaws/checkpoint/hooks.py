"""Checkpoint hooks: intercept file-mutating tools to back up files before modification.

Covers Write, Edit, MultiEdit, NotebookEdit and ApplyPatch (every path a
patch adds, updates, deletes or moves to).  Import this module after tools
are registered to install the hooks.

State is keyed by session id so concurrent sessions in one process (daemon,
bridges, web) never see each other's tracked edits.  A tool call is
attributed to the session named by its config's ``_session_id`` when that
session was registered with :func:`set_session`; otherwise it falls back to
the most recently registered session (the historical single-REPL behaviour).
"""
from __future__ import annotations

import threading
from pathlib import Path

from . import store

# ── Module state ────────────────────────────────────────────────────────────

_lock = threading.RLock()
_current_session_id: str | None = None
_sessions: set[str] = set()
# session_id → {file_path → backup_filename (None = did not exist / not copied)}
_tracked_by_session: dict[str, dict[str, str | None]] = {}
# session_id → {file_path → existed_before_first_edit}
_existed_by_session: dict[str, dict[str, bool]] = {}


def set_session(session_id: str) -> None:
    global _current_session_id
    with _lock:
        _current_session_id = session_id
        _sessions.add(session_id)
        _tracked_by_session.setdefault(session_id, {})
        _existed_by_session.setdefault(session_id, {})


def _resolve(session_id: str | None) -> str | None:
    return session_id if session_id is not None else _current_session_id


def get_tracked_edits(session_id: str | None = None) -> dict[str, str | None]:
    """Return the current interval's tracked edits (for make_snapshot)."""
    with _lock:
        return dict(_tracked_by_session.get(_resolve(session_id), {}))


def get_pre_edit_state(session_id: str | None = None) -> dict[str, tuple[str | None, bool]]:
    """{path: (pre-edit backup name, existed_before)} for this interval."""
    sid = _resolve(session_id)
    with _lock:
        tracked = _tracked_by_session.get(sid, {})
        existed = _existed_by_session.get(sid, {})
        return {p: (b, existed.get(p, b is not None)) for p, b in tracked.items()}


def reset_tracked(session_id: str | None = None) -> None:
    """Clear tracked edits after a snapshot is created."""
    sid = _resolve(session_id)
    with _lock:
        _tracked_by_session.get(sid, {}).clear()
        _existed_by_session.get(sid, {}).clear()


def forget_session(session_id: str) -> None:
    """Drop all in-memory state for a finished session."""
    global _current_session_id
    with _lock:
        _sessions.discard(session_id)
        _tracked_by_session.pop(session_id, None)
        _existed_by_session.pop(session_id, None)
        if _current_session_id == session_id:
            _current_session_id = None


# Backwards-compatible alias: ``hooks._tracked_edits`` used to be a module
# global; it now resolves to the current session's dict.
def __getattr__(name):   # PEP 562
    if name == "_tracked_edits":
        with _lock:
            return _tracked_by_session.setdefault(_current_session_id, {}) \
                if _current_session_id is not None else {}
    raise AttributeError(name)


# ── Backup logic ────────────────────────────────────────────────────────────

def _session_for(config: dict | None) -> str | None:
    sid = (config or {}).get("_session_id")
    with _lock:
        if sid and sid in _sessions:
            return sid
        return _current_session_id


def _backup_before_write(file_path: str, session_id: str | None = None) -> None:
    """Back up a file before it is modified (first-write-wins per snapshot interval)."""
    sid = _resolve(session_id)
    if sid is None:
        return
    with _lock:
        tracked = _tracked_by_session.setdefault(sid, {})
        if file_path in tracked:
            return  # already backed up this interval
        existed = Path(file_path).exists()
        backup_name = store.track_file_edit(sid, file_path)
        tracked[file_path] = backup_name
        _existed_by_session.setdefault(sid, {})[file_path] = existed


# ── Hook installation ───────────────────────────────────────────────────────

_hooks_installed = False


def _paths_for(name: str, params: dict, config: dict) -> list[str]:
    if name == "NotebookEdit":
        fp = params.get("notebook_path", "")
        return [fp] if fp else []
    if name == "ApplyPatch":
        try:
            from cheetahclaws.tools.patch import patch_paths
            return patch_paths(params.get("patch") or params.get("input") or "", config)
        except Exception:
            return []
    fp = params.get("file_path", "")
    return [fp] if fp else []


def _wrap(name: str) -> None:
    from cheetahclaws.tool_registry import get_tool
    tool = get_tool(name)
    if not tool:
        return
    original = tool.func

    def hooked(params, config, _orig=original, _name=name):
        try:
            sid = _session_for(config)
            for fp in _paths_for(_name, params or {}, config or {}):
                _backup_before_write(fp, sid)
        except Exception:
            pass   # checkpointing must never block the edit itself
        return _orig(params, config)

    tool.func = hooked


def install_hooks() -> None:
    """Wrap file-mutating tool functions to call backup before execution."""
    global _hooks_installed
    if _hooks_installed:
        return
    _hooks_installed = True
    for name in ("Write", "Edit", "MultiEdit", "NotebookEdit", "ApplyPatch"):
        _wrap(name)
