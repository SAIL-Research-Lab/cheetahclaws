"""Plugin install consent: git/pip installs show a summary and need a yes;
the installed commit is recorded."""
from __future__ import annotations

import json

import pytest

import cheetahclaws.plugin.store as _store
from cheetahclaws.plugin.types import PluginScope

URL = "https://example.com/evil/plugin.git"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(autouse=True)
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(_store, "USER_PLUGIN_DIR", tmp_path / "user_plugins")
    monkeypatch.setattr(_store, "USER_PLUGIN_CFG", tmp_path / "user_plugins.json")
    monkeypatch.setattr(_store, "_project_plugin_dir", lambda: tmp_path / "proj_plugins")
    monkeypatch.setattr(_store, "_project_plugin_cfg", lambda: tmp_path / "proj.json")
    monkeypatch.delenv(_store.INSTALL_YES_ENV, raising=False)
    pip_calls = []
    monkeypatch.setattr(_store, "_install_dependencies",
                        lambda deps: (pip_calls.append(list(deps)) or (True, "ok")))
    monkeypatch.setattr(_store, "_missing_dependencies", lambda deps: list(deps))
    monkeypatch.setattr(_store, "_git_head", lambda repo: SHA)

    def fake_clone(url, dest):
        dest.mkdir(parents=True)
        (dest / "plugin.json").write_text(json.dumps({
            "name": "evil", "version": "1.0", "description": "d",
            "tools": ["t"], "dependencies": ["requests-evil"]}))
        return True, "cloned"

    monkeypatch.setattr(_store, "_clone_plugin", fake_clone)
    return pip_calls


def test_declined_install_cleans_up_and_skips_pip(paths, tmp_path):
    seen = []
    ok, msg = _store.install_plugin(f"evil@{URL}", confirm=lambda s: seen.append(s) or False)
    assert not ok
    assert "--yes" in msg and _store.INSTALL_YES_ENV in msg
    assert URL in seen[0] and "requests-evil" in seen[0] and SHA[:12] in seen[0]
    assert paths == []
    assert not (tmp_path / "user_plugins" / "evil").exists()
    assert _store.get_plugin("evil") is None


def test_non_interactive_default_refuses(paths):
    # pytest's stdin is not a TTY → default confirm must say no, not block.
    ok, msg = _store.install_plugin(f"evil@{URL}")
    assert not ok and "not confirmed" in msg
    assert paths == []


def test_yes_flag_installs_and_records_commit(paths):
    ok, msg = _store.install_plugin(f"evil@{URL} --yes")
    assert ok, msg
    assert SHA[:12] in msg
    assert paths == [["requests-evil"]]
    entry = _store.get_plugin("evil")
    assert entry.commit == SHA
    saved = json.loads(_store.USER_PLUGIN_CFG.read_text())
    assert saved["plugins"]["evil"]["commit"] == SHA


def test_env_and_kwarg_consent(paths, monkeypatch):
    ok, _ = _store.install_plugin(f"evil@{URL}", assume_yes=True)
    assert ok
    _store.uninstall_plugin("evil")
    monkeypatch.setenv(_store.INSTALL_YES_ENV, "1")
    ok, _ = _store.install_plugin(f"evil@{URL}")
    assert ok


def test_confirm_callback_yes(paths):
    ok, _ = _store.install_plugin(f"evil@{URL}", confirm=lambda s: True)
    assert ok


def test_local_install_without_deps_needs_no_prompt(tmp_path):
    src = tmp_path / "local"
    src.mkdir()
    (src / "plugin.json").write_text(json.dumps({"name": "loc"}))
    ok, msg = _store.install_plugin(f"loc@{src}")
    assert ok, msg
