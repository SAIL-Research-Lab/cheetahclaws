"""
bridges/qq.py — QQ Bot bridge for CheetahClaws.

Uses the official qq-botpy SDK (WebSocket + HTTP) to connect to QQ groups
and C2C private chats.  Runs botpy's async Client on a dedicated asyncio
event loop inside a daemon thread, bridging to CheetahClaws's synchronous
main thread via threading.Queue and threading.Event.

Setup: /qq start  — connect with configured appid/secret
       /qq stop   — stop the bridge
       /qq status — show current status

Prerequisite: pip install qq-botpy
  Obtain appid + secret from https://q.qq.com
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time as _time_mod

from cheetahclaws import jobs as _jobs
from cheetahclaws import logging_utils as _log
from cheetahclaws import runtime
from cheetahclaws.tools.interaction import _qq_thread_local
from cheetahclaws.ui.render import clr, err, info, ok, warn

_qq_thread: threading.Thread | None = None
_qq_stop = threading.Event()

# ── Per-target job queues ──────────────────────────────────────────────────
# key: target_id (group_openid or user_openid) → list of (job_id, prompt, image_b64)
_qq_queues: dict[str, list[tuple[str, str, str | None]]] = {}
_qq_queues_lock = threading.Lock()
_qq_busy: dict[str, bool] = {}
_qq_run_lock = threading.Lock()

# ── Message queue: async botpy → sync poll loop ───────────────────────────
_qq_msg_queue: asyncio.Queue | None = None  # created inside async loop

# ── Deduplication ──────────────────────────────────────────────────────────
_qq_seen_msgids: set[str] = set()

# ── Passive reply tracking ────────────────────────────────────────────────
# QQ requires passive replies reference the original msg_id or event_id within
# a short validity window. botpy documents the current group/C2C passive reply
# window as 5 minutes. Track per-target:
#   {target_id: (msg_id, event_id, next_seq, timestamp, msg_type)}
# msg_id can be None for group messages; event_id can also be None if expired.
# msg_type is "group" or "c2c" — stored here to avoid race conditions with
# RuntimeContext.qq_current_msg_type being overwritten by concurrent handlers.
_qq_reply_ctx: dict[str, tuple[str | None, str | None, int, float, str]] = {}
_qq_reply_lock = threading.Lock()

_QQ_PASSIVE_WINDOW = 300  # seconds (5 minutes)
_QQ_STREAM_INTERVAL = 2.0
_QQ_STREAM_MIN_LEN = 80
_QQ_MAX_MSG_LEN = 2000

# ── Intents ────────────────────────────────────────────────────────────────


def _make_intents():
    """Build botpy.Intents for group + C2C messages."""
    import botpy

    return botpy.Intents(public_messages=True)


# ── Send helpers (called from main thread) ─────────────────────────────────


def _qq_log_send_future(future, route_name: str, target_id: str) -> None:
    """Surface async QQ HTTP failures scheduled via run_coroutine_threadsafe."""
    try:
        exc = future.exception()
    except Exception as callback_exc:
        _log.warn(
            "qq_send_future_error",
            route=route_name,
            target_id=target_id,
            error=str(callback_exc)[:200],
        )
        return
    if exc is not None:
        _log.warn(
            "qq_send_api_error",
            route=route_name,
            target_id=target_id,
            error=str(exc)[:200],
        )


async def _qq_post_group(
    api,
    group_openid: str,
    content: str,
    msg_id: str | None = None,
    event_id: str | None = None,
    msg_seq: int = 1,
) -> None:
    """Send text to a QQ group via botpy HTTP layer with a clean payload.

    We bypass api.post_group_message() because it uses ``locals()`` which
    includes all None-valued keyword args (embed, ark, etc.) that the QQ
    API rejects with error 11255.

    For passive replies within 5 minutes, provide either msg_id or event_id.
    """
    from botpy.http import Route

    payload: dict = {
        "group_openid": group_openid,
        "msg_type": 0,
        "content": content[:_QQ_MAX_MSG_LEN],
    }
    if msg_id:
        payload["msg_id"] = msg_id
        payload["msg_seq"] = msg_seq
    elif event_id:
        payload["event_id"] = event_id
        payload["msg_seq"] = msg_seq

    await api._http.request(
        Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid),
        json=payload,
    )


async def _qq_post_c2c(
    api,
    openid: str,
    content: str,
    msg_id: str | None = None,
    event_id: str | None = None,
    msg_seq: int = 1,
) -> None:
    """Send text to a C2C user via botpy HTTP layer with a clean payload.

    For passive replies within 5 minutes, provide either msg_id or event_id.
    """
    from botpy.http import Route

    payload: dict = {
        "openid": openid,
        "msg_type": 0,
        "content": content[:_QQ_MAX_MSG_LEN],
    }
    if msg_id:
        payload["msg_id"] = msg_id
        payload["msg_seq"] = msg_seq
    elif event_id:
        payload["event_id"] = event_id
        payload["msg_seq"] = msg_seq
    await api._http.request(
        Route("POST", "/v2/users/{openid}/messages", openid=openid),
        json=payload,
    )


def _qq_send_group(
    api,
    group_openid: str,
    content: str,
    msg_id: str | None = None,
    event_id: str | None = None,
    msg_seq: int = 1,
) -> None:
    """Send text to a QQ group (thread-safe wrapper)."""
    try:
        loop = _get_async_loop()
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                _qq_post_group(api, group_openid, content, msg_id, event_id, msg_seq),
                loop,
            )
            future.add_done_callback(
                lambda fut: _qq_log_send_future(fut, "group", group_openid)
            )
    except Exception as exc:
        _log.warn("qq_send_group_error", error=str(exc)[:200])


def _qq_send_c2c(
    api,
    openid: str,
    content: str,
    msg_id: str | None = None,
    event_id: str | None = None,
    msg_seq: int = 1,
) -> None:
    """Send text to a C2C user (thread-safe wrapper)."""
    try:
        loop = _get_async_loop()
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                _qq_post_c2c(api, openid, content, msg_id, event_id, msg_seq),
                loop,
            )
            future.add_done_callback(
                lambda fut: _qq_log_send_future(fut, "c2c", openid)
            )
    except Exception as exc:
        _log.warn("qq_send_c2c_error", error=str(exc)[:200])


def _qq_send(
    target_id: str, text: str, config: dict, msg_type: str | None = None
) -> None:
    """High-level send: route to group or C2C.

    If msg_type is provided, use it directly (avoids race conditions
    when called from a background thread).

    Otherwise fall back to the msg_type stored in _qq_reply_ctx for this
    target_id (set when the message was first received).  This is safer
    than RuntimeContext because the latter can be overwritten by concurrent
    handlers.

    Final fallback: RuntimeContext.qq_current_msg_type or "group".
    """
    # Defensive: if target_id is empty, try thread-local fallback (avoids 404
    # when concurrent handlers clear RuntimeContext.qq_current_target_id).
    if not target_id:
        target_id = getattr(_qq_thread_local, "target_id", "") or ""
    if not target_id:
        _log.warn("qq_send_empty_target_id", text_preview=text[:80])
        return

    if msg_type is None:
        with _qq_reply_lock:
            ctx = _qq_reply_ctx.get(target_id)
            if ctx and len(ctx) >= 5:
                msg_type = ctx[4]  # msg_type stored at index 4
        if msg_type is None:
            sctx = runtime.get_ctx(config)
            msg_type = getattr(sctx, "qq_current_msg_type", "") or "group"
    api = _qq_api_client
    if api is None:
        return

    if not text or not text.strip():
        return

    with _qq_reply_lock:
        ctx = _qq_reply_ctx.get(target_id)
        if ctx:
            msg_id, event_id, seq, ts = ctx[0], ctx[1], ctx[2], ctx[3]
            stored_type = ctx[4] if len(ctx) > 4 else (msg_type or "group")
            if _time_mod.time() - ts > _QQ_PASSIVE_WINDOW:
                # Clear both msg_id and event_id when window expires;
                # active pushes do not need msg_seq.
                msg_id, event_id, seq = None, None, 0
            seq += 1  # first call: 0→1, second: 1→2, etc.
            _qq_reply_ctx[target_id] = (
                msg_id,
                event_id,
                seq,
                _time_mod.time(),
                stored_type,
            )
        else:
            msg_id, event_id, seq = None, None, 1

    chunks = [
        text[i : i + _QQ_MAX_MSG_LEN]
        for i in range(0, max(len(text), 1), _QQ_MAX_MSG_LEN)
    ]
    for chunk in chunks:
        if msg_type == "c2c":
            _qq_send_c2c(api, target_id, chunk, msg_id, event_id, seq)
        else:
            _qq_send_group(api, target_id, chunk, msg_id, event_id, seq)
        if msg_id or event_id:
            seq += 1

    # Update stored seq so the next _qq_send starts after the last used seq.
    # Without this, multi-chunk messages reuse the same seq values.
    if (msg_id or event_id) and target_id in _qq_reply_ctx:
        with _qq_reply_lock:
            ctx = _qq_reply_ctx.get(target_id)
            if ctx:
                _qq_reply_ctx[target_id] = (
                    ctx[0], ctx[1], seq, _time_mod.time(), ctx[4]
                )


# ── Async loop management ──────────────────────────────────────────────────

_async_loop: asyncio.AbstractEventLoop | None = None
_qq_api_client = None  # botpy client.api — module-level to avoid mutating config dict


def _get_async_loop() -> asyncio.AbstractEventLoop | None:
    return _async_loop


# ── botpy logging suppression ──────────────────────────────────────────────


def _mute_botpy():
    """Raise all botpy loggers (and their handlers) to WARNING."""
    import logging

    for _logger_name in list(logging.root.manager.loggerDict):
        if _logger_name.startswith("botpy"):
            _lg = logging.getLogger(_logger_name)
            _lg.setLevel(logging.WARNING)
            for _h in _lg.handlers:
                _h.setLevel(logging.WARNING)


# ── Blocking image fetch (runs in executor, never on the event loop) ───────


def _qq_download_image_b64(url: str) -> str | None:
    """Fetch an image URL and return base64.  Blocking — call only via
    ``loop.run_in_executor`` so the async botpy event loop stays responsive."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as resp:
        img_bytes = resp.read()
    return base64.b64encode(img_bytes).decode("utf-8")


# ── botpy Client subclass ──────────────────────────────────────────────────


def _create_client_class():
    """Build the QQBridgeClient class. Deferred to avoid import-time dependency on botpy."""
    import botpy
    from botpy.message import C2CMessage, GroupMessage

    class QQBridgeClient(botpy.Client):
        async def on_ready(self):
            _mute_botpy()  # suppress any loggers created at runtime
            _log.info("qq_bridge_ready", robot=getattr(self.robot, "name", ""))

        async def on_group_at_message_create(self, message: GroupMessage):
            await self._handle_message(message, "group")

        async def on_c2c_message_create(self, message: C2CMessage):
            await self._handle_message(message, "c2c")

        async def _handle_message(self, message, msg_type: str):
            import re

            # Extract text content — strip @mention prefix for group messages
            content = (message.content or "").strip()
            if msg_type == "group":
                content = re.sub(r"<@!\d+>\s*", "", content).strip()

            # Use message.id for dedup, fall back to event_id
            raw_id = getattr(message, "id", None)
            event_id = getattr(message, "event_id", None)

            dedup_id = raw_id or event_id
            if dedup_id and dedup_id in _qq_seen_msgids:
                return
            if dedup_id:
                _qq_seen_msgids.add(dedup_id)
                if len(_qq_seen_msgids) > 2000:
                    for old in list(_qq_seen_msgids)[:500]:
                        _qq_seen_msgids.discard(old)

            # Determine target ID and author
            if msg_type == "group":
                target_id = getattr(message, "group_openid", "")
                author_id = (
                    getattr(message.author, "member_openid", "")
                    if message.author
                    else ""
                )
            else:
                target_id = (
                    getattr(message.author, "user_openid", "") if message.author else ""
                )
                author_id = target_id

            # For passive replies: store both msg_id and event_id.
            # msg_id can be None for group messages; event_id should always exist.
            # QQ API accepts either msg_id or event_id for passive replies.
            reply_msg_id = raw_id if raw_id else None
            reply_event_id = event_id if event_id else None

            # Store reply context: seq starts at 0, incremented to 1 on first send
            # Also store msg_type to avoid race conditions with concurrent handlers.
            with _qq_reply_lock:
                _qq_reply_ctx[target_id] = (
                    reply_msg_id,
                    reply_event_id,
                    0,
                    _time_mod.time(),
                    msg_type,
                )

            # Download images from attachments.  urllib is blocking, so fetch
            # in the default executor — a synchronous urlopen here would freeze
            # the botpy event loop (and its WebSocket heartbeat) for up to 30s
            # per image, risking a heartbeat-timeout disconnect.
            images: list[str] = []
            loop = asyncio.get_running_loop()
            for att in message.attachments or []:
                url = getattr(att, "url", "")
                if url:
                    try:
                        img_b64 = await loop.run_in_executor(
                            None, _qq_download_image_b64, url
                        )
                        if img_b64:
                            images.append(img_b64)
                    except Exception as exc:
                        _log.warn("qq_image_download_error", error=str(exc)[:200])

            if not content and images:
                content = "What do you see in this image? Describe it in detail."
            if not content:
                return

            # Enqueue for the sync poll loop
            if _qq_msg_queue is not None:
                await _qq_msg_queue.put(
                    {
                        "content": content,
                        "target_id": target_id,
                        "author_id": author_id,
                        "msg_type": msg_type,
                        "msg_id": dedup_id,
                        "images": images,
                    }
                )

    return QQBridgeClient


def _qq_try_deliver_input(session_ctx, target_id: str, text: str) -> bool:
    """Deliver a pending QQ permission/input reply only from the prompt target."""
    evt = getattr(session_ctx, "qq_input_event", None)
    if evt is None:
        return False

    pending_target = getattr(session_ctx, "qq_input_target_id", "") or ""
    if pending_target != target_id:
        _log.warn(
            "qq_input_wrong_target",
            expected=pending_target,
            actual=target_id,
            text_preview=text[:80],
        )
        return False

    session_ctx.qq_input_value = text
    print(clr(f"\n  📩 QQ 权限回复: {text}", "cyan"))
    evt.set()
    return True


# ── Poll loop (daemon thread) ──────────────────────────────────────────────


def _qq_poll_loop(config: dict) -> str:
    """Run the botpy client in its own asyncio loop on this thread.

    Processes messages from _qq_msg_queue (filled by async handlers).
    Returns "stopped", or raises.
    """
    global _async_loop, _qq_msg_queue, _qq_api_client

    session_ctx = runtime.get_session_ctx(config.get("_session_id", "default"))
    run_query_cb = session_ctx.run_query

    _async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_async_loop)
    _qq_msg_queue = asyncio.Queue()

    appid = config.get("qq_appid", "")
    secret = config.get("qq_secret", "")

    QQBridgeClient = _create_client_class()
    client = QQBridgeClient(intents=_make_intents())

    _mute_botpy()  # mute before starting

    # Start the botpy client in a background task within this loop
    async def _run_botpy():
        try:
            await client.start(appid=appid, secret=secret)
        except Exception as exc:
            _log.error("qq_botpy_start_error", error=str(exc)[:200])
            raise

    botpy_task = _async_loop.create_task(_run_botpy())

    # Store the API object for send helpers (module-level, not in config dict)
    _qq_api_client = client.api

    # Set up the session-level send callback
    session_ctx.qq_send = lambda tid, txt: _qq_send(tid, txt, config)

    consecutive_failures = 0

    try:
        while not _qq_stop.is_set():
            try:
                # Drain the message queue with a timeout
                msg = _async_loop.run_until_complete(
                    asyncio.wait_for(_qq_msg_queue.get(), timeout=2.0)
                )
            except asyncio.TimeoutError:
                if botpy_task.done():
                    # Surface startup/runtime failure to the supervisor instead
                    # of leaving an alive thread with a dead botpy client.
                    botpy_task.result()
                    return "stopped"
                continue
            except Exception:
                consecutive_failures += 1
                if consecutive_failures >= 10:
                    return "stopped"
                _qq_stop.wait(1)
                continue
            consecutive_failures = 0

            if msg is None:
                continue

            text = msg["content"]
            target_id = msg["target_id"]
            msg_type = msg["msg_type"]
            images = msg.get("images") or []
            image_b64 = images[0] if images else None

            # Set qq_current_msg_type for all _qq_send calls in this message handler
            sctx = runtime.get_ctx(config)
            sctx.qq_current_target_id = target_id
            sctx.qq_current_msg_type = msg_type

            # ── Sender authorization (bridges/auth.py) ─────────────────
            # Every path below (PTY input, permission replies, slash, !shell,
            # agent jobs) is privileged, so unapproved senders stop here.
            author_id = msg.get("author_id") or ""
            from cheetahclaws.bridges import auth as _bauth
            if not _bauth.is_authorized("qq", author_id, target_id, config,
                                        is_private=(msg_type == "c2c")):
                _bauth.log_refusal("qq", author_id, target_id)
                print(clr(f"\n  ⛔ QQ [{author_id}] not in qq_allowed_users — ignored", "yellow"))
                if _bauth.should_reply_refusal("qq", author_id):
                    _qq_send(target_id, _bauth.refusal_text("qq", author_id), config, msg_type)
                continue

            # ── Interactive PTY session ────────────────────────────────
            from cheetahclaws.bridges.interactive_session import (
                InteractiveSession,
                get_session,
                remove_session,
                set_session,
            )

            _sess_key = f"qq_{target_id}"
            _active_sess = get_session(_sess_key)

            if _active_sess:
                stripped = text.strip().lower()
                _norm = stripped.replace(" ", "")
                _exit_set = {"!exit", "!quit", "!stop", "/exit", "/quit"}
                if (
                    stripped in _exit_set
                    or _norm in _exit_set
                    or stripped == "/exit_session"
                ):
                    remove_session(_sess_key)
                    _qq_send(target_id, "⏹ Interactive session ended.", config)
                    continue
                if stripped in ("!ping", "!screen", "!refresh") or _norm in (
                    "!ping",
                    "!screen",
                    "!refresh",
                ):
                    _qq_send(target_id, "⏹ Refreshing screen…", config)
                    _active_sess.force_flush()
                    continue
                _active_sess.send_input(text)
                _qq_send(target_id, f"⌨ `{text[:60]}`", config)
                continue

            # ── Permission input pending ───────────────────────────────
            if _qq_try_deliver_input(session_ctx, target_id, text):
                continue

            # ── Slash commands ─────────────────────────────────────────
            if text.strip().startswith("/"):
                slash_cb = session_ctx.handle_slash
                if slash_cb:

                    def _qq_slash_runner(_slash_text, _tid, _mtype):
                        _qq_thread_local.active = True
                        _qq_thread_local.target_id = _tid
                        _qq_thread_local.msg_type = _mtype
                        sctx = runtime.get_ctx(config)
                        sctx.qq_current_target_id = _tid
                        sctx.qq_current_msg_type = _mtype
                        try:
                            cmd_type = slash_cb(_slash_text)
                        except Exception as e:
                            _qq_send(_tid, f"⚠ Error: {e}", config)
                            return
                        finally:
                            _qq_thread_local.active = False
                            _qq_thread_local.target_id = ""
                            _qq_thread_local.msg_type = ""
                            sctx.qq_current_target_id = ""
                            sctx.qq_current_msg_type = ""
                        if cmd_type == "simple":
                            cmd_name = _slash_text.strip().split()[0]
                            _qq_send(_tid, f"✅ {cmd_name} executed.", config, _mtype)
                            return
                        qq_state = session_ctx.agent_state
                        if qq_state and qq_state.messages:
                            for m in reversed(qq_state.messages):
                                if m.get("role") == "assistant":
                                    content = m.get("content", "")
                                    if isinstance(content, list):
                                        parts = [
                                            (
                                                b.get("text", "")
                                                if isinstance(b, dict)
                                                and b.get("type") == "text"
                                                else (b if isinstance(b, str) else "")
                                            )
                                            for b in content
                                        ]
                                        content = "\n".join(p for p in parts if p)
                                    if content:
                                        _qq_send(_tid, content, config, _mtype)
                                    break

                    threading.Thread(
                        target=_qq_slash_runner,
                        args=(text, target_id, msg_type),
                        daemon=True,
                    ).start()
                continue

            # ── ! commands (shell / terminal) ──────────────────────────
            if text.strip().startswith("!"):
                raw_cmd = text.strip()[1:].strip()
                sess_key = f"qq_{target_id}"

                if raw_cmd.lower() in ("stop", ""):
                    from cheetahclaws.bridges.terminal_runner import stop_terminal

                    killed = stop_terminal(sess_key)
                    _qq_send(
                        target_id,
                        "🛑 Command stopped." if killed else "ℹ No command running.",
                        config,
                    )
                    continue

                _interactive_progs = (
                    "claude",
                    "python",
                    "python3",
                    "ipython",
                    "bash",
                    "sh",
                    "zsh",
                    "node",
                    "irb",
                    "sqlite3",
                    "psql",
                    "mysql",
                    "redis-cli",
                )
                _base = raw_cmd.split()[0].split("/")[-1]
                if _base in _interactive_progs:

                    def _start_pty_qq(cmd, tid, skey, mt):
                        def _send(out):
                            _qq_send(tid, out, config)

                        try:
                            sess = InteractiveSession(cmd, _send, session_key=skey)
                            set_session(skey, sess)
                            _qq_send(
                                tid,
                                f"▶ {cmd} 已启动\n发消息即可交互，发 !exit 结束会话",
                                config,
                            )
                        except Exception as e:
                            _qq_send(tid, f"⚠ 无法启动: {e}", config)

                    threading.Thread(
                        target=_start_pty_qq,
                        args=(raw_cmd, target_id, sess_key, msg_type),
                        daemon=True,
                    ).start()
                    continue

                def _qq_terminal(cmd, tid, skey):
                    from cheetahclaws.bridges.terminal_runner import run_terminal

                    _qq_send(tid, f"▶ {cmd}", config)
                    run_terminal(
                        cmd,
                        lambda out: _qq_send(tid, out, config),
                        session_key=skey,
                        stop_event=_qq_stop,
                    )

                threading.Thread(
                    target=_qq_terminal,
                    args=(raw_cmd, target_id, sess_key),
                    daemon=True,
                ).start()
                continue

            # ── Job dashboard & control commands ───────────────────────
            stripped_lower = text.strip().lower()
            if stripped_lower in ("!jobs", "!j", "!status"):
                _qq_send(target_id, _jobs.format_dashboard(), config)
                continue

            if stripped_lower.startswith("!job "):
                jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                _qq_send(target_id, _jobs.format_detail(jid), config)
                continue

            if stripped_lower.startswith("!retry "):
                jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                original = _jobs.get(jid)
                if not original:
                    _qq_send(target_id, f"❓ Job #{jid} not found.", config)
                    continue
                retry_job = _jobs.create(
                    original.prompt, source="qq", retry_of=original.id
                )
                _qq_send(
                    target_id,
                    f'↩ Retrying #{jid} as #{retry_job.id}:\n"{original.title}"',
                    config,
                )
                queued_pos = _queue_or_dispatch_qq_job(
                    retry_job,
                    original.prompt,
                    target_id,
                    msg_type,
                    run_query_cb,
                    session_ctx,
                    config,
                )
                if queued_pos:
                    _qq_send(
                        target_id,
                        f"⏳ 已排队 #{retry_job.id}（第 {queued_pos} 位）\n"
                        f"「{retry_job.title}」\n"
                        f"发 !jobs 查看进度",
                        config,
                    )
                continue

            if stripped_lower in ("!cancel", "!kill"):
                running = _jobs.list_running()
                if running:
                    for j in running:
                        _jobs.cancel(j.id)
                    _qq_send(target_id, f"🚫 已取消 {len(running)} 个任务", config)
                else:
                    _qq_send(target_id, "ℹ 当前没有运行中的任务", config)
                continue

            if stripped_lower.startswith(("!cancel ", "!kill ")):
                jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                j = _jobs.get(jid)
                if j:
                    _jobs.cancel(jid)
                    _qq_send(target_id, f"🚫 任务 #{jid} 已取消", config)
                else:
                    _qq_send(target_id, f"❓ 找不到任务 #{jid}", config)
                continue

            # ── Claude query: create job, queue if busy, else run now ──
            print(clr(f"\n  📩 QQ: {text}", "cyan"))
            if image_b64:
                print(clr("  📎 QQ image attachment received", "dim"))
            job = _jobs.create(text, source="qq")

            queue_pos = _queue_or_dispatch_qq_job(
                job,
                text,
                target_id,
                msg_type,
                run_query_cb,
                session_ctx,
                config,
                image_b64,
            )
            if queue_pos:
                _qq_send(
                    target_id,
                    f"⏳ 已排队 #{job.id}（第 {queue_pos} 位）\n"
                    f"「{job.title}」\n"
                    f"发 !jobs 查看进度",
                    config,
                )

    except Exception:
        if not _qq_stop.is_set():
            raise
    finally:
        botpy_task.cancel()
        try:
            _async_loop.run_until_complete(
                asyncio.wait_for(
                    asyncio.gather(botpy_task, return_exceptions=True), timeout=5.0
                )
            )
        except Exception:
            pass
        _async_loop.stop()
        _async_loop = None
        _qq_msg_queue = None
        _qq_api_client = None
        session_ctx.qq_send = None

    return "stopped"


# ── Job dispatch & background runner ──────────────────────────────────────


def _queue_or_dispatch_qq_job(
    job,
    q_text: str,
    target_id: str,
    msg_type: str,
    run_query_cb,
    session_ctx,
    config: dict,
    image_b64: str | None = None,
) -> int:
    """Queue a QQ job if target is busy, otherwise mark busy and dispatch it.

    Returns 0 when dispatched immediately, or the target-local queue position.
    """
    with _qq_queues_lock:
        if _qq_busy.get(target_id):
            _qq_queues.setdefault(target_id, []).append((job.id, q_text, image_b64))
            return len(_qq_queues[target_id])
        _qq_busy[target_id] = True

    _dispatch_qq_job(
        job, q_text, target_id, msg_type, run_query_cb, session_ctx, config, image_b64
    )
    return 0


def _dispatch_qq_job(
    job,
    q_text: str,
    target_id: str,
    msg_type: str,
    run_query_cb,
    session_ctx,
    config: dict,
    image_b64: str | None = None,
) -> None:
    def _run():
        try:
            _qq_bg_runner(
                job,
                q_text,
                target_id,
                msg_type,
                run_query_cb,
                session_ctx,
                config,
                image_b64,
            )
        finally:
            _drain_qq_queue(target_id, msg_type, run_query_cb, session_ctx, config)

    threading.Thread(target=_run, daemon=True).start()


def _drain_qq_queue(
    target_id: str, msg_type: str, run_query_cb, session_ctx, config: dict
) -> None:
    with _qq_queues_lock:
        queue = _qq_queues.get(target_id, [])
        if not queue:
            _qq_busy[target_id] = False
            return
        job_id, prompt, image_b64 = queue.pop(0)
        _qq_busy[target_id] = True

    job = _jobs.get(job_id)
    if not job or job.status == "cancelled":
        _drain_qq_queue(target_id, msg_type, run_query_cb, session_ctx, config)
        return

    remaining = len(_qq_queues.get(target_id, []))
    pos_msg = f"（还有 {remaining} 个待处理）" if remaining else ""
    _qq_send(
        target_id, f"▶ 开始执行 #{job_id}{pos_msg}：\n「{job.title}」", config, msg_type
    )
    _dispatch_qq_job(
        job, prompt, target_id, msg_type, run_query_cb, session_ctx, config, image_b64
    )


def _qq_bg_runner(
    job,
    q_text: str,
    target_id: str,
    msg_type: str,
    run_query_cb,
    session_ctx,
    config: dict,
    image_b64: str | None = None,
) -> None:
    """Execute one QQ AI query with job tracking.

    QQ does not support message editing — we buffer chunks and send
    a new message every ~2 seconds as text arrives.
    """
    _jobs.start(job.id)
    _qq_send(target_id, f"⏳ 任务 #{job.id} 执行中…", config, msg_type)

    _chunks: list[str] = []
    _last_send = [_time_mod.monotonic()]
    _stream_lock = threading.Lock()

    def _flush_chunks():
        text_so_far = "".join(_chunks)
        if len(text_so_far) >= _QQ_STREAM_MIN_LEN:
            _qq_send(target_id, text_so_far, config, msg_type)
            _chunks.clear()
        _last_send[0] = _time_mod.monotonic()

    def _on_chunk(chunk: str):
        _chunks.append(chunk)
        _jobs.stream_result(job.id, chunk)
        with _stream_lock:
            if _time_mod.monotonic() - _last_send[0] >= _QQ_STREAM_INTERVAL:
                _flush_chunks()

    def _on_tool_start(name: str, inputs: dict):
        from cheetahclaws.ui.render import _tool_desc

        desc = _tool_desc(name, inputs or {})
        _jobs.add_step(job.id, name, desc[:80])
        label = f"⚙ {desc}"
        _qq_send(target_id, label, config, msg_type)

    def _on_tool_end(name: str, result: str):
        _jobs.finish_step(job.id, name, result[:80] if result else "")

    with _qq_run_lock:
        sctx = runtime.get_ctx(config)
        sctx.qq_current_target_id = target_id
        sctx.qq_current_msg_type = msg_type
        sctx.qq_incoming = True
        sctx.in_qq_turn = True
        if image_b64:
            sctx.pending_image = image_b64
        _qq_thread_local.active = True
        _qq_thread_local.target_id = target_id
        _qq_thread_local.msg_type = msg_type
        session_ctx.on_text_chunk = _on_chunk
        session_ctx.on_tool_start = _on_tool_start
        session_ctx.on_tool_end = _on_tool_end
        try:
            if run_query_cb:
                run_query_cb(q_text)
        except Exception as e:
            _jobs.fail(job.id, str(e))
            _qq_send(
                target_id,
                f"❌ 任务 #{job.id} 失败：{e}\n↩ 重试：!retry {job.id}",
                config,
                msg_type,
            )
            return
        finally:
            session_ctx.on_text_chunk = None
            session_ctx.on_tool_start = None
            session_ctx.on_tool_end = None
            if image_b64 and getattr(sctx, "pending_image", None) == image_b64:
                sctx.pending_image = None
            sctx.qq_incoming = False
            sctx.in_qq_turn = False
            sctx.qq_current_target_id = ""
            sctx.qq_current_msg_type = ""
            _qq_thread_local.active = False
            _qq_thread_local.target_id = ""
            _qq_thread_local.msg_type = ""

    # Flush remaining chunks
    text_so_far = "".join(_chunks).strip()
    if text_so_far:
        _qq_send(target_id, text_so_far, config, msg_type)
    elif not _chunks:
        # No streaming chunks at all - get final message from state
        state = session_ctx.agent_state
        if state and state.messages:
            for m in reversed(state.messages):
                if m.get("role") == "assistant":
                    content = m.get("content", "")
                    if isinstance(content, list):
                        content = "\n".join(
                            (
                                b.get("text", "")
                                if isinstance(b, dict) and b.get("type") == "text"
                                else (b if isinstance(b, str) else "")
                            )
                            for b in content
                        )
                    if content:
                        _qq_send(target_id, content, config, msg_type)
                    break

    full_result = text_so_far.strip()
    _jobs.complete(job.id, full_result)

    j = _jobs.get(job.id)
    if j and j.step_count > 0:
        dur = f"  {j.duration_s:.0f}s" if j.duration_s else ""
        _qq_send(
            target_id,
            f"✅ 任务 #{job.id} 完成（{j.step_count} 步{dur}）",
            config,
            msg_type,
        )


# ── Supervisor with backoff ────────────────────────────────────────────────

_QQ_BACKOFF_INITIAL = 2.0
_QQ_BACKOFF_MAX = 120.0


def _qq_supervisor(config: dict) -> None:
    """Wrap _qq_poll_loop with exponential-backoff reconnect on unexpected exit."""
    global _qq_thread
    backoff = _QQ_BACKOFF_INITIAL
    attempt = 0
    while not _qq_stop.is_set():
        attempt += 1
        try:
            reason = _qq_poll_loop(config)
        except Exception as exc:
            if _qq_stop.is_set():
                break
            _log.warn(
                "bridge_crash",
                bridge="qq",
                attempt=attempt,
                error=str(exc)[:200],
                backoff_s=backoff,
            )
            print(
                clr(
                    f"\n  ⚠ QQ bridge crashed (attempt {attempt}), "
                    f"reconnecting in {backoff:.0f}s…",
                    "yellow",
                )
            )
            _qq_stop.wait(backoff)
            backoff = min(backoff * 2, _QQ_BACKOFF_MAX)
            continue

        # Normal return without _qq_stop set → transient failure (e.g. 10 consecutive
        # errors).  Backoff and reconnect instead of giving up permanently.
        if not _qq_stop.is_set():
            _log.warn(
                "bridge_reconnect",
                bridge="qq",
                attempt=attempt,
                reason=reason,
                backoff_s=backoff,
            )
            print(
                clr(
                    f"\n  ⚠ QQ bridge exited (attempt {attempt}), "
                    f"reconnecting in {backoff:.0f}s…",
                    "yellow",
                )
            )
            _qq_stop.wait(backoff)
            backoff = min(backoff * 2, _QQ_BACKOFF_MAX)
            continue
        break

    _qq_thread = None


def _qq_start_bridge(config) -> None:
    global _qq_thread, _qq_stop
    _qq_stop = threading.Event()
    _qq_thread = threading.Thread(
        target=_qq_supervisor, args=(config,), daemon=True, name="qq-bridge"
    )
    _qq_thread.start()
    ok("QQ bridge started.")
    info("Send a message in QQ — @mention in groups or direct message in C2C.")
    info("Stop with /qq stop.")


# ── Slash command ──────────────────────────────────────────────────────────


def cmd_qq(args: str, _state, config) -> bool:
    """QQ bot bridge via official botpy SDK.

    Secret precedence: $QQ_SECRET (recommended) > REPL arg (deprecated) > config.json.

    Usage: /qq <appid>                   — start (secret from $QQ_SECRET / config)
           /qq <appid> <secret>          — start (DEPRECATED — secret leaks to history)
           /qq                           — start using saved/env credentials
           /qq stop                      — stop the bridge
           /qq status                    — show current status
           /qq logout                    — clear saved credentials

    Obtain appid + secret from https://q.qq.com developer portal.
    """
    global _qq_thread, _qq_stop
    import os as _os
    from cheetahclaws.config import save_config
    from cheetahclaws.bridges import resolve_bridge_token, scrub_token_from_history

    parts = args.strip().split()

    if parts and parts[0].lower() in ("stop", "off"):
        if _qq_thread and _qq_thread.is_alive():
            _qq_stop.set()
            _qq_thread.join(timeout=5)
            _qq_thread = None
            ok("QQ bridge stopped.")
        else:
            warn("QQ bridge is not running.")
        return True

    if parts and parts[0].lower() == "status":
        running = _qq_thread and _qq_thread.is_alive()
        appid = config.get("qq_appid", "") or _os.environ.get("QQ_APPID", "")
        has_secret = bool(config.get("qq_secret") or _os.environ.get("QQ_SECRET"))
        if running:
            ok(f"QQ bridge running  (appid: {appid[:8]}…)")
        elif appid and has_secret:
            info("Configured but not running. Use /qq to start.")
        else:
            info("Not configured. Set $QQ_SECRET (and $QQ_APPID), then /qq.")
        return True

    if parts and parts[0].lower() == "logout":
        if _qq_thread and _qq_thread.is_alive():
            _qq_stop.set()
            _qq_thread.join(timeout=5)
            _qq_thread = None
        config.pop("qq_appid", None)
        config.pop("qq_secret", None)
        save_config(config)
        ok("QQ credentials cleared.")
        return True

    # Resolve credentials.  Precedence per value: env var > REPL arg > config.
    #   /qq <appid> <secret>   — both via REPL (DEPRECATED: secret leaks to history)
    #   /qq <appid>            — appid via REPL, secret from $QQ_SECRET / config
    #   /qq                    — both from env / config
    repl_appid = parts[0] if len(parts) >= 1 else ""
    repl_secret = parts[1] if len(parts) >= 2 else ""

    appid, _appid_source = resolve_bridge_token(
        "QQ_APPID", "qq_appid", repl_appid, config
    )
    secret, secret_source = resolve_bridge_token(
        "QQ_SECRET", "qq_secret", repl_secret, config
    )

    if secret_source == "repl":
        warn(
            "Passing the QQ secret as a REPL argument is deprecated — it lands "
            "in readline history. Set $QQ_SECRET and run `/qq <appid>` instead."
        )
        scrub_token_from_history(secret)

    if not appid or not secret:
        err("No config found. Set $QQ_SECRET (and $QQ_APPID), or /qq <appid> <secret>.")
        return True

    if _qq_thread and _qq_thread.is_alive():
        warn("QQ bridge is already running. Use /qq stop first.")
        return True

    # Persist the appid (a public identifier) and only a REPL-supplied secret —
    # an env-sourced secret is never written to ~/.cheetahclaws/config.json.
    config["qq_appid"] = appid
    if secret_source == "repl":
        config["qq_secret"] = secret
    save_config(config)
    if secret_source != "repl":
        # Make the live env/config secret available to the bridge thread in
        # memory only — set after save_config so it never lands on disk.
        config["qq_secret"] = secret

    _qq_start_bridge(config)
    return True
