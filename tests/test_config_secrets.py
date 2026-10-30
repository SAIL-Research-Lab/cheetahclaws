"""config.json secrecy: 0600 atomic writes, 0700 dir, env values not persisted;
daemon token created 0600 with no chmod race."""
from __future__ import annotations

import json
import os
import stat

import pytest

import cheetahclaws.config as config_mod


@pytest.fixture()
def cfg_home(tmp_path, monkeypatch):
    d = tmp_path / "cc"
    monkeypatch.setattr(config_mod, "CONFIG_DIR", d)
    monkeypatch.setattr(config_mod, "CONFIG_FILE", d / "config.json")
    monkeypatch.setattr(config_mod, "SESSIONS_DIR", d / "sessions")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ENDPOINT", raising=False)
    return d


def _mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def _saved(d):
    return json.loads((d / "config.json").read_text())


def test_save_creates_private_file_and_dir(cfg_home):
    config_mod.save_config({"model": "x", "qq_secret": "s3cret"})
    assert _mode(cfg_home) == 0o700
    assert _mode(cfg_home / "config.json") == 0o600
    assert _saved(cfg_home)["qq_secret"] == "s3cret"
    assert not [p for p in cfg_home.iterdir() if p.name.endswith(".tmp")]


def test_save_tightens_existing_loose_file(cfg_home):
    cfg_home.mkdir(mode=0o755)
    os.chmod(cfg_home, 0o755)
    f = cfg_home / "config.json"
    f.write_text("{}")
    os.chmod(f, 0o644)
    config_mod.save_config({"model": "x"})
    assert _mode(f) == 0o600
    assert _mode(cfg_home) == 0o700


def test_env_api_key_not_persisted(cfg_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-secret")
    monkeypatch.setenv("ANTHROPIC_ENDPOINT", "https://proxy.example")
    cfg = config_mod.load_config()
    assert cfg["anthropic_api_key"] == "sk-env-secret"
    config_mod.save_config(cfg)
    raw = (cfg_home / "config.json").read_text()
    assert "sk-env-secret" not in raw
    assert "proxy.example" not in raw


def test_env_key_dropped_even_without_tracking(cfg_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-secret")
    config_mod.save_config({"anthropic_api_key": "sk-env-secret"})
    assert "anthropic_api_key" not in _saved(cfg_home)


def test_user_set_key_still_persisted(cfg_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-secret")
    cfg = config_mod.load_config()
    cfg["anthropic_api_key"] = "sk-typed-by-user"
    config_mod.save_config(cfg)
    assert _saved(cfg_home)["anthropic_api_key"] == "sk-typed-by-user"


def test_env_endpoint_does_not_clobber_saved_endpoint(cfg_home, monkeypatch):
    config_mod.save_config({"anthropic_endpoint": "https://mine.example"})
    monkeypatch.setenv("ANTHROPIC_ENDPOINT", "https://env.example")
    cfg = config_mod.load_config()
    assert cfg["anthropic_endpoint"] == "https://env.example"
    config_mod.save_config(cfg)
    assert _saved(cfg_home)["anthropic_endpoint"] == "https://mine.example"


def test_env_tracking_key_not_written(cfg_home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    config_mod.save_config(config_mod.load_config())
    assert "_env_sourced" not in _saved(cfg_home)


# ── daemon token ──────────────────────────────────────────────────────────

def test_daemon_token_created_0600(tmp_path):
    from cheetahclaws.daemon import auth
    p = tmp_path / "d" / "token"
    tok = auth.load_or_create_token(p)
    assert _mode(p) == 0o600
    assert auth.load_or_create_token(p) == tok


def test_daemon_token_create_never_world_readable(tmp_path, monkeypatch):
    """The file must be opened 0600 — never written then chmod'ed."""
    from cheetahclaws.daemon import auth
    opened = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **k):
        opened.append(mode)
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(auth.os, "open", spy)
    old = os.umask(0)
    try:
        auth.load_or_create_token(tmp_path / "token")
        auth.rotate_token(tmp_path / "token")
    finally:
        os.umask(old)
    assert opened == [0o600, 0o600]
    assert _mode(tmp_path / "token") == 0o600


def test_daemon_token_lost_race_uses_existing(tmp_path, monkeypatch):
    from cheetahclaws.daemon import auth
    p = tmp_path / "token"

    def racing_write(path, token, *, exclusive):
        path.write_text("winner")
        raise FileExistsError

    monkeypatch.setattr(auth, "_write_token_file", racing_write)
    assert auth.load_or_create_token(p) == "winner"


def test_daemon_token_existing_loose_mode_tightened(tmp_path):
    from cheetahclaws.daemon import auth
    p = tmp_path / "token"
    p.write_text("abc")
    os.chmod(p, 0o644)
    assert auth.load_or_create_token(p) == "abc"
    assert _mode(p) == 0o600


def test_save_keeps_persisted_key_equal_to_env(tmp_path, monkeypatch):
    import json
    from cheetahclaws import config as cc
    cfile = tmp_path / "config.json"
    monkeypatch.setattr(cc, "CONFIG_FILE", cfile)
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path)
    cfile.write_text(json.dumps({"anthropic_api_key": "sk-same"}))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-same")
    cfg = cc.load_config()
    cfg["model"] = "x"
    cc.save_config(cfg)
    assert json.loads(cfile.read_text())["anthropic_api_key"] == "sk-same"
