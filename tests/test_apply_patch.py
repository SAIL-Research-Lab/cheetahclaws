"""ApplyPatch: Codex-format parsing, fuzzy context, atomic multi-file apply."""
from __future__ import annotations

import pytest

from cheetahclaws.tools import execute_tool, preview_edit
from cheetahclaws.tools import file_state
from cheetahclaws.tools.patch import apply_patch, parse_patch, patch_paths, PatchError


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    file_state.reset_all_trackers()
    root = tmp_path / "ws"
    root.mkdir()
    yield root
    file_state.reset_all_trackers()


def cfg(root, **kw):
    return {"_session_id": "p1", "_worktree_cwd": str(root), "edit_require_read": False, **kw}


def P(body: str) -> str:
    return "*** Begin Patch\n" + body + "*** End Patch\n"


def test_update_add_delete_move(ws):
    (ws / "a.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    (ws / "old.txt").write_text("bye\n")
    (ws / "mv.txt").write_text("keep\nme\n")
    out = apply_patch(P(
        "*** Update File: a.py\n"
        "@@ def g():\n"
        "-    return 2\n"
        "+    return 3\n"
        "*** Add File: pkg/new.py\n"
        "+print('new')\n"
        "*** Delete File: old.txt\n"
        "*** Update File: mv.txt\n"
        "*** Move to: moved/mv2.txt\n"
        " keep\n"
        "-me\n"
        "+you\n"
    ), cfg(ws))
    assert out.startswith("Success."), out
    assert (ws / "a.py").read_text().endswith("def g():\n    return 3\n")
    assert (ws / "pkg/new.py").read_text() == "print('new')\n"
    assert not (ws / "old.txt").exists()
    assert not (ws / "mv.txt").exists()
    assert (ws / "moved/mv2.txt").read_text() == "keep\nyou\n"


def test_atomic_failure_changes_nothing(ws):
    (ws / "a.txt").write_text("one\ntwo\n")
    (ws / "b.txt").write_text("three\n")
    out = apply_patch(P(
        "*** Update File: a.txt\n"
        "-one\n+ONE\n"
        "*** Delete File: b.txt\n"
        "*** Update File: a2.txt\n"
        "-zzz\n+yyy\n"
    ), cfg(ws))
    assert out.startswith("Error:") and "No files were modified" in out
    assert (ws / "a.txt").read_text() == "one\ntwo\n"
    assert (ws / "b.txt").exists()


def test_fuzzy_trailing_whitespace_and_crlf_preserved(ws):
    (ws / "w.txt").write_bytes(b"alpha  \r\nbeta\t\r\ngamma\r\n")
    out = apply_patch(P("*** Update File: w.txt\n alpha\n-beta\n+BETA\n gamma\n"), cfg(ws))
    assert out.startswith("Success."), out
    assert (ws / "w.txt").read_bytes() == b"alpha  \r\nBETA\r\ngamma\r\n"


def test_ambiguous_context_is_an_error(ws):
    (ws / "d.txt").write_text("x\ny\nx\ny\n")
    out = apply_patch(P("*** Update File: d.txt\n x\n-y\n+z\n"), cfg(ws))
    assert "matches 2 locations" in out
    out = apply_patch(P("*** Update File: d.txt\n x\n-y\n+z\n x\n y\n*** End of File\n"), cfg(ws))
    # 3-line context x,y,x ending at EOF is unique
    assert out.startswith("Success."), out
    assert (ws / "d.txt").read_text() == "x\nz\nx\ny\n"


def test_eof_and_missing_final_newline(ws):
    (ws / "n.txt").write_text("a\nb")      # no trailing newline
    out = apply_patch(P("*** Update File: n.txt\n a\n-b\n+c\n"), cfg(ws))
    assert out.startswith("Success."), out
    assert (ws / "n.txt").read_text() == "a\nc"
    out = apply_patch(P("*** Update File: n.txt\n c\n+d\n"), cfg(ws))
    assert (ws / "n.txt").read_text() == "a\nc\nd"
    out = apply_patch(P("*** Update File: n.txt\n@@ d\n+e\n"), cfg(ws))
    assert (ws / "n.txt").read_text() == "a\nc\nd\ne\n"


def test_add_existing_file_refused(ws):
    (ws / "e.txt").write_text("x\n")
    out = apply_patch(P("*** Add File: e.txt\n+y\n"), cfg(ws))
    assert "already exists" in out and (ws / "e.txt").read_text() == "x\n"


def test_parse_errors():
    with pytest.raises(PatchError):
        parse_patch("no markers")
    with pytest.raises(PatchError):
        parse_patch(P("*** Update File: a\nbogus line\n"))
    with pytest.raises(PatchError):
        parse_patch(P("*** Update File: a\n"))
    ops = parse_patch("apply_patch <<'EOF'\n" + P("*** Delete File: x\n") + "EOF\n")
    assert ops[0].kind == "delete"


def test_patch_paths_and_preview_are_pure(ws):
    (ws / "a.txt").write_text("1\n")
    patch = P("*** Update File: a.txt\n*** Move to: b.txt\n-1\n+2\n*** Add File: c.txt\n+c\n")
    paths = patch_paths(patch, cfg(ws))
    assert paths == [str(ws / "a.txt"), str(ws / "b.txt"), str(ws / "c.txt")]
    d = preview_edit("ApplyPatch", {"patch": patch}, cfg(ws))
    assert "rename a.txt → b.txt" in d and "+2" in d and "+c" in d
    assert (ws / "a.txt").read_text() == "1\n" and not (ws / "c.txt").exists()


def test_registry_requires_read_for_updates_only(ws):
    (ws / "a.txt").write_text("1\n")
    c = {"_session_id": "p2", "_worktree_cwd": str(ws)}
    out = execute_tool("ApplyPatch", {"patch": P("*** Update File: a.txt\n-1\n+2\n")},
                       permission_mode="accept-all", config=c)
    assert "has not been read" in out
    out = execute_tool("ApplyPatch", {"patch": P("*** Add File: n.txt\n+x\n")},
                       permission_mode="accept-all", config=c)
    assert out.startswith("Success.")
    execute_tool("Read", {"file_path": str(ws / "a.txt")}, permission_mode="accept-all", config=c)
    out = execute_tool("ApplyPatch", {"patch": P("*** Update File: a.txt\n-1\n+2\n")},
                       permission_mode="accept-all", config=c)
    assert out.startswith("Success."), out


def test_delete_goes_through_permission(ws):
    (ws / "a.txt").write_text("1\n")
    asked = []

    def ask(desc):
        asked.append(desc)
        return False
    out = execute_tool("ApplyPatch", {"patch": P("*** Delete File: a.txt\n")},
                       permission_mode="auto", ask_permission=ask, config=cfg(ws))
    assert out.startswith("Denied") and asked == ["ApplyPatch: D a.txt"]
    assert (ws / "a.txt").exists()


def test_plan_mode_blocks_patch(ws):
    out = execute_tool("ApplyPatch", {"patch": P("*** Add File: x.txt\n+x\n")},
                       permission_mode="accept-all", config=cfg(ws, permission_mode="plan"))
    assert "plan mode" in out and not (ws / "x.txt").exists()


def test_rollback_when_rename_fails_midway(ws, monkeypatch):
    (ws / "a.txt").write_text("a\n")
    (ws / "b.txt").write_text("b\n")
    from cheetahclaws.tools import patch as patch_mod
    real = patch_mod.commit_temp
    calls = []

    def flaky(tmp, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("boom")
        return real(tmp, target)
    monkeypatch.setattr(patch_mod, "commit_temp", flaky)
    out = apply_patch(P("*** Update File: a.txt\n-a\n+A\n*** Update File: b.txt\n-b\n+B\n"), cfg(ws))
    assert "rolled back" in out
    assert (ws / "a.txt").read_text() == "a\n" and (ws / "b.txt").read_text() == "b\n"
    assert sorted(p.name for p in ws.iterdir()) == ["a.txt", "b.txt"]
