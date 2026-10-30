"""Edit / MultiEdit / Write quality: read-before-edit, encodings, line endings,
atomic writes, error hints and diff previews."""
from __future__ import annotations

import codecs
import os
import stat

import pytest

from cheetahclaws.tools import execute_tool, preview_edit
from cheetahclaws.tools.fs import _edit, _multi_edit, _write, replace_in_text, EditError
from cheetahclaws.tools import file_state


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    file_state.reset_all_trackers()
    yield
    file_state.reset_all_trackers()


def _cfg(sid="s1", **kw):
    return {"_session_id": sid, "permission_mode": "accept-all", **kw}


def run(name, cfg=None, **inputs):
    return execute_tool(name, inputs, permission_mode="accept-all", config=cfg or _cfg())


# ── read-before-edit ─────────────────────────────────────────────────────

def test_edit_requires_prior_read(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    out = run("Edit", file_path=str(f), old_string="x = 1", new_string="x = 2")
    assert out.startswith("Error:") and "has not been read" in out
    assert f.read_text() == "x = 1\n"
    run("Read", file_path=str(f))
    out = run("Edit", file_path=str(f), old_string="x = 1", new_string="x = 2")
    assert out.startswith("Changes applied to a.py")
    assert f.read_text() == "x = 2\n"
    # The agent's own edit refreshes the stamp: a second edit needs no re-read.
    out = run("Edit", file_path=str(f), old_string="x = 2", new_string="x = 3")
    assert out.startswith("Changes applied"), out


def test_stale_file_is_refused_until_reread(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    run("Read", file_path=str(f))
    f.write_text("x = 1\ny = 2\n")          # changed behind the agent's back
    os.utime(f, ns=(1, 1))
    out = run("Edit", file_path=str(f), old_string="x = 1", new_string="x = 9")
    assert "modified on disk since you last read it" in out
    assert f.read_text() == "x = 1\ny = 2\n"
    run("Read", file_path=str(f))
    assert run("Edit", file_path=str(f), old_string="x = 1",
               new_string="x = 9").startswith("Changes applied")


def test_touch_without_content_change_is_not_stale(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    run("Read", file_path=str(f))
    os.utime(f, ns=(10**9, 10**9))
    assert run("Edit", file_path=str(f), old_string="x = 1",
               new_string="x = 2").startswith("Changes applied")


def test_tracker_is_session_scoped(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    run("Read", cfg=_cfg("A"), file_path=str(f))
    out = run("Edit", cfg=_cfg("B"), file_path=str(f), old_string="x = 1", new_string="x = 2")
    assert "has not been read" in out
    assert run("Edit", cfg=_cfg("A"), file_path=str(f), old_string="x = 1",
               new_string="x = 2").startswith("Changes applied")


def test_overwriting_write_requires_read_but_new_file_does_not(tmp_path):
    f = tmp_path / "new.txt"
    assert run("Write", file_path=str(f), content="hi\n").startswith("Created")
    # Written by the agent → it knows the content, may overwrite.
    assert run("Write", file_path=str(f), content="ho\n").startswith("File updated")
    g = tmp_path / "existing.txt"
    g.write_text("keep\n")
    out = run("Write", file_path=str(g), content="clobber\n")
    assert "has not been read" in out and g.read_text() == "keep\n"


def test_escape_hatch_disables_read_requirement(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    out = run("Edit", cfg=_cfg(edit_require_read=False), file_path=str(f),
              old_string="x = 1", new_string="x = 2")
    assert out.startswith("Changes applied")


def test_direct_function_calls_keep_legacy_behaviour(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world\n")
    assert "+goodbye world" in _edit(str(f), "hello", "goodbye")
    assert "-goodbye world" in _write(str(f), "new\n")


# ── uniqueness / not-found diagnostics ───────────────────────────────────

def test_ambiguous_match_reports_count_and_lines(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a\nfoo\nb\nfoo\nc\nfoo\n")
    out = _edit(str(f), "foo", "bar")
    assert "appears 3 times" in out and "lines 2, 4, 6" in out


def test_whitespace_hint_not_applied(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def f():\n\treturn 1   \n")
    out = _edit(str(f), "def f():\n    return 1\n", "def f():\n    return 2\n")
    assert "old_string not found" in out
    assert "ignoring whitespace" in out and "lines 1-2" in out
    assert f.read_text() == "def f():\n\treturn 1   \n"


def test_no_op_edit_is_rejected(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x\n")
    assert "No changes to make" in _edit(str(f), "x", "x")


def test_empty_old_string_creates_file(tmp_path):
    f = tmp_path / "sub" / "n.py"
    out = _edit(str(f), "", "print(1)\n")
    assert out.startswith("Created") and f.read_text() == "print(1)\n"


# ── line endings ─────────────────────────────────────────────────────────

def test_crlf_file_stays_crlf(tmp_path):
    f = tmp_path / "w.txt"
    f.write_bytes(b"one\r\ntwo\r\nthree\r\n")
    _edit(str(f), "two\n", "TWO\nextra\n")
    assert f.read_bytes() == b"one\r\nTWO\r\nextra\r\nthree\r\n"


def test_mixed_endings_untouched_outside_region(tmp_path):
    f = tmp_path / "m.txt"
    f.write_bytes(b"a\r\nb\nc\r\nd\n")
    _edit(str(f), "c", "C1\nC2")
    # Only the edited region changed; the LF line 'b' and 'd' kept their LF.
    assert f.read_bytes() == b"a\r\nb\nC1\r\nC2\r\nd\n"


def test_replace_all_maps_offsets_correctly():
    text = "x\r\ny\r\nx\r\n"
    assert replace_in_text(text, "x\n", "z\n", True) == "z\r\ny\r\nz\r\n"


def test_write_keeps_crlf_style_for_lf_content(tmp_path):
    f = tmp_path / "w.txt"
    f.write_bytes(b"a\r\nb\r\n")
    _write(str(f), "a\nB\n")
    assert f.read_bytes() == b"a\r\nB\r\n"


# ── encodings ────────────────────────────────────────────────────────────

def test_utf8_bom_preserved(tmp_path):
    f = tmp_path / "b.txt"
    f.write_bytes(codecs.BOM_UTF8 + "héllo\n".encode())
    _edit(str(f), "﻿héllo", "hi")      # BOM in old_string is tolerated
    assert f.read_bytes() == codecs.BOM_UTF8 + b"hi\n"


def test_utf16_roundtrip(tmp_path):
    f = tmp_path / "u16.txt"
    f.write_bytes("line1\r\nlíne2\r\n".encode("utf-16"))
    out = _edit(str(f), "líne2", "line二")
    assert out.startswith("Changes applied"), out
    data = f.read_bytes()
    assert data.startswith(codecs.BOM_UTF16_LE)
    assert data.decode("utf-16") == "line1\r\nline二\r\n"


def test_read_shows_utf16_and_hides_bom(tmp_path):
    f = tmp_path / "u16.txt"
    f.write_bytes("alpha\nbeta\n".encode("utf-16"))
    out = run("Read", file_path=str(f))
    assert "     1\talpha" in out and "     2\tbeta" in out
    g = tmp_path / "bom.txt"
    g.write_bytes(codecs.BOM_UTF8 + b"first\n")
    assert run("Read", file_path=str(g)).startswith("     1\tfirst")


def test_latin1_file_ascii_edit_is_byte_exact(tmp_path):
    f = tmp_path / "l1.txt"
    original = "café = 1\nother = 2\n".encode("latin-1")
    f.write_bytes(original)
    out = _edit(str(f), "other = 2", "other = 3")
    assert out.startswith("Changes applied"), out
    assert f.read_bytes() == "café = 1\nother = 3\n".encode("latin-1")
    assert b"\xef\xbf\xbd" not in f.read_bytes()


def test_gbk_file_non_ascii_edit_refused(tmp_path):
    f = tmp_path / "gbk.txt"
    f.write_bytes("中文\nx = 1\n".encode("gbk"))
    before = f.read_bytes()
    out = _edit(str(f), "x = 1", "x = 中")
    assert out.startswith("Error:") and "not valid UTF-8" in out
    assert f.read_bytes() == before


def test_replacement_char_never_written(tmp_path):
    f = tmp_path / "gbk.txt"
    f.write_bytes("中文\n".encode("gbk"))
    before = f.read_bytes()
    out = _write(str(f), "��\n")
    assert out.startswith("Error:") and "U+FFFD" in out
    assert f.read_bytes() == before


def test_binary_file_refused(tmp_path):
    f = tmp_path / "bin.dat"
    f.write_bytes(b"abc\x00\xff\xfe\x01")
    out = _edit(str(f), "abc", "xyz")
    assert "binary" in out and f.read_bytes() == b"abc\x00\xff\xfe\x01"


# ── atomic writes ────────────────────────────────────────────────────────

@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_mode_bits_preserved_and_no_temp_left(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    f = d / "run.sh"
    f.write_text("echo hi\n")
    os.chmod(f, 0o751)
    _edit(str(f), "hi", "bye")
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o751
    assert sorted(p.name for p in d.iterdir()) == ["run.sh"]


@pytest.mark.skipif(os.name != "posix", reason="symlinks")
def test_symlink_target_updated_link_kept(tmp_path):
    real = tmp_path / "real.txt"
    real.write_text("a\n")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    _edit(str(link), "a", "b")
    assert link.is_symlink() and real.read_text() == "b\n"


def test_failed_write_leaves_original(tmp_path, monkeypatch):
    d = tmp_path / "d"
    d.mkdir()
    f = d / "a.txt"
    f.write_text("orig\n")

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(file_state.os, "replace", boom)
    out = _edit(str(f), "orig", "new")
    assert out.startswith("Error:") and f.read_text() == "orig\n"
    assert sorted(p.name for p in d.iterdir()) == ["a.txt"]


# ── MultiEdit ────────────────────────────────────────────────────────────

def test_multiedit_sequential_and_atomic(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("a = 1\nb = 2\n")
    out = _multi_edit(str(f), [
        {"old_string": "a = 1", "new_string": "a = 10"},
        {"old_string": "a = 10\nb", "new_string": "a = 10\nbb"},
    ])
    assert out.startswith("Changes applied to m.py (2 edits)")
    assert f.read_text() == "a = 10\nbb = 2\n"
    out = _multi_edit(str(f), [
        {"old_string": "a = 10", "new_string": "a = 11"},
        {"old_string": "missing", "new_string": "x"},
    ])
    assert "edit 2/2" in out and "No edits were applied" in out
    assert f.read_text() == "a = 10\nbb = 2\n"


def test_multiedit_via_registry_requires_read(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("a\n")
    edits = [{"old_string": "a", "new_string": "b"}]
    assert "has not been read" in run("MultiEdit", file_path=str(f), edits=edits)
    run("Read", file_path=str(f))
    assert run("MultiEdit", file_path=str(f), edits=edits).startswith("Changes applied")
    assert "missing required parameter 'edits'" in run("MultiEdit", file_path=str(f))


def test_multiedit_blocked_in_plan_mode(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("a\n")
    cfg = _cfg(permission_mode="plan", edit_require_read=False)
    out = execute_tool("MultiEdit", {"file_path": str(f),
                                     "edits": [{"old_string": "a", "new_string": "b"}]},
                       permission_mode="accept-all", config=cfg)
    assert "plan mode" in out and f.read_text() == "a\n"


# ── preview ──────────────────────────────────────────────────────────────

def test_preview_edit_is_pure_and_colorless(tmp_path):
    f = tmp_path / "p.py"
    f.write_text("x = 1\n")
    d = preview_edit("Edit", {"file_path": str(f), "old_string": "x = 1",
                              "new_string": "x = 2"}, {})
    assert "-x = 1" in d and "+x = 2" in d and "\x1b[" not in d
    assert f.read_text() == "x = 1\n"
    d = preview_edit("Write", {"file_path": str(tmp_path / "n.py"), "content": "y\n"}, {})
    assert "+y" in d and not (tmp_path / "n.py").exists()
    d = preview_edit("MultiEdit", {"file_path": str(f), "edits": [
        {"old_string": "x", "new_string": "z"}]}, {})
    assert "+z = 1" in d
    assert preview_edit("Edit", {"file_path": str(f), "old_string": "nope",
                                 "new_string": "q"}, {}).startswith("Error:")
    assert preview_edit("Bash", {"command": "ls"}, {}) == ""


def test_preview_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("".join(f"l{i}\n" for i in range(500)))
    d = preview_edit("Write", {"file_path": str(f), "content": "x\n"},
                     {"edit_preview_max_lines": 20})
    assert "more lines" in d and d.count("\n") < 30
