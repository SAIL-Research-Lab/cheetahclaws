"""Tests for the Requesty provider entry + multi-level model routing.

Requesty serves 700+ models behind one OpenAI-compatible endpoint. Like
OpenRouter, the first segment of `requesty/<model>` is the provider and the
rest is passed through verbatim: either a catalog `<vendor>/<model>` path
(`requesty/openai/gpt-4o-mini`) or a managed policy ID with no vendor prefix
(`requesty/claude-sonnet-4-6`, `requesty/gpt-5-mini@eu`).
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


def test_requesty_provider_entry_present():
    assert "requesty" in PROVIDERS
    e = PROVIDERS["requesty"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://router.requesty.ai/v1"
    assert e["api_key_env"] == "REQUESTY_API_KEY"
    assert len(e["models"]) >= 5, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("requesty/openai/gpt-4o-mini",          "openai/gpt-4o-mini"),
    ("requesty/anthropic/claude-sonnet-4-6", "anthropic/claude-sonnet-4-6"),
    ("requesty/claude-sonnet-4-6",           "claude-sonnet-4-6"),
    ("requesty/gpt-5-mini@eu",               "gpt-5-mini@eu"),
])
def test_requesty_routing_strips_only_first_segment(model_id, expected_bare):
    """`requesty/<model>` must route to requesty and keep the rest verbatim,
    including managed policy IDs and their `@eu` suffix."""
    assert detect_provider(model_id) == "requesty"
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
    ("requesty/openai/gpt-4o-mini", "openai/gpt-4o-mini"),
    ("requesty/gpt-5-mini@eu",      "gpt-5-mini@eu"),
])
def test_stream_dispatches_to_requesty_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve requesty/... to the Requesty base_url and pass
    the model ID through unchanged, using the requesty_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"requesty_api_key": "rqsty-test-123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "rqsty-test-123"
    assert captured["base_url"] == "https://router.requesty.ai/v1"
    assert captured["model"] == expected_model
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_requesty_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("REQUESTY_API_KEY", "rqsty-env-456")

    list(stream("requesty/openai/gpt-4o-mini", "sys", [], [], {}))

    assert captured["api_key"] == "rqsty-env-456"


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


def test_requesty_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """A requesty/deepseek-v4-flash route must not pick up the DeepSeek API
    fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "requesty/deepseek-v4-flash", "sys", [], [],
        {"requesty_api_key": "rqsty-x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://router.requesty.ai/v1"


def test_requesty_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A route whose vendor segment is "openai" must send `max_tokens`, not
    the OpenAI-only `max_completion_tokens`, capped by the requesty entry."""
    captured = _capture_request(monkeypatch)

    list(stream("requesty/openai/gpt-5", "sys", [], [],
                {"requesty_api_key": "rqsty-x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["requesty"]["max_completion_tokens"]


# ── Per-model registry lookups (cost, context window) ────────────────────


@pytest.mark.parametrize("model_id", [
    "requesty/anthropic/claude-sonnet-4-6",
    "requesty/claude-sonnet-4-6",
    "requesty/claude-sonnet-4-6@eu",
])
def test_requesty_usage_is_priced(model_id):
    direct = calc_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
    assert direct > 0
    assert calc_cost(model_id, 1_000_000, 1_000_000) == direct


def test_requesty_context_window_falls_back_to_vendor_provider():
    """requesty/anthropic/... with no per-model entry reads Anthropic's own
    window instead of the gateway's generic default."""
    from cheetahclaws.compaction import get_context_limit
    model = "requesty/anthropic/claude-sonnet-4-6"
    assert (get_context_limit(model, {"model": model})
            == PROVIDERS["anthropic"]["context_limit"])


def test_requesty_eu_suffix_keeps_model_family_overlay():
    from cheetahclaws.prompts.select import _family_overlay_for_model
    assert _family_overlay_for_model("requesty/claude-sonnet-4-6@eu") == "claude.md"
