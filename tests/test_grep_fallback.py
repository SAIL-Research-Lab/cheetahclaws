"""Grep tool without ripgrep installed.

The fallback used to pass ripgrep's flags to grep, which rejects them, and the
empty output was reported as "No matches found" — so on any machine without
`rg` the tool told the model that text plainly present in a file wasn't there.
"""
from __future__ import annotations

import shutil

import pytest

import cheetahclaws.tools.shell as _shell
from cheetahclaws.tools.shell import _grep

pytestmark = pytest.mark.skipif(shutil.which("grep") is None, reason="needs grep")


@pytest.fixture(params=["grep", "rg"])
def corpus(request, tmp_path, monkeypatch):
    """A small tree, searched once per backend so both stay in agreement."""
    if request.param == "rg" and not _shell._has_rg():
        pytest.skip("ripgrep not installed")
    monkeypatch.setattr(_shell, "_has_rg", lambda: request.param == "rg")
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.md").write_text("alpha\nProject Falcon launch\n", encoding="utf-8")
    (tmp_path / "sub" / "b.py").write_text("falcon = 1\nfalcon += 1\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("nothing here\n", encoding="utf-8")
    return tmp_path


def test_finds_files_recursively(corpus):
    out = _grep("Falcon", path=str(corpus), case_insensitive=True)
    assert "a.md" in out and "b.py" in out and "c.txt" not in out


def test_content_mode_has_line_numbers(corpus):
    out = _grep("Falcon", path=str(corpus), output_mode="content")
    assert "a.md:2:Project Falcon launch" in out


def test_count_mode_lists_only_matching_files(corpus):
    out = _grep("falcon", path=str(corpus), output_mode="count")
    assert out.strip().endswith("b.py:2")
    assert "c.txt" not in out and "a.md" not in out


def test_glob_filter(corpus):
    out = _grep("falcon", path=str(corpus), glob="*.py", case_insensitive=True)
    assert "b.py" in out and "a.md" not in out


def test_alternation_regex(corpus):
    out = _grep("alpha|nothing", path=str(corpus))
    assert "a.md" in out and "c.txt" in out


def test_pattern_starting_with_dash(corpus):
    (corpus / "d.txt").write_text("--flag value\n", encoding="utf-8")
    assert "d.txt" in _grep("--flag", path=str(corpus))


def test_no_match_is_not_an_error(corpus):
    assert _grep("zzz-not-present", path=str(corpus)) == "No matches found"


def test_failure_is_reported_not_swallowed(corpus):
    out = _grep("x", path=str(corpus / "does-not-exist"))
    assert out.startswith("Error:")
