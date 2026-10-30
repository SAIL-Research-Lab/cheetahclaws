# Research — multi-source topic research

`/research <topic>` fans out to up to **20 sources** in parallel, ranks
results by real engagement (citations, stars, upvotes, points, USD
volume, HF paper upvotes, Twitter likes, B站播放, 微博赞, 小红书赞, 知乎赞),
dedupes cross-source, and optionally asks the active model to
synthesize a brief with inline citations **plus a cross-platform
attention table and a publication trend sparkline** so you can see at
a glance which platforms the topic is alive on, how the buzz has moved
month-by-month, and where coverage is thin.

Supports **time-range filtering** (`--range 30d|6m|1y`, or absolute
`--since`/`--until`), **notable-citer analysis** for academic topics
(find authors with > N total citations who've cited the top papers),
and **auto-saved reports** to `~/.cheetahclaws/research_reports/` with
a `/reports` command for browsing, opening, and exporting.

The same pipeline is exposed to the agent as the **`Research`** tool, so
the model can trigger it mid-task when it needs current, multi-source
information on an academic, technical, financial, news, or social topic.

## Quick start

```
/research transformer inference efficiency
/research --domain academic "attention is all you need"
/research --sources arxiv,github "vLLM"
/research --range 30d "latest AI reasoning benchmarks"
/research --since 2024-01-01 --until 2024-06-30 "kubernetes CVEs"
/research --citations "diffusion models"               # find 10k+ citation authors
/research --citation-threshold 50000 "RLHF"
/research --expand "frontier LLM benchmarks"           # auto-generate 4 sibling queries
/research --expand 6 --range 30d "AI agent frameworks" # 6 subqueries, last 30 days
/research compare "GPT-5" vs "Claude-Opus-5"           # side-by-side, 2 topics
/research compare "RAG" vs "long context" vs "agents" --range 90d
/research --save-as ~/work/nvidia-q4.md "NVIDIA Q4 earnings"
/research list-sources

/reports                         # list recent saved reports
/reports open 3                  # print saved report #3
/reports delete 3
/reports path 3                  # print file path
```

No configuration required — 13 of 20 sources work out of the box.

## Sources

### Free (zero configuration)

| Source | Domains | What it gives you |
|---|---|---|
| **arXiv** | academic | Preprint feed — title, abstract, authors |
| **Semantic Scholar** | academic | Citation counts + influential citations + official TL;DRs |
| **OpenAlex** | academic | 250M+ open academic works with full citation graph |
| **HackerNews** (Algolia) | tech, social, news | Stories + comments with points + comment counts |
| **GitHub** | tech | Repos (sorted by stars) + issues (sorted by reactions) |
| **Reddit** | social, news | Last-30-days site-wide search with upvotes + comments |
| **StackOverflow** | tech | Questions scored by upvotes + answers + views |
| **Google News RSS** | news, web | Multilingual news via the public RSS feed |
| **Polymarket** | finance | Prediction market odds backed by real USD volume |
| **SEC EDGAR** | finance | 10-K / 10-Q / 8-K / S-1 / 13F filings |
| **HuggingFace Papers** | academic, tech | HF's curated daily papers — upvotes + comments from the AI/ML community |
| **alphaXiv** | academic | Community discussion layer over arXiv — one click to paper comments |
| **Bilibili (B站)** | social, tech, news | 视频 + 专栏搜索 · 播放/点赞/弹幕/评论 engagement. Zero-config — no key |

### Optional (need an API key, cookie, or package — silently skipped without)

| Source | Domains | Key / cookie / package | Notes |
|---|---|---|---|
| **Tavily** | web, news, tech, finance, academic | `TAVILY_API_KEY` | 1000 req/month free |
| **Brave Search** | web, news, tech, finance | `BRAVE_API_KEY` | 2000 req/month free |
| **Twitter / X** | social, news | `X_API_BEARER_TOKEN` (or `TWITTER_BEARER_TOKEN`) | v2 recent-search, 7d window, rate-limited per tier |
| **知乎 Zhihu** | social, tech, finance, news | `ZHIHU_COOKIE` | Paste `d_c0; z_c0` from browser; Zhihu blocks anonymous API |
| **微博 Weibo** | social, news | `WEIBO_COOKIE` | Paste `SUB; SUBP` from m.weibo.cn after logging in; the mobile API returns `ok: -100` anonymously |
| **小红书 Xiaohongshu** | social, news | `XHS_COOKIE` (+ sometimes `XHS_X_S`) | Xiaohongshu uses signed requests — cookie must come from an active browser session; anti-bot is aggressive and cookies may expire hourly. Alternative: use `--sources tavily` with `<query> site:xiaohongshu.com` |
| **Google Scholar** | academic | `pip install scholarly` | No official API; `scholarly` scrapes HTML — brittle (~5-20s per query, CAPTCHA-prone). Set `SKIP_GOOGLE_SCHOLAR=1` to force-disable even when installed. |
| **Serply Scholar** | academic | `SERPLY_API_KEY` | Google Scholar through the Serply API: Scholar's citation counts without scraping, ~1-2s per query. Each query (and each sub-query after expansion) uses one Serply request |

You can also optionally set:

- `CHEETAHCLAWS_GITHUB_TOKEN` (or `GITHUB_TOKEN`) — raises GitHub search limits from 10/min → 60/min
- `SEMANTIC_SCHOLAR_API_KEY` (or `S2_API_KEY`) — raises Semantic Scholar limits
- `STACKEXCHANGE_KEY` — raises StackOverflow daily quota from 300 → 10000
- `OPENALEX_EMAIL` / `SEC_CONTACT_EMAIL` — identifier for polite-pool rate limits
- `research_email` in `config.json` — applied to OpenAlex + SEC EDGAR at once

## Flags

| Flag | Meaning |
|---|---|
| `--domain D` | Restrict to these domain buckets. Valid: `academic`, `tech`, `finance`, `news`, `social`, `web`. Repeatable as comma list. |
| `--sources s1,s2` | Explicit source names. Overrides `--domain`. Run `/research list-sources` to see names. |
| `--limit N` | Max results per source (default 15, capped at 50). |
| `--range WIN` | Time window. Presets: `1d · 3d · 7d · 14d · 30d · 60d · 90d · 6m · 1y · 2y · 5y · all`. Natural: `30days`, `6months`, `2years`. Each source translates this to its native filter. |
| `--since YYYY-MM-DD` | Absolute lower bound. Overrides `--range`. |
| `--until YYYY-MM-DD` | Absolute upper bound. Overrides `--range`. |
| `--citations` | Run secondary Semantic Scholar lookups on top academic results — surfaces "Notable citing authors" with total citation counts ≥ threshold. Adds 2-5 API calls. |
| `--citation-threshold N` | Citation count to qualify as "notable" (default 10000). |
| `--expand [N]` | Ask the active model to propose 2-6 sibling subqueries (default 4), run each in parallel, merge results. Best for broad topics where a single query misses facets. Adds 1 LLM call + N × source_count HTTP calls (per-source limit shrinks proportionally). |
| `--save-as PATH` | Also copy the rendered brief to this path (`~/path.md` ok). Auto-save still happens. |
| `--no-cache` | Skip the 24h SQLite cache at `~/.cheetahclaws/research_cache.db`. |
| `--no-save` | Skip auto-save to `~/.cheetahclaws/research_reports/`. |
| `--no-synth` | Skip the LLM brief generation — return raw results only. |

## Topic → domain auto-classification

If you don't pass `--domain` or `--sources`, the classifier picks a
domain mix from topic keywords. Examples:

| Topic | Routed to |
|---|---|
| `"attention mechanism ablation"` | academic, tech, social |
| `"kubernetes pod autoscaling"` | tech, social |
| `"NVDA Q4 earnings reaction"` | finance, news |
| `"BTC price prediction"` | finance, social |
| `"AI regulation this week"` | news, web |
| `"zxqvn pfj"` (no signal) | web, news |

The classifier is offline + keyword-based (not an LLM call) so it adds
essentially zero latency. When in doubt, pass `--domain` explicitly.

## Time-range filter — per-source mapping

When you pass `--range 30d` (or `--since`/`--until`), every source that
can honor a date filter translates it to its native syntax:

| Source | Native filter mechanism |
|---|---|
| arXiv | `submittedDate:[YYYYMMDDHHMM TO YYYYMMDDHHMM]` in query |
| alphaXiv | Inherits from arXiv |
| Semantic Scholar | `year=LO-HI` param |
| OpenAlex | `filter=from_publication_date:…,to_publication_date:…` |
| HuggingFace Papers | Client-side filter on `publishedAt` |
| HackerNews | `numericFilters=created_at_i>TS,created_at_i<TS` |
| GitHub | `pushed:>=YYYY-MM-DD pushed:<=YYYY-MM-DD` in query |
| Reddit | `t=hour\|day\|week\|month\|year\|all` (auto-mapped by duration) |
| StackOverflow | `fromdate=TS&todate=TS` (unix seconds) |
| Google News | `after:YYYY-MM-DD before:YYYY-MM-DD` in query |
| SEC EDGAR | `dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD` |
| Tavily | `start_published_date` / `end_published_date` in POST body |
| Brave | `freshness=pd\|pw\|pm\|py` (best match to range duration) |
| Twitter / X | `start_time=ISO&end_time=ISO` params |
| Google Scholar | Client-side filter on year |
| Serply Scholar | `as_ylo=YYYY&as_yhi=YYYY` (Scholar's year filter) |
| Polymarket | (ignored — polymarket only returns active markets) |
| Zhihu | (ignored — no native date filter in v4 search) |

Unsupported sources still return their default results; the ranker's
recency weight (14-day half-life) biases freshness even without a
server-side filter.


## Notable-citer analysis (`--citations`)

When enabled, the pipeline makes secondary Semantic Scholar calls:
1. For each of the top 3 academic results, fetch its citations list.
2. For each citing paper's first 3 authors, fetch their
   `citationCount` and `hIndex` from `/author/{id}`.
3. Authors whose total citations ≥ `--citation-threshold` (default
   10,000) are surfaced in the brief as:

```
## Notable citing authors (≥10,000 total citations)

| Author | Affiliation | Total cites | h-index | Cited |
|---|---|---|---|---|
| Yoshua Bengio | Mila | 452,310 | 229 | Attention Is All You Need |
| Yann LeCun | Meta AI / NYU | 310,847 | 189 | Sparse Transformers (+1 more) |
```

Cost: 2-10 extra API calls per run. Works best with a
`SEMANTIC_SCHOLAR_API_KEY` to avoid the 100 req / 5 min anonymous limit.


## Top mentioned entities — offline pattern extraction

Every brief includes a `## Top mentioned entities` section directly beneath
the heat table, mined by pattern-matching each pulled result's title and
snippet. Four categories:

- **Models** — curated regex patterns for all major families: GPT · Claude
  (Opus/Sonnet/Haiku) · Gemini (Flash/Pro/Ultra/Nano) · Llama · Mistral /
  Mixtral · Grok · DeepSeek (V/R/Coder/Chat/Math) · Qwen / QwQ · GLM /
  ChatGLM · Moonshot / Kimi · Phi · Yi · Baichuan · MiniMax · Nova ·
  Command-R · OLMo · Falcon · StableLM · Vicuna · …
- **Benchmarks** — explicit list: MMLU / MMLU-Pro · GSM8K · MATH · AIME ·
  HumanEval / HumanEval+ / MBPP · SWE-bench / LiveCodeBench · MMMU /
  MathVista · Chatbot Arena / MT-Bench · Arena-Hard · GAIA /
  AgentBench / WebArena · HarmBench / AdvBench · C-Eval / CMMLU /
  GaoKao-Bench · RULER / LongBench / Needle-in-a-Haystack ·
  FrontierMath / ARC-AGI / GPQA-Diamond / HLE · …
- **Orgs / Labs** — OpenAI · Anthropic · Google DeepMind · Meta AI · xAI ·
  Mistral AI · Cohere · DeepSeek · Moonshot · Alibaba · Zhipu AI · Baidu
  · Tencent · ByteDance · Hugging Face · NVIDIA · 01.AI · AI2 · Mila ·
  Stanford / MIT / Berkeley / CMU / Tsinghua / 北大 · …
- **People** — extracted from the `author` field of academic results only
  (safe — no free-text NER over arbitrary snippets). Shows authors
  mentioned in ≥2 papers.

Counts dedupe per-result: one abstract mentioning `GPT-5` ten times
counts as **1**, not 10. Example output:

```
## Top mentioned entities

**Models** (5): GPT-5 ×8 · Claude-Opus-5 ×5 · Llama-4 ×3 · Gemini-2.5-Pro ×2 · GLM-5.1 ×2

**Benchmarks** (4): MMLU ×6 · HumanEval ×4 · SWE-bench ×3 · MATH ×2

**Orgs / Labs** (3): OpenAI ×7 · Anthropic ×5 · Meta ×3

**People** (2): Ilya Sutskever ×3 · Jim Fan ×2
```

This lets you answer *"what is everyone actually talking about"* in 1 glance,
without waiting for or paying for an LLM synthesis round trip.


## Multi-query expansion (`--expand`)

Broad topics ("frontier LLM benchmarks", "AI agent frameworks") have many
angles — a single query misses most. `--expand [N]` asks the active model
for N distinct subqueries (N defaults to 4, capped at 6), runs each in
parallel across all 20 sources, then merges into a single ranked set
before synthesis.

Example expansion for `frontier LLM benchmarks`:

```
1. LLM evaluation methodology       (theory angle)
2. benchmark saturation and contamination   (controversy angle)
3. capability measurement frontier models   (research angle)
4. human preference benchmarks evaluation   (industry deployment angle)
```

Each subquery gets a reduced per-source limit (so total results stay
manageable); the final brief cites across the full pool. Coverage jumps
3-5× for broad topics; subquery-distinct-angle prompt forbids paraphrases
so you don't burn API calls on near-duplicates.

Cost: 1 LLM call for expansion + N × source_count HTTP calls instead of
1 × source_count. Cache still keyed per (source, query) pair — subqueries
cache independently.


## Side-by-side compare

```
/research compare "GPT-5" vs "Claude-Opus-5"
/research compare "RAG" vs "long context" vs "agents" --range 90d
/research compare "CUDA" vs "ROCm" --limit 20 --save-as gpu-stack.md
```

2 or 3 topics (max 3), run in parallel. Produces a unified brief:

```
## Verdict at a glance
  One-paragraph headline comparison, cited as [A-N] / [B-N] / [C-N].

## Side-by-side heat
  Three heat tables stacked with 2-3 sentences pointing out distribution gaps.

## Shared themes
  2-3 bullets with citations from both / all.

## Unique strengths — GPT-5 (A)
  2-3 bullets with [A-N] citations only.

## Unique strengths — Claude-Opus-5 (B)
  2-3 bullets with [B-N] citations only.

## Open questions / gaps
  What would sharpen the comparison.
```

Prefixed citation format (`[A-N]` / `[B-N]` / `[C-N]`) keeps the
model honest — every claim can be traced back to the right topic's
evidence pool. Falls back to a deterministic no-LLM rendering with
all heat tables + entity tables side-by-side when no model is set.

Auto-saves to the reports dir like a normal `/research` run; the topic
is stored as `"topic A vs topic B"` for easy `/reports list` grep.


## Weekly trend tracking — subscribe via `/monitor`

Every `/research` topic can be turned into a recurring subscription
that re-runs on a schedule. The `/monitor` wizard picks up a new
topic type, **`research:<query>`**, which invokes the full 20-source
pipeline each time and pushes the resulting brief via your configured
channel (console / Telegram / Slack).

```
/subscribe research:RLHF weekly
/subscribe research:30d:NVIDIA chips daily --telegram
/subscribe research:90d:AGI safety weekly --slack
```

Subscription ID format:
- `research:<query>` — uses a 7-day window (aligns with the `weekly`
  default schedule)
- `research:<range>:<query>` — explicit window (`3d`, `7d`, `30d`,
  `90d`, `6m`, `1y`)

Each weekly run:
1. Fans out to all 20 sources
2. Filters by the window you picked
3. Renders the cross-platform attention heat table + sparkline
4. Writes a saved report (under `~/.cheetahclaws/research_reports/`)
5. Pushes a digest to your channels

`/monitor run research:RLHF` forces an immediate manual run.


## Saved reports

Every `/research` run auto-saves to
`~/.cheetahclaws/research_reports/<YYYY-MM-DD_HHMMSS>-<slug>.md` plus
a `.json` sidecar containing the full serialized Brief (results,
statuses, notable citers). Opt out with `--no-save`.

```
/reports              → list the 50 most recent
/reports open 3       → print report #3 to stdout
/reports open 2026-04-20_143015-nvidia-earnings    → open by stem
/reports delete 3     → remove #3
/reports path 3       → print the .md file path (for external tools)
```

Use `--save-as ~/my/custom.md` to also copy the brief to a
user-chosen path — the auto-saved copy still lives in the reports dir.


## One-click wizard via `/ssj`

The SSJ power menu (`/ssj`) exposes three research shortcuts that let
non-power users drive everything with arrow keys, no flags needed:

- **`16. 🔍 Research`** — wizard asks for topic + time range + whether to
  include notable-citer analysis, then runs `/research` with the right flags.
- **`17. 📊 Trend Track`** — wizard asks for topic + tracking window + frequency,
  then creates a `/subscribe research:<range>:<topic>` subscription on a
  weekly (or daily / 12h) schedule.
- **`18. 📁 Reports`** — opens the saved-reports browser (same as `/reports`).


## Output shape

```
# Research Brief: <topic>

_Routed to <domains> · N results from K sources · Mms · X cached_

## TL;DR
- 3-5 bullets, each with inline [N] citations

## Cross-platform attention
| Platform | Results | Top signal | Median age | Domain |
|---|---|---|---|---|
| arxiv            | 12 | preprint                     | 14d   | academic     |
| semantic_scholar | 15 | 234 citations                | 2y    | academic     |
| openalex         |  8 | 1,887 citations              | 4y    | academic     |
| huggingface      |  4 | 120 upvotes · 8 comments     | 5d    | academic/tech|
| alphaxiv         | 12 | community discussion         | 14d   | academic     |
| hackernews       |  8 | 498 pts · 112 comments       | 3d    | tech/social  |
| github           |  5 | 45,200 ⭐ · 2,300 forks      | 30d   | tech         |
| reddit           |  6 | 12,400 upvotes · 340 comments| 12d   | social/news  |
| zhihu            |  4 | 1,234 赞 · 56 评论            | 20d   | social/tech  |
| twitter          |  9 | 5,600 ❤ · 890 ↻              | 4h    | social/news  |
| tavily           |  0 | skipped · TAVILY_API_KEY…    | —     | web/news     |

Plus 2-3 sentences from the model comparing where attention concentrates
on this topic — academic-heavy, social-heavy, or balanced.

## Key findings by domain
### Academic / Tech / Finance / …
- Per-domain highlights, each with [N] citations

## Contrarian or minority views
- Only included when the evidence shows them

## Open questions / gaps
- What the pulled evidence does NOT cover

## Citations
[1] (arxiv)       Paper title — 12 citations
    https://arxiv.org/abs/...
[2] (hackernews)  Thread title — 498 pts · 112 comments
    https://news.ycombinator.com/...

## Missed / skipped sources
- tavily — TAVILY_API_KEY not set
- twitter — X_API_BEARER_TOKEN not set
```

## Engagement scoring — how results are ranked

Each source reports engagement on its own scale:

| Source | Native signal | Calibration point (→ score 1.0) |
|---|---|---|
| HackerNews | points + comments/2 | 500 |
| GitHub | stars | 5000 |
| Reddit | upvotes + comments/2 | 2000 |
| Semantic Scholar | citations | 100 |
| OpenAlex | citations | 100 |
| Polymarket | USD 24h volume | 10000 |
| StackOverflow | score·10 + answers·5 + views/100 | 100 |
| HuggingFace Papers | upvotes + comments | 100 |
| Zhihu | 赞 + 评论/2 | 500 |
| Twitter / X | likes + 3×retweets + replies + 2×quotes | 2000 |

Normalization is `min(1, log1p(raw) / log1p(calibration))` so viral content
clusters near 1.0 and median content sits around 0.3–0.5.

Final score = `0.7 × engagement + 0.3 × recency`, where recency decays
with a 14-day half-life. A fresh-but-low-engagement piece can still beat
a stale viral one when it's genuinely new.

## Using it as an agent tool

The model calls `Research` like any other tool:

```json
{
  "name": "Research",
  "input": {
    "topic": "stripe webhook idempotency",
    "domains": ["tech"],
    "limit": 10
  }
}
```

The tool returns a fully-rendered markdown brief — ready to paste into
the conversation, a report, or a PR description. Sources that fail or
skip are surfaced in a `## Missed / skipped sources` footer.

## Caching

Results are cached in `~/.cheetahclaws/research_cache.db` (SQLite) with
a 24h TTL. The cache key is `(source, normalized_query, limit)`. Pass
`--no-cache` to force a fresh fetch.

Concurrent `/research` runs share the cache safely. If the DB is
unreachable (read-only FS, corrupt file) the cache silently no-ops —
the worst case is a full re-fetch.

## Extending — adding a new source

1. Create `research/sources/my_source.py`.
2. Define `search(query: str, limit: int, config: dict | None = None) -> list[Result]`.
3. Call `register(SourceSpec(name, domains, tier, search, requires_env, description))`.
4. Add the import to `research/sources/__init__.py`.
5. Add a calibration row to `research/ranker.py`'s `_CALIBRATION`.
6. Write a test in `tests/test_research.py` that mocks `get`/`post_json`.

See `research/sources/hackernews.py` for a minimal template.

## Known limitations

- **Polymarket** uses client-side substring match on recent active
  markets — the Gamma API has no full-text endpoint. Very long-tail
  terms may return 0 matches even when relevant markets exist.
- **SEC EDGAR** full-text is only recent filings; older historical
  filings may not be searchable.
- **Reddit** is rate-limited per IP (~60 req/min). Heavy use may need
  an authenticated client — not currently supported.
- The **classifier** is keyword-based, not semantic. Ambiguous topics
  may route unexpectedly; `--domain` always wins.
