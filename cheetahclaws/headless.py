"""Headless (non-interactive) execution: `cheetahclaws exec` and `-p/--print`.

Runs one prompt through the agent loop without the REPL and without ever
reading the terminal for approval, then exits with a meaningful status:

    0    the agent finished (exit_reason "completed")
    1    error (API failure, loop guard, bad arguments …)
    2    stopped by policy: max turns, permission denied (with
         --on-permission-denied stop), budget reached, or a hook block
    130  interrupted (Ctrl-C)

Output formats (stdout carries *only* this; all progress/diagnostics go to
stderr):

    text         the final assistant answer
    json         one JSON object — the ``result`` event
    stream-json  one JSON event per line (JSONL), the same events that are
                 appended to ~/.cheetahclaws/sessions/<id>/events.jsonl
                 (see cheetahclaws/event_log.py), plus assistant_delta

Permission policy: whatever the session's permission mode auto-approves runs;
anything that would normally show an approval prompt is matched against
``--allowed-tools`` and otherwise *denied* with an explanatory tool result
(the model sees why and can carry on) and a ``permission_decision`` event.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import time
import uuid
from typing import Optional, TextIO

OUTPUT_FORMATS = ("text", "json", "stream-json")
PERMISSION_MODES = ("auto", "accept-edits", "accept-all", "manual", "plan")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_STOPPED = 2
EXIT_INTERRUPTED = 130

_EXIT_BY_REASON = {
    "completed": EXIT_OK,
    "max_turns": EXIT_STOPPED,
    "permission_denied": EXIT_STOPPED,
    "quota": EXIT_STOPPED,
    "hook_blocked": EXIT_STOPPED,
    "hook_stopped": EXIT_STOPPED,
    "interrupted": EXIT_INTERRUPTED,
}

# Tools that need a human at the keyboard; hidden from the model in headless
# runs so it doesn't stall on (or fail at) asking a question nobody sees.
_INTERACTIVE_ONLY_TOOLS = ("AskUserQuestion",)


def exit_code_for(reason: str) -> int:
    return _EXIT_BY_REASON.get(reason or "", EXIT_ERROR)


# ── argparse ──────────────────────────────────────────────────────────────

def add_arguments(parser) -> None:
    """Headless-only flags, shared by `cheetahclaws exec` and `-p`."""
    g = parser.add_argument_group("headless (-p / exec)")
    g.add_argument("--output-format", choices=OUTPUT_FORMATS, default=None,
                   help="text (final answer only) | json (one result object) | "
                        "stream-json (JSONL events). Default: text")
    g.add_argument("--max-turns", type=int, default=None, metavar="N",
                   help="Stop after N model turns (exit code 2)")
    g.add_argument("--permission-mode", choices=PERMISSION_MODES, default=None,
                   help="Permission mode for this run. Any explicit mode other "
                        "than accept-all also turns off autonomous auto-approve, "
                        "so only that mode's safe operations run unprompted")
    g.add_argument("--allowed-tools", "--allowedTools", dest="allowed_tools",
                   action="append", default=None, metavar="RULES",
                   help='Approve these without prompting, e.g. "Read,Edit" or '
                        '"Bash(git diff:*)" (comma/space separated, repeatable)')
    g.add_argument("--disallowed-tools", "--disallowedTools", dest="disallowed_tools",
                   action="append", default=None, metavar="RULES",
                   help='Hide/deny these, e.g. "WebFetch" or "Bash(rm:*)"')
    g.add_argument("--resume", metavar="SESSION_ID", default=None,
                   help="Continue a saved session by id")
    g.add_argument("--continue", dest="continue_session", action="store_true",
                   help="Continue the most recently saved session")
    g.add_argument("--on-permission-denied", choices=("continue", "stop"),
                   default="continue",
                   help="continue: tell the model and keep going (default); "
                        "stop: end the run at the first denial (exit 2)")
    g.add_argument("--no-event-log", action="store_true",
                   help="Do not write ~/.cheetahclaws/sessions/<id>/events.jsonl")


def split_rules(values) -> list[str]:
    """["Read,Edit", "Bash(git diff:*) Write"] → ["Read","Edit","Bash(git diff:*)","Write"].
    Commas/spaces inside parentheses are kept."""
    out: list[str] = []
    for v in values or []:
        buf, depth = "", 0
        for ch in str(v):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            if depth == 0 and (ch == "," or ch.isspace()):
                if buf.strip():
                    out.append(buf.strip())
                buf = ""
            else:
                buf += ch
        if buf.strip():
            out.append(buf.strip())
    return out


_RULE_RE = re.compile(r"^([\w.\-*]+)(?:\((.*)\))?$", re.S)
# Shell control characters: a prefix rule like "git diff:*" must not approve
# "git diff; rm -rf ~".
_SHELL_META_RE = re.compile(r"[;&|`$<>\n\r]|\$\(")


def _rule_parts(rule: str):
    m = _RULE_RE.match(rule.strip())
    return (m.group(1), m.group(2)) if m else (None, None)


def rule_matches(rule: str, name: str, inp: Optional[dict]) -> bool:
    """Match a Claude-Code-style permission rule against a tool call.

    ``Tool``                 any call to Tool (glob allowed: ``mcp__github__*``)
    ``Bash(git diff:*)``     Bash command equal to / starting with "git diff "
    ``Bash(npm test)``       exact command (glob allowed)
    ``Edit(src/**)``         path-taking tools: glob on the file path
    """
    tname, spec = _rule_parts(rule)
    if not tname or not fnmatch.fnmatchcase(name, tname):
        return False
    if spec is None or spec.strip() in ("", "*"):
        return True
    inp = inp or {}
    if name == "Bash":
        cmd = str(inp.get("command", "")).strip()
        if _SHELL_META_RE.search(cmd):
            return False
        if spec.endswith(":*"):
            prefix = spec[:-2].strip()
            return cmd == prefix or cmd.startswith(prefix + " ")
        return fnmatch.fnmatchcase(cmd, spec)
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    if not path:
        # URL / pattern arguments are matched as given.
        other = inp.get("url") or inp.get("pattern") or ""
        return bool(other) and fnmatch.fnmatchcase(str(other), spec)
    # File paths are matched only in normalised form: fnmatch's `*` also
    # matches "/" and "..", so the raw string `src/../../.bashrc` would match
    # `src/**`.  A relative spec covers paths inside the working directory;
    # an absolute spec is matched against the resolved absolute path.
    try:
        absolute = os.path.realpath(os.path.expanduser(str(path)))
        rel = os.path.relpath(absolute, os.path.realpath(os.getcwd()))
    except (ValueError, OSError):
        return False
    if os.path.isabs(os.path.expanduser(spec)):
        return fnmatch.fnmatchcase(absolute, os.path.normpath(os.path.expanduser(spec)))
    if rel == ".." or rel.startswith(".." + os.sep) or os.path.isabs(rel):
        return False
    return fnmatch.fnmatchcase(rel, spec)


# ── prompt input ──────────────────────────────────────────────────────────

def _stdin_has_data(stdin, timeout: float) -> bool:
    try:
        import select
        r, _, _ = select.select([stdin], [], [], timeout)
        return bool(r)
    except Exception:
        return True    # can't tell (e.g. Windows) → just read


def read_prompt(prompt_args: list[str], stdin: Optional[TextIO] = None,
                stdin_wait: float = 2.0) -> str:
    """Build the prompt like `claude -p`: positional words, plus stdin when
    it is piped (or when "-" is given).  Both → prompt, blank line, stdin."""
    stdin = stdin if stdin is not None else sys.stdin
    parts = list(prompt_args or [])
    explicit = "-" in parts
    parts = [p for p in parts if p != "-"]
    text = " ".join(parts).strip()
    data = ""
    if stdin is not None:
        try:
            is_tty = stdin.isatty()
        except Exception:
            is_tty = True
        if explicit or (not is_tty and _stdin_has_data(stdin, stdin_wait)):
            try:
                data = stdin.read() or ""
            except Exception:
                data = ""
    data = data.strip("\n")
    if text and data.strip():
        return f"{text}\n\n{data}"
    return text or data


# ── session resume ────────────────────────────────────────────────────────

def load_saved_session(session_id: Optional[str], *, latest: bool = False) -> Optional[dict]:
    """Return {"session_id", "messages", ...} from the session store (SQLite),
    falling back to the JSON autosave files."""
    try:
        from cheetahclaws import session_store
        if latest:
            rows = session_store.list_sessions(limit=1)
            if rows:
                session_id = rows[0]["id"]
        if session_id:
            data = session_store.load_session(session_id)
            if data:
                return data
    except Exception:
        pass
    if not session_id:
        return None
    try:
        from cheetahclaws.config import DAILY_DIR, MR_SESSION_DIR
        candidates = sorted(DAILY_DIR.glob(f"*/session_*_{session_id}.json"), reverse=True)
        latest_file = MR_SESSION_DIR / "session_latest.json"
        if latest_file.exists():
            candidates.append(latest_file)
        for p in candidates:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("session_id") == session_id:
                return data
    except Exception:
        pass
    return None


def _save_session(session_id: str, state, config: dict) -> None:
    try:
        from cheetahclaws import session_store
        from cheetahclaws.commands.session import derive_title
        session_store.save_session(
            session_id, state.messages,
            title=derive_title(state.messages), model=config.get("model", ""),
            turn_count=state.turn_count,
            input_tokens=state.total_input_tokens,
            output_tokens=state.total_output_tokens,
        )
    except Exception as e:
        print(f"[cheetahclaws] warning: could not save session {session_id}: {e}",
              file=sys.stderr)


# ── progress (text mode, stderr) ──────────────────────────────────────────

def _progress_sink(err: TextIO):
    def sink(ev: dict) -> None:
        t = ev.get("type")
        if t == "tool_call":
            arg = json.dumps(ev.get("input", {}), ensure_ascii=False, default=str)
            print(f"  > {ev.get('name')} {arg[:160]}", file=err, flush=True)
        elif t == "tool_result" and ev.get("is_error"):
            first = str(ev.get("output", "")).strip().splitlines()[:1]
            print(f"    ! {ev.get('name')}: {(first[0] if first else '')[:200]}",
                  file=err, flush=True)
        elif t == "permission_decision" and ev.get("decision") == "deny":
            print(f"  ! denied {ev.get('name')} ({ev.get('source')})", file=err, flush=True)
        elif t in ("error", "notice"):
            print(f"  [{t}] {ev.get('message') or ev.get('text')}", file=err, flush=True)
    return sink


# ── main entry ────────────────────────────────────────────────────────────

def _final_text(messages: list, start: int) -> str:
    for m in reversed(messages[start:]):
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(b.get("text", "") for b in c
                        if isinstance(b, dict) and b.get("type") == "text")
        if isinstance(c, str) and c.strip():
            return c
    return ""


def apply_args_to_config(config: dict, args) -> list[str]:
    """Apply headless flags to config in place.  Returns error strings."""
    errors = []
    if getattr(args, "max_turns", None) is not None:
        if args.max_turns <= 0:
            errors.append("--max-turns must be a positive integer")
        config["max_turns"] = args.max_turns
    mode = getattr(args, "permission_mode", None)
    if mode:
        config["permission_mode"] = mode
        if mode != "accept-all":
            from cheetahclaws.permissions import set_auto_approve
            set_auto_approve(False, config, persist=False)
    disabled = list(config.get("disabled_tools") or [])
    for rule in split_rules(getattr(args, "disallowed_tools", None)):
        tname, spec = _rule_parts(rule)
        if not tname:
            errors.append(f"bad --disallowed-tools rule: {rule!r}")
        elif spec is None and "*" not in tname:
            disabled.append(tname)
    for t in _INTERACTIVE_ONLY_TOOLS:
        if t not in disabled:
            disabled.append(t)
    config["disabled_tools"] = disabled
    for rule in split_rules(getattr(args, "allowed_tools", None)):
        if not _rule_parts(rule)[0]:
            errors.append(f"bad --allowed-tools rule: {rule!r}")
    if getattr(args, "no_event_log", False):
        config["event_log"] = False
    return errors


def run(config: dict, args, *, out: Optional[TextIO] = None,
        err: Optional[TextIO] = None, stdin: Optional[TextIO] = None) -> int:
    """Run one headless request.  ``out`` receives only the formatted result."""
    out = out or sys.stdout
    err = err or sys.stderr
    fmt = getattr(args, "output_format", None) or "text"
    t0 = time.monotonic()

    problems = apply_args_to_config(config, args)
    if getattr(args, "resume", None) and getattr(args, "continue_session", False):
        problems.append("use either --resume or --continue, not both")
    if problems:
        for p in problems:
            print(f"Error: {p}", file=err)
        return EXIT_ERROR

    prompt = read_prompt(getattr(args, "prompt", None) or [], stdin)
    if not prompt.strip():
        print("Error: no prompt given (pass it as an argument or pipe it on stdin)",
              file=err)
        return EXIT_ERROR

    # Nothing may block on the terminal from here on: tools that fall back to
    # input() get EOF instead of waiting for a human who isn't there.
    _real_stdin = None
    if stdin is None:
        import io
        _real_stdin, sys.stdin = sys.stdin, io.StringIO("")
    try:
        return _run(config, args, prompt, fmt, t0, out, err)
    finally:
        if _real_stdin is not None:
            sys.stdin = _real_stdin


def _run(config, args, prompt, fmt, t0, out, err) -> int:
    from cheetahclaws.agent import AgentState, PermissionRequest, run as agent_run
    from cheetahclaws import event_log, hooks, runtime

    state = AgentState()
    resumed = False
    session_id = None
    if getattr(args, "resume", None) or getattr(args, "continue_session", False):
        data = load_saved_session(getattr(args, "resume", None),
                                  latest=bool(getattr(args, "continue_session", False)))
        if not data:
            print("Error: no saved session found"
                  + (f" for id {args.resume!r}" if getattr(args, "resume", None) else ""),
                  file=err)
            return EXIT_ERROR
        session_id = str(data.get("session_id") or "")
        state.messages = list(data.get("messages") or [])
        state.turn_count = int(data.get("turn_count") or 0)
        state.total_input_tokens = int(data.get("total_input_tokens") or 0)
        state.total_output_tokens = int(data.get("total_output_tokens") or 0)
        resumed = True
    if not session_id or not event_log.valid_session_id(session_id):
        session_id = uuid.uuid4().hex[:8]

    config["_session_id"] = session_id
    sctx = runtime.get_session_ctx(session_id)
    sctx.agent_state = state

    emitter = event_log.make_emitter(session_id, config)
    config["_event_emitter"] = emitter
    if fmt == "stream-json":
        def _jsonl_sink(ev: dict) -> None:
            out.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            out.flush()
        emitter.add_sink(_jsonl_sink)
    elif fmt == "text" and (config.get("verbose") or _isatty(err)):
        emitter.add_sink(_progress_sink(err))

    # --disallowed-tools rules with arguments ("Bash(rm:*)") are enforced as an
    # in-process PreToolUse hook so they win over every auto-approve path.
    deny_rules = [r for r in split_rules(getattr(args, "disallowed_tools", None))
                  if _rule_parts(r)[1] is not None or "*" in (_rule_parts(r)[0] or "")]
    unregister = None
    if deny_rules:
        def _deny_hook(payload: dict):
            for r in deny_rules:
                if rule_matches(r, payload.get("tool_name", ""), payload.get("tool_input")):
                    return {"decision": "deny",
                            "reason": f"matches --disallowed-tools rule {r!r}"}
            return None
        unregister = hooks.register("PreToolUse", _deny_hook, name="disallowed-tools")

    allow_rules = split_rules(getattr(args, "allowed_tools", None))
    stop_on_denial = getattr(args, "on_permission_denied", "continue") == "stop"
    denials: list[dict] = []

    emitter.emit("session_start", model=config.get("model", ""), cwd=os.getcwd(),
                 permission_mode=config.get("permission_mode", "auto"),
                 mode="headless", resumed=resumed, version=_version(),
                 max_turns=config.get("max_turns"))
    try:
        hooks.session_start(config, source="resume" if resumed else "startup")
    except Exception:
        pass

    start_len = len(state.messages)
    start_turns = state.turn_count
    start_in, start_out = state.total_input_tokens, state.total_output_tokens
    start_cr, start_cw = state.total_cache_read_tokens, state.total_cache_write_tokens
    exit_reason = ""
    error_message = ""

    try:
        from cheetahclaws.context import build_system_prompt
        system_prompt = build_system_prompt(config)
        for event in agent_run(prompt, state, config, system_prompt,
                               cancel_check=lambda: stop_on_denial and bool(denials)):
            if isinstance(event, PermissionRequest):
                name = event.tool_name or ""
                if any(rule_matches(r, name, event.tool_input) for r in allow_rules):
                    event.granted = True
                    event.decided_by = "allowed_tools"
                    continue
                event.granted = False
                event.decided_by = "headless"
                event.deny_reason = _denial_text(name, event.description)
                denials.append({"id": event.tool_id, "name": name,
                                "description": event.description})
        exit_reason = state.exit_reason or "completed"
        if stop_on_denial and denials and exit_reason == "cancelled":
            exit_reason = "permission_denied"
    except KeyboardInterrupt:
        exit_reason = "interrupted"
    except Exception as e:  # never die without a result record
        exit_reason = "error"
        error_message = f"{type(e).__name__}: {e}"
        emitter.emit("error", message=error_message[:2000])
    finally:
        if unregister:
            unregister()

    usage = {
        "input_tokens": state.total_input_tokens - start_in,
        "output_tokens": state.total_output_tokens - start_out,
        "cache_read_tokens": state.total_cache_read_tokens - start_cr,
        "cache_write_tokens": state.total_cache_write_tokens - start_cw,
    }
    cost = None
    try:
        from cheetahclaws.providers import calc_cost
        cost = round(calc_cost(config.get("model", ""), usage["input_tokens"],
                               usage["output_tokens"], usage["cache_read_tokens"],
                               usage["cache_write_tokens"]), 6)
    except Exception:
        pass
    final_text = _final_text(state.messages, start_len)
    code = exit_code_for(exit_reason)
    result_fields = dict(
        final_text=final_text,
        exit_reason=exit_reason,
        is_error=code != EXIT_OK,
        exit_code=code,
        turns=state.turn_count - start_turns,
        usage=usage,
        cost_usd=cost,
        duration_ms=int((time.monotonic() - t0) * 1000),
        model=config.get("model", ""),
        permission_denials=denials,
    )
    if error_message:
        result_fields["error"] = error_message
    result_ev = emitter.emit("result", **result_fields)

    _save_session(session_id, state, config)
    try:
        hooks.session_end(config, reason="exit" if exit_reason != "interrupted" else "interrupted")
    except Exception:
        pass
    emitter.close()

    if fmt == "json":
        out.write(json.dumps(result_ev, ensure_ascii=False, default=str) + "\n")
    elif fmt == "text":
        if final_text:
            out.write(final_text.rstrip("\n") + "\n")
        if code != EXIT_OK:
            msg = error_message or f"stopped: {exit_reason}"
            print(f"[cheetahclaws] {msg} (session {session_id}, exit {code})", file=err)
    try:
        out.flush()
    except Exception:
        pass
    return code


def _denial_text(name: str, description: str) -> str:
    return (
        f"Denied: '{name}' needs approval ({description}), but this is a "
        f"non-interactive (headless) run and nobody can approve it. Do not "
        f"retry the same call; finish what you can without it and say what "
        f"remains. [operator: allow it with --allowed-tools \"{name}\" or "
        f"--permission-mode accept-all]"
    )


def _isatty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("cheetahclaws")
    except Exception:
        return ""
