"""Workspace trust: don't run a repo's code just because you opened it.

Two project-level files can make cheetahclaws execute code on startup:

  * ``.mcp.json`` (found walking up from cwd) — stdio MCP servers are
    spawned as subprocesses by a background thread at import time.
  * ``.cheetahclaws/plugins.json`` — enabled plugins are ``exec_module``'d
    while the tool registry is built.

Neither is loaded until the user trusts the project. Trust is recorded in
``~/.cheetahclaws/trust.json`` (mode 0600)::

    {
      "version": 1,
      "projects":  {"/real/path/to/repo": {"trusted_at": 1730000000}},
      "approvals": {"/real/path/to/repo/.mcp.json": {"<server>": "<fp>"}, ...}
    }

``projects`` holds trusted roots (subdirectories inherit trust). ``approvals``
pins a fingerprint of every MCP server's command line / every plugin's
source+install_dir as it was when the user trusted it, so a later edit that
adds a server or changes a command needs re-approval.

User-level config (``~/.cheetahclaws/mcp.json``, user-scope plugins) is
always trusted. Escape hatches that restore the old load-everything
behaviour: env ``CHEETAHCLAWS_TRUST_ALL=1`` or config ``trust_all_projects:
true``.

Public API: is_trusted(path), trust(path), revoke(path), list_trusted(),
pending_untrusted(), is_mcp_server_approved(), is_plugin_approved(),
warn_untrusted_once().
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

TRUST_ENV = "CHEETAHCLAWS_TRUST_ALL"
TRUST_CONFIG_KEY = "trust_all_projects"

_lock = threading.RLock()
_warned: set[str] = set()


_VIA = "__via__"   # approvals key: trusted roots the approval was granted from


def _trust_file() -> Path:
    # Resolved at call time so tests (and HOME changes) are honoured.
    return Path.home() / ".cheetahclaws" / "trust.json"


def _real(path: str | os.PathLike | None) -> str:
    return os.path.realpath(os.path.expanduser(str(path if path is not None else os.getcwd())))


# ── Persistence ───────────────────────────────────────────────────────────

def _load() -> dict:
    p = _trust_file()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("projects", {})
            data.setdefault("approvals", {})
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"[trust] ignoring unreadable {p}: {exc}", file=sys.stderr)
    return {"version": 1, "projects": {}, "approvals": {}}


def _save(data: dict) -> None:
    p = _trust_file()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".trust.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Escape hatch ──────────────────────────────────────────────────────────

def trust_all_enabled(config: dict | None = None) -> bool:
    """True when the user opted out of workspace trust entirely."""
    if os.environ.get(TRUST_ENV, "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    if config is not None:
        return bool(config.get(TRUST_CONFIG_KEY))
    return _saved_config_trust_all()


def _saved_config_trust_all() -> bool:
    try:
        from cheetahclaws.config import CONFIG_FILE
        saved = json.loads(Path(CONFIG_FILE).read_text(encoding="utf-8"))
        return bool(isinstance(saved, dict) and saved.get(TRUST_CONFIG_KEY))
    except Exception:
        return False


# ── Trusted roots ─────────────────────────────────────────────────────────

def is_trusted(path: str | os.PathLike | None = None) -> bool:
    """Is ``path`` (default cwd) inside a trusted project root?"""
    if trust_all_enabled():
        return True
    real = _real(path)
    projects = _load()["projects"]
    p = Path(real)
    for cand in (p, *p.parents):
        if str(cand) in projects:
            return True
    return False


def list_trusted() -> list[str]:
    return sorted(_load()["projects"])


def trust(path: str | os.PathLike | None = None) -> dict:
    """Trust ``path`` (default cwd) and approve its current MCP servers/plugins.

    Also trusts the directory of the ``.mcp.json`` that a walk-up from
    ``path`` finds (that's the file the warning named). Returns
    ``{"roots": [...], "mcp": [names], "plugins": [names]}``.
    """
    real = _real(path)
    with _lock:
        data = _load()
        now = int(time.time())
        roots = [real]
        data["projects"].setdefault(real, {"trusted_at": now})
        approved_mcp: list[str] = []
        approved_plugins: list[str] = []

        def _pin(file: Path, entries: dict) -> None:
            # Approvals remember which trusted root they were granted from, so
            # an .mcp.json found *above* the project (say ~/.mcp.json) is
            # approved for this project only — its directory is not made a
            # trusted root — and revoking the root revokes them too.
            prev = data["approvals"].get(str(file), {})
            via = sorted(set(prev.get(_VIA, [])) | {real})
            data["approvals"][str(file)] = {**entries, _VIA: via}

        mcp_file = find_project_mcp_file(real)
        if mcp_file is not None:
            # Started in a subdirectory of the repo that holds the .mcp.json:
            # trust that repo root too.  An .mcp.json *outside* the repo
            # (~/.mcp.json, /tmp/.mcp.json) never turns its directory —
            # and every repo under it — into a trusted root.
            mroot = str(mcp_file.parent)
            groot = _git_root(real)
            if mroot not in data["projects"] and groot is not None \
                    and (mroot == groot or mroot.startswith(groot.rstrip(os.sep) + os.sep)):
                data["projects"][mroot] = {"trusted_at": now}
                roots.append(mroot)
            servers = _read_mcp_servers(mcp_file)
            _pin(mcp_file, {n: mcp_fingerprint(raw) for n, raw in servers.items()})
            approved_mcp = sorted(servers)

        pfile = project_plugins_file(real)
        if pfile.exists():
            plugins = _read_project_plugins(pfile)
            _pin(pfile, {n: plugin_fingerprint(raw) for n, raw in plugins.items()})
            approved_plugins = sorted(plugins)

        sfile = project_settings_file(real)
        hooks_block = _read_project_hooks(sfile)
        if hooks_block:
            _pin(sfile, {"hooks": hooks_fingerprint(hooks_block)})

        _save(data)
        _warned.clear()
    return {"roots": roots, "mcp": approved_mcp, "plugins": approved_plugins}


def approve_plugin(plugins_file: str | os.PathLike, name: str, raw: dict) -> None:
    """Approve ONE project plugin the user just installed themselves.

    Marks the project root trusted (so later additions show as "changed",
    not silently loaded) without approving anything else in it.
    """
    real_file = _real(plugins_file)
    root = str(Path(real_file).parent.parent)
    with _lock:
        data = _load()
        data["projects"].setdefault(root, {"trusted_at": int(time.time())})
        data["approvals"].setdefault(real_file, {})[name] = plugin_fingerprint(raw)
        _save(data)


def revoke(path: str | os.PathLike | None = None) -> bool:
    """Forget trust for ``path`` (exact root) and approvals of files under it."""
    real = _real(path)
    with _lock:
        data = _load()
        found = data["projects"].pop(real, None) is not None
        prefix = real.rstrip(os.sep) + os.sep
        for f in list(data["approvals"]):
            via = data["approvals"][f].get(_VIA, [])
            if f.startswith(prefix) or real in via:
                data["approvals"].pop(f, None)
                found = True
        if found:
            _save(data)
    return found


# ── Fingerprints ──────────────────────────────────────────────────────────

def _fp(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def mcp_fingerprint(raw: dict) -> str:
    """Hash what decides *what runs*: type, command, args, url, env, cwd.

    Headers are left out so rotating a bearer token doesn't force re-approval.
    """
    raw = raw if isinstance(raw, dict) else {}
    return _fp({k: raw.get(k) for k in ("type", "command", "args", "url", "env", "cwd")})


def hooks_fingerprint(hooks_block: Any) -> str:
    """Hash a settings.json ``hooks`` block — any changed command re-asks."""
    return _fp(hooks_block)


def plugin_fingerprint(raw: dict) -> str:
    raw = raw if isinstance(raw, dict) else {}
    inst = raw.get("install_dir")
    # Normalise like PluginEntry.to_dict() does, so file and entry agree.
    return _fp({"source": str(raw.get("source") or ""),
                "install_dir": str(Path(inst)) if inst else ""})


# ── Project file discovery ────────────────────────────────────────────────

def _git_root(start: str) -> str | None:
    """Nearest ancestor (inclusive) holding a .git entry, or None."""
    p = Path(start)
    for cand in (p, *p.parents):
        if (cand / ".git").exists():
            return str(cand)
    return None


def find_project_mcp_file(start: str | os.PathLike | None = None) -> Path | None:
    """Walk up (max 10 levels) from ``start`` to the nearest ``.mcp.json``."""
    # Follow mcp_client.config's file name if it's loaded (tests override it),
    # without importing the package — that would spawn its init thread.
    mcfg = sys.modules.get("cheetahclaws.mcp_client.config")
    fname = getattr(mcfg, "PROJECT_MCP_NAME", ".mcp.json")
    p = Path(_real(start))
    for _ in range(10):
        candidate = p / fname
        if candidate.exists():
            return candidate
        if p.parent == p:
            break
        p = p.parent
    return None


def project_plugins_file(root: str | os.PathLike | None = None) -> Path:
    return Path(_real(root)) / ".cheetahclaws" / "plugins.json"


def project_settings_file(root: str | os.PathLike | None = None) -> Path:
    return Path(_real(root)) / ".cheetahclaws" / "settings.json"


def _read_project_hooks(path: Path) -> Any:
    try:
        if _real(path) == _real(Path.home() / ".cheetahclaws" / "settings.json"):
            return None      # cwd == $HOME: that's the user's own settings
        return json.loads(path.read_text(encoding="utf-8")).get("hooks") or None
    except Exception:
        return None


def is_hooks_approved(settings_file: str | os.PathLike, hooks_block: Any) -> bool:
    """Project hooks run commands, so they need the same pinned approval as
    MCP servers: trusting a folder approves the hooks present at that moment;
    a hook added or changed later (a `git pull`) is skipped until re-approved."""
    if trust_all_enabled():
        return True
    return _approved(Path(settings_file), "hooks", hooks_fingerprint(hooks_block))


def _is_user_plugins_file(path: Path) -> bool:
    """cwd == $HOME makes the "project" plugins.json the user one — trusted."""
    return _real(path) == _real(Path.home() / ".cheetahclaws" / "plugins.json")


def _read_mcp_servers(path: Path) -> dict:
    try:
        servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers", {})
        return servers if isinstance(servers, dict) else {}
    except Exception:
        return {}


def _read_project_plugins(path: Path) -> dict:
    try:
        plugins = json.loads(path.read_text(encoding="utf-8")).get("plugins", {})
        return plugins if isinstance(plugins, dict) else {}
    except Exception:
        return {}


# ── Per-item approval ─────────────────────────────────────────────────────

def _approved(file: Path, name: str, fp: str) -> bool:
    if trust_all_enabled():
        return True
    real_file = _real(file)
    pinned = _load()["approvals"].get(real_file, {})
    if pinned.get(name) != fp:
        return False
    via = pinned.get(_VIA)
    if via is None:          # approvals written before "via" was recorded
        return is_trusted(os.path.dirname(real_file))
    return any(is_trusted(v) for v in via)


def is_mcp_server_approved(mcp_file: str | os.PathLike, name: str, raw: dict) -> bool:
    return _approved(Path(mcp_file), name, mcp_fingerprint(raw))


def is_plugin_approved(plugins_file: str | os.PathLike, name: str, raw: dict) -> bool:
    """``plugins_file`` is the project ``.cheetahclaws/plugins.json``."""
    if _is_user_plugins_file(Path(plugins_file)):
        return True
    project_root = Path(_real(plugins_file)).parent.parent
    if not trust_all_enabled() and not is_trusted(project_root):
        return False
    return _approved(Path(plugins_file), name, plugin_fingerprint(raw))


def pending_untrusted(path: str | os.PathLike | None = None) -> list[dict]:
    """Project MCP servers / plugins that exist but are NOT allowed to run.

    Each item: ``{"kind": "mcp"|"plugin", "name", "file", "reason"}`` where
    reason is ``"untrusted"`` (project never trusted) or ``"changed"``
    (trusted, but the entry is new or its command changed since).
    """
    if trust_all_enabled():
        return []
    out: list[dict] = []
    mcp_file = find_project_mcp_file(path)
    if mcp_file is not None:
        trusted = is_trusted(mcp_file.parent)
        for name, raw in _read_mcp_servers(mcp_file).items():
            if not is_mcp_server_approved(mcp_file, name, raw):
                out.append({"kind": "mcp", "name": name, "file": str(mcp_file),
                            "reason": "changed" if trusted else "untrusted"})
    pfile = project_plugins_file(path)
    if pfile.exists() and not _is_user_plugins_file(pfile):
        trusted = is_trusted(pfile.parent.parent)
        for name, raw in _read_project_plugins(pfile).items():
            if not (isinstance(raw, dict) and raw.get("enabled", True)):
                continue
            if not is_plugin_approved(pfile, name, raw):
                out.append({"kind": "plugin", "name": name, "file": str(pfile),
                            "reason": "changed" if trusted else "untrusted"})
    sfile = project_settings_file(path)
    hooks_block = _read_project_hooks(sfile)
    if hooks_block and not is_hooks_approved(sfile, hooks_block):
        events = ", ".join(sorted(hooks_block)) if isinstance(hooks_block, dict) else "hooks"
        out.append({"kind": "hooks", "name": events, "file": str(sfile),
                    "reason": "changed" if is_trusted(sfile.parent.parent) else "untrusted"})
    return out


def untrusted_hint() -> str:
    return ("run /trust in the REPL (or `cheetahclaws trust`) to allow; "
            f"set {TRUST_CONFIG_KEY}: true or {TRUST_ENV}=1 to trust all projects")


def warn_untrusted_once(kind: str, items: list[dict]) -> None:
    """Print ONE stderr line per (kind, file) summarising skipped items."""
    by_file: dict[str, list[dict]] = {}
    for it in items:
        if it.get("kind") == kind:
            by_file.setdefault(it["file"], []).append(it)
    label = "MCP server" if kind == "mcp" else "plugin"
    for file, its in by_file.items():
        key = f"{kind}:{file}:{','.join(sorted(i['name'] for i in its))}"
        with _lock:
            if key in _warned:
                continue
            _warned.add(key)
        names = ", ".join(sorted(i["name"] for i in its))
        why = ("new or changed since you trusted it"
               if all(i["reason"] == "changed" for i in its) else "project not trusted")
        print(f"[trust] Skipped {len(its)} project {label}(s) ({names}) from {file} — "
              f"{why}; {untrusted_hint()}.", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    """``cheetahclaws trust [list|revoke [path]|path]`` entry point."""
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = argv[0] if argv else ""
    if sub == "list":
        for root in list_trusted():
            print(root)
        for it in pending_untrusted():
            print(f"pending {it['kind']} {it['name']} ({it['reason']}) in {it['file']}")
        return 0
    if sub == "revoke":
        target = argv[1] if len(argv) > 1 else None
        if revoke(target):
            print(f"Revoked trust for {_real(target)}")
            return 0
        print(f"{_real(target)} was not trusted")
        return 1
    target = sub or None
    res = trust(target)
    print(f"Trusted {', '.join(res['roots'])}"
          + (f"; MCP servers: {', '.join(res['mcp'])}" if res["mcp"] else "")
          + (f"; plugins: {', '.join(res['plugins'])}" if res["plugins"] else ""))
    return 0
