"""Tests for _fetch_custom_model_limit caching (#183).

Regression: the cache was keyed on the full model string ("custom/tools-pool")
while the /v1/models response stores bare ids ("tools-pool"), so the lookup
missed on every call and neither caller remembered a miss — GET /v1/models
fired before each chat completion (184 GETs for 47 completions in one long
session on 3.5.87).
"""
from __future__ import annotations

import json

import cheetahclaws.providers as _providers
from cheetahclaws.providers import _fetch_custom_model_limit


def _fake_models(data_models, calls):
    """urlopen stub returning a fixed /v1/models payload, counting requests."""

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        payload = {"data": [{"id": m, "max_model_len": l} for m, l in data_models]}

        class _Resp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return _Resp()

    return fake_urlopen


def test_fetch_custom_model_limit_caches_by_bare_model(monkeypatch):
    _providers._custom_ctx_cache.clear()
    calls: list[str] = []
    monkeypatch.setattr("urllib.request.urlopen", _fake_models(
        [("tools-pool", 131072)], calls,
    ))

    lim1 = _fetch_custom_model_limit("http://x", "custom/tools-pool", "k")
    lim2 = _fetch_custom_model_limit("http://x", "custom/tools-pool", "k")
    assert lim1 == lim2 == 131072
    assert len(calls) == 1, "second lookup must hit the cache, not /v1/models"


def test_fetch_custom_model_limit_bare_and_prefixed_interop(monkeypatch):
    """A bare-id lookup and a prefixed lookup of the same model share one request."""
    _providers._custom_ctx_cache.clear()
    calls: list[str] = []
    monkeypatch.setattr("urllib.request.urlopen", _fake_models(
        [("tools-pool", 65536)], calls,
    ))

    bare = _fetch_custom_model_limit("http://y", "tools-pool", "k")
    prefixed = _fetch_custom_model_limit("http://y", "custom/tools-pool", "k")
    assert bare == prefixed == 65536
    assert len(calls) == 1


def test_fetch_custom_model_limit_memoizes_miss(monkeypatch):
    """A model the endpoint does not list is asked about once, not per call."""
    _providers._custom_ctx_cache.clear()
    calls: list[str] = []
    monkeypatch.setattr("urllib.request.urlopen", _fake_models([], calls))

    for _ in range(3):
        assert _fetch_custom_model_limit("http://z", "custom/unknown", "k") is None
    assert len(calls) == 1, "a miss must be remembered so /v1/models is not re-fetched"


def test_fetch_custom_model_limit_network_failure_not_cached(monkeypatch):
    """Transient failures are not memoized — a later success must still work."""
    _providers._custom_ctx_cache.clear()

    def boom(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert _fetch_custom_model_limit("http://w", "custom/m", "k") is None

    calls: list[str] = []
    monkeypatch.setattr("urllib.request.urlopen", _fake_models(
        [("m", 4096)], calls,
    ))
    assert _fetch_custom_model_limit("http://w", "custom/m", "k") == 4096
    assert len(calls) == 1
