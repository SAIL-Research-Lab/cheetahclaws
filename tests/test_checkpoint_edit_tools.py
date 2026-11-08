"""Checkpoints cover MultiEdit / ApplyPatch (incl. delete + move), are keyed
per session, and can rewind files first touched after the target snapshot."""
from __future__ import annotations

import pytest

from cheetahclaws.checkpoint import hooks, store
from cheetahclaws.tools import execute_tool
from cheetahclaws.tools import file_state


class FakeState:
    def __init__(self, n=0):
        self.messages = [{}] * n
        self.turn_count = n


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    store.reset_file_versions()
    file_state.reset_all_trackers()
    hooks.install_hooks()
    ws = tmp_path / "ws"
    ws.mkdir()
    yield ws
    for sid in ("ck1", "ck2", "ck3"):
        hooks.forget_session(sid)
    file_state.reset_all_trackers()


def _run(name, sid, ws, **inp):
    cfg = {"_session_id": sid, "_worktree_cwd": str(ws), "edit_require_read": False}
    return execute_tool(name, inp, permission_mode="accept-all", config=cfg)


def _snap(sid, n):
    s = store.make_snapshot(sid, FakeState(n), {}, f"turn {n}",
                            tracked_edits=hooks.get_tracked_edits(sid))
    hooks.reset_tracked(sid)
    return s


def test_multiedit_and_patch_are_tracked_and_rewindable(env):
    ws = env
    hooks.set_session("ck1")
    a, b, gone = ws / "a.txt", ws / "b.txt", ws / "gone.txt"
    a.write_text("a1\n")
    b.write_text("b1\n")
    gone.write_text("bye\n")
    s0 = _snap("ck1", 0)

    out = _run("MultiEdit", "ck1", ws, file_path=str(a),
               edits=[{"old_string": "a1", "new_string": "a2"}])
    assert out.startswith("Changes applied")
    out = _run("ApplyPatch", "ck1", ws, patch=(
        "*** Begin Patch\n"
        "*** Update File: b.txt\n*** Move to: c.txt\n-b1\n+c1\n"
        "*** Delete File: gone.txt\n"
        "*** Add File: new.txt\n+n\n"
        "*** End Patch\n"))
    assert out.startswith("Success."), out
    tracked = hooks.get_tracked_edits("ck1")
    assert set(tracked) == {str(a), str(b), str(ws / "c.txt"), str(gone), str(ws / "new.txt")}
    _snap("ck1", 1)

    assert set(store.files_changed_since("ck1", s0.id)) >= {str(a), str(gone)}
    store.rewind_files("ck1", s0.id)
    assert a.read_text() == "a1\n"
    assert b.read_text() == "b1\n"
    assert gone.read_text() == "bye\n"
    assert not (ws / "c.txt").exists()
    assert not (ws / "new.txt").exists()


def test_tracked_edits_are_per_session(env):
    ws = env
    hooks.set_session("ck2")
    hooks.set_session("ck3")          # most recent → default
    f = ws / "x.txt"
    f.write_text("x\n")
    _run("Edit", "ck2", ws, file_path=str(f), old_string="x", new_string="y")
    assert str(f) in hooks.get_tracked_edits("ck2")
    assert hooks.get_tracked_edits("ck3") == {}
    assert hooks.get_tracked_edits() == {}          # current session = ck3
    hooks.reset_tracked("ck3")
    assert str(f) in hooks.get_tracked_edits("ck2")


def test_large_file_not_deleted_on_rewind(env, monkeypatch):
    ws = env
    hooks.set_session("ck1")
    monkeypatch.setattr(store, "_MAX_FILE_SIZE", 3)
    big = ws / "big.txt"
    big.write_text("0123456789\n")
    s0 = _snap("ck1", 0)
    _run("Edit", "ck1", ws, file_path=str(big), old_string="0123", new_string="abcd")
    _snap("ck1", 1)
    res = store.rewind_files("ck1", s0.id)
    assert big.exists()                    # existed before: never deleted
    assert any("not restorable" in r for r in res)


def test_snapshot_json_roundtrip_keeps_pre_edit(env):
    from cheetahclaws.checkpoint.types import Snapshot
    s = Snapshot(1, "s", "t", 0, 0, "", {}, {}, {"/p": {"backup_filename": None, "existed": False}})
    assert Snapshot.from_dict(s.to_dict()).pre_edit_backups == s.pre_edit_backups
    legacy = Snapshot(1, "s", "t", 0, 0, "", {}).to_dict()
    assert "pre_edit_backups" not in legacy
    assert Snapshot.from_dict(legacy).pre_edit_backups == {}
