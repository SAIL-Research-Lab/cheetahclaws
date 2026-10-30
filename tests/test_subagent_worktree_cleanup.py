"""Sub-agent worktree cleanup must never destroy the sub-agent's work."""
import subprocess

import pytest

from cheetahclaws.multi_agent.subagent import _create_worktree, _remove_worktree


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.txt").write_text("a\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _branches(repo):
    return _git(repo, "branch", "--format=%(refname:short)").split()


def test_untouched_worktree_is_fully_removed(repo):
    wt, br = _create_worktree(str(repo))
    assert _remove_worktree(wt, br, str(repo)) == ""
    assert br not in _branches(repo)


def test_branch_with_commits_is_kept(repo):
    wt, br = _create_worktree(str(repo))
    with open(f"{wt}/new.txt", "w") as f:
        f.write("work\n")
    _git(wt, "add", ".")
    _git(wt, "commit", "-qm", "sub-agent work")
    note = _remove_worktree(wt, br, str(repo))
    assert br in _branches(repo)
    assert f"git merge {br}" in note


def test_uncommitted_changes_keep_worktree_and_branch(repo, tmp_path):
    wt, br = _create_worktree(str(repo))
    with open(f"{wt}/a.txt", "w") as f:
        f.write("edited\n")
    note = _remove_worktree(wt, br, str(repo))
    assert "uncommitted changes" in note
    assert br in _branches(repo)
    with open(f"{wt}/a.txt") as f:
        assert f.read() == "edited\n"
