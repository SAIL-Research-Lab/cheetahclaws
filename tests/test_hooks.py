"""User hooks: settings loading, command protocol, trust gating, registry."""
from __future__ import annotations

import json
import sys
import types

import pytest

from cheetahclaws import hooks

PY = sys.executable


@pytest.fixture
def env(tmp_path, monkeypatch):
    user = tmp_path / "user_settings.json"
    proj = tmp_path / "proj"
    (proj / ".cheetahclaws").mkdir(parents=True)
    monkeypatch.setattr(hooks, "_user_settings_path", lambda: user)
    monkeypatch.setenv("CHEETAHCLAWS_PROJECT_DIR", str(proj))
    monkeypatch.delenv("CHEETAHCLAWS_DISABLE_HOOKS", raising=False)
    hooks.clear_registered()
    yield types.SimpleNamespace(user=user, proj=proj, tmp=tmp_path)
    hooks.clear_registered()


def _script(tmp, name, body):
    p = tmp / name
    p.write_text(body)
    return f"{PY} {p}"


def _settings(path, event, command, matcher=None, **extra):
    group = {"hooks": [{"type": "command", "command": command, **extra}]}
    if matcher:
        group["matcher"] = matcher
    path.write_text(json.dumps({"hooks": {event: [group]}}))


def test_no_hooks_is_noop(env):
    assert not hooks.has_hooks("PreToolUse")
    r = hooks.run_hooks("PreToolUse", {"tool_name": "Bash"}, match_value="Bash")
    assert r.ran == 0 and r.decision is None


def test_exit_2_blocks_with_stderr_and_gets_payload(env):
    cmd = _script(env.tmp, "h.py", (
        "import json, os, sys\n"
        "p = json.load(sys.stdin)\n"
        "assert p['hook_event_name'] == 'PreToolUse'\n"
        "assert os.environ['CHEETAHCLAWS_PROJECT_DIR']\n"
        "sys.stderr.write('no ' + p['tool_input']['command'])\n"
        "sys.exit(2)\n"))
    _settings(env.user, "PreToolUse", cmd, matcher="Bash")
    r = hooks.run_hooks("PreToolUse", {"tool_name": "Bash",
                                       "tool_input": {"command": "rm"}},
                        match_value="Bash")
    assert r.decision == "deny" and r.reason == "no rm"
    # matcher is a full regex match on the tool name
    r2 = hooks.run_hooks("PreToolUse", {"tool_name": "BashX"}, match_value="BashX")
    assert r2.ran == 0


def test_claude_code_json_envelope(env):
    out = {"hookSpecificOutput": {"permissionDecision": "deny",
                                  "permissionDecisionReason": "policy",
                                  "updatedInput": {"command": "ls -la"}}}
    cmd = _script(env.tmp, "h.py", f"print({json.dumps(json.dumps(out))})")
    _settings(env.user, "PreToolUse", cmd)
    r = hooks.run_hooks("PreToolUse", {"tool_input": {"command": "ls"}}, match_value="Bash")
    assert r.decision == "deny" and r.reason == "policy"
    assert r.updated_input == {"command": "ls -la"}


def test_nonzero_exit_is_non_blocking_unless_fail_closed(env):
    cmd = _script(env.tmp, "h.py", "import sys; sys.exit(1)")
    _settings(env.user, "PreToolUse", cmd)
    r = hooks.run_hooks("PreToolUse", {}, match_value="Bash")
    assert r.decision is None and r.errors

    _settings(env.user, "PreToolUse", cmd + " ", failClosed=True)
    r = hooks.run_hooks("PreToolUse", {}, match_value="Bash")
    assert r.decision == "deny" and "fail-closed" in r.reason


def test_timeout(env):
    cmd = _script(env.tmp, "h.py", "import time; time.sleep(5)")
    _settings(env.user, "Stop", cmd, timeout=0.3)
    r = hooks.run_hooks("Stop", {})
    assert r.decision is None and "timed out" in r.errors[0]


def test_plain_stdout_is_context_for_prompt_submit(env):
    cmd = _script(env.tmp, "h.py", "print('today is tuesday')")
    _settings(env.user, "UserPromptSubmit", cmd)
    r = hooks.run_hooks("UserPromptSubmit", {"prompt": "x"})
    assert r.additional_context == "today is tuesday"


def test_continue_false_halts(env):
    cmd = _script(env.tmp, "h.py",
                  "print('{\"continue\": false, \"stopReason\": \"enough\"}')")
    _settings(env.user, "PostToolUse", cmd)
    r = hooks.run_hooks("PostToolUse", {}, match_value="Edit")
    assert r.halt and r.stop_reason == "enough"


def test_project_hooks_require_trust(env, monkeypatch):
    cmd = _script(env.tmp, "h.py", "import sys; sys.exit(2)")
    _settings(env.proj / ".cheetahclaws" / "settings.json", "PreToolUse", cmd)
    # project never trusted (conftest isolates trust.json) → ignored
    assert not hooks.has_hooks("PreToolUse")

    from cheetahclaws import trust as _trust
    monkeypatch.setattr(_trust, "is_hooks_approved",
                        lambda f, block: str(f).startswith(str(env.proj)))
    hooks._cache["key"] = None
    assert hooks.has_hooks("PreToolUse")
    assert hooks.run_hooks("PreToolUse", {}, match_value="Bash").decision == "deny"


def test_disable_all_hooks(env):
    cmd = _script(env.tmp, "h.py", "import sys; sys.exit(2)")
    env.user.write_text(json.dumps({
        "disableAllHooks": True,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": cmd}]}]}}))
    assert not hooks.has_hooks("Stop")


def test_python_registry_and_precedence(env):
    hooks.register("PreToolUse", lambda p: {"decision": "allow"})
    hooks.register("PreToolUse", lambda p: {"decision": "ask"}, matcher="Write|Edit")
    assert hooks.run_hooks("PreToolUse", {}, match_value="Read").decision == "allow"
    assert hooks.run_hooks("PreToolUse", {}, match_value="Edit").decision == "ask"
    unreg = hooks.register("PreToolUse", lambda p: {"decision": "deny"})
    assert hooks.run_hooks("PreToolUse", {}, match_value="Read").decision == "deny"
    unreg()
    assert hooks.run_hooks("PreToolUse", {}, match_value="Read").decision == "allow"


def test_python_hook_exception_is_contained(env):
    def boom(_):
        raise RuntimeError("x")
    hooks.register("PostToolUse", boom)
    r = hooks.run_hooks("PostToolUse", {}, match_value="Bash")
    assert r.decision is None and "RuntimeError" in r.errors[0]


def test_updated_input_chains_between_hooks(env):
    hooks.register("PreToolUse", lambda p: {"updatedInput": {"n": p["tool_input"]["n"] + 1}})
    hooks.register("PreToolUse", lambda p: {"updatedInput": {"n": p["tool_input"]["n"] * 10}})
    r = hooks.run_hooks("PreToolUse", {"tool_input": {"n": 1}}, match_value="X")
    assert r.updated_input == {"n": 20}


def test_register_rejects_unknown_event():
    with pytest.raises(ValueError):
        hooks.register("BeforeLunch", lambda p: None)


def test_hook_outcome_recorded_in_event_log(env, tmp_path):
    from cheetahclaws.event_log import EventEmitter
    em = EventEmitter("hookrec", base_dir=tmp_path)
    got = []
    em.add_sink(got.append)
    hooks.register("PreToolUse", lambda p: {"decision": "deny", "reason": "nope"})
    hooks.run_hooks("PreToolUse", {}, match_value="Bash",
                    config={"_event_emitter": em, "_session_id": "hookrec"})
    assert got[-1]["type"] == "hook" and got[-1]["decision"] == "deny"
