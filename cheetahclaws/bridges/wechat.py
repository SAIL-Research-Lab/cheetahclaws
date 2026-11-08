"""
bridges/wechat.py — WeChat (iLink Bot API) bridge for CheetahClaws.

Uses Tencent's iLink Bot API to receive/send WeChat messages.
Authentication via QR code scan.

Setup: /wechat login  — scan QR code with WeChat to authenticate
       /wechat        — re-start bridge using saved credentials
       /wechat stop   — stop the bridge
       /wechat status — show current status

Prerequisite: enable the "ClawBot" plugin inside WeChat
  (WeChat → Me → Settings → Plugins → ClawBot)
"""
from __future__ import annotations

import json
import threading
import time as _time_mod
import base64 as _b64_mod
import struct as _struct_mod
import secrets as _secrets_mod

from cheetahclaws.ui.render import clr, info, ok, warn, err
from cheetahclaws import runtime
from cheetahclaws import logging_utils as _log
from cheetahclaws import jobs as _jobs

_wechat_thread: threading.Thread | None = None
_wechat_stop = threading.Event()

# ── Per-user job queues (WeChat is multi-user) ─────────────────────────────
# key: from_uid → list of (job_id, prompt)
_wx_queues: dict[str, list[tuple[str, str]]] = {}
_wx_queues_lock = threading.Lock()
_wx_busy: dict[str, bool] = {}   # from_uid → is_processing

_ILINK_BASE_URL         = "https://ilinkai.weixin.qq.com"
_ILINK_APP_ID           = "bot"
_ILINK_CLIENT_VERSION   = (2 << 16) | (2 << 8) | 0
_ILINK_CHANNEL_VERSION  = "2.2.0"
_ILINK_DEFAULT_BOT_TYPE = "3"

_WX_EP_GET_UPDATES   = "ilink/bot/getupdates"
_WX_EP_SEND_MESSAGE  = "ilink/bot/sendmessage"
_WX_EP_SEND_TYPING   = "ilink/bot/sendtyping"
_WX_EP_GET_BOT_QR    = "ilink/bot/get_bot_qrcode"
_WX_EP_GET_QR_STATUS = "ilink/bot/get_qrcode_status"

_WX_LONG_POLL_TIMEOUT = 37
_WX_API_TIMEOUT       = 15
_WX_QR_TIMEOUT        = 37

_WX_MSG_TYPE_BOT   = 2
_WX_MSG_STATE_DONE = 2
_WX_ITEM_TEXT      = 1
_WX_TYPING_START   = 1

_wx_context_tokens: dict = {}
_wx_seen_msgids: set = set()


# ── Single-instance lock ──────────────────────────────────────────────────
# Two cheetahclaws processes sharing the same WeChat session both poll the
# same inbound messages → each one independently dispatches a job → user
# sees double replies. The fix is a process-level pid lock under
# ``~/.cheetahclaws/wechat.lock`` so only one bridge runs per host. The
# second instance still works as a REPL — just without WeChat.

import os as _os_lock

_WX_LOCK_PATH = _os_lock.path.expanduser("~/.cheetahclaws/wechat.lock")
_wx_lock_acquired = False


def _wx_pid_alive(pid: int) -> bool:
    """Return True iff a process with this pid currently exists."""
    if pid <= 0:
        return False
    try:
        _os_lock.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # PermissionError → process exists but is owned by another user;
        # for our single-instance check that still counts as "running".
        return isinstance(__import__("sys").exc_info()[1], PermissionError)
    except OSError:
        return False


def _wx_acquire_lock() -> tuple[bool, int]:
    """Try to acquire the WeChat-bridge single-instance lock.

    Returns ``(acquired, holder_pid)``. ``acquired=True`` means we now own
    the lock and should start the bridge; ``False`` means another live
    cheetahclaws process owns it (``holder_pid`` is its pid). A stale
    lock (holder process dead) is silently reaped and re-acquired.
    """
    global _wx_lock_acquired
    try:
        _os_lock.makedirs(_os_lock.path.dirname(_WX_LOCK_PATH), exist_ok=True)
    except OSError:
        # Best effort — if we can't create the dir, skip the lock entirely
        # rather than blocking the bridge.
        _wx_lock_acquired = True
        return True, 0

    # Read existing holder, if any.
    if _os_lock.path.exists(_WX_LOCK_PATH):
        try:
            with open(_WX_LOCK_PATH, "r", encoding="utf-8") as _f:
                holder_pid = int((_f.read() or "0").strip() or "0")
        except (OSError, ValueError):
            holder_pid = 0
        if holder_pid and holder_pid != _os_lock.getpid() \
                and _wx_pid_alive(holder_pid):
            return False, holder_pid
        # Stale lock — fall through to overwrite.

    # Write our pid atomically (.tmp swap).
    tmp_path = _WX_LOCK_PATH + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as _f:
            _f.write(str(_os_lock.getpid()))
        _os_lock.replace(tmp_path, _WX_LOCK_PATH)
        _wx_lock_acquired = True
        # Best-effort cleanup on normal interpreter exit.
        import atexit as _atexit_lock
        _atexit_lock.register(_wx_release_lock)
        return True, _os_lock.getpid()
    except OSError:
        return True, 0       # filesystem trouble → don't block bridge


def _wx_release_lock() -> None:
    """Drop the lock if we hold it. Idempotent + safe at shutdown."""
    global _wx_lock_acquired
    if not _wx_lock_acquired:
        return
    try:
        if _os_lock.path.exists(_WX_LOCK_PATH):
            with open(_WX_LOCK_PATH, "r", encoding="utf-8") as _f:
                holder = (_f.read() or "0").strip()
            if holder == str(_os_lock.getpid()):
                _os_lock.unlink(_WX_LOCK_PATH)
    except OSError:
        pass
    _wx_lock_acquired = False


# ── HTTP helpers ───────────────────────────────────────────────────────────

def _wx_random_uin() -> str:
    value = _struct_mod.unpack(">I", _secrets_mod.token_bytes(4))[0]
    return _b64_mod.b64encode(str(value).encode()).decode("ascii")

def _wx_app_headers() -> dict:
    return {
        "iLink-App-Id": _ILINK_APP_ID,
        "iLink-App-ClientVersion": str(_ILINK_CLIENT_VERSION),
    }

def _wx_auth_headers(token: str, body: str) -> dict:
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "Content-Length": str(len(body.encode("utf-8"))),
        "X-WECHAT-UIN": _wx_random_uin(),
        **_wx_app_headers(),
    }

def _wx_get(base_url: str, endpoint: str, timeout: int = _WX_QR_TIMEOUT) -> dict | None:
    import urllib.request
    url = f"{base_url.rstrip('/')}/{endpoint}"
    req = urllib.request.Request(url, headers=_wx_app_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def _wx_post(base_url: str, endpoint: str, token: str, payload: dict,
             timeout: int = _WX_API_TIMEOUT) -> dict | None:
    import urllib.request
    payload["base_info"] = {"channel_version": _ILINK_CHANNEL_VERSION}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    url = f"{base_url.rstrip('/')}/{endpoint}"
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_wx_auth_headers(token, body))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception:
        return None

def _wx_get_updates(base_url: str, token: str, sync_buf: str) -> dict | None:
    import urllib.request, socket as _socket
    payload = {
        "get_updates_buf": sync_buf,
        "base_info": {"channel_version": _ILINK_CHANNEL_VERSION},
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    url = f"{base_url.rstrip('/')}/{_WX_EP_GET_UPDATES}"
    data = body.encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_wx_auth_headers(token, body))
    try:
        with urllib.request.urlopen(req, timeout=_WX_LONG_POLL_TIMEOUT) as resp:
            return json.loads(resp.read())
    except (_socket.timeout, TimeoutError):
        return {"ret": 0, "errcode": 0, "msgs": [], "get_updates_buf": sync_buf}
    except Exception:
        return None

def _wx_print_qr(url_or_value: str) -> None:
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url_or_value)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except ImportError:
        print(f"\n  {url_or_value}\n")
        info("(Install 'qrcode' for inline QR rendering: pip install qrcode)")

def _wx_send(user_id: str, text: str, config: dict) -> None:
    import uuid as _uuid
    token    = config.get("wechat_token", "")
    base_url = config.get("wechat_base_url", _ILINK_BASE_URL)
    if not token or not user_id:
        return
    ctx_token = _wx_context_tokens.get(user_id)
    MAX = 2000
    chunks = [text[i:i+MAX] for i in range(0, max(len(text), 1), MAX)]
    for chunk in chunks:
        msg: dict = {
            "from_user_id": "",
            "to_user_id": user_id,
            "client_id": str(_uuid.uuid4()),
            "message_type": _WX_MSG_TYPE_BOT,
            "message_state": _WX_MSG_STATE_DONE,
            "item_list": [{"type": _WX_ITEM_TEXT, "text_item": {"text": chunk}}],
        }
        if ctx_token:
            msg["context_token"] = ctx_token
        _wx_post(base_url, _WX_EP_SEND_MESSAGE, token, {"msg": msg})

def _wx_typing(user_id: str, config: dict) -> None:
    ticket = config.get(f"_wx_typing_ticket_{user_id}")
    if not ticket:
        return
    token    = config.get("wechat_token", "")
    base_url = config.get("wechat_base_url", _ILINK_BASE_URL)
    _wx_post(base_url, _WX_EP_SEND_TYPING, token, {
        "ilink_user_id": user_id,
        "typing_ticket": ticket,
        "status": _WX_TYPING_START,
    }, timeout=5)

def _wx_typing_loop(user_id: str, stop_event: threading.Event, config: dict) -> None:
    while not stop_event.is_set():
        _wx_typing(user_id, config)
        stop_event.wait(4)


# ── QR login ───────────────────────────────────────────────────────────────

def _wx_qr_login(config: dict, bot_type: str = _ILINK_DEFAULT_BOT_TYPE,
                 timeout_seconds: int = 480) -> bool:
    from cheetahclaws.config import save_config
    import time as _time

    info("Fetching WeChat QR code from iLink...")
    base_url = _ILINK_BASE_URL

    qr_resp = _wx_get(base_url, f"{_WX_EP_GET_BOT_QR}?bot_type={bot_type}")
    if not qr_resp:
        err("Could not reach iLink API. Check your network connection.")
        return False

    qrcode_value = str(qr_resp.get("qrcode") or "")
    qrcode_img   = str(qr_resp.get("qrcode_img_content") or "")
    if not qrcode_value:
        err("iLink returned an empty QR code. Try again later.")
        return False

    print()
    print(clr("  请用微信扫描以下二维码 / Scan with WeChat:", "cyan"))
    _wx_print_qr(qrcode_img or qrcode_value)
    print(clr("  等待扫码中... / Waiting for scan...", "cyan"))

    deadline      = _time.time() + timeout_seconds
    refresh_count = 0
    current_base  = base_url

    while _time.time() < deadline:
        status_resp = _wx_get(
            current_base,
            f"{_WX_EP_GET_QR_STATUS}?qrcode={qrcode_value}",
        )
        if status_resp is None:
            _time.sleep(1)
            continue

        status = str(status_resp.get("status") or "wait")

        if status == "wait":
            print(".", end="", flush=True)
        elif status == "scaned":
            print()
            info("已扫码，请在微信里点击确认 / Scanned — confirm in WeChat...")
        elif status == "scaned_but_redirect":
            redirect_host = str(status_resp.get("redirect_host") or "")
            if redirect_host:
                current_base = f"https://{redirect_host}"
        elif status == "expired":
            refresh_count += 1
            if refresh_count > 3:
                print()
                err("二维码多次过期 / QR code expired too many times. Please try again.")
                return False
            print()
            info(f"二维码已过期，正在刷新... ({refresh_count}/3) / QR expired, refreshing...")
            qr_resp = _wx_get(base_url, f"{_WX_EP_GET_BOT_QR}?bot_type={bot_type}")
            if not qr_resp:
                err("Failed to refresh QR code.")
                return False
            qrcode_value = str(qr_resp.get("qrcode") or "")
            qrcode_img   = str(qr_resp.get("qrcode_img_content") or "")
            _wx_print_qr(qrcode_img or qrcode_value)
        elif status == "confirmed":
            token    = str(status_resp.get("bot_token") or "")
            new_base = str(status_resp.get("baseurl") or base_url)
            acct_id  = str(status_resp.get("ilink_bot_id") or "")
            if not token:
                err("iLink confirmed but returned no token. Try again.")
                return False
            print()
            config["wechat_token"]    = token
            config["wechat_base_url"] = new_base
            if acct_id:
                config["wechat_account_id"] = acct_id
            save_config(config)
            ok(f"微信登录成功 / WeChat authenticated (account: {acct_id or 'unknown'})")
            return True

        _time.sleep(1)

    print()
    err("登录超时 / WeChat QR login timed out. Please try again.")
    return False


# ── Poll loop ──────────────────────────────────────────────────────────────

def _wx_sender_authorized(from_uid: str, config: dict) -> bool:
    """Shared allowlist check (bridges/auth.py) for one WeChat sender.

    ``filehelper`` is the owner's own 文件传输助手 — only the logged-in
    account can write there, so it is always trusted. ``@chatroom`` ids
    are groups and never auto-bind as owner.
    """
    from cheetahclaws.bridges import auth as _bauth
    if from_uid == "filehelper":
        return True
    return _bauth.is_authorized(
        "wechat", from_uid, from_uid, config,
        is_private=not from_uid.endswith("@chatroom"),
    )


def _wx_poll_loop(token: str, base_url: str, config: dict) -> str:
    """Returns "stopped", "auth_error", or raises on unexpected fatal error."""
    from cheetahclaws.tools import _wx_thread_local
    from cheetahclaws.bridges import wechat_smart_reply as _sr
    session_ctx = runtime.get_session_ctx(config.get("_session_id", "default"))
    run_query_cb = session_ctx.run_query
    sync_buf = ""
    consecutive_failures = 0

    session_ctx.wx_send = lambda uid, txt: _wx_send(uid, txt, config)

    # Smart-reply panel store (SQLite-backed; falls back to in-memory) and
    # contacts loader, lifecycles bound to the poll loop.
    _smart_store = _sr.make_store(
        timeout_s=float(config.get("wechat_smart_reply_timeout_s",
                                    _sr.DEFAULT_TIMEOUT_S)),
    )
    _smart_store.start_janitor()
    _smart_contacts = _sr.ContactsStore()

    while not _wechat_stop.is_set():
        try:
            result = _wx_get_updates(base_url, token, sync_buf)
            if result is None:
                consecutive_failures += 1
                if consecutive_failures >= 3:
                    print(clr("\n  ⚠ WeChat: repeated connection failures, retrying in 30s...", "yellow"))
                    _wechat_stop.wait(30)
                    consecutive_failures = 0
                else:
                    _wechat_stop.wait(2)
                continue
            consecutive_failures = 0

            ret     = result.get("ret",     0)
            errcode = result.get("errcode", 0)
            if ret not in (0, None) or errcode not in (0, None):
                if ret == -14 or errcode == -14:
                    print(clr("\n  ⚠ WeChat: session expired — re-authenticate with /wechat login", "yellow"))
                    config.pop("wechat_token", None)
                    config.pop("wechat_base_url", None)
                    from cheetahclaws.config import save_config
                    save_config(config)
                    _log.warn("bridge_auth_error", bridge="wechat", ret=ret, errcode=errcode)
                    session_ctx.wx_send = None
                    return "auth_error"
                errmsg = result.get("errmsg", "")
                print(clr(f"\n  ⚠ WeChat: API error ret={ret} errcode={errcode} {errmsg}, retrying...", "yellow"))
                _wechat_stop.wait(5)
                continue

            new_buf = result.get("get_updates_buf")
            if new_buf:
                sync_buf = new_buf

            for msg in result.get("msgs") or []:
                ctx_tok  = msg.get("context_token")
                from_uid = str(msg.get("from_user_id") or "").strip()
                if ctx_tok and from_uid:
                    _wx_context_tokens[from_uid] = ctx_tok

                # Auto-record the bot owner's own uid the first time we
                # see them write to the bot.  Smart-reply uses this to
                # short-circuit (your own messages must always reach the
                # agent, regardless of what's in wechat_smart_reply_whitelist).
                # Filehelper and groups never count as "self".
                if (from_uid
                        and not config.get("wechat_self_uid")
                        and from_uid != "filehelper"
                        and not from_uid.endswith("@chatroom")):
                    config["wechat_self_uid"] = from_uid
                    try:
                        from cheetahclaws.config import save_config
                        save_config(config)
                    except Exception:
                        pass

                msg_id = msg.get("message_id") or msg.get("seq") or msg.get("client_id") or ""
                # Fallback dedup signature when the API leaves all id-like
                # fields empty: hash (from_uid, content, create_time).
                # Without this the same message would re-dispatch every
                # poll cycle until the API stops re-serving it.
                if not msg_id:
                    import hashlib as _h_dedup
                    _content_preview = ""
                    for _it in msg.get("item_list") or []:
                        if _it.get("type") == _WX_ITEM_TEXT:
                            _content_preview = (
                                (_it.get("text_item") or {})
                                .get("text", "")[:200]
                            )
                            break
                    if not _content_preview:
                        _content_preview = str(
                            msg.get("content") or msg.get("text") or ""
                        )[:200]
                    _create_time = str(msg.get("create_time")
                                        or msg.get("timestamp") or "")
                    _dedup_seed = f"{from_uid}|{_create_time}|{_content_preview}"
                    msg_id = "auto_" + _h_dedup.md5(
                        _dedup_seed.encode("utf-8", "ignore"),
                    ).hexdigest()[:16]
                if msg_id and msg_id in _wx_seen_msgids:
                    continue
                if msg_id:
                    _wx_seen_msgids.add(msg_id)
                    if len(_wx_seen_msgids) > 2000:
                        oldest = list(_wx_seen_msgids)[:500]
                        for k in oldest:
                            _wx_seen_msgids.discard(k)

                if msg.get("message_type") == 2:
                    continue

                text = ""
                for item in msg.get("item_list") or []:
                    if item.get("type") == _WX_ITEM_TEXT:
                        text = (item.get("text_item") or {}).get("text", "").strip()
                        break
                if not text:
                    text = str(msg.get("content") or msg.get("text") or "").strip()

                if not text or not from_uid:
                    continue

                evt = session_ctx.wx_input_event
                if evt and getattr(runtime.get_ctx(config), "wx_current_user_id", None) == from_uid:
                    session_ctx.wx_input_value = text
                    evt.set()
                    continue

                # ── Smart-reply: filehelper input routes panel choice ──────
                # Only consume the message if there's an active panel and
                # the user is responding to it; otherwise fall through so
                # they can still use !jobs / etc. from filehelper.
                if _sr.is_filehelper(from_uid):
                    consumed = _sr.handle_filehelper_message(
                        text, _smart_store,
                        send_to_target=lambda uid, txt: _wx_send(uid, txt, config),
                        send_to_filehelper=lambda txt: _wx_send(_sr._FILEHELPER_UID, txt, config),
                    )
                    if consumed:
                        print(clr(f"\n  ✓ smart-reply panel resolved", "dim"))
                        continue

                # ── Sender authorization (bridges/auth.py) ─────────────────
                # Everything below can reach shell / slash / agent dispatch.
                # Unapproved senders may only feed smart-reply drafting,
                # which proposes replies to the owner and runs no tools.
                if not _wx_sender_authorized(from_uid, config):
                    if _sr.is_smart_reply_target(from_uid, config, text=text):
                        label = (msg.get("from_user_nickname")
                                 or msg.get("from_username")
                                 or from_uid[:8])
                        _sr.trigger_smart_reply(
                            target_uid=from_uid,
                            target_label=str(label),
                            message=text,
                            store=_smart_store,
                            config=config,
                            send_to_filehelper=lambda txt: _wx_send(_sr._FILEHELPER_UID, txt, config),
                            contacts=_smart_contacts,
                        )
                        continue
                    from cheetahclaws.bridges import auth as _bauth
                    _bauth.log_refusal("wechat", from_uid)
                    print(clr(f"\n  ⛔ WeChat [{from_uid}] not in wechat_allowed_users — ignored", "yellow"))
                    if _bauth.should_reply_refusal("wechat", from_uid):
                        _wx_send(from_uid, _bauth.refusal_text("wechat", from_uid), config)
                    continue

                print(clr(f"\n  📩 WeChat [{from_uid}]: {text}", "cyan"))

                # ── /draft pick: digit-only reply consumes a pending draft ──
                # If the user previously ran /draft and we have candidates
                # cached for this uid, a bare "1"/"2"/"3" returns just the
                # chosen line — no agent, no smart-reply panel. One-shot.
                _stripped = text.strip()
                if _stripped.isdigit() and 1 <= int(_stripped) <= 9:
                    from cheetahclaws.bridges.draft_cache import take as _draft_take
                    _picked = _draft_take(from_uid, int(_stripped))
                    if _picked is not None:
                        _wx_send(from_uid, _picked, config)
                        print(clr(f"  ↳ /draft pick #{_stripped} sent", "dim"))
                        continue

                # ── Interactive PTY session ────────────────────────────────
                from cheetahclaws.bridges.interactive_session import get_session, set_session, remove_session, InteractiveSession
                _sess_key = f"wx_{from_uid}"
                _active_sess = get_session(_sess_key)

                if _active_sess:
                    stripped = text.strip().lower()
                    _norm = stripped.replace(" ", "")
                    _exit_set = {"!exit", "!quit", "!stop", "/exit", "/quit"}
                    if stripped in _exit_set or _norm in _exit_set or stripped == "/exit_session":
                        remove_session(_sess_key)
                        _wx_send(from_uid, "⏹ Interactive session ended.", config)
                        continue
                    if stripped in ("!ping", "!screen", "!refresh") or _norm in ("!ping", "!screen", "!refresh"):
                        _wx_send(from_uid, "🔄 Refreshing screen…", config)
                        _active_sess.force_flush()
                        continue
                    _active_sess.send_input(text)
                    _wx_send(from_uid, f"⌨ `{text[:60]}`", config)
                    continue

                # ── !agent sub-commands (remote agent control) ────────────
                if text.strip().lower().startswith("!agent"):
                    agent_args = text.strip()[6:].strip()
                    def _wx_agent_ctrl(aargs, uid):
                        def _send(msg): _wx_send(uid, msg, config)
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
                    threading.Thread(target=_wx_agent_ctrl, args=(agent_args, from_uid),
                                     daemon=True).start()
                    continue

                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    if not raw_cmd or raw_cmd.lower() == "stop":
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(_sess_key)
                        _wx_send(from_uid, "🛑 Stopped." if killed else "ℹ Nothing running.", config)
                        continue
                    _interactive_progs = ("claude", "python", "python3", "ipython",
                                          "bash", "sh", "zsh", "node", "irb",
                                          "sqlite3", "psql", "mysql", "redis-cli")
                    _base = raw_cmd.split()[0].split("/")[-1]
                    if _base in _interactive_progs:
                        def _start_pty_wx(cmd, uid, skey):
                            def _send(out): _wx_send(uid, out, config)
                            try:
                                sess = InteractiveSession(cmd, _send, session_key=skey)
                                set_session(skey, sess)
                                _wx_send(uid,
                                         f"▶ {cmd} 已启动\n发消息即可交互，发 !exit 结束会话",
                                         config)
                            except Exception as e:
                                _wx_send(uid, f"⚠ 无法启动: {e}", config)
                        threading.Thread(target=_start_pty_wx,
                                         args=(raw_cmd, from_uid, _sess_key),
                                         daemon=True).start()
                        continue
                    def _wx_terminal(cmd, uid, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _wx_send(uid, f"▶ {cmd}", config)
                        run_terminal(cmd, lambda out: _wx_send(uid, out, config),
                                     session_key=skey, stop_event=_wechat_stop)
                    threading.Thread(target=_wx_terminal,
                                     args=(raw_cmd, from_uid, _sess_key),
                                     daemon=True).start()
                    continue

                if text.strip().lower() in ("/stop", "/off"):
                    _wx_send(from_uid, "🔴 cheetahclaws bridge stopped.", config)
                    _wechat_stop.set()
                    break

                if text.strip().lower() == "/start":
                    _wx_send(from_uid, "🟢 cheetahclaws bridge is active. Send me anything.", config)
                    continue

                if text.strip().startswith("/"):
                    slash_cb = session_ctx.handle_slash
                    if slash_cb:
                        def _wx_slash_runner(_slash_text, _uid):
                            import io as _io, sys as _sys, re as _re_ansi
                            _wx_thread_local.active = True
                            sctx = runtime.get_ctx(config)
                            sctx.wx_current_user_id = _uid
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
                                _wx_send(_uid, f"⚠ Error: {e}", config)
                                return
                            finally:
                                _sys.stdout, _sys.stderr = _orig_out, _orig_err
                                _wx_thread_local.active = False
                                sctx.wx_current_user_id = None
                            _captured = (_buf_out.getvalue() + _buf_err.getvalue())
                            _captured = _re_ansi.sub(r'\x1b\[[0-9;]*m', '', _captured).strip()
                            if cmd_type == "simple":
                                cmd_name = _slash_text.strip().split()[0]
                                if _captured:
                                    _wx_send(_uid, _captured, config)
                                else:
                                    _wx_send(_uid, f"✅ {cmd_name} executed.", config)
                                return
                            wx_state = session_ctx.agent_state
                            if wx_state and wx_state.messages:
                                for m in reversed(wx_state.messages):
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
                                            _wx_send(_uid, content, config)
                                        break
                        threading.Thread(
                            target=_wx_slash_runner, args=(text, from_uid), daemon=True
                        ).start()
                    continue

                # ── !command: run shell command and stream output ──────────
                if text.strip().startswith("!"):
                    raw_cmd = text.strip()[1:].strip()
                    sess_key = f"wx_{from_uid}"

                    if raw_cmd.lower() in ("stop", ""):
                        from cheetahclaws.bridges.terminal_runner import stop_terminal
                        killed = stop_terminal(sess_key)
                        _wx_send(from_uid, "🛑 Command stopped." if killed else "ℹ No command running.", config)
                        continue

                    def _wx_terminal(cmd, uid, skey):
                        from cheetahclaws.bridges.terminal_runner import run_terminal
                        _wx_send(uid, f"▶ {cmd}", config)
                        run_terminal(cmd, lambda out: _wx_send(uid, out, config),
                                     session_key=skey, stop_event=_wechat_stop)

                    threading.Thread(target=_wx_terminal,
                                     args=(raw_cmd, from_uid, sess_key),
                                     daemon=True).start()
                    continue

                # ── Job dashboard & control commands ───────────────────────
                stripped_lower = text.strip().lower()
                if stripped_lower in ("!jobs", "!j", "!status"):
                    _wx_send(from_uid, _jobs.format_dashboard(), config)
                    continue

                if stripped_lower.startswith("!job "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    _wx_send(from_uid, _jobs.format_detail(jid), config)
                    continue

                if stripped_lower.startswith("!retry "):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    original = _jobs.get(jid)
                    if not original:
                        _wx_send(from_uid, f"❓ Job #{jid} not found.", config)
                        continue
                    retry_job = _jobs.create(original.prompt, source="wechat",
                                             retry_of=original.id)
                    _wx_send(from_uid,
                             f"↩ Retrying #{jid} as #{retry_job.id}:\n\"{original.title}\"",
                             config)
                    _dispatch_wx_job(retry_job, original.prompt, from_uid,
                                     run_query_cb, session_ctx, config)
                    continue

                if stripped_lower in ("!cancel", "!kill"):
                    running = _jobs.list_running()
                    if running:
                        for j in running:
                            _jobs.cancel(j.id)
                        _wx_send(from_uid, f"🚫 已取消 {len(running)} 个任务", config)
                    else:
                        _wx_send(from_uid, "ℹ 当前没有运行中的任务", config)
                    continue

                if stripped_lower.startswith(("!cancel ", "!kill ")):
                    jid = text.strip().split(None, 1)[1].lstrip("#").strip()
                    j = _jobs.get(jid)
                    if j:
                        _jobs.cancel(jid)
                        _wx_send(from_uid, f"🚫 任务 #{jid} 已取消", config)
                    else:
                        _wx_send(from_uid, f"❓ 找不到任务 #{jid}", config)
                    continue

                # ── Wizard / interactive input pending ────────────────────
                _pending_evt = getattr(session_ctx, "wx_input_event", None)
                if _pending_evt is not None:
                    session_ctx.wx_input_value = text
                    _pending_evt.set()
                    continue

                # ── Smart-reply: whitelisted contact → draft, don't auto-reply ─
                if _sr.is_smart_reply_target(from_uid, config, text=text):
                    label = (msg.get("from_user_nickname")
                             or msg.get("from_username")
                             or from_uid[:8])
                    triggered = _sr.trigger_smart_reply(
                        target_uid=from_uid,
                        target_label=str(label),
                        message=text,
                        store=_smart_store,
                        config=config,
                        send_to_filehelper=lambda txt: _wx_send(_sr._FILEHELPER_UID, txt, config),
                        contacts=_smart_contacts,
                    )
                    if triggered:
                        print(clr(f"  ↳ smart-reply panel sent to filehelper", "dim"))
                        continue
                    # Generation failed → fall through to normal dispatch so
                    # the user still gets *some* response.
                    print(clr(f"  ⚠ smart-reply candidate generation failed; falling back to auto-reply", "yellow"))

                # ── Claude query: create job, queue if busy, else run now ──
                job = _jobs.create(text, source="wechat")

                if _wx_busy.get(from_uid):
                    with _wx_queues_lock:
                        _wx_queues.setdefault(from_uid, []).append((job.id, text))
                    queue_pos = len(_wx_queues[from_uid])
                    _wx_send(from_uid,
                             f"⏳ 已排队 #{job.id}（第 {queue_pos} 位）\n"
                             f"「{job.title}」\n"
                             f"发 !jobs 查看进度",
                             config)
                    continue

                _dispatch_wx_job(job, text, from_uid, run_query_cb, session_ctx, config)

        except Exception:
            _wechat_stop.wait(5)

    session_ctx.wx_send = None
    return "stopped"


# ── Job dispatch & background runner ──────────────────────────────────────

def _dispatch_wx_job(job, q_text: str, uid: str,
                     run_query_cb, session_ctx, config: dict) -> None:
    """Fire job in a background thread for this user, then drain their queue.

    IMPORTANT: ``_wx_busy[uid]`` is set ``True`` SYNCHRONOUSLY before the
    thread starts. Otherwise a race window exists between
    ``_dispatch_wx_job`` returning and the thread setting the flag, during
    which a follow-up poll-cycle message would see ``_wx_busy=False`` and
    spawn a second concurrent runner for the same user (observed in the
    field as one inbound message producing 2-3 ``任务 #xxx 执行中`` lines).
    """
    _wx_busy[uid] = True

    def _run():
        try:
            _wx_bg_runner(job, q_text, uid, run_query_cb, session_ctx, config)
        finally:
            _wx_busy[uid] = False
            _drain_wx_queue(uid, run_query_cb, session_ctx, config)
    threading.Thread(target=_run, daemon=True).start()


def _drain_wx_queue(uid: str, run_query_cb, session_ctx, config: dict) -> None:
    with _wx_queues_lock:
        queue = _wx_queues.get(uid, [])
        if not queue:
            return
        job_id, prompt = queue.pop(0)

    job = _jobs.get(job_id)
    if not job or job.status == "cancelled":
        _drain_wx_queue(uid, run_query_cb, session_ctx, config)
        return

    remaining = len(_wx_queues.get(uid, []))
    pos_msg = f"（还有 {remaining} 个待处理）" if remaining else ""
    _wx_send(uid, f"▶ 开始执行 #{job_id}{pos_msg}：\n「{job.title}」", config)
    _dispatch_wx_job(job, prompt, uid, run_query_cb, session_ctx, config)


def _wx_bg_runner(job, q_text: str, uid: str,
                  run_query_cb, session_ctx, config: dict) -> None:
    """Execute one WeChat AI query with job tracking.

    WeChat does not support message editing — we buffer chunks and send
    a new message every ~3 seconds as text arrives.
    """
    _jobs.start(job.id)

    _wx_send(uid, f"⏳ 任务 #{job.id} 执行中…", config)

    _typing_stop = threading.Event()
    threading.Thread(
        target=_wx_typing_loop, args=(uid, _typing_stop, config), daemon=True
    ).start()

    _chunks: list[str] = []
    _last_send = [_time_mod.monotonic()]
    _stream_lock = threading.Lock()
    _WX_STREAM_INTERVAL = 3.0
    _WX_STREAM_MIN_LEN  = 80
    _result_buf: list[str] = []   # accumulate full result for job record

    def _flush_chunks():
        text_so_far = "".join(_chunks)
        if len(text_so_far) >= _WX_STREAM_MIN_LEN:
            _wx_send(uid, text_so_far[-2000:], config)
            _result_buf.append(text_so_far)
            _chunks.clear()
        _last_send[0] = _time_mod.monotonic()

    def _on_chunk(chunk: str):
        _chunks.append(chunk)
        _jobs.stream_result(job.id, chunk)
        with _stream_lock:
            if _time_mod.monotonic() - _last_send[0] >= _WX_STREAM_INTERVAL:
                _flush_chunks()

    def _on_tool_start(name: str, inputs: dict):
        preview = str(inputs.get("command",
                      inputs.get("file_path",
                      inputs.get("pattern",
                      inputs.get("query", ""))))).strip()[:60]
        _jobs.add_step(job.id, name, preview)
        label = f"🔧 {name}" + (f": {preview}" if preview else "")
        _wx_send(uid, label, config)

    def _on_tool_end(name: str, result: str):
        _jobs.finish_step(job.id, name, result[:80] if result else "")

    session_ctx.on_text_chunk = _on_chunk
    session_ctx.on_tool_start = _on_tool_start
    session_ctx.on_tool_end   = _on_tool_end   # ← now wired

    sctx = runtime.get_ctx(config)
    sctx.wx_current_user_id = uid
    sctx.in_wechat_turn = True
    try:
        if run_query_cb:
            run_query_cb(q_text)
    except Exception as e:
        _typing_stop.set()
        _jobs.fail(job.id, str(e))
        _wx_send(uid, f"❌ 任务 #{job.id} 失败：{e}\n↩ 重试：!retry {job.id}", config)
        return
    finally:
        session_ctx.on_text_chunk = None
        session_ctx.on_tool_start = None
        session_ctx.on_tool_end   = None
        sctx.in_wechat_turn = False
        sctx.wx_current_user_id = None

    _typing_stop.set()

    # Flush remaining chunks
    remaining_text = "".join(_chunks).strip()
    if remaining_text:
        _wx_send(uid, remaining_text, config)
        _result_buf.append(remaining_text)
    elif not _chunks and not _result_buf:
        # Nothing streamed — fall back to state.messages
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
                        _wx_send(uid, content, config)
                        _result_buf.append(content)
                    break

    full_result = "".join(_result_buf)
    _jobs.complete(job.id, full_result)

    # Send compact completion notice
    j = _jobs.get(job.id)
    if j and j.step_count > 0:
        dur = f"  {j.duration_s:.0f}s" if j.duration_s else ""
        _wx_send(uid, f"✅ 任务 #{job.id} 完成（{j.step_count} 步{dur}）", config)


_WX_BACKOFF_INITIAL = 2.0
_WX_BACKOFF_MAX     = 120.0


def _wx_supervisor(token: str, base_url: str, config: dict) -> None:
    """Wrap _wx_poll_loop with exponential-backoff reconnect on unexpected exit."""
    global _wechat_thread
    backoff = _WX_BACKOFF_INITIAL
    attempt = 0
    while not _wechat_stop.is_set():
        attempt += 1
        try:
            reason = _wx_poll_loop(token, base_url, config)
        except Exception as exc:
            if _wechat_stop.is_set():
                break
            _log.warn("bridge_crash", bridge="wechat", attempt=attempt,
                      error=str(exc)[:200], backoff_s=backoff)
            print(clr(f"\n  ⚠ WeChat bridge crashed (attempt {attempt}), "
                      f"reconnecting in {backoff:.0f}s…", "yellow"))
            _wechat_stop.wait(backoff)
            backoff = min(backoff * 2, _WX_BACKOFF_MAX)
            continue

        if reason == "auth_error":
            print(clr("\n  ⚠ WeChat: session expired — stopping bridge. Use /wechat login.", "yellow"))
            _log.warn("bridge_auth_error_stop", bridge="wechat")
            break
        break

    _wechat_thread = None


def _wx_start_bridge(config) -> None:
    global _wechat_thread, _wechat_stop

    # Single-instance guard — refuse to start a second bridge against the
    # same WeChat session (would cause double-dispatch since the two
    # processes' in-memory dedup sets are independent).
    acquired, holder_pid = _wx_acquire_lock()
    if not acquired:
        warn(f"WeChat bridge already running (pid={holder_pid}) — "
             f"this REPL will not connect to WeChat.")
        info("To take over: stop the other instance, then `/wechat start`.")
        info(f"Lock file: {_WX_LOCK_PATH}")
        return

    token    = config.get("wechat_token", "")
    base_url = config.get("wechat_base_url", _ILINK_BASE_URL)
    _wechat_stop = threading.Event()
    _wechat_thread = threading.Thread(
        target=_wx_supervisor, args=(token, base_url, config), daemon=True,
        name="wechat-bridge"
    )
    _wechat_thread.start()
    ok("WeChat bridge started.")
    info("Send a message from WeChat — it will be processed here.")
    info("Stop with /wechat stop or send /stop from WeChat.")


# ── Slash command ──────────────────────────────────────────────────────────

def cmd_wechat(args: str, _state, config) -> bool:
    """WeChat bridge via Tencent iLink Bot API — authenticate with QR code scan.

    Prerequisites:
      Enable "ClawBot" in WeChat: Me → Settings → Plugins → ClawBot

    Usage:
      /wechat login      — scan QR code with WeChat to authenticate & start
      /wechat            — start bridge using saved credentials (login if needed)
      /wechat stop       — stop the bridge
      /wechat status     — show current status
      /wechat logout     — clear saved credentials
    """
    global _wechat_thread, _wechat_stop
    from cheetahclaws.config import save_config

    sub = args.strip().split()[0].lower() if args.strip() else ""

    if sub in ("stop", "off"):
        if _wechat_thread and _wechat_thread.is_alive():
            _wechat_stop.set()
            _wechat_thread.join(timeout=5)
            _wechat_thread = None
            _wx_release_lock()
            ok("WeChat bridge stopped.")
        else:
            warn("WeChat bridge is not running.")
            _wx_release_lock()  # cover stale-lock cleanup if held without thread
        return True

    if sub == "status":
        running  = _wechat_thread and _wechat_thread.is_alive()
        token    = config.get("wechat_token", "")
        base_url = config.get("wechat_base_url", _ILINK_BASE_URL)
        acct     = config.get("wechat_account_id", "")
        if running:
            ok(f"WeChat bridge running  (account: {acct or 'unknown'}, iLink: {base_url})")
        elif token:
            info("Configured but not running. Use /wechat to start.")
        else:
            info("Not authenticated. Use /wechat login to scan the QR code.")
        return True

    if sub == "logout":
        if _wechat_thread and _wechat_thread.is_alive():
            _wechat_stop.set()
            _wechat_thread.join(timeout=5)
            _wechat_thread = None
        _wx_release_lock()
        config.pop("wechat_token", None)
        config.pop("wechat_base_url", None)
        config.pop("wechat_account_id", None)
        save_config(config)
        ok("WeChat credentials cleared.")
        return True

    if sub == "login":
        if _wechat_thread and _wechat_thread.is_alive():
            warn("Bridge is already running. Use /wechat stop first.")
            return True
        if not _wx_qr_login(config):
            return True
        _wx_start_bridge(config)
        return True

    if _wechat_thread and _wechat_thread.is_alive():
        warn("WeChat bridge is already running. Use /wechat stop first.")
        return True

    token = config.get("wechat_token", "")
    if not token:
        info("No saved credentials — starting QR login flow.")
        if not _wx_qr_login(config):
            return True
        _wx_start_bridge(config)
        return True

    base_url = config.get("wechat_base_url", _ILINK_BASE_URL)
    probe = _wx_post(base_url, _WX_EP_GET_UPDATES, token, {"get_updates_buf": ""}, timeout=8)
    if probe is not None and probe.get("ret") == -14:
        warn("Session expired. Re-authenticating via QR code...")
        config.pop("wechat_token", None)
        config.pop("wechat_base_url", None)
        save_config(config)
        if not _wx_qr_login(config):
            return True

    _wx_start_bridge(config)
    return True
