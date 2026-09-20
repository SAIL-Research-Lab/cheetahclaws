"""
commands/config_cmd.py — Configuration and model commands for CheetahClaws.

Commands: /model, /config, /verbose, /thinking, /permissions, /auto, /cwd
"""
from __future__ import annotations

import json
import os

from cheetahclaws.ui.render import clr, info, ok, warn, err


def cmd_model(args: str, _state, config) -> bool:
    from cheetahclaws.providers import PROVIDERS, detect_provider
    if not args:
        model = config["model"]
        pname = detect_provider(model)
        info(f"Current model:    {model}  (provider: {pname})")
        info("\nAvailable models by provider:")
        for pn, pdata in PROVIDERS.items():
            if pn == "ollama":
                # Show live local models instead of hardcoded list
                from cheetahclaws.providers import list_ollama_models
                base_url = (
                    os.environ.get("OLLAMA_BASE_URL")
                    or config.get("ollama_base_url")
                    or pdata.get("base_url", "http://localhost:11434")
                )
                local = list_ollama_models(base_url)
                if local:
                    info(f"  {'ollama':12s}  " + ", ".join(local[:6]) + ("..." if len(local) > 6 else ""))
                    info(f"  {'':12s}  " + clr(f"({len(local)} local models — /model ollama to pick)", "dim"))
                else:
                    info(f"  {'ollama':12s}  " + clr("(not running or no models pulled)", "dim"))
                continue
            ms = pdata.get("models", [])
            if ms:
                info(f"  {pn:12s}  " + ", ".join(ms[:4]) + ("..." if len(ms) > 4 else ""))
        info("\nFormat: 'provider/model' or just model name (auto-detected)")
        info("  e.g. /model gpt-4o")
        info("  e.g. /model ollama/qwen2.5-coder")
        info("  e.g. /model kimi:moonshot-v1-32k")
        info("  e.g. /model openrouter/deepseek/deepseek-v4-flash  (multi-level: provider/upstream/model)")
        info("  e.g. /model openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8  (pin provider/quantization)")
    else:
        m = args.strip()
        # "/model ollama" with no model name → interactive picker
        if m == "ollama":
            if _interactive_ollama_picker(config):
                return True
            return True
        if "/" not in m and ":" in m:
            left, right = m.split(":", 1)
            if left in PROVIDERS:
                m = f"{left}/{right}"
        config["model"] = m
        pname = detect_provider(m)
        ok(f"Model set to {m}  (provider: {pname})")
        from cheetahclaws.config import save_config
        save_config(config)
    return True


def _interactive_ollama_picker(config: dict) -> bool:
    """Prompt the user to select from locally available Ollama models."""
    from cheetahclaws.providers import PROVIDERS, list_ollama_models
    from cheetahclaws.tools import ask_input_interactive
    prov = PROVIDERS.get("ollama", {})
    base_url = (
        os.environ.get("OLLAMA_BASE_URL")
        or config.get("ollama_base_url")
        or prov.get("base_url", "http://localhost:11434")
    )

    models = list_ollama_models(base_url)
    if not models:
        err(f"No local Ollama models found at {base_url}.")
        return False

    menu_buf = clr("\n  ── Local Ollama Models ──", "dim")
    for i, m in enumerate(models):
        menu_buf += "\n" + clr(f"  [{i+1:2d}] ", "yellow") + m
    print(menu_buf)
    print()

    try:
        ans = ask_input_interactive(clr("  Select a model number or Enter to cancel > ", "cyan"), config, menu_buf).strip()
        if not ans: return False
        idx = int(ans) - 1
        if 0 <= idx < len(models):
            new_model = f"ollama/{models[idx]}"
            config["model"] = new_model
            from cheetahclaws.config import save_config
            save_config(config)
            ok(f"Model updated to {new_model}")
            return True
        else:
            err("Invalid selection.")
    except (ValueError, KeyboardInterrupt, EOFError):
        pass
    return False


def cmd_config(args: str, _state, config) -> bool:
    from cheetahclaws.config import save_config
    if not args:
        _SECRETS = {"api_key", "anthropic_api_key", "telegram_token", "wechat_token"}
        display = {k: v for k, v in config.items()
                   if k not in _SECRETS and not k.startswith("_")
                   and not k.endswith(("_key", "_token", "_secret"))}
        print(json.dumps(display, indent=2))
    elif "=" in args:
        key, _, val = args.partition("=")
        key, val = key.strip(), val.strip()
        if val.lower() in ("true", "false"):
            val = val.lower() == "true"
        elif val.isdigit():
            val = int(val)
        # JSON-style values: lists, objects, numbers with signs, quoted strings.
        # Without this branch, /config wechat_smart_reply_whitelist=["a","b"]
        # silently stored the literal string '["a","b"]'.
        elif val and val[0] in '[{"-' or (val.startswith("-") and val[1:].isdigit()):
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                pass  # leave as string
        if key == "tool_profile":
            try:
                from cheetahclaws.tool_registry import normalize_tool_profile
                val = normalize_tool_profile(val)
            except ValueError as exc:
                err(str(exc))
                return False
        config[key] = val
        save_config(config)
        ok(f"Set {key} = {val!r}")
        if key == "context_window" and isinstance(val, int) and not isinstance(val, bool) and val > 0:
            # The override drives the prompt %, /context, AND the compaction
            # trigger. Warn if it exceeds the model's real window, since that
            # disables compaction and the API may reject oversized prompts.
            from cheetahclaws.compaction import get_context_limit
            # Real window with the override forced off (keeps custom_base_url so
            # custom/vLLM endpoints still get their live lookup).
            real = get_context_limit(config.get("model", ""), {**config, "context_window": 0})
            if real and val > real:
                warn(f"context_window={val:,} exceeds the model's real window "
                     f"(~{real:,}); compaction won't fire before the real limit, "
                     "so the API may reject oversized prompts. Use this only to "
                     "correct a wrong default.")
            info("Takes effect on the next prompt (no restart needed).")
    else:
        k = args.strip()
        v = config.get(k, "(not set)")
        info(f"{k} = {v}")
    return True


def cmd_verbose(_args: str, _state, config) -> bool:
    from cheetahclaws.config import save_config
    config["verbose"] = not config.get("verbose", False)
    state_str = "ON" if config["verbose"] else "OFF"
    ok(f"Verbose mode: {state_str}")
    save_config(config)
    return True


def cmd_quiet(_args: str, _state, config) -> bool:
    from cheetahclaws.config import save_config
    config["quiet"] = not config.get("quiet", True)
    state_str = "ON" if config["quiet"] else "OFF"
    ok(f"Quiet mode: {state_str}  "
       + ("(hide tool execution, show a per-turn summary)" if config["quiet"]
          else "(show each tool call)"))
    save_config(config)
    return True


def cmd_terminal_setup(_args: str, _state, _config) -> bool:
    """Configure the current editor so its terminal tab shows the live task.

    In VS Code / Cursor / Windsurf this flips
    ``terminal.integrated.tabs.title`` to include ``${sequence}`` (backing up
    settings.json first). Other terminals already show it natively, so this
    reports there's nothing to do. Runs automatically once on first launch;
    this command re-runs it on demand."""
    from cheetahclaws.ui.vscode_setup import run_terminal_setup
    run_terminal_setup()
    return True


def cmd_thinking(_args: str, _state, config) -> bool:
    from cheetahclaws.config import save_config
    config["thinking"] = not config.get("thinking", False)
    state_str = "ON" if config["thinking"] else "OFF"
    ok(f"Extended thinking: {state_str}")
    save_config(config)
    return True


def cmd_permissions(args: str, _state, config) -> bool:
    from cheetahclaws.config import save_config
    from cheetahclaws.tools import ask_input_interactive
    modes = ["auto", "accept-edits", "accept-all", "manual", "plan"]
    mode_desc = {
        "auto":         "Auto-run every read-only tool + read-only shell commands; ask before edits, arbitrary commands, sub-agents (default)",
        "accept-edits": "Like auto, but also auto-run file edits (Write/Edit); other Bash still asks",
        "accept-all":   "Run everything without asking (host-destroying commands are still hard-blocked)",
        "manual":       "Ask before every tool call, including reads",
        "plan":         "Read-only: reads + safe Bash run, all edits/writes are refused (see /plan for the plan-file workflow)",
    }
    from cheetahclaws import permissions as _perms
    arg = args.strip()

    # "/permissions clear" drops the session-scoped grants made by answering
    # "s" at a prompt — the escape hatch when one was given too broadly.
    if arg in ("clear", "reset"):
        from cheetahclaws import runtime
        grants = runtime.get_ctx(config).approved_sigs
        n = len(grants)
        grants.clear()
        ok(f"Cleared {n} session permission grant{'s' if n != 1 else ''}.")
        return True

    # "/permissions allow <sig> ..." / "forget <sig>|all" manage the saved
    # grants made by answering "!" at a prompt.
    if arg.split(" ", 1)[0] in ("allow", "forget", "remember"):
        verb, _, rest = arg.partition(" ")
        sigs = [x for x in rest.split() if x]
        if not sigs:
            err(f"Usage: /permissions {verb} <signature> [<signature> ...]"
                + ("  (or 'all')" if verb == "forget" else ""))
            return True
        if verb == "forget":
            if sigs == ["all"]:
                ok(f"Forgot {_perms.forget_all(config)} saved permission grant(s).")
                return True
            for sig in sigs:
                if _perms.forget_signature(sig, config):
                    ok(f"Forgot saved grant: {sig}")
                else:
                    warn(f"Not a saved grant: {sig}")
            return True
        added = _perms.extend_signatures(sigs, config)
        ok(f"Saved {added} permission grant(s) — these will never be asked again.")
        return True
    if not arg:
        current = config.get("permission_mode", "auto")
        menu_buf = clr("\n  ── Permission Mode ──", "dim")
        for i, m in enumerate(modes):
            marker = clr("●", "green") if m == current else clr("○", "dim")
            menu_buf += f"\n  {marker} {clr(f'[{i+1}]', 'yellow')} {clr(m, 'cyan')}  {clr(mode_desc[m], 'dim')}"
        try:
            from cheetahclaws import runtime
            grants = sorted(runtime.get_ctx(config).approved_sigs)
        except Exception:
            grants = []
        if grants:
            menu_buf += "\n\n  " + clr(f"Session grants ({len(grants)}) — /permissions clear to drop:", "dim")
            for g in grants[:10]:
                menu_buf += "\n    " + clr(f"• {g}", "dim")
            if len(grants) > 10:
                menu_buf += "\n    " + clr(f"… {len(grants) - 10} more", "dim")
        saved = sorted(_perms.saved_signatures(config))
        if saved:
            menu_buf += "\n\n  " + clr(
                f"Saved grants ({len(saved)}) — /permissions forget <sig|all> to drop:", "dim")
            for g in saved[:10]:
                menu_buf += "\n    " + clr(f"• {g}", "dim")
            if len(saved) > 10:
                menu_buf += "\n    " + clr(f"… {len(saved) - 10} more", "dim")
        if _perms.auto_approve_on(config):
            menu_buf += "\n\n  " + clr(
                "🚀 Autonomous mode is ON (the default) — nothing is prompted. "
                "/auto off to approve each step.", "dim")
        else:
            menu_buf += "\n\n  " + clr(
                "Autonomous mode is OFF — /auto on to stop the prompts.", "dim")
        print(menu_buf)
        print()
        try:
            ans = ask_input_interactive(clr("  Select a mode number or Enter to cancel > ", "cyan"), config, menu_buf).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return True
        if not ans:
            return True
        if ans.isdigit() and 1 <= int(ans) <= len(modes):
            m = modes[int(ans) - 1]
            config["permission_mode"] = m
            save_config(config)
            ok(f"Permission mode set to: {m}")
        else:
            err("Invalid selection.")
    else:
        m = arg
        if m not in modes:
            err(f"Unknown mode: {m}. Choose: {', '.join(modes)}")
            info("Also: /permissions clear | allow <sig> | forget <sig|all>")
        else:
            config["permission_mode"] = m
            save_config(config)
            ok(f"Permission mode set to: {m}")
    return True


def cmd_auto(args: str, _state, config) -> bool:
    """/auto [on|off] — run tasks end to end without approval prompts.

    **On by default.** The point is that a request becomes a *result*: the
    agent edits, runs and verifies whatever the task needs instead of stopping
    at every tool call for a keystroke. Unlike ``accept-all`` (session-only by
    design) the choice is saved, so ``/auto off`` holds across restarts too.

    Still enforced in this mode: the Bash hard-denylist (host-destroying
    commands are refused outright), the filesystem sandbox / credential-path
    denylist, and the ``manual`` and ``plan`` permission modes, which are
    explicit "ask me" requests and keep overriding autonomy.
    """
    from cheetahclaws import permissions as _perms
    arg = args.strip().lower()

    if arg in ("", "status"):
        if _perms.auto_approve_on(config):
            ok("🚀 Autonomous mode: ON (the default) — tasks run end to end, "
               "nothing is prompted.")
            info("  Want to approve each step? /auto off")
        else:
            info("Autonomous mode: OFF — edits and arbitrary commands ask first.")
            info("  Back to the default:  /auto on")
        mode = config.get("permission_mode", "auto")
        if mode in ("manual", "plan"):
            warn(f"  permission_mode is '{mode}', which overrides autonomous mode.")
        saved = _perms.saved_signatures(config)
        if saved:
            info(f"  {len(saved)} saved per-command grant(s) — see /permissions")
        return True

    if arg in ("on", "yes", "true", "1", "enable"):
        _perms.set_auto_approve(True, config)
        ok("🚀 Autonomous mode ON — I'll carry tasks through without asking.")
        mode = config.get("permission_mode", "auto")
        if mode in ("manual", "plan"):
            warn(f"  Note: permission_mode is '{mode}' and still asks/blocks. "
                 f"Run /permissions auto to clear it.")
        info("  Host-destroying commands are still refused. /auto off to undo.")
        return True

    if arg in ("off", "no", "false", "0", "disable"):
        _perms.set_auto_approve(False, config)
        ok("Autonomous mode OFF — edits and arbitrary commands ask first again.")
        info("  This is saved; /auto on (the default) stops the prompts.")
        return True

    err(f"Unknown option: {arg}. Usage: /auto [on|off|status]")
    return True


def cmd_cwd(args: str, _state, config) -> bool:
    if not args.strip():
        info(f"Working directory: {os.getcwd()}")
    else:
        p = args.strip()
        try:
            os.chdir(p)
            ok(f"Changed directory to: {os.getcwd()}")
        except Exception as e:
            err(str(e))
    return True
