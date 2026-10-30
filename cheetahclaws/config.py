"""Configuration management for CheetahClaws (multi-provider)."""
import os
import json
from pathlib import Path

CONFIG_DIR        = Path.home() / ".cheetahclaws"
CONFIG_FILE       = CONFIG_DIR  / "config.json"
HISTORY_FILE      = CONFIG_DIR  / "input_history.txt"
SESSIONS_DIR      = CONFIG_DIR  / "sessions"
DAILY_DIR         = SESSIONS_DIR / "daily"       # daily/YYYY-MM-DD/session_*.json
SESSION_HIST_FILE = SESSIONS_DIR / "history.json" # master: all sessions ever

# kept for backward-compat (/resume still reads from here)
MR_SESSION_DIR = SESSIONS_DIR / "mr_sessions"

DEFAULTS = {
    "model":            "ollama/gemma4:e4b",
    "max_tokens":       40000,    # max OUTPUT tokens per response (NOT the context window)
    # Context-window override in tokens. 0 = use the model/provider default.
    # Drives the prompt % indicator, /context, and the compaction trigger. Set
    # via `/config context_window=<N>` to correct a stale provider default for
    # the session. WARNING: setting it ABOVE the model's real window disables the
    # compaction safety net — the API may then reject oversized prompts.
    "context_window":   0,
    "permission_mode":  "auto",   # auto | accept-edits | accept-all | manual | plan
    # Full autonomy, and the default: a request is carried out end to end and
    # you get the result, instead of the turn stopping at an approval menu for
    # every command it needs to run. Remembered across restarts (unlike the
    # session-only `accept-all`).
    #
    # Turn the prompts back on with `/auto off` (persisted) or the `--ask`
    # launch flag (one run). Still enforced while this is on: the Bash
    # hard-denylist refuses host-destroying commands at execution time, the
    # filesystem sandbox and credential-path denylist still apply, and the
    # `manual` / `plan` permission modes still override it.
    "auto_approve":     True,
    # Permission signatures approved for good — "Bash:pytest", "Bash:git push",
    # "Edit:/repo/app.py". Answering "!" at a prompt appends one, so a command
    # you have already vouched for never prompts again in any future session.
    # Inspect with `/permissions`, drop with `/permissions forget <sig|all>`.
    "always_allow":     [],
    # Extra program names to treat as read-only in the Bash auto-approval
    # check (tools/security.py). Use for a project's own reporting/query
    # commands so routine calls stop prompting:
    #   /config bash_safe_extra=["bazel-query","./scripts/status"]
    # Only add programs that cannot write, delete, or execute other programs.
    "bash_safe_extra":  [],
    # Auto-approve a Write that CREATES a new file inside the working
    # directory (nothing to overwrite, nothing outside the workspace).
    # Overwrites, paths outside the workspace, and any dot-prefixed path
    # (.git/, .github/, .env) still prompt. Set False to review every write.
    "auto_create_files": True,
    "verbose":          False,
    # Render a Markdown `---` separator as a full-width horizontal rule.
    # Models use `---` freely to divide sections, and the rule then lands
    # mid-turn — between two tool-summary lines, say — where it reads like
    # the app drew a divider rather than the answer containing one. Off by
    # default; the surrounding blank line already separates the sections.
    "markdown_rules":   False,
    # /resume repaints the loaded conversation so a resumed session looks
    # resumed, instead of restoring it invisibly and leaving you talking to
    # something that remembers a conversation you can't see. Set False to
    # restore silently; resume_replay_limit caps how many messages are
    # painted (0 = all) so a very long session doesn't flood the terminal.
    "resume_replay":       True,
    "resume_replay_limit": 40,
    # terminal_title: set the terminal window/tab title to the current task —
    #   a pulsing glyph while working, a static badge when idle (Claude-Code
    #   style). Auto-disabled on non-TTYs / dumb terminals. Set False to leave
    #   the shell's own title untouched.
    "terminal_title":   True,
    # Tri-state: None = unset (use provider default), True = ON, False = explicit OFF.
    # The explicit-OFF state matters for DeepSeek v4 where the server default
    # is ON; providers.py only injects the disable toggle when value is False.
    "thinking":         None,
    "thinking_budget":  10000,
    "custom_base_url":  "",       # for "custom" provider
    "max_tool_output":  32000,
    # Tool schemas are part of every provider request.  Default to the full
    # surface so no capability (web, sub-agents, MCP, plugins) silently
    # disappears for users who rely on it; opt into ``standard`` (compact
    # coding-only), ``research``, or ``orchestration`` to shrink the surface
    # and save prompt tokens when a session doesn't need everything.
    "tool_profile":     "full",  # full | standard | research | orchestration
    # Bound input work before a tool result reaches the generic output cap.
    "tool_read_max_bytes":      256 * 1024,
    "tool_read_scan_max_bytes": 2 * 1024 * 1024,
    "tool_read_max_output_chars": 50_000,
    "web_fetch_max_bytes":      512 * 1024,
    "web_search_max_bytes":     512 * 1024,
    "web_fetch_max_seconds":    30,
    "web_search_max_seconds":   30,
    "pdf_extract_max_chars":    50_000,
    "pdf_extract_max_pages":    50,
    "pdf_extract_max_file_bytes": 32 * 1024 * 1024,
    "summarize_max_input_bytes": 16 * 1024 * 1024,
    "summarize_chunk_max_output_chars": 8_000,
    "summarize_reduce_max_input_chars": 200_000,
    # Read-only cache values are post-truncation and capped independently so a
    # single large fetch cannot consume unbounded resident memory.
    "max_tool_cache_output":    12_000,
    "max_agent_depth":  3,
    "max_concurrent_agents": 3,
    "session_daily_limit":   10000,    # max sessions kept per day in daily/
    "session_history_limit": 100000,  # max sessions kept in history.json
    # ── Workspaces ──────────────────────────────────────────────────────────
    # workspace_auto: when True, the CLI chdirs into a workspace under
    #   ~/.cheetahclaws/workspaces on startup. Default False so launching in a
    #   project directory keeps operating on that directory (opt-in isolation).
    "workspace_auto":    False,
    # workspace_default: the workspace entered at startup when workspace_auto is
    #   on. null → fall back to workspace_last, then "workspace1". Set via
    #   `/workspace default <name>`; NOT overwritten by `/workspace switch`.
    "workspace_default": None,
    # workspace_last: the most recently switched-to workspace (updated by
    #   `/workspace switch`). Used as the startup fallback when no default is set.
    "workspace_last":    None,
    # ── Security settings ──────────────────────────────────────────────────
    # allowed_root: restrict file operations (Read/Write/Edit/Glob/Grep) to this
    # directory tree.  null = unrestricted (CLI default).  Set to the project
    # root in production deployments to prevent path traversal.
    "allowed_root": None,
    # shell_policy: controls Bash tool execution.
    #   "allow"   — execute freely (CLI default)
    #   "log"     — execute but write every command to stderr with session_id
    #   "deny"    — block all Bash execution
    "shell_policy": "allow",
    # ── Structured logging ─────────────────────────────────────────────────
    # log_level: "off" | "error" | "warn" | "info" | "debug"
    #   Default "warn" keeps the interactive CLI quiet; set to "info" on
    #   production servers to capture every API call, retry, and quota event.
    "log_level": "warn",
    # log_file: absolute path or null.  null → stderr (only warn/error visible
    #   at default level).  Point to a file in production for persistent logs.
    "log_file": None,
    # ── Prompt caching (Anthropic) ─────────────────────────────────────────
    # prompt_cache: mark cache_control breakpoints on Anthropic requests so
    #   the provider's prompt cache activates (cache read = 0.1x input price,
    #   cache write = 1.25x; within-turn tool loops re-send an identical
    #   prefix 5-50 times, so this is a large input-cost/latency win).
    #   Escape hatch: set to false when a custom anthropic_endpoint proxy
    #   rejects cache_control fields (a 400 naming cache_control also
    #   auto-disables it for the rest of the process). Other providers
    #   ignore this flag — their caching is implicit server-side.
    "prompt_cache": True,
    # ── Circuit breaker ────────────────────────────────────────────────────
    # circuit_failure_threshold: consecutive failures (in window) to trip open.
    "circuit_failure_threshold": 5,
    # circuit_window_seconds: rolling window for failure counting.
    "circuit_window_seconds": 60,
    # circuit_cooldown_seconds: how long to stay OPEN before probing again.
    "circuit_cooldown_seconds": 120,
    # ── Quota / budget control ─────────────────────────────────────────────
    # All limits are null (unlimited) by default.  Set to enforce hard caps.
    "session_token_budget": None,  # max tokens (in+out) per session
    "session_cost_budget":  None,  # max USD per session
    "daily_token_budget":   None,  # max tokens today (all sessions)
    "daily_cost_budget":    None,  # max USD today (all sessions)
    # ── Auto-fanout for oversize tool outputs ─────────────────────────────
    # When a single tool output (e.g. Read on a 6.6 MB PDF) is bigger than
    # auto_fanout_threshold * model_context_window, instead of letting the
    # next API call overflow, split it into chunks and dispatch parallel
    # sub-LLM calls to summarize each chunk, then merge. Critical for small
    # context windows (32k local models) reading large source material.
    "auto_fanout_enabled":                  True,
    "auto_fanout_threshold":                0.4,   # fraction of ctx_window
    "auto_fanout_max_subagents":            5,
    "auto_fanout_chunk_overlap_tokens":     200,
    # ── Autonomous-agent stagnation detection ─────────────────────────────
    # Stop the iteration loop in agent_runner if the model emits the same
    # summary text N iterations in a row (e.g. "task complete" repeated).
    # 0 disables. 3 catches the common "model declares done; template
    # politely asks again" case without false-positives on slowly-progressing
    # multi-day work where consecutive iterations may produce similar status
    # updates.
    "auto_agent_dup_summary_limit":         3,
    # RFC 0002 F-4: run agent_runner as a subprocess under daemon
    # supervision instead of an in-process thread. Off by default so
    # REPL behaviour is unchanged; daemon code paths can opt in
    # explicitly. The CHEETAHCLAWS_ENABLE_F4 env var also enables it.
    "agent_runner_subprocess":              False,
    # ── Input ghost text ───────────────────────────────────────────────────
    # After each turn the auxiliary model drafts the line you are most likely
    # to type next; it shows dim at the prompt and Tab accepts it in full.
    # See ui/suggest.py. Also switchable per-run with CHEETAH_SUGGEST=0.
    "input_suggest":                        True,
    # Per-provider API keys (optional; env vars take priority)
    # "anthropic_api_key": "sk-ant-..."
    # "openai_api_key":    "sk-..."
    # "gemini_api_key":    "..."
    # "kimi_api_key":      "..."
    # "qwen_api_key":      "..."
    # "zhipu_api_key":     "..."
    # "deepseek_api_key":  "..."
    # ── QQ Bot bridge ──────────────────────────────────────────────────────
    # qq_appid / qq_secret from https://q.qq.com developer portal
    "qq_appid":    "",
    "qq_secret":   "",
    # ── WeChat smart-reply (off by default) ────────────────────────────────
    # When enabled, inbound messages from whitelisted contacts no longer
    # auto-reply via the agent.  Instead the auxiliary cheap model drafts
    # 3 candidate replies and pushes them to the user's `filehelper`
    # (文件传输助手) chat for approval.  See bridges/wechat_smart_reply.py.
    "wechat_smart_reply":                  False,
    "wechat_smart_reply_whitelist":        [],     # list of from_user_id strings
    "wechat_smart_reply_groups":           False,  # also draft for group messages
    "wechat_smart_reply_groups_at_only":   False,  # in groups, only when @<self>
    "wechat_smart_reply_timeout_s":        300,    # panel expiry seconds
    # WeChat self nickname — needed for groups_at_only matching.  Not set
    # automatically; user provides via config or `/wechat self <nickname>`.
    "wechat_self_nickname":                "",
    # WeChat self uid — bridge inbound from this uid is YOUR OWN message
    # to the bot. smart-reply ignores it unconditionally so your normal
    # messages still reach the agent, even if you accidentally put your
    # own uid in wechat_smart_reply_whitelist (which is intended for OTHER
    # contacts whose messages you want the bot to draft replies for).
    # Auto-recorded by the wechat bridge on first inbound (see _wx_poll_loop).
    "wechat_self_uid":                     "",
    # ── Bridge sender allowlists (bridges/auth.py) ─────────────────────────
    # Only these sender ids may run !shell, slash commands or agent turns via
    # a bridge. Empty → the first sender in a 1:1 private chat is bound as
    # owner and saved here. Group members must be added explicitly, e.g.
    #   /config telegram_allowed_users=["123456789","987654321"]
    # Escape hatch (old behaviour, anyone who can message the bot):
    #   /config <bridge>_allow_all_senders=true
    "telegram_allowed_users":              [],
    "wechat_allowed_users":                [],
    "qq_allowed_users":                    [],
    "slack_allowed_users":                 [],
    # ── Workspace trust (trust.py) ─────────────────────────────────────────
    # A project's .mcp.json servers and .cheetahclaws/plugins.json plugins
    # only run once you `/trust` the project. True restores the old
    # load-everything behaviour (also: env CHEETAHCLAWS_TRUST_ALL=1).
    "trust_all_projects":                  False,
}


# Bumped whenever a saved config needs fixing up on load. Deliberately NOT a
# DEFAULTS key: save_config prunes default-valued keys, which would erase the
# marker and make every migration run again on the next launch.
CONFIG_VERSION = 2


def _migrate_saved_config(saved: dict) -> dict:
    """Fix up a config written by an older build, and record that we did.

    Rewrites the file in place when something changed, so the repair happens
    once rather than on every launch. Best-effort: a read-only HOME still gets
    the corrected values for the running session.
    """
    version = saved.get("config_version", 0)
    if version >= CONFIG_VERSION:
        return saved
    out = dict(saved)

    # v0/v1 → v2: `auto_approve` shipped as False, and save_config persisted
    # every key including the defaults — so the False was frozen into configs
    # that never chose it, and flipping the default to True (autonomous by
    # default) could not reach them. Drop the inherited value; a deliberate
    # `/auto off` after this migration writes it back and is then kept,
    # because save_config only persists what differs from DEFAULTS.
    if version < 2 and out.get("auto_approve") is False:
        out.pop("auto_approve", None)

    # Saved grants whose signature still carries a shell operator were written
    # by the old signature builder ("Bash:date;" for `date; date -u`). They can
    # never match anything the current builder produces, so they are dead
    # entries that only make `/permissions` confusing.
    if version < 2 and isinstance(out.get("always_allow"), list):
        cleaned = [g for g in out["always_allow"]
                   if not (isinstance(g, str) and any(ch in g for ch in ";&|"))]
        if cleaned != out["always_allow"]:
            out["always_allow"] = cleaned

    # …and prune the rest of the frozen defaults in the same pass, so the file
    # is clean now rather than only after the next save. Without this, all ~76
    # inherited values sit there blocking the *next* default change too.
    if version < 2:
        out = {k: v for k, v in out.items()
               if k not in DEFAULTS or v != DEFAULTS[k]}

    out["config_version"] = CONFIG_VERSION
    if out != saved:
        try:
            _ensure_private_dir(CONFIG_DIR)
            _write_private_json(CONFIG_FILE, out)
        except Exception:
            pass
    return out


# ── Private file helpers ──────────────────────────────────────────────────
# config.json holds API keys and bridge tokens. It must never be readable by
# other local users, not even for the instant between create and chmod, and a
# crash mid-write must not leave a truncated file behind.

def _ensure_private_dir(path: Path) -> None:
    """Create ``path`` as 0700; tighten an existing group/world-accessible one."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        if path.stat().st_mode & 0o077:
            os.chmod(path, 0o700)
    except OSError:
        pass


def _write_private_json(path: Path, data: dict) -> None:
    """Atomically write ``data`` as JSON to ``path`` with mode 0600.

    The temp file is created 0600 by mkstemp (no umask window), then renamed
    over the target, so the final file is 0600 even if an older build left a
    0644 one behind.
    """
    import tempfile
    text = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# Config keys that load_config may fill from the environment. A value that
# came from the environment is never written back to config.json — otherwise
# exporting ANTHROPIC_API_KEY once would silently persist the secret to disk.
# To persist a key deliberately, set it with `/config anthropic_api_key=...`
# to a value different from the env var (or unset the env var first).
_ENV_SOURCED_KEYS = {
    "anthropic_api_key":  "ANTHROPIC_API_KEY",
    "anthropic_endpoint": "ANTHROPIC_ENDPOINT",
}
# Runtime-only map {config_key: value_taken_from_env}; the leading underscore
# keeps it out of config.json (save_config strips "_" keys).
_ENV_TRACK_KEY = "_env_sourced"


def load_config() -> dict:
    _ensure_private_dir(CONFIG_DIR)
    SESSIONS_DIR.mkdir(exist_ok=True)
    cfg = dict(DEFAULTS)
    saved_config: dict = {}
    if CONFIG_FILE.exists():
        try:
            saved_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(saved_config, dict):
                saved_config = _migrate_saved_config(saved_config)
                cfg.update(saved_config)
            else:
                saved_config = {}
        except Exception:
            pass
    # A missing profile (including old config files) inherits the ``full``
    # DEFAULTS value above, so upgrading never removes a capability a user
    # already relied on. Shrinking the surface is an explicit opt-in via
    # ``tool_profile=standard`` (or research/orchestration).
    # Backward-compat: legacy single api_key → anthropic_api_key
    if cfg.get("api_key") and not cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = cfg.pop("api_key")
    env_sourced: dict = {}
    # Also accept ANTHROPIC_API_KEY env for backward-compat
    if not cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
        if cfg["anthropic_api_key"]:
            env_sourced["anthropic_api_key"] = cfg["anthropic_api_key"]
    # Env var always wins over persisted value so .env changes take effect immediately
    if os.environ.get("ANTHROPIC_ENDPOINT"):
        cfg["anthropic_endpoint"] = os.environ["ANTHROPIC_ENDPOINT"]
        env_sourced["anthropic_endpoint"] = cfg["anthropic_endpoint"]
    elif not cfg.get("anthropic_endpoint"):
        cfg["anthropic_endpoint"] = "https://api.anthropic.com"
    cfg[_ENV_TRACK_KEY] = env_sourced
    return cfg


def _strip_env_sourced(cfg: dict, data: dict) -> dict:
    """Drop (or restore the on-disk value of) keys whose value came from env.

    Uses the map load_config recorded, plus the live environment as a
    fallback for config dicts that were built without load_config.
    """
    env_vals: dict = {}
    for key, var in _ENV_SOURCED_KEYS.items():
        v = os.environ.get(var)
        if v:
            env_vals.setdefault(key, []).append(v)
    tracked = cfg.get(_ENV_TRACK_KEY)
    if isinstance(tracked, dict):
        for key, v in tracked.items():
            if v:
                env_vals.setdefault(key, []).append(v)
    if not env_vals:
        return data
    on_disk: dict = {}
    try:
        if CONFIG_FILE.exists():
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                on_disk = loaded
    except Exception:
        pass
    out = dict(data)
    for key, values in env_vals.items():
        if key in out and out[key] in values:
            if on_disk.get(key):
                # The user persisted this key themselves — even if it equals
                # the env value, deleting it would strand launches that run
                # without that env var (desktop app, cron).
                out[key] = on_disk[key]
            else:
                out.pop(key, None)
    return out


def save_config(cfg: dict):
    _ensure_private_dir(CONFIG_DIR)
    # Strip internal runtime keys (e.g. _run_query_callback) before saving
    data = {k: v for k, v in cfg.items() if not k.startswith("_")}
    # Never persist secrets/endpoints that only came from the environment.
    data = _strip_env_sourced(cfg, data)
    # `accept-all` is a one-time-confirmation escape hatch — it should NEVER
    # outlive the session that set it. Persisting it means a user who once
    # clicked "Accept all" silently keeps that mode on every future launch.
    if data.get("permission_mode") == "accept-all":
        data.pop("permission_mode", None)
    # Write only what differs from DEFAULTS. This used to persist all ~76 keys,
    # which quietly froze every default into the file the first time anything
    # called save_config — so changing a default in a later release never
    # reached an existing user, it only reached a brand-new install. Since
    # load_config layers the saved file over DEFAULTS, dropping default-valued
    # keys loads identically while letting defaults actually be defaults.
    # `config_version` is deliberately absent from DEFAULTS so migrations
    # can't prune the marker that records they already ran.
    data = {k: v for k, v in data.items()
            if k not in DEFAULTS or v != DEFAULTS[k]}
    data["config_version"] = CONFIG_VERSION
    _write_private_json(CONFIG_FILE, data)


def current_provider(cfg: dict) -> str:
    from cheetahclaws.providers import detect_provider
    return detect_provider(cfg.get("model", "claude-opus-4-6"))


def has_api_key(cfg: dict) -> bool:
    """Check whether the active provider has an API key configured."""
    from cheetahclaws.providers import get_api_key
    pname = current_provider(cfg)
    key = get_api_key(pname, cfg)
    return bool(key)


def calc_cost(model: str, in_tokens: int, out_tokens: int,
              cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> float:
    from cheetahclaws.providers import calc_cost as _cc
    return _cc(model, in_tokens, out_tokens, cache_read_tokens, cache_write_tokens)
