"""Shared pytest fixtures.

Currently the only thing here is an autouse fixture that redirects the
research-lab default output directory to a per-session ``tmp_path`` so
running ``pytest`` does NOT pollute ``~/.cheetahclaws/research_papers/``
with little folders for every test that hits the orchestrator.

Any test that wants to write to a specific path (verifying directory
naming, etc.) can still pass ``output_dir=tmp_path / "papers"`` to
``write_markdown_report`` or ``output_root=...`` to ``run_one_lab_session``
— that explicit override takes precedence over the default we set
here.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_trust_and_bridge_auth(tmp_path, monkeypatch):
    """Keep workspace-trust state and bridge owner auto-binds out of the
    real ~/.cheetahclaws (trust.json / config.json)."""
    monkeypatch.delenv("CHEETAHCLAWS_TRUST_ALL", raising=False)
    try:
        from cheetahclaws import trust as _trust
        trust_file = tmp_path / "_trust" / "trust.json"
        monkeypatch.setattr(_trust, "_trust_file", lambda: trust_file)
        monkeypatch.setattr(_trust, "_saved_config_trust_all", lambda: False)
        _trust._warned.clear()
    except Exception:
        pass
    try:
        from cheetahclaws.bridges import auth as _bauth
        monkeypatch.setattr(_bauth, "_persist", lambda config: None)
        _bauth._last_refusal.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _isolate_lab_output_dir(tmp_path, monkeypatch):
    """Redirect DEFAULT_OUTPUT_DIR to a tmp dir for the duration of the
    test. Without this, tests calling ``run_one_lab_session(topic="t", …)``
    were creating real folders in ``~/.cheetahclaws/research_papers/``.

    Imported lazily so this file doesn't break test discovery if
    research/lab/ isn't on the import path (e.g. minimal CI matrices).
    """
    try:
        from cheetahclaws.research.lab import storage as _storage
    except Exception:
        return
    sandbox_root = tmp_path / "lab_test_papers"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(_storage, "DEFAULT_OUTPUT_DIR", sandbox_root)
    # output.py + sandbox.py both import the constant by reference,
    # so re-bind those module-level names too.
    try:
        from cheetahclaws.research.lab import output as _output
        monkeypatch.setattr(_output, "DEFAULT_OUTPUT_DIR", sandbox_root)
    except Exception:
        pass
