"""tools_shell.py — Shell tool implementations: Bash, Grep."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


# Patterns that are *never* allowed, even under permission_mode=accept-all.
# These are obvious host-destroying / filesystem-corrupting invocations that
# no legitimate agent task should ever issue. The list is intentionally
# narrow to avoid false positives.
_BASH_HARD_DENY = (
    re.compile(r"\brm\s+(?:-[a-zA-Z]*[rRf][a-zA-Z]*\s+|--recursive\s+|--force\s+)+/\s*(?:$|\s)"),
    re.compile(r"\brm\s+-[a-zA-Z]*[rRf][a-zA-Z]*\s+/\*"),
    re.compile(r"\bmkfs(?:\.\w+)?\s"),
    re.compile(r"\bdd\b[^\n]*\bof=/dev/(?:sd|hd|nvme|vd|mmcblk|xvd)"),
    re.compile(r">\s*/dev/(?:sd|hd|nvme|vd|mmcblk|xvd)"),
    re.compile(r"\bchmod\s+-R\s+[0-7]{3,4}\s+/\s*(?:$|\s)"),
    re.compile(r"\bchown\s+-R\s+\S+\s+/\s*(?:$|\s)"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:"),  # classic fork bomb
)


def _bash_hard_denied(cmd: str) -> str | None:
    """Return a denial reason if cmd matches a hard denylist, else None."""
    for pat in _BASH_HARD_DENY:
        if pat.search(cmd):
            return (
                f"Error: command refused by Bash hard-denylist "
                f"(matched pattern: {pat.pattern!r}). This is a host-"
                f"destroying invocation and cannot be bypassed by "
                f"permission_mode."
            )
    return None


# ── Process tree kill ─────────────────────────────────────────────────────

def _kill_proc_tree(pid: int) -> None:
    """Kill a process and all its children."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


# ── Bash ──────────────────────────────────────────────────────────────────

_BASH_MAX_CMD_LEN = 65536


def _bash(command: str, timeout: int = 30, cwd: str = None,
          shell_policy: str = "allow", session_id: str = "default") -> str:
    if shell_policy == "deny":
        return "Error: Bash execution is disabled (shell_policy=deny)."
    if not isinstance(command, str):
        return "Error: Bash command must be a string."
    if "\x00" in command:
        return "Error: Bash command contains a NUL byte."
    if len(command) > _BASH_MAX_CMD_LEN:
        return f"Error: Bash command exceeds {_BASH_MAX_CMD_LEN} chars."
    denied = _bash_hard_denied(command)
    if denied:
        print(
            f"[bash][session={session_id}] BLOCKED {command[:300]}",
            file=sys.stderr, flush=True,
        )
        return denied
    if shell_policy == "log":
        print(
            f"[bash][session={session_id}] {command[:300]}",
            file=sys.stderr, flush=True,
        )
    kwargs = dict(
        shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', cwd=cwd or os.getcwd(),
    )
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(command, **kwargs)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_proc_tree(proc.pid)
            proc.wait()
            return f"Error: timed out after {timeout}s (process killed)"
        out = stdout
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        return out.strip() or "(no output)"
    except Exception as e:
        return f"Error: {e}"


# ── Grep ──────────────────────────────────────────────────────────────────

def _has_rg() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, check=True, encoding='utf-8', errors='replace')
        return True
    except Exception:
        return False


def _grep(
    pattern: str,
    path: str = None,
    glob: str = None,
    output_mode: str = "files_with_matches",
    case_insensitive: bool = False,
    context: int = 0,
    cwd: str = None,
) -> str:
    use_rg = _has_rg()
    # grep needs its own flags: it rejects ripgrep's --no-heading outright, and
    # without -r it won't descend into a directory. -E keeps the regex dialect
    # close to ripgrep's; -I skips binary files as ripgrep does.
    cmd = ["rg", "--no-heading"] if use_rg else ["grep", "-r", "-E", "-I"]
    if case_insensitive:
        cmd.append("-i")
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")
    else:
        cmd.append("-n")
        if context:
            cmd += ["-C", str(context)]
    if glob:
        cmd += (["--glob", glob] if use_rg else ["--include", glob])
    cmd += ["-e", pattern]
    cmd.append(path or cwd or str(Path.cwd()))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        out = r.stdout.strip()
        if not use_rg and output_mode == "count":
            # grep -c lists every file it read; ripgrep only those that match.
            out = "\n".join(l for l in out.splitlines() if not l.endswith(":0"))
        if out:
            return out[:20000]
        # Both tools exit 1 for "nothing matched" and 2+ for a real failure
        # (bad regex, unreadable path, unsupported flag). Reporting the latter
        # as "No matches found" tells the model the text isn't there.
        if r.returncode > 1:
            return f"Error: {cmd[0]} failed: {r.stderr.strip()[:500] or f'exit code {r.returncode}'}"
        return "No matches found"
    except Exception as e:
        return f"Error: {e}"
