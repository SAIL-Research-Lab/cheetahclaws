"""Tool plugin registry for cheetahclaws.

Provides a central registry for tool definitions, lookup, schema export,
dispatch with output truncation, and result caching for read-only tools.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional


@dataclass
class ToolDef:
    """Definition of a single tool plugin.

    Attributes:
        name: unique tool identifier
        schema: JSON-schema dict sent to the API (name, description, input_schema)
        func: callable(params: dict, config: dict) -> str
        read_only: True if the tool never mutates state
        concurrent_safe: True if safe to run in parallel with other tools
        profiles: optional tool-surface profiles this tool belongs to.  ``None``
            applies the built-in classification for known tools; third-party
            tools default to ``full`` so they are never exposed accidentally.
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False
    profiles: Optional[FrozenSet[str]] = None


# --------------- internal state ---------------

_registry: Dict[str, ToolDef] = {}

# ``standard`` deliberately contains the small, high-frequency coding surface.
# Other profiles extend it rather than making the model choose among every
# optional integration on every turn.  Unknown/plugin tools remain opt-in via
# ``full`` unless their author explicitly sets ``ToolDef.profiles``.
_PROFILE_NAMES = frozenset({"standard", "research", "orchestration", "full"})
_STANDARD_TOOLS = frozenset({
    "Read", "Write", "Edit", "Bash", "Glob", "Grep", "GetDiagnostics",
    "AskUserQuestion", "NotebookEdit",
    "MemorySave", "MemoryDelete", "MemorySearch", "MemoryList", "MemoryVerify",
})
_RESEARCH_TOOLS = frozenset({
    "WebFetch", "WebSearch", "WebBrowse", "Research", "ReadPDF", "ReadImage",
    "ReadSpreadsheet", "ReadEmail", "SummarizeLargeFile",
})
_ORCHESTRATION_TOOLS = frozenset({
    "Agent", "SendMessage", "CheckAgentResult", "ListAgentTasks",
    "ListAgentTypes", "Skill", "SkillList", "TaskCreate", "TaskUpdate",
    "TaskGet", "TaskList", "EnterPlanMode", "ExitPlanMode", "SleepTimer",
})


def _default_profiles(name: str) -> FrozenSet[str]:
    """Classify first-party tools without forcing every registration to change."""
    if name in _STANDARD_TOOLS:
        return frozenset({"standard"})
    if name in _RESEARCH_TOOLS:
        return frozenset({"research"})
    if name in _ORCHESTRATION_TOOLS:
        return frozenset({"orchestration"})
    return frozenset({"full"})


def normalize_tool_profile(profile: str | None) -> str:
    """Return a validated profile name.

    Missing/empty values select ``full``: upgrading must never silently drop a
    capability a user relied on. Callers that want a smaller, token-cheaper
    surface opt in explicitly with ``standard``/``research``/``orchestration``.
    """
    if profile is None:
        return "full"
    if not isinstance(profile, str):
        raise ValueError("Tool profile must be a string.")
    normalized = (profile or "full").strip().lower()
    if normalized not in _PROFILE_NAMES:
        choices = ", ".join(sorted(_PROFILE_NAMES))
        raise ValueError(f"Unknown tool profile '{profile}'. Choose one of: {choices}.")
    return normalized


def _profile_allows(tool: ToolDef, profile: str) -> bool:
    if profile == "full":
        return True
    labels = tool.profiles or _default_profiles(tool.name)
    if "standard" in labels:
        return True
    return profile in labels

# --------------- result cache (read-only tools only) ---------------

_CACHE_MAX = 64  # max cached entries
_cache: Dict[str, str] = {}   # hash → result
_cache_order: list[str] = []  # LRU eviction order
_cache_lock = threading.RLock()
_cache_generation = 0
_DEFAULT_CACHE_VALUE_MAX = 12_000
_CACHE_CONFIG_KEYS = (
    # Path authorization is checked inside the tool function.  Include it in
    # the cache key so a result authorized under one root cannot bypass a
    # stricter root later in the same session.
    "allowed_root", "_worktree_cwd",
    # These settings change source work or visible content for read-only tools.
    "tool_read_max_bytes", "tool_read_scan_max_bytes", "tool_read_max_output_chars",
    "web_fetch_max_bytes", "web_search_max_bytes", "web_fetch_max_seconds", "web_search_max_seconds",
    "pdf_extract_max_chars", "pdf_extract_max_pages",
    "pdf_extract_max_file_bytes", "summarize_max_input_bytes",
    "summarize_chunk_max_output_chars", "summarize_reduce_max_input_chars",
    "max_tool_cache_output", "model", "tool_profile", "disabled_tools",
    "_active_tool_names",
)


def _cache_key(
    name: str,
    params: Dict[str, Any],
    session_id: str = "",
    config: Dict[str, Any] | None = None,
) -> str:
    """Create a stable hash from tool name + params + session + output policy.

    Including the session_id keeps cached results scoped to the originator —
    in a shared daemon, A's Read of ~/.env never gets handed to B's session.
    """
    cache_config = {}
    for key in _CACHE_CONFIG_KEYS:
        if key not in (config or {}):
            continue
        value = (config or {}).get(key)
        # Active/disabled tool sets alter profile-aware redirects and hints.
        # Serialize them deterministically rather than relying on set repr.
        if isinstance(value, (set, frozenset)):
            value = sorted(map(str, value))
        cache_config[key] = value
    raw = json.dumps(
        {"n": name, "p": params, "s": session_id, "c": cache_config},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def clear_tool_cache() -> None:
    """Clear the tool result cache. Called on file writes to invalidate."""
    global _cache_generation
    with _cache_lock:
        _cache.clear()
        _cache_order.clear()
        _cache_generation += 1


# --------------- public API ---------------

def register_tool(tool_def: ToolDef) -> None:
    """Register a tool, overwriting any existing tool with the same name."""
    if tool_def.profiles is None:
        tool_def.profiles = _default_profiles(tool_def.name)
    _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    """Look up a tool by name. Returns None if not found."""
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    """Return all registered tools (insertion order)."""
    return list(_registry.values())


def get_tool_schemas(
    profile: str | None = "full",
    disabled_tools: Iterable[str] | None = None,
) -> List[Dict[str, Any]]:
    """Return schemas visible to the model for one tool-surface profile."""
    active_profile = normalize_tool_profile(profile)
    disabled = set(disabled_tools or ())
    return [
        tool.schema for tool in _registry.values()
        if tool.name not in disabled and _profile_allows(tool, active_profile)
    ]


def get_active_tool_names(
    profile: str | None = "full",
    disabled_tools: Iterable[str] | None = None,
) -> FrozenSet[str]:
    """Return the executable counterpart to :func:`get_tool_schemas`."""
    return frozenset(
        schema["name"] for schema in get_tool_schemas(profile, disabled_tools)
    )


def get_profile_tool_names(
    profile: str | None = "full",
    disabled_tools: Iterable[str] | None = None,
) -> FrozenSet[str]:
    """Return the built-in profile surface without importing tool modules.

    Prompt construction can run before the agent imports its tool package.
    This lightweight view keeps that prompt profile-aware without triggering
    plugin registration or other unrelated import side effects.  During an
    agent turn, ``_active_tool_names`` remains the authoritative exact set.
    """
    active_profile = normalize_tool_profile(profile)
    names = set(_STANDARD_TOOLS)
    if active_profile in {"research", "full"}:
        names.update(_RESEARCH_TOOLS)
    if active_profile in {"orchestration", "full"}:
        names.update(_ORCHESTRATION_TOOLS)
    if active_profile == "full":
        names.update(_registry)
    names.difference_update(disabled_tools or ())
    return frozenset(names)


def _effective_output_cap(config: Dict[str, Any], max_output: int) -> int:
    """Keep an individual tool result below model-context safety limits."""
    try:
        from cheetahclaws.compaction import get_context_limit
        model = config.get("model", "") if config else ""
        # Pass config so a user-set context_window and the custom endpoint's
        # own per-model limit apply; without it a custom model falls back to
        # the provider-wide default, which is unrelated to the model in use.
        declared_ctx = get_context_limit(model, config) or 32768
        # Reserve 16K for system prompt + tool schemas + framing + headroom.
        # 0.5× for CJK-safety (1 char ≈ 1 token worst case).
        safe_ctx = min(declared_ctx, 30000)
        effective_max = max(2000, int((safe_ctx - 16000) * 0.5))
        return min(max_output, effective_max)
    except Exception:
        # Compaction module unavailable in some test contexts — retain the
        # static cap rather than failing dispatch.
        return max_output


def _truncate_result(
    result: str,
    params: Dict[str, Any],
    max_output: int,
    config: Dict[str, Any] | None = None,
) -> str:
    """Trim a result while retaining a useful beginning and ending."""
    output_limit = max(1, int(max_output))
    if len(result) <= output_limit:
        return result
    truncated = len(result)
    file_hint = ""
    fpath = (params or {}).get("file_path") if isinstance(params, dict) else None
    if fpath and isinstance(fpath, str):
        active_names = (config or {}).get("_active_tool_names")
        profile = (config or {}).get("tool_profile")
        summary_available = (
            "SummarizeLargeFile" in active_names
            if active_names is not None
            else profile in {"research", "full"}
        )
        if summary_available:
            short_path = fpath[:160] + ("…" if len(fpath) > 160 else "")
            file_hint = (
                f" Tip: this came from `{short_path}` — call "
                f"`SummarizeLargeFile(file_path='{short_path}')` to get a "
                f"complete chunked + map-reduce summary that fits."
            )
        else:
            short_path = fpath[:160] + ("…" if len(fpath) > 160 else "")
            file_hint = (
                f" Tip: this came from `{short_path}` — use Read again with "
                "a narrower offset and limit."
            )
    marker = (
        f"\n[... {truncated:,} chars truncated to keep total tool "
        f"output ≤ {output_limit:,} chars (model context safety).{file_hint}]\n"
    )
    if len(marker) >= output_limit:
        return marker[:output_limit]
    visible_budget = output_limit - len(marker)
    first = (visible_budget * 2) // 3
    last = visible_budget - first
    return result[:first] + marker + (result[-last:] if last else "")


def _cache_put(key: str, value: str, generation: int) -> None:
    """Insert a bounded value unless a write invalidated it mid-flight."""
    with _cache_lock:
        if generation != _cache_generation:
            return
        if key in _cache:
            if key in _cache_order:
                _cache_order.remove(key)
        _cache[key] = value
        _cache_order.append(key)
        while len(_cache_order) > _CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 32000,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters

    Returns:
        Tool result string, possibly truncated.
    """
    tool = get_tool(name)
    if tool is None:
        return f"Error: tool '{name}' not found."

    active_names = (config or {}).get("_active_tool_names")
    if active_names is not None and name not in active_names:
        profile = (config or {}).get("tool_profile", "standard")
        return (
            f"Error: tool '{name}' is not enabled by the {profile!r} tool "
            "profile for this turn. Select a profile that includes it and retry."
        )

    output_cap = _effective_output_cap(config or {}, max_output)

    # Cache hit for read-only tools (same name + same params + same session).
    use_cache = tool.read_only
    mutates_files = name in ("Write", "Edit", "Bash", "NotebookEdit")
    if use_cache:
        sid = (config or {}).get("_session_id", "") or ""
        key = _cache_key(name, params, sid, config)
        with _cache_lock:
            cached = _cache.get(key)
            if cached is not None:
                if key in _cache_order:
                    _cache_order.remove(key)
                _cache_order.append(key)
            generation = _cache_generation
        if cached is not None:
            # Cache values are already bounded, but cap again because a later
            # call can have a smaller context window than the original one.
            return _truncate_result(cached, params, output_cap, config)
    else:
        # Write tools invalidate cache (file content may have changed)
        if mutates_files:
            clear_tool_cache()

    try:
        result = tool.func(params, config)
    except Exception as e:
        return f"Error executing {name}: {e}"
    finally:
        # A Read can start after the pre-mutation invalidation but before a
        # slow Write/Bash actually changes a file. Clear again so it cannot
        # retain that old snapshot once the mutation finishes (or fails).
        if mutates_files:
            clear_tool_cache()

    result = _truncate_result(result, params, output_cap, config)

    # Cache only a bounded post-truncation result.  This prevents a single
    # pathological read-only response from occupying unbounded process RAM.
    if use_cache:
        try:
            cache_cap = int((config or {}).get(
                "max_tool_cache_output", _DEFAULT_CACHE_VALUE_MAX
            ))
        except (TypeError, ValueError):
            cache_cap = _DEFAULT_CACHE_VALUE_MAX
        cache_cap = max(1_000, min(output_cap, cache_cap))
        _cache_put(
            key, _truncate_result(result, params, cache_cap, config), generation,
        )

    return result


def clear_registry() -> None:
    """Remove all registered tools. Intended for testing."""
    _registry.clear()
