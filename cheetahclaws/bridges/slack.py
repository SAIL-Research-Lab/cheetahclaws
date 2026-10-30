"""
bridges/slack.py — Slack Web API bridge for CheetahClaws.

Setup:
  1. Create a Slack App at https://api.slack.com/apps
  2. Add Bot Token Scopes: channels:history, chat:write, groups:history,
     im:history, mpim:history, channels:read
  3. Install app to workspace → copy Bot User OAuth Token (xoxb-...)
  4. Invite the bot to the target channel: /invite @<bot_name>
  5. Run /slack <token> <channel_id>
"""
from __future__ import annotations

import json
import threading
import time as _time_mod

from cheetahclaws.ui.render import clr, info, ok, warn, err
from cheetahclaws import runtime
from cheetahclaws import logging_utils as _log
from cheetahclaws import jobs as _jobs

_slack_thread: threading.Thread | None = None
_slack_stop   = threading.Event()

# ── Per-bridge job queue ───────────────────────────────────────────────────
_sl_queue: list[tuple[str, str, str, str]] = []  # [(job_id, prompt, token, channel)]
_sl_queue_lock = threading.Lock()
_sl_busy = threading.Event()

_SLACK_API_BASE      = "https://slack.com/api"
_SLACK_POLL_INTERVAL = 2
_SLACK_API_TIMEOUT   = 15
_SLACK_MAX_SEEN      = 2000
_slack_seen_ts: set[str] = set()


# ── HTTP helpers ───────────────────────────────────────────────────────────

def _slack_api(token: str, method: str, params: dict | None = None, *,
               timeout: int = _SLACK_API_TIMEOUT) -> dict | None:
    import urllib.request, urllib.parse
    url = f"{_SLACK_API_BASE}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def _slack_post(token: str, method: str, payload: dict, *,
                timeout: int = _SLACK_API_TIMEOUT) -> dict | None:
    import urllib.request
    url = f"{_SLACK_API_BASE}/{method}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def _slack_send(token: str, channel: str, text: str) -> None:
    _slack_post(token, "chat.postMessage", {"channel": channel, "text": text})


# ── Poll loop ──────────────────────────────────────────────────────────────

def _slack_poll_loop(token: str, channel: str, config: dict) -> str:
    """Returns "stopped", "auth_error", or raises on unexpected fatal error."""
    from cheetahclaws.tools import _slack_thread_local
    session_ctx = runtime.get_session_ctx(config.get("_session_id", "default"))
    run_query_cb = session_ctx.run_query

    session_ctx.slack_send = lambda ch, txt: _slack_send(token, ch, txt)
    _slack_send(token, channel, "🟢 cheetahclaws is online. Send me a message and I'll process it.")

    import time as _time
    oldest = str(_time.time())
    consecutive_failures = 0

    while not _slack_stop.is_set():
        _slack_stop.wait(_SLACK_POLL_INTERVAL)
        if _slack_stop.is_set():
            break

        try:
            result = _slack_api(token, "conversations.history", {
                "channel": channel,
                "oldest": oldest,
                "limit": 20,
            })

            if result is None:
                consecutive_failures += 1
                if consecutive_failures >= 5:
                    print(clr("\n  ⚠ Slack: repeated connection failures, retrying in 30s...", "yellow"))
                    _slack_stop.wait(30)
                    consecutive_failures = 0
                continue
            consecutive_failures = 0

            if not result.get("ok"):
                slack_err = result.get("error", "unknown")
                if slack_err in ("invalid_auth", "token_revoked", "account_inactive"):
                    print(clr(f"\n  ⚠ Slack: auth error ({slack_err}) — use /slack logout and reconnect", "yellow"))
                    _log.warn("bridge_auth_error", bridge="slack", error=slack_err)
                    session_ctx.slack_send = None
                    return "auth_error"
                print(clr(f"\n  ⚠ Slack: API error {slack_err}, retrying...", "yellow"))
                _slack_stop.wait(5)
                continue

            messages = list(reversed(result.get("messages") or []))

            for msg in messages:
                ts = msg.get("ts", "")
                if not ts:
                    continue
                if ts > oldest:
                    oldest = ts
                if ts in _slack_seen_ts:
                    continue
                _slack_seen_ts.add(ts)
                if len(_slack_seen_ts) > _SLACK_MAX_SEEN:
                    oldest_keys = sorted(_slack_seen_ts)[:500]
                    for k in oldest_keys:
                        _slack_seen_ts.discard(k)

                if msg.get("bot_id") or msg.get("subtype"):
                    continue

                text = (msg.get("text") or "").strip()
                if not text:
                    continue

                user_id = msg.get("user", "unknown")

                # ── Sender authorization (bridges/auth.py) ─────────────────
                # Anyone in the channel can post; only allowlisted users may
                # answer prompts, run !shell / slash commands or agent turns.
                # DM channel ids start with "D" (1:1 → owner auto-bind).
                from cheetahclaws.bridges import auth as _bauth
                if not _bauth.is_authorized("slack", msg.get("user", ""), channel, config,
                                            is_private=str(channel).startswith("D")):
                    _bauth.log_refusal("slack", user_id, channel)
                    print(clr(f"\n  ⛔ Slack [{user_id}] not in slack_allowed_users — ignored", "yellow"))
                    if _bauth.should_reply_refusal("slack", user_id):
                        _slack_send(token, channel, _bauth.refusal_text("slack", user_id))
                    continue

                print(clr(f"\n  📩 Slack [{user_id[:8]}]: {text}", "cyan"))

                evt = session_ctx.slack_input_event
                if evt:
                    session_ctx.slack_input_value = text
                    evt.set()
                    continue

                # ── Interactive PTY session ────────────────────────────────
                from cheetahclaws.bridges.interactive_session import get_session, set_session, remove_session, InteractiveSession
                _sess_key = f"slack_{channel}"
                _active_sess = get_session(_sess_key)

                if _active_sess:
                    stripped = text.strip().lower()
                    _norm = stripped.replace(" ", "")
                    _exit_set = {"!exit", "!quit", "!stop", "/exit", "/quit"}
                    if stripped in _exit_set or _norm in _exit_set or stripped == "/exit_session":
                        remove_session(_sess_key)
                        _slack_send(token, channel, "⏹ Interactive session ended.")
                        continue
                    if stripped in ("!ping", "!screen", "!refresh") or _norm in ("!ping", "!screen", "!refresh"):
                        _slack_send(token, channel, "🔄 Refreshing screen…")
                        _active_sess.force_flush()
                        continue
                    _active_sess.send_input(text)
                    _slack_send(token, channel, f"⌨ `{text[:60]}`")
                    continue

                # ── !agent sub-commands (remote agent control) ────────────
                if text.strip().lower().startswith("!agent"):
                    agent_args = text.strip()[6:].strip()
                    def _sl_agent_ctrl(aargs, ch):
                        def _send(msg): _slack_send(token, ch, msg)
                        try:
                            from cheetahclaws.agent_runner import list_runners, stop_runner, stop_all, get_runner
                            subcmd_parts = aargs.split(None, 1)
                            subcmd = subcmd_parts[0].lower() if subcmd_parts else "list"
                            rest = subcmd_parts[1] if len(subcmd_parts) > 1 else ""
                            if subcmd in ("list", "ls"):
                                runners = list_runners()
                                _send("ℹ No agents running." if not runners else
                                      "🤖 " + ", ".join(f"{r.name}({r.status})" for r in runners))
                            elif subcmd == "stop":
                                target = rest.strip()
                                if target.lower() == "all":
                                    n = stop_all(); _send(f"⏹ Stopped {n} agent(s).")
                                else:
                                    ok_ = stop_runner(target)
                                    _send(f"⏹ '{target}' stopped." if ok_ else f"ℹ No agent '{target}'.")
                            elif subcmd == "status":
                                r = get_runner(rest.strip())
                                _send(r.summary_text() if r else f"ℹ No agent '{rest.strip()}'.")
                            else:
                                _send("Usage: !agent list | !agent stop <name> | !agent status <name>")
                        except Exception as e:
                            _send(f"⚠ agent error: {e}")
                    threading.Thread(target=_sl_agent_ctrl, args=(agent_args, channel),
                                     daemon=True).start()
                    continue

                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    if not raw_cmd or raw_cmd.lower() == "stop":
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(_sess_key)
                        _slack_send(token, channel, "🛑 Stopped." if killed else "ℹ Nothing running.")
                        continue
                    _interactive_progs = ("claude", "python", "python3", "ipython",
                                          "bash", "sh", "zsh", "node", "irb",
                                          "sqlite3", "psql", "mysql", "redis-cli")
                    _base = raw_cmd.split()[0].split("/")[-1]
                    if _base in _interactive_progs:
                        def _start_pty_slack(cmd, ch, skey):
                            def _send(out): _slack_send(token, ch, out)
                            try:
                                sess = InteractiveSession(cmd, _send, session_key=skey)
                                set_session(skey, sess)
                                _slack_send(token, ch,
                                            f"▶ `{cmd}` started. Type normally to interact. Send `!exit` to end.")
                            except Exception as e:
                                _slack_send(token, ch, f"⚠ Could not start session: {e}")
                        threading.Thread(target=_start_pty_slack,
                                         args=(raw_cmd, channel, _sess_key),
                                         daemon=True).start()
                        continue
                    def _slack_terminal(cmd, ch, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _slack_send(token, ch, f"▶ `{cmd}`")
                        run_terminal(cmd, lambda out: _slack_send(token, ch, out),
                                     session_key=skey, stop_event=_slack_stop)
                    threading.Thread(target=_slack_terminal,
                                     args=(raw_cmd, channel, _sess_key),
                                     daemon=True).start()
                    continue

                if text.strip().lower() in ("/stop", "/off"):
                    _slack_send(token, channel, "🔴 cheetahclaws bridge stopped.")
                    _slack_stop.set()
                    break

                if text.strip().lower() == "/start":
                    _slack_send(token, channel, "🟢 cheetahclaws bridge is active. Send me anything.")
                    continue

                if text.strip().startswith("/"):
                    slash_cb = session_ctx.handle_slash
                    if slash_cb:
                        def _slack_slash_runner(_slash_text, _ch):
                            import io as _io, sys as _sys, re as _re_ansi
                            _slack_thread_local.active = True
                            sctx = runtime.get_ctx(config)
                            sctx.slack_current_channel = _ch
                            # Capture print()/info()/ok() output so commands
                            # like /help (which render via print) reach the
                            # user instead of disappearing into server logs
                            # (issue #84 follow-up — same root cause as the
                            # Telegram bridge).
                            _buf_out, _buf_err = _io.StringIO(), _io.StringIO()
                            _orig_out, _orig_err = _sys.stdout, _sys.stderr
                            class _Tee:
                                def __init__(self, *streams):
                                    self._streams = streams
                                def write(self, data):
                                    for s in self._streams:
                                        try: s.write(data)
                                        except Exception: pass
                                def flush(self):
                                    for s in self._streams:
                                        try: s.flush()
                                        except Exception: pass
                            _sys.stdout = _Tee(_orig_out, _buf_out)
                            _sys.stderr = _Tee(_orig_err, _buf_err)
                            try:
                                cmd_type = slash_cb(_slash_text)
                            except Exception as e:
                                _sys.stdout, _sys.stderr = _orig_out, _orig_err
                                _slack_send(token, _ch, f"⚠ Error: {e}")
                                return
                            finally:
                                _sys.stdout, _sys.stderr = _orig_out, _orig_err
                                _slack_thread_local.active = False
                                sctx.slack_current_channel = None
                            _captured = (_buf_out.getvalue() + _buf_err.getvalue())
                            _captured = _re_ansi.sub(r'\x1b\[[0-9;]*m', '', _captured).strip()
                            if cmd_type == "simple":
                                cmd_name = _slash_text.strip().split()[0]
                                if _captured:
                                    _slack_send(token, _ch, _captured)
                                else:
                                    _slack_send(token, _ch, f"✅ {cmd_name} executed.")
                                return
                            slack_state = session_ctx.agent_state
                            if slack_state and slack_state.messages:
                                for m in reversed(slack_state.messages):
                                    if m.get("role") == "assistant":
                                        content = m.get("content", "")
                                        if isinstance(content, list):
                                            parts = [
                                                b.get("text", "") if isinstance(b, dict) and b.get("type") == "text"
                                                else (b if isinstance(b, str) else "")
                                                for b in content
                                            ]
                                            content = "\n".join(p for p in parts if p)
                                        if content:
                                            _slack_send(token, _ch, content)
                                        break
                        threading.Thread(
                            target=_slack_slash_runner, args=(text, channel), daemon=True
                        ).start()
                    continue

                # ── !command: run shell command and stream output ──────────
                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    sess_key = f"slack_{channel}"

                    if raw_cmd.lower() in ("stop", ""):
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(sess_key)
                        _slack_send(token, channel, "🛑 Command stopped." if killed else "ℹ No command running.")
                        continue

                    def _slack_terminal(cmd, ch, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _slack_send(token, ch, f"▶ `{cmd}`")
                        run_terminal(cmd, lambda out: _slack_send(token, ch, out),
                                     session_key=skey, stop_event=_slack_stop)

                    threading.Thread(target=_slack_terminal,
                                     args=(raw_cmd, channel, sess_key),
                                     daemon=True).start()
                    continue

                # ── Job dashboard & control commands ───────────────────────
                stripped_lower = text.strip().lower()
                if stripped_lower in ("!jobs", "!j", "!status"):
                    _slack_send(token, channel, _jobs.format_dashboard())
                    continue

                if stripped_lower.startswith("!job "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    _slack_send(token, channel, _jobs.format_detail(jid))
                    continue

                if stripped_lower.startswith("!retry "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    original = _jobs.get(jid)
                    if not original:
                        _slack_send(token, channel, f"❓ Job #{jid} not found.")
                        continue
                    retry_job = _jobs.create(original.prompt, source="slack",
                                             retry_of=original.id)
                    _slack_send(token, channel,
                                f"↩ Retrying #{jid} as #{retry_job.id}:\n\"{original.title}\"")
                    _dispatch_sl_job(retry_job, original.prompt, token, channel,
                                     run_query_cb, session_ctx, config)
                    continue

                if stripped_lower in ("!cancel", "!kill"):
                    running = _jobs.list_running()
                    if running:
                        for j in running:
                            _jobs.cancel(j.id)
                        _slack_send(token, channel, f"🚫 Cancelled {len(running)} job(s).")
                    else:
                        _slack_send(token, channel, "ℹ No running jobs to cancel.")
                    continue

                if stripped_lower.startswith(("!cancel ", "!kill ")):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    j = _jobs.get(jid)
                    if j:
                        _jobs.cancel(jid)
                        _slack_send(token, channel, f"🚫 Job #{jid} cancelled.")
                    else:
                        _slack_send(token, channel, f"❓ Job #{jid} not found.")
                    continue

                # ── Wizard / interactive input pending ────────────────────
                _pending_evt = getattr(session_ctx, "slack_input_event", None)
                if _pending_evt is not None:
                    session_ctx.slack_input_value = text
                    _pending_evt.set()
                    continue

                # ── Claude query: create job, queue if busy, else run now ──
                job = _jobs.create(text, source="slack")

                if _sl_busy.is_set():
                    with _sl_queue_lock:
                        _sl_queue.append((job.id, text, token, channel))
                    queue_pos = len(_sl_queue)
                    _slack_send(token, channel,
                                f"⏳ Queued as job #{job.id} (position {queue_pos})\n"
                                f"\"{job.title}\"\n"
                                f"Use `!jobs` to check status.")
                    continue

                _dispatch_sl_job(job, text, token, channel,
                                 run_query_cb, session_ctx, config)

        except Exception:
            _slack_stop.wait(5)

    session_ctx.slack_send = None
    return "stopped"


# ── Job dispatch & background runner ──────────────────────────────────────

def _dispatch_sl_job(job, q_text: str, token: str, channel: str,
                     run_query_cb, session_ctx, config: dict) -> None:
    def _run():
        _sl_busy.set()
        try:
            _sl_bg_runner(job, q_text, token, channel, run_query_cb, session_ctx, config)
        finally:
            _sl_busy.clear()
            _drain_sl_queue(run_query_cb, session_ctx, config)
    threading.Thread(target=_run, daemon=True).start()


def _drain_sl_queue(run_query_cb, session_ctx, config: dict) -> None:
    with _sl_queue_lock:
        if not _sl_queue:
            return
        job_id, prompt, token, channel = _sl_queue.pop(0)

    job = _jobs.get(job_id)
    if not job or job.status == "cancelled":
        _drain_sl_queue(run_query_cb, session_ctx, config)
        return

    remaining = len(_sl_queue)
    pos_msg = f" ({remaining} more in queue)" if remaining else ""
    _slack_send(token, channel,
                f"▶ Starting job #{job_id}{pos_msg}:\n\"{job.title}\"")
    _dispatch_sl_job(job, prompt, token, channel, run_query_cb, session_ctx, config)


def _sl_bg_runner(job, q_text: str, token: str, channel: str,
                  run_query_cb, session_ctx, config: dict) -> None:
    """Execute one Slack AI query with full job tracking + live streaming."""

    _jobs.start(job.id)

    think_resp = _slack_post(token, "chat.postMessage", {
        "channel": channel,
        "text": f"⏳ Job #{job.id} running…",
    })
    think_ts = (think_resp or {}).get("ts") if think_resp and think_resp.get("ok") else None

    _chunks: list[str] = []
    _last_edit = [0.0]
    _stream_lock = threading.Lock()

    def _update_placeholder():
        text_so_far = "".join(_chunks)
        if not text_so_far or not think_ts:
            return
        _slack_post(token, "chat.update", {
            "channel": channel, "ts": think_ts,
            "text": text_so_far[-3000:],
        })
        _last_edit[0] = _time_mod.monotonic()

    def _on_chunk(chunk: str):
        _chunks.append(chunk)
        _jobs.stream_result(job.id, chunk)
        with _stream_lock:
            if _time_mod.monotonic() - _last_edit[0] >= 1.2:
                _update_placeholder()

    def _on_tool_start(name: str, inputs: dict):
        preview = str(inputs.get("command",
                      inputs.get("file_path",
                      inputs.get("pattern",
                      inputs.get("query", ""))))).strip()[:60]
        _jobs.add_step(job.id, name, preview)
        label = f"🔧 *{name}*" + (f": `{preview}`" if preview else "")
        _slack_send(token, channel, label)

    def _on_tool_end(name: str, result: str):
        _jobs.finish_step(job.id, name, result[:80] if result else "")

    session_ctx.on_text_chunk = _on_chunk
    session_ctx.on_tool_start = _on_tool_start
    session_ctx.on_tool_end   = _on_tool_end

    sctx = runtime.get_ctx(config)
    sctx.slack_current_channel = channel
    sctx.in_slack_turn = True
    try:
        if run_query_cb:
            run_query_cb(q_text)
    except Exception as e:
        _jobs.fail(job.id, str(e))
        _slack_send(token, channel,
                    f"❌ Job #{job.id} failed: {e}\n↩ Retry with: `!retry {job.id}`")
        return
    finally:
        session_ctx.on_text_chunk = None
        session_ctx.on_tool_start = None
        session_ctx.on_tool_end   = None
        sctx.in_slack_turn = False
        sctx.slack_current_channel = None

    _update_placeholder()

    final_text = "".join(_chunks).strip()
    if not final_text:
        state = session_ctx.agent_state
        if state and state.messages:
            for m in reversed(state.messages):
                if m.get("role") == "assistant":
                    content = m.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(
                            b.get("text", "") if isinstance(b, dict) and b.get("type") == "text"
                            else (b if isinstance(b, str) else "")
                            for b in content
                        )
                    if content:
                        if think_ts:
                            _slack_post(token, "chat.update", {
                                "channel": channel, "ts": think_ts, "text": content
                            })
                        else:
                            _slack_send(token, channel, content)
                        final_text = content
                    break

    _jobs.complete(job.id, final_text)

    j = _jobs.get(job.id)
    if j and j.step_count > 0:
        dur = f"  {j.duration_s:.0f}s" if j.duration_s else ""
        _slack_send(token, channel,
                    f"✅ Job #{job.id} done ({j.step_count} steps{dur})")

    print(clr(f"  ✅  Slack job #{job.id} done", "green"))


_SLACK_BACKOFF_INITIAL = 2.0
_SLACK_BACKOFF_MAX     = 120.0


def _slack_supervisor(token: str, channel: str, config: dict) -> None:
    """Wrap _slack_poll_loop with exponential-backoff reconnect on unexpected exit."""
    global _slack_thread
    backoff = _SLACK_BACKOFF_INITIAL
    attempt = 0
    while not _slack_stop.is_set():
        attempt += 1
        try:
            reason = _slack_poll_loop(token, channel, config)
        except Exception as exc:
            if _slack_stop.is_set():
                break
            _log.warn("bridge_crash", bridge="slack", attempt=attempt,
                      error=str(exc)[:200], backoff_s=backoff)
            print(clr(f"\n  ⚠ Slack bridge crashed (attempt {attempt}), "
                      f"reconnecting in {backoff:.0f}s…", "yellow"))
            _slack_stop.wait(backoff)
            backoff = min(backoff * 2, _SLACK_BACKOFF_MAX)
            continue

        if reason == "auth_error":
            print(clr("\n  ⚠ Slack: invalid token — stopping bridge. Use /slack logout.", "yellow"))
            _log.warn("bridge_auth_error_stop", bridge="slack")
            break
        break

    _slack_thread = None


def _slack_start_bridge(config, *, token: str = "", channel: str = "") -> None:
    """Start the Slack supervisor. Caller may pass token/channel explicitly
    (preferred — keeps env-sourced tokens off `config`); otherwise we fall
    back to the values stored on `config`."""
    global _slack_thread, _slack_stop
    token   = token   or config.get("slack_token", "")
    channel = channel or config.get("slack_channel", "")
    _slack_stop = threading.Event()
    _slack_thread = threading.Thread(
        target=_slack_supervisor, args=(token, channel, config), daemon=True,
        name="slack-bridge"
    )
    _slack_thread.start()
    ok("Slack bridge started.")
    info("Send a message in the configured Slack channel — it will be processed here.")
    info("Stop with /slack stop or send /stop in Slack.")


# ── Slash command ──────────────────────────────────────────────────────────

def cmd_slack(args: str, _state, config) -> bool:
    """Slack bot bridge — receive and respond to messages via Slack Web API.

    Token precedence: $SLACK_BOT_TOKEN (recommended) > REPL arg (deprecated) > config.json.

    Usage:
      /slack <channel_id>             — start (token from env or config)
      /slack <token> <channel_id>     — start (DEPRECATED — token leaks into history)
      /slack                          — start with saved credentials
      /slack stop                     — stop the bridge
      /slack status                   — show current status
      /slack logout                   — clear saved credentials
    """
    global _slack_thread, _slack_stop
    import os as _os
    from cheetahclaws.config import save_config
    from cheetahclaws.bridges import resolve_bridge_token, scrub_token_from_history

    parts = args.strip().split()

    if parts and parts[0].lower() in ("stop", "off"):
        if _slack_thread and _slack_thread.is_alive():
            _slack_stop.set()
            _slack_thread.join(timeout=5)
            _slack_thread = None
            ok("Slack bridge stopped.")
        else:
            warn("Slack bridge is not running.")
        return True

    if parts and parts[0].lower() == "status":
        running = _slack_thread and _slack_thread.is_alive()
        token   = config.get("slack_token", "")
        channel = config.get("slack_channel", "")
        if running:
            ok(f"Slack bridge running  (channel: {channel})")
        elif token or _os.environ.get("SLACK_BOT_TOKEN"):
            info("Configured but not running. Use /slack <channel_id> to start.")
        else:
            info("Not configured. Set $SLACK_BOT_TOKEN, then /slack <channel_id>.")
        return True

    if parts and parts[0].lower() == "logout":
        if _slack_thread and _slack_thread.is_alive():
            _slack_stop.set()
            _slack_thread.join(timeout=5)
            _slack_thread = None
        config.pop("slack_token", None)
        config.pop("slack_channel", None)
        save_config(config)
        ok("Slack credentials cleared.")
        return True

    # Parse arguments. Two supported shapes:
    #   /slack <channel_id>             — token from env/config
    #   /slack <token> <channel_id>     — DEPRECATED
    repl_token = ""
    channel_arg = ""
    if len(parts) == 1:
        channel_arg = parts[0]
    elif len(parts) >= 2 and parts[0].startswith("xoxb-"):
        repl_token = parts[0]
        channel_arg = parts[1]
    elif len(parts) >= 2:
        # First arg isn't a token shape — treat both args as channel + extra
        channel_arg = parts[0]

    token, source = resolve_bridge_token(
        "SLACK_BOT_TOKEN", "slack_token", repl_token, config
    )
    if source == "repl":
        warn(
            "Passing the Slack token as a REPL argument is deprecated — it "
            "lands in readline history. Set $SLACK_BOT_TOKEN and run "
            "`/slack <channel_id>` instead."
        )
        scrub_token_from_history(token)

    if _slack_thread and _slack_thread.is_alive():
        warn("Slack bridge is already running. Use /slack stop first.")
        return True

    channel = channel_arg or config.get("slack_channel", "")
    if channel:
        config["slack_channel"] = channel
    if source == "repl" and token:
        config["slack_token"] = token
    save_config(config)

    if not token or not channel:
        warn("No token+channel available. Set $SLACK_BOT_TOKEN and run "
             "`/slack <channel_id>`.")
        info("Get your token at https://api.slack.com/apps → OAuth & Permissions")
        return True

    me = _slack_api(token, "auth.test")
    if me is None or not me.get("ok"):
        slack_err = (me or {}).get("error", "connection failed")
        if slack_err in ("invalid_auth", "token_revoked"):
            warn(f"Slack token invalid ({slack_err}). Clear with /slack logout.")
            config.pop("slack_token", None)
            config.pop("slack_channel", None)
            save_config(config)
        else:
            warn(f"Slack auth check failed: {slack_err}. Retrying at next poll.")
        return True

    bot_name = me.get("user", "bot")
    info(f"Slack authenticated as @{bot_name}")
    _slack_start_bridge(config, token=token, channel=channel)
    return True
