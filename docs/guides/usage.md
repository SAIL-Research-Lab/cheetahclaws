# Usage Guide — All Providers

Per-provider setup and example commands for every supported model backend. The
[README](../../README.md#usage-closed-source-api-models) carries a condensed
version of this; the complete per-provider detail lives here.

See also: [Supported Models table](../../README.md#supported-models) ·
[Model Name Format](../../README.md#model-name-format).

---

## Usage: Closed-Source API Models

### Anthropic Claude

Get your API key at [console.anthropic.com](https://console.anthropic.com).

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...

# Default model (claude-opus-4-6)
cheetahclaws

# Choose a specific model
cheetahclaws --model claude-sonnet-4-6
cheetahclaws --model claude-haiku-4-5-20251001

# Enable Extended Thinking
cheetahclaws --model claude-opus-4-6 --thinking --verbose
```

### OpenAI GPT

Get your API key at [platform.openai.com](https://platform.openai.com).

```bash
export OPENAI_API_KEY=sk-...

cheetahclaws --model gpt-4o
cheetahclaws --model gpt-4o-mini
cheetahclaws --model gpt-4.1-mini
cheetahclaws --model o3-mini
```

### Google Gemini

Get your API key at [aistudio.google.com](https://aistudio.google.com).

```bash
export GEMINI_API_KEY=AIza...

cheetahclaws --model gemini/gemini-3-flash-preview
cheetahclaws --model gemini/gemini-3.1-pro-preview
```

### Kimi (Moonshot AI)

Get your API key at [platform.moonshot.cn](https://platform.moonshot.cn).

```bash
export MOONSHOT_API_KEY=sk-...

cheetahclaws --model kimi/moonshot-v1-32k
cheetahclaws --model kimi/moonshot-v1-128k
```

### Qwen (Alibaba DashScope)

Get your API key at [dashscope.aliyun.com](https://dashscope.aliyun.com).

```bash
export DASHSCOPE_API_KEY=sk-...

cheetahclaws --model qwen/Qwen3.5-Plus
cheetahclaws --model qwen/Qwen3-MAX
cheetahclaws --model qwen/Qwen3.5-Flash
```

### Zhipu GLM

Get your API key at [open.bigmodel.cn](https://open.bigmodel.cn).

```bash
export ZHIPU_API_KEY=...

cheetahclaws --model zhipu/glm-4-plus
cheetahclaws --model zhipu/glm-4-flash   # free tier
```

### DeepSeek

Get your API key at [platform.deepseek.com](https://platform.deepseek.com).

```bash
export DEEPSEEK_API_KEY=sk-...

cheetahclaws --model deepseek/deepseek-chat
cheetahclaws --model deepseek/deepseek-reasoner
```

### MiniMax

Get your API key at [platform.minimaxi.chat](https://platform.minimaxi.chat).

```bash
export MINIMAX_API_KEY=...

cheetahclaws --model minimax/MiniMax-Text-01
cheetahclaws --model minimax/MiniMax-VL-01
cheetahclaws --model minimax/abab6.5s-chat
```

### OpenRouter (400+ models, one key)

[OpenRouter](https://openrouter.ai) fronts every major vendor behind one
OpenAI-compatible endpoint, so a single key reaches Claude, GPT, Gemini,
DeepSeek, Llama, Qwen and ~400 more. Get a key at
[openrouter.ai/keys](https://openrouter.ai/keys).

```bash
export OPENROUTER_API_KEY=sk-or-...       # or: /config openrouter_api_key=sk-or-...

cheetahclaws --model openrouter/deepseek/deepseek-v4-flash
cheetahclaws --model openrouter/anthropic/claude-sonnet-4-6
cheetahclaws --model openrouter/openai/gpt-5
```

**The model ID is double-prefixed.** OpenRouter addresses models by an
upstream `<vendor>/<model>` path, so the first segment (`openrouter`) is the
provider and *everything after it* is passed through verbatim as the model
ID. `openrouter/deepseek/deepseek-v4-flash` therefore sends
`deepseek/deepseek-v4-flash` — which is exactly what OpenRouter's catalog
lists. (`nim/` works the same way.)

**Pinning the upstream provider / quantization.** OpenRouter picks a
secondary provider for you by default. To force one, append
`@<provider-slug>[/<quantization>]` to the model:

```bash
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash@gmicloud       # this provider only
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8   # + quantization
cheetahclaws --model openrouter/deepseek/deepseek-v4-flash@fp8            # quantization only
```

The suffix is **split off before the request** and sent as OpenRouter's
`provider` routing object — the model field always stays a real catalog ID
(gluing the provider into the model ID makes OpenRouter reject the call as
an unknown model). Accepted quantizations: `fp4` · `fp8` · `int4` · `int8`.
Pinning a provider also sets `allow_fallbacks: false`, so a request fails
loudly instead of silently landing on a different upstream — drop the
suffix if you would rather have OpenRouter reroute around an outage.

> **Cost tracking:** `/cost` and the `/quota` budget price OpenRouter usage
> from the same per-model table as direct calls, so a model CheetahClaws
> already knows (`deepseek-v4-flash`, `claude-sonnet-4-6`, …) is billed the
> same whichever route it takes. A model with no price entry still records
> tokens but estimates $0 — set a **token** budget rather than a dollar one
> if you rely on hard caps for exotic models.

### Requesty (700+ models, one key)

[Requesty](https://www.requesty.ai) is an LLM gateway with 700+ models behind
one OpenAI-compatible endpoint (`https://router.requesty.ai/v1`). Get a key at
[app.requesty.ai/api-keys](https://app.requesty.ai/api-keys); docs are at
[docs.requesty.ai](https://docs.requesty.ai).

```bash
export REQUESTY_API_KEY=rqsty-...         # or: /config requesty_api_key=rqsty-...

cheetahclaws --model requesty/openai/gpt-4o-mini
cheetahclaws --model requesty/anthropic/claude-sonnet-4-6
cheetahclaws --model requesty/claude-sonnet-4-6       # managed policy ID
cheetahclaws --model requesty/gpt-5-mini@eu           # EU providers only
```

As with OpenRouter, the first segment (`requesty`) is the provider and
everything after it is sent verbatim as the model ID. That can be a catalog
`<vendor>/<model>` path (the full list is at `GET /v1/models`) or a managed
policy ID with no vendor prefix (`GET /v1/models/managed`), which is a
Requesty maintained routing chain across several upstream providers for one
model. Managed policy IDs ending in `@eu` only route through EU providers.
Cost tracking uses the same per-model table as direct calls.

### LiteLLM (AWS Bedrock / Azure / Vertex AI)

Use the `litellm/` prefix when the upstream needs auth that's painful to
wire by hand — **AWS Bedrock SigV4 signing**, **Azure OpenAI deployment
routing**, or **Google Vertex AI service-account JWTs**. For plain
OpenAI-shaped endpoints (vLLM, LM Studio, TGI, Together, Groq, …) prefer
the zero-dependency `custom/` adapter from Option C below.

```bash
pip install ".[litellm]"

# AWS Bedrock — uses your boto3 credential chain (AWS_PROFILE, ~/.aws/
# credentials, IAM role on EC2). No explicit api_key needed.
export AWS_REGION=us-east-1
cheetahclaws --model litellm/bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0

# Azure OpenAI — deployment-id routing via api_base + api_version pair.
export AZURE_API_KEY=...
export AZURE_API_BASE=https://my-resource.openai.azure.com
export AZURE_API_VERSION=2024-10-01-preview
cheetahclaws --model litellm/azure/my-gpt4o-deployment

# Google Vertex AI — Application Default Credentials.
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export VERTEXAI_PROJECT=my-project
export VERTEXAI_LOCATION=us-central1
cheetahclaws --model litellm/vertex_ai/gemini-2.0-flash
```

The model string format is **`litellm/<provider>/<model>`** — the first
segment routes to this adapter, everything after is passed verbatim to
`litellm.completion(model=...)`. See [LiteLLM docs](https://docs.litellm.ai/docs/providers)
for the full list of 100+ supported providers, and
[`recipes.md`](recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider)
for the troubleshooting table.

---

## Usage: Open-Source Models (Local)

### Option A — Ollama (Recommended)

Ollama runs models locally with zero configuration. No API key required.

**Step 1: Install Ollama**

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Or download from https://ollama.com/download
```

**Step 2: Pull a model**

```bash
# Best for coding (recommended)
ollama pull qwen2.5-coder          # 4.7 GB (7B)
ollama pull qwen2.5-coder:32b      # 19 GB (32B)

# General purpose
ollama pull llama3.3               # 42 GB (70B)
ollama pull llama3.2               # 2.0 GB (3B)

# Reasoning
ollama pull deepseek-r1            # 4.7 GB (7B)
ollama pull deepseek-r1:32b        # 19 GB (32B)

# Other
ollama pull phi4                   # 9.1 GB (14B)
ollama pull mistral                # 4.1 GB (7B)
```

**Step 3: Start Ollama server** (runs automatically on macOS; on Linux run manually)

```bash
ollama serve     # starts on http://localhost:11434
```

**Step 4: Run cheetahclaws**

```bash
cheetahclaws --model ollama/qwen2.5-coder
cheetahclaws --model ollama/llama3.3
cheetahclaws --model ollama/deepseek-r1
```

Or

```bash
python cheetahclaws.py --model ollama/qwen2.5-coder
python cheetahclaws.py --model ollama/llama3.3
python cheetahclaws.py --model ollama/deepseek-r1
python cheetahclaws.py --model ollama/qwen3.5:35b
```

**List your locally available models:**

```bash
ollama list
```

Then use any model from the list:

```bash
cheetahclaws --model ollama/<model-name>
```

**If a local model "just keeps talking" instead of editing files / running commands:**
that means it emitted its tool calls as text rather than as structured calls.
CheetahClaws auto-recovers the common text formats — `<tool_call>…</tool_call>`
(Qwen/Hermes), `<|tool_call|>…` (Gemma), and `[TOOL_CALLS]…` (Mistral) — so they
now execute. For best results pick a function-calling model (`qwen2.5-coder`,
`llama3.3`, `mistral`, `phi4`) and give concrete prompts (a path, a filename, an
exact command). Small local models are inherently weaker at agentic tool use than
cloud models, so they may still need more explicit instructions. If a model has no
tool template at all, the first tool-enabled request returns `500` and CheetahClaws
falls back to chat-only mode (a yellow `[warn]` is printed) — pull one of the
recommended models instead.

---

### Option B — LM Studio

LM Studio provides a GUI to download and run models, with a built-in OpenAI-compatible server.

**Step 1:** Download [LM Studio](https://lmstudio.ai) and install it.

**Step 2:** Search and download a model inside LM Studio (GGUF format).

**Step 3:** Go to **Local Server** tab → click **Start Server** (default port: 1234).

**Step 4:**

```bash
cheetahclaws --model lmstudio/<model-name>
# e.g.:
cheetahclaws --model lmstudio/phi-4-GGUF
cheetahclaws --model lmstudio/qwen2.5-coder-7b
```

The model name should match what LM Studio shows in the server status bar.

---

### Option C — vLLM / Self-Hosted OpenAI-Compatible Server

For self-hosted inference servers (vLLM, TGI, llama.cpp server, etc.) that expose an OpenAI-compatible API:

Quick Start for option C:
Step 1: Start vllm:
 ```
CUDA_VISIBLE_DEVICES=7 python -m vllm.entrypoints.openai.api_server \
      --model Qwen/Qwen2.5-Coder-7B-Instruct \
      --host 0.0.0.0 \
      --port 8000 \
      --enable-auto-tool-choice \
      --tool-call-parser hermes
```


 Step 2: Start cheetahclaws：
```
  export CUSTOM_BASE_URL=http://localhost:8000/v1
  export CUSTOM_API_KEY=none
  cheetahclaws --model custom/Qwen/Qwen2.5-Coder-7B-Instruct
```


```bash
# Example: vLLM serving Qwen2.5-Coder-32B
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct \
    --port 8000 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes

# Then run cheetahclaws pointing to your server:
cheetahclaws
```

Inside the REPL:

```
/config custom_base_url=http://localhost:8000/v1
/config custom_api_key=token-abc123    # skip if no auth
/model custom/Qwen2.5-Coder-32B-Instruct
```

Or set via environment:

```bash
export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123

cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

For a remote GPU server:

```bash
/config custom_base_url=http://192.168.1.100:8000/v1
/model custom/your-model-name
```

#### Using vLLM with the Web UI

`--web --model <name>` now persists the model into `~/.cheetahclaws/config.json` before the server starts, so the Chat UI hits the right endpoint on the very first request:

```bash
export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=dummy            # vLLM doesn't validate but the OpenAI SDK requires non-empty
cheetahclaws --web --no-auth --port 8080 --model custom/qwen2.5-72b
```

If you skip `--model`, the Chat UI uses whatever was previously saved (it will **not** silently fall back to a default). Switch models on the fly from the Chat UI's Settings panel or with `/model custom/<name>` in the message box. The model name after `custom/` must match the vLLM `--served-model-name` exactly.

### Option D — Atlas Cloud (hosted, OpenAI-compatible)

🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** is a full-modal AI inference platform with an OpenAI-compatible API — DeepSeek, Qwen, GLM, Kimi, MiniMax and more behind one endpoint. It plugs into the zero-dependency `custom/` adapter:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

`deepseek-ai/deepseek-v4-pro` is a reasoning model; any other Atlas chat model id works the same way.

<details>
<summary>All Atlas Cloud chat models (59)</summary>

- **Anthropic (Claude):** `anthropic/claude-haiku-4.5-20251001`, `anthropic/claude-opus-4.8`, `anthropic/claude-sonnet-4.6`
- **OpenAI (GPT):** `openai/gpt-5.4`, `openai/gpt-5.5`
- **Google (Gemini):** `google/gemini-3.1-flash-lite`, `google/gemini-3.1-pro-preview`, `google/gemini-3.5-flash`
- **Qwen:** `qwen/qwen2.5-7b-instruct`, `Qwen/Qwen3-235B-A22B-Instruct-2507`, `qwen/qwen3-235b-a22b-thinking-2507`, `qwen/qwen3-30b-a3b`, `Qwen/Qwen3-30B-A3B-Instruct-2507`, `qwen/qwen3-30b-a3b-thinking-2507`, `qwen/qwen3-32b`, `qwen/qwen3-8b`, `Qwen/Qwen3-Coder`, `qwen/qwen3-coder-next`, `qwen/qwen3-max-2026-01-23`, `Qwen/Qwen3-Next-80B-A3B-Instruct`, `Qwen/Qwen3-Next-80B-A3B-Thinking`, `Qwen/Qwen3-VL-235B-A22B-Instruct`, `qwen/qwen3-vl-235b-a22b-thinking`, `qwen/qwen3-vl-30b-a3b-instruct`, `qwen/qwen3-vl-30b-a3b-thinking`, `qwen/qwen3-vl-8b-instruct`, `qwen/qwen3.5-122b-a10b`, `qwen/qwen3.5-27b`, `qwen/qwen3.5-35b-a3b`, `qwen/qwen3.5-397b-a17b`, `qwen/qwen3.6-35b-a3b`, `qwen/qwen3.6-plus`
- **DeepSeek:** `deepseek-ai/deepseek-ocr`, `deepseek-ai/deepseek-r1-0528`, `deepseek-ai/DeepSeek-V3-0324`, `deepseek-ai/DeepSeek-V3.1`, `deepseek-ai/DeepSeek-V3.1-Terminus`, `deepseek-ai/deepseek-v3.2`, `deepseek-ai/DeepSeek-V3.2-Exp`, `deepseek-ai/deepseek-v4-flash`, `deepseek-ai/deepseek-v4-pro`
- **Moonshot (Kimi):** `moonshotai/Kimi-K2-Instruct`, `moonshotai/Kimi-K2-Instruct-0905`, `moonshotai/Kimi-K2-Thinking`, `moonshotai/kimi-k2.5`, `moonshotai/kimi-k2.6`
- **Zhipu (GLM):** `zai-org/GLM-4.6`, `zai-org/glm-4.7`, `zai-org/glm-5`, `zai-org/glm-5-turbo`, `zai-org/glm-5.1`, `zai-org/glm-5v-turbo`
- **MiniMax:** `MiniMaxAI/MiniMax-M2`, `minimaxai/minimax-m2.1`, `minimaxai/minimax-m2.5`, `minimaxai/minimax-m2.7`
- **xAI:** `xai/grok-4.3`
- **Kwaipilot:** `kwaipilot/kat-coder-pro-v2`
- **Other:** `owl`

</details>

---

## Tool Profiles (`tool_profile`)

Every model request carries the JSON schemas of the tools the agent may call.
The **tool profile** selects how much of that surface is advertised on each
turn — a smaller surface means fewer prompt tokens and less for the model to
choose between, which helps on small-context or weaker local models.

The default is **`full`**, so out of the box **nothing is hidden** — web,
sub-agents, MCP, plugins, and every built-in tool are available. Shrinking the
surface is always an explicit opt-in.

| Profile | Tools advertised | Use when |
|---------|------------------|----------|
| `full` *(default)* | Everything registered — coding, web/documents, multi-agent + tasks, plan mode, email, MCP, and plugins | You want the complete surface (default behavior). |
| `standard` | Compact coding set only: `Read`, `Write`, `Edit`, `Bash`, `Glob`, `Grep`, `GetDiagnostics`, `NotebookEdit`, `AskUserQuestion`, and the `Memory*` tools | Plain coding sessions; smallest prompt / best for small-context models. |
| `research` | `standard` **+** `WebFetch`, `WebSearch`, `WebBrowse`, `Research`, `ReadPDF`, `ReadImage`, `ReadSpreadsheet`, `ReadEmail`, `SummarizeLargeFile` | Web + document research without multi-agent overhead. |
| `orchestration` | `standard` **+** `Agent`, `SendMessage`, `CheckAgentResult`, `ListAgentTasks`, `ListAgentTypes`, `Skill`, `SkillList`, `TaskCreate`/`TaskUpdate`/`TaskGet`/`TaskList`, `EnterPlanMode`, `ExitPlanMode`, `SleepTimer` | Multi-agent workflows, task lists, and plan mode. |

Every non-`full` profile still includes the `standard` coding tools, so you
never lose Read/Write/Edit/Bash by narrowing the surface.

**Set it:**

```bash
# In a CLI session (persists to ~/.cheetahclaws/config.json):
/config tool_profile=standard

# Or edit ~/.cheetahclaws/config.json directly:
#   "tool_profile": "research"
```

In the **Web UI**, use the *Tool Surface* dropdown in Settings, or
`PATCH /api/config` with `{"config": {"tool_profile": "research"}}`. An
unknown value is rejected (`400` on the API, an error on the CLI).

> **Notes**
> - A config that predates this setting (or omits it) inherits `full`, so
>   upgrading never silently removes a capability you relied on.
> - Sub-agents inherit the parent session's `tool_profile`. If you rely on
>   `researcher` sub-agents reaching the web, keep the parent on `full` (the
>   default) or `research`.
> - The profile only changes what is **advertised** per turn; it does not
>   uninstall anything. Switch back to `full` at any time.
