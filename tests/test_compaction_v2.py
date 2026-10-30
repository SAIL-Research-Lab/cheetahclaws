"""Structured summariser input, failure backoff, usage-aware estimates."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cheetahclaws import compaction as C


def _history(n_pairs=12, big=3000):
    msgs = []
    for i in range(n_pairs):
        msgs.append({"role": "user", "content": f"request {i}: please fix bug {i}"})
        msgs.append({"role": "assistant", "content": f"looking at {i}",
                     "tool_calls": [{"id": f"e{i}", "name": "Edit", "input": {
                         "file_path": f"/repo/src/mod{i}.py",
                         "old_string": "a" * 50, "new_string": "b" * 50}}]})
        content = ("Error: old_string not found" if i == 3 else "ok " + "x" * big)
        msgs.append({"role": "tool", "tool_call_id": f"e{i}", "content": content})
    return msgs


# ── structured transcript ─────────────────────────────────────────────────

def test_transcript_has_index_and_key_args():
    t = C.build_structured_transcript(_history(), budget_chars=40_000)
    assert "## User requests" in t and "request 0: please fix bug 0" in t
    assert "## Files modified" in t and "/repo/src/mod7.py (Edit)" in t
    assert "## Errors seen" in t and "old_string not found" in t
    assert "Edit(file_path='/repo/src/mod2.py'" in t
    assert "[tool result: Edit]" in t


def test_transcript_respects_budget_and_scales_per_message():
    msgs = _history(big=20_000)
    small = C.build_structured_transcript(msgs, budget_chars=10_000)
    large = C.build_structured_transcript(msgs, budget_chars=200_000)
    assert len(small) < 12_000
    assert len(large) > 4 * len(small)
    # Legacy summariser cut every message at 500 chars; the large budget
    # keeps far more of each message.
    assert "x" * 2000 in large


def test_summariser_receives_structured_prompt(monkeypatch):
    seen = {}

    def fake_aux(system, messages, config):
        seen["prompt"] = messages[0]["content"]
        return "SUMMARY"

    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary", fake_aux)
    out = C.compact_messages(_history(), {"model": "claude-sonnet-4-5"})
    assert out[0]["content"].startswith("[Previous conversation summary]\nSUMMARY")
    assert "Files touched" in seen["prompt"]
    assert "/repo/src/mod0.py" in seen["prompt"]


# ── failure → deterministic fallback + backoff ────────────────────────────

def _failing_aux(counter):
    def fake(system, messages, config):
        counter.append(1)
        raise RuntimeError("aux down")
    return fake


def test_compact_messages_falls_back_deterministically(monkeypatch):
    calls = []
    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary", _failing_aux(calls))
    msgs = _history()
    out = C.compact_messages(msgs, {"model": "claude-sonnet-4-5"})
    assert len(out) < len(msgs)
    assert "deterministic digest" in out[0]["content"]
    assert "/repo/src/mod0.py" in out[0]["content"]
    # Legacy escape hatch returns the input untouched.
    same = C.compact_messages(msgs, {"model": "claude-sonnet-4-5",
                                     "compaction_deterministic_fallback": False})
    assert same is msgs


def test_maybe_compact_backs_off_after_failure(monkeypatch):
    calls = []
    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary", _failing_aux(calls))
    cfg = {"model": "x", "context_window": 8_000, "compaction_count_overhead": False,
           "compaction_failure_backoff_turns": 2}
    state = SimpleNamespace(messages=_history(big=4000), turn_count=1)
    assert C.maybe_compact(state, cfg) is True
    assert len(calls) == 1
    assert "deterministic digest" in state.messages[0]["content"]
    for turn in (2, 3):
        state.turn_count = turn
        state.messages = _history(big=4000)
        assert C.maybe_compact(state, cfg) is True
    assert len(calls) == 1      # LLM not retried during backoff
    state.turn_count = 4
    state.messages = _history(big=4000)
    C.maybe_compact(state, cfg)
    assert len(calls) == 2      # retried after backoff


# ── estimates: overhead + recorded usage ──────────────────────────────────

def test_estimate_tokens_backward_compatible_and_overhead():
    msgs = [{"role": "user", "content": "x" * 2800}]
    base = C.estimate_tokens(msgs)
    assert base == int((1000 + 4) * 1.1)
    with_sys = C.estimate_tokens(msgs, system_prompt="s" * 2800,
                                 tool_schemas=[{"name": "t", "description": "d" * 2800}])
    assert with_sys > base + 2000


def test_record_usage_preferred_while_fresh():
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}]
    state = SimpleNamespace(messages=msgs)
    C.record_usage(state, input_tokens=50_000, output_tokens=100,
                   cache_read_tokens=1_000)
    assert C.estimate_context_tokens(state) == 51_100
    state.messages.append({"role": "tool", "tool_call_id": "a", "content": "y" * 2800})
    est = C.estimate_context_tokens(state)
    assert 51_100 + 1000 < est < 51_100 + 1200
    # A copied list still matches (same message objects).
    state.messages = list(state.messages)
    assert C.estimate_context_tokens(state) == est
    # Compaction replaces the prefix → falls back to the heuristic.
    state.messages = [{"role": "user", "content": "summary"}] + state.messages[1:]
    assert C.estimate_context_tokens(state) < 2_000


def test_maybe_compact_uses_recorded_usage(monkeypatch):
    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary",
                        lambda **k: "S")
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"}]
    state = SimpleNamespace(messages=msgs, turn_count=1)
    cfg = {"model": "x", "context_window": 100_000}
    # Heuristic says tiny; provider says 90% full → compaction considered.
    assert C.maybe_compact(state, cfg) is False
    C.record_usage(state, input_tokens=90_000)
    assert C.maybe_compact(state, cfg) is True


def test_snip_adjusts_recorded_usage_instead_of_dropping_it(monkeypatch):
    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary",
                        lambda **k: "S")
    msgs = _history(n_pairs=6, big=3000)
    state = SimpleNamespace(messages=msgs, turn_count=1)
    C.record_usage(state, input_tokens=95_000)
    cfg = {"model": "x", "context_window": 100_000}
    assert C.maybe_compact(state, cfg) is True
    # Snipping a few KB cannot bring a 95K prompt under 70K → LLM compaction ran.
    assert state.messages[0]["content"].startswith("[Previous conversation summary]")


def test_huge_overhead_does_not_trigger_every_turn():
    state = SimpleNamespace(messages=[{"role": "user", "content": "hi"}], turn_count=1)
    cfg = {"model": "x", "context_window": 10_000,
           "_system_prompt": "s" * 30_000}   # overhead alone > 70%
    assert C.maybe_compact(state, cfg) is False


def test_maybe_compact_counts_system_prompt(monkeypatch):
    monkeypatch.setattr("cheetahclaws.auxiliary.stream_auxiliary",
                        lambda **k: "S")
    cfg = {"model": "x", "context_window": 100_000, "tool_profile": "standard"}
    # messages ≈ 50K tokens: under 70% alone, over once a 25K-token system
    # prompt is counted.
    msgs = _history(n_pairs=10, big=13_000)
    state = SimpleNamespace(messages=list(msgs), turn_count=1)
    assert C.maybe_compact(state, {**cfg, "compaction_count_overhead": False}) is False
    state = SimpleNamespace(messages=list(msgs), turn_count=1)
    assert C.maybe_compact(state, {**cfg, "_system_prompt": "s" * 70_000}) is True
