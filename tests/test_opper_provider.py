"""Tests for the Opper provider entry + multi-level model routing.

Opper serves 700+ models behind one OpenAI-compatible endpoint. Like
OpenRouter, the first segment of `opper/<model>` is the provider and the rest
is passed through verbatim: either a model name with no vendor prefix
(`opper/claude-sonnet-4-6`, routed across the providers that serve it) or a
`<provider>/<model>` path that pins one route
(`opper/anthropic/claude-sonnet-4-6`).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.providers import (
    PROVIDERS, AssistantTurn, TextChunk,
    bare_model, calc_cost, detect_provider, stream,
)


# ── Provider registration ────────────────────────────────────────────────


def test_opper_provider_entry_present():
    assert "opper" in PROVIDERS
    e = PROVIDERS["opper"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://api.opper.ai/v3/compat"
    assert e["api_key_env"] == "OPPER_API_KEY"
    assert len(e["models"]) >= 5, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("opper/claude-sonnet-4-6",           "claude-sonnet-4-6"),
    ("opper/gpt-5.4-mini",                "gpt-5.4-mini"),
    ("opper/anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
    ("opper/openai/gpt-4o-mini",          "openai/gpt-4o-mini"),
])
def test_opper_routing_strips_only_first_segment(model_id, expected_bare):
    """`opper/<model>` must route to opper and keep the rest verbatim,
    including a pinned `<provider>/<model>` route."""
    assert detect_provider(model_id) == "opper"
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
    ("opper/claude-sonnet-4-6",           "claude-sonnet-4-6"),
    ("opper/anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
])
def test_stream_dispatches_to_opper_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve opper/... to the Opper base_url and pass the
    model ID through unchanged, using the opper_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"opper_api_key": "op-test-123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "op-test-123"
    assert captured["base_url"] == "https://api.opper.ai/v3/compat"
    assert captured["model"] == expected_model
    assert captured["config"]["_provider_name"] == "opper"
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_opper_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("OPPER_API_KEY", "op-env-456")

    list(stream("opper/claude-sonnet-4-6", "sys", [], [], {}))

    assert captured["api_key"] == "op-env-456"


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


def test_opper_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """An opper/deepseek-v4-flash route must not pick up the DeepSeek API
    fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "opper/deepseek-v4-flash", "sys", [], [],
        {"opper_api_key": "op-x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert kwargs["model"] == "deepseek-v4-flash"
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://api.opper.ai/v3/compat"


def test_opper_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A route whose vendor segment is "openai" must send `max_tokens`, not
    the OpenAI-only `max_completion_tokens`, capped by the opper entry."""
    captured = _capture_request(monkeypatch)

    list(stream("opper/openai/gpt-5.4-mini", "sys", [], [],
                {"opper_api_key": "op-x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["opper"]["max_completion_tokens"]


# ── Per-model registry lookups (cost, context window) ────────────────────


@pytest.mark.parametrize("model_id", [
    "opper/claude-sonnet-4-6",
    "opper/anthropic/claude-sonnet-4-6",
])
def test_opper_usage_is_priced(model_id):
    direct = calc_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert direct > 0
    assert calc_cost(model_id, 1_000_000, 1_000_000) == direct


def test_opper_context_window_falls_back_to_vendor_provider():
    """opper/anthropic/... with no per-model entry reads Anthropic's own
    window instead of the gateway's generic default."""
    from cheetahclaws.compaction import get_context_limit
    model = "opper/anthropic/claude-sonnet-4-6"
    assert (get_context_limit(model, {"model": model})
            == PROVIDERS["anthropic"]["context_limit"])


def test_opper_model_name_keeps_model_family_overlay():
    from cheetahclaws.prompts.select import _family_overlay_for_model
    assert _family_overlay_for_model("opper/claude-sonnet-4-6") == "claude.md"
