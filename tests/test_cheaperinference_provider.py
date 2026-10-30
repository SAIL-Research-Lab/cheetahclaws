"""Tests for the Cheaper Inference provider entry + model routing.

Cheaper Inference is an OpenAI-compatible LLM gateway. One key gives access to
models from several labs. Like OpenRouter, the first segment of
`cheaperinference/<model>` is the provider and the rest is passed through
verbatim; the model IDs are the bare ids from the gateway's model list
(`cheaperinference/gpt-5.4-mini`, `cheaperinference/claude-sonnet-5`).
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


def test_cheaperinference_provider_entry_present():
    assert "cheaperinference" in PROVIDERS
    e = PROVIDERS["cheaperinference"]
    assert e["type"] == "openai"
    assert e["base_url"] == "https://api.cheaperinference.com/v1"
    assert e["api_key_env"] == "CHEAPERINFERENCE_API_KEY"
    assert len(e["models"]) >= 5, "expect a curated model list for the /model picker"


@pytest.mark.parametrize("model_id,expected_bare", [
    ("cheaperinference/gpt-5.4-mini",      "gpt-5.4-mini"),
    ("cheaperinference/claude-sonnet-5",   "claude-sonnet-5"),
    ("cheaperinference/deepseek-v4-flash", "deepseek-v4-flash"),
])
def test_cheaperinference_routing_strips_only_first_segment(model_id, expected_bare):
    """`cheaperinference/<model>` must route to cheaperinference and keep the
    rest verbatim as the model ID."""
    assert detect_provider(model_id) == "cheaperinference"
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
    ("cheaperinference/gpt-5.4-mini",    "gpt-5.4-mini"),
    ("cheaperinference/claude-sonnet-5", "claude-sonnet-5"),
])
def test_stream_dispatches_to_cheaperinference_endpoint(monkeypatch, model_id, expected_model):
    """`stream()` must resolve cheaperinference/... to the Cheaper Inference
    base_url and pass the model ID through unchanged, using the
    cheaperinference_api_key."""
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))

    cfg = {"cheaperinference_api_key": "ci_live_test_123"}
    events = list(stream(model_id, "sys", [], [], cfg))

    assert captured["api_key"] == "ci_live_test_123"
    assert captured["base_url"] == "https://api.cheaperinference.com/v1"
    assert captured["model"] == expected_model
    assert "_openrouter_provider" not in captured["config"]
    assert any(isinstance(ev, AssistantTurn) for ev in events)


def test_cheaperinference_api_key_from_env(monkeypatch):
    captured = {}
    monkeypatch.setattr("cheetahclaws.providers.stream_openai_compat",
                        _fake_stream(captured))
    monkeypatch.setenv("CHEAPERINFERENCE_API_KEY", "ci_live_env_456")

    list(stream("cheaperinference/gpt-5.4-mini", "sys", [], [], {}))

    assert captured["api_key"] == "ci_live_env_456"


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


def test_cheaperinference_deepseek_route_omits_deepseek_only_fields(monkeypatch):
    """A cheaperinference/deepseek-v4-flash route must not pick up the DeepSeek
    API fields (extra_body.thinking, reasoning_effort)."""
    captured = _capture_request(monkeypatch)

    list(stream(
        "cheaperinference/deepseek-v4-flash", "sys", [], [],
        {"cheaperinference_api_key": "ci_live_x", "thinking": False,
         "reasoning_effort": "high"},
    ))

    kwargs = captured["kwargs"]
    assert "thinking" not in (kwargs.get("extra_body") or {})
    assert "reasoning_effort" not in kwargs
    assert captured["client"]["base_url"] == "https://api.cheaperinference.com/v1"


def test_cheaperinference_uses_max_tokens_and_its_own_cap(monkeypatch):
    """A cheaperinference route must send `max_tokens`, not the OpenAI-only
    `max_completion_tokens`, capped by the cheaperinference entry."""
    captured = _capture_request(monkeypatch)

    list(stream("cheaperinference/gpt-5.4", "sys", [], [],
                {"cheaperinference_api_key": "ci_live_x", "max_tokens": 64000}))

    kwargs = captured["kwargs"]
    assert "max_completion_tokens" not in kwargs
    assert kwargs["max_tokens"] <= PROVIDERS["cheaperinference"]["max_completion_tokens"]


# ── Per-model registry lookups (cost) ────────────────────────────────────


def test_cheaperinference_usage_is_priced():
    """A route whose bare model ID has a cost table entry must price the same
    as a direct call, so gateway usage is not billed as $0.00."""
    direct = calc_cost("deepseek-v4-flash", 1_000_000, 1_000_000)
    assert direct > 0
    assert calc_cost("cheaperinference/deepseek-v4-flash", 1_000_000, 1_000_000) == direct
