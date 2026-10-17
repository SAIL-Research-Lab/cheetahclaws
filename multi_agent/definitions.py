"""Proxy -- re-exports agent definitions from multi_agent.subagent."""
from .subagent import (
    AgentDefinition,
    get_agent_definition,
    load_agent_definitions,
    _parse_agent_md,
    _BUILTIN_AGENTS,
)

__all__ = ["AgentDefinition", "get_agent_definition", "load_agent_definitions"]
