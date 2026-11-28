"""Tests for the LLMTR provider entry + multi-level model routing.

LLMTR serves open models behind one OpenAI-compatible endpoint. Like
OpenRouter, the first segment of `llmtr/<vendor>/<model>` is the provider
and the rest is passed through verbatim as the model ID
(`llmtr/deepseek/deepseek-v4-pro`).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.providers import (
    PROVIDERS, AssistantTurn, TextChunk,
    bare_model, detect_provider, stream,
)


# ── Provider registration ────────────────────────────────────────────────


def test_llmtr_provider_entry_present():
    assert "llmtr" in PROVIDERS
    e = PROVIDERS["llmtr"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://llmtr.com/v1"
    assert e["api_key_env"] == "LLMTR_API_KEY"
    assert len(e["models"]) >= 4, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("llmtr/deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
    ("llmtr/qwen/qwen3.8-flash",                 "qwen/qwen3.8-flash"),
    ("llmtr/openai/gpt-5.4-mini",             "openai/gpt-5.4-mini"),
])
def test_llmtr_routing_strips_only_first_segment(model_id, expected_bare):
    """`llmtr/<vendor>/<model>` must route to llmtr and keep the rest
    verbatim, including the vendor segment."""
    assert detect_provider(model_id) == "llmtr"
    assert bare_model(model_id) == expected_bare


def _fake_stream(captured):
    def fake_stream(api_key, base_url, model, system, messages, tool_schemas, config):
        captured["api_key"] = api_key
        captured["base_url"] = base_url
        captured["model"] = model
        captured["config"] = config
        yield TextChunk("hi")
        yield AssistantTurn("hi", [], in_tokens=1, out_tokens=1)
    return fake_stream


@pytest.mark.parametrize("model_id,expected_model", [
    ("llmtr/deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro"),
    ("llmtr/qwen/qwen3.8-flash",              "qwen/qwen3.8-flash"),
])
def test_stream_dispatches_to_llmtr_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve llmtr/... to the LLMTR base_url and pass
    the model ID through unchanged, using the llmtr_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"llmtr_api_key": "llmtr_test_123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "llmtr_test_123"
    assert captured["base_url"] == "https://llmtr.com/v1"
    assert captured["model"] == expected_model
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_llmtr_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("LLMTR_API_KEY", "llmtr_test_env_456")

    list(stream("llmtr/qwen/qwen3.8-flash", "sys", [], [], {}))

    assert captured["api_key"] == "llmtr_test_env_456"


# ── Provider identity must survive the prefix strip ──────────────────────


def _capture_request(monkeypatch):
    """Patch openai.OpenAI and return the dict that receives create()'s kwargs."""
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            return []

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            captured["client"] = kwargs
            self.chat = FakeChat

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    return captured


def test_llmtr_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """A llmtr/deepseek-ai/... route must not pick up the DeepSeek API
    fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "llmtr/deepseek/deepseek-v4-pro", "sys", [], [],
        {"llmtr_api_key": "llmtr_test_x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://llmtr.com/v1"


def test_llmtr_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A route whose vendor segment is "openai" must send `max_tokens`, not
    the OpenAI-only `max_completion_tokens`, capped by the llmtr entry."""
    captured = _capture_request(monkeypatch)

    list(stream("llmtr/openai/gpt-5.4-mini", "sys", [], [],
                {"llmtr_api_key": "llmtr_test_x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["llmtr"]["max_completion_tokens"]
