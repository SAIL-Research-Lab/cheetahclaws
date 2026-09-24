# Recipes — Common Use Cases

Practical examples to get started with CheetahClaws after installation.

---

## 1. Code Review with a Local Ollama Model

Use a free, local model to review code without sending anything to the cloud.

```bash
# Pull a capable model
ollama pull qwen2.5-coder:14b

# Start CheetahClaws with Ollama
cheetahclaws --model ollama/qwen2.5-coder:14b
```

```
[project] » Review the code in src/api.py for security issues, performance 
             problems, and potential bugs. Be specific with line numbers.
```

For a full project audit:
```
[project] » Read all Python files in this project and give me a prioritized 
             list of the 10 most important issues to fix before shipping.
```

**Tip:** Ollama models run locally — your code never leaves your machine.

### Alternative: self-hosted vLLM (or any OpenAI-compatible endpoint) via the `custom/` provider

Use this when you have your own inference server — vLLM, LM Studio, TGI, llama.cpp's
OpenAI server, or a remote machine exposing `/v1/chat/completions`. The `custom/`
provider is just an OpenAI-compatible client; it needs a `base_url` and (optionally)
an API key.

**Step 1 — start your server.** Example: launch a quantized Qwen 2.5 72B on two GPUs
with vLLM. The `--served-model-name` you pass here becomes the suffix after `custom/`.

```bash
CUDA_VISIBLE_DEVICES=6,7 python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-72B-Instruct-AWQ \
    --tensor-parallel-size 2 \
    --quantization awq_marlin \
    --host 0.0.0.0 --port 8000 \
    --max-model-len 32768 \
    --gpu-memory-utilization 0.9 \
    --enable-auto-tool-choice \
    --tool-call-parser hermes \
    --served-model-name qwen2.5-72b
```

**Step 2 — verify the endpoint is reachable.** This catches firewall / wrong-port
issues before CheetahClaws ever sees them.

```bash
curl http://localhost:8000/v1/models
# Should list "qwen2.5-72b"
```

**Step 3 — point CheetahClaws at it.** The model string is `custom/<served-model-name>`;
it must match `--served-model-name` exactly. You also need a `base_url` — set it
either via env var or `/config`. **Don't forget the `/v1` suffix.**

Env-var form (one-shot):

```bash
export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=EMPTY     # vLLM ignores the key, but the OpenAI SDK requires a non-empty string
cheetahclaws --web --model custom/qwen2.5-72b
```

In-app form (persists across launches):

```
[project] » /config custom_base_url=http://localhost:8000/v1
[project] » /config custom_api_key=EMPTY
[project] » /model custom/qwen2.5-72b
```

**Troubleshooting:**

| Symptom | Cause | Fix |
|---|---|---|
| `ValueError: custom provider requires a base_url` | `CUSTOM_BASE_URL` unset and no `custom_base_url` in config | Set one of them; remember the `/v1` suffix |
| `404 Not Found` on `/v1/chat/completions` | Wrong path — used `http://host:8000` without `/v1` | Append `/v1` to the base URL |
| `model not found` from vLLM | Model string mismatch | `custom/<X>` must match `--served-model-name <X>` exactly |
| Connection refused from another machine | vLLM bound to `127.0.0.1` only, or firewall | Launch with `--host 0.0.0.0` and open the port |
| Tool calls never fire | vLLM started without tool-call support | Add `--enable-auto-tool-choice --tool-call-parser hermes` (or the parser matching your model) |

**Tip:** CheetahClaws queries `/v1/models` on first use to discover the model's real
context window, so you don't need to hard-code `context_limit` in
`providers.py` — `--max-model-len` on the server is the source of truth.

### Alternative: cloud providers with non-trivial auth via the `litellm/` provider

Use this when the upstream needs auth that's painful to wire by hand —
**AWS Bedrock SigV4 signing**, **Azure OpenAI deployment routing**, or
**Google Vertex AI service-account JWTs**. For plain OpenAI-shaped
endpoints (vLLM, LM Studio, TGI, Together, Fireworks, …) prefer the
`custom/` provider above; it adds no dependency.

```bash
pip install cheetahclaws[litellm]

# Bedrock — uses your boto3 credential chain (AWS_PROFILE, ~/.aws/credentials,
# IAM role on EC2). No api_key needed.
export AWS_REGION=us-east-1
cheetahclaws --model litellm/bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0

# Azure OpenAI — deployment-id routing via the api_base + api_version pair.
export AZURE_API_KEY=...
export AZURE_API_BASE=https://my-resource.openai.azure.com
export AZURE_API_VERSION=2024-10-01-preview
cheetahclaws --model litellm/azure/my-gpt4o-deployment

# Vertex AI — Google Application Default Credentials.
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export VERTEXAI_PROJECT=my-project
export VERTEXAI_LOCATION=us-central1
cheetahclaws --model litellm/vertex_ai/gemini-2.0-flash
```

The model string format is **`litellm/<provider>/<model>`** — the first
segment selects this adapter, everything after is passed verbatim to
`litellm.completion(model=...)`. See https://docs.litellm.ai/docs/providers
for the full list of 100+ supported providers.

| Symptom | Cause | Fix |
|---|---|---|
| `litellm SDK not installed` | Extra not selected at install time | `pip install cheetahclaws[litellm]` |
| `400 …unsupported param…` | Model rejected a kwarg (e.g. `temperature` on o1) | Adapter already passes `drop_params=True`; double-check the kwarg name |
| `metadata.cost_unknown: True` on responses | litellm has no price entry for that model | Cost ledger records `cost_micro=0`; tokens still count. Either upgrade litellm or accept the unknown |
| 401 on Bedrock | Wrong region or no IAM permission | Confirm `AWS_REGION` matches the model's region; check `bedrock:InvokeModel` on the principal |
| 403 on Azure | `api_version` too old for the deployment | Bump `AZURE_API_VERSION` to a version listed on the deployment's page |

**When to prefer `custom/` over `litellm/`:** if your endpoint speaks
plain OpenAI Chat Completions and accepts a bearer token (vLLM, LM
Studio, TGI, Together, Fireworks, Groq, …), `custom/` is
zero-dependency and zero-config beyond `CUSTOM_BASE_URL`. Reach for
`litellm/` only when the auth gymnastics above are the actual blocker.

**OpenRouter has its own provider now** — prefer `openrouter/<vendor>/<model>`
over both `custom/` and `litellm/openrouter/…`: the base URL and key env
(`OPENROUTER_API_KEY`) are built in, the models show up in the `/model` Tab
picker, and it is the only route that supports pinning the upstream provider
with the `@<provider>[/<quantization>]` suffix. See
[usage.md](usage.md#openrouter-400-models-one-key). The same goes for
Requesty: use `requesty/<model>` with `REQUESTY_API_KEY` rather than
`custom/` (see [usage.md](usage.md#requesty-700-models-one-key)).

---

## 2. Remote Control via Telegram

Control CheetahClaws from your phone while it runs on your server/workstation.

**Setup (one time):**
1. Message [@BotFather](https://t.me/BotFather) on Telegram, create a bot, get the token
2. Get your chat ID from [@userinfobot](https://t.me/userinfobot)
3. Configure:
```bash
cheetahclaws
/config telegram_token=YOUR_BOT_TOKEN
/config telegram_chat_id=YOUR_CHAT_ID
/telegram start
```

**Usage from phone:**
```
You (Telegram): What files changed in the last commit?
Bot: [reads git log, shows diff summary]

You: Fix the bug in auth.py line 42
Bot: [edits file, shows diff, confirms]

You: !git status
Bot: [runs command, returns output]
```

**Tip:** Use `!command` prefix to run shell commands directly from Telegram.

---

## 3. Autonomous Research Agent

Let CheetahClaws research a topic independently while you do other work.

```
[project] » /agent
```

Select **"Research Assistant"** from the wizard, then:
```
Research topic: Compare React Server Components vs Next.js App Router 
                for a production e-commerce site

Output: Write findings to research_output.md
```

The agent will:
- Search the web for current information
- Read documentation and blog posts
- Synthesize findings into the output file
- Continue iterating until the research is complete

**Monitor progress:**
```
/agents              # see running agents
/tasks               # see task progress
```

---

## 4. Quick Bug Fix Workflow

```bash
# Start with the bug context
cheetahclaws -p "Fix the TypeError in utils.py:42 where None is passed to len()"
```

Or interactively:
```
[project] » There's a crash when users submit an empty form. The error is 
             TypeError: argument of type 'NoneType' is not iterable in 
             handlers/form.py. Find and fix it.
```

CheetahClaws will:
1. Read the file
2. Identify the root cause
3. Apply the fix
4. Show you the diff for approval

---

## 5. Multi-Model Brainstorm

Get perspectives from different models on a design decision.

```
[project] » /brainstorm

Topic: Should we use PostgreSQL or MongoDB for our user activity tracking 
       system? We expect 10M events/day with complex aggregation queries.
```

The brainstorm spawns multiple sub-agents that discuss and debate, then synthesizes a final recommendation.

---

## 6. Session Persistence Across Days

Work on a long-running project across multiple sessions:

```bash
# Day 1: Start working
cheetahclaws
[project] » Let's refactor the authentication module. Start by analyzing 
             the current auth flow...
# ... work happens ...
# Ctrl+D to exit (auto-saves)

# Day 2: Resume where you left off
cheetahclaws
[project] » /resume
# Your full conversation context is restored
[project] » Continue with the auth refactor. What's left?
```

**Tip:** Use `/save my-refactor` to name a session for easy retrieval later with `/load my-refactor`.

---

## 7. Monitoring AI Research Papers

Stay updated on topics that matter to you:

```
[project] » /monitor
```

Select **"Add subscription"**, then:
```
Topic: ai_research
Schedule: daily
Notification: --telegram
```

Every day, CheetahClaws will:
- Fetch the latest papers from arXiv
- Summarize the most relevant ones
- Send you a digest via Telegram

Other subscription types: `stock_TSLA`, `crypto_BTC`, `world_news`, `custom:<query>`

---

## 8. Project Bootstrap with /init

Start a new project with AI-readable context:

```bash
mkdir my-new-project && cd my-new-project
git init
cheetahclaws
[my-new-project] » /init
```

This creates a `CLAUDE.md` file that CheetahClaws reads on every startup — containing project conventions, tech stack, and guidelines that shape all future interactions.

---

## 9. Search Past Conversations

Find anything you discussed in previous sessions:

```
[project] » /search authentication bug
```

Output:
```
Found 2 session(s) matching "authentication bug":

  [a3f8c2e1] Auth refactor (gpt-4o)
    2026-04-14 15:30:22 · 12 turns
    How do I fix the >>>authentication<<< >>>bug<<< in login.py?

  [c9e2d1b3] Security review (claude-sonnet-4-6)
    2026-04-10 11:00:00 · 6 turns
    ...found an >>>authentication<<< >>>bug<<< in the middleware...
```

Then load and resume:
```
[project] » /load a3f8c2e1
Session loaded from ... (24 messages)
[project] » Continue where we left off with the auth fix.
```

**Tip:** Sessions are automatically indexed. Your first `/search` will import all existing JSON sessions into the search index.

---

## 10. Browse Dynamic Web Pages

Use `WebBrowse` for JavaScript-heavy pages that `WebFetch` can't render:

```
[project] » Go to https://github.com/trending and tell me the top 5 trending repos today.
```

The AI will use `WebBrowse` to render the page with headless Chromium and extract the content.

**Install:** `pip install cheetahclaws[browser] && playwright install chromium`

---

## 11. Read and Reply to Emails

```bash
# First, configure email (one time)
cheetahclaws
/config email_address=you@gmail.com
/config email_password=your-app-password
/config email_imap_host=imap.gmail.com
/config email_smtp_host=smtp.gmail.com
```

Then use naturally:

```
[project] » Check my latest emails from boss@company.com
[project] » Summarize the quarterly report email
[project] » Draft a reply saying I'll have the analysis ready by Friday
```

The AI reads your inbox, summarizes emails, and drafts replies — always asking for confirmation before sending.

---

## 12. Analyze PDFs and Spreadsheets

```
[project] » Read the contract at ~/Documents/contract.pdf and summarize the key terms
[project] » Open data.xlsx and find the top 10 customers by revenue
[project] » Extract text from this scanned receipt: ~/photos/receipt.jpg
```

**Install:**
```bash
pip install "cheetahclaws[files]"    # PDF + Excel
pip install "cheetahclaws[ocr]"      # image OCR (also needs: brew install tesseract)
```

---

## Tips

- **`/search <query>`** — full-text search across all past sessions
- **`/status`** — quick overview: model, token usage, cost, session stats
- **`/doctor`** — diagnose connectivity, dependencies, and configuration issues
- **`/compact`** — manually compress conversation when context gets large
- **`/copy`** — copy the last response to clipboard
- **`/export`** — export the full conversation to a Markdown file
- **`Ctrl+C`** — interrupt a long response without losing conversation
- **`!command`** — run a shell command inline (e.g., `!git status`)
