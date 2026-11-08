"""Headless mode: `cheetahclaws exec` / `-p` — prompt input, output formats,
non-interactive permission policy, exit codes, resume, CLI routing."""
from __future__ import annotations

import argparse
import io
import json
import sys

import pytest

from cheetahclaws import agent, headless, hooks
from cheetahclaws.providers import AssistantTurn


def _turn(text="", tool_calls=None):
    value = AssistantTurn.__new__(AssistantTurn)
    value.text = text
    value.tool_calls = tool_calls or []
    value.in_tokens = 10
    value.out_tokens = 5
    value.cache_read_tokens = 0
    value.cache_write_tokens = 0
    return value


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """Isolate sessions dir, session DB, hooks and system prompt."""
    import cheetahclaws.config as cfg
    from cheetahclaws import session_store
    import cheetahclaws.context as ctx
    monkeypatch.setattr(cfg, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(cfg, "DAILY_DIR", tmp_path / "sessions" / "daily")
    monkeypatch.setattr(cfg, "MR_SESSION_DIR", tmp_path / "sessions" / "mr")
    monkeypatch.setattr(session_store, "_DB_PATH", tmp_path / "sessions.db")
    monkeypatch.setattr(session_store._local, "conn", None, raising=False)
    monkeypatch.setattr(ctx, "build_system_prompt", lambda config=None: "sys")
    monkeypatch.setattr(hooks, "_user_settings_path", lambda: tmp_path / "none.json")
    monkeypatch.setenv("CHEETAHCLAWS_PROJECT_DIR", str(tmp_path))
    hooks.clear_registered()
    yield tmp_path
    hooks.clear_registered()


def _script(monkeypatch, replies):
    it = iter(replies)

    def fake_stream(**kwargs):
        yield next(it)

    monkeypatch.setattr(agent, "stream", fake_stream)


def _args(argv):
    p = argparse.ArgumentParser()
    p.add_argument("prompt", nargs="*")
    headless.add_arguments(p)
    return p.parse_args(argv)


def _run(argv, config=None, stdin=None):
    out, err = io.StringIO(), io.StringIO()
    cfg = {"model": "test", "permission_mode": "auto", **(config or {})}
    code = headless.run(cfg, _args(argv), out=out, err=err,
                        stdin=stdin if stdin is not None else TTY(""))
    return code, out.getvalue(), err.getvalue(), cfg


# ── prompt input ──────────────────────────────────────────────────────────

def test_read_prompt_args_stdin_and_dash():
    assert headless.read_prompt(["fix", "bug"], TTY("ignored")) == "fix bug"
    piped = io.StringIO("diff --x\n+line\n")
    assert headless.read_prompt(["review:"], piped) == "review:\n\ndiff --x\n+line"
    assert headless.read_prompt(["-"], io.StringIO("only stdin")) == "only stdin"
    assert headless.read_prompt([], TTY("")) == ""


def test_split_and_match_rules():
    rules = headless.split_rules(["Read,Edit", "Bash(git log:*) Write(src/*.py)"])
    assert rules == ["Read", "Edit", "Bash(git log:*)", "Write(src/*.py)"]
    m = headless.rule_matches
    assert m("Read", "Read", {})
    assert m("mcp__gh__*", "mcp__gh__list", {})
    assert m("Bash(git log:*)", "Bash", {"command": "git log -3"})
    assert m("Bash(git log:*)", "Bash", {"command": "git log"})
    assert not m("Bash(git log:*)", "Bash", {"command": "git logx"})
    # shell control operators never ride along on a prefix rule
    assert not m("Bash(git log:*)", "Bash", {"command": "git log; rm -rf ~"})
    assert not m("Bash(git log:*)", "Bash", {"command": "git log $(rm x)"})
    assert m("Write(src/*.py)", "Write", {"file_path": "src/a.py"})
    assert not m("Write(src/*.py)", "Write", {"file_path": "other/a.py"})
    assert not m("Read", "Write", {})


# ── output formats ────────────────────────────────────────────────────────

def test_text_mode_prints_only_final_answer(iso, monkeypatch):
    _script(monkeypatch, [_turn("The answer is 42.")])
    code, out, err, _ = _run(["what", "is", "it"])
    assert code == 0
    assert out == "The answer is 42.\n"


def test_json_mode_result_object(iso, monkeypatch):
    _script(monkeypatch, [_turn("done")])
    code, out, _, _ = _run(["hi", "--output-format", "json"])
    res = json.loads(out)
    assert code == 0
    assert res["type"] == "result" and res["final_text"] == "done"
    assert res["exit_reason"] == "completed" and res["turns"] == 1
    assert res["usage"]["input_tokens"] == 10 and res["usage"]["output_tokens"] == 5
    assert res["is_error"] is False and "duration_ms" in res and res["session_id"]


def test_stream_json_events_match_event_log(iso, monkeypatch):
    _script(monkeypatch, [
        _turn("checking", tool_calls=[{"id": "t1", "name": "Bash",
                                       "input": {"command": "echo hi"}}]),
        _turn("all good"),
    ])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "hi")
    code, out, _, _ = _run(["go", "--output-format", "stream-json",
                            "--permission-mode", "accept-all"])
    evs = [json.loads(line) for line in out.splitlines()]
    types = [e["type"] for e in evs]
    assert code == 0
    assert types[0] == "session_start" and types[-1] == "result"
    assert evs[0]["model"] == "test" and evs[0]["cwd"]
    assert "tool_call" in types and "tool_result" in types and "usage" in types
    tc = next(e for e in evs if e["type"] == "tool_call")
    assert tc["id"] == "t1" and tc["input"] == {"command": "echo hi"}
    assert evs[-1]["final_text"] == "all good"
    # the persisted log is the same stream minus deltas
    from cheetahclaws import event_log
    sid = evs[0]["session_id"]
    logged = event_log.read_events(sid)
    assert [e["seq"] for e in logged] == [e["seq"] for e in evs
                                          if e["type"] != "assistant_delta"]


# ── permissions ───────────────────────────────────────────────────────────

_WRITE = {"id": "w1", "name": "Write", "input": {"file_path": "/tmp/x", "content": "y"}}


def test_unapproved_tool_is_denied_with_explanation(iso, monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[_WRITE]), _turn("could not write")])
    executed = []
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: executed.append(a) or "ok")
    state_holder = {}
    real_run = agent.run

    def spy(msg, state, *a, **k):
        state_holder["s"] = state
        yield from real_run(msg, state, *a, **k)

    monkeypatch.setattr(agent, "run", spy)
    code, out, _, _ = _run(["write it", "--output-format", "json",
                            "--permission-mode", "manual"])
    res = json.loads(out)
    assert code == 0 and not executed
    assert res["permission_denials"][0]["name"] == "Write"
    tool_msg = [m for m in state_holder["s"].messages if m["role"] == "tool"][0]
    assert "non-interactive" in tool_msg["content"] and tool_msg["is_error"]


def test_stop_on_permission_denied_exits_2(iso, monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[_WRITE]), _turn("never")])
    code, out, _, _ = _run(["write", "--output-format", "json", "--permission-mode",
                            "manual", "--on-permission-denied", "stop"])
    assert code == 2 and json.loads(out)["exit_reason"] == "permission_denied"


def test_allowed_tools_grant(iso, monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[_WRITE]), _turn("written")])
    executed = []
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: executed.append(a) or "ok")
    code, out, _, _ = _run(["write", "--permission-mode", "manual",
                            "--allowed-tools", "Write(/tmp/*)"])
    assert code == 0 and executed and out == "written\n"


def test_disallowed_rule_with_args_denies_even_in_accept_all(iso, monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": "b", "name": "Bash",
                                             "input": {"command": "rm -rf x"}}]),
                          _turn("ok")])
    executed = []
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: executed.append(a) or "ok")
    code, _, _, cfg = _run(["x", "--permission-mode", "accept-all",
                            "--disallowed-tools", "Bash(rm:*),WebFetch"])
    assert code == 0 and not executed
    assert "WebFetch" in cfg["disabled_tools"] and "AskUserQuestion" in cfg["disabled_tools"]
    assert not hooks._PY_HOOKS          # per-run hook was unregistered


def test_explicit_permission_mode_disables_autonomous_default(iso):
    cfg = {"auto_approve": True}
    headless.apply_args_to_config(cfg, _args(["--permission-mode", "auto"]))
    from cheetahclaws.permissions import auto_approve_on
    assert not auto_approve_on(cfg)


# ── exit codes / limits ───────────────────────────────────────────────────

def test_max_turns_exit_2(iso, monkeypatch):
    _script(monkeypatch, [_turn(tool_calls=[{"id": f"t{i}", "name": "Bash",
                                             "input": {"command": f"echo {i}"}}])
                          for i in range(5)])
    monkeypatch.setattr(agent, "execute_tool", lambda *a, **k: "ok")
    code, out, _, _ = _run(["loop", "--max-turns", "2", "--output-format", "json",
                            "--permission-mode", "accept-all"])
    res = json.loads(out)
    assert code == 2 and res["exit_reason"] == "max_turns" and res["turns"] == 2


def test_api_failure_exit_1(iso, monkeypatch):
    def boom(**_):
        raise ValueError("bad request")
        yield  # pragma: no cover

    monkeypatch.setattr(agent, "stream", boom)
    code, out, _, _ = _run(["x", "--output-format", "json"])
    res = json.loads(out)
    assert code == 1 and res["exit_reason"] == "api_error" and res["is_error"]


def test_missing_prompt_is_error(iso):
    code, out, err, _ = _run([])
    assert code == 1 and out == "" and "no prompt" in err


# ── resume ────────────────────────────────────────────────────────────────

def test_resume_and_continue(iso, monkeypatch):
    _script(monkeypatch, [_turn("first"), _turn("second"), _turn("third")])
    _, out, _, _ = _run(["remember 7", "--output-format", "json"])
    sid = json.loads(out)["session_id"]

    seen = {}
    real_run = agent.run

    def spy(msg, state, *a, **k):
        seen["n"] = len(state.messages)
        yield from real_run(msg, state, *a, **k)

    monkeypatch.setattr(agent, "run", spy)
    code, out, _, _ = _run(["what number?", "--resume", sid, "--output-format", "json"])
    assert code == 0 and seen["n"] == 2 and json.loads(out)["session_id"] == sid
    code, out, _, _ = _run(["again", "--continue", "--output-format", "json"])
    assert code == 0 and seen["n"] == 4

    code, _, err, _ = _run(["x", "--resume", "nosuchid"])
    assert code == 1 and "no saved session" in err


# ── CLI routing ───────────────────────────────────────────────────────────

def test_cli_exec_routes_to_headless(iso, monkeypatch):
    import cheetahclaws.cli as cli
    import cheetahclaws.config as cfg
    import cheetahclaws.bootstrap as boot
    monkeypatch.setattr(cfg, "load_config", lambda: {"model": "test"})
    monkeypatch.setattr(boot, "bootstrap", lambda c: None)
    captured = {}

    def fake_run(config, args, out=None):
        captured.update(args=args, out=out, stdout=sys.stdout)
        return 2

    monkeypatch.setattr(headless, "run", fake_run)
    monkeypatch.setattr(sys, "stdout", sys.stdout)   # restored after main swaps it
    monkeypatch.setattr(sys, "argv", ["cheetahclaws", "exec", "--output-format",
                                      "json", "--max-turns", "3", "do", "it"])
    with pytest.raises(SystemExit) as ei:
        cli.main()
    assert ei.value.code == 2
    a = captured["args"]
    assert a.print_mode and a.prompt == ["do", "it"] and a.max_turns == 3
    assert a.output_format == "json"
    # everything but the result goes to stderr while headless runs
    assert captured["stdout"] is sys.stderr


def test_help_text_is_not_stale():
    import cheetahclaws.cli as cli
    assert "python cheetahclaws.py" not in cli.__doc__
    assert "cheetahclaws exec" in cli.__doc__


def test_path_rules_cannot_escape_the_workspace(tmp_path, monkeypatch):
    from cheetahclaws.headless import rule_matches
    (tmp_path / "src").mkdir()
    monkeypatch.chdir(tmp_path)
    assert rule_matches("Edit(src/**)", "Edit", {"file_path": "src/a.py"})
    assert rule_matches("Edit(src/**)", "Edit", {"file_path": str(tmp_path / "src" / "a.py")})
    assert not rule_matches("Edit(src/**)", "Edit", {"file_path": "src/../../../home/u/.bashrc"})
    assert not rule_matches("Edit(*.py)", "Edit", {"file_path": "../outside.py"})
    assert not rule_matches("Write(src/*.py)", "Write", {"file_path": "/etc/passwd"})
    assert rule_matches("Read(/etc/*)", "Read", {"file_path": "/etc/hosts"})


def test_untrusted_project_items_are_reported_not_silent(iso, monkeypatch):
    import os
    from cheetahclaws import trust
    monkeypatch.delenv(trust.TRUST_ENV, raising=False)
    item = {"kind": "mcp", "name": "gh", "file": "/r/.mcp.json", "reason": "untrusted"}
    monkeypatch.setattr(trust, "pending_untrusted",
                        lambda path=None: [] if trust.trust_all_enabled({}) else [item])
    _script(monkeypatch, [_turn("done"), _turn("done")])
    code, out, err, _ = _run(["hi", "--output-format", "json"])
    assert code == 0
    assert json.loads(out)["skipped_untrusted"] == [item]
    assert "mcp:gh" in err and "--trust-workspace" in err

    code, out, err, _ = _run(["hi", "--output-format", "json", "--trust-workspace"])
    assert json.loads(out)["skipped_untrusted"] == []
    assert "--trust-workspace" not in err
    assert trust.TRUST_ENV not in os.environ        # this run only
