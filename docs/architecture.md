# Architecture Guide

This document is for contributors who want to understand, modify, or
extend CheetahClaws — the *why* and *how* behind the code, not the PR
checklist.  For the quick-start flow, pointers on where to add things,
and the PR checklist, see [CONTRIBUTING.md](../CONTRIBUTING.md).  For
the user-facing surface (CLI flags, slash commands, provider setup),
see [README.md](../README.md).

---

## Overview

CheetahClaws is a Python-native terminal AI coding assistant that
speaks to any LLM provider (Anthropic, OpenAI, Gemini, Kimi, Qwen,
Zhipu, DeepSeek, MiniMax, Ollama, LM Studio, any OpenAI-compatible
endpoint).  It started as a ~900-line single-file script and has grown
into a roughly 45 KLoC multi-package codebase; the repository is in a
**mostly-package layout with intentional backward-compat shims** at the
top level.

The high-level shape:

```
                        User Input
                            │
                            ▼
   ┌───────────────────────────────────────────────────────────┐
   │  cheetahclaws/cli.py  —  REPL, slash dispatch, permission UI   │
   └────┬──────────────────────────────┬───────────────────────┘
        │                              │
        │    ┌─────────────────────────┴──────────────┐
        │    │                                        │
        ▼    ▼                                        ▼
   bootstrap.py                                   commands/
   (logging → tool registry                        (/save /load /model
    → health HTTP server)                           /plan /agent /mcp
        │                                           /brainstorm /ssj …)
        ▼
   agent.py ── multi-turn generator loop
        │
        ├──► context.py ── system prompt (base template + env +
        │                   memory index + tmux / plan blocks)
        │
        ├──► providers.py ── stream adapter (anthropic + openai-compat)
        │
        ├──► tool_registry.py ──► tools/  (fs, shell, web, notebook,
        │                                  diagnostics, interaction, …)
        │                        + memory/, multi_agent/, skill/, mcp_client/,
        │                          task/, checkpoint/hooks, plugins, modular/
        │
        ├──► compaction.py ── snip + LLM-summarize old turns
        │
        ├──► quota.py + circuit_breaker.py + error_classifier.py
        │         (API-failure resilience layer, always on)
        │
        └──► runtime.py ── RuntimeContext (per-session live state)
                │
                └──► bridges/  (telegram / wechat / slack) wire
                     incoming messages to runtime callbacks
```

**Dependencies flow downward**: nothing in `tools/` or feature packages
imports from `cheetahclaws/cli.py` or `agent.py` at module load time.
Circular references are broken with lazy imports inside functions
(`multi_agent.subagent` calls back into `agent` this way).

---

## Repository layout

Three layers coexist in this repo, on purpose:

### 1. Top-level runtime (root `.py` files)

These are the per-session, per-turn workhorses.  Each one has a narrow
responsibility.

| Module | Role |
|---|---|
| [`cheetahclaws/cli.py`](../cheetahclaws/cli.py) | REPL shell, `COMMANDS` dispatch, permission prompt UI, streaming render, entry point (`main()`) |
| [`bootstrap.py`](../cheetahclaws/bootstrap.py) | Explicit startup sequence — configure logging, import `tools` (triggers registrations), optionally start health HTTP server.  Idempotent. |
| [`agent.py`](../cheetahclaws/agent.py) | Multi-turn agent loop (generator yielding typed events), permission gating, parallel tool execution, retry-with-backoff on API errors |
| [`agent_runner.py`](../cheetahclaws/agent_runner.py) | Autonomous loop runner — runs a Markdown agent template (`agent_templates/*.md`) in a background thread, with iteration logging and bridge notifications |
| [`context.py`](../cheetahclaws/context.py) | System-prompt assembly (base prompt + env block + memory + tmux/plan fragments) + prompt-injection threat scanner |
| [`compaction.py`](../cheetahclaws/compaction.py) | Context-window management: cheap snip layer + LLM-driven summarization layer |
| [`providers.py`](../cheetahclaws/providers.py) | Provider registry (`PROVIDERS` dict), auto-detection by model prefix, streaming adapters for Anthropic native + OpenAI-compatible APIs |
| [`tool_registry.py`](../cheetahclaws/tool_registry.py) | Central `ToolDef` registry, dispatch, output truncation |
| [`runtime.py`](../cheetahclaws/runtime.py) | `RuntimeContext` — per-session live state (callbacks, bridge flags, plan-mode state, streaming hooks). **Not** persisted. |
| [`config.py`](../cheetahclaws/config.py) | Defaults + `~/.cheetahclaws/config.json` load/save.  Strips `_`-prefixed keys on save. |
| [`quota.py`](../cheetahclaws/quota.py) | Per-session and daily token/cost budgets.  Checked before every API call. |
| [`circuit_breaker.py`](../cheetahclaws/circuit_breaker.py) | Trip-open-after-N-failures protection around provider calls. |
| [`error_classifier.py`](../cheetahclaws/error_classifier.py) | Categorize API errors (rate limit / context-too-long / network / transient) so `agent.run()` can pick the right retry strategy. |
| [`logging_utils.py`](../cheetahclaws/logging_utils.py) | Structured logging facade (info/warn/error with kwargs).  Configured from `config["log_level"]` / `config["log_file"]`. |
| [`session_store.py`](../cheetahclaws/session_store.py) | On-disk session history (daily rotation + cap) and `session_latest.json` for `/resume`. |
| [`jobs.py`](../cheetahclaws/jobs.py) | Background job bookkeeping used by `/worker` and subscription runs. |
| [`health.py`](../cheetahclaws/health.py) | Optional HTTP health endpoint started by bootstrap when `health_check_port` is set. |
| [`tmux_tools.py`](../cheetahclaws/tmux_tools.py) | Tmux `TmuxNewSession` / `TmuxSendKeys` / … tool definitions (register at import). |
| [`auxiliary.py`](../cheetahclaws/auxiliary.py) | Small helper(s) for an "auxiliary" cheap model (used for compaction summaries and the like). |

### 2. Packages

Each directory is a coherent feature or subsystem with its own
internal structure.

| Package | What it owns |
|---|---|
| [`tools/`](../cheetahclaws/tools) | All built-in LLM-callable tools.  `tools/__init__.py` holds `TOOL_SCHEMAS`, calls `_register_builtins()`, and imports extension modules.  One file per category: `fs.py`, `shell.py`, `web.py`, `notebook.py`, `diagnostics.py`, `security.py`, `interaction.py`, plus optional `browser.py`, `email.py`, `files.py`. |
| [`commands/`](../cheetahclaws/commands) | Slash-command handlers.  `core.py` (help/clear/context/cost/…), `config_cmd.py` (model/config/permissions), `session.py` (save/load/resume), `advanced.py` (brainstorm/worker/ssj/memory/agents/skills/mcp/plugin/tasks — `/brainstorm` runs a lead-moderated multi-round adversarial debate; see [`docs/guides/brainstorm.md`](guides/brainstorm.md)), `checkpoint_plan.py` (checkpoint/rewind/plan), `agent_cmd.py` (/agent), `monitor_cmd.py` (subscribe/monitor). |
| [`bridges/`](../cheetahclaws/bridges) | External messaging adapters: `telegram.py`, `wechat.py`, `slack.py`, plus shared `interactive_session.py` and `terminal_runner.py`. |
| [`ui/`](../cheetahclaws/ui) | Terminal rendering — `input.py` (prompt_toolkit / readline; slash completion + ghost text), `suggest.py` (auxiliary-model draft of the likely next prompt, pushed into `input.py` as ghost text), `render.py` (rich Markdown, ANSI helpers, spinners, status line). |
| [`web/`](../cheetahclaws/web) | Optional self-hosted web UI (FastAPI-style — xterm.js frontend, SQLite session store, per-user auth).  Enabled by `[web]` extra. |
| [`memory/`](../cheetahclaws/memory) | Persistent memory across sessions — `store.py` (CRUD), `scan.py`/`context.py` (index + freshness), `consolidator.py` (`/memory consolidate`), `tools.py` (`MemorySave` / `MemoryDelete` / `MemorySearch` / `MemoryList`). |
| [`multi_agent/`](../cheetahclaws/multi_agent) | Sub-agent subsystem.  `subagent.py` owns `SubAgentManager` (ThreadPoolExecutor), depth gating, git-worktree isolation; `tools.py` exposes `Agent` / `SendMessage` / `CheckAgentResult` / `ListAgentTasks` / `ListAgentTypes`. |
| [`skill/`](../cheetahclaws/skill) | Markdown-based skill templates — `loader.py` parses frontmatter + resolves project→user→built-in precedence, `executor.py` runs a skill inline or in a fork, `builtin.py` ships a few default skills, `tools.py` exposes `Skill` / `SkillList`. |
| [`mcp_client/`](../cheetahclaws/mcp_client) | MCP (Model Context Protocol) client — `config.py` loads `.mcp.json`, `client.py` speaks stdio/SSE/HTTP JSON-RPC, `tools.py` connects servers and registers each remote tool as `mcp__<server>__<tool>`.  Renamed from `mcp/` to avoid stdlib collision. |
| [`task/`](../cheetahclaws/task) | In-session task list — `types.py` (model + status enum), `store.py` (thread-safe CRUD + dependency-edge maintenance), `tools.py` (`TaskCreate` / `TaskUpdate` / `TaskGet` / `TaskList`). |
| [`checkpoint/`](../cheetahclaws/checkpoint) | Auto-snapshot of conversation + file state after every turn.  `types.py` data models, `store.py` backup + rewind, `hooks.py` monkey-patches `Write` / `Edit` / `NotebookEdit` to snapshot pre-edit.  Command wiring in `commands/checkpoint_plan.py`. |
| [`plugin/`](../cheetahclaws/plugin) | Plugin install / enable / disable / update from git URLs or local paths.  `loader.py` imports user plugins and registers their `TOOL_DEFS` / `COMMAND_DEFS`; `recommend.py` scores plugin marketplace by keyword/tag match. |
| [`monitor/`](../cheetahclaws/monitor) | AI-monitored topic subscriptions — `fetchers.py` (arxiv / stocks / crypto / news), `summarizer.py` (LLM-based), `scheduler.py` (cron-ish), `notifier.py` (Telegram/Slack/stdout), `store.py` (subscription state). |
| [`prompts/`](../cheetahclaws/prompts) | System-prompt assets as plain Markdown — `base/default.md` is the shared baseline for every model; `overlays/<family>.md` (claude / gemini / openai-reasoning / qwen) appends short, vendor-documented quirks on top; `fragments/{tmux,plan}.md` are conditional blocks.  `select.py::pick_base_prompt` assembles base + matched overlay; `load_fragment` reads the conditional blocks.  See [`prompts/README.md`](../cheetahclaws/prompts/README.md) for the overlay-admission policy. |
| [`modular/`](../cheetahclaws/modular) | Auto-discovered optional feature modules.  Each subdir exposes `cmd.py::COMMAND_DEFS` and/or `tools.py::TOOL_DEFS`; `modular/__init__.py::load_all_commands` picks them up at startup.  Ships with `modular/voice/`, `modular/video/`, `modular/trading/`. |

### 3. Backward-compat shims

A few root `.py` files now just re-export from the moved package.  They
exist because third-party plugin code and some legacy imports still
reference them.  **Edit the underlying package; keep the shim public
surface stable.**

| Shim | Re-exports from |
|---|---|
| [`memory.py`](../cheetahclaws/memory.py) | `memory/` package |
| [`skills.py`](../cheetahclaws/skills.py) | `skill/` package |
| [`subagent.py`](../cheetahclaws/subagent.py) | `multi_agent/subagent` module |

---

## Core subsystems in depth

### Tool registry

Every LLM-callable capability is a `ToolDef` entered into a single
process-wide registry.

```python
# tool_registry.py
@dataclass
class ToolDef:
    name: str               # unique identifier (e.g. "Read", "MemorySave")
    schema: dict            # JSON schema sent to the LLM API
    func: Callable          # (params: dict, config: dict) -> str
    read_only: bool         # auto-approved in 'auto' permission mode
    concurrent_safe: bool   # safe to run in parallel with others in a turn
```

**Five registration paths** all feed the same registry:

1. **Built-ins** — `tools/__init__.py::_register_builtins()` runs at
   module import.  Registers 13+ core tools (Read, Write, Edit, Bash,
   Glob, Grep, WebFetch, WebSearch, NotebookEdit, GetDiagnostics,
   AskUserQuestion, SleepTimer, plus `EnterPlanMode` / `ExitPlanMode`
   at the bottom of the file).
2. **Extension packages** — a `_EXTENSION_MODULES` list in
   `tools/__init__.py` (`memory.tools`, `multi_agent.tools`,
   `skill.tools`, `mcp_client.tools`, `task.tools`) is imported for side
   effects; each module calls `register_tool()` at its own import time.
   Failures are swallowed (extensions are best-effort).
3. **Plugins** — user-installed packages expose a `TOOL_DEFS` list; the
   loader in `plugin/loader.py::register_plugin_tools()` iterates and
   registers.  **Plugin code must not call `register_tool()` directly.**
4. **Modular ecosystem** — `modular/<name>/tools.py::TOOL_DEFS`
   collected via `modular.load_all_tools()`.  Auto-discovered, no
   wiring required.
5. **Checkpoint hooks** — `checkpoint/hooks.py::install_hooks()`
   monkey-patches the already-registered Write / Edit / NotebookEdit
   tools so each mutation snapshots the pre-state.  Runs *after*
   `_register_builtins()` at the bottom of `tools/__init__.py`;
   ordering matters.

**Output truncation** — `execute_tool(name, params, config, max_output)`
truncates any result larger than `max_output` (default 32 000 chars)
to `first_half + "[... N chars truncated ...]" + last_quarter`.  This
is the first line of defense against a runaway tool blowing up context.

**Auto-fanout** (`multi_agent/fanout.py`) is the *second* line of defense,
running between tool execution and conversation-history append in `agent.py`:
when a single tool result still exceeds `0.4 × ctx_window` after
`execute_tool`'s truncation (e.g. a PDF that fits within 32 K chars but
estimates to >13 K tokens on a 32 K-context model), `should_fanout` fires
and `fanout_summarize` chunks the text at paragraph boundaries with
token overlap, dispatches parallel sub-LLM map calls (cap default 5),
then a single reduce call merges the per-chunk summaries. The merged
summary replaces the original result before it enters `state.messages`,
so the next API call sees a tractable input. Fanout is opportunistic:
any internal failure falls through to the original (potentially over-
sized) result and lets the downstream layers (compaction, dynamic cap)
try.

**Per-call dynamic max_tokens cap** (`providers.dynamic_cap_max_tokens`)
is the *third* line — even after fanout, before each API call we estimate
the actual prompt size (messages + system + tool schemas) and shrink
`max_tokens` so that `input + output + 1024 safety ≤ ctx_window`. This
matters most for 32 K-context local models (Qwen 2.5/3, Mistral, Llama 3
small variants) where a single big tool result can come close to the
limit even after compaction. The per-model context window comes from
`providers._MODEL_CONTEXT_LIMITS` (registry of known local models) or,
for `custom/...` providers, a live `/v1/models` query that backfills
`PROVIDERS["custom"]["context_limit"]` so subsequent `compaction.
get_context_limit` calls see the real value instead of the stale 128 K
default.

**Auto-compact** (`compaction.maybe_compact`) is the *fourth* line — when
the conversation history (not a single tool result) crosses 70 % of the
ctx window, snip old tool outputs first, then if still over threshold
LLM-summarize older turns into a compressed system message.

### Agent loop

`agent.run(user_message, state, config, system_prompt, depth,
cancel_check) -> Generator` is the core multi-turn loop.  Callers
consume the event stream; nothing else drives the model.

```
1. Append user message (possibly attach pending image)
2. Inject transient keys into config: _depth, _system_prompt
3. Loop:
   a. If cancel_check() → return
   b. maybe_compact(state, config)    # snip → summarize if still big
   c. sanitize_history(state.messages) # enforce tool_calls ↔ tool-response pairing
   d. Quota check                      # raise [Quota exceeded] and break
   e. Stream from provider, retrying up to 3× on retryable errors:
        TextChunk / ThinkingChunk → yield to caller
        AssistantTurn             → capture
        — On RATE_LIMIT for a NIM model AND `nim_auto_fallback=True`,
          swap to the next model in the curated NIM chain
          (`providers.nim_next_model`) without consuming a retry slot.
          Capped at 3 swaps/turn so a fully-throttled tier can't busy-
          loop; falls through to standard backoff after the cap.
   f. Record assistant turn in state.messages
   g. yield TurnDone(in_tokens, out_tokens)
   h. If no tool_calls:
        - if user message contained an absolute path AND we have NOT
          yet nudged this run() call: append a one-shot "[system
          reminder] use your tools, don't ask for what was given"
          message to state.messages and continue back to step 3a.
          Bounded to one nudge per user turn — second text-only reply
          always falls through to break. See `_looks_like_investigation`
          in agent.py.
        - otherwise: break (conversation turn complete)
   i. Permission gate each tool_call (sequential — may prompt user).
      For each read-only call (Read/Glob/Grep/WebFetch/WebSearch),
      compute `(name, args)` signature; if already seen in this run(),
      mark redundant — `_exec_one` short-circuits to a `[deduped]`
      reminder and ToolStart/ToolEnd UI yields are suppressed (a
      brief `[deduped X: already in context]` text marker is yielded
      instead). The synthetic tool_result is still appended to
      state.messages so OpenAI/Anthropic tool_calls ↔ tool_response
      pairing stays valid. Write/Edit/Bash are NOT deduped (intentional
      rewrites are common).
   j. Execute:
        - parallel batch for concurrent_safe tools when >1 in a turn
        - sequential batch for everything else
   k. yield ToolEnd(name, result, permitted) in original order
   l. Append each tool result to state.messages, loop back to step 3d
```

**Event types** the caller sees:

| Event | Fields | When |
|---|---|---|
| `TextChunk` | `text` | Streaming text delta |
| `ThinkingChunk` | `text` | Extended thinking (Claude) or reasoning stream (o1/o3/deepseek-r1) |
| `ToolStart` | `name, inputs` | Just before a tool is invoked |
| `ToolEnd` | `name, result, permitted` | After tool completes (or was denied) |
| `PermissionRequest` | `description, granted` | Needs user approval; caller sets `.granted` |
| `TurnDone` | `input_tokens, output_tokens` | End of one API call |

**Session-level token totals** live on `AgentState`, not on the per-turn event:

| Field | Source |
|---|---|
| `total_input_tokens` / `total_output_tokens` | Summed from each turn's `in_tokens` / `out_tokens` |
| `total_cache_read_tokens` / `total_cache_write_tokens` | Summed from each turn's `cache_read_tokens` / `cache_write_tokens` via `getattr(..., 0)`. Anthropic populates both; OpenAI-schema providers populate read-only (their spec has no cache-write counter); Ollama and custom providers default to 0. |

All four totals are persisted into `checkpoint/store.make_snapshot`'s `token_snapshot` dict and restored on `/checkpoint <id>` / `/rewind`, so rewind never leaves the running counters out of sync with the snapshot they were rewound to.

Error handling is classified (`error_classifier.classify`) into
`retryable / context-too-long / auth / network / unknown`.  Retryable
errors back off exponentially (bounded to 30 s); context-too-long
triggers a forced compaction mid-turn; circuit-open errors short-circuit
to avoid hammering a failing provider.

### Provider abstraction

`providers.py` keeps a `PROVIDERS` dict of provider metadata (API key
env var, base URL, context limit, known model IDs, per-provider
`max_completion_tokens` cap).  `detect_provider(model_id)` auto-routes
based on the model string:

```python
# Illustrative (not exhaustive)
"claude-opus-4-7"                 → anthropic
"gpt-5"                           → openai
"gemini-3.1-pro-preview"          → gemini
"qwen/Qwen3-MAX"                  → qwen
"ollama/qwen2.5-coder"            → ollama  (explicit prefix)
"custom/my-endpoint"              → custom
"nim/meta/llama-3.3-70b-instruct" → nim     (build.nvidia.com free tier)
"openrouter/deepseek/deepseek-v4-flash" → openrouter  (400+ models, one key)
"requesty/openai/gpt-4o-mini"           → requesty    (700+ models, one key)
```

`stream(model, system, messages, tool_schemas, config) -> Generator`
is the one entry point agent.py uses.  Internally it dispatches to
`stream_anthropic()` (native SDK) or `stream_openai_compat()` (used by
every OpenAI-compatible provider).

**Gateway model IDs are multi-level.** OpenRouter, Requesty, NIM and LiteLLM
address models by an upstream `<vendor>/<model>` path, so only the first
segment is the provider and `bare_model()` deliberately strips just that
one.  Two consequences the rest of the file relies on:

* The provider name cannot be re-derived downstream — `bare_model()`'s
  output (`deepseek/deepseek-v4-flash`) reads as a *different* provider.
  `stream()` therefore passes the resolved name in `config["_provider_name"]`,
  and `stream_openai_compat()` reads that instead of re-detecting.
* Per-model registries (`COSTS`, `_MODEL_CONTEXT_LIMITS`) are keyed by
  plain model name, so lookups fall back to `lookup_model_key()` — which
  drops both the vendor path and OpenRouter's optional
  `@<provider>[/<quantization>]` routing suffix.  Without it a gateway
  route silently prices at $0 and reads the provider-level context
  default instead of the model's own.

**OpenRouter provider pinning.** `parse_openrouter_routing()` splits the
`@<provider>[/<quantization>]` suffix off the model ID and stores it in
`config["_openrouter_provider"]`; `stream_openai_compat()` forwards it as
the `provider` object in `extra_body`.  Provider selection is a
request-body element in OpenRouter's API — glued into the model ID it
would be rejected as an unknown model.

**NIM 429 cascade.** The `nim` provider points at `build.nvidia.com`'s
free OpenAI-compatible endpoint with a curated 10-model chain
(deepseek-r1, llama-3.3-70b, qwen2.5-coder-32b, …).  When one model
returns a rate-limit error, the agent loop calls
`providers.nim_next_model()` and retries with the next model in the
chain — no retry slot consumed.  Capped at 3 swaps per turn so a
fully-throttled tier can't busy-loop; falls through to the regular
exponential-backoff retry path after the cap.  Disabled by setting
`config["nim_auto_fallback"] = False`.  Other providers (anthropic,
openai, etc.) are not affected — the swap is gated by
`detect_provider(model) == "nim"`.

**Neutral message format** — the single internal contract agent.py,
providers.py, compaction.py, and session_store.py all agree on:

```python
{"role": "user",      "content": "...", "images": [...]?}
{"role": "assistant", "content": "...", "tool_calls": [{"id", "name", "input", "extra_content"?}]}
{"role": "tool",      "tool_call_id": "...", "name": "...", "content": "..."}
```

Adapter functions `messages_to_anthropic()` and `messages_to_openai()`
convert bidirectionally.  **Preserve tool_call IDs exactly** — some
providers are strict.  Gemini 3 additionally requires an opaque
`thought_signature` round-tripped on every tool_call; this is carried
transparently through `extra_content`.

### Context (system prompt) assembly

`context.build_system_prompt(config)` is the only public entry point.
The prompt content itself lives in `prompts/` as plain Markdown — no
inline strings in code — and the assembly is:

```
build_system_prompt(config) ->
    pick_base_prompt(provider, model_id)     # default.md + matched overlay
  + _render_env_block(config)                # date, cwd, platform, git, CLAUDE.md
  + memory index                             # memory.get_memory_context(), if non-empty
  + tmux fragment                            # prompts/fragments/tmux.md, if tmux_available()
  + plan-mode fragment                       # prompts/fragments/plan.md, if permission_mode == "plan"
```

The prompt subsystem is **single base + small family overlays**:

```
prompts/
├── select.py             # pick_base_prompt + load_fragment (lru_cache'd)
├── base/
│   └── default.md        # shared baseline for every model (~150-line cap)
├── overlays/
│   ├── claude.md         # XML-tag preference (Anthropic guide)
│   ├── gemini.md         # explicit "Agentic Mode" framing (Gemini 3 guide)
│   ├── openai-reasoning.md  # don't narrate CoT (o1 / o3 / o4 / gpt-5-codex)
│   └── qwen.md           # "call the tool, don't ask the user" (Qwen function-calling guide)
└── fragments/
    ├── tmux.md
    └── plan.md
```

Every model starts from the same `default.md` (general prompt-engineering
guidance — be concise, parallel tool calls, minimal scope, stop conditions,
safe-vs-unsafe action list, etc.).  An overlay is appended only when the
model has an **authoritative, vendor-documented quirk**; the overlay file
must cite its source URL in a top-of-file `<!-- Source: ... -->` comment
(enforced by `tests/test_prompt_size.py::test_overlay_cites_source`) and
must be ≤ 20 lines.  Overlay routing is by **model family**, not provider
or runtime — Qwen-3 served via DashScope, Ollama, vLLM, or OpenRouter all
get the same prompt.

Contributor guidance and the overlay-admission policy live in
[`prompts/README.md`](../cheetahclaws/prompts/README.md).

`context.py` also runs a regex scan on any CLAUDE.md content before
inclusion — patterns like "ignore previous instructions", "you are
now…", or shell commands dereferencing `$ANTHROPIC_API_KEY` are
flagged and the file is excluded with a warning to stderr.  This is
best-effort, not a security boundary.

### Compaction

Two layers, applied in order only when needed.

**Layer 1 — snip** (`snip_old_tool_results`):

- Rule-based, no API cost.
- Truncates tool-role messages older than `preserve_last_n_turns`
  (default 6) to first-half + last-quarter.
- Run unconditionally before each streaming call.

**Layer 2 — auto-compact** (`compact_messages`):

- LLM-driven: calls the current model (or an auxiliary cheaper model
  via `auxiliary.py`) to summarize old turns.
- Splits messages into `[old | recent]` roughly at the 70/30 mark by
  token count, replaces `old` with a summary + acknowledgement turn.
- Preserves the plan-mode plan file content across compactions
  (`_restore_plan_context`).

**Trigger** — `maybe_compact(state, config)` fires when
`estimate_tokens(messages) > context_limit * 0.7`.  The model's
context limit is read from `providers.PROVIDERS[provider]["context_limit"]`.

Token estimation is a crude `len(text) / 3.5`.  Good enough for the
threshold decision; the SDK returns real counts after each call for
billing/quota.

### Permission model

Four modes, set by `config["permission_mode"]` and checked in
`agent.py::_check_permission`:

| Mode | Reads | Writes | Bash (unsafe) | Plan-file write |
|---|---|---|---|---|
| `auto` (default) | auto-approved | prompt | prompt | n/a |
| `accept-all` | auto | auto | auto | n/a |
| `manual` | prompt | prompt | prompt | prompt |
| `plan` | auto | **blocked** | _is_safe_bash only | auto-approved |

`EnterPlanMode` and `ExitPlanMode` are always auto-approved so the
model can enter/exit plan mode without interactive friction.

Plus two security layers that apply regardless of mode:

- **`allowed_root`** (`config.py` default `None`) — if set to a
  path, restricts file tools (Read / Write / Edit / Glob / Grep) to
  that subtree.  Null means unrestricted (CLI default).
- **`shell_policy`** — `allow` (default) / `log` / `deny` for the
  Bash tool.

### Parallel tool execution

When an assistant turn produces more than one tool call, `agent.run()`
batches them:

- **Parallel batch** — tool calls where `ToolDef.concurrent_safe=True`
  AND the turn has >1 call; run via a `ThreadPoolExecutor(max_workers=8)`.
- **Sequential batch** — everything else, one at a time.

Permission-denied calls always go to the sequential batch so the model
gets a consistent "denied" result.  Yielded `ToolEnd` events preserve
the **original tool_call order**, not the completion order, so the
assistant sees results in the order it asked for them.

Mark `concurrent_safe=False` for anything touching shared mutable
state (files, process spawn, bridge sockets, global registries).

---

## Cross-cutting services

### Quota

`quota.py` checks a per-session and per-day budget before every API
call and records usage after.  Budgets are:

- `session_token_budget`, `session_cost_budget` — per `_session_id`.
- `daily_token_budget`, `daily_cost_budget` — aggregated across all
  sessions for today.

All four default to `None` (unlimited) in `config.DEFAULTS`.  When
exceeded, `agent.run()` yields a `TextChunk("[Quota exceeded — …]")`
and breaks the loop.  Long-running / autonomous workflows should turn
these on.

### Circuit breaker

`circuit_breaker.py` tracks consecutive failures against a provider.
After `circuit_failure_threshold` failures within
`circuit_window_seconds`, the circuit opens for
`circuit_cooldown_seconds`; calls during the cooldown raise
`CircuitOpenError` which the agent loop surfaces as
`[Circuit open — …]` rather than hammering a failing endpoint.

### Error classification

`error_classifier.classify(exc)` returns a `ClassifiedError` with:

- `category` (rate_limit / context_too_long / auth / network / transient / unknown)
- `retryable: bool`
- `should_compress: bool` — true for context-too-long; triggers a
  forced compaction mid-turn.
- `backoff_multiplier: float` — scales the exponential backoff.
- `hint: str | None` — actionable message (e.g. "check OPENAI_API_KEY").

### Logging

`logging_utils.py` is a thin structured-logging facade:

```python
import logging_utils as _log
_log.info("tool_start", session_id="abc", tool="Read", input_keys=["file_path"])
```

Configured by `configure_from_config(config)` during bootstrap.
Output goes to stderr by default; set `config["log_file"]` to persist.
Levels: `off` / `error` / `warn` / `info` / `debug`.  Default `warn`
to keep the interactive CLI quiet.

### Session persistence

`session_store.py` writes on `/exit`, `/quit`, Ctrl+C, and Ctrl+D:

- `~/.cheetahclaws/sessions/daily/YYYY-MM-DD/session_<ts>.json`
  (capped by `session_daily_limit`).
- `~/.cheetahclaws/sessions/history.json` (capped by
  `session_history_limit`).
- `~/.cheetahclaws/sessions/mr_sessions/session_latest.json` for
  `/resume`.

The web UI (`web/`) uses its own SQLite store (`web/db.py`) for
multi-user history; the two don't share state today.

---

## REPL and slash commands

`cheetahclaws/cli.py::main()` runs the CLI, parses args, calls
`bootstrap(config)`, then enters `repl(config, initial_prompt)`.

The REPL loop:

1. Read input (via `ui.input.read_input` — prompt_toolkit when
   available, else readline).  Under prompt_toolkit the prompt also
   carries ghost text: the predicted next message published by
   `ui.suggest` (Tab accepts), falling back to shell history.
2. If it starts with `/`, dispatch via the `COMMANDS` dict.
3. Otherwise, call `agent.run()` and render the event stream with
   `ui.render`.
4. After every turn, run checkpoint snapshot (throttled), autosave the
   session, and — foreground turns only — kick off `ui.suggest.schedule()`
   on a background thread to draft the next prompt's ghost text.
5. Handle Ctrl+C (3× within 2 s triggers `os._exit(1)` to escape
   stuck I/O).

`COMMANDS` is a flat `{name: callable}` dict built in
`cheetahclaws/cli.py` by importing every `cmd_*` from `commands/*.py`.
Plugins and `modular/` modules can contribute additional entries via
`_load_external_commands_into(COMMANDS)`.

---

## Feature subsystems

### Sub-agents (`multi_agent/`)

`SubAgentManager` owns a `concurrent.futures.ThreadPoolExecutor`
(default 3 workers).  Each spawned sub-agent:

- Starts with **fresh message history** + task prompt.
- Runs `agent.run()` with `depth + 1`.
- Optionally creates an isolated **git worktree** (`isolation="worktree"`)
  on a short-lived branch for parallel file edits without conflicts.
- Is cancelled **cooperatively** — Python threads can't be killed
  safely, so `cancel(task_id)` sets a flag checked at the top of each
  loop iteration.

Depth is bounded at 3 (`max_agent_depth`) and checked at `spawn` time;
the model gets an error string rather than a silently-removed tool so
it can adjust strategy.

Agent *types* are loaded from `~/.cheetahclaws/agents/<name>.md`
(Markdown with YAML frontmatter: `model`, `tools`, extra system
prompt).  Five built-ins: `general-purpose`, `coder`, `reviewer`,
`researcher`, `tester`.

### Plan mode (`commands/checkpoint_plan.py` + `tools/__init__.py`)

`/plan <desc>` sets `config["permission_mode"] = "plan"` and creates a
plan file at `.nano_claude/plans/<session_id>.md`.  The only write the
model can perform in this mode is to that file; everything else
returns a `[Plan mode]` message explaining the restriction.

Two agent-callable tools — `EnterPlanMode` and `ExitPlanMode` — let
the model enter/exit plan mode autonomously on complex requests.
`ExitPlanMode` refuses to exit if the plan file is empty, forcing the
model to actually write the plan before resuming normal permissions.

**The historical path `.nano_claude/plans/…` is intentional** (dates
from when the project was called "Nano Claude Code").  Don't rename
without updating plan mode code.

### Checkpoint (`checkpoint/`)

After every turn, `checkpoint/store.py` captures:

- A post-edit copy of every file the turn modified.
- A full snapshot of the conversation state.

100-snapshot sliding window per session.  `/checkpoint <id>` or
`/rewind <id>` atomically restores both files **and** message history
to that point.  Instrumented by `checkpoint/hooks.py::install_hooks`
which wraps the Write / Edit / NotebookEdit tool functions
post-registration.

### Memory (`memory/`)

Dual-scope file-based store:

- User scope — `~/.cheetahclaws/memory/<slug>.md` (shared).
- Project scope — `.cheetahclaws/memory/<slug>.md` (per cwd).

Each memory is a Markdown file with YAML frontmatter (`name`,
`description`, `type` ∈ `{user, feedback, project, reference}`,
`confidence`, `source`, `last_used_at`, `conflict_group`).  Index
files (`MEMORY.md`) are auto-maintained and injected into every system
prompt.

`MemorySearch` re-ranks results by `confidence × 30-day recency
decay` and refreshes `last_used_at` on hits.  `/memory consolidate`
runs a cheap LLM pass over the current session and saves up to 3
high-confidence insights without overwriting higher-confidence user
entries.

### MCP (`mcp_client/`)

Standard MCP client.  Supports stdio (subprocess), SSE, and
streamable HTTP transports.  `.mcp.json` in the project root or
`~/.cheetahclaws/mcp.json` (user scope) lists servers; `/mcp reload`
reconnects.  Every discovered remote tool is registered as
`mcp__<server>__<tool>` and participates in the normal permission /
execution flow.

Renamed from `mcp/` to `mcp_client/` to avoid import-time collision with
Python's stdlib namespace and the `modelcontextprotocol` package.
**Import from `mcp_client`, not `mcp`.**

### Tasks (`task/`)

Structured in-session task list with a dependency graph.
`TaskCreate` / `TaskUpdate` support `add_blocks` / `add_blocked_by`
edges; `TaskList` formats remaining blockers for each open task.
Persisted to `.cheetahclaws/tasks.json` per cwd.

Distinct from `TodoWrite` in other coding agents — CheetahClaws
tasks have **IDs, statuses (`pending / in_progress / completed /
cancelled / deleted`), owners, metadata, and dependencies**, not a
flat checkbox list.

### Skills (`skill/`)

Markdown-with-frontmatter prompt templates.  `Skill(name, args)`
loads the file, substitutes `$ARGUMENTS`, and either runs the prompt
inline in the current session or forks a sub-agent.  Precedence:
project `.cheetahclaws/skills/` → user `~/.cheetahclaws/skills/` →
built-in (`skill/builtin.py`).  Two built-ins ship: `/commit` and
`/review`.

### Plugins (`plugin/`)

`/plugin install <name>@<git-url-or-local-path>` clones the plugin,
reads `plugin.json` (or `PLUGIN.md` with YAML frontmatter), and
registers declared `tools` / `skills` / `commands` / `mcp_servers`.
**Plugins export `TOOL_DEFS` / `COMMAND_DEFS` lists — they do not
call `register_tool()` directly.**

Scopes: user (`~/.cheetahclaws/plugins/`) and project
(`.cheetahclaws/plugins/`).  `/plugin recommend [context]` scores the
built-in marketplace by tag/keyword match.

### Monitoring (`monitor/`)

`/subscribe <topic> [schedule]` registers an AI-monitored topic:

- `fetchers.py` talks to the topic source (arxiv, yfinance, CoinGecko,
  RSS for news, or a custom search query).
- `summarizer.py` asks the LLM to produce a readable summary.
- `scheduler.py` runs subscriptions on cron-style intervals
  (15m / hourly / daily / weekly).
- `notifier.py` pushes the output to Telegram / Slack / console.
- `store.py` holds subscription state.

`/monitor start` launches the background scheduler; `/monitor run`
executes all subscriptions once synchronously.

### Bridges (`bridges/`)

Each bridge wraps an incoming-message channel and hooks it into
`RuntimeContext`:

- `telegram.py` — Bot API long-polling, typing indicator, slash
  passthrough.
- `wechat.py` — iLink QR login, personal WeChat account.
- `slack.py` — Web API polling of `conversations.history`, stdlib
  `urllib` only (no `slack_sdk` dependency).

Common pattern: set a thread-local flag on entry (`_is_in_tg_turn`),
overwrite `RuntimeContext.tg_send` / `slack_send` / `wx_send`, route
the incoming text to `runtime.ctx.run_query(...)`, then clear the
flag.  `AskUserQuestion` and permission prompts use bridge-specific
synchronous-input events (`tg_input_event` / `slack_input_event` /
`wx_input_event`) to round-trip through the chat.

### Autonomous agent runner (`agent_runner.py`)

`/agent start <template> [args]` launches an autonomous loop that
repeatedly calls `agent.run()` on a Markdown task program (from
[`agent_templates/`](../agent_templates) or
`~/.cheetahclaws/agent_templates/`).  Built-in templates:
`auto_bug_fixer`, `auto_coder`, `paper_writer`, `research_assistant`,
plus `modular/trading/agent_templates/trading_agent.md`.

Per-iteration behavior:

- Runs with `auto_approve=true` so permission prompts don't block.
- Emits a ≤500-char summary via `send_fn` (bridge or stdout) after
  each iteration.
- Persists iteration records to
  `~/.cheetahclaws/agents/<name>/log.jsonl`.
- Wakes up on `stop_event.wait(interval)` — set `interval` small for
  active monitoring, large for batch work.

**F-4 execution mode (subprocess, opt-in).** On POSIX, setting
`CHEETAHCLAWS_ENABLE_F4=1` or `agent_runner_subprocess: true` flips
`start_runner` from threading to subprocess-per-runner. Each runner
becomes a `python -m agent_runner --pipe` child supervised by
`daemon.runner_supervisor`; iteration boundaries and crashes are
observable on the daemon event bus and persisted to the `agent_runs`
/ `agent_iterations` SQLite tables. The threaded path stays the
default so REPL behaviour is byte-for-byte unchanged. See
[RFC 0002 §F-4](RFC/0002-daemon-foundation-roadmap.md#f-4--agent_runner-subprocess)
for the wire protocol and lifecycle.

This is the closest thing the project has to a "7 × 24 agent"
runtime today; see CONTRIBUTING.md for the current production-
readiness gaps (daemon mode, SQLite session store, cost guardrails).
The daemon-mode work is tracked in [issue #68](https://github.com/SafeRL-Lab/cheetahclaws/issues/68);
the IPC / permission-routing / local-auth contract is captured in
[RFC 0001](RFC/0001-daemon-design-note.md) and validated end-to-end by
the `daemon/` reference scaffolding ([spike notes](RFC/0001-spike-notes.md)).

### Modular ecosystem (`modular/`)

Auto-discovered drop-in modules.  `modular/__init__.py::load_all_commands()`
scans every subdir for `cmd.py::COMMAND_DEFS` and `tools.py::TOOL_DEFS`;
found commands/tools are merged into `COMMANDS` / the tool registry
with no explicit wiring.

Ships with:

- `modular/voice/` — recording (`sounddevice`/`arecord`/`sox`), STT
  (`faster-whisper`/`openai-whisper`/OpenAI API), TTS generation.
  Replaces the older top-level `voice/`.
- `modular/video/` — story → TTS → images → subtitles → MP4 pipeline.
- `modular/trading/` — multi-agent trading analysis (Bull/Bear debate
  → risk panel → portfolio manager), BM25 memory over past trades,
  four backtest strategies.

### Web UI (`web/`)

Optional self-hosted browser-accessible UI, enabled by `[web]` extra
(`sqlalchemy`, `passlib[bcrypt]`, `PyJWT`).  `web/server.py` runs an
HTTP server; `web/static/` serves an xterm.js frontend; `web/db.py`
persists per-user session history in SQLite.  Launched by `/web` slash
command inside the REPL.

The web UI will eventually become a client of the daemon described in
the next section (per [RFC 0001](RFC/0001-daemon-design-note.md));
today it stands alone.

### Daemon (`daemon/` + `commands/daemon_cmd.py`)

The headless `cheetahclaws serve` runtime — foundation for the
"long-running services survive REPL exit" work tracked in
[issue #68](https://github.com/SafeRL-Lab/cheetahclaws/issues/68).
Designed in [RFC 0001](RFC/0001-daemon-design-note.md);
implementation phasing in
[RFC 0002](RFC/0002-daemon-foundation-roadmap.md).
Reference scaffolding lives at
[RFC 0001 spike notes](RFC/0001-spike-notes.md) — the F-1 foundation
adopts that scaffolding wholesale and layers the integration glue on
top.

**Module map (foundation = spike + glue).**

Pulled in unchanged from the spike (these encode the wire contract):

- `daemon/__init__.py` — `API_VERSION = "0"`, `API_VERSION_HEADER =
  "Cheetahclaws-Api-Version"`.
- `daemon/server.py` — `ThreadedTCPServer` and `ThreadedUnixServer`
  (the latter conditional on `socketserver.UnixStreamServer`, so
  Windows skips it cleanly), 256-deep listen backlog, per-connection
  request handler, SSE loop with 15 s heartbeat, `Cheetahclaws-Api-Version`
  gate that returns `426` on mismatch.
- `daemon/auth.py` — `SO_PEERCRED` peer-cred check (Linux; macOS
  TODO), bearer-token auth for TCP, per-peer brute-force throttle,
  audit-log default-on for both transports.
- `daemon/originator.py` — `client_id` mint / persist
  (`~/.cheetahclaws/clients/<kind>.id`) / resume so disconnect-and-
  reconnect keeps the originator identity stable.
- `daemon/rpc.py` — JSON-RPC 2.0 dispatcher.  Application errors
  `-32001` (`not_originator`) and `-32002` (`unknown_request`) carry
  HTTP `403` so observers can't answer permission requests they don't
  own.
- `daemon/events.py` — in-memory ring buffer + per-subscriber Queue;
  emits a `gap` event on overflow so SSE clients know to re-sync.  F-2
  swaps the ring for the `daemon_events` SQLite table without changing
  the channel API.
- `daemon/permission.py` — pending-request store, originator-only
  `answer`, 30 min default interactive timeout + `permission.refresh_timeout`
  RPC.
- `daemon/methods.py` — spike's `echo.ping` / `permission.demo` /
  `permission.answer` / `permission.refresh_timeout` / `permission.list`.
- `daemon/spike_client.py` — stdlib smoke client, useful for manual
  debugging; not a runtime dependency.

Added by the F-1 foundation:

- `daemon/discovery.py` — atomic write/read of
  `~/.cheetahclaws/daemon.json` (pid, transport, address, started_at,
  schema version, plus an optional `token_path` recorded only when
  `serve --token-path` overrides the default location) so REPL / Web /
  bridge clients — and `cheetahclaws daemon {status, stop, rotate-token}`
  themselves — can locate the daemon and the token file it's actually
  using.  Auto-clears stale files when the recorded pid is no longer
  alive.
- `daemon/system_methods.py` — registers `system.ping` (RFC contract
  name; coexists with spike's `echo.ping`) and `system.shutdown`
  (triggers `DaemonState.shutdown_event`, our cross-platform graceful
  exit since Windows can't deliver SIGTERM cleanly to another Python
  process).
- `daemon/cli.py` — rewritten `serve_main(argv)` that calls
  `bootstrap()`, pins `log_file` to `<data_dir>/logs/daemon.log`,
  threads loaded config + `--unauthenticated-metrics` through
  `DaemonState`, writes the discovery file on bind, watches the
  shutdown event, and clears discovery on exit.
- `commands/daemon_cmd.py` — `cheetahclaws daemon {status, stop, logs,
  rotate-token}`.  All actions read the discovery file.  `stop` prefers
  the `system.shutdown` RPC and falls back to SIGTERM /
  TerminateProcess.  Sends the `Cheetahclaws-Api-Version: 0` header on
  every RPC.
- `health.py` — refactored: extracted `healthz_payload(config)` /
  `readyz_payload(config)` / `metrics_payload(config)` /
  `payload_for(path, config)` module-level helpers so both the existing
  standalone health HTTP server and `daemon/server.py` reuse the
  same circuit-breaker / quota / runtime-registry probes without
  starting a second listener.

Added by the F-4 skeleton (subprocess-per-agent — branch `daemon/f-4`,
[RFC 0002 §F-4](RFC/0002-daemon-foundation-roadmap.md#f-4--agent_runner-subprocess)):

- `daemon/runner_supervisor.py` — owns the lifecycle of one or more
  `python -m agent_runner --pipe` subprocesses. `start` /
  `stop` / `stop_all` / `get` / `list_all`. Three-phase stop bounded
  ≤ 5 s (IPC `stop` → SIGTERM at 2 s → SIGKILL at 5 s). Per-runner
  reader thread pumps `iteration_done` / `permission_request` / `log` /
  `notify` IPC into the F-2 SQLite tables (`agent_runs` + `agent_iterations`)
  and the F-2 event bus (`agent_runner_start` / `agent_iteration_done` /
  `agent_runner_stopped` / `agent_runner_crash`). All DB writes are
  best-effort; supervisor never crashes on persistence failure. POSIX
  only (`enabled()` returns False on Windows).
- `daemon/runner_ipc.py` — thin re-export of
  `kernel.runner.ipc.JsonLineChannel` so both runner families share
  one IPC implementation and one set of bug fixes.
- `daemon/agent_methods.py` — JSON-RPC handlers `agent.start`,
  `agent.stop`, `agent.list`, `agent.status`, registered from
  `DaemonState.__init__` alongside `system_methods` / `monitor_methods`.
  Param validation raises `TypeError` so the dispatcher returns the
  standard `-32602 INVALID_PARAMS` shape.
- `agent_runner.py` — gains the `--pipe` subprocess entry point
  (`_pipe_main` + `_PipeAgentRunner` subclass that swaps
  `send_fn` / `_persist_record` to write IPC instead of in-process
  callbacks). `start_runner` / `stop_runner` / `stop_all` dispatch on
  `agent_runner_subprocess` config key (or `CHEETAHCLAWS_ENABLE_F4=1`
  env var); default off — REPL stays threaded.

**Wire surface (HTTP/1.1 over UDS or TCP).**

| Verb + path | Purpose |
|---|---|
| `POST /rpc` | JSON-RPC 2.0 — methods, batches, notifications.  Requires `Cheetahclaws-Api-Version: 0`. |
| `GET /events?since=<id>` | SSE event stream (heartbeats every 15 s; `gap` event on backlog overflow). |
| `GET /healthz` `/readyz` `/metrics` | Real `health.py` payloads, auth-gated by default; `--unauthenticated-metrics` opts out for trusted scrapers. |

**Auth.** Single-user, single-host threat model — see RFC 0001 §3.
Unix socket relies on file mode `0600` + `SO_PEERCRED`.  TCP requires
`Authorization: Bearer <token>` against `~/.cheetahclaws/daemon_token`
(mode `0600`, generated lazily on first `serve --listen tcp://...`).
Both transports have audit log default-on; per-peer brute-force
throttle returns `429` after sustained bad attempts.

**Lifecycle.**
- `cheetahclaws serve [--listen unix://path | tcp://host:port]
  [--unauthenticated-metrics] [--no-audit] [--print-token]`
- `cheetahclaws daemon status` — pid, transport, address, uptime,
  ping check.
- `cheetahclaws daemon stop` — graceful via RPC, OS signal as fallback.
- `cheetahclaws daemon logs [-n N]` — tail
  `~/.cheetahclaws/logs/daemon.log` (the `serve` entrypoint pins
  `log_file` to that path when not overridden in config).
- `cheetahclaws daemon rotate-token` — regenerate token; existing TCP
  clients receive `401` until they re-read the file.

**RPC surface (as of all F-1 through F-9 landings).**  The daemon
exposes the spike's `echo.*` / `permission.*`, plus `system.ping` /
`system.shutdown` / `system.status` (F-1, F-9), `monitor.*` (F-3),
`agent.start` / `agent.stop` / `agent.list` / `agent.status` /
`agent.resume` (F-4 + F-9), `proactive.set` / `proactive.get` /
`proactive.tickle` (F-5), `bridge.start` / `bridge.stop` /
`bridge.list` / `bridge.send` / `bridge.status` (F-6/7/8), and
`session.send` / `session.reply` / `session.list_recent` (F-6 Phase 2).
The F-6/7/8 Phase 2 inbound refactor moves the bridge poll loop into
a slim daemon-driven worker that publishes `session_inbound` on the
event bus instead of calling `session_ctx.run_query`, so the agent
driver (REPL/Web/automation) and the transport (bridges) decouple.

#### Persistence (F-2)

`cheetahclaws serve` now initialises a daemon-owned schema in the
existing ``~/.cheetahclaws/sessions.db`` (shared with `session_store`).
Seven additive tables — the `sessions` table from `session_store` is
left untouched:

- `daemon_events` — append-only event log (replaces F-1's in-memory ring).
  ID is `AUTOINCREMENT` so it stays monotonic across restarts and across
  retention pruning.  Default retention is 24 h / 100 K rows; pruning
  runs opportunistically every 100 publishes.  When `replay_since(N)`
  finds the requested cursor older than `MIN(id)` it yields a synthetic
  `gap` event so SSE clients (Web UI / future bridges) know to resync.
- `agent_runs` / `agent_iterations` — populated by F-4. One row per
  spawned subprocess in `agent_runs` (status: `running` /
  `stopped` / `crashed` / `paused_budget` after F-9), one row per
  iteration in `agent_iterations` (status, duration, tokens, cost,
  ≤400-char summary).
- `jobs` — replaces `~/.cheetahclaws/jobs.json`.  `jobs.py` migrates
  the legacy file once on first call (tracked via
  `schema_meta.jobs_migrated_from_json`).  Migration is **one-way**:
  after the marker is set, edits to the JSON file are no longer read
  by `jobs.py`.  The file is left on disk for backward viewing only
  (e.g. users still on the prior release, or backup-style tooling);
  SQLite is the source of truth from then on.
- `monitor_subscriptions` / `monitor_reports` — placeholder for F-3.
- `bridges` — populated by F-6/7/8. One row per bridge kind with
  `enabled`, `config_json` (secrets redacted), `last_poll_at`,
  `last_error`. `bridge.list` merges live workers with persisted rows
  so an operator sees disabled bridges from earlier daemon runs.
- `schema_meta` — schema version + per-feature migration markers.

`daemon/schema.py:init_schema()` is idempotent (CREATE IF NOT
EXISTS only) and serialised by an internal lock, so concurrent serve
attempts can't trip on each other.  Schema version is recorded as
`schema_meta.schema_version`; future bumps go through
`_apply_migrations()` which is currently a no-op for v1.

The headline F-2 user-visible win: an SSE client that disconnects,
the daemon restarts, and the client reconnects with `?since=<id>` —
events published while the client was away (and still inside the
retention window) are replayed from SQLite, so observers don't lose
their event timeline across daemon restarts.

#### Monitor in daemon (F-3)

`monitor/scheduler.py` is now daemon-owned.  When `cheetahclaws serve`
starts, it kicks the scheduler loop **after the listener has bound and
the discovery file is on disk** — so a misconfigured fetch/summarize
chain cannot fail before external clients can see the daemon.
Subscriptions and generated reports live in the SQLite
`monitor_subscriptions` and `monitor_reports` tables (migrated once
from `~/.cheetahclaws/monitor_subscriptions.json` on first daemon run,
tracked via `schema_meta.monitor_migrated_from_json`).  Migration is
**one-way**: edits to the JSON file are not picked up after the
marker is set; SQLite is the source of truth.  The JSON file is left
on disk for backward viewing only.

Behaviour:

- **REPL detects daemon → skips local scheduler.**  When the user types
  `/monitor start` in REPL while a daemon is running,
  `commands/monitor_cmd.py` calls `daemon.discovery.locate()`, sees
  a live daemon, prints "scheduler is owned by the running daemon", and
  no-ops.  Avoids the race of two schedulers fighting over
  `last_run_at` and double-firing subscriptions.  `/monitor stop`
  behaves the same way.
- **`/monitor subscribe` / `unsubscribe` / `list` always work in REPL.**
  These hit SQLite directly through `monitor.store`; the daemon picks
  up the new state on its next 60 s poll.  No RPC round-trip needed.
- **External clients use RPC.**  `daemon/monitor_methods.py`
  registers `monitor.subscribe`, `monitor.unsubscribe`, `monitor.list`,
  `monitor.run` for Web UI / third-party tools that don't share the
  process tree.
- **Reports become events.**  `scheduler.run_one()` persists the full
  report body to `monitor_reports` and publishes a `monitor_report`
  event on the SSE channel (`{topic, report_id, body, sent_to,
  errors}`).  SSE subscribers see digests as they land; the
  `report_id` ties the event back to the row in `monitor_reports` for
  later retrieval.
- **Telegram / Slack / WeChat delivery from daemon is wired via
  F-6/7/8.**  A subscription configured with `--telegram` lands its
  report in `monitor_reports`, emits the SSE `monitor_report` event,
  and (when the matching bridge is running in-daemon under the
  per-kind feature flag) is also pushed to the chat. REPL doesn't
  need to be open for delivery once the bridge worker is live.

The headline F-3 user-visible win: `/monitor subscribe arxiv
--schedule daily --console`, then exit REPL — the daemon scheduler
keeps firing on schedule, reports persist to SQLite, SSE clients see
each digest as it lands, history is `monitor.list_reports("arxiv")`
away when the user reconnects.

#### F-4 follow-ups: permission routing, restart policy, bridge notify

The F-4 skeleton above gives crash isolation. Three follow-ups close
the remaining acceptance gaps (RFC 0002 §F-4 #1/#2/#3):

- **§F-4 #1 — permission routing.** When a runner is started with
  `auto_approve=False`, the supervisor routes the runner's
  `permission_request` IPC frame through
  `daemon/permission.py:PermissionStore`. The originator (the
  `client_id` that called `agent.start`) is the only client that can
  answer via `permission.answer`. Timeouts and denials feed back over
  IPC as `permission_response`; the runner unblocks within its
  30-minute wait either way.
- **§F-4 #2 — bridge `notify` forwarding.** The reader's `notify` IPC
  branch now calls `daemon/bridge_supervisor.notify(kind, text)` so
  a subprocess runner's iteration summary reaches the originating
  bridge (Telegram / Slack / WeChat). The runner can target a specific
  bridge via `msg["bridge"]` or omit it for a `"*"` broadcast.
  `agent_runner_notify` events on the bus carry `{name, run_id,
  bridge, delivered, text[:500]}` so observers can audit deliveries.
- **§F-4 #3 — restart policy.** `agent.start` accepts
  `restart_policy="on-crash"`, `max_restarts`, `backoff_base_s`,
  `backoff_cap_s`, `backoff_jitter_s`. A crashed lineage's reader
  `finally` consults `RestartPolicy.next_delay(restart_count)`, arms a
  `threading.Timer`, and respawns with `_restart_count_carry=N+1`.
  `stop()` cancels any pending Timer before the kill ladder, and
  `_unregister(name, expected=handle)` does an identity check so a
  successor handle spawned mid-stop isn't silently popped.  Events on
  the bus: `agent_runner_restart_scheduled`, `agent_runner_restart`,
  `agent_runner_restart_failed`, `agent_runner_restart_exhausted`.

#### Proactive watcher in daemon (F-5)

`_proactive_watcher_loop` from `cheetahclaws/cli.py` is now daemon-owned.
`daemon/proactive_state.py` persists `proactive.enabled` /
`proactive.interval_s` / `proactive.last_tick_at` in the F-2
`schema_meta` table (so the setting survives daemon restarts); a
single background thread (`proactive-scheduler`) ticks at 1 s,
publishes `proactive_tick` on the SSE bus when the idle threshold is
crossed, and resets `last_tick_at`.  REPL `/proactive` slash command
routes through `proactive.set` / `proactive.get` / `proactive.tickle`
RPCs when a daemon is detected; otherwise the legacy in-process
watcher runs.  Step-aside check at every loop tick prevents
double-firing across REPL + daemon.

#### Bridges in daemon (F-6 / F-7 / F-8)

`daemon/bridge_supervisor.py` owns the lifecycle of one or more
daemon-side bridge threads, gated per-kind by feature flags so REPL
behaviour is byte-for-byte unchanged until the user opts in:

| Env var                          | Effect                          |
|----------------------------------|---------------------------------|
| `CHEETAHCLAWS_ENABLE_F6`         | Telegram-in-daemon allowed.     |
| `CHEETAHCLAWS_ENABLE_F7`         | Slack-in-daemon (requires F-6). |
| `CHEETAHCLAWS_ENABLE_F8`         | WeChat-in-daemon (requires F-6).|

Two modes per bridge:

- **Phase 1 (legacy supervisor in daemon).** `bridge.start kind=…
  daemon_phase2=False`. The daemon thread invokes
  `bridges/<kind>.py:_<kind>_supervisor` unchanged, so today's REPL
  network code is re-used verbatim. F-4 #2 needs this — outbound
  `notify` from a subprocess runner lands in the bridge's send path
  (`_tg_send` / `_slack_send` / `_wx_send`).
- **Phase 2 (daemon-driven inbound).** `bridge.start kind=…
  daemon_phase2=True`. The legacy supervisor is bypassed; the worker
  runs a slim loop that (a) subscribes to the daemon event bus and
  filters `session_outbound` events by `session_id` /
  `target_bridges`, (b) re-uses the per-kind HTTP poll helpers from
  `bridges/<kind>.py` and publishes `session_inbound` for every new
  phone message instead of calling `session_ctx.run_query`.

Wire-level RPCs: `bridge.start`, `bridge.stop`, `bridge.list`,
`bridge.send`, `bridge.status` (in `daemon/bridge_methods.py`).
Persisted state lives in the F-2 `bridges` table (`kind`, `enabled`,
`config_json`, `last_poll_at`, `last_error`); secrets are redacted
to last 4 chars before any row write or bus publish (broad pattern:
`token`, `secret`, `api_key`, `password`, `auth`).

`session_id` formatting per kind: `tg:<chat_id>`,
`sl:<channel>`, `wc:<user_id>`. Permission requests born inside a
bridge-driven turn can use this as the PermissionStore originator
(RFC 0001 §2), pinning answers back to the originating bridge.

#### Session message-passing primitives (F-6 Phase 2 support)

`daemon/session_methods.py` registers three methods that any
inbound / outbound source can talk:

- **`session.send(session_id, text, origin?, message_id?)`** —
  publishes `session_inbound` on the bus. Defaults `origin` to the
  RPC caller's `client_id`. Records `(session_id, origin)` in an
  in-memory LRU (last 256, newest-first).
- **`session.reply(session_id, text, target_bridges?, message_id?)`** —
  publishes `session_outbound`. `target_bridges=None` is a broadcast;
  a list of kinds restricts delivery. Phase 2 bridge workers filter
  on `(session_id == handle.session_id())` *and*
  `(target_bridges is None or kind in target_bridges)`.
- **`session.list_recent(limit=20)`** — newest-first snapshot of the
  LRU.

These are I/O-free message-passing primitives — no agent loop is
driven by them. A REPL / Web / future automation client subscribes
to `session_inbound`, runs the agent, calls `session.reply` for each
outbound chunk; that gives a clean separation between transport
(bridges) and intelligence (agent driver).

#### Cost guardrails + quota-pause (F-9)

Headless `cheetahclaws serve` runs unattended for hours; an unbounded
agent can quietly compound costs while no one is watching. F-9 flips
the four budget keys to conservative defaults under `serve` mode:

```jsonc
{
  "session_token_budget": 200000,
  "session_cost_budget":   2.0,
  "daily_token_budget":   2000000,
  "daily_cost_budget":     20.0
}
```

REPL (`--in-process`) keeps `None` (unlimited) for back-compat; F-9
only fires in `cmd_serve`'s startup via `_apply_serve_defaults`.

Three RPC surfaces around it:

- **`system.status`** — returns `{budgets: {…four keys…}, runners,
  bridges}`. `cheetahclaws daemon status` prints this so operators
  can confirm the defaults are in effect.
- **`agent.resume(budget_overrides, name?)`** — merges
  `budget_overrides` into `daemon_state.config`; when `name` is
  supplied, also sends a `resume` IPC frame to the named runner so a
  `paused_budget` runner unblocks. Returns `{budgets, resumed}` so
  the caller can confirm both halves landed.

Per-runner quota-pause hook:

| Stage | Where | Behaviour |
|-------|-------|-----------|
| Pre-iter check | `AgentRunner._run_loop` (top of each iter) | `quota.check_quota` against `_config`; raises `QuotaExceeded` → `_on_quota_exceeded(qe)`. |
| Base impl | `AgentRunner._on_quota_exceeded` | No-op — REPL path keeps today's behaviour (agent.run catches internally, yields `[Quota exceeded …]` text). |
| F-4 override | `_PipeAgentRunner._on_quota_exceeded` | Sends `paused_budget` IPC, sets `status='paused_budget'`, blocks on `_resume_event.wait()`. Wakes from `resume` IPC, sends `resumed` IPC, returns. |
| Supervisor inbound | `daemon/runner_supervisor:_reader_loop` | New `paused_budget` / `resumed` branches: flip `agent_runs.status` in SQLite, publish `quota_warn` / `agent_runner_resumed` on the bus. |
| Supervisor outbound | `runner_supervisor.resume(name)` | Sends `resume` IPC to the named runner; called by `agent.resume(name=…)`. |
| Control loop | `agent_runner._pipe_main:_control_loop` | New `resume` handler sets `_resume_event`. `stop` handler also sets it so a stop arriving while paused unblocks cleanly. |

### Agent OS kernel (`kernel/`)

Layer above the daemon and below the user-facing CLI/REPL/bridges.
Turns cheetahclaws into a true single-node agent operating system:
process table, capability model, quota ledger, scheduler, mailbox/
registry, virtual filesystem, observability, and a frozen 58-method
JSON-RPC contract — backed by a single SQLite WAL-mode database
(`kernel.db`).

Activated at runtime by `cheetahclaws serve --enable-kernel`.
Without that flag the kernel code is dormant and the legacy
single-process REPL/bridge path is byte-for-byte unchanged. Full
overview at [`docs/agent-os.md`](agent-os.md).

**Module map.**

- `kernel/api.py` — `Kernel` facade. `Kernel.open(...)` opens a
  WAL-mode SQLite store and exposes the `cap` / `ledger` / `sched` /
  `mbox` / `registry` / `fs` / `events` substores. `make_supervisor()`
  constructs a `Supervisor` ready to spawn subprocess agents.
- `kernel/store.py` + `kernel/schema.py` — single-connection
  store with forward-only migrations (v1 → v7); a `write_lock`
  serializes mutations across substores.
- `kernel/capability.py` (RFC 0005) — `tool_grants` / `fs_grants`
  / `net_grants` / `model_grants` / `sub_agent` capability bag with
  `derive(...)` for sub-agent attenuation.
- `kernel/ledger.py` (RFC 0006) — per-agent ResourceLedger with
  atomic `charge` + `first_breach` signal so the scheduler can
  shed load without polling.
- `kernel/scheduler.py` (RFC 0007) — priority queue +
  admission filter (consults ledger before claim).
- `kernel/mailbox.py` (RFC 0009) — direct + topic pub/sub
  with at-least-once delivery semantics.
- `kernel/registry.py` (RFC 0010) — name → pid lookup for
  service discovery.
- `kernel/agent_fs.py` (RFC 0011) — VFS unifying memory /
  checkpoint / skill / task storage.
- `kernel/sandbox.py` (RFC 0008) — RLIMIT (CPU/AS/FSIZE/
  NOFILE) preexec_fn + optional bubblewrap wrapper +
  wall-clock killer thread + `new_session` (own process group).
- `kernel/contract.py` (RFC 0013) — frozen v1.0 method
  registry; CI drift guard fails the build if a registered
  RPC method isn't classified `stable`/`experimental`/
  `deprecated`.
- `kernel/cli.py` — `cheetahclaws kernel <action>` subcommand
  for read-only inspection over the daemon's RPC: `summary`,
  `info`, `agents`, `proc <pid>`, `events`, `queue`, `registry`,
  `methods`, `prometheus`.
- `kernel/runner/supervisor.py` (RFC 0016/0017) — spawns
  subprocess agents with a JSON-line IPC channel
  (`runner/ipc.py`); processes `init` / `ready` / `tool_call`
  / `chunk` / `iteration_done` / `exit` messages; integrates
  the streaming-chunk substrate (RFC 0026) so callers can
  subscribe to incremental output via `wait(pid,
  on_chunk=...)`.
- `kernel/runner/llm/` (RFC 0019/0020/0022/0027) — LLM
  agent runner. Provider protocol (callable returning
  `LlmResponse` + optional `stream(req, on_delta)`); Anthropic
  + scripted-mock adapters; multi-iteration tool-calling loop
  with per-iter chunk emission; multi-turn dialogue
  orchestrator.
- `kernel/runner/bridge_mirror/` (RFC 0018) — mirrors
  bridges' inbound/outbound messages into `kernel.mbox` and
  back without touching `bridges/` source files (BC
  constraint).
- `kernel/tools/` — tool registry + dispatch + handlers.
  Auto-registered: `Echo`, `Read`, `Write`, `Glob`, `List`,
  `Diff`, `AST`. Opt-in (operator must call
  `register_<tool>`): `Exec`, `Fetch`, `Git` — each with its
  own threat model documented in the relevant RFC.

**Streaming.** Three layers feed a single `on_chunk(payload)`
sink:

- **LLM** (RFC 0027): provider's `stream(req, on_delta)` emits
  per-token text deltas → runner forwards via `op="chunk"`.
- **Exec** (RFC 0028): Popen + queue-serialized reader threads
  emit per-line stdout/stderr through `ToolContext.on_chunk`.
- **Fetch** (RFC 0029): terminal-hop body chunks per 8 KB
  read.

`Supervisor.wait(...)` accumulates all chunks in
`RunnerExitInfo.chunks` and forwards to the user's callback in
arrival order; bad callbacks are caught at the boundary so they
can't break the wait loop.

**Backwards compatibility.** All surface in `kernel/` is
isolated; the only edits outside the package are one-line opt-in
hooks in `cheetahclaws/cli.py` (the `cheetahclaws kernel ...`
subcommand dispatcher). Schema is forward-only — old `kernel.db`
files upgrade in place. The 58-method contract is frozen at
v1.0 with CI drift guard.

**Where to next.** Two RFCs remain explicitly parked: **RFC 0014
multi-tenant** (only worth doing if cheetahclaws is deployed as
team SaaS) and **RFC 0015 cluster** (only worth doing once a
single host saturates). Higher-ROI follow-ups: tag a v1.x release
+ CHANGELOG, integration performance tests under real LLM
workload, operator documentation for `--enable-kernel` deployment.

### Research Lab (`research/lab/` + `commands/lab_cmd.py` + `web/lab_*`)

Autonomous multi-agent research engine — `/lab start <topic>` (CLI)
or `POST /api/lab/runs` (web) drives 9 specialised agents through 9
stages until an arXiv-grade Markdown preprint lands at
`~/.cheetahclaws/research_papers/<run_id>/report.md`.

Full user-facing guide:
[`docs/guides/research-lab.md`](guides/research-lab.md).

**Module map.**

- `research/lab/orchestrator.py` — 9-stage state machine
  (QUESTIONING → SURVEY → OUTLINE → IMPLEMENTATION → EXPERIMENT →
  ANALYSIS → DRAFTING → VERIFICATION → FINALIZATION).  Each stage
  invokes its producer agent, optional reviewer-author iteration
  (default 2/3 reviewers passing advances; max 5 rounds force-decision
  to avoid infinite loops), and budget tracking.  Cancellation is
  cooperative via a per-run `cancel_check` callable.
- `research/lab/storage.py` — SQLite at
  `~/.cheetahclaws/research_lab.db` (separate file from the daemon's
  `sessions.db` so neither interferes with the other).  Five additive
  tables: `lab_runs`, `lab_stages`, `lab_messages`, `lab_artifacts`,
  `lab_budget`, `lab_experiments`.
- `research/lab/sandbox.py` — `subprocess.run` + `RLIMIT_CPU` +
  `RLIMIT_AS` + workspace `cwd` for executing the Engineer's Python
  scripts.  v0-grade isolation (good enough against an honest LLM
  producing a heavy script; **not** a hostile-code boundary —
  Docker is Phase 2.5).  Captures stdout/stderr, collects PNG/CSV/
  JSON artifacts, and persists them under
  `~/.cheetahclaws/research_papers/<run_id>/workspace/`.
- `research/lab/verifier.py` — citation existence check against
  three free APIs in priority order (arXiv → Semantic Scholar →
  CrossRef).  Jaccard title similarity ≥ 0.55 + surname-overlap
  ≥ 0.5 to count as `verified`; `not_found` is a fabrication signal.
  Distinguishes `verification_skipped` (network failed) from
  `not_found` (network worked but nothing matched) so we don't
  wrongly accuse offline users' citations of being fabricated.
- `research/lab/roles.py` — 9-role assignment with cross-family
  model selection.  Default reviewer pool draws from three different
  provider families (Claude / GPT / Gemini, etc.) when API keys are
  available, to reduce same-source rubber-stamping in the
  reviewer-author debate.  Falls back to the user's primary model
  when fewer keys are configured.
- `research/lab/convergence.py` — reviewer quorum rule + budget
  status calculator.  Decision branches: pass (advance), iterate,
  redesign (after N rounds with 0/3 passing), force-advance (max
  rounds), budget-exhausted (skip to FINALIZATION).
- `research/lab/output.py` — Markdown report assembly +
  BibTeX bundle + experiment-log appendix from artifacts in storage.
- `agent_templates/lab/*.md` — the 9 role prompts (PI, Questioner,
  Surveyor, Designer, Engineer, Analyst, Writer, Reviewer, Lay
  Reader).  Engineer's prompt pins a `RESULT: {...}` JSON output
  protocol so the Analyst can parse numerical findings without
  fabrication.
- `commands/lab_cmd.py` — `/lab {start, status, abort, logs, resume}`.
- `web/lab_api.py` — JSON dispatcher under `/api/lab/*`; reuses the
  existing stdlib HTTP server.
- `web/lab.html` — single-page vanilla-JS UI; auto-polls every 5 s
  while a run is open; renders the final report client-side.

**Why this lives in `research/lab/`** rather than a top-level
package: the existing `research/` package already houses the
`/research` literature pipeline + 20-source aggregator that the
Surveyor leans on indirectly.  Putting the lab next to it keeps the
research-toolchain code co-located.

**Key invariants.**

- The Analyst-to-Writer pipe means Writer is **told** to use the
  pre-drafted Results section verbatim, materially reducing the
  surface where the LLM could fabricate experimental numbers.
- Per-run state is **always** in SQLite before stage transitions, so
  a crash mid-stage is recoverable in principle (resume support is
  Phase 2.5).
- The verifier **never** marks `not_found` when network failure
  prevented the lookup — the `verification_skipped` state is
  intentional to avoid false fabrication accusations.
- Convergence rule **always** advances after `max_rounds` regardless
  of reviewer score — a model that loves to nitpick cannot block
  progress.

**v0 scope, intentionally not yet covered.**

- Multi-tenant user isolation (Phase 4).
- Docker-isolated experiment execution (Phase 2.5).
- LaTeX / PDF rendering (Phase 2.5).
- GPU pool / Modal-style compute backend (Phase 4).
- `/lab resume <run_id>` — placeholder; orchestrator state is in
  SQLite but the worker thread doesn't auto-resume after process
  restart.
- Real-time SSE event streaming — frontend polls every 5 s instead.
- Reference-manager export beyond raw BibTeX (Zotero / Mendeley
  integration is Phase 3).
- Plagiarism / novelty scoring (Phase 3).

---

## Key architectural invariants

These are the implicit rules the codebase holds itself to.  Breaking
them is always a bug.

### 1. `config` dict vs `RuntimeContext`

`config` is a **serializable** dict loaded from
`~/.cheetahclaws/config.json`.  It holds user settings (model,
permission mode, API keys, budgets, log level).  `save_config()`
strips any key starting with `_` before writing.

`RuntimeContext` ([runtime.py](../cheetahclaws/runtime.py)) is **per-session live
state** — threads, callbacks, bridge flags, plan-mode pointer,
pending image, streaming hooks.  Keyed by `_session_id`, never
persisted.

```python
# CORRECT
import runtime
sctx = runtime.get_ctx(config)
sctx.plan_file = path

# WRONG (this used to exist and was refactored out)
config["_plan_file"] = path
```

The **only** `_`-prefixed key allowed in `config` is `_session_id` —
the bridge between a config dict and its runtime context.  Transient
per-turn keys (`_depth`, `_system_prompt`, `_worktree_cwd`) are
injected by `agent.run()` into a local copy of config at call time
and never persisted.

### 2. Tool registration is the single extension point

Everything the model can call ends up in
`tool_registry._registry`.  This is how plugins, MCP servers, skills,
feature packages, and the modular ecosystem all compose without
knowing about each other.

### 3. Neutral message format

Every subsystem that handles conversation messages speaks the same
format (see Provider abstraction above).  Providers adapt at the
boundary, not in the middle of the pipeline.

### 4. Bootstrap order

`bootstrap.py` is the **one and only** place where startup side
effects happen in a defined order: logging → tool registry → health
server.  Don't add import-time side effects to top-level modules.
New feature tools register via `_EXTENSION_MODULES` or the modular
ecosystem, never by putting `register_tool()` in some module's
top-level code that happens to get imported.

### 5. Windows file-encoding discipline

`tools/fs.py::_read` / `_write` / `_edit` force `encoding="utf-8"`
and `newline=""`.  `_edit` additionally detects pure-CRLF files
(every `\n` belongs to a `\r\n`) and restores the original line
endings after the edit; mixed-ending files are left alone to avoid
corruption.  Any new file-writing tool must mirror this.

---

## Data flow: end-to-end example

User types `Read config.py and change session_daily_limit to 20`
with Claude as the active model.

```
 1. cheetahclaws/cli.py            reads line via ui.input
 2. repl()                     dispatches to agent.run()
 3. agent.run()                appends user message; config["_depth"]=0
 4. maybe_compact()            messages well under 70% limit — no-op
 5. quota.check_quota()        no budget set — pass
 6. providers.stream()         detects "claude-*" → stream_anthropic()
 7. context already built      system prompt = default.md + claude overlay + env
 8. Model responds:            "I'll read it first."
                              + tool_call[Read(file_path=".../config.py")]
 9. agent._check_permission    Read is read_only → auto-approve
10. tool_registry.execute_tool Read via tools.fs._read → file content
11. checkpoint hook: no-op     (Read doesn't mutate, no snapshot)
12. agent yields ToolEnd;      appends tool message to state
13. Loop back to providers.stream()
14. Model responds:            "Changing 10 → 20"
                              + tool_call[Edit(file_path=..., old="10", new="20")]
15. agent._check_permission    Edit is not read_only, permission_mode=auto
                              → PermissionRequest yielded
16. cheetahclaws/cli.py renders    prompt [y/N/a]; user types y → req.granted=True
17. checkpoint hook fires      captures pre-edit file copy in snapshot dir
18. tool_registry.execute_tool Edit runs, returns unified diff
19. ui.render                  shows the diff in red/green
20. Model responds:            "Done."   (no tool_calls)
21. agent.run() breaks loop;   TurnDone yielded; REPL prints final text
22. post-turn                  checkpoint.snapshot_session()
                              session_store.save_latest()
```

---

## Testing

```bash
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q
```

`[tool.pytest.ini_options]` sets `python_files = ["test_*.py",
"e2e_*.py"]` — end-to-end tests are collected by default.  E2E tests
may spawn subprocesses or touch the network; keep them
self-contained.

Test layout:

- `test_<subsystem>.py` — unit tests for one package/module
  (compaction, memory, subagent, mcp, plugin, task, skill, tool
  registry, …).
- `e2e_<scenario>.py` — integration tests (plan mode, compact, slash
  commands, plan tools).
- `tests/fixtures/` — golden prompt fixtures etc.

Most tests use `monkeypatch` + `tmp_path` to avoid global state.
Sub-agent tests mock `_agent_run` to avoid real API calls.  CI
(`.github/workflows/ci.yml`) runs the suite on Python 3.10–3.13.

---

## Known gotchas

A collection of non-obvious traps; most bit someone at some point.

- **`cc_` prefix dropped**: modules once carried a `cc_` prefix
  (`cc_config.py`, `cc_daemon/`, `cc_kernel/`, `cc_mcp/`); the prefix
  was removed for readability.  Three of the four reverted to plain
  names (`config`, `daemon`, `kernel`).  The MCP client could **not**
  revert to bare `mcp` — that shadows Python's namespace and the
  `modelcontextprotocol` package — so it is `mcp_client/`.  Always
  `import config` / `from mcp_client import ...`, never `import mcp`.
- **`.nano_claude/plans/` vs `~/.cheetahclaws/`**: runtime state is
  under `~/.cheetahclaws/` (underscore), but plan mode writes to
  `.nano_claude/plans/<session>.md` in cwd.  The `.nano_claude` path
  is historical (pre-rename) and intentional; don't "fix" it without
  updating plan-mode code.
- **py-modules discipline**: top-level `.py` files must be listed in
  `pyproject.toml` `py-modules`, and packages in `packages`.  `pip
  install .` silently drops anything not listed.  Backward-compat
  shims (`memory.py`, `skills.py`, `subagent.py`) **are** listed — do
  not delete them from `py-modules` without also deleting the shim.
- **pytest picks up `e2e_*.py`**: some e2e tests depend on Unix-only
  modules (`pty`, `termios`).  On Windows these collection errors are
  pre-existing; skip them with `--ignore` until the project grows
  Windows-compatible substitutes.
- **Circuit breaker + quota**: every stream call is wrapped.  If you
  see `[Quota exceeded]` or `[Circuit open]` in output, that's the
  layer doing its job.  Don't bypass it; reset via `/circuit` or
  check `config` budgets.
- **Ollama 500 on non-tool-calling models**: some Ollama models
  return HTTP 500 when `tools` are sent in the request.  Adapter
  retries once without tools.  Tests in `tests/test_providers*` cover
  the regression path.
- **Gemini 3 `thought_signature`**: Gemini requires an opaque
  signature echoed in every tool_call response.  It rides in
  `extra_content` on tool_call dicts.  Any code path that reconstructs
  tool calls (compaction, replay) must preserve it.
- **Plugin tools registration**: plugin code declaring `TOOL_DEFS`
  gets loaded through `plugin/loader.py::register_plugin_tools`.
  Never call `register_tool()` directly in plugin code; the loader
  handles resolution order and scoping.
- **Prompt files: don't recreate per-family base files**.  An earlier
  iteration shipped `prompts/base/{anthropic,openai,gemini,kimi,deepseek}.md`
  and routed by family.  That design duplicated content and silently
  denied general guidance to families without a dedicated file.  We
  collapsed back to a single `default.md` plus tiny `overlays/<family>.md`
  for vendor-documented quirks only.  Two regression tests
  (`test_dead_family_base_files_are_gone`, `test_overlay_cites_source`)
  prevent silent drift back to the old shape.  See
  [`prompts/README.md`](../cheetahclaws/prompts/README.md) for the admission policy.

---

## Related docs

- [CONTRIBUTING.md](../CONTRIBUTING.md) — quick start, "where to add
  things", PR checklist.  Practical, short, kept current.
- [README.md](../README.md) — user-facing surface (CLI flags, slash
  commands, provider setup, memory / plugin / skill walkthroughs).
- [docs/contributor_guide.md](contributor_guide.md) — older "where to
  edit what" reference.  Partially overlapping with CONTRIBUTING.md;
  may be folded in over time.
- [docs/guides/extensions.md](guides/extensions.md) — user-level
  docs for memory / skills / sub-agents / MCP / plugins.
- [docs/guides/plugin-authoring.md](guides/plugin-authoring.md) —
  full plugin manifest + tool / command contract.
