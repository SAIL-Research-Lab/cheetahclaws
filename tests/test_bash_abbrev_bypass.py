"""Long-option abbreviations and flag-before-subcommand tricks must not be
classified read-only (review findings on the v3.5.90 classifier)."""
import pytest

from cheetahclaws.tools import _is_safe_bash


@pytest.mark.parametrize("cmd", [
    "git ls-remote --upload-pa='touch X' .",
    "git log --ext-dif",
    "git log --textcon",
    "git log --outp=/tmp/x",
    "tar --list -f a.tar --checkpoint=1 --checkpoint-act=exec='touch X'",
    "tar --lis -f a.tar --to-comm='sh -c id'",
    "sort --compress-prog=./x.sh big",
    "sort --outp=/etc/x a",
    "git remote -v add evil https://x",
    "git remote -v set-url origin https://x",
    "git remote --verbose remove origin",
    "git reflog --all expire --expire=now",
    "git reflog -q delete HEAD@{0}",
    "sed --expr='1e touch x' -n p",
    "sed --in-pl s/a/b/ f",
    "sed --bogus-option p f",
    "git config --list --ad x.y z",
])
def test_bypasses_are_not_read_only(cmd):
    assert _is_safe_bash(cmd, {}) is False


@pytest.mark.parametrize("cmd", [
    "git remote -v",
    "git remote",
    "git remote show origin",
    "git remote -v get-url origin",
    "git reflog",
    "git reflog --all",
    "git reflog show HEAD",
    "git log --oneline -5",
    "tar --list -f a.tar",
    "tar -tvf a.tar",
    "sort -n a.txt",
    "sed -n 1,5p f.txt",
    "sed --quiet 1p f.txt",
    "sed --expression=s/a/b/ f.txt",
])
def test_everyday_commands_stay_read_only(cmd):
    assert _is_safe_bash(cmd, {}) is True
