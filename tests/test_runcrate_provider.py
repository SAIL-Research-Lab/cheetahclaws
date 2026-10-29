"""Tests for the Runcrate provider entry + multi-level model routing.

Runcrate serves open models behind one OpenAI-compatible endpoint. Like
OpenRouter, the first segment of `runcrate/<vendor>/<model>` is the provider
and the rest is passed through verbatim as the model ID
(`runcrate/deepseek-ai/DeepSeek-V4.1-Flash`).
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


def test_runcrate_provider_entry_present():
    assert "runcrate" in PROVIDERS
    e = PROVIDERS["runcrate"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://api.runcrate.ai/v1"
    assert e["api_key_env"] == "RUNCRATE_API_KEY"
    assert len(e["models"]) >= 5, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("runcrate/deepseek-ai/DeepSeek-V4.1-Flash", "deepseek-ai/DeepSeek-V4.1-Flash"),
    ("runcrate/zai-org/GLM-5.3",                 "zai-org/GLM-5.3"),
    ("runcrate/openai/gpt-oss-120b",             "openai/gpt-oss-120b"),
])
def test_runcrate_routing_strips_only_first_segment(model_id, expected_bare):
    """`runcrate/<vendor>/<model>` must route to runcrate and keep the rest
    verbatim, including the vendor segment."""
    assert detect_provider(model_id) == "runcrate"
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
    ("runcrate/deepseek-ai/DeepSeek-V4.1-Flash", "deepseek-ai/DeepSeek-V4.1-Flash"),
    ("runcrate/Qwen/Qwen3.8-Flash",              "Qwen/Qwen3.8-Flash"),
])
def test_stream_dispatches_to_runcrate_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve runcrate/... to the Runcrate base_url and pass
    the model ID through unchanged, using the runcrate_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"runcrate_api_key": "rc_live_test_123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "rc_live_test_123"
    assert captured["base_url"] == "https://api.runcrate.ai/v1"
    assert captured["model"] == expected_model
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_runcrate_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("RUNCRATE_API_KEY", "rc_live_env_456")

    list(stream("runcrate/zai-org/GLM-5.3", "sys", [], [], {}))

    assert captured["api_key"] == "rc_live_env_456"


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


def test_runcrate_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """A runcrate/deepseek-ai/... route must not pick up the DeepSeek API
    fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "runcrate/deepseek-ai/DeepSeek-V4.1-Flash", "sys", [], [],
        {"runcrate_api_key": "rc_live_x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://api.runcrate.ai/v1"


def test_runcrate_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A route whose vendor segment is "openai" must send `max_tokens`, not
    the OpenAI-only `max_completion_tokens`, capped by the runcrate entry."""
    captured = _capture_request(monkeypatch)

    list(stream("runcrate/openai/gpt-oss-120b", "sys", [], [],
                {"runcrate_api_key": "rc_live_x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["runcrate"]["max_completion_tokens"]
