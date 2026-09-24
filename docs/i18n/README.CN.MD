[English](../../README.md) | 中文 | [한국어](README.KO.MD) | [日本語](README.JP.MD) | [Français](README.FR.MD) | [Deutsch](README.DE.MD) | [Español](README.ES.MD) | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>：面向长时程、多模型、工具使用型 AI 系统的快速易用 Agent Harness 基础设施</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">官网</a>
    ·
    <a href="https://arxiv.org/pdf/2605.26112">Scaling the Harness</a>
    ·
    <a href="https://github.com/SafeRL-Lab/cheetahclaws/issues">Issue</a>
    ·
    <a href="https://pypi.org/project/cheetahclaws/">
      <img src="https://img.shields.io/badge/downloads-9.6K-blue" alt="Downloads 9.6K" align="absmiddle">
    </a>
  </p>
</div>


### 快速安装

```bash
pip install cheetahclaws
```

然后直接运行：

```bash
cheetahclaws        # start chatting!
```

其他安装方式：[一行安装脚本](#其他方式一行安装脚本) | [从源码安装](#其他方式用-pip-从源码安装) | [uv 安装](#其他方式用-uv-安装) | [从源码直接运行](#其他方式直接从源码运行无需安装) | [完整安装说明](#安装)

> 🖥️ **想要原生应用？** 桌面版构建（Electron）将完整的聊天 UI 封装进一个窗口 —— 无需终端。参见 [`desktop/`](../../desktop/README.md)。

## 🔥🔥🔥 新闻（太平洋时间）

- 2026 年 8 月 16 日（**v3.5.87**）：**权限确认只留给真正需要你做决定的操作，外加 OpenRouter 成为一等公民供应商。**`auto` 模式的判定重写为一条规则：只有可能**改动你的文件、执行任意代码、或触及会话之外**的动作才询问。现在静默执行的包括：注册表中标记为只读的**全部**工具（比之前多 18 个——诊断、任务/记忆查询、文档读取等）、只读 shell **管道**（`git log | head -20`、`ls -la | grep test`——旧实现只要含 `|` 就一律询问）、会话状态类工具（任务/记忆/技能），以及在工作区内**新建**文件。仍然询问：覆盖已有文件、写到工作区外、`.git/hooks` 与 `.github/workflows` 等路径、解释器与构建/测试运行器、任何删除或上传动作、以及子 agent 生成。确认框新增 **`s`**：批准并且**这一条命令或这一个文件**本会话不再问——accept-all 的有作用域替代品（`/permissions clear` 可清空）。shell 判定也从前缀匹配换成了真正的解析，顺带堵掉了一个洞：旧词表会把 `python `、`node `、`find ` 开头的命令直接放行，等于自动执行任意代码。**OpenRouter（PR #179）**：`/model openrouter/<vendor>/<model>` 一把 key 直达 400+ 模型，可用 `@<provider>[/<quantization>]` 固定上游提供商；随之修复了网关模型串带来的四个路由问题（provider 误判、成本记 0、上下文窗口一刀切 128k、量化后缀吃掉 prompt overlay）。[详情](../news.md)
- 2026 年 7 月 30 日（**v3.5.86**）：**输入框「幽灵提示」—— REPL 预测你下一句要输入的内容。** 每轮回答结束后，由**辅助（便宜/快速）模型**草拟你最可能输入的下一句，以浅灰斜体显示在提示符里：按 **Tab**（或 **→**）完整填入，直接打字即覆盖，只按回车不会提交它。草拟在后台线程进行，不阻塞 REPL；任何失败都静默处理（没有辅助模型 / 没有 API key / 供应商故障 → 只是不显示提示）；每条提示只对当前这一个提示符有效，不会残留成过期建议。关闭方式：`/config input_suggest=false` 或 `CHEETAH_SUGGEST=0`。本版本还修复了 **Remote-SSH / WSL / devcontainer 下终端标签标题无法自动配置**的问题：此前它把设置写进服务器端一个 VS Code 永远不会读的文件并从此不再重试，现在会写入窗口真正读取的远端 Machine 设置。本版本也是首个包含 7 月 11 日（终端标签标题 + Anthropic 提示缓存修复）与 7 月 20 日（`tool_profile` + bounded-I/O 修复）改动的正式版本。[详情](../news.md)
- 2026 年 7 月 9 日：**官方 Docker 镜像 + 一条命令发布。** Docker Hub 上提供预构建镜像（`docker pull chauncygu/cheetahclaws`），无需克隆即可运行 Web UI；修复了首次运行时的 `PermissionError`，方法是预先创建由非 root 用户所有的 `.cheetahclaws`/`workspace` 目录，使 compose 的 `image` 可通过 `CHEETAH_IMAGE` 覆盖，并新增 `scripts/docker-publish.sh`（自动读取版本，支持多/单架构）。新增文档章节：**从 Docker Hub 拉取** 与 **交互式设置 / CLI 模式**。[详情](../news.md)
- 2026 年 7 月 8 日：新增 **`/workspace`** 命令，用于管理 `~/.cheetahclaws/workspaces` 下的隔离工作目录（`list`/`switch`/`default`/`create`/`delete`）（PR #162）；启动时自动切换现为通过 `workspace_auto` **可选开启**（默认关闭，因此在项目目录中启动的行为保持不变），且 `default` 现在是一个独立于「最近使用」的固定键。[详情](../news.md)
- 2026 年 7 月 6 日（**v3.5.84**）：**`/image` 现在会用本地 OCR 文本丰富提示词**，让即使是非视觉模型也能处理剪贴板截图（错误转储、代码、表格）；仅在安装了 `pytesseract`/`tesseract` 时运行，并可通过 `CHEETAHCLAWS_IMAGE_OCR=0` 完全关闭。[详情](../news.md)
- 2026 年 6 月 28 日：新增 **`accept-edits`** 权限模式（自动执行文件编辑，但对未在允许列表中的 Bash 仍会询问）—— 介于 `auto` 与 `accept-all` 之间的折中方案；同时在 `/permissions` 中暴露既有的 `plan` 模式，并修正了提示中对 `auto` 的误导性描述。[详情](../news.md)
- 2026 年 6 月 28 日：**记忆陈旧度**现在锚定于 `last_verified` 日期而非文件 mtime，因此读取一条记忆无法伪造刷新一条陈旧记忆（PR #150）；新的 **`MemoryVerify`** 工具是唯一能重置该计时的方式，提示会告诉 agent 在重新核对后调用它，注入的记忆清单会按已验证的新近度排序。[详情](../news.md)
- 2026 年 6 月 23 日（**v3.5.83**）：文档精简（README 新闻 → 每条一行，Atlas 59 模型列表 → usage.md，FAQ 缩减），并在 `desktop/` 下新增原生**桌面应用**（封装 Web UI 的 Electron 外壳）；版本字符串格式统一为 `v3.5.x`。[详情](../news.md)
- 2026 年 6 月 16 日：所有内部模块现在都归于单一的 `cheetahclaws` 包下（`from cheetahclaws import kernel`），消除了启动时的 `sys.path` 名称冲突崩溃 —— 仅当你直接导入内部模块时才会有破坏性影响；完整测试套件全绿（2449 通过）。[详情](../news.md)
- 2026 年 6 月 6 日（**v3.5.82**）：macOS 安装现在能可靠地将 `cheetahclaws` 加入 PATH，并且以文本形式发出工具调用的本地 Ollama 模型现在会真正执行它们（来自 #131 的两处修复）。[详情](../news.md)
- 2026 年 6 月 5 日：用户可控的 token/成本预算 —— `/budget $5` / `/budget daily $20` 可限制每个会话或每天的花费，在每次模型调用前强制执行。[详情](../news.md)
- 2026 年 6 月 5 日：自适应 Markdown 流式输出通过为每台设备自动选择一个分层，使实时输出在每台设备上都保持正确；同时新增可视化的 `/context` 网格，以及 `deepseek-v4-flash` 的 1M 上下文。[详情](../news.md)


更多新闻请见[这里](../news.md)。

---

## 赞助

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws：**快速**且**易于使用**的 Python 原生 Agent Harness 基础设施，**支持任意模型**，如 Claude、GPT、Gemini、Kimi、Qwen、智谱、DeepSeek、MiniMax，以及通过 Ollama 或任何 OpenAI 兼容端点接入的本地开源模型。

---

## 目录
  * [为什么选择 CheetahClaws](#为什么选择-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [功能特性](#功能特性)
  * [支持的模型](#支持的模型)
  * [安装](#安装)
  * [用法：闭源 API 模型](#用法闭源-api-模型)
  * [用法：开源模型（本地）](#用法开源模型本地)
  * [模型名称格式](#模型名称格式)
  * [交易 Agent](#交易-agent)
  * [Web UI](#web-ui)
  * [文档](#文档)（涵盖所有功能的指南）
  * [贡献](#贡献) · [FAQ](#faq) · [引用](#引用)


### 演示

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>在终端中执行任务</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web UI：浏览器聊天 —— 侧边栏、工具卡片、审批提示、Markdown 流式输出</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>自主交易 agent</i></sub></div>

> 更多动画演示（代码审查、`/research`、`/brainstorm`、`/lab`、Telegram/微信/Slack 桥接）见 [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/)。

---

## 为什么选择 CheetahClaws

Claude Code 是一款强大的、生产级的 AI 编码助手 —— 但它的源码是一个编译后约 12 MB 的 TypeScript/Node 打包文件（约 1,300 个文件，约 28.3 万行），与 Anthropic API 紧密耦合，难以修改，并且无法针对本地或替代模型运行。

**CheetahClaws** 用约 9 万行可读的 Python 重新实现了相同的核心循环 —— 保留你需要的，去掉你不需要的，并加入多提供商 + 本地模型支持。完整对比：[docs/guides/comparison.md](../guides/comparison.md)。

| 维度 | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| 语言 | TypeScript + React/Ink | Python 3.8+ |
| 源文件数 / 代码行数 | 约 1,332 个文件 / 约 28.3 万 | 约 315 个文件 / 约 9 万（核心；含测试约 12.7 万） |
| 内置工具数 / 命令数 | 44+ / 88 | 27 / 50+ |
| 模型提供商 | 仅 Anthropic | 8+（Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …） |
| 本地模型 | 否 | 是 —— Ollama、LM Studio、vLLM，任意 OpenAI 兼容端点 |
| 构建步骤 | 有（Bun + esbuild） | 无 —— `python cheetahclaws.py` |
| 可扩展性 | 封闭（编译期） | 开放 —— 运行时 `register_tool()`、Markdown 技能、git 插件、MCP |
| 语音输入 | 专有 WebSocket（OAuth） | 本地 Whisper / OpenAI —— 可离线工作 |

**Claude Code 的优势：** 更丰富的 React/Ink UI、更多内置工具、企业功能（MDM、团队权限同步、OAuth/keychain）、AI 驱动的记忆提取、单一二进制的生产级可靠性。

**CheetahClaws 的优势：** 任意模型切换（`--model`/`/model`，无需重新编译），包括完整的本地/离线支持；单文件中可读的 agent 循环（`agent.py`，约 740 行）；零构建；运行时工具注册 + MCP + git 插件 + Markdown 技能；任务依赖图（`blocks`/`blocked_by`）；两层上下文压缩；离线语音；云端会话同步；桥接 Telegram/微信/Slack/QQ。

**适用人群：** 想要本地/非 Anthropic 编码助手的开发者、研究 agent 型助手工作原理的研究人员，以及需要一个可魔改基线且不想要 Node.js 构建链的团队。

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) 是另一款流行的开源助手（TypeScript/Node）。二者**主要目标不同** —— OpenClaw 是横跨各类消息渠道的个人生活助手；CheetahClaws 则是开发者/编码工具。

| 维度 | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| 代码行数 | 约 24.5 万（约 10,349 个文件） | 约 9 万核心（约 315 个文件） |
| 主要侧重 | 横跨各渠道的个人助手 | AI 编码助手 / 开发工具 |
| 架构 | 常驻的 Gateway 守护进程 + 应用 | 零安装的终端 REPL |
| 消息渠道 | 20+（WhatsApp · Signal · iMessage · Discord · Matrix · …） | 终端 + Telegram · 微信 · Slack · QQ 桥接 |
| 本地 / 离线模型 | 有限 | 完整 —— Ollama · vLLM · LM Studio · 任意 OpenAI 兼容 |
| 代码编辑工具 | 浏览器控制、Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| 移动端 / Live Canvas | 是（菜单栏 + iOS/Android，A2UI） | — |
| MCP 支持 | — | 是（stdio/SSE/HTTP） |
| 可魔改性 | 24.5 万行，较难修改 | 约 9 万行 —— agent 循环在单个文件中 |

| 如果你想要… | 使用 |
|---|---|
| 一款运行在 WhatsApp/Signal/Discord 上、以移动端为先、带浏览器自动化 + Canvas 的个人助手 | **OpenClaw** |
| 一款在终端中的 AI 编码助手，完整的离线/本地模型、多提供商切换、源码一下午即可读完 | **CheetahClaws** |

> 完整对比 —— 双方各自的优势 + 关键设计差异（agent 循环、工具注册、上下文压缩、记忆）：[docs/guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw)。

---

## 功能特性

| 功能 | 详情 |
|---|---|
| 多提供商 | Anthropic · OpenAI · Gemini · Kimi · Qwen · 智谱 · DeepSeek · MiniMax · Ollama · LM Studio · 自定义端点 |
| Agent 循环 | 流式 API + 自动工具使用循环；整个循环都在 `agent.py` 中 |
| 28 个内置工具 | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *（MCP + 插件工具会自动加入）* |
| MCP 集成 | 连接任意 MCP 服务器（stdio/SSE/HTTP）；工具自动注册 —— 参见[扩展指南](../guides/extensions.md) |
| 插件系统 | 从 git URL 或本地路径安装/启用/更新插件；多作用域；推荐引擎 |
| 任务管理 | `TaskCreate/Update/Get/List`，顺序 ID，依赖边，持久化到 `.cheetahclaws/tasks.json` |
| 上下文压缩 | 四个协同层 —— 动态 `max_tokens` 上限、按模型的上下文窗口注册表、在 70% 时的两层裁剪 + AI 摘要，以及对超大工具输出的自动 fanout。[详情](../guides/reference.md) |
| 持久记忆 | 双作用域（用户 + 项目）、4 种类型、置信度/来源元数据、冲突检测、按新近度加权的搜索、`/memory consolidate`。基于验证锚定的陈旧度 —— 新鲜度追踪 `last_verified` 日期（而非文件 mtime），因此读取一条记忆无法伪造刷新它；只有 `MemoryVerify` 能重置该计时。[详情](../guides/features.md) |
| 多 Agent | 派生有类型的子 agent（coder/reviewer/researcher/…）、git-worktree 隔离、后台模式 |
| 权限系统 | 只有可能改动你的文件、执行任意代码、或触及会话之外的动作才会询问 —— 所有只读工具、只读 shell 管道（`git log \| head`）、以及在工作区内新建文件都静默执行。在确认框按 `s` 可将**这一条命令或这一个文件**授权到本会话结束（accept-all 的有作用域替代品，`/permissions clear` 清空）。模式：`auto` / `accept-edits` / `accept-all` / `manual` / `plan`；硬性拒绝列表在所有模式下都会阻止会毁坏主机的命令。[详情](../guides/security.md#what-runs-without-asking-auto-mode) |
| 检查点与 plan 模式 | 每一轮自动快照对话 + 文件（`/checkpoint`、`/rewind`）；`/plan` 只读分析模式 |
| 斜杠命令与主题 | 50+ 个带 Tab 补全的斜杠命令；`/theme` 提供 15 套精选配色 |
| 下一句输入预测（幽灵文字） | 每轮结束后由辅助（便宜）模型草拟你最可能输入的下一句，浅色显示在提示符里 —— **Tab**（或 **→**）完整填入，直接打字即忽略。后台草拟，不阻塞 REPL，失败静默。可通过 `/config input_suggest=false` 或 `CHEETAH_SUGGEST=0` 关闭。[详情](../guides/reference.md#next-prompt-ghost-text) |
| Brainstorm → Worker | `/brainstorm` 运行一场 N 角色辩论 → `todo_list.txt`；`/worker` 自动实现待办任务 |
| SSJ 开发者模式 | `/ssj` —— 持久化的强力菜单，串联 Brainstorm、Worker、Review、Trading、Agent、Video/TTS、Monitor 等 |
| 交易 agent | `/trading` 多 agent 分析、回测、模拟盘校准、MV 组合。[指南](../guides/trading.md) |
| Monitor | `/monitor` 按计划订阅 AI 监测的主题（arxiv / 股票 / 加密 / 新闻 / 自定义），将报告推送到桥接/控制台 |
| Research（多来源） | `/research` 扇出到 **20 个来源**，带注意力热度表、实体提取、趋势迷你图、对比模式。[指南](../guides/research.md) |
| 自主 agent | `/agent` 从 Markdown 模板运行后台循环；迭代摘要通过桥接推送；停滞停止保护 |
| 桥接 + 远程控制 | Telegram · 微信 · Slack · QQ —— 聊天往返、斜杠透传、每桥接的作业队列（`!jobs`/`!retry`/`!cancel`）。[指南](../guides/bridges.md) |
| 语音 / 视觉 / 视频 / TTS | 离线 Whisper `/voice`；`/image` 剪贴板视觉（本地 + 云端）；`/video` + `/tts` 内容工厂。[指南](../guides/voice-and-video.md) |
| Web UI | `--web` —— 多用户浏览器聊天 + PTY 终端。[指南](../guides/web-ui.md) |
| 更多 | Tmux 集成 · `!cmd` shell 转义 · 主动监测 · 3×Ctrl+C 强制退出 · 会话持久化 · `/cloudsave` GitHub-Gist 同步 · 成本追踪 · `--print` 非交互模式 |

> **完整功能参考** —— 上表每一行的完整细节（上下文压缩层、自动 fanout、15 套主题、完整的 Trading/Research/Agents 详述……）：[docs/guides/features.md](../guides/features.md)。

---

## 支持的模型

### 闭源（API）

| 提供商 | 示例模型 | 上下文 | API Key 环境变量 |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **阿里巴巴 (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **智谱 (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash`（免费层） | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ 模型，一把 key)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | 视情况而定 | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ 模型，一把 key)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | 视情况而定 | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(通过 litellm)_ | `litellm/<provider>/<model>` | 视情况而定 | 特定于提供商 |

> **`openrouter/` 网关：** 一把 key 覆盖跨厂商的 400+ 模型。模型 ID 保留 OpenRouter 上游的 `<vendor>/<model>` 路径，因此调用是双层前缀的：`openrouter/deepseek/deepseek-v4-flash`。若要指定由哪个上游提供商（及量化精度）来服务该请求，在模型后追加 `@<provider>[/<quantization>]` —— `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` —— 它会作为 OpenRouter 的 `provider` 请求体对象发送，而不是拼进模型 ID。参见 [usage.md](../guides/usage.md#openrouter-400-models-one-key)。

> **`requesty/` 网关：** 用法相同：`requesty/` 之后的全部内容作为模型 ID 发送，可以是目录中的 `<vendor>/<model>` 路径（`requesty/openai/gpt-4o-mini`），也可以是托管策略 ID（`requesty/claude-sonnet-4-6`）。以 `@eu` 结尾的托管策略 ID（`requesty/gpt-5-mini@eu`）只经由欧盟提供商路由。参见 [usage.md](../guides/usage.md#requesty-700-models-one-key)。

> **`litellm/` 适配器：** 在单一 SDK 后路由到 100+ 提供商 —— 主要用于认证方式较棘手的上游（Bedrock SigV4、Azure 部署路由、Vertex 服务账号 JWT）。对于普通的 OpenAI 形态端点，优先使用零依赖的 `custom/` 适配器。用 `pip install ".[litellm]"` 安装。参见 [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider)。

### 开源（通过 Ollama 本地运行）

| 模型 | 规模 | 强项 | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **最适合编码** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | 通用 | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | 推理、数学 | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | 快速 / 强 MoE | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | 推理 / 开源 / 代码 | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **视觉** | `ollama pull llava` |

> **工具调用**需要一个支持函数调用的模型 —— 推荐：`qwen2.5-coder`、`llama3.3`、`mistral`、`phi4`。以**文本**形式发出工具调用（`<tool_call>…</tool_call>`、`[TOOL_CALLS]…`）而非使用 Ollama 结构化字段的模型会被自动恢复，因此它们开箱即可执行工具，而不只是空谈。推理模型（`deepseek-r1`、`qwen3`、`gemma4`）会流式输出原生的 `<think>` 块；用 `/verbose` + `/thinking` 启用。

---

## 安装

```bash
pip install cheetahclaws
```

可在 **Linux、macOS、WSL2 和 Android (Termux)** 上运行（Python 3.10+）。首次运行会引导你完成提供商 + API key 设置；随时可用 `cheetahclaws --setup` 重新运行。

> **Windows：** 不支持原生 Windows —— 请使用 [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)。**Android/Termux：** `pkg install python git && pip install cheetahclaws`。

### 其他方式：一行安装脚本

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

安装后，重新加载你的 shell，使 `cheetahclaws` 位于 PATH 上：

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### 其他方式：用 `pip` 从源码安装

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### 可选附加组件

```bash
pip install ".[voice]"      # voice input (sounddevice + faster-whisper)
pip install ".[vision]"     # clipboard image capture (Pillow)
pip install ".[autosuggest]"# typing-time slash autosuggest (prompt_toolkit)
pip install ".[browser]"    # headless browser (playwright); then: playwright install chromium
pip install ".[files]"      # PDF + Excel reading (pymupdf, openpyxl)
pip install ".[ocr]"        # image OCR (pytesseract)
pip install ".[trading]"    # trading agent (yfinance, rank-bm25)
pip install ".[qq]"         # QQ bot bridge (qq-botpy)
pip install ".[litellm]"    # AWS Bedrock / Azure / Vertex auth via litellm
pip install ".[all]"        # everything above
```

### 其他方式：用 `uv` 安装

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### 其他方式：直接从源码运行（无需安装）

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## 用法：闭源 API 模型

每个云提供商都遵循相同的模式 —— 导出其 API key（环境变量名见[支持的模型](#闭源api)表格），然后选择一个模型：

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

各提供商的获取 key 页面：[Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [智谱](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat)。

**AWS Bedrock / Azure / Vertex** 使用 `litellm/<provider>/<model>` 形式（`pip install ".[litellm]"`）—— 完整的环境变量配方见 [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider)。

> **完整的分提供商指南** —— 每个提供商的获取 key 页面 + 示例模型命令，外加 Bedrock/Azure/Vertex 环境变量配方：[docs/guides/usage.md](../guides/usage.md)。

---

## 用法：开源模型（本地）

### Ollama（推荐）

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

下载 [LM Studio](https://lmstudio.ai)，获取一个 GGUF 模型，启动其 **Local Server**（端口 1234），然后：

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / 自托管的 OpenAI 兼容服务器

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

`custom/` 之后的名称必须与服务器的 `--served-model-name` 匹配。对于 Web UI，`--web --model custom/<name>` 会在服务器启动前持久化该模型。远程服务器？将 `CUSTOM_BASE_URL` 指向其 IP。

> **完整的本地模型指南** —— Ollama 分步说明、LM Studio、vLLM + Web UI：[docs/guides/usage.md](../guides/usage.md#usage-open-source-models-local)。

### Atlas Cloud（托管，OpenAI 兼容）

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** 通过零依赖的 `custom/` 适配器，在单一 OpenAI 兼容端点后提供 DeepSeek、Qwen、GLM、Kimi、MiniMax 等模型：

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> 任意 Atlas 聊天模型 id 都以同样的方式工作 —— **全部 59 个模型的完整列表：** [docs/guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible)。

---

## 模型名称格式

接受三种等价形式：

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**按前缀自动检测：** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama。

---

## 交易 Agent

内置的 AI 交易分析 + 回测模块（`pip install "cheetahclaws[trading]"`）。

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4 种策略（`dual_ma`、`rsi_mean_reversion`、`bollinger_breakout`、`macd_crossover`），对过往情形的 BM25 记忆，美股/港股/A 股 + 加密市场，并带无需 API key 的数据回退。通过 `/ssj` → **Trading** 进入引导式子菜单。

> **完整指南：** [docs/guides/trading.md](../guides/trading.md)

---

## Web UI

一个生产就绪的浏览器界面 —— 真实用户账户（bcrypt + JWT）、SQLite 支持的历史记录、运维端点 —— 由 Python 标准库 + 十个原生 JS 模块提供服务（无 Node.js / React / 构建步骤）。

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

打开 `http://localhost:<port>/chat` —— 第一个账户成为管理员。包含流式聊天（WS）+ SSE 斜杠命令、带文件夹/搜索/Markdown 导出的持久会话、工具卡片、内联权限审批、设置面板、浅色/深色/系统主题，以及 `/health` + `/metrics` 端点。完整的 xterm.js PTY 终端位于 `/`（与 CLI 100% 对等）。

> **完整指南：** [docs/guides/web-ui.md](../guides/web-ui.md) · **Docker / 家庭服务器：** [docs/guides/docker.md](../guides/docker.md) · **原生桌面应用：** [desktop/README.md](../../desktop/README.md)

---

## 文档

详细指南位于 [`docs/guides/`](../guides/)，以保持本 README 聚焦：

| 指南 | 内容 |
|---|---|
| [**功能特性（完整）**](../guides/features.md) | 完整功能表 —— 每一行的完整细节（上下文压缩、自动 fanout、主题、Trading/Research/Agents 详述） |
| [**用法（所有提供商）**](../guides/usage.md) | 分提供商设置 + 示例命令：Anthropic/OpenAI/Gemini/Kimi/Qwen/智谱/DeepSeek/MiniMax/litellm，以及本地 Ollama/LM Studio/vLLM |
| [**Web UI**](../guides/web-ui.md) | 聊天 UI、PTY 终端、API 端点、设置、认证、SSE 流式 |
| [**桌面应用**](../../desktop/README.md) | 封装本地 Web UI 的原生窗口外壳（Electron）；构建自包含的 `.dmg`/`.exe`/`.AppImage` |
| [**Docker / 家庭服务器**](../guides/docker.md) | Dockerfile + compose：一个容器中的 Web UI + 桥接、宿主 Ollama、工作区挂载 |
| [**参考**](../guides/reference.md) | CLI、50+ 命令、33 个内置工具、会话搜索、错误分类、工具缓存 |
| [**扩展**](../guides/extensions.md) | 记忆、技能、子 Agent、MCP 服务器、插件、Monitor、自主 Agent |
| [**桥接**](../guides/bridges.md) | Telegram、微信、Slack、QQ 设置 + 从手机远程控制 |
| [**安全与环境变量**](../guides/security.md) | 威胁模型、`CHEETAHCLAWS_*` 变量、bot token 处理、Bash 拒绝列表、文件系统沙箱、CSRF |
| [**语音与视频**](../guides/voice-and-video.md) | 离线 Whisper 语音输入、视频工厂、TTS 工厂 |
| [**交易**](../guides/trading.md) | 多 agent 分析、回测、BM25 记忆、数据回退、SSJ 集成 |
| [**进阶**](../guides/advanced.md) | Brainstorm、SSJ、Tmux、主动监测、检查点、plan 模式、会话、云同步 |
| [**对比**](../guides/comparison.md) | 相对 Claude Code 与 OpenClaw 的完整定位 —— 一览表、双方各自的优势、关键设计差异 |
| [**Recipes**](../guides/recipes.md) | 12 个分步示例：代码审查、远程控制、研究、修 bug、浏览、邮件、PDF/Excel |
| [**FAQ**](../guides/faq.md) | 完整 FAQ（MCP、模型/提供商、CLI/脚本、语音） |
| [**插件开发**](../guides/plugin-authoring.md) · [示例](../../examples/example-plugin/) | 构建插件：工具、命令、技能、MCP；入门模板 |
| [**研究实验室**](../guides/research-lab.md) | `/lab start <topic>` —— 带沙箱实验的自主多 agent 论文写作 |
| [**Agent OS**](../agent-os.md) · [RFC 索引](../RFC/) | `kernel/` 层 + 所有设计说明（RFC 0001-0032） |
| [**贡献**](../../CONTRIBUTING.md) | 项目结构、架构指南、PR 检查清单 |

---

## 快速参考

```
cheetahclaws [OPTIONS] [PROMPT]

  -p, --print          Non-interactive: run prompt and exit
  -m, --model MODEL    Override model (e.g. gpt-4o, ollama/llama3.3)
  --accept-all         Auto-approve all operations (no permission prompts)
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
cheetahclaws --web --port 8008 --no-auth              # browser chat + terminal
```

全部 50+ 个斜杠命令、工具和配置选项见[参考指南](../guides/reference.md)。

---

## 贡献

我们欢迎贡献！架构、约定和 PR 检查清单见[贡献指南](../../CONTRIBUTING.md)。

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

要构建插件？参见[插件开发指南](../guides/plugin-authoring.md)和[示例模板](../../examples/example-plugin/)。

---

## FAQ

几个常见问题 —— **完整 FAQ** 见 [docs/guides/faq.md](../guides/faq.md)。

**问：如何添加 MCP 服务器？**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**问：工具调用在我的本地 Ollama 模型上不起作用（它只是不停地描述它要做什么，而不去做）。**
CheetahClaws 现在会自动恢复本地模型以**文本**形式（`<tool_call>…</tool_call>`、`[TOOL_CALLS]…`）而非 Ollama 结构化字段发出的工具调用，因此大多数支持函数调用的模型开箱即可执行工具。为获得最佳可靠性，请使用支持工具调用的模型 —— `qwen2.5-coder`、`llama3.3`、`mistral` 或 `phi4`。小模型在 agent 型工具使用方面也弱于云端模型，因此预期它们需要更清晰、更具体的提示。

**问：在 macOS 上安装后，出现 `cheetahclaws: command not found`，并且没有创建 `~/.zshrc`。**
先重新加载你的 shell：`source ~/.zshrc`（zsh）或 `source ~/.bash_profile`（bash）。安装程序会在 `~/.zshrc` 缺失时创建它，将二进制文件符号链接到 `~/.local/bin`，并将其加入 PATH。如果你安装的是旧版本，可以重新运行安装程序，或自行添加这一行：`echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`。

更多问题 —— 远程 vLLM、API 成本（`/cost`）、每个会话多个 key、跨项目的默认模型、管道输入、语音设置、乱码修复 —— 都在 [docs/guides/faq.md](../guides/faq.md) 中解答。

---

## 引用
如果你觉得本仓库有用，请引用这项研究
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


## 感谢所有贡献者：

<!-- contributors:start -->

<a href="https://github.com/chauncygu"><img src="https://avatars.githubusercontent.com/u/27274029?v=4&s=48" width="48" height="48" alt="chauncygu"/></a>
<a href="https://github.com/KevRojo"><img src="https://avatars.githubusercontent.com/u/9065636?v=4&s=48" width="48" height="48" alt="KevRojo"/></a>
<a href="https://github.com/mxh1999"><img src="https://avatars.githubusercontent.com/u/30319236?v=4&s=48" width="48" height="48" alt="mxh1999"/></a>
<a href="https://github.com/seetvn"><img src="https://avatars.githubusercontent.com/u/100040536?v=4&s=48" width="48" height="48" alt="seetvn"/></a>
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
