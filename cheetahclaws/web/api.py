"""Structured chat API for CheetahClaws web UI.

Bridges the synchronous agent.run() generator to WebSocket event streaming,
following the same pattern as the Telegram/Slack/WeChat bridges:
wire RuntimeContext callbacks → run agent on background thread → push events.
"""
from __future__ import annotations

import copy
import json
import os
import queue
import sys
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ensure the package root is importable (web/ is a subpackage)
_PKG_ROOT = str(Path(__file__).resolve().parent.parent)
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)


# ── Event envelope ─────────────────────────────────────────────────────────

@dataclass
class ChatEvent:
    """JSON-serializable event sent to browser via WebSocket."""
    type: str       # text_chunk | thinking_chunk | tool_start | tool_end |
                    # permission_request | permission_response | turn_done |
                    # error | status
    data: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "data": self.data, "ts": self.ts})


# ── Slash command handler (can't import from cheetahclaws.py — it has
#    top-level code that runs on import).  Build our own from commands/*.
# ──────────────────────────────────────────────────────────────────────────

_WEB_COMMANDS: dict | None = None


def _get_web_commands() -> dict:
    """Lazily build the slash command registry from commands/ submodules."""
    global _WEB_COMMANDS
    if _WEB_COMMANDS is not None:
        return _WEB_COMMANDS

    cmds: dict = {}
    # Import each group separately so partial failures don't block others
    _imports = [
        # (module, [(cmd_name, func_name), ...])
        ("commands.core", [
            ("help", "cmd_help"), ("clear", "cmd_clear"),
            ("context", "cmd_context"), ("cost", "cmd_cost"),
            ("compact", "cmd_compact"), ("status", "cmd_status"),
            ("export", "cmd_export"), ("copy", "cmd_copy"),
            ("doctor", "cmd_doctor"), ("init", "cmd_init"),
            ("proactive", "cmd_proactive"), ("image", "cmd_image"),
            ("img", "cmd_image"),
        ]),
        ("commands.session", [
            ("save", "cmd_save"), ("load", "cmd_load"),
            ("resume", "cmd_resume"), ("search", "cmd_search"),
            ("history", "cmd_history"), ("cloudsave", "cmd_cloudsave"),
            ("exit", "cmd_exit"), ("quit", "cmd_exit"),
        ]),
        ("commands.config_cmd", [
            ("model", "cmd_model"), ("config", "cmd_config"),
            ("verbose", "cmd_verbose"), ("thinking", "cmd_thinking"),
            ("permissions", "cmd_permissions"), ("cwd", "cmd_cwd"),
        ]),
        ("commands.advanced", [
            ("brainstorm", "cmd_brainstorm"), ("worker", "cmd_worker"),
            ("ssj", "cmd_ssj"), ("skills", "cmd_skills"),
            ("memory", "cmd_memory"), ("agents", "cmd_agents"),
            ("mcp", "cmd_mcp"), ("plugin", "cmd_plugin"),
            ("tasks", "cmd_tasks"), ("task", "cmd_tasks"),
        ]),
        ("commands.checkpoint_plan", [
            ("plan", "cmd_plan"), ("checkpoint", "cmd_checkpoint"),
        ]),
        ("commands.agent_cmd", [
            ("agent", "cmd_agent"),
        ]),
        ("commands.monitor_cmd", [
            ("subscribe", "cmd_subscribe"),
            ("subscriptions", "cmd_subscriptions"),
            ("subs", "cmd_subscriptions"),
            ("unsubscribe", "cmd_unsubscribe"),
            ("monitor", "cmd_monitor"),
        ]),
        # External bridges — telegram / slack / wechat / voice.
        # Each lives in its own module so missing deps (e.g. sounddevice for
        # voice) just skip that one command instead of blocking the rest.
        ("bridges.telegram", [("telegram", "cmd_telegram")]),
        ("bridges.slack",    [("slack",    "cmd_slack")]),
        ("bridges.wechat",   [("wechat",   "cmd_wechat"),
                              ("weixin",   "cmd_wechat")]),
        ("modular.voice.cmd", [("voice",   "cmd_voice")]),
    ]
    import importlib
    for mod_name, pairs in _imports:
        try:
            mod = importlib.import_module(mod_name)
            for cmd_name, func_name in pairs:
                fn = getattr(mod, func_name, None)
                if fn:
                    cmds[cmd_name] = fn
        except ImportError:
            pass
    _WEB_COMMANDS = cmds
    return cmds


def _web_handle_slash(line: str, state, config):
    """Handle /command. Returns True if handled, or sentinel tuple."""
    if not line.startswith("/"):
        return False
    parts = line[1:].split(None, 1)
    if not parts:
        return False
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    commands = _get_web_commands()
    handler = commands.get(cmd)
    if handler:
        result = handler(args, state, config)
        # Sentinel tuples need special handling by the caller
        _SENTINELS = ("__voice__", "__image__", "__brainstorm__", "__worker__",
                      "__ssj_cmd__", "__ssj_query__", "__ssj_debate__",
                      "__ssj_passthrough__", "__ssj_promote_worker__", "__plan__")
        if isinstance(result, tuple) and result[0] in _SENTINELS:
            return result
        return True
    print(f"Unknown command: /{cmd}  (type /help for commands)")
    return True


# ── Chat Session ───────────────────────────────────────────────────────────

_IDLE_TIMEOUT = 1800  # 30 min before session is considered stale

_SAFE_CONFIG_KEYS = frozenset({
    "model", "permission_mode", "max_tokens", "verbose", "thinking",
    "thinking_budget", "max_tool_output", "max_agent_depth",
    "shell_policy", "log_level", "tool_profile",
})

_WRITABLE_CONFIG_KEYS = frozenset({
    "model", "permission_mode", "verbose", "thinking",
    "thinking_budget", "max_tokens", "tool_profile",
    # API keys — written to session config only, not persisted to disk
    "anthropic_api_key", "openai_api_key", "gemini_api_key",
    "kimi_api_key", "qwen_api_key", "zhipu_api_key",
    "deepseek_api_key", "minimax_api_key", "custom_api_key",
    "custom_base_url", "ollama_base_url",
})

# Keys that contain secrets — never expose in GET responses
_SECRET_KEYS = frozenset({
    "anthropic_api_key", "openai_api_key", "gemini_api_key",
    "kimi_api_key", "qwen_api_key", "zhipu_api_key",
    "deepseek_api_key", "minimax_api_key", "custom_api_key",
})

# ── Multi-user privilege model ────────────────────────────────────────────
# Web chat sessions run in the server owner's process with the owner's
# config. Admins (the first registered account, or the --no-auth owner) can
# do anything the REPL can; other accounts cannot touch process-global or
# persistent state, nor loosen the owner's permission mode. The owner can
# restore the old "everyone is trusted" behaviour with
# "web_nonadmin_privileged": true in config.json.

# Slash commands that change global/persistent state, reach the owner's
# private data, or drive external bridges.
_ADMIN_ONLY_COMMANDS = frozenset({
    "config", "permissions", "cwd", "plugin", "mcp",
    "telegram", "slack", "wechat", "weixin", "voice",
    "load", "resume", "history", "search", "cloudsave", "memory",
    "subscribe", "unsubscribe", "monitor",
    # write files as the owner or start long-lived owner-privileged workers
    "export", "checkpoint", "rewind", "init", "agent", "worker", "ssj",
    "trust", "qq", "daemon", "workspace", "lab", "proactive",
})

# Config keys only admins may change: they redirect the owner's API keys
# to arbitrary hosts (SSRF / key exfiltration).
_ADMIN_ONLY_CONFIG_KEYS = frozenset({"custom_base_url", "ollama_base_url"})

# Higher = more permissive. Non-admins may not exceed the owner's mode.
_PERMISSION_RANK = {
    "plan": 0, "manual": 1, "auto": 2, "accept-edits": 3, "accept-all": 4,
}

_ADMIN_HINT = ("The server owner can set \"web_nonadmin_privileged\": true "
               "in ~/.cheetahclaws/config.json to allow all users.")


def _user_is_admin(user_id: Optional[int]) -> bool:
    """True for chat-UI admins and for the --no-auth owner."""
    try:
        from cheetahclaws.web import server as _srv
        if _srv._server_no_auth:
            return True
    except ImportError:
        pass
    if user_id is None:
        return False
    try:
        from cheetahclaws.web import db as _db
        user = _db.repo.get_user(user_id)
    except Exception:  # noqa: BLE001
        return False
    return bool(user and user.get("is_admin"))


def _is_secret_key(key: str) -> bool:
    k = key.lower()
    return (k.endswith("_api_key") or k.endswith("token")
            or k.endswith("secret") or "password" in k
            or k in _SECRET_KEYS)


def _redact_secrets(text: str, config: dict) -> str:
    """Mask any secret config value (API keys, bot tokens...) found in text."""
    if not text or not isinstance(text, str):
        return text
    for k, v in config.items():
        if (isinstance(k, str) and isinstance(v, str) and len(v) >= 8
                and _is_secret_key(k) and v in text):
            text = text.replace(v, "***redacted***")
    return text


_API_KEY_CONFIG_MAP = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "kimi": "kimi_api_key",
    "qwen": "qwen_api_key",
    "zhipu": "zhipu_api_key",
    "deepseek": "deepseek_api_key",
    "minimax": "minimax_api_key",
    "custom": "custom_api_key",
}


class ChatSession:
    """One agent conversation, bridged to WebSocket clients.

    Persistence: session metadata and message history are mirrored to SQLite
    via web.db.repo. The in-memory `messages` list is a write-through cache
    for fast replay; event queue/buffer stay in-memory only.
    """

    # Owner baseline defaults (overwritten in __init__ from base_config).
    _owner_permission_mode = "auto"
    _owner_tool_profile = None

    def __init__(self, base_config: dict, user_id: int, *,
                 session_id: Optional[str] = None,
                 title: Optional[str] = None):
        from cheetahclaws.web import db as _db
        _db.init_db()

        # Hydrate-from-DB path vs new-session path
        existing = (_db.repo.get_session(session_id, user_id)
                    if session_id else None)

        self.session_id: str = (existing["id"] if existing
                                else (session_id or uuid.uuid4().hex[:12]))
        self.user_id: int = user_id
        self.title: str = (existing["title"] if existing
                           else (title or "New chat"))
        self.created_at: float = (existing["created_at"] if existing
                                  else time.time())
        self.last_active: float = time.time()

        # Deep-copy config so permission_mode changes don't leak
        base = copy.deepcopy(base_config)
        # The owner's configured baseline — the ceiling for non-admins.
        self._owner_permission_mode = base.get("permission_mode", "auto")
        self._owner_tool_profile = base.get("tool_profile")
        if existing and existing.get("config"):
            base.update(existing["config"])
        self.config: dict = base
        if not self._privileged():
            # A persisted session may predate the privilege model (or the
            # user may have been demoted): re-clamp to the owner's ceiling.
            if not self._mode_allowed(self.config.get("permission_mode")):
                self.config["permission_mode"] = self._owner_permission_mode
            if not self._profile_allowed(self.config.get("tool_profile")):
                self.config["tool_profile"] = self._owner_tool_profile
        self.config["_session_id"] = self.session_id

        # Event fan-out: multiple WS clients can subscribe
        self._subscribers: list[queue.Queue] = []
        self._sub_lock = threading.Lock()

        # Buffer recent events so late-joining subscribers don't miss them.
        # Capped at 500 events; covers the gap between agent start and WS connect.
        self._event_buffer: list[ChatEvent] = []
        self._EVENT_BUFFER_MAX = 500

        # Agent state (in-process, NOT a PTY subprocess)
        self._agent_state = None  # type: ignore[assignment]
        self._agent_thread: Optional[threading.Thread] = None
        self._busy = threading.Event()

        # Message history for UI replay on reconnect (hydrated from DB)
        self.messages: list[dict] = (_db.repo.get_messages(self.session_id)
                                     if existing else [])
        self._msg_lock = threading.Lock()

        # Persist (create-or-update) metadata
        _db.repo.upsert_session(
            self.session_id, user_id,
            title=self.title,
            config={k: v for k, v in self.config.items()
                    if k in _SAFE_CONFIG_KEYS},
        )

        self._init_runtime()

    # ── Privilege checks ───────────────────────────────────────────────

    def _privileged(self) -> bool:
        if self.config.get("web_nonadmin_privileged"):
            return True
        return _user_is_admin(self.user_id)

    def _mode_allowed(self, mode) -> bool:
        """May a non-admin use this permission_mode?"""
        rank = _PERMISSION_RANK.get(mode)
        ceiling = _PERMISSION_RANK.get(self._owner_permission_mode, 2)
        return rank is not None and rank <= ceiling

    def _profile_allowed(self, profile) -> bool:
        """May a non-admin use this tool_profile? Every profile is a subset
        of "full" and a superset of "standard". An unknown profile name is
        let through here so update_config reports it as a ValueError (400)."""
        try:
            from cheetahclaws.tool_registry import normalize_tool_profile
        except ImportError:
            return False
        try:
            want = normalize_tool_profile(profile)
        except ValueError:
            return True
        try:
            owner = normalize_tool_profile(self._owner_tool_profile)
        except ValueError:
            return False
        return want == owner or want == "standard" or owner == "full"

    def _check_config_update(self, updates: dict) -> None:
        """Raise PermissionError if a non-admin tries a privileged change."""
        if self._privileged():
            return
        for k in updates:
            if k in _ADMIN_ONLY_CONFIG_KEYS:
                raise PermissionError(
                    f"Only admins can change '{k}'. {_ADMIN_HINT}")
        if ("permission_mode" in updates
                and not self._mode_allowed(updates["permission_mode"])):
            raise PermissionError(
                f"permission_mode '{updates['permission_mode']}' is more "
                f"permissive than the server owner's "
                f"'{self._owner_permission_mode}'; only admins can raise "
                f"it. {_ADMIN_HINT}")
        if ("tool_profile" in updates
                and not self._profile_allowed(updates["tool_profile"])):
            raise PermissionError(
                f"tool_profile '{updates['tool_profile']}' exceeds the server "
                f"owner's profile; only admins can widen it. {_ADMIN_HINT}")

    def _slash_denied(self, line: str) -> bool:
        """Broadcast a refusal and return True if `line` is admin-only."""
        parts = line[1:].split(None, 1) if line.startswith("/") else []
        cmd = parts[0].lower() if parts else ""
        if cmd not in _ADMIN_ONLY_COMMANDS or self._privileged():
            return False
        msg = (f"/{cmd} is restricted to admin users in the web UI. "
               f"{_ADMIN_HINT}")
        self._broadcast(ChatEvent("command_result", {
            "command": line, "output": msg,
        }))
        return True

    def _init_runtime(self):
        """Initialize RuntimeContext and AgentState."""
        from cheetahclaws.agent import AgentState
        from cheetahclaws import runtime

        self._agent_state = AgentState()
        ctx = runtime.get_session_ctx(self.session_id)
        ctx.agent_state = self._agent_state
        ctx.run_query = lambda msg: self.submit_prompt(msg)

    # ── Subscriber management ──────────────────────────────────────────

    def subscribe(self) -> queue.Queue:
        """Add a subscriber and replay any buffered events."""
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._sub_lock:
            # Replay buffered events so late-joiners don't miss anything
            for evt in self._event_buffer:
                try:
                    q.put_nowait(evt)
                except queue.Full:
                    break
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue):
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event: ChatEvent):
        with self._sub_lock:
            # Buffer for late-joining subscribers
            self._event_buffer.append(event)
            if len(self._event_buffer) > self._EVENT_BUFFER_MAX:
                self._event_buffer = self._event_buffer[-self._EVENT_BUFFER_MAX:]
            # Push to live subscribers
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    # ── Prompt submission ──────────────────────────────────────────────

    def handle_slash_sync(self, line: str) -> list[dict]:
        """Handle a slash command synchronously. Returns list of event dicts
        to send back in the HTTP response.

        Synchronous events are returned via HTTP only — re-broadcasting them
        to WS subscribers would duplicate every reply in the chat UI, since
        the same client also iterates the HTTP `events` payload. Background
        threads spawned by the handler still broadcast normally, because
        `_broadcast` is restored before they emit anything.
        """
        events: list[dict] = []
        orig_broadcast = self._broadcast

        def capture_broadcast(event: ChatEvent):
            events.append({"type": event.type, "data": event.data})

        self._broadcast = capture_broadcast  # type: ignore
        try:
            self._handle_slash(line)
        finally:
            self._broadcast = orig_broadcast  # type: ignore
        return events

    def handle_slash_stream(self, line: str, event_callback):
        """Handle a slash command, calling event_callback(dict) for each event.
        Blocks until the command (including long-running ones) completes.
        Used by the SSE streaming endpoint.

        Events are delivered via the SSE callback only — re-broadcasting them
        to WS subscribers would duplicate every reply in the chat UI, since
        the same client also calls _handleEvent on the SSE stream.
        """
        done_event = threading.Event()
        orig_broadcast = self._broadcast

        def stream_broadcast(event: ChatEvent):
            event_callback({"type": event.type, "data": event.data})
            if event.type == "status" and event.data.get("state") == "idle":
                done_event.set()

        self._broadcast = stream_broadcast  # type: ignore
        try:
            self._handle_slash(line)
            # For long-running commands, wait until the bg thread finishes
            if self._busy.is_set():
                done_event.wait(timeout=600)  # 10 min max
        finally:
            self._broadcast = orig_broadcast  # type: ignore

    def submit_prompt(self, prompt: str) -> bool:
        """Submit a prompt or slash command. Returns False if agent is busy."""
        # Handle slash commands locally (don't send to LLM)
        if prompt.startswith("/"):
            return self._handle_slash(prompt)

        if self._busy.is_set():
            self._broadcast(ChatEvent("error", {"message": "Agent is busy"}))
            return False

        self.last_active = time.monotonic()
        # Clear event buffer for fresh turn — don't replay stale events
        with self._sub_lock:
            self._event_buffer.clear()
        self._append_msg({"role": "user", "content": prompt})
        self._broadcast(ChatEvent("status", {"state": "running"}))

        def _run():
            self._busy.set()
            try:
                self._run_agent(prompt)
            except Exception as exc:
                self._broadcast(ChatEvent("error", {
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                }))
            finally:
                self._busy.clear()
                self._broadcast(ChatEvent("status", {"state": "idle"}))

        self._agent_thread = threading.Thread(target=_run, daemon=True)
        self._agent_thread.start()
        return True

    def _handle_slash(self, line: str) -> bool:
        """Handle /commands locally, capture stdout, broadcast as system message.

        Some commands return sentinel tuples that require follow-up agent runs
        (e.g. __brainstorm__, __worker__, __plan__, __ssj_cmd__).  These are
        executed on a background thread exactly like a regular prompt.
        """
        import io
        import re as _re
        self.last_active = time.monotonic()

        self._append_msg({"role": "user", "content": line})

        # Parse command and args
        cmd_parts = line[1:].split(None, 1)
        cmd_name = cmd_parts[0].lower() if cmd_parts else ""
        cmd_args = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

        if self._slash_denied(line):
            return True

        # /ssj with no args → show interactive menu
        if cmd_name == "ssj" and not cmd_args:
            self._broadcast(ChatEvent("interactive_menu", {
                "command": line,
                "menu": "ssj",
                "items": [
                    {"key":"1",  "icon":"bulb",    "label":"Brainstorm",    "cmd":"/brainstorm"},
                    {"key":"2",  "icon":"clipboard","label":"Show TODO",     "cmd":"/ssj todo"},
                    {"key":"3",  "icon":"worker",   "label":"Worker",        "cmd":"/worker"},
                    {"key":"4",  "icon":"brain",    "label":"Debate File",   "cmd":"/ssj debate"},
                    {"key":"5",  "icon":"sparkle",  "label":"Propose Improvement","cmd":"/ssj propose"},
                    {"key":"6",  "icon":"search",   "label":"Review File",   "cmd":"/ssj review"},
                    {"key":"7",  "icon":"book",     "label":"Generate README","cmd":"/ssj readme"},
                    {"key":"8",  "icon":"chat",     "label":"AI Commit Msg", "cmd":"/ssj commit"},
                    {"key":"9",  "icon":"test",     "label":"Scan Git Diff", "cmd":"/ssj scan"},
                    {"key":"10", "icon":"note",     "label":"Promote to Tasks","cmd":"/ssj promote"},
                    {"key":"13", "icon":"monitor",  "label":"Monitor",       "cmd":"/monitor"},
                    {"key":"15", "icon":"robot",    "label":"Autonomous Agent","cmd":"/agent"},
                ],
            }))
            return True

        # /ssj <subcommand> → map to direct actions (skip the interactive menu)
        _SSJ_DIRECT = {
            "debate":  ("__ssj_query__", "Act as a panel of 3 expert engineers. Each gives 2-3 critical insights on the codebase. Be specific and constructive."),
            "propose": ("__ssj_query__", "Analyze the codebase and propose 3 high-impact improvements with code examples. Focus on correctness, performance, or maintainability."),
            "review":  ("__ssj_query__", "Give a quick code review: identify bugs, code smells, or missing edge cases. Be concise."),
            "readme":  ("__ssj_query__", "Generate a comprehensive README.md for this project. Include: project description, features, installation, usage examples, and contributing guidelines."),
            "commit":  ("__ssj_query__", "Review the git diff (git diff HEAD) and suggest a concise, descriptive commit message following conventional commits format. Also list files changed."),
            "scan":    ("__ssj_query__", "Run git diff HEAD and analyze the changes. Summarize what was changed, why it might have been changed, and flag any potential issues or regressions."),
            "todo":    None,  # handled below
        }
        if cmd_name == "ssj" and cmd_args.split()[0].lower() in _SSJ_DIRECT:
            sub = cmd_args.split()[0].lower()
            extra_args = cmd_args[len(sub):].strip()
            if sub == "todo":
                pass  # fall through to normal handler
            else:
                action = _SSJ_DIRECT[sub]
                prompt = action[1]
                if extra_args:
                    prompt += f" Focus on: {extra_args}"
                # Run as agent query
                self._broadcast(ChatEvent("status", {"state": "running"}))
                self._broadcast(ChatEvent("command_result", {
                    "command": line,
                    "output": f"Running SSJ {sub}...",
                }))

                def _run_ssj():
                    self._busy.set()
                    from cheetahclaws import runtime
                    ctx = runtime.get_session_ctx(self.session_id)
                    ctx.in_web_turn = True
                    try:
                        self._run_agent(prompt)
                    except Exception as exc:
                        self._broadcast(ChatEvent("error",
                                                  {"message": str(exc)}))
                    finally:
                        ctx.in_web_turn = False
                        self._busy.clear()
                        self._broadcast(ChatEvent("status",
                                                  {"state": "idle"}))

                self._agent_thread = threading.Thread(target=_run_ssj,
                                                      daemon=True)
                self._agent_thread.start()
                return True

        # /brainstorm with no topic → ask for topic via input_request event
        if cmd_name == "brainstorm" and not cmd_args:
            self._broadcast(ChatEvent("input_request", {
                "command": "/brainstorm",
                "prompt": "Brainstorm topic (Enter for general):",
                "placeholder": "e.g. improve test coverage, refactor auth...",
                "default_cmd": "/brainstorm general project improvement",
            }))
            return True

        # Long-running commands — run on background thread with live events.
        # These call providers.stream() internally and take minutes.
        # We redirect stdout so their print() output streams to the browser.
        _LONG_RUNNING = {"brainstorm", "worker", "agent", "plan"}
        if cmd_name in _LONG_RUNNING:
            self._broadcast(ChatEvent("status", {"state": "running"}))
            session_ref = self  # capture for closure

            # Thread-local stdout wrapper: intercepts print() calls from
            # the command handler and broadcasts them as text_chunk events.
            # Uses threading.current_thread() check to avoid affecting other threads.
            _target_thread_id = [None]  # set inside the thread

            class _ThreadLocalStdout:
                """Only intercepts writes from the target thread."""
                def __init__(self, broadcast_fn, real):
                    self._broadcast = broadcast_fn
                    self._real = real
                def write(self, s):
                    if not s:
                        return
                    if threading.current_thread().ident == _target_thread_id[0]:
                        import re as _re2
                        clean = _re2.sub(r'\x1b\[[0-9;]*m', '', s)
                        clean = _redact_secrets(clean, session_ref.config)
                        if clean.strip():
                            self._broadcast(ChatEvent("text_chunk",
                                                      {"text": clean}))
                    else:
                        self._real.write(s)
                def flush(self):
                    self._real.flush()
                # Forward attributes to real stdout for compatibility
                def fileno(self):
                    return self._real.fileno()
                @property
                def encoding(self):
                    return getattr(self._real, 'encoding', 'utf-8')

            def _run_long():
                _target_thread_id[0] = threading.current_thread().ident
                self._busy.set()
                from cheetahclaws import runtime
                ctx = runtime.get_session_ctx(self.session_id)
                ctx.in_web_turn = True
                wrapper = _ThreadLocalStdout(session_ref._broadcast,
                                            sys.stdout)
                old_out, old_err = sys.stdout, sys.stderr
                sys.stdout = wrapper
                sys.stderr = wrapper
                try:
                    result = _web_handle_slash(line, self._agent_state,
                                              self.config)
                    if isinstance(result, tuple):
                        self._process_sentinel(result)
                    elif result is True:
                        self._broadcast(ChatEvent("command_result", {
                            "command": line,
                            "output": "(done)",
                        }))
                except Exception as exc:
                    self._broadcast(ChatEvent("error",
                                              {"message": str(exc)}))
                finally:
                    sys.stdout = old_out
                    sys.stderr = old_err
                    ctx.in_web_turn = False
                    self._busy.clear()
                    self._broadcast(ChatEvent("status", {"state": "idle"}))

            self._agent_thread = threading.Thread(target=_run_long,
                                                  daemon=True)
            self._agent_thread.start()
            return True

        # Quick commands — capture stdout synchronously
        capture = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = capture
            sys.stderr = capture
            result = _web_handle_slash(line, self._agent_state, self.config)
        except Exception as exc:
            self._broadcast(ChatEvent("error", {"message": str(exc)}))
            return True
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        output = capture.getvalue().strip()
        output = _re.sub(r'\x1b\[[0-9;]*m', '', output)
        output = _redact_secrets(output, self.config)

        if output:
            self._append_msg({"role": "assistant", "content": output})
            self._broadcast(ChatEvent("command_result", {
                "command": line, "output": output,
            }))

        # Handle sentinel tuples from quick commands (unlikely but safe)
        if isinstance(result, tuple):
            self._broadcast(ChatEvent("status", {"state": "running"}))

            def _run_sentinel():
                self._busy.set()
                try:
                    self._process_sentinel(result)
                except Exception as exc:
                    self._broadcast(ChatEvent("error",
                                              {"message": str(exc)}))
                finally:
                    self._busy.clear()
                    self._broadcast(ChatEvent("status", {"state": "idle"}))

            self._agent_thread = threading.Thread(target=_run_sentinel,
                                                  daemon=True)
            self._agent_thread.start()
            return True

        if not output and result is True:
            self._broadcast(ChatEvent("command_result", {
                "command": line, "output": "(done)",
            }))

        return True

    def _process_sentinel(self, result: tuple):
        """Execute the multi-step workflow described by a sentinel tuple."""
        sentinel = result[0]

        if sentinel == "__brainstorm__":
            _, brain_prompt, brain_out_file = result
            self._broadcast(ChatEvent("command_result", {
                "command": "/brainstorm",
                "output": "Starting multi-persona brainstorm...",
            }))
            self._run_agent(brain_prompt)
            # Generate todo list from synthesis
            from pathlib import Path
            todo_path = str(Path(brain_out_file).parent / "todo_list.txt")
            self._run_agent(
                f"Based on the Master Plan you just synthesized, generate a "
                f"todo list file at {todo_path}. Format: one task per line, "
                f"each starting with '- [ ] '. Order by priority. Include ALL "
                f"actionable items from the plan. Use the Write tool to create "
                f"the file. Do NOT explain, just write the file now."
            )

        elif sentinel == "__worker__":
            _, worker_tasks = result
            total = len(worker_tasks)
            for i, (line_idx, task_text, prompt) in enumerate(worker_tasks):
                self._broadcast(ChatEvent("command_result", {
                    "command": f"/worker ({i+1}/{total})",
                    "output": task_text,
                }))
                self._run_agent(prompt)

        elif sentinel == "__plan__":
            _, plan_desc = result
            self._broadcast(ChatEvent("command_result", {
                "command": "/plan",
                "output": f"Entering plan mode: {plan_desc}",
            }))
            self._run_agent(
                f"Please analyze the codebase and create a detailed "
                f"implementation plan for: {plan_desc}"
            )

        elif sentinel == "__ssj_cmd__":
            # SSJ delegates to another slash command
            _, cmd_name, cmd_args = result
            inner_line = f"/{cmd_name} {cmd_args}".strip()
            self._broadcast(ChatEvent("command_result", {
                "command": "/ssj",
                "output": f"Executing: {inner_line}",
            }))
            # Re-enter slash handling for the delegated command
            self._handle_slash_inner(inner_line)

        elif sentinel in ("__ssj_query__", "__ssj_debate__",
                          "__ssj_passthrough__", "__ssj_promote_worker__"):
            # These carry a prompt to run through the agent
            prompt = result[1] if len(result) > 1 else ""
            if prompt:
                self._run_agent(prompt)

        elif sentinel == "__image__":
            self._broadcast(ChatEvent("command_result", {
                "command": "/image",
                "output": "Image/vision: paste an image URL or use the terminal for clipboard support.",
            }))

        elif sentinel == "__voice__":
            self._broadcast(ChatEvent("command_result", {
                "command": "/voice",
                "output": "Voice input requires the terminal (microphone access).",
            }))

        else:
            # Unknown sentinel — try to extract a prompt if it has one
            if len(result) > 1 and isinstance(result[1], str) and result[1]:
                self._run_agent(result[1])
            else:
                self._broadcast(ChatEvent("command_result", {
                    "command": str(result[0]),
                    "output": "This feature may require the terminal for full support.",
                }))

    def _handle_slash_inner(self, line: str):
        """Re-entrant slash handling for SSJ delegation."""
        import io
        import re as _re

        if self._slash_denied(line):
            return

        capture = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        try:
            sys.stdout = capture
            sys.stderr = capture
            result = _web_handle_slash(line, self._agent_state, self.config)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        output = _re.sub(r'\x1b\[[0-9;]*m', '', capture.getvalue().strip())
        output = _redact_secrets(output, self.config)
        if output:
            self._append_msg({"role": "assistant", "content": output})
            self._broadcast(ChatEvent("command_result", {
                "command": line, "output": output,
            }))

        if isinstance(result, tuple):
            self._process_sentinel(result)

    def _run_agent(self, prompt: str):
        """Iterate agent.run() generator, broadcast events."""
        from cheetahclaws.agent import (run, TextChunk, ThinkingChunk, ToolStart,
                           ToolEnd, TurnDone, PermissionRequest)
        from cheetahclaws.context import build_system_prompt
        from cheetahclaws import runtime

        ctx = runtime.get_session_ctx(self.session_id)
        ctx.in_web_turn = True
        system_prompt = build_system_prompt(self.config)

        text_chunks: list[str] = []
        tool_calls: list[dict] = []

        # Do NOT wire RuntimeContext callbacks — we broadcast from the
        # generator loop below.  Wiring ctx.on_text_chunk etc. would cause
        # duplicate events because the REPL's run_query() also fires them
        # for every yielded event.  Single event source = generator loop only.
        ctx.on_text_chunk = None
        ctx.on_tool_start = None
        ctx.on_tool_end = None

        try:
            for event in run(prompt, self._agent_state, self.config,
                             system_prompt):
                if isinstance(event, TextChunk):
                    text_chunks.append(event.text)
                    self._broadcast(ChatEvent("text_chunk",
                                              {"text": event.text}))

                elif isinstance(event, ThinkingChunk):
                    self._broadcast(ChatEvent("thinking_chunk",
                                              {"text": event.text}))

                elif isinstance(event, ToolStart):
                    tool_calls.append({
                        "name": event.name,
                        "inputs": event.inputs,
                        "status": "running",
                    })
                    self._broadcast(ChatEvent("tool_start", {
                        "name": event.name,
                        "inputs": event.inputs,
                    }))

                elif isinstance(event, PermissionRequest):
                    self._broadcast(ChatEvent("permission_request", {
                        "description": event.description,
                    }))
                    # Block until browser responds
                    evt = threading.Event()
                    ctx.web_input_event = evt
                    try:
                        if evt.wait(timeout=300):
                            val = ctx.web_input_value.strip().lower()
                            event.granted = val in ("y", "yes", "true", "1")
                        else:
                            event.granted = False
                            self._broadcast(ChatEvent("error", {
                                "message": "Permission request timed out (5 min)",
                            }))
                    finally:
                        # Always clean up — prevents dangling event objects
                        ctx.web_input_event = None
                        ctx.web_input_value = ""
                    self._broadcast(ChatEvent("permission_response", {
                        "granted": event.granted,
                    }))

                elif isinstance(event, ToolEnd):
                    for tc in reversed(tool_calls):
                        if tc["name"] == event.name and tc["status"] == "running":
                            tc["status"] = "done" if event.permitted else "denied"
                            tc["result"] = event.result[:2000] if event.result else ""
                            break
                    self._broadcast(ChatEvent("tool_end", {
                        "name": event.name,
                        "result": event.result[:2000] if event.result else "",
                        "permitted": event.permitted,
                    }))

                elif isinstance(event, TurnDone):
                    self._broadcast(ChatEvent("turn_done", {
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                    }))

            # Store assistant response in history
            final_text = "".join(text_chunks)
            msg: dict = {"role": "assistant", "content": final_text}
            if tool_calls:
                msg["tool_calls"] = tool_calls
            self._append_msg(msg)

        except Exception as exc:
            self._broadcast(ChatEvent("error", {"message": str(exc)}))
        finally:
            ctx.on_text_chunk = None
            ctx.on_tool_start = None
            ctx.on_tool_end = None
            ctx.in_web_turn = False

    # ── Permission approval ────────────────────────────────────────────

    def approve_permission(self, granted: bool):
        """Respond to a pending PermissionRequest."""
        from cheetahclaws import runtime
        ctx = runtime.get_session_ctx(self.session_id)
        evt = ctx.web_input_event
        if evt:
            ctx.web_input_value = "y" if granted else "n"
            evt.set()

    # ── Introspection ──────────────────────────────────────────────────

    def _append_msg(self, msg: dict):
        with self._msg_lock:
            self.messages.append(msg)
        # Persist to DB (best-effort; don't break streaming on DB failure)
        try:
            from cheetahclaws.web import db as _db
            _db.repo.append_message(
                self.session_id,
                msg.get("role", "system"),
                msg.get("content", "") or "",
                msg.get("tool_calls"),
            )
            # Keep in-memory title in sync with auto-titling in repo
            sess = _db.repo.get_session(self.session_id, self.user_id)
            if sess and sess["title"] != self.title:
                self.title = sess["title"]
        except Exception as exc:  # noqa: BLE001
            from cheetahclaws.web.logging_setup import get_logger
            get_logger("api").exception("message persist failed",
                                         extra={"session_id": self.session_id,
                                                "err": str(exc)})

    def get_messages(self) -> list[dict]:
        with self._msg_lock:
            return list(self.messages)

    def get_safe_config(self) -> dict:
        result = {k: self.config.get(k) for k in _SAFE_CONFIG_KEYS
                  if k in self.config}
        # Show which providers have API keys configured (without revealing them)
        result["api_keys_configured"] = {
            provider: bool(self.config.get(cfg_key) or
                          os.environ.get(cfg_key.upper(), ""))
            for provider, cfg_key in _API_KEY_CONFIG_MAP.items()
        }
        result["custom_base_url"] = self.config.get("custom_base_url", "")
        result["ollama_base_url"] = self.config.get("ollama_base_url",
                                                     "http://localhost:11434")
        return result

    def update_config(self, updates: dict) -> dict:
        if not isinstance(updates, dict):
            raise ValueError("Config update must be an object.")
        self._check_config_update(updates)
        normalized_profile = None
        if "tool_profile" in updates:
            from cheetahclaws.tool_registry import normalize_tool_profile
            normalized_profile = normalize_tool_profile(updates["tool_profile"])
        for k, v in updates.items():
            if k in _WRITABLE_CONFIG_KEYS:
                if k == "tool_profile":
                    v = normalized_profile
                self.config[k] = v
        # Persist non-secret config keys to DB (secrets stay session-only)
        try:
            from cheetahclaws.web import db as _db
            _db.repo.upsert_session(
                self.session_id, self.user_id,
                title=self.title,
                config={k: v for k, v in self.config.items()
                        if k in _SAFE_CONFIG_KEYS},
            )
        except Exception as exc:  # noqa: BLE001
            from cheetahclaws.web.logging_setup import get_logger
            get_logger("api").exception("config persist failed",
                                         extra={"session_id": self.session_id,
                                                "err": str(exc)})
        return self.get_safe_config()

    def is_idle(self) -> bool:
        return not self._busy.is_set()

    def is_stale(self) -> bool:
        return (time.monotonic() - self.last_active) > _IDLE_TIMEOUT

    # ── Cleanup ────────────────────────────────────────────────────────

    def cleanup(self):
        from cheetahclaws import runtime
        runtime.release_session_ctx(self.session_id)


# ── Session registry ───────────────────────────────────────────────────────

_chat_sessions: dict[str, ChatSession] = {}
_chat_lock = threading.Lock()


def create_chat_session(base_config: dict, user_id: int) -> ChatSession:
    session = ChatSession(base_config, user_id=user_id)
    with _chat_lock:
        _chat_sessions[session.session_id] = session
    return session


def get_chat_session(sid: str,
                    user_id: Optional[int] = None,
                    base_config: Optional[dict] = None) -> Optional[ChatSession]:
    """Return a live ChatSession, hydrating from DB if necessary.

    If the session isn't in the in-memory cache but exists in the DB (and is
    owned by `user_id`), it's lazily rehydrated so restarts don't lose state.
    `user_id` is required for DB hydration; pass None to skip hydration and
    only look in memory (used by internal callers that already validated).
    """
    with _chat_lock:
        sess = _chat_sessions.get(sid)
        if sess:
            # Enforce ownership even on cache hits — otherwise users could
            # read each other's sessions whenever the cache is warm.
            if user_id is not None and sess.user_id != user_id:
                return None
            return sess
    if user_id is None or base_config is None:
        return None
    # Try to hydrate from DB
    try:
        from cheetahclaws.web import db as _db
        row = _db.repo.get_session(sid, user_id)
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    session = ChatSession(base_config, user_id=user_id, session_id=sid)
    with _chat_lock:
        # Guard against a race where another thread hydrated concurrently.
        existing = _chat_sessions.get(sid)
        if existing:
            return existing
        _chat_sessions[sid] = session
    return session


def list_chat_sessions(user_id: int) -> list[dict]:
    """List this user's sessions (DB is the source of truth, not memory)."""
    try:
        from cheetahclaws.web import db as _db
        rows = _db.repo.list_sessions(user_id)
    except Exception as exc:  # noqa: BLE001
        from cheetahclaws.web.logging_setup import get_logger
        get_logger("api").exception("list_sessions failed",
                                     extra={"user_id": user_id,
                                            "err": str(exc)})
        rows = []
    busy_ids = set()
    with _chat_lock:
        for sid, s in _chat_sessions.items():
            if s._busy.is_set():
                busy_ids.add(sid)
    return [{**r, "busy": r["id"] in busy_ids} for r in rows]


def remove_chat_session(sid: str, user_id: int) -> bool:
    """Remove session from DB and in-memory cache. Returns True if removed."""
    try:
        from cheetahclaws.web import db as _db
        deleted = _db.repo.delete_session(sid, user_id)
    except Exception as exc:  # noqa: BLE001
        from cheetahclaws.web.logging_setup import get_logger
        get_logger("api").exception("delete_session failed",
                                     extra={"session_id": sid,
                                            "user_id": user_id,
                                            "err": str(exc)})
        deleted = False
    with _chat_lock:
        session = _chat_sessions.pop(sid, None)
    if session:
        session.cleanup()
    return deleted


def list_folders(user_id: int) -> list[dict]:
    from cheetahclaws.web import db as _db
    return _db.repo.list_folders(user_id)


def create_folder(user_id: int, name: str) -> Optional[dict]:
    from cheetahclaws.web import db as _db
    return _db.repo.create_folder(user_id, name)


def rename_folder(folder_id: int, user_id: int, name: str) -> bool:
    from cheetahclaws.web import db as _db
    return _db.repo.rename_folder(folder_id, user_id, name)


def remove_folder(folder_id: int, user_id: int) -> bool:
    from cheetahclaws.web import db as _db
    return _db.repo.delete_folder(folder_id, user_id)


def move_session_to_folder(sid: str, user_id: int,
                            folder_id: Optional[int]) -> bool:
    from cheetahclaws.web import db as _db
    return _db.repo.move_session_to_folder(sid, user_id, folder_id)


def batch_remove_chat_sessions(sids: list, user_id: int) -> dict:
    """Delete multiple sessions for a user. Cross-user IDs are silently
    skipped (delete_session enforces ownership). Returns counts."""
    deleted = 0
    failed: list[str] = []
    for sid in sids:
        try:
            if remove_chat_session(sid, user_id):
                deleted += 1
            else:
                failed.append(sid)
        except Exception:  # noqa: BLE001
            failed.append(sid)
    return {"deleted": deleted, "failed": failed, "requested": len(sids)}


def batch_export_chat_sessions_markdown(sids: list,
                                         user_id: int) -> Optional[str]:
    """Combine multiple sessions into a single markdown document. Returns
    None when no requested session belongs to the user."""
    parts: list[str] = []
    rendered = 0
    for sid in sids:
        md = export_chat_session_markdown(sid, user_id)
        if md is None:
            continue
        rendered += 1
        if parts:
            parts.append("\n\n---\n\n")
        parts.append(md)
    if rendered == 0:
        return None
    import datetime as _dt
    header = (
        f"# Chat Export — {rendered} session"
        f"{'s' if rendered != 1 else ''}\n\n"
        f"- Exported: {_dt.datetime.now():%Y-%m-%d %H:%M}\n"
        f"- User ID: {user_id}\n\n---\n\n"
    )
    return header + "".join(parts)


def rename_chat_session(sid: str, user_id: int, title: str) -> bool:
    try:
        from cheetahclaws.web import db as _db
        ok = _db.repo.rename_session(sid, user_id, title)
    except Exception:  # noqa: BLE001
        return False
    if ok:
        with _chat_lock:
            s = _chat_sessions.get(sid)
            if s:
                s.title = title.strip()[:200] or "Untitled"
    return ok


def export_chat_session_markdown(sid: str, user_id: int) -> Optional[str]:
    """Render a session's messages as Markdown. Returns None if not found."""
    try:
        from cheetahclaws.web import db as _db
        meta = _db.repo.get_session(sid, user_id)
        if not meta:
            return None
        msgs = _db.repo.get_messages(sid)
    except Exception:  # noqa: BLE001
        return None
    import datetime as _dt
    lines: list[str] = []
    lines.append(f"# {meta['title']}")
    lines.append("")
    lines.append(f"- Session ID: `{sid}`")
    lines.append(f"- Created: {_dt.datetime.fromtimestamp(meta['created_at']):%Y-%m-%d %H:%M}")
    lines.append(f"- Messages: {len(msgs)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    for m in msgs:
        role = m.get("role", "?")
        when = _dt.datetime.fromtimestamp(m.get("created_at", 0)).strftime("%H:%M:%S")
        lines.append(f"## {role.title()} · {when}")
        lines.append("")
        lines.append(m.get("content", "") or "_(no content)_")
        if m.get("tool_calls"):
            lines.append("")
            lines.append("<details><summary>Tool calls</summary>")
            lines.append("")
            for tc in m["tool_calls"]:
                lines.append(f"- **{tc.get('name','?')}** "
                             f"(status: {tc.get('status','?')})")
                if tc.get("inputs"):
                    import json as _j
                    lines.append("  ```json")
                    lines.append("  " + _j.dumps(tc["inputs"], indent=2)
                                 .replace("\n", "\n  "))
                    lines.append("  ```")
            lines.append("")
            lines.append("</details>")
        lines.append("")
    return "\n".join(lines)


def get_available_models() -> list[dict]:
    """Return all providers and their models for the UI model picker."""
    try:
        from cheetahclaws.providers import PROVIDERS
    except ImportError:
        return []
    result = []
    for name, info in PROVIDERS.items():
        result.append({
            "provider": name,
            "models": list(info.get("models", [])),
            "context_limit": info.get("context_limit", 128000),
            "needs_api_key": info.get("api_key_env") is not None,
            "has_api_key": bool(
                os.environ.get(info.get("api_key_env") or "", "") or
                info.get("api_key", "")
            ),
        })
    return result


def reap_stale_chat_sessions():
    """Called periodically by server.py's reaper thread.

    `remove_chat_session` requires the owning user_id for ownership-check
    parity with the per-user DELETE endpoint, so we capture it from the
    cached ChatSession object — collecting `(sid, user_id)` pairs under the
    lock and applying outside it (remove_chat_session re-acquires).
    """
    stale: list[tuple[str, int]] = []
    with _chat_lock:
        for sid, session in _chat_sessions.items():
            if session.is_stale() and session.is_idle():
                stale.append((sid, session.user_id))
    for sid, user_id in stale:
        remove_chat_session(sid, user_id)
