"""
commands/session.py — Session management commands for CheetahClaws.

Commands: /save, /load, /resume, /history, /cloudsave, /exit
Also exports: save_latest, _build_session_data (used by repl.py)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from cheetahclaws.ui.render import clr, info, ok, warn, err

# ── Session format version ─────────────────────────────────────────────────
# Increment when the on-disk structure changes in a backward-incompatible way.
# Loaders call _migrate_session(data) which upgrades older files in memory.
SESSION_VERSION = 1


def _migrate_session(data: dict) -> dict:
    """Upgrade a session dict to the current SESSION_VERSION format.

    Always returns a (possibly modified) copy — never mutates the input.
    Unknown future versions are accepted as-is to be forward-compatible.
    """
    v = data.get("_version", 0)
    if v == SESSION_VERSION:
        return data           # already current
    out = dict(data)
    # v0 → v1: no structural change; just tag it
    if v == 0:
        out["_version"] = 1
    return out


# ── Session data builder ───────────────────────────────────────────────────

def derive_title(messages: list, max_len: int = 64) -> str:
    """A human-readable name for a session: its opening request.

    /resume lists sessions by this, the way Claude Code does — "id:4f2a1c
    turns:12" tells you nothing about which conversation it was, while
    "Add a /resume picker with session names" does. Taken from the first
    real user message: slash commands, system-injected turns and tool
    results are skipped, newlines collapse to spaces, and the result is
    ellipsized so every row stays one line.
    """
    for m in messages or []:
        if m.get("role") != "user":
            continue
        content = m.get("content", "")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        text = ""          # a tool result is not a request
                        break
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        break
        text = " ".join(str(text).split())
        if not text:
            continue
        # Skip slash commands and the framework's own injected prompts.
        if text.startswith("/") or text.startswith("(System"):
            continue
        if text.startswith("[") and "]" in text[:40]:
            text = text.split("]", 1)[1].strip() or text
        if not text:
            continue
        return text if len(text) <= max_len else text[:max_len - 1] + "…"
    return ""


def _build_session_data(state, session_id: str | None = None) -> dict:
    """Serialize current conversation state to a JSON-serializable dict."""
    import uuid
    return {
        "_version": SESSION_VERSION,
        "session_id": session_id or uuid.uuid4().hex[:8],
        "title": derive_title(getattr(state, "messages", [])),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [
            m if not isinstance(m.get("content"), list) else
            {**m, "content": [
                b if isinstance(b, dict) else b.model_dump()
                for b in m["content"]
            ]}
            for m in state.messages
        ],
        "turn_count": state.turn_count,
        "total_input_tokens": state.total_input_tokens,
        "total_output_tokens": state.total_output_tokens,
    }


# ── /save ──────────────────────────────────────────────────────────────────

def cmd_save(args: str, state, config) -> bool:
    from cheetahclaws.config import SESSIONS_DIR
    import uuid
    sid   = uuid.uuid4().hex[:8]
    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = args.strip() or f"session_{ts}_{sid}.json"
    path  = Path(fname) if "/" in fname else SESSIONS_DIR / fname
    data  = _build_session_data(state, session_id=sid)
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False),
                    encoding="utf-8")
    ok(f"Session saved → {path}  (id: {sid})")
    return True


# ── save_latest (auto-save on exit) ───────────────────────────────────────

def save_latest(args: str, state, config=None) -> bool:
    """Save session on exit: session_latest.json + daily/ copy + append to history.json."""
    from cheetahclaws.config import MR_SESSION_DIR, DAILY_DIR, SESSION_HIST_FILE
    if not state.messages:
        return True

    cfg = config or {}
    daily_limit   = cfg.get("session_daily_limit",   5)
    history_limit = cfg.get("session_history_limit", 100)

    import uuid
    now = datetime.now()
    sid = uuid.uuid4().hex[:8]
    ts  = now.strftime("%H%M%S")
    date_str = now.strftime("%Y-%m-%d")
    data = _build_session_data(state, session_id=sid)
    payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)

    def _atomic_write(path: Path, content: str):
        """Write to a temp file then rename — prevents corruption on crash."""
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)

    try:
        MR_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        latest_path = MR_SESSION_DIR / "session_latest.json"
        _atomic_write(latest_path, payload)
    except Exception as e:
        err(f"Failed to save session: {e}")
        return True

    try:
        day_dir = DAILY_DIR / date_str
        day_dir.mkdir(parents=True, exist_ok=True)
        daily_path = day_dir / f"session_{ts}_{sid}.json"
        _atomic_write(daily_path, payload)

        daily_files = sorted(day_dir.glob("session_*.json"))
        for old in daily_files[:-daily_limit]:
            old.unlink(missing_ok=True)
    except Exception as e:
        warn(f"Daily backup failed: {e}")
        daily_path = Path("(skipped)")

    try:
        if SESSION_HIST_FILE.exists():
            try:
                hist = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                hist = {"total_turns": 0, "sessions": []}
        else:
            hist = {"total_turns": 0, "sessions": []}

        hist["sessions"].append(data)
        hist["total_turns"] = sum(s.get("turn_count", 0) for s in hist["sessions"])

        if len(hist["sessions"]) > history_limit:
            hist["sessions"] = hist["sessions"][-history_limit:]

        _atomic_write(SESSION_HIST_FILE, json.dumps(hist, indent=2, default=str, ensure_ascii=False))
    except Exception as e:
        warn(f"History update failed: {e}")

    # Also save to SQLite for full-text search
    try:
        from cheetahclaws.session_store import save_session as _db_save
        _db_save(
            session_id=sid,
            messages=data.get("messages", []),
            title=data.get("title", ""),
            model=cfg.get("model", ""),
            turn_count=data.get("turn_count", 0),
            input_tokens=data.get("total_input_tokens", 0),
            output_tokens=data.get("total_output_tokens", 0),
        )
    except Exception:
        pass  # SQLite save is best-effort

    ok(f"Session saved → {latest_path}")
    if str(daily_path) != "(skipped)":
        ok(f"             → {daily_path}  (id: {sid})")
    return True


# ── autosave (per-turn crash safety) ──────────────────────────────────────
# A running session keeps one stable id so every autosave rewrites the SAME
# session_latest.json instead of churning new ids each turn.
_autosave_sid: str | None = None


def autosave_session(state, config=None) -> None:
    """Silently persist the live transcript to session_latest.json after every
    turn, so a crash or power loss mid-conversation stays recoverable via
    /resume.

    Unlike save_latest(), this ONLY rewrites session_latest.json — no daily
    copy, no history.json append, no SQLite row, no console output. Those are
    exit-time finalization steps; doing them every turn would spam daily/ and
    history.json with dozens of partial sessions. Best-effort: this must never
    raise into the REPL loop.
    """
    from cheetahclaws.config import MR_SESSION_DIR
    if not getattr(state, "messages", None):
        return

    global _autosave_sid
    if _autosave_sid is None:
        import uuid
        _autosave_sid = uuid.uuid4().hex[:8]

    try:
        data = _build_session_data(state, session_id=_autosave_sid)
        payload = json.dumps(data, indent=2, default=str, ensure_ascii=False)
        MR_SESSION_DIR.mkdir(parents=True, exist_ok=True)
        latest_path = MR_SESSION_DIR / "session_latest.json"
        # Temp + fsync + atomic replace: fsync forces the bytes to disk so a
        # power cut can't leave session_latest.json pointing at unflushed data.
        tmp = latest_path.with_suffix(".autosave.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, latest_path)
    except Exception:
        pass  # autosave is best-effort; never disrupt the conversation


# ── /load ──────────────────────────────────────────────────────────────────

def cmd_load(args: str, state, config) -> bool:
    from cheetahclaws.config import SESSIONS_DIR, MR_SESSION_DIR, DAILY_DIR
    from cheetahclaws.tools import ask_input_interactive

    path = None
    if not args.strip():
        sessions: list[Path] = []
        if DAILY_DIR.exists():
            for day_dir in sorted(DAILY_DIR.iterdir(), reverse=True):
                if day_dir.is_dir():
                    sessions.extend(sorted(day_dir.glob("session_*.json"), reverse=True))
        if not sessions and MR_SESSION_DIR.exists():
            sessions = [s for s in sorted(MR_SESSION_DIR.glob("*.json"), reverse=True)
                        if s.name != "session_latest.json"]
        sessions.extend(sorted(SESSIONS_DIR.glob("session_*.json"), reverse=True))

        if not sessions:
            info("No saved sessions found.")
            return True

        print(clr("  Select a session to load:", "cyan", "bold"))
        menu_buf = clr('  Select a session to load:', 'cyan', 'bold')
        prev_date = None
        for i, s in enumerate(sessions):
            date_label = s.parent.name if s.parent.name != "mr_sessions" else ""
            if date_label and date_label != prev_date:
                print(clr(f"\n  ── {date_label} ──", "dim"))
                menu_buf += "\n" + clr(f"\n  ── {date_label} ──", "dim")
                prev_date = date_label

            label = s.name
            try:
                meta     = json.loads(s.read_text(encoding="utf-8"))
                saved_at = meta.get("saved_at", "")[-8:]
                sid      = meta.get("session_id", "")
                turns    = meta.get("turn_count", "?")
                label    = f"{saved_at}  id:{sid}  turns:{turns}  {s.name}"
            except Exception:
                pass
            print(clr(f"  [{i+1:2d}] ", "yellow") + label)
            menu_buf += "\n" + clr(f"  [{i+1:2d}] ", "yellow") + label

        from cheetahclaws.config import SESSION_HIST_FILE
        has_history = SESSION_HIST_FILE.exists()
        if has_history:
            try:
                hist_meta = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
                n_sess  = len(hist_meta.get("sessions", []))
                n_turns = hist_meta.get("total_turns", 0)
                print(clr(f"\n  ── Complete History ──", "dim"))
                menu_buf += "\n" + clr(f"\n  ── Complete History ──", "dim")
                hist_prt = clr("  [ H] ", "yellow") + f"Load ALL history  ({n_sess} sessions / {n_turns} total turns)  {SESSION_HIST_FILE}"
                print(hist_prt)
                menu_buf += "\n" + hist_prt
            except Exception:
                has_history = False

        print()
        ans = ask_input_interactive(clr("  Enter number(s) (e.g. 1 or 1,2,3), H for full history, or Enter to cancel > ", "cyan"), config, menu_buf).strip().lower()

        if not ans:
            info("  Cancelled.")
            return True

        if ans == "h":
            if not has_history:
                err("history.json not found.")
                return True
            hist_data = json.loads(SESSION_HIST_FILE.read_text(encoding="utf-8"))
            all_sessions = hist_data.get("sessions", [])
            if not all_sessions:
                info("history.json is empty.")
                return True
            all_messages = []
            for s in all_sessions:
                all_messages.extend(s.get("messages", []))
            total_turns = sum(s.get("turn_count", 0) for s in all_sessions)
            est_tokens = sum(len(str(m.get("content", ""))) for m in all_messages) // 4
            print()
            print(clr(f"  {len(all_messages)} messages / ~{est_tokens:,} tokens estimated", "dim"))
            confirm = ask_input_interactive(clr("  Load full history into current session? [y/N] > ", "yellow"), config).strip().lower()
            if confirm != "y":
                info("  Cancelled.")
                return True
            state.messages = all_messages
            state.turn_count = total_turns
            ok(f"Full history loaded from {SESSION_HIST_FILE} ({len(all_messages)} messages across {len(all_sessions)} sessions)")
            return True

        raw_parts = [p.strip() for p in ans.split(",")]
        indices = []
        for p in raw_parts:
            if not p.isdigit():
                err(f"Invalid input '{p}'. Enter numbers separated by commas, or H.")
                return True
            idx = int(p) - 1
            if idx < 0 or idx >= len(sessions):
                err(f"Invalid selection: {p} (valid range: 1–{len(sessions)})")
                return True
            if idx not in indices:
                indices.append(idx)

        if len(indices) == 1:
            path = sessions[indices[0]]
        else:
            all_messages = []
            total_turns  = 0
            loaded_names = []
            for idx in indices:
                s_path = sessions[idx]
                s_data = _migrate_session(json.loads(s_path.read_text(encoding="utf-8")))
                all_messages.extend(s_data.get("messages", []))
                total_turns += s_data.get("turn_count", 0)
                loaded_names.append(s_path.name)
            est_tokens = sum(len(str(m.get("content", ""))) for m in all_messages) // 4
            print()
            print(clr(f"  {len(loaded_names)} sessions / {len(all_messages)} messages / ~{est_tokens:,} tokens estimated", "dim"))
            confirm = ask_input_interactive(clr("  Merge and load? [y/N] > ", "yellow"), config).strip().lower()
            if confirm != "y":
                info("  Cancelled.")
                return True
            state.messages = all_messages
            state.turn_count = total_turns
            ok(f"Loaded {len(loaded_names)} sessions ({len(all_messages)} messages): {', '.join(loaded_names)}")
            return True

    if not path:
        fname = args.strip()
        path = Path(fname) if "/" in fname or "\\" in fname else SESSIONS_DIR / fname
        if not path.exists() and ("/" not in fname and "\\" not in fname):
            for alt in [MR_SESSION_DIR / fname,
                        *(d / fname for d in DAILY_DIR.iterdir()
                          if DAILY_DIR.exists() and d.is_dir())]:
                if alt.exists():
                    path = alt
                    break
        if not path.exists():
            err(f"File not found: {path}")
            return True

    try:
        raw = path.read_text(encoding="utf-8")
        data = _migrate_session(json.loads(raw))
    except json.JSONDecodeError as e:
        err(f"Session file is corrupted: {path}")
        warn(f"  JSON error: {e}")
        warn(f"  Try loading a different session from: /load")
        return True
    except Exception as e:
        err(f"Cannot read session file: {e}")
        return True
    state.messages = data.get("messages", [])
    state.turn_count = data.get("turn_count", 0)
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)
    ok(f"Session loaded from {path} ({len(state.messages)} messages)")
    return True


# ── Replaying a resumed transcript ─────────────────────────────────────────

def _message_text(content) -> str:
    """The human-readable text of a message, ignoring tool plumbing."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            block = getattr(block, "__dict__", {}) or {}
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p)


def _tool_blocks(content) -> list[dict]:
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if not isinstance(block, dict):
            block = getattr(block, "__dict__", {}) or {}
        if block.get("type") == "tool_use":
            out.append(block)
    return out


def _is_tool_result(content) -> bool:
    if not isinstance(content, list):
        return False
    for block in content:
        if not isinstance(block, dict):
            block = getattr(block, "__dict__", {}) or {}
        if block.get("type") == "tool_result":
            return True
    return False


def replay_conversation(messages: list, config=None, max_messages: int = 0) -> None:
    """Reprint a loaded transcript so a resumed session *looks* resumed.

    Restoring only `state.messages` leaves the model with the full history
    and the user with an empty screen — you are talking to something that
    remembers a conversation you can't see. This paints the conversation back:
    user turns in the prompt's own colour, assistant replies through the
    normal Markdown renderer, and each batch of tool calls collapsed to the
    same one-line summary a live turn prints ("Ran 2 shell commands").

    ``max_messages`` > 0 keeps only the last N messages and says how many
    were elided, so resuming a very long session doesn't flood the terminal.
    """
    from cheetahclaws.ui.render import _make_renderable, _RICH, console

    cfg = config or {}
    elided = 0
    if max_messages and len(messages) > max_messages:
        elided = len(messages) - max_messages
        messages = messages[-max_messages:]

    print()
    if elided:
        print(clr(f"  … {elided} earlier message{'s' if elided != 1 else ''} "
                  f"not shown (the model still has them)", "dim"))
        print()

    pending_tools: list[str] = []

    def _flush_tools() -> None:
        if not pending_tools:
            return
        from cheetahclaws.ui.render import _SUMMARY_VERBS
        counts: dict[str, int] = {}
        order: list[str] = []
        for name in pending_tools:
            if name not in counts:
                order.append(name)
            counts[name] = counts.get(name, 0) + 1
        parts = []
        for name in order:
            n = counts[name]
            verb, sing, plur = _SUMMARY_VERBS.get(name, ("called", name, name))
            parts.append(f"{verb} {n} {sing if n == 1 else plur}")
        line = ", ".join(parts)
        print(clr(f"  {line[0].upper() + line[1:]}", "dim"))
        pending_tools.clear()

    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")

        # A tool result is the transcript's plumbing, not a user turn.
        if role == "user" and _is_tool_result(content):
            continue

        if role == "user":
            _flush_tools()
            text = _message_text(content).strip()
            if not text:
                continue
            print()
            print(clr("» ", "cyan", "bold") + text)
            continue

        if role == "assistant":
            # Text first, then the tools this same message went on to call:
            # the model says "let me check" and *then* runs the command, so
            # queueing the tools first would print the summary above the line
            # that announced it.
            text = _message_text(content).strip()
            if text:
                _flush_tools()          # tools queued by *earlier* messages
                print()
                if _RICH and console is not None:
                    console.print(_make_renderable(text))
                else:
                    print(text)
            for block in _tool_blocks(content):
                pending_tools.append(block.get("name", "Tool"))

    _flush_tools()
    print()


# ── /resume ────────────────────────────────────────────────────────────────

def _read_session_meta(path: Path) -> dict | None:
    """Header fields of a session file, without keeping its messages around.

    The picker lists dozens of sessions; holding every transcript in memory
    to print one line each is wasteful, so only the metadata is kept and the
    messages are re-read from disk for the one the user picks.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    msgs = data.get("messages", [])
    return {
        "session_id": data.get("session_id", ""),
        "title": data.get("title") or derive_title(msgs),
        "saved_at": data.get("saved_at", ""),
        "turn_count": data.get("turn_count", 0),
        "messages": len(msgs),
        "path": path,
        "model": "",
    }


def list_resumable(limit: int = 30) -> list[dict]:
    """Recent sessions, newest first, deduped by session id.

    Sources, in priority order: the live autosave (session_latest.json),
    the per-day backups, and the SQLite history. A session that exists as
    both a file and a database row is listed once, keeping the file entry
    because only that one can be loaded back without the DB.
    """
    from cheetahclaws.config import MR_SESSION_DIR, DAILY_DIR

    found: list[dict] = []
    latest = MR_SESSION_DIR / "session_latest.json"
    if latest.exists():
        meta = _read_session_meta(latest)
        if meta:
            meta["latest"] = True
            found.append(meta)

    if DAILY_DIR.exists():
        daily = sorted(DAILY_DIR.rglob("session_*.json"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        for f in daily[:limit * 2]:
            meta = _read_session_meta(f)
            if meta:
                found.append(meta)

    try:
        from cheetahclaws.session_store import list_sessions
        for row in list_sessions(limit=limit):
            found.append({
                "session_id": row.get("id", ""),
                "title": row.get("title", ""),
                "saved_at": row.get("saved_at", ""),
                "turn_count": row.get("turn_count", 0),
                "messages": 0,
                "path": None,
                "model": row.get("model", ""),
            })
    except Exception:
        pass   # the DB is an extra source, never a requirement

    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for m in found:
        sid = m.get("session_id") or ""
        key = str(m["path"]) if m.get("path") else ""
        if key and key in seen_paths:
            continue
        if sid and sid in seen_ids:
            continue
        if sid:
            seen_ids.add(sid)
        if key:
            seen_paths.add(key)
        out.append(m)

    # Newest first. The autosave is pinned to the top: it is the session the
    # user was in a moment ago, which is what /resume is usually reaching for.
    out.sort(key=lambda m: (m.get("latest", False), m.get("saved_at", "")),
             reverse=True)
    return out[:limit]


def _apply_session(data: dict, state) -> None:
    state.messages = data.get("messages", [])
    state.turn_count = data.get("turn_count", 0)
    state.total_input_tokens = data.get("total_input_tokens", 0)
    state.total_output_tokens = data.get("total_output_tokens", 0)


def _announce_resume(label: str, state, config, where: str) -> None:
    """Say what was restored, then paint the conversation back.

    Replay is skipped on a bridge turn (Telegram / Slack / WeChat): the
    transcript would be one enormous chat message, and the user is looking at
    that history in the chat app already.
    """
    cfg = config or {}
    ok(f"Resumed \u201c{label}\u201d \u2014 {len(state.messages)} messages, "
       f"{state.turn_count} turns  ({where})")
    if not cfg.get("resume_replay", True):
        return
    try:
        from cheetahclaws.tools.interaction import (
            _is_in_tg_turn, _is_in_wx_turn, _is_in_slack_turn, _is_in_qq_turn,
        )
        if any(fn(cfg) for fn in (_is_in_tg_turn, _is_in_wx_turn,
                                  _is_in_slack_turn, _is_in_qq_turn)):
            return
    except Exception:
        pass
    try:
        replay_conversation(state.messages, cfg,
                            max_messages=int(cfg.get("resume_replay_limit", 40)))
    except Exception as e:
        warn(f"Could not replay the transcript: {e}")


def _resume_entry(entry: dict, state, config=None) -> bool:
    """Load one picker row into `state`, from its file or the database."""
    path = entry.get("path")
    if path is not None:
        try:
            data = _migrate_session(json.loads(Path(path).read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            err(f"Session file is corrupted: {path}")
            warn(f"  JSON error: {e}")
            return True
        except Exception as e:
            err(f"Cannot read session file: {e}")
            return True
        _apply_session(data, state)
        label = data.get("title") or derive_title(data.get("messages", [])) or Path(path).name
        _announce_resume(label, state, config, str(path))
        return True

    sid = entry.get("session_id", "")
    try:
        from cheetahclaws.session_store import load_session
        data = load_session(sid)
    except Exception as e:
        err(f"Cannot read session {sid}: {e}")
        return True
    if not data:
        err(f"Session not found: {sid}")
        return True
    _apply_session(_migrate_session(data), state)
    label = data.get("title") or derive_title(data.get("messages", [])) or sid
    _announce_resume(label, state, config, f"id: {sid}")
    return True


def _format_resume_row(i: int, m: dict) -> str:
    title = m.get("title") or "(no opening message)"
    when  = m.get("saved_at", "") or "?"
    turns = m.get("turn_count", 0)
    tag   = clr("  ← last", "green") if m.get("latest") else ""
    meta  = f"{when} · {turns} turn{'s' if turns != 1 else ''}"
    if m.get("model"):
        meta += f" · {m['model']}"
    if m.get("session_id"):
        meta += f" · id:{m['session_id']}"
    return (clr(f"  [{i:2d}] ", "yellow") + title + tag + "\n"
            + clr(f"       {meta}", "dim"))


def _pick_session(config) -> dict | None:
    """Show the named list and return the chosen entry (None = cancelled)."""
    from cheetahclaws.tools import ask_input_interactive

    sessions = list_resumable()
    if not sessions:
        info("No saved sessions found.")
        return None

    header = clr("  Select a session to resume:", "cyan", "bold")
    rows = [_format_resume_row(i + 1, m) for i, m in enumerate(sessions)]
    menu_buf = "\n".join([header, *rows])
    print(menu_buf)
    print()

    try:
        ans = ask_input_interactive(
            clr(f"  Enter a number 1–{len(sessions)}, an id, or Enter to cancel > ", "cyan"),
            config, menu_buf,
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return None

    if not ans:
        info("  Cancelled.")
        return None
    if ans.isdigit():
        idx = int(ans) - 1
        if 0 <= idx < len(sessions):
            return sessions[idx]
        err(f"Invalid selection: {ans} (valid range: 1–{len(sessions)})")
        return None
    for m in sessions:
        if m.get("session_id") == ans:
            return m
    err(f"No session matches: {ans}")
    return None


def _can_prompt(config) -> bool:
    """True when there is somebody who can answer the picker.

    A bridge turn (Telegram / Slack / WeChat / QQ / web) can always be asked
    — ``ask_input_interactive`` routes the menu there. A bare terminal can
    only be asked when stdin is a TTY; piped or headless runs would block
    forever, so those resume the latest session instead.
    """
    try:
        from cheetahclaws.tools.interaction import (
            _is_in_tg_turn, _is_in_wx_turn, _is_in_slack_turn,
            _is_in_web_turn, _is_in_qq_turn,
        )
        if any(fn(config) for fn in (_is_in_tg_turn, _is_in_wx_turn,
                                     _is_in_slack_turn, _is_in_web_turn,
                                     _is_in_qq_turn)):
            return True
    except Exception:
        pass
    try:
        return bool(sys.stdin.isatty())
    except Exception:
        return False


def cmd_resume(args: str, state, config) -> bool:
    """/resume — pick a past session by name, or jump straight to one.

        /resume              interactive picker, newest first
        /resume last         the most recent auto-saved session (no prompt)
        /resume <id>         a session id as shown in the picker
        /resume <file|path>  a specific session JSON file
    """
    from cheetahclaws.config import MR_SESSION_DIR
    arg = args.strip()

    if not arg:
        # Non-interactive callers (-p, a piped stdin, a cron run) have nobody
        # to answer the picker, so they keep the old behavior: resume the most
        # recent session directly.
        if not _can_prompt(config):
            arg = "last"
        else:
            entry = _pick_session(config)
            if entry is None:
                return True
            return _resume_entry(entry, state, config)

    if arg in ("last", "latest", "-"):
        path = MR_SESSION_DIR / "session_latest.json"
        if not path.exists():
            info("No auto-saved sessions found.")
            return True
        return _resume_entry({"path": path}, state, config)

    # A bare session id (as printed by the picker, /search and /save).
    if "/" not in arg and "\\" not in arg and not arg.endswith(".json"):
        for m in list_resumable(limit=200):
            if m.get("session_id") == arg:
                return _resume_entry(m, state, config)

    path = Path(arg) if ("/" in arg or "\\" in arg) else MR_SESSION_DIR / arg
    if not path.exists():
        err(f"File not found: {path}")
        info("Run /resume with no arguments to pick from the session list.")
        return True

    try:
        data = _migrate_session(json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as e:
        err(f"Session file is corrupted: {path}")
        warn(f"  JSON error: {e}")
        # Try falling back to daily backups
        from cheetahclaws.config import DAILY_DIR
        daily_files = sorted(DAILY_DIR.rglob("session_*.json"),
                             key=lambda f: f.stat().st_mtime, reverse=True)
        if daily_files:
            warn(f"  Try loading a recent backup: /load {daily_files[0]}")
        return True
    except Exception as e:
        err(f"Cannot read session file: {e}")
        return True

    _apply_session(data, state)
    label = data.get("title") or derive_title(data.get("messages", [])) or path.name
    _announce_resume(label, state, config, str(path))
    return True


# ── /search ────────────────────────────────────────────────────────────────

def cmd_search(args: str, state, config) -> bool:
    """Full-text search across all saved sessions."""
    query = args.strip()
    if not query:
        info("Usage: /search <query>")
        info("Search across all past session conversations.")
        return True

    from cheetahclaws.session_store import search_sessions, session_count, import_json_sessions

    # Auto-import legacy JSON sessions on first search
    count = session_count()
    if count == 0:
        from cheetahclaws.config import SESSION_HIST_FILE
        imported = import_json_sessions(SESSION_HIST_FILE)
        if imported:
            info(f"Imported {imported} sessions from history.json into search index.")

    results = search_sessions(query)
    if not results:
        info(f"No sessions found matching: \"{query}\"")
        return True

    info(f"Found {len(results)} session(s) matching \"{query}\":\n")
    for r in results:
        sid = r.get("id", "?")
        title = r.get("title", "") or "(untitled)"
        date = r.get("saved_at", "?")
        model = r.get("model", "")
        snippet = r.get("snippet", "")
        turns = r.get("turn_count", 0)

        header = clr(f"  [{sid}]", "yellow") + f" {title}"
        if model:
            header += clr(f" ({model})", "dim")
        print(header)
        print(clr(f"    {date} · {turns} turns", "dim"))
        if snippet:
            # Clean up FTS5 snippet markers
            clean = snippet.replace(">>>", "\033[32m").replace("<<<", "\033[0m")
            print(f"    {clean}")
        print()

    info("Load a session with: /load <session_id>")
    return True


# ── /history ───────────────────────────────────────────────────────────────

def cmd_history(_args: str, state, config) -> bool:
    if not state.messages:
        info("(empty conversation)")
        return True
    for i, m in enumerate(state.messages):
        role = clr(m["role"].upper(), "bold",
                   "cyan" if m["role"] == "user" else "green")
        content = m["content"]
        if isinstance(content, str):
            print(f"[{i}] {role}: {content[:200]}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    btype = block.get("type", "")
                else:
                    btype = getattr(block, "type", "")
                if btype == "text":
                    text = block.get("text", "") if isinstance(block, dict) else block.text
                    print(f"[{i}] {role}: {text[:200]}")
                elif btype == "tool_use":
                    name = block.get("name", "") if isinstance(block, dict) else block.name
                    print(f"[{i}] {role}: [tool_use: {name}]")
                elif btype == "tool_result":
                    cval = block.get("content", "") if isinstance(block, dict) else block.content
                    print(f"[{i}] {role}: [tool_result: {str(cval)[:100]}]")
    return True


# ── /cloudsave ─────────────────────────────────────────────────────────────

def cmd_cloudsave(args: str, state, config) -> bool:
    """Sync sessions to GitHub Gist.

    /cloudsave setup <token>   — configure GitHub Personal Access Token
    /cloudsave                 — upload current session to Gist
    /cloudsave push [desc]     — same as above with optional description
    /cloudsave auto on|off     — toggle auto-upload on /exit
    /cloudsave list            — list your cheetahclaws Gists
    /cloudsave load <gist_id>  — download and load a session from Gist
    """
    from cheetahclaws.cloudsave import validate_token, upload_session, list_sessions, download_session
    from cheetahclaws.config import save_config

    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    token = config.get("gist_token", "")

    if sub == "setup":
        if not rest:
            err("Usage: /cloudsave setup <GitHub_Personal_Access_Token>")
            return True
        new_token = rest.strip()
        info("Validating token…")
        valid, msg = validate_token(new_token)
        if not valid:
            err(msg)
            return True
        config["gist_token"] = new_token
        save_config(config)
        ok(f"GitHub token saved (logged in as: {msg}). Cloud sync is ready.")
        return True

    if sub == "auto":
        flag = rest.strip().lower()
        if flag == "on":
            config["cloudsave_auto"] = True
            save_config(config)
            ok("Auto cloud-sync ON — session will be uploaded to Gist on /exit.")
        elif flag == "off":
            config["cloudsave_auto"] = False
            save_config(config)
            ok("Auto cloud-sync OFF.")
        else:
            status = "ON" if config.get("cloudsave_auto") else "OFF"
            info(f"Auto cloud-sync is currently {status}. Use 'on' or 'off' to toggle.")
        return True

    if not token:
        err("No GitHub token configured. Run: /cloudsave setup <token>")
        info("Get a token at https://github.com/settings/tokens (needs 'gist' scope)")
        return True

    if sub == "list":
        info("Fetching your cheetahclaws sessions from GitHub Gist…")
        sessions, err_msg = list_sessions(token)
        if err_msg:
            err(err_msg)
            return True
        if not sessions:
            info("No sessions found. Upload one with /cloudsave")
            return True
        info(f"Found {len(sessions)} session(s):")
        for s in sessions:
            ts = s["updated_at"][:16].replace("T", " ")
            desc = s["description"].replace("[cheetahclaws]", "").strip()
            print(f"  {clr(s['id'][:8], 'yellow')}…  {clr(ts, 'dim')}  {desc or s['files'][0]}")
        return True

    if sub == "load":
        gist_id = rest.strip()
        if not gist_id:
            err("Usage: /cloudsave load <gist_id>")
            return True
        info(f"Downloading session {gist_id[:8]}… from Gist…")
        data, err_msg = download_session(token, gist_id)
        if err_msg:
            err(err_msg)
            return True
        state.messages = data.get("messages", [])
        state.turn_count = data.get("turn_count", 0)
        state.total_input_tokens = data.get("total_input_tokens", 0)
        state.total_output_tokens = data.get("total_output_tokens", 0)
        ok(f"Session loaded from Gist ({len(state.messages)} messages).")
        return True

    if sub in ("", "push"):
        description = rest.strip() if sub == "push" else ""
        if not state.messages:
            info("Nothing to save — conversation is empty.")
            return True
        info("Uploading session to GitHub Gist…")
        session_data = _build_session_data(state)
        existing_id = config.get("cloudsave_last_gist_id")
        gist_id, err_msg = upload_session(session_data, token, description, existing_id)
        if err_msg:
            err(f"Upload failed: {err_msg}")
            return True
        config["cloudsave_last_gist_id"] = gist_id
        save_config(config)
        ok(f"Session uploaded → https://gist.github.com/{gist_id}")
        return True

    err(f"Unknown subcommand '{sub}'. Run /help for usage.")
    return True


# ── /exit ──────────────────────────────────────────────────────────────────

def cmd_exit(_args: str, _state, config) -> bool:
    import sys as _sys
    if _sys.stdin.isatty() and _sys.platform != "win32":
        _sys.stdout.write("\x1b[?2004l")
        _sys.stdout.flush()
    ok("Goodbye!")
    save_latest("", _state, config)
    if config.get("cloudsave_auto") and config.get("gist_token") and _state.messages:
        info("Auto cloud-sync: uploading session to Gist…")
        from cheetahclaws.cloudsave import upload_session
        from cheetahclaws.config import save_config
        session_data = _build_session_data(_state)
        gist_id, err_msg = upload_session(
            session_data, config["gist_token"],
            existing_gist_id=config.get("cloudsave_last_gist_id"),
        )
        if err_msg:
            err(f"Cloud sync failed: {err_msg}")
        else:
            config["cloudsave_last_gist_id"] = gist_id
            save_config(config)
            ok(f"Session synced → https://gist.github.com/{gist_id}")
    _sys.exit(0)
