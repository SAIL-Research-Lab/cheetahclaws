"""Tests for the two ways a task runs without stopping for approval.

``always_allow``  a per-signature grant ("!" at a prompt) that is written to
                  config, so the same command never prompts again — in this
                  session or any future one.
``auto_approve``  full autonomy ("/auto on", ``--auto``, or the last option
                  at a prompt): nothing is prompted at all, and the choice
                  survives a restart.

Both are deliberately beaten by ``manual`` and ``plan`` permission modes,
which are explicit "ask me / don't touch anything" requests.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import cheetahclaws.tools  # noqa: F401  (registers the built-in tools)
from cheetahclaws import permissions
from cheetahclaws.agent import _check_permission


def _tc(name: str, **inp) -> dict:
    return {"id": "t1", "name": name, "input": inp}


def _cfg(session_id: str, **extra) -> dict:
    cfg = {"permission_mode": "auto", "_session_id": session_id}
    cfg.update(extra)
    return cfg


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point config.save_config at a throwaway HOME so tests never touch
    the developer's real ~/.cheetahclaws/config.json."""
    from cheetahclaws import config as config_mod
    monkeypatch.setattr(config_mod, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", tmp_path / "config.json")
    return tmp_path / "config.json"


# ── Saved per-signature grants ───────────────────────────────────────────

def test_saved_grant_suppresses_the_prompt(isolated_config):
    cfg = _cfg("saved")
    tc = _tc("Bash", command="rm -rf build")
    assert _check_permission(tc, cfg) is False
    permissions.remember_signature("Bash:rm", cfg)
    assert _check_permission(tc, cfg) is True
    # …and covers the same program with different arguments
    assert _check_permission(_tc("Bash", command="rm /tmp/x"), cfg) is True
    # …but not a different one
    assert _check_permission(_tc("Bash", command="git push"), cfg) is False


def test_saved_grant_is_written_to_config(isolated_config):
    cfg = _cfg("persisted")
    assert permissions.remember_signature("Bash:pytest", cfg) is True
    assert permissions.remember_signature("Bash:pytest", cfg) is False  # idempotent
    saved = json.loads(isolated_config.read_text())
    assert saved["always_allow"] == ["Bash:pytest"]


def test_saved_grant_is_reread_from_a_fresh_session(isolated_config):
    """The point of "!" over "s": a new process inherits the grant."""
    permissions.remember_signature("Bash:pytest", _cfg("writer"))
    from cheetahclaws.config import load_config
    fresh = load_config()
    fresh["_session_id"] = "reader"
    assert _check_permission(_tc("Bash", command="pytest -q"), fresh) is True


def test_forgetting_a_saved_grant_restores_the_prompt(isolated_config):
    cfg = _cfg("forget")
    permissions.remember_signature("Edit:/repo/app.py", cfg)
    assert permissions.forget_signature("Edit:/repo/app.py", cfg) is True
    assert permissions.forget_signature("Edit:/repo/app.py", cfg) is False
    assert _check_permission(_tc("Edit", file_path="/repo/app.py"), cfg) is False


def test_forget_all_drops_every_saved_grant(isolated_config):
    cfg = _cfg("forget-all")
    permissions.extend_signatures(["Bash:pytest", "Bash:rm", "Bash:git push"], cfg)
    assert permissions.forget_all(cfg) == 3
    assert permissions.saved_signatures(cfg) == set()


def test_manual_mode_ignores_saved_grants(isolated_config):
    cfg = _cfg("manual-saved", permission_mode="manual")
    permissions.remember_signature("Bash:pytest", cfg)
    assert _check_permission(_tc("Bash", command="pytest -q"), cfg) is False


def test_a_hand_edited_scalar_does_not_crash(isolated_config):
    cfg = _cfg("scalar", always_allow="Bash:pytest")
    assert permissions.saved_signatures(cfg) == {"Bash:pytest"}
    assert _check_permission(_tc("Bash", command="pytest -q"), cfg) is True


# ── Autonomous mode ──────────────────────────────────────────────────────

@pytest.mark.parametrize("tc", [
    _tc("Write", file_path="/etc/hosts"),
    _tc("Edit", file_path="/repo/app.py"),
    _tc("Bash", command="rm -rf build"),
    _tc("Agent", prompt="do a thing"),
    _tc("mcp__server__do_thing"),
])
def test_autonomous_mode_runs_everything(tc, isolated_config):
    cfg = _cfg("yolo")
    assert _check_permission(tc, cfg) is False
    permissions.set_auto_approve(True, cfg)
    assert _check_permission(tc, cfg) is True


def test_autonomous_mode_is_persisted(isolated_config):
    """Asserted through load_config, not the file: `True` matches the default
    so save_config prunes the key — what has to survive is the behavior."""
    from cheetahclaws.config import load_config
    cfg = load_config()
    permissions.set_auto_approve(False, cfg)
    assert permissions.auto_approve_on(load_config()) is False
    permissions.set_auto_approve(True, cfg)
    assert permissions.auto_approve_on(load_config()) is True


def test_the_launch_flag_does_not_leak_into_the_saved_config(isolated_config):
    """`--auto` governs one run. A later save_config (from /model, say) must
    not turn autonomy on for every future session."""
    from cheetahclaws.config import save_config
    cfg = _cfg("flag")
    permissions.set_auto_approve(True, cfg, persist=False)
    assert permissions.auto_approve_on(cfg) is True
    save_config(cfg)
    assert json.loads(isolated_config.read_text()).get("auto_approve") is not True


def test_auto_off_wins_inside_a_session_launched_with_the_flag(isolated_config):
    cfg = _cfg("flag-off", auto_approve=True)
    permissions.set_auto_approve(False, cfg, persist=False)
    assert permissions.auto_approve_on(cfg) is False


@pytest.mark.parametrize("mode", ["manual", "plan"])
def test_explicit_ask_me_modes_override_autonomy(mode, isolated_config):
    """Autonomy is a convenience; "ask me everything" / "touch nothing" are
    requests, and a saved convenience must not silently undo them."""
    cfg = _cfg("override", permission_mode=mode, auto_approve=True)
    assert _check_permission(_tc("Write", file_path="/repo/app.py"), cfg) is False


def test_autonomy_does_not_reach_the_bash_hard_denylist():
    """The denylist lives at execution time, below the permission gate, so
    "approved" still does not mean "runs"."""
    from cheetahclaws.tools.shell import _bash_hard_denied
    assert _bash_hard_denied("rm -rf /") is not None
    assert _bash_hard_denied("pytest -q") is None


# ── The shipped default ──────────────────────────────────────────────────

def test_autonomy_is_the_default_out_of_the_box(isolated_config):
    """A fresh install carries the task through instead of stopping at an
    approval menu for every command it needs to run."""
    from cheetahclaws.config import load_config
    cfg = load_config()
    cfg["_session_id"] = "fresh"
    assert permissions.auto_approve_on(cfg) is True
    assert _check_permission(_tc("Bash", command="date; date -u"), cfg) is True
    assert _check_permission(_tc("Edit", file_path="/repo/app.py"), cfg) is True


def test_turning_the_prompts_back_on_persists(isolated_config):
    """`/auto off` is a real preference, not a per-session toggle — it has to
    survive the restart, otherwise the prompts come back the next launch."""
    from cheetahclaws.config import load_config
    cfg = load_config()
    permissions.set_auto_approve(False, cfg)
    fresh = load_config()
    fresh["_session_id"] = "asked"
    assert permissions.auto_approve_on(fresh) is False
    assert _check_permission(_tc("Bash", command="rm -rf build"), fresh) is False


def test_the_ask_flag_does_not_erase_the_saved_preference(isolated_config):
    """`--ask` governs one run; it must not write `auto_approve: false` for
    every future session the way `/auto off` deliberately does."""
    from cheetahclaws.config import load_config, save_config
    cfg = load_config()
    permissions.set_auto_approve(False, cfg, persist=False)
    assert permissions.auto_approve_on(cfg) is False
    save_config(cfg)
    assert permissions.auto_approve_on(load_config()) is True


# ── Config persistence: defaults must stay defaults ──────────────────────

def test_save_config_only_writes_what_differs_from_the_defaults(isolated_config):
    """save_config used to persist all ~76 keys, which froze every default
    into the file the first time anything saved — so a default changed in a
    later release reached new installs only, never existing users."""
    from cheetahclaws.config import DEFAULTS, save_config
    cfg = dict(DEFAULTS)
    cfg["model"] = "claude-opus-5"
    save_config(cfg)
    written = json.loads(isolated_config.read_text())
    assert written["model"] == "claude-opus-5"
    assert "verbose" not in written          # still at its default
    assert "auto_approve" not in written


def test_a_saved_config_still_loads_identically(isolated_config):
    from cheetahclaws.config import DEFAULTS, load_config, save_config
    cfg = dict(DEFAULTS)
    cfg["model"] = "claude-opus-5"
    cfg["always_allow"] = ["Bash:pytest"]
    save_config(cfg)
    loaded = load_config()
    for k in DEFAULTS:
        assert loaded[k] == cfg[k], k


def test_a_deliberate_auto_off_survives_the_pruning(isolated_config):
    """`False` differs from the `True` default, so it is written and kept —
    the pruning must not swallow a real preference."""
    from cheetahclaws.config import load_config
    cfg = load_config()
    permissions.set_auto_approve(False, cfg)
    assert json.loads(isolated_config.read_text())["auto_approve"] is False
    assert permissions.auto_approve_on(load_config()) is False


# ── Migration off the frozen default ─────────────────────────────────────

def test_an_inherited_auto_approve_false_is_migrated_away(isolated_config):
    """A config written before autonomy became the default carries
    `auto_approve: false` that nobody chose. Drop it once, so the new default
    actually applies."""
    isolated_config.write_text(json.dumps({
        "model": "deepseek-v4-flash",
        "auto_approve": False,
        "always_allow": ["Bash:date;"],
    }))
    from cheetahclaws.config import load_config
    cfg = load_config()
    assert permissions.auto_approve_on(cfg) is True
    assert cfg["model"] == "deepseek-v4-flash"        # real settings untouched
    # …and the dead grant the old signature builder wrote goes with it: it
    # carries a shell operator, so it can never match a current signature.
    assert cfg["always_allow"] == []


def test_migration_keeps_grants_that_can_still_match(isolated_config):
    isolated_config.write_text(json.dumps({
        "auto_approve": False,
        "always_allow": ["Bash:date;", "Bash:pytest", "Edit:/repo/app.py"],
    }))
    from cheetahclaws.config import load_config
    assert load_config()["always_allow"] == ["Bash:pytest", "Edit:/repo/app.py"]


def test_the_migration_runs_once_not_on_every_launch(isolated_config):
    """After migrating, a deliberate `/auto off` must stick — re-running the
    migration would silently undo it on the next launch."""
    isolated_config.write_text(json.dumps({"auto_approve": False}))
    from cheetahclaws.config import load_config
    cfg = load_config()
    assert permissions.auto_approve_on(cfg) is True
    assert json.loads(isolated_config.read_text())["config_version"] == 2

    permissions.set_auto_approve(False, cfg)
    assert permissions.auto_approve_on(load_config()) is False
    assert permissions.auto_approve_on(load_config()) is False


def test_migration_leaves_a_fresh_install_alone(isolated_config):
    from cheetahclaws.config import load_config
    assert permissions.auto_approve_on(load_config()) is True


# ── Signatures name the program, not a shell fragment ────────────────────

@pytest.mark.parametrize("cmd,expected", [
    # `shlex.split` glues the operator to the token: "date;" matched nothing
    ("date; date -u; TZ=Asia/Shanghai date", "Bash:date"),
    ("curl -s a ; echo ---; curl -s b",      "Bash:curl"),
    ("TZ=UTC date",                          "Bash:date"),
    ("git push origin main",                 "Bash:git push"),
    ("; ; ;",                                "Bash"),
])
def test_signature_names_the_program(cmd, expected):
    from cheetahclaws.agent import _permission_signature
    assert _permission_signature(_tc("Bash", command=cmd)) == expected


def test_a_grant_made_for_a_chained_command_actually_applies(isolated_config):
    """The whole point of "!": the next run of that command must not prompt."""
    from cheetahclaws.agent import _permission_signature
    cfg = _cfg("chained")
    tc = _tc("Bash", command="date; date -u; TZ=Asia/Shanghai date")
    permissions.remember_signature(_permission_signature(tc), cfg)
    assert _check_permission(tc, cfg) is True
    assert _check_permission(_tc("Bash", command="date +%s"), cfg) is True


# ── The prompt's new answers ─────────────────────────────────────────────

def test_answering_bang_saves_the_grant(monkeypatch, isolated_config):
    from cheetahclaws import cli
    monkeypatch.setattr(cli, "ask_input_interactive", lambda *a, **k: "!")
    cfg = _cfg("prompt-bang")
    assert cli.ask_permission_interactive("Run: rm -rf build", cfg, "Bash:rm") is True
    assert "Bash:rm" in permissions.saved_signatures(cfg)
    # this is a narrow grant, not a mode change
    assert cfg["permission_mode"] == "auto"
    assert permissions.auto_approve_on(cfg) is False


def test_answering_auto_turns_on_autonomy(monkeypatch, isolated_config):
    from cheetahclaws import cli
    monkeypatch.setattr(cli, "ask_input_interactive", lambda *a, **k: "auto")
    cfg = _cfg("prompt-auto")
    assert cli.ask_permission_interactive("Run: rm -rf build", cfg, "Bash:rm") is True
    assert permissions.auto_approve_on(cfg) is True


def test_answering_a_is_still_accept_all_not_autonomy(monkeypatch, isolated_config):
    """"a" and "auto" sit next to each other in the menu; the session-only
    one must not be upgraded to the persisted one by accident."""
    from cheetahclaws import cli
    monkeypatch.setattr(cli, "ask_input_interactive", lambda *a, **k: "a")
    cfg = _cfg("prompt-a")
    assert cli.ask_permission_interactive("Run: rm -rf build", cfg, "Bash:rm") is True
    assert cfg["permission_mode"] == "accept-all"
    assert permissions.auto_approve_on(cfg) is False


def test_every_menu_digit_resolves_to_a_distinct_answer():
    """The terminal/Slack/WeChat menus are answered by number, so no two
    options may collapse onto the same canonical value."""
    from cheetahclaws.tools.interaction import _build_value_map
    options = [("✅ Approve", "y"), ("❌ Reject", "n"),
               ("🔁 Always allow Bash:rm (this session)", "s"),
               ("💾 Always allow Bash:rm (remember forever)", "!"),
               ("✅✅ Accept all (this session)", "a"),
               ("🚀 Auto-run everything from now on", "auto")]
    table = _build_value_map(options)
    assert [table[str(i)] for i in range(1, 7)] == ["y", "n", "s", "!", "a", "auto"]


# ── /auto command ────────────────────────────────────────────────────────

def test_auto_command_toggles_and_reports(isolated_config, capsys):
    from cheetahclaws.commands.config_cmd import cmd_auto
    cfg = _cfg("cmd")
    cmd_auto("on", None, cfg)
    assert permissions.auto_approve_on(cfg) is True
    cmd_auto("", None, cfg)
    assert "ON" in capsys.readouterr().out
    cmd_auto("off", None, cfg)
    assert permissions.auto_approve_on(cfg) is False


def test_auto_command_warns_when_a_mode_overrides_it(isolated_config, capsys):
    from cheetahclaws.commands.config_cmd import cmd_auto
    cfg = _cfg("cmd-warn", permission_mode="plan")
    cmd_auto("on", None, cfg)
    assert "plan" in capsys.readouterr().out


def test_permissions_forget_drops_saved_grants(isolated_config, capsys):
    from cheetahclaws.commands.config_cmd import cmd_permissions
    cfg = _cfg("perm-forget")
    cmd_permissions("allow Bash:pytest Bash:rm", None, cfg)
    assert permissions.saved_signatures(cfg) == {"Bash:pytest", "Bash:rm"}
    cmd_permissions("forget Bash:rm", None, cfg)
    assert permissions.saved_signatures(cfg) == {"Bash:pytest"}
    cmd_permissions("forget all", None, cfg)
    assert permissions.saved_signatures(cfg) == set()


def test_permissions_clear_still_only_touches_session_grants(isolated_config):
    """`clear` is the session escape hatch; forgetting a saved grant is a
    separate, more deliberate act."""
    from cheetahclaws.commands.config_cmd import cmd_permissions
    from cheetahclaws import runtime
    cfg = _cfg("perm-clear")
    permissions.remember_signature("Bash:pytest", cfg)
    runtime.get_ctx(cfg).approved_sigs.add("Bash:git push")
    cmd_permissions("clear", None, cfg)
    assert runtime.get_ctx(cfg).approved_sigs == set()
    assert permissions.saved_signatures(cfg) == {"Bash:pytest"}
