"""Tests for /resume: sessions are listed by name, not by opaque id.

A session's name is its opening request, derived from the first real user
message. The picker lists recent sessions newest-first with the live
autosave pinned on top, and accepts a number or a session id; passing an
id, a path or "last" skips the picker entirely.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.commands import session as S


class _State:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.turn_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0


@pytest.fixture
def sessions_home(tmp_path, monkeypatch):
    """Redirect every session path at a throwaway directory."""
    from cheetahclaws import config as config_mod
    mr = tmp_path / "sessions" / "mr_sessions"
    daily = tmp_path / "sessions" / "daily"
    mr.mkdir(parents=True)
    daily.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(config_mod, "MR_SESSION_DIR", mr)
    monkeypatch.setattr(config_mod, "DAILY_DIR", daily)
    # The SQLite store is an optional extra source — keep it out of the way
    # so these tests exercise the file path deterministically.
    import cheetahclaws.session_store as store
    monkeypatch.setattr(store, "list_sessions", lambda limit=50, offset=0: [])
    return {"mr": mr, "daily": daily}


def _write_session(path: Path, *, sid: str, title_text: str,
                   saved_at: str, turns: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "_version": 1,
        "session_id": sid,
        "title": title_text,
        "saved_at": saved_at,
        "messages": [{"role": "user", "content": title_text},
                     {"role": "assistant", "content": "ok"}],
        "turn_count": turns,
        "total_input_tokens": 10,
        "total_output_tokens": 20,
    }))
    return path


# ── Naming a session ─────────────────────────────────────────────────────

def test_title_comes_from_the_first_user_message():
    msgs = [{"role": "user", "content": "Add a /resume picker with session names"},
            {"role": "assistant", "content": "sure"}]
    assert S.derive_title(msgs) == "Add a /resume picker with session names"


def test_title_reads_structured_content_blocks():
    msgs = [{"role": "user", "content": [{"type": "text", "text": "Fix the flaky test"}]}]
    assert S.derive_title(msgs) == "Fix the flaky test"


def test_title_skips_slash_commands_and_tool_results():
    msgs = [
        {"role": "user", "content": "/model"},
        {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]},
        {"role": "user", "content": "Actually, refactor the parser"},
    ]
    assert S.derive_title(msgs) == "Actually, refactor the parser"


def test_title_collapses_newlines_and_is_ellipsized():
    msgs = [{"role": "user", "content": "line one\n\n   line two " + "x" * 200}]
    title = S.derive_title(msgs)
    assert "\n" not in title
    assert title.startswith("line one line two")
    assert len(title) <= 64


def test_title_of_an_empty_session_is_blank():
    assert S.derive_title([]) == ""
    assert S.derive_title([{"role": "assistant", "content": "hi"}]) == ""


def test_saved_sessions_carry_their_title():
    data = S._build_session_data(_State([{"role": "user", "content": "Ship the picker"}]))
    assert data["title"] == "Ship the picker"


# ── Listing ──────────────────────────────────────────────────────────────

def test_list_is_newest_first_with_the_live_session_pinned(sessions_home):
    _write_session(sessions_home["daily"] / "2026-09-18" / "session_a.json",
                   sid="aaa", title_text="Old work", saved_at="2026-09-18 09:00:00")
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_b.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    _write_session(sessions_home["mr"] / "session_latest.json",
                   sid="ccc", title_text="Right now", saved_at="2026-09-17 09:00:00")

    rows = S.list_resumable()
    assert [r["title"] for r in rows] == ["Right now", "Newer work", "Old work"]
    assert rows[0]["latest"] is True


def test_a_session_present_in_two_places_is_listed_once(sessions_home):
    _write_session(sessions_home["mr"] / "session_latest.json",
                   sid="dup", title_text="Same session", saved_at="2026-09-19 10:00:00")
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_dup.json",
                   sid="dup", title_text="Same session", saved_at="2026-09-19 10:00:00")
    assert len(S.list_resumable()) == 1


def test_a_corrupted_file_is_skipped_not_fatal(sessions_home):
    (sessions_home["daily"] / "2026-09-19").mkdir(parents=True)
    (sessions_home["daily"] / "2026-09-19" / "session_bad.json").write_text("{not json")
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_ok.json",
                   sid="ok1", title_text="Good one", saved_at="2026-09-19 09:00:00")
    assert [r["title"] for r in S.list_resumable()] == ["Good one"]


def test_empty_list_when_nothing_was_saved(sessions_home):
    assert S.list_resumable() == []


def test_a_row_shows_the_name_the_date_and_the_turn_count(sessions_home):
    row = {"title": "Add the picker", "saved_at": "2026-09-19 14:32:00",
           "turn_count": 12, "session_id": "4f2a1c"}
    text = S._format_resume_row(1, row)
    assert "Add the picker" in text
    assert "2026-09-19 14:32:00" in text
    assert "12 turns" in text
    assert "4f2a1c" in text


# ── Picking ──────────────────────────────────────────────────────────────

def _answer(monkeypatch, reply: str):
    import cheetahclaws.tools as tools
    monkeypatch.setattr(tools, "ask_input_interactive", lambda *a, **k: reply)


def test_picking_a_number_loads_that_session(sessions_home, monkeypatch, capsys):
    _write_session(sessions_home["daily"] / "2026-09-18" / "session_a.json",
                   sid="aaa", title_text="Old work", saved_at="2026-09-18 09:00:00")
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_b.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    _answer(monkeypatch, "2")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    state = _State()
    assert S.cmd_resume("", state, {"_session_id": "x"}) is True
    assert len(state.messages) == 2
    assert "Old work" in capsys.readouterr().out


def test_picking_by_id_works_too(sessions_home, monkeypatch):
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_b.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    _answer(monkeypatch, "bbb")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    state = _State()
    S.cmd_resume("", state, {"_session_id": "x"})
    assert state.turn_count == 3


def test_pressing_enter_cancels_without_touching_state(sessions_home, monkeypatch):
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_s.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    _answer(monkeypatch, "")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    state = _State([{"role": "user", "content": "keep me"}])
    S.cmd_resume("", state, {"_session_id": "x"})
    assert state.messages == [{"role": "user", "content": "keep me"}]


def test_an_out_of_range_number_is_rejected(sessions_home, monkeypatch, capsys):
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_s.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    _answer(monkeypatch, "9")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    state = _State()
    S.cmd_resume("", state, {"_session_id": "x"})
    assert state.messages == []
    assert "Invalid selection" in capsys.readouterr().err


# ── Skipping the picker ──────────────────────────────────────────────────

def test_resume_last_loads_the_autosave_without_asking(sessions_home, monkeypatch):
    _write_session(sessions_home["mr"] / "session_latest.json",
                   sid="ccc", title_text="Right now", saved_at="2026-09-19 12:00:00")

    def _boom(*a, **k):
        raise AssertionError("/resume last must not prompt")
    import cheetahclaws.tools as tools
    monkeypatch.setattr(tools, "ask_input_interactive", _boom)

    state = _State()
    S.cmd_resume("last", state, {"_session_id": "x"})
    assert len(state.messages) == 2


def test_resume_by_id_skips_the_picker(sessions_home, monkeypatch):
    _write_session(sessions_home["daily"] / "2026-09-19" / "session_s.json",
                   sid="bbb", title_text="Newer work", saved_at="2026-09-19 09:00:00")
    import cheetahclaws.tools as tools
    monkeypatch.setattr(tools, "ask_input_interactive",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("prompted")))
    state = _State()
    S.cmd_resume("bbb", state, {"_session_id": "x"})
    assert state.turn_count == 3


def test_a_non_interactive_run_resumes_the_latest_instead_of_prompting(
        sessions_home, monkeypatch):
    """Piped stdin / -p / cron have nobody to answer a menu, so the old
    behavior is kept rather than blocking forever."""
    _write_session(sessions_home["mr"] / "session_latest.json",
                   sid="ccc", title_text="Right now", saved_at="2026-09-19 12:00:00")
    monkeypatch.setattr(S, "_can_prompt", lambda cfg: False)
    state = _State()
    S.cmd_resume("", state, {"_session_id": "x"})
    assert len(state.messages) == 2


def test_a_missing_file_reports_and_points_at_the_picker(sessions_home, capsys):
    state = _State()
    assert S.cmd_resume("nope.json", state, {"_session_id": "x"}) is True
    captured = capsys.readouterr()
    assert "File not found" in captured.err      # err() writes to stderr
    assert "/resume" in captured.out


def test_no_sessions_at_all_says_so(sessions_home, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    state = _State()
    S.cmd_resume("", state, {"_session_id": "x"})
    assert "No saved sessions" in capsys.readouterr().out
