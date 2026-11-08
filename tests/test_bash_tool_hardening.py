"""Bash tool execution hardening: hard denylist, process-group cleanup,
opt-in environment scrubbing and opt-in sandbox."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.tools import shell as shell_mod
from cheetahclaws.tools.shell import _bash, _bash_hard_denied

POSIX = sys.platform != "win32"
HAS_BWRAP = sys.platform.startswith("linux") and shutil.which("bwrap") is not None


# ── Hard denylist ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /*",
    'rm -rf "/"',
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf ~/*",
    "rm -rf $HOME",
    'rm -rf "${HOME}/"',
    "rm -r --no-preserve-root /x",
    "sudo rm -rf /usr",
    "cd /tmp && rm -fr /etc/",
    "find / -delete",
    "find ~ -mindepth 1 -delete",
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda bs=1M",
    "cat x > /dev/nvme0n1",
    "shred -n1 /dev/sdb",
    "chmod -R 777 /",
    "chmod -R a+rwx /usr",
    "chown -R nobody /etc",
    ":(){ :|:& };:",
    "bomb(){ bomb|bomb& };bomb",
])
def test_host_destroying_commands_are_refused(cmd):
    assert _bash_hard_denied(cmd) is not None
    assert _bash(cmd).startswith("Error: command refused by Bash hard-denylist")


@pytest.mark.parametrize("cmd", [
    "rm -rf build dist",
    "rm -rf ./node_modules",
    "rm -rf /tmp/build-123",
    "rm -rf ~/project/build",
    'rm -rf "$HOME/.cache/pip"',
    "rm -f /etc-backup.txt",
    "find ~ -name '*.pyc' -delete",
    "find . -delete",
    "chmod -R 755 ./scripts",
    "chown -R me:me ~",
    "dd if=/dev/zero of=./disk.img bs=1M count=1",
    "echo hi > /dev/null",
])
def test_routine_commands_are_not_refused(cmd):
    assert _bash_hard_denied(cmd) is None


# ── Process-group cleanup ────────────────────────────────────────────────

def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie still answers kill(0); check its state where we can.
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split()[2] != "Z"
    except OSError:
        return True


def _wait_dead(pid: int, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.skipif(not POSIX, reason="process groups are POSIX")
def test_timeout_kills_background_descendants(tmp_path):
    pidfile = tmp_path / "pid"
    out = _bash(f"sleep 60 & echo $! > {pidfile}; wait", timeout=1, cwd=str(tmp_path))
    assert "timed out" in out
    pid = int(pidfile.read_text().strip())
    assert _wait_dead(pid), "background child survived the timeout"


@pytest.mark.skipif(not POSIX, reason="process groups are POSIX")
def test_keyboard_interrupt_kills_the_command(tmp_path, monkeypatch):
    pidfile = tmp_path / "pid"
    real_communicate = subprocess.Popen.communicate

    def interrupted(self, *a, **k):
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.1)
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    with pytest.raises(KeyboardInterrupt):
        _bash(f"sleep 60 & echo $! > {pidfile}; wait", timeout=30, cwd=str(tmp_path))
    monkeypatch.setattr(subprocess.Popen, "communicate", real_communicate)
    pid = int(pidfile.read_text().strip())
    assert _wait_dead(pid), "Ctrl-C left the command running as an orphan"


# ── Environment scrubbing ────────────────────────────────────────────────

@pytest.mark.skipif(not POSIX, reason="uses sh parameter expansion")
def test_scrub_env_is_opt_in_and_strips_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "false")
    monkeypatch.delenv("CHEETAHCLAWS_BASH_SCRUB_ENV", raising=False)
    probe = ('echo "${OPENAI_API_KEY:-none} ${GITHUB_TOKEN:-none} '
             '${AWS_SECRET_ACCESS_KEY:-none} ${TOKENIZERS_PARALLELISM:-none}"')
    assert _bash(probe) == "sk-secret ghp-secret aws-secret false"
    assert _bash(probe, config={"bash_scrub_env": True}) == "none none none false"
    assert _bash(probe, config={"bash_scrub_env": True,
                                "bash_env_keep": ["GITHUB_TOKEN"]}) \
        == "none ghp-secret none false"


# ── Sandbox ──────────────────────────────────────────────────────────────

def test_sandbox_mode_is_validated():
    out = _bash("true", config={"bash_sandbox": "bogus"})
    assert out.startswith("Error:") and "bash_sandbox" in out


def test_sandbox_fails_closed_when_unavailable(monkeypatch):
    from cheetahclaws.kernel import sandbox
    monkeypatch.setattr(sandbox.shutil, "which", lambda name: None)
    monkeypatch.setattr(sandbox.os.path, "exists",
                        lambda p, _e=os.path.exists: False if "sandbox-exec" in str(p) else _e(p))
    out = _bash("echo ran", config={"bash_sandbox": "workspace-write"})
    assert out.startswith("Error:")
    assert "bash_sandbox=off" in out
    assert "ran" not in out.splitlines()


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_workspace_write_sandbox(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    outside = tmp_path / "outside.txt"
    cfg = {"bash_sandbox": "workspace-write"}
    out = _bash(f"touch inside.txt && echo ok; touch {outside}; "
                f"touch /usr/cheetah-should-fail 2>&1 || echo ro", cwd=str(ws), config=cfg)
    if "bwrap:" in out and "ok" not in out:
        pytest.skip(f"bwrap cannot create namespaces here: {out}")
    assert (ws / "inside.txt").exists()
    assert "ro" in out
    # /tmp is a private tmpfs: a write there never reaches the host
    assert not outside.exists()


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_read_only_sandbox_blocks_workspace_writes(tmp_path):
    out = _bash("touch x.txt 2>/dev/null && echo wrote || echo blocked",
                cwd=str(tmp_path), config={"bash_sandbox": "read-only"})
    if "bwrap:" in out:
        pytest.skip(f"bwrap cannot create namespaces here: {out}")
    assert "blocked" in out
    assert not (tmp_path / "x.txt").exists()


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_sandbox_denies_network_unless_enabled(tmp_path):
    # /proc/net/dev lists the interfaces of the caller's net namespace; an
    # unshared one has only the loopback device.
    probe = "tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | sort | tr '\\n' ' '"
    out = _bash(probe, cwd=str(tmp_path), config={"bash_sandbox": "workspace-write"})
    if "bwrap:" in out:
        pytest.skip(f"bwrap cannot create namespaces here: {out}")
    assert out.split() == ["lo"]
    host = _bash(probe, cwd=str(tmp_path))
    if host.split() != ["lo"]:
        out = _bash(probe, cwd=str(tmp_path), config={
            "bash_sandbox": "workspace-write", "bash_sandbox_network": True})
        assert out.split() == host.split()


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_sandbox_masks_credential_stores(tmp_path):
    ssh = os.path.expanduser("~/.ssh")
    if not os.path.isdir(ssh) or not os.listdir(ssh):
        pytest.skip("no populated ~/.ssh on this host")
    out = _bash(f"ls -A {ssh} | wc -l", cwd=str(tmp_path),
                config={"bash_sandbox": "read-only"})
    if "bwrap:" in out:
        pytest.skip(f"bwrap cannot create namespaces here: {out}")
    assert out.strip() == "0"


def test_sandbox_off_is_the_default(monkeypatch):
    monkeypatch.delenv("CHEETAHCLAWS_BASH_SANDBOX", raising=False)
    assert shell_mod._bash_sandbox_mode({}) == "off"
    assert shell_mod._bash_sandbox_mode({"bash_sandbox": True}) == "workspace-write"


def test_interpreter_binds_are_only_for_this_python_and_never_expose_home():
    from cheetahclaws.kernel.sandbox import interpreter_bind_paths
    assert interpreter_bind_paths(["/bin/sh", "-c", "true"]) == []
    paths = interpreter_bind_paths([sys.executable, "-c", "pass"])
    home = os.path.realpath(os.path.expanduser("~"))
    for p in paths:
        rp = os.path.realpath(p)
        assert rp != "/" and rp != home
        assert not home.startswith(rp.rstrip("/") + "/")
    # already-bound prefixes are not bound twice
    assert interpreter_bind_paths([sys.executable], existing=("/",)) == []
