"""Proxy -- re-exports task classes from multi_agent.subagent."""
from .subagent import (
    SubAgentTask,
    _extract_final_text,
    _git_root,
    _create_worktree,
    _remove_worktree,
    _agent_run,
)

__all__ = ["SubAgentTask"]
