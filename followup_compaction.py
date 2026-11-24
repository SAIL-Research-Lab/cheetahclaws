"""Follow-up compaction: destroy past-turn tool content before each API call.

At each user turn boundary, ALL tool messages and assistant tool_calls from
prior turns are completely removed (no stubs).  The current turn is always
kept intact.

Non-destructive to state.messages -- produces a new list so persistence and
resume keep the full history.
"""
from __future__ import annotations

import html
import re
import time


_THINKING_BLOCK_RE = re.compile(r'<thinking>.*?</thinking>\s*', re.DOTALL)


_ARGS_PREFERRED_KEY = {
    "Read": "file_path", "Edit": "file_path", "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern", "Grep": "pattern",
    "Bash": "command",
    "WebFetch": "url", "WebSearch": "query",
}


def _escape_xml_attr(s: str) -> str:
    return html.escape(str(s), quote=True)


def _input_brief(tool_name: str, input_dict: dict, max_len: int = 60) -> str:
    if not input_dict:
        return ""
    val = input_dict.get(_ARGS_PREFERRED_KEY.get(tool_name, ""))
    if val is None:
        for v in input_dict.values():
            if isinstance(v, str) and v:
                val = v
                break
    if val is None:
        return ""
    val = str(val).replace("\n", " ")
    if len(val) > max_len:
        val = val[: max_len - 3] + "..."
    return val


def _build_tc_lookup(tool_calls: list | None) -> dict:
    lookup: dict = {}
    for tc in tool_calls or []:
        tid = tc.get("id", "")
        if tid:
            lookup[tid] = (tc.get("name", "tool"), tc.get("input") or {})
    return lookup


def _xml_replacer(tc_lookup: dict, target_ids: set | None = None):
    def _replacer(match):
        name, tid = match.group(1), match.group(2)
        if target_ids is not None and tid not in target_ids:
            return match.group(0)
        tc_name, tc_input = tc_lookup.get(tid, (name, {}))
        brief = _input_brief(tc_name, tc_input)
        return f'<tool_use_elided name="{_escape_xml_attr(tc_name)}" brief="{_escape_xml_attr(brief)}"/>'
    return _replacer


_TOOL_USE_RE = re.compile(
    r'<tool_use\s+name="([^"]+)"\s+id="([^"]+)"[^>]*>.*?</tool_use>',
    re.DOTALL,
)


def compact_assistant_xml(content: str, tool_calls: list | None = None) -> str:
    """Replace ALL inline XML tool_use blocks with one-line summaries."""
    if not content or "<tool_use" not in content:
        return content
    return _TOOL_USE_RE.sub(
        _xml_replacer(_build_tc_lookup(tool_calls)), content,
    )


def compact_assistant_xml_selective(
    content: str, tool_calls: list | None, target_ids: set,
) -> str:
    """Replace only XML blocks whose id is in target_ids, leaving others intact."""
    if not content or "<tool_use" not in content or not target_ids:
        return content
    return _TOOL_USE_RE.sub(
        _xml_replacer(_build_tc_lookup(tool_calls), target_ids), content,
    )


def _is_completed_boundary(messages: list, user_idx: int) -> bool:
    if user_idx == 0:
        return True
    prev = messages[user_idx - 1]
    return prev.get("role") == "assistant" and not prev.get("tool_calls")


def compact_tool_history(messages: list, keep_last_n_turns: int = 0) -> list:
    """Completely remove prior-turn tool content.

    At user turn boundaries, ALL tool messages and assistant tool_calls from
    prior turns are destroyed (no stubs).  Assistant messages that become empty
    after stripping are also removed.

    The current turn (last ``keep_last_n_turns + 1`` user messages onward) is
    kept intact.
    """
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indices:
        return list(messages)

    valid_boundaries = [i for i in user_indices
                        if _is_completed_boundary(messages, i)]

    total_keep = keep_last_n_turns + 1
    if total_keep >= len(valid_boundaries):
        return list(messages)

    current_turn_start = valid_boundaries[-total_keep]

    result = []
    for i, msg in enumerate(messages):
        if i >= current_turn_start:
            result.append(msg)
            continue

        role = msg.get("role")

        if role == "tool":
            continue

        if role == "user":
            result.append(msg)
            continue

        if role == "assistant":
            tool_calls = msg.get("tool_calls")
            content = msg.get("content", "") or ""

            if tool_calls:
                content = compact_assistant_xml(content, tool_calls)
                cleaned = dict(msg)
                cleaned.pop("tool_calls", None)
                cleaned["content"] = content
                if not content.strip():
                    continue
                result.append(cleaned)
            else:
                if content.strip():
                    result.append(msg)
            continue

        result.append(msg)

    return result


def _mark_compaction_boundary(messages: list) -> None:
    """Mark the last message before the current user turn with _cache_breakpoint.

    This tells messages_to_anthropic where to place cache_control so the
    compacted prefix is cached and current-loop messages stay fresh.
    """
    user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if len(user_indices) < 2:
        return
    valid_boundaries = []
    for idx in user_indices:
        if idx == 0:
            valid_boundaries.append(idx)
        else:
            prev = messages[idx - 1]
            role = prev.get("role")
            if role == "assistant" and not prev.get("tool_calls"):
                valid_boundaries.append(idx)
            elif role == "user":
                valid_boundaries.append(idx)
    if len(valid_boundaries) < 2:
        return
    current_start = valid_boundaries[-1]
    if current_start > 0:
        messages[current_start - 1]["_cache_breakpoint"] = True


def _strip_thinking_from_messages(messages: list) -> list:
    """Remove <thinking>...</thinking> blocks from assistant message content.

    Non-destructive: returns a new list with new dicts where needed.
    Handles both string and list-of-blocks content formats.
    """
    result = []
    for msg in messages:
        if msg.get("role") != "assistant":
            result.append(msg)
            continue
        content = msg.get("content", "")
        if isinstance(content, str) and "<thinking>" in content:
            cleaned = _THINKING_BLOCK_RE.sub("", content)
            result.append({**msg, "content": cleaned or "."})
        elif isinstance(content, list):
            new_blocks = []
            changed = False
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text" and "<thinking>" in block.get("text", ""):
                    cleaned = _THINKING_BLOCK_RE.sub("", block["text"])
                    new_blocks.append({**block, "text": cleaned or "."})
                    changed = True
                else:
                    new_blocks.append(block)
            result.append({**msg, "content": new_blocks} if changed else msg)
        else:
            result.append(msg)
    return result


def build_messages_for_api(state, config: dict) -> list:
    """Compact prior-turn tool content at user boundaries, then apply ContextGC.

    compact_tool_history runs on every build so the post-compaction prefix is
    byte-stable across every call in a turn, not just the one that immediately
    follows a user message. The function is idempotent: it always leaves the
    last user turn intact and only touches prior-turn tool content.
    """
    compacted = compact_tool_history(list(state.messages))
    result = _apply_context_gc(compacted, state)
    try:
        from context_gc import strip_trashed_stubs
        result = strip_trashed_stubs(result)
    except ImportError:
        pass
    result = _strip_thinking_from_messages(result)
    _mark_compaction_boundary(result)
    return result


def _apply_context_gc(messages: list, state) -> list:
    """Apply model-driven GC decisions.  Notes and audit info are injected
    into the last user message in dispatch.py, keeping them out of system
    blocks for Anthropic cache stability."""
    try:
        from context_gc import apply_gc
    except ImportError:
        return messages
    gc_state = getattr(state, 'gc_state', None)
    if not gc_state:
        return messages
    if not gc_state.trashed_ids and not gc_state.snippets:
        return messages

    try:
        from compaction import estimate_tokens
        tokens_before = estimate_tokens(messages)
    except ImportError:
        tokens_before = None

    result = apply_gc(messages, gc_state)

    if tokens_before is not None:
        try:
            tokens_after = estimate_tokens(result)
            if tokens_before != tokens_after and hasattr(state, 'compaction_log'):
                state.compaction_log.append({
                    "event": "context_gc",
                    "timestamp": time.time(),
                    "turn": getattr(state, "turn_count", 0),
                    "trashed_count": len(gc_state.trashed_ids),
                    "snippet_count": len(gc_state.snippets),
                    "notes_count": len(gc_state.notes),
                    "tokens_est_saved": tokens_before - tokens_after,
                })
        except ImportError:
            pass
    return result
