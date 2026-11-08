"""tools_security.py — Path-traversal guard and bash safety check."""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

# ── Read-only shell vocabulary ────────────────────────────────────────────
#
# A command is auto-approved (no permission prompt) only when *every* segment
# of the pipeline is a known read-only invocation.  The classification is by
# parsed program name — not a string prefix — so `lsof` can never satisfy an
# `ls` rule and `rm` can never hide behind a leading `echo`.
#
# Three ways a segment can qualify:
#   1. the program is in _READ_ONLY_COMMANDS (plus its per-command flag guard)
#   2. the program is in _READ_ONLY_SUBCOMMANDS and its subcommand is listed
#   3. the invocation is nothing but an info flag (`--version`, `--help`)
#
# Anything else prompts.  Deliberately NOT here: interpreters (python, node,
# ruby, perl, sh), build/test runners (make, pytest, npm run), and anything
# that takes a user-supplied program to run (xargs, env VAR=…, timeout).
# Those execute arbitrary code, which is exactly what the prompt is for.
#
# Also NOT here: network clients (curl, wget, …).  A request reaches outside
# the session, and any `$VAR` in its URL or headers ships the environment —
# API keys included — to whoever runs the server.  `curl -I` used to be on
# the list; add it back with ``bash_safe_extra: ["curl"]`` (its header-only
# flag guard below still applies, and `$` expansions are still refused).

_READ_ONLY_COMMANDS = frozenset({
    # filesystem inspection
    "ls", "ll", "pwd", "stat", "file", "tree", "realpath", "readlink",
    "basename", "dirname", "du", "df", "mountpoint",
    # file contents
    "cat", "head", "tail", "nl", "wc", "od", "xxd", "strings", "base64",
    "md5sum", "sha1sum", "sha256sum", "sha512sum", "cksum",
    "diff", "cmp", "comm",
    # text processing (pipeline members)
    "sort", "uniq", "cut", "tr", "rev", "fold", "paste", "join", "column",
    "jq", "yq", "sed", "grep", "egrep", "fgrep", "rg", "ag", "fd", "find",
    # environment / system introspection
    "echo", "printf", "date", "cal", "uptime", "hostname", "uname",
    "whoami", "id", "groups", "which", "type", "command", "env", "printenv",
    "locale", "nproc", "arch", "lscpu", "lsblk", "free", "ps", "top",
    "netstat", "ss", "lsof", "ulimit", "tty",
    # archives — listing only (see _COMMAND_FLAG_GUARDS)
    "tar", "unzip", "zipinfo", "gunzip", "zcat",
})

# Directories whose binaries are "the" program of that name.
_SYSTEM_BIN_DIRS = frozenset({
    "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin",
    "/usr/local/sbin", "/opt/homebrew/bin",
})

# Programs that talk to the network.  Never auto-approved by default; when a
# user opts one in via ``bash_safe_extra``, an invocation that expands a shell
# parameter (`$API_KEY`, `${HOME}`) is still refused — that is the shape of an
# environment exfiltration, not of an inspection.
_NETWORK_PROGRAMS = frozenset({
    "curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ftp",
    "ssh", "scp", "sftp", "rsync", "http", "https", "xh", "aria2c",
    "dig", "nslookup", "host", "ping", "ping6", "traceroute", "whois",
})

# program → subcommands that only read state.
_READ_ONLY_SUBCOMMANDS = {
    "git": frozenset({
        "log", "status", "diff", "show", "branch", "remote", "tag", "blame",
        "describe", "rev-parse", "rev-list", "ls-files", "ls-tree", "ls-remote",
        "cat-file", "shortlog", "whatchanged", "reflog", "count-objects",
        "grep", "annotate", "verify-commit", "check-ignore",
        "config", "stash", "worktree", "submodule", "bisect", "notes",
        # NOT difftool: it launches the configured external diff program.
    }),
    "docker":  frozenset({"ps", "images", "image", "logs", "inspect", "version",
                          "info", "top", "stats", "port", "diff", "history"}),
    "podman":  frozenset({"ps", "images", "logs", "inspect", "version", "info"}),
    "kubectl": frozenset({"get", "describe", "logs", "top", "version",
                          "explain", "api-resources", "api-versions",
                          "cluster-info"}),
    "npm":     frozenset({"ls", "list", "view", "info", "outdated", "why", "ping"}),
    "pnpm":    frozenset({"ls", "list", "outdated", "why"}),
    "yarn":    frozenset({"list", "info", "why", "outdated"}),
    "pip":     frozenset({"show", "list", "freeze", "check"}),
    "pip3":    frozenset({"show", "list", "freeze", "check"}),
    "uv":      frozenset({"tree", "version"}),
    "cargo":   frozenset({"metadata", "tree", "search", "verify-project"}),
    "go":      frozenset({"list", "env", "version", "doc"}),
    "brew":    frozenset({"list", "info", "outdated", "config", "--version"}),
    "systemctl": frozenset({"status", "list-units", "list-unit-files", "show",
                            "is-active", "is-enabled", "cat"}),
    "poetry":  frozenset({"show", "check", "env"}),
    "conda":   frozenset({"list", "info", "env"}),
}

# Global flags (before the subcommand) that take a separate value argument —
# `git -C /repo status` is still `git status`.
_GLOBAL_VALUE_FLAGS = {
    "git":     {"-C", "--namespace", "--work-tree"},
    "kubectl": {"-n", "--namespace", "--context", "--cluster", "--user", "-s",
                "--server"},
    "docker":  {"--context", "-H", "--host", "-l", "--log-level"},
}

# Global flags that hand the program a command to run or a config that can
# name one.  `git -c core.fsmonitor=CMD status` runs CMD; so does a kubeconfig
# with an `exec` credential plugin, or a --git-dir pointing at a config the
# agent wrote itself.
_GLOBAL_BANNED_FLAGS = {
    "git":     {"-c", "--config-env", "--git-dir", "--exec-path", "--super-prefix"},
    "kubectl": {"--kubeconfig"},
    "docker":  {"--config"},
}

# Flags banned anywhere in a git invocation: they write a file or launch an
# external program (diff driver, textconv filter, pager, remote helper).
_GIT_BANNED_ANYWHERE = {"--output", "--ext-diff", "--textconv", "--filters",
                        "--open-files-in-pager", "--upload-pack", "--exec",
                        "--receive-pack"}


def _flag_name(a: str) -> str:
    return a.split("=", 1)[0]


def _flag_in(a: str, banned) -> bool:
    """True if ``a`` names a flag in ``banned``, counting GNU/git long-option
    abbreviations: getopt_long and git's parse-options accept any unique
    prefix, so `--upload-pa` *is* `--upload-pack` and `--checkpoint-act` *is*
    `--checkpoint-action`.  Matching a prefix of a banned name errs safe."""
    name = _flag_name(a)
    if name in banned:
        return True
    return (name.startswith("--") and len(name) > 2
            and any(b.startswith("--") and b.startswith(name) for b in banned))


def _short_cluster(a: str) -> str:
    """'-tvf' → 'tvf'; '' for long flags and non-flags."""
    if a.startswith("-") and not a.startswith("--") and len(a) > 1:
        return a[1:]
    return ""


def _positionals(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def _git_listing_guard(write_flags: set[str], ok_letters: str,
                       list_flags: set[str]):
    """`git branch` / `git tag` list when given only filter flags, but create,
    rename or delete when given a name or a write flag."""
    def guard(args: list[str]) -> bool:
        listing = False
        for a in args:
            name = _flag_name(a)
            if _flag_in(a, write_flags):
                return False
            cluster = _short_cluster(a)
            if cluster and not a.startswith("--"):
                if any(ch not in ok_letters for ch in cluster):
                    return False
                if "l" in cluster:
                    listing = True
            if name in list_flags:
                listing = True
        return listing or not _positionals(args)
    return guard


# Subcommands that are read-only only with the right flag.
_SUBCOMMAND_FLAG_GUARDS = {
    ("git", "config"):    lambda args: any(a in ("--get", "--get-all", "--list", "-l",
                                                 "--get-regexp") for a in args)
                          and not any(_flag_in(a, (
                              "--add", "--unset", "--unset-all", "--replace-all",
                              "--rename-section", "--remove-section", "-e",
                              "--edit", "--file", "--blob")) for a in args),
    ("git", "stash"):     lambda args: bool(args) and args[0] in ("list", "show"),
    ("git", "worktree"):  lambda args: bool(args) and args[0] == "list",
    ("git", "submodule"): lambda args: bool(args) and args[0] in ("status", "summary"),
    ("git", "bisect"):    lambda args: bool(args) and args[0] in ("log", "view"),
    ("git", "notes"):     lambda args: bool(args) and args[0] in ("list", "show"),
    # Flags may come before the subcommand (`git remote -v add …`), so judge
    # the first positional, not the first argument.
    ("git", "remote"):    lambda args: (_positionals(args)[:1] or ["show"])[0]
                          in ("show", "get-url"),
    ("git", "reflog"):    lambda args: not any(p in ("expire", "delete", "drop")
                                               for p in _positionals(args)),
    ("git", "branch"):    _git_listing_guard(
        {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy",
         "-f", "--force", "-u", "--set-upstream-to", "--unset-upstream",
         "--edit-description", "-t", "--track", "--no-track", "--create-reflog"},
        "arvlq",
        {"--list", "--contains", "--no-contains", "--merged", "--no-merged",
         "--points-at", "--show-current"}),
    ("git", "tag"):       _git_listing_guard(
        {"-d", "--delete", "-a", "--annotate", "-s", "--sign", "-u",
         "--local-user", "-f", "--force", "-m", "--message", "-F", "--file",
         "-e", "--edit", "--create-reflog"},
        "ln0123456789",
        {"--list", "--contains", "--no-contains", "--merged", "--no-merged",
         "--points-at"}),
    ("git", "grep"):      lambda args: not any(a.startswith("-O") for a in args),
    ("git", "ls-remote"): lambda args: not any(a == "-u" or "::" in a for a in args),
    ("docker", "image"):  lambda args: bool(args) and args[0] in ("ls", "list",
                                                                  "inspect", "history"),
    ("conda", "env"):     lambda args: bool(args) and args[0] == "list",
    ("poetry", "env"):    lambda args: bool(args) and args[0] in ("info", "list"),
    ("go", "env"):        lambda args: not any(a in ("-w", "-u") for a in args),
    ("go", "list"):       lambda args: not any(_flag_name(a) in ("-toolexec", "-exec",
                                                                 "--toolexec", "--exec")
                                               for a in args),
}

# Flags that turn an otherwise read-only command into a mutating one.
def _guard_find(args: list[str]) -> bool:
    banned = {"-delete", "-exec", "-execdir", "-ok", "-okdir",
              "-fprint", "-fprint0", "-fprintf", "-fls"}
    return not any(a in banned for a in args)


def _guard_no_flags(banned: set[str]):
    return lambda args: not any(_flag_in(a, banned) for a in args)


def _guard_no_flag_prefix(*prefixes: str):
    return lambda args: not any(a.startswith(p) for a in args for p in prefixes)


def _sed_script_is_safe(script: str) -> bool:
    """True if a sed script only prints, deletes, substitutes and branches.

    GNU sed can run commands (`e`, the `e` flag of `s///`) and write files
    (`w`, `W`, the `w` flag of `s///`).  Everything else a script can do only
    shapes stdout.  Unknown syntax is treated as unsafe.
    """
    s, i, n = script, 0, len(script)

    def skip_delimited(j: int, delim: str) -> int:
        """Return the index just past the next unescaped ``delim``."""
        while j < n:
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == delim:
                return j + 1
            j += 1
        return -1

    while i < n:
        c = s[i]
        if c in " \t\n;{}!,0123456789$+~":
            i += 1
            continue
        if c == "#":                       # comment to end of line
            nl = s.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c in "/\\":                     # regex address: /re/ or \%re%
            if c == "\\":
                if i + 1 >= n:
                    return False
                delim, i = s[i + 1], i + 2
            else:
                delim, i = "/", i + 1
            i = skip_delimited(i, delim)
            if i < 0:
                return False
            while i < n and s[i] in "IM":
                i += 1
            continue
        if c in "sy":
            if i + 1 >= n or s[i + 1] in "\n\\":
                return False
            delim = s[i + 1]
            i = skip_delimited(i + 2, delim)          # pattern
            if i < 0:
                return False
            i = skip_delimited(i, delim)              # replacement
            if i < 0:
                return False
            if c == "s":
                flags_start = i
                while i < n and (s[i].isalnum() or s[i] in "&"):
                    i += 1
                if any(f in s[flags_start:i] for f in "ewW"):
                    return False
            continue
        if c in "ewW":                     # execute / write
            return False
        if c in "rR":                      # read a file into the output
            nl = s.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c in "aic":                     # text to end of line
            nl = s.find("\n", i)
            i = n if nl < 0 else nl + 1
            continue
        if c in "btT:":                    # labels run to ; or newline
            i += 1
            while i < n and s[i] not in ";\n":
                i += 1
            continue
        if c in "qQlL":                    # optional numeric argument
            i += 1
            continue
        if c in "pPdDnNgGhHxz=F":
            i += 1
            continue
        return False
    return True


# GNU sed's long options; an abbreviation resolves to the unique match.
_SED_LONG = ("--expression", "--file", "--in-place", "--separate",
             "--line-length", "--quiet", "--silent", "--regexp-extended",
             "--null-data", "--zero-terminated", "--posix", "--debug",
             "--sandbox", "--unbuffered", "--follow-symlinks", "--binary",
             "--version", "--help")


def _sed_long_name(a: str) -> str:
    """Full option name for ``a`` ('' if unknown or ambiguous)."""
    name = _flag_name(a)
    if name in _SED_LONG:
        return name
    hits = [o for o in _SED_LONG if o.startswith(name)]
    return hits[0] if len(hits) == 1 else ""


def _guard_sed(args: list[str]) -> bool:
    scripts: list[str] = []
    positional: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        name = _sed_long_name(a) if a.startswith("--") and a != "--" else _flag_name(a)
        if a.startswith("--") and a != "--" and not name:
            return False                   # unknown / ambiguous long option
        if name in ("--in-place", "--file", "--separate"):
            return False
        if name == "--expression":
            if "=" in a:
                scripts.append(a.split("=", 1)[1])
            elif i + 1 < len(args):
                scripts.append(args[i + 1])
                i += 1
            else:
                return False
        elif name in ("--line-length",) and "=" not in a:
            i += 1
        elif a.startswith("--"):
            pass
        elif a.startswith("-") and len(a) > 1:
            cluster = a[1:]
            for k, ch in enumerate(cluster):
                if ch in "isf":
                    return False           # in-place / separate / script file
                if ch in "el":
                    rest = cluster[k + 1:]
                    value = rest if rest else (args[i + 1] if i + 1 < len(args) else None)
                    if value is None:
                        return False
                    if not rest:
                        i += 1
                    if ch == "e":
                        scripts.append(value)
                    break
        else:
            positional.append(a)
        i += 1
    if not scripts:
        if not positional:
            return True                    # `sed --version`-ish; nothing runs
        scripts.append(positional[0])
    return all(_sed_script_is_safe(sc) for sc in scripts)


def _guard_tar(args: list[str]) -> bool:
    listing = False
    for a in args:
        name = _flag_name(a)
        if a.startswith("--"):
            if _flag_in(a, ("--list",)):
                listing = True
            if _flag_in(a, ("--extract", "--get", "--create", "--append", "--update",
                            "--delete", "--concatenate", "--catenate",
                            "--to-command", "--checkpoint-action",
                            "--use-compress-program", "--info-script",
                            "--new-volume-script", "--rsh-command", "--rmt-command",
                            "--index-file", "--file-list", "--files-from",
                            "--remove-files", "--overwrite")):
                return False
            continue
        cluster = _short_cluster(a)
        if cluster:
            if "t" in cluster:
                listing = True
            if any(ch in cluster for ch in "xcruAIF"):
                return False
    return listing


def _guard_curl(args: list[str]) -> bool:
    """Header-only requests to an http(s) URL, nothing written, nothing sent.
    Only consulted when the user opts curl in via ``bash_safe_extra``."""
    allowed = {"-I", "--head", "-s", "--silent", "-S", "--show-error", "-L",
               "--location", "-k", "--insecure", "-v", "--verbose", "-i",
               "--include", "-f", "--fail"}
    with_value = {"-m", "--max-time", "--connect-timeout", "--retry",
                  "-A", "--user-agent"}
    head = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-I", "--head"):
            head = True
        if a in allowed:
            pass
        elif _flag_name(a) in with_value:
            if "=" not in a:
                i += 1
        elif _short_cluster(a) and all(ch in "IsSLkvif" for ch in a[1:]):
            head = head or "I" in a
        elif a.startswith("-"):
            return False
        elif not a.startswith(("http://", "https://")):
            return False
        i += 1
    return head


def _guard_max_positionals(n: int):
    return lambda args: len(_positionals(args)) <= n


_COMMAND_FLAG_GUARDS = {
    "find":  _guard_find,
    "fd":    _guard_no_flag_prefix("-x", "--exec", "-X"),
    "sed":   _guard_sed,
    "sort":  lambda args: _guard_no_flags({"-o", "--output", "--compress-program"})(args)
             and not any(_short_cluster(a) and "o" in a for a in args),
    "rg":    _guard_no_flag_prefix("--pre", "--hostname-bin"),
    "ag":    _guard_no_flag_prefix("--pager"),
    "tree":  _guard_no_flags({"-o"}),
    "file":  _guard_no_flags({"-C", "--compile"}),
    "yq":    lambda args: _guard_no_flags({"--inplace"})(args)
             and not any(_short_cluster(a) and "i" in a for a in args),
    # `uniq in out` / `xxd in out` write their second operand
    "uniq":  _guard_max_positionals(1),
    "xxd":   _guard_max_positionals(1),
    "date":  lambda args: not any(_flag_name(a) == "--set" or
                                  (_short_cluster(a) and "s" in a) for a in args),
    "hostname": lambda args: not _positionals(args)
             and not any(_flag_name(a) in ("-F", "--file", "-b", "--boot") for a in args),
    # archives: listing only
    "tar":   _guard_tar,
    "unzip": lambda args: any(a in ("-l", "-v", "-t") for a in args),
    "gunzip": lambda args: any(_flag_name(a) in ("--stdout", "--to-stdout", "--list",
                                                 "--test")
                               or (_short_cluster(a) and any(ch in a for ch in "clt"))
                               for a in args),
    # network: header-only requests, never a body fetch or an -o download
    "curl":  _guard_curl,
    # `top` must be in batch mode or it never exits
    "top":   lambda args: any(a.startswith("-b") for a in args),
    # `env` alone prints the environment; `env FOO=1 cmd` runs a command
    "env":   lambda args: not args,
    "command": lambda args: bool(args) and args[0] in ("-v", "-V"),
    "type":  lambda args: True,
}

# Never auto-approved, even as a pipeline member: these run whatever they are
# handed, so no argument inspection makes them safe.
_NEVER_SAFE = frozenset({
    "sudo", "doas", "su", "sh", "bash", "zsh", "fish", "dash", "ksh",
    "eval", "exec", "source", ".", "xargs", "nohup", "setsid", "timeout",
    "watch", "nice", "ionice", "strace", "ltrace", "gdb", "awk", "gawk",
    "mawk", "perl", "python", "python3", "ruby", "node", "php", "tee",
    "ssh", "scp", "rsync", "make", "cmake", "ninja", "npx", "pipx",
})

# An invocation that is nothing but one of these is always safe, whatever the
# program — `python --version` tells you a version, it does not run your code.
# Long forms only, plus `-V`: the single-letter short flags are too ambiguous
# to trust across unknown programs (`-v` is verbose for most commands, and
# `shutdown -h` halts the machine rather than printing help).
_INFO_ONLY_FLAGS = frozenset({"--version", "-V", "--help", "--usage",
                              "version", "help"})

# Structures that can smuggle a second command past segment parsing.
_UNSAFE_SUBSTRINGS = ("`", "$(", "<(", ">(", "${!")

# A `#` that starts a word begins a comment.  shlex would swallow the newline
# that ends it — and the command on the next line — into the current segment,
# so a command with a comment-like `#` is never classified at all.
_COMMENT_RE = re.compile(r"(?:^|[\s;&|()])#")

# Shell operators that separate one command from the next.
_SEGMENT_SEPARATORS = {"|", "||", "&&", ";", "\n", "|&"}

# Redirections.  Output redirection is harmless only into /dev/null or onto
# another descriptor (`2>&1`); anything else writes a file.
_OUTPUT_REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&", "<>"}
_INPUT_REDIRECTS = {"<", "<<<", "<&"}
_HEREDOC_OPS = {"<<", "<<-"}

_PUNCT = "();<>|&\n"


def _strip_heredocs(cmd: str) -> str | None:
    """Remove here-document bodies, which are data, not commands.

    Quote-aware: a `<<` inside quotes is not a heredoc.  Returns None when a
    body would be expanded by the shell (unquoted delimiter) and contains a
    command substitution — that body *runs* code.
    """
    out: list[str] = []
    i, n = 0, len(cmd)
    quote = ""
    pending: list[tuple[str, bool]] = []     # (delimiter, quoted)
    while i < n:
        c = cmd[i]
        if quote:
            out.append(c)
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            out.append(cmd[i:i + 2])
            i += 2
            continue
        if c in "'\"":
            quote = c
            out.append(c)
            i += 1
            continue
        if cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            j = i + 2
            if j < n and cmd[j] == "-":
                j += 1
            while j < n and cmd[j] in " \t":
                j += 1
            m = re.match(r"""(['"]?)([A-Za-z0-9_.\-]+)\1""", cmd[j:])
            if not m:
                return None
            pending.append((m.group(2), bool(m.group(1))))
            out.append(cmd[i:j + m.end()])
            i = j + m.end()
            continue
        if c == "\n" and pending:
            out.append(c)
            i += 1
            for delim, quoted in pending:
                body_lines = []
                while True:
                    if i >= n:
                        return None              # unterminated heredoc
                    nl = cmd.find("\n", i)
                    line = cmd[i:] if nl < 0 else cmd[i:nl]
                    i = n if nl < 0 else nl + 1
                    if line.strip("\t") == delim:
                        break
                    body_lines.append(line)
                body = "\n".join(body_lines)
                if not quoted and ("$(" in body or "`" in body):
                    return None
            pending = []
            continue
        out.append(c)
        i += 1
    if pending:
        return None
    return "".join(out)


def _tokenize(cmd: str) -> list[str] | None:
    """shlex-tokenize a command line, keeping newlines as separators."""
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=_PUNCT)
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        raw = list(lexer)
    except ValueError:
        return None   # unbalanced quotes — don't guess
    out: list[str] = []
    for tok in raw:
        if "\n" in tok and tok and all(ch in _PUNCT for ch in tok):
            # shlex glues runs of punctuation: ";\n", "&&\n", "\n\n".
            stripped = tok.replace("\n", "")
            if stripped:
                out.append(stripped)
            out.append("\n")
        else:
            out.append(tok)
    return out


def split_command_segments(cmd: str, *, allow_background: bool = False
                           ) -> list[list[str]] | None:
    """Split a shell command line into its simple-command segments.

    Returns a list of token lists — one per command joined by `|`, `||`,
    `&&`, `;`, `|&` or a newline — or None when the line contains anything
    that cannot be analysed segment by segment: command or process
    substitution, a subshell, output redirection into a file, an unterminated
    heredoc, a comment, unbalanced quotes, or (unless ``allow_background``)
    a backgrounding `&`.

    Shared by the read-only classifier and the permission-grant matcher so the
    two can never disagree on where one command ends and the next begins.
    """
    c = (cmd or "").strip()
    if not c:
        return None
    c = _strip_heredocs(c)     # a quoted heredoc body is data, `$(` and all
    if c is None or _COMMENT_RE.search(c):
        return None
    if any(s in c for s in _UNSAFE_SUBSTRINGS):
        return None
    tokens = _tokenize(c)
    if not tokens:
        return None

    segments: list[list[str]] = []
    segment: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        is_op = all(ch in _PUNCT for ch in tok)
        if not is_op:
            segment.append(tok)
            i += 1
            continue
        if tok in _SEGMENT_SEPARATORS or (tok == "&" and allow_background):
            if segment or tok != "\n":     # blank lines are not commands
                segments.append(segment)
            segment = []
            i += 1
            continue
        if tok in _OUTPUT_REDIRECTS:
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            fd_dup = tok in (">&", "<&") and (target.isdigit() or target == "-")
            if target != "/dev/null" and not fd_dup:
                return None
            # `2>/dev/null` lexes as "2", ">", "/dev/null": drop the fd number
            if segment and segment[-1].isdigit():
                segment.pop()
            i += 2
            continue
        if tok in _INPUT_REDIRECTS or tok in _HEREDOC_OPS:
            if segment and segment[-1].isdigit():
                segment.pop()
            i += 2     # the file / delimiter is input, not an argument
            continue
        return None    # `&`, `(`, `)`, `;;`, or an operator we don't know
    if segment or not segments or tokens[-1] != "\n":
        segments.append(segment)
    return segments


def _classify_segment(tokens: list[str], extra_safe: frozenset[str]) -> bool:
    """Return True if one pipeline segment is a known read-only invocation."""
    if not tokens:
        return False
    prog_raw = tokens[0]
    # `VAR=value cmd` — an assignment prefix hides the real program.
    if "=" in prog_raw and not prog_raw.startswith("-"):
        return False
    # `/usr/bin/git` is git; `./git` or `/tmp/x/git` is whatever the
    # workspace put there, and only matches a bash_safe_extra entry naming
    # that exact path.
    head, base = os.path.split(os.path.normpath(prog_raw))
    if "/" not in prog_raw or head in _SYSTEM_BIN_DIRS:
        prog = base
    else:
        prog = prog_raw     # a path never equals a bare vocabulary name
    args = tokens[1:]

    if prog in _NEVER_SAFE and prog not in extra_safe:
        # `python --version` and friends stay safe — nothing is executed.
        return bool(args) and all(a in _INFO_ONLY_FLAGS for a in args)

    if args and all(a in _INFO_ONLY_FLAGS for a in args):
        return True

    # A network-capable program expanding a parameter is how an environment
    # variable (an API key) leaves the machine: `curl -I http://x/$TOKEN`.
    if (prog in _NETWORK_PROGRAMS or prog in _READ_ONLY_SUBCOMMANDS) \
            and any("$" in a for a in args):
        return False

    if prog in _READ_ONLY_SUBCOMMANDS:
        # Skip global flags before the subcommand, including the ones that
        # take a value — `git -C /repo status` is still `git status`.
        value_flags = _GLOBAL_VALUE_FLAGS.get(prog, set())
        banned = _GLOBAL_BANNED_FLAGS.get(prog, set())
        sub, sub_idx, skip = "", -1, False
        for idx, a in enumerate(args):
            if skip:
                skip = False
                continue
            if a.startswith("-"):
                if _flag_in(a, banned):
                    return False
                skip = a in value_flags and "=" not in a
                continue
            sub, sub_idx = a, idx
            break
        if sub not in _READ_ONLY_SUBCOMMANDS[prog]:
            return False
        rest = args[sub_idx + 1:]
        if prog == "git" and any(_flag_in(a, _GIT_BANNED_ANYWHERE) for a in rest):
            return False
        if prog == "kubectl" and any(_flag_in(a, banned) for a in rest):
            return False
        guard = _SUBCOMMAND_FLAG_GUARDS.get((prog, sub))
        if guard:
            return bool(guard(rest))
        return True

    if prog in _READ_ONLY_COMMANDS or prog in extra_safe:
        guard = _COMMAND_FLAG_GUARDS.get(prog)
        return bool(guard(args)) if guard else True

    return False


def _extra_safe(config: dict | None) -> frozenset[str]:
    extra = config.get("bash_safe_extra") if config else None
    return frozenset(extra) if isinstance(extra, (list, tuple, set)) else frozenset()


def segment_is_read_only(tokens: list[str], config: dict | None = None) -> bool:
    """Public wrapper around the per-segment read-only classifier."""
    return _classify_segment(tokens, _extra_safe(config))


def _is_safe_bash(cmd: str, config: dict | None = None) -> bool:
    """Return True if cmd is read-only and never needs a permission prompt.

    The command is parsed, split on pipeline/list operators (including
    newlines), and *every* segment must be a known read-only invocation — so
    `git log | head -20` and `ls -la | grep test` auto-run, while
    `ls && rm -rf build` does not.  Output redirection into a file,
    backgrounding, subshells and command substitution are refused outright,
    since they can act (or hide a second command) after a safe-looking
    prefix; `2>&1` and `>/dev/null` are fine.

    ``config['bash_safe_extra']`` may list additional program names to treat
    as read-only (see docs/guides/reference.md).
    """
    segments = split_command_segments(cmd)
    if not segments:
        return False
    extra_safe = _extra_safe(config)
    return all(_classify_segment(seg, extra_safe) for seg in segments)


# Path patterns that hold credentials or system secrets — never accessed by
# default, even when no allowed_root is configured. Set
# CHEETAHCLAWS_FS_NO_SANDBOX=1 to bypass (e.g. when intentionally auditing
# your own secrets).
_HOME = Path.home()
_SECRET_DIRS = (
    _HOME / ".aws",
    _HOME / ".gnupg",
    _HOME / ".kube",
    _HOME / ".docker",
    Path("/root"),
    Path("/etc/sudoers.d"),
)
_SECRET_FILES = (
    _HOME / ".netrc",
    _HOME / ".pgpass",
    Path("/etc/shadow"),
    Path("/etc/gshadow"),
    Path("/etc/sudoers"),
)
_SECRET_SSH_PREFIX = _HOME / ".ssh"
_SECRET_SSH_PUBLIC = {"config", "known_hosts", "known_hosts.old", "authorized_keys"}


def _is_secret_path(resolved: Path) -> bool:
    """Best-effort check: is this path a known credential / secret store?"""
    for d in _SECRET_DIRS:
        try:
            resolved.relative_to(d.resolve(strict=False))
            return True
        except ValueError:
            continue
    for f in _SECRET_FILES:
        try:
            if resolved == f.resolve(strict=False):
                return True
        except OSError:
            continue
    # ~/.ssh: deny everything except the documented public files (config,
    # known_hosts, authorized_keys). Private keys (id_*) are always denied.
    try:
        rel = resolved.relative_to(_SECRET_SSH_PREFIX.resolve(strict=False))
        return rel.name not in _SECRET_SSH_PUBLIC or rel.parent != Path(".")
    except ValueError:
        pass
    return False


def _check_path_allowed(file_path: str, config: dict) -> str | None:
    """Return an error string if file_path is disallowed, else None.

    Two layers of defense:
      1. If config["allowed_root"] / config["_worktree_cwd"] is set, the
         file_path must resolve inside that root.
      2. Independent of (1), a default credential denylist refuses paths
         like ~/.ssh/id_*, ~/.aws/credentials, /etc/shadow, etc.
         Set CHEETAHCLAWS_FS_NO_SANDBOX=1 to disable layer (2).
    """
    try:
        resolved = Path(file_path).resolve()
    except Exception as e:
        return f"Error: path validation failed: {e}"

    allowed_root = config.get("allowed_root") or config.get("_worktree_cwd")
    if allowed_root:
        try:
            root = Path(allowed_root).resolve()
            resolved.relative_to(root)
        except ValueError:
            return (
                f"Error: path '{file_path}' is outside the allowed root '{allowed_root}'. "
                "Set config['allowed_root'] to a broader directory if this is intentional."
            )
        except Exception as e:
            return f"Error: path validation failed: {e}"

    if os.environ.get("CHEETAHCLAWS_FS_NO_SANDBOX", "0") != "1":
        if _is_secret_path(resolved):
            return (
                f"Error: path '{file_path}' is on the credential denylist "
                f"(SSH keys, ~/.aws, ~/.gnupg, /etc/shadow, etc.). "
                f"Set CHEETAHCLAWS_FS_NO_SANDBOX=1 to override."
            )
    return None
