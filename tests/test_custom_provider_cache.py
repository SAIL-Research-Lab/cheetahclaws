"""Tests for _fetch_custom_model_limit caching (#183).

The cache is keyed by the ids /v1/models returns, but callers pass the model
either bare ("tools-pool") or prefixed ("custom/tools-pool"), and a model the
endpoint doesn't describe used to be re-fetched before every call.
"""
from __future__ import annotations

import json

import pytest

import cheetahclaws.providers as _providers
from cheetahclaws.providers import _fetch_custom_model_limit

URL = "http://endpoint/v1"


@pytest.fixture()
def endpoint(monkeypatch):
    """Stub /v1/models. Returns (set_models, calls); isolates module state."""
    monkeypatch.setattr(_providers, "_custom_ctx_cache", {})
    monkeypatch.setattr(_providers, "_custom_ctx_skip_until", {})
    # _fetch_custom_model_limit backfills PROVIDERS["custom"]["context_limit"]
    monkeypatch.setitem(
        _providers.PROVIDERS, "custom", dict(_providers.PROVIDERS.get("custom", {}))
    )
    state = {"models": [], "error": None}
    calls: list[str] = []

    class _Resp:
        def read(self):
            return json.dumps({"data": state["models"]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if state["error"]:
            raise state["error"]
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return state, calls


@pytest.mark.parametrize("served_id, lookup", [
    ("tools-pool", "tools-pool"),
    ("tools-pool", "custom/tools-pool"),
    # vLLM serves HuggingFace ids; the vendor segment is part of the id and
    # must survive when the caller has already stripped the provider prefix.
    ("Qwen/Qwen3-Coder", "Qwen/Qwen3-Coder"),
    ("Qwen/Qwen3-Coder", "custom/Qwen/Qwen3-Coder"),
])
def test_limit_found_and_cached(endpoint, served_id, lookup):
    state, calls = endpoint
    state["models"] = [{"id": served_id, "max_model_len": 32768}]

    results = [_fetch_custom_model_limit(URL, lookup, "k") for _ in range(3)]

    assert results == [32768] * 3
    assert len(calls) == 1


def test_bare_and_prefixed_lookups_share_one_request(endpoint):
    state, calls = endpoint
    state["models"] = [{"id": "tools-pool", "max_model_len": 65536}]

    assert _fetch_custom_model_limit(URL, "tools-pool", "k") == 65536
    assert _fetch_custom_model_limit(URL, "custom/tools-pool", "k") == 65536
    assert len(calls) == 1


def test_exact_id_wins_over_prefix_stripping(endpoint):
    """An endpoint may really serve an id that starts with "custom/"."""
    state, _ = endpoint
    state["models"] = [
        {"id": "custom/m", "max_model_len": 8192},
        {"id": "m", "max_model_len": 4096},
    ]

    assert _fetch_custom_model_limit(URL, "custom/m", "k") == 8192


@pytest.mark.parametrize("models", [
    [],                                   # model not listed at all
    [{"id": "tools-pool"}],               # listed, but no limit field
    [{"id": "tools-pool", "max_model_len": None}],
])
def test_miss_is_remembered(endpoint, models):
    state, calls = endpoint
    state["models"] = models

    for lookup in ("tools-pool", "custom/tools-pool") * 2:
        assert _fetch_custom_model_limit(URL, lookup, "k") is None

    # One request per distinct spelling, then no more.
    assert len(calls) == 2


def test_miss_is_per_endpoint(endpoint):
    state, calls = endpoint
    assert _fetch_custom_model_limit(URL, "m", "k") is None

    state["models"] = [{"id": "m", "max_model_len": 4096}]
    assert _fetch_custom_model_limit("http://other/v1", "m", "k") == 4096
    assert len(calls) == 2


def test_network_failure_is_retried_after_a_pause(endpoint, monkeypatch):
    """A failure must not be permanent, nor re-attempted before every call."""
    state, calls = endpoint
    now = [1000.0]
    monkeypatch.setattr(_providers.time, "monotonic", lambda: now[0])
    state["error"] = OSError("connection refused")
    for _ in range(3):
        assert _fetch_custom_model_limit(URL, "custom/m", "k") is None
    assert len(calls) == 1

    state["error"] = None
    state["models"] = [{"id": "m", "max_model_len": 4096}]
    now[0] += _providers._CUSTOM_CTX_FAILURE_RETRY_S - 1
    assert _fetch_custom_model_limit(URL, "custom/m", "k") is None
    now[0] += 2
    assert _fetch_custom_model_limit(URL, "custom/m", "k") == 4096
    assert len(calls) == 2


def test_backfills_smallest_limit_as_provider_default(endpoint):
    state, _ = endpoint
    state["models"] = [
        {"id": "big", "max_model_len": 131072},
        {"id": "small", "context_window": 32768},
        {"id": "undescribed"},
    ]

    _fetch_custom_model_limit(URL, "undescribed", "k")

    assert _providers.PROVIDERS["custom"]["context_limit"] == 32768
