"""MultiEdit / ApplyPatch go through the same permission gates as Edit/Write."""
import pytest

from cheetahclaws import agent
from cheetahclaws.agent import _check_permission, _permission_desc, _permission_signature

PATCH_A = "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch\n"
PATCH_AB = ("*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n"
            "*** Delete File: b.py\n*** End Patch\n")


def _tc(name, inp):
    return {"id": "t1", "name": name, "input": inp}


def _cfg(mode):
    return {"permission_mode": mode, "auto_approve": False, "_session_id": "perm-test"}


@pytest.mark.parametrize("tc", [
    _tc("MultiEdit", {"file_path": "/tmp/x.py", "edits": [{"old_string": "a", "new_string": "b"}]}),
    _tc("ApplyPatch", {"patch": PATCH_A}),
])
def test_new_edit_tools_are_not_auto_approved_in_auto_or_plan(tc):
    assert _check_permission(tc, _cfg("auto")) is False
    assert _check_permission(tc, _cfg("plan")) is False


@pytest.mark.parametrize("name,inp", [
    ("MultiEdit", {"file_path": "/tmp/x.py", "edits": []}),
    ("ApplyPatch", {"patch": PATCH_A}),
])
def test_accept_edits_covers_new_edit_tools(name, inp):
    assert _check_permission(_tc(name, inp), _cfg("accept-edits")) is True


def test_apply_patch_signature_names_exact_file_set():
    s1 = _permission_signature(_tc("ApplyPatch", {"patch": PATCH_A}))
    s2 = _permission_signature(_tc("ApplyPatch", {"patch": PATCH_AB}))
    assert s1.startswith("ApplyPatch:") and s1 != s2 and s1 != "ApplyPatch"
    assert _permission_signature(_tc("ApplyPatch", {"patch": "garbage"})) == ""


def test_session_grant_for_one_patch_does_not_cover_another(monkeypatch):
    cfg = _cfg("auto")
    granted = {_permission_signature(_tc("ApplyPatch", {"patch": PATCH_A}))}
    monkeypatch.setattr(agent.runtime, "get_ctx",
                        lambda c: type("C", (), {"approved_sigs": granted, "plan_file": ""})())
    assert _check_permission(_tc("ApplyPatch", {"patch": PATCH_A}), cfg) is True
    assert _check_permission(_tc("ApplyPatch", {"patch": PATCH_AB}), cfg) is False


def test_permission_desc_summarises_patch():
    d = _permission_desc(_tc("ApplyPatch", {"patch": PATCH_AB}))
    assert "M a.py" in d and "D b.py" in d
