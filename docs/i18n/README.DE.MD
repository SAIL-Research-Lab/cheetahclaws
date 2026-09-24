[English](../../README.md) | [中文](README.CN.MD) | [한국어](README.KO.MD) | [日本語](README.JP.MD) | [Français](README.FR.MD) | Deutsch | [Español](README.ES.MD) | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: Eine schnelle und benutzerfreundliche Agent-Harness-Infrastruktur für KI-Systeme mit langem Zeithorizont, mehreren Modellen und Werkzeugnutzung</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">Website</a>
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


### Schnellinstallation

```bash
pip install cheetahclaws
```

Dann einfach ausführen:

```bash
cheetahclaws        # start chatting!
```

Weitere Installationsmethoden: [Ein-Zeilen-Installationsskript](#alternative-ein-zeilen-installationsskript) | [Installation aus dem Quellcode](#alternative-installation-mit-pip-aus-dem-quellcode) | [uv-Installation](#alternative-installation-mit-uv) | [direkt aus dem Quellcode ausführen](#alternative-direkt-aus-dem-quellcode-ausführen-ohne-installation) | [vollständige Installationsdetails](#installation)

> 🖥️ **Lieber eine native App?** Ein Desktop-Build (Electron) verpackt die vollständige Chat-Benutzeroberfläche in einem Fenster – kein Terminal nötig. Siehe [`desktop/`](../../desktop/README.md).

## 🔥🔥🔥 News (Pacific Time)

- 9. Juli 2026: **Offizielles Docker-Image + Veröffentlichung mit einem Befehl.** Vorgefertigtes Image auf Docker Hub (`docker pull chauncygu/cheetahclaws`), damit du die Web-UI ohne Klonen ausführen kannst; behebt einen `PermissionError` beim ersten Start, indem die Verzeichnisse `.cheetahclaws`/`workspace` vorab im Besitz des Nicht-Root-Benutzers angelegt werden, macht das Compose-`image` über `CHEETAH_IMAGE` überschreibbar und fügt `scripts/docker-publish.sh` hinzu (liest die Version automatisch, multi-/single-arch). Neue Doku-Abschnitte: **Pull from Docker Hub** und **Interactive setup / CLI mode**. [Details](../news.md)
- 8. Juli 2026: Der neue Befehl **`/workspace`** verwaltet isolierte Arbeitsverzeichnisse unter `~/.cheetahclaws/workspaces` (`list`/`switch`/`default`/`create`/`delete`) (PR #162); das automatische Umschalten beim Start ist **opt-in** über `workspace_auto` (standardmäßig aus, sodass ein Start in einem Projektverzeichnis unverändert bleibt), und `default` ist nun ein fixer Schlüssel getrennt vom zuletzt Verwendeten. [Details](../news.md)
- 6. Juli 2026 (**v3.5.84**): **`/image` reichert den Prompt jetzt mit lokalem OCR-Text an**, sodass selbst Modelle ohne Vision auf Zwischenablage-Screenshots reagieren können (Fehlerausgaben, Code, Tabellen); läuft nur, wenn `pytesseract`/`tesseract` installiert sind, und ist über `CHEETAHCLAWS_IMAGE_OCR=0` vollständig abschaltbar. [Details](../news.md)
- 28. Juni 2026: Neuer Berechtigungsmodus **`accept-edits`** (Dateibearbeitungen automatisch ausführen, bei nicht allowlistetem Bash weiterhin nachfragen) – der Mittelweg zwischen `auto` und `accept-all`; legt außerdem den bestehenden `plan`-Modus in `/permissions` offen und korrigiert die irreführende `auto`-Beschreibung im Prompt. [Details](../news.md)
- 28. Juni 2026: **Speicher-Veralterung** orientiert sich jetzt an einem `last_verified`-Datum statt an der Datei-mtime, sodass das Lesen eines Speichers einen veralteten Eintrag nicht scheinbar auffrischen kann (PR #150); das neue Werkzeug **`MemoryVerify`** ist das Einzige, das die Uhr zurücksetzt, der Prompt weist den Agenten an, es nach erneuter Prüfung aufzurufen, und das eingefügte Speicher-Manifest ordnet nach verifizierter Aktualität. [Details](../news.md)
- 23. Juni 2026 (**v3.5.83**): Doku verschlankt (README-News → je eine Zeile, Atlas-Liste mit 59 Modellen → usage.md, FAQ gekürzt) und eine native **Desktop-App** (Electron-Hülle um die Web-UI) unter `desktop/` hinzugefügt; das Format der Versionszeichenkette auf `v3.5.x` vereinheitlicht. [Details](../news.md)
- 16. Juni 2026: Alle internen Module liegen jetzt unter einem einzigen `cheetahclaws`-Paket (`from cheetahclaws import kernel`), wodurch `sys.path`-Namenskollisions-Abstürze beim Start entfallen – ein Bruch nur, wenn du interne Teile direkt importierst; vollständige Testsuite grün (2449 bestanden). [Details](../news.md)
- 6. Juni 2026 (**v3.5.82**): Die macOS-Installation setzt `cheetahclaws` jetzt zuverlässig auf den PATH, und lokale Ollama-Modelle, die Werkzeugaufrufe als Text ausgeben, führen diese nun tatsächlich aus (zwei Fixes aus #131). [Details](../news.md)
- 5. Juni 2026: Benutzersteuerbare Token-/Kostenbudgets – `/budget $5` / `/budget daily $20` begrenzen die Ausgaben pro Sitzung oder Tag und werden vor jedem Modellaufruf durchgesetzt. [Details](../news.md)
- 5. Juni 2026: Adaptives Markdown-Streaming hält die Live-Ausgabe auf jedem Gerät korrekt, indem es automatisch eine gerätespezifische Stufe auswählt; fügt außerdem ein visuelles `/context`-Raster und 1M-Kontext für `deepseek-v4-flash` hinzu. [Details](../news.md)


Für weitere News siehe [hier](../news.md).

---

## Sponsor

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **Eine schnelle** und **benutzerfreundliche** Python-native Agent-Harness-Infrastruktur, die **jedes Modell unterstützt**, etwa Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax sowie lokale Open-Source-Modelle über Ollama oder jeden OpenAI-kompatiblen Endpunkt.

---

## Inhalt
  * [Warum CheetahClaws](#warum-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [Funktionen](#funktionen)
  * [Unterstützte Modelle](#unterstützte-modelle)
  * [Installation](#installation)
  * [Nutzung: Closed-Source-API-Modelle](#nutzung-closed-source-api-modelle)
  * [Nutzung: Open-Source-Modelle (lokal)](#nutzung-open-source-modelle-lokal)
  * [Format des Modellnamens](#format-des-modellnamens)
  * [Trading-Agent](#trading-agent)
  * [Web-UI](#web-ui)
  * [Dokumentation](#dokumentation) (Anleitungen zu allen Funktionen)
  * [Mitwirken](#mitwirken) · [FAQ](#faq) · [Zitation](#zitation)


### Demos

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>Aufgabenausführung im Terminal</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web-UI: Browser-Chat – Seitenleiste, Werkzeugkarten, Genehmigungsaufforderungen, Markdown-Streaming</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Autonomer Trading-Agent</i></sub></div>

> Weitere animierte Demos (Code-Review, `/research`, `/brainstorm`, `/lab`, Telegram-/WeChat-/Slack-Brücken) finden sich in [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/).

---

## Warum CheetahClaws

Claude Code ist ein leistungsstarker, produktionsreifer KI-Coding-Assistent – aber sein Quellcode ist ein kompiliertes ~12 MB großes TypeScript/Node-Bundle (~1.300 Dateien, ~283.000 Zeilen), eng an die Anthropic-API gekoppelt, schwer zu modifizieren und unmöglich gegen ein lokales oder alternatives Modell auszuführen.

**CheetahClaws** implementiert dieselbe Kernschleife in ~90.000 Zeilen lesbarem Python neu – behält, was du brauchst, lässt weg, was du nicht brauchst, und ergänzt Multi-Provider- + Lokalmodell-Unterstützung. Vollständiger Vergleich: [docs/guides/comparison.md](../guides/comparison.md).

| Dimension | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Sprache | TypeScript + React/Ink | Python 3.8+ |
| Quelldateien / LoC | ~1.332 Dateien / ~283K | ~315 Dateien / ~90K (Kern; ~127K mit Tests) |
| Eingebaute Werkzeuge / Befehle | 44+ / 88 | 27 / 50+ |
| Modellanbieter | nur Anthropic | 8+ (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| Lokale Modelle | Nein | Ja – Ollama, LM Studio, vLLM, jeder OpenAI-kompatible Endpunkt |
| Build-Schritt | Ja (Bun + esbuild) | Nein – `python cheetahclaws.py` |
| Erweiterbarkeit | Geschlossen (zur Kompilierzeit) | Offen – `register_tool()` zur Laufzeit, Markdown-Skills, Git-Plugins, MCP |
| Spracheingabe | Proprietärer WebSocket (OAuth) | Lokales Whisper / OpenAI – funktioniert offline |

**Wo Claude Code punktet:** reichhaltigere React/Ink-Benutzeroberfläche, mehr eingebaute Werkzeuge, Enterprise-Funktionen (MDM, Team-Berechtigungssynchronisierung, OAuth/Keychain), KI-gesteuerte Speicherextraktion, Single-Binary-Produktionszuverlässigkeit.

**Wo CheetahClaws punktet:** Umschalten zwischen beliebigen Modellen (`--model`/`/model`, kein Neukompilieren) inkl. voller Lokal-/Offline-Unterstützung; eine lesbare Agent-Schleife in einer Datei (`agent.py`, ~740 Zeilen); kein Build; Werkzeugregistrierung zur Laufzeit + MCP + Git-Plugins + Markdown-Skills; Aufgaben-Abhängigkeitsgraph (`blocks`/`blocked_by`); zweischichtige Kontextkompression; Offline-Sprache; Cloud-Sitzungssynchronisierung; Brücken zu Telegram/WeChat/Slack/QQ.

**Für wen es gedacht ist:** Entwickler, die einen lokalen/nicht-Anthropic-Coding-Assistenten wollen, Forschende, die untersuchen, wie agentische Assistenten funktionieren, und Teams, die eine hackbare Grundlage brauchen – ohne eine Node.js-Build-Kette.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) ist ein weiterer beliebter Open-Source-Assistent (TypeScript/Node). Beide verfolgen **unterschiedliche Hauptziele** – OpenClaw ist ein persönlicher Lebensassistent über Messaging-Kanäle hinweg; CheetahClaws ist ein Entwickler-/Coding-Werkzeug.

| Dimension | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Codezeilen | ~245K (~10.349 Dateien) | ~90K Kern (~315 Dateien) |
| Hauptfokus | Persönlicher Assistent über Kanäle hinweg | KI-Coding-Assistent / Dev-Tool |
| Architektur | Dauerhaft laufender Gateway-Daemon + Apps | Terminal-REPL ohne Installation |
| Messaging-Kanäle | 20+ (WhatsApp · Signal · iMessage · Discord · Matrix · …) | Terminal + Telegram · WeChat · Slack · QQ-Brücken |
| Lokale / Offline-Modelle | Begrenzt | Vollständig – Ollama · vLLM · LM Studio · jeder OpenAI-kompatible |
| Code-Bearbeitungswerkzeuge | Browsersteuerung, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| Mobil / Live Canvas | Ja (Menüleiste + iOS/Android, A2UI) | — |
| MCP-Unterstützung | — | Ja (stdio/SSE/HTTP) |
| Hackbarkeit | 245K Zeilen, schwerer zu modifizieren | ~90K Zeilen – Agent-Schleife in einer Datei |

| Wenn du willst… | Nutze |
|---|---|
| Einen persönlichen Assistenten auf WhatsApp/Signal/Discord, Mobile-first, Browser-Automatisierung + Canvas | **OpenClaw** |
| Einen KI-Coding-Assistenten in deinem Terminal, volle Offline-/Lokalmodelle, Multi-Provider-Umschaltung, Quellcode, den du an einem Nachmittag lesen kannst | **CheetahClaws** |

> Vollständiger Vergleich – die Stärken beider Seiten + zentrale Designunterschiede (Agent-Schleife, Werkzeugregistrierung, Kontextkompression, Speicher): [docs/guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw).

---

## Funktionen

| Funktion | Details |
|---|---|
| Multi-Provider | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · Eigener Endpunkt |
| Agent-Schleife | Streaming-API + automatische Werkzeugnutzungs-Schleife; die gesamte Schleife liegt in `agent.py` |
| 28 eingebaute Werkzeuge | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(MCP- + Plugin-Werkzeuge automatisch ergänzt)* |
| MCP-Integration | Verbinde jeden MCP-Server (stdio/SSE/HTTP); Werkzeuge automatisch registriert – siehe [Erweiterungs-Anleitung](../guides/extensions.md) |
| Plugin-System | Installiere/aktiviere/aktualisiere Plugins von Git-URLs oder lokalen Pfaden; mehrere Geltungsbereiche; Empfehlungs-Engine |
| Aufgabenverwaltung | `TaskCreate/Update/Get/List`, fortlaufende IDs, Abhängigkeitskanten, persistiert in `.cheetahclaws/tasks.json` |
| Kontextkompression | Vier zusammenwirkende Schichten – dynamische `max_tokens`-Obergrenze, modellspezifisches Kontextfenster-Register, zweischichtiges Kürzen + KI-Zusammenfassung bei 70 %, und automatisches Fanout für übergroße Werkzeugausgaben. [Details](../guides/reference.md) |
| Persistenter Speicher | Dualer Geltungsbereich (Benutzer + Projekt), 4 Typen, Konfidenz-/Quellen-Metadaten, Konflikterkennung, aktualitätsgewichtete Suche, `/memory consolidate`. Verifizierungsverankerte Veralterung – Aktualität orientiert sich an einem `last_verified`-Datum (nicht an der Datei-mtime), sodass das Lesen eines Speichers ihn nicht scheinbar auffrischen kann; nur `MemoryVerify` setzt die Uhr zurück. [Details](../guides/features.md) |
| Multi-Agent | Erzeuge typisierte Sub-Agenten (coder/reviewer/researcher/…), Git-Worktree-Isolation, Hintergrundmodus |
| Berechtigungssystem | Gefragt wird nur bei Aktionen, die deine Dateien ändern, beliebigen Code ausführen oder über die Sitzung hinausreichen können. Alle als read-only markierten Tools, read-only Shell-Pipelines (`git log \| head`) und das Anlegen einer **neuen** Datei im Workspace laufen ohne Rückfrage. Mit `s` an der Eingabeaufforderung erlaubst du genau **diesen einen Befehl bzw. diese eine Datei** für den Rest der Sitzung – die begrenzte Alternative zu accept-all (`/permissions clear` verwirft sie). Modi: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`; eine harte Sperrliste blockiert hostzerstörende Befehle in jedem Modus. [Details](../guides/security.md#what-runs-without-asking-auto-mode) |
| Checkpoints & Plan-Modus | Automatischer Snapshot von Konversation + Dateien in jeder Runde (`/checkpoint`, `/rewind`); `/plan` schreibgeschützter Analysemodus |
| Slash-Befehle & Themes | 50+ Slash-Befehle mit Tab-Vervollständigung; `/theme` bietet 15 kuratierte Paletten |
| Brainstorm → Worker | `/brainstorm` führt eine Debatte mit N Personas durch → `todo_list.txt`; `/worker` implementiert die ausstehenden Aufgaben automatisch |
| SSJ Developer Mode | `/ssj` – persistentes Power-Menü, das Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor usw. verkettet |
| Trading-Agent | `/trading` Multi-Agent-Analyse, Backtesting, Paper-Trade-Kalibrierung, MV-Portfolios. [Anleitung](../guides/trading.md) |
| Monitor | `/monitor` abonniert KI-überwachte Themen nach Zeitplan (arxiv / stock / crypto / news / custom), sendet Berichte an Brücken/Konsole |
| Research (mehrquellig) | `/research` fächert auf **20 Quellen** auf, mit Aufmerksamkeits-Heat-Tabelle, Entitätsextraktion, Trend-Sparkline, Vergleichsmodus. [Anleitung](../guides/research.md) |
| Autonome Agenten | `/agent` Hintergrundschleifen aus Markdown-Vorlagen; Iterationszusammenfassungen über Brücke gesendet; Stagnations-Stopp-Schutz |
| Brücken + Fernsteuerung | Telegram · WeChat · Slack · QQ – Chat-Roundtrip, Slash-Durchreichung, Job-Warteschlange pro Brücke (`!jobs`/`!retry`/`!cancel`). [Anleitung](../guides/bridges.md) |
| Voice / Vision / Video / TTS | Offline-Whisper `/voice`; `/image` Zwischenablage-Vision (lokal + Cloud); `/video` + `/tts` Content-Fabriken. [Anleitung](../guides/voice-and-video.md) |
| Web-UI | `--web` – Mehrbenutzer-Browser-Chat + PTY-Terminal. [Anleitung](../guides/web-ui.md) |
| Mehr | Tmux-Integration · `!cmd` Shell-Escape · proaktive Überwachung · 3×Strg+C-Beenden erzwingen · Sitzungspersistenz · `/cloudsave` GitHub-Gist-Sync · Kostenverfolgung · `--print` nicht-interaktiver Modus |

> **Vollständige Funktionsreferenz** – jede Zeile oben mit vollständigen Details (Kontextkompressions-Schichten, Auto-Fanout, 15 Themes, die vollständigen Trading-/Research-/Agents-Beschreibungen, …): [docs/guides/features.md](../guides/features.md).

---

## Unterstützte Modelle

### Closed-Source (API)

| Anbieter | Beispielmodelle | Kontext | API-Key-Env |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (kostenlose Stufe) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ Modelle, ein Schlüssel)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | variiert | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ Modelle, ein Schlüssel)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | variiert | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(über litellm)_ | `litellm/<provider>/<model>` | variiert | anbieterspezifisch |

> **`openrouter/`-Gateway:** ein Schlüssel für über 400 Modelle verschiedener Anbieter. Die Modell-ID behält den Upstream-Pfad `<vendor>/<model>` von OpenRouter bei, der Aufruf ist also doppelt präfixiert: `openrouter/deepseek/deepseek-v4-flash`. Um festzulegen, welcher Upstream-Anbieter (und welche Quantisierung) die Anfrage bedient, hänge `@<provider>[/<quantization>]` an — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — das als `provider`-Objekt im Request-Body gesendet wird, statt in die Modell-ID eingebaut zu werden. Siehe [usage.md](../guides/usage.md#openrouter-400-models-one-key).

> **`requesty/`-Gateway:** funktioniert genauso: alles nach `requesty/` wird als Modell-ID gesendet, entweder ein Katalogpfad `<vendor>/<model>` (`requesty/openai/gpt-4o-mini`) oder eine Managed-Policy-ID (`requesty/claude-sonnet-4-6`). Managed-Policy-IDs mit der Endung `@eu` (`requesty/gpt-5-mini@eu`) werden nur über EU-Anbieter geroutet. Siehe [usage.md](../guides/usage.md#requesty-700-models-one-key).

> **`litellm/`-Adapter:** leitet zu über 100 Anbietern hinter einem SDK weiter – hauptsächlich für Upstreams mit umständlicher Authentifizierung (Bedrock SigV4, Azure-Deployment-Routing, Vertex-Service-Account-JWTs). Für einfache OpenAI-förmige Endpunkte ist der abhängigkeitsfreie `custom/`-Adapter vorzuziehen. Installiere mit `pip install ".[litellm]"`. Siehe [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

### Open-Source (lokal über Ollama)

| Modell | Größe | Stärken | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **Am besten fürs Coding** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | Allzweck | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | Schlussfolgern, Mathematik | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | Schnell / starkes MoE | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | Schlussfolgern / offen / Code | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **Vision** | `ollama pull llava` |

> **Werkzeugaufrufe** benötigen ein Modell mit Funktionsaufruf – empfohlen: `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Modelle, die Werkzeugaufrufe als **Text** ausgeben (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) statt in Ollamas strukturiertem Feld, werden automatisch wiederhergestellt, sodass sie Werkzeuge sofort ausführen, statt nur darüber zu reden. Reasoning-Modelle (`deepseek-r1`, `qwen3`, `gemma4`) streamen native `<think>`-Blöcke; aktiviere sie mit `/verbose` + `/thinking`.

---

## Installation

```bash
pip install cheetahclaws
```

Funktioniert unter **Linux, macOS, WSL2 und Android (Termux)** (Python 3.10+). Der erste Start führt dich durch die Einrichtung von Anbieter + API-Key; jederzeit erneut ausführbar mit `cheetahclaws --setup`.

> **Windows:** natives Windows wird nicht unterstützt – nutze [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). **Android/Termux:** `pkg install python git && pip install cheetahclaws`.

### Alternative: Ein-Zeilen-Installationsskript

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

Lade nach der Installation deine Shell neu, damit `cheetahclaws` im PATH liegt:

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### Alternative: Installation mit `pip` aus dem Quellcode

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### Optionale Extras

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

### Alternative: Installation mit `uv`

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### Alternative: direkt aus dem Quellcode ausführen (ohne Installation)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## Nutzung: Closed-Source-API-Modelle

Jeder Cloud-Anbieter folgt demselben Muster – exportiere seinen API-Key (siehe die Tabelle [Unterstützte Modelle](#closed-source-api) für den Env-Var-Namen), wähle dann ein Modell:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

Key-Beschaffungsseiten der Anbieter: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat).

**AWS Bedrock / Azure / Vertex** verwenden die Form `litellm/<provider>/<model>` (`pip install ".[litellm]"`) – vollständige Env-Var-Rezepte in [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

> **Vollständige Anleitung pro Anbieter** – die Key-Beschaffungsseite jedes Anbieters + Beispiel-Modellbefehle sowie Bedrock-/Azure-/Vertex-Env-Var-Rezepte: [docs/guides/usage.md](../guides/usage.md).

---

## Nutzung: Open-Source-Modelle (lokal)

### Ollama (empfohlen)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

Lade [LM Studio](https://lmstudio.ai) herunter, hole dir ein GGUF-Modell, starte seinen **Local Server** (Port 1234), dann:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / selbstgehosteter OpenAI-kompatibler Server

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

Der Name nach `custom/` muss mit dem `--served-model-name` des Servers übereinstimmen. Für die Web-UI persistiert `--web --model custom/<name>` das Modell, bevor der Server startet. Entfernter Server? Richte `CUSTOM_BASE_URL` auf dessen IP.

> **Vollständige Lokalmodell-Anleitung** – Ollama Schritt für Schritt, LM Studio, vLLM + Web-UI: [docs/guides/usage.md](../guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (gehostet, OpenAI-kompatibel)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** stellt DeepSeek, Qwen, GLM, Kimi, MiniMax und mehr hinter einem OpenAI-kompatiblen Endpunkt bereit, über den abhängigkeitsfreien `custom/`-Adapter:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> Jede Atlas-Chat-Modell-ID funktioniert auf dieselbe Weise – **vollständige Liste aller 59 Modelle:** [docs/guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## Format des Modellnamens

Drei gleichwertige Formen werden akzeptiert:

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**Automatische Erkennung per Präfix:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

---

## Trading-Agent

Ein eingebautes Modul für KI-Trading-Analyse + Backtesting (`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4 Strategien (`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), BM25-Speicher vergangener Situationen, US-/HK-/A-Aktien- + Krypto-Märkte mit Daten-Fallbacks ohne API-Key. Geführtes Untermenü über `/ssj` → **Trading**.

> **Vollständige Anleitung:** [docs/guides/trading.md](../guides/trading.md)

---

## Web-UI

Eine produktionsreife Browser-Oberfläche – echte Benutzerkonten (bcrypt + JWT), SQLite-gestützter Verlauf, Ops-Endpunkte – bereitgestellt von der Python-Standardbibliothek + zehn Vanilla-JS-Modulen (kein Node.js / React / Build-Schritt).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

Öffne `http://localhost:<port>/chat` – das erste Konto wird zum Admin. Umfasst Streaming-Chat (WS) + SSE-Slash-Befehle, persistente Sitzungen mit Ordnern/Suche/Markdown-Export, Werkzeugkarten, Inline-Berechtigungsgenehmigung, Einstellungsbereich, Hell-/Dunkel-/System-Theme sowie `/health`- + `/metrics`-Endpunkte. Ein vollständiges xterm.js-PTY-Terminal liegt unter `/` (100 % CLI-Parität).

> **Vollständige Anleitung:** [docs/guides/web-ui.md](../guides/web-ui.md) · **Docker / Home-Server:** [docs/guides/docker.md](../guides/docker.md) · **Native Desktop-App:** [desktop/README.md](../../desktop/README.md)

---

## Dokumentation

Ausführliche Anleitungen liegen in [`docs/guides/`](../guides/), damit dieses README fokussiert bleibt:

| Anleitung | Was enthalten ist |
|---|---|
| [**Funktionen (vollständig)**](../guides/features.md) | Die vollständige Funktionstabelle – jede Zeile mit allen Details (Kontextkompression, Auto-Fanout, Themes, Trading-/Research-/Agents-Beschreibungen) |
| [**Nutzung (alle Anbieter)**](../guides/usage.md) | Einrichtung pro Anbieter + Beispielbefehle: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm sowie lokales Ollama/LM Studio/vLLM |
| [**Web-UI**](../guides/web-ui.md) | Chat-UI, PTY-Terminal, API-Endpunkte, Einstellungen, Auth, SSE-Streaming |
| [**Desktop-App**](../../desktop/README.md) | Native-Fenster-Hülle (Electron), die die lokale Web-UI umschließt; baue eine eigenständige `.dmg`/`.exe`/`.AppImage` |
| [**Docker / Home-Server**](../guides/docker.md) | Dockerfile + compose: Web-UI + Brücken in einem Container, Host-Ollama, Workspace-Mount |
| [**Referenz**](../guides/reference.md) | CLI, 50+ Befehle, 33 eingebaute Werkzeuge, Sitzungssuche, Fehlerklassifizierung, Werkzeug-Cache |
| [**Erweiterungen**](../guides/extensions.md) | Speicher, Skills, Sub-Agenten, MCP-Server, Plugins, Monitor, autonome Agenten |
| [**Brücken**](../guides/bridges.md) | Einrichtung von Telegram, WeChat, Slack, QQ + Fernsteuerung von deinem Telefon |
| [**Sicherheit & Env-Vars**](../guides/security.md) | Bedrohungsmodell, `CHEETAHCLAWS_*`-Variablen, Umgang mit Bot-Tokens, Bash-Denylist, FS-Sandbox, CSRF |
| [**Voice & Video**](../guides/voice-and-video.md) | Offline-Whisper-Spracheingabe, Video-Fabrik, TTS-Fabrik |
| [**Trading**](../guides/trading.md) | Multi-Agent-Analyse, Backtesting, BM25-Speicher, Daten-Fallbacks, SSJ-Integration |
| [**Erweitert**](../guides/advanced.md) | Brainstorm, SSJ, Tmux, proaktive Überwachung, Checkpoints, Plan-Modus, Sitzungen, Cloud-Sync |
| [**Vergleich**](../guides/comparison.md) | Vollständige Positionierung gegenüber Claude Code und OpenClaw – Übersichtstabellen, die Stärken beider Seiten, zentrale Designunterschiede |
| [**Rezepte**](../guides/recipes.md) | 12 Schritt-für-Schritt-Beispiele: Code-Review, Fernsteuerung, Research, Bugfix, Browsen, E-Mail, PDF/Excel |
| [**FAQ**](../guides/faq.md) | Die vollständige FAQ (MCP, Modelle/Anbieter, CLI/Scripting, Voice) |
| [**Plugin-Erstellung**](../guides/plugin-authoring.md) · [Beispiel](../../examples/example-plugin/) | Baue ein Plugin: Werkzeuge, Befehle, Skills, MCP; Starter-Vorlage |
| [**Research Lab**](../guides/research-lab.md) | `/lab start <topic>` – autonomes Multi-Agent-Verfassen von Papern mit gesandboxten Experimenten |
| [**Agent OS**](../agent-os.md) · [RFC-Index](../RFC/) | Die `kernel/`-Schicht + alle Design-Notizen (RFC 0001-0032) |
| [**Mitwirken**](../../CONTRIBUTING.md) | Projektstruktur, Architektur-Anleitung, PR-Checkliste |

---

## Kurzreferenz

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

Siehe die [Referenz-Anleitung](../guides/reference.md) für alle 50+ Slash-Befehle, Werkzeuge und Konfigurationsoptionen.

---

## Mitwirken

Wir freuen uns über Beiträge! Siehe die [Mitwirken-Anleitung](../../CONTRIBUTING.md) für Architektur, Konventionen und die PR-Checkliste.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

Baust du ein Plugin? Siehe die [Anleitung zur Plugin-Erstellung](../guides/plugin-authoring.md) und die [Beispielvorlage](../../examples/example-plugin/).

---

## FAQ

Ein paar häufige Fragen – die **vollständige FAQ** findest du in [docs/guides/faq.md](../guides/faq.md).

**F: Wie füge ich einen MCP-Server hinzu?**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**F: Werkzeugaufrufe funktionieren mit meinem lokalen Ollama-Modell nicht (es beschreibt nur immer weiter, was es tun würde, statt es zu tun).**
CheetahClaws stellt jetzt automatisch Werkzeugaufrufe wieder her, die lokale Modelle als **Text** ausgeben (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) statt in Ollamas strukturiertem Feld, sodass die meisten Modelle mit Funktionsaufruf Werkzeuge sofort ausführen. Für beste Zuverlässigkeit nutze ein Modell mit Funktionsaufruf – `qwen2.5-coder`, `llama3.3`, `mistral` oder `phi4`. Kleine Modelle sind bei der agentischen Werkzeugnutzung außerdem schwächer als Cloud-Modelle, erwarte also, dass sie klarere, konkretere Prompts brauchen.

**F: Nach der Installation unter macOS erscheint `cheetahclaws: command not found` und es wurde keine `~/.zshrc` erstellt.**
Lade zuerst deine Shell neu: `source ~/.zshrc` (zsh) oder `source ~/.bash_profile` (bash). Der Installer erstellt `~/.zshrc`, falls sie fehlt, verlinkt das Binary per Symlink nach `~/.local/bin` und fügt es dem PATH hinzu. Falls du eine ältere Version installiert hast, führe entweder den Installer erneut aus oder füge diese Zeile selbst hinzu: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

Mehr – entferntes vLLM, API-Kosten (`/cost`), mehrere Keys pro Sitzung, Standardmodell projektübergreifend, Eingabe per Pipe, Voice-Einrichtung, Behebung von wirrem Text – wird alles in [docs/guides/faq.md](../guides/faq.md) beantwortet.

---

## Zitation
Wenn du das Repository nützlich findest, zitiere bitte die Studie
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


## Dank an alle Mitwirkenden:

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
