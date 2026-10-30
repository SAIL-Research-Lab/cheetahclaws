"""Context window management: two-layer compression for long conversations."""
from __future__ import annotations

from cheetahclaws import providers


# ── Token estimation ──────────────────────────────────────────────────────

def _count_str_chars(obj) -> int:
    """Recursively count total characters across all string values in a nested structure."""
    if isinstance(obj, str):
        return len(obj)
    if isinstance(obj, dict):
        return sum(_count_str_chars(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(_count_str_chars(item) for item in obj)
    return 0


def estimate_tokens(messages: list, system_prompt=None, tool_schemas=None) -> int:
    """Estimate token count. Uses chars/2.8 (conservative for code-heavy content).

    The old chars/3.5 divisor underestimated real token counts for code-heavy
    conversations because: (1) code tokens are ~2.5-3 chars each, not 3.5,
    (2) tool schemas, JSON keys, and special chars take more tokens than plain
    text, (3) per-message framing overhead (~4 tokens/msg) is not counted.
    This caused compaction to skip when it should have triggered, leading to
    context overflow crashes.

    Args:
        messages: list of message dicts with "content" field (str or list of dicts)
        system_prompt: optional system prompt (str or list of text blocks);
            counted when given, since it is sent with every request
        tool_schemas: optional list of tool schema dicts, counted as JSON
    Returns:
        approximate token count, int
    """
    return (_estimate_message_tokens(messages)
            + estimate_overhead_tokens(system_prompt, tool_schemas))


def estimate_overhead_tokens(system_prompt=None, tool_schemas=None) -> int:
    """Estimate tokens for the per-request overhead: system prompt + tools."""
    chars = 0
    if isinstance(system_prompt, str):
        chars += len(system_prompt)
    elif isinstance(system_prompt, list):
        chars += _count_str_chars(system_prompt)
    if tool_schemas:
        try:
            import json as _json
            chars += len(_json.dumps(tool_schemas, ensure_ascii=False))
        except Exception:
            chars += _count_str_chars(tool_schemas)
    if not chars:
        return 0
    return int(chars / 2.8 * 1.1)


def _estimate_message_tokens(messages: list) -> int:
    total_chars = 0
    msg_count = 0
    for m in messages:
        msg_count += 1
        content = m.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    for v in block.values():
                        if isinstance(v, str):
                            total_chars += len(v)
        for tc in m.get("tool_calls", []):
            # Recursively count all string values, including nested input dicts
            # (e.g. {"id": "c1", "name": "Bash", "input": {"command": "..."}})
            total_chars += _count_str_chars(tc)
    # chars/2.8 for content + 4 tokens/msg framing overhead + 10% buffer
    content_tokens = int(total_chars / 2.8)
    framing_tokens = msg_count * 4
    return int((content_tokens + framing_tokens) * 1.1)


# ── Real usage from the provider ──────────────────────────────────────────
#
# Heuristic estimates drift (CJK, images, provider tokenizers).  When the
# provider reports the real prompt size, the loop can call record_usage()
# after appending the assistant turn; estimates then use
#     reported tokens + heuristic(messages added since)
# for as long as the recorded prefix is unchanged.

_USAGE_ATTR = "_compaction_usage"


def record_usage(state, input_tokens: int, output_tokens: int = 0,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                 message_count: int | None = None) -> None:
    """Record the provider-reported prompt size for ``state.messages``.

    Call right after the assistant turn is appended.  ``input_tokens`` plus
    any cache read/write tokens (Anthropic reports them separately) is the
    full prompt — system + tools + messages[:n-1]; ``output_tokens`` covers
    the assistant message just appended.  ``message_count`` defaults to
    ``len(state.messages)``.  Non-positive totals are ignored.
    """
    try:
        msgs = state.messages
        total = int(input_tokens or 0) + int(cache_read_tokens or 0) \
            + int(cache_write_tokens or 0) + int(output_tokens or 0)
        if total <= 0:
            return
        n = len(msgs) if message_count is None else int(message_count)
        n = max(0, min(n, len(msgs)))
        setattr(state, _USAGE_ATTR, {
            "tokens": total,
            "count": n,
            # References (not ids) so a freed+reused id can't fake freshness.
            "first": msgs[0] if n else None,
            "last": msgs[n - 1] if n else None,
        })
    except Exception:
        pass


def clear_usage(state) -> None:
    try:
        if hasattr(state, _USAGE_ATTR):
            delattr(state, _USAGE_ATTR)
    except Exception:
        pass


def _fresh_usage(state):
    """Return the recorded usage if it still describes a prefix of
    state.messages (prefix not shortened, replaced or compacted)."""
    rec = getattr(state, _USAGE_ATTR, None)
    if not isinstance(rec, dict):
        return None
    msgs = getattr(state, "messages", None)
    if msgs is None:
        return None
    n = rec.get("count", 0)
    if n > len(msgs):
        return None
    if n and (msgs[0] is not rec.get("first") or msgs[n - 1] is not rec.get("last")):
        return None
    return rec


def estimate_context_tokens(state, system_prompt=None, tool_schemas=None) -> int:
    """Best estimate of the next request's prompt size for ``state``.

    Uses provider-reported usage (see record_usage) when fresh, otherwise
    the heuristic over messages + system prompt + tool schemas.
    """
    msgs = state.messages
    rec = _fresh_usage(state)
    if rec is not None:
        return rec["tokens"] + _estimate_message_tokens(msgs[rec["count"]:])
    return estimate_tokens(msgs, system_prompt, tool_schemas)


def get_context_limit(model: str, config: dict | None = None) -> int:
    """Look up context window size for a model.

    Delegates to providers.get_model_context_window for a single source of
    truth. The optional config arg lets callers pass custom_base_url so that
    custom/vLLM endpoints get a live /v1/models lookup instead of falling
    back to the stale 128000 default.

    A positive ``context_window`` in config overrides the looked-up default
    (set via ``/config context_window=<N>``). This is deliberately distinct from
    ``max_tokens`` (the output cap): the override lets a user correct a stale
    provider default for the session and applies consistently to the prompt %,
    /context, and the compaction trigger. It is bidirectional — a smaller value
    forces earlier compaction; a larger value can disable it (the caller should
    warn about that footgun). Scope: it applies wherever ``config`` is passed —
    the prompt %, /context, the compaction trigger, AND the per-call output-token
    cap (providers shares this parser via ``context_window_override``). Only
    auto-fanout sizing, called without ``config``, still uses the registry window.

    Args:
        model: model string (e.g. "claude-opus-4-6", "ollama/llama3.3",
               "custom/qwen2.5-72b")
        config: optional agent config dict; reads context_window override, plus
                custom_base_url / custom_api_key if provider is 'custom'
    Returns:
        context limit in tokens
    """
    override = providers.context_window_override(config)
    if override > 0:
        return override
    provider_name = providers.detect_provider(model)
    base_url = ""
    api_key = ""
    if config and provider_name == "custom":
        base_url = config.get("custom_base_url", "") or ""
        api_key = config.get("custom_api_key", "") or ""
    return providers.get_model_context_window(
        provider_name, model, base_url, api_key
    )


# ── Layer 1: Snip old tool results ────────────────────────────────────────

def snip_old_tool_results(
    messages: list,
    max_chars: int = 2000,
    preserve_last_n_turns: int = 6,
) -> list:
    """Truncate tool-role messages older than preserve_last_n_turns from end.

    For old tool messages whose content exceeds max_chars, keep the first half
    and last quarter, inserting '[... N chars snipped ...]' in between.
    Mutates in place and returns the same list.

    Args:
        messages: list of message dicts (mutated in place)
        max_chars: maximum character length before truncation
        preserve_last_n_turns: number of messages from end to preserve
    Returns:
        the same messages list (mutated)
    """
    cutoff = max(0, len(messages) - preserve_last_n_turns)
    for i in range(cutoff):
        m = messages[i]
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if not isinstance(content, str) or len(content) <= max_chars:
            continue
        first_half = content[: max_chars // 2]
        last_quarter = content[-(max_chars // 4):]
        snipped = len(content) - len(first_half) - len(last_quarter)
        m["content"] = f"{first_half}\n[... {snipped} chars snipped ...]\n{last_quarter}"
    return messages


# ── Layer 2: Auto-compact ─────────────────────────────────────────────────

def _respect_tool_pairs(messages: list, split: int) -> int:
    """Advance split so it never falls inside a tool_calls → tool-response block.

    OpenAI-compatible APIs (DeepSeek, etc.) reject any 'tool' message that is
    not preceded by an 'assistant' with matching tool_calls. If the split lands
    between an assistant(tool_calls) and its tool responses, the recent half
    would contain orphan tool messages after compaction.
    """
    n = len(messages)
    if split <= 0 or split >= n:
        return split
    prev = messages[split - 1]
    if prev.get("role") == "assistant" and (prev.get("tool_calls") or []):
        j = split
        while j < n and messages[j].get("role") == "tool":
            j += 1
        split = j
    while split < n and messages[split].get("role") == "tool":
        split += 1
    return split


def find_split_point(messages: list, keep_ratio: float = 0.3) -> int:
    """Find index that splits messages so ~keep_ratio of tokens are in the recent portion.

    Walks backwards from end, accumulating token estimates, and returns the
    index where the recent portion reaches ~keep_ratio of total tokens. The
    index is then adjusted so it never cuts a tool-call response block.

    Args:
        messages: list of message dicts
        keep_ratio: fraction of tokens to keep in the recent portion
    Returns:
        split index (messages[:idx] = old, messages[idx:] = recent).
        Returns 0 if no safe split exists (caller should skip compaction).
    """
    if not messages:
        return 0
    keep_ratio = max(0.0, min(1.0, keep_ratio))
    total = estimate_tokens(messages)
    target = int(total * keep_ratio)
    running = 0
    raw = 0
    for i in range(len(messages) - 1, -1, -1):
        running += estimate_tokens([messages[i]])
        if running >= target:
            raw = i
            break
    adjusted = _respect_tool_pairs(messages, raw)
    if adjusted >= len(messages):
        return 0
    return adjusted


def sanitize_history(messages: list) -> list:
    """Enforce the tool-calls ↔ tool-response invariant required by OpenAI-compatible APIs.

    Walks the list in order maintaining a set of pending tool_call_ids from the
    most recent assistant(tool_calls). Drops any 'tool' message whose
    tool_call_id is not in that set (orphan). When a non-tool message arrives
    with pending ids still open, strips those unanswered tool_calls from the
    preceding assistant message (so DeepSeek won't reject it).

    Returns a new list; the input is not mutated.
    """
    cleaned: list = []
    pending: set[str] = set()

    def _strip_unanswered():
        if not pending:
            return
        # Walk back past any trailing tool messages to reach the assistant that owns them.
        target = None
        for k in range(len(cleaned) - 1, -1, -1):
            role_k = cleaned[k].get("role")
            if role_k == "tool":
                continue
            if role_k == "assistant":
                target = k
            break
        if target is None:
            return
        prev = cleaned[target]
        tcs = prev.get("tool_calls") or []
        kept = [tc for tc in tcs if tc.get("id") not in pending]
        if len(kept) == len(tcs):
            return
        new_prev = dict(prev)
        if kept:
            new_prev["tool_calls"] = kept
        else:
            new_prev.pop("tool_calls", None)
            if new_prev.get("content") in (None, ""):
                new_prev["content"] = ""
        cleaned[target] = new_prev

    for m in messages:
        role = m.get("role")
        if role == "tool":
            tid = m.get("tool_call_id")
            if tid in pending:
                cleaned.append(m)
                pending.discard(tid)
            continue
        _strip_unanswered()
        pending = set()
        if role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                pending = {tc["id"] for tc in tcs if tc.get("id")}
        cleaned.append(m)

    _strip_unanswered()
    return cleaned


_KEY_ARG_NAMES = (
    "file_path", "notebook_path", "path", "command", "pattern", "glob",
    "url", "query", "subagent_type", "name", "to", "offset", "limit",
)
_EDIT_TOOL_NAMES = ("Write", "Edit", "NotebookEdit")
_READ_TOOL_NAMES = ("Read", "ReadPDF", "ReadImage", "ReadSpreadsheet",
                    "SummarizeLargeFile")
_SUMMARY_SYSTEM = "You are a precise summarizer of software-engineering sessions."
_SUMMARY_HEADER = "[Previous conversation summary]"


def _clip(text: str, budget: int) -> str:
    """Keep head and tail of ``text`` within ``budget`` chars."""
    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text
    if budget < 80:
        return text[:budget]
    head = (budget * 2) // 3
    tail = budget - head - 40
    omitted = len(text) - head - max(tail, 0)
    return (text[:head] + f"\n[… {omitted} chars omitted …]\n"
            + (text[-tail:] if tail > 0 else ""))


def _content_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("content"), str):
                    parts.append(block["content"])
                elif block.get("type"):
                    parts.append(f"<{block['type']}>")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _fmt_tool_call(tc: dict, arg_budget: int = 200) -> str:
    name = tc.get("name", "?")
    inp = tc.get("input") or {}
    if not isinstance(inp, dict):
        return f"{name}({_clip(str(inp), arg_budget)})"
    args = []
    for k in _KEY_ARG_NAMES:
        if k in inp and inp[k] not in (None, ""):
            args.append(f"{k}={_clip(str(inp[k]), arg_budget)!r}")
    if name == "Edit":
        for k in ("old_string", "new_string"):
            if isinstance(inp.get(k), str):
                args.append(f"{k}={_clip(inp[k], arg_budget // 2)!r}")
    elif name == "Write" and isinstance(inp.get("content"), str):
        args.append(f"content=<{len(inp['content'])} chars>")
    elif name in ("Agent", "Task") and isinstance(inp.get("prompt"), str):
        args.append(f"prompt={_clip(inp['prompt'], arg_budget)!r}")
    if not args and inp:
        args.append(_clip(", ".join(f"{k}={v!r}" for k, v in inp.items()),
                          arg_budget))
    return f"{name}({', '.join(args)})"


def _looks_like_error(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return (head.startswith("error") or head.startswith("denied")
            or "traceback (most recent call last)" in text[-4000:].lower()
            or "exit code" in head and "exit code: 0" not in head)


def build_structured_transcript(messages: list, budget_chars: int = 60_000) -> str:
    """Render ``messages`` for the summariser.

    Starts with deterministic indices (user requests, files modified/read,
    errors) and follows with a chronological transcript in which tool calls
    keep their key arguments and every message gets a per-message budget
    proportional to ``budget_chars``.
    """
    budget_chars = max(4_000, int(budget_chars))
    user_asks: list = []
    files_modified: dict = {}
    files_read: dict = {}
    errors: list = []
    tc_names: dict = {}

    for m in messages:
        role = m.get("role")
        if role == "user":
            text = _content_text(m.get("content", "")).strip()
            if text and not text.startswith(_SUMMARY_HEADER):
                user_asks.append(_clip(text, 300))
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc, dict):
                    continue
                tc_names[tc.get("id")] = tc
                inp = tc.get("input") or {}
                path = (inp.get("file_path") or inp.get("notebook_path")
                        if isinstance(inp, dict) else None)
                if path:
                    if tc.get("name") in _EDIT_TOOL_NAMES:
                        files_modified.setdefault(path, set()).add(tc["name"])
                    elif tc.get("name") in _READ_TOOL_NAMES:
                        files_read.setdefault(path, None)
        elif role == "tool":
            text = _content_text(m.get("content", ""))
            if m.get("is_error") or (m.get("is_error") is None
                                     and _looks_like_error(text)):
                tc = tc_names.get(m.get("tool_call_id")) or {}
                label = _fmt_tool_call(tc, 120) if tc else (m.get("name") or "tool")
                errors.append(f"{label}: {_clip(text.strip(), 300)}")

    sections = []
    if user_asks:
        sections.append("## User requests (chronological)\n"
                        + "\n".join(f"- {a}" for a in user_asks[-30:]))
    if files_modified:
        sections.append("## Files modified\n" + "\n".join(
            f"- {p} ({', '.join(sorted(t))})" for p, t in files_modified.items()))
    if files_read:
        sections.append("## Files read\n" + "\n".join(
            f"- {p}" for p in list(files_read)[:60]))
    if errors:
        sections.append("## Errors seen\n" + "\n".join(
            f"- {e}" for e in errors[-20:]))
    index = "\n\n".join(sections)
    index = _clip(index, budget_chars // 3)

    remaining = max(2_000, budget_chars - len(index))
    n = max(1, len(messages))
    per_msg = max(500, min(8_000, remaining // n))
    lines = []
    for m in messages:
        role = m.get("role", "?")
        text = _content_text(m.get("content", ""))
        if role == "tool":
            tc = tc_names.get(m.get("tool_call_id")) or {}
            label = tc.get("name") or m.get("name") or "tool"
            lines.append(f"[tool result: {label}]: {_clip(text, per_msg)}")
            continue
        if text:
            lines.append(f"[{role}]: {_clip(text, per_msg)}")
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                lines.append(f"[{role} → tool call] {_fmt_tool_call(tc)}")
        if m.get("images"):
            lines.append(f"[{role}]: <{len(m['images'])} image(s) attached>")
    transcript = _clip("\n".join(lines), remaining)
    parts = []
    if index:
        parts.append("# Index (extracted deterministically)\n\n" + index)
    parts.append("# Transcript\n\n" + transcript)
    return "\n\n".join(parts)


def _summary_input_budget(config: dict) -> int:
    """Chars of transcript to hand the summariser: ~40% of the smaller of
    the main / auxiliary model windows (2.8 chars/token), 8K..300K chars.
    ``compaction_summary_input_chars`` overrides."""
    try:
        override = int(config.get("compaction_summary_input_chars") or 0)
    except (TypeError, ValueError):
        override = 0
    if override > 0:
        return override
    ctx = 32_768
    try:
        ctx = get_context_limit(config.get("model", ""), config) or ctx
        from cheetahclaws.auxiliary import get_auxiliary_model
        aux = get_auxiliary_model(config)
        if aux and aux != config.get("model"):
            aux_ctx = get_context_limit(aux, None)
            if aux_ctx:
                ctx = min(ctx, aux_ctx)
    except Exception:
        pass
    return max(8_000, min(300_000, int(ctx * 0.4 * 2.8)))


_SUMMARY_INSTRUCTIONS = (
    "Summarize the earlier part of this coding session so the work can "
    "continue seamlessly without it. Be specific and faithful; prefer exact "
    "file paths, function names, commands and error messages over prose. "
    "Use these sections (omit empty ones):\n"
    "1. User requests & intent — every distinct ask, constraints, preferences.\n"
    "2. Key decisions & rationale.\n"
    "3. Files touched — path: what changed / why (and notable files read).\n"
    "4. Commands & tool results that matter (tests run, outcomes).\n"
    "5. Errors & how they were resolved (or not).\n"
    "6. Current state — what is done, what is in progress.\n"
    "7. Open TODOs / next steps."
)


def _summarize(old: list, config: dict, focus: str = "") -> str:
    """Return an LLM summary of ``old``; raises or returns '' on failure."""
    transcript = build_structured_transcript(old, _summary_input_budget(config))
    summary_prompt = _SUMMARY_INSTRUCTIONS
    if focus:
        summary_prompt += f"\n\nFocus especially on: {focus}"
    summary_prompt += "\n\n" + transcript
    from cheetahclaws.auxiliary import stream_auxiliary
    return stream_auxiliary(
        system=_SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": summary_prompt}],
        config=config,
    )


def _summary_pair(summary_text: str) -> list:
    return [
        {"role": "user", "content": f"{_SUMMARY_HEADER}\n{summary_text}"},
        {"role": "assistant",
         "content": "Understood. I have the context from the previous conversation. Let's continue."},
    ]


def deterministic_compact(messages: list, config: dict) -> list:
    """Compact without an LLM: replace the old portion with the deterministic
    index + a tightly budgeted transcript.  Used when the summariser fails."""
    split = find_split_point(messages)
    if split <= 0:
        return messages
    old, recent = messages[:split], messages[split:]
    budget = max(4_000, _summary_input_budget(config) // 6)
    digest = build_structured_transcript(old, budget)
    note = ("(LLM summary unavailable — deterministic digest of the earlier "
            "conversation; details beyond these excerpts were dropped.)\n\n")
    return [*_summary_pair(note + digest), *recent]


def _compact_with_status(messages: list, config: dict, focus: str = "") -> tuple:
    """Return (new_messages, status) with status in
    {"noop", "ok", "failed"}."""
    split = find_split_point(messages)
    if split <= 0:
        return messages, "noop"

    old = messages[:split]
    recent = messages[split:]

    # Call auxiliary (fast/cheap) model for summary instead of the primary model.
    try:
        summary_text = _summarize(old, config, focus)
    except Exception as e:
        try:
            from cheetahclaws import logging_utils as _log
            _log.warn("compaction_summary_failed",
                      error_type=type(e).__name__, error=str(e)[:200])
        except Exception:
            pass
        return messages, "failed"

    if not summary_text or not summary_text.strip():
        return messages, "failed"
    return [*_summary_pair(summary_text), *recent], "ok"


def compact_messages(messages: list, config: dict, focus: str = "") -> list:
    """Compress old messages into a summary via LLM call.

    Splits at find_split_point, summarizes old portion (as a structured
    transcript), returns [summary_msg, ack_msg, *recent_messages].  If the
    summariser fails, falls back to :func:`deterministic_compact` (disable
    with ``compaction_deterministic_fallback: false`` to get the original
    messages back unchanged, the legacy behaviour).

    Args:
        messages: full message list
        config: agent config dict (must contain "model")
        focus: optional focus instructions for the summarizer
    Returns:
        new compacted message list
    """
    out, status = _compact_with_status(messages, config, focus)
    if status == "failed" and config.get("compaction_deterministic_fallback", True):
        return deterministic_compact(messages, config)
    return out


# ── Main entry ────────────────────────────────────────────────────────────

_BACKOFF_ATTR = "_compaction_backoff_until"


def _turn_counter(state) -> int:
    turn = getattr(state, "turn_count", None)
    if isinstance(turn, int):
        return turn
    n = getattr(state, "_compaction_calls", 0) + 1
    try:
        state._compaction_calls = n
    except Exception:
        pass
    return n


def _request_overhead(config: dict, system_prompt, tool_schemas) -> tuple:
    """Resolve system prompt / tool schemas for the estimate.  Defaults come
    from the loop's config (``_system_prompt``, tool profile).  Disable with
    ``compaction_count_overhead: false``."""
    if not config.get("compaction_count_overhead", True):
        return None, None
    if system_prompt is None:
        system_prompt = config.get("_system_prompt")
    if tool_schemas is None:
        try:
            from cheetahclaws.tool_registry import (
                get_tool_schemas, normalize_tool_profile,
            )
            disabled = config.get("disabled_tools") or ()
            if not isinstance(disabled, (list, tuple, set, frozenset)):
                disabled = ()
            tool_schemas = get_tool_schemas(
                normalize_tool_profile(config.get("tool_profile")), disabled)
        except Exception:
            tool_schemas = None
    return system_prompt, tool_schemas


def maybe_compact(state, config: dict, system_prompt=None, tool_schemas=None) -> bool:
    """Check if context window is getting full and compress if needed.

    Runs snip_old_tool_results first, then auto-compact if still over threshold.
    The estimate includes the system prompt and tool schemas, and prefers
    provider-reported usage recorded via :func:`record_usage`.  If the LLM
    summariser fails, a deterministic digest is used instead and the LLM is
    not retried for ``compaction_failure_backoff_turns`` (default 3) turns.

    Args:
        state: AgentState with .messages list
        config: agent config dict (must contain "model")
        system_prompt / tool_schemas: optional; default to the loop's
            ``_system_prompt`` and active tool profile from config
    Returns:
        True if compaction was performed
    """
    model = config.get("model", "")
    limit = get_context_limit(model, config)
    system_prompt, tool_schemas = _request_overhead(config, system_prompt, tool_schemas)
    overhead = estimate_overhead_tokens(system_prompt, tool_schemas)
    # Fire at 70% of the window, but always leave messages at least 30% of
    # it: when the fixed overhead alone is huge (big tool surface on a small
    # model) compaction cannot help and must not run every turn.
    threshold = max(limit * 0.7, overhead + limit * 0.3)

    def _estimate() -> int:
        rec = _fresh_usage(state)
        if rec is not None:
            return rec["tokens"] + _estimate_message_tokens(
                state.messages[rec["count"]:])
        return _estimate_message_tokens(state.messages) + overhead

    turn = _turn_counter(state)
    if _estimate() <= threshold:
        return False

    # Layer 1: snip old tool results.  Snipping edits the recorded prefix in
    # place, so shift a recorded usage figure by the heuristic delta.
    rec = _fresh_usage(state)
    before_snip = _estimate_message_tokens(state.messages) if rec else 0
    snip_old_tool_results(state.messages)
    if rec is not None:
        removed = before_snip - _estimate_message_tokens(state.messages)
        rec["tokens"] = max(0, rec["tokens"] - max(0, removed))

    if _estimate() <= threshold:
        return True

    # Layer 2: auto-compact (LLM), unless recently failed → deterministic
    backoff_until = getattr(state, _BACKOFF_ATTR, 0) or 0
    if turn < backoff_until:
        new_msgs, status = deterministic_compact(state.messages, config), "fallback"
    else:
        new_msgs, status = _compact_with_status(state.messages, config)
        if status == "failed":
            try:
                n = int(config.get("compaction_failure_backoff_turns", 3))
            except (TypeError, ValueError):
                n = 3
            try:
                setattr(state, _BACKOFF_ATTR, turn + max(0, n) + 1)
            except Exception:
                pass
            if config.get("compaction_deterministic_fallback", True):
                new_msgs = deterministic_compact(state.messages, config)
    state.messages = new_msgs
    state.messages.extend(_restore_plan_context(config))
    clear_usage(state)
    return True


# ── Plan context restoration ─────────────────────────────────────────────

def _restore_plan_context(config: dict) -> list:
    """If in plan mode, return messages that restore plan file context."""
    from pathlib import Path
    from cheetahclaws import runtime
    plan_file = runtime.get_ctx(config).plan_file or ""
    if not plan_file or config.get("permission_mode") != "plan":
        return []
    p = Path(plan_file)
    if not p.exists():
        return []
    content = p.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return [
        {"role": "user", "content": f"[Plan file restored after compaction: {plan_file}]\n\n{content}"},
        {"role": "assistant", "content": "I have the plan context. Let's continue."},
    ]


# ── Manual compact ───────────────────────────────────────────────────────

def manual_compact(state, config: dict, focus: str = "") -> tuple[bool, str]:
    """User-triggered compaction via /compact. Not gated by threshold.

    Returns (success, info_message).
    """
    if len(state.messages) < 4:
        return False, "Not enough messages to compact."

    before = estimate_tokens(state.messages)
    snip_old_tool_results(state.messages)
    new_msgs, status = _compact_with_status(state.messages, config, focus=focus)
    note = ""
    if status == "failed":
        if config.get("compaction_deterministic_fallback", True):
            new_msgs = deterministic_compact(state.messages, config)
            note = " (summariser unavailable — used deterministic digest)"
        else:
            note = " (summariser unavailable — only old tool results were snipped)"
    state.messages = new_msgs
    state.messages.extend(_restore_plan_context(config))
    clear_usage(state)
    after = estimate_tokens(state.messages)
    saved = before - after
    return True, f"Compacted: ~{before} → ~{after} tokens (~{saved} saved){note}"
