"""System context: CLAUDE.md, git info, cwd injection.

Prompt assembly pipeline:

    build_system_prompt(config) -> str
        = pick_base_prompt(provider, model)      # default.md + matched overlay
        + _render_env_block(config)              # date / cwd / platform / git / CLAUDE.md
        + memory index (if any)
        + tmux fragment (if tmux available)      # prompts/fragments/tmux.md
        + plan mode fragment (if plan active)    # prompts/fragments/plan.md

Base + overlay design lives under ``prompts/`` — see ``prompts/README.md``.
Base/overlay files contain no placeholders and are loaded verbatim.
Dynamic per-run data (date, cwd, CLAUDE.md, plan file path) is rendered
separately and appended.

Callers outside this module should only touch ``build_system_prompt``.
The helper functions (``get_git_info``, ``get_claude_md``,
``get_platform_hints``) are exposed for tests and for REPL commands
that want to show individual context blocks (e.g. ``/doctor``).
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

from cheetahclaws.memory import get_memory_context
from cheetahclaws.prompts import pick_base_prompt, load_fragment


# Short-TTL caches: each turn rebuilds the system prompt, and shelling out to
# git + re-reading CLAUDE.md every turn is a measurable chunk of latency in
# long REPL sessions. Numbers are deliberately conservative.
_GIT_CACHE_TTL = 30.0   # seconds — long enough to span a tool batch
_CLAUDE_MD_TTL = 10.0   # seconds — short so user edits to CLAUDE.md show up quickly

_git_cache: tuple[float, str, str] | None = None   # (expiry, cwd, value)
_claude_md_cache: tuple[float, str, str] | None = None
_cache_lock = threading.Lock()

# ── Prompt injection detection ───────────────────────────────────────────
_THREAT_PATTERNS = [
    re.compile(r'ignore\s+(previous|all|above|prior)(\s+\w+)*\s+(instructions?|prompts?|rules?)', re.I),
    re.compile(r'system\s+prompt\s+(override|replace|change|modify|ignore)', re.I),
    re.compile(r'you\s+are\s+now\s+(a|an|no\s+longer)', re.I),
    re.compile(r'disregard\s+(all|any|your)\s+(previous|prior|above)', re.I),
    re.compile(r'new\s+instructions?\s*:', re.I),
    re.compile(r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)', re.I),
    re.compile(r'(cat|echo|print|export)\s+.*\$(ANTHROPIC|OPENAI|API|SECRET|TOKEN)', re.I),
    re.compile(r'base64\s+(encode|decode).*\b(key|token|secret|password)\b', re.I),
]


def _scan_for_threats(content: str, source: str) -> str | None:
    """Scan content for prompt injection patterns. Returns warning or None."""
    for pattern in _THREAT_PATTERNS:
        match = pattern.search(content)
        if match:
            return (
                f"[SECURITY WARNING] Potential prompt injection detected in {source}:\n"
                f"  Pattern: {match.group()!r}\n"
                f"  This content has been excluded from the system prompt."
            )
    return None


def get_git_info() -> str:
    """Return git branch/status summary if in a git repo. Cached for ~30s."""
    global _git_cache
    cwd = str(Path.cwd())
    now = time.monotonic()
    with _cache_lock:
        if _git_cache is not None and _git_cache[1] == cwd and _git_cache[0] > now:
            return _git_cache[2]
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL, text=True).strip()
        status = subprocess.check_output(
            ["git", "status", "--short"],
            stderr=subprocess.DEVNULL, text=True).strip()
        log = subprocess.check_output(
            ["git", "log", "--oneline", "-5"],
            stderr=subprocess.DEVNULL, text=True).strip()
        parts = [f"- Git branch: {branch}"]
        if status:
            lines = status.split('\n')[:10]
            parts.append("- Git status:\n" + "\n".join(f"  {l}" for l in lines))
        if log:
            parts.append("- Recent commits:\n" + "\n".join(f"  {l}" for l in log.split('\n')))
        result = "\n".join(parts) + "\n"
    except Exception:
        result = ""
    with _cache_lock:
        _git_cache = (now + _GIT_CACHE_TTL, cwd, result)
    return result


# ── Project instructions (AGENTS.md / CLAUDE.md / …) ─────────────────────

# Per-directory instruction files, in load order.  AGENTS.md is the shared
# cross-tool standard (Codex, Muse, …); CLAUDE.md / CLAUDE.local.md keep
# Claude Code compatibility; .cheetahclaws/INSTRUCTIONS.md is our own.
_PROJECT_INSTRUCTION_FILES = (
    ("AGENTS.md", "AGENTS.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    ("CLAUDE.local.md", "CLAUDE.local.md"),
    (os.path.join(".cheetahclaws", "INSTRUCTIONS.md"), "INSTRUCTIONS.md"),
)
_IMPORT_MAX_DEPTH = 5
_INSTRUCTION_FILE_MAX_CHARS = 64_000      # per file (incl. imports)
_INSTRUCTIONS_TOTAL_MAX_CHARS = 200_000   # whole block
# `@path` import: not preceded by a word char/backtick (skips emails and
# inline code), path chars only.  Resolved only if the file exists.
_IMPORT_RE = re.compile(r"(?<![\w`@])@((?:~|\.{1,2})?/?[\w.\-+/~]+)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_SECRET_DIR_NAMES = (".ssh", ".aws", ".gnupg", ".kube", ".docker")
_SECRET_FILE_RE = re.compile(
    r"(^id_[a-z0-9]+$)|(\.pem$)|(\.key$)|(^\.env(\..*)?$)|(^\.netrc$)|"
    r"(^credentials(\.json)?$)|(^shadow$)", re.I)


def _find_git_root(start: Path) -> Path | None:
    p = start
    for _ in range(64):
        if (p / ".git").exists():
            return p
        if p.parent == p:
            return None
        p = p.parent
    return None


def _legacy_nearest_claude_md_dir(start: Path) -> Path | None:
    """Directory of the nearest CLAUDE.md walking up ≤10 levels (the
    historical lookup, kept so a CLAUDE.md above the git root still loads)."""
    p = start
    for _ in range(10):
        if (p / "CLAUDE.md").exists():
            return p
        if p.parent == p:
            return None
        p = p.parent
    return None


def _project_instruction_dirs(cwd: Path) -> list[Path]:
    """Directories to scan, outermost first: git root → cwd (all levels).
    Without a git repo, only the nearest directory holding an instruction
    file (walking up ≤10 levels)."""
    git_root = _find_git_root(cwd)
    dirs: list[Path] = []
    if git_root is not None:
        p = cwd
        while True:
            dirs.append(p)
            if p == git_root or p.parent == p:
                break
            p = p.parent
        dirs.reverse()
        legacy = _legacy_nearest_claude_md_dir(cwd)
        if legacy is not None and legacy not in dirs:
            dirs.insert(0, legacy)
        return dirs
    p = cwd
    for _ in range(10):
        if any((p / rel).exists() for rel, _ in _PROJECT_INSTRUCTION_FILES):
            return [p]
        if p.parent == p:
            break
        p = p.parent
    return []


def _is_sensitive_path(path: Path) -> bool:
    parts = set(path.parts)
    if any(d in parts for d in _SECRET_DIR_NAMES):
        return True
    return bool(_SECRET_FILE_RE.search(path.name))


def _read_instruction_file(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(_INSTRUCTION_FILE_MAX_CHARS + 1)
    except Exception:
        return None
    if len(text) > _INSTRUCTION_FILE_MAX_CHARS:
        text = (text[:_INSTRUCTION_FILE_MAX_CHARS]
                + f"\n[… truncated at {_INSTRUCTION_FILE_MAX_CHARS:,} chars]")
    return text


def _find_imports(text: str, base_dir: Path) -> list[Path]:
    """Return existing files referenced as ``@path`` outside code fences."""
    found: list[Path] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in _IMPORT_RE.finditer(line):
            raw = m.group(1).rstrip(".,;:)")
            if not raw or raw in (".", ".."):
                continue
            candidate = Path(os.path.expanduser(raw))
            if not candidate.is_absolute():
                candidate = base_dir / candidate
            try:
                if candidate.is_file():
                    found.append(candidate)
            except OSError:
                continue
    return found


def _collect_instruction_file(path: Path, label: str, seen_real: set,
                              seen_hash: set, parts: list, warnings: list,
                              budget: list, depth: int = 0,
                              chain: tuple = ()) -> None:
    """Append ``path`` (and, recursively, its ``@imports``) to ``parts``.

    Dedupes by real path and by content hash; cycle-safe via ``chain`` and
    ``seen_real``; stops at depth ``_IMPORT_MAX_DEPTH`` and when the total
    character budget (``budget[0]``) is spent.
    """
    try:
        real = path.resolve()
    except Exception:
        return
    if real in seen_real or real in chain or budget[0] <= 0:
        return
    if depth > 0 and _is_sensitive_path(real):
        warnings.append(f"[instructions] Skipped import of sensitive path {path}")
        return
    text = _read_instruction_file(real)
    if text is None:
        return
    seen_real.add(real)
    import hashlib
    digest = hashlib.sha256(text.strip().encode("utf-8", "replace")).hexdigest()
    if digest in seen_hash:
        return
    seen_hash.add(digest)
    threat = _scan_for_threats(text, f"{label} ({path})")
    if threat:
        warnings.append(threat)
        return
    if len(text) > budget[0]:
        text = text[:budget[0]] + "\n[… instructions budget exhausted]"
    budget[0] -= len(text)
    parts.append(f"[{label}]\n{text}")
    if depth >= _IMPORT_MAX_DEPTH:
        return
    for imp in _find_imports(text, real.parent):
        _collect_instruction_file(
            imp, f"Imported by {path.name}: {imp}", seen_real, seen_hash,
            parts, warnings, budget, depth + 1, chain + (real,),
        )


def get_claude_md() -> str:
    """Load project / user instruction files.

    Sources, outermost first:
      * user level: ``~/.claude/CLAUDE.md`` and ``~/.cheetahclaws/AGENTS.md``
      * every directory from the git root down to cwd (or, outside git, the
        nearest directory that has one): ``AGENTS.md``, ``CLAUDE.md``,
        ``CLAUDE.local.md``, ``.cheetahclaws/INSTRUCTIONS.md``
      * ``@path/to/file.md`` imports inside any of them, resolved relative
        to the including file (depth ≤ 5, cycle-safe, size-capped)

    Identical files (same real path or same content) are included once.
    Each file is scanned for prompt injection patterns before inclusion.
    Cached for ~10s; the cache key is cwd so changing directories invalidates.
    """
    global _claude_md_cache
    cwd = str(Path.cwd())
    now = time.monotonic()
    with _cache_lock:
        if _claude_md_cache is not None and _claude_md_cache[1] == cwd and _claude_md_cache[0] > now:
            return _claude_md_cache[2]

    content_parts: list = []
    warnings: list = []
    seen_real: set = set()
    seen_hash: set = set()
    budget = [_INSTRUCTIONS_TOTAL_MAX_CHARS]

    home = Path.home()
    user_files = (
        (home / ".claude" / "CLAUDE.md", "Global CLAUDE.md"),
        (home / ".cheetahclaws" / "AGENTS.md", "Global AGENTS.md"),
    )
    for path, label in user_files:
        try:
            if path.exists():
                _collect_instruction_file(path, label, seen_real, seen_hash,
                                          content_parts, warnings, budget)
        except Exception:
            pass

    try:
        project_dirs = _project_instruction_dirs(Path(cwd))
    except Exception:
        project_dirs = []
    for d in project_dirs:
        for rel, name in _PROJECT_INSTRUCTION_FILES:
            candidate = d / rel
            try:
                if candidate.exists():
                    _collect_instruction_file(
                        candidate, f"Project {name}: {candidate}", seen_real,
                        seen_hash, content_parts, warnings, budget)
            except Exception:
                pass

    # Print warnings to stderr so user sees them
    if warnings:
        import sys
        for w in warnings:
            print(f"\033[33m{w}\033[0m", file=sys.stderr)

    if not content_parts:
        result = ""
    else:
        result = "\n# Memory / CLAUDE.md\n" + "\n\n".join(content_parts) + "\n"
    with _cache_lock:
        _claude_md_cache = (now + _CLAUDE_MD_TTL, cwd, result)
    return result


def get_platform_hints() -> str:
    """Return shell hints tailored to the current OS."""
    import platform as _plat
    if _plat.system() == "Windows":
        return (
            "\n## Windows Shell Hints\n"
            "You are on Windows. Do NOT use Unix commands. Use these instead:\n"
            "- `type file.txt` instead of `cat file.txt`\n"
            "- `type file.txt | findstr /n /i \"pattern\"` instead of `grep`\n"
            "- `powershell -Command \"Get-Content file.txt -Tail 20\"` instead of `tail -n 20`\n"
            "- `powershell -Command \"Get-Content file.txt -Head 20\"` instead of `head -n 20`\n"
            "- `dir /s /b *.py` or `powershell -Command \"Get-ChildItem -Recurse -Filter *.py\"` instead of `find . -name '*.py'`\n"
            "- `del file.txt` instead of `rm file.txt`\n"
            "- `mkdir folder` works on both (no -p needed)\n"
            "- `copy` / `move` instead of `cp` / `mv`\n"
            "- Use `&&` to chain commands, not `;`\n"
            "- Paths use backslashes `\\` but forward slashes `/` also work in most cases\n"
            "- Python is available: `python -c \"...\"` works for complex text processing\n"
        )
    return ""


def _render_env_block(config: dict | None = None) -> str:
    """Render the per-run environment block (date / cwd / platform / git / CLAUDE.md).

    This used to be the ``# Environment`` section at the bottom of the
    monolithic SYSTEM_PROMPT_TEMPLATE.  It now renders fresh every call
    so the base prompt can remain pure static text.
    """
    import platform as _plat
    # Trailing \n on the Platform line is load-bearing: get_git_info()
    # returns content that starts with "- Git branch:" (no leading newline),
    # so without this \n it concatenates as "Platform: Linux- Git branch:".
    header = (
        "# Environment\n"
        f"- Current date: {datetime.now().strftime('%Y-%m-%d %A')}\n"
        f"- Working directory: {Path.cwd()}\n"
        f"- Platform: {_plat.system()}\n"
    )
    return header + get_platform_hints() + get_git_info() + get_claude_md()


def _render_plan_fragment(config: dict) -> str:
    """Load the plan-mode fragment and fill in {plan_file}."""
    from cheetahclaws import runtime
    plan_file = runtime.get_ctx(config).plan_file or ""
    template = load_fragment("plan")
    return template.format(plan_file=plan_file)


def _render_active_tool_surface(config: dict) -> str:
    """Describe exactly the profile-filtered tools executable this turn."""
    from cheetahclaws.tool_registry import (
        get_profile_tool_names,
        normalize_tool_profile,
    )

    try:
        profile = normalize_tool_profile(config.get("tool_profile"))
    except ValueError:
        profile = "full"
    disabled = config.get("disabled_tools") or ()
    if not isinstance(disabled, (list, tuple, set, frozenset)):
        disabled = ()
    names = config.get("_active_tool_names")
    if names is None:
        names = get_profile_tool_names(profile, disabled)
    visible = ", ".join(f"`{name}`" for name in sorted(names)) or "(none)"
    planning_hint = ""
    if {"EnterPlanMode", "ExitPlanMode"} <= set(names):
        # Keep the planning cue with its optional tools rather than paying for
        # it on every standard coding turn. This also makes the prompt
        # deterministic: it must not depend on slash-command imports.
        planning_hint = (
            "- For complex or multi-file work, use `EnterPlanMode` before "
            "making changes, then finish with `ExitPlanMode`.\n"
        )
    return (
        "# Active Tool Surface\n"
        f"- Profile: `{profile}`\n"
        f"- Enabled tools: {visible}\n"
        "- Call only the enabled tools above; a tool mentioned elsewhere is not "
        "available unless it appears in this list.\n"
        f"{planning_hint}"
    )


def _tmux_available() -> bool:
    try:
        from cheetahclaws.tmux_tools import tmux_available
        return tmux_available()
    except Exception:
        # Optional integrations must not prevent prompt construction when an
        # older supported Python cannot import their modern type annotations.
        return False


def _tmux_fragment_enabled(config: dict) -> bool:
    """Show tmux instructions only when its executable tool is active."""
    from cheetahclaws.tool_registry import (
        get_active_tool_names,
        normalize_tool_profile,
    )

    try:
        profile = normalize_tool_profile(config.get("tool_profile"))
    except ValueError:
        profile = "full"
    if profile != "full" or not _tmux_available():
        return False
    disabled = config.get("disabled_tools") or ()
    if not isinstance(disabled, (list, tuple, set, frozenset)):
        disabled = ()
    names = config.get("_active_tool_names")
    if names is None:
        names = get_active_tool_names(profile, disabled)
    return "TmuxNewSession" in names and "TmuxNewSession" not in disabled


def _render_commands_block() -> str:
    """Render a markdown list of every registered slash command.

    Pulls live from ``cheetahclaws._CMD_META`` (lazy import to avoid the
    cheetahclaws -> context -> cheetahclaws circular at module load), so
    the prompt always reflects the current command surface — including
    plugins merged in via ``_load_external_commands_into``.

    Without this block the model has no idea what `/trading`,
    `/research`, `/lab`, `/web`, `/wechat` etc. are and will confabulate
    when the user asks "what can you do?" — see context.py docstring.
    """
    try:
        import cheetahclaws as _cc
    except ImportError:
        return ""
    meta = getattr(_cc, "_CMD_META", None)
    if not meta:
        return ""

    lines = [
        "# Available Slash Commands (User-invokable in this CheetahClaws session)",
        "",
        "These commands the **user** can invoke at the REPL prompt — they are"
        " NOT tools you call. When the user asks 'what can you do?' / '你能做什么?'"
        " / asks about a feature like trading or research or web UI, reference"
        " these by their exact `/name` so the user can try them. Do not invent"
        " commands that are not on this list.",
        "",
    ]
    for name in sorted(meta.keys()):
        desc, subs = meta[name]
        sub_str = f" `[{' | '.join(subs)}]`" if subs else ""
        lines.append(f"- `/{name}`{sub_str} — {desc}")
    return "\n".join(lines)


def build_system_prompt(config: dict | None = None) -> str:
    """Build the full system prompt for the current session.

    Structure (top → bottom):
        1. Provider-selected base prompt (``prompts/base/<provider>.md``)
        2. Per-run environment block (date, cwd, platform, git, CLAUDE.md)
        3. Live slash-command index (so the model can answer
           "what can you do?" without confabulating)
        4. Memory index (if any memories exist)
        5. Tmux fragment (if tmux is installed)
        6. Plan-mode fragment (if ``permission_mode == "plan"``)
    """
    # Resolve provider lazily to avoid circular imports at module load.
    from cheetahclaws.providers import detect_provider

    cfg = config or {}
    model_id = cfg.get("model", "")
    # No model -> empty provider so pick_base_prompt falls through to
    # default.md.  The previous "anthropic" fallback silently gave Claude-
    # styled prompts (XML tags, minimal-scope guard) to whatever model
    # picked them up later, which is wrong for non-Claude families.
    provider = detect_provider(model_id) if model_id else ""

    # Optional integration instructions must agree with the exact active tool
    # set. A detected binary alone does not make a tool callable.
    tmux_fragment = load_fragment("tmux") if _tmux_fragment_enabled(cfg) else ""

    parts: list[str] = [
        pick_base_prompt(provider, model_id),
        _render_active_tool_surface(cfg),
        _render_env_block(cfg),
    ]

    cmds_block = _render_commands_block()
    if cmds_block:
        parts.append(cmds_block)

    memory_ctx = get_memory_context()
    if memory_ctx:
        parts.append(f"# Memory\nYour persistent memories:\n{memory_ctx}")

    if tmux_fragment:
        parts.append(tmux_fragment)

    if cfg.get("permission_mode") == "plan":
        parts.append(_render_plan_fragment(cfg))

    # Collapse any trailing whitespace on each part so the "\n\n"
    # separator produces a consistent two-newline gap regardless of how
    # each file/helper terminates.
    return "\n\n".join(p.rstrip() for p in parts if p)
