"""
bridges/telegram.py — Telegram bot bridge for CheetahClaws.

Provides:
  - _tg_api / _tg_send / _tg_typing_loop  (HTTP helpers)
  - _tg_poll_loop  (long-polling loop, runs in daemon thread)
  - cmd_telegram   (/telegram slash command)
"""
from __future__ import annotations

import json
import os
import threading
import time as _time_mod

from cheetahclaws.ui.render import clr, info, ok, warn, err
from cheetahclaws import runtime
from cheetahclaws import logging_utils as _log
from cheetahclaws import jobs as _jobs

_telegram_thread: threading.Thread | None = None
_telegram_stop = threading.Event()

# ── Per-bridge job queue ───────────────────────────────────────────────────
# When the AI is processing a query, new messages are queued rather than dropped.
_tg_queue: list[tuple[str, str, int]] = []   # [(prompt, token, chat_id), ...]
_tg_queue_lock = threading.Lock()
_tg_busy = threading.Event()   # set while a query is running


# ── HTTP helpers ───────────────────────────────────────────────────────────

def _tg_api(token: str, method: str, params: dict = None):
    """Call Telegram Bot API. Returns parsed JSON or None on error."""
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _tg_send(token: str, chat_id: int, text: str):
    """Send a message to a Telegram chat, splitting if too long."""
    MAX = 4000
    chunks = [text[i:i+MAX] for i in range(0, len(text), MAX)]
    for chunk in chunks:
        result = _tg_api(token, "sendMessage", {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"})
        if not result or not result.get("ok"):
            _tg_api(token, "sendMessage", {"chat_id": chat_id, "text": chunk})


# Telegram bot API hard limit for sendDocument is 50 MiB; cap below that for headroom.
_TG_FILE_MAX_BYTES = 49 * 1024 * 1024


def _tg_send_keyboard(token: str, chat_id: int, text: str,
                      keyboard: list[list[dict]]) -> int:
    """Send a message with an inline keyboard. Returns message_id (0 on failure).

    `keyboard` is a list of rows; each row is a list of button dicts
    `{"text": <label>, "callback_data": <≤64 byte payload>}`.
    Falls back to plain text (no parse_mode, no keyboard) on Markdown failure
    so a button label / prompt with stray Markdown chars never blocks delivery.
    """
    md_payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": keyboard},
    }
    result = _tg_api(token, "sendMessage", md_payload)
    if not (result and result.get("ok")):
        # Retry without parse_mode but keep the keyboard.  Use a fresh dict so
        # the previous payload is not mutated (callers / log captures may hold
        # a reference to it).
        plain_kb_payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": {"inline_keyboard": keyboard},
        }
        result = _tg_api(token, "sendMessage", plain_kb_payload)
    if not (result and result.get("ok")):
        # Last resort: plain text, no keyboard. The user still sees the prompt.
        result = _tg_api(token, "sendMessage", {"chat_id": chat_id, "text": text})
    if result and result.get("ok"):
        return int(result.get("result", {}).get("message_id") or 0)
    return 0


def _tg_message_authorized(msg: dict, chat_id, config: dict | None) -> bool:
    """Shared sender check (bridges/auth.py) for one Telegram message.

    Keeps the original ``chat_id`` pin and, inside that chat, requires the
    sender to be in ``telegram_allowed_users``. A private chat with no
    allowlist auto-binds its user as owner; in a group every member must be
    listed explicitly (escape hatch: ``telegram_allow_all_senders``).
    """
    from cheetahclaws.bridges import auth as _bauth
    chat = msg.get("chat") or {}
    msg_chat_id = chat.get("id")
    if msg_chat_id != chat_id:
        return False
    if config is None:
        return True          # legacy callers: chat_id pin only
    sender = (msg.get("from") or {}).get("id")
    if sender is None and chat.get("type") == "private":
        sender = msg_chat_id     # private chat id == user id
    return _bauth.is_authorized("telegram", sender, msg_chat_id, config,
                                is_private=(chat.get("type") == "private"))


def _handle_callback_query(token: str, chat_id: int, cb: dict,
                           session_ctx, config: dict | None = None) -> None:
    """Process a single inline_keyboard click.

    Extracted from the poll loop so it can be unit-tested in isolation.
    Behavior:
      1. Reject clicks from any chat other than the configured one.
      2. Acknowledge via answerCallbackQuery so Telegram dismisses the spinner.
      3. Parse callback_data of the form ``cc:<prompt_id>:<value>``.
      4. Validate prompt_id matches session_ctx.tg_callback_prompt_id (drops
         stale clicks from a previous prompt).
      5. Edit the original message to strip the keyboard and append
         ``✓ <label>`` for visual confirmation.
      6. Set session_ctx.tg_input_value and fire tg_input_event so the
         agent thread blocked in ask_input_interactive() unblocks.
    """
    cb_id   = cb.get("id", "")
    cb_data = cb.get("data", "") or ""
    cb_chat = (cb.get("message") or {}).get("chat", {}).get("id")
    cb_msg  = (cb.get("message") or {}).get("message_id")
    cb_text = (cb.get("message") or {}).get("text", "") or ""

    unauthorized = cb_chat != chat_id
    if not unauthorized and config is not None:
        # A group member clicking someone else's approval keyboard must be
        # allowlisted too — the click answers a tool-permission prompt.
        unauthorized = not _tg_message_authorized(
            {"chat": (cb.get("message") or {}).get("chat") or {},
             "from": cb.get("from") or {}},
            chat_id, config)
    if unauthorized:
        if cb_id:
            _tg_api(token, "answerCallbackQuery",
                    {"callback_query_id": cb_id, "text": "⛔ Unauthorized"})
        return

    # Always acknowledge first so the click spinner clears even on errors below.
    if cb_id:
        _tg_api(token, "answerCallbackQuery", {"callback_query_id": cb_id})

    if not cb_data.startswith("cc:") or cb_data.count(":") < 2:
        return  # not one of ours

    _, prompt_id, value = cb_data.split(":", 2)
    expected = getattr(session_ctx, "tg_callback_prompt_id", "") or ""
    if not expected:
        # No prompt is currently waiting — this click belongs to an
        # already-answered or timed-out prompt.  Don't edit the message
        # with a fake "✓ Selected" confirmation; the user would think the
        # action took effect when in fact nothing happens (issue #84
        # follow-up).  The acknowledgeCallbackQuery above clears the
        # spinner so the click still feels handled.
        return
    if expected != prompt_id:
        # Stale click from an earlier prompt — ignore so the live prompt
        # keeps waiting for its own button press.
        return

    # Sanitize the value for visual confirmation.  Callers can pass any
    # string as the option value (it travels in callback_data), so escape
    # backticks/Markdown markers before embedding in the edited message —
    # otherwise editMessageText silently fails on parse errors and the
    # user just sees the original prompt unchanged.
    label_for_value = (
        str(value).replace("\\", "\\\\").replace("`", "'").replace("*", "·")
    )

    if cb_msg:
        new_body = cb_text + f"\n\n✓ Selected: `{label_for_value}`"
        _tg_api(token, "editMessageText", {
            "chat_id": chat_id, "message_id": cb_msg,
            "text": new_body, "parse_mode": "Markdown",
        })

    evt = getattr(session_ctx, "tg_input_event", None)
    if evt is not None:
        session_ctx.tg_input_value = value
        session_ctx.tg_callback_prompt_id = ""
        session_ctx.tg_callback_message_id = 0
        try:
            evt.set()
        except Exception:
            pass


def _tg_send_document(token: str, chat_id: int, file_path: str,
                      caption: str | None = None) -> bool:
    """Upload a local file to a Telegram chat as a document.

    Uses multipart/form-data because urllib's JSON path can't carry binary bodies.
    Returns True on success, False on any failure (and reports the reason in chat).
    """
    import os, mimetypes, uuid, urllib.request

    if not os.path.isfile(file_path):
        _tg_send(token, chat_id, f"⚠ Cannot send: file not found `{file_path}`")
        return False
    try:
        size = os.path.getsize(file_path)
    except OSError as exc:
        _tg_send(token, chat_id, f"⚠ Cannot stat `{file_path}`: {exc}")
        return False
    if size <= 0:
        _tg_send(token, chat_id, f"⚠ Skipping empty file `{file_path}`")
        return False
    if size > _TG_FILE_MAX_BYTES:
        _tg_send(token, chat_id,
                 f"⚠ File too large to send via Telegram "
                 f"({size/1024/1024:.1f} MB > 50 MB): `{file_path}`")
        return False

    fname = os.path.basename(file_path) or "file"
    mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    boundary = "----TGB" + uuid.uuid4().hex

    parts: list[bytes] = []
    def _field(name: str, value: str) -> None:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))

    _field("chat_id", str(chat_id))
    if caption:
        _field("caption", caption[:1024])
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="document"; '
        f'filename="{fname}"\r\nContent-Type: {mime}\r\n\r\n'.encode("utf-8")
    )
    try:
        with open(file_path, "rb") as fh:
            parts.append(fh.read())
    except OSError as exc:
        _tg_send(token, chat_id, f"⚠ Failed to read `{file_path}`: {exc}")
        return False
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        _tg_send(token, chat_id, f"⚠ Telegram upload failed: {exc}")
        return False
    if not data.get("ok"):
        _tg_send(token, chat_id,
                 f"⚠ Telegram rejected upload: {data.get('description', 'unknown')}")
        return False
    return True


def _tg_typing_loop(token: str, chat_id: int, stop_event: threading.Event):
    """Send 'typing...' indicator every 4 seconds until stop_event is set."""
    while not stop_event.is_set():
        _tg_api(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
        stop_event.wait(4)


# ── Poll loop ──────────────────────────────────────────────────────────────

def _tg_poll_loop(token: str, chat_id: int, config: dict) -> str:
    """Long-polling loop that reads Telegram messages and feeds them to run_query.

    Returns:
      "stopped"    — clean stop via _telegram_stop or /stop command
      "auth_error" — token rejected by Telegram (don't reconnect)
    Raises on unexpected fatal errors so the supervisor can reconnect.
    """
    from cheetahclaws.tools import _tg_thread_local
    session_ctx = runtime.get_session_ctx(config.get("_session_id", "default"))
    run_query_cb = session_ctx.run_query
    # Flush old messages
    flush = _tg_api(token, "getUpdates", {"offset": -1, "timeout": 0})
    if flush and flush.get("ok") and flush.get("result"):
        offset = flush["result"][-1]["update_id"] + 1
    else:
        offset = 0
    _tg_send(token, chat_id, "🟢 cheetahclaws is online.\nSend me a message and I'll process it.")

    while not _telegram_stop.is_set():
        try:
            result = _tg_api(token, "getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            })
            if not result or not result.get("ok"):
                if result:
                    tg_err = result.get("error_code")
                    desc   = result.get("description", "")
                    if tg_err == 401 or "unauthorized" in desc.lower():
                        _log.warn("bridge_auth_error", bridge="telegram", description=desc[:100])
                        return "auth_error"
                _telegram_stop.wait(5)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                # Inline-keyboard click — route to the callback handler and
                # skip the rest of the message pipeline for this update.
                cb = update.get("callback_query")
                if cb:
                    try:
                        _handle_callback_query(token, chat_id, cb, session_ctx,
                                               config=config)
                    except Exception as _cb_exc:
                        _log.warn("bridge_callback_error",
                                  bridge="telegram", error=str(_cb_exc)[:200])
                    continue

                msg = update.get("message", {})
                msg_chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if not _tg_message_authorized(msg, chat_id, config):
                    from cheetahclaws.bridges import auth as _bauth
                    sender = (msg.get("from") or {}).get("id")
                    _bauth.log_refusal("telegram", sender, msg_chat_id)
                    if msg_chat_id != chat_id:
                        _tg_api(token, "sendMessage", {
                            "chat_id": msg_chat_id,
                            "text": "⛔ Unauthorized."
                        })
                    elif _bauth.should_reply_refusal("telegram", sender):
                        _tg_api(token, "sendMessage", {
                            "chat_id": msg_chat_id,
                            "text": _bauth.refusal_text("telegram", sender),
                        })
                    continue

                # Handle photo messages
                photo_list = msg.get("photo")
                if photo_list:
                    caption = msg.get("caption", "").strip() or "What do you see in this image? Describe it in detail."
                    file_id = photo_list[-1]["file_id"]
                    try:
                        file_info = _tg_api(token, "getFile", {"file_id": file_id})
                        if file_info and file_info.get("ok"):
                            file_path = file_info["result"]["file_path"]
                            import urllib.request, base64
                            url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                            with urllib.request.urlopen(url, timeout=30) as resp:
                                img_bytes = resp.read()
                            b64 = base64.b64encode(img_bytes).decode("utf-8")
                            size_kb = len(img_bytes) / 1024
                            sctx = runtime.get_ctx(config)
                            sctx.pending_image = b64
                            text = caption
                            print(clr(f"\n  📩 Telegram: 📷 image ({size_kb:.0f} KB) + \"{caption[:50]}\"", "cyan"))
                        else:
                            _tg_send(token, chat_id, "⚠ Could not download image.")
                            continue
                    except Exception as e:
                        _tg_send(token, chat_id, f"⚠ Image error: {e}")
                        continue

                # Handle document/file uploads from the user.
                doc_msg = msg.get("document")
                if doc_msg and not text:
                    file_id = doc_msg["file_id"]
                    fname = doc_msg.get("file_name") or f"upload_{file_id[:8]}"
                    fsize = doc_msg.get("file_size", 0)
                    caption = msg.get("caption", "").strip()
                    if fsize and fsize > _TG_FILE_MAX_BYTES:
                        _tg_send(token, chat_id,
                                 f"⚠ File too large to receive ({fsize/1024/1024:.1f} MB).")
                        continue
                    try:
                        file_info = _tg_api(token, "getFile", {"file_id": file_id})
                        if not (file_info and file_info.get("ok")):
                            _tg_send(token, chat_id, "⚠ Could not download file.")
                            continue
                        import urllib.request, os, tempfile, re as _re
                        remote_path = file_info["result"]["file_path"]
                        url = f"https://api.telegram.org/file/bot{token}/{remote_path}"
                        with urllib.request.urlopen(url, timeout=120) as resp:
                            data = resp.read()
                        # Sanitize the filename (drop path components, control chars).
                        safe_name = _re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(fname)) or "upload"
                        target_dir = "/workspace" if os.path.isdir("/workspace") else tempfile.gettempdir()
                        saved = os.path.join(target_dir, safe_name)
                        with open(saved, "wb") as fh:
                            fh.write(data)
                        kb = len(data) / 1024
                        print(clr(f"\n  📩 Telegram: 📎 file '{safe_name}' ({kb:.0f} KB) → {saved}", "cyan"))
                        _tg_send(token, chat_id, f"📎 Saved `{safe_name}` to `{saved}`")
                        text = caption or f"I just uploaded a file at `{saved}`. Please review it."
                    except Exception as exc:
                        _tg_send(token, chat_id, f"⚠ File error: {exc}")
                        continue

                # Handle voice messages
                voice_msg = msg.get("voice") or msg.get("audio")
                if voice_msg and not text:
                    file_id = voice_msg["file_id"]
                    duration = voice_msg.get("duration", 0)
                    try:
                        file_info = _tg_api(token, "getFile", {"file_id": file_id})
                        if file_info and file_info.get("ok"):
                            file_path = file_info["result"]["file_path"]
                            import urllib.request
                            url = f"https://api.telegram.org/file/bot{token}/{file_path}"
                            with urllib.request.urlopen(url, timeout=30) as resp:
                                audio_bytes = resp.read()
                            size_kb = len(audio_bytes) / 1024
                            _tg_send(token, chat_id, f"🎙 Voice received ({duration}s, {size_kb:.0f} KB) — transcribing...")
                            print(clr(f"\n  📩 Telegram: 🎙 voice ({duration}s, {size_kb:.0f} KB)", "cyan"))
                            from cheetahclaws.voice import transcribe_audio_file
                            suffix = ".ogg" if msg.get("voice") else ".mp3"
                            transcribed = transcribe_audio_file(audio_bytes, suffix=suffix)
                            if transcribed:
                                _tg_send(token, chat_id, f"📝 Transcribed: \"{transcribed}\"")
                                text = transcribed
                            else:
                                _tg_send(token, chat_id, "⚠ No speech detected in voice message.")
                                continue
                        else:
                            _tg_send(token, chat_id, "⚠ Could not download voice message.")
                            continue
                    except Exception as e:
                        _tg_send(token, chat_id, f"⚠ Voice error: {e}")
                        continue

                if not text:
                    continue

                # Intercept text if a permission prompt is waiting
                evt = session_ctx.tg_input_event
                if evt:
                    session_ctx.tg_input_value = text
                    evt.set()
                    continue

                # ── Interactive PTY session (e.g. !claude, !python, !bash) ─
                from cheetahclaws.bridges.interactive_session import get_session, set_session, remove_session, InteractiveSession
                _sess_key = f"tg_{chat_id}"
                _active_sess = get_session(_sess_key)

                if _active_sess:
                    stripped = text.strip().lower()
                    # Normalize: "! exit" → "!exit" (handle accidental spaces)
                    _norm = stripped.replace(" ", "")
                    # Exit commands (with or without space after !)
                    _exit_set = {"!exit", "!quit", "!stop", "/exit", "/quit"}
                    if stripped in _exit_set or _norm in _exit_set or stripped == "/exit_session":
                        remove_session(_sess_key)
                        _tg_send(token, chat_id, "⏹ Interactive session ended.")
                        continue
                    # Force-refresh screen (useful when output stalled)
                    if stripped in ("!ping", "!screen", "!refresh") or _norm in ("!ping", "!screen", "!refresh"):
                        _tg_send(token, chat_id, "🔄 Refreshing screen…")
                        _active_sess.force_flush()
                        continue
                    # Route all input to the running process
                    _active_sess.send_input(text)
                    # Small acknowledgement so user knows input was received
                    _tg_send(token, chat_id, f"⌨ `{text[:60]}`")
                    continue

                # ── !sendfile <path> — explicitly mail a file to this chat ─
                if text.strip().lower().startswith("!sendfile"):
                    parts_sf = text.strip().split(None, 1)
                    if len(parts_sf) < 2 or not parts_sf[1].strip():
                        _tg_send(token, chat_id, "Usage: !sendfile <absolute_path>")
                        continue
                    target = parts_sf[1].strip().strip("`'\"")
                    def _send_file_async(path, t, cid):
                        import os
                        cap = f"📎 {os.path.basename(path)}" if os.path.isfile(path) else None
                        if _tg_send_document(t, cid, path, caption=cap):
                            _tg_send(t, cid, f"✅ Sent `{os.path.basename(path)}`.")
                    threading.Thread(target=_send_file_async,
                                     args=(target, token, chat_id), daemon=True).start()
                    continue

                # ── !agent sub-commands (remote agent control) ────────────
                if text.strip().lower().startswith("!agent"):
                    agent_args = text.strip()[6:].strip()
                    def _agent_ctrl(aargs, chat_token, cid):
                        try:
                            from cheetahclaws.agent_runner import list_runners, stop_runner, stop_all, get_runner
                            subcmd_parts = aargs.split(None, 1)
                            subcmd = subcmd_parts[0].lower() if subcmd_parts else "list"
                            rest = subcmd_parts[1] if len(subcmd_parts) > 1 else ""
                            if subcmd in ("list", "ls"):
                                runners = list_runners()
                                if not runners:
                                    _tg_send(chat_token, cid, "ℹ No agents running.")
                                else:
                                    lines = [f"🤖 {len(runners)} agent(s):"]
                                    for r in runners:
                                        lines.append(f"  • {r.name}: {r.status}")
                                        recs = r.recent_log(1)
                                        if recs:
                                            lines.append(f"    {recs[-1].summary[:80]}")
                                    _tg_send(chat_token, cid, "\n".join(lines))
                            elif subcmd == "stop":
                                target = rest.strip()
                                if not target:
                                    _tg_send(chat_token, cid, "Usage: !agent stop <name> | all")
                                elif target.lower() == "all":
                                    n = stop_all()
                                    _tg_send(chat_token, cid, f"⏹ Stopped {n} agent(s).")
                                else:
                                    ok = stop_runner(target)
                                    _tg_send(chat_token, cid, f"⏹ '{target}' stopped." if ok else f"ℹ No agent '{target}'.")
                            elif subcmd == "status":
                                name = rest.strip()
                                r = get_runner(name)
                                if r:
                                    _tg_send(chat_token, cid, r.summary_text())
                                else:
                                    _tg_send(chat_token, cid, f"ℹ No agent '{name}'.")
                            else:
                                _tg_send(chat_token, cid, "Usage: !agent list | !agent stop <name> | !agent status <name>")
                        except Exception as e:
                            _tg_send(chat_token, cid, f"⚠ agent error: {e}")
                    threading.Thread(target=_agent_ctrl,
                                     args=(agent_args, token, chat_id),
                                     daemon=True).start()
                    continue

                # Start a new interactive session with !cmd
                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    if not raw_cmd or raw_cmd.lower() == "stop":
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(_sess_key)
                        _tg_send(token, chat_id, "🛑 Stopped." if killed else "ℹ Nothing running.")
                        continue
                    # Detect interactive programs → use PTY session
                    _interactive_progs = ("claude", "python", "python3", "ipython",
                                          "bash", "sh", "zsh", "node", "irb", "pry",
                                          "sqlite3", "psql", "mysql", "redis-cli")
                    _base = raw_cmd.split()[0].split("/")[-1]
                    if _base in _interactive_progs:
                        def _start_pty(cmd, chat_token, cid, skey):
                            def _send(out): _tg_send(chat_token, cid, out)
                            try:
                                sess = InteractiveSession(cmd, _send, session_key=skey)
                                set_session(skey, sess)
                                _tg_send(chat_token, cid,
                                         f"▶ `{cmd}` started.\n"
                                         f"Type normally to interact. Send `!exit` to end.")
                            except Exception as e:
                                _tg_send(chat_token, cid, f"⚠ Could not start session: {e}")
                        threading.Thread(target=_start_pty,
                                         args=(raw_cmd, token, chat_id, _sess_key),
                                         daemon=True).start()
                        continue
                    # Non-interactive command → run and stream output
                    def _terminal_runner(cmd, chat_token, cid, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _tg_send(chat_token, cid, f"▶ `{cmd}`")
                        run_terminal(cmd, lambda out: _tg_send(chat_token, cid, out),
                                     session_key=skey, stop_event=_telegram_stop)
                    threading.Thread(target=_terminal_runner,
                                     args=(raw_cmd, token, chat_id, _sess_key),
                                     daemon=True).start()
                    continue

                # Handle Telegram bot commands
                if text.strip().startswith("/"):
                    tg_cmd = text.strip().lower()
                    if tg_cmd in ("/stop", "/off"):
                        _tg_send(token, chat_id, "🔴 Telegram bridge stopped.")
                        _telegram_stop.set()
                        break
                    elif tg_cmd == "/start":
                        _tg_send(token, chat_id, "🟢 cheetahclaws bridge is active. Send me anything.")
                        continue
                    slash_cb = session_ctx.handle_slash
                    if slash_cb:
                        def _slash_runner(_slash_text, _token, _chat_id):
                            import io as _io, sys as _sys, re as _re_ansi
                            _tg_thread_local.active = True
                            # Capture print()/info()/ok()/warn()/err() output so
                            # commands like /help (which render their menu via
                            # print) surface in the chat instead of disappearing
                            # into the server log (issue #84 follow-up).
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
                                _tg_send(_token, _chat_id, f"⚠ Error: {e}")
                                return
                            finally:
                                _sys.stdout, _sys.stderr = _orig_out, _orig_err
                                _tg_thread_local.active = False
                            _captured = (_buf_out.getvalue() + _buf_err.getvalue())
                            _captured = _re_ansi.sub(r'\x1b\[[0-9;]*m', '', _captured).strip()
                            if cmd_type == "simple":
                                cmd_name = _slash_text.strip().split()[0]
                                # Forward the captured menu/status text so the
                                # user actually sees /help, /status, /model
                                # output.  Fall back to the bare ack only when
                                # the command produced nothing.
                                if _captured:
                                    _tg_send(_token, _chat_id, _captured)
                                else:
                                    _tg_send(_token, _chat_id, f"✅ {cmd_name} executed.")
                                return
                            tg_state = session_ctx.agent_state
                            if tg_state and tg_state.messages:
                                for m in reversed(tg_state.messages):
                                    if m.get("role") == "assistant":
                                        content = m.get("content", "")
                                        if isinstance(content, list):
                                            parts = []
                                            for block in content:
                                                if isinstance(block, dict) and block.get("type") == "text":
                                                    parts.append(block["text"])
                                                elif isinstance(block, str):
                                                    parts.append(block)
                                            content = "\n".join(parts)
                                        if content:
                                            _tg_send(_token, _chat_id, content)
                                        break
                        threading.Thread(target=_slash_runner, args=(text, token, chat_id), daemon=True).start()
                    continue

                print(clr(f"\n  📩 Telegram: {text}", "cyan"))

                # ── Job dashboard & control commands ───────────────────────
                stripped_lower = text.strip().lower()
                if stripped_lower in ("!jobs", "!j", "!status"):
                    _tg_send(token, chat_id, _jobs.format_dashboard())
                    continue

                if stripped_lower.startswith("!job "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    _tg_send(token, chat_id, _jobs.format_detail(jid))
                    continue

                if stripped_lower.startswith("!retry "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    original = _jobs.get(jid)
                    if not original:
                        _tg_send(token, chat_id, f"❓ Job #{jid} not found.")
                        continue
                    retry_job = _jobs.create(original.prompt, source="telegram",
                                             retry_of=original.id)
                    _tg_send(token, chat_id,
                             f"↩ Retrying #{jid} as #{retry_job.id}:\n\"{original.title}\"")
                    _dispatch_tg_job(retry_job, original.prompt, token, chat_id,
                                     run_query_cb, session_ctx, config)
                    continue

                if stripped_lower in ("!cancel", "!kill"):
                    running = _jobs.list_running()
                    if running:
                        for j in running:
                            _jobs.cancel(j.id)
                        _tg_send(token, chat_id,
                                 f"🚫 Cancelled {len(running)} job(s).")
                    else:
                        _tg_send(token, chat_id, "ℹ No running jobs to cancel.")
                    continue

                if stripped_lower.startswith("!cancel ") or stripped_lower.startswith("!kill "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    j = _jobs.get(jid)
                    if j:
                        _jobs.cancel(jid)
                        _tg_send(token, chat_id, f"🚫 Job #{jid} cancelled.")
                    else:
                        _tg_send(token, chat_id, f"❓ Job #{jid} not found.")
                    continue

                # ── !command: run shell command and stream output ──────────
                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    sess_key = f"tg_{chat_id}"

                    if raw_cmd.lower() in ("stop", ""):
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(sess_key)
                        _tg_send(token, chat_id, "🛑 Command stopped." if killed else "ℹ No command running.")
                        continue

                    def _terminal_runner(cmd, chat_token, cid, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _tg_send(chat_token, cid, f"▶ `{cmd}`")
                        run_terminal(cmd, lambda out: _tg_send(chat_token, cid, out),
                                     session_key=skey, stop_event=_telegram_stop)

                    threading.Thread(target=_terminal_runner,
                                     args=(raw_cmd, token, chat_id, sess_key),
                                     daemon=True).start()
                    continue

                # ── Wizard / interactive input pending ────────────────────
                # If a /monitor or other interactive command is waiting for
                # user input, route this message to it instead of the AI.
                _pending_evt = getattr(session_ctx, "tg_input_event", None)
                if _pending_evt is not None:
                    session_ctx.tg_input_value = text
                    _pending_evt.set()
                    continue

                # ── Claude query: create job, queue if busy, else run now ──
                job = _jobs.create(text, source="telegram")

                if _tg_busy.is_set():
                    with _tg_queue_lock:
                        _tg_queue.append((job.id, text, token, chat_id))
                    queue_pos = len(_tg_queue)
                    _tg_send(token, chat_id,
                             f"⏳ Queued as job #{job.id} (position {queue_pos})\n"
                             f"\"{job.title}\"\n"
                             f"Use !jobs to check status.")
                    continue

                _dispatch_tg_job(job, text, token, chat_id,
                                 run_query_cb, session_ctx, config)

        except Exception:
            _telegram_stop.wait(5)

    return "stopped"


# ── Job dispatch & background runner ──────────────────────────────────────

def _dispatch_tg_job(job, q_text: str, token: str, chat_id: int,
                     run_query_cb, session_ctx, config: dict) -> None:
    """Fire job in a background thread, then drain the queue."""
    def _run():
        _tg_busy.set()
        try:
            _bg_runner(job, q_text, token, chat_id, run_query_cb, session_ctx, config)
        finally:
            _tg_busy.clear()
            _drain_tg_queue(run_query_cb, session_ctx, config)
    threading.Thread(target=_run, daemon=True).start()


def _drain_tg_queue(run_query_cb, session_ctx, config: dict) -> None:
    """Run the next queued job, if any."""
    with _tg_queue_lock:
        if not _tg_queue:
            return
        job_id, prompt, token, chat_id = _tg_queue.pop(0)

    job = _jobs.get(job_id)
    if not job or job.status == "cancelled":
        # Skip cancelled jobs, try next
        _drain_tg_queue(run_query_cb, session_ctx, config)
        return

    remaining = len(_tg_queue)
    pos_msg = f" ({remaining} more in queue)" if remaining else ""
    _tg_send(token, chat_id,
             f"▶ Starting job #{job_id}{pos_msg}:\n\"{job.title}\"")
    _dispatch_tg_job(job, prompt, token, chat_id, run_query_cb, session_ctx, config)


def _bg_runner(job, q_text: str, chat_token: str, chat_id: int,
               run_query_cb, session_ctx, config: dict) -> None:
    """Execute one AI query with full job tracking + live streaming."""

    _jobs.start(job.id)

    # Post placeholder message; we'll edit it live as chunks arrive
    init_resp = _tg_api(chat_token, "sendMessage", {
        "chat_id": chat_id,
        "text": f"⏳ Job #{job.id} running…",
    })
    msg_id = (
        (init_resp or {}).get("result", {}).get("message_id")
        if init_resp and init_resp.get("ok") else None
    )

    _chunks: list[str] = []
    _last_edit = [0.0]
    _stream_lock = threading.Lock()
    _step_lines: list[str] = []     # running list of tool invocations for progress view
    _pending_writes: list[str] = [] # file_paths from in-flight Write calls (FIFO with tool_end)
    _sent_files: set[str] = set()   # de-dup: don't mail the same path twice per turn

    def _edit_msg(force: bool = False):
        text_so_far = "".join(_chunks)
        if not text_so_far or not msg_id:
            return
        _tg_api(chat_token, "editMessageText", {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text_so_far[-4000:],
        })
        _last_edit[0] = _time_mod.monotonic()

    def _on_chunk(chunk: str):
        _chunks.append(chunk)
        _jobs.stream_result(job.id, chunk)
        with _stream_lock:
            if _time_mod.monotonic() - _last_edit[0] >= 1.2:
                _edit_msg()

    def _on_tool_start(name: str, inputs: dict):
        preview = str(inputs.get("command",
                      inputs.get("file_path",
                      inputs.get("pattern",
                      inputs.get("query", ""))))).strip()[:60]
        _jobs.add_step(job.id, name, preview)
        step_label = f"🔧 {name}" + (f": `{preview}`" if preview else "")
        _step_lines.append(step_label)
        # Send compact progress message (not one per tool, batched)
        if len(_step_lines) == 1 or len(_step_lines) % 3 == 0:
            _tg_send(chat_token, chat_id, step_label)
        # Remember Write targets so we can mail the file once the tool succeeds.
        if name == "Write":
            fp = (inputs or {}).get("file_path")
            if isinstance(fp, str) and fp:
                _pending_writes.append(fp)

    def _on_tool_end(name: str, result: str):
        _jobs.finish_step(job.id, name, result[:80] if result else "")
        if name == "Write" and _pending_writes:
            fp = _pending_writes.pop(0)
            res_lc = (result or "").lower()
            # Skip on permission denial / explicit error from the tool dispatcher.
            if fp in _sent_files or res_lc.startswith(("error", "denied")):
                return
            _sent_files.add(fp)
            def _async_send(path):
                import os
                try:
                    size = os.path.getsize(path)
                except OSError:
                    return
                cap = f"📎 {os.path.basename(path)} ({size/1024:.1f} KB)"
                _tg_send_document(chat_token, chat_id, path, caption=cap)
            threading.Thread(target=_async_send, args=(fp,), daemon=True).start()

    session_ctx.on_text_chunk = _on_chunk
    session_ctx.on_tool_start = _on_tool_start
    session_ctx.on_tool_end   = _on_tool_end   # ← now wired!

    try:
        sctx = runtime.get_ctx(config)
        sctx.telegram_incoming = True
        run_query_cb(q_text)
    except Exception as e:
        _jobs.fail(job.id, str(e))
        _tg_send(chat_token, chat_id,
                 f"❌ Job #{job.id} failed: {e}\n↩ Retry with: !retry {job.id}")
        return
    finally:
        session_ctx.on_text_chunk = None
        session_ctx.on_tool_start = None
        session_ctx.on_tool_end   = None
        sctx.telegram_incoming = False

    # Finalize
    _edit_msg(force=True)

    final_text = "".join(_chunks).strip()
    if not final_text:
        # Pure tool-use turn: grab last assistant message
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
                        final_text = content
                        _tg_send(chat_token, chat_id, content)
                    break

    _jobs.complete(job.id, final_text)

    # Send completion summary
    j = _jobs.get(job.id)
    if j and j.step_count > 0:
        dur = f"  {j.duration_s:.0f}s" if j.duration_s else ""
        _tg_send(chat_token, chat_id,
                 f"✅ Job #{job.id} done ({j.step_count} steps{dur})")


# ── Supervisor (auto-reconnect) ────────────────────────────────────────────

_TG_BACKOFF_INITIAL = 2.0
_TG_BACKOFF_MAX     = 120.0


def _tg_supervisor(token: str, chat_id: int, config: dict) -> None:
    """Wrap _tg_poll_loop with exponential-backoff reconnect on unexpected exit."""
    global _telegram_thread
    backoff = _TG_BACKOFF_INITIAL
    attempt = 0
    while not _telegram_stop.is_set():
        attempt += 1
        try:
            reason = _tg_poll_loop(token, chat_id, config)
        except Exception as exc:
            if _telegram_stop.is_set():
                break
            _log.warn("bridge_crash", bridge="telegram", attempt=attempt,
                      error=str(exc)[:200], backoff_s=backoff)
            print(clr(f"\n  ⚠ Telegram bridge crashed (attempt {attempt}), "
                      f"reconnecting in {backoff:.0f}s…", "yellow"))
            _telegram_stop.wait(backoff)
            backoff = min(backoff * 2, _TG_BACKOFF_MAX)
            continue

        if reason == "auth_error":
            print(clr("\n  ⚠ Telegram: invalid token — stopping bridge.", "yellow"))
            _log.warn("bridge_auth_error_stop", bridge="telegram")
            break
        # Clean stop or _telegram_stop set
        break

    _telegram_thread = None


# ── Slash command ──────────────────────────────────────────────────────────

def cmd_telegram(args: str, _state, config) -> bool:
    """Telegram bot bridge — receive and respond to messages via Telegram.

    Token precedence: $TELEGRAM_BOT_TOKEN (recommended) > REPL arg (deprecated) > config.json.

    Usage: /telegram <chat_id>                     — start (token from env or config)
           /telegram <bot_token> <chat_id>         — start (DEPRECATED — token leaks
                                                     into readline history)
           /telegram stop                          — stop the bridge
           /telegram status                        — show current status
    """
    global _telegram_thread, _telegram_stop
    from cheetahclaws.config import save_config
    from cheetahclaws.bridges import resolve_bridge_token, scrub_token_from_history

    parts = args.strip().split()

    if parts and parts[0].lower() in ("stop", "off"):
        if _telegram_thread and _telegram_thread.is_alive():
            _telegram_stop.set()
            _telegram_thread.join(timeout=5)
            _telegram_thread = None
            ok("Telegram bridge stopped.")
        else:
            warn("Telegram bridge is not running.")
        return True

    if parts and parts[0].lower() == "status":
        running = _telegram_thread and _telegram_thread.is_alive()
        token = config.get("telegram_token", "")
        chat_id = config.get("telegram_chat_id", 0)
        if running:
            ok(f"Telegram bridge is running. Chat ID: {chat_id}")
        elif token or os.environ.get("TELEGRAM_BOT_TOKEN"):
            info("Configured but not running. Use /telegram <chat_id> to start.")
        else:
            info("Not configured. Set $TELEGRAM_BOT_TOKEN, then /telegram <chat_id>.")
        return True

    # Parse arguments. Two supported shapes:
    #   /telegram <chat_id>             — token from env/config
    #   /telegram <token> <chat_id>     — DEPRECATED
    repl_token = ""
    chat_id_arg = ""
    if len(parts) == 1:
        chat_id_arg = parts[0]
    elif len(parts) >= 2:
        repl_token = parts[0]
        chat_id_arg = parts[1]

    token, source = resolve_bridge_token(
        "TELEGRAM_BOT_TOKEN", "telegram_token", repl_token, config
    )
    if source == "repl":
        warn(
            "Passing the bot token as a REPL argument is deprecated — it "
            "lands in readline history. Set $TELEGRAM_BOT_TOKEN and run "
            "`/telegram <chat_id>` instead."
        )
        scrub_token_from_history(token)

    if chat_id_arg:
        try:
            chat_id = int(chat_id_arg)
        except ValueError:
            err("Chat ID must be a number.")
            return True
    else:
        chat_id = config.get("telegram_chat_id", 0)

    # Persist chat_id always; persist token ONLY if it came from the REPL
    # (env-supplied tokens shouldn't be copied to disk without consent).
    if chat_id:
        config["telegram_chat_id"] = chat_id
    if source == "repl" and token:
        config["telegram_token"] = token
    save_config(config)

    if not token or not chat_id:
        err("No token+chat_id available. Set $TELEGRAM_BOT_TOKEN and "
            "run `/telegram <chat_id>`.")
        return True

    if _telegram_thread and _telegram_thread.is_alive():
        warn("Telegram bridge is already running. Use /telegram stop first.")
        return True

    me = _tg_api(token, "getMe")
    if not me or not me.get("ok"):
        err("Invalid bot token. Check your token from @BotFather.")
        return True

    bot_name = me["result"].get("username", "unknown")
    ok(f"Connected to @{bot_name}. Starting bridge...")

    _telegram_stop = threading.Event()
    _telegram_thread = threading.Thread(
        target=_tg_supervisor, args=(token, chat_id, config), daemon=True,
        name="telegram-bridge"
    )
    _telegram_thread.start()
    ok(f"Telegram bridge active. Chat ID: {chat_id}")
    info("Send messages to your bot — they'll be processed here.")
    info("Stop with /telegram stop or send /stop in Telegram.")
    return True
