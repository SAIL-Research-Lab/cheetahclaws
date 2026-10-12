from __future__ import annotations

import threading

import pytest

from cheetahclaws.tool_registry import (
    ToolDef,
    clear_tool_cache,
    clear_registry,
    execute_tool,
    get_active_tool_names,
    get_all_tools,
    get_tool,
    get_tool_schemas,
    register_tool,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate registry tests without leaving later integration tests empty."""
    original_tools = get_all_tools()
    clear_registry()
    clear_tool_cache()
    yield
    clear_registry()
    clear_tool_cache()
    for tool in original_tools:
        register_tool(tool)


def _make_echo_tool(name: str = "echo", read_only: bool = False) -> ToolDef:
    """Helper to build a simple echo tool."""
    schema = {
        "name": name,
        "description": f"Echo tool ({name})",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "text to echo"},
            },
            "required": ["text"],
        },
    }

    def func(params: dict, config: dict) -> str:
        return params["text"]

    return ToolDef(
        name=name,
        schema=schema,
        func=func,
        read_only=read_only,
        concurrent_safe=True,
    )


# ------------------------------------------------------------------
# register and get
# ------------------------------------------------------------------

def test_register_and_get():
    tool = _make_echo_tool()
    register_tool(tool)
    result = get_tool("echo")
    assert result is not None
    assert result.name == "echo"


def test_get_unknown_returns_none():
    assert get_tool("no_such_tool") is None


# ------------------------------------------------------------------
# get_all_tools
# ------------------------------------------------------------------

def test_get_all_tools_empty():
    assert get_all_tools() == []


def test_get_all_tools():
    register_tool(_make_echo_tool("a"))
    register_tool(_make_echo_tool("b"))
    names = [t.name for t in get_all_tools()]
    assert sorted(names) == ["a", "b"]


# ------------------------------------------------------------------
# get_tool_schemas
# ------------------------------------------------------------------

def test_get_tool_schemas():
    register_tool(_make_echo_tool("echo"))
    schemas = get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"


def test_tool_profiles_filter_schemas_and_names():
    register_tool(ToolDef(
        name="core",
        schema={"name": "core", "input_schema": {}},
        func=lambda _p, _c: "core",
        profiles=frozenset({"standard"}),
    ))
    register_tool(ToolDef(
        name="research_only",
        schema={"name": "research_only", "input_schema": {}},
        func=lambda _p, _c: "research",
        profiles=frozenset({"research"}),
    ))
    register_tool(ToolDef(
        name="full_only",
        schema={"name": "full_only", "input_schema": {}},
        func=lambda _p, _c: "full",
        profiles=frozenset({"full"}),
    ))

    assert [s["name"] for s in get_tool_schemas("standard")] == ["core"]
    assert [s["name"] for s in get_tool_schemas("research")] == [
        "core", "research_only",
    ]
    assert get_active_tool_names("orchestration") == frozenset({"core"})
    assert {s["name"] for s in get_tool_schemas("full")} == {
        "core", "research_only", "full_only",
    }


def test_tool_profiles_honor_disabled_tools():
    register_tool(ToolDef(
        name="core",
        schema={"name": "core", "input_schema": {}},
        func=lambda _p, _c: "core",
        profiles=frozenset({"standard"}),
    ))
    assert get_tool_schemas("standard", disabled_tools=["core"]) == []


# ------------------------------------------------------------------
# execute_tool
# ------------------------------------------------------------------

def test_execute_tool():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "hello"}, config={})
    assert result == "hello"


def test_execute_unknown_tool():
    result = execute_tool("missing", {}, config={})
    assert "unknown" in result.lower() or "not found" in result.lower()


# ------------------------------------------------------------------
# output truncation
# ------------------------------------------------------------------

def test_output_truncation():
    def big_func(params: dict, config: dict) -> str:
        return "x" * 100

    tool = ToolDef(
        name="big",
        schema={"name": "big", "description": "big", "input_schema": {"type": "object", "properties": {}}},
        func=big_func,
        read_only=True,
        concurrent_safe=True,
    )
    register_tool(tool)

    result = execute_tool("big", {}, config={}, max_output=40)
    # Tiny caps may only fit a marker; the hard cap always wins over keeping
    # a prefix/suffix.
    assert len(result) <= 40
    assert "truncated" in result


def test_output_truncation_never_exceeds_cap_with_a_long_file_path():
    register_tool(ToolDef(
        name="path_big",
        schema={"name": "path_big", "input_schema": {}},
        func=lambda _p, _c: "x" * 5_000,
        read_only=True,
    ))

    result = execute_tool(
        "path_big", {"file_path": "/" + "x" * 2_000},
        {"tool_profile": "research"}, max_output=1_000,
    )

    assert len(result) <= 1_000
    assert "truncated" in result


def test_no_truncation_when_within_limit():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "short"}, config={})
    assert result == "short"


def test_cache_stores_bounded_result_and_reapplies_smaller_cap():
    calls = 0

    def big_func(params: dict, config: dict) -> str:
        nonlocal calls
        calls += 1
        return "x" * 20_000

    register_tool(ToolDef(
        name="cached_big",
        schema={"name": "cached_big", "input_schema": {}},
        func=big_func,
        read_only=True,
    ))

    first = execute_tool(
        "cached_big", {}, {"max_tool_cache_output": 2_000}, max_output=10_000,
    )
    second = execute_tool(
        "cached_big", {}, {"max_tool_cache_output": 2_000}, max_output=1_500,
    )

    assert calls == 1
    assert "truncated" in first
    assert "truncated" in second
    assert len(second) < len(first)


def test_cache_key_includes_input_bound_settings():
    calls = 0

    def config_echo(_params: dict, config: dict) -> str:
        nonlocal calls
        calls += 1
        return str(config["tool_read_max_bytes"])

    register_tool(ToolDef(
        name="config_sensitive",
        schema={"name": "config_sensitive", "input_schema": {}},
        func=config_echo,
        read_only=True,
    ))

    assert execute_tool("config_sensitive", {}, {"tool_read_max_bytes": 10}) == "10"
    assert execute_tool("config_sensitive", {}, {"tool_read_max_bytes": 20}) == "20"
    assert calls == 2


def test_write_invalidation_cannot_recache_an_inflight_stale_read():
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_read(_params: dict, _config: dict) -> str:
        nonlocal calls
        calls += 1
        value = "old" if calls == 1 else "new"
        if calls == 1:
            started.set()
            assert release.wait(timeout=2)
        return value

    register_tool(ToolDef(
        name="slow_read",
        schema={"name": "slow_read", "input_schema": {}},
        func=slow_read,
        read_only=True,
    ))
    thread = threading.Thread(
        target=lambda: execute_tool("slow_read", {}, {"_session_id": "race"}),
    )
    thread.start()
    assert started.wait(timeout=2)
    clear_tool_cache()  # Equivalent to a Write/Edit/Bash invalidation.
    release.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    assert execute_tool("slow_read", {}, {"_session_id": "race"}) == "new"
    assert calls == 2


def test_post_write_invalidation_clears_a_read_cached_during_mutation():
    write_started = threading.Event()
    release_write = threading.Event()
    state = {"value": "old"}
    reads = 0

    def read_value(_params: dict, _config: dict) -> str:
        nonlocal reads
        reads += 1
        return state["value"]

    def slow_write(_params: dict, _config: dict) -> str:
        write_started.set()
        assert release_write.wait(timeout=2)
        state["value"] = "new"
        return "written"

    register_tool(ToolDef(
        name="cached_read", schema={"name": "cached_read", "input_schema": {}},
        func=read_value, read_only=True,
    ))
    register_tool(ToolDef(
        name="Write", schema={"name": "Write", "input_schema": {}},
        func=slow_write,
    ))
    thread = threading.Thread(target=lambda: execute_tool("Write", {}, {}))
    thread.start()
    assert write_started.wait(timeout=2)
    assert execute_tool("cached_read", {}, {"_session_id": "mid-write"}) == "old"
    release_write.set()
    thread.join(timeout=2)
    assert not thread.is_alive()

    assert execute_tool("cached_read", {}, {"_session_id": "mid-write"}) == "new"
    assert reads == 2


def test_cache_varies_by_active_tool_surface_for_profile_aware_hints():
    calls = 0

    def large_result(_params: dict, _config: dict) -> str:
        nonlocal calls
        calls += 1
        return "x" * 20_000

    register_tool(ToolDef(
        name="profile_read", schema={"name": "profile_read", "input_schema": {}},
        func=large_result, read_only=True,
    ))
    params = {"file_path": "/tmp/large.txt"}
    research = {
        "_session_id": "surface", "tool_profile": "research",
        "_active_tool_names": frozenset({"profile_read", "SummarizeLargeFile"}),
    }
    standard = {
        "_session_id": "surface", "tool_profile": "standard",
        "_active_tool_names": frozenset({"profile_read"}),
    }
    first = execute_tool("profile_read", params, research, max_output=10_000)
    second = execute_tool("profile_read", params, standard, max_output=10_000)

    assert "SummarizeLargeFile" in first
    assert "SummarizeLargeFile" not in second
    assert "narrower offset and limit" in second
    assert calls == 2


# ------------------------------------------------------------------
# duplicate register overwrites
# ------------------------------------------------------------------

def test_duplicate_register_overwrites():
    register_tool(_make_echo_tool("dup"))

    def new_func(params: dict, config: dict) -> str:
        return "new"

    replacement = ToolDef(
        name="dup",
        schema={"name": "dup", "description": "new", "input_schema": {"type": "object", "properties": {}}},
        func=new_func,
        read_only=False,
        concurrent_safe=False,
    )
    register_tool(replacement)

    assert len(get_all_tools()) == 1
    result = execute_tool("dup", {}, config={})
    assert result == "new"


def test_output_cap_honors_context_window_override():
    """The cap follows the config's context window, not just the registry's
    provider-wide default for the model (#184)."""
    from cheetahclaws.tool_registry import _effective_output_cap

    model = "custom/some-local-model"
    assert _effective_output_cap({"model": model}, 32000) == 7000
    assert _effective_output_cap({"model": model, "context_window": 16000}, 32000) == 2000
    assert _effective_output_cap({"model": model, "context_window": 24000}, 32000) == 4000


def test_output_cap_uses_custom_endpoint_model_limit(monkeypatch):
    """A custom model's own limit wins over the smallest limit on the endpoint,
    which is what the provider-wide default gets backfilled with."""
    # compaction's own reference: other test modules reload cheetahclaws.providers.
    from cheetahclaws.compaction import providers as _providers
    from cheetahclaws.tool_registry import _effective_output_cap

    monkeypatch.setattr(_providers, "_custom_ctx_cache", {
        "http://endpoint/v1": {"big-model": 131072, "tiny-model": 8192},
    })
    monkeypatch.setitem(
        _providers.PROVIDERS, "custom",
        {**_providers.PROVIDERS.get("custom", {}), "context_limit": 8192},
    )
    config = {"model": "custom/big-model", "custom_base_url": "http://endpoint/v1"}

    assert _effective_output_cap(config, 32000) == 7000
    assert _effective_output_cap({"model": "custom/big-model"}, 32000) == 2000
