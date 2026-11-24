"""
MemPalace bridge tools for CheetahClaws.

Provides direct Python-access tools that wrap MemPalace's API — no MCP needed.
If mempalace is not installed, tools degrade gracefully with helpful install messages.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tool_registry import ToolDef, register_tool

_MEMPALACE_AVAILABLE = False
_palace_path = os.environ.get(
    "MEMPALACE_PALACE_PATH",
    str(Path.home() / ".mempalace" / "palace"),
)


def _check_mempalace() -> str | None:
    """Return None if mempalace is importable, else an error message."""
    global _MEMPALACE_AVAILABLE
    try:
        import mempalace  # noqa: F401
        _MEMPALACE_AVAILABLE = True
        return None
    except ImportError:
        return (
            "MemPalace is not installed. Install it with:\n"
            "  pip install mempalace\n"
            "Then initialize a palace:\n"
            "  mempalace init ~/my-project && mempalace mine ~/my-project"
        )


def _get_palace_path(params: dict) -> str:
    return params.get("palace_path", _palace_path)


# ── Tool: MempalaceSearch ──────────────────────────────────────────────────

def _mempalace_search(params: dict, config: dict) -> str:
    err = _check_mempalace()
    if err:
        return err

    from mempalace.searcher import search_memories

    result = search_memories(
        query=params["query"],
        palace_path=_get_palace_path(params),
        wing=params.get("wing"),
        room=params.get("room"),
        n_results=params.get("n_results", 5),
    )

    if "error" in result:
        return f"MemPalace search error: {result['error']}\nHint: {result.get('hint', 'Run mempalace init && mempalace mine')}"

    hits = result.get("results", [])
    if not hits:
        return f"No memories found for: \"{params['query']}\""

    lines = [f"MemPalace search: \"{params['query']}\"  ({len(hits)} results)\n"]
    for i, h in enumerate(hits, 1):
        lines.append(f"  [{i}] {h['wing']} / {h['room']}  (similarity: {h['similarity']})")
        lines.append(f"      Source: {h['source_file']}")
        for line in h["text"].strip().split("\n")[:20]:
            lines.append(f"      {line}")
        lines.append("")

    return "\n".join(lines)


# ── Tool: MempalaceSave ───────────────────────────────────────────────────

def _mempalace_save(params: dict, config: dict) -> str:
    err = _check_mempalace()
    if err:
        return err

    from mempalace.config import MempalaceConfig
    import chromadb

    palace_path = _get_palace_path(params)
    wing = params["wing"]
    room = params["room"]
    content = params["content"]
    hall = params.get("hall", "")
    source = params.get("source", "cheetahclaws")

    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        return (
            f"No palace found at {palace_path}.\n"
            "Initialize one first:\n"
            "  mempalace init <project-dir> && mempalace mine <project-dir>"
        )

    from datetime import datetime

    drawer_id = f"drawer_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{source}"
    meta = {
        "wing": wing,
        "room": room,
        "hall": hall,
        "source_file": source,
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    col.add(ids=[drawer_id], documents=[content], metadatas=[meta])

    return f"Saved to {wing} / {room} (drawer: {drawer_id})"


# ── Tool: MempalaceWakeUp ─────────────────────────────────────────────────

def _mempalace_wake_up(params: dict, config: dict) -> str:
    err = _check_mempalace()
    if err:
        return err

    from mempalace.config import MempalaceConfig
    import chromadb

    palace_path = _get_palace_path(params)

    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        return (
            f"No palace found at {palace_path}. "
            "Run: mempalace init <dir> && mempalace mine <dir>"
        )

    total = col.count()

    # Get wing/room breakdown
    wing_rooms: dict[str, dict[str, int]] = {}
    offset = 0
    while offset < total:
        batch = col.get(limit=1000, offset=offset, include=["metadatas"])
        for meta in batch["metadatas"]:
            w = meta.get("wing", "unknown")
            r = meta.get("room", "unknown")
            wing_rooms.setdefault(w, {}).setdefault(r, 0)
            wing_rooms[w][r] += 1
        if not batch["ids"]:
            break
        offset += len(batch["ids"])

    lines = [
        f"🏛️  MemPalace Wake-Up — {total} drawers across {len(wing_rooms)} wings",
        "",
    ]
    for wing, rooms in sorted(wing_rooms.items()):
        room_count = sum(rooms.values())
        room_names = ", ".join(f"{r}({c})" for r, c in sorted(rooms.items()))
        lines.append(f"  {wing}: {room_count} drawers — {room_names}")

    return "\n".join(lines)


# ── Tool: MempalaceKGQuery ────────────────────────────────────────────────

def _mempalace_kg_query(params: dict, config: dict) -> str:
    err = _check_mempalace()
    if err:
        return err

    from mempalace.palace_graph import traverse, find_tunnels, graph_stats

    palace_path = _get_palace_path(params)

    if params.get("action") == "traverse":
        result = traverse(params["room"], config=_make_config(palace_path))
    elif params.get("action") == "tunnels":
        result = find_tunnels(
            wing_a=params.get("wing_a"),
            wing_b=params.get("wing_b"),
            config=_make_config(palace_path),
        )
    elif params.get("action") == "stats":
        result = graph_stats(config=_make_config(palace_path))
    else:
        return "Action must be one of: traverse, tunnels, stats"

    return json.dumps(result, indent=2, default=str)


def _make_config(palace_path: str):
    from mempalace.config import MempalaceConfig
    cfg = MempalaceConfig()
    cfg.palace_path = palace_path
    return cfg


# ── Tool: MempalaceDiaryWrite ─────────────────────────────────────────────

def _mempalace_diary_write(params: dict, config: dict) -> str:
    err = _check_mempalace()
    if err:
        return err

    from mempalace.config import MempalaceConfig
    import chromadb
    from datetime import datetime

    palace_path = _get_palace_path(params)
    content = params["content"]
    session_id = params.get("session_id", "unknown")
    wing = params.get("wing", "wing_cheetahclaws")
    room = params.get("room", "session-diary")

    try:
        client = chromadb.PersistentClient(path=palace_path)
        col = client.get_collection("mempalace_drawers")
    except Exception:
        return f"No palace found at {palace_path}. Run: mempalace init <dir> && mempalace mine <dir>"

    drawer_id = f"diary_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id}"
    meta = {
        "wing": wing,
        "room": room,
        "hall": "diary",
        "source_file": f"cheetahclaws-session-{session_id}",
        "date": datetime.now().strftime("%Y-%m-%d"),
    }

    col.add(ids=[drawer_id], documents=[content], metadatas=[meta])

    return f"Diary entry saved to {wing} / {room} (id: {drawer_id})"


# ── Register all tools ─────────────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "MempalaceSearch",
        "description": (
            "Search MemPalace for memories using semantic search. "
            "Returns verbatim text from matching drawers with similarity scores. "
            "Optionally filter by wing (project) or room (aspect)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "wing": {
                    "type": "string",
                    "description": "Optional wing (project) filter, e.g. 'wing_myproject'",
                },
                "room": {
                    "type": "string",
                    "description": "Optional room (aspect) filter, e.g. 'api-design'",
                },
                "n_results": {
                    "type": "integer",
                    "description": "Number of results (default 5)",
                    "default": 5,
                },
                "palace_path": {
                    "type": "string",
                    "description": "Override palace path (default: ~/.mempalace/palace)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "MempalaceSave",
        "description": (
            "Save content to MemPalace. Files verbatim text into a wing/room drawer. "
            "Use this to persist conversation knowledge, decisions, or code snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "wing": {
                    "type": "string",
                    "description": "Wing name (project/domain), e.g. 'wing_myproject'",
                },
                "room": {
                    "type": "string",
                    "description": "Room name (aspect/topic), e.g. 'api-design'",
                },
                "content": {
                    "type": "string",
                    "description": "Verbatim content to store",
                },
                "hall": {
                    "type": "string",
                    "description": "Optional hall (sub-category)",
                },
                "source": {
                    "type": "string",
                    "description": "Source identifier (default: 'cheetahclaws')",
                },
                "palace_path": {
                    "type": "string",
                    "description": "Override palace path",
                },
            },
            "required": ["wing", "room", "content"],
        },
    },
    {
        "name": "MempalaceWakeUp",
        "description": (
            "Load MemPalace context for session start. Returns palace status: "
            "total drawers, wing/room breakdown. Run this at the start of each "
            "session to orient yourself with available memories."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "palace_path": {
                    "type": "string",
                    "description": "Override palace path",
                },
            },
        },
    },
    {
        "name": "MempalaceKGQuery",
        "description": (
            "Query MemPalace's knowledge graph. Three actions: "
            "'traverse' — walk the graph from a room, finding connected ideas; "
            "'tunnels' — find rooms that bridge two wings; "
            "'stats' — overall graph statistics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["traverse", "tunnels", "stats"],
                    "description": "Graph query action",
                },
                "room": {
                    "type": "string",
                    "description": "Starting room for traverse action",
                },
                "wing_a": {
                    "type": "string",
                    "description": "First wing for tunnels action",
                },
                "wing_b": {
                    "type": "string",
                    "description": "Second wing for tunnels action",
                },
                "palace_path": {
                    "type": "string",
                    "description": "Override palace path",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "MempalaceDiaryWrite",
        "description": (
            "Write a session diary entry to MemPalace. Use for auto-saving "
            "key decisions, context, and knowledge at session boundaries "
            "(compaction, stop, or periodic intervals)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Diary content to save (verbatim, be thorough)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session identifier",
                },
                "wing": {
                    "type": "string",
                    "description": "Wing to save under (default: wing_cheetahclaws)",
                },
                "room": {
                    "type": "string",
                    "description": "Room to save under (default: session-diary)",
                },
                "palace_path": {
                    "type": "string",
                    "description": "Override palace path",
                },
            },
            "required": ["content"],
        },
    },
]

_tool_funcs = {
    "MempalaceSearch": _mempalace_search,
    "MempalaceSave": _mempalace_save,
    "MempalaceWakeUp": _mempalace_wake_up,
    "MempalaceKGQuery": _mempalace_kg_query,
    "MempalaceDiaryWrite": _mempalace_diary_write,
}

_read_only = {"MempalaceSearch", "MempalaceWakeUp", "MempalaceKGQuery"}
_concurrent_safe = {"MempalaceSearch", "MempalaceWakeUp", "MempalaceKGQuery"}

for _schema in TOOL_SCHEMAS:
    _name = _schema["name"]
    register_tool(ToolDef(
        name=_name,
        schema=_schema,
        func=_tool_funcs[_name],
        read_only=_name in _read_only,
        concurrent_safe=_name in _concurrent_safe,
    ))
