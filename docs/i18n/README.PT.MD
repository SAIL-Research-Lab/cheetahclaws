[English](../../README.md) | [中文](README.CN.MD) | [한국어](README.KO.MD) | [日本語](README.JP.MD) | [Français](README.FR.MD) | [Deutsch](README.DE.MD) | [Español](README.ES.MD) | Português

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: Uma infraestrutura de harness de agentes rápida e fácil de usar para sistemas de IA de longo horizonte, multimodelo e que usam ferramentas</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">Site</a>
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


### Instalação rápida

```bash
pip install cheetahclaws
```

Depois é só executar:

```bash
cheetahclaws        # comece a conversar!
```

Outros métodos de instalação: [script de instalação de uma linha](#alternativa-script-de-instalação-de-uma-linha) | [instalar a partir do código-fonte](#alternativa-instalar-com-pip-a-partir-do-código-fonte) | [instalar com uv](#alternativa-instalar-com-uv) | [executar a partir do código-fonte](#alternativa-executar-diretamente-a-partir-do-código-fonte-sem-instalação) | [detalhes completos de instalação](#instalação)

> 🖥️ **Prefere um aplicativo nativo?** Uma versão desktop (Electron) empacota toda a interface de chat em uma janela — sem necessidade de terminal. Veja [`desktop/`](../../desktop/README.md).

## 🔥🔥🔥 Novidades (Horário do Pacífico)

- 9 de julho de 2026: **Imagem Docker oficial + publicação com um comando.** Imagem pré-compilada no Docker Hub (`docker pull chauncygu/cheetahclaws`) para você executar a Web UI sem clonar; corrige um `PermissionError` na primeira execução ao pré-criar os diretórios `.cheetahclaws`/`workspace` de propriedade do usuário não-root, torna o `image` do compose sobrescrevível via `CHEETAH_IMAGE` e adiciona `scripts/docker-publish.sh` (lê a versão automaticamente, multi/single-arch). Novas seções da documentação: **Pull do Docker Hub** e **Configuração interativa / modo CLI**. [Detalhes](../news.md)
- 8 de julho de 2026: O novo comando **`/workspace`** gerencia diretórios de trabalho isolados em `~/.cheetahclaws/workspaces` (`list`/`switch`/`default`/`create`/`delete`) (PR #162); a troca automática na inicialização é **opt-in** via `workspace_auto` (desligada por padrão, então iniciar em um diretório de projeto permanece inalterado), e `default` agora é uma chave fixa separada da última usada. [Detalhes](../news.md)
- 6 de julho de 2026 (**v3.5.84**): **`/image` agora enriquece o prompt com texto de OCR local** para que até modelos sem visão possam agir sobre capturas de tela da área de transferência (dumps de erro, código, tabelas); só é executado quando `pytesseract`/`tesseract` estão instalados e é totalmente desativável via `CHEETAHCLAWS_IMAGE_OCR=0`. [Detalhes](../news.md)
- 28 de junho de 2026: Novo modo de permissão **`accept-edits`** (executa edições de arquivo automaticamente, ainda pergunta antes de comandos Bash fora da allow-list) — o meio-termo entre `auto` e `accept-all`; também expõe o modo `plan` existente em `/permissions` e corrige a descrição enganosa de `auto` no prompt. [Detalhes](../news.md)
- 28 de junho de 2026: A **obsolescência de memória** agora se ancora em uma data `last_verified` em vez do mtime do arquivo, de modo que ler uma memória não pode falsamente atualizar uma que esteja desatualizada (PR #150); a nova ferramenta **`MemoryVerify`** é a única coisa que reinicia o relógio, o prompt instrui o agente a chamá-la após reverificar, e o manifesto de memória injetado é ordenado pela recência verificada. [Detalhes](../news.md)
- 23 de junho de 2026 (**v3.5.83**): Documentação enxugada (novidades do README → uma linha cada, lista de 59 modelos da Atlas → usage.md, FAQ reduzida) e um **aplicativo desktop** nativo (shell Electron envolvendo a web UI) adicionado em `desktop/`; formato da string de versão unificado para `v3.5.x`. [Detalhes](../news.md)
- 16 de junho de 2026: Todos os módulos internos agora vivem sob um único pacote `cheetahclaws` (`from cheetahclaws import kernel`), eliminando falhas por colisão de nomes de `sys.path` na inicialização — só quebra se você importar internos diretamente; suíte completa verde (2449 aprovados). [Detalhes](../news.md)
- 6 de junho de 2026 (**v3.5.82**): A instalação no macOS agora coloca `cheetahclaws` no PATH de forma confiável, e modelos Ollama locais que emitem chamadas de ferramenta como texto agora realmente as executam (duas correções do #131). [Detalhes](../news.md)
- 5 de junho de 2026: Orçamentos de tokens/custo controláveis pelo usuário — `/budget $5` / `/budget daily $20` limitam o gasto por sessão ou por dia, aplicados antes de cada chamada ao modelo. [Detalhes](../news.md)
- 5 de junho de 2026: O streaming Markdown adaptativo mantém a saída ao vivo correta em todos os dispositivos ao selecionar automaticamente um nível por dispositivo; também adiciona uma grade visual `/context` e contexto de 1M para `deepseek-v4-flash`. [Detalhes](../news.md)


Para mais novidades, veja [aqui](../news.md).

---

## Patrocinador

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **Uma infraestrutura de harness de agentes** nativa em Python, **rápida** e **fácil de usar**, **compatível com qualquer modelo**, como Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax e modelos open-source locais via Ollama ou qualquer endpoint compatível com OpenAI.

---

## Conteúdo
  * [Por que CheetahClaws](#por-que-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [Funcionalidades](#funcionalidades)
  * [Modelos suportados](#modelos-suportados)
  * [Instalação](#instalação)
  * [Uso: modelos de API de código fechado](#uso-modelos-de-api-de-código-fechado)
  * [Uso: modelos open-source (locais)](#uso-modelos-open-source-locais)
  * [Formato do nome do modelo](#formato-do-nome-do-modelo)
  * [Agente de trading](#agente-de-trading)
  * [Web UI](#web-ui)
  * [Documentação](#documentação) (guias para todas as funcionalidades)
  * [Contribuindo](#contribuindo) · [FAQ](#faq) · [Citação](#citação)


### Demonstrações

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>Execução de tarefas no terminal</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web UI: chat no navegador — barra lateral, cartões de ferramentas, prompts de aprovação, streaming Markdown</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Agente de trading autônomo</i></sub></div>

> Mais demonstrações animadas (revisão de código, `/research`, `/brainstorm`, `/lab`, pontes Telegram/WeChat/Slack) estão em [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/).

---

## Por que CheetahClaws

O Claude Code é um assistente de IA para codificação poderoso e de nível de produção — mas seu código-fonte é um bundle TypeScript/Node compilado de ~12 MB (~1.300 arquivos, ~283 mil linhas), fortemente acoplado à API da Anthropic, difícil de modificar e impossível de rodar contra um modelo local ou alternativo.

**CheetahClaws** reimplementa o mesmo loop central em ~90 mil linhas de Python legível — mantendo o que você precisa, descartando o que não precisa e adicionando suporte multiprovedor + modelos locais. Comparação completa: [../guides/comparison.md](../guides/comparison.md).

| Dimensão | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Linguagem | TypeScript + React/Ink | Python 3.8+ |
| Arquivos-fonte / LoC | ~1.332 arquivos / ~283 mil | ~315 arquivos / ~90 mil (núcleo; ~127 mil com testes) |
| Ferramentas / comandos integrados | 44+ / 88 | 27 / 50+ |
| Provedores de modelo | Apenas Anthropic | 8+ (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| Modelos locais | Não | Sim — Ollama, LM Studio, vLLM, qualquer endpoint compatível com OpenAI |
| Etapa de build | Sim (Bun + esbuild) | Não — `python cheetahclaws.py` |
| Extensibilidade | Fechada (em tempo de compilação) | Aberta — `register_tool()` em tempo de execução, skills em Markdown, plugins git, MCP |
| Entrada de voz | WebSocket proprietário (OAuth) | Whisper local / OpenAI — funciona offline |

**Onde o Claude Code vence:** UI React/Ink mais rica, mais ferramentas integradas, recursos empresariais (MDM, sincronização de permissões de equipe, OAuth/keychain), extração de memória guiada por IA, confiabilidade de produção em binário único.

**Onde o CheetahClaws vence:** troca de qualquer modelo (`--model`/`/model`, sem recompilação) incluindo suporte completo local/offline; um loop de agente legível em um único arquivo (`agent.py`, ~740 linhas); zero build; registro de ferramentas em tempo de execução + MCP + plugins git + skills em Markdown; grafo de dependências de tarefas (`blocks`/`blocked_by`); compressão de contexto em duas camadas; voz offline; sincronização de sessões na nuvem; pontes para Telegram/WeChat/Slack/QQ.

**Para quem é:** desenvolvedores que querem um assistente de codificação local/não-Anthropic, pesquisadores que estudam como funcionam os assistentes agentivos e equipes que precisam de uma base hackeável — sem uma cadeia de build Node.js.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) é outro assistente open-source popular (TypeScript/Node). Os dois têm **objetivos principais diferentes** — o OpenClaw é um assistente de vida pessoal em canais de mensagens; o CheetahClaws é uma ferramenta de desenvolvimento/codificação.

| Dimensão | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Linhas de código | ~245 mil (~10.349 arquivos) | ~90 mil no núcleo (~315 arquivos) |
| Foco principal | Assistente pessoal em vários canais | Assistente de codificação por IA / ferramenta de dev |
| Arquitetura | Daemon Gateway sempre ativo + apps | REPL de terminal sem instalação |
| Canais de mensagens | 20+ (WhatsApp · Signal · iMessage · Discord · Matrix · …) | Terminal + pontes Telegram · WeChat · Slack · QQ |
| Modelos locais / offline | Limitado | Completo — Ollama · vLLM · LM Studio · qualquer um compatível com OpenAI |
| Ferramentas de edição de código | Controle de navegador, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| Mobile / Live Canvas | Sim (barra de menu + iOS/Android, A2UI) | — |
| Suporte a MCP | — | Sim (stdio/SSE/HTTP) |
| Hackeabilidade | 245 mil linhas, mais difícil de modificar | ~90 mil linhas — loop de agente em um único arquivo |

| Se você quer… | Use |
|---|---|
| Um assistente pessoal no WhatsApp/Signal/Discord, mobile-first, automação de navegador + Canvas | **OpenClaw** |
| Um assistente de codificação por IA no seu terminal, modelos totalmente offline/locais, troca multiprovedor, código-fonte que você lê em uma tarde | **CheetahClaws** |

> Comparação completa — vitórias dos dois lados + diferenças-chave de design (loop de agente, registro de ferramentas, compressão de contexto, memória): [../guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw).

---

## Funcionalidades

| Funcionalidade | Detalhes |
|---|---|
| Multiprovedor | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · Endpoint personalizado |
| Loop de agente | API de streaming + loop automático de uso de ferramentas; todo o loop está em `agent.py` |
| 28 ferramentas integradas | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(ferramentas MCP + de plugins adicionadas automaticamente)* |
| Integração MCP | Conecte qualquer servidor MCP (stdio/SSE/HTTP); ferramentas registradas automaticamente — veja o [guia de extensões](../guides/extensions.md) |
| Sistema de plugins | Instale/ative/atualize plugins a partir de URLs git ou caminhos locais; multiescopo; motor de recomendação |
| Gerenciamento de tarefas | `TaskCreate/Update/Get/List`, IDs sequenciais, arestas de dependência, persistidos em `.cheetahclaws/tasks.json` |
| Compressão de contexto | Quatro camadas cooperantes — limite dinâmico de `max_tokens`, registro de janela de contexto por modelo, corte em duas camadas + resumo por IA a 70%, e auto-fanout para saídas de ferramenta grandes demais. [Detalhes](../guides/reference.md) |
| Memória persistente | Duplo escopo (usuário + projeto), 4 tipos, metadados de confiança/origem, detecção de conflitos, busca ponderada por recência, `/memory consolidate`. Obsolescência ancorada em verificação — a atualidade rastreia uma data `last_verified` (não o mtime do arquivo), de modo que ler uma memória não pode falsamente atualizá-la; apenas `MemoryVerify` reinicia o relógio. [Detalhes](../guides/features.md) |
| Multiagente | Cria subagentes tipados (coder/reviewer/researcher/…), isolamento por git-worktree, modo em segundo plano |
| Sistema de permissões | Só pergunta em ações que possam alterar seus arquivos, executar código arbitrário ou sair da sessão. Todas as ferramentas somente-leitura, pipelines de shell somente-leitura (`git log \| head`) e a criação de um arquivo **novo** dentro do workspace rodam sem perguntar. Responder `s` concede **aquele comando ou aquele arquivo** pelo resto da sessão — a alternativa delimitada ao accept-all (`/permissions clear` descarta). Modos: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`; uma lista de negação rígida bloqueia comandos destrutivos em todos os modos. [Detalhes](../guides/security.md#what-runs-without-asking-auto-mode) |
| Checkpoints e modo plano | Snapshot automático da conversa + arquivos a cada turno (`/checkpoint`, `/rewind`); modo de análise somente leitura `/plan` |
| Comandos slash e temas | 50+ comandos slash com autocompletar por Tab; `/theme` oferece 15 paletas selecionadas |
| Brainstorm → Worker | `/brainstorm` executa um debate de N personas → `todo_list.txt`; `/worker` implementa automaticamente as tarefas pendentes |
| Modo Desenvolvedor SSJ | `/ssj` — menu de poder persistente encadeando Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor, etc. |
| Agente de trading | `/trading` análise multiagente, backtesting, calibração de paper-trade, portfólios MV. [Guia](../guides/trading.md) |
| Monitor | `/monitor` assina tópicos monitorados por IA em uma agenda (arxiv / ações / cripto / notícias / personalizado), envia relatórios para pontes/console |
| Pesquisa (múltiplas fontes) | `/research` se ramifica em **20 fontes** com tabela de calor de atenção, extração de entidades, sparkline de tendência, modo de comparação. [Guia](../guides/research.md) |
| Agentes autônomos | `/agent` loops em segundo plano a partir de templates Markdown; resumos de iteração enviados via ponte; proteção contra estagnação |
| Pontes + controle remoto | Telegram · WeChat · Slack · QQ — chat de ida e volta, passagem de comandos slash, fila de trabalhos por ponte (`!jobs`/`!retry`/`!cancel`). [Guia](../guides/bridges.md) |
| Voz / Visão / Vídeo / TTS | Whisper offline `/voice`; visão de área de transferência `/image` (local + nuvem); fábricas de conteúdo `/video` + `/tts`. [Guia](../guides/voice-and-video.md) |
| Web UI | `--web` — chat multiusuário no navegador + terminal PTY. [Guia](../guides/web-ui.md) |
| Mais | Integração com Tmux · escape de shell `!cmd` · monitoramento proativo · saída forçada com 3×Ctrl+C · persistência de sessão · sincronização `/cloudsave` via GitHub-Gist · rastreamento de custos · modo não interativo `--print` |

> **Referência completa de funcionalidades** — cada linha acima com todos os detalhes (camadas de compressão de contexto, auto-fanout, 15 temas, os textos completos de Trading/Research/Agents, …): [../guides/features.md](../guides/features.md).

---

## Modelos suportados

### Código fechado (API)

| Provedor | Modelos de exemplo | Contexto | Variável da chave de API |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (nível gratuito) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ modelos, uma única chave)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | varia | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ modelos, uma única chave)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | varia | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(via litellm)_ | `litellm/<provider>/<model>` | varia | específico do provedor |

> **Gateway `openrouter/`:** uma única chave para mais de 400 modelos de vários fornecedores. O ID do modelo mantém o caminho upstream `<vendor>/<model>` do OpenRouter, então a chamada tem prefixo duplo: `openrouter/deepseek/deepseek-v4-flash`. Para fixar qual fornecedor upstream (e qual quantização) atende a requisição, acrescente `@<provider>[/<quantization>]` — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — que é enviado como o objeto `provider` no corpo da requisição, em vez de ser colado ao ID do modelo. Veja [usage.md](../guides/usage.md#openrouter-400-models-one-key).

> **Gateway `requesty/`:** funciona da mesma forma: tudo o que vem depois de `requesty/` é enviado como ID do modelo, seja um caminho de catálogo `<vendor>/<model>` (`requesty/openai/gpt-4o-mini`) ou um ID de política gerenciada (`requesty/claude-sonnet-4-6`). IDs de política gerenciada terminados em `@eu` (`requesty/gpt-5-mini@eu`) passam apenas por provedores da UE. Veja [usage.md](../guides/usage.md#requesty-700-models-one-key).

> **Adaptador `litellm/`:** roteia para mais de 100 provedores por trás de um único SDK — principalmente para upstreams com autenticação complicada (SigV4 do Bedrock, roteamento de deployment do Azure, JWTs de service-account do Vertex). Para endpoints simples no formato OpenAI, prefira o adaptador `custom/` sem dependências. Instale com `pip install ".[litellm]"`. Veja [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

### Open-Source (local via Ollama)

| Modelo | Tamanho | Pontos fortes | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **Melhor para codificação** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | Uso geral | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | Raciocínio, matemática | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | Rápido / MoE forte | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | Raciocínio / aberto / código | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **Visão** | `ollama pull llava` |

> **Chamada de ferramentas** requer um modelo com function-calling — recomendados: `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Modelos que emitem chamadas de ferramenta como **texto** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) em vez do campo estruturado do Ollama são recuperados automaticamente, de modo que executam ferramentas de imediato em vez de apenas falar sobre isso. Modelos de raciocínio (`deepseek-r1`, `qwen3`, `gemma4`) transmitem blocos `<think>` nativos; ative com `/verbose` + `/thinking`.

---

## Instalação

```bash
pip install cheetahclaws
```

Funciona em **Linux, macOS, WSL2 e Android (Termux)** (Python 3.10+). A primeira execução guia você pela configuração de provedor + chave de API; execute novamente a qualquer momento com `cheetahclaws --setup`.

> **Windows:** o Windows nativo não é suportado — use o [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). **Android/Termux:** `pkg install python git && pip install cheetahclaws`.

### Alternativa: script de instalação de uma linha

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

Após a instalação, recarregue seu shell para que `cheetahclaws` esteja no PATH:

```bash
source ~/.zshrc     # macOS
# ou: source ~/.bashrc   # Linux
cheetahclaws        # comece a conversar!
```

### Alternativa: instalar com `pip` a partir do código-fonte

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # depois: cheetahclaws
git pull && pip install --force-reinstall .   # para atualizar
```

#### Extras opcionais

```bash
pip install ".[voice]"      # entrada de voz (sounddevice + faster-whisper)
pip install ".[vision]"     # captura de imagem da área de transferência (Pillow)
pip install ".[autosuggest]"# autossugestão de slash em tempo de digitação (prompt_toolkit)
pip install ".[browser]"    # navegador headless (playwright); depois: playwright install chromium
pip install ".[files]"      # leitura de PDF + Excel (pymupdf, openpyxl)
pip install ".[ocr]"        # OCR de imagem (pytesseract)
pip install ".[trading]"    # agente de trading (yfinance, rank-bm25)
pip install ".[qq]"         # ponte de bot QQ (qq-botpy)
pip install ".[litellm]"    # autenticação AWS Bedrock / Azure / Vertex via litellm
pip install ".[all]"        # tudo acima
```

### Alternativa: instalar com `uv`

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # mínimo: uv tool install .
uv tool install ".[all]" --reinstall   # atualizar   ·   uv tool uninstall cheetahclaws
```

### Alternativa: executar diretamente a partir do código-fonte (sem instalação)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # as mudanças têm efeito imediato
```

---

## Uso: modelos de API de código fechado

Todo provedor de nuvem segue o mesmo padrão — exporte sua chave de API (veja a tabela de [Modelos suportados](#código-fechado-api) para o nome da variável de ambiente) e depois selecione um modelo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # ou OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # modelo padrão
cheetahclaws --model gpt-4o             # escolha qualquer modelo
cheetahclaws --model deepseek-chat --thinking --verbose
```

Páginas para obter a chave de cada provedor: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat).

**AWS Bedrock / Azure / Vertex** usam o formato `litellm/<provider>/<model>` (`pip install ".[litellm]"`) — receitas completas de variáveis de ambiente em [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

> **Guia completo por provedor** — página de obtenção de chave + comandos de modelo de exemplo de cada provedor, além de receitas de variáveis de ambiente para Bedrock/Azure/Vertex: [../guides/usage.md](../guides/usage.md).

---

## Uso: modelos open-source (locais)

### Ollama (recomendado)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # instalar
ollama pull qwen2.5-coder                        # baixar um modelo com tool-calling
ollama serve                                     # http://localhost:11434 (inicia automaticamente no macOS)
cheetahclaws --model ollama/qwen2.5-coder        # executar (use `ollama list` para ver os modelos locais)
```

### LM Studio

Baixe o [LM Studio](https://lmstudio.ai), obtenha um modelo GGUF, inicie seu **Local Server** (porta 1234) e depois:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / servidor auto-hospedado compatível com OpenAI

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # qualquer string não vazia se o servidor não tiver autenticação
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

O nome após `custom/` deve corresponder ao `--served-model-name` do servidor. Para a Web UI, `--web --model custom/<name>` persiste o modelo antes de o servidor iniciar. Servidor remoto? Aponte `CUSTOM_BASE_URL` para o IP dele.

> **Guia completo de modelos locais** — Ollama passo a passo, LM Studio, vLLM + Web UI: [../guides/usage.md](../guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (hospedado, compatível com OpenAI)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** oferece DeepSeek, Qwen, GLM, Kimi, MiniMax e mais por trás de um único endpoint compatível com OpenAI, via o adaptador `custom/` sem dependências:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> Qualquer id de modelo de chat da Atlas funciona da mesma forma — **lista completa de todos os 59 modelos:** [../guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## Formato do nome do modelo

Três formas equivalentes são aceitas:

```bash
cheetahclaws --model gpt-4o                  # 1. detecção automática por prefixo
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**Detecção automática por prefixo:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

---

## Agente de trading

Um módulo integrado de análise de trading + backtesting por IA (`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # pipeline de 5 fases: dados → debate Bull/Bear → Juiz → painel de Risco → decisão do PM
/trading backtest AAPL dual_ma   # backtest de uma estratégia (ou deixe a IA escolher); Sharpe/Sortino/Calmar/drawdown/taxa de acerto
```

4 estratégias (`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), memória BM25 de situações passadas, mercados de EUA/HK/A-share + cripto com fallbacks de dados sem chave de API. Submenu guiado via `/ssj` → **Trading**.

> **Guia completo:** [../guides/trading.md](../guides/trading.md)

---

## Web UI

Uma interface de navegador pronta para produção — contas de usuário reais (bcrypt + JWT), histórico com backing em SQLite, endpoints de ops — servida pela biblioteca padrão do Python + dez módulos vanilla-JS (sem Node.js / React / etapa de build).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # escolhe automaticamente uma porta livre (tenta 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # vincular explicitamente / abrir para a LAN
cheetahclaws --web --no-auth        # pular login (apenas dev em localhost)
```

Abra `http://localhost:<port>/chat` — a primeira conta se torna admin. Inclui chat com streaming (WS) + comandos slash via SSE, sessões persistentes com pastas/busca/exportação Markdown, cartões de ferramentas, aprovação de permissão inline, painel de configurações, tema claro/escuro/sistema e endpoints `/health` + `/metrics`. Um terminal PTY completo com xterm.js fica em `/` (100% de paridade com a CLI).

> **Guia completo:** [../guides/web-ui.md](../guides/web-ui.md) · **Docker / servidor doméstico:** [../guides/docker.md](../guides/docker.md) · **Aplicativo desktop nativo:** [desktop/README.md](../../desktop/README.md)

---

## Documentação

Guias detalhados vivem em [`docs/guides/`](../guides/) para manter este README focado:

| Guia | O que há dentro |
|---|---|
| [**Funcionalidades (completo)**](../guides/features.md) | A tabela completa de funcionalidades — cada linha com todos os detalhes (compressão de contexto, auto-fanout, temas, textos de Trading/Research/Agents) |
| [**Uso (todos os provedores)**](../guides/usage.md) | Configuração por provedor + comandos de exemplo: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm, e Ollama/LM Studio/vLLM locais |
| [**Web UI**](../guides/web-ui.md) | Interface de chat, terminal PTY, endpoints de API, configurações, autenticação, streaming SSE |
| [**Aplicativo desktop**](../../desktop/README.md) | Shell de janela nativa (Electron) que envolve a web UI local; gere um `.dmg`/`.exe`/`.AppImage` autocontido |
| [**Docker / Servidor Doméstico**](../guides/docker.md) | Dockerfile + compose: web UI + pontes em um contêiner, Ollama no host, montagem de workspace |
| [**Referência**](../guides/reference.md) | CLI, 50+ comandos, 33 ferramentas integradas, busca de sessões, classificação de erros, cache de ferramentas |
| [**Extensões**](../guides/extensions.md) | Memória, Skills, Subagentes, servidores MCP, Plugins, Monitor, Agentes autônomos |
| [**Pontes**](../guides/bridges.md) | Configuração de Telegram, WeChat, Slack, QQ + controle remoto pelo seu celular |
| [**Segurança e variáveis de ambiente**](../guides/security.md) | Modelo de ameaças, variáveis `CHEETAHCLAWS_*`, tratamento de tokens de bot, denylist do Bash, sandbox de fs, CSRF |
| [**Voz e Vídeo**](../guides/voice-and-video.md) | Entrada de voz com Whisper offline, fábrica de Vídeo, fábrica de TTS |
| [**Trading**](../guides/trading.md) | Análise multiagente, backtesting, memória BM25, fallbacks de dados, integração com SSJ |
| [**Avançado**](../guides/advanced.md) | Brainstorm, SSJ, Tmux, monitoramento proativo, checkpoints, modo plano, sessões, sincronização na nuvem |
| [**Comparação**](../guides/comparison.md) | Posicionamento completo vs Claude Code e OpenClaw — tabelas resumidas, vitórias dos dois lados, diferenças-chave de design |
| [**Receitas**](../guides/recipes.md) | 12 exemplos passo a passo: revisão de código, controle remoto, pesquisa, correção de bug, navegação, e-mail, PDF/Excel |
| [**FAQ**](../guides/faq.md) | O FAQ completo (MCP, modelos/provedores, CLI/scripting, voz) |
| [**Criação de plugins**](../guides/plugin-authoring.md) · [Exemplo](../../examples/example-plugin/) | Crie um plugin: ferramentas, comandos, skills, MCP; template inicial |
| [**Laboratório de Pesquisa**](../guides/research-lab.md) | `/lab start <topic>` — escrita autônoma multiagente de artigos com experimentos em sandbox |
| [**Agent OS**](../agent-os.md) · [Índice de RFCs](../RFC/) | A camada `kernel/` + todas as notas de design (RFC 0001-0032) |
| [**Contribuindo**](../../CONTRIBUTING.md) | Estrutura do projeto, guia de arquitetura, checklist de PR |

---

## Referência rápida

```
cheetahclaws [OPTIONS] [PROMPT]

  -p, --print          Não interativo: executa o prompt e sai
  -m, --model MODEL    Sobrescreve o modelo (ex.: gpt-4o, ollama/llama3.3)
  --accept-all         Aprova automaticamente todas as operações (sem prompts de permissão)
  --verbose            Mostra blocos de raciocínio e contagem de tokens por turno
  --show-tools         Mostra cada chamada de ferramenta em vez de um resumo por turno
                       (alias: --no-quiet; o resumo compacto é o padrão)
  --thinking           Ativa o Extended Thinking (apenas Claude)
  --web                Inicia o servidor web (Chat UI + terminal PTY no navegador)
  --port / --host      Porta / host do servidor web (padrão 8080 / 127.0.0.1)
  --no-auth            Desativa a senha da web (apenas uso local)
  --version / -h       Imprime a versão / mostra a ajuda
```

```bash
cheetahclaws                                          # REPL interativo, modelo padrão
cheetahclaws -m ollama/deepseek-r1:32b                # escolha um modelo
cheetahclaws -p "Write a Python fibonacci function"   # não interativo
cheetahclaws --accept-all -p "Init a pyproject.toml"  # CI / automação
cheetahclaws --web --port 8008 --no-auth              # chat no navegador + terminal
```

Veja o [Guia de Referência](../guides/reference.md) para todos os 50+ comandos slash, ferramentas e opções de configuração.

---

## Contribuindo

Contribuições são bem-vindas! Veja o [Guia de Contribuição](../../CONTRIBUTING.md) para arquitetura, convenções e o checklist de PR.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ testes devem passar
python cheetahclaws.py              # executar o REPL
```

Está criando um plugin? Veja o [Guia de Criação de Plugins](../guides/plugin-authoring.md) e o [template de exemplo](../../examples/example-plugin/).

---

## FAQ

Algumas perguntas comuns — o **FAQ completo** está em [../guides/faq.md](../guides/faq.md).

**P: Como adiciono um servidor MCP?**
```
/mcp add git uvx mcp-server-git          # ou crie .mcp.json no seu projeto, depois /mcp reload
```

**P: As chamadas de ferramenta não funcionam com meu modelo Ollama local (ele fica apenas descrevendo o que faria em vez de fazer).**
O CheetahClaws agora recupera automaticamente as chamadas de ferramenta que modelos locais emitem como **texto** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) em vez do campo estruturado do Ollama, então a maioria dos modelos com function-calling executa ferramentas de imediato. Para melhor confiabilidade, use um modelo com tool-calling — `qwen2.5-coder`, `llama3.3`, `mistral` ou `phi4`. Modelos pequenos também são mais fracos no uso agentivo de ferramentas do que modelos de nuvem, então espere que precisem de prompts mais claros e concretos.

**P: Depois de instalar no macOS, `cheetahclaws: command not found` e nenhum `~/.zshrc` foi criado.**
Recarregue seu shell primeiro: `source ~/.zshrc` (zsh) ou `source ~/.bash_profile` (bash). O instalador cria `~/.zshrc` se ele não existir, cria um symlink do binário em `~/.local/bin` e o adiciona ao PATH. Se você instalou uma versão mais antiga, re-execute o instalador ou adicione esta linha você mesmo: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

Mais — vLLM remoto, custo de API (`/cost`), múltiplas chaves por sessão, modelo padrão entre projetos, encaminhamento de entrada por pipe, configuração de voz, correções de texto corrompido — estão todos respondidos em [../guides/faq.md](../guides/faq.md).

---

## Citação
Se você achar o repositório útil, por favor, cite o estudo
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


## Agradecimentos a todos os contribuidores:

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
