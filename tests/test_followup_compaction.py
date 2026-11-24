"""Tests for followup_compaction.py."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from followup_compaction import (
    compact_tool_history,
    compact_assistant_xml,
    compact_assistant_xml_selective,
    build_messages_for_api,
)


def _turn(user_text: str, tool_calls: list, tool_results: list) -> list:
    """Build [user, assistant+tool_calls, tool_result, tool_result, ...]."""
    msgs = [{"role": "user", "content": user_text}]
    msgs.append({"role": "assistant", "content": "ok", "tool_calls": tool_calls})
    msgs.extend(tool_results)
    return msgs


HEAVY = "X" * 5000
_TERM_ASST = {"role": "assistant", "content": "done"}


class TestCompactToolHistory:
    def test_removes_old_tool_messages(self):
        history = (
            _turn(
                "first question",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [{"role": "assistant", "content": "done", "tool_calls": []}]
            + _turn(
                "follow up",
                [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        prior_tools = [m for m in out if m.get("role") == "tool" and m.get("tool_call_id") == "t1"]
        assert len(prior_tools) == 0
        current_tools = [m for m in out if m.get("role") == "tool" and m.get("tool_call_id") == "t2"]
        assert len(current_tools) == 1
        assert current_tools[0]["content"] == HEAVY

    def test_strips_tool_calls_from_prior_assistant(self):
        history = (
            _turn(
                "first",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [_TERM_ASST]
            + [{"role": "user", "content": "follow"}]
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        prior_assistants = [m for m in out if m.get("role") == "assistant"]
        for a in prior_assistants:
            assert "tool_calls" not in a

    def test_current_turn_intact(self):
        history = (
            _turn(
                "first",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [_TERM_ASST]
            + _turn(
                "current",
                [{"id": "t2", "name": "Bash", "input": {"command": "ls"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Bash", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        assert out[-1]["content"] == HEAVY

    def test_keep_last_n_turns_1(self):
        history = (
            _turn(
                "first",
                [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
                [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
            )
            + [_TERM_ASST]
            + _turn(
                "second",
                [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}],
                [{"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY}],
            )
            + [_TERM_ASST]
            + _turn(
                "third (current)",
                [{"id": "t3", "name": "Read", "input": {"file_path": "c.py"}}],
                [{"role": "tool", "tool_call_id": "t3", "name": "Read", "content": HEAVY}],
            )
        )
        out = compact_tool_history(history, keep_last_n_turns=1)
        by_id = {m["tool_call_id"]: m for m in out if m.get("role") == "tool"}
        assert "t1" not in by_id
        assert by_id["t2"]["content"] == HEAVY
        assert by_id["t3"]["content"] == HEAVY

    def test_removes_empty_assistant_after_stripping(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            _TERM_ASST,
            {"role": "user", "content": "follow"},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        assert len(out) == 3
        assert out[0]["content"] == "first"
        assert out[1]["content"] == "done"
        assert out[2]["content"] == "follow"

    def test_non_destructive(self):
        original = _turn(
            "q",
            [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
            [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
        ) + [_TERM_ASST, {"role": "user", "content": "follow"}]
        snapshot_content = original[2]["content"]
        compact_tool_history(original, keep_last_n_turns=0)
        assert original[2]["content"] == snapshot_content
        assert original[2]["content"] == HEAVY

    def test_no_compaction_when_only_one_turn(self):
        history = _turn(
            "only",
            [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}],
            [{"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY}],
        )
        out = compact_tool_history(history, keep_last_n_turns=0)
        assert out[2]["content"] == HEAVY


class _FakeState:
    def __init__(self, messages):
        self.messages = messages
        self.compaction_log = []
        self.turn_count = 1


class TestBuildMessagesForApi:
    def test_mid_loop_compacts_prior_turns_keeps_current(self):
        """Mid-loop (last msg is tool): prior turn gets compacted, current turn intact."""
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "follow"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}]},
            {"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1, "t1 (prior turn) must be compacted, t2 (current turn) kept"
        assert HEAVY in tool_msgs[0]["content"]
        assert tool_msgs[0]["tool_call_id"] == "t2"

    def test_user_turn_compacts_prior_tools(self):
        """When last message is user (new turn), prior tool content is removed."""
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "ok", "tool_calls": [{"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "follow"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 0

    def test_audit_does_not_mutate_last_user_message(self):
        """The audit must live in the system volatile block, NOT be prepended to any user msg."""
        history = [
            {"role": "user", "content": "do stuff"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "b99", "name": "Bash", "input": {"command": "ls"}}
            ]},
            {"role": "tool", "tool_call_id": "b99", "name": "Bash", "content": "a" * 700},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        user_msg = next(m for m in result if m.get("role") == "user")
        assert user_msg["content"] == "do stuff"
        assert "Verbatim tool_results" not in user_msg["content"]


class TestCompactAssistantXml:
    def test_strips_xml_keeps_prose(self):
        content = (
            'Analysis here.\n\n'
            '<tool_use name="Read" id="r1"><param name="file_path">foo.py</param></tool_use>'
            '\n\nMore text.'
        )
        tool_calls = [{"id": "r1", "name": "Read", "input": {"file_path": "foo.py"}}]
        result = compact_assistant_xml(content, tool_calls)
        assert "Analysis here." in result
        assert "More text." in result
        assert '<tool_use ' not in result and '<tool_use name=' not in result
        assert '<tool_use_elided name="Read"' in result

    def test_no_xml_returns_unchanged(self):
        assert compact_assistant_xml("Just plain text, no XML.") == "Just plain text, no XML."

    def test_empty_content(self):
        assert compact_assistant_xml("") == ""

    def test_multiple_tool_calls(self):
        content = (
            '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
            '\ntext\n'
            '<tool_use name="Bash" id="b1"><param name="command">ls</param></tool_use>'
        )
        tool_calls = [
            {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}},
            {"id": "b1", "name": "Bash", "input": {"command": "ls"}},
        ]
        result = compact_assistant_xml(content, tool_calls)
        assert '<tool_use ' not in result and '<tool_use name=' not in result
        assert '<tool_use_elided name="Read"' in result
        assert '<tool_use_elided name="Bash"' in result
        assert "text" in result

    def test_no_tool_calls_list_falls_back_to_xml_name(self):
        content = '<tool_use name="Grep" id="g1"><param name="pattern">TODO</param></tool_use>'
        result = compact_assistant_xml(content, None)
        assert '<tool_use_elided name="Grep"' in result
        assert '<tool_use ' not in result and '<tool_use name=' not in result

    def test_cdata_in_params(self):
        content = (
            '<tool_use name="Write" id="w1">'
            '<param name="file_path"><![CDATA[test.py]]></param>'
            '<param name="content"><![CDATA[print("hello")]]></param>'
            '</tool_use>'
        )
        tool_calls = [{"id": "w1", "name": "Write", "input": {"file_path": "test.py"}}]
        result = compact_assistant_xml(content, tool_calls)
        assert '<tool_use_elided name="Write"' in result
        assert '<tool_use ' not in result and '<tool_use name=' not in result


class TestCompactAssistantXmlSelective:
    def test_only_targeted_ids_compacted(self):
        content = (
            '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
            '\ntext\n'
            '<tool_use name="Write" id="w1"><param name="file_path">b.py</param>'
            '<param name="content">big code</param></tool_use>'
        )
        tool_calls = [
            {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}},
            {"id": "w1", "name": "Write", "input": {"file_path": "b.py"}},
        ]
        result = compact_assistant_xml_selective(content, tool_calls, {"w1"})
        assert '<tool_use name="Read" id="r1">' in result
        assert '<tool_use_elided name="Write"' in result
        assert "big code" not in result
        assert "text" in result

    def test_empty_target_ids_unchanged(self):
        content = '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
        assert compact_assistant_xml_selective(content, [], set()) == content

    def test_no_xml_unchanged(self):
        assert compact_assistant_xml_selective("plain text", [], {"r1"}) == "plain text"

    def test_all_ids_targeted_same_as_full_compact(self):
        content = '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
        tool_calls = [{"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}]
        selective = compact_assistant_xml_selective(content, tool_calls, {"r1"})
        full = compact_assistant_xml(content, tool_calls)
        assert selective == full


class TestCompactToolHistoryAssistantXml:
    def test_old_assistant_xml_compacted(self):
        xml_content = (
            'Prose here.\n\n'
            '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
        )
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": xml_content, "tool_calls": [
                {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": HEAVY},
            _TERM_ASST,
            {"role": "user", "content": "follow up"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "r2", "name": "Read", "input": {"file_path": "b.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r2", "name": "Read", "content": HEAVY},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        prior_asst = out[1]
        assert '<tool_use ' not in prior_asst["content"] and '<tool_use name=' not in prior_asst["content"]
        assert "Prose here." in prior_asst["content"]
        assert '<tool_use_elided name="Read"' in prior_asst["content"]
        assert "tool_calls" not in prior_asst

    def test_current_turn_assistant_preserved(self):
        xml_content = '<tool_use name="Read" id="r2"><param name="file_path">b.py</param></tool_use>'
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": HEAVY},
            _TERM_ASST,
            {"role": "user", "content": "current"},
            {"role": "assistant", "content": xml_content, "tool_calls": [
                {"id": "r2", "name": "Read", "input": {"file_path": "b.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r2", "name": "Read", "content": HEAVY},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        current_asst = next(
            m for m in out
            if m.get("role") == "assistant" and m.get("tool_calls")
        )
        assert "<tool_use" in current_asst["content"]

    def test_assistant_without_tool_calls_unchanged(self):
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "just text, no tools"},
            {"role": "user", "content": "second"},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        assert out[1]["content"] == "just text, no tools"

    def test_non_destructive_for_assistant(self):
        xml_content = '<tool_use name="Read" id="r1"><param name="file_path">a.py</param></tool_use>'
        history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": xml_content, "tool_calls": [
                {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": HEAVY},
            _TERM_ASST,
            {"role": "user", "content": "follow"},
        ]
        compact_tool_history(history, keep_last_n_turns=0)
        assert history[1]["content"] == xml_content


class TestInterruptedTurnPreservation:
    """After Ctrl+C, the interrupted turn's tool results must survive compaction."""

    def test_interrupted_turn_not_compacted(self):
        """No terminal assistant before user2 -> not a valid boundary -> no compaction."""
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "after interrupt"},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        tool_msgs = [m for m in out if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == HEAVY

    def test_completed_then_interrupted_preserves_interrupted(self):
        """Completed turn compacted, interrupted turn preserved."""
        history = [
            {"role": "user", "content": "turn1"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "turn2"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t2", "name": "Bash", "input": {"command": "ls"}}
            ]},
            {"role": "tool", "tool_call_id": "t2", "name": "Bash", "content": HEAVY},
            {"role": "user", "content": "after interrupt"},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        by_id = {m["tool_call_id"]: m for m in out if m.get("role") == "tool"}
        assert "t1" not in by_id, "completed turn's tools should be compacted"
        assert "t2" in by_id, "interrupted turn's tools must be preserved"
        assert by_id["t2"]["content"] == HEAVY

    def test_multiple_interrupted_turns_all_preserved(self):
        """Two consecutive interrupted turns: neither is compacted."""
        history = [
            {"role": "user", "content": "turn1"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "turn2 after interrupt"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t2", "name": "Read", "input": {"file_path": "b.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t2", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "turn3 after interrupt"},
        ]
        out = compact_tool_history(history, keep_last_n_turns=0)
        tool_msgs = [m for m in out if m.get("role") == "tool"]
        assert len(tool_msgs) == 2, "both interrupted turns' tools must be preserved"

    def test_build_messages_preserves_interrupted(self):
        """build_messages_for_api preserves interrupted turn tool results."""
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok", "tool_calls": [
                {"id": "t1", "name": "Read", "input": {"file_path": "a.py"}}
            ]},
            {"role": "tool", "tool_call_id": "t1", "name": "Read", "content": HEAVY},
            {"role": "user", "content": "after ctrl+c"},
        ]
        state = _FakeState(history)
        result = build_messages_for_api(state, {})
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        assert len(tool_msgs) == 1
        assert tool_msgs[0]["content"] == HEAVY
