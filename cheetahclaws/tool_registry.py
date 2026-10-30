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
        max_output: optional per-tool upper bound on result chars; the
            context-scaled cap applies on top of it.
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False
    profiles: Optional[FrozenSet[str]] = None
    max_output: Optional[int] = None


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


# Context windows at or below this size keep the original conservative cap
# (16K reserved for prompt/schemas, 0.5x CJK safety, capped at 7K chars).
_SMALL_CONTEXT_TOKENS = 32768
# Default share of the context window one tool result may occupy on larger
# models, and the chars-per-token conversion used for it.  2 chars/token sits
# between code (~3) and CJK (~1) so a result costs about ``fraction`` of the
# window for code and at most ~2x that in the CJK worst case.
_DEFAULT_TOOL_OUTPUT_CTX_FRACTION = 0.10
_TOOL_OUTPUT_CHARS_PER_TOKEN = 2
# Absolute ceiling for a single tool result regardless of window size.
_DEFAULT_TOOL_OUTPUT_MAX_CHARS = 100_000


def _legacy_output_cap(declared_ctx: int) -> int:
    # Reserve 16K for system prompt + tool schemas + framing + headroom.
    # 0.5x for CJK-safety (1 char ~ 1 token worst case).
    safe_ctx = min(declared_ctx, 30000)
    return max(2000, int((safe_ctx - 16000) * 0.5))


def _config_number(config: Dict[str, Any], key: str, default, cast=float):
    try:
        value = (config or {}).get(key)
        if value is None:
            return default
        return cast(value)
    except (TypeError, ValueError):
        return default


def _effective_output_cap(config: Dict[str, Any], max_output: int | None) -> int:
    """Keep an individual tool result below model-context safety limits.

    Small windows (<= 32K tokens) keep the historical conservative cap.
    Larger windows scale with the window: ``tool_output_context_fraction``
    (default 0.10) of the context, converted at 2 chars/token, bounded by
    the caller/tool ``max_output`` and ``tool_output_max_chars`` (default
    100K chars).  Setting ``tool_output_context_fraction`` to 0 restores the
    legacy fixed cap for every window size.
    """
    ceiling = _config_number(
        config, "tool_output_max_chars", _DEFAULT_TOOL_OUTPUT_MAX_CHARS, int,
    )
    ceiling = max(1_000, ceiling)
    bound = ceiling if max_output is None else min(int(max_output), ceiling)
    try:
        from cheetahclaws.compaction import get_context_limit
        model = config.get("model", "") if config else ""
        # Pass config so a user-set context_window and the custom endpoint's
        # own per-model limit apply; without it a custom model falls back to
        # the provider-wide default, which is unrelated to the model in use.
        declared_ctx = get_context_limit(model, config) or 32768
    except Exception:
        # Compaction module unavailable in some test contexts — retain the
        # static cap rather than failing dispatch.
        return bound if max_output is not None else 32000
    legacy = _legacy_output_cap(declared_ctx)
    fraction = _config_number(
        config, "tool_output_context_fraction", _DEFAULT_TOOL_OUTPUT_CTX_FRACTION,
    )
    if declared_ctx <= _SMALL_CONTEXT_TOKENS or fraction <= 0:
        return min(bound, legacy)
    fraction = min(fraction, 0.5)
    scaled = int(declared_ctx * fraction * _TOOL_OUTPUT_CHARS_PER_TOKEN)
    return min(bound, max(legacy, scaled))


def _snap_head(text: str, budget: int) -> str:
    """Leading ``budget`` chars, ending on a line boundary when one is close."""
    head = text[:budget]
    cut = head.rfind("\n")
    if cut >= budget * 0.8:
        return head[:cut + 1]
    return head


def _snap_tail(text: str, budget: int) -> str:
    """Trailing ``budget`` chars, starting on a line boundary when one is close."""
    if budget <= 0:
        return ""
    tail = text[-budget:]
    cut = tail.find("\n")
    if 0 <= cut <= budget * 0.2:
        return tail[cut + 1:]
    return tail


def _more_hint(params: Dict[str, Any], config: Dict[str, Any] | None) -> str:
    """Explain how the model can see the omitted part."""
    params = params if isinstance(params, dict) else {}
    fpath = params.get("file_path")
    if fpath and isinstance(fpath, str):
        active_names = (config or {}).get("_active_tool_names")
        profile = (config or {}).get("tool_profile")
        summary_available = (
            "SummarizeLargeFile" in active_names
            if active_names is not None
            else profile in {"research", "full"}
        )
        short_path = fpath[:160] + ("…" if len(fpath) > 160 else "")
        if summary_available:
            return (
                f" Tip: this came from `{short_path}` — call "
                f"`SummarizeLargeFile(file_path='{short_path}')` to get a "
                f"complete chunked + map-reduce summary that fits, or Read "
                "with a narrower offset and limit."
            )
        return (
            f" Tip: this came from `{short_path}` — use Read again with "
            "a narrower offset and limit."
        )
    if isinstance(params.get("command"), str):
        return (
            " To see the omitted part, re-run piping through `grep`/`head`/"
            "`tail -n N`, or redirect to a file and Read it with offset/limit."
        )
    if "pattern" in params:
        return " Narrow the pattern or path to see the rest."
    return ""


def _truncate_result(
    result: str,
    params: Dict[str, Any],
    max_output: int,
    config: Dict[str, Any] | None = None,
) -> str:
    """Trim a result while retaining a useful beginning and ending.

    Both ends are kept: the head shows what ran, the tail is where test
    failures, tracebacks and summaries usually live.  The marker states how
    much was omitted and how to see it.
    """
    output_limit = max(1, int(max_output))
    if len(result) <= output_limit:
        return result
    truncated = len(result)
    hint = _more_hint(params, config)

    def _marker(omitted_chars: int, omitted_lines: int) -> str:
        lines = f", {omitted_lines:,} lines" if omitted_lines else ""
        return (
            f"\n[... {omitted_chars:,} chars{lines} omitted from the middle "
            f"of {truncated:,}; output truncated to keep total tool "
            f"output ≤ {output_limit:,} chars (model context safety).{hint}]\n"
        )

    # Size the marker with worst-case numbers so the final text always fits.
    probe = _marker(truncated, result.count("\n"))
    if len(probe) >= output_limit:
        short = f"\n[... {truncated:,} chars truncated]\n"
        return (short if len(short) <= output_limit else probe)[:output_limit]
    visible_budget = output_limit - len(probe)
    # Favour the head slightly but keep a substantial tail (errors at end).
    first_budget = (visible_budget * 3) // 5
    last_budget = visible_budget - first_budget
    head = _snap_head(result, first_budget)
    tail = _snap_tail(result, last_budget)
    omitted = result[len(head):len(result) - len(tail)]
    marker = _marker(len(omitted), omitted.count("\n"))
    return head + marker + tail


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
    max_output: int | None = None,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters.  ``None``
            (default) lets the cap scale with the model's context window
            (see :func:`_effective_output_cap`); ``ToolDef.max_output``
            further bounds it per tool.

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

    if tool.max_output is not None:
        max_output = (
            tool.max_output if max_output is None
            else min(int(max_output), int(tool.max_output))
        )
    output_cap = _effective_output_cap(config or {}, max_output)

    # Cache hit for read-only tools (same name + same params + same session).
    use_cache = tool.read_only
    mutates_files = name in ("Write", "Edit", "MultiEdit", "ApplyPatch",
                             "Bash", "NotebookEdit")
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
