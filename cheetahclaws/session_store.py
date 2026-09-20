"""SQLite-backed session storage with FTS5 full-text search.

Replaces JSON file storage for session history. Provides:
- Persistent session storage with atomic writes (WAL mode)
- Full-text search across all past conversations
- Session metadata (title, model, token counts, timestamps)
- Backward-compatible: imports existing JSON sessions on first use
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


_DB_PATH: Optional[Path] = None
_local = threading.local()
# Serializes save_session across threads within a single process so two
# concurrent writers for the same session_id don't both win the
# INSERT OR REPLACE race and silently drop one set of changes.
_save_lock = threading.Lock()


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        from cheetahclaws.config import CONFIG_DIR
        _DB_PATH = CONFIG_DIR / "sessions.db"
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    """Get a thread-local SQLite connection (one per thread, reused)."""
    conn = getattr(_local, "conn", None)
    db_path = _get_db_path()
    if conn is None:
        conn = sqlite3.connect(str(db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _init_tables(conn)
    return conn


def _init_tables(conn: sqlite3.Connection):
    """Create tables and FTS5 index if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          TEXT PRIMARY KEY,
            title       TEXT DEFAULT '',
            model       TEXT DEFAULT '',
            saved_at    TEXT NOT NULL,
            turn_count  INTEGER DEFAULT 0,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            messages    TEXT NOT NULL  -- JSON array
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
            id, title, content,
            tokenize='unicode61'
        );
    """)
    conn.commit()


def save_session(session_id: str, messages: list, *,
                 title: str = "", model: str = "",
                 turn_count: int = 0,
                 input_tokens: int = 0,
                 output_tokens: int = 0) -> None:
    """Save or update a session in the database."""
    with _save_lock:
        conn = _get_conn()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        messages_json = json.dumps(messages, default=str, ensure_ascii=False)

        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT OR REPLACE INTO sessions
                    (id, title, model, saved_at, turn_count, input_tokens, output_tokens, messages)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (session_id, title, model, now, turn_count, input_tokens, output_tokens, messages_json))

            # Build searchable content from messages
            text_parts = []
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, str):
                    text_parts.append(content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
            searchable = " ".join(text_parts)[:50000]  # cap at 50k chars

            # Update FTS index
            conn.execute("DELETE FROM sessions_fts WHERE id = ?", (session_id,))
            conn.execute(
                "INSERT INTO sessions_fts (id, title, content) VALUES (?, ?, ?)",
                (session_id, title, searchable),
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise


def load_session(session_id: str) -> Optional[dict]:
    """Load a session by ID. Returns dict with messages, metadata, or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        return None
    return {
        "session_id": row["id"],
        "title": row["title"],
        "model": row["model"],
        "saved_at": row["saved_at"],
        "turn_count": row["turn_count"],
        "total_input_tokens": row["input_tokens"],
        "total_output_tokens": row["output_tokens"],
        "messages": json.loads(row["messages"]),
    }


def list_sessions(limit: int = 50, offset: int = 0) -> list[dict]:
    """List sessions ordered by most recent first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, title, model, saved_at, turn_count, input_tokens, output_tokens "
        "FROM sessions ORDER BY saved_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def search_sessions(query: str, limit: int = 20) -> list[dict]:
    """Full-text search across all session content.

    Returns list of dicts with session_id, title, saved_at, and snippet.
    """
    conn = _get_conn()
    # FTS5 query — tokenize words for broad matching
    words = query.split()
    fts_query = " ".join(w.replace('"', '""') for w in words if w)
    try:
        rows = conn.execute("""
            SELECT f.id, f.title,
                   snippet(sessions_fts, 2, '>>>', '<<<', '...', 40) as snippet,
                   s.saved_at, s.turn_count, s.model
            FROM sessions_fts f
            JOIN sessions s ON s.id = f.id
            WHERE sessions_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (fts_query, limit)).fetchall()
    except sqlite3.OperationalError:
        # Fallback: simple LIKE search if FTS query fails. Escape the SQL
        # LIKE wildcards (%, _) and our chosen escape char (\) so a user
        # query like "100%" doesn't degenerate to "match everything".
        like_q = (
            query.replace("\\", "\\\\")
                 .replace("%", "\\%")
                 .replace("_", "\\_")
        )
        rows = conn.execute("""
            SELECT f.id, f.title, '' as snippet,
                   s.saved_at, s.turn_count, s.model
            FROM sessions_fts f
            JOIN sessions s ON s.id = f.id
            WHERE f.content LIKE ? ESCAPE '\\'
            ORDER BY s.saved_at DESC
            LIMIT ?
        """, (f"%{like_q}%", limit)).fetchall()

    return [dict(r) for r in rows]


def delete_session(session_id: str) -> bool:
    """Delete a session from the database."""
    conn = _get_conn()
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.execute("DELETE FROM sessions_fts WHERE id = ?", (session_id,))
    conn.commit()
    return True


def session_count() -> int:
    """Return total number of stored sessions."""
    conn = _get_conn()
    return conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]


def import_json_sessions(json_history_path: Path) -> int:
    """Import sessions from the legacy history.json file.

    Skips sessions that already exist in SQLite. Returns count imported.
    """
    if not json_history_path.exists():
        return 0
    try:
        data = json.loads(json_history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, Exception):
        return 0

    sessions = data.get("sessions", [])
    imported = 0
    for s in sessions:
        sid = s.get("session_id", "")
        if not sid:
            continue
        # Skip if already in SQLite
        conn = _get_conn()
        exists = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if exists:
            continue

        save_session(
            session_id=sid,
            messages=s.get("messages", []),
            title=s.get("title", ""),
            model=s.get("model", ""),
            turn_count=s.get("turn_count", 0),
            input_tokens=s.get("total_input_tokens", 0),
            output_tokens=s.get("total_output_tokens", 0),
        )
        imported += 1
    return imported
