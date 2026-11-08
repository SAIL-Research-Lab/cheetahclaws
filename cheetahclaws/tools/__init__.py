"""Tool definitions and implementations for CheetahClaws.

Implementations live in focused sub-modules:
  tools.security     _check_path_allowed, _is_safe_bash
  tools.fs           Read / Write / Edit / MultiEdit / Glob + diff helpers,
                     preview_edit (diff preview for approval prompts)
  tools.patch        ApplyPatch (Codex-style multi-file patches, atomic)
  tools.file_state   encoding detection, atomic writes, read-before-edit tracker
  tools.shell        Bash / Grep
  tools.web          WebFetch / WebSearch
  tools.notebook     NotebookEdit
  tools.diagnostics  GetDiagnostics
  tools.interaction  AskUserQuestion / SleepTimer / bridge routing

This module re-exports every public symbol for backward compatibility,
holds the TOOL_SCHEMAS list, the execute_tool dispatcher, and calls
_register_builtins() which wires all built-ins into the tool registry.
"""
from __future__ import annotations

from typing import Callable, Optional

# ── Re-exports (backward compat) ──────────────────────────────────────────

from cheetahclaws.tools.security import _check_path_allowed, _is_safe_bash  # noqa: F401

from cheetahclaws.tools.fs import (  # noqa: F401
    _read, _write, _edit, _multi_edit, _glob,
    generate_unified_diff, maybe_truncate_diff, preview_edit,
    record_file_state,
)

from cheetahclaws.tools.patch import apply_patch as _apply_patch, patch_paths, describe_patch  # noqa: F401

from cheetahclaws.tools.shell import _bash, _grep, _kill_proc_tree, _has_rg  # noqa: F401

from cheetahclaws.tools.web import _webfetch, _websearch  # noqa: F401

from cheetahclaws.tools.research import _research  # noqa: F401

from cheetahclaws.tools.notebook import _notebook_edit, _parse_cell_id  # noqa: F401

from cheetahclaws.tools.diagnostics import (  # noqa: F401
    _get_diagnostics, _detect_language, _run_quietly,
)

from cheetahclaws.tools.interaction import (  # noqa: F401
    _tg_thread_local, _wx_thread_local, _slack_thread_local, _qq_thread_local,
    _is_in_tg_turn, _is_in_wx_turn, _is_in_slack_turn, _is_in_qq_turn, _is_in_web_turn,
    _ask_user_question, ask_input_interactive,
    _sleeptimer, _INPUT_WAIT_TIMEOUT,
)

from cheetahclaws.tool_registry import ToolDef, register_tool
from cheetahclaws.tool_registry import execute_tool as _registry_execute


# ── Tool JSON schemas (sent to the LLM API) ───────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "Read",
        "description": (
            "Read a file's contents. Returns content with line numbers "
            "(format: 'N\\tline'). Use limit/offset to read large files in chunks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute file path"},
                "limit":     {"type": "integer", "description": "Max lines to read"},
                "offset":    {"type": "integer", "description": "Start line (0-indexed)"},
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "Write",
        "description": (
            "Write content to a file, creating parent directories as needed. "
            "To overwrite an existing file you must Read it first in this session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content":   {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "Edit",
        "description": (
            "Replace exact text in a file. old_string must match exactly (including whitespace). "
            "If old_string appears multiple times, use replace_all=true or add more context. "
            "You must Read the file first in this session; the edit is refused if the "
            "file changed on disk since. Line endings and encoding are preserved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path":   {"type": "string"},
                "old_string":  {"type": "string", "description": "Exact text to replace"},
                "new_string":  {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "MultiEdit",
        "description": (
            "Make several exact-text replacements in ONE file in a single call. "
            "Edits apply in order, each to the result of the previous one, and are "
            "all-or-nothing: if any edit fails, the file is left untouched. Same "
            "matching rules as Edit. Prefer this over repeated Edit calls on one file. "
            "You must Read the file first in this session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute file path"},
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "description": "Replacements to apply in sequence",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string":  {"type": "string", "description": "Exact text to replace"},
                            "new_string":  {"type": "string", "description": "Replacement text"},
                            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
                        },
                        "required": ["old_string", "new_string"],
                    },
                },
            },
            "required": ["file_path", "edits"],
        },
    },
    {
        "name": "ApplyPatch",
        "description": (
            "Apply a multi-file patch atomically (all files change or none do). Format:\n"
            "*** Begin Patch\n"
            "*** Update File: path/to/file.py\n"
            "@@ def optional_anchor_line():\n"
            " context line\n"
            "-removed line\n"
            "+added line\n"
            "*** Add File: path/new.py\n"
            "+every line prefixed with +\n"
            "*** Delete File: path/old.py\n"
            "*** End Patch\n"
            "Optional '*** Move to: new/path' directly after an Update File header renames "
            "the file. Paths are relative to the working directory (absolute also accepted). "
            "Give ~3 lines of context around each change; context must identify a unique "
            "location. Files being updated must have been Read in this session."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Full patch text from '*** Begin Patch' to '*** End Patch'"},
            },
            "required": ["patch"],
        },
    },
    {
        "name": "Bash",
        "description": "Execute a shell command. Returns stdout+stderr. Stateless (no cd persistence).",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "Seconds before timeout (default 120). Use 300+ for package installs (npm, pip, npx), builds, and long-running commands."},
            },
            "required": ["command"],
        },
    },
    {
        "name": "Glob",
        "description": "Find files matching a glob pattern. Returns sorted list of matching paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern e.g. **/*.py"},
                "path":    {"type": "string", "description": "Base directory (default: cwd)"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "Grep",
        "description": "Search file contents with regex using ripgrep (falls back to grep).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern":          {"type": "string", "description": "Regex pattern"},
                "path":             {"type": "string", "description": "File or directory to search"},
                "glob":             {"type": "string", "description": "File filter e.g. *.py"},
                "output_mode":      {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                    "description": "content=matching lines, files_with_matches=file paths, count=match counts",
                },
                "case_insensitive": {"type": "boolean"},
                "context":          {"type": "integer", "description": "Lines of context around matches"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "WebFetch",
        "description": "Fetch a URL and return its text content (HTML stripped).",
        "input_schema": {
            "type": "object",
            "properties": {
                "url":    {"type": "string"},
                "prompt": {"type": "string", "description": "Hint for what to extract"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "WebSearch",
        "description": "Search the web via DuckDuckGo and return top results.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "Research",
        "description": (
            "Research a topic across up to 11 sources in parallel "
            "(arXiv, Semantic Scholar, OpenAlex, HackerNews, GitHub, Reddit, "
            "StackOverflow, Google News, Polymarket, SEC EDGAR, Tavily, Brave). "
            "Returns a synthesized markdown brief with TL;DR, per-domain "
            "findings, minority views, open questions, and numbered citations. "
            "Use this instead of WebSearch when the agent needs current, "
            "engagement-ranked information — academic papers with citation "
            "counts, GitHub repos with star counts, HN threads with points, "
            "SEC filings, prediction market odds, etc. "
            "Domains are auto-classified from the topic; override with "
            "`domains` or pick explicit `sources`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Natural-language query"},
                "domains": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": ["academic", "tech", "finance",
                                       "news", "social", "web"]},
                    "description": "Restrict to these domains. Omit for auto-classification.",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit source names (overrides domains).",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results per source (default 15).",
                },
                "synthesize": {
                    "type": "boolean",
                    "description": "Run model synthesis (default true).",
                },
                "use_cache": {
                    "type": "boolean",
                    "description": "Use 24h cache (default true).",
                },
                "time_range": {
                    "type": "string",
                    "description": (
                        "Preset time window: 1d, 3d, 7d, 30d, 90d, 6m, 1y, "
                        "2y, 5y, all, or natural forms like '30days', "
                        "'6months', '2years'. Affects arXiv submittedDate, "
                        "HN created_at, GitHub pushed, Reddit t, Tavily "
                        "start_published_date, etc."
                    ),
                },
                "since": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) lower bound. Overrides time_range.",
                },
                "until": {
                    "type": "string",
                    "description": "ISO date (YYYY-MM-DD) upper bound. Overrides time_range.",
                },
                "analyze_citations": {
                    "type": "boolean",
                    "description": (
                        "If true, run secondary Semantic Scholar queries on "
                        "top academic results to surface notable citing "
                        "authors (default 10k-citation threshold). Adds "
                        "2-5 extra API calls per run."
                    ),
                },
                "citation_threshold": {
                    "type": "integer",
                    "description": "Min total citations for a citer to be notable (default 10000).",
                },
                "expand": {
                    "type": "integer",
                    "description": (
                        "If > 0, ask the active model to propose N related "
                        "subqueries (2-6) and merge their results for broader "
                        "coverage. Adds ~1 LLM call and N×source_count HTTP "
                        "calls. Default 0 (disabled)."
                    ),
                },
                "save_as": {
                    "type": "string",
                    "description": "Also copy the rendered brief to this path (absolute or ~-relative).",
                },
                "auto_save": {
                    "type": "boolean",
                    "description": (
                        "Auto-save to ~/.cheetahclaws/research_reports/ "
                        "(default true)."
                    ),
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "TaskCreate",
        "description": (
            "Create a new task in the task list. "
            "Use this to track work items, to-dos, and multi-step plans."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject":     {"type": "string", "description": "Brief title"},
                "description": {"type": "string", "description": "What needs to be done"},
                "active_form": {"type": "string", "description": "Present-continuous label while in_progress"},
                "metadata":    {"type": "object", "description": "Arbitrary metadata"},
            },
            "required": ["subject", "description"],
        },
    },
    {
        "name": "TaskUpdate",
        "description": (
            "Update a task: change status, subject, description, owner, "
            "dependency edges, or metadata. "
            "Set status='deleted' to remove. "
            "Statuses: pending, in_progress, completed, cancelled, deleted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id":        {"type": "string"},
                "subject":        {"type": "string"},
                "description":    {"type": "string"},
                "status":         {"type": "string", "enum": ["pending","in_progress","completed","cancelled","deleted"]},
                "active_form":    {"type": "string"},
                "owner":          {"type": "string"},
                "add_blocks":     {"type": "array", "items": {"type": "string"}},
                "add_blocked_by": {"type": "array", "items": {"type": "string"}},
                "metadata":       {"type": "object"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "TaskGet",
        "description": "Retrieve full details of a single task by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID to retrieve"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "TaskList",
        "description": "List all tasks with their status, owner, and pending blockers.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "NotebookEdit",
        "description": (
            "Edit a Jupyter notebook (.ipynb) cell. "
            "Supports replace (modify existing cell), insert (add new cell after cell_id), "
            "and delete (remove cell) operations. "
            "Read the notebook with the Read tool first to see cell IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "notebook_path": {
                    "type": "string",
                    "description": "Absolute path to the .ipynb notebook file",
                },
                "new_source": {
                    "type": "string",
                    "description": "New source code/text for the cell",
                },
                "cell_id": {
                    "type": "string",
                    "description": (
                        "ID of the cell to edit. For insert, the new cell is inserted after this cell "
                        "(or at the beginning if omitted). Use 'cell-N' (0-indexed) if no IDs are set."
                    ),
                },
                "cell_type": {
                    "type": "string",
                    "enum": ["code", "markdown"],
                    "description": "Cell type. Required for insert; defaults to current type for replace.",
                },
                "edit_mode": {
                    "type": "string",
                    "enum": ["replace", "insert", "delete"],
                    "description": "replace (default) / insert / delete",
                },
            },
            "required": ["notebook_path", "new_source"],
        },
    },
    {
        "name": "GetDiagnostics",
        "description": (
            "Get LSP-style diagnostics (errors, warnings, hints) for a source file. "
            "Uses pyright/mypy/flake8 for Python, tsc for TypeScript/JavaScript, "
            "and shellcheck for shell scripts. Returns structured diagnostic output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file to diagnose",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Override auto-detected language: python, javascript, typescript, "
                        "shellscript. Omit to auto-detect from file extension."
                    ),
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "AskUserQuestion",
        "description": (
            "Pause execution and ask the user a clarifying question. "
            "Use this when you need a decision from the user before proceeding. "
            "Returns the user's answer as a string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user.",
                },
                "options": {
                    "type": "array",
                    "description": "Optional list of choices. Each item: {label, description}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label":       {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["label"],
                    },
                },
                "allow_freetext": {
                    "type": "boolean",
                    "description": "If true (default), user may type a free-text answer instead of selecting an option.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "SleepTimer",
        "description": (
            "Schedule a silent background timer. When the timer finishes, it injects an automated "
            "prompt: '(System Automated Event): The timer has finished...' so you can wake up and "
            "execute deferred monitoring tasks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "description": "Number of seconds to sleep before waking up."},
            },
            "required": ["seconds"],
        },
    },
]


# ── Dispatcher (backward-compatible wrapper) ──────────────────────────────

def execute_tool(
    name: str,
    inputs: dict,
    permission_mode: str = "auto",
    ask_permission: Optional[Callable[[str], bool]] = None,
    config: dict = None,
) -> str:
    """Dispatch tool execution; ask permission for write/destructive ops."""
    cfg = config or {}

    # This check must run *before* the registry's read-only cache lookup.  A
    # cache key can cover normal config values, but it cannot safely encode
    # ambient authorization such as the filesystem sandbox environment or the
    # credential-path denylist.  Keep the wrapper check too as defense in depth
    # for callers that invoke the registry directly.
    if name == "Read" and inputs.get("file_path"):
        denied = _check_path_allowed(inputs["file_path"], cfg)
        if denied:
            return denied

    def _check(desc: str) -> bool:
        if permission_mode == "accept-all":
            return True
        if ask_permission:
            return ask_permission(desc)
        return False  # deny by default when no permission handler is set

    # NOTE: read fields with `.get(..., "")` rather than `inputs[...]`. When
    # a weak model fires a tool_call with empty/missing args (qwen2.5 + vLLM
    # is a known offender — see news.md "Be agentic on every model" entry),
    # the registered ToolDef's lambda already returns a friendly "missing
    # required parameter X" string that the model can self-correct from.
    # Raising KeyError here masks that path and surfaces a confusing
    # `Error executing Write: KeyError: 'file_path'` instead.
    if name == "Write":
        if not _check(f"Write to {inputs.get('file_path', '<missing path>')}"):
            return "Denied: user rejected write operation"
    elif name == "Edit":
        if not _check(f"Edit {inputs.get('file_path', '<missing path>')}"):
            return "Denied: user rejected edit operation"
    elif name == "MultiEdit":
        if not _check(f"MultiEdit {inputs.get('file_path', '<missing path>')}"):
            return "Denied: user rejected edit operation"
    elif name == "ApplyPatch":
        # Covers Add / Update / Move *and* Delete File: deletes go through the
        # same approval as every other write.
        if not _check(f"ApplyPatch: {describe_patch(inputs.get('patch') or '', cfg)}"):
            return "Denied: user rejected patch"
    elif name == "Bash":
        cmd = inputs.get("command", "") or ""
        if permission_mode != "accept-all" and not _is_safe_bash(cmd, cfg):
            if not _check(f"Bash: {cmd or '<missing command>'}"):
                return "Denied: user rejected bash command"
    elif name == "NotebookEdit":
        if not _check(f"Edit notebook {inputs.get('notebook_path', '<missing path>')}"):
            return "Denied: user rejected notebook edit operation"

    return _registry_execute(name, inputs, cfg)


# ── MultiEdit / ApplyPatch wrappers ──────────────────────────────────────

def _plan_mode_blocks(paths: list, config: dict) -> Optional[str]:
    """Defense in depth: in plan mode only the plan file may be modified.

    The agent-level permission gate knows Write/Edit by name; these newer
    tools enforce the rule themselves so plan mode can never be bypassed.
    """
    if config.get("permission_mode") != "plan":
        return None
    import os as _os
    try:
        from cheetahclaws import runtime as _rt
        plan_file = _rt.get_ctx(config).plan_file or ""
    except Exception:
        plan_file = ""
    for path in paths:
        if not plan_file or _os.path.realpath(path) != _os.path.realpath(plan_file):
            return ("Error: plan mode is active — only the plan file may be "
                    "modified. Call ExitPlanMode before editing other files.")
    return None


def _multi_edit_tool(p: dict, c: dict) -> str:
    fp = p.get("file_path")
    if not fp:
        return "Error: missing required parameter 'file_path'"
    if "edits" not in p:
        return "Error: missing required parameter 'edits'"
    return (_check_path_allowed(fp, c) or _plan_mode_blocks([fp], c)
            or _multi_edit(fp, p.get("edits"), config=c))


def _apply_patch_tool(p: dict, c: dict) -> str:
    patch = p.get("patch") or p.get("input")   # "input" = Codex's field name
    if not isinstance(patch, str) or not patch.strip():
        return "Error: missing required parameter 'patch'"
    paths = patch_paths(patch, c)
    for path in paths:
        denied = _check_path_allowed(path, c)
        if denied:
            return denied
    return _plan_mode_blocks(paths, c) or _apply_patch(patch, c)


# ── Register built-in tools with the plugin registry ─────────────────────

def _register_builtins() -> None:
    """Register all built-in tools into the central registry."""
    _schemas = {s["name"]: s for s in TOOL_SCHEMAS}

    def _read_with_overflow_check(p: dict, c: dict) -> str:
        """Read wrapper that auto-redirects on too-large files. If the
        Read result would risk overflowing the model's context on the
        next API call, replace it with a short message routing the model
        to SummarizeLargeFile. See `_maybe_redirect_to_summarize`."""
        if not p.get("file_path"):
            return "Error: missing required parameter 'file_path'"
        denied = _check_path_allowed(p["file_path"], c)
        if denied:
            return denied
        result = _read(
            **p,
            max_bytes=c.get("tool_read_max_bytes", 256 * 1024),
            scan_max_bytes=c.get("tool_read_scan_max_bytes", 2 * 1024 * 1024),
            max_output_chars=c.get("tool_read_max_output_chars", 50_000),
        )
        if result and not result.startswith("Error"):
            # Read-before-edit: remember what this session has seen.
            record_file_state(p["file_path"], c)
        # Skip redirect for already-small results (errors, empty, etc.)
        if not result or len(result) < 8000:
            return result
        from cheetahclaws.tools.files import _maybe_redirect_to_summarize
        redirect = _maybe_redirect_to_summarize(result, p["file_path"], c)
        return redirect if redirect else result

    _tool_defs = [
        ToolDef(
            name="Read",
            schema=_schemas["Read"],
            func=_read_with_overflow_check,
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="Write",
            schema=_schemas["Write"],
            func=lambda p, c: (
                "Error: missing required parameter 'file_path'" if not p.get("file_path")
                else _check_path_allowed(p["file_path"], c) or _write(**p, config=c)
            ),
            read_only=False, concurrent_safe=False,
        ),
        ToolDef(
            name="Edit",
            schema=_schemas["Edit"],
            func=lambda p, c: (
                "Error: missing required parameter 'file_path'" if not p.get("file_path")
                else _check_path_allowed(p["file_path"], c) or _edit(**p, config=c)
            ),
            read_only=False, concurrent_safe=False,
        ),
        ToolDef(
            name="MultiEdit",
            schema=_schemas["MultiEdit"],
            func=_multi_edit_tool,
            read_only=False, concurrent_safe=False,
            profiles=frozenset({"standard"}),
        ),
        ToolDef(
            name="ApplyPatch",
            schema=_schemas["ApplyPatch"],
            func=_apply_patch_tool,
            read_only=False, concurrent_safe=False,
            profiles=frozenset({"standard"}),
        ),
        ToolDef(
            name="Bash",
            schema=_schemas["Bash"],
            func=lambda p, c: (
                "Error: Bash requires a non-empty 'command' argument "
                "(the shell command to run). Pass it like "
                "{\"command\": \"ls -la\"}."
                if not (isinstance(p.get("command"), str) and p["command"].strip())
                else _bash(
                    p["command"], p.get("timeout", c.get("bash_default_timeout", 120)),
                    c.get("_worktree_cwd"),
                    c.get("shell_policy", "allow"),
                    c.get("_session_id", "default"),
                    config=c,
                )
            ),
            read_only=False, concurrent_safe=False,
        ),
        ToolDef(
            name="Glob",
            schema=_schemas["Glob"],
            func=lambda p, c: (
                "Error: Glob requires a non-empty 'pattern' argument "
                "(e.g. \"**/*.py\")."
                if not (isinstance(p.get("pattern"), str) and p["pattern"].strip())
                else _glob(p["pattern"], p.get("path"), c.get("_worktree_cwd"))
            ),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="Grep",
            schema=_schemas["Grep"],
            func=lambda p, c: (
                "Error: Grep requires a non-empty 'pattern' argument "
                "(the regex to search for)."
                if not (isinstance(p.get("pattern"), str) and p["pattern"].strip())
                else _grep(
                    p["pattern"], p.get("path"), p.get("glob"),
                    p.get("output_mode", "files_with_matches"),
                    p.get("case_insensitive", False),
                    p.get("context", 0),
                    c.get("_worktree_cwd"),
                )
            ),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="WebFetch",
            schema=_schemas["WebFetch"],
            func=lambda p, c: (
                _webfetch(
                    p["url"], p.get("prompt"),
                    max_bytes=c.get("web_fetch_max_bytes", 512 * 1024),
                    max_seconds=c.get("web_fetch_max_seconds", 30),
                    config=c,
                )
                if isinstance(p.get("url"), str) and p["url"].strip()
                else "Error: WebFetch requires a non-empty 'url' "
                     "argument (the URL to fetch)."
            ),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="WebSearch",
            schema=_schemas["WebSearch"],
            func=lambda p, c: (
                _websearch(
                    p["query"],
                    max_bytes=c.get("web_search_max_bytes", 512 * 1024),
                    max_seconds=c.get("web_search_max_seconds", 30),
                )
                if isinstance(p.get("query"), str) and p["query"].strip()
                else "Error: WebSearch requires a non-empty 'query' "
                     "argument (the search string). Pass it like "
                     "{\"query\": \"berkeley weather today\"}."
            ),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="Research",
            schema=_schemas["Research"],
            func=lambda p, c: _research(
                topic=p["topic"],
                domains=p.get("domains"),
                sources=p.get("sources"),
                limit=p.get("limit", 15),
                synthesize=p.get("synthesize", True),
                use_cache=p.get("use_cache", True),
                time_range=p.get("time_range"),
                since=p.get("since"),
                until=p.get("until"),
                analyze_citations=p.get("analyze_citations", False),
                citation_threshold=p.get("citation_threshold", 10000),
                expand=p.get("expand", 0),
                save_as=p.get("save_as"),
                auto_save=p.get("auto_save", True),
                config=c,
            ),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="NotebookEdit",
            schema=_schemas["NotebookEdit"],
            func=lambda p, c: _notebook_edit(
                p["notebook_path"], p["new_source"],
                p.get("cell_id"), p.get("cell_type"),
                p.get("edit_mode", "replace"),
            ),
            read_only=False, concurrent_safe=False,
        ),
        ToolDef(
            name="GetDiagnostics",
            schema=_schemas["GetDiagnostics"],
            func=lambda p, c: _get_diagnostics(p["file_path"], p.get("language")),
            read_only=True, concurrent_safe=True,
        ),
        ToolDef(
            name="AskUserQuestion",
            schema=_schemas["AskUserQuestion"],
            func=lambda p, c: _ask_user_question(
                p["question"], p.get("options"), p.get("allow_freetext", True),
                config=c,
            ),
            read_only=True, concurrent_safe=False,
        ),
        ToolDef(
            name="SleepTimer",
            schema=_schemas["SleepTimer"],
            func=lambda p, c: _sleeptimer(p["seconds"], c),
            read_only=False, concurrent_safe=True,
        ),
    ]
    for td in _tool_defs:
        register_tool(td)


_register_builtins()


# ── Extension tools (auto-discovery) ─────────────────────────────────────
# Each module self-registers its tools on import. Failures are best-effort.

_EXTENSION_MODULES = [
    "cheetahclaws.memory.tools",
    "cheetahclaws.multi_agent.tools",
    "cheetahclaws.skill.tools",
    "cheetahclaws.mcp_client.tools",
    "cheetahclaws.task.tools",
]

for _mod_name in _EXTENSION_MODULES:
    try:
        __import__(_mod_name)
    except Exception:
        pass  # Extension loading is best-effort; never crash startup

from cheetahclaws.multi_agent.tools import get_agent_manager as _get_agent_manager  # noqa: F401

try:
    from cheetahclaws.plugin.loader import register_plugin_tools as _reg_plugin_tools
    _reg_plugin_tools()
except Exception:
    pass   # Plugin loading is best-effort; never crash startup

try:
    from cheetahclaws.checkpoint.hooks import install_hooks as _install_checkpoint_hooks
    _install_checkpoint_hooks()
except Exception:
    pass

# Sub-modules within tools/ package (self-registering on import)
import importlib as _il
for _sub in ("browser", "email", "files"):
    try:
        _il.import_module(f"cheetahclaws.tools.{_sub}")
    except Exception:
        pass

# ── Plan mode tools (EnterPlanMode / ExitPlanMode) ────────────────────────

from pathlib import Path as _Path


def _enter_plan_mode(params: dict, config: dict) -> str:
    if config.get("permission_mode") == "plan":
        return "Already in plan mode. Write your plan to the plan file, then call ExitPlanMode."

    session_id = config.get("_session_id", "default")
    plans_dir  = _Path(config.get("_worktree_cwd") or _Path.cwd()) / ".nano_claude" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path  = plans_dir / f"{session_id}.md"

    task_desc = params.get("task_description", "")
    if not plan_path.exists() or plan_path.stat().st_size == 0:
        header = f"# Plan: {task_desc}\n\n" if task_desc else "# Plan\n\n"
        plan_path.write_text(header, encoding="utf-8")
    # The agent is told the plan file's path; let it edit it without a Read.
    record_file_state(plan_path, config)

    from cheetahclaws import runtime
    sctx = runtime.get_ctx(config)
    sctx.prev_permission_mode = config.get("permission_mode", "auto")
    config["permission_mode"]  = "plan"
    sctx.plan_file             = str(plan_path)
    return (
        f"Plan mode activated. Plan file: {plan_path}\n"
        "Write your step-by-step plan to the plan file, then call ExitPlanMode when ready to implement."
    )


def _exit_plan_mode(params: dict, config: dict) -> str:
    if config.get("permission_mode") != "plan":
        return "Not in plan mode."
    from cheetahclaws import runtime
    sctx = runtime.get_ctx(config)
    plan_file = sctx.plan_file or ""
    plan_content = ""
    if plan_file:
        try:
            plan_content = _Path(plan_file).read_text(encoding="utf-8").strip()
        except Exception:
            plan_content = ""

    # Reject if plan file is effectively empty (only whitespace / top-level title)
    # A top-level title is exactly "# ..." (single #).  ## sections count as content.
    non_trivial_lines = [
        l for l in plan_content.splitlines()
        if l.strip() and not (l.strip().startswith("# ") and not l.strip().startswith("## "))
    ]
    if not non_trivial_lines:
        return (
            "Plan is empty — please write your step-by-step plan to the plan file "
            f"({plan_file}) before exiting plan mode."
        )

    config["permission_mode"] = sctx.prev_permission_mode or "auto"
    sctx.prev_permission_mode = None
    sctx.plan_file = None
    return (
        f"Plan mode exited. Resuming normal permissions.\n\n"
        f"Plan content:\n{plan_content}\n\n"
        "Wait for the user to approve the plan before executing any steps."
    )


_plan_schema_enter = {
    "name": "EnterPlanMode",
    "description": (
        "Switch to plan mode: read-only except for writing the plan file. "
        "Use this to analyze a task and write a step-by-step plan before executing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Brief description of what you plan to do",
            },
        },
        "required": [],
    },
}
_plan_schema_exit = {
    "name": "ExitPlanMode",
    "description": "Exit plan mode and return to normal permissions to begin executing the plan.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

register_tool(ToolDef("EnterPlanMode", _plan_schema_enter, _enter_plan_mode,
                       read_only=True, concurrent_safe=False))
register_tool(ToolDef("ExitPlanMode",  _plan_schema_exit,  _exit_plan_mode,
                       read_only=False, concurrent_safe=False))
