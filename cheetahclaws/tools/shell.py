"""tools_shell.py — Shell tool implementations: Bash, Grep."""
from __future__ import annotations

import os
import re
import shlex
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
    re.compile(r"\brm\b[^\n;&|]*--no-preserve-root"),
    re.compile(r"\bmkfs(?:\.\w+)?\s"),
    re.compile(r"\bdd\b[^\n]*\bof=/dev/(?:sd|hd|nvme|vd|mmcblk|xvd|disk)"),
    re.compile(r">\s*/dev/(?:sd|hd|nvme|vd|mmcblk|xvd|disk)"),
    re.compile(r"\b(?:shred|wipefs)\b[^\n]*/dev/(?:sd|hd|nvme|vd|mmcblk|xvd|disk)"),
    re.compile(r"\bchmod\s+-R\s+[0-7]{3,4}\s+/\s*(?:$|\s)"),
    re.compile(r"\bchown\s+-R\s+\S+\s+/\s*(?:$|\s)"),
    re.compile(r":\(\)\s*\{\s*:\s*\|\s*:&\s*\}\s*;\s*:"),  # classic fork bomb
    # the same bomb under any name: `b(){ b|b& };b`
    re.compile(r"([A-Za-z_:][\w:]*)\s*\(\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;?\s*\1\b"),
)

# Recursive targets whose loss is unrecoverable: the root, the home
# directory, and the top-level system directories.  Matched against parsed
# arguments of rm / chmod / chown / find, so quoting (`rm -rf "/"`) and
# spelling (`~`, `$HOME`, `${HOME}/*`) don't slip past.
_SYSTEM_TOP_DIRS = ("/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib64",
                    "/proc", "/root", "/sbin", "/srv", "/sys", "/usr", "/var",
                    "/System", "/Users", "/Library", "/Applications")
_HOME_SPELLINGS = ("~", "$HOME", "${HOME}")


def _is_catastrophic_target(arg: str, include_home: bool = True) -> bool:
    a = arg.strip()
    if a.endswith("/*"):
        a = a[:-2] or "/"
    if a in _HOME_SPELLINGS or any(a == h + "/" for h in _HOME_SPELLINGS):
        return include_home
    if not a.startswith("/"):
        return False
    norm = os.path.normpath(a)
    if norm.startswith("//"):
        norm = "/" + norm.lstrip("/")
    if norm == "/" or norm in _SYSTEM_TOP_DIRS:
        return True
    try:
        home = os.path.normpath(os.path.expanduser("~"))
        return include_home and home != "/" and norm in (home, os.path.realpath(home))
    except Exception:
        return False


def _is_recursive_flag(a: str, letters: str = "rR") -> bool:
    if a == "--recursive":
        return True
    return a.startswith("-") and not a.startswith("--") and any(ch in a[1:] for ch in letters)


def _hard_denied_by_tokens(cmd: str) -> str | None:
    """Token-level checks for the destructive forms a regex can't see."""
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        tokens = cmd.split()
    segments: list[list[str]] = [[]]
    for t in tokens:
        if t and all(ch in ";&|()<>\n" for ch in t):
            segments.append([])
        else:
            segments[-1].append(t)
    for seg in segments:
        for i, tok in enumerate(seg):
            prog = os.path.basename(tok)
            args = seg[i + 1:]
            if prog == "rm":
                if any(_is_recursive_flag(a, "rR") for a in args) and \
                        any(_is_catastrophic_target(a) for a in args
                            if not a.startswith("-")):
                    return "recursive rm of /, the home directory, or a system directory"
            elif prog in ("chmod", "chown", "chgrp"):
                if any(_is_recursive_flag(a, "R") for a in args) and \
                        any(_is_catastrophic_target(a, include_home=False)
                            for a in args if not a.startswith("-")):
                    return f"recursive {prog} of /, the home directory, or a system directory"
            elif prog == "find":
                paths = []
                for a in args:
                    if a.startswith("-") or a in ("(", "!"):
                        break
                    paths.append(a)
                # Only the unfiltered form: `find ~ -name '*.pyc' -delete`
                # is routine cleanup, `find / -delete` is not.
                rest, j = args[len(paths):], 0
                preds = []
                while j < len(rest):
                    if rest[j] in ("-mindepth", "-maxdepth"):
                        j += 2
                        continue
                    if rest[j] not in ("-depth", "-xdev", "-mount", "-P", "-L", "-H"):
                        preds.append(rest[j])
                    j += 1
                if any(_is_catastrophic_target(p) for p in paths) and preds == ["-delete"]:
                    return "find -delete over /, the home directory, or a system directory"
    return None


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
    reason = _hard_denied_by_tokens(cmd)
    if reason:
        return (
            f"Error: command refused by Bash hard-denylist ({reason}). This "
            f"is a host-destroying invocation and cannot be bypassed by "
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


def _terminate_proc_tree(proc: subprocess.Popen, grace: float = 2.0) -> None:
    """SIGTERM the command's whole process group, then SIGKILL survivors.

    The Bash child is started in its own session, so its pid is also its
    process-group id — killing the group reaches every descendant even after
    the shell itself has exited (a backgrounded `sleep`, a dev server).
    """
    if sys.platform == "win32":
        _kill_proc_tree(proc.pid)
        try:
            proc.wait(timeout=grace)
        except Exception:
            pass
        return
    import signal
    pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    # Sweep the group even when the leader exited on SIGTERM: descendants
    # that ignore it (or were mid-fork) are still there.
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass


# ── Child environment ─────────────────────────────────────────────────────

# Variable names that hold a credential.  Matched on `_`-separated words, so
# TOKENIZERS_PARALLELISM or PASSENGER_HOME are left alone.
_SECRET_ENV_RE = re.compile(
    r"(?:^|_)(?:API_?KEY|APIKEY|KEY_?ID|TOKEN|SECRET|SECRETS|PASSWORD|PASSWD|"
    r"PASSPHRASE|CREDENTIALS?|PRIVATE_KEY|ACCESS_KEY|SESSION_KEY|AUTH_KEY)(?:_|$)",
    re.IGNORECASE,
)
_SECRET_ENV_PREFIXES = ("AWS_", "AZURE_", "GOOGLE_APPLICATION_CREDENTIALS")


def _bash_child_env(config: dict) -> dict | None:
    """The environment for the Bash child, or None to inherit unchanged.

    With ``bash_scrub_env: true`` provider API keys, tokens, passwords and
    cloud credentials are removed, so a command the model runs (or a script
    it was tricked into running) cannot read them.  ``bash_env_keep`` lists
    names to pass through anyway (e.g. ``["GITHUB_TOKEN"]`` for `gh`).
    """
    scrub = config.get("bash_scrub_env")
    if scrub is None:
        scrub = os.environ.get("CHEETAHCLAWS_BASH_SCRUB_ENV", "0") == "1"
    if not scrub:
        return None
    keep = set(config.get("bash_env_keep") or ())
    env = {}
    for k, v in os.environ.items():
        if k not in keep and (_SECRET_ENV_RE.search(k) or k.startswith(_SECRET_ENV_PREFIXES)):
            continue
        env[k] = v
    return env


def _bash_sandbox_mode(config: dict) -> str:
    mode = config.get("bash_sandbox")
    if mode is None:
        mode = os.environ.get("CHEETAHCLAWS_BASH_SANDBOX", "off")
    if mode is True:
        return "workspace-write"
    if mode in (False, None, ""):
        return "off"
    return str(mode).strip().lower()


# ── Bash ──────────────────────────────────────────────────────────────────

_BASH_MAX_CMD_LEN = 65536


def _bash(command: str, timeout: int = 30, cwd: str = None,
          shell_policy: str = "allow", session_id: str = "default",
          config: dict | None = None) -> str:
    """Run ``command`` with ``/bin/sh -c`` and return its combined output.

    ``config`` (optional) enables the opt-in hardening:

    * ``bash_sandbox``: ``"off"`` (default), ``"workspace-write"`` or
      ``"read-only"`` — run inside bubblewrap (Linux) / sandbox-exec (macOS)
      with the host read-only, the workspace (``cwd``) writable in
      ``workspace-write``, a private /tmp and credential stores masked.
      ``bash_sandbox_network`` (default False) keeps network access;
      ``bash_sandbox_writable`` adds more writable directories.  When the
      sandbox is on but unavailable the command is refused, not run bare.
    * ``bash_scrub_env``: strip API keys / tokens from the child environment.

    The command's whole process group is terminated on timeout and on
    KeyboardInterrupt, so nothing it started outlives the tool call.
    """
    cfg = config or {}
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
    workdir = cwd or os.getcwd()
    kwargs = dict(
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace', cwd=workdir,
    )
    env = _bash_child_env(cfg)
    if env is not None:
        kwargs["env"] = env
    if sys.platform != "win32":
        kwargs["start_new_session"] = True

    mode = _bash_sandbox_mode(cfg)
    if mode == "off":
        args, kwargs["shell"] = command, True
    else:
        from cheetahclaws.kernel.sandbox import (
            SandboxNotAvailable, SandboxPolicyError, shell_sandbox_argv,
        )
        try:
            args = shell_sandbox_argv(
                ["/bin/sh", "-c", command], mode,
                workspace=workdir,
                network=bool(cfg.get("bash_sandbox_network", False)),
                writable=tuple(cfg.get("bash_sandbox_writable") or ()),
            )
        except (SandboxNotAvailable, SandboxPolicyError) as e:
            return f"Error: {e}"

    proc = None
    try:
        proc = subprocess.Popen(args, **kwargs)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _terminate_proc_tree(proc)
            return f"Error: timed out after {timeout}s (process killed)"
        out = stdout
        if stderr:
            out += ("\n" if out else "") + "[stderr]\n" + stderr
        return out.strip() or "(no output)"
    except Exception as e:
        return f"Error: {e}"
    finally:
        # KeyboardInterrupt (or any other escape) mid-communicate: don't
        # leave the command running as an orphan.
        if proc is not None and proc.poll() is None:
            _terminate_proc_tree(proc)


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
