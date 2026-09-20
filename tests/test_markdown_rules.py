"""A Markdown `---` should not read as the app drawing a divider.

Models separate sections with `---` freely. Rich renders that as a full-width
horizontal rule, which lands mid-turn — between two tool-summary lines, say —
where it looks like CheetahClaws printed it rather than the answer containing
it. Rules are dropped by default and `markdown_rules=true` brings them back.

What must survive the stripping is the interesting part: a `---` is a rule
only in some positions, and in others it is a heading, a table or content.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from cheetahclaws.ui import render
from cheetahclaws.ui.render import _strip_thematic_breaks as strip


# ── Dropped ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rule", ["---", "***", "___", "- - -", "* * *",
                                  "-----------", "   ---", "--- "])
def test_a_thematic_break_is_dropped(rule):
    out = strip(f"before\n\n{rule}\n\nafter")
    assert rule.strip() not in out
    assert "before" in out and "after" in out


def test_a_rule_at_the_very_start_is_dropped():
    assert strip("---\n\ntext").strip() == "text"


def test_several_rules_all_go():
    out = strip("a\n\n---\n\nb\n\n***\n\nc")
    assert "---" not in out and "***" not in out
    assert all(x in out for x in ("a", "b", "c"))


# ── Kept: the same characters meaning something else ─────────────────────

def test_a_setext_h2_underline_survives():
    """`Title\\n---` is an H2 in CommonMark. Dropping the underline silently
    demotes the heading to body text."""
    text = "上海今天天气\n---\n晴,23°C"
    assert strip(text) == text


def test_a_rule_inside_a_fenced_code_block_survives():
    text = "```yaml\n---\nkey: value\n---\n```\nafter"
    assert strip(text) == text


def test_a_tilde_fence_is_honoured_too():
    text = "~~~\n---\n~~~\ntail"
    assert strip(text) == text


def test_a_table_separator_row_survives():
    text = "| 项目 | 数据 |\n| --- | --- |\n| 天气 | 晴 |"
    assert strip(text) == text


def test_a_bullet_list_survives():
    text = "- item one\n- item two\n- item three"
    assert strip(text) == text


def test_a_yaml_front_matter_style_pair_inside_code_survives():
    text = "text\n\n```\n---\na\n---\n```"
    assert strip(text) == text


def test_an_unterminated_fence_keeps_everything_after_it():
    """A truncated stream can end mid-fence; treat the rest as code rather
    than silently editing what is probably a code sample."""
    text = "intro\n\n```python\nx = 1\n---\nmore"
    assert strip(text) == text


def test_text_with_no_candidates_is_returned_unchanged():
    text = "just a sentence with no markup at all"
    assert strip(text) is text


# ── The toggle ───────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _restore_flag():
    before = render._MD_RULES
    yield
    render.set_markdown_rules(before)


def test_rules_are_off_by_default():
    from cheetahclaws.config import DEFAULTS
    assert DEFAULTS["markdown_rules"] is False


def test_turning_rules_on_leaves_the_markdown_alone():
    render.set_markdown_rules(True)
    out = render._make_renderable("a\n\n---\n\n**b**")
    source = getattr(out, "markup", out)
    assert "---" in source


def test_with_rules_off_the_renderable_has_no_rule():
    render.set_markdown_rules(False)
    out = render._make_renderable("a\n\n---\n\n**b**")
    source = getattr(out, "markup", out)
    assert "---" not in source
    assert "**b**" in source


def test_rich_renders_no_horizontal_line_once_stripped():
    """The end-to-end property: nothing in the painted output is a run of
    box/dash characters spanning the width."""
    pytest.importorskip("rich")
    from rich.console import Console
    render.set_markdown_rules(False)
    console = Console(width=40, file=open(os.devnull, "w"), record=True)
    console.print(render._make_renderable("数据来源:wttr.in\n\n---\n\n**下一段**"))
    painted = console.export_text()
    assert not any(len(ln.strip()) > 20 and set(ln.strip()) <= set("-─_*")
                   for ln in painted.splitlines()), painted
