---
name: mempalace
description: "MemPalace — Local AI memory with 96.6% recall. Semantic search, temporal knowledge graph, palace architecture (wings/rooms/drawers). Free, no cloud, no API keys."
version: 3.1.0
homepage: https://github.com/milla-jovovich/mempalace
user-invocable: true
triggers: ["/mempalace", "/palace"]
tools: [MempalaceSearch, MempalaceSave, MempalaceWakeUp, MempalaceKGQuery, MempalaceDiaryWrite]
---

# MemPalace — Local AI Memory for CheetahClaws

You have access to a local memory palace via bridge tools and/or MCP. The palace stores verbatim conversation history and a temporal knowledge graph — all on the user's machine, zero cloud, zero API calls.

## Architecture

- **Wings** = people or projects (e.g. `wing_alice`, `wing_myproject`)
- **Halls** = categories (facts, events, preferences, advice)
- **Rooms** = specific topics (e.g. `chromadb-setup`, `riley-school`)
- **Drawers** = individual memory chunks (verbatim text)
- **Knowledge Graph** = entity-relationship facts with time validity

## Protocol — FOLLOW THIS EVERY SESSION

1. **ON WAKE-UP**: Call `MempalaceWakeUp` to load palace overview (total drawers, wings, rooms).
2. **BEFORE RESPONDING** about any person, project, or past event: call `MempalaceSearch` FIRST. Never guess — verify from the palace.
3. **IF UNSURE** about a fact: say "let me check the palace" and query. Wrong is worse than slow.
4. **AFTER EACH SESSION**: Call `MempalaceDiaryWrite` to record what happened, what you learned, what matters.
5. **FOR CROSS-DOMAIN INSIGHTS**: Use `MempalaceKGQuery` with action `traverse` to walk the graph and find connected ideas.

## Bridge Tools (Direct Python — No MCP Needed)

These tools work out of the box once `mempalace` is pip-installed:

| Tool | Purpose |
|------|---------|
| `MempalaceWakeUp` | Load palace context at session start |
| `MempalaceSearch` | Semantic search across all memories |
| `MempalaceSave` | Store verbatim content into a wing/room |
| `MempalaceKGQuery` | Query knowledge graph (traverse/tunnels/stats) |
| `MempalaceDiaryWrite` | Write session diary entries |

## MCP Tools (Full Feature Set)

If you've also added the MemPalace MCP server, you get the complete toolset:

### Search & Browse
- `mempalace_search` — Semantic search. Always start here.
- `mempalace_check_duplicate` — Check if content already exists before filing.
- `mempalace_status` — Palace overview + AAAK dialect spec
- `mempalace_list_wings` — All wings with drawer counts
- `mempalace_list_rooms` — Rooms within a wing
- `mempalace_get_taxonomy` — Full wing/room/count tree

### Knowledge Graph (Temporal Facts)
- `mempalace_kg_query` — Query entity relationships with time filtering
- `mempalace_kg_add` — Add a fact: subject -> predicate -> object
- `mempalace_kg_invalidate` — Mark a fact as no longer true
- `mempalace_kg_timeline` — Chronological story of an entity
- `mempalace_kg_stats` — Graph overview

### Palace Graph (Cross-Domain Connections)
- `mempalace_traverse` — Walk from a room, find connected ideas
- `mempalace_find_tunnels` — Find rooms that bridge two wings
- `mempalace_graph_stats` — Graph connectivity overview

### Write
- `mempalace_add_drawer` — Store verbatim content (auto-duplicate-checks)
- `mempalace_delete_drawer` — Remove a drawer by ID
- `mempalace_diary_write` — Write a session diary entry
- `mempalace_diary_read` — Read recent diary entries

## Setup

### Quick Install (CheetahClaws Plugin)

```bash
cheetahclaws plugin install mempalace
```

### Manual Install

1. Install MemPalace:
```bash
pip install mempalace
```

2. Initialize a palace:
```bash
mempalace init ~/my-convos
mempalace mine ~/my-convos
```

3. Copy this plugin to `~/.cheetahclaws/plugins/mempalace/` or add to your project's `.cheetahclaws/plugins/`.

### CheetahClaws MCP Config

Add to `.cheetahclaws/mcp.json` for the full MCP toolset:

```json
{
  "mcpServers": {
    "mempalace": {
      "type": "stdio",
      "command": "python3",
      "args": ["-m", "mempalace.mcp_server"]
    }
  }
}
```

### Other MCP Hosts

```bash
# Claude Code
claude mcp add mempalace -- python -m mempalace.mcp_server

# Cursor — add to .cursor/mcp.json
# Codex — add to .codex/mcp.json
```

## Session Auto-Save Hooks

This plugin includes hooks for automatic memory persistence:

- **session_start**: Initializes palace tracking state
- **stop**: Every 15 exchanges, triggers auto-save checkpoint
- **precompact**: Emergency save before context compaction

Configure in `.cheetahclaws/hooks.json` or let the plugin system handle it.

## Tips

- Search is semantic (meaning-based), not keyword. "What did we discuss about database performance?" works better than "database".
- The knowledge graph stores typed relationships with time windows. Use it for facts about people and projects.
- Diary entries accumulate across sessions. Write one at the end of each conversation.
- Use `mempalace_check_duplicate` (MCP) or `MempalaceSearch` (bridge) before storing to avoid duplicates.
- The AAAK dialect (from `mempalace_status`) is a compressed notation. Expand codes mentally, treat *markers* as emotional context.

## License

[MemPalace](https://github.com/milla-jovovich/mempalace) is MIT licensed. Created by Milla Jovovich, Ben Sigman, Igor Lins e Silva, and contributors.
