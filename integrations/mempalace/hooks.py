"""
MemPalace session hooks for CheetahClaws.

Integrates auto-save into the CheetahClaws session lifecycle:
  - session_start: initialize palace tracking, run wake-up
  - precompact: emergency save before context compaction
  - stop: periodic auto-save every N exchanges

Install by adding to .cheetahclaws/hooks.json or via plugin system.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

SAVE_INTERVAL = 15  # auto-save every N human exchanges
STATE_DIR = Path.home() / ".mempalace" / "hook_state"


def _log(message: str):
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_DIR / "hook.log", "a") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {message}\n")
    except OSError:
        pass


def _count_human_messages(transcript_path: str) -> int:
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return 0
    count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    msg = entry.get("message", {})
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content", "")
                        text = content if isinstance(content, str) else " ".join(
                            b.get("text", "") for b in content if isinstance(b, dict)
                        )
                        if "<command-message>" not in text:
                            count += 1
                except (json.JSONDecodeError, AttributeError):
                    pass
    except OSError:
        return 0
    return count


def _save_to_palace(content: str, session_id: str):
    try:
        from mempalace.config import MempalaceConfig
        import chromadb

        cfg = MempalaceConfig()
        client = chromadb.PersistentClient(path=cfg.palace_path)
        col = client.get_collection("mempalace_drawers")

        drawer_id = f"diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id}"
        meta = {
            "wing": "wing_cheetahclaws",
            "room": "session-diary",
            "hall": "auto-save",
            "source_file": f"cheetahclaws-session-{session_id}",
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        col.add(ids=[drawer_id], documents=[content], metadatas=[meta])
        _log(f"Auto-saved to palace: {drawer_id}")
    except Exception as e:
        _log(f"Auto-save failed: {e}")


def hook_session_start(session_id: str):
    _log(f"SESSION START for session {session_id}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Initialize last save point
    (STATE_DIR / f"{session_id}_last_save").write_text("0", encoding="utf-8")


def hook_stop(session_id: str, transcript_path: str):
    last_save_file = STATE_DIR / f"{session_id}_last_save"
    last_save = 0
    if last_save_file.is_file():
        try:
            last_save = int(last_save_file.read_text().strip())
        except (ValueError, OSError):
            last_save = 0

    exchange_count = _count_human_messages(transcript_path)
    since_last = exchange_count - last_save

    _log(f"Session {session_id}: {exchange_count} exchanges, {since_last} since last save")

    if since_last >= SAVE_INTERVAL and exchange_count > 0:
        try:
            last_save_file.write_text(str(exchange_count), encoding="utf-8")
        except OSError:
            pass

        _log(f"TRIGGERING AUTO-SAVE at exchange {exchange_count}")
        return {
            "decision": "block",
            "reason": (
                "AUTO-SAVE checkpoint. Save key topics, decisions, quotes, and code "
                "from this session to MemPalace. Use MempalaceSave or MempalaceDiaryWrite. "
                "Organize into appropriate wings/rooms. Use verbatim quotes where possible. "
                "Continue conversation after saving."
            ),
        }

    return {}


def hook_precompact(session_id: str):
    _log(f"PRE-COMPACT triggered for session {session_id}")
    return {
        "decision": "block",
        "reason": (
            "COMPACTION IMMINENT. Save ALL topics, decisions, quotes, code, and "
            "important context from this session to MemPalace. Use MempalaceSave or "
            "MempalaceDiaryWrite. Be thorough — after compaction, detailed context "
            "will be lost. Organize into appropriate wings/rooms. Save everything, "
            "then allow compaction to proceed."
        ),
    }
