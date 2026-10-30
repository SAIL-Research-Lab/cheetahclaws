"""Anthropic message conversion: thinking replay, images, tool_result is_error."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from cheetahclaws import providers
from cheetahclaws.providers import messages_to_anthropic

PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAAB"
JPEG_B64 = "/9j/4AAQSkZJRgABAQ"


# ── messages_to_anthropic ──────────────────────────────────────────────────

def _tool_turn(**extra):
    return {
        "role": "assistant", "content": "checking",
        "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a"}}],
        **extra,
    }


def test_thinking_blocks_replayed_first_from_message_field():
    msg = _tool_turn(thinking_blocks=[
        {"type": "thinking", "thinking": "hmm", "signature": "SIG"},
        {"type": "redacted_thinking", "data": "ENC"},
    ])
    out = messages_to_anthropic([{"role": "user", "content": "hi"}, msg])
    blocks = out[1]["content"]
    assert [b["type"] for b in blocks] == [
        "thinking", "redacted_thinking", "text", "tool_use"]
    assert blocks[0] == {"type": "thinking", "thinking": "hmm", "signature": "SIG"}
    assert blocks[1] == {"type": "redacted_thinking", "data": "ENC"}
    # tool_use block never leaks the private ride-along key
    assert set(blocks[3]) == {"type", "id", "name", "input"}


def test_thinking_blocks_replayed_from_tool_call_ride_along():
    msg = _tool_turn()
    msg["tool_calls"][0]["anthropic_thinking"] = [
        {"type": "thinking", "thinking": "x", "signature": "S"}]
    blocks = messages_to_anthropic([msg])[0]["content"]
    assert blocks[0]["type"] == "thinking"
    assert "anthropic_thinking" not in blocks[-1]


def test_thinking_omitted_when_disabled_or_unsigned():
    msg = _tool_turn(thinking_blocks=[
        {"type": "thinking", "thinking": "x", "signature": "S"}])
    blocks = messages_to_anthropic([msg], include_thinking=False)[0]["content"]
    assert [b["type"] for b in blocks] == ["text", "tool_use"]
    unsigned = _tool_turn(thinking_blocks=[{"type": "thinking", "thinking": "x"}])
    blocks = messages_to_anthropic([unsigned])[0]["content"]
    assert [b["type"] for b in blocks] == ["text", "tool_use"]


def test_user_images_become_image_blocks():
    out = messages_to_anthropic([{
        "role": "user", "content": "what is this?",
        "images": [PNG_B64, JPEG_B64, f"data:image/gif;base64,R0lGODlh"],
    }])
    blocks = out[0]["content"]
    assert [b["type"] for b in blocks] == ["image", "image", "image", "text"]
    assert blocks[0]["source"] == {
        "type": "base64", "media_type": "image/png", "data": PNG_B64}
    assert blocks[1]["source"]["media_type"] == "image/jpeg"
    assert blocks[2]["source"] == {
        "type": "base64", "media_type": "image/gif", "data": "R0lGODlh"}
    assert blocks[3] == {"type": "text", "text": "what is this?"}


def test_user_without_images_unchanged():
    out = messages_to_anthropic([{"role": "user", "content": "plain"}])
    assert out == [{"role": "user", "content": "plain"}]


def test_tool_result_is_error_explicit_and_heuristic():
    msgs = [
        _tool_turn(),
        {"role": "tool", "tool_call_id": "t1", "content": "ok output"},
    ]
    msgs[0]["tool_calls"] += [
        {"id": "t2", "name": "Bash", "input": {}},
        {"id": "t3", "name": "Bash", "input": {}},
        {"id": "t4", "name": "Bash", "input": {}},
    ]
    msgs += [
        {"role": "tool", "tool_call_id": "t2", "content": "Error: boom"},
        {"role": "tool", "tool_call_id": "t3", "content": "fine", "is_error": True},
        {"role": "tool", "tool_call_id": "t4", "content": "Error-looking but ok",
         "is_error": False},
    ]
    results = messages_to_anthropic(msgs)[1]["content"]
    assert "is_error" not in results[0]
    assert results[1]["is_error"] is True
    assert results[2]["is_error"] is True
    assert "is_error" not in results[3]


# ── stream_anthropic captures thinking blocks ──────────────────────────────

_CAPTURED: dict = {}


class _Usage:
    input_tokens = 5
    output_tokens = 3
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


def _final(blocks):
    return SimpleNamespace(content=blocks, usage=_Usage())


class _Stream:
    def __init__(self, kwargs, final):
        _CAPTURED.clear()
        _CAPTURED.update(kwargs)
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self._final


def _install(monkeypatch, final):
    class _Messages:
        def stream(self, **kwargs):
            return _Stream(kwargs, final)

    class _Client:
        def __init__(self, api_key="", base_url=""):
            self.messages = _Messages()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=_Client))
    providers._client_cache_clear()
    providers._cache_control_disabled.clear()


def _run(config, messages):
    return list(providers.stream_anthropic(
        "k", "claude-sonnet-4-5", "SYS", messages, [], config))


def test_stream_captures_thinking_and_round_trips(monkeypatch):
    final = _final([
        SimpleNamespace(type="thinking", thinking="plan", signature="SIG1"),
        SimpleNamespace(type="redacted_thinking", data="RED"),
        SimpleNamespace(type="text", text="ok"),
        SimpleNamespace(type="tool_use", id="tu1", name="Read", input={"file_path": "x"}),
    ])
    _install(monkeypatch, final)
    cfg = {"thinking": True, "prompt_cache": False}
    turn = _run(cfg, [{"role": "user", "content": "go"}])[-1]
    assert turn.thinking_blocks == [
        {"type": "thinking", "thinking": "plan", "signature": "SIG1"},
        {"type": "redacted_thinking", "data": "RED"},
    ]
    # Simulate the loop: it copies text + tool_calls only.
    history = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": turn.text, "tool_calls": turn.tool_calls},
        {"role": "tool", "tool_call_id": "tu1", "content": "data"},
    ]
    _run(cfg, history)
    sent_assistant = _CAPTURED["messages"][1]["content"]
    assert sent_assistant[0] == {
        "type": "thinking", "thinking": "plan", "signature": "SIG1"}
    assert sent_assistant[1] == {"type": "redacted_thinking", "data": "RED"}
    assert sent_assistant[-1]["type"] == "tool_use"
    assert "anthropic_thinking" not in sent_assistant[-1]


def test_stream_without_thinking_config_does_not_replay(monkeypatch):
    _install(monkeypatch, _final([]))
    msg = _tool_turn(thinking_blocks=[
        {"type": "thinking", "thinking": "x", "signature": "S"}])
    _run({"prompt_cache": False}, [{"role": "user", "content": "q"}, msg,
                                   {"role": "tool", "tool_call_id": "t1", "content": "r"}])
    assert [b["type"] for b in _CAPTURED["messages"][1]["content"]] == [
        "text", "tool_use"]


def test_text_only_turn_has_no_ride_along(monkeypatch):
    _install(monkeypatch, _final([
        SimpleNamespace(type="thinking", thinking="t", signature="S"),
        SimpleNamespace(type="text", text="done"),
    ]))
    turn = _run({"thinking": True, "prompt_cache": False},
                [{"role": "user", "content": "q"}])[-1]
    assert turn.tool_calls == []
    assert turn.thinking_blocks[0]["signature"] == "S"
