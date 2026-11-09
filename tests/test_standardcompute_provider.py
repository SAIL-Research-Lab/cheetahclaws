"""Tests for the Standard Compute provider entry + multi-level model routing.

Standard Compute serves open and frontier models behind one OpenAI-compatible
endpoint. Like OpenRouter, the first segment of `standardcompute/<vendor>/<model>`
is the provider and the rest is passed through verbatim as the model ID
(`standardcompute/deepseek/deepseek-v4.1-flash`). The routed model has no vendor
segment (`standardcompute/StandardCompute`).
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


def test_standardcompute_provider_entry_present():
    assert "standardcompute" in PROVIDERS
    e = PROVIDERS["standardcompute"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://api.stdcmpt.com/v1"
    assert e["api_key_env"] == "STANDARDCOMPUTE_API_KEY"
    assert len(e["models"]) >= 5, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("standardcompute/deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash"),
    ("standardcompute/z-ai/glm-5.3",                 "z-ai/glm-5.3"),
    ("standardcompute/openai/gpt-5.6-sol",           "openai/gpt-5.6-sol"),
    ("standardcompute/StandardCompute",              "StandardCompute"),
])
def test_standardcompute_routing_strips_only_first_segment(model_id, expected_bare):
    """`standardcompute/<vendor>/<model>` must route to standardcompute and keep the rest
    verbatim, including the vendor segment."""
    assert detect_provider(model_id) == "standardcompute"
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
    ("standardcompute/deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash"),
    ("standardcompute/qwen/qwen3.8-flash",              "qwen/qwen3.8-flash"),
])
def test_stream_dispatches_to_standardcompute_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve standardcompute/... to the Standard Compute base_url and pass
    the model ID through unchanged, using the standardcompute_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"standardcompute_api_key": "sc_test_123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "sc_test_123"
    assert captured["base_url"] == "https://api.stdcmpt.com/v1"
    assert captured["model"] == expected_model
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_standardcompute_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("STANDARDCOMPUTE_API_KEY", "sc_env_456")

    list(stream("standardcompute/z-ai/glm-5.3", "sys", [], [], {}))

    assert captured["api_key"] == "sc_env_456"


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


def test_standardcompute_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """A standardcompute/deepseek/... route must not pick up the DeepSeek API
    fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "standardcompute/deepseek/deepseek-v4.1-flash", "sys", [], [],
        {"standardcompute_api_key": "sc_x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://api.stdcmpt.com/v1"


def test_standardcompute_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A route whose vendor segment is "openai" must send `max_tokens`, not
    the OpenAI-only `max_completion_tokens`, capped by the standardcompute entry."""
    captured = _capture_request(monkeypatch)

    list(stream("standardcompute/openai/gpt-5.6-sol", "sys", [], [],
                {"standardcompute_api_key": "sc_x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["standardcompute"]["max_completion_tokens"]
