# GitHub Action

The repository root contains a composite action, `action.yml`. It installs
cheetahclaws and runs `cheetahclaws exec --output-format json` (see
[headless.md](headless.md)), so a workflow can use the agent for pull-request
review, issue triage or a scheduled cleanup.

## Example: review every pull request

```yaml
# .github/workflows/cheetahclaws-review.yml
name: CheetahClaws PR review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - id: agent
        uses: SAIL-Research-Lab/cheetahclaws@main     # pin a tag or SHA in production
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        with:
          model: claude-sonnet-4-6
          permission-mode: auto                 # reads + safe shell only; nothing else is approved
          allowed-tools: "Bash(git diff:*),Bash(git log:*)"
          disallowed-tools: "WebFetch,WebSearch"
          max-turns: "25"
          prompt: |
            Review the changes in this pull request against origin/${{ github.base_ref }}
            (use `git diff origin/${{ github.base_ref }}...HEAD`). Report bugs, security
            problems and missing tests, most important first, with file:line references.
            Do not modify any files.

      - name: Post the review
        if: always() && steps.agent.outputs.final-text != ''
        env:
          GH_TOKEN: ${{ github.token }}
          BODY: ${{ steps.agent.outputs.final-text }}
        run: gh pr comment ${{ github.event.pull_request.number }} --body "$BODY"
```

The prompt goes to the agent through an environment variable and stdin, and
is never pasted into a shell command. That means it can safely contain text
from the pull request, such as its title or body.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `prompt` | (required) | The task for the agent. |
| `model` | `claude-sonnet-4-6` | Any model id cheetahclaws supports (`gpt-4o`, `deepseek/deepseek-chat`, `ollama/...` …). |
| `permission-mode` | `auto` | Set this explicitly in CI. Any mode other than `accept-all` turns off the autonomous default, so calls that would need approval are **denied** instead (there is nobody to ask). |
| `allowed-tools` | — | Extra approvals, for example `Bash(pytest:*),Edit(src/*)`. |
| `disallowed-tools` | — | Hides tools (`WebFetch`) or denies matching calls (`Bash(git push:*)`). |
| `max-turns` | `30` | Stops a runaway run (exit code 2). |
| `working-directory` | `.` | |
| `python-version` | `3.11` | |
| `cheetahclaws-version` | latest | A pip specifier, for example `==3.5.90`. |
| `anthropic-api-key` / `openai-api-key` | — | Or set the provider's usual environment variable in the step `env`, as in the example above. |
| `fail-on-error` | `true` | Fails the step when the exit code is not 0. |

## Outputs

| Output | |
|---|---|
| `final-text` | The agent's final answer. |
| `exit-code` | 0 done, 1 error, 2 stopped (max turns, permission denied, budget or hook). |
| `result` | Path to the JSON `result` object (usage, cost, permission denials …). |
| `session-id` | The run's session id. The event log is in `~/.cheetahclaws/sessions/<id>/events.jsonl` on the runner; upload it with `actions/upload-artifact` to keep an audit trail. |

The action also adds the exit reason, the number of turns, the cost and the
answer to the job summary.

## Policy hooks in CI

The project's `.cheetahclaws/settings.json` hooks run only when the workspace
is trusted. On a CI runner you can install policy hooks in the user settings
instead, for example to block every `git push`:

```yaml
      - run: |
          mkdir -p ~/.cheetahclaws
          cat > ~/.cheetahclaws/settings.json <<'EOF'
          {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": "jq -e '.tool_input.command | test(\"git\\\\s+push\") | not' >/dev/null || { echo 'no pushes from CI' >&2; exit 2; }"}
          ]}]}}
          EOF
```

See [hooks.md](hooks.md) for the full hook protocol.
