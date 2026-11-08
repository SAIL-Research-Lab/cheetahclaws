# Hooks

Hooks are shell commands, or Python functions registered by plugins, that run
at fixed points in the agent's lifecycle. They can enforce a policy (for
example, block `git push` to main), add context (the current ticket, the
branch), give the model feedback (lint output after each edit), or keep the
agent working until the tests pass.

The configuration format is compatible with Claude Code, so most existing
Claude Code hook scripts run unchanged. `CLAUDE_PROJECT_DIR` is also set for
them.

## Where hooks are configured

| File | When it is used |
|---|---|
| `~/.cheetahclaws/settings.json` | Always |
| `<project>/.cheetahclaws/settings.json` | Only when the workspace is **trusted**. A repository you just cloned can't run commands on your machine. If you have hooks there in an untrusted workspace, you get a single warning on stderr and the hooks are skipped. |

Hooks from both files run, user hooks first. Setting `"disableAllHooks": true`
turns every hook off, and so does the environment variable
`CHEETAHCLAWS_DISABLE_HOOKS=1`.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {"type": "command", "command": "~/.cheetahclaws/hooks/no-push-main.sh", "timeout": 10}
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "ruff check --quiet \"$CHEETAHCLAWS_PROJECT_DIR\" 1>&2 || exit 2"}]
      }
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "./scripts/require-green-tests.sh", "failClosed": true}]}
    ]
  }
}
```

* **`matcher`** is a regular expression that must match the **whole** tool
  name (`Edit|Write`, `mcp__github__.*`). If it is missing, or set to `*`, the
  hook matches every tool. For `SessionStart` the matcher is compared with the
  source (`startup`/`resume`), and for `PreCompact` with the trigger (`auto`).
  The other events ignore matchers.
* **`timeout`** is in seconds and defaults to 60.
* **`failClosed`** (cheetahclaws only): if the hook crashes, times out or exits
  with a code other than 0 or 2, that counts as a *block*. By default such a
  failure is only logged and the agent carries on.

## Events

| Event | When | Payload fields (besides the common ones) | What the hook can do |
|---|---|---|---|
| `PreToolUse` | before each tool call | `tool_name`, `tool_input`, `tool_use_id` | allow (skips the prompt), deny (with a reason the model sees), ask (forces a prompt), rewrite the input, stop |
| `PostToolUse` | after a permitted call | `tool_name`, `tool_input`, `tool_use_id`, `tool_response`, `is_error` | add feedback to the result the model sees, stop |
| `UserPromptSubmit` | before a prompt reaches the model | `prompt` | block the prompt, add context |
| `Stop` | when the agent is about to finish | `stop_hook_active`, `last_assistant_message` | keep it working ("block" + reason), at most 3 times per prompt (`stop_hook_max_continues`) |
| `SessionStart` | REPL start, headless start or resume | `source` | add context, which is attached to the session's first prompt |
| `SessionEnd` | REPL exit, end of a headless run | `reason` | clean up (informational) |
| `PreCompact` | before the conversation is compacted | `trigger` | informational (for example, archive the transcript) |
| `Notification` | the agent needs a permission decision | `message`, `notification_type` | informational (desktop or Slack alert); runs in the background |

Every payload also contains `hook_event_name`, `session_id`, `cwd`,
`permission_mode` and, when the event log is on, `transcript_path` (the
session's `events.jsonl`).

## Protocol for command hooks

A hook reads the payload as one JSON object on **stdin**. Its environment has
`CHEETAHCLAWS_PROJECT_DIR` (and `CLAUDE_PROJECT_DIR`),
`CHEETAHCLAWS_HOOK_EVENT` and `CHEETAHCLAWS_SESSION_ID`. It runs with the
project directory as its working directory.

| Result | Effect |
|---|---|
| exit 0, no output | No effect. |
| exit 0, JSON on stdout | A structured decision, described below. |
| exit 0, plain text on stdout | For `UserPromptSubmit` and `SessionStart`, the text is added as context. For other events it is ignored. |
| **exit 2** | **Block.** stderr becomes the reason: for `PreToolUse` the call is denied, `UserPromptSubmit` drops the prompt, and `Stop` keeps the agent working. For `PostToolUse`, stderr is passed to the model as feedback. |
| other exit code, a timeout or a crash | Logged as a non-blocking error, unless the hook has `failClosed`. |

JSON fields are read in their flat form and also inside Claude Code's
`hookSpecificOutput` wrapper:

```json
{
  "decision": "deny",                // PreToolUse: allow | deny | ask ("approve"/"block" also accepted)
                                     // UserPromptSubmit / Stop / PostToolUse: "block"
  "reason": "pushing to main is not allowed",
  "updatedInput": {"command": "git push origin HEAD:feature"},   // PreToolUse only
  "additionalContext": "extra text for the model",
  "continue": false,                 // stop the agent after this step
  "stopReason": "budget exhausted",
  "systemMessage": "shown in the event log"
}
```

When several hooks match, they run one after another in the order they are
configured. The strictest decision wins: `deny`/`block`, then `ask`, then
`allow`. A rewritten `updatedInput` is passed on to the hooks after it.

### Example: block pushes to main

```bash
#!/usr/bin/env bash
# ~/.cheetahclaws/hooks/no-push-main.sh
cmd=$(jq -r '.tool_input.command // ""')
if [[ "$cmd" =~ git[[:space:]]+push.*(main|master) ]]; then
  echo "Pushing to main is blocked; push a feature branch and open a PR." >&2
  exit 2
fi
```

### Example: don't stop until the tests pass

```bash
#!/usr/bin/env bash
# scripts/require-green-tests.sh  (Stop hook)
log=$(mktemp)
if ! pytest -q -x >"$log" 2>&1; then
  echo "Tests are failing; fix them before finishing:" >&2
  tail -20 "$log" >&2
  exit 2          # Stop + exit 2 = keep working, stderr is the reason
fi
```

## Python hooks for plugins

```python
from cheetahclaws import hooks

def no_secrets(payload):
    if ".env" in str(payload.get("tool_input", {}).get("file_path", "")):
        return {"decision": "deny", "reason": "never touch .env files"}

unregister = hooks.register("PreToolUse", no_secrets, matcher="Read|Edit|Write")
```

A Python hook gets the same payload dict and can return `None`, a dict in the
JSON format above, or a `hooks.HookResult`. If it raises an exception, the
error is logged and the hook is skipped.

## Seeing what hooks did

Every hook outcome is written to the session event log as a `hook` event. View
it with `cheetahclaws replay <session-id>`, or in a headless run with
`--output-format stream-json`. See [headless.md](headless.md).
