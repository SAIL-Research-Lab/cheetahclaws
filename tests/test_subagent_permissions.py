"""Sub-agent PermissionRequests are answered by a policy, never left unanswered."""
from __future__ import annotations

import pytest

from cheetahclaws.agent import PermissionRequest
from cheetahclaws.multi_agent.subagent import (
    SubAgentManager,
    SubAgentPermissionPolicy,
)


def _req(desc, sig=""):
    return PermissionRequest(description=desc, signature=sig)


def _policy(**kw):
    base = dict(agent_name="worker", parent_auto_approve=False)
    base.update(kw)
    return SubAgentPermissionPolicy(**base)


def test_inherit_denies_edit_outside_worktree_with_reason(tmp_path):
    p = _policy()
    r = _req(f"Edit: {tmp_path}/a.py", f"Edit:{tmp_path}/a.py")
    assert p.decide(r) is False
    assert r.granted is False
    assert "no interactive approver" in r.reason
    assert "a.py" in p.denial_report()


def test_inherit_allows_edit_inside_isolated_worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    p = _policy(worktree_path=str(wt))
    inside = _req(f"Edit: {wt}/src/x.py", f"Edit:{wt}/src/x.py")
    outside = _req(f"Write to: {tmp_path}/y.py", f"Write:{tmp_path}/y.py")
    escape = _req(f"Edit: {wt}/../z.py", f"Edit:{wt}/../z.py")
    assert p.decide(inside) is True
    assert p.decide(outside) is False
    assert p.decide(escape) is False


def test_inherit_denies_bash_without_approver():
    p = _policy()
    r = _req("Run: rm -rf build", "Bash:rm")
    assert p.decide(r) is False
    assert r.reason


def test_parent_grants_and_auto_approve_apply():
    p = _policy(parent_grants={"Bash:git commit"})
    assert p.decide(_req("Run: git commit -m x", "Bash:git commit")) is True
    p2 = _policy(parent_auto_approve=True)
    assert p2.decide(_req("Run: make", "Bash:make")) is True


def test_auto_edits_mode_allows_edits_only():
    p = _policy(mode="auto-edits")
    assert p.decide(_req("Edit: /tmp/q.py", "Edit:/tmp/q.py")) is True
    assert p.decide(_req("Run: make", "Bash:make")) is False


def test_deny_mode_denies_even_with_callback():
    calls = []
    p = _policy(mode="deny", callback=lambda d, c: calls.append(d) or True)
    r = _req("Edit: /tmp/q.py", "Edit:/tmp/q.py")
    assert p.decide(r) is False
    assert "deny" in r.reason
    assert calls == []


def test_callback_forwarded_with_subagent_label():
    seen = []

    def cb(desc, config, signature):
        seen.append((desc, signature))
        return signature == "Bash:make"

    p = _policy(callback=cb)
    assert p.decide(_req("Run: make", "Bash:make")) is True
    r = _req("Run: rm x", "Bash:rm")
    assert p.decide(r) is False
    assert "user rejected" in r.reason
    assert seen[0] == ("[sub-agent worker] Run: make", "Bash:make")


def test_two_arg_callback_and_raising_callback():
    p = _policy(callback=lambda d, c: True)
    assert p.decide(_req("Run: make", "Bash:make")) is True

    def boom(d, c):
        raise RuntimeError("tty gone")
    p2 = _policy(callback=boom)
    r = _req("Run: make", "Bash:make")
    assert p2.decide(r) is False and "tty gone" in r.reason


def test_manual_mode_skips_auto_grants(tmp_path):
    p = _policy(permission_mode="manual", worktree_path=str(tmp_path),
                parent_auto_approve=True)
    assert p.decide(_req(f"Edit: {tmp_path}/a", f"Edit:{tmp_path}/a")) is False


def test_from_parent_config_reads_mode_and_callback():
    cb = lambda d, c: True  # noqa: E731
    p = SubAgentPermissionPolicy.from_parent_config(
        {"subagent_permission": "AUTO-EDITS", "_permission_callback": cb,
         "auto_approve": False}, agent_name="n")
    assert p.mode == "auto-edits" and p.callback is cb
    bad = SubAgentPermissionPolicy.from_parent_config(
        {"subagent_permission": "bogus", "auto_approve": False})
    assert bad.mode == "inherit"
    assert bad.system_note()  # explains denials up front
    auto = SubAgentPermissionPolicy.from_parent_config({"auto_approve": True})
    assert auto.parent_auto_approve and auto.system_note() == ""


# ── integration with SubAgentManager._run ──────────────────────────────────

@pytest.fixture
def manager_with_perm_run(monkeypatch):
    seen = {}

    def fake_run(prompt, state, config, system_prompt, depth=0, cancel_check=None):
        seen["system"] = system_prompt
        req = PermissionRequest(description="Edit: /etc/hosts",
                                signature="Edit:/etc/hosts")
        yield req
        seen["granted"] = req.granted
        state.messages.append({"role": "assistant", "content": "done"})

    monkeypatch.setattr("cheetahclaws.multi_agent.subagent._agent_run", fake_run)
    mgr = SubAgentManager(max_concurrent=2, max_depth=3)
    yield mgr, seen
    mgr.shutdown()


def test_manager_answers_requests_and_reports_denials(manager_with_perm_run):
    mgr, seen = manager_with_perm_run
    task = mgr.spawn("go", {"auto_approve": False}, "SYS", name="w1")
    mgr.wait(task.id, timeout=5)
    assert task.status == "completed"
    assert seen["granted"] is False
    assert "Sub-agent permissions" in seen["system"]
    assert task.result.startswith("done")
    assert "/etc/hosts" in task.result and "denials" in task.result


def test_manager_forwards_to_parent_callback(manager_with_perm_run):
    mgr, seen = manager_with_perm_run
    asked = []
    parent = {"auto_approve": False,
              "_permission_callback": lambda d, c: asked.append(d) or True}
    child = {k: v for k, v in parent.items() if not k.startswith("_")}
    task = mgr.spawn("go", child, "SYS", name="w2", parent_config=parent)
    mgr.wait(task.id, timeout=5)
    assert seen["granted"] is True
    assert asked == ["[sub-agent w2] Edit: /etc/hosts"]
    assert task.result == "done"
