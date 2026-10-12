# Plugin Authoring Guide

Build and distribute plugins for CheetahClaws. Plugins can add tools (callable by the AI), slash commands (typed by the user), skills (prompt templates), and MCP servers.

## Quick Start

```bash
# Create a plugin from the example template
cp -r examples/example-plugin ~/.cheetahclaws/plugins/my-plugin
# Edit the files, then restart cheetahclaws
cheetahclaws
/plugin                  # verify it's loaded
```

Or install from a git repo:
```bash
/plugin install my-plugin@https://github.com/you/cheetahclaws-my-plugin
```

---

## Plugin Structure

```
my-plugin/
├── plugin.json          # manifest (required)
├── tools.py             # tool definitions (optional)
├── cmd.py               # slash commands (optional)
├── skills/              # skill markdown files (optional)
│   └── my-skill.md
└── README.md            # documentation (optional)
```

The only required file is the manifest (`plugin.json` or `PLUGIN.md`).

---

## Manifest: plugin.json

```json
{
  "name": "my-plugin",
  "version": "0.1.0",
  "description": "What this plugin does (shown in /plugin list)",
  "author": "Your Name",
  "tags": ["tag1", "tag2"],
  "tools": ["tools"],
  "commands": ["cmd"],
  "skills": ["skills/my-skill.md"],
  "mcp_servers": {},
  "dependencies": ["some-pip-package>=1.0"],
  "homepage": "https://github.com/you/cheetahclaws-my-plugin"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | **Required.** Plugin identifier (alphanumeric + hyphens) |
| `version` | string | Semver version (default: `"0.1.0"`) |
| `description` | string | One-line description |
| `author` | string | Author name |
| `tags` | list[string] | Searchable tags |
| `tools` | list[string] | Python module names that export `TOOL_DEFS` |
| `commands` | list[string] | Python module names that export `COMMAND_DEFS` |
| `skills` | list[string] | Relative paths to skill `.md` files |
| `mcp_servers` | dict | MCP server configs (see below) |
| `dependencies` | list[string] | pip packages to auto-install |
| `homepage` | string | URL to the plugin's homepage/repo |

**Alternative: PLUGIN.md** — you can use YAML frontmatter instead of JSON:

```markdown
---
name: my-plugin
version: 0.1.0
description: What this plugin does
tools:
  - tools
commands:
  - cmd
---

# My Plugin

Documentation goes here...
```

---

## Adding Tools

Tools are functions the AI can call during a conversation. Create a `tools.py` that exports `TOOL_DEFS`:

```python
"""my-plugin/tools.py"""
from tool_registry import ToolDef


def _my_tool(params: dict, config: dict) -> str:
    """Tool handler. Receives JSON params from the AI, returns a string result."""
    query = params["query"]
    # ... do something ...
    return f"Result for: {query}"


def _my_readonly_tool(params: dict, config: dict) -> str:
    """A read-only tool that never modifies state."""
    return "some information"


# This list is what the plugin loader reads.
# Do NOT call register_tool() directly — the loader handles registration.
TOOL_DEFS = [
    ToolDef(
        name="MyPluginSearch",
        schema={
            "name": "MyPluginSearch",
            "description": "Search for something using my plugin.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
        func=_my_tool,
        read_only=False,
        concurrent_safe=True,
    ),
    ToolDef(
        name="MyPluginStatus",
        schema={
            "name": "MyPluginStatus",
            "description": "Show plugin status information.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        func=_my_readonly_tool,
        read_only=True,
        concurrent_safe=True,
    ),
]
```

### Tool handler contract

```python
def my_handler(params: dict, config: dict) -> str:
```

- `params` — the JSON parameters from the AI, validated against your `input_schema`
- `config` — the runtime config dict (model, API keys, settings)
- Return a **string** — this is what the AI sees as the tool result
- Output is trimmed to fit the model's context — between 2,000 and 7,000 characters depending on the context window. The middle is cut and replaced with a `[... N chars truncated ...]` marker, so put what matters at the start or the end

### ToolDef fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Unique tool name (PascalCase recommended) |
| `schema` | dict | JSON Schema with `name`, `description`, `input_schema` |
| `func` | callable | Handler function `(params, config) -> str` |
| `read_only` | bool | `True` if the tool never modifies files/state |
| `concurrent_safe` | bool | `True` if safe to run in parallel with other tools |

### Graceful degradation

If your tool depends on an optional package, check at call time:

```python
def _my_tool(params: dict, config: dict) -> str:
    try:
        import some_package
    except ImportError:
        return (
            "some_package is not installed. Install it with:\n"
            "  pip install some_package"
        )
    # ... use some_package ...
```

---

## Adding Slash Commands

Commands are typed by the user in the REPL (e.g., `/mycommand args`). Create a `cmd.py` that exports `COMMAND_DEFS`:

```python
"""my-plugin/cmd.py"""
from ui.render import info, ok, err


def _cmd_greet(args: str, state, config) -> bool:
    """Handle /greet [name]"""
    name = args.strip() or "world"
    ok(f"Hello, {name}!")
    return True


def _cmd_mystatus(args: str, state, config) -> bool:
    """Handle /mystatus"""
    info(f"Messages: {len(state.messages)}")
    info(f"Model: {config.get('model', '?')}")
    return True


COMMAND_DEFS = {
    "greet": {
        "func": _cmd_greet,
        "help": ("Say hello", []),           # (description, [subcommands])
        "aliases": ["hello", "hi"],
    },
    "mystatus": {
        "func": _cmd_mystatus,
        "help": ("Show plugin status", []),
        "aliases": [],
    },
}
```

### Command handler contract

```python
def my_command(args: str, state, config: dict) -> bool:
```

- `args` — everything after the command name (e.g., `/greet Alice` → `args = "Alice"`)
- `state` — the `AgentState` object (messages, token counts, turn count)
- `config` — the runtime config dict
- Return `True` to stay in the REPL

### Subcommands

For commands with subcommands (e.g., `/myplugin setup`, `/myplugin status`):

```python
def _cmd_myplugin(args: str, state, config) -> bool:
    parts = args.split() if args.strip() else []
    sub = parts[0] if parts else ""
    rest = " ".join(parts[1:])

    if sub == "setup":
        ok("Setting up...")
        return True
    elif sub == "status":
        info("All good")
        return True
    else:
        info("Usage: /myplugin <setup|status>")
        return True


COMMAND_DEFS = {
    "myplugin": {
        "func": _cmd_myplugin,
        "help": ("My plugin", ["setup", "status"]),  # subcommands shown in Tab-complete
        "aliases": ["mp"],
    },
}
```

---

## Adding Skills

Skills are Markdown prompt templates invoked via the `Skill` tool. Place `.md` files under a `skills/` directory and list them in the manifest.

```markdown
---
name: my-analysis
description: "Run a deep analysis on a codebase"
user-invocable: true
triggers: ["/my-analysis", "/analyze"]
tools: [Read, Glob, Grep]
---

# Analysis Skill

You are an expert code analyst. Perform a thorough analysis of the codebase.

## Steps

1. Use Glob to find all source files
2. Read the main entry point
3. Identify architectural patterns
4. Report findings in a structured format

## Arguments

- `{args}` — optional focus area provided by the user
```

The `{args}` placeholder is replaced with the user's input when the skill is invoked.

---

## Adding MCP Servers

Bundle an MCP server with your plugin:

```json
{
  "mcp_servers": {
    "myserver": {
      "command": "python3",
      "args": ["-m", "my_mcp_module"],
      "env": {
        "MY_CONFIG": "value"
      }
    }
  }
}
```

The server name is auto-qualified as `<plugin_name>__<server_name>` to avoid collisions. Tools from the MCP server are registered as `mcp__<plugin>__<server>__<tool>`.

---

## Installation Scopes

Plugins live in one of three scopes:

| Scope | Directory | Config | Use case |
|-------|-----------|--------|----------|
| **User** (default) | `~/.cheetahclaws/plugins/<name>/` | `~/.cheetahclaws/plugins.json` | Personal tools available everywhere |
| **Project** | `.cheetahclaws/plugins/<name>/` | `.cheetahclaws/plugins.json` | Project-specific tools, committed to git |
| **External** | Any dir listed in `$CHEETAHCLAWS_PLUGIN_PATH` | enable state in `~/.cheetahclaws/plugins.json` | Shared team/company plugins, no install step |

```bash
# Install to user scope (default)
/plugin install my-plugin@https://github.com/you/my-plugin

# Install to project scope
/plugin install my-plugin@./local/path --project
```

---

## External Plugins (`CHEETAHCLAWS_PLUGIN_PATH`)

External plugins are discovered **in-place** from directories you control — CheetahClaws never copies them to `~/.cheetahclaws/plugins/`. This is the right fit for shared team or company plugin directories: the ops team maintains one source of truth, users just point an env var at it.

### Setup

```bash
# Single directory
export CHEETAHCLAWS_PLUGIN_PATH=/opt/company/cheetahclaws-plugins

# Multiple directories (colon-separated on Linux/macOS, semicolon on Windows)
export CHEETAHCLAWS_PLUGIN_PATH=/opt/company/plugins:$HOME/my-shared-plugins
```

Each **immediate subdirectory** with a `plugin.json` or `PLUGIN.md` is picked up:

```
/opt/company/cheetahclaws-plugins/
├── audit-tools/
│   ├── plugin.json
│   └── tools.py
├── company-skills/
│   ├── PLUGIN.md
│   └── skills/
└── .cache/              # hidden dirs are skipped
```

### Default: disabled

External plugins start **disabled**. Run `/plugin` to see what was discovered:

```
Installed plugins (3):
  git-helper      [user] enabled      Git convenience tools
  audit-tools     [external] disabled Compliance & audit helpers
  company-skills  [external] disabled Shared team prompts
```

Enable once — the decision persists to `~/.cheetahclaws/plugins.json` and survives restarts:

```
/plugin enable audit-tools
```

If the plugin declares `dependencies` in its manifest, pip packages are installed at enable time (that's your informed-consent point — nothing auto-installs silently during normal use).

### Name collisions

If the same plugin name exists in both installed (`USER`/`PROJECT`) and external scopes, the **installed** entry wins. Within external scopes, the **earliest** directory in `CHEETAHCLAWS_PLUGIN_PATH` wins — same semantics as `$PATH`.

### Maintenance

- `/plugin uninstall <name>` on an external plugin only drops CheetahClaws's enable-state record. **It never deletes the source directory** — that's the plugin author's to manage.
- `/plugin update <name>` is refused for externals (update the source directory directly, e.g. `git pull` in the shared repo).
- Malformed `plugin.json` files are logged to stderr and skipped; one broken manifest in the path cannot crash `/plugin`.

---

## Testing Your Plugin

### Manual testing

```bash
# Copy to user plugins
cp -r my-plugin ~/.cheetahclaws/plugins/my-plugin

# Start CheetahClaws
cheetahclaws

# Verify
/plugin                          # should show your plugin
/greet World                     # test your command
```

### Unit testing

```python
"""tests/test_my_plugin.py"""
import pytest
from my_plugin.tools import TOOL_DEFS, _my_tool


def test_tool_defs_structure():
    """Verify TOOL_DEFS exports are valid."""
    assert len(TOOL_DEFS) > 0
    for tdef in TOOL_DEFS:
        assert tdef.name
        assert tdef.schema.get("name") == tdef.name
        assert "input_schema" in tdef.schema
        assert callable(tdef.func)


def test_my_tool_returns_string():
    config = {"model": "test"}
    result = _my_tool({"query": "hello"}, config)
    assert isinstance(result, str)
    assert "hello" in result
```

---

## Publishing

1. Push your plugin to a public git repo
2. Users install with: `/plugin install <name>@<git-url>`
3. Consider naming your repo `cheetahclaws-<name>` for discoverability

### Checklist before publishing

- [ ] `plugin.json` has accurate `name`, `version`, `description`
- [ ] `TOOL_DEFS` list (not direct `register_tool()` calls)
- [ ] Graceful degradation for optional dependencies
- [ ] No hardcoded paths or API keys
- [ ] README with install instructions and usage examples
- [ ] Tested with `cheetahclaws` on Python 3.10+

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Calling `register_tool()` directly | Export `TOOL_DEFS` list instead — the loader registers for you |
| Importing `cheetahclaws` in plugin code | Use `config` parameter or `import runtime` for runtime state |
| Assuming hooks exist (`hook_session_start`, etc.) | No event-based hooks — use tool/command handlers instead |
| Putting runtime state in `config["_xxx"]` | Use `runtime.get_ctx(config)` for session state |
| Hardcoding file paths | Use `Path.home() / ".cheetahclaws"` or relative paths |

---

## Reference

- [CONTRIBUTING.md](../../CONTRIBUTING.md) — project architecture and conventions
- [Plugin loader source](../../plugin/loader.py) — how plugins are loaded
- [ToolDef source](../../tool_registry.py) — tool registration API
- [Example plugin](../../examples/example-plugin/) — minimal working template
