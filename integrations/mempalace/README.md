# MemPalace × CheetahClaws Integration

Give your CheetahClaws agent a persistent, semantic memory with 96.6% recall — no cloud, no API keys.

## Quick Start

```bash
# 1. Install MemPalace
pip install mempalace

# 2. Initialize a palace from your conversation history
mempalace init ~/my-convos
mempalace mine ~/my-convos

# 3. Install the CheetahClaws plugin
cheetahclaws plugin install mempalace
```

Done. Your CheetahClaws sessions now have semantic memory.

## What You Get

### Bridge Tools (Direct Python — No MCP Config Needed)

| Tool | What It Does |
|------|-------------|
| `MempalaceWakeUp` | Load palace context at session start |
| `MempalaceSearch` | Semantic search across all memories |
| `MempalaceSave` | Store verbatim content into a wing/room |
| `MempalaceKGQuery` | Query knowledge graph (traverse/tunnels/stats) |
| `MempalaceDiaryWrite` | Write session diary entries |

These work immediately after `pip install mempalace` — no MCP server configuration required.

### MCP Tools (Full Feature Set)

For the complete 19-tool MemPalace experience (knowledge graph CRUD, duplicate checking, diary read, AAAK dialect), add the MCP server to `.cheetahclaws/mcp.json`:

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

### Session Auto-Save Hooks

The plugin includes automatic memory persistence:

- **Session start**: Initializes palace tracking, runs wake-up
- **Every 15 exchanges**: Triggers auto-save checkpoint
- **Before compaction**: Emergency save of all context

## Architecture

MemPalace uses the **palace metaphor** for organizing memory:

- **Wings** = people or projects (`wing_alice`, `wing_myproject`)
- **Halls** = categories (facts, events, preferences, advice)
- **Rooms** = specific topics (`chromadb-setup`, `riley-school`)
- **Drawers** = individual memory chunks (verbatim text)
- **Knowledge Graph** = entity-relationship facts with time validity

All stored locally via ChromaDB. Zero cloud. Zero API calls.

## Manual Install

If you prefer not to use the plugin system:

```bash
# Copy to user plugins
cp -r integrations/mempalace ~/.cheetahclaws/plugins/mempalace

# Or to project plugins
cp -r integrations/mempalace .cheetahclaws/plugins/mempalace
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MEMPALACE_PALACE_PATH` | `~/.mempalace/palace` | Path to the ChromaDB palace |
| `MEMPAL_DIR` | *(none)* | Auto-ingest directory on session hooks |

## Compatibility

- CheetahClaws >= 0.1.0
- MemPalace >= 3.1.0
- Python 3.9+
- macOS, Linux, Windows

## Links

- [MemPalace GitHub](https://github.com/milla-jovovich/mempalace)
- [CheetahClaws GitHub](https://github.com/SafeRL-Lab/cheetahclaws)
- [MemPalace Benchmarks](https://github.com/milla-jovovich/mempalace#benchmarks)

## License

MemPalace is MIT licensed. Created by Milla Jovovich, Ben Sigman, Igor Lins e Silva, and contributors.
