from __future__ import annotations

import pytest
from pathlib import Path

import cheetahclaws.skill.loader as _loader
from cheetahclaws.skill.loader import _parse_skill_file, _parse_list_field, find_skill, SkillDef
from cheetahclaws.skill import load_skills, substitute_arguments


COMMIT_MD = """\
---
name: commit
description: Create a git commit
triggers: [/commit, commit changes]
tools: [Bash, Read]
---
Review staged changes and create a commit with a descriptive message.
"""

REVIEW_MD = """\
---
name: review
description: Review a pull request
triggers: [/review, /review-pr]
tools: [Bash, Read, Grep]
---
Analyze the PR diff and provide constructive feedback.
"""

ARGS_MD = """\
---
name: deploy
description: Deploy to an environment
triggers: [/deploy]
tools: [Bash]
argument-hint: [env] [version]
arguments: [env, version]
---
Deploy $VERSION to $ENV environment. Full args: $ARGUMENTS
"""


@pytest.fixture()
def skill_dir(tmp_path, monkeypatch):
    """Create a temp skill directory with sample skills and patch _get_skill_paths."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "commit.md").write_text(COMMIT_MD, encoding="utf-8")
    (skills_dir / "review.md").write_text(REVIEW_MD, encoding="utf-8")
    (skills_dir / "deploy.md").write_text(ARGS_MD, encoding="utf-8")

    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [skills_dir])
    # Also patch the builtin list to be empty so tests are predictable
    monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
    return skills_dir


# ------------------------------------------------------------------
# _parse_list_field
# ------------------------------------------------------------------

def test_parse_list_field_bracket():
    assert _parse_list_field("[a, b, c]") == ["a", "b", "c"]


def test_parse_list_field_plain():
    assert _parse_list_field("a, b, c") == ["a", "b", "c"]


def test_parse_list_field_single():
    assert _parse_list_field("solo") == ["solo"]


# ------------------------------------------------------------------
# _parse_skill_file
# ------------------------------------------------------------------

def test_parse_skill_file(skill_dir):
    path = skill_dir / "commit.md"
    skill = _parse_skill_file(path)
    assert skill is not None
    assert skill.name == "commit"
    assert skill.description == "Create a git commit"
    assert "/commit" in skill.triggers
    assert "commit changes" in skill.triggers
    assert "Bash" in skill.tools
    assert "Read" in skill.tools
    assert "commit" in skill.prompt.lower()
    assert skill.file_path == str(path)


def test_parse_skill_file_review(skill_dir):
    path = skill_dir / "review.md"
    skill = _parse_skill_file(path)
    assert skill is not None
    assert skill.name == "review"
    assert "/review" in skill.triggers
    assert "/review-pr" in skill.triggers


def test_parse_skill_file_invalid(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("no frontmatter here", encoding="utf-8")
    assert _parse_skill_file(bad) is None


def test_parse_skill_file_no_name(tmp_path):
    no_name = tmp_path / "noname.md"
    no_name.write_text("---\ndescription: test\n---\nbody\n", encoding="utf-8")
    assert _parse_skill_file(no_name) is None


def test_parse_skill_file_context_fork(tmp_path):
    fork_md = tmp_path / "fork.md"
    fork_md.write_text("---\nname: fork-task\ndescription: test\ncontext: fork\n---\nbody\n")
    skill = _parse_skill_file(fork_md)
    assert skill is not None
    assert skill.context == "fork"


def test_parse_skill_file_allowed_tools(tmp_path):
    md = tmp_path / "t.md"
    md.write_text("---\nname: myskill\ndescription: d\nallowed-tools: [Bash, Read]\n---\nbody\n")
    skill = _parse_skill_file(md)
    assert skill is not None
    assert "Bash" in skill.tools
    assert "Read" in skill.tools


# ------------------------------------------------------------------
# load_skills
# ------------------------------------------------------------------

def test_load_skills(skill_dir):
    skills = load_skills()
    assert len(skills) == 3
    names = {s.name for s in skills}
    assert names == {"commit", "review", "deploy"}


def test_load_skills_empty_dir(tmp_path, monkeypatch):
    empty = tmp_path / "empty_skills"
    empty.mkdir()
    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [empty])
    monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
    assert load_skills() == []


def test_load_skills_nonexistent_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [tmp_path / "does_not_exist"])
    monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
    assert load_skills() == []


def test_load_skills_builtins_present(monkeypatch):
    """Without patching, builtins (commit, review) should be present."""
    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [])
    skills = load_skills()
    names = {s.name for s in skills}
    assert "commit" in names
    assert "review" in names


def test_load_skills_project_overrides_builtin(tmp_path, monkeypatch):
    """A project skill with the same name overrides the builtin."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    # project-level "commit" with different description
    (skills_dir / "commit.md").write_text(
        "---\nname: commit\ndescription: OVERRIDDEN\n---\ncustom commit prompt\n"
    )
    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [skills_dir])
    skills = load_skills()
    commit = next(s for s in skills if s.name == "commit")
    assert commit.description == "OVERRIDDEN"


# ------------------------------------------------------------------
# find_skill
# ------------------------------------------------------------------

def test_find_skill_commit(skill_dir):
    skill = find_skill("/commit")
    assert skill is not None
    assert skill.name == "commit"


def test_find_skill_review(skill_dir):
    skill = find_skill("/review")
    assert skill is not None
    assert skill.name == "review"


def test_find_skill_review_pr(skill_dir):
    skill = find_skill("/review-pr some-pr-url")
    assert skill is not None
    assert skill.name == "review"


def test_find_skill_nonexistent(skill_dir):
    result = find_skill("/nonexistent")
    assert result is None


# ------------------------------------------------------------------
# substitute_arguments
# ------------------------------------------------------------------

def test_substitute_arguments_placeholder():
    result = substitute_arguments("Deploy $ARGUMENTS please", "v1.2 prod", [])
    assert result == "Deploy v1.2 prod please"


def test_substitute_named_args(tmp_path):
    result = substitute_arguments(
        "Deploy $VERSION to $ENV. Full args: $ARGUMENTS",
        "1.0 staging",
        ["env", "version"],
    )
    # arg_names are positional: env=1.0, version=staging
    assert "$VERSION" not in result
    assert "$ENV" not in result
    assert "$ARGUMENTS" not in result


def test_substitute_missing_arg():
    # If user provides fewer args than named slots, missing ones become ""
    result = substitute_arguments("Hello $NAME!", "", ["name"])
    assert result == "Hello !"


def test_substitute_no_placeholders():
    result = substitute_arguments("just a plain prompt", "some args", [])
    assert result == "just a plain prompt"


# ------------------------------------------------------------------
# _iter_skill_files (nested directory support)
# ------------------------------------------------------------------

from cheetahclaws.skill.loader import _iter_skill_files


def test_iter_skill_files_flat(skill_dir):
    files = list(_iter_skill_files(skill_dir))
    names = [f.name for f in files]
    assert "commit.md" in names
    assert "review.md" in names


def test_iter_skill_files_nested(tmp_path):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    nested = skill_dir / "myskill"
    nested.mkdir()
    (nested / "skill.md").write_text(
        "---\nname: myskill\ndescription: Nested\n---\nbody\n",
        encoding="utf-8",
    )
    files = list(_iter_skill_files(skill_dir))
    assert any("myskill" in str(f) for f in files)


def test_iter_skill_files_empty(tmp_path):
    assert list(_iter_skill_files(tmp_path / "nope")) == []


def test_load_skills_finds_nested(tmp_path, monkeypatch):
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()
    nested = skill_dir / "myskill"
    nested.mkdir()
    (nested / "skill.md").write_text(
        "---\nname: myskill\ndescription: Nested\n---\nbody\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(_loader, "_get_skill_paths", lambda: [skill_dir])
    monkeypatch.setattr(_loader, "_BUILTIN_SKILLS", [])
    skills = load_skills()
    assert any(s.name == "myskill" for s in skills)


# ------------------------------------------------------------------
# _skill_tool args normalization (#182)
# ------------------------------------------------------------------

from cheetahclaws.skill.tools import _skill_tool


def _fake_run(*args, **kwargs):
    class _Ev:
        text = "deployed to prod"
    yield _Ev()


def _call_skill(params):
    """Run _skill_tool against the deploy skill. A regression that raises will
    fail the test outright — that is the point of the suite."""
    return _skill_tool(params, {})


def test_skill_tool_coerces_dict_wrapped_single_value_args(skill_dir, monkeypatch):
    """#182: a model that wraps args in an object (`{"args": {...}}`) must not
    crash the Skill tool — take the single string value and proceed."""
    monkeypatch.setattr("cheetahclaws.agent.run", _fake_run)
    out = _call_skill({"name": "deploy", "args": {"args": "--env prod"}})
    assert "CRASH" not in out
    assert "deployed to prod" in out


def test_skill_tool_joins_list_args(skill_dir, monkeypatch):
    monkeypatch.setattr("cheetahclaws.agent.run", _fake_run)
    out = _call_skill({"name": "deploy", "args": ["--env", "prod"]})
    assert "CRASH" not in out
    assert "deployed to prod" in out


def test_skill_tool_rejects_multivalue_dict_with_clear_error(skill_dir, monkeypatch):
    """Multi-key dicts have no unambiguous string form — return an error the
    model can act on instead of a raw TypeError."""
    monkeypatch.setattr("cheetahclaws.agent.run", _fake_run)
    out = _call_skill({"name": "deploy", "args": {"env": "prod", "version": "1"}})
    assert "CRASH" not in out
    assert "must be a string" in out


def test_skill_tool_rejects_non_string_args(skill_dir, monkeypatch):
    monkeypatch.setattr("cheetahclaws.agent.run", _fake_run)
    out = _call_skill({"name": "deploy", "args": 123})
    assert "CRASH" not in out
    assert "must be a string" in out
