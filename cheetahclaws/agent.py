"""Core agent loop: neutral message format, multi-provider streaming."""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Generator

from cheetahclaws.tool_registry import (
    get_active_tool_names,
    get_tool_schemas,
    normalize_tool_profile,
)
from cheetahclaws.tools import execute_tool
from cheetahclaws import tools as _tools_init  # ensure built-in tools are registered on import
from cheetahclaws.providers import stream, AssistantTurn, TextChunk, ThinkingChunk, detect_provider, nim_next_model
from cheetahclaws.compaction import maybe_compact, estimate_tokens, get_context_limit, compact_messages, sanitize_history
from cheetahclaws import logging_utils as _log
from cheetahclaws import quota as _quota
from cheetahclaws.circuit_breaker import CircuitOpenError as _CircuitOpenError
from cheetahclaws import runtime
from cheetahclaws import hooks as _hooks

# ── Re-export event types (used by cheetahclaws.py) ────────────────────────
__all__ = [
    "AgentState", "run",
    "TextChunk", "ThinkingChunk",
    "ToolStart", "ToolEnd", "TurnDone", "PermissionRequest",
]


@dataclass
class AgentState:
    """Mutable session state. messages use the neutral provider-independent format."""
    messages: list = field(default_factory=list)
    total_input_tokens:  int = 0
    total_output_tokens: int = 0
    total_cache_read_tokens:  int = 0
    total_cache_write_tokens: int = 0
    turn_count: int = 0
    # Why the most recent run() returned: "completed", "max_turns",
    # "loop_guard", "api_error", "quota", "cancelled", "interrupted",
    # "hook_blocked" (UserPromptSubmit) or "hook_stopped" (continue=false).
    # Empty while a run is in progress.
    exit_reason: str = ""


@dataclass
class ToolStart:
    name:   str
    inputs: dict
    id:     str = ""          # provider tool_call id (pairs with ToolEnd.id)

@dataclass
class ToolEnd:
    name:      str
    result:    str
    permitted: bool = True
    id:        str = ""
    is_error:  bool = False

@dataclass
class TurnDone:
    input_tokens:  int
    output_tokens: int

@dataclass
class PermissionRequest:
    description: str
    granted: bool = False
    # Coarse key for a session-scoped "don't ask again" grant, e.g.
    # "Bash:git push" or "Edit:/repo/src/app.py". Empty when the front end
    # should offer approve/reject only. See agent._permission_signature.
    signature: str = ""
    # Structured view of the call, for front ends that decide by policy
    # instead of asking a human (headless mode's --allowed-tools).
    tool_name:  str = ""
    tool_input: dict | None = None
    tool_id:    str = ""
    # Set by the front end alongside granted=False to explain the denial to
    # the model (e.g. "non-interactive session"); default text otherwise.
    deny_reason: str = ""
    # Who decided ("user", "headless", "allowed_tools" …) — for the event log.
    decided_by: str = ""

@dataclass
class QuotaPause:
    """Yielded when a configured budget is reached, instead of making a billable
    call. The REPL auto-saves the session and tells the user how to resume or
    raise the budget. ``usage`` is the snapshot from quota.get_usage(); the
    key/scope/unit/limit identify which cap broke so the hint targets it."""
    reason: str
    usage: dict = field(default_factory=dict)
    key: str | None = None
    scope: str | None = None
    unit: str | None = None
    limit: float | None = None


# ── Agent loop ─────────────────────────────────────────────────────────────

def run(
    user_message: str,
    state: AgentState,
    config: dict,
    system_prompt: str,
    depth: int = 0,
    cancel_check=None,
) -> Generator:
    """
    Multi-turn agent loop (generator).
    Yields: TextChunk | ThinkingChunk | ToolStart | ToolEnd |
            PermissionRequest | TurnDone

    Args:
        depth: sub-agent nesting depth, 0 for top-level
        cancel_check: callable returning True to abort the loop early

    Config keys honored here (all optional):
        max_turns: cap on model calls in this run() (top level only);
            exceeding it ends the loop with state.exit_reason="max_turns".
        _event_emitter: an event_log.EventEmitter; structured events
            (tool_call, tool_result, permission_decision, usage …) are sent
            to it.  Absent → no events, zero overhead.
    """
    state.exit_reason = ""
    _session_key = config.get("_session_id", "default")

    # ── UserPromptSubmit hooks (top level only) ───────────────────────────
    # A hook may block the prompt outright or attach extra context to it.
    if depth == 0 and isinstance(user_message, str):
        _extra_ctx = _hooks.pop_session_context(_session_key)
        if _hooks.has_hooks("UserPromptSubmit"):
            _hr = _hooks.run_hooks("UserPromptSubmit", {"prompt": user_message},
                                   config=config)
            if _hr.blocked:
                _why = _hr.reason or "blocked by a UserPromptSubmit hook"
                _emit(config, "notice", text=f"prompt blocked: {_why}")
                yield TextChunk(f"\n[Prompt blocked by hook: {_why}]\n")
                state.exit_reason = "hook_blocked"
                return
            if _hr.halt:
                yield TextChunk(f"\n[Stopped by hook: {_hr.stop_reason}]\n")
                state.exit_reason = "hook_stopped"
                return
            if _hr.additional_context:
                _extra_ctx = (_extra_ctx + "\n" + _hr.additional_context).strip()
        _emit(config, "user_message", text=user_message)
        if _extra_ctx:
            user_message = (f"{user_message}\n\n<hook-context>\n{_extra_ctx}\n"
                            f"</hook-context>")

    # Append user turn in neutral format
    user_msg = {"role": "user", "content": user_message}
    # Attach pending image from /image command if present
    sctx = runtime.get_ctx(config)
    pending_img = sctx.pending_image
    sctx.pending_image = None
    if pending_img:
        user_msg["images"] = [pending_img]
    state.messages.append(user_msg)

    # Inject runtime metadata into config so tools (e.g. Agent) can access it
    config = {**config, "_depth": depth, "_system_prompt": system_prompt}
    session_id = config.get("_session_id", "default")

    # Wire up structured logging from config (idempotent, cheap)
    _log.configure_from_config(config)

    # Loop guard: defends against models that retry failing tool calls
    # indefinitely (e.g. Gemma 4 31B looping on WebSearch+Bash whose
    # args got eaten by the native tool-call parser). Two thresholds:
    #   - same (name+args) repeated → break after `_LOOP_REPEAT_LIMIT`
    #   - any tool returning Error/Denied N consecutive times → break
    #     after `_LOOP_ERROR_LIMIT`, even across different tool names
    _loop_last_call_sig: tuple | None = None
    _loop_repeat_count = 0
    _loop_consecutive_errors = 0
    _LOOP_REPEAT_LIMIT = 3
    _LOOP_ERROR_LIMIT  = 5

    # Auto-nudge: weaker models (qwen2.5, kimi, smaller llamas, …) often
    # reply with prose like "please give me the file name" when handed an
    # absolute path that they could have explored themselves. We give them
    # exactly one transparent "try again with tools" reminder when this
    # happens. Bounded to one shot per user message to prevent any loop.
    _nudges_remaining = 1 if _looks_like_investigation(user_message) else 0

    # Read-only dedup: when the model fires the same Read/Glob/Grep/WebFetch/
    # WebSearch call with identical args twice in this run(), short-circuit
    # the second one. We still append a synthetic tool_result to history
    # (the OpenAI/Anthropic format requires tool_calls ↔ tool_response
    # pairing) but the result is a brief reminder telling the model the
    # content is already in its context — and we suppress the UI yields
    # so the user doesn't see `⚙ Read(…)` printed twice for the same file.
    # Catches the qwen2.5 pattern where the same file gets Read in two
    # consecutive turns, then the master plan gets echoed as text twice.
    _readonly_sigs_seen: set[str] = set()
    _READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}

    # Turn cap (None = unlimited, the historical behaviour).  Sub-agents run
    # their own loops with their own budgets, so the cap is top-level only.
    _max_turns = _parse_max_turns(config.get("max_turns")) if depth == 0 else None
    _turns_this_run = 0

    # Stop hooks may force the agent to keep going; bounded so a hook that
    # always says "continue" can't spin forever.
    _stop_continues = 0
    _stop_continue_limit = _parse_max_turns(
        config.get("stop_hook_max_continues")) or _STOP_HOOK_MAX_CONTINUES

    while True:
        if cancel_check and cancel_check():
            state.exit_reason = "cancelled"
            return
        if _max_turns is not None and _turns_this_run >= _max_turns:
            state.exit_reason = "max_turns"
            _emit(config, "notice", text=f"reached max_turns={_max_turns}")
            yield TextChunk(f"\n[Stopped: reached max_turns={_max_turns}]\n")
            break
        _turns_this_run += 1
        state.turn_count += 1
        assistant_turn: AssistantTurn | None = None

        # Compact context if approaching window limit
        try:
            if _hooks.has_hooks("PreCompact") and _needs_compaction(state, config):
                _hooks.run_hooks("PreCompact", {"trigger": "auto"},
                                 match_value="auto", config=config)
            if maybe_compact(state, config):
                _emit(config, "compaction", trigger="auto")
        except Exception as _compact_err:
            _log.warn("compact_failed", error=str(_compact_err))

        # Enforce tool_calls ↔ tool-response pairing before every API call.
        # Defends against compaction artifacts, crashed tool execs, or any
        # other source of orphan 'tool' messages that OpenAI-compatible
        # providers (DeepSeek et al.) reject with a 400.
        _before_len = len(state.messages)
        state.messages = sanitize_history(state.messages)
        if len(state.messages) != _before_len:
            _log.warn("history_sanitized",
                      session_id=session_id,
                      removed=_before_len - len(state.messages))

        # Derive the model-visible and executable surface from the same source
        # for this turn.  This prevents a provider from seeing a schema that
        # dispatch would reject (or vice versa), and avoids sending optional
        # integration schemas on every coding request.
        try:
            active_profile = normalize_tool_profile(config.get("tool_profile"))
        except ValueError as profile_error:
            # Fall back to the full surface rather than silently hiding tools
            # because of a typo'd profile name.
            active_profile = "full"
            _log.warn("invalid_tool_profile",
                      session_id=session_id,
                      requested=config.get("tool_profile"),
                      fallback=active_profile,
                      error=str(profile_error))
        disabled_tools = config.get("disabled_tools") or ()
        if not isinstance(disabled_tools, (list, tuple, set, frozenset)):
            disabled_tools = ()
        active_tool_schemas = get_tool_schemas(active_profile, disabled_tools)
        active_tool_names = get_active_tool_names(active_profile, disabled_tools)
        config = {
            **config,
            "tool_profile": active_profile,
            "_active_tool_names": active_tool_names,
        }

        # ── Quota check — before spending tokens ──────────────────────────
        # Project this request's INPUT so a single large (tool-heavy) call can't
        # blow past the cap, then clamp the OUTPUT cap to the remaining headroom
        # so the response can't either — keeping the overshoot near zero.
        _proj_tokens, _proj_cost = 0, 0.0
        _call_config = config
        if any(config.get(k) for k in ("session_token_budget", "session_cost_budget",
                                       "daily_token_budget", "daily_cost_budget")):
            try:
                from cheetahclaws.compaction import estimate_tokens as _est_tok
                from cheetahclaws.providers import calc_cost as _calc_cost
                _proj_tokens = (_est_tok(state.messages)
                                + _est_tok([{"role": "system", "content": system_prompt}]))
                _proj_cost = _calc_cost(config["model"], _proj_tokens, 0)
                # Prompt caching bills cache-writes at 1.25x the input rate,
                # and a full-miss request writes its entire prefix. Reserve
                # that worst case up front so a permitted call can't overshoot
                # the cost budget (token projection needs no bump — the
                # estimate already covers the whole prompt, which the API
                # merely splits into input/cache_read/cache_write).
                # is_prompt_cache_active mirrors what stream_anthropic will
                # really send: once a proxy rejection disables the endpoint,
                # requests go out raw and the premium must not be reserved.
                from cheetahclaws.providers import is_prompt_cache_active as _pc_active
                if (_pc_active(config)
                        and detect_provider(config.get("model", "")) == "anthropic"):
                    _proj_cost *= 1.25
            except Exception:
                _proj_tokens, _proj_cost = 0, 0.0
        try:
            _quota.check_quota(session_id, config,
                               projected_tokens=_proj_tokens, projected_cost=_proj_cost)
        except _quota.QuotaExceeded as qe:
            _log.warn("quota_exceeded", session_id=session_id, reason=qe.reason)
            _emit(config, "notice", text=f"budget reached: {qe.reason}")
            state.exit_reason = "quota"
            yield QuotaPause(qe.reason, _quota.get_usage(session_id),
                             key=qe.key, scope=qe.scope, unit=qe.unit, limit=qe.limit)
            break
        _room = _quota.output_room(session_id, config, _proj_tokens, _proj_cost)
        if _room is not None:
            _cur_cap = config.get("max_tokens") or 4096
            if _room < _cur_cap:
                _call_config = {**config, "max_tokens": max(256, int(_room))}

        # NIM-only: when build.nvidia.com rate-limits a model, cycle to
        # the next free-tier model before consuming a regular retry. Capped
        # at _NIM_FALLBACK_LIMIT total swaps per turn so a fully-throttled
        # tier can't cause a busy loop.
        _nim_fallbacks_used = 0
        _NIM_FALLBACK_LIMIT = 3

        # Bounded to ONE per turn so a genuine overflow (prompt itself
        # too big) eventually surfaces instead of looping. See
        # `_try_reduce_output_cap_from_error` for the parser.
        _output_cap_reduced_this_turn = False

        # Stream from provider — retry on ANY error (never crash the session)
        max_retries = 3
        for attempt in range(max_retries + 1):
            try:
                for event in stream(
                    model=config["model"],
                    system=system_prompt,
                    messages=state.messages,
                    tool_schemas=active_tool_schemas,
                    config=_call_config,
                ):
                    if isinstance(event, (TextChunk, ThinkingChunk)):
                        if depth == 0 and isinstance(event, TextChunk):
                            _emit(config, "assistant_delta", text=event.text)
                        yield event
                    elif isinstance(event, AssistantTurn):
                        assistant_turn = event
                        # Record usage for quota tracking
                        _quota.record_usage(
                            session_id, config["model"],
                            event.in_tokens, event.out_tokens,
                            cache_read_tokens=getattr(event, "cache_read_tokens", 0),
                            cache_write_tokens=getattr(event, "cache_write_tokens", 0),
                        )
                break  # success — exit retry loop

            except _CircuitOpenError as e:
                _log.warn("circuit_open_skip", session_id=session_id,
                          error=str(e)[:200])
                _emit(config, "error", message=str(e)[:500], category="circuit_open")
                state.exit_reason = "api_error"
                yield TextChunk(f"\n[{e}]\n")
                return  # circuit manages its own cooldown — don't retry

            except Exception as e:
                from cheetahclaws.error_classifier import classify as _classify_err, ErrorCategory as _ErrCat
                cerr = _classify_err(e)

                # NIM 429 cascade: swap to the next free-tier model before
                # spending a retry slot. Doesn't increment `attempt` so a
                # transient global throttle still gets the regular backoff
                # path after _NIM_FALLBACK_LIMIT swaps.
                if (cerr.category == _ErrCat.RATE_LIMIT
                        and detect_provider(config.get("model", "")) == "nim"
                        and config.get("nim_auto_fallback", True)
                        and _nim_fallbacks_used < _NIM_FALLBACK_LIMIT):
                    _old = config["model"]
                    _new = nim_next_model(_old)
                    if _new and _new != _old:
                        config = {**config, "model": _new}
                        _nim_fallbacks_used += 1
                        _log.warn("nim_fallback",
                                   session_id=session_id,
                                   from_model=_old, to_model=_new,
                                   used=_nim_fallbacks_used,
                                   limit=_NIM_FALLBACK_LIMIT)
                        yield TextChunk(
                            f"\n[NIM rate-limited on {_old} — switching to "
                            f"{_new} ({_nim_fallbacks_used}/"
                            f"{_NIM_FALLBACK_LIMIT})]\n"
                        )
                        continue   # retry without consuming attempt budget

                if attempt >= max_retries or not cerr.retryable:
                    _log.error("api_failed", session_id=session_id,
                               error_type=type(e).__name__,
                               category=cerr.category.value,
                               error=_truncate_err(str(e)))
                    hint = f" Hint: {cerr.hint}" if cerr.hint else ""
                    _emit(config, "error",
                          message=f"{type(e).__name__}: {_truncate_err(str(e), 500)}",
                          category=cerr.category.value, hint=cerr.hint or "")
                    yield TextChunk(f"\n[Failed — {type(e).__name__}: {_truncate_err(str(e))}.{hint}]\n")
                    break

                if cerr.should_compress:
                    # Before compacting, try to PARSE the error message
                    # for explicit token counts. Many providers return:
                    #   "max context 32768. requested 8192 output tokens
                    #    and your prompt contains 24577 input tokens..."
                    # When the prompt itself fits but `requested_output`
                    # pushes total over the limit, we can fix this by
                    # lowering max_tokens — no compaction needed (it
                    # wouldn't help anyway when the user's input is the
                    # huge thing, e.g. a PDF read).
                    # Bounded to ONE auto-reduction per turn so a true
                    # overflow eventually surfaces.
                    if not _output_cap_reduced_this_turn:
                        new_cap = _try_reduce_output_cap_from_error(str(e), config)
                        if new_cap and new_cap >= 256:
                            _output_cap_reduced_this_turn = True
                            old_cap = config.get("max_tokens")
                            config = {**config, "max_tokens": new_cap}
                            _log.info("output_cap_auto_reduced",
                                       session_id=session_id,
                                       from_cap=old_cap, to_cap=new_cap)
                            yield TextChunk(
                                f"\n[Context overflow — reducing output cap "
                                f"{old_cap}→{new_cap} and retrying (attempt "
                                f"{attempt+1}/{max_retries})]\n"
                            )
                            continue
                    if _hooks.has_hooks("PreCompact"):
                        _hooks.run_hooks("PreCompact", {"trigger": "auto"},
                                         match_value="auto", config=config)
                    _force_compact(state, config)
                    _emit(config, "compaction", trigger="overflow")
                    yield TextChunk(f"\n[Context too long — compacted and retrying (attempt {attempt+1}/{max_retries})]\n")
                    continue

                backoff = int(2 ** (attempt + 1) * cerr.backoff_multiplier)
                backoff = min(backoff, 30)
                _log.warn("api_retry", session_id=session_id,
                          attempt=attempt + 1, max_retries=max_retries,
                          category=cerr.category.value,
                          error_type=type(e).__name__,
                          error=_truncate_err(str(e)),
                          backoff_s=backoff)
                yield TextChunk(f"\n[Retry {attempt+1}/{max_retries} after {backoff}s — {cerr.category.value}: {_truncate_err(str(e))}]\n")
                time.sleep(backoff)

        if assistant_turn is None:
            state.exit_reason = "api_error"
            break

        # Record assistant turn in neutral format
        _assistant_msg = {
            "role":       "assistant",
            "content":    assistant_turn.text,
            "tool_calls": assistant_turn.tool_calls,
        }
        # DeepSeek v4 requires reasoning_content to be echoed back on
        # subsequent requests when the turn contains tool_calls.  Storing it
        # on the neutral history lets messages_to_openai pass it through.
        _rc = getattr(assistant_turn, "reasoning_content", "")
        if _rc and assistant_turn.tool_calls:
            _assistant_msg["reasoning_content"] = _rc
        state.messages.append(_assistant_msg)

        state.total_input_tokens  += assistant_turn.in_tokens
        state.total_output_tokens += assistant_turn.out_tokens
        state.total_cache_read_tokens  += getattr(assistant_turn, 'cache_read_tokens', 0)
        state.total_cache_write_tokens += getattr(assistant_turn, 'cache_write_tokens', 0)
        # Real prompt size from the provider beats the chars/token estimate
        # for the next compaction decision.
        try:
            from cheetahclaws.compaction import record_usage as _record_usage
            _record_usage(state, assistant_turn.in_tokens, assistant_turn.out_tokens,
                          cache_read_tokens=getattr(assistant_turn, 'cache_read_tokens', 0),
                          cache_write_tokens=getattr(assistant_turn, 'cache_write_tokens', 0))
        except Exception:
            pass
        _emit_d(config, depth, "assistant_message",
                text=assistant_turn.text or "",
                tool_calls=[{"id": tc.get("id", ""), "name": tc.get("name", "")}
                            for tc in (assistant_turn.tool_calls or [])],
                model=config.get("model", ""))
        _emit_d(config, depth, "usage",
                input_tokens=assistant_turn.in_tokens,
                output_tokens=assistant_turn.out_tokens,
                cache_read_tokens=getattr(assistant_turn, 'cache_read_tokens', 0),
                cache_write_tokens=getattr(assistant_turn, 'cache_write_tokens', 0),
                model=config.get("model", ""))
        yield TurnDone(assistant_turn.in_tokens, assistant_turn.out_tokens)

        if not assistant_turn.tool_calls:
            # Auto-nudge: text-only reply when the user clearly wanted
            # investigation (their message contained an absolute path).
            # One shot only — see `_nudges_remaining` init above.
            if _nudges_remaining > 0 and active_tool_schemas:
                _nudges_remaining -= 1
                _nudge_msg = (
                    "[system reminder] You replied with text and no tool "
                    "calls, but the user's request includes a concrete path "
                    "or file reference. Do NOT ask the user to clarify what "
                    "they already provided. Instead: list the path with Bash "
                    "`ls` (or Glob `**/*` for recursive), Read the relevant "
                    "files, then answer. Try again now."
                )
                state.messages.append({"role": "user", "content": _nudge_msg})
                _log.info("auto_nudge_text_only",
                           session_id=session_id,
                           reason="user_provided_path_but_assistant_text_only")
                continue   # retry the loop with the nudge in history
            # Stop hooks: a hook may refuse to let the agent stop yet
            # ("decision": "block" / exit 2) and say why; that reason goes
            # back to the model as a user turn.  Bounded per run().
            if depth == 0 and _hooks.has_hooks("Stop"):
                _hr = _hooks.run_hooks(
                    "Stop",
                    {"stop_hook_active": _stop_continues > 0,
                     "last_assistant_message": assistant_turn.text or ""},
                    config=config)
                if _hr.halt:
                    state.exit_reason = "hook_stopped"
                    break
                if _hr.blocked:
                    if _stop_continues < _stop_continue_limit:
                        _stop_continues += 1
                        _why = _hr.reason or "A Stop hook asked you to keep working."
                        state.messages.append({
                            "role": "user",
                            "content": f"[Stop hook] {_why}",
                        })
                        yield TextChunk(f"\n[Stop hook: continuing — {_why}]\n")
                        continue
                    _log.warn("stop_hook_continue_limit",
                              session_id=session_id, limit=_stop_continue_limit)
            state.exit_reason = "completed"
            break   # No tools → conversation turn complete

        # ── Execute tools (parallel when safe) ────────────────────────────
        tool_calls = assistant_turn.tool_calls

        # Loop guard: same tool_calls signature repeated N times → break.
        # The model is stuck retrying without progress (typically because
        # a tool result it can't parse came back, or its tool-call arg
        # parser keeps emitting the same malformed payload).
        import hashlib as _h_loop
        import json as _j_loop
        _sig = tuple(
            (tc.get("name", ""),
             _h_loop.md5(
                 _j_loop.dumps(tc.get("input", {}) or {},
                                sort_keys=True, default=str).encode(
                     "utf-8", "ignore"),
             ).hexdigest())
            for tc in tool_calls
        )
        if _sig == _loop_last_call_sig:
            _loop_repeat_count += 1
        else:
            _loop_last_call_sig = _sig
            _loop_repeat_count = 1
        if _loop_repeat_count >= _LOOP_REPEAT_LIMIT:
            _names = ", ".join(sorted({tc.get("name", "?")
                                         for tc in tool_calls}))
            _loop_msg = (
                f"\n[Loop guard] Same tool call repeated "
                f"{_LOOP_REPEAT_LIMIT} times — stopping to prevent a "
                f"runaway loop. The model kept calling {_names} with "
                f"identical args without making progress. Try /clear "
                f"and rephrase your request, or switch to a more "
                f"capable model.\n"
            )
            _log.warn("loop_guard_triggered",
                       session_id=session_id,
                       tools=_names,
                       repeats=_loop_repeat_count)
            yield TextChunk(_loop_msg)
            state.messages.append({
                "role": "assistant", "content": _loop_msg.strip(),
            })
            state.exit_reason = "loop_guard"
            break

        # Read-only dedup: walk the batch first, mark any read-only call
        # whose (name, args) signature already fired in this run() as a
        # short-circuit. The actual execution + UI yields will skip these,
        # but a synthetic tool_result still gets appended to history so the
        # OpenAI/Anthropic tool_calls ↔ tool_response pairing stays valid.
        _redundant_tcs: dict[str, str] = {}   # tool_call id → reminder text
        for tc in tool_calls:
            if tc.get("name") not in _READ_ONLY_TOOLS:
                continue
            try:
                _args_blob = _j_loop.dumps(tc.get("input", {}) or {},
                                            sort_keys=True, default=str)
            except Exception:
                continue
            _ro_sig = f"{tc['name']}:{_h_loop.md5(_args_blob.encode('utf-8','ignore')).hexdigest()}"
            if _ro_sig in _readonly_sigs_seen:
                _arg_summary = _args_blob[:120]
                _redundant_tcs[tc["id"]] = (
                    f"[deduped] You already called {tc['name']} with these "
                    f"args earlier in this turn ({_arg_summary}). The result "
                    f"is identical to your previous tool result — do not "
                    f"re-call read-only tools, use the content already in "
                    f"your context."
                )
                _log.info("readonly_dedup",
                           session_id=session_id,
                           tool=tc["name"],
                           sig=_ro_sig)
            else:
                _readonly_sigs_seen.add(_ro_sig)

        for tc in tool_calls:
            _emit_d(config, depth, "tool_call", id=tc.get("id", ""),
                    name=tc.get("name", ""), input=tc.get("input", {}))

        # Check permissions first (must be sequential — may prompt user).
        # PreToolUse hooks run first: they may rewrite the input, allow
        # (skip the prompt), deny (with a reason fed to the model), or force
        # a prompt ("ask").
        permissions: dict[str, bool] = {}
        _deny_reasons: dict[str, str] = {}
        _hook_halt_reason = ""
        _pre_hooks_on = _hooks.has_hooks("PreToolUse")
        _plan_mode = config.get("permission_mode") == "plan"
        for tc in tool_calls:
            if tc["name"] not in active_tool_names:
                # Treat a stale/malicious call as an execution error, not a
                # permission question.  The model never received this schema
                # on this turn, so prompting a user for it would be misleading.
                permissions[tc["id"]] = True
                continue
            _hook_decision = None
            if _pre_hooks_on and tc["id"] not in _redundant_tcs:
                _hr = _hooks.run_hooks(
                    "PreToolUse",
                    {"tool_name": tc["name"], "tool_input": tc.get("input") or {},
                     "tool_use_id": tc["id"]},
                    match_value=tc["name"], config=config)
                if isinstance(_hr.updated_input, dict):
                    tc["input"] = _hr.updated_input
                if _hr.halt and not _hook_halt_reason:
                    _hook_halt_reason = _hr.stop_reason or "stopped by hook"
                _hook_decision = _hr.decision
                if _hook_decision == "deny":
                    permissions[tc["id"]] = False
                    _deny_reasons[tc["id"]] = (
                        "Denied by PreToolUse hook: "
                        + (_hr.reason or "operation blocked by policy"))
                    _emit_d(config, depth, "permission_decision", id=tc["id"],
                            name=tc["name"], decision="deny", source="hook",
                            reason=_hr.reason)
                    continue
                if _hook_decision == "allow" and not _plan_mode:
                    permissions[tc["id"]] = True
                    _emit_d(config, depth, "permission_decision", id=tc["id"],
                            name=tc["name"], decision="allow", source="hook",
                            reason=_hr.reason)
                    continue
            permitted = (False if _hook_decision == "ask"
                         else _check_permission(tc, config))
            if not permitted:
                if _plan_mode and _hook_decision != "ask":
                    permitted = False
                    _emit_d(config, depth, "permission_decision", id=tc["id"],
                            name=tc["name"], decision="deny", source="plan_mode")
                else:
                    req = PermissionRequest(
                        description=_permission_desc(tc),
                        signature=_permission_signature(tc),
                        tool_name=tc["name"],
                        tool_input=tc.get("input") or {},
                        tool_id=tc["id"],
                    )
                    _hooks.fire_and_forget(
                        "Notification",
                        {"message": f"CheetahClaws needs your permission to use "
                                    f"{tc['name']}: {req.description[:200]}",
                         "notification_type": "permission_prompt"},
                        config=config)
                    yield req
                    permitted = req.granted
                    if not permitted and req.deny_reason:
                        _deny_reasons[tc["id"]] = req.deny_reason
                    _emit_d(config, depth, "permission_decision", id=tc["id"],
                            name=tc["name"],
                            decision="allow" if permitted else "deny",
                            source=req.decided_by or "user",
                            reason=req.deny_reason if not permitted else "")
            permissions[tc["id"]] = permitted

        # Determine which tools can run in parallel — but treat redundant
        # read-only calls as "sequential" (and short-circuit during exec)
        # so the dedup path always lands on a single, predictable code path.
        from cheetahclaws.tool_registry import get_tool as _get_tool
        parallel_batch = []
        sequential_batch = []
        for tc in tool_calls:
            if not permissions[tc["id"]] or tc["id"] in _redundant_tcs:
                sequential_batch.append(tc)
                continue
            tdef = _get_tool(tc["name"])
            if tdef and tdef.concurrent_safe and len(tool_calls) > 1:
                parallel_batch.append(tc)
            else:
                sequential_batch.append(tc)

        def _exec_one(tc):
            """Execute a single tool call, return (tc, result, permitted)."""
            tid = tc["id"]
            if tc["name"] not in active_tool_names:
                return (
                    tc,
                    f"Error: tool '{tc['name']}' is not enabled by the "
                    f"{active_profile!r} tool profile for this turn.",
                    True,
                )
            # Read-only dedup short-circuit: skip the actual execute_tool
            # call, return the synthetic reminder as the tool result. Marked
            # `permitted=True` so downstream loop-error counters don't treat
            # it as a denial.
            if tid in _redundant_tcs:
                return tc, _redundant_tcs[tid], True
            permitted = permissions[tid]
            if not permitted:
                if tid in _deny_reasons:
                    result = _deny_reasons[tid]
                elif config.get("permission_mode") == "plan":
                    plan_file = runtime.get_ctx(config).plan_file or ""
                    result = (
                        f"[Plan mode] Write operations are blocked except to the plan file: {plan_file}\n"
                        "Finish your analysis and write the plan to the plan file. "
                        "The user will run /plan done to exit plan mode and begin implementation."
                    )
                else:
                    result = "Denied: user rejected this operation"
            else:
                result = execute_tool(
                    tc["name"], tc["input"],
                    permission_mode="accept-all",
                    config=config,
                )
            return tc, result, permitted

        # Results are collected by id and emitted/appended in the model's
        # original call order below, whichever batch produced them.
        results_by_id: dict[str, tuple] = {}

        try:
            # Run parallel batch concurrently
            if parallel_batch:
                from concurrent.futures import ThreadPoolExecutor
                for tc in parallel_batch:
                    yield ToolStart(tc["name"], tc["input"], id=tc["id"])
                pool = ThreadPoolExecutor(max_workers=min(len(parallel_batch), 8))
                futures = [(tc, pool.submit(_exec_one, tc)) for tc in parallel_batch]
                try:
                    for tc, future in futures:
                        _tc, result, permitted = future.result()
                        _log.debug("tool_end", session_id=session_id,
                                   tool=tc["name"], permitted=permitted,
                                   result_len=len(result))
                        results_by_id[tc["id"]] = (tc, result, permitted)
                except BaseException:
                    # Ctrl-C (or anything else): don't wait for the remaining
                    # threads — cancel what hasn't started, keep what finished.
                    pool.shutdown(wait=False, cancel_futures=True)
                    for tc, future in futures:
                        if (tc["id"] not in results_by_id and future.done()
                                and not future.cancelled()
                                and future.exception() is None):
                            results_by_id[tc["id"]] = future.result()
                    raise
                pool.shutdown(wait=True)

            # Run sequential batch one by one
            for tc in sequential_batch:
                if tc["id"] not in _redundant_tcs:
                    yield ToolStart(tc["name"], tc["input"], id=tc["id"])
                    _log.debug("tool_start", session_id=session_id,
                               tool=tc["name"], input_keys=list(tc["input"].keys()))
                else:
                    # Tell the user *something* happened, but tersely — don't
                    # repeat the full ⚙ Read(<long path>) line.
                    yield TextChunk(f"\n[deduped {tc['name']}: already in context]\n")
                tc, result, permitted = _exec_one(tc)
                _log.debug("tool_end", session_id=session_id,
                           tool=tc["name"], permitted=permitted,
                           result_len=len(result))
                results_by_id[tc["id"]] = (tc, result, permitted)
        except KeyboardInterrupt:
            # Keep history valid: every tool_call in the assistant message
            # must get a tool_result, so record the finished ones and mark
            # the rest as interrupted before propagating the interrupt.
            for tc in tool_calls:
                if tc["id"] in results_by_id:
                    _tc, result, permitted = results_by_id[tc["id"]]
                    is_err = _result_is_error(result, permitted)
                else:
                    result, is_err = _INTERRUPTED_RESULT, True
                state.messages.append(_tool_message(tc, result, is_err))
                _emit_d(config, depth, "tool_result", id=tc["id"],
                        name=tc["name"], is_error=is_err,
                        output=_event_output(config, result))
            state.exit_reason = "interrupted"
            raise

        results_ordered = [results_by_id[tc["id"]] for tc in tool_calls]
        _post_hooks_on = _hooks.has_hooks("PostToolUse")

        # Yield results and append to state in original order
        _all_errors = bool(results_ordered)
        for tc, result, permitted in results_ordered:
            is_err = _result_is_error(result, permitted)
            # Suppress the visible ToolEnd for deduped calls — the brief
            # `[deduped ...]` line above is enough. The tool_result still
            # gets appended to state.messages so the next API request has
            # a valid tool_calls ↔ tool_response pairing.
            if tc["id"] not in _redundant_tcs:
                yield ToolEnd(tc["name"], result, permitted, id=tc["id"],
                              is_error=is_err)
            # Auto-fanout: when a single tool result is too big to fit in the
            # active model's context window, split it across parallel sub-LLM
            # summaries instead of letting the next API call overflow.  Only
            # fires for permitted, oversize, non-error results — denials and
            # error strings are tiny and would just waste sub-calls.
            if permitted and isinstance(result, str):
                if not is_err:
                    try:
                        from cheetahclaws.multi_agent.fanout import (
                            should_fanout, fanout_summarize, make_llm_caller,
                            fanout_notice,
                        )
                        from cheetahclaws.compaction import get_context_limit
                        _ctx = get_context_limit(config.get("model", ""), config)
                        if should_fanout(tc["name"], result, _ctx, config):
                            # Find last user message for query focus
                            _user_q = ""
                            for _m in reversed(state.messages):
                                if _m.get("role") == "user":
                                    _c = _m.get("content", "")
                                    if isinstance(_c, str):
                                        _user_q = _c
                                    break
                            _max_sub = int(config.get("auto_fanout_max_subagents", 5) or 5)
                            yield TextChunk(
                                "\n" + fanout_notice(tc["name"], len(result),
                                                     _max_sub, _ctx) + "\n"
                            )
                            _log.info("auto_fanout_triggered",
                                       session_id=session_id,
                                       tool=tc["name"],
                                       original_chars=len(result),
                                       ctx_window=_ctx,
                                       max_subagents=_max_sub)
                            result = fanout_summarize(
                                text=result, user_question=_user_q,
                                config=config, llm_call=make_llm_caller(config),
                                ctx_window=_ctx, max_subagents=_max_sub,
                            )
                    except Exception as _fanout_err:
                        # Fanout is opportunistic — never block the tool result
                        # path on a fanout failure.  Log + fall through with
                        # the original result; downstream compaction / dynamic
                        # cap can still try.
                        _log.warn("auto_fanout_failed",
                                   session_id=session_id,
                                   tool=tc["name"],
                                   error_type=type(_fanout_err).__name__,
                                   error=_truncate_err(str(_fanout_err)))
            # PostToolUse hooks: may append feedback the model sees with the
            # result (e.g. lint output after an Edit), or halt the run.
            if (_post_hooks_on and permitted and tc["id"] not in _redundant_tcs
                    and tc["name"] in active_tool_names):
                _hr = _hooks.run_hooks(
                    "PostToolUse",
                    {"tool_name": tc["name"], "tool_input": tc.get("input") or {},
                     "tool_use_id": tc["id"], "tool_response": result,
                     "is_error": is_err},
                    match_value=tc["name"], config=config)
                _fb = _hr.additional_context or (_hr.reason if _hr.blocked else "")
                if _fb and isinstance(result, str):
                    result = f"{result}\n\n[PostToolUse hook feedback]\n{_fb}"
                if _hr.halt and not _hook_halt_reason:
                    _hook_halt_reason = _hr.stop_reason or "stopped by hook"
            state.messages.append(_tool_message(tc, result, is_err))
            _emit_d(config, depth, "tool_result", id=tc["id"], name=tc["name"],
                    is_error=is_err, output=_event_output(config, result))
            # Loop guard: track whether this batch was all errors.
            res_str = result if isinstance(result, str) else str(result)
            res_low = res_str.lstrip()[:24].lower()
            # (String-based on purpose: a plan-mode block is is_error for the
            # model but must not trip the runaway-loop guard.)
            if not (res_low.startswith("error")
                    or res_low.startswith("denied")
                    or "keyerror" in res_low):
                _all_errors = False

        if _hook_halt_reason:
            _emit(config, "notice", text=f"stopped by hook: {_hook_halt_reason}")
            yield TextChunk(f"\n[Stopped by hook: {_hook_halt_reason}]\n")
            state.exit_reason = "hook_stopped"
            break

        # Loop guard: cross-tool consecutive-error counter — break if
        # the model keeps invoking tools that all fail (e.g. cycling
        # between empty-args WebSearch and empty-args Bash).
        if _all_errors:
            _loop_consecutive_errors += len(results_ordered)
        else:
            _loop_consecutive_errors = 0
        if _loop_consecutive_errors >= _LOOP_ERROR_LIMIT:
            _err_msg = (
                f"\n[Loop guard] {_loop_consecutive_errors} consecutive "
                f"tool calls returned errors — stopping to prevent a "
                f"runaway loop. Likely cause: the model is emitting "
                f"tool calls without valid args (Gemma 4 + vLLM "
                f"hermes parser is a known offender). Try /clear and "
                f"rephrase, or switch to a model with native "
                f"function-calling support (claude-*, gpt-*, "
                f"deepseek-*).\n"
            )
            _log.warn("loop_guard_consecutive_errors_triggered",
                       session_id=session_id,
                       count=_loop_consecutive_errors)
            yield TextChunk(_err_msg)
            state.messages.append({
                "role": "assistant", "content": _err_msg.strip(),
            })
            state.exit_reason = "loop_guard"
            break


# ── Helpers ───────────────────────────────────────────────────────────────

_STOP_HOOK_MAX_CONTINUES = 3
_INTERRUPTED_RESULT = "Error: interrupted by user before this tool call completed."


def _emit(config: dict, etype: str, **fields) -> None:
    """Send a structured event to the session's EventEmitter, if any.
    Never raises — observability must not break the loop."""
    em = config.get("_event_emitter")
    if em is None:
        return
    try:
        em.emit(etype, **fields)
    except Exception:
        pass


def _emit_d(config: dict, depth: int, etype: str, **fields) -> None:
    """_emit, tagging events from sub-agent loops with their depth."""
    if config.get("_event_emitter") is None:
        return
    if depth:
        fields["depth"] = depth
    _emit(config, etype, **fields)


def _event_output(config: dict, result) -> str:
    em = config.get("_event_emitter")
    limit = getattr(em, "max_output_chars", 4000)
    s = result if isinstance(result, str) else str(result)
    if limit and len(s) > limit:
        return s[:limit] + f"\n… [truncated {len(s) - limit} chars]"
    return s


def _parse_max_turns(value) -> int | None:
    """Positive int or None (unset / 0 / garbage → unlimited)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _needs_compaction(state: AgentState, config: dict) -> bool:
    """Mirror of maybe_compact's trigger, used only to decide whether to fire
    PreCompact hooks (so hook-less sessions skip the token estimate)."""
    try:
        limit = get_context_limit(config.get("model", ""), config)
        return estimate_tokens(state.messages) > limit * 0.7
    except Exception:
        return False


def _result_is_error(result, permitted: bool) -> bool:
    """Structured error flag for a tool result.

    Denials are errors from the model's point of view.  Otherwise tools
    report failure by convention with an "Error…" / "Denied…" prefix.
    """
    if not permitted:
        return True
    if not isinstance(result, str):
        return False
    head = result.lstrip()[:24].lower()
    return head.startswith("error") or head.startswith("denied")


def _tool_message(tc: dict, result, is_error: bool) -> dict:
    msg = {
        "role":         "tool",
        "tool_call_id": tc["id"],
        "name":         tc["name"],
        "content":      result,
    }
    if is_error:
        msg["is_error"] = True
    return msg


# Tools that mutate only CheetahClaws' own session state — task lists, saved
# memories, loaded skill text, a sleep timer.  They touch nothing in the
# user's repo, reach no network, and are undone by editing the same store, so
# prompting for them is pure friction.  Anything that can reach the user's
# files, the shell, or the outside world stays off this list — notably Agent
# (a sub-agent runs its own tool loop) and MemoryDelete (destroys user data).
_SELF_STATE_TOOLS = frozenset({
    "TaskCreate", "TaskUpdate", "MemorySave", "Skill", "SleepTimer",
    "EnterPlanMode", "ExitPlanMode", "AskUserQuestion",
})


def _tool_is_read_only(name: str) -> bool:
    """True when the registry marks this tool as never mutating state.

    Read from the registry rather than a hardcoded name list so every
    read-only tool — built-in, plugin, or module (Task/Memory/Skill queries,
    document readers, browser reads) — is auto-approved on the same rule, and
    a new one is covered the day it is registered.  Unknown tools (MCP,
    third-party) default to False and still prompt.
    """
    try:
        from cheetahclaws.tool_registry import get_tool
        tdef = get_tool(name)
        return bool(tdef and tdef.read_only)
    except Exception:
        return False


# Files without a leading dot that an interpreter executes on its own the
# next time it starts — creating one is never a formality.
_AUTO_EXECUTED_NAMES = frozenset({"sitecustomize.py", "usercustomize.py"})
_AUTO_EXECUTED_SUFFIXES = (".pth",)


def _creates_new_workspace_file(tc: dict, config: dict) -> bool:
    """True for a Write that creates a *new* file inside the workspace.

    Creating a file destroys nothing: there is no prior content to lose and
    the file is inside the directory the session is already working in, so
    prompting for it is friction without a decision behind it.  Overwriting
    an existing file, or writing anywhere outside the workspace, still asks.

    Excluded regardless: any path with a dot-prefixed component
    (``.git/hooks/pre-commit``, ``.github/workflows/*``, ``.env``,
    ``.mcp.json``, ``.cheetahclaws/``, ``.envrc``) — those are configuration
    and hook locations that get executed or trusted by other tools, which
    makes creating one a decision the user should see.  The same goes for
    files Python runs at startup (``sitecustomize.py``, ``*.pth``), for a
    path that is itself a symlink (even a dangling one), and for a path whose
    symlinked parent leads out of the workspace — the check is made on both
    the path as written and its fully resolved form.
    Disable the whole rule with ``/config auto_create_files=false``.
    """
    if not config.get("auto_create_files", True):
        return False
    path = (tc.get("input") or {}).get("file_path") or ""
    if not path:
        return False
    try:
        from pathlib import Path as _Path
        target = _Path(path).expanduser()
        if not target.is_absolute():
            target = _Path.cwd() / target
        written = _Path(os.path.normpath(str(target)))
        if os.path.lexists(written):
            return False   # existing file, or a symlink planted at the path
        resolved = written.resolve()
        if resolved.exists():
            return False   # overwriting real content → ask
        root_raw = _Path(os.path.normpath(str(_Path(
            config.get("allowed_root")
            or config.get("_worktree_cwd")
            or _Path.cwd()).expanduser().absolute())))
        root = root_raw.resolve()
        rel = resolved.relative_to(root)   # ValueError → outside the workspace
        rels = [rel.parts]
        try:
            rels.append(written.relative_to(root_raw).parts)
        except ValueError:
            pass   # root reached through a symlink; the resolved form decides
    except Exception:
        return False
    if not rel.parts:
        return False
    for parts in rels:
        if any(part.startswith(".") for part in parts):
            return False
    name = rel.parts[-1]
    if name in _AUTO_EXECUTED_NAMES or name.endswith(_AUTO_EXECUTED_SUFFIXES):
        return False
    return True


# Path components an edit must never touch without asking, even in
# accept-edits: files other programs execute or trust (git hooks, CI, shell
# rc files, package-manager config) and cheetahclaws' own settings, where a
# hook entry is a command that runs on the next tool call.
_EDIT_PROTECTED_PARTS = frozenset({
    ".git", ".github", ".gitlab-ci.yml", ".husky", ".cheetahclaws", ".claude",
    ".vscode", ".idea", ".mcp.json", ".envrc", ".env", ".bashrc", ".zshrc",
    ".profile", ".bash_profile", ".zprofile", ".npmrc", ".pypirc",
    ".yarnrc", ".yarnrc.yml", ".cargo", ".ssh", ".config",
})


def _edit_targets(tc: dict) -> list[str]:
    inp = tc.get("input") or {}
    if tc.get("name") == "ApplyPatch":
        from cheetahclaws.tools.patch import patch_paths
        return patch_paths(inp.get("patch") or inp.get("input") or "")
    path = inp.get("file_path") or inp.get("notebook_path") or ""
    return [path] if path else []


def _edit_targets_are_plain_workspace_files(tc: dict, config: dict) -> bool:
    """accept-edits pre-approves edits only to ordinary files inside the
    workspace.  Anything outside it, any protected config/hook location and
    files Python runs at startup still prompt.
    ``accept_edits_outside_workspace: true`` drops the workspace limit."""
    targets = _edit_targets(tc)
    if not targets:
        return False
    try:
        from pathlib import Path as _Path
        root = _Path(config.get("allowed_root") or config.get("_worktree_cwd")
                     or _Path.cwd()).expanduser().resolve()
        for t in targets:
            p = _Path(t).expanduser()
            if not p.is_absolute():
                p = root / p
            resolved = p.resolve()
            parts = set(_Path(os.path.normpath(str(p))).parts) | set(resolved.parts)
            if parts & _EDIT_PROTECTED_PARTS:
                return False
            if resolved.name in _AUTO_EXECUTED_NAMES \
                    or resolved.name.endswith(_AUTO_EXECUTED_SUFFIXES):
                return False
            if not config.get("accept_edits_outside_workspace", False):
                resolved.relative_to(root)   # ValueError → outside
    except Exception:
        return False
    return True


# ── Bash grant signatures ─────────────────────────────────────────────────
#
# A grant ("s"/"!" at a prompt) is keyed on program + subcommand.  A command
# line can chain several programs, so the grant is checked per *segment*: the
# command runs unprompted only when every segment is either read-only (see
# tools/security.py) or itself covered by a grant.  Approving `git status`
# therefore never approves `git status && curl x | sh`.

# Programs whose second word is a subcommand worth keying a grant on.
_SIG_MULTI = frozenset({
    "git", "npm", "pnpm", "yarn", "pip", "pip3", "uv", "cargo", "go",
    "docker", "kubectl", "make", "poetry", "conda", "systemctl", "brew", "gh",
})

# A segment starting with one of these is never covered by a grant: it runs
# code that is not visible as a program name (eval, a sourced file), changes
# privilege, or is shell syntax that does not fit "one program per segment".
_SIG_UNGRANTABLE = frozenset({
    "eval", "exec", "source", ".", "sudo", "doas", "su", "pkexec", "builtin",
    "alias", "trap", "function", "coproc", "if", "then", "else", "elif", "fi",
    "for", "while", "until", "do", "done", "case", "esac", "select",
    "{", "}", "[[", "]]", "!",
})

_SIG_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "mksh", "fish",
                         "busybox"})

# Harmless shell built-ins that may sit between granted segments
# (`cd sub && pytest`).
_SIG_NEUTRAL = frozenset({"cd", "pushd", "popd", "true", "false", ":"})

# `VAR=value` prefixes that change what the next program loads or runs.  A
# segment carrying one is never covered by a grant for that program.
_SIG_DANGEROUS_ENV = frozenset({
    "PATH", "BASH_ENV", "ENV", "IFS", "SHELLOPTS", "BASHOPTS", "PS4",
    "PROMPT_COMMAND", "ZDOTDIR", "HOME", "NODE_OPTIONS", "PAGER", "EDITOR",
    "VISUAL", "LESSOPEN", "LESSCLOSE", "RUBYOPT", "JAVA_TOOL_OPTIONS",
    "_JAVA_OPTIONS", "KUBECONFIG", "DOCKER_CONFIG",
})
_SIG_DANGEROUS_ENV_PREFIXES = ("LD_", "DYLD_", "GIT_", "PYTHON", "PERL5",
                               "PERLLIB", "NPM_CONFIG_", "npm_config_")

# Directories whose binaries are "the" program of that name: `/usr/bin/git`
# keys like `git`, but `./git` or `/tmp/x/git` key on their literal path.
_SIG_SYSTEM_BIN_DIRS = frozenset({
    "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin",
    "/usr/local/sbin", "/opt/homebrew/bin",
})

# Wrappers that run the program named after their own options:
# wrapper → (flags that take a separate value, positionals to skip).
_SIG_WRAPPERS = {
    "timeout": ({"-s", "--signal", "-k", "--kill-after"}, 1),
    "nice":    ({"-n", "--adjustment"}, 0),
    "nohup":   (set(), 0),
    "time":    ({"-f", "--format", "-o", "--output"}, 0),
    "stdbuf":  ({"-i", "-o", "-e", "--input", "--output", "--error"}, 0),
    "xargs":   ({"-I", "-n", "-P", "-L", "-s", "-d", "-E", "-a", "--max-args",
                 "--max-procs", "--max-lines", "--max-chars", "--delimiter",
                 "--eof", "--arg-file", "--replace"}, 0),
    "env":     (set(), 0),
}


def _sig_env_is_dangerous(assignment: str) -> bool:
    name = assignment.split("=", 1)[0]
    return (name in _SIG_DANGEROUS_ENV
            or name.startswith(_SIG_DANGEROUS_ENV_PREFIXES))


def _is_assignment(tok: str) -> bool:
    name = tok.split("=", 1)[0]
    return ("=" in tok and bool(name) and not name[0].isdigit()
            and name.replace("_", "a").isalnum())


def _bash_segment_signature(tokens: list[str]) -> str | None:
    """Grant key for one simple command, or None when no grant may cover it."""
    toks = list(tokens)
    while toks and _is_assignment(toks[0]):
        if _sig_env_is_dangerous(toks[0]):
            return None
        toks = toks[1:]
    # Unwrap `timeout 60 pytest`, `xargs rm`, `env FOO=1 make` → the program
    # that actually runs.
    while toks and os.path.basename(toks[0]) in _SIG_WRAPPERS:
        wrapper = os.path.basename(toks[0])
        value_flags, positionals = _SIG_WRAPPERS[wrapper]
        rest, i = toks[1:], 0
        while i < len(rest) and rest[i].startswith("-") and rest[i] != "-":
            if wrapper == "env":
                return None        # env -i / -u / -S reshape what runs
            if rest[i] in value_flags:
                i += 1
            i += 1
        if wrapper == "env":
            while i < len(rest) and _is_assignment(rest[i]):
                if _sig_env_is_dangerous(rest[i]):
                    return None
                i += 1
        i += positionals
        toks = rest[i:]
    if not toks:
        return None
    prog_raw = toks[0]
    if not prog_raw or any(ch in prog_raw for ch in "$*?[`\\"):
        return None
    if "/" in prog_raw:
        norm = os.path.normpath(prog_raw)
        head, base = os.path.split(norm)
        if head in _SIG_SYSTEM_BIN_DIRS:
            prog = base
        else:
            prog = norm if os.path.isabs(norm) or norm.startswith("..") else "./" + norm
    else:
        prog = prog_raw
    name = os.path.basename(prog)
    if name in _SIG_UNGRANTABLE:
        return None
    args = toks[1:]
    if name in _SIG_SHELLS and any(
            a == "-c" or (a.startswith("-") and not a.startswith("--") and "c" in a)
            for a in args):
        return None                # `bash -c "…"` hides the real command
    if prog == "git":
        # `git -c core.fsmonitor=CMD …`, --config-env, --exec-path and a
        # foreign --git-dir all let the invocation run arbitrary code.
        i = 0
        while i < len(args) and args[i].startswith("-"):
            flag = args[i].split("=", 1)[0]
            if flag in ("-c", "--config-env", "--exec-path", "--git-dir"):
                return None
            if flag in ("-C", "--work-tree", "--namespace") and "=" not in args[i]:
                i += 1
            i += 1
        args = args[i:]
        return f"Bash:git {args[0]}" if args else "Bash:git"
    if prog in _SIG_MULTI and args and not args[0].startswith("-"):
        return f"Bash:{prog} {args[0]}"
    return f"Bash:{prog}"


def _bash_grant_plan(cmd: str, config: dict | None = None):
    """Split ``cmd`` for grant matching.

    Returns ``(needed, first)``.  ``needed`` lists, in order and
    de-duplicated, the signatures of the segments that are neither read-only
    nor a harmless built-in — the grants the command needs.  ``first`` is the
    signature of the first non-empty segment, the key offered when nothing
    needs a grant.  Returns None when no grant can cover the command at all
    (command substitution, a redirect into a file, `eval`, `bash -c`, a
    dangerous env prefix, unparseable input).
    """
    from cheetahclaws.tools.security import (
        split_command_segments, segment_is_read_only,
    )
    segments = split_command_segments(cmd, allow_background=True)
    if segments is None:
        return None
    needed: list[str] = []
    first: str | None = None
    for seg in segments:
        if not seg:
            continue
        sig = _bash_segment_signature(seg)
        if first is None:
            first = sig
        if segment_is_read_only(seg, config):
            continue
        if seg[0] in _SIG_NEUTRAL or all(_is_assignment(t) for t in seg):
            if any(_is_assignment(t) and _sig_env_is_dangerous(t) for t in seg):
                return None        # `PATH=/evil:$PATH; git status`
            continue
        if sig is None:
            return None
        if sig not in needed:
            needed.append(sig)
    return needed, first


def _expand_grants(sigs) -> set[str]:
    """A compound grant "Bash:git add + git commit" covers each component."""
    out: set[str] = set()
    for s in sigs:
        s = str(s)
        out.add(s)
        if s.startswith("Bash:") and " + " in s:
            out.update("Bash:" + part.strip() for part in s[5:].split(" + ")
                       if part.strip())
    return out


def _permission_signature(tc: dict) -> str:
    """Stable key for a 'don't ask again this session' grant.

    Deliberately coarser than the exact call so a grant is actually useful,
    but never so coarse that it covers a different kind of action:

      Bash  → the program + its subcommand ("git push", "pytest"), so repeat
              runs of the same command with different arguments are covered.
              A chained command names every program that needs approval
              ("Bash:git add + git commit"); read-only segments are left out.
              Empty — no "always allow" offered — for a command no grant can
              ever cover (command substitution, file redirects, `bash -c`).
      Write/Edit/NotebookEdit → the specific file, so approving one file
              never approves another
      other → the tool name
    """
    name = tc["name"]
    inp = tc.get("input") or {}
    if name == "Bash":
        cmd = (inp.get("command", "") or "").strip()
        plan = _bash_grant_plan(cmd)
        if plan is None:
            # Nothing but separators ("; ; ;") keeps the old bare key; any
            # other unplannable command is one no grant may cover.
            return "Bash" if not cmd.strip(" \t\n;&|") else ""
        needed, first = plan
        if needed:
            return "Bash:" + " + ".join(s[len("Bash:"):] for s in needed)
        return first or "Bash"
    if name == "ApplyPatch":
        # One grant per exact set of files, so approving a patch to a.py
        # never approves a later patch that touches (or deletes) b.py.
        # Empty (no "always allow") when the patch doesn't parse.
        from cheetahclaws.tools.patch import patch_paths
        paths = sorted(set(patch_paths(inp.get("patch") or inp.get("input") or "")))
        return f"ApplyPatch:{'|'.join(paths)}" if paths else ""
    path = inp.get("file_path") or inp.get("notebook_path")
    if path:
        return f"{name}:{os.path.abspath(path)}"
    return name


def _bash_grant_covers(cmd: str, granted: set[str], config: dict) -> bool:
    plan = _bash_grant_plan(cmd, config)
    if plan is None:
        return False
    needed, _first = plan
    # Nothing to grant means every segment is read-only; that decision
    # belongs to _is_safe_bash, not to a grant.
    return bool(needed) and all(sig in granted for sig in needed)


def _session_approved(tc: dict, config: dict) -> bool:
    """True if this call was already granted — for the session ("s" at a
    prompt) or permanently ("!" at a prompt, stored in config).

    Bash is matched per segment (see ``_bash_grant_plan``); every other tool
    by its exact signature.
    """
    from cheetahclaws.permissions import saved_signatures
    granted = set(saved_signatures(config))
    try:
        granted |= set(runtime.get_ctx(config).approved_sigs)
    except Exception:
        pass
    if tc.get("name") == "Bash":
        try:
            cmd = ((tc.get("input") or {}).get("command", "") or "").strip()
            return _bash_grant_covers(cmd, _expand_grants(granted), config)
        except Exception:
            return False
    try:
        sig = _permission_signature(tc)
    except Exception:
        return False
    return bool(sig) and sig in granted


def _check_permission(tc: dict, config: dict) -> bool:
    """Return True if operation is auto-approved (no need to ask user)."""
    perm_mode = config.get("permission_mode", "auto")
    name = tc["name"]

    # Plan mode tools are always auto-approved
    if name in ("EnterPlanMode", "ExitPlanMode", "AskUserQuestion"):
        return True

    if perm_mode == "accept-all":
        return True
    if perm_mode == "manual":
        return False   # always ask

    if perm_mode == "plan":
        # Allow writes ONLY to the plan file
        if name in ("Write", "Edit", "MultiEdit"):
            plan_file = runtime.get_ctx(config).plan_file or ""
            target = tc["input"].get("file_path", "")
            if plan_file and target and \
               os.path.normpath(target) == os.path.normpath(plan_file):
                return True
            return False
        if name in ("NotebookEdit", "ApplyPatch"):
            return False
        if name == "Bash":
            from cheetahclaws.tools import _is_safe_bash
            return _is_safe_bash(tc["input"].get("command", ""), config)
        return True  # reads are fine

    # Full autonomy: the user asked for the task to be carried out end to end
    # without approval stops. Deliberately checked *after* manual/plan so an
    # explicit "ask me everything" mode still wins, and it never reaches the
    # Bash hard-denylist, which refuses host-destroying commands regardless.
    from cheetahclaws.permissions import auto_approve_on
    if auto_approve_on(config):
        return True

    # Already granted by answering "s" (this session) or "!" (permanently)
    # at an earlier prompt.
    if _session_approved(tc, config):
        return True

    # "accept-edits" mode: same as "auto", but file edits are pre-approved.
    # Bash and everything else still follow the auto rules below, so a
    # non-allow-listed shell command is still prompted (and the hard denylist
    # still applies at execution time).
    if perm_mode == "accept-edits" and name in ("Write", "Edit", "MultiEdit",
                                                "ApplyPatch", "NotebookEdit"):
        if _edit_targets_are_plain_workspace_files(tc, config):
            return True

    # "auto" mode (and accept-edits fall-through): prompt only for actions
    # that can change the user's files, run arbitrary code, or reach outside
    # the session — reads and self-state updates run straight through.
    if _tool_is_read_only(name) or name in _SELF_STATE_TOOLS:
        return True
    if name == "Write" and _creates_new_workspace_file(tc, config):
        return True
    if name == "Bash":
        from cheetahclaws.tools import _is_safe_bash
        return _is_safe_bash(tc["input"].get("command", ""), config)
    return False   # Write, Edit, and anything unclassified → ask


def _permission_desc(tc: dict) -> str:
    name = tc["name"]
    inp  = tc["input"]
    if name == "Bash":   return f"Run: {inp.get('command', '')}"
    if name == "Write":  return f"Write to: {inp.get('file_path', '')}"
    if name == "Edit":   return f"Edit: {inp.get('file_path', '')}"
    if name == "MultiEdit":
        return f"MultiEdit ({len(inp.get('edits') or [])} edits): {inp.get('file_path', '')}"
    if name == "ApplyPatch":
        from cheetahclaws.tools.patch import describe_patch
        return f"ApplyPatch: {describe_patch(inp.get('patch') or inp.get('input') or '')}"
    return f"{name}({list(inp.values())[:1]})"


def _force_compact(state: AgentState, config: dict) -> bool:
    """Force compaction regardless of threshold. Used when API rejects for context too long."""
    limit = get_context_limit(config.get("model", ""), config)
    before = estimate_tokens(state.messages)
    if before <= 0:
        return False
    from cheetahclaws.compaction import snip_old_tool_results
    snip_old_tool_results(state.messages, max_chars=1000, preserve_last_n_turns=3)
    if estimate_tokens(state.messages) < limit * 0.9:
        return True
    state.messages = compact_messages(state.messages, config)
    from cheetahclaws.compaction import _restore_plan_context
    state.messages.extend(_restore_plan_context(config))
    after = estimate_tokens(state.messages)
    return after < before


def _truncate_err(s: str, max_len: int = 120) -> str:
    if len(s) <= max_len:
        return s
    return s[:max_len - 3] + "..."


def _try_reduce_output_cap_from_error(error_str: str, config: dict) -> int | None:
    """Parse an OpenAI-style context-overflow error and compute a safe
    new max_tokens cap that fits within the model's window.

    Most providers return the message in this shape:

        "This model's maximum context length is 32768 tokens. However,
         you requested 8192 output tokens and your prompt contains at
         least 24577 input tokens, for a total of 32769 tokens..."

    From those numbers we can compute the largest output cap that fits:
        new_cap = model_max - prompt_tokens - SAFETY_BUFFER

    Returns:
        Suggested new max_tokens (>=1), or None if numbers couldn't be
        parsed or the new cap would be too small (<256) to be useful —
        in which case the caller falls back to compaction.
    """
    if not error_str:
        return None
    import re as _re_cap
    # Three numbers, in order: max-context, requested-output, prompt-tokens.
    # All providers we've seen use these patterns; tolerant on phrasing.
    m_max = _re_cap.search(
        r"(?:maximum\s+context\s+length|context\s+window|max(?:imum)?\s+tokens)\s+"
        r"(?:is\s+|of\s+)?(\d+)",
        error_str, _re_cap.IGNORECASE,
    )
    m_prompt = _re_cap.search(
        r"prompt\s+contains\s+(?:at\s+least\s+)?(\d+)",
        error_str, _re_cap.IGNORECASE,
    )
    if not (m_max and m_prompt):
        return None
    try:
        model_max = int(m_max.group(1))
        prompt_tokens = int(m_prompt.group(1))
    except ValueError:
        return None
    # Buffer must absorb provider-side prompt-token-count variance
    # between attempts. Observed in the wild on vLLM-served qwen2.5-72b:
    # the prompt grows by ~+1000 tokens between the original attempt
    # and the retry (vLLM appears to reserve decoder priming budget
    # that's not counted in the initial validation message). 2500
    # (~7.6% of 32K, ~1.25% of 200K) gives real headroom for that
    # behavior across providers we've seen.
    SAFETY_BUFFER = 2500
    new_cap = model_max - prompt_tokens - SAFETY_BUFFER
    # Don't return a cap that's even smaller than what's currently set
    # — that would be a no-op or a regression.
    current_cap = config.get("max_tokens") or 0
    if current_cap and new_cap >= current_cap:
        return None
    if new_cap < 256:
        return None
    return new_cap


# Matches an absolute-path-like token: starts with '/', has at least two
# segments, segment chars are word/dot/dash. Rejects bare '/' or '//'.
# The leading lookbehind keeps URL paths (https://host/...) out of the match.
import re as _re_invest
_PATH_RE = _re_invest.compile(
    r"(?:(?<=^)|(?<=[\s,;:'\"`(<\[]))/[A-Za-z0-9_.][\w./-]*/[\w.][\w./-]*"
)


def _looks_like_investigation(text: str) -> bool:
    """Heuristic: does the user message hand the agent a path/file to look at?

    Only the highest-precision signal is used — an absolute path token —
    because the auto-nudge that consumes this signal must not fire on
    benign greetings. URLs are stripped first so 'https://x/y' does not
    count as a filesystem path.
    """
    if not text:
        return False
    # Strip URLs so http(s)://host/path doesn't masquerade as a fs path.
    no_urls = _re_invest.sub(r"https?://\S+", " ", text)
    return bool(_PATH_RE.search(no_urls))
