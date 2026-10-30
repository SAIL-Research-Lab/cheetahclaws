"""Tests for the permission gate: what runs silently vs what asks.

The rule under test: in the default ``auto`` mode a tool call is prompted
only when it can change the user's files, execute arbitrary code, or reach
outside the session. Reads, read-only shell pipelines, and CheetahClaws'
own session state (tasks, memories, skills) run straight through — and a
"session grant" ("s" at a prompt) suppresses repeats of one specific
command or file without going all the way to accept-all.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import cheetahclaws.tools  # noqa: F401  (registers the built-in tools)
from cheetahclaws import runtime
from cheetahclaws.agent import (
    _check_permission, _permission_signature, _tool_is_read_only,
)
from cheetahclaws.tools.security import _is_safe_bash


def _tc(name: str, **inp) -> dict:
    return {"id": "t1", "name": name, "input": inp}


def _cfg(session_id: str, **extra) -> dict:
    cfg = {"permission_mode": "auto", "_session_id": session_id}
    cfg.update(extra)
    return cfg


# ── Read-only shell vocabulary ───────────────────────────────────────────

@pytest.mark.parametrize("cmd", [
    "ls -la",
    "cat README.md",
    "git log --oneline -20",
    "git status --porcelain",
    "git diff --stat",
    "git config --get user.email",
    "git stash list",
    "wc -l setup.py",
    "find . -name '*.py'",
    "stat pyproject.toml",
    "jq '.name' package.json",
    "docker ps -a",
    "kubectl get pods",
    "pip list",
    "cargo tree",
    "sed -n '1,20p' README.md",
    "tar -tzf pkg.tar.gz",
    "cat < input.txt",
])
def test_read_only_commands_run_without_asking(cmd):
    assert _is_safe_bash(cmd) is True


@pytest.mark.parametrize("cmd", [
    "git log | head -20",
    "ls -la | grep test",
    "ps aux | grep python",
    "df -h | sort -k5 -r | head -5",
    "grep -rn TODO src/ | wc -l",
])
def test_read_only_pipelines_run_without_asking(cmd):
    """A pipeline of read-only stages is still read-only — the old check
    rejected every `|`, which prompted for the most common inspection idiom
    in the codebase."""
    assert _is_safe_bash(cmd) is True


@pytest.mark.parametrize("cmd", [
    # a safe-looking prefix followed by a destructive command
    "ls && rm -rf build",
    "ls; rm -rf /tmp/x",
    "cat f | tee out.txt",
    "echo hi > file.txt",
    "echo hi >> file.txt",
    # command substitution / backgrounding / subshells
    "echo `whoami`",
    "echo $(rm -rf /)",
    "ls &",
    # arbitrary code execution
    "python script.py",
    "python -c 'import os; os.system(\"rm -rf /\")'",
    "node server.js",
    "bash script.sh",
    "awk '{print $1}' f",
    "xargs rm < list.txt",
    "env FOO=1 rm -rf /",
    "sudo ls",
    "make test",
    "pytest -q",
    # read-only programs turned mutating by a flag
    "find . -name '*.log' -delete",
    "sed -i 's/a/b/' f.txt",
    "sort -o out.txt in.txt",
    "curl -o out.bin https://example.com",
    "tar -xzf pkg.tar.gz",
    # write subcommands of otherwise-readable tools
    "git push origin main",
    "git commit -am wip",
    "git config user.email me@example.com",
    "npm install",
    "pip install requests",
    "docker run -it ubuntu",
    "kubectl delete pod x",
    # nothing to classify
    "",
    "   ",
])
def test_mutating_commands_still_ask(cmd):
    assert _is_safe_bash(cmd) is False


def test_interpreters_are_safe_only_for_info_flags():
    """`python --version` executes nothing; `python foo.py` executes anything."""
    assert _is_safe_bash("python --version") is True
    assert _is_safe_bash("python -V") is True
    assert _is_safe_bash("node --version") is True
    assert _is_safe_bash("python -c 'print(1)'") is False


@pytest.mark.parametrize("cmd", ["shutdown -h", "rm -v", "kill -9 1234",
                                 "systemctl restart nginx", "git clean -v"])
def test_short_flags_are_not_mistaken_for_info_flags(cmd):
    """`-h` halts on `shutdown` and `-v` is verbose almost everywhere, so an
    unknown program invoked with only short flags is not a version query."""
    assert _is_safe_bash(cmd) is False


def test_bash_safe_extra_extends_the_vocabulary():
    """Projects can add their own read-only commands via config."""
    assert _is_safe_bash("bazel-query //...") is False
    assert _is_safe_bash("bazel-query //...",
                         {"bash_safe_extra": ["bazel-query"]}) is True


def test_network_clients_need_an_explicit_opt_in():
    """`curl -I` reaches outside the session, so it is no longer read-only by
    default; bash_safe_extra brings it back with its header-only guard."""
    assert _is_safe_bash("curl -I https://example.com") is False
    cfg = {"bash_safe_extra": ["curl"]}
    assert _is_safe_bash("curl -I https://example.com", cfg) is True
    assert _is_safe_bash("curl -o x https://example.com", cfg) is False
    assert _is_safe_bash("curl -I https://example.com/$API_KEY", cfg) is False


def test_unbalanced_quotes_are_not_guessed_at():
    assert _is_safe_bash("ls 'unterminated") is False


# ── Tool-level classification ────────────────────────────────────────────

@pytest.mark.parametrize("name", [
    "Read", "Glob", "Grep", "WebFetch", "WebSearch",       # always were auto
    "GetDiagnostics", "TaskList", "TaskGet", "MemoryList", # newly auto
    "MemorySearch", "SkillList", "ListAgentTypes", "SummarizeLargeFile",
])
def test_read_only_tools_are_auto_approved(name):
    """Auto-approval reads ToolDef.read_only from the registry instead of a
    hardcoded five-name list, so every read-only tool is covered."""
    assert _tool_is_read_only(name) is True
    assert _check_permission(_tc(name), _cfg("ro")) is True


@pytest.mark.parametrize("name", ["TaskCreate", "TaskUpdate", "MemorySave",
                                  "Skill", "SleepTimer"])
def test_self_state_tools_are_auto_approved(name):
    """These mutate only CheetahClaws' own session state — no repo file, no
    shell, no network."""
    assert _check_permission(_tc(name), _cfg("self")) is True


@pytest.mark.parametrize("tc", [
    _tc("Write", file_path="/tmp/x.py"),
    _tc("Edit", file_path="/tmp/x.py"),
    _tc("NotebookEdit", notebook_path="/tmp/x.ipynb"),
    _tc("Bash", command="rm -rf build"),
    _tc("Agent", prompt="do a thing"),      # a sub-agent runs its own loop
    _tc("MemoryDelete", memory_id="x"),     # destroys user data
])
def test_state_changing_tools_still_ask(tc):
    assert _check_permission(tc, _cfg("ask")) is False


def test_unknown_tools_still_ask():
    """MCP / third-party tools are unclassified — they keep prompting."""
    assert _check_permission(_tc("mcp__someserver__do_thing"), _cfg("mcp")) is False


# ── Creating new files in the workspace ──────────────────────────────────

def test_creating_a_new_file_in_the_workspace_is_auto_approved(tmp_path, monkeypatch):
    """Nothing is overwritten and nothing outside the workspace is touched,
    so there is no decision for the user to make."""
    monkeypatch.chdir(tmp_path)
    cfg = _cfg("new-file")
    assert _check_permission(_tc("Write", file_path="src/new_module.py"), cfg) is True
    assert _check_permission(_tc("Write", file_path=str(tmp_path / "notes.md")), cfg) is True


def test_overwriting_an_existing_file_still_asks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / "app.py"
    existing.write_text("real content\n")
    assert _check_permission(_tc("Write", file_path=str(existing)),
                             _cfg("overwrite")) is False


def test_writing_outside_the_workspace_still_asks(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    outside = tmp_path / "elsewhere" / "x.py"
    assert _check_permission(_tc("Write", file_path=str(outside)),
                             _cfg("outside")) is False


@pytest.mark.parametrize("path", [
    ".github/workflows/ci.yml",   # runs in CI
    ".git/hooks/pre-commit",      # runs on every commit
    ".env",                       # trusted by other tools
    ".vscode/tasks.json",
])
def test_creating_dot_paths_still_asks(tmp_path, monkeypatch, path):
    """Hook/config locations are executed or trusted by other tools — creating
    one is a decision, not a formality."""
    monkeypatch.chdir(tmp_path)
    assert _check_permission(_tc("Write", file_path=path), _cfg("dotpath")) is False


def test_auto_create_files_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _cfg("no-auto-create", auto_create_files=False)
    assert _check_permission(_tc("Write", file_path="new.py"), cfg) is False


def test_allowed_root_bounds_the_auto_create_rule(tmp_path, monkeypatch):
    """When a sandbox root is configured it — not the cwd — is the boundary."""
    root = tmp_path / "sandbox"
    (root / "sub").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    cfg = _cfg("rooted", allowed_root=str(root))
    assert _check_permission(_tc("Write", file_path=str(root / "sub" / "a.py")), cfg) is True
    assert _check_permission(_tc("Write", file_path=str(tmp_path / "b.py")), cfg) is False


# ── Mode semantics are unchanged ─────────────────────────────────────────

def test_manual_mode_asks_even_for_reads():
    assert _check_permission(_tc("Read", file_path="x"),
                             _cfg("m", permission_mode="manual")) is False


def test_accept_all_never_asks():
    assert _check_permission(_tc("Bash", command="rm -rf build"),
                             _cfg("aa", permission_mode="accept-all")) is True


def test_accept_edits_preapproves_edits_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = _cfg("ae", permission_mode="accept-edits")
    assert _check_permission(_tc("Edit", file_path="x.py"), cfg) is True
    assert _check_permission(_tc("Bash", command="rm -rf build"), cfg) is False
    # Outside the workspace still asks, unless explicitly widened.
    assert _check_permission(_tc("Edit", file_path="/etc/x.py"), cfg) is False
    cfg["accept_edits_outside_workspace"] = True
    assert _check_permission(_tc("Edit", file_path="/etc/x.py"), cfg) is True


def test_plan_mode_refuses_writes_outside_the_plan_file():
    cfg = _cfg("plan", permission_mode="plan")
    runtime.get_ctx(cfg).plan_file = "/tmp/plan.md"
    assert _check_permission(_tc("Write", file_path="/tmp/plan.md"), cfg) is True
    assert _check_permission(_tc("Write", file_path="/tmp/other.py"), cfg) is False
    assert _check_permission(_tc("Bash", command="git log"), cfg) is True
    assert _check_permission(_tc("Bash", command="git push"), cfg) is False


# ── Session-scoped grants ────────────────────────────────────────────────

@pytest.mark.parametrize("tc,expected", [
    (_tc("Bash", command="git push origin main"), "Bash:git push"),
    (_tc("Bash", command="git push"),             "Bash:git push"),
    (_tc("Bash", command="pytest -q tests/"),     "Bash:pytest"),
    (_tc("Bash", command="/usr/bin/make test"),   "Bash:make test"),
    (_tc("Edit", file_path="/repo/app.py"),       "Edit:/repo/app.py"),
    (_tc("Agent", prompt="x"),                    "Agent"),
])
def test_permission_signature_is_coarse_but_not_sloppy(tc, expected):
    assert _permission_signature(tc) == expected


def test_session_grant_suppresses_repeats_of_the_same_command():
    cfg = _cfg("grant-cmd")
    tc = _tc("Bash", command="pytest -q")
    assert _check_permission(tc, cfg) is False
    runtime.get_ctx(cfg).approved_sigs.add(_permission_signature(tc))
    assert _check_permission(tc, cfg) is True
    # …and covers the same command with different arguments
    assert _check_permission(_tc("Bash", command="pytest tests/x.py -k foo"), cfg) is True
    # …but not a different program
    assert _check_permission(_tc("Bash", command="rm -rf build"), cfg) is False


def test_session_grant_for_one_file_does_not_cover_another():
    cfg = _cfg("grant-file")
    runtime.get_ctx(cfg).approved_sigs.add("Edit:/repo/app.py")
    assert _check_permission(_tc("Edit", file_path="/repo/app.py"), cfg) is True
    assert _check_permission(_tc("Edit", file_path="/repo/secrets.py"), cfg) is False


def test_session_grants_are_per_session():
    """A grant lives on the RuntimeContext, so another session never inherits it."""
    cfg_a, cfg_b = _cfg("sess-a"), _cfg("sess-b")
    runtime.get_ctx(cfg_a).approved_sigs.add("Bash:pytest")
    assert _check_permission(_tc("Bash", command="pytest -q"), cfg_a) is True
    assert _check_permission(_tc("Bash", command="pytest -q"), cfg_b) is False


def test_manual_mode_ignores_session_grants():
    """Explicitly asking for every call must not be overridden by a grant
    made earlier under a laxer mode."""
    cfg = _cfg("sess-manual", permission_mode="manual")
    runtime.get_ctx(cfg).approved_sigs.add("Bash:pytest")
    assert _check_permission(_tc("Bash", command="pytest -q"), cfg) is False


def test_answering_s_records_the_grant(monkeypatch):
    """The prompt's "s" option stores the signature on the session context."""
    from cheetahclaws import cli
    monkeypatch.setattr(cli, "ask_input_interactive", lambda *a, **k: "s")
    cfg = _cfg("prompt-s")
    granted = cli.ask_permission_interactive("Run: pytest -q", cfg, "Bash:pytest")
    assert granted is True
    assert "Bash:pytest" in runtime.get_ctx(cfg).approved_sigs
    # and the blunt instrument is untouched — this is not accept-all
    assert cfg["permission_mode"] == "auto"


def test_two_arg_permission_handlers_still_work(monkeypatch):
    """A bridge/plugin override that predates the `signature` argument must
    still be *called* — passing it three positionals raises a TypeError the
    callers swallow, which silently denies the tool instead of asking."""
    from cheetahclaws import cli
    from cheetahclaws.agent import PermissionRequest
    calls = []

    def legacy_handler(desc, cfg):        # no `signature` parameter
        calls.append(desc)
        return True

    monkeypatch.setattr(cli, "ask_permission_interactive", legacy_handler)
    ev = PermissionRequest(description="Run: pytest -q", signature="Bash:pytest")
    assert cli._ask_permission_event(ev, _cfg("legacy")) is True
    assert calls == ["Run: pytest -q"]


def test_signature_reaches_handlers_that_accept_it(monkeypatch):
    from cheetahclaws import cli
    from cheetahclaws.agent import PermissionRequest
    seen = {}

    def new_handler(desc, cfg, signature=""):
        seen["signature"] = signature
        return True

    monkeypatch.setattr(cli, "ask_permission_interactive", new_handler)
    ev = PermissionRequest(description="Run: pytest -q", signature="Bash:pytest")
    assert cli._ask_permission_event(ev, _cfg("modern")) is True
    assert seen["signature"] == "Bash:pytest"


def test_answering_a_still_flips_to_accept_all(monkeypatch):
    from cheetahclaws import cli
    monkeypatch.setattr(cli, "ask_input_interactive", lambda *a, **k: "a")
    cfg = _cfg("prompt-a")
    assert cli.ask_permission_interactive("Run: pytest -q", cfg, "Bash:pytest") is True
    assert cfg["permission_mode"] == "accept-all"


def test_permissions_clear_drops_session_grants():
    from cheetahclaws.commands.config_cmd import cmd_permissions
    cfg = _cfg("clear-me")
    runtime.get_ctx(cfg).approved_sigs.update({"Bash:pytest", "Edit:/repo/app.py"})
    cmd_permissions("clear", None, cfg)
    assert runtime.get_ctx(cfg).approved_sigs == set()
