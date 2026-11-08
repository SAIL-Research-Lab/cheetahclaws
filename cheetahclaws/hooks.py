"""User hooks: run shell commands (or Python callables) at agent lifecycle points.

Configuration lives in ``settings.json`` files, using the same shape as
Claude Code so existing hook scripts can be reused unchanged::

    {
      "hooks": {
        "PreToolUse": [
          {"matcher": "Bash|Write",
           "hooks": [{"type": "command", "command": "./scripts/guard.sh",
                      "timeout": 30}]}
        ]
      }
    }

Sources (merged, user first):

* ``~/.cheetahclaws/settings.json``                — always honored
* ``<project>/.cheetahclaws/settings.json``        — honored only when the
  workspace is trusted (``cheetahclaws.trust.is_trusted``); a repository you
  just cloned must not be able to run commands on your machine.

Events: PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart,
SessionEnd, PreCompact, Notification.  See docs/guides/hooks.md for the full
input/output contract.

A hook receives one JSON object on stdin and may answer with:

* exit 0 + JSON on stdout  → structured decision (see ``_normalize_output``)
* exit 0 + plain stdout    → additional context (UserPromptSubmit/SessionStart)
* exit 2                   → block; stderr is the reason fed back to the model
* any other exit / timeout → non-blocking error (logged), unless the hook sets
  ``"failClosed": true`` in which case it counts as a block

Plugins can register in-process hooks with :func:`register`.

Everything here is a no-op (one ``stat`` per settings file) when no hooks are
configured, so it is safe to call from the agent loop's hot path.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

HOOK_EVENTS = (
    "PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop",
    "SessionStart", "SessionEnd", "PreCompact", "Notification",
)

DEFAULT_TIMEOUT = 60          # seconds per command hook
_MAX_CAPTURE = 64 * 1024      # cap on captured stdout/stderr per hook


# ── Result ────────────────────────────────────────────────────────────────

@dataclass
class HookResult:
    """Merged outcome of every hook that matched one event.

    decision:
        PreToolUse → "allow" | "deny" | "ask" | None
        UserPromptSubmit / Stop / PostToolUse → "block" | None
    halt:
        a hook returned ``"continue": false`` — the agent should stop after
        the current step (``stop_reason`` explains why).
    """
    decision: Optional[str] = None
    reason: str = ""
    updated_input: Optional[dict] = None
    additional_context: str = ""
    system_message: str = ""
    halt: bool = False
    stop_reason: str = ""
    errors: list = field(default_factory=list)
    ran: int = 0

    @property
    def blocked(self) -> bool:
        return self.decision in ("block", "deny")


_DECISION_RANK = {None: 0, "allow": 1, "ask": 2, "block": 3, "deny": 3}


def _merge(into: HookResult, part: HookResult) -> None:
    if _DECISION_RANK.get(part.decision, 0) > _DECISION_RANK.get(into.decision, 0):
        into.decision = part.decision
    if part.reason:
        into.reason = f"{into.reason}\n{part.reason}".strip()
    if part.updated_input is not None:
        into.updated_input = part.updated_input
    if part.additional_context:
        into.additional_context = (
            f"{into.additional_context}\n{part.additional_context}".strip())
    if part.system_message:
        into.system_message = (
            f"{into.system_message}\n{part.system_message}".strip())
    if part.halt:
        into.halt = True
        into.stop_reason = into.stop_reason or part.stop_reason
    into.errors.extend(part.errors)
    into.ran += part.ran


# ── Python-callable hook registry (for plugins) ──────────────────────────

@dataclass
class _PyHook:
    event: str
    fn: Callable
    matcher: Optional[str]
    name: str


_PY_HOOKS: list[_PyHook] = []
_PY_LOCK = threading.Lock()


def register(event: str, fn: Callable, matcher: Optional[str] = None,
             name: str = "") -> Callable[[], None]:
    """Register an in-process hook.

    ``fn(payload: dict)`` is called with the same JSON object a command hook
    gets on stdin and may return ``None`` or a dict using the command-hook
    output schema (``{"decision": "deny", "reason": "..."}`` etc.).
    Returns a zero-arg callable that unregisters the hook.
    """
    if event not in HOOK_EVENTS:
        raise ValueError(f"unknown hook event {event!r}; expected one of {HOOK_EVENTS}")
    if matcher:
        re.compile(matcher)  # fail fast on a bad pattern
    hook = _PyHook(event, fn, matcher or None, name or getattr(fn, "__name__", "hook"))
    with _PY_LOCK:
        _PY_HOOKS.append(hook)

    def _unregister() -> None:
        with _PY_LOCK:
            try:
                _PY_HOOKS.remove(hook)
            except ValueError:
                pass
    return _unregister


def clear_registered() -> None:
    with _PY_LOCK:
        _PY_HOOKS.clear()


# ── Settings loading ──────────────────────────────────────────────────────

def _user_settings_path() -> Path:
    from cheetahclaws.config import CONFIG_DIR
    return Path(CONFIG_DIR) / "settings.json"


def project_dir() -> Path:
    env = os.environ.get("CHEETAHCLAWS_PROJECT_DIR")
    return Path(env) if env else Path.cwd()


def _project_settings_path(root: Optional[Path] = None) -> Path:
    return (root or project_dir()) / ".cheetahclaws" / "settings.json"


def _is_trusted(path: Path) -> bool:
    """Project hooks run arbitrary commands → only for trusted workspaces.
    The trust module may be absent on older builds; absent means untrusted."""
    try:
        from cheetahclaws.trust import is_trusted
    except ImportError:
        return False
    try:
        return bool(is_trusted(path))
    except Exception:
        return False


def _hooks_approved(settings_file: Path, hooks_block) -> bool:
    """Trusted folder AND these exact hook commands approved (see trust.py)."""
    try:
        from cheetahclaws.trust import is_hooks_approved
    except ImportError:
        return False
    try:
        return bool(is_hooks_approved(settings_file, hooks_block))
    except Exception:
        return False


_cache_lock = threading.Lock()
_cache: dict = {"key": None, "hooks": {}, "disabled": False}
_warned_untrusted: set = set()


def _stat_key(p: Path):
    try:
        st = p.stat()
        return (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(p), None, None)


def _read_settings(p: Path) -> dict:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        _warn(f"ignoring unreadable hook settings {p}: {e}")
        return {}


def _parse_hook_block(settings: dict, source: str) -> dict:
    out: dict = {}
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        if event not in HOOK_EVENTS:
            _warn(f"unknown hook event {event!r} in {source} settings — ignored")
            continue
        if isinstance(groups, dict):
            groups = [groups]
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher") or None
            if matcher in ("*", ".*"):
                matcher = None
            if matcher:
                try:
                    re.compile(matcher)
                except re.error as e:
                    _warn(f"bad hook matcher {matcher!r} ({e}) — ignored")
                    continue
            entries = group.get("hooks")
            if entries is None and "command" in group:
                entries = [group]       # flat shorthand: {"matcher", "command"}
            for h in entries or []:
                if not isinstance(h, dict):
                    continue
                if h.get("type", "command") != "command" or not h.get("command"):
                    continue
                try:
                    timeout = float(h.get("timeout", DEFAULT_TIMEOUT))
                except (TypeError, ValueError):
                    timeout = DEFAULT_TIMEOUT
                out.setdefault(event, []).append({
                    "matcher": matcher,
                    "command": str(h["command"]),
                    "timeout": max(0.1, timeout),
                    "fail_closed": bool(h.get("failClosed", h.get("fail_closed", False))),
                    "source": source,
                })
    return out


def load_hooks() -> dict:
    """Return ``{event: [command-hook dicts]}`` from user + trusted project
    settings.  Cached on the files' mtimes, so cheap to call repeatedly."""
    if os.environ.get("CHEETAHCLAWS_DISABLE_HOOKS"):
        return {}
    user_p = _user_settings_path()
    root = project_dir()
    proj_p = _project_settings_path(root)
    try:
        same = proj_p.resolve() == user_p.resolve()
    except OSError:
        same = False
    key = (_stat_key(user_p), None if same else _stat_key(proj_p))
    with _cache_lock:
        if _cache["key"] == key:
            return _cache["hooks"]

    user_s = _read_settings(user_p)
    merged: dict = {}
    disabled = bool(user_s.get("disableAllHooks"))
    for ev, lst in _parse_hook_block(user_s, "user").items():
        merged.setdefault(ev, []).extend(lst)
    if not same and key[1][1] is not None:
        proj_s = _read_settings(proj_p)
        if proj_s.get("hooks"):
            if _hooks_approved(proj_p, proj_s.get("hooks")):
                disabled = disabled or bool(proj_s.get("disableAllHooks"))
                for ev, lst in _parse_hook_block(proj_s, "project").items():
                    merged.setdefault(ev, []).extend(lst)
            elif str(root) not in _warned_untrusted:
                _warned_untrusted.add(str(root))
                _warn(f"project hooks in {proj_p} ignored: not approved "
                      f"(new or changed, or folder not trusted) — run /trust")
    if disabled:
        merged = {}
    with _cache_lock:
        _cache.update(key=key, hooks=merged)
    return merged


def has_hooks(event: str) -> bool:
    """Fast check used by the agent loop before building a payload."""
    if _PY_HOOKS and any(h.event == event for h in _PY_HOOKS):
        return True
    try:
        return bool(load_hooks().get(event))
    except Exception:
        return False


# ── Execution ─────────────────────────────────────────────────────────────

def _matches(matcher: Optional[str], value: Optional[str]) -> bool:
    if not matcher:
        return True
    if value is None:
        return True        # events without a match target ignore matchers
    try:
        return re.fullmatch(matcher, value) is not None
    except re.error:
        return False


def _normalize_output(event: str, data: dict) -> HookResult:
    """Map a hook's JSON answer onto HookResult.

    Accepts both the flat cheetahclaws keys and Claude Code's
    ``hookSpecificOutput`` envelope:

      decision            "allow"|"approve"|"deny"|"ask"|"block"
      reason              explanation (shown to the model on deny/block)
      updatedInput        PreToolUse: replacement tool input (dict)
      additionalContext   text appended for the model
      continue            false → stop the agent after this step
      stopReason          message shown when continue=false
      systemMessage       message for the user (logged / event stream)
    """
    r = HookResult(ran=1)
    hso = data.get("hookSpecificOutput")
    hso = hso if isinstance(hso, dict) else {}

    dec = hso.get("permissionDecision") or hso.get("decision") or data.get("decision")
    if isinstance(dec, str):
        dec = dec.strip().lower()
        if dec == "approve":
            dec = "allow"
        if event == "PreToolUse":
            if dec == "block":
                dec = "deny"
            if dec in ("allow", "deny", "ask"):
                r.decision = dec
        elif dec in ("block", "deny"):
            r.decision = "block"
    r.reason = str(hso.get("permissionDecisionReason") or data.get("reason") or "")
    upd = (hso.get("updatedInput") or data.get("updatedInput")
           or data.get("updated_input"))
    if isinstance(upd, dict):
        r.updated_input = upd
    ctx = (hso.get("additionalContext") or data.get("additionalContext")
           or data.get("additional_context"))
    if ctx:
        r.additional_context = str(ctx)
    if data.get("systemMessage"):
        r.system_message = str(data["systemMessage"])
    if data.get("continue") is False:
        r.halt = True
        r.stop_reason = str(data.get("stopReason") or r.reason or "stopped by hook")
    return r


def _blocking_decision(event: str) -> str:
    return "deny" if event == "PreToolUse" else "block"


def _run_command(entry: dict, event: str, payload: dict) -> HookResult:
    root = project_dir()
    env = {
        **os.environ,
        "CHEETAHCLAWS_PROJECT_DIR": str(root),
        "CLAUDE_PROJECT_DIR": str(root),   # lets Claude Code hook scripts run as-is
        "CHEETAHCLAWS_HOOK_EVENT": event,
        "CHEETAHCLAWS_SESSION_ID": str(payload.get("session_id") or ""),
    }
    cmd = entry["command"]
    try:
        proc = subprocess.run(
            cmd, shell=True, input=json.dumps(payload, default=str),
            capture_output=True, text=True, timeout=entry["timeout"],
            env=env, cwd=str(root) if root.is_dir() else None,
        )
    except subprocess.TimeoutExpired:
        return _hook_failure(entry, event, f"hook timed out after {entry['timeout']:g}s: {cmd}")
    except Exception as e:
        return _hook_failure(entry, event, f"hook failed to start ({e}): {cmd}")

    stdout = (proc.stdout or "")[:_MAX_CAPTURE].strip()
    stderr = (proc.stderr or "")[:_MAX_CAPTURE].strip()
    if proc.returncode == 2:
        r = HookResult(ran=1, decision=_blocking_decision(event),
                       reason=stderr or f"blocked by hook: {cmd}")
        if event == "PostToolUse":
            # The tool already ran; "block" here means "tell the model".
            r.additional_context = r.reason
        return r
    if proc.returncode != 0:
        return _hook_failure(
            entry, event,
            f"hook exited {proc.returncode}: {cmd}" + (f" — {stderr[:300]}" if stderr else ""))
    if stdout.startswith("{"):
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict):
            return _normalize_output(event, data)
    r = HookResult(ran=1)
    if stdout and event in ("UserPromptSubmit", "SessionStart"):
        r.additional_context = stdout
    return r


def _hook_failure(entry: dict, event: str, msg: str) -> HookResult:
    r = HookResult(ran=1, errors=[msg])
    if entry.get("fail_closed"):
        r.decision = _blocking_decision(event)
        r.reason = f"fail-closed hook error: {msg}"
    return r


def _run_python(hook: _PyHook, event: str, payload: dict) -> HookResult:
    try:
        out = hook.fn(dict(payload))
    except Exception as e:
        return HookResult(ran=1, errors=[f"python hook {hook.name} raised {type(e).__name__}: {e}"])
    if out is None:
        return HookResult(ran=1)
    if isinstance(out, HookResult):
        out.ran = max(out.ran, 1)
        return out
    if isinstance(out, dict):
        return _normalize_output(event, out)
    return HookResult(ran=1)


def _base_payload(event: str, config: Optional[dict]) -> dict:
    cfg = config or {}
    sid = cfg.get("_session_id") or ""
    payload = {
        "hook_event_name": event,
        "session_id": sid,
        "cwd": os.getcwd(),
        "permission_mode": cfg.get("permission_mode", "auto"),
    }
    em = cfg.get("_event_emitter")
    path = getattr(em, "path", None)
    if path:
        payload["transcript_path"] = str(path)
    return payload


def run_hooks(event: str, payload: Optional[dict] = None, *,
              match_value: Optional[str] = None,
              config: Optional[dict] = None) -> HookResult:
    """Run every hook registered for ``event`` whose matcher accepts
    ``match_value`` (tool name for tool events).  Hooks run sequentially in
    config order (user, then project, then Python-registered); a PreToolUse
    ``updatedInput`` is visible to the hooks that follow it."""
    result = HookResult()
    if event not in HOOK_EVENTS:
        return result
    try:
        cmd_hooks = [h for h in load_hooks().get(event, [])
                     if _matches(h["matcher"], match_value)]
    except Exception as e:
        cmd_hooks = []
        result.errors.append(f"failed to load hooks: {e}")
    with _PY_LOCK:
        py_hooks = [h for h in _PY_HOOKS
                    if h.event == event and _matches(h.matcher, match_value)]
    if not cmd_hooks and not py_hooks:
        return result

    full = {**_base_payload(event, config), **(payload or {})}
    for entry in cmd_hooks:
        part = _run_command(entry, event, full)
        _merge(result, part)
        if part.updated_input is not None and "tool_input" in full:
            full["tool_input"] = part.updated_input
    for hook in py_hooks:
        part = _run_python(hook, event, full)
        _merge(result, part)
        if part.updated_input is not None and "tool_input" in full:
            full["tool_input"] = part.updated_input

    for e in result.errors:
        _warn(e)
    _record(event, match_value, result, config)
    return result


def fire_and_forget(event: str, payload: Optional[dict] = None, *,
                    match_value: Optional[str] = None,
                    config: Optional[dict] = None) -> None:
    """Run hooks for an informational event (Notification, SessionEnd …) on a
    daemon thread so a slow hook never delays the agent."""
    if not has_hooks(event):
        return
    t = threading.Thread(
        target=lambda: run_hooks(event, payload, match_value=match_value, config=config),
        name=f"hook-{event}", daemon=True)
    t.start()


def _record(event: str, match_value, result: HookResult, config) -> None:
    """Mirror a hook outcome into the session event log, if one is attached."""
    em = (config or {}).get("_event_emitter")
    if em is None or not result.ran:
        return
    try:
        fields = {"event": event, "hooks_run": result.ran}
        if match_value is not None:
            fields["matcher_value"] = match_value
        if result.decision:
            fields["decision"] = result.decision
        if result.reason:
            fields["reason"] = result.reason[:2000]
        if result.updated_input is not None:
            fields["updated_input"] = result.updated_input
        if result.additional_context:
            fields["additional_context"] = result.additional_context[:2000]
        if result.system_message:
            fields["system_message"] = result.system_message[:2000]
        if result.halt:
            fields["halt"] = True
            fields["stop_reason"] = result.stop_reason
        if result.errors:
            fields["errors"] = result.errors[:10]
        em.emit("hook", **fields)
    except Exception:
        pass


# ── Session-level helpers ─────────────────────────────────────────────────

_pending_context: dict = {}
_pending_lock = threading.Lock()


def session_start(config: dict, source: str = "startup") -> HookResult:
    """Fire SessionStart.  Context a hook returns is queued and attached to
    the first user message of the session by ``agent.run``."""
    if not has_hooks("SessionStart"):
        return HookResult()
    r = run_hooks("SessionStart", {"source": source}, match_value=source, config=config)
    if r.additional_context:
        sid = config.get("_session_id") or "default"
        with _pending_lock:
            _pending_context[sid] = (
                _pending_context.get(sid, "") + "\n" + r.additional_context).strip()
    return r


def pop_session_context(session_id: str) -> str:
    with _pending_lock:
        return _pending_context.pop(session_id or "default", "")


def session_end(config: dict, reason: str = "exit") -> None:
    if has_hooks("SessionEnd"):
        run_hooks("SessionEnd", {"reason": reason}, match_value=reason, config=config)


def _warn(msg: str) -> None:
    try:
        from cheetahclaws import logging_utils as _log
        _log.warn("hook_warning", message=msg[:500])
    except Exception:
        pass
    try:
        print(f"[hooks] {msg}", file=sys.stderr)
    except Exception:
        pass
