"""Cost math for listed Anthropic, OpenAI and Gemini models comes from llm-prices.

Before: every model in PROVIDERS that COSTS did not list (gpt-5, gpt-4.1, o3,
o4-mini, claude-opus-4-5, ...) cost $0.00, so cost budgets never moved, and
the typed Opus 4.6 row billed the retired Opus 4.0 rate.
"""
import pytest

from cheetahclaws import providers, quota
from cheetahclaws.providers import COSTS, calc_cost, model_rates

M = 1_000_000


@pytest.mark.parametrize("model", [
    "gpt-5", "gpt-5-mini", "gpt-4.1", "o3", "o4-mini",
    "claude-opus-4-5", "claude-sonnet-4-5",
])
def test_models_offered_in_providers_are_no_longer_free(model):
    assert model not in COSTS
    assert calc_cost(model, M, M) > 0


def test_list_prices():
    assert calc_cost("claude-opus-4-6", M, M) == pytest.approx(5 + 25)
    assert calc_cost("claude-haiku-4-5-20251001", M, M) == pytest.approx(1 + 5)
    assert calc_cost("gpt-5", M, M) == pytest.approx(1.25 + 10)
    assert calc_cost("gemini-2.5-pro", M, M) == pytest.approx(1.25 + 10)


def test_gateway_routes_price_like_the_upstream_model():
    direct = calc_cost("claude-sonnet-4-6", M, M)
    assert calc_cost("openrouter/anthropic/claude-sonnet-4-6", M, M) == pytest.approx(direct)


def test_published_cache_rates():
    # Sonnet 4.6: cache read $0.30, 5-minute cache write $3.75 per 1M.
    assert calc_cost("claude-sonnet-4-6", 0, 0, M, 0) == pytest.approx(0.30)
    assert calc_cost("claude-sonnet-4-6", 0, 0, 0, M) == pytest.approx(3.75)


def test_other_providers_keep_their_costs_rows():
    assert model_rates("deepseek-v4-flash") == COSTS["deepseek-v4-flash"]
    assert model_rates("nim/meta/llama-3.3-70b-instruct") == (0.0, 0.0)
    assert model_rates("qwen-max") == COSTS["qwen-max"]
    assert model_rates("not-a-model") == (0.0, 0.0)


def test_cost_budget_room_uses_list_output_price():
    with quota._lock:
        quota._sess_cost["lp"] = 0.0
    # gpt-5 output is $10 per 1M: $0.10 leaves 10k output tokens. It used to
    # return None (no cost cap applied) because gpt-5 had no COSTS row.
    room = quota.output_room("lp", {"model": "gpt-5", "session_cost_budget": 0.10})
    assert room == 10_000


def test_without_the_package_costs_rows_still_apply(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_llm_prices(name, *args, **kwargs):
        if name == "llm_prices":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_llm_prices)
    assert providers._list_price("gpt-5") is None
    assert model_rates("gpt-4o") == COSTS["gpt-4o"]
