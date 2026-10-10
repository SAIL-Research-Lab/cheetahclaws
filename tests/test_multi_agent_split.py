"""Tests for multi_agent package split import paths (PR #51)."""
from multi_agent.subagent import (
    AgentDefinition,
    SubAgentManager,
    SubAgentTask,
    get_agent_definition,
    load_agent_definitions,
    _extract_final_text,
)


class TestSplitImportPaths:
    def test_definitions_reexports(self):
        from multi_agent.definitions import (
            AgentDefinition as AD,
            get_agent_definition as gad,
            load_agent_definitions as lad,
        )
        assert AD is AgentDefinition
        assert gad is get_agent_definition
        assert lad is load_agent_definitions

    def test_manager_reexports(self):
        from multi_agent.manager import SubAgentManager as SAM
        assert SAM is SubAgentManager

    def test_task_reexports(self):
        from multi_agent.task import SubAgentTask as SAT
        from multi_agent.task import _extract_final_text as eft
        assert SAT is SubAgentTask
        assert eft is _extract_final_text

    def test_backward_compat_root_shim(self):
        import subagent
        assert hasattr(subagent, 'SubAgentManager')
        assert hasattr(subagent, 'SubAgentTask')
        assert hasattr(subagent, 'AgentDefinition')


class TestAgentDefinitionsViaProxy:
    def test_builtin_agents(self):
        from multi_agent.definitions import load_agent_definitions
        agents = load_agent_definitions()
        for name in ("general-purpose", "coder", "reviewer", "researcher", "tester"):
            assert name in agents

    def test_get_valid(self):
        from multi_agent.definitions import get_agent_definition
        defn = get_agent_definition("coder")
        assert defn is not None
        assert defn.name == "coder"

    def test_get_unknown_returns_none(self):
        from multi_agent.definitions import get_agent_definition
        assert get_agent_definition("nonexistent_xyz") is None
