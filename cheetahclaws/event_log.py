"""Per-session append-only event log + replay.

One :class:`EventEmitter` per session is the single source of structured
events.  It appends each event as one JSON line to
``~/.cheetahclaws/sessions/<session_id>/events.jsonl`` and fans it out to any
attached sinks (``cheetahclaws exec --output-format stream-json`` is just a
sink that writes the same dicts to stdout).

Event envelope (every event)::

    {"type": "<event type>", "seq": 7, "ts": 1730000000.123,
     "session_id": "1a2b3c4d", ...type-specific fields}

``ts`` is epoch seconds like the kernel's ``agent_events.ts``; ``type`` plays
the role of the kernel's ``kind`` and ``seq`` of its ``event_id`` (monotonic
per session).  Fields are flat rather than nested under ``payload`` so the
stream is pleasant to consume with ``jq``.

Event types: session_start, user_message, assistant_delta (streamed to sinks,
not persisted by default), assistant_message, tool_call, permission_decision,
tool_result, usage, hook, compaction, notice, error, result, session_end.

``cheetahclaws replay <session-id>`` renders a past session's timeline.  It
is read-only: nothing is re-executed.

Opt out of persistence with ``event_log: false`` in config.  This module never
imports the kernel and is cheap enough for the agent loop's hot path.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

# Streamed to sinks but not written to disk unless persist_deltas=True:
# token deltas would multiply the log size for no replay value (the full text
# is recorded in assistant_message).
NON_PERSISTED_TYPES = frozenset({"assistant_delta"})

DEFAULT_MAX_OUTPUT_CHARS = 4000

_SID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def sessions_dir() -> Path:
    from cheetahclaws.config import SESSIONS_DIR
    return Path(SESSIONS_DIR)


def valid_session_id(session_id: str) -> bool:
    return bool(session_id) and bool(_SID_RE.match(session_id)) and session_id not in (".", "..")


def events_path(session_id: str, base_dir: Optional[Path] = None) -> Path:
    if not valid_session_id(session_id):
        raise ValueError(f"invalid session id: {session_id!r}")
    return Path(base_dir or sessions_dir()) / session_id / "events.jsonl"


def truncate_output(text, limit: int = DEFAULT_MAX_OUTPUT_CHARS) -> str:
    s = text if isinstance(text, str) else str(text)
    if limit and len(s) > limit:
        return s[:limit] + f"\n… [truncated {len(s) - limit} chars]"
    return s


class EventEmitter:
    """Thread-safe emitter: append to the session's JSONL file + fan out."""

    def __init__(self, session_id: str, *, persist: bool = True,
                 base_dir: Optional[Path] = None, persist_deltas: bool = False,
                 max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS):
        self.session_id = session_id
        self.persist = bool(persist) and valid_session_id(session_id)
        self.persist_deltas = persist_deltas
        self.max_output_chars = max_output_chars
        self.path: Optional[Path] = (
            events_path(session_id, base_dir) if self.persist else None)
        self._sinks: list[Callable[[dict], None]] = []
        self._lock = threading.Lock()
        self._fh = None
        self._seq = self._last_seq() if self.path else 0
        self._closed = False

    # ── sinks ──
    def add_sink(self, fn: Callable[[dict], None]) -> None:
        self._sinks.append(fn)

    # ── emit ──
    def emit(self, type: str, **fields) -> dict:
        with self._lock:
            self._seq += 1
            ev = {"type": type, "seq": self._seq,
                  "ts": round(time.time(), 3), "session_id": self.session_id}
            ev.update(fields)
            if (self.path is not None and not self._closed
                    and (type not in NON_PERSISTED_TYPES or self.persist_deltas)):
                self._write(ev)
            sinks = list(self._sinks)
        for sink in sinks:
            try:
                sink(ev)
            except Exception:
                pass
        return ev

    def _write(self, ev: dict) -> None:
        try:
            if self._fh is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._fh = open(self.path, "a", encoding="utf-8")
            self._fh.write(json.dumps(ev, default=str, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception:
            # A full disk or read-only home must never break a session.
            self.path = None

    def _last_seq(self) -> int:
        """Continue numbering when appending to an existing (resumed) log."""
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 65536))
                tail = f.read().decode("utf-8", "ignore").splitlines()
            for line in reversed(tail):
                try:
                    return int(json.loads(line).get("seq", 0))
                except Exception:
                    continue
        except OSError:
            pass
        return 0

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None


def make_emitter(session_id: str, config: Optional[dict] = None) -> EventEmitter:
    cfg = config or {}
    return EventEmitter(
        session_id,
        persist=cfg.get("event_log", True) is not False,
        persist_deltas=bool(cfg.get("event_log_deltas", False)),
    )


# ── Reading ───────────────────────────────────────────────────────────────

def read_events(session_id: str, base_dir: Optional[Path] = None) -> list[dict]:
    path = events_path(session_id, base_dir)
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue          # torn last line after a crash
            if isinstance(ev, dict):
                out.append(ev)
    return out


def list_logged_sessions(base_dir: Optional[Path] = None) -> list[tuple[str, float]]:
    """(session_id, mtime) for every session with an event log, newest first."""
    root = Path(base_dir or sessions_dir())
    found = []
    try:
        for d in root.iterdir():
            p = d / "events.jsonl"
            if d.is_dir() and p.is_file():
                found.append((d.name, p.stat().st_mtime))
    except OSError:
        return []
    found.sort(key=lambda t: t[1], reverse=True)
    return found


def resolve_session_id(prefix: str, base_dir: Optional[Path] = None) -> Optional[str]:
    """Exact id, unique prefix, or "last"/"latest"."""
    sessions = list_logged_sessions(base_dir)
    if prefix in ("last", "latest"):
        return sessions[0][0] if sessions else None
    ids = [s for s, _ in sessions]
    if prefix in ids:
        return prefix
    matches = [s for s in ids if s.startswith(prefix)]
    return matches[0] if len(matches) == 1 else None


# ── Rendering ─────────────────────────────────────────────────────────────

def _clock(ts) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "--:--:--"


def _short(text, limit: Optional[int]) -> str:
    s = text if isinstance(text, str) else json.dumps(text, default=str, ensure_ascii=False)
    s = s.rstrip()
    if limit and len(s) > limit:
        return s[:limit] + f" … (+{len(s) - limit} chars)"
    return s


def _indent(text: str, pad: str = "             ") -> str:
    return "\n".join(pad + ln for ln in text.splitlines()) if text else ""


def render_event(ev: dict, full: bool = False) -> Optional[str]:
    """One human-readable block for an event (None to skip it)."""
    lim = None if full else 400
    t = ev.get("type", "?")
    head = f"[{_clock(ev.get('ts'))}] "
    depth = ev.get("depth")
    if depth:
        head += f"(sub-agent d{depth}) "
    if t == "session_start":
        bits = [f"model={ev.get('model', '?')}", f"cwd={ev.get('cwd', '?')}"]
        if ev.get("mode"):
            bits.append(f"mode={ev['mode']}")
        if ev.get("resumed"):
            bits.append("resumed")
        return head + "== session start  " + "  ".join(bits)
    if t == "user_message":
        return head + "USER\n" + _indent(_short(ev.get("text", ""), lim))
    if t == "assistant_message":
        text = ev.get("text") or ""
        calls = ev.get("tool_calls") or []
        lines = head + "ASSISTANT"
        if text.strip():
            lines += "\n" + _indent(_short(text, lim))
        if calls and not text.strip():
            lines += f"  ({len(calls)} tool call{'s' if len(calls) != 1 else ''})"
        return lines
    if t == "tool_call":
        return (head + f"-> {ev.get('name')}  [{ev.get('id', '')}]\n"
                + _indent(_short(ev.get("input", {}), None if full else 300)))
    if t == "permission_decision":
        reason = f" — {ev['reason']}" if ev.get("reason") else ""
        return (head + f"   permission {str(ev.get('decision', '?')).upper()} "
                f"{ev.get('name', '')} via {ev.get('source', '?')}{reason}")
    if t == "tool_result":
        mark = "ERROR" if ev.get("is_error") else "ok"
        out = _short(ev.get("output", ""), None if full else 300)
        return (head + f"<- {ev.get('name', '')} {mark}  [{ev.get('id', '')}]"
                + ("\n" + _indent(out) if out else ""))
    if t == "usage":
        return (head + f"   tokens +{ev.get('input_tokens', 0)} in / "
                f"+{ev.get('output_tokens', 0)} out")
    if t == "hook":
        bits = [str(ev.get("event"))]
        if ev.get("matcher_value"):
            bits.append(str(ev["matcher_value"]))
        if ev.get("decision"):
            bits.append(f"decision={ev['decision']}")
        if ev.get("reason"):
            bits.append(f"reason={_short(ev['reason'], 200)}")
        if ev.get("errors"):
            bits.append(f"errors={len(ev['errors'])}")
        return head + "   hook " + " ".join(bits)
    if t == "compaction":
        return head + f"   context compacted ({ev.get('trigger', 'auto')})"
    if t == "notice":
        return head + "   note: " + _short(ev.get("text", ""), lim)
    if t == "error":
        return head + "!! error: " + _short(ev.get("message", ""), lim)
    if t == "result":
        bits = [f"exit_reason={ev.get('exit_reason')}", f"turns={ev.get('turns')}"]
        if ev.get("cost_usd") is not None:
            bits.append(f"cost=${float(ev['cost_usd']):.4f}")
        if ev.get("duration_ms") is not None:
            bits.append(f"duration={int(ev['duration_ms']) / 1000:.1f}s")
        return head + "== result  " + "  ".join(bits)
    if t == "session_end":
        return head + f"== session end ({ev.get('reason', 'exit')})"
    if t == "assistant_delta":
        return None
    return head + f"   {t} " + _short({k: v for k, v in ev.items()
                                       if k not in ("type", "seq", "ts", "session_id")}, 200)


def render_timeline(events: Iterable[dict], full: bool = False) -> str:
    blocks = [b for b in (render_event(ev, full) for ev in events) if b]
    return "\n".join(blocks)


def replay_main(argv: list[str]) -> int:
    """`cheetahclaws replay [session-id|last] [--json] [--full] [--list]`."""
    import argparse
    p = argparse.ArgumentParser(
        prog="cheetahclaws replay",
        description="Show the recorded event timeline of a past session "
                    "(read-only; nothing is re-executed).")
    p.add_argument("session_id", nargs="?",
                   help="session id, unique prefix, or 'last' (omit to list sessions)")
    p.add_argument("--json", action="store_true", help="print raw JSONL events")
    p.add_argument("--full", action="store_true", help="do not truncate long text")
    p.add_argument("--list", action="store_true", help="list sessions with event logs")
    p.add_argument("--limit", type=int, default=20, help="rows for --list (default 20)")
    a = p.parse_args(argv)

    if a.list or not a.session_id:
        rows = list_logged_sessions()
        if not rows:
            print("No recorded sessions (event logs live in "
                  f"{sessions_dir()}/<id>/events.jsonl).")
            return 0
        print("Recorded sessions (newest first):")
        for sid, mtime in rows[: max(1, a.limit)]:
            print(f"  {sid:<16} {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))}")
        print("\nReplay one with: cheetahclaws replay <session-id>")
        return 0

    sid = resolve_session_id(a.session_id)
    if not sid:
        print(f"No event log found for session {a.session_id!r} "
              "(ambiguous prefix or event_log disabled).", file=sys.stderr)
        return 1
    try:
        events = read_events(sid)
    except (OSError, ValueError) as e:
        print(f"Cannot read event log for {sid}: {e}", file=sys.stderr)
        return 1
    if a.json:
        for ev in events:
            print(json.dumps(ev, ensure_ascii=False, default=str))
        return 0
    print(f"Session {sid} — {len(events)} events — {events_path(sid)}")
    print(render_timeline(events, full=a.full))
    return 0
