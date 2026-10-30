"""Shared bridge sender authorization (bridges/auth.py) and its call sites."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cheetahclaws.bridges import auth


# ── is_authorized ─────────────────────────────────────────────────────────

def test_allowlist_membership():
    cfg = {"qq_allowed_users": ["a", "b"]}
    assert auth.is_authorized("qq", "a", "g1", cfg)
    assert not auth.is_authorized("qq", "c", "g1", cfg)
    assert not auth.is_authorized("qq", "", "g1", cfg)


def test_comma_string_allowlist():
    assert auth.allowed_users("slack", {"slack_allowed_users": "U1, U2"}) == ["U1", "U2"]


def test_private_first_contact_auto_binds_and_persists(capsys):
    saved = []
    cfg = {}
    with patch.object(auth, "_persist", lambda c: saved.append(dict(c))):
        assert auth.is_authorized("slack", "U1", "D1", cfg, is_private=True)
    assert cfg["slack_allowed_users"] == ["U1"]
    assert saved and saved[0]["slack_allowed_users"] == ["U1"]
    assert "bound the first private-chat sender 'U1'" in capsys.readouterr().err
    # Second private sender is NOT bound.
    assert not auth.is_authorized("slack", "U2", "D2", cfg, is_private=True)


def test_group_never_auto_binds():
    cfg = {}
    assert not auth.is_authorized("qq", "m1", "group1", cfg, is_private=False)
    assert "qq_allowed_users" not in cfg


def test_allow_all_escape_hatch():
    assert auth.is_authorized("qq", "anyone", "g", {"qq_allow_all_senders": True})


def test_telegram_chat_pin_still_applies():
    cfg = {"telegram_chat_id": 42, "telegram_allowed_users": ["7"]}
    assert auth.is_authorized("telegram", 7, 42, cfg)
    assert not auth.is_authorized("telegram", 7, 43, cfg)
    assert not auth.is_authorized("telegram", 7, 43, dict(cfg, telegram_allow_all_senders=True))


def test_wechat_seeds_from_legacy_self_uid():
    cfg = {"wechat_self_uid": "owner"}
    assert auth.is_authorized("wechat", "owner", "owner", cfg, is_private=True)
    assert not auth.is_authorized("wechat", "stranger", "stranger", cfg, is_private=True)
    assert cfg["wechat_allowed_users"] == ["owner"]


def test_refusal_text_and_throttle():
    txt = auth.refusal_text("qq", "m9")
    assert "qq_allowed_users" in txt and "m9" in txt and "qq_allow_all_senders" in txt
    assert auth.should_reply_refusal("qq", "m9")
    assert not auth.should_reply_refusal("qq", "m9")


# ── Telegram ──────────────────────────────────────────────────────────────

def _tg_msg(chat_id, chat_type, from_id):
    return {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": from_id}}


def test_telegram_group_member_refused_owner_private_bound():
    from cheetahclaws.bridges import telegram as tg
    cfg = {"telegram_chat_id": 100}
    # Owner's private chat (chat id == user id) binds on first contact.
    assert tg._tg_message_authorized(_tg_msg(100, "private", 100), 100, cfg)
    assert cfg["telegram_allowed_users"] == ["100"]

    gcfg = {"telegram_chat_id": -5}
    assert not tg._tg_message_authorized(_tg_msg(-5, "group", 9), -5, gcfg)
    gcfg["telegram_allowed_users"] = ["9"]
    assert tg._tg_message_authorized(_tg_msg(-5, "group", 9), -5, gcfg)
    assert not tg._tg_message_authorized(_tg_msg(-6, "group", 9), -5, gcfg)


def test_telegram_callback_from_unlisted_group_member_rejected():
    from cheetahclaws.bridges import telegram as tg
    ctx = SimpleNamespace(tg_callback_prompt_id="p", tg_input_event=None,
                          tg_input_value=None)
    cb = {"id": "c1", "data": "cc:p:y", "from": {"id": 9},
          "message": {"chat": {"id": -5, "type": "group"}, "message_id": 1}}
    with patch.object(tg, "_tg_api") as api:
        tg._handle_callback_query("tok", -5, cb, ctx, config={"telegram_chat_id": -5})
    api.assert_called_once()
    assert api.call_args[0][1] == "answerCallbackQuery"
    assert ctx.tg_input_value is None


# ── WeChat ────────────────────────────────────────────────────────────────

def test_wechat_sender_check():
    from cheetahclaws.bridges import wechat as wx
    cfg = {}
    assert wx._wx_sender_authorized("filehelper", cfg)
    assert "wechat_allowed_users" not in cfg      # filehelper never binds
    assert not wx._wx_sender_authorized("123@chatroom", cfg)
    assert wx._wx_sender_authorized("owner", cfg)  # first private contact
    assert not wx._wx_sender_authorized("other", cfg)


# ── Slack / QQ poll loops refuse before dispatch ──────────────────────────

def test_slack_poll_loop_refuses_unlisted_channel_member(monkeypatch):
    from cheetahclaws.bridges import slack as sl
    sent = []
    ctx = SimpleNamespace(run_query=None, slack_send=None, slack_input_event=None,
                          handle_slash=lambda t: pytest.fail("slash reached"))
    monkeypatch.setattr(sl.runtime, "get_session_ctx", lambda sid: ctx)
    monkeypatch.setattr(sl, "_slack_send", lambda tok, ch, txt: sent.append(txt))
    calls = {"n": 0}

    def fake_api(token, method, params=None, **kw):
        calls["n"] += 1
        if calls["n"] > 1:
            sl._slack_stop.set()
            return {"ok": True, "messages": []}
        return {"ok": True, "messages": [
            {"ts": "9999999999.1", "user": "UX", "text": "!cat /etc/passwd"}]}

    monkeypatch.setattr(sl, "_slack_api", fake_api)
    monkeypatch.setattr(sl, "_SLACK_POLL_INTERVAL", 0)
    ran = []
    monkeypatch.setattr("cheetahclaws.bridges.terminal_runner.run_terminal",
                        lambda *a, **k: ran.append(a))
    sl._slack_stop.clear()
    try:
        sl._slack_poll_loop("tok", "C123", {"slack_allowed_users": ["UOWNER"]})
    finally:
        sl._slack_stop.clear()
    assert ran == []
    assert any("Not authorized" in s and "UX" in s for s in sent)
