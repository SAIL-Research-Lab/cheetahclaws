# Headless mode, JSON events and session replay

`cheetahclaws exec` (or `cheetahclaws -p`) runs one request through the agent
without the REPL and exits. It never waits for a person at the terminal, writes
only the result to stdout, and returns an exit code your script can check.

```bash
cheetahclaws exec "explain what src/app.py does"
git diff main | cheetahclaws -p "review this diff"          # stdin is appended to the prompt
cheetahclaws exec - < task.md                                # prompt only from stdin
cheetahclaws exec --output-format json "count TODOs" | jq .final_text
cheetahclaws exec --output-format stream-json "fix the failing test" | jq -c 'select(.type=="tool_call")'
```

`cheetahclaws "prompt"` without `-p` behaves as before: it opens the REPL
rendering, runs the prompt once and exits.

## Flags

| Flag | Meaning |
|---|---|
| `--output-format text\|json\|stream-json` | `text` (default) prints the final answer. `json` prints one `result` object. `stream-json` prints one JSON event per line (JSONL). |
| `--max-turns N` | Stops after N model turns, with exit code 2. |
| `--permission-mode M` | `auto`, `accept-edits`, `accept-all`, `manual` or `plan`. Any mode other than `accept-all` also turns off the autonomous default (`auto_approve`) for this run, so only operations that mode treats as safe run without approval. |
| `--allowed-tools RULES` | Approves matching calls without asking: `Read,Edit`, `Bash(pytest:*)`, `Write(src/*.py)`, `mcp__github__*`. |
| `--disallowed-tools RULES` | A bare name (`WebFetch`) removes the tool from the model's tool list. A rule with arguments (`Bash(rm:*)`) denies matching calls even under `accept-all`. |
| `--resume ID` / `--continue` | Continues a saved session by id, or the most recently saved one. |
| `--on-permission-denied continue\|stop` | `continue` (default) tells the model the call was denied and lets it carry on. `stop` ends the run at the first denial with exit code 2. |
| `--no-event-log` | Skips writing `events.jsonl` for this run. |
| `-m/--model`, `--accept-all`, `--auto`/`--yolo`, `--ask`, `--budget`, `--thinking`, `--verbose` | Same as in the REPL. |

The `-p`/`exec` flags can be combined with the other options above.

**Bash prefix rules never match a command that contains shell control
characters** (`; & | $ \` < >` or a newline). For example, `Bash(git log:*)`
approves `git log -5` but not `git log; rm -rf ~`.

## Permission policy (non-interactive)

1. Calls that the permission mode or autonomous setting already approves run
   as usual.
2. A call that would show an approval prompt in the REPL is checked against
   `--allowed-tools`. If it matches, it runs.
3. Otherwise the call is **denied**. The model receives a tool result saying
   the run is non-interactive and that it should continue without that call.
   A `permission_decision` event with `source: "headless"` is emitted, and the
   call is listed in `result.permission_denials`.

Interactive-only tools (`AskUserQuestion`) are hidden in headless runs, and
stdin is closed to tools, so nothing can block waiting for input.

## Exit codes

| Code | `exit_reason` |
|---|---|
| 0 | `completed` |
| 1 | `api_error`, `loop_guard`, `error` (a bad flag or a missing prompt also returns 1) |
| 2 | `max_turns`, `permission_denied` (with `--on-permission-denied stop`), `quota` (a `--budget` was hit), `hook_blocked`, `hook_stopped` |
| 130 | `interrupted` (Ctrl-C) |

## Events (`stream-json`, and the session event log)

Every event has the same envelope:

```json
{"type": "tool_call", "seq": 7, "ts": 1761800000.123, "session_id": "1a2b3c4d", ...}
```

`ts` is in epoch seconds, like the kernel's `agent_events.ts`. `seq` increases
monotonically within a session and keeps counting across `--resume`.

| type | fields |
|---|---|
| `session_start` | `model`, `cwd`, `permission_mode`, `mode` (`headless`/`repl`), `resumed`, `version`, `max_turns` |
| `user_message` | `text` |
| `assistant_delta` | `text` (streamed tokens; sent to stdout only, not persisted) |
| `assistant_message` | `text`, `tool_calls: [{id, name}]`, `model` |
| `tool_call` | `id`, `name`, `input` |
| `permission_decision` | `id`, `name`, `decision` (`allow`/`deny`), `source` (`hook`, `plan_mode`, `user`, `headless`, `allowed_tools`), `reason` |
| `tool_result` | `id`, `name`, `is_error`, `output` (truncated to 4000 chars) |
| `usage` | `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `model` |
| `hook` | `event`, `hooks_run`, `decision`, `reason`, `updated_input`, `additional_context`, `errors` … |
| `compaction` | `trigger` (`auto` / `overflow`) |
| `notice` | `text` (max turns reached, budget, hook stop, prompt blocked) |
| `error` | `message`, `category`, `hint` |
| `result` | `final_text`, `exit_reason`, `exit_code`, `is_error`, `turns`, `usage{…}`, `cost_usd`, `duration_ms`, `model`, `permission_denials[]`, `error?` |
| `session_end` | `reason` (REPL only) |

Events from sub-agent loops have a `depth` field (1, 2, …).
`--output-format json` prints only the `result` event.

## Session event log and replay

Every session, from either the REPL or a headless run, appends the same events
(without the deltas) to

```
~/.cheetahclaws/sessions/<session-id>/events.jsonl
```

The file is append-only and a new line is written after each event, so it can
be read with `tail -f` while the session is running. A crash loses at most the
last, partly written line.

```bash
cheetahclaws replay                 # list recorded sessions
cheetahclaws replay last            # show the timeline of the newest session
cheetahclaws replay 1a2b            # unique id prefix
cheetahclaws replay 1a2b --full     # don't truncate long text
cheetahclaws replay 1a2b --json     # raw JSONL, e.g. for jq
```

Replay only displays the recorded timeline and never re-runs anything. To
continue the conversation, use `cheetahclaws exec --resume <id> "..."`.

To turn the log off, set `/config event_log=false` or pass `--no-event-log`.
`event_log_deltas=true` also stores the token deltas.
