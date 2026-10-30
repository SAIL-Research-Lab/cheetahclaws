"""Agent loop: max_turns, structured is_error, result ordering, Ctrl-C during
parallel tools, hook wiring and event emission."""
from __future__ import annotations

import os
import signal
import threading
import time
from types import SimpleNamespace

import pytest

from cheetahclaws import agent, hooks
from cheetahclaws.agent import AgentState, PermissionRequest, ToolEnd, ToolStart, run
from cheetahclaws.event_log import EventEmitter
from cheetahclaws.providers import AssistantTurn


def _turn(text="", tool_calls=None):
    value = AssistantTurn.__new__(AssistantTurn)
    value.text = text
    value.tool_calls = tool_calls or []
    value.in_tokens = 3
    value.out_tokens = 2
    value.cache_read_tokens = 0
    value.cache_write_tokens = 0
    return value


def _config(**extra):
    return {"model": "test", "permission_mode": "accept-all",
            "_session_id": "loop-upgrade-test", **extra}


@pytest.fixture(autouse=True)
def _no_user_hooks(monkeypatch, tmp_path):
    """Isolate from the developer's real ~/.cheetahclaws/settings.json."""
    monkeypatch.setattr(hooks, "_user_settings_path", lambda: tmp_path / "none.json")
    monkeypatch.setenv("CHEETAHCLAWS_PROJECT_DIR", str(tmp_path))
    hooks.clear_registered()
    yield
    hooks.clear_registered()


def _script(monkeypatch, replies):
    calls = []
    it = iter(replies)

    def fake_stream(**kwargs):
        calls.append(kwargs)
        yield next(it)

    monkeypatch.setattr(agent, "stream", fake_stream)
    return calls


def _tool_msgs(state):
    return [m for m in state.messages if m.get("role") == "tool"]


# ── max_turns ─────────────────────────────────────────────────────────────

def test_max_turns_caps_model_calls(monkeypatch):
    replies = [_turn(tool_calls=[{"id": f"t{i}", "name": "Bash",
                                  "input": {"command": f"echo {i}"}}])
               for i in range(10)]
    calls = _script(monkeypatch, replies)
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "ok")
    state = AgentState()
    events = list(run("go", state, _config(max_turns=2), "sys"))
    assert len(calls) == 2
    assert state.exit_reason == "max_turns"
    assert any("max_turns=2" in getattr(e, "text", "") for e in events)
    # history ends with complete tool_call ↔ tool_result pairs
    assert state.messages[-1]["role"] == "tool"


def test_no_max_turns_keeps_default_behaviour(monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": "a", "name": "Bash",
                                             "input": {"command": "ls"}}]),
                          _turn("done")])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "ok")
    state = AgentState()
    list(run("go", state, _config(), "sys"))
    assert state.exit_reason == "completed"


@pytest.mark.parametrize("value", [None, 0, -3, "nope"])
def test_parse_max_turns_invalid_is_unlimited(value):
    assert agent._parse_max_turns(value) is None


# ── is_error + ordering ───────────────────────────────────────────────────

def test_is_error_flag_and_original_order(monkeypatch):
    calls = [
        {"id": "r1", "name": "Read", "input": {"file_path": "/a"}},
        {"id": "b1", "name": "Bash", "input": {"command": "false"}},
        {"id": "r2", "name": "Read", "input": {"file_path": "/b"}},
    ]
    _script(monkeypatch, [_turn(tool_calls=calls), _turn("done")])

    def fake_exec(name, inputs, **_):
        if name == "Bash":
            return "Error: exit code 1"
        return f"content of {inputs['file_path']}"

    monkeypatch.setattr(agent, "execute_tool", fake_exec)
    import cheetahclaws.tool_registry as reg
    monkeypatch.setattr(reg, "get_tool", lambda n: SimpleNamespace(
        concurrent_safe=(n == "Read")))
    state = AgentState()
    events = list(run("go", state, _config(), "sys"))

    msgs = _tool_msgs(state)
    assert [m["tool_call_id"] for m in msgs] == ["r1", "b1", "r2"]
    assert msgs[1]["is_error"] is True
    assert "is_error" not in msgs[0] and "is_error" not in msgs[2]
    ends = [e for e in events if isinstance(e, ToolEnd)]
    assert [e.id for e in ends] == ["r1", "b1", "r2"]
    assert [e.is_error for e in ends] == [False, True, False]
    starts = [e for e in events if isinstance(e, ToolStart)]
    assert {s.id for s in starts} == {"r1", "b1", "r2"}


def test_denied_permission_uses_front_end_reason(monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": "w", "name": "Write",
                                             "input": {"file_path": "/x", "content": "y"}}]),
                          _turn("ok")])
    executed = []
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: executed.append(a) or "ok")
    state = AgentState()
    gen = run("go", state, _config(permission_mode="manual"), "sys")
    for ev in gen:
        if isinstance(ev, PermissionRequest):
            assert ev.tool_name == "Write" and ev.tool_id == "w"
            assert ev.tool_input["file_path"] == "/x"
            ev.granted = False
            ev.deny_reason = "Denied: headless run"
    assert not executed
    msg = _tool_msgs(state)[0]
    assert msg["content"] == "Denied: headless run"
    assert msg["is_error"] is True


# ── Ctrl-C during parallel tools ──────────────────────────────────────────

def test_ctrl_c_during_parallel_tools_keeps_history_valid(monkeypatch):
    calls = [
        {"id": "p1", "name": "Read", "input": {"file_path": "/slow"}},
        {"id": "p2", "name": "Read", "input": {"file_path": "/boom"}},
        {"id": "s1", "name": "Bash", "input": {"command": "ls"}},
    ]
    _script(monkeypatch, [_turn(tool_calls=calls)])
    release = threading.Event()

    def fake_exec(name, inputs, **_):
        if inputs.get("file_path") == "/slow":
            release.wait(10)
            return "slow done"
        if inputs.get("file_path") == "/boom":
            # A real Ctrl-C: SIGINT lands on the main thread while it is
            # blocked waiting for the parallel batch.
            time.sleep(0.2)
            os.kill(os.getpid(), signal.SIGINT)
            return "boom finished"
        return "never runs"

    monkeypatch.setattr(agent, "execute_tool", fake_exec)
    import cheetahclaws.tool_registry as reg
    monkeypatch.setattr(reg, "get_tool", lambda n: SimpleNamespace(
        concurrent_safe=(n == "Read")))
    state = AgentState()
    t0 = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            list(run("go", state, _config(), "sys"))
        # p1 is still sleeping: we must not have waited for it
        assert time.monotonic() - t0 < 5
    finally:
        release.set()
    msgs = {m["tool_call_id"]: m for m in _tool_msgs(state)}
    assert [m["tool_call_id"] for m in _tool_msgs(state)] == ["p1", "p2", "s1"]
    # finished work is kept; unfinished calls get an interrupted error result
    assert msgs["p2"]["content"] == "boom finished" and "is_error" not in msgs["p2"]
    for tid in ("p1", "s1"):
        assert msgs[tid]["is_error"] is True
        assert "interrupted" in msgs[tid]["content"]
    assert state.exit_reason == "interrupted"


# ── hooks ─────────────────────────────────────────────────────────────────

def test_pre_tool_use_hook_denies_and_rewrites(monkeypatch):
    calls = [{"id": "a", "name": "Bash", "input": {"command": "rm -rf /tmp/x"}},
             {"id": "b", "name": "Bash", "input": {"command": "echo hi"}}]
    _script(monkeypatch, [_turn(tool_calls=calls), _turn("done")])
    seen = []
    monkeypatch.setattr(agent, "execute_tool",
                        lambda name, inputs, **k: seen.append(inputs["command"]) or "ok")

    def guard(payload):
        cmd = payload["tool_input"]["command"]
        if cmd.startswith("rm"):
            return {"decision": "deny", "reason": "no rm"}
        return {"updatedInput": {"command": cmd + " --safe"}}

    hooks.register("PreToolUse", guard, matcher="Bash")
    state = AgentState()
    list(run("go", state, _config(), "sys"))
    assert seen == ["echo hi --safe"]
    msgs = _tool_msgs(state)
    assert msgs[0]["content"] == "Denied by PreToolUse hook: no rm"
    assert msgs[0]["is_error"] is True


def test_pre_tool_use_allow_skips_prompt(monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": "a", "name": "Write",
                                             "input": {"file_path": "/x"}}]),
                          _turn("done")])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "written")
    hooks.register("PreToolUse", lambda p: {"decision": "allow"})
    events = list(run("go", AgentState(), _config(permission_mode="manual"), "sys"))
    assert not any(isinstance(e, PermissionRequest) for e in events)


def test_post_tool_use_feedback_reaches_model(monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": "a", "name": "Bash",
                                             "input": {"command": "ls"}}]),
                          _turn("done")])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "file.txt")
    hooks.register("PostToolUse",
                   lambda p: {"additionalContext": f"lint ok for {p['tool_response']}"})
    state = AgentState()
    list(run("go", state, _config(), "sys"))
    assert "lint ok for file.txt" in _tool_msgs(state)[0]["content"]


def test_user_prompt_submit_block_and_context(monkeypatch):
    calls = _script(monkeypatch, [_turn("done")])
    hooks.register("UserPromptSubmit",
                   lambda p: {"decision": "block", "reason": "secret"}
                   if "password" in p["prompt"] else {"additionalContext": "ctx!"})
    state = AgentState()
    list(run("my password", state, _config(), "sys"))
    assert state.exit_reason == "hook_blocked"
    assert not calls and not state.messages

    state = AgentState()
    list(run("hello", state, _config(), "sys"))
    assert "ctx!" in state.messages[0]["content"]


def test_stop_hook_forces_continue_but_is_bounded(monkeypatch):
    calls = _script(monkeypatch, [_turn(f"answer {i}") for i in range(10)])
    seen_active = []

    def stop(payload):
        seen_active.append(payload["stop_hook_active"])
        return {"decision": "block", "reason": "run the tests first"}

    hooks.register("Stop", stop)
    state = AgentState()
    list(run("go", state, _config(stop_hook_max_continues=2), "sys"))
    assert len(calls) == 3                     # 1 + 2 forced continues
    assert seen_active == [False, True, True]
    assert state.exit_reason == "completed"
    assert any("[Stop hook] run the tests first" == m.get("content")
               for m in state.messages)


def test_session_start_context_attached_to_first_prompt(monkeypatch):
    _script(monkeypatch, [_turn("done")])
    hooks.register("SessionStart", lambda p: {"additionalContext": "branch: main"})
    cfg = _config(_session_id="ss-ctx")
    hooks.session_start(cfg, "startup")
    state = AgentState()
    list(run("hi", state, cfg, "sys"))
    assert "branch: main" in state.messages[0]["content"]


# ── events ────────────────────────────────────────────────────────────────

def test_agent_emits_structured_events(monkeypatch, tmp_path):
    _script(monkeypatch, [_turn("thinking", tool_calls=[{"id": "a", "name": "Bash",
                                                         "input": {"command": "ls"}}]),
                          _turn("final")])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "Error: nope")
    em = EventEmitter("evtest", base_dir=tmp_path)
    got = []
    em.add_sink(got.append)
    list(run("go", AgentState(), _config(_event_emitter=em), "sys"))
    types = [e["type"] for e in got]
    assert types[0] == "user_message"
    assert types.index("tool_call") < types.index("tool_result")
    assert types.count("assistant_message") == 2 and types.count("usage") == 2
    tr = next(e for e in got if e["type"] == "tool_result")
    assert tr["id"] == "a" and tr["is_error"] is True and tr["output"] == "Error: nope"
    assert [e["seq"] for e in got] == sorted(e["seq"] for e in got)
