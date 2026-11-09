"""Tests for the CloudGPU provider entry + routing.

CloudGPU serves DeepSeek, Kimi, GLM, MiniMax and Qwen models behind one
OpenAI-compatible endpoint. Its model IDs are single-segment
(`deepseek-v4.1-flash`, `kimi-k3`), so `cloudgpu/<model>` is a plain explicit
prefix: the provider is `cloudgpu` and the rest is sent as the model ID.
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


def test_cloudgpu_provider_entry_present():
    assert "cloudgpu" in PROVIDERS
    e = PROVIDERS["cloudgpu"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://cloudgpu.app/v1"
    assert e["api_key_env"] == "CLOUDGPU_API_KEY"
    assert e["models"], "model list should not be empty"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("cloudgpu/deepseek-v4.1-flash", "deepseek-v4.1-flash"),
    ("cloudgpu/kimi-k3",             "kimi-k3"),
    ("cloudgpu/qwen3-coder-480b",    "qwen3-coder-480b"),
])
def test_cloudgpu_routing(model_id, expected_bare):
    """`cloudgpu/<model>` must route to cloudgpu and strip only the prefix."""
    assert detect_provider(model_id) == "cloudgpu"
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
    ("cloudgpu/deepseek-v4.1-flash", "deepseek-v4.1-flash"),
    ("cloudgpu/glm-5.2",             "glm-5.2"),
])
def test_stream_dispatches_to_cloudgpu_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve cloudgpu/... to the CloudGPU base_url and pass
    the bare model ID, using the cloudgpu_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"cloudgpu_api_key": "cg_test_123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "cg_test_123"
    assert captured["base_url"] == "https://cloudgpu.app/v1"
    assert captured["model"] == expected_model
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_cloudgpu_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("CLOUDGPU_API_KEY", "cg_env_456")

    list(stream("cloudgpu/kimi-k3", "sys", [], [], {}))

    assert captured["api_key"] == "cg_env_456"


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


def test_cloudgpu_deepseek_model_omits_deepseek_only_fields(monkeypatch):
    """cloudgpu/deepseek-... must not pick up the DeepSeek API fields
    (extra_body.thinking, reasoning_effort) even though the bare model ID
    starts with "deepseek-"."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "cloudgpu/deepseek-v4.1-flash", "sys", [], [],
        {"cloudgpu_api_key": "cg_x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://cloudgpu.app/v1"


def test_cloudgpu_uses_max_tokens_and_its_own_cap(monkeypatch):
    """CloudGPU must send `max_tokens`, not the OpenAI-only
    `max_completion_tokens`, capped by the cloudgpu entry."""
    captured = _capture_request(monkeypatch)

    list(stream("cloudgpu/qwen3-coder-480b", "sys", [], [],
                {"cloudgpu_api_key": "cg_x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["cloudgpu"]["max_completion_tokens"]
