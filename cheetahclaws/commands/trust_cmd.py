"""
commands/trust_cmd.py - /trust slash command (workspace trust, see trust.py).

Usage:
  /trust              Trust the current directory: start its .mcp.json
                      servers and load its .cheetahclaws/plugins.json plugins
  /trust list         Show trusted roots and anything pending approval
  /trust revoke [dir] Forget trust for <dir> (default: current directory)
"""
from __future__ import annotations

import os

from cheetahclaws.ui.render import clr, info, ok, warn, err


def _show_pending(pending: list[dict]) -> None:
    for it in pending:
        label = "MCP server" if it["kind"] == "mcp" else "plugin"
        why = "untrusted project" if it["reason"] == "untrusted" else "new/changed"
        print(f"  {clr(it['name'], 'yellow')} ({label}, {why})  {clr(it['file'], 'dim')}")


def _activate_now() -> None:
    """Start newly-approved MCP servers and plugin tools in this session."""
    try:
        from cheetahclaws.mcp_client.tools import reload_mcp
        errors = reload_mcp()
        for name, e in (errors or {}).items():
            if e:
                warn(f"MCP server '{name}' failed to connect: {e}")
    except Exception as e:
        warn(f"MCP reload failed: {e}")
    try:
        from cheetahclaws.plugin.loader import register_plugin_tools
        from cheetahclaws.plugin.types import PluginScope
        register_plugin_tools(PluginScope.PROJECT)
    except Exception as e:
        warn(f"Plugin load failed: {e}")


def cmd_trust(args: str, _state, config) -> bool:
    from cheetahclaws import trust as _trust

    parts = (args or "").split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub in ("list", "ls", "status"):
        roots = _trust.list_trusted()
        if _trust.trust_all_enabled(config):
            warn("Workspace trust is OFF (trust_all_projects / CHEETAHCLAWS_TRUST_ALL) "
                 "— every project's MCP servers and plugins load.")
        if roots:
            info(f"Trusted project roots ({len(roots)}):")
            for r in roots:
                print(f"  {r}")
        else:
            info("No trusted projects.")
        pending = _trust.pending_untrusted()
        if pending:
            info("Pending in this directory (run /trust to allow):")
            _show_pending(pending)
        return True

    if sub == "revoke":
        target = os.path.expanduser(rest) if rest else os.getcwd()
        if _trust.revoke(target):
            ok(f"Revoked trust for {os.path.realpath(target)}. "
               "Already-running servers stop on restart.")
        else:
            err(f"{os.path.realpath(target)} is not a trusted root (see /trust list).")
        return True

    if sub in ("help", "-h", "--help"):
        info("Usage: /trust | /trust list | /trust revoke [dir]")
        return True

    target = os.path.expanduser(args.strip()) if sub else os.getcwd()
    pending = _trust.pending_untrusted(target)
    if pending:
        warn("Trusting runs this code with your privileges:")
        _show_pending(pending)
    res = _trust.trust(target)
    ok(f"Trusted {', '.join(res['roots'])}.")
    if res["mcp"] or res["plugins"]:
        _activate_now()
        if res["plugins"]:
            info("Plugin slash commands from this project load on next start.")
    return True


# Same shape as plugin COMMAND_DEFS so cli.py can merge it like the others.
COMMAND_DEFS = {
    "trust": {
        "func": cmd_trust,
        "help": ("Trust this project (load its .mcp.json / plugins)", ["list", "revoke"]),
        "aliases": [],
    }
}
