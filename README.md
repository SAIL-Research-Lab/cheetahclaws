English | [中文](docs/i18n/README.CN.MD) | [한국어](docs/i18n/README.KO.MD) | [日本語](docs/i18n/README.JP.MD) | [Français](docs/i18n/README.FR.MD) | [Deutsch](docs/i18n/README.DE.MD) | [Español](docs/i18n/README.ES.MD) | [Português](docs/i18n/README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: A Fast and Easy-to-Use Agent Harness Infrastructure for Long-Horizon, Multi-Model, and Tool-Using AI Systems</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">Website</a>
    ·
    <a href="https://arxiv.org/pdf/2605.26112">Scaling the Harness</a>
    ·
    <a href="https://github.com/SafeRL-Lab/cheetahclaws/issues">Issue</a>
    ·
    <a href="https://pypi.org/project/cheetahclaws/">
      <img src="https://img.shields.io/badge/downloads-16.6K-blue" alt="Downloads 16.6K" align="absmiddle">
    </a>
  </p>
</div>


### Quick Install

```bash
pip install cheetahclaws
```

Then just run (e.g., using deepseek-v4-flash model):

```bash
cheetahclaws        # start chatting!
```

Other install methods: [one-line install script](#alternative-one-line-install-script) | [install from source](#alternative-install-with-pip-from-source-code) | [uv install](#alternative-install-with-uv) | [run from source install](#alternative-run-directly-from-source-no-install) | [full install details](#installation) | [docker install](https://hub.docker.com/r/chauncygu/cheetahclaws)

> 🖥️ **Prefer a native app?** A desktop build (Electron) wraps the full chat UI in a window — no terminal needed. See [`desktop/`](desktop/README.md).

## 🔥🔥🔥 News (Pacific Time)

- September 20, 2026 (**v3.5.88**): **Autonomous by default, `/resume` by name, and transcripts you can read.** **(1)** A request now becomes a *result*: `auto_approve` ships as `True`, so a turn that needs six commands runs them instead of stopping six times at an approval menu. `/auto off` turns the prompts back on and is saved; `--ask` does it for one run. The Bash hard denylist, the filesystem sandbox and the `manual`/`plan` modes still override autonomy, and the banner calls out the non-default state. At a prompt, **`!`** now saves a grant for one command/file permanently and **`auto`** switches to autonomous mode. **(2)** `save_config` used to persist every key including the defaults, which froze them into `config.json` and meant a default changed in a later release could never reach an existing user; it now writes only what differs, with a one-time migration that cleans up what is already on disk. **(3)** **`/resume` lists sessions by name** — each row is the session's opening request plus date, turn count, model and id, newest first with the live session pinned on top — and resuming **repaints the conversation** rather than printing a file path. `/resume last|<id>|<path>` skip the picker. **(4)** Sessions are saved as **UTF-8, not `\uXXXX`**, so a Chinese message is stored as Chinese — readable and greppable. **(5)** A Markdown `---` in the model's answer is no longer painted as a full-width rule mid-turn (`markdown_rules=true` restores it), with setext headings, table rows, lists and fenced code left alone. [Details](docs/news.md)
- August 16, 2026 (**v3.5.87**): **Permission prompts are now reserved for what actually needs a decision.** `auto` mode asks only when an action can change your files, run arbitrary code, or reach outside the session. Auto-approved now: **every** registry-marked read-only tool (18 more than before — diagnostics, task/memory queries, document readers), read-only shell **pipelines** (`git log | head -20`, `ls -la | grep test` — the old check rejected every `|`), session-state tools (tasks/memories/skills), and creating a **new** file inside the workspace. Still asks: overwrites, writes outside the workspace, `.git/hooks` and `.github/workflows` paths, interpreters and test/build runners, anything that deletes or uploads, and sub-agent spawns. The prompt also gained **`s`** — approve and stop asking for *that one command or file* for the session, a scoped alternative to `accept-all` (`/permissions clear` drops grants). The shell check is now a real parser instead of a prefix match, which along the way closed a hole where anything starting with `python `/`node `/`find ` auto-ran. [Details](docs/news.md)
- August 16, 2026: **OpenRouter is now a first-class provider — one key, 400+ models, with the secondary provider pinnable per call (PR #179).** `/model openrouter/<vendor>/<model>` (e.g. `openrouter/deepseek/deepseek-v4-flash`) routes through [OpenRouter](https://openrouter.ai); the key comes from `OPENROUTER_API_KEY` or `/config openrouter_api_key=sk-or-...`, and the model shows up in the `/model` Tab picker and the Web UI picker automatically. Append `@<provider>[/<quantization>]` — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — to pin which upstream serves the request; it is sent as OpenRouter's `provider` request-body object, so the model field stays a real catalog ID. Shipped alongside four routing fixes that gateway model IDs exposed: the provider is no longer re-derived from an already-stripped model string (which read `openrouter/deepseek/…` as the *DeepSeek* API and leaked DeepSeek-only request fields), cost estimates and context windows now resolve per model instead of defaulting to $0.00 and a flat 128k, and the `@…` routing suffix no longer strips a model of its prompt-family overlay. [Details](docs/news.md)
- July 30, 2026 (**v3.5.86**): **Next-prompt ghost text — the REPL predicts the line you'd type next.** After each reply the **auxiliary** (cheap/fast) model drafts your most likely next message and shows it dim at the prompt; **Tab** (or **→**) accepts it in full, typing just types over it, and Enter alone never submits it. Drafting runs on a background thread so the prompt never waits, stays silent on any failure (no key / no model → simply no ghost), and is one-shot per prompt so a stale prediction is never shown. Off with `/config input_suggest=false` or `CHEETAH_SUGGEST=0`. Also in this release: the **terminal tab title now configures itself over Remote-SSH / WSL / devcontainers** — it used to write a settings file on the server that the editor never reads, and never retry; it now targets the remote Machine settings the window actually reads. First tagged release carrying the July 11 tab-title / prompt-cache and July 20 `tool_profile` / bounded-I/O changes. [Details](docs/news.md)
- July 20, 2026: **Bounded-I/O fixes and a configurable tool surface.** `tool_profile` selects how many tool schemas are sent each turn — `full` (default, nothing hidden) / `standard` (compact coding) / `research` / `orchestration` — to cut prompt tokens on small-context models, switchable with `/config tool_profile=standard`. Also fixes two bounded-I/O regressions: `SummarizeLargeFile` no longer "summarizes" its own chunk-failure markers (clean `Error` when map/reduce fails), and the DuckDuckGo parser no longer crashes on a valueless `class` attribute. [Details](docs/news.md)
- July 11, 2026: **Terminal tab title tracks the live task, plus a cross-turn fix for the Anthropic prompt cache.** [Details](docs/news.md)
- July 10, 2026 (**v3.5.85**): **REPL quality-of-life.** Live typing-time completion now works on *every* install — `prompt_toolkit` is a **core dependency** (no `[autosuggest]` extra needed, so `pip install` / `uv tool install` both get it out of the box); **`/model` gained a Tab-completion picker** (provider/model + a two-level LiteLLM tree, PR #166); and sessions now **autosave every turn** (atomic write + `fsync`) so a crash or power-loss mid-conversation stays recoverable via `/resume` — the loud daily/history save still happens once on exit. [Details](docs/news.md)
- July 9, 2026: **Official Docker image + one-command publish.** Pre-built image on Docker Hub (`docker pull chauncygu/cheetahclaws`) so you can run the Web UI without cloning; fixes a first-run `PermissionError` by pre-creating the `.cheetahclaws`/`workspace` dirs owned by the non-root user, makes the compose `image` overridable via `CHEETAH_IMAGE`, and adds `scripts/docker-publish.sh` (auto-reads the version, multi/single-arch). New docs sections: **Pull from Docker Hub** and **Interactive setup / CLI mode**. [Details](docs/news.md)
- July 8, 2026: New **`/workspace`** command manages isolated working directories under `~/.cheetahclaws/workspaces` (`list`/`switch`/`default`/`create`/`delete`) (PR #162); startup auto-switching is **opt-in** via `workspace_auto` (off by default, so launching in a project directory is unchanged), and `default` is now a sticky key separate from last-used. [Details](docs/news.md)
- July 6, 2026 (**v3.5.84**): **`/image` now enriches the prompt with local OCR text** so even non-vision models can act on clipboard screenshots (error dumps, code, tables); runs only when `pytesseract`/`tesseract` are installed and is fully opt-out via `CHEETAHCLAWS_IMAGE_OCR=0`. [Details](docs/news.md)



For more news, see [here](docs/news.md).

---

## Sponsor

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **A Fast** and **Easy-to-Use** Python native Agent Harness Infrastructure, **Supporting Any Model**, such as Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax, and local open-source models via Ollama or any OpenAI-compatible endpoint.

---

## Content
  * [Why CheetahClaws](#why-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [Features](#features)
  * [Supported Models](#supported-models)
  * [Installation](#installation)
  * [Usage: Closed-Source API Models](#usage-closed-source-api-models)
  * [Usage: Open-Source Models (Local)](#usage-open-source-models-local)
  * [Model Name Format](#model-name-format)
  * [Trading Agent](#trading-agent)
  * [Web UI](#web-ui)
  * [Documentation](#documentation) (guides for all features)
  * [Contributing](#contributing) · [FAQ](#faq) · [Citation](#citation)


### Demos

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>Task execution in the terminal</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web UI: browser chat — sidebar, tool cards, approval prompts, Markdown streaming</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Autonomous trading agent</i></sub></div>

> More animated demos (code review, `/research`, `/brainstorm`, `/lab`, Telegram/WeChat/Slack bridges) live in [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/).

---

## Why CheetahClaws

Claude Code is a powerful, production-grade AI coding assistant — but its source is a compiled ~12 MB TypeScript/Node bundle (~1,300 files, ~283K lines), tightly coupled to the Anthropic API, hard to modify, and impossible to run against a local or alternative model.

**CheetahClaws** reimplements the same core loop in ~90K lines of readable Python — keeping what you need, dropping what you don't, and adding multi-provider + local-model support. Full comparison: [docs/guides/comparison.md](docs/guides/comparison.md).

| Dimension | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Language | TypeScript + React/Ink | Python 3.8+ |
| Source files / LoC | ~1,332 files / ~283K | ~315 files / ~90K (core; ~127K with tests) |
| Built-in tools / commands | 44+ / 88 | 27 / 50+ |
| Model providers | Anthropic only | 8+ (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| Local models | No | Yes — Ollama, LM Studio, vLLM, any OpenAI-compatible endpoint |
| Build step | Yes (Bun + esbuild) | No — `python cheetahclaws.py` |
| Extensibility | Closed (compile-time) | Open — `register_tool()` at runtime, Markdown skills, git plugins, MCP |
| Voice input | Proprietary WebSocket (OAuth) | Local Whisper / OpenAI — works offline |

**Where Claude Code wins:** richer React/Ink UI, more built-in tools, enterprise features (MDM, team permission sync, OAuth/keychain), AI-driven memory extraction, single-binary production reliability.

**Where CheetahClaws wins:** any-model switching (`--model`/`/model`, no recompile) incl. full local/offline support; a readable agent loop in one file (`agent.py`, ~740 lines); zero build; runtime tool registration + MCP + git plugins + Markdown skills; task dependency graph (`blocks`/`blocked_by`); two-layer context compression; offline voice; cloud session sync; bridges to Telegram/WeChat/Slack/QQ.

**Who it's for:** developers who want a local/non-Anthropic coding assistant, researchers studying how agentic assistants work, and teams who need a hackable baseline — without a Node.js build chain.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) is another popular open-source assistant (TypeScript/Node). The two have **different primary goals** — OpenClaw is a personal life-assistant across messaging channels; CheetahClaws is a developer/coding tool.

| Dimension | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Lines of code | ~245K (~10,349 files) | ~90K core (~315 files) |
| Primary focus | Personal assistant across channels | AI coding assistant / dev tool |
| Architecture | Always-on Gateway daemon + apps | Zero-install terminal REPL |
| Messaging channels | 20+ (WhatsApp · Signal · iMessage · Discord · Matrix · …) | Terminal + Telegram · WeChat · Slack · QQ bridges |
| Local / offline models | Limited | Full — Ollama · vLLM · LM Studio · any OpenAI-compatible |
| Code editing tools | Browser control, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| Mobile / Live Canvas | Yes (menu bar + iOS/Android, A2UI) | — |
| MCP support | — | Yes (stdio/SSE/HTTP) |
| Hackability | 245K lines, harder to modify | ~90K lines — agent loop in one file |

| If you want… | Use |
|---|---|
| A personal assistant on WhatsApp/Signal/Discord, mobile-first, browser automation + Canvas | **OpenClaw** |
| An AI coding assistant in your terminal, full offline/local models, multi-provider switching, source you can read in an afternoon | **CheetahClaws** |

> Full comparison — both sides' wins + key design differences (agent loop, tool registration, context compression, memory): [docs/guides/comparison.md](docs/guides/comparison.md#cheetahclaws-vs-openclaw).

---

## Features

| Feature | Details |
|---|---|
| Multi-provider | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · OpenRouter · Ollama · LM Studio · Custom endpoint |
| Agent loop | Streaming API + automatic tool-use loop; the whole loop is in `agent.py` |
| 28 built-in tools | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(MCP + plugin tools auto-added)* |
| Tool profiles | `tool_profile` trims the tool surface sent each turn to save prompt tokens: `full` (default, everything) · `standard` (compact coding) · `research` (web + documents) · `orchestration` (agents + tasks). Set with `/config tool_profile=standard`. [Guide](docs/guides/usage.md#tool-profiles-tool_profile) |
| MCP integration | Connect any MCP server (stdio/SSE/HTTP); tools auto-registered — see [extensions guide](docs/guides/extensions.md) |
| Plugin system | Install/enable/update plugins from git URLs or local paths; multi-scope; recommendation engine |
| Task management | `TaskCreate/Update/Get/List`, sequential IDs, dependency edges, persisted to `.cheetahclaws/tasks.json` |
| Context compression | Four cooperating layers — dynamic `max_tokens` cap, per-model context-window registry, two-layer snip + AI summarize at 70%, and auto-fanout for oversized tool outputs. [Details](docs/guides/reference.md) |
| Persistent memory | Dual-scope (user + project), 4 types, confidence/source metadata, conflict detection, recency-weighted search, `/memory consolidate`. Verification-anchored staleness — freshness tracks a `last_verified` date (not file mtime), so reading a memory can't fake-refresh it; only `MemoryVerify` resets the clock. [Details](docs/guides/features.md) |
| Multi-agent | Spawn typed sub-agents (coder/reviewer/researcher/…), git-worktree isolation, background mode |
| Permission system | Prompts only for what can change your files, run arbitrary code, or reach outside the session — every read-only tool, read-only shell pipeline (`git log \| head`), and new-file creation in the workspace runs silently. **Autonomous by default** — a request is carried out end to end and you get the result, with no approval stops; `/auto off` (or `--ask` for one run) turns the prompts back on, and at a prompt `s` grants one command/file for the session while `!` saves that grant for good. Modes: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`; a hard denylist blocks host-destroying commands in every mode |
| Checkpoints & plan mode | Auto-snapshot conversation + files each turn (`/checkpoint`, `/rewind`); `/plan` read-only analysis mode |
| Slash commands & themes | 50+ slash commands with Tab-complete; `/theme` offers 15 curated palettes |
| Next-prompt ghost text | After each turn the auxiliary (cheap) model drafts the line you'd most likely type next and shows it dim at the prompt — **Tab** (or **→**) accepts it in full, typing ignores it. Background-drafted, never blocks the REPL, silent on failure. Off via `/config input_suggest=false` or `CHEETAH_SUGGEST=0`. [Details](docs/guides/reference.md#next-prompt-ghost-text) |
| Brainstorm → Worker | `/brainstorm` runs an N-persona debate → `todo_list.txt`; `/worker` auto-implements the pending tasks |
| SSJ Developer Mode | `/ssj` — persistent power menu chaining Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor, etc. |
| Trading agent | `/trading` multi-agent analysis, backtesting, paper-trade calibration, MV portfolios. [Guide](docs/guides/trading.md) |
| Monitor | `/monitor` subscribes to AI-monitored topics on a schedule (arxiv / stock / crypto / news / custom), pushes reports to bridges/console |
| Research (multi-source) | `/research` fans out to **20 sources** with attention heat table, entity extraction, trend sparkline, comparison mode. [Guide](docs/guides/research.md) |
| Autonomous agents | `/agent` background loops from Markdown templates; iteration summaries pushed via bridge; stagnation-stop guard |
| Bridges + remote control | Telegram · WeChat · Slack · QQ — chat round-trip, slash passthrough, per-bridge job queue (`!jobs`/`!retry`/`!cancel`). [Guide](docs/guides/bridges.md) |
| Voice / Vision / Video / TTS | Offline Whisper `/voice`; `/image` clipboard vision (local + cloud); `/video` + `/tts` content factories. [Guide](docs/guides/voice-and-video.md) |
| Web UI | `--web` — multi-user browser chat + PTY terminal. [Guide](docs/guides/web-ui.md) |
| More | Tmux integration · `!cmd` shell escape · proactive monitoring · 3×Ctrl+C force-quit · crash-safe session autosave (every turn, `fsync` + atomic write; `/resume` to recover) · `/cloudsave` GitHub-Gist sync · cost tracking · Anthropic prompt caching (cache-aware cost/quota) · animated terminal tab title showing the live task (auto-configures VS Code; `/terminal-setup`) · `--print` non-interactive mode |

> **Full feature reference** — every row above with complete detail (context-compression layers, auto-fanout, 15 themes, the full Trading/Research/Agents writeups, …): [docs/guides/features.md](docs/guides/features.md).

---

## Supported Models

### Closed-Source (API)

| Provider | Example models | Context | API Key Env |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (free tier) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ models, one key)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | varies | `OPENROUTER_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(via litellm)_ | `litellm/<provider>/<model>` | varies | provider-specific |

> **`openrouter/` gateway:** one key for 400+ models across vendors. The model ID keeps OpenRouter's upstream `<vendor>/<model>` path, so the call is double-prefixed: `openrouter/deepseek/deepseek-v4-flash`. To pin which upstream provider (and quantization) serves the request, append `@<provider>[/<quantization>]` — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — which is sent as OpenRouter's `provider` request-body object rather than glued into the model ID. See [usage.md](docs/guides/usage.md#openrouter-400-models-one-key).

> **`litellm/` adapter:** routes to 100+ providers behind one SDK — mainly for upstreams with awkward auth (Bedrock SigV4, Azure deployment routing, Vertex service-account JWTs). For plain OpenAI-shaped endpoints, prefer the zero-dependency `custom/` adapter. Install with `pip install ".[litellm]"`. See [recipes.md](docs/guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

### Open-Source (Local via Ollama)

| Model | Size | Strengths | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **Best for coding** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | General purpose | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | Reasoning, math | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | Fast / strong MoE | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | Reasoning / open / code | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **Vision** | `ollama pull llava` |

> **Tool calling** needs a function-calling model — recommended: `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Models that emit tool calls as **text** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) instead of Ollama's structured field are auto-recovered, so they execute tools out of the box rather than just chatting about it. Reasoning models (`deepseek-r1`, `qwen3`, `gemma4`) stream native `<think>` blocks; enable with `/verbose` + `/thinking`.

---

## Installation

```bash
pip install cheetahclaws
```

Works on **Linux, macOS, WSL2, and Android (Termux)** (Python 3.10+). First run guides you through provider + API-key setup; re-run anytime with `cheetahclaws --setup`.

> **Windows:** native Windows is not supported — use [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). **Android/Termux:** `pkg install python git && pip install cheetahclaws`.

### Alternative: one-line install script

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

After installation, reload your shell so `cheetahclaws` is on PATH:

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### Alternative: install with `pip` from source code

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### Optional extras

```bash
pip install ".[voice]"      # voice input (sounddevice + faster-whisper)
pip install ".[vision]"     # clipboard image capture (Pillow)
# note: typing-time completion (prompt_toolkit) is now built in — no extra needed.
#       the [autosuggest] extra is kept as a no-op alias for backward compat.
pip install ".[browser]"    # headless browser (playwright); then: playwright install chromium
pip install ".[files]"      # PDF + Excel reading (pymupdf, openpyxl)
pip install ".[ocr]"        # image OCR (pytesseract)
pip install ".[trading]"    # trading agent (yfinance, rank-bm25)
pip install ".[qq]"         # QQ bot bridge (qq-botpy)
pip install ".[litellm]"    # AWS Bedrock / Azure / Vertex auth via litellm
pip install ".[all]"        # everything above
```

### Alternative: install with `uv`

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### Alternative: run directly from source (no install)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## Usage: Closed-Source API Models

Every cloud provider follows the same pattern — export its API key (see the [Supported Models](#closed-source-api) table for the env-var name), then select a model:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

Provider get-key pages: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat) · [OpenRouter](https://openrouter.ai/keys).

**One key for 400+ models** — [OpenRouter](https://openrouter.ai) fronts every major vendor behind one OpenAI-compatible endpoint, so a single key covers Claude, GPT, Gemini, DeepSeek, Llama, Qwen and the rest:

```bash
export OPENROUTER_API_KEY=sk-or-...
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash
cheetahclaws --model openrouter/anthropic/claude-sonnet-4-6
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8   # pin the upstream provider
```

**AWS Bedrock / Azure / Vertex** use the `litellm/<provider>/<model>` form (`pip install ".[litellm]"`) — full env-var recipes in [recipes.md](docs/guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

> **Full per-provider guide** — every provider's get-key page + example model commands, plus Bedrock/Azure/Vertex env-var recipes: [docs/guides/usage.md](docs/guides/usage.md).

---

## Usage: Open-Source Models (Local)

### Ollama (recommended)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

Download [LM Studio](https://lmstudio.ai), grab a GGUF model, start its **Local Server** (port 1234), then:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / self-hosted OpenAI-compatible server

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

The name after `custom/` must match the server's `--served-model-name`. For the Web UI, `--web --model custom/<name>` persists the model before the server starts. Remote server? Point `CUSTOM_BASE_URL` at its IP.

> **Full local-model guide** — Ollama step-by-step, LM Studio, vLLM + Web UI: [docs/guides/usage.md](docs/guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (hosted, OpenAI-compatible)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** serves DeepSeek, Qwen, GLM, Kimi, MiniMax and more behind one OpenAI-compatible endpoint, via the zero-dependency `custom/` adapter:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> Any Atlas chat model id works the same way — **full list of all 59 models:** [docs/guides/usage.md](docs/guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## Model Name Format

Three equivalent forms are accepted:

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**Gateways keep the upstream path.** OpenRouter, NIM and LiteLLM address models by a `<vendor>/<model>` path of their own, so those calls are double-prefixed — only the **first** segment is the provider, everything after it is passed through verbatim:

```bash
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash        # → OpenRouter, model "deepseek/deepseek-v4-flash"
cheetahclaws --model nim/meta/llama-3.3-70b-instruct              # → NVIDIA NIM
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8   # + pinned provider / quantization
```

OpenRouter additionally accepts an `@<provider>[/<quantization>]` suffix (quantizations: `fp4` · `fp8` · `int4` · `int8`). It never reaches the model field — it is split off and sent as OpenRouter's `provider` routing object (`order` + `allow_fallbacks: false`, plus `quantizations` when given), so pinning `@gmicloud` means the request fails rather than silently landing on a different upstream.

**Auto-detection by prefix:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

**Tab-completion (PR #166):** inside the REPL, type `/model ` and press **Tab** for a `provider/model` picker — one default per provider, plus a two-level `litellm/<backend>/<model>` tree you can drill into. Completions appear as you type when `prompt_toolkit` is present (now a core dependency, so always); otherwise readline serves them on Tab.

---

## Trading Agent

A built-in AI trading analysis + backtesting module (`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4 strategies (`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), BM25 memory of past situations, US/HK/A-share + crypto markets with no-API-key data fallbacks. Guided sub-menu via `/ssj` → **Trading**.

> **Full guide:** [docs/guides/trading.md](docs/guides/trading.md)

---

## Web UI

A production-ready browser interface — real user accounts (bcrypt + JWT), SQLite-backed history, ops endpoints — served by Python stdlib + ten vanilla-JS modules (no Node.js / React / build step).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

Open `http://localhost:<port>/chat` — first account becomes admin. Includes streaming chat (WS) + SSE slash commands, persistent sessions with folders/search/Markdown export, tool cards, inline permission approval, settings panel, light/dark/system theme, and `/health` + `/metrics` endpoints. A full xterm.js PTY terminal lives at `/` (100% CLI parity).

> **Full guide:** [docs/guides/web-ui.md](docs/guides/web-ui.md) · **Docker / home server:** [docs/guides/docker.md](docs/guides/docker.md) · **Native desktop app:** [desktop/README.md](desktop/README.md)

---

## Documentation

Detailed guides live in [`docs/guides/`](docs/guides/) to keep this README focused:

| Guide | What's inside |
|---|---|
| [**Features (full)**](docs/guides/features.md) | The complete feature table — every row with full detail (context compression, auto-fanout, themes, Trading/Research/Agents writeups) |
| [**Usage (all providers)**](docs/guides/usage.md) | Per-provider setup + example commands: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm, and local Ollama/LM Studio/vLLM |
| [**Web UI**](docs/guides/web-ui.md) | Chat UI, PTY terminal, API endpoints, settings, auth, SSE streaming |
| [**Desktop app**](desktop/README.md) | Native-window shell (Electron) that wraps the local web UI; build a self-contained `.dmg`/`.exe`/`.AppImage` |
| [**Docker / Home Server**](docs/guides/docker.md) | Dockerfile + compose: web UI + bridges in one container, host Ollama, workspace mount |
| [**Reference**](docs/guides/reference.md) | CLI, 50+ commands, 33 built-in tools, session search, error classification, tool cache |
| [**Extensions**](docs/guides/extensions.md) | Memory, Skills, Sub-Agents, MCP servers, Plugins, Monitor, Autonomous Agents |
| [**Bridges**](docs/guides/bridges.md) | Telegram, WeChat, Slack, QQ setup + remote control from your phone |
| [**Security & env vars**](docs/guides/security.md) | Threat model, `CHEETAHCLAWS_*` vars, bot-token handling, Bash denylist, fs sandbox, CSRF |
| [**Voice & Video**](docs/guides/voice-and-video.md) | Offline Whisper voice input, Video factory, TTS factory |
| [**Trading**](docs/guides/trading.md) | Multi-agent analysis, backtesting, BM25 memory, data fallbacks, SSJ integration |
| [**Advanced**](docs/guides/advanced.md) | Brainstorm, SSJ, Tmux, proactive monitoring, checkpoints, plan mode, sessions, cloud sync |
| [**Comparison**](docs/guides/comparison.md) | Full positioning vs Claude Code and OpenClaw — at-a-glance tables, both sides' wins, key design differences |
| [**Recipes**](docs/guides/recipes.md) | 12 step-by-step examples: code review, remote control, research, bug fix, browse, email, PDF/Excel |
| [**FAQ**](docs/guides/faq.md) | The full FAQ (MCP, models/providers, CLI/scripting, voice) |
| [**Plugin Authoring**](docs/guides/plugin-authoring.md) · [Example](examples/example-plugin/) | Build a plugin: tools, commands, skills, MCP; starter template |
| [**Research Lab**](docs/guides/research-lab.md) | `/lab start <topic>` — autonomous multi-agent paper writing with sandboxed experiments |
| [**Agent OS**](docs/agent-os.md) · [RFC index](docs/RFC/) | The `kernel/` layer + all design notes (RFC 0001-0032) |
| [**Contributing**](CONTRIBUTING.md) | Project structure, architecture guide, PR checklist |

---

## Quick Reference

```
cheetahclaws [OPTIONS] [PROMPT]

  -p, --print          Non-interactive: run prompt and exit
  -m, --model MODEL    Override model (e.g. gpt-4o, ollama/llama3.3)
  --accept-all         Auto-approve all operations (no permission prompts)
  --auto, --yolo       Autonomous: carry the whole task through with no prompts
                       (the default; overrides a saved /auto off)
  --ask, --no-auto     Turn approval prompts back on for this run
  --verbose            Show thinking blocks and per-turn token counts
  --show-tools         Show each tool call instead of a per-turn summary
                       (alias: --no-quiet; compact summary is the default)
  --thinking           Enable Extended Thinking (Claude only)
  --web                Start web server (Chat UI + PTY terminal in browser)
  --port / --host      Web server port / host (default 8080 / 127.0.0.1)
  --no-auth            Disable web password (local use only)
  --version / -h       Print version / show help
```

```bash
cheetahclaws                                          # interactive REPL, default model
cheetahclaws -m ollama/deepseek-r1:32b                # pick a model
cheetahclaws -p "Write a Python fibonacci function"   # non-interactive
cheetahclaws --accept-all -p "Init a pyproject.toml"  # CI / automation
cheetahclaws --ask "Refactor the parser"             # approve each step instead
cheetahclaws --web --port 8008 --no-auth              # browser chat + terminal
```

See the [Reference Guide](docs/guides/reference.md) for all 50+ slash commands, tools, and config options.

---

## Contributing

We welcome contributions! See the [Contributing Guide](CONTRIBUTING.md) for architecture, conventions, and the PR checklist.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

Building a plugin? See the [Plugin Authoring Guide](docs/guides/plugin-authoring.md) and the [example template](examples/example-plugin/).

---

## FAQ

A few common questions — the **full FAQ** is in [docs/guides/faq.md](docs/guides/faq.md).

**Q: How do I add an MCP server?**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**Q: Tool calls don't work with my local Ollama model (it just keeps describing what it would do instead of doing it).**
CheetahClaws now auto-recovers tool calls that local models emit as **text** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) instead of in Ollama's structured field, so most function-calling models execute tools out of the box. For best reliability use a tool-calling model — `qwen2.5-coder`, `llama3.3`, `mistral`, or `phi4`. Small models are also weaker at agentic tool use than cloud models, so expect them to need clearer, more concrete prompts.

**Q: After installing on macOS, `cheetahclaws: command not found` and no `~/.zshrc` was created.**
Reload your shell first: `source ~/.zshrc` (zsh) or `source ~/.bash_profile` (bash). The installer creates `~/.zshrc` if missing, symlinks the binary into `~/.local/bin`, and adds it to PATH. If you installed an older version, either re-run the installer or add this line yourself: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

More — remote vLLM, API cost (`/cost`), multiple keys per session, default model across projects, piping input, voice setup, garbled-text fixes — are all answered in [docs/guides/faq.md](docs/guides/faq.md).

---

## Citation
If you find the repository useful, please cite the study
``` Bash
@article{gu2026model,
  title={From Model Scaling to System Scaling: Scaling the Harness in Agentic AI},
  author={Gu, Shangding},
  journal={arXiv preprint arXiv:2605.26112},
  year={2026}
}

@article{cheetahclaws2026,
  title={CheetahClaws: Agent Harness Infrastructure for Long-Horizon, Multi-Model, and Tool-Using AI Systems},
  author={CheetahClaws Team},
  journal={github},
  year={2026}
}
```


---


## Thanks to all contributors:

<!-- contributors:start --> 

<a href="https://github.com/chauncygu"><img src="https://avatars.githubusercontent.com/u/27274029?v=4&s=48" width="48" height="48" alt="chauncygu"/></a>
<a href="https://github.com/KevRojo"><img src="https://avatars.githubusercontent.com/u/9065636?v=4&s=48" width="48" height="48" alt="KevRojo"/></a>
<a href="https://github.com/mxh1999"><img src="https://avatars.githubusercontent.com/u/30319236?v=4&s=48" width="48" height="48" alt="mxh1999"/></a>
<a href="https://github.com/seetvn"><img src="https://avatars.githubusercontent.com/u/100040536?v=4&s=48" width="48" height="48" alt="seetvn"/></a>
<a href="https://github.com/bmaltais"><img src="https://avatars.githubusercontent.com/u/187094624?v=4&s=48" width="48" height="48" alt="huytg2610"/></a>
<a href="https://github.com/bmaltais"><img src="https://avatars.githubusercontent.com/u/7474674?v=4&s=48" width="48" height="48" alt="bmaltais"/></a>
<a href="https://github.com/RheagalFire"><img src="https://avatars.githubusercontent.com/u/60213893?v=4&s=48" width="48" height="48" alt="RheagalFire"/></a>
<a href="https://github.com/yamaceay"><img src="https://avatars.githubusercontent.com/u/46201716?v=4&s=48" width="48" height="48" alt="yamaceay"/></a>
<a href="https://github.com/tsint"><img src="https://avatars.githubusercontent.com/u/63944253?v=4&s=48" width="48" height="48" alt="tsint"/></a>
<a href="https://github.com/albertcheng"><img src="https://avatars.githubusercontent.com/u/2686135?v=4&s=48" width="48" height="48" alt="albertcheng"/></a>
<a href="https://github.com/LostAion"><img src="https://avatars.githubusercontent.com/u/84846068?v=4&s=48" width="48" height="48" alt="LostAion"/></a>
<a href="https://github.com/lucaszhu-hue"><img src="https://avatars.githubusercontent.com/u/278269343?v=4&s=48" width="48" height="48" alt="lucaszhu-hue"/></a>
<a href="https://github.com/skint007"><img src="https://avatars.githubusercontent.com/u/37035851?v=4&s=48" width="48" height="48" alt="skint007"/></a>
<a href="https://github.com/thekbbohara"><img src="https://avatars.githubusercontent.com/u/133592644?v=4&s=48" width="48" height="48" alt="thekbbohara"/></a>

<!-- contributors:end -->
