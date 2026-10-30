"""Context-scaled tool output cap and head+tail truncation."""
from __future__ import annotations

import pytest

from cheetahclaws.tool_registry import (
    ToolDef,
    _effective_output_cap,
    _truncate_result,
    clear_registry,
    clear_tool_cache,
    execute_tool,
    get_all_tools,
    register_tool,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    original = get_all_tools()
    clear_registry()
    clear_tool_cache()
    yield
    clear_registry()
    clear_tool_cache()
    for tool in original:
        register_tool(tool)


def _cfg(ctx, **extra):
    return {"model": "custom/m", "context_window": ctx, **extra}


@pytest.mark.parametrize("ctx,expected", [
    (8_000, 2_000),       # tiny local model: floor
    (32_000, 7_000),      # legacy conservative cap kept for <=32K
    (32_768, 7_000),
    (200_000, 40_000),    # 10% of window at 2 chars/token
    (1_000_000, 100_000), # absolute ceiling
])
def test_cap_scales_with_context_window(ctx, expected):
    assert _effective_output_cap(_cfg(ctx), None) == expected


def test_cap_is_monotonic_in_window_size():
    caps = [_effective_output_cap(_cfg(c), None)
            for c in (4_000, 16_000, 32_768, 40_000, 64_000, 128_000,
                      200_000, 400_000, 1_000_000, 2_000_000)]
    assert caps == sorted(caps)


def test_cap_bounded_by_caller_max_output():
    assert _effective_output_cap(_cfg(200_000), 32_000) == 32_000
    assert _effective_output_cap(_cfg(8_000), 32_000) == 2_000


def test_cap_config_escape_hatches():
    # fraction=0 → legacy fixed cap everywhere
    assert _effective_output_cap(
        _cfg(1_000_000, tool_output_context_fraction=0), None) == 7_000
    assert _effective_output_cap(
        _cfg(200_000, tool_output_max_chars=12_000), None) == 12_000
    assert _effective_output_cap(
        _cfg(200_000, tool_output_context_fraction=0.2), None) == 80_000
    # Garbage config values fall back to defaults instead of raising.
    assert _effective_output_cap(
        _cfg(200_000, tool_output_context_fraction="x"), None) == 40_000


def test_tooldef_max_output_bounds_result():
    register_tool(ToolDef(
        name="t", schema={"name": "t", "input_schema": {}},
        func=lambda _p, _c: "y" * 50_000, max_output=5_000,
    ))
    out = execute_tool("t", {}, _cfg(1_000_000))
    assert len(out) <= 5_000
    assert "truncated" in out


def test_large_model_gets_more_than_legacy_7k():
    register_tool(ToolDef(
        name="big", schema={"name": "big", "input_schema": {}},
        func=lambda _p, _c: "z" * 30_000,
    ))
    assert execute_tool("big", {}, _cfg(200_000)) == "z" * 30_000
    small = execute_tool("big", {}, _cfg(32_000))
    assert len(small) <= 7_000


def test_truncation_keeps_head_and_tail_lines():
    lines = [f"line {i}" for i in range(5_000)]
    lines[-1] = "FAILED tests/test_x.py::test_y - AssertionError"
    text = "\n".join(lines)
    out = _truncate_result(text, {"command": "pytest"}, 4_000)
    assert len(out) <= 4_000
    assert out.startswith("line 0\n")
    assert out.endswith("FAILED tests/test_x.py::test_y - AssertionError")
    assert "omitted from the middle" in out
    assert "lines" in out
    assert "grep" in out  # how to see more for shell output
    # Head and tail cut on line boundaries.
    head, _, rest = out.partition("\n[...")
    assert head.splitlines()[-1].startswith("line ")
    tail = rest.split("]\n", 1)[1]
    assert tail.splitlines()[0].startswith("line ")


def test_truncation_omitted_count_is_exact():
    text = "a" * 10_000
    out = _truncate_result(text, {}, 2_000)
    marker_start = out.index("\n[...")
    marker_end = out.index("]\n", marker_start) + 2
    kept = len(out) - (marker_end - marker_start)
    assert f"{10_000 - kept:,} chars" in out


def test_truncation_read_hint_for_file_path():
    out = _truncate_result("q" * 10_000, {"file_path": "/a/b.py"}, 2_000,
                           {"tool_profile": "standard"})
    assert "offset and limit" in out and "/a/b.py" in out
