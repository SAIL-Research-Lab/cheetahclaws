"""
bridges/terminal_runner.py — Shell command execution with streaming output for bridges.

Usage (from any bridge bg thread):
    from cheetahclaws.bridges.terminal_runner import run_terminal, stop_terminal

When a user sends "!<command>" from phone, the bridge calls run_terminal().
Stdout/stderr are streamed back to the phone via send_fn in chunks.

The running process is tracked per session so "!stop" can kill it.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from typing import Callable

from cheetahclaws import logging_utils as _log

# ── Active process registry ────────────────────────────────────────────────
_active: dict[str, subprocess.Popen] = {}   # session_key → Popen
_lock = threading.Lock()

_MAX_CHUNK_CHARS  = 3500   # max chars per message chunk (Telegram/Slack safe)
_CHUNK_INTERVAL   = 2.0    # seconds between streamed chunks
_MAX_TOTAL_OUTPUT = 40_000  # stop collecting after this many chars total
_MAX_RUNTIME      = 300     # hard timeout seconds (5 min)
_MAX_CMD_LEN      = 4096


def _bridge_terminal_disabled() -> bool:
    """Operators can hard-disable remote shell with CHEETAHCLAWS_BRIDGE_TERMINAL=0."""
    return os.environ.get("CHEETAHCLAWS_BRIDGE_TERMINAL", "1") == "0"


def run_terminal(
    cmd: str,
    send_fn: Callable[[str], None],
    session_key: str = "default",
    *,
    stop_event: threading.Event | None = None,
) -> None:
    """
    Execute `cmd` in a shell, streaming stdout+stderr back via send_fn.

    Enabled by default. ``shell=True`` is the feature (``!cmd`` is a remote
    shell), so callers MUST gate on bridges.auth.is_authorized() before
    reaching here — every bridge poll loop does so for all ``!`` commands.
    Set CHEETAHCLAWS_BRIDGE_TERMINAL=0 to hard-disable for sensitive deployments.
    NUL byte / length / hard-denylist guards still apply.
    """
    if _bridge_terminal_disabled():
        send_fn("⚠ Remote terminal is disabled (CHEETAHCLAWS_BRIDGE_TERMINAL=0).")
        _log.warn("terminal_blocked_disabled", session=session_key, cmd=cmd[:100])
        return
    if not isinstance(cmd, str) or "\x00" in cmd or len(cmd) > _MAX_CMD_LEN:
        send_fn("⚠ Refused: command empty, too long, or contains NUL.")
        return
    try:
        from cheetahclaws.tools.shell import _bash_hard_denied
        denied = _bash_hard_denied(cmd)
    except Exception:
        denied = None
    if denied:
        send_fn(f"⚠ {denied}")
        _log.warn("terminal_blocked_hard_deny", session=session_key, cmd=cmd[:100])
        return

    _log.info("terminal_run", session=session_key, cmd=cmd[:200])

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except Exception as exc:
        send_fn(f"⚠ Could not start command: {exc}")
        return

    with _lock:
        _active[session_key] = proc

    buf: list[str] = []
    total_chars = 0
    last_send = time.monotonic()
    truncated = False

    def _flush() -> None:
        nonlocal last_send
        if not buf:
            return
        chunk = "".join(buf)
        buf.clear()
        send_fn(f"```\n{chunk}\n```")
        last_send = time.monotonic()

    try:
        deadline = time.monotonic() + _MAX_RUNTIME
        for line in proc.stdout:           # type: ignore[union-attr]
            if stop_event and stop_event.is_set():
                proc.kill()
                break
            if time.monotonic() > deadline:
                proc.kill()
                send_fn("⏱ Command timed out (5 min limit).")
                break

            buf.append(line)
            total_chars += len(line)

            if total_chars > _MAX_TOTAL_OUTPUT:
                _flush()
                send_fn("⚠ Output truncated (limit reached).")
                truncated = True
                proc.kill()
                break

            # Send chunk every _CHUNK_INTERVAL seconds or every _MAX_CHUNK_CHARS chars
            if (time.monotonic() - last_send >= _CHUNK_INTERVAL
                    or sum(len(l) for l in buf) >= _MAX_CHUNK_CHARS):
                _flush()

        if not truncated:
            _flush()

        proc.wait(timeout=5)
        rc = proc.returncode
        _log.info("terminal_done", session=session_key, returncode=rc)
        if rc is not None and rc != 0:
            send_fn(f"⚠ Exit code: {rc}")

    except Exception as exc:
        _log.warn("terminal_error", session=session_key, error=str(exc)[:200])
        send_fn(f"⚠ Error during execution: {exc}")
    finally:
        with _lock:
            _active.pop(session_key, None)


def stop_terminal(session_key: str = "default") -> bool:
    """Kill the active terminal command for this session. Returns True if killed."""
    with _lock:
        proc = _active.pop(session_key, None)
    if proc:
        try:
            proc.kill()
        except Exception:
            pass
        _log.info("terminal_stop", session=session_key)
        return True
    return False


def is_terminal_running(session_key: str = "default") -> bool:
    with _lock:
        return session_key in _active
