"""Two things a resumed session owes the user.

1. The transcript on disk is the conversation, readable as itself — a saved
   Chinese message is Chinese, not `\\u5e2e\\u6211...`.
2. /resume *shows* the conversation. Restoring only `state.messages` leaves
   the model with the history and the user with an empty screen.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.commands import session as S

CN = "帮我看看今天上海的天气"
REPLY = "上海今天**晴**,23°C。"


class _State:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.turn_count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0


@pytest.fixture
def home(tmp_path, monkeypatch):
    from cheetahclaws import config as config_mod
    mr = tmp_path / "sessions" / "mr_sessions"
    daily = tmp_path / "sessions" / "daily"
    mr.mkdir(parents=True)
    daily.mkdir(parents=True)
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(config_mod, "MR_SESSION_DIR", mr)
    monkeypatch.setattr(config_mod, "DAILY_DIR", daily)
    monkeypatch.setattr(config_mod, "SESSION_HIST_FILE", tmp_path / "sessions" / "history.json")
    import cheetahclaws.session_store as store
    monkeypatch.setattr(store, "list_sessions", lambda limit=50, offset=0: [])
    monkeypatch.setattr(store, "save_session", lambda *a, **k: None)
    return {"root": tmp_path, "mr": mr, "daily": daily}


def _convo():
    return [
        {"role": "user", "content": CN},
        {"role": "assistant", "content": [
            {"type": "text", "text": "我查一下。"},
            {"type": "tool_use", "id": "t1", "name": "WebFetch", "input": {"url": "x"}},
            {"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "date"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        {"role": "assistant", "content": REPLY},
    ]


# ── Text is stored as text ───────────────────────────────────────────────

def test_save_writes_readable_utf8(home):
    S.cmd_save("", _State(_convo()), {})
    saved = next((home["root"] / "sessions").glob("session_*.json"))
    raw = saved.read_text(encoding="utf-8")
    assert CN in raw
    assert "\\u5e2e" not in raw


def test_autosave_and_exit_save_write_readable_utf8(home):
    state = _State(_convo())
    S.autosave_session(state, {})
    S.save_latest("", state, {"model": "m"})
    for path in [home["mr"] / "session_latest.json",
                 *home["daily"].rglob("session_*.json"),
                 home["root"] / "sessions" / "history.json"]:
        raw = path.read_text(encoding="utf-8")
        assert CN in raw, path
        assert "\\u" not in raw, path


def test_config_is_written_readable_too(home):
    from cheetahclaws.config import load_config, save_config
    cfg = load_config()
    cfg["wechat_self_nickname"] = "顾尚丁"
    save_config(cfg)
    assert "顾尚丁" in (home["root"] / "config.json").read_text(encoding="utf-8")


def test_an_older_escaped_file_still_loads(home):
    """Escaped files are valid JSON with identical content — reading them
    must keep working, no migration required."""
    path = home["daily"] / "2026-09-20" / "session_old.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"session_id": "old1", "saved_at": "2026-09-20 09:00:00",
                                "messages": [{"role": "user", "content": CN}],
                                "turn_count": 1}), encoding="utf-8")
    assert "\\u5e2e" in path.read_text(encoding="utf-8")
    state = _State()
    S.cmd_resume("old1", state, {"resume_replay": False})
    assert state.messages[0]["content"] == CN


def test_the_round_trip_preserves_the_text_exactly(home):
    state = _State(_convo())
    S.save_latest("", state, {"model": "m"})
    restored = _State()
    S.cmd_resume("last", restored, {"resume_replay": False})
    assert restored.messages == state.messages


# ── /resume shows the conversation ───────────────────────────────────────

def test_resume_repaints_the_conversation(home, capsys):
    S.save_latest("", _State(_convo()), {"model": "m"})
    capsys.readouterr()
    S.cmd_resume("last", _State(), {})
    out = capsys.readouterr().out
    assert CN in out                      # the user's question
    assert "我查一下" in out               # the assistant's interstitial text
    assert "上海今天" in out               # the final answer
    assert "Fetched 1 URL, ran 1 shell command" in out   # the tools, collapsed


def test_the_transcript_reads_in_the_order_it_happened(home, capsys):
    S.save_latest("", _State(_convo()), {"model": "m"})
    capsys.readouterr()
    S.cmd_resume("last", _State(), {})
    out = capsys.readouterr().out
    # "let me check" is said before the tool it announces runs
    assert out.index("我查一下") < out.index("Fetched 1 URL")
    assert out.index("Fetched 1 URL") < out.index("上海今天")


def test_a_tool_result_is_not_replayed_as_a_user_turn(home, capsys):
    S.save_latest("", _State(_convo()), {"model": "m"})
    capsys.readouterr()
    S.cmd_resume("last", _State(), {})
    out = capsys.readouterr().out
    assert out.count("» ") == 1           # one real user turn, not two


def test_replay_can_be_turned_off(home, capsys):
    S.save_latest("", _State(_convo()), {"model": "m"})
    capsys.readouterr()
    state = _State()
    S.cmd_resume("last", state, {"resume_replay": False})
    out = capsys.readouterr().out
    assert "Resumed" in out
    assert "我查一下" not in out
    assert state.messages                  # …but the session is still restored


def test_a_long_transcript_is_trimmed_and_says_so(home, capsys):
    long_convo = [{"role": "user", "content": f"问题 {i}"} for i in range(60)]
    S.save_latest("", _State(long_convo), {"model": "m"})
    capsys.readouterr()
    S.cmd_resume("last", _State(), {"resume_replay_limit": 10})
    out = capsys.readouterr().out
    assert "50 earlier messages not shown" in out
    assert "问题 59" in out
    assert "问题 0\n" not in out


def test_replay_never_breaks_the_resume(home, capsys, monkeypatch):
    """A rendering failure must not cost the user the restored session."""
    S.save_latest("", _State(_convo()), {"model": "m"})
    monkeypatch.setattr(S, "replay_conversation",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    state = _State()
    capsys.readouterr()
    S.cmd_resume("last", state, {})
    assert state.messages                  # restored anyway
    assert "boom" in capsys.readouterr().out   # warn() goes to stdout


def test_replay_is_skipped_on_a_bridge_turn(home, capsys, monkeypatch):
    """A whole transcript as one Telegram message helps nobody, and the user
    is scrolling that history in the chat app already."""
    import cheetahclaws.tools.interaction as inter
    monkeypatch.setattr(inter, "_is_in_tg_turn", lambda cfg: True)
    S.save_latest("", _State(_convo()), {"model": "m"})
    capsys.readouterr()
    state = _State()
    S.cmd_resume("last", state, {})
    out = capsys.readouterr().out
    assert "Resumed" in out
    assert "我查一下" not in out
    assert state.messages
