[English](../../README.md) | [中文](README.CN.MD) | [한국어](README.KO.MD) | [日本語](README.JP.MD) | [Français](README.FR.MD) | [Deutsch](README.DE.MD) | Español | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: Una infraestructura de arnés de agentes rápida y fácil de usar para sistemas de IA de largo horizonte, multimodelo y con uso de herramientas</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">Sitio web</a>
    ·
    <a href="https://arxiv.org/pdf/2605.26112">Escalando el arnés</a>
    ·
    <a href="https://github.com/SafeRL-Lab/cheetahclaws/issues">Incidencias</a>
    ·
    <a href="https://pypi.org/project/cheetahclaws/">
      <img src="https://img.shields.io/badge/downloads-9.6K-blue" alt="Downloads 9.6K" align="absmiddle">
    </a>
  </p>
</div>


### Instalación rápida

```bash
pip install cheetahclaws
```

Luego simplemente ejecuta:

```bash
cheetahclaws        # ¡empieza a chatear!
```

Otros métodos de instalación: [script de instalación en una línea](#alternativa-script-de-instalación-en-una-línea) | [instalar desde el código fuente](#alternativa-instalar-con-pip-desde-el-código-fuente) | [instalación con uv](#alternativa-instalar-con-uv) | [ejecutar desde el código fuente](#alternativa-ejecutar-directamente-desde-el-código-fuente-sin-instalación) | [detalles completos de instalación](#instalación)

> 🖥️ **¿Prefieres una app nativa?** Una compilación de escritorio (Electron) envuelve toda la interfaz de chat en una ventana — sin necesidad de terminal. Consulta [`desktop/`](../../desktop/README.md).

## 🔥🔥🔥 Novedades (hora del Pacífico)

- 9 de julio de 2026: **Imagen Docker oficial + publicación con un solo comando.** Imagen precompilada en Docker Hub (`docker pull chauncygu/cheetahclaws`) para que puedas ejecutar la Web UI sin clonar; corrige un `PermissionError` en la primera ejecución al precrear los directorios `.cheetahclaws`/`workspace` propiedad del usuario no root, permite sobrescribir el `image` de compose mediante `CHEETAH_IMAGE` y añade `scripts/docker-publish.sh` (lee la versión automáticamente, multi/mono arquitectura). Nuevas secciones de documentación: **Descargar desde Docker Hub** y **Configuración interactiva / modo CLI**. [Detalles](../news.md)
- 8 de julio de 2026: El nuevo comando **`/workspace`** gestiona directorios de trabajo aislados bajo `~/.cheetahclaws/workspaces` (`list`/`switch`/`default`/`create`/`delete`) (PR #162); el cambio automático al arrancar es **opcional** mediante `workspace_auto` (desactivado por defecto, por lo que lanzarlo en un directorio de proyecto no cambia), y `default` es ahora una clave fija independiente de la última usada. [Detalles](../news.md)
- 6 de julio de 2026 (**v3.5.84**): **`/image` ahora enriquece el prompt con texto OCR local** para que incluso los modelos sin visión puedan actuar sobre capturas de pantalla del portapapeles (volcados de errores, código, tablas); se ejecuta solo cuando `pytesseract`/`tesseract` están instalados y es totalmente desactivable con `CHEETAHCLAWS_IMAGE_OCR=0`. [Detalles](../news.md)
- 28 de junio de 2026: Nuevo modo de permisos **`accept-edits`** (ejecuta ediciones de archivos automáticamente, pero sigue preguntando antes de Bash no incluido en la lista de permitidos) — el punto intermedio entre `auto` y `accept-all`; también expone el modo `plan` existente en `/permissions` y corrige la descripción engañosa de `auto` en el prompt. [Detalles](../news.md)
- 28 de junio de 2026: La **caducidad de la memoria** ahora se ancla a una fecha `last_verified` en lugar de al mtime del archivo, de modo que leer una memoria no puede refrescar falsamente una obsoleta (PR #150); la nueva herramienta **`MemoryVerify`** es lo único que reinicia el reloj, el prompt indica al agente que la llame tras volver a comprobar, y el manifiesto de memoria inyectado se clasifica por la recencia de verificación. [Detalles](../news.md)
- 23 de junio de 2026 (**v3.5.83**): Documentación adelgazada (novedades del README → una línea cada una, lista de 59 modelos de Atlas → usage.md, FAQ recortada) y se añadió una **app de escritorio** nativa (envoltorio Electron sobre la web UI) bajo `desktop/`; se unificó el formato de la cadena de versión a `v3.5.x`. [Detalles](../news.md)
- 16 de junio de 2026: Todos los módulos internos viven ahora bajo un único paquete `cheetahclaws` (`from cheetahclaws import kernel`), eliminando los fallos por colisión de nombres de `sys.path` al arrancar — rompe solo si importas los internos directamente; suite completa en verde (2449 aprobados). [Detalles](../news.md)
- 6 de junio de 2026 (**v3.5.82**): La instalación en macOS ahora coloca de forma fiable `cheetahclaws` en el PATH, y los modelos Ollama locales que emiten llamadas a herramientas como texto ahora sí las ejecutan (dos correcciones de #131). [Detalles](../news.md)
- 5 de junio de 2026: Presupuestos de tokens/coste controlables por el usuario — `/budget $5` / `/budget daily $20` limitan el gasto por sesión o por día, aplicado antes de cada llamada al modelo. [Detalles](../news.md)
- 5 de junio de 2026: El streaming adaptativo de Markdown mantiene la salida en vivo correcta en todos los dispositivos seleccionando automáticamente un nivel por dispositivo; también añade una cuadrícula visual `/context` y contexto de 1M para `deepseek-v4-flash`. [Detalles](../news.md)


Para más novedades, consulta [aquí](../news.md).

---

## Patrocinador

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **Una infraestructura de arnés de agentes** nativa de Python, **rápida** y **fácil de usar**, **compatible con cualquier modelo**, como Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax y modelos locales de código abierto vía Ollama o cualquier endpoint compatible con OpenAI.

---

## Contenido
  * [Por qué CheetahClaws](#por-qué-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [Características](#características)
  * [Modelos compatibles](#modelos-compatibles)
  * [Instalación](#instalación)
  * [Uso: modelos de API de código cerrado](#uso-modelos-de-api-de-código-cerrado)
  * [Uso: modelos de código abierto (locales)](#uso-modelos-de-código-abierto-locales)
  * [Formato del nombre del modelo](#formato-del-nombre-del-modelo)
  * [Agente de trading](#agente-de-trading)
  * [Web UI](#web-ui)
  * [Documentación](#documentación) (guías de todas las características)
  * [Contribuir](#contribuir) · [FAQ](#faq) · [Cita](#cita)


### Demostraciones

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>Ejecución de tareas en la terminal</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web UI: chat en el navegador — barra lateral, tarjetas de herramientas, avisos de aprobación, streaming de Markdown</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Agente de trading autónomo</i></sub></div>

> Más demostraciones animadas (revisión de código, `/research`, `/brainstorm`, `/lab`, puentes con Telegram/WeChat/Slack) viven en [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/).

---

## Por qué CheetahClaws

Claude Code es un asistente de programación con IA potente y de nivel de producción — pero su código fuente es un bundle compilado de TypeScript/Node de ~12 MB (~1300 archivos, ~283K líneas), fuertemente acoplado a la API de Anthropic, difícil de modificar e imposible de ejecutar contra un modelo local o alternativo.

**CheetahClaws** reimplementa el mismo bucle central en ~90K líneas de Python legible — conservando lo que necesitas, descartando lo que no, y añadiendo soporte multiproveedor + modelos locales. Comparación completa: [docs/guides/comparison.md](../guides/comparison.md).

| Dimensión | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Lenguaje | TypeScript + React/Ink | Python 3.8+ |
| Archivos fuente / LoC | ~1332 archivos / ~283K | ~315 archivos / ~90K (núcleo; ~127K con pruebas) |
| Herramientas / comandos integrados | 44+ / 88 | 27 / 50+ |
| Proveedores de modelos | Solo Anthropic | 8+ (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| Modelos locales | No | Sí — Ollama, LM Studio, vLLM, cualquier endpoint compatible con OpenAI |
| Paso de compilación | Sí (Bun + esbuild) | No — `python cheetahclaws.py` |
| Extensibilidad | Cerrada (en tiempo de compilación) | Abierta — `register_tool()` en tiempo de ejecución, skills en Markdown, plugins de git, MCP |
| Entrada de voz | WebSocket propietario (OAuth) | Whisper local / OpenAI — funciona sin conexión |

**Dónde gana Claude Code:** UI más rica de React/Ink, más herramientas integradas, funciones empresariales (MDM, sincronización de permisos de equipo, OAuth/keychain), extracción de memoria impulsada por IA, fiabilidad de producción de binario único.

**Dónde gana CheetahClaws:** cambio a cualquier modelo (`--model`/`/model`, sin recompilar) incl. soporte completo local/sin conexión; un bucle de agente legible en un solo archivo (`agent.py`, ~740 líneas); cero compilación; registro de herramientas en tiempo de ejecución + MCP + plugins de git + skills en Markdown; grafo de dependencias de tareas (`blocks`/`blocked_by`); compresión de contexto de dos capas; voz sin conexión; sincronización de sesiones en la nube; puentes con Telegram/WeChat/Slack/QQ.

**Para quién es:** desarrolladores que quieren un asistente de programación local/no-Anthropic, investigadores que estudian cómo funcionan los asistentes agénticos, y equipos que necesitan una base modificable — sin una cadena de compilación de Node.js.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) es otro asistente de código abierto popular (TypeScript/Node). Ambos tienen **objetivos principales distintos** — OpenClaw es un asistente de vida personal a través de canales de mensajería; CheetahClaws es una herramienta de desarrollo/programación.

| Dimensión | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Líneas de código | ~245K (~10 349 archivos) | ~90K núcleo (~315 archivos) |
| Enfoque principal | Asistente personal a través de canales | Asistente de programación con IA / herramienta de desarrollo |
| Arquitectura | Daemon Gateway siempre activo + apps | REPL de terminal sin instalación |
| Canales de mensajería | 20+ (WhatsApp · Signal · iMessage · Discord · Matrix · …) | Terminal + puentes con Telegram · WeChat · Slack · QQ |
| Modelos locales / sin conexión | Limitado | Completo — Ollama · vLLM · LM Studio · cualquiera compatible con OpenAI |
| Herramientas de edición de código | Control del navegador, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| Móvil / Live Canvas | Sí (barra de menú + iOS/Android, A2UI) | — |
| Soporte MCP | — | Sí (stdio/SSE/HTTP) |
| Facilidad de modificación | 245K líneas, más difícil de modificar | ~90K líneas — bucle de agente en un solo archivo |

| Si quieres… | Usa |
|---|---|
| Un asistente personal en WhatsApp/Signal/Discord, orientado a móvil, con automatización de navegador + Canvas | **OpenClaw** |
| Un asistente de programación con IA en tu terminal, modelos locales/sin conexión completos, cambio multiproveedor, y código fuente que puedes leer en una tarde | **CheetahClaws** |

> Comparación completa — victorias de ambos lados + diferencias clave de diseño (bucle de agente, registro de herramientas, compresión de contexto, memoria): [docs/guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw).

---

## Características

| Característica | Detalles |
|---|---|
| Multiproveedor | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · Endpoint personalizado |
| Bucle de agente | API de streaming + bucle automático de uso de herramientas; todo el bucle está en `agent.py` |
| 28 herramientas integradas | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(herramientas de MCP + plugins añadidas automáticamente)* |
| Integración MCP | Conecta cualquier servidor MCP (stdio/SSE/HTTP); herramientas registradas automáticamente — consulta la [guía de extensiones](../guides/extensions.md) |
| Sistema de plugins | Instala/activa/actualiza plugins desde URLs de git o rutas locales; multi-ámbito; motor de recomendaciones |
| Gestión de tareas | `TaskCreate/Update/Get/List`, IDs secuenciales, aristas de dependencia, persistidas en `.cheetahclaws/tasks.json` |
| Compresión de contexto | Cuatro capas cooperantes — límite dinámico de `max_tokens`, registro de ventanas de contexto por modelo, recorte de dos capas + resumen por IA al 70%, y auto-fanout para salidas de herramientas sobredimensionadas. [Detalles](../guides/reference.md) |
| Memoria persistente | Doble ámbito (usuario + proyecto), 4 tipos, metadatos de confianza/origen, detección de conflictos, búsqueda ponderada por recencia, `/memory consolidate`. Caducidad anclada a verificación — la frescura sigue una fecha `last_verified` (no el mtime del archivo), de modo que leer una memoria no puede refrescarla falsamente; solo `MemoryVerify` reinicia el reloj. [Detalles](../guides/features.md) |
| Multi-agente | Genera subagentes tipados (coder/reviewer/researcher/…), aislamiento con git-worktree, modo en segundo plano |
| Sistema de permisos | Solo pregunta por acciones que puedan cambiar tus archivos, ejecutar código arbitrario o salir de la sesión. Todas las herramientas de solo lectura, las tuberías de shell de solo lectura (`git log \| head`) y la creación de un archivo **nuevo** dentro del espacio de trabajo se ejecutan sin preguntar. Pulsar `s` en el aviso concede **ese único comando o ese único archivo** durante el resto de la sesión: la alternativa acotada a accept-all (`/permissions clear` las descarta). Modos: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`; una lista de denegación estricta bloquea comandos destructivos en todos los modos. [Detalles](../guides/security.md#what-runs-without-asking-auto-mode) |
| Puntos de control y modo plan | Instantánea automática de la conversación + archivos en cada turno (`/checkpoint`, `/rewind`); modo de análisis de solo lectura `/plan` |
| Comandos slash y temas | 50+ comandos slash con autocompletado por Tab; `/theme` ofrece 15 paletas seleccionadas |
| Brainstorm → Worker | `/brainstorm` ejecuta un debate de N personas → `todo_list.txt`; `/worker` implementa automáticamente las tareas pendientes |
| Modo desarrollador SSJ | `/ssj` — menú de potencia persistente que encadena Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor, etc. |
| Agente de trading | `/trading` análisis multi-agente, backtesting, calibración de paper-trade, carteras MV. [Guía](../guides/trading.md) |
| Monitor | `/monitor` se suscribe a temas monitorizados por IA en una programación (arxiv / acciones / cripto / noticias / personalizado), envía informes a puentes/consola |
| Investigación (multifuente) | `/research` se despliega a **20 fuentes** con tabla de calor de atención, extracción de entidades, sparkline de tendencias, modo comparación. [Guía](../guides/research.md) |
| Agentes autónomos | `/agent` bucles en segundo plano desde plantillas Markdown; resúmenes de iteración enviados vía puente; guardia de parada por estancamiento |
| Puentes + control remoto | Telegram · WeChat · Slack · QQ — ida y vuelta de chat, paso de comandos slash, cola de trabajos por puente (`!jobs`/`!retry`/`!cancel`). [Guía](../guides/bridges.md) |
| Voz / Visión / Vídeo / TTS | Whisper sin conexión `/voice`; visión de portapapeles `/image` (local + nube); fábricas de contenido `/video` + `/tts`. [Guía](../guides/voice-and-video.md) |
| Web UI | `--web` — chat en navegador multiusuario + terminal PTY. [Guía](../guides/web-ui.md) |
| Más | Integración con Tmux · escape de shell `!cmd` · monitorización proactiva · salida forzada con 3×Ctrl+C · persistencia de sesiones · sincronización `/cloudsave` con GitHub-Gist · seguimiento de costes · modo no interactivo `--print` |

> **Referencia completa de características** — cada fila anterior con detalle completo (capas de compresión de contexto, auto-fanout, 15 temas, los artículos completos de Trading/Research/Agents, …): [docs/guides/features.md](../guides/features.md).

---

## Modelos compatibles

### Código cerrado (API)

| Proveedor | Modelos de ejemplo | Contexto | Env de clave API |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (nivel gratuito) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ modelos, una sola clave)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | varía | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ modelos, una sola clave)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | varía | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(vía litellm)_ | `litellm/<provider>/<model>` | varía | específico del proveedor |

> **Pasarela `openrouter/`:** una sola clave para más de 400 modelos de distintos proveedores. El ID del modelo conserva la ruta upstream `<vendor>/<model>` de OpenRouter, así que la llamada lleva doble prefijo: `openrouter/deepseek/deepseek-v4-flash`. Para fijar qué proveedor upstream (y qué cuantización) atiende la petición, añade `@<provider>[/<quantization>]` — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — que se envía como el objeto `provider` del cuerpo de la petición en lugar de pegarse al ID del modelo. Consulta [usage.md](../guides/usage.md#openrouter-400-models-one-key).

> **Pasarela `requesty/`:** funciona igual: todo lo que va después de `requesty/` se envía como ID del modelo, ya sea una ruta de catálogo `<vendor>/<model>` (`requesty/openai/gpt-4o-mini`) o un ID de política gestionada (`requesty/claude-sonnet-4-6`). Los IDs de política gestionada que terminan en `@eu` (`requesty/gpt-5-mini@eu`) solo se enrutan a través de proveedores de la UE. Consulta [usage.md](../guides/usage.md#requesty-700-models-one-key).

> **Adaptador `litellm/`:** enruta a más de 100 proveedores tras un único SDK — principalmente para upstreams con autenticación incómoda (Bedrock SigV4, enrutamiento de despliegues de Azure, JWT de cuentas de servicio de Vertex). Para endpoints con forma OpenAI simple, prefiere el adaptador `custom/` sin dependencias. Instala con `pip install ".[litellm]"`. Consulta [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

### Código abierto (local vía Ollama)

| Modelo | Tamaño | Fortalezas | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **Mejor para programar** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | Propósito general | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | Razonamiento, matemáticas | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | Rápido / MoE potente | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | Razonamiento / abierto / código | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **Visión** | `ollama pull llava` |

> **La llamada a herramientas** necesita un modelo con function-calling — recomendados: `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Los modelos que emiten llamadas a herramientas como **texto** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) en lugar del campo estructurado de Ollama se recuperan automáticamente, de modo que ejecutan herramientas directamente en lugar de solo hablar de ello. Los modelos de razonamiento (`deepseek-r1`, `qwen3`, `gemma4`) transmiten bloques `<think>` nativos; actívalos con `/verbose` + `/thinking`.

---

## Instalación

```bash
pip install cheetahclaws
```

Funciona en **Linux, macOS, WSL2 y Android (Termux)** (Python 3.10+). La primera ejecución te guía en la configuración del proveedor + clave API; vuelve a ejecutar en cualquier momento con `cheetahclaws --setup`.

> **Windows:** Windows nativo no es compatible — usa [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). **Android/Termux:** `pkg install python git && pip install cheetahclaws`.

### Alternativa: script de instalación en una línea

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

Tras la instalación, recarga tu shell para que `cheetahclaws` esté en el PATH:

```bash
source ~/.zshrc     # macOS
# o: source ~/.bashrc   # Linux
cheetahclaws        # ¡empieza a chatear!
```

### Alternativa: instalar con `pip` desde el código fuente

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # luego: cheetahclaws
git pull && pip install --force-reinstall .   # para actualizar
```

#### Extras opcionales

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

### Alternativa: instalar con `uv`

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### Alternativa: ejecutar directamente desde el código fuente (sin instalación)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## Uso: modelos de API de código cerrado

Todos los proveedores en la nube siguen el mismo patrón — exporta su clave API (consulta la tabla de [Modelos compatibles](#código-cerrado-api) para el nombre de la variable de entorno), luego selecciona un modelo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

Páginas para obtener clave de cada proveedor: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat).

**AWS Bedrock / Azure / Vertex** usan la forma `litellm/<provider>/<model>` (`pip install ".[litellm]"`) — recetas completas de variables de entorno en [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

> **Guía completa por proveedor** — la página para obtener clave de cada proveedor + comandos de modelo de ejemplo, más recetas de variables de entorno de Bedrock/Azure/Vertex: [docs/guides/usage.md](../guides/usage.md).

---

## Uso: modelos de código abierto (locales)

### Ollama (recomendado)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

Descarga [LM Studio](https://lmstudio.ai), toma un modelo GGUF, inicia su **Local Server** (puerto 1234), luego:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / servidor autoalojado compatible con OpenAI

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

El nombre después de `custom/` debe coincidir con el `--served-model-name` del servidor. Para la Web UI, `--web --model custom/<name>` persiste el modelo antes de que arranque el servidor. ¿Servidor remoto? Apunta `CUSTOM_BASE_URL` a su IP.

> **Guía completa de modelos locales** — Ollama paso a paso, LM Studio, vLLM + Web UI: [docs/guides/usage.md](../guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (alojado, compatible con OpenAI)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** sirve DeepSeek, Qwen, GLM, Kimi, MiniMax y más tras un único endpoint compatible con OpenAI, mediante el adaptador `custom/` sin dependencias:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> Cualquier id de modelo de chat de Atlas funciona igual — **lista completa de los 59 modelos:** [docs/guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## Formato del nombre del modelo

Se aceptan tres formas equivalentes:

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**Autodetección por prefijo:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

---

## Agente de trading

Un módulo integrado de análisis de trading + backtesting con IA (`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4 estrategias (`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), memoria BM25 de situaciones pasadas, mercados de EE. UU./HK/acciones A + cripto con datos de respaldo sin clave API. Submenú guiado vía `/ssj` → **Trading**.

> **Guía completa:** [docs/guides/trading.md](../guides/trading.md)

---

## Web UI

Una interfaz de navegador lista para producción — cuentas de usuario reales (bcrypt + JWT), historial respaldado por SQLite, endpoints de operaciones — servida por la biblioteca estándar de Python + diez módulos JS vanilla (sin Node.js / React / paso de compilación).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

Abre `http://localhost:<port>/chat` — la primera cuenta se convierte en admin. Incluye chat en streaming (WS) + comandos slash por SSE, sesiones persistentes con carpetas/búsqueda/exportación a Markdown, tarjetas de herramientas, aprobación de permisos en línea, panel de configuración, tema claro/oscuro/sistema, y endpoints `/health` + `/metrics`. Una terminal PTY completa con xterm.js vive en `/` (100% de paridad con la CLI).

> **Guía completa:** [docs/guides/web-ui.md](../guides/web-ui.md) · **Docker / servidor doméstico:** [docs/guides/docker.md](../guides/docker.md) · **App de escritorio nativa:** [desktop/README.md](../../desktop/README.md)

---

## Documentación

Las guías detalladas viven en [`docs/guides/`](../guides/) para mantener este README enfocado:

| Guía | Qué contiene |
|---|---|
| [**Características (completo)**](../guides/features.md) | La tabla completa de características — cada fila con detalle completo (compresión de contexto, auto-fanout, temas, artículos de Trading/Research/Agents) |
| [**Uso (todos los proveedores)**](../guides/usage.md) | Configuración por proveedor + comandos de ejemplo: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm, y Ollama/LM Studio/vLLM locales |
| [**Web UI**](../guides/web-ui.md) | Interfaz de chat, terminal PTY, endpoints de API, configuración, auth, streaming SSE |
| [**App de escritorio**](../../desktop/README.md) | Envoltorio de ventana nativa (Electron) que envuelve la web UI local; construye un `.dmg`/`.exe`/`.AppImage` autocontenido |
| [**Docker / servidor doméstico**](../guides/docker.md) | Dockerfile + compose: web UI + puentes en un contenedor, Ollama en el host, montaje de workspace |
| [**Referencia**](../guides/reference.md) | CLI, 50+ comandos, 33 herramientas integradas, búsqueda de sesiones, clasificación de errores, caché de herramientas |
| [**Extensiones**](../guides/extensions.md) | Memoria, Skills, Subagentes, servidores MCP, Plugins, Monitor, Agentes autónomos |
| [**Puentes**](../guides/bridges.md) | Configuración de Telegram, WeChat, Slack, QQ + control remoto desde tu teléfono |
| [**Seguridad y variables de entorno**](../guides/security.md) | Modelo de amenazas, variables `CHEETAHCLAWS_*`, manejo de tokens de bot, lista de denegación de Bash, sandbox de fs, CSRF |
| [**Voz y vídeo**](../guides/voice-and-video.md) | Entrada de voz Whisper sin conexión, fábrica de vídeo, fábrica de TTS |
| [**Trading**](../guides/trading.md) | Análisis multi-agente, backtesting, memoria BM25, datos de respaldo, integración SSJ |
| [**Avanzado**](../guides/advanced.md) | Brainstorm, SSJ, Tmux, monitorización proactiva, puntos de control, modo plan, sesiones, sincronización en la nube |
| [**Comparación**](../guides/comparison.md) | Posicionamiento completo frente a Claude Code y OpenClaw — tablas de un vistazo, victorias de ambos lados, diferencias clave de diseño |
| [**Recetas**](../guides/recipes.md) | 12 ejemplos paso a paso: revisión de código, control remoto, investigación, corrección de bugs, navegación, correo, PDF/Excel |
| [**FAQ**](../guides/faq.md) | La FAQ completa (MCP, modelos/proveedores, CLI/scripting, voz) |
| [**Creación de plugins**](../guides/plugin-authoring.md) · [Ejemplo](../../examples/example-plugin/) | Construye un plugin: herramientas, comandos, skills, MCP; plantilla inicial |
| [**Laboratorio de investigación**](../guides/research-lab.md) | `/lab start <topic>` — redacción autónoma de artículos multi-agente con experimentos en sandbox |
| [**Agent OS**](../agent-os.md) · [Índice de RFC](../RFC/) | La capa `kernel/` + todas las notas de diseño (RFC 0001-0032) |
| [**Contribuir**](../../CONTRIBUTING.md) | Estructura del proyecto, guía de arquitectura, checklist de PR |

---

## Referencia rápida

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

Consulta la [Guía de referencia](../guides/reference.md) para todos los 50+ comandos slash, herramientas y opciones de configuración.

---

## Contribuir

¡Damos la bienvenida a las contribuciones! Consulta la [Guía de contribución](../../CONTRIBUTING.md) para la arquitectura, las convenciones y el checklist de PR.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

¿Construyendo un plugin? Consulta la [Guía de creación de plugins](../guides/plugin-authoring.md) y la [plantilla de ejemplo](../../examples/example-plugin/).

---

## FAQ

Algunas preguntas comunes — la **FAQ completa** está en [docs/guides/faq.md](../guides/faq.md).

**P: ¿Cómo añado un servidor MCP?**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**P: Las llamadas a herramientas no funcionan con mi modelo Ollama local (solo sigue describiendo lo que haría en lugar de hacerlo).**
CheetahClaws ahora recupera automáticamente las llamadas a herramientas que los modelos locales emiten como **texto** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) en lugar de en el campo estructurado de Ollama, de modo que la mayoría de los modelos con function-calling ejecutan herramientas directamente. Para la mejor fiabilidad usa un modelo con function-calling — `qwen2.5-coder`, `llama3.3`, `mistral` o `phi4`. Los modelos pequeños también son más débiles en el uso agéntico de herramientas que los modelos en la nube, así que espera que necesiten prompts más claros y concretos.

**P: Tras instalar en macOS, `cheetahclaws: command not found` y no se creó ningún `~/.zshrc`.**
Recarga primero tu shell: `source ~/.zshrc` (zsh) o `source ~/.bash_profile` (bash). El instalador crea `~/.zshrc` si falta, enlaza simbólicamente el binario en `~/.local/bin` y lo añade al PATH. Si instalaste una versión más antigua, vuelve a ejecutar el instalador o añade esta línea tú mismo: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

Más — vLLM remoto, coste de API (`/cost`), varias claves por sesión, modelo por defecto entre proyectos, canalizar entrada, configuración de voz, correcciones de texto ilegible — se responden todas en [docs/guides/faq.md](../guides/faq.md).

---

## Cita
Si encuentras el repositorio útil, por favor cita el estudio
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


## Gracias a todos los colaboradores:

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
