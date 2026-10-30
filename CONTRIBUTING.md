# Contributing to CheetahClaws

Thank you for your interest in contributing! This guide covers the architecture, conventions, and common pitfalls to help your PR land smoothly.

## Quick Start

```bash
git clone git@github.com:SAIL-Research-Lab/cheetahclaws.git
cd cheetahclaws
pip install -r requirements.txt
pip install pytest
python -m pytest tests/ -x -q    # all 327+ tests should pass
python cheetahclaws.py            # run the REPL
```

## Project Structure

```
cheetahclaws/
├── cheetahclaws.py          # REPL loop, slash commands, readline setup
├── agent.py                 # LLM turn loop, retries, permission checks
├── providers.py             # API streaming (Anthropic, OpenAI, Ollama, etc.)
├── config.py                # User config (load/save to ~/.cheetahclaws/config.json)
├── runtime.py               # RuntimeContext — per-session live state (NOT config)
├── tool_registry.py         # Central tool registry (ToolDef, register_tool)
├── context.py               # System prompt builder (assembles base + overlay + env + fragments)
├── compaction.py            # Context window compaction
│
├── tools/                   # Tool implementations (one file per category)
│   ├── __init__.py          # Re-exports all tool functions; holds TOOL_SCHEMAS
│   ├── fs.py                # Read / Write / Edit / Glob
│   ├── shell.py             # Bash / Grep
│   ├── web.py               # WebFetch / WebSearch
│   ├── notebook.py          # NotebookEdit
│   ├── security.py          # Path/command allow-lists
│   ├── diagnostics.py       # GetDiagnostics
│   └── interaction.py       # AskUserQuestion / bridge input routing
│
├── commands/                # Slash command handlers (/config, /plan, /model, etc.)
├── bridges/                 # Telegram, WeChat, Slack integrations
├── plugin/                  # Plugin system (install, load, manifest parsing)
├── skill/                   # Skill system (Markdown prompt templates)
├── daemon/               # Daemon foundation (F-1..F-9 all landed) — `cheetahclaws serve` + RPC surface (agent/monitor/bridge/session/proactive/system); see docs/RFC/0002
├── mcp_client/                  # MCP (Model Context Protocol) client & tools
├── research/lab/            # Autonomous multi-agent research engine (/lab — 9-stage state machine + sandboxed experiments + citation verifier)
├── memory/                  # Persistent memory system
├── multi_agent/             # Sub-agent spawning & worktree isolation
├── monitor/                 # Subscription monitoring (arxiv, stocks, news)
├── checkpoint/              # Session snapshot & restore
├── task/                    # Task tracking
├── ui/                      # Terminal rendering (colors, spinners, status bar)
├── modular/                 # Optional modules (voice, video)
├── prompts/                 # System prompt assets — base/default.md (shared baseline)
│                            #   + overlays/<family>.md (vendor-documented quirks)
│                            #   + fragments/<name>.md (conditional blocks).
│                            #   See prompts/README.md for the overlay-admission policy.
└── tests/                   # pytest suite (578+ tests)
```

## Key Architecture Concepts

### Config vs. RuntimeContext

**`config` dict** — serializable user settings loaded from `~/.cheetahclaws/config.json`. Contains model name, API keys, permission mode, etc. Saved to disk by `save_config()`.

**`RuntimeContext`** (in `runtime.py`) — per-session live state: threads, bridge flags, plan mode state, pending images, etc. **Never** stored in the config dict.

```python
# CORRECT: runtime state goes in RuntimeContext
import runtime
sctx = runtime.get_ctx(config)       # get context for this session
sctx.plan_file = "/path/to/plan.md"

# WRONG: don't put runtime state in config
config["_plan_file"] = "/path/to/plan.md"   # NO!
```

The only `_`-prefixed key allowed in config is `_session_id`, which bridges config to RuntimeContext.

### Tool System

Tools are registered via `tool_registry.py`:

```python
from tool_registry import ToolDef, register_tool

register_tool(ToolDef(
    name="MyTool",
    schema={
        "name": "MyTool",
        "description": "What this tool does",
        "input_schema": {"type": "object", "properties": {...}, "required": [...]},
    },
    func=my_tool_func,       # (params: dict, config: dict) -> str
    read_only=False,
    concurrent_safe=False,
))
```

### Plugin System

Plugins live in `~/.cheetahclaws/plugins/<name>/` (user scope) or `.cheetahclaws/plugins/<name>/` (project scope). Installed via `/plugin install name@<url>`.

**Manifest**: `plugin.json` at the plugin root:

```json
{
  "name": "myplugin",
  "version": "0.1.0",
  "description": "What it does",
  "tools": ["tools"],
  "skills": ["skills/myplugin.md"],
  "commands": ["cmd"],
  "dependencies": ["some-pip-package"]
}
```

**Plugin tools**: The module listed in `tools` must export a `TOOL_DEFS` list:

```python
TOOL_DEFS = [
    ToolDef(name="MyPluginTool", schema={...}, func=my_func),
]
```

Do **not** call `register_tool()` directly in plugin code — the loader reads `TOOL_DEFS` and registers them for you.

**Plugin commands**: The module listed in `commands` must export a `COMMAND_DEFS` dict:

```python
COMMAND_DEFS = {
    "mycommand": {
        "func": my_command_func,    # (args: str, state, config) -> bool
        "help": ("Short description", ["subcommand1", "subcommand2"]),
    }
}
```

### Hooks System

CheetahClaws does **not** have a generic event-based hooks system. The `checkpoint/hooks.py` module wraps Write/Edit/NotebookEdit tools to create file backups before writes. There is no `hooks.json` and no `hook_session_start`/`hook_stop` events.

### Bridges

Telegram, WeChat, Slack, and QQ bridges receive messages and route them through `RuntimeContext.run_query`. Telegram/WeChat/Slack long-poll; QQ uses the qq-botpy async WebSocket SDK on a dedicated event-loop thread. Bridge-specific state (turn flags, current user/channel/target) lives in `RuntimeContext`, not in the config dict.

## Conventions

### Dependencies

- **`pyproject.toml`** is the source of truth for dependencies
- `requirements.txt` mirrors `pyproject.toml` dependencies for convenience
- Optional deps go in `[project.optional-dependencies]`, not in core `dependencies`
- If you add a new dependency, update both files

### Adding New Modules

- New tool implementations → add to `tools/` package (e.g., `tools/mytool.py`)
- New command handlers → add to `commands/`
- New top-level `.py` files → **must be added to `pyproject.toml` `py-modules` list**, otherwise `pip install .` will not ship them
- New sub-packages (directories with `__init__.py`) under an existing tracked package → **picked up automatically** by `[tool.setuptools.packages.find]`. No `pyproject.toml` change needed.
- New top-level package directory → add a wildcard entry like `"newpkg*"` to the `include` list under `[tool.setuptools.packages.find]`.

> ⚠️ **Never use the same name in `py-modules` AND as a directory package** (e.g., a `memory.py` shim alongside a `memory/` package). On Windows + Python 3.13 + setuptools ≥ 75 this triggers a silent package-drop during wheel build and unrelated packages disappear (cause of issue #97). The `tests/test_packaging.py::test_pyproject_no_module_package_collision` regression test will catch this in CI; if you hit it, delete the shim and have callers `import name` against the package directory directly.

### Error Handling

- Never show raw Python tracebacks to users
- Use `err()` / `warn()` from `ui.render` for user-facing messages
- Use `logging_utils` for internal logging
- API errors should include actionable hints (check API key, check connection, etc.)

### Testing

- All tests live in `tests/`
- Run with `python -m pytest tests/ -x -q`
- CI runs on Python 3.10–3.13; make sure your code is compatible
- `pip install .` smoke test verifies all modules are importable

## PR Checklist

Before submitting a PR:

- [ ] `python -m pytest tests/ -x -q` passes (all 1000+ tests)
- [ ] No new dependencies added to core without discussion
- [ ] Runtime state uses `RuntimeContext`, not `config["_xxx"]`
- [ ] Plugin tools export `TOOL_DEFS`, not direct `register_tool()` calls
- [ ] New top-level `.py` files added to `pyproject.toml` `py-modules`; new top-level packages added to `[tool.setuptools.packages.find]` `include` patterns (sub-packages auto-discover)
- [ ] No `<name>.py` shim with the same name as a `<name>/` package — see issue #97
- [ ] No secrets or API keys in committed code
- [ ] Separate bug fixes from new features (one concern per PR)

## Questions?

Open an issue or start a discussion on the [GitHub repo](https://github.com/SAIL-Research-Lab/cheetahclaws).
