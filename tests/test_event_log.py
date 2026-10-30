"""Session event log: JSONL persistence, resume numbering, replay."""
from __future__ import annotations

import json

import pytest

from cheetahclaws import event_log
from cheetahclaws.event_log import EventEmitter


@pytest.fixture
def sdir(tmp_path, monkeypatch):
    import cheetahclaws.config as cfg
    monkeypatch.setattr(cfg, "SESSIONS_DIR", tmp_path)
    return tmp_path


def test_emit_persists_jsonl_and_fans_out(sdir):
    em = EventEmitter("abc123")
    got = []
    em.add_sink(got.append)
    em.emit("session_start", model="m", cwd="/w")
    em.emit("assistant_delta", text="hi")
    em.emit("tool_call", id="t1", name="Bash", input={"command": "ls"})
    em.close()
    lines = (sdir / "abc123" / "events.jsonl").read_text().splitlines()
    persisted = [json.loads(line) for line in lines]
    # deltas go to sinks only
    assert [e["type"] for e in persisted] == ["session_start", "tool_call"]
    assert [e["type"] for e in got] == ["session_start", "assistant_delta", "tool_call"]
    assert all(e["session_id"] == "abc123" and "ts" in e for e in persisted)
    assert [e["seq"] for e in got] == [1, 2, 3]


def test_opt_out_writes_nothing(sdir):
    em = event_log.make_emitter("quiet1", {"event_log": False})
    em.emit("session_start")
    assert em.path is None
    assert not (sdir / "quiet1").exists()


def test_seq_continues_when_resuming(sdir):
    em = EventEmitter("res1")
    em.emit("a")
    em.emit("b")
    em.close()
    em2 = EventEmitter("res1")
    ev = em2.emit("c")
    em2.close()
    assert ev["seq"] == 3
    assert [e["type"] for e in event_log.read_events("res1")] == ["a", "b", "c"]


def test_read_tolerates_torn_line(sdir):
    em = EventEmitter("torn")
    em.emit("a")
    em.close()
    with open(sdir / "torn" / "events.jsonl", "a") as f:
        f.write('{"type": "b", "se')
    assert [e["type"] for e in event_log.read_events("torn")] == ["a"]


@pytest.mark.parametrize("bad", ["", "..", "../etc", "a/b", "x" * 200])
def test_invalid_session_ids_rejected(bad):
    with pytest.raises(ValueError):
        event_log.events_path(bad)


def test_render_timeline_covers_event_types():
    evs = [
        {"type": "session_start", "ts": 0, "model": "m", "cwd": "/w"},
        {"type": "user_message", "ts": 0, "text": "fix it"},
        {"type": "assistant_message", "ts": 0, "text": "", "tool_calls": [{"id": "1"}]},
        {"type": "tool_call", "ts": 0, "id": "1", "name": "Bash", "input": {"command": "ls"}},
        {"type": "permission_decision", "ts": 0, "id": "1", "name": "Bash",
         "decision": "deny", "source": "headless", "reason": "nobody"},
        {"type": "tool_result", "ts": 0, "id": "1", "name": "Bash", "is_error": True,
         "output": "Denied"},
        {"type": "result", "ts": 0, "exit_reason": "completed", "turns": 2,
         "cost_usd": 0.01, "duration_ms": 1500},
        {"type": "assistant_delta", "ts": 0, "text": "x"},
    ]
    out = event_log.render_timeline(evs)
    for needle in ("session start", "fix it", "-> Bash", "permission DENY Bash via headless",
                   "<- Bash ERROR", "exit_reason=completed", "cost=$0.0100"):
        assert needle in out
    assert out.count("\n") >= 6


def test_replay_main(sdir, capsys):
    em = EventEmitter("deadbeef")
    em.emit("session_start", model="m", cwd="/w")
    em.emit("user_message", text="hello replay")
    em.close()

    assert event_log.replay_main([]) == 0
    assert "deadbeef" in capsys.readouterr().out

    assert event_log.replay_main(["dead"]) == 0          # unique prefix
    assert "hello replay" in capsys.readouterr().out

    assert event_log.replay_main(["last", "--json"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[1])["text"] == "hello replay"

    assert event_log.replay_main(["nope"]) == 1
