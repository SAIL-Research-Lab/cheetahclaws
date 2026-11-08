"""sandbox.py — RLIMIT + optional bubblewrap subprocess sandbox (RFC 0008).

This module is the third Phase-1 invariant ("blast radius = 1 agent")
for the cheetahclaws agent OS. It is a primitive: it provides building
blocks (preexec_fn, argv wrapper, one-shot run helper) but does not
spawn or supervise long-running agents. F-4 (subprocess agent runner)
will adopt the API.

Also provides the opt-in Bash tool sandbox (``shell_sandbox_argv``,
used by tools/shell.py when ``bash_sandbox`` is set). Importing this
module has no side effects beyond loading stdlib modules.

Threat model: defends against buggy/naive agents on a single-user host.
Out of scope: deliberately malicious agents with root, side-channel
attacks, sandboxing the user from themselves. See RFC 0008 §1.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence


# ── Platform detection ─────────────────────────────────────────────────────

_HAS_RESOURCE = False
try:
    import resource  # POSIX-only
    _HAS_RESOURCE = True
except ImportError:
    resource = None  # type: ignore[assignment]


# ── Errors ─────────────────────────────────────────────────────────────────


class SandboxPolicyError(ValueError):
    """Raised when SandboxPolicy fields don't pass validation."""


class SandboxNotAvailable(RuntimeError):
    """Raised when a policy requires a tool that isn't installed
    (most commonly: ``use_bubblewrap=True`` without ``/usr/bin/bwrap``)."""


# ── Policy + Result ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SandboxPolicy:
    # ── CPU / memory / IO limits (POSIX setrlimit) ────────────────────
    cpu_seconds:    Optional[int] = None       # RLIMIT_CPU  (soft+hard)
    memory_bytes:   Optional[int] = None       # RLIMIT_AS   (virtual mem)
    fsize_bytes:    Optional[int] = None       # RLIMIT_FSIZE
    nproc:          Optional[int] = None       # RLIMIT_NPROC
    nofile:         Optional[int] = None       # RLIMIT_NOFILE
    core_size:      int = 0                    # RLIMIT_CORE — 0 = no cores

    # ── Wall-clock (parent-side killer thread) ────────────────────────
    wall_seconds:   Optional[float] = None

    # ── Filesystem isolation (bubblewrap, Linux) ──────────────────────
    use_bubblewrap: bool = False
    bind_ro:        tuple = ()                 # absolute paths
    bind_rw:        tuple = ()
    workdir:        Optional[str] = None       # cwd inside sandbox

    # ── Network ───────────────────────────────────────────────────────
    deny_network:   bool = False

    # ── Process group ─────────────────────────────────────────────────
    new_session:    bool = True

    # ── Validation ────────────────────────────────────────────────────

    def __post_init__(self):
        for fld in ("cpu_seconds", "memory_bytes", "fsize_bytes",
                    "nproc", "nofile"):
            v = getattr(self, fld)
            if v is not None and (not isinstance(v, int) or v < 1):
                raise SandboxPolicyError(
                    f"{fld} must be a positive int or None, got {v!r}"
                )
        if self.core_size < 0:
            raise SandboxPolicyError("core_size must be >= 0")
        if self.wall_seconds is not None:
            if not isinstance(self.wall_seconds, (int, float)) or self.wall_seconds <= 0:
                raise SandboxPolicyError(
                    f"wall_seconds must be > 0 or None, got {self.wall_seconds!r}"
                )
        if not isinstance(self.bind_ro, tuple) or not isinstance(self.bind_rw, tuple):
            raise SandboxPolicyError("bind_ro / bind_rw must be tuples")
        for p in self.bind_ro + self.bind_rw:
            if not isinstance(p, str):
                raise SandboxPolicyError(f"bind path must be str, got {type(p).__name__}")
            if not p.startswith("/"):
                raise SandboxPolicyError(f"bind path must be absolute: {p!r}")
        if self.deny_network and not self.use_bubblewrap:
            raise SandboxPolicyError(
                "deny_network=True requires use_bubblewrap=True "
                "(network namespacing requires the bwrap layer)"
            )


@dataclass(frozen=True)
class SandboxResult:
    exit_code:   int
    stdout:      bytes
    stderr:      bytes
    duration_s:  float
    timed_out:   bool          = False
    rlimit_hit:  Optional[str] = None
    killed:      bool          = False


# ── Named profiles ─────────────────────────────────────────────────────────

SANDBOX_OFF = SandboxPolicy()


def _default_profile() -> SandboxPolicy:
    return SandboxPolicy(
        cpu_seconds   = 300,
        memory_bytes  = 2 * 1024**3,
        fsize_bytes   = 1 * 1024**3,
        nofile        = 1024,
        wall_seconds  = 900,
        new_session   = True,
    )


def _strict_profile() -> SandboxPolicy:
    return SandboxPolicy(
        cpu_seconds    = 120,
        memory_bytes   = 512 * 1024**2,
        fsize_bytes    = 64 * 1024**2,
        nproc          = 16,
        nofile         = 256,
        wall_seconds   = 300,
        use_bubblewrap = True,
        deny_network   = True,
        bind_ro        = ("/usr", "/lib", "/lib64", "/etc/resolv.conf"),
        new_session    = True,
    )


# Lazy-construct so importing the module on a platform that hates these
# values still works.
SANDBOX_DEFAULT = _default_profile()
SANDBOX_STRICT  = _strict_profile()


# ── Tool detection ─────────────────────────────────────────────────────────


def detect_isolation_tools() -> dict:
    """Return {'bubblewrap': path-or-None, 'firejail': path-or-None}.

    Used by F-4 to decide whether ``use_bubblewrap=True`` is honourable
    or whether the supervisor must downgrade to RLIMIT-only.
    """
    return {
        "bubblewrap": shutil.which("bwrap"),
        "firejail":   shutil.which("firejail"),
    }


# ── RLIMIT preexec ─────────────────────────────────────────────────────────


# Mapping from policy-field name to (resource-constant-name, applies-to-nproc-flag)
_RLIMIT_FIELDS = (
    ("cpu_seconds",  "RLIMIT_CPU"),
    ("memory_bytes", "RLIMIT_AS"),
    ("fsize_bytes",  "RLIMIT_FSIZE"),
    ("nofile",       "RLIMIT_NOFILE"),
    # nproc handled specially — see below
)


def apply_rlimits_in_child(policy: SandboxPolicy) -> Callable[[], None]:
    """Return a preexec_fn that the parent passes to ``subprocess.Popen``.

    The function runs in the child after fork() but before execve(),
    so the limits affect the spawned program rather than the daemon.

    Limits unavailable on the host platform are silently skipped (e.g.
    ``RLIMIT_NPROC`` on macOS); the kernel sandbox prefers degraded
    enforcement over refusing to start. The single exception is
    ``use_bubblewrap=True`` without bwrap, which raises in the parent
    before this preexec_fn ever runs.
    """
    if not _HAS_RESOURCE:
        # Non-POSIX (Windows). Return a no-op that may still run setsid;
        # but setsid is also POSIX-only, so on Windows we truly do
        # nothing.
        def _noop():
            return None
        return _noop

    # Capture immutable values now; preexec_fn must be callable post-fork
    # without doing anything that could deadlock (e.g. logging via a
    # threaded logger). resource.setrlimit and os.setsid are safe.
    cpu  = policy.cpu_seconds
    mem  = policy.memory_bytes
    fsz  = policy.fsize_bytes
    nofl = policy.nofile
    nprc = policy.nproc
    cor  = policy.core_size
    use_bwrap = policy.use_bubblewrap
    new_session = policy.new_session

    def _apply():
        # Core dumps off (or capped). RLIMIT_CORE always exists on POSIX.
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (cor, cor))
        except (ValueError, OSError):
            pass

        for fld_name, rlim_const in _RLIMIT_FIELDS:
            value = {"cpu_seconds": cpu, "memory_bytes": mem,
                     "fsize_bytes": fsz, "nofile": nofl}[fld_name]
            if value is None:
                continue
            rlim = getattr(resource, rlim_const, None)
            if rlim is None:
                continue
            try:
                resource.setrlimit(rlim, (value, value))
            except (ValueError, OSError):
                # Hard limit may already be lower than the requested
                # soft. Don't fail the child for it; the supervisor will
                # see the rlimit_hit field in SandboxResult if it
                # matters.
                pass

        # nproc is per-uid on Linux without a PID namespace. Only honour
        # it under bubblewrap (where bwrap has unshared the PID NS) so
        # we don't accidentally wedge the parent's other threads.
        if nprc is not None and use_bwrap:
            rlim = getattr(resource, "RLIMIT_NPROC", None)
            if rlim is not None:
                try:
                    resource.setrlimit(rlim, (nprc, nprc))
                except (ValueError, OSError):
                    pass

        if new_session:
            try:
                os.setsid()
            except OSError:
                pass

    return _apply


# ── Bubblewrap argv wrapping ───────────────────────────────────────────────


def _covered_by(path: str, binds: Sequence[str]) -> bool:
    """True if ``path`` already sits under one of ``binds``."""
    for b in binds:
        b = b.rstrip("/") or "/"
        if path == b or path.startswith(b + "/") or b == "/":
            return True
    return False


def interpreter_bind_paths(
    argv: Sequence[str], existing: Sequence[str] = (),
) -> list[str]:
    """Read-only binds needed to exec ``argv[0]`` when it is this Python.

    A venv's ``bin/python`` is a symlink into the base installation
    (``sys.base_prefix``), often living somewhere bwrap was not told about
    (``/tmp/venv`` → ``~/anaconda3``), so bwrap's execvp failed with
    "No such file or directory". When ``argv[0]`` resolves to the running
    interpreter we bind the venv prefix, the base prefix and every hop of
    the symlink chain — both as written and fully resolved, since $HOME may
    itself be a symlink (``/home/x`` → ``/srv/home/x``).

    Never binds ``/`` or a directory containing the user's home (that would
    re-expose ``~/.ssh``); paths already covered by ``existing`` are skipped.
    """
    if not argv:
        return []
    exe = str(argv[0])
    try:
        if os.path.realpath(exe) != os.path.realpath(sys.executable):
            return []
    except OSError:
        return []

    candidates: list[str] = []
    for prefix in (sys.prefix, sys.exec_prefix,
                   getattr(sys, "base_prefix", sys.prefix),
                   getattr(sys, "base_exec_prefix", sys.exec_prefix)):
        if prefix:
            candidates.append(os.path.abspath(prefix))
    # Every hop of the executable's symlink chain needs its directory.
    hop, seen = os.path.abspath(exe), set()
    while hop not in seen:
        seen.add(hop)
        candidates.append(os.path.dirname(hop))
        if not os.path.islink(hop):
            break
        target = os.readlink(hop)
        hop = os.path.normpath(os.path.join(os.path.dirname(hop), target))
    candidates.append(os.path.dirname(os.path.realpath(exe)))

    home = os.path.realpath(os.path.expanduser("~"))
    out: list[str] = []
    for c in candidates:
        for p in (c, os.path.realpath(c)):
            p = p.rstrip("/") or "/"
            if p == "/" or not os.path.exists(p):
                continue
            rp = os.path.realpath(p)
            if rp == home or home.startswith(rp.rstrip("/") + "/"):
                continue
            if p in out or _covered_by(p, tuple(existing) + tuple(out)):
                continue
            out.append(p)
    return out


def wrap_with_bubblewrap(
    argv: Sequence[str], policy: SandboxPolicy,
) -> list[str]:
    """Return the bwrap-prefixed argv list. Raises if bwrap is missing."""
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxNotAvailable(
            "policy.use_bubblewrap=True but /usr/bin/bwrap is not installed"
        )
    cmd: list[str] = [
        bwrap,
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--die-with-parent",
        "--new-session",
    ]
    if policy.deny_network:
        cmd.append("--unshare-net")
    for path in policy.bind_ro:
        cmd.extend(["--ro-bind", path, path])
    for path in policy.bind_rw:
        cmd.extend(["--bind", path, path])
    for path in interpreter_bind_paths(argv, policy.bind_ro + policy.bind_rw):
        cmd.extend(["--ro-bind", path, path])
    if policy.workdir:
        cmd.extend(["--chdir", policy.workdir])
    cmd.append("--")
    cmd.extend(argv)
    return cmd


# ── Shell sandbox (Bash tool) ──────────────────────────────────────────────
#
# A whole-host view for an interactive shell: everything is readable (so
# compilers, interpreters and the user's toolchain keep working), nothing is
# writable except the workspace (``workspace-write``) or nothing at all
# (``read-only``), /tmp is a private tmpfs, credential stores are masked,
# and the network is unshared unless asked for.

SHELL_SANDBOX_MODES = ("off", "workspace-write", "read-only")

# Masked inside the shell sandbox. Directories become an empty tmpfs, files
# are replaced by /dev/null.
_SHELL_HIDDEN_DIRS = (".ssh", ".aws", ".gnupg", ".kube", ".docker",
                      ".config/gcloud", ".azure", ".cheetahclaws")
_SHELL_HIDDEN_FILES = (".netrc", ".pgpass", ".git-credentials", ".npmrc",
                       ".pypirc")


def _shell_hidden_paths() -> tuple[list[str], list[str]]:
    # Resolved: bwrap cannot mount onto a path whose parent is a symlink
    # (/home → /srv/home), and sandbox-exec matches real paths only.
    home = os.path.realpath(os.path.expanduser("~"))
    dirs = [os.path.realpath(os.path.join(home, d)) for d in _SHELL_HIDDEN_DIRS]
    files = [os.path.realpath(os.path.join(home, f)) for f in _SHELL_HIDDEN_FILES]
    return ([d for d in dirs if os.path.isdir(d)],
            [f for f in files if os.path.isfile(f)])


def _bubblewrap_shell_argv(argv, mode, workspace, network, writable):
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxNotAvailable(
            "bash_sandbox requires bubblewrap (`bwrap`), which is not "
            "installed. Install it (e.g. `apt install bubblewrap`) or set "
            "/config bash_sandbox=off."
        )
    cmd = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
           "--tmpfs", "/tmp", "--unshare-pid", "--unshare-ipc",
           "--die-with-parent", "--new-session"]
    if not network:
        cmd.append("--unshare-net")
    hidden_dirs, hidden_files = _shell_hidden_paths()
    for d in hidden_dirs:
        cmd.extend(["--tmpfs", d])
    for f in hidden_files:
        cmd.extend(["--ro-bind", "/dev/null", f])
    rw = list(writable)
    if mode == "workspace-write" and workspace:
        rw.insert(0, workspace)
    elif workspace and os.path.exists(workspace):
        # Re-expose a workspace that sits under the private /tmp or a
        # masked directory; read-only in this mode.
        cmd.extend(["--ro-bind", workspace, workspace])
    for p in rw:
        if p and os.path.exists(p):
            cmd.extend(["--bind", p, p])
    if workspace and os.path.isdir(workspace):
        cmd.extend(["--chdir", workspace])
    cmd.append("--")
    cmd.extend(argv)
    return cmd


def _sb_quote(path: str) -> str:
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _seatbelt_shell_argv(argv, mode, workspace, network, writable):
    exe = shutil.which("sandbox-exec") or (
        "/usr/bin/sandbox-exec" if os.path.exists("/usr/bin/sandbox-exec") else None)
    if not exe:
        raise SandboxNotAvailable(
            "bash_sandbox requires /usr/bin/sandbox-exec on macOS; set "
            "/config bash_sandbox=off to run unsandboxed."
        )
    rules = ["(version 1)", "(allow default)", "(deny file-write*)"]
    allow = ["/private/tmp", "/private/var/folders", "/dev"]
    if mode == "workspace-write" and workspace:
        allow.append(workspace)
    allow.extend(p for p in writable if p)
    rules.append("(allow file-write* " + " ".join(
        f"(subpath {_sb_quote(os.path.realpath(p))})" for p in allow) + ")")
    hidden_dirs, hidden_files = _shell_hidden_paths()
    for d in hidden_dirs:
        rules.append(f"(deny file-read* (subpath {_sb_quote(os.path.realpath(d))}))")
    for f in hidden_files:
        rules.append(f"(deny file-read* (literal {_sb_quote(os.path.realpath(f))}))")
    if not network:
        rules.append("(deny network*)")
    return [exe, "-p", "\n".join(rules), *argv]


def shell_sandbox_argv(
    argv: Sequence[str],
    mode: str,
    *,
    workspace: Optional[str] = None,
    network: bool = False,
    writable: Sequence[str] = (),
) -> list[str]:
    """Wrap a shell ``argv`` for the Bash tool's opt-in sandbox.

    ``mode`` is one of :data:`SHELL_SANDBOX_MODES`; ``"off"`` returns
    ``argv`` unchanged. Linux uses bubblewrap, macOS uses ``sandbox-exec``.
    Raises :class:`SandboxNotAvailable` when the mode is on but the platform
    has no supported backend — the caller must fail closed rather than run
    the command unsandboxed.
    """
    if mode not in SHELL_SANDBOX_MODES:
        raise SandboxPolicyError(
            f"bash_sandbox must be one of {SHELL_SANDBOX_MODES}, got {mode!r}"
        )
    argv = list(argv)
    if mode == "off":
        return argv
    workspace = os.path.realpath(workspace) if workspace else None
    writable = [os.path.realpath(p) for p in writable if isinstance(p, str) and p]
    if sys.platform.startswith("linux"):
        return _bubblewrap_shell_argv(argv, mode, workspace, network, writable)
    if sys.platform == "darwin":
        return _seatbelt_shell_argv(argv, mode, workspace, network, writable)
    raise SandboxNotAvailable(
        f"bash_sandbox is not supported on {sys.platform}; set "
        "/config bash_sandbox=off to run unsandboxed."
    )


# ── One-shot runner ────────────────────────────────────────────────────────


@dataclass
class _RunControl:
    """Mutable state shared with the wall-clock killer thread."""
    finished: bool = False
    timed_out: bool = False
    killed: bool = False


def _wall_clock_killer(
    proc: subprocess.Popen, deadline: float, ctl: _RunControl,
) -> None:
    """Daemon thread: kill the process group when wall_seconds elapses."""
    while not ctl.finished:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            ctl.timed_out = True
            ctl.killed = True
            _kill_process_group(proc)
            return
        time.sleep(min(0.25, remaining))


def _kill_process_group(proc: subprocess.Popen) -> None:
    """SIGTERM the process group, then SIGKILL after a grace period."""
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, OSError):
        pgid = None
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        # Brief grace, then forceful.
        try:
            proc.wait(timeout=1.0)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
    else:
        # No pgid (Windows or new_session=False) — fall back to direct
        # process kill.
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass


def _classify_rlimit_hit(returncode: int, policy: SandboxPolicy) -> Optional[str]:
    """Best-effort classification of which RLIMIT killed the child.

    Linux signals:
      SIGXCPU (-24)  — RLIMIT_CPU
      SIGXFSZ (-25)  — RLIMIT_FSIZE
      SIGSEGV / -9   — often RLIMIT_AS (malloc returns NULL → SEGV) or wall-kill

    Best-effort: we report 'cpu' / 'fsize' / 'memory' when we can, else
    None. The supervisor logs the rlimit_hit alongside exit_code so the
    operator can interpret ambiguous cases.
    """
    if returncode == -getattr(signal, "SIGXCPU", 0xff):
        return "cpu"
    if returncode == -getattr(signal, "SIGXFSZ", 0xff):
        return "fsize"
    # If we set RLIMIT_AS and the process died via SIGKILL/SIGSEGV with
    # AS set, attribute it best-effort.
    if returncode in (-signal.SIGKILL, -signal.SIGSEGV) and policy.memory_bytes is not None:
        return "memory"
    return None


def run_sandboxed(
    argv: Sequence[str],
    policy: SandboxPolicy,
    *,
    stdin: Optional[bytes] = None,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[str] = None,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
) -> SandboxResult:
    """Spawn ``argv`` under ``policy``, wait, return a SandboxResult.

    Convenience wrapper around the lower-level building blocks. The
    F-4 supervisor will use ``apply_rlimits_in_child`` /
    ``wrap_with_bubblewrap`` directly so it can manage the long-running
    Popen itself and stream output back to the daemon. This helper
    exists for tests and for short-lived tools the kernel might run
    inline.
    """
    if not isinstance(policy, SandboxPolicy):
        raise SandboxPolicyError(
            f"policy must be SandboxPolicy, got {type(policy).__name__}"
        )

    # Validate bind paths exist before we fork — easier to surface a
    # decent error.
    for p in policy.bind_ro + policy.bind_rw:
        if not Path(p).exists():
            raise SandboxPolicyError(f"bind path does not exist: {p!r}")

    # Wrap argv with bubblewrap if requested.
    if policy.use_bubblewrap:
        full_argv = wrap_with_bubblewrap(list(argv), policy)
    else:
        full_argv = list(argv)

    preexec = apply_rlimits_in_child(policy) if not policy.use_bubblewrap else None
    # When bwrap is the entrypoint, the rlimits applied in the bwrap
    # process don't transfer to the eventual child (bwrap re-execs into
    # its own process tree). bwrap doesn't expose a `--rlimit` flag yet,
    # so under bubblewrap, RLIMIT enforcement is best-effort and we rely
    # on namespace-level isolation (PID/IPC/net) plus wall_seconds for
    # CPU. Documented in RFC 0008 §3.1.
    # If bubblewrap is on AND rlimits are also requested, we still try
    # the preexec — bwrap honours inherited rlimits for itself, and on
    # most distros it execs into the user argv in a way that preserves
    # them.
    if policy.use_bubblewrap:
        preexec = apply_rlimits_in_child(policy)

    ctl = _RunControl()
    start = time.monotonic()
    proc = subprocess.Popen(
        full_argv,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
        env=dict(env) if env is not None else None,
        cwd=cwd,
        preexec_fn=preexec,
        # Note: we deliberately don't pass start_new_session here —
        # apply_rlimits_in_child() calls os.setsid() for us. Doing both
        # would be redundant; doing only the kwarg would skip our
        # explicit logging hook.
    )

    killer_thread: Optional[threading.Thread] = None
    if policy.wall_seconds is not None:
        deadline = time.monotonic() + policy.wall_seconds
        killer_thread = threading.Thread(
            target=_wall_clock_killer,
            args=(proc, deadline, ctl),
            daemon=True,
            name="sandbox-wall-killer",
        )
        killer_thread.start()

    try:
        out, err = proc.communicate(input=stdin)
    finally:
        ctl.finished = True
        if killer_thread is not None:
            killer_thread.join(timeout=2.0)

    duration = time.monotonic() - start
    rlimit_hit = _classify_rlimit_hit(proc.returncode, policy)

    return SandboxResult(
        exit_code  = proc.returncode,
        stdout     = out or b"",
        stderr     = err or b"",
        duration_s = duration,
        timed_out  = ctl.timed_out,
        rlimit_hit = rlimit_hit,
        killed     = ctl.killed or proc.returncode < 0,
    )
