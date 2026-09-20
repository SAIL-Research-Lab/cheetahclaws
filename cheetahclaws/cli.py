#!/usr/bin/env python3
"""
CheetahClaws — A Fast, Easy-to-Use, Python-Native Personal AI Assistant for Any Model, Built to Work for You Autonomously 24/7.

Usage:
  python cheetahclaws.py [options] [prompt]

Options:
  -p, --print          Non-interactive: run prompt and exit (also --print-output)
  -m, --model MODEL    Override model
  --accept-all         Never ask permission for this session (dangerous)
  --auto               Autonomous: run the whole task without approval prompts
                       (this is the default; overrides a saved /auto off)
  --ask                Turn approval prompts back on for this run
  --verbose            Show thinking + token counts
  --version            Print version and exit

Slash commands in REPL:
  /help       Show this help
  /clear      Clear conversation
  /model [m]  Show or set model
  /config     Show config / set key=value
  /save [f]   Save session to file
  /load [f]   Load session from file
  /resume [f] Pick a past session by name (or pass an id / file / "last")
  /history    Print conversation history
  /context    Show context window usage
  /cost       Show API cost this session
  /budget     View or set token/cost budgets (session + daily)
  /status     Show current session status (model, mode, tokens, cost)
  /verbose    Toggle verbose mode
  /quiet      Toggle compact tool display (hide execution, show per-turn summary)
  /thinking   Toggle extended thinking
  /permissions [mode]  Set permission mode (also: clear | allow <sig> | forget <sig|all>)
  /auto [on|off]  Autonomous mode (ON by default): carry tasks through
                  without asking. /auto off restores approval prompts.
  /cwd [path] Show or change working directory
  /workspace [cmd] Manage CheetahClaws workspaces (list/switch/create/delete)
  /compact    Compact conversation history to save context space
  /init       Initialize a CLAUDE.md file in the current directory
  /export [f] Export conversation history to a Markdown file
  /copy       Copy the last assistant response to clipboard
  /doctor     Diagnose installation health and tool connectivity
  /circuit    Show per-provider circuit breakers
  /circuit reset <provider|all>   Force-close a breaker (recover from circuit_open_skip)
  /web [port] [--host H] [--no-auth]  Start web terminal / chat UI in background
  /web status  Show whether the web server is running
  /memory [query]         Show/search persistent memories
  /memory consolidate     Extract long-term insights from current session via AI
  /skills           List available skills
  /agents           Show sub-agent tasks
  /mcp              List MCP servers and their tools
  /mcp reload       Reconnect all MCP servers
  /mcp add <n> <cmd> [args]  Add a stdio MCP server
  /mcp remove <n>   Remove an MCP server from config
  /plugin           List installed plugins
  /plugin install name@url   Install a plugin
  /plugin uninstall name     Uninstall a plugin
  /plugin enable/disable name  Toggle plugin
  /plugin update name        Update a plugin
  /plugin recommend [ctx]    Recommend plugins for context
  /tasks            List all tasks
  /tasks create <subject>    Quick-create a task
  /tasks start/done/cancel <id>  Update task status
  /tasks delete <id>         Delete a task
  /tasks get <id>            Show full task details
  /tasks clear               Delete all tasks
  /checkpoint       List checkpoints or restore one (/checkpoint restore <id>)
  /rewind [id]      Rewind conversation to a checkpoint
  /plan <desc>      Enter plan mode (write-protect everything except plan file)
  /plan done        Exit plan mode and restore permissions
  /plan status      Show plan mode status
  /brainstorm <topic>  Multi-persona iterative brainstorming session
  /draft <msg>      Draft 3 candidate replies for a message (manual copy/paste)
  /draft @<contact> <msg>   Same, but tone-conditioned on wx_contacts.json
  /worker           Auto-implement tasks from todo_list.txt
  /agent start <template> [args]  Autonomous agent loop (research_assistant / auto_bug_fixer / paper_writer / auto_coder)
  /agent stop <name>    Stop a running agent
  /agent list           List running agents
  /agent templates      List available task templates
  /ssj              SSJ Developer Mode — power menu (brainstorm, debate, worker, trading, review…)
  /trading analyze <SYMBOL>   Multi-agent analysis (Bull/Bear debate → Risk panel → PM decision)
  /trading backtest <SYM> [strategy]  Backtest a strategy (dual_ma, rsi_mean_reversion, bollinger_breakout, macd_crossover)
  /trading price <SYMBOL>     Current price and key metrics
  /trading indicators <SYMBOL>  Technical indicators report (SMA, RSI, MACD, Bollinger, ADX…)
  /trading status             Trading memory status
  /trading history            Past trading decisions
  /trading memory [action]    Manage trading memory (list, search, clear)
  /image [prompt]   Send clipboard image to vision model
  /video [topic]    AI video content factory — story → TTS → images → subtitles → MP4
  /voice            Record voice input, transcribe, and submit
  /voice status     Show available recording and STT backends
  /voice lang <code>  Set STT language (e.g. zh, en, ja — default: auto)
  /tts              AI text-to-speech wizard — script → MP3 in any voice style
  /proactive [dur]  Background sentinel polling (e.g. /proactive 5m)
  /proactive off    Disable proactive polling
  /cloudsave setup <token>   Configure GitHub token for cloud sync
  /cloudsave        Upload current session to GitHub Gist
  /cloudsave push [desc]     Upload with optional description
  /cloudsave auto on|off     Toggle auto-upload on exit
  /cloudsave list   List your cheetahclaws Gists
  /cloudsave load <gist_id>  Download and load a session from Gist
  /subscribe <topic> [schedule] [--telegram] [--slack]
                    Subscribe to AI-monitored topic (ai_research, stock_TSLA, crypto_BTC, world_news, custom:<query>)
  /subscriptions    List active subscriptions
  /unsubscribe <topic>  Remove a subscription
  /monitor run [topic]  Run monitor(s) now and print AI report
  /monitor start    Start background scheduler (runs subscriptions on schedule)
  /monitor stop     Stop background scheduler
  /monitor status   Show scheduler status and subscription overview
  /monitor set telegram <token> <chat_id>  Configure Telegram delivery
  /monitor set slack <token> <channel_id>  Configure Slack delivery
  /monitor topics   List available built-in topics
  /telegram <bot_token> <chat_id>  Start Telegram bridge
  /telegram stop|status             Stop or check Telegram bridge
  /wechat login                     Authenticate WeChat via QR code
  /wechat stop|status               Stop or check WeChat bridge
  /qq <appid> <secret>              Start QQ bridge (QQ Bot)
  /qq stop|status                   Stop or check QQ bridge
  /slack <token> <channel_id>       Start Slack bridge (Web API)
  /slack stop|status|logout         Stop, check, or clear Slack bridge
  /lab start <topic>                Autonomous multi-agent research run (9 stages)
  /lab status [<run_id>]            List runs / detail one run
  /lab logs <run_id> [n]            Last N agent messages for a run
  /lab abort <run_id>               Cancel an in-flight run after current stage
  /lab resume <run_id> [<stage>]    Continue a run; optionally rewind to <stage>
  /lab iterate <run_id>             Score the report + revise weakest stage; loops to target
  /lab backlog add <topic> [--iterate] [--target=N] [--max=N] [--prio=N]
                                    Queue a topic for the daemon
  /lab backlog list / remove <id> / clear
                                    Manage the queue
  /lab daemon start | stop | status 24/7 worker that pulls from the backlog
  /lab models                       Show effective per-role model assignment
  /lab migrate-paths [--apply]      Rename legacy lab_xxx/ output dirs to human-readable form
  /exit /quit Exit
"""
from __future__ import annotations

# ── Standard library ───────────────────────────────────────────────────────
import os

# Load .env before any other imports read os.environ
def _load_env() -> None:
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            _v = _v.strip()
            if len(_v) >= 2 and _v[0] in ('"', "'") and _v[-1] == _v[0]:
                _v = _v[1:-1]
            os.environ.setdefault(_k.strip(), _v)
_load_env()

import re
import sys
import uuid
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape codes on Windows CMD
import json
try:
    import readline
except ImportError:
    readline = None  # Windows compatibility
import atexit
import argparse
import time
import traceback
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Union


# ── Safe stdio wrapper (prevents BrokenPipeError in daemon/bridge mode) ──
class _SafeWriter:
    """Wraps stdout/stderr to silently handle broken pipes and closed fds."""
    __slots__ = ("_inner",)

    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        try:
            return self._inner.write(data)
        except (BrokenPipeError, OSError, ValueError):
            return len(data) if isinstance(data, str) else 0

    def flush(self):
        try:
            self._inner.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


sys.stdout = _SafeWriter(sys.stdout)
sys.stderr = _SafeWriter(sys.stderr)


# ── UI / rendering ─────────────────────────────────────────────────────────
from cheetahclaws.ui.render import (
    C, clr, info, ok, warn, err, _truncate_err_global,
    render_diff, _has_diff,
    stream_text, stream_thinking, flush_response,
    _start_tool_spinner, _stop_tool_spinner, _change_spinner_phrase,
    set_spinner_phrase, set_rich_live, set_stream_mode, auto_stream_mode, set_spinner_tips,
    set_terminal_title_enabled, set_task_title, terminal_working_start, terminal_working_stop,
    clear_terminal_title,
    print_tool_start, print_tool_end,
    set_quiet, set_markdown_rules, reset_turn_stats, print_turn_summary,
    set_spinner_tokens, print_turn_stats,
    _RICH, console, _rgb,
)

# ── Input layer (prompt_toolkit with readline fallback) ──────────────────
import cheetahclaws.ui.input as _ui_input
_pt_read_line = _ui_input.read_line
HAS_PROMPT_TOOLKIT = _ui_input.HAS_PROMPT_TOOLKIT

# ── Bridge commands ────────────────────────────────────────────────────────
import cheetahclaws.bridges.telegram as _btg
import cheetahclaws.bridges.wechat   as _bwx
import cheetahclaws.bridges.slack    as _bslk
import cheetahclaws.bridges.qq       as _bqq
from cheetahclaws.bridges.telegram import cmd_telegram, _tg_send
from cheetahclaws.bridges.wechat import cmd_wechat, _wx_start_bridge
from cheetahclaws.bridges.slack import cmd_slack, _slack_start_bridge
from cheetahclaws.bridges.qq import cmd_qq, _qq_start_bridge, _qq_send

# ── Session commands ───────────────────────────────────────────────────────
from cheetahclaws.commands.session import (
    cmd_save, cmd_load, cmd_resume, cmd_history, cmd_search,
    cmd_cloudsave, cmd_exit, save_latest, autosave_session,
)

# ── Config commands ────────────────────────────────────────────────────────
from cheetahclaws.commands.config_cmd import (
    cmd_model, cmd_config, cmd_verbose, cmd_thinking, cmd_quiet,
    cmd_permissions, cmd_auto, cmd_cwd, _interactive_ollama_picker,
    cmd_terminal_setup,
)
from cheetahclaws.commands.workspace_cmd import cmd_workspace, _apply_workspace

# ── Core commands ──────────────────────────────────────────────────────────
from cheetahclaws.commands.core import (
    cmd_help, cmd_clear, cmd_context, cmd_cost, cmd_budget, cmd_compact,
    cmd_init, cmd_export, cmd_copy, cmd_status, cmd_doctor,
    cmd_proactive, cmd_image, cmd_circuit, cmd_web, run_setup_wizard,
)

# ── Checkpoint / Plan commands ─────────────────────────────────────────────
from cheetahclaws.commands.checkpoint_plan import cmd_checkpoint, cmd_rewind, cmd_plan

# ── Advanced commands ──────────────────────────────────────────────────────
from cheetahclaws.commands.advanced import (
    cmd_brainstorm, cmd_worker, cmd_ssj, cmd_draft, cmd_summarize,
    cmd_memory, cmd_agents, cmd_skills, cmd_mcp, cmd_plugin, cmd_tasks,
    _save_synthesis, _print_background_notifications,
)

# ── Agent (autonomous loop) command ───────────────────────────────────────
from cheetahclaws.commands.agent_cmd import cmd_agent

# ── Monitor / Subscribe commands ──────────────────────────────────────────
from cheetahclaws.commands.monitor_cmd import cmd_subscribe, cmd_subscriptions, cmd_unsubscribe, cmd_monitor

from cheetahclaws.commands.research_cmd import cmd_research, cmd_reports
from cheetahclaws.commands.lab_cmd import cmd_lab

# ── Theme command ──────────────────────────────────────────────────────────
from cheetahclaws.commands.theme_cmd import cmd_theme

# ── Tools / thread-local bridge state ─────────────────────────────────────
from cheetahclaws.tools import (
    ask_input_interactive,
    _tg_thread_local, _is_in_tg_turn,
    _wx_thread_local, _is_in_wx_turn,
    _slack_thread_local, _is_in_slack_turn,
    _qq_thread_local, _is_in_qq_turn,
)

# ── Live session context (replaces config["_run_query_callback"] etc.) ─────
from cheetahclaws import runtime

def _read_version() -> str:
    """Read version from pyproject.toml (single source of truth)."""
    try:
        # pyproject.toml lives at the repo root, one level above this package.
        _toml = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for _line in _toml.read_text(encoding="utf-8").splitlines():
            if _line.startswith("version"):
                return _line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    try:
        from importlib.metadata import version as _pkg_version
        return _pkg_version("cheetahclaws")
    except Exception:
        return "0.0.0"


VERSION = _read_version()

# ── Load feature modules from modular/ ecosystem ───────────────────────────
# Commands from modular/ are merged into COMMANDS after the dict is built.
# Each module is optional — missing modules degrade gracefully.
try:
    from cheetahclaws.modular import load_all_commands as _modular_load_commands
    _MODULAR_AVAILABLE = True
except ImportError:
    _MODULAR_AVAILABLE = False
    def _modular_load_commands(): return {}  # type: ignore[misc]

# Quick availability checks for UI (help text, menus)
def _modular_has(cmd_name: str) -> bool:
    if not _MODULAR_AVAILABLE:
        return False
    try:
        from cheetahclaws import modular
        cmds = modular.load_all_commands()
        return cmd_name in cmds
    except Exception:
        return False

_VIDEO_AVAILABLE = _modular_has("video")
_VOICE_MODULAR   = _modular_has("voice")   # voice from modular (has its own cmd)

# Fallback stubs shown when a module is absent
def _missing_module_cmd(name: str):
    def _stub(args: str, _state, config) -> bool:
        warn(f"'{name}' module not available. Check modular/{name}/.")
        return True
    _stub.__name__ = f"cmd_{name}"
    return _stub


# ── Permission prompt ──────────────────────────────────────────────────────

def _compact_perm_desc(desc: str, max_len: int = 100) -> str:
    """Collapse a multi-line / very long permission description to one line.

    Quiet mode hides tool execution, so a permission prompt that dumps a whole
    heredoc script defeats the purpose. We keep the first meaningful line and
    note how many more lines were hidden, e.g.
        Run: python3 << 'PYEOF'  … (+58 行)
    """
    if not desc:
        return desc
    lines = desc.splitlines()
    first = lines[0].rstrip()
    extra = len(lines) - 1
    if len(first) > max_len:
        first = first[:max_len - 1] + "…"
    if extra > 0:
        first += f"  … (+{extra} 行)"
    return first


def ask_permission_interactive(desc: str, config: dict, signature: str = "") -> bool:
    # Inline-keyboard buttons for bridges that support them (Telegram today).
    # Terminal / Slack / WeChat ignore `options` and the [y/N/s/a] hint in the
    # prompt text keeps them functional.
    # In quiet mode, collapse multi-line commands so the approval prompt stays
    # a single tidy line instead of dumping the entire script.
    quiet = config.get("quiet", True) and not config.get("verbose", False)
    if quiet:
        desc = _compact_perm_desc(desc)
    perm_options = [
        ("✅ Approve",       "y"),
        ("❌ Reject",        "n"),
    ]
    # "s" is the scoped alternative to the blunt accept-all: it grants exactly
    # this command/file for the rest of the session, so a task that edits one
    # file forty times asks once instead of forty times — without handing over
    # the whole tool surface the way accept-all does.  "!" is the same grant
    # made permanent, so a command the user has already vouched for never
    # prompts again in any future session either.
    hint = "[y/N/a(ccept-all)/auto(=never ask again)]"
    if signature:
        perm_options.append((f"🔁 Always allow {signature} (this session)", "s"))
        perm_options.append((f"💾 Always allow {signature} (remember forever)", "!"))
        hint = (f"[y/N/s(ession: {signature})/!(remember)/a(ccept-all)/"
                f"auto(=never ask again)]")
    perm_options.append(("✅✅ Accept all (this session)", "a"))
    perm_options.append(("🚀 Auto-run everything from now on", "auto"))
    text = ask_input_interactive(
        f"  Allow: {desc}  {hint} ",
        config,
        options=perm_options,
    ).strip().lower()

    if signature and text in ("s", "session"):
        try:
            from cheetahclaws import runtime as _runtime
            _runtime.get_ctx(config).approved_sigs.add(signature)
        except Exception:
            pass   # a failed grant just means the next call asks again
        msg = f"Allowing {signature} for the rest of this session."
        if _is_in_tg_turn(config):
            _tg_send(config.get("telegram_token"), config.get("telegram_chat_id"),
                     f"🔁 {msg}")
        else:
            ok(f"  {msg}")
        return True

    if signature and text in ("!", "remember", "forever", "always"):
        from cheetahclaws.permissions import remember_signature
        remember_signature(signature, config)
        try:
            from cheetahclaws import runtime as _runtime
            _runtime.get_ctx(config).approved_sigs.add(signature)
        except Exception:
            pass
        msg = (f"Always allowing {signature} — saved, this will not be asked "
               f"again. Undo with /permissions forget {signature}")
        if _is_in_tg_turn(config):
            _tg_send(config.get("telegram_token"), config.get("telegram_chat_id"),
                     f"💾 {msg}")
        else:
            ok(f"  {msg}")
        return True

    if text in ("auto", "autonomous", "auto-run"):
        from cheetahclaws.permissions import set_auto_approve
        set_auto_approve(True, config)
        msg = ("Autonomous mode ON — tasks now run end to end without "
               "approval prompts (saved across restarts; /auto off to undo).")
        if _is_in_tg_turn(config):
            _tg_send(config.get("telegram_token"), config.get("telegram_chat_id"),
                     f"🚀 {msg}")
        else:
            ok(f"  {msg}")
        return True

    if text in ("a", "accept all", "accept-all"):
        config["permission_mode"] = "accept-all"
        if _is_in_tg_turn(config):
            token = config.get("telegram_token")
            chat_id = config.get("telegram_chat_id")
            _tg_send(token, chat_id, "✅ Permission mode set to accept-all for this session.")
        else:
            ok("  Permission mode set to accept-all for this session.")
        return True

    return text in ("y", "yes")


def _ask_permission_event(ev, config: dict) -> bool:
    """Route a PermissionRequest to the prompt, tolerating 2-arg handlers.

    ``ask_permission_interactive`` gained a third ``signature`` argument, but
    bridges, plugins and tests may hold a two-argument override of it. Calling
    those with three positionals raises a TypeError that the callers' `except`
    turns into a silent *denial* — the failure mode is invisible and looks
    like the model being blocked for no reason. Pass the signature only when
    the live callable actually accepts it.
    """
    sig = getattr(ev, "signature", "")
    fn = ask_permission_interactive   # resolved at call time: honours monkeypatching
    if sig:
        try:
            import inspect
            params = inspect.signature(fn).parameters.values()
            accepts = (len(params) >= 3
                       or any(p.kind in (inspect.Parameter.VAR_POSITIONAL,
                                         inspect.Parameter.VAR_KEYWORD)
                              for p in params))
        except (TypeError, ValueError):
            accepts = False
        if accepts:
            return fn(ev.description, config, sig)
    return fn(ev.description, config)


# ── Proactive watcher ──────────────────────────────────────────────────────

def _proactive_foreign_daemon_running() -> bool:
    """True iff a daemon other than this process owns the discovery file.

    F-5: when one is running, the daemon's :mod:`daemon.proactive_scheduler`
    fires the tick events; the REPL's own watcher must step aside so we
    don't double-fire or run on stale local state.
    """
    try:
        import os
        from cheetahclaws.daemon import discovery
        info_d = discovery.locate()
        if info_d is None:
            return False
        peer_pid = info_d.get("pid")
        return isinstance(peer_pid, int) and peer_pid != os.getpid()
    except Exception:
        return False


def _proactive_watcher_loop(config):
    """Background daemon that fires a wake-up prompt after a period of inactivity.

    F-5: when a foreign daemon is up, this loop becomes a no-op — the
    daemon's scheduler owns the cadence and emits ``proactive_tick`` on
    the SSE bus instead.
    """
    while True:
        time.sleep(1)
        if _proactive_foreign_daemon_running():
            # Daemon owns the watcher. Skip the tick and wait for the
            # next poll — discovery file disappearing flips this back.
            continue
        sctx = runtime.get_ctx(config)
        if not sctx.proactive_enabled:
            continue
        try:
            now = time.time()
            interval = sctx.proactive_interval
            last = sctx.last_interaction_time
            if now - last >= interval:
                sctx.last_interaction_time = now
                cb = sctx.run_query
                if cb:
                    cb(f"(System Automated Event) You have been inactive for {interval} seconds. "
                       "Before doing anything else, review your previous messages in this conversation. "
                       "If you said you would implement, fix, or do something and didn't finish it, "
                       "continue and complete that work now. "
                       "Otherwise, check if you have any pending tasks to execute or simply say 'No pending tasks'.")
        except Exception as e:
            from cheetahclaws import logging_utils as _log
            _log.error("proactive_watcher_error", error=str(e)[:200])


# ── Slash commands ─────────────────────────────────────────────────────────

COMMANDS = {
    "help":        cmd_help,
    "clear":       cmd_clear,
    "model":       cmd_model,
    "config":      cmd_config,
    "save":        cmd_save,
    "load":        cmd_load,
    "history":     cmd_history,
    "search":      cmd_search,
    "context":     cmd_context,
    "cost":        cmd_cost,
    "budget":      cmd_budget,
    "verbose":     cmd_verbose,
    "quiet":       cmd_quiet,
    "terminal-setup": cmd_terminal_setup,
    "thinking":    cmd_thinking,
    "permissions": cmd_permissions,
    "auto":        cmd_auto,
    "cwd":         cmd_cwd,
    "workspace":   cmd_workspace,
    "skills":      cmd_skills,
    "memory":      cmd_memory,
    "agents":      cmd_agents,
    "mcp":         cmd_mcp,
    "plugin":      cmd_plugin,
    "tasks":       cmd_tasks,
    "task":        cmd_tasks,
    "proactive":   cmd_proactive,
    "cloudsave":   cmd_cloudsave,
    # "voice" and "video" are loaded from modular/ by _load_external_commands_into()
    "image":       cmd_image,
    "img":         cmd_image,
    "brainstorm":  cmd_brainstorm,
    "summarize":   cmd_summarize,
    "draft":       cmd_draft,
    "worker":      cmd_worker,
    "agent":       cmd_agent,
    "ssj":         cmd_ssj,
    "telegram":    cmd_telegram,
    "wechat":      cmd_wechat,
    "weixin":      cmd_wechat,
    "slack":       cmd_slack,
    "qq":          cmd_qq,
    "checkpoint":  cmd_checkpoint,
    "rewind":      cmd_rewind,
    "plan":        cmd_plan,
    "subscribe":   cmd_subscribe,
    "subscriptions": cmd_subscriptions,
    "subs":        cmd_subscriptions,
    "unsubscribe": cmd_unsubscribe,
    "monitor":     cmd_monitor,
    "research":    cmd_research,
    "reports":     cmd_reports,
    "lab":         cmd_lab,
    "compact":     cmd_compact,
    "init":        cmd_init,
    "export":      cmd_export,
    "copy":        cmd_copy,
    "status":      cmd_status,
    "doctor":      cmd_doctor,
    "circuit":     cmd_circuit,
    "web":         cmd_web,
    "setup":       lambda a, s, c: (run_setup_wizard(c), True)[1],
    "theme":       cmd_theme,
    "exit":        cmd_exit,
    "quit":        cmd_exit,
    "resume":      cmd_resume,
}

# ── Load commands from modular/ ecosystem + installed plugins ──────────────
def _register_external_meta(meta_dict: dict, cmd_name: str, cmd_def: dict) -> None:
    """Populate _CMD_META for a modular/plugin command so it shows up in /help,
    tab-completion, and the system-prompt slash-command index. Without this the
    command is callable but invisible to those surfaces."""
    if cmd_name in meta_dict:
        return
    help_field = cmd_def.get("help")
    if isinstance(help_field, tuple) and len(help_field) >= 1:
        desc = help_field[0]
        subs = list(help_field[1]) if len(help_field) >= 2 and help_field[1] else []
    elif isinstance(help_field, str):
        desc, subs = help_field, []
    else:
        desc, subs = "External command", []
    meta_dict[cmd_name] = (desc, subs)


def _load_external_commands_into(commands_dict: dict) -> None:
    """Merge commands from modular/ modules and user-installed plugins into COMMANDS."""
    # 1. modular/ ecosystem (auto-discovered, ships with the project)
    try:
        for cmd_name, cmd_def in _modular_load_commands().items():
            if cmd_name not in commands_dict and callable(cmd_def.get("func")):
                commands_dict[cmd_name] = cmd_def["func"]
                _register_external_meta(_CMD_META, cmd_name, cmd_def)
                for alias in cmd_def.get("aliases", []):
                    commands_dict.setdefault(alias, cmd_def["func"])
                    _CMD_META.setdefault(alias, (f"Alias for /{cmd_name}", []))
    except Exception:
        pass

    # 2. user-installed plugins (via /plugin install)
    try:
        from cheetahclaws.plugin.loader import load_plugin_commands
        for cmd_name, cmd_def in load_plugin_commands().items():
            if cmd_name not in commands_dict and callable(cmd_def.get("func")):
                commands_dict[cmd_name] = cmd_def["func"]
                _register_external_meta(_CMD_META, cmd_name, cmd_def)
                for alias in cmd_def.get("aliases", []):
                    commands_dict.setdefault(alias, cmd_def["func"])
                    _CMD_META.setdefault(alias, (f"Alias for /{cmd_name}", []))
    except Exception:
        pass


def __getattr__(name: str):
    """Module-level __getattr__ for backward-compatible access to modular attributes.

    Exposes cmd_voice and _voice_language from modular/voice/cmd.py so that
    external code and tests can access cheetahclaws.cmd_voice and
    cheetahclaws._voice_language without the voice module being hard-coded here.
    """
    if name == "cmd_voice":
        if "voice" in COMMANDS:
            return COMMANDS["voice"]
        return _missing_module_cmd("voice")
    if name == "_voice_language":
        try:
            import cheetahclaws.modular.voice.cmd as _vc
            return _vc._voice_language
        except Exception:
            return "auto"
    raise AttributeError(f"module 'cheetahclaws' has no attribute {name!r}")


def handle_slash(line: str, state, config) -> Union[bool, tuple]:
    """Handle /command [args]. Returns True if handled, tuple (skill, args) for skill match."""
    if not line.startswith("/"):
        return False
    parts = line[1:].split(None, 1)
    if not parts:
        return False
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        result = handler(args, state, config)
        # cmd_voice/cmd_image/cmd_brainstorm/cmd_plan return sentinels to ask the REPL to run_query
        if isinstance(result, tuple) and result[0] in ("__voice__", "__image__", "__brainstorm__", "__worker__", "__ssj_cmd__", "__ssj_query__", "__ssj_debate__", "__ssj_passthrough__", "__ssj_promote_worker__", "__plan__"):
            return result
        return True

    # Fall through to skill lookup
    from cheetahclaws.skill import find_skill
    skill = find_skill(line)
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        return (skill, skill_args)

    err(f"Unknown command: /{cmd}  (type /help for commands)")
    return True


# ── Input history setup ────────────────────────────────────────────────────

# Descriptions and subcommands for each slash command (used by Tab completion)
_CMD_META: dict[str, tuple[str, list[str]]] = {
    "help":        ("Show help",                          []),
    "clear":       ("Clear conversation history",         []),
    "model":       ("Show / set model",                   []),
    "config":      ("Show / set config key=value",        []),
    "save":        ("Save session to file",               []),
    "load":        ("Load a saved session",               []),
    "history":     ("Show conversation history",          []),
    "search":      ("Search past sessions",               []),
    "context":     ("Visualize context-window usage by category", []),
    "cost":        ("Show cost estimate",                 []),
    "budget":      ("View or set token/cost budgets (session + daily)", ["session", "daily", "clear"]),
    "verbose":     ("Toggle verbose output",              []),
    "quiet":       ("Toggle compact tool display",        []),
    "thinking":    ("Toggle extended thinking",           []),
    "permissions": ("Set permission mode",                ["auto", "accept-edits", "accept-all", "manual", "plan",
                                                           "clear", "allow", "forget"]),
    "auto":        ("Run tasks end to end without approval prompts",
                                                          ["on", "off", "status"]),
    "cwd":         ("Show / change working directory",    []),
    "workspace":   ("Manage CheetahClaws workspaces",       ["list", "switch", "default", "create", "delete"]),
    "skills":      ("List available skills",              []),
    "memory":      ("Search / list / consolidate memories", ["consolidate"]),
    "agents":      ("Show background agents",             []),
    "mcp":         ("Manage MCP servers",                 ["reload", "add", "remove", "list"]),
    "plugin":      ("Manage plugins",                     ["install", "uninstall", "enable",
                                                           "disable", "disable-all", "update",
                                                           "recommend", "info"]),
    "tasks":       ("Manage tasks",                       ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "task":        ("Manage tasks (alias)",               ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "proactive":   ("Manage proactive background watcher", ["off"]),
    "cloudsave":   ("Cloud-sync sessions to GitHub Gist", ["setup", "auto", "list", "load", "push"]),
    **({"voice": ("Voice input (record → STT)", ["lang", "status", "device"])} if _VOICE_MODULAR else {}),
    **({"tts": ("AI voice generator: text → any style → audio file", ["status"])} if _VOICE_MODULAR else {}),
    "image":       ("Send clipboard image to model",      []),
    "img":         ("Send clipboard image (alias)",       []),
    "brainstorm":  ("Multi-persona AI debate + auto tasks", []),
    "summarize":   ("Multi-agent map-reduce summary of any-size file (PDF / txt / code)", []),
    "draft":       ("Draft 3 reply candidates for a message (manual copy)", []),
    "worker":      ("Auto-implement pending tasks",       []),
    "agent":       ("Autonomous agent loop (task templates)", ["start", "stop", "list", "status", "templates"]),
    "ssj":         ("SSJ Developer Mode — power menu",    []),
    "telegram":    ("Telegram bot bridge",                ["stop", "status"]),
    "wechat":      ("WeChat bridge (iLink Bot API)",      ["stop", "status"]),
    "slack":       ("Slack bot bridge (Web API)",         ["stop", "status", "logout"]),
    "qq":          ("QQ bot bridge (botpy SDK)",          ["<appid> <secret>", "stop", "status"]),
    **({"video": ("AI video factory: story→voice→images→mp4", ["status", "niches"])} if _VIDEO_AVAILABLE else {}),
    "checkpoint":  ("List / restore checkpoints",          ["clear"]),
    "rewind":      ("Rewind to checkpoint (alias)",        ["clear"]),
    "plan":        ("Enter/exit plan mode",                ["done", "status"]),
    "compact":     ("Compact conversation history",         []),
    "init":        ("Initialize CLAUDE.md template",        []),
    "export":      ("Export conversation to file",          []),
    "copy":        ("Copy last response to clipboard",      []),
    "status":      ("Show session status and model info",   []),
    "doctor":      ("Diagnose installation health",         []),
    "circuit":     ("Show / reset per-provider circuit breakers", ["status", "reset"]),
    "web":         ("Start the web terminal / chat UI in background", ["status", "--no-auth", "--host"]),
    "lab":         ("Autonomous research lab — multi-agent paper drafting + reviewer iteration",
                    ["start", "status", "abort", "logs", "resume", "iterate",
                     "backlog", "daemon", "models", "migrate-paths"]),
    "setup":       ("Run interactive setup wizard",         []),
    "theme":       ("List or set the console color theme",  []),
    "exit":        ("Exit cheetahclaws",              []),
    "quit":        ("Exit (alias for /exit)",             []),
    "resume":      ("Pick a past session by name (or id / file / 'last')",
                                                          ["last"]),
}


# Merge modular/ + plugin commands into both COMMANDS and _CMD_META.
# Must run after _CMD_META is defined so external commands show up in
# tab-completion, /help, and the system-prompt slash-command index.
_load_external_commands_into(COMMANDS)


# ── Dynamic command completers (prompt_toolkit + readline) ─────────────────

def _model_dynamic_completions(partial: str) -> list[str]:
    """Return /model completion suggestions in provider/model format.

    Mirrors the Dulus /model picker: native providers + a two-level LiteLLM
    tree. Only uses public providers that CheetahClaws already supports.
    LM Studio and custom endpoints are excluded because they are dynamic or
    user-defined.
    """
    from cheetahclaws.providers import PROVIDERS

    suggestions: list[str] = []
    partial = partial.lstrip()

    # Providers with a curated static model list (exclude dynamic/user-defined).
    static_providers = {
        pname for pname, pdata in PROVIDERS.items()
        if pdata.get("models") and pname not in {"lmstudio", "custom", "litellm"}
    }

    # Group LiteLLM models by backend for the two-level tree.
    litellm_models = PROVIDERS.get("litellm", {}).get("models", [])
    litellm_backends: dict[str, list[str]] = {}
    for m in litellm_models:
        if "/" in m:
            backend, rest = m.split("/", 1)
            litellm_backends.setdefault(backend, []).append(rest)

    if not partial:
        # First tab after `/model ` — one default model per native provider +
        # LiteLLM backend prefixes so the user can drill down.
        for pname in sorted(static_providers):
            models = PROVIDERS[pname]["models"]
            if models:
                suggestions.append(f"{pname}/{models[0]}")
        for backend in sorted(litellm_backends):
            suggestions.append(f"litellm/{backend}/")
        return suggestions[:50]

    # Native provider already typed: complete its models.
    if "/" in partial:
        provider_prefix, rest = partial.split("/", 1)
        if provider_prefix in static_providers:
            for m in PROVIDERS[provider_prefix]["models"]:
                if m.startswith(rest):
                    suggestions.append(f"{provider_prefix}/{m}")
            return suggestions[:50]

    # LiteLLM two-level tree.
    if partial.startswith("litellm/"):
        rest = partial[len("litellm/"):]
        if not rest or "/" not in rest:
            # Level 1: backends (with trailing slash to invite level 2).
            for backend in sorted(litellm_backends):
                if backend.startswith(rest):
                    suggestions.append(f"litellm/{backend}/")
            # Also offer full model strings for users who skip the slash.
            for m in litellm_models:
                if m.startswith(rest):
                    suggestions.append(f"litellm/{m}")
        else:
            # Level 2: models under chosen backend.
            backend, model_partial = rest.split("/", 1)
            for model_rest in litellm_backends.get(backend, []):
                if model_rest.startswith(model_partial):
                    suggestions.append(f"litellm/{backend}/{model_rest}")
        return suggestions[:50]

    # General fallback: match any native provider/model or LiteLLM full string.
    for pname in sorted(static_providers):
        for m in PROVIDERS[pname]["models"]:
            candidate = f"{pname}/{m}"
            if candidate.startswith(partial):
                suggestions.append(candidate)
    for m in litellm_models:
        candidate = f"litellm/{m}"
        if candidate.startswith(partial):
            suggestions.append(candidate)

    return suggestions[:50]


def _dynamic_completions_provider() -> dict:
    """Registry of dynamic command completers used by the input UI."""
    return {
        "model": _model_dynamic_completions,
    }


_rl_current_prompt = ""   # set by _read_input before each input() call


def setup_readline(history_file: Path):
    global _rl_current_prompt
    if readline is None:
        return
    try:
        readline.read_history_file(str(history_file))
    except (FileNotFoundError, PermissionError, OSError):
        pass
    readline.set_history_length(1000)
    def _save_history():
        try:
            readline.write_history_file(str(history_file))
        except Exception:
            pass
    atexit.register(_save_history)

    # Allow "/" to be part of a completion token so "/model" is one word
    delims = readline.get_completer_delims().replace("/", "")
    readline.set_completer_delims(delims)

    def completer(text: str, state: int):
        line = readline.get_line_buffer()

        # ── Completing a command name: line starts with "/" and no space yet ──
        if line.startswith("/") and " " not in line:
            matches = sorted(f"/{c}" for c in _CMD_META if f"/{c}".startswith(text))
            return matches[state] if state < len(matches) else None

        # ── Completing a subcommand: "/cmd <partial>" ─────────────────────────
        if line.startswith("/") and " " in line:
            cmd = line.split()[0][1:]          # e.g. "mcp"
            if cmd in _CMD_META:
                subs = _CMD_META[cmd][1]
                if subs:
                    matches = sorted(s for s in subs if s.startswith(text))
                    return matches[state] if state < len(matches) else None
            # Dynamic command-specific completions (e.g. /model)
            dynamic = _dynamic_completions_provider()
            completer_fn = dynamic.get(cmd)
            if completer_fn:
                matches = sorted(completer_fn(text))
                return matches[state] if state < len(matches) else None

        return None

    def display_matches(substitution: str, matches: list, longest: int):
        """Custom display: show command descriptions alongside each match."""
        sys.stdout.write("\n")
        line = readline.get_line_buffer()
        is_cmd = line.startswith("/") and " " not in line

        if is_cmd:
            col_w = max(len(m) for m in matches) + 2
            for m in sorted(matches):
                cmd = m[1:]
                desc = _CMD_META.get(cmd, ("", []))[0]
                subs = _CMD_META.get(cmd, ("", []))[1]
                sub_hint = ("  [" + ", ".join(subs[:4])
                            + ("…" if len(subs) > 4 else "") + "]") if subs else ""
                sys.stdout.write(f"  \033[36m{m:<{col_w}}\033[0m  {desc}{sub_hint}\n")
        else:
            for m in sorted(matches):
                sys.stdout.write(f"  {m}\n")
        # Redisplay prompt + current buffer so typing continues on the prompt line
        sys.stdout.write(_rl_current_prompt + readline.get_line_buffer())
        sys.stdout.flush()

    readline.set_completion_display_matches_hook(display_matches)
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")


# ── Headless bridge bootstrap (used by --web / Docker server mode) ────────

def _make_bridge_slash_handler(state, config, run_query):
    """Build the ``session_ctx.handle_slash`` callback used by Telegram /
    Slack / WeChat bridges. Calls the top-level ``handle_slash(line, state,
    config)`` and processes sentinel tuples by routing them through the
    supplied ``run_query``.

    Returns ``"simple"`` when the command finishes synchronously
    (toggle-like commands such as ``/help``, ``/status``, ``/model``) and
    ``"query"`` when a background agent run was started for a sentinel
    workflow (``__brainstorm__`` / ``__worker__``).

    Used by both ``repl()`` (interactive terminal) and
    ``_start_headless_bridges()`` (Docker / ``--web`` headless deploys) so
    the slash-command path on every bridge stays mode-agnostic.
    """
    def _handler(line: str):
        result = handle_slash(line, state, config)
        if not isinstance(result, tuple):
            return "simple"
        if result[0] == "__brainstorm__":
            _, brain_payload, brain_out_file = result
            _todo_path = str(Path(brain_out_file).parent / "todo_list.txt")
            run_query(
                brain_payload + "\n\n"
                f"Now write the todo list file at {_todo_path}.\n\n"
                "STRICT RULES:\n"
                "1. Call Write EXACTLY ONCE with the full todo content. "
                "One task per line, each starting with '- [ ] '. Order "
                "by priority. Keep names / numbers / paths intact.\n"
                "2. Do NOT call Read — there is nothing to read.\n"
                "3. Do NOT call Bash to verify the file was created.\n"
                "4. Do NOT echo the file content back after Write.\n"
                "5. After the single Write succeeds, your turn ENDS."
            )
        elif result[0] == "__worker__":
            _, worker_tasks = result
            for i, (line_idx, task_text, prompt) in enumerate(worker_tasks):
                print(clr(f"\n  ── Worker ({i+1}/{len(worker_tasks)}): "
                          f"{task_text} ──", "yellow"))
                run_query(prompt)
        return "query"
    return _handler


def _start_headless_bridges(config: dict) -> None:
    """Auto-start configured Telegram/WeChat/Slack/QQ bridges in headless mode.

    Sets up a shared ``session_ctx`` with a minimal ``run_query`` driving the
    agent loop directly (no REPL UI). Bridges keep their existing event
    hooks (``on_text_chunk``, ``on_tool_start``, ``on_tool_end``) for
    streaming output back over their channel.
    """
    if not (config.get("telegram_token") and config.get("telegram_chat_id")) \
            and not config.get("wechat_token") \
            and not (config.get("slack_token") and config.get("slack_channel")) \
            and not (config.get("qq_appid") and config.get("qq_secret")):
        return  # nothing configured — no-op

    from cheetahclaws import runtime as _runtime
    from cheetahclaws.agent import (
        AgentState, run as _agent_run,
        TextChunk, ToolStart, ToolEnd, PermissionRequest,
    )
    from cheetahclaws.context import build_system_prompt

    state = AgentState(messages=[], total_input_tokens=0, total_output_tokens=0)
    session_ctx = _runtime.get_session_ctx(config.get("_session_id", "default"))
    session_ctx.agent_state = state
    # Wire the low-level Telegram sender so ask_input_interactive can render
    # inline-keyboard permission prompts.  Without this, the Telegram branch
    # in tools/interaction.py:256 falls through to terminal input(), making
    # approval prompts invisible in headless/Docker mode (issue #84 follow-up).
    session_ctx.tg_send = _tg_send

    def _headless_run_query(prompt: str, is_background: bool = False) -> None:
        # Promote the per-turn telegram_incoming flag so _is_in_tg_turn() sees
        # in_telegram_turn=True for the duration of this query.  Without this,
        # ask_input_interactive routes prompts to the terminal even though the
        # query was triggered by an inbound Telegram message.
        session_ctx.in_telegram_turn = session_ctx.telegram_incoming
        session_ctx.telegram_incoming = False
        system_prompt = build_system_prompt(config)
        try:
            for ev in _agent_run(prompt, state, config, system_prompt):
                if isinstance(ev, TextChunk) and session_ctx.on_text_chunk:
                    try: session_ctx.on_text_chunk(ev.text)
                    except Exception: pass
                elif isinstance(ev, ToolStart) and session_ctx.on_tool_start:
                    try: session_ctx.on_tool_start(ev.name, ev.inputs or {})
                    except Exception: pass
                elif isinstance(ev, ToolEnd) and session_ctx.on_tool_end:
                    try: session_ctx.on_tool_end(ev.name, str(ev.result or "")[:500])
                    except Exception: pass
                elif isinstance(ev, PermissionRequest):
                    # Mirror repl()'s permission handling so headless deploys
                    # actually surface the [Approve][Reject][Accept all]
                    # inline-keyboard prompt over the bridge.  Defaults to
                    # denied on any failure so a broken bridge never auto-runs
                    # a sensitive tool.
                    try:
                        ev.granted = _ask_permission_event(ev, config)
                    except Exception:
                        ev.granted = False
        except Exception:
            pass  # never let a bridge query crash the server thread
        finally:
            session_ctx.in_telegram_turn = False

    session_ctx.run_query = _headless_run_query
    # Wire slash-command dispatch so bridges' /<cmd> messages don't go to
    # /dev/null. Without this, bridges/telegram.py:533+ falls through to
    # `continue` (no reply, no log) because `session_ctx.handle_slash` is
    # None — issue #84 follow-up.
    session_ctx.handle_slash = _make_bridge_slash_handler(
        state, config, _headless_run_query
    )

    # Pre-set QQ send callback so permission prompts work before the poll loop sets it.
    if config.get("qq_appid") and config.get("qq_secret"):
        session_ctx.qq_send = lambda tid, text: _qq_send(tid, text, config)

    if config.get("telegram_token") and config.get("telegram_chat_id"):
        if not (_btg._telegram_thread and _btg._telegram_thread.is_alive()):
            _btg._telegram_stop.clear()
            _btg._telegram_thread = threading.Thread(
                target=_btg._tg_poll_loop,
                args=(config["telegram_token"], config["telegram_chat_id"], config),
                daemon=True,
            )
            _btg._telegram_thread.start()

    if config.get("wechat_token"):
        if not (_bwx._wechat_thread and _bwx._wechat_thread.is_alive()):
            _wx_start_bridge(config)

    if config.get("slack_token") and config.get("slack_channel"):
        if not (_bslk._slack_thread and _bslk._slack_thread.is_alive()):
            _slack_start_bridge(config)

    if config.get("qq_appid") and config.get("qq_secret"):
        if not (_bqq._qq_thread and _bqq._qq_thread.is_alive()):
            _qq_start_bridge(config)


# ── Main REPL ──────────────────────────────────────────────────────────────

def repl(config: dict, initial_prompt: str = None):
    from cheetahclaws.config import HISTORY_FILE
    from cheetahclaws.context import build_system_prompt
    from cheetahclaws.agent import AgentState, run, TextChunk, ThinkingChunk, ToolStart, ToolEnd, TurnDone, PermissionRequest, QuotaPause

    if HAS_PROMPT_TOOLKIT:
        # Inject live providers so ui.input's completer enumerates the same
        # command set the dispatcher accepts (includes plugin/modular adds).
        _ui_input.setup(
            lambda: COMMANDS,
            lambda: _CMD_META,
            dynamic_completions_provider=_dynamic_completions_provider,
        )
    else:
        setup_readline(HISTORY_FILE)

    # prompt_toolkit's FileHistory uses an incompatible format to readline's
    # history file, so give it a sibling path. Both persist across sessions;
    # toggling CHEETAH_PT_INPUT only switches which file is active.
    PT_HISTORY_FILE = HISTORY_FILE.with_name("input_history_pt.txt")

    state = AgentState()
    verbose = config.get("verbose", False)

    # Create the per-session RuntimeContext early so all wiring uses it, not
    # the global singleton.  session_id must be set in config before any
    # bridge or tool code runs so they can look up the right context.
    from cheetahclaws import checkpoint as ckpt
    session_id = uuid.uuid4().hex[:8]
    config["_session_id"] = session_id
    session_ctx = runtime.get_session_ctx(session_id)
    session_ctx.tg_send = _tg_send
    session_ctx.agent_state = state

    ckpt.set_session(session_id)
    ckpt.cleanup_old_sessions()
    # Initial snapshot: capture the "blank slate" before any prompts
    ckpt.make_snapshot(session_id, state, config, "(initial state)", tracked_edits=None)

    # Banner
    if not initial_prompt:
        from cheetahclaws.providers import detect_provider

        # ── Cheetah startup animation ──
        _CHEETAH_FRAMES = [
            "     ✦",
            "    ✦ ·",
            "   ✦ · ·",
            "  ✦ · · ·",
            " ✦ · · · ·",
            "✦ · · · · ·",
        ]
        _CHEETAH_LOGO = [
            # CHEETAH (ansi_shadow)
            " ██████╗██╗  ██╗███████╗███████╗████████╗ █████╗ ██╗  ██╗",
            "██╔════╝██║  ██║██╔════╝██╔════╝╚══██╔══╝██╔══██╗██║  ██║",
            "██║     ███████║█████╗  █████╗     ██║   ███████║███████║",
            "██║     ██╔══██║██╔══╝  ██╔══╝     ██║   ██╔══██║██╔══██║",
            "╚██████╗██║  ██║███████╗███████╗   ██║   ██║  ██║██║  ██║",
            " ╚═════╝╚═╝  ╚═╝╚══════╝╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝",
            # CLAWS, centered under CHEETAH
            "         ██████╗██╗      █████╗ ██╗    ██╗███████╗",
            "        ██╔════╝██║     ██╔══██╗██║    ██║██╔════╝",
            "        ██║     ██║     ███████║██║ █╗ ██║███████╗",
            "        ██║     ██║     ██╔══██║██║███╗██║╚════██║",
            "        ╚██████╗███████╗██║  ██║╚███╔███╔╝███████║",
            "         ╚═════╝╚══════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝",
        ]
        _CHEETAH_GRADIENT = [  # warm cheetah-gold vertical gradient (top -> bottom)
            "#FFE082", "#FFD54F", "#FFCA28", "#FFB300", "#FFA000", "#FF8F00",
            "#FB8C00", "#F57C00", "#EF6C00", "#E65100", "#DD4B0E", "#D84315",
        ]

        # Spinning galaxy animation
        _GALAXY_FRAMES = ["◜", "◝", "◞", "◟"]
        try:
            for i in range(8):
                frame = _GALAXY_FRAMES[i % 4]
                sys.stdout.write(f"\r  {clr(frame, 'cyan', 'bold')} Initializing Cheetah...")
                sys.stdout.flush()
                time.sleep(0.12)
            sys.stdout.write(f"\r{' ' * 40}\r")
            sys.stdout.flush()
        except Exception:
            pass

        # Blank line so the logo sits a little farther below the shell prompt.
        print()

        # Print logo - warm cheetah-gold vertical gradient, plain if color is off.
        if C["reset"]:
            for _ln, _hex in zip(_CHEETAH_LOGO, _CHEETAH_GRADIENT):
                print(C["bold"] + _rgb(_hex) + _ln + C["reset"])
        else:
            for _ln in _CHEETAH_LOGO:
                print(_ln)
        print()

        model    = config["model"]
        pname    = detect_provider(model)
        model_clr = clr(model, "cyan", "bold")
        prov_clr  = clr(f"({pname})", "dim")
        from cheetahclaws.permissions import auto_approve_on as _auto_on
        # Autonomy is the default and silent; the banner calls out the state
        # that would otherwise be a surprise — that this session *will* stop
        # and ask. (ASCII only: an emoji is 2 terminal columns but len()==1,
        # which would skew the box-drawing width maths below.)
        _pmode_plain = config.get("permission_mode", "auto")
        if not _auto_on(config) or _pmode_plain in ("manual", "plan"):
            _pmode_plain += "  (asks before acting)"
        pmode     = clr(_pmode_plain, "yellow")
        ver_clr   = clr(f"v{VERSION}", "green")
        out_mode  = "quiet" if (config.get("quiet", True) and not config.get("verbose", False)) else "full"
        out_clr   = clr(out_mode, "cyan")

        # ── Banner: aligned box ─────────────────────────────────────────
        # Compute widths from plain text (strip ANSI escapes from coloring).
        title_plain = f"CheetahClaws v{VERSION}"
        line_plains = [
            f"  Model: {model} ({pname})",
            f"  Permissions: {_pmode_plain}",
            f"  Output: {out_mode}",
            f"  /model to switch · /help for commands",
        ]
        # Inner width = widest content; title needs 3 chars of decoration ("─ X ").
        inner_w = max(len(title_plain) + 6, *(len(p) for p in line_plains)) + 2
        # Don't shrink below the previous visual width.
        inner_w = max(inner_w, 56)

        # Top: ╭─ CheetahClaws vX ─...─╮
        title_decoration_width = 3 + len(title_plain)  # "─ TITLE "
        top_trailing = "─" * (inner_w - title_decoration_width)
        print(
            clr("  ╭", "dim")
            + clr("─ ", "dim")
            + clr("CheetahClaws ", "cyan", "bold")
            + ver_clr
            + clr(" ", "dim")
            + clr(top_trailing + "╮", "dim")
        )

        # Middle lines — each must close with │, padded to inner_w on the right.
        def _row(colored: str, plain: str) -> str:
            pad = " " * (inner_w - len(plain))
            return clr("  │", "dim") + colored + pad + clr("│", "dim")

        print(_row(clr("  Model: ", "dim") + model_clr + " " + prov_clr, line_plains[0]))
        print(_row(clr("  Permissions: ", "dim") + pmode,                 line_plains[1]))
        print(_row(clr("  Output: ", "dim") + out_clr,                    line_plains[2]))
        print(_row(clr(line_plains[3], "dim"),                            line_plains[3]))

        # Bottom: ╰─...─╯ (same inner_w as top)
        print(clr("  ╰" + "─" * inner_w + "╯", "dim"))

        # Show active non-default settings
        active_flags = []
        if config.get("verbose"):
            active_flags.append("verbose")
        if config.get("thinking"):
            active_flags.append("thinking")
        if session_ctx.proactive_enabled:
            active_flags.append("proactive")
        if config.get("telegram_token") and config.get("telegram_chat_id"):
            active_flags.append("telegram")
        if config.get("wechat_token"):
            active_flags.append("wechat")
        if config.get("slack_token") and config.get("slack_channel"):
            active_flags.append("slack")
        if config.get("qq_appid") and config.get("qq_secret"):
            active_flags.append("qq")
        if active_flags:
            flags_str = " · ".join(clr(f, "green") for f in active_flags)
            info(f"Active: {flags_str}")
        print()

    query_lock = threading.RLock()

    # Pick the streaming tier for this device (see ui.render.auto_stream_mode):
    #   "live"   — full in-place Rich redraw (capable terminals, incl. modern
    #              emulators over SSH like iTerm2 / WezTerm / Windows Terminal /
    #              VSCode / kitty / Alacritty / Ghostty).
    #   "commit" — append-only progressive Markdown for terminals where cursor-up
    #              redraw is unsafe (Apple Terminal, unknown SSH PTYs, pipes). Still
    #              renders rich formatting block-by-block — a big upgrade over the
    #              old raw-token fallback.
    #   "plain"  — only when Rich is unavailable.
    # An explicit `stream_mode` or legacy `rich_live` config value overrides detection.
    set_stream_mode(auto_stream_mode(config))

    # Apply spinner_tips config: rotating Claude-Code-style tips beneath the
    # spinner. Disabled automatically where multi-line cursor moves misbehave
    # (dumb terminals, macOS Terminal.app) so the tip line never garbles output.
    import os as _os, platform as _plat
    _is_dumb = (console is not None and getattr(console, "is_dumb_terminal", False))
    _is_macos_terminal = (_plat.system() == "Darwin"
                          and _os.environ.get("TERM_PROGRAM", "") in ("Apple_Terminal", ""))
    _spinner_tips_default = not _is_dumb and not _is_macos_terminal
    set_spinner_tips(config.get("spinner_tips", _spinner_tips_default))

    # Claude-Code-style terminal tab title: pulses while working, static when
    # idle, and reads out the current task instead of the shell default.
    # Auto-disabled on non-TTYs by set_terminal_title_enabled.
    set_terminal_title_enabled(config.get("terminal_title", True))
    # VS Code hides program-set titles by default; offer to flip the one
    # setting that surfaces them — once, safely, only inside VS Code/Cursor/
    # Windsurf. No-op elsewhere. See ui/vscode_setup.py.
    try:
        from cheetahclaws.ui.vscode_setup import maybe_setup_vscode_terminal_title
        maybe_setup_vscode_terminal_title(config)
    except Exception:
        pass

    # Initialize proactive polling state via RuntimeContext (defaults already set)
    session_ctx.last_interaction_time = time.time()
    if session_ctx.proactive_thread is None:
        t = threading.Thread(target=_proactive_watcher_loop, args=(config,), daemon=True)
        session_ctx.proactive_thread = t
        t.start()

    def run_query(user_input: str, is_background: bool = False):
        nonlocal verbose

        with query_lock:
            verbose = config.get("verbose", False)
            # Quiet mode (Claude-Code-style): hide per-tool execution lines and
            # show one summary line per turn. Verbose always overrides it.
            quiet = config.get("quiet", True) and not verbose
            set_quiet(quiet)
            set_markdown_rules(config.get("markdown_rules", False))
            reset_turn_stats()
            # Live token meter (estimated) + real per-turn totals for the footer.
            set_spinner_tokens(0)
            turn_start = time.monotonic()
            turn_in_tokens = 0
            turn_out_tokens = 0
            quota_paused = False    # set when a budget is reached mid-turn
            streamed_chars = 0

            # Rebuild system prompt each turn (picks up cwd changes, etc.)
            system_prompt = build_system_prompt(config)

            if is_background and not (session_ctx.telegram_incoming or session_ctx.qq_incoming):
                print(clr("\n\n[Background Event Triggered]", "yellow"))
            session_ctx.in_telegram_turn = session_ctx.telegram_incoming
            session_ctx.telegram_incoming = False
            session_ctx.in_qq_turn = session_ctx.qq_incoming
            session_ctx.qq_incoming = False

            print(clr("\n╭─ CheetahClaws ", "dim") + clr("●", "green") + clr(" ─────────────────────────", "dim"))

            thinking_started = False
            spinner_shown = True
            # Terminal tab title: show what the user is doing + start the pulse.
            if not is_background:
                set_task_title(user_input)
            terminal_working_start()
            _start_tool_spinner()
            _pre_tool_text = []   # text chunks before a tool call
            _post_tool = False    # true after a tool has executed
            _post_tool_buf = []   # text chunks after tool (to check for duplicates)
            _duplicate_suppressed = False

            try:
                for event in run(user_input, state, config, system_prompt):
                    # Live token meter: estimate output tokens from streamed
                    # text + reasoning so the spinner can show "↓ N tokens"
                    # while the model is still working (real usage only lands
                    # at TurnDone). Accumulates across the whole user-turn.
                    if isinstance(event, (TextChunk, ThinkingChunk)):
                        streamed_chars += len(getattr(event, "text", "") or "")
                        set_spinner_tokens(streamed_chars // 4)
                        # Reasoning models stream thinking while the spinner is
                        # still up — label it so it reads "Thinking… (7s · ↓ N tokens)".
                        if isinstance(event, ThinkingChunk) and spinner_shown and not verbose:
                            set_spinner_phrase("Thinking")

                    # Stop spinner only when visible output arrives
                    if spinner_shown:
                        show_thinking = isinstance(event, ThinkingChunk) and verbose
                        # In quiet mode a ToolStart prints nothing, so keep the
                        # spinner alive (it just updates its phrase) instead of
                        # tearing it down and redrawing it for every tool.
                        tool_breaks_spinner = isinstance(event, ToolStart) and not quiet
                        if isinstance(event, TextChunk) or show_thinking or tool_breaks_spinner:
                            _stop_tool_spinner()
                            spinner_shown = False
                            # Quiet mode: emit the tool summary at the tool→text
                            # boundary so it sits just above the reply, the way
                            # Claude Code does. No-op if no tools are pending.
                            if quiet and isinstance(event, TextChunk) and _post_tool:
                                print_turn_summary()
                            # Restore │ prefix for first text chunk in plain-text (non-Rich) mode
                            if isinstance(event, TextChunk) and not _RICH and not _post_tool:
                                print(clr("│ ", "dim"), end="", flush=True)

                    if isinstance(event, TextChunk):
                        if thinking_started:
                            print("\033[0m\n")  # Reset dim ANSI + break line after thinking block
                            thinking_started = False

                        if _post_tool and not _duplicate_suppressed:
                            # Buffer post-tool text to check for duplicates
                            _post_tool_buf.append(event.text)
                            post_so_far = "".join(_post_tool_buf).strip()
                            pre_text = "".join(_pre_tool_text).strip()
                            # If post-tool text matches start of pre-tool text, suppress
                            if pre_text and pre_text.startswith(post_so_far):
                                if len(post_so_far) >= len(pre_text):
                                    # Full duplicate confirmed — suppress entirely
                                    _duplicate_suppressed = True
                                    _post_tool_buf.clear()
                                continue
                            elif post_so_far and not pre_text.startswith(post_so_far):
                                # Not a duplicate — flush buffered text
                                for chunk in _post_tool_buf:
                                    stream_text(chunk)
                                _post_tool_buf.clear()
                                _duplicate_suppressed = True  # stop checking
                                continue

                        # stream_text auto-starts Live on first chunk when Rich available
                        if not _post_tool:
                            _pre_tool_text.append(event.text)
                        stream_text(event.text)
                        # Fire bridge streaming hook
                        _hook = session_ctx.on_text_chunk
                        if _hook:
                            try:
                                _hook(event.text)
                            except Exception:
                                pass

                    elif isinstance(event, ThinkingChunk):
                        if verbose:
                            if not thinking_started:
                                flush_response()  # stop Live before printing static thinking
                                print(clr("  [thinking]", "dim"))
                                thinking_started = True
                            stream_thinking(event.text, verbose)

                    elif isinstance(event, ToolStart):
                        flush_response()
                        print_tool_start(event.name, event.inputs, verbose)
                        _hook = session_ctx.on_tool_start
                        if _hook:
                            try:
                                _hook(event.name, event.inputs or {})
                            except Exception:
                                pass

                    elif isinstance(event, PermissionRequest):
                        _stop_tool_spinner()
                        flush_response()
                        event.granted = _ask_permission_event(event, config)
                        # Live will restart automatically on next TextChunk

                    elif isinstance(event, ToolEnd):
                        print_tool_end(event.name, event.result, verbose)
                        _hook = session_ctx.on_tool_end
                        if _hook:
                            try:
                                _hook(event.name, str(event.result or "")[:500])
                            except Exception:
                                pass
                        _post_tool = True
                        _post_tool_buf.clear()
                        _duplicate_suppressed = False
                        if not _RICH:
                            print(clr("│ ", "dim"), end="", flush=True)
                        # Restart spinner while waiting for model's next action
                        _change_spinner_phrase()
                        _start_tool_spinner()
                        spinner_shown = True

                    elif isinstance(event, TurnDone):
                        _stop_tool_spinner()
                        spinner_shown = False
                        # Real usage (a turn may fire several TurnDone events
                        # across tool round-trips — accumulate for the footer).
                        turn_in_tokens += event.input_tokens
                        turn_out_tokens += event.output_tokens
                        if quiet:
                            flush_response()  # commit final text before summary
                            print_turn_summary()
                        if verbose:
                            flush_response()  # stop Live before printing token info
                            print(clr(
                                f"\n  [tokens: +{event.input_tokens} in / "
                                f"+{event.output_tokens} out]", "dim"
                            ))

                    elif isinstance(event, QuotaPause):
                        # A configured budget was reached BEFORE making the next
                        # (billable) call. Auto-save so nothing is lost, then tell
                        # the user how to resume or raise the budget and continue.
                        _stop_tool_spinner()
                        spinner_shown = False
                        flush_response()
                        quota_paused = True
                        print()
                        print(clr(f"  ⛔ Budget reached — {event.reason}", "yellow", "bold"))
                        # save_latest() prints the saved paths itself — don't echo.
                        try:
                            from cheetahclaws.commands.session import save_latest
                            save_latest("", state, config)
                        except Exception:
                            pass
                        # Suggest raising the cap that actually broke, in its own
                        # unit/scope — a token cap can't be lifted with a $ amount.
                        try:
                            from cheetahclaws import quota as _q
                            _pre = "daily " if event.scope == "daily" else ""
                            _amt = _q.fmt_amount((event.limit or 0) * 2, event.unit or "tok")
                            _raise_cmd = f"/budget {_pre}{_amt}" if event.limit else "/budget 40k"
                        except Exception:
                            _raise_cmd = "/budget 40k"
                        print(clr("  To continue:", "bold"))
                        print("    • raise it:   " + clr(_raise_cmd, "cyan")
                              + "  (or " + clr("/budget clear", "cyan") + "), then resend your message")
                        print("    • later:      restart and run " + clr("/resume", "cyan")
                              + " to pick up where you left off")
                        print("    • view usage: " + clr("/budget", "cyan"))
            except KeyboardInterrupt:
                _stop_tool_spinner()
                flush_response()
                raise  # propagate to REPL handler which calls _track_ctrl_c
            except Exception as e:
                _stop_tool_spinner()
                flush_response()
                import urllib.error
                # Catch 404 Not Found (Ollama model missing)
                if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                    from cheetahclaws.providers import detect_provider
                    if detect_provider(config["model"]) == "ollama":
                        err(f"Ollama model '{config['model']}' not found.")
                        if _interactive_ollama_picker(config):
                            if state.messages and state.messages[-1]["role"] == "user":
                                state.messages.pop()
                            return run_query(user_input, is_background)
                        terminal_working_stop()  # idle title on early exit
                        return
                # ── Actionable error messages via error classifier ────────
                from cheetahclaws.error_classifier import classify as _classify_err
                cerr = _classify_err(e)
                err(f"Error: {type(e).__name__}: {_truncate_err_global(str(e))}")
                if cerr.hint:
                    warn(f"Hint: {cerr.hint}")
                warn("Your conversation is intact. You can retry or type a new message.")

            _stop_tool_spinner()
            terminal_working_stop()  # turn done → static idle tab title
            set_spinner_tokens(0)  # clear the live meter for the next turn
            flush_response()  # stop Live, commit any remaining text
            # Quiet-mode footer: real elapsed time + token usage for the turn.
            # Verbose already prints per-turn token lines, so skip it there.
            if quiet:
                print_turn_stats(time.monotonic() - turn_start,
                                 turn_in_tokens, turn_out_tokens,
                                 show_input=config.get("stats_show_input", False))
            # Budget proximity warnings (≥80% / ≥95%) — heads-up before the hard
            # stop arrives. Skipped when this turn already hit the cap.
            if not quota_paused:
                try:
                    from cheetahclaws import quota as _quota
                    for _level, _msg in _quota.warnings(config.get("_session_id", "default"), config):
                        (err if _level == "crit" else warn)(f"  ⚠ Budget: {_msg} — /budget to view")
                except Exception:
                    pass
            print(clr("╰──────────────────────────────────────────────", "dim"))
            print()

            # If this was a background task, we redraw the prompt for the user
            if is_background:
                print(clr(f"\n[{Path.cwd().name}] » ", "yellow"), end="", flush=True)

                # If Telegram is connected and this background task didn't originate from a live Telegram query,
                # forward the alert to the Telegram user so they are notified!
                is_tg_turn = session_ctx.in_telegram_turn
                ttok = config.get("telegram_token")
                tchat = config.get("telegram_chat_id")
                if not is_tg_turn and ttok and tchat:
                    if state.messages and state.messages[-1].get("role") == "assistant":
                        ans_content = state.messages[-1].get("content", "")
                        if isinstance(ans_content, list):
                            parts = [b["text"] if isinstance(b, dict) else str(b) for b in ans_content if (isinstance(b, dict) and b.get("type") == "text") or isinstance(b, str)]
                            ans_content = "\n".join(parts)
                        if ans_content:
                            _tg_send(ttok, tchat, ans_content)

        # ── Auto-snapshot after each turn ──
        try:
            tracked = ckpt.get_tracked_edits()
            # Throttle: skip snapshot only if no files changed AND no new messages
            last_snaps = ckpt.list_snapshots(session_id)
            skip = False
            if not tracked and last_snaps:
                if len(state.messages) == last_snaps[-1].get("message_index", -1):
                    skip = True
            if not skip:
                ckpt.make_snapshot(session_id, state, config, user_input, tracked_edits=tracked)
            ckpt.reset_tracked()
        except Exception:
            pass  # never let checkpoint errors break the REPL

        # ── Silent autosave so a crash/power-loss mid-conversation is
        # recoverable via /resume. Only rewrites session_latest.json; the
        # loud daily/history save still happens once on exit (save_latest).
        autosave_session(state, config)

        session_ctx.last_interaction_time = time.time()

        # ── Predicted next prompt ──
        # Drafts (in the background) the line the user most likely types next
        # and shows it as dim ghost text at the prompt; Tab accepts it.
        # Background turns don't own the prompt, so they never draft one.
        if not is_background:
            try:
                from cheetahclaws.ui import suggest as _ui_suggest
                _ui_suggest.schedule(state.messages, config)
            except Exception:
                pass

    session_ctx.run_query = lambda msg: run_query(msg, is_background=True)
    # Same handler used by the headless bridges path — see
    # `_make_bridge_slash_handler` for sentinel processing.
    session_ctx.handle_slash = _make_bridge_slash_handler(
        state, config, run_query
    )

    # ── Auto-start Telegram bridge if configured ──────────────────────
    if config.get("telegram_token") and config.get("telegram_chat_id"):
        if not (_btg._telegram_thread and _btg._telegram_thread.is_alive()):
            _btg._telegram_stop.clear()
            _btg._telegram_thread = threading.Thread(
                target=_btg._tg_poll_loop,
                args=(config["telegram_token"], config["telegram_chat_id"], config),
                daemon=True
            )
            _btg._telegram_thread.start()

    # ── Auto-start WeChat bridge if configured ────────────────────────
    if config.get("wechat_token"):
        if not (_bwx._wechat_thread and _bwx._wechat_thread.is_alive()):
            _wx_start_bridge(config)

    # ── Auto-start Slack bridge if configured ─────────────────────────
    if config.get("slack_token") and config.get("slack_channel"):
        if not (_bslk._slack_thread and _bslk._slack_thread.is_alive()):
            _slack_start_bridge(config)

    # ── Auto-start QQ bridge if configured ────────────────────────────
    if config.get("qq_appid") and config.get("qq_secret"):
        if not (_bqq._qq_thread and _bqq._qq_thread.is_alive()):
            _qq_start_bridge(config)

    # ── Rapid Ctrl+C force-quit ─────────────────────────────────────────
    # 3 Ctrl+C presses within 2 seconds → immediate hard exit
    _ctrl_c_times = []

    def _track_ctrl_c():
        """Call this on every KeyboardInterrupt. Returns True if force-quit triggered."""
        now = time.time()
        _ctrl_c_times.append(now)
        # Keep only presses within the last 2 seconds
        _ctrl_c_times[:] = [t for t in _ctrl_c_times if now - t <= 2.0]
        if len(_ctrl_c_times) >= 3:
            _stop_tool_spinner()
            clear_terminal_title()   # os._exit bypasses the atexit handler
            print(clr("\n\n  Force quit (3x Ctrl+C).", "red", "bold"))
            os._exit(1)
        return False

    # ── Main loop ──
    if initial_prompt:
        try:
            run_query(initial_prompt)
        except KeyboardInterrupt:
            _track_ctrl_c()
            print()
        return

    # ── Bracketed paste mode ──────────────────────────────────────────────
    # Terminals that support bracketed paste wrap pasted content with
    #   ESC[200~  (start)  …content…  ESC[201~  (end)
    _PASTE_START = "\x1b[200~"
    _PASTE_END   = "\x1b[201~"
    _bpm_active  = sys.stdin.isatty() and sys.platform != "win32"

    if _bpm_active:
        sys.stdout.write("\x1b[?2004h")   # enable bracketed paste mode
        sys.stdout.flush()

    def _read_input(prompt: str) -> str:
        """Read one user turn, collecting multi-line pastes as a single string."""
        global _rl_current_prompt
        import select as _sel

        # ── Phase 1a: prompt_toolkit (TTY + library available + not opted out) ─
        # Handles bracketed paste natively, so phase-2/3 are skipped on success.
        # Preserves the "(pasted N lines)" notification for parity with the
        # readline-based paste handling in phase 2/3.
        if (
            HAS_PROMPT_TOOLKIT
            and sys.stdin.isatty()
            and os.environ.get("CHEETAH_PT_INPUT", "1") != "0"
        ):
            try:
                result = _pt_read_line(prompt, PT_HISTORY_FILE)
                if "\n" in result:
                    n = result.count("\n") + 1
                    info(f"  (pasted {n} line{'s' if n > 1 else ''})")
                return result
            except (EOFError, KeyboardInterrupt):
                raise
            except Exception as _pt_err:
                warn(
                    f"prompt_toolkit failed ({type(_pt_err).__name__}: {_pt_err}); "
                    "falling back to readline"
                )
                _ui_input.reset_session()
                # fall through to phase 1b

        # ── Phase 1b: get first line via readline (history, line-edit intact) ──
        # Wrap ANSI codes so readline counts them as zero-width (#29/#31).
        rl_prompt = re.sub(r'(\x1b\[[0-9;]*m)', r'\001\1\002', prompt)
        _rl_current_prompt = prompt   # for display_matches to redisplay
        first = input(rl_prompt)

        # ── Phase 2: bracketed paste? ─────────────────────────────────────────
        if _PASTE_START in first:
            # Strip leading marker; first line may already contain paste end too
            body = first.replace(_PASTE_START, "")
            if _PASTE_END in body:
                # Single-line paste (no embedded newlines)
                return body.replace(_PASTE_END, "").strip()

            # Multi-line paste: keep reading until end marker arrives
            lines = [body]
            while True:
                ready = _sel.select([sys.stdin], [], [], 2.0)[0]
                if not ready:
                    break  # safety timeout — paste stalled
                raw = sys.stdin.readline()
                if not raw:
                    break
                raw = raw.rstrip("\n")
                if _PASTE_END in raw:
                    tail = raw.replace(_PASTE_END, "")
                    if tail:
                        lines.append(tail)
                    break
                lines.append(raw)

            result = "\n".join(lines).strip()
            n = result.count("\n") + 1
            info(f"  (pasted {n} line{'s' if n > 1 else ''})")
            return result

        # ── Phase 3: timing fallback ─────────────────────────────────────────
        if sys.stdin.isatty():
            lines = [first]
            import time as _time

            if sys.platform == "win32":
                # Windows: use msvcrt.kbhit() to detect buffered paste data
                import msvcrt
                deadline = 0.12   # wider window for Windows paste latency
                chunk_to = 0.03
                t0 = _time.monotonic()
                while (_time.monotonic() - t0) < deadline:
                    _time.sleep(chunk_to)
                    if not msvcrt.kbhit():
                        break
                    raw = sys.stdin.readline()
                    if not raw:
                        break
                    stripped = raw.rstrip("\n").rstrip("\r")
                    lines.append(stripped)
                    t0 = _time.monotonic()  # extend while data keeps coming
            else:
                # Unix: use select() for precise timing
                deadline = 0.06
                chunk_to = 0.025
                t0 = _time.monotonic()
                while (_time.monotonic() - t0) < deadline:
                    ready = _sel.select([sys.stdin], [], [], chunk_to)[0]
                    if not ready:
                        break
                    raw = sys.stdin.readline()
                    if not raw:
                        break
                    stripped = raw.rstrip("\n")
                    if _PASTE_END in stripped:
                        break
                    lines.append(stripped)
                    t0 = _time.monotonic()

            if len(lines) > 1:
                result = "\n".join(lines).strip()
                info(f"  (pasted {len(lines)} lines)")
                return result

        return first

    while True:
        # Show notifications for background agents that finished
        _print_background_notifications()
        try:
            cwd_short = Path.cwd().name
            # Context usage indicator in prompt
            ctx_hint = ""
            try:
                from cheetahclaws.compaction import estimate_tokens, get_context_limit
                used = estimate_tokens(state.messages)
                limit = get_context_limit(config.get("model", ""), config)
                pct = int(used / limit * 100) if limit else 0
                if pct >= 70:
                    ctx_hint = clr(f" {pct}%", "red")
                elif pct >= 40:
                    ctx_hint = clr(f" {pct}%", "yellow")
                elif state.messages:
                    ctx_hint = clr(f" {pct}%", "dim")
            except Exception:
                pass
            try:
                _cols = os.get_terminal_size().columns
            except OSError:
                _cols = 80
            print(clr("─" * _cols, "dim"))
            prompt = clr(f"[{cwd_short}]", "dim") + ctx_hint + clr(" ", "dim") + clr("» ", "cyan", "bold")
            terminal_working_stop()  # safety net: idle title whenever we await input
            user_input = _read_input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            try:
                save_latest("", state, config)
            except Exception as e:
                warn(f"Auto-save failed on exit: {e}")
            if _bpm_active:
                sys.stdout.write("\x1b[?2004l")  # disable bracketed paste mode
                sys.stdout.flush()
            ok("Goodbye!")
            sys.exit(0)

        if not user_input:
            continue

        # ── Shell escape: !command runs directly in the system shell ──
        if user_input.startswith("!"):
            shell_cmd = user_input[1:].strip()
            if shell_cmd:
                # Defense against bracketed-paste / clipboard injection: reject
                # NUL bytes, ASCII control chars (except tab), and excessive
                # length. Normal interactive commands never contain these.
                if "\x00" in shell_cmd or any(
                    (c < " " and c != "\t") for c in shell_cmd
                ):
                    warn("Shell escape: rejected control characters in command.")
                    continue
                if len(shell_cmd) > 4096:
                    warn("Shell escape: command exceeds 4096 chars; refusing.")
                    continue
                print(clr(f"  $ {shell_cmd}", "dim"))
                try:
                    import subprocess as _sp
                    _sp.run(shell_cmd, shell=True)
                except Exception as e:
                    warn(f"Shell error: {e}")
            continue

        # Strip leading whitespace so a paste with a stray space (e.g.
        # ` /lab daemon start`) still hits the slash dispatcher instead
        # of being routed to the agent. Trailing whitespace is preserved
        # so command arguments aren't accidentally rstripped.
        if user_input != user_input.lstrip():
            user_input = user_input.lstrip()
        # Wrap in KeyboardInterrupt guard so Ctrl+C during a slow
        # synchronous slash command (/monitor run, /research, /trading
        # backtest, etc.) just cancels that command and returns to the
        # prompt, instead of unwinding the whole REPL → main() → process.
        # The previous behavior printed a traceback through atexit and
        # left the user at a bash shell.
        try:
            result = handle_slash(user_input, state, config)
        except KeyboardInterrupt:
            _track_ctrl_c()
            print(clr("\n  (command interrupted)", "yellow"))
            continue
        # ── Sentinel processing loop ──
        # Processes sentinel tuples returned by commands. SSJ-originated
        # sentinels loop back to the SSJ menu after completion.
        while isinstance(result, tuple):
            # Voice sentinel: ("__voice__", transcribed_text)
            if result[0] == "__voice__":
                _, voice_text = result
                try:
                    run_query(voice_text)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                break
            # Image sentinel: ("__image__", prompt_text)
            if result[0] == "__image__":
                _, image_prompt = result
                try:
                    run_query(image_prompt)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                break

            # Plan sentinel: ("__plan__", description)
            if result[0] == "__plan__":
                _, plan_desc = result
                try:
                    run_query(f"Please analyze the codebase and create a detailed implementation plan for: {plan_desc}")
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                break

            # SSJ passthrough: user typed a /command inside SSJ menu
            if result[0] == "__ssj_passthrough__":
                _, slash_line = result
                # Guard against /ssj re-entering itself infinitely
                if slash_line.strip().lower() == "/ssj":
                    result = handle_slash("/ssj", state, config)
                    continue
                try:
                    inner = handle_slash(slash_line, state, config)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (command interrupted)", "yellow"))
                    result = handle_slash("/ssj", state, config)
                    continue
                if isinstance(inner, tuple):
                    result = inner
                    continue
                break

            # SSJ command sentinel: ("__ssj_cmd__", cmd_name, args)
            # Delegate to the real command and re-process its returned sentinel
            if result[0] == "__ssj_cmd__":
                _, cmd_name, cmd_args = result
                try:
                    inner = handle_slash(f"/{cmd_name} {cmd_args}".strip(), state, config)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (command interrupted)", "yellow"))
                    result = handle_slash("/ssj", state, config)
                    continue
                if isinstance(inner, tuple):
                    # Tag so we know to loop back to SSJ after processing
                    result = ("__ssj_wrap__", inner)
                    continue
                # Command handled directly, loop back to SSJ
                result = handle_slash("/ssj", state, config)
                continue

            # Unwrap SSJ-wrapped sentinel and process the inner sentinel
            if result[0] == "__ssj_wrap__":
                result = result[1]
                _from_ssj_flag = True
            else:
                _from_ssj_flag = result[0] == "__ssj_query__"

            # Brainstorm sentinel: ("__brainstorm__", todo_payload, out_file)
            # The lead moderator now does opening + probe + synthesis inside
            # cmd_brainstorm and writes everything to out_file. todo_payload
            # already inlines the master plan, so the main agent only needs
            # to write the TODO file — no Read, no re-synthesis. This
            # eliminates the duplicate-Read pattern that weak models like
            # qwen2.5 fell into when asked to Read-then-rewrite.
            if result[0] == "__brainstorm__":
                _, brain_payload, brain_out_file = result
                _todo_path = str(Path(brain_out_file).parent / "todo_list.txt")
                print(clr("\n  ── Generating TODO List from Lead Synthesis ──", "dim"))
                try:
                    run_query(
                        brain_payload + "\n\n"
                        f"Now write the todo list file at {_todo_path}.\n\n"
                        "STRICT RULES:\n"
                        "1. Call Write EXACTLY ONCE with the full todo content. "
                        "Format: one task per line, each starting with '- [ ] '. "
                        "Order by priority. Include every concrete action from "
                        "the master plan above (keep names / numbers / paths "
                        "intact — do NOT generalize).\n"
                        "2. Do NOT call Read — there is nothing to read.\n"
                        "3. Do NOT call Bash to verify the file was created. "
                        "The Write tool's success message is sufficient.\n"
                        "4. Do NOT echo the file content back as text after "
                        "Write succeeds. The file is on disk; the user can "
                        "open it themselves.\n"
                        "5. After the single Write succeeds, your turn ENDS. "
                        "Do not write any further text. Do not summarize. "
                        "Do not ask follow-up questions."
                    )
                    info(f"TODO list saved to {_todo_path}. Edit it freely, then use /worker to start implementing.")
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                if _from_ssj_flag:
                    result = handle_slash("/ssj", state, config)
                    continue
                break

            # Promote-then-Worker: generate todo_list.txt from brainstorm .md, then run worker
            if result[0] == "__ssj_promote_worker__":
                _, md_path, todo_path_str, task_nums_str, max_workers_str = result
                promote_prompt = (
                    f"Read the brainstorm file {md_path} and extract all actionable ideas. "
                    f"Convert each idea into a task with checkbox format (- [ ] task description). "
                    f"Write them to {todo_path_str} using the Write tool. Prioritize by impact. "
                    f"Do NOT explain, just write the file now."
                )
                print(clr(f"\n  ── Generating TODO list from {Path(md_path).name} ──", "dim"))
                try:
                    run_query(promote_prompt)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                    result = handle_slash("/ssj", state, config)
                    continue
                # Now run worker on the newly created file
                worker_args = f"--path {todo_path_str}"
                if task_nums_str:
                    worker_args += f" --tasks {task_nums_str}"
                if max_workers_str and max_workers_str.isdigit():
                    worker_args += f" --workers {max_workers_str}"
                inner = handle_slash(f"/worker {worker_args}".strip(), state, config)
                if isinstance(inner, tuple):
                    result = ("__ssj_wrap__", inner)
                    continue
                result = handle_slash("/ssj", state, config)
                continue

            # Worker sentinel: ("__worker__", [(line_idx, task_text, prompt), ...])
            if result[0] == "__worker__":
                _, worker_tasks = result
                for i, (line_idx, task_text, prompt) in enumerate(worker_tasks):
                    print(clr(f"\n  ── Worker ({i+1}/{len(worker_tasks)}): {task_text} ──", "yellow"))
                    try:
                        run_query(prompt)
                    except KeyboardInterrupt:
                        _track_ctrl_c()
                        print(clr("\n  (worker interrupted — remaining tasks skipped)", "yellow"))
                        break
                ok("Worker finished. Run /worker to check remaining tasks.")
                if _from_ssj_flag:
                    result = handle_slash("/ssj", state, config)
                    continue
                break

            # Debate sentinel: ("__ssj_debate__", filepath, nagents, rounds, out_file)
            # Drives the debate round-by-round, showing a spinner before each expert's turn.
            if result[0] == "__ssj_debate__":
                _, _dfile, _nagents, _rounds, _debate_out = result
                import random as _random

                # ── Stdout wrapper: stops spinner on first real (non-\r) output ──
                class _DebateSpinnerWrapper:
                    def __init__(self, real_out):
                        self._real = real_out
                        self._stopped = False
                    def write(self, s):
                        if not self._stopped and s and not s.startswith('\r'):
                            self._stopped = True
                            _stop_tool_spinner()
                            self._real.write('\n')
                        return self._real.write(s)
                    def flush(self):   return self._real.flush()
                    def __getattr__(self, name): return getattr(self._real, name)

                def _spin_and_query(phrase, prompt):
                    """Show spinner with phrase, stop it on first model output, run query."""
                    set_spinner_phrase(phrase)
                    _start_tool_spinner()
                    _orig = sys.stdout
                    sys.stdout = _DebateSpinnerWrapper(sys.stdout)
                    try:
                        run_query(prompt)
                    finally:
                        _stop_tool_spinner()
                        sys.stdout = _orig

                try:
                    # ── Step 1: Read file and assign expert personas ──────────
                    _spin_and_query(
                        "⚔️  Assembling expert panel...",
                        f"Read the file {_dfile}. Then introduce the {_nagents} expert debaters you will "
                        f"role-play, each with a distinct focus area chosen to best challenge each other "
                        f"(e.g. architecture, performance, security, UX, testing, maintainability). "
                        f"List their names and focus areas. Do NOT debate yet."
                    )

                    # ── Step 2: Each round, each expert takes a turn ──────────
                    for _r in range(1, _rounds + 1):
                        for _e in range(1, _nagents + 1):
                            _phase = "opening argument" if _r == 1 else f"round {_r} response"
                            _spin_and_query(
                                _random.choice([
                                    f"⚔️  Round {_r}/{_rounds} — Expert {_e} thinking...",
                                    f"💬  Round {_r}/{_rounds} — Expert {_e} formulating...",
                                    f"🧠  Round {_r}/{_rounds} — Expert {_e} responding...",
                                ]),
                                f"Now speak as Expert {_e}. Give your {_phase}. "
                                f"Be specific, reference the file content, and directly address "
                                f"the previous arguments. Be concise (3-5 key points)."
                            )

                    # ── Step 3: Consensus + save ──────────────────────────────
                    _spin_and_query(
                        "📜  Drafting final consensus...",
                        f"Based on this entire debate, write a final consensus that all experts agree on. "
                        f"List the top actionable changes ranked by impact. "
                        f"Then use the Write tool to save the complete debate transcript and this consensus "
                        f"to: {_debate_out}"
                    )
                    ok(f"Debate complete. Saved to {_debate_out}")

                except KeyboardInterrupt:
                    _track_ctrl_c()
                    _stop_tool_spinner()
                    sys.stdout = sys.__stdout__
                    print(clr("\n  (debate interrupted)", "yellow"))

                result = handle_slash("/ssj", state, config)
                continue

            # SSJ query sentinel: ("__ssj_query__", prompt)
            if result[0] == "__ssj_query__":
                _, ssj_prompt = result
                try:
                    run_query(ssj_prompt)
                except KeyboardInterrupt:
                    _track_ctrl_c()
                    print(clr("\n  (interrupted)", "yellow"))
                # Loop back to SSJ menu
                result = handle_slash("/ssj", state, config)
                continue

            # Skill match (fallback): (SkillDef, args_str)
            skill, skill_args = result
            info(f"Running skill: {skill.name}" + (f" [{skill.context}]" if skill.context == "fork" else ""))
            try:
                from cheetahclaws.skill import substitute_arguments
                rendered = substitute_arguments(skill.prompt, skill_args, skill.arguments)
                run_query(f"[Skill: {skill.name}]\n\n{rendered}")
            except KeyboardInterrupt:
                _track_ctrl_c()
                print(clr("\n  (interrupted)", "yellow"))
            break

        # Sentinel or command was handled — don't fall through to run_query
        if result:
            continue

        try:
            run_query(user_input)
        except KeyboardInterrupt:
            _track_ctrl_c()
            print(clr("\n  (interrupted)", "yellow"))
            # Keep conversation history up to the interruption


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    # Subcommand short-circuit: avoid colliding with the positional `prompt`
    # parser.  `cheetahclaws serve` runs the daemon; `cheetahclaws daemon
    # <action>` is the daemon-control verb (status / stop / logs /
    # rotate-token).  See docs/RFC/0001-daemon-design-note.md and
    # docs/RFC/0002-daemon-foundation-roadmap.md.
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        from cheetahclaws.daemon.cli import serve_main as _serve_main
        sys.exit(_serve_main(sys.argv[2:]))
    if len(sys.argv) >= 2 and sys.argv[1] == "daemon":
        from cheetahclaws.commands.daemon_cmd import dispatch as _daemon_dispatch
        sys.exit(_daemon_dispatch(sys.argv[2:]))
    # Read-only kernel inspection (RFC 0003+ surface). Talks to a
    # running `cheetahclaws serve --enable-kernel` daemon over the
    # existing daemon RPC channel; gracefully reports "not running"
    # when the daemon is absent.
    if len(sys.argv) >= 2 and sys.argv[1] == "kernel":
        from cheetahclaws.kernel.cli import dispatch as _kernel_dispatch
        sys.exit(_kernel_dispatch(sys.argv[2:]))
    # Backward-compat alias for the spike's `cheetahclaws spike-daemon ...`
    # surface (referenced in docs/RFC/0001-spike-notes.md).  Routes through
    # the same paths as `serve` / `daemon <action>` so spike-notes commands
    # keep working unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] == "spike-daemon":
        from cheetahclaws.daemon.cli import main as _legacy_main
        sys.exit(_legacy_main(sys.argv[2:]))

    parser = argparse.ArgumentParser(
        prog="cheetahclaws",
        description="CheetahClaws — minimal Python Claude Code implementation",
        add_help=False,
    )
    parser.add_argument("prompt", nargs="*", help="Initial prompt (non-interactive)")
    parser.add_argument("-p", "--print", "--print-output",
                        dest="print_mode", action="store_true",
                        help="Non-interactive mode: run prompt and exit")
    parser.add_argument("-m", "--model", help="Override model")
    parser.add_argument("--accept-all", action="store_true",
                        help="Never ask permission (accept all operations)")
    parser.add_argument("--auto", "--yolo", dest="auto", action="store_true",
                        help="Autonomous: carry the whole task through without "
                             "approval prompts. This is the default; the flag "
                             "is here to override a saved `/auto off`.")
    parser.add_argument("--ask", "--no-auto", dest="ask", action="store_true",
                        help="Turn approval prompts back on for this run "
                             "(autonomous mode is the default). Use /auto off "
                             "to make it stick.")
    parser.add_argument("--verbose", action="store_true",
                        help="Show thinking + token counts")
    parser.add_argument("--show-tools", "--no-quiet", dest="show_tools",
                        action="store_true",
                        help="Show each tool call instead of a per-turn summary")
    parser.add_argument("--thinking", action="store_true",
                        help="Enable extended thinking")
    parser.add_argument("--budget", metavar="AMOUNT",
                        help="Session budget cap, e.g. --budget $5 (cost) or "
                             "--budget 200k (tokens). Auto-saves and prompts to "
                             "resume / raise when reached.")
    parser.add_argument("--version", action="store_true", help="Print version")
    parser.add_argument("--setup", action="store_true", help="Run interactive setup wizard")
    parser.add_argument("--web", action="store_true",
                        help="Start web terminal (browser-based access)")
    parser.add_argument("--port", type=int, default=None,
                        help="Port for web terminal (default: 8080, "
                             "auto-picks a free port if 8080 is taken)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host for web terminal (default: 127.0.0.1, use 0.0.0.0 for network)")
    parser.add_argument("--no-auth", action="store_true",
                        help="Disable web terminal password (local use only)")
    parser.add_argument("-h", "--help", action="store_true", help="Show help")

    args = parser.parse_args()

    if args.version:
        print(f"cheetahclaws v{VERSION}")
        sys.exit(0)

    if args.help:
        print(__doc__)
        sys.exit(0)

    if args.web:
        from cheetahclaws.config import load_config as _load_cfg, save_config as _save_cfg
        _cfg = _load_cfg()
        # --model needs to persist: web request handlers reload config from
        # disk per request, so an in-memory override would be ignored.
        if args.model:
            m = args.model
            if "/" not in m and ":" in m:
                from cheetahclaws.providers import PROVIDERS as _PROVIDERS
                left, _ = m.split(":", 1)
                if left in _PROVIDERS:
                    m = m.replace(":", "/", 1)
            _cfg["model"] = m
            _save_cfg(_cfg)
        from cheetahclaws.bootstrap import bootstrap as _bootstrap
        _bootstrap(_cfg)
        # Auto-start configured Telegram/WeChat/Slack bridges in the same
        # process as the web server so a headless server deployment (Docker,
        # systemd) gets both channels with one command.
        _start_headless_bridges(_cfg)
        from cheetahclaws.web.server import start_web_server
        start_web_server(port=args.port, host=args.host, no_auth=args.no_auth)
        sys.exit(0)

    from cheetahclaws.config import load_config, save_config, has_api_key
    from cheetahclaws.providers import detect_provider, PROVIDERS

    config = load_config()

    # ── Workspace: opt-in. Only chdir into a managed workspace when the user
    # has enabled it (config workspace_auto=true). Off by default so launching
    # in a project directory keeps operating on that directory. ───────────────
    if config.get("workspace_auto", False):
        try:
            _apply_workspace(config)
        except Exception as _e:
            if config.get("verbose", False):
                warn(f"Could not apply workspace: {_e}")

    # Apply persisted console theme (if any) before any output is rendered.
    try:
        from cheetahclaws.ui.render import apply_theme as _apply_theme
        _apply_theme(config.get("theme", "default"))
    except Exception:
        pass

    # Explicit bootstrap: configure logging, ensure tool registry is ready,
    # and start the optional health-check server.
    from cheetahclaws.bootstrap import bootstrap as _bootstrap
    _bootstrap(config)

    # Apply CLI overrides first (so key check uses the right provider)
    if args.model:
        m = args.model
        # Convert "provider:model" → "provider/model" only when left side is a known provider
        if "/" not in m and ":" in m:
            from cheetahclaws.providers import PROVIDERS
            left, _ = m.split(":", 1)
            if left in PROVIDERS:
                m = m.replace(":", "/", 1)
        config["model"] = m
    if args.accept_all:
        config["permission_mode"] = "accept-all"
    if getattr(args, "auto", False) or getattr(args, "ask", False):
        # persist=False: a launch flag governs this run only, so it never
        # rewrites the user's saved preference either way.
        from cheetahclaws.permissions import set_auto_approve
        set_auto_approve(not getattr(args, "ask", False), config, persist=False)
    if args.verbose:
        config["verbose"] = True
    if getattr(args, "show_tools", False):
        config["quiet"] = False
    if args.thinking:
        config["thinking"] = True
    if getattr(args, "budget", None):
        from cheetahclaws import quota as _quota
        try:
            _kind, _val = _quota.parse_budget(args.budget)
            config[_quota.BUDGET_KEYS[(_kind, "session")]] = _val
            _shown = _quota.fmt_amount(_val, "usd" if _kind == "cost" else "tok")
            print(clr(f"  Session {'cost' if _kind == 'cost' else 'token'} budget: {_shown}", "dim"))
        except ValueError as _e:
            warn(f"--budget: {_e} (e.g. --budget $5 or --budget 200k); ignoring.")

    # ── Setup wizard: --setup flag or first-run auto-trigger ─────────────
    from cheetahclaws.config import CONFIG_FILE
    is_first_run = not CONFIG_FILE.exists() or os.path.getsize(CONFIG_FILE) < 5
    if args.setup or (is_first_run and sys.stdin.isatty() and not args.print_mode):
        run_setup_wizard(config)
        # Reload after wizard may have changed config
        config = load_config()
    elif not has_api_key(config):
        # Check API key for active provider (warn only, don't block local providers)
        pname = detect_provider(config["model"])
        prov  = PROVIDERS.get(pname, {})
        env   = prov.get("api_key_env", "")
        if env:   # local providers like ollama have no env key requirement
            warn(f"No API key found for provider '{pname}'. "
                 f"Set {env} or run: /config {pname}_api_key=YOUR_KEY"
                 f"\n  Or run: cheetahclaws --setup")

    initial = " ".join(args.prompt) if args.prompt else None
    if args.print_mode and not initial:
        err("--print requires a prompt argument")
        sys.exit(1)

    repl(config, initial_prompt=initial)


if __name__ == "__main__":
    main()
