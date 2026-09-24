[English](../../README.md) | [中文](README.CN.MD) | [한국어](README.KO.MD) | [日本語](README.JP.MD) | Français | [Deutsch](README.DE.MD) | [Español](README.ES.MD) | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong> : une infrastructure de harnais d'agent rapide et facile à utiliser pour les systèmes d'IA à horizon long, multi-modèles et utilisant des outils</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">Site web</a>
    ·
    <a href="https://arxiv.org/pdf/2605.26112">Scaling the Harness</a>
    ·
    <a href="https://github.com/SafeRL-Lab/cheetahclaws/issues">Signaler un problème</a>
    ·
    <a href="https://pypi.org/project/cheetahclaws/">
      <img src="https://img.shields.io/badge/downloads-9.6K-blue" alt="Downloads 9.6K" align="absmiddle">
    </a>
  </p>
</div>


### Installation rapide

```bash
pip install cheetahclaws
```

Puis lancez simplement :

```bash
cheetahclaws        # start chatting!
```

Autres méthodes d'installation : [script d'installation en une ligne](#alternative--script-dinstallation-en-une-ligne) | [installation depuis les sources](#alternative--installation-avec-pip-depuis-le-code-source) | [installation avec uv](#alternative--installation-avec-uv) | [exécution directe depuis les sources](#alternative--exécution-directe-depuis-les-sources-sans-installation) | [détails complets d'installation](#installation)

> 🖥️ **Vous préférez une application native ?** Une version desktop (Electron) englobe toute l'interface de chat dans une fenêtre — sans terminal. Voir [`desktop/`](../../desktop/README.md).

## 🔥🔥🔥 Actualités (heure du Pacifique)

- 9 juillet 2026 : **Image Docker officielle + publication en une commande.** Image pré-compilée sur Docker Hub (`docker pull chauncygu/cheetahclaws`) pour exécuter l'interface Web sans cloner le dépôt ; corrige une `PermissionError` au premier lancement en pré-créant les répertoires `.cheetahclaws`/`workspace` appartenant à l'utilisateur non-root, rend l'`image` de compose surchargeable via `CHEETAH_IMAGE`, et ajoute `scripts/docker-publish.sh` (lecture automatique de la version, multi/mono-architecture). Nouvelles sections de docs : **Pull from Docker Hub** et **Interactive setup / CLI mode**. [Détails](../news.md)
- 8 juillet 2026 : la nouvelle commande **`/workspace`** gère des répertoires de travail isolés sous `~/.cheetahclaws/workspaces` (`list`/`switch`/`default`/`create`/`delete`) (PR #162) ; le basculement automatique au démarrage est **optionnel** via `workspace_auto` (désactivé par défaut, donc le lancement dans un répertoire de projet reste inchangé), et `default` est désormais une clé persistante distincte du dernier utilisé. [Détails](../news.md)
- 6 juillet 2026 (**v3.5.84**) : **`/image` enrichit désormais le prompt avec du texte OCR local** afin que même les modèles sans vision puissent traiter les captures d'écran du presse-papiers (dumps d'erreurs, code, tableaux) ; ne s'exécute que si `pytesseract`/`tesseract` sont installés et se désactive entièrement via `CHEETAHCLAWS_IMAGE_OCR=0`. [Détails](../news.md)
- 28 juin 2026 : nouveau mode de permission **`accept-edits`** (exécution automatique des modifications de fichiers, tout en demandant confirmation avant tout Bash non autorisé) — le juste milieu entre `auto` et `accept-all` ; expose également le mode `plan` existant dans `/permissions` et corrige la description trompeuse du mode `auto` dans le prompt. [Détails](../news.md)
- 28 juin 2026 : l'**obsolescence de la mémoire** s'ancre désormais sur une date `last_verified` plutôt que sur le mtime du fichier, de sorte que lire une mémoire ne peut plus faussement rafraîchir une mémoire obsolète (PR #150) ; le nouvel outil **`MemoryVerify`** est la seule chose qui réinitialise l'horloge, le prompt demande à l'agent de l'appeler après re-vérification, et le manifeste de mémoire injecté est classé par ancienneté de vérification. [Détails](../news.md)
- 23 juin 2026 (**v3.5.83**) : documentation allégée (actualités du README → une ligne chacune, liste des 59 modèles Atlas → usage.md, FAQ élaguée) et ajout d'une **application desktop** native (coquille Electron englobant l'interface web) sous `desktop/` ; format de chaîne de version unifié en `v3.5.x`. [Détails](../news.md)
- 16 juin 2026 : tous les modules internes vivent désormais sous un unique paquet `cheetahclaws` (`from cheetahclaws import kernel`), supprimant les plantages de collision de noms `sys.path` au démarrage — ne casse que si vous importez directement les composants internes ; suite complète au vert (2449 réussis). [Détails](../news.md)
- 6 juin 2026 (**v3.5.82**) : l'installation sur macOS place désormais de manière fiable `cheetahclaws` dans le PATH, et les modèles Ollama locaux qui émettent des appels d'outils sous forme de texte les exécutent désormais réellement (deux corrections issues de #131). [Détails](../news.md)
- 5 juin 2026 : budgets de tokens/coûts contrôlables par l'utilisateur — `/budget $5` / `/budget daily $20` plafonnent les dépenses par session ou par jour, appliqués avant chaque appel de modèle. [Détails](../news.md)
- 5 juin 2026 : le streaming Markdown adaptatif maintient la sortie en direct correcte sur tous les appareils en sélectionnant automatiquement un niveau par appareil ; ajoute également une grille visuelle `/context` et un contexte de 1M pour `deepseek-v4-flash`. [Détails](../news.md)


Pour plus d'actualités, voir [ici](../news.md).

---

## Sponsor

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws : une infrastructure de harnais d'agent native Python **rapide** et **facile à utiliser**, **prenant en charge n'importe quel modèle**, tels que Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax, et des modèles open-source locaux via Ollama ou tout point de terminaison compatible OpenAI.

---

## Sommaire
  * [Pourquoi CheetahClaws](#pourquoi-cheetahclaws)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [Fonctionnalités](#fonctionnalités)
  * [Modèles pris en charge](#modèles-pris-en-charge)
  * [Installation](#installation)
  * [Utilisation : modèles API propriétaires](#utilisation--modèles-api-propriétaires)
  * [Utilisation : modèles open-source (locaux)](#utilisation--modèles-open-source-locaux)
  * [Format du nom de modèle](#format-du-nom-de-modèle)
  * [Agent de trading](#agent-de-trading)
  * [Interface Web](#interface-web)
  * [Documentation](#documentation) (guides pour toutes les fonctionnalités)
  * [Contribuer](#contribuer) · [FAQ](#faq) · [Citation](#citation)


### Démos

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>Exécution d'une tâche dans le terminal</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Interface Web : chat dans le navigateur — barre latérale, cartes d'outils, invites d'approbation, streaming Markdown</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Agent de trading autonome</i></sub></div>

> D'autres démos animées (revue de code, `/research`, `/brainstorm`, `/lab`, passerelles Telegram/WeChat/Slack) sont disponibles dans [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/).

---

## Pourquoi CheetahClaws

Claude Code est un assistant de codage IA puissant et de qualité production — mais son code source est un bundle TypeScript/Node compilé d'environ 12 Mo (~1 300 fichiers, ~283K lignes), étroitement couplé à l'API Anthropic, difficile à modifier et impossible à exécuter avec un modèle local ou alternatif.

**CheetahClaws** réimplémente la même boucle centrale en ~90K lignes de Python lisible — en gardant ce dont vous avez besoin, en abandonnant ce dont vous n'avez pas besoin, et en ajoutant la prise en charge multi-fournisseurs + modèles locaux. Comparaison complète : [../guides/comparison.md](../guides/comparison.md).

| Dimension | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Langage | TypeScript + React/Ink | Python 3.8+ |
| Fichiers source / LdC | ~1 332 fichiers / ~283K | ~315 fichiers / ~90K (cœur ; ~127K avec les tests) |
| Outils / commandes intégrés | 44+ / 88 | 27 / 50+ |
| Fournisseurs de modèles | Anthropic uniquement | 8+ (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| Modèles locaux | Non | Oui — Ollama, LM Studio, vLLM, tout point de terminaison compatible OpenAI |
| Étape de build | Oui (Bun + esbuild) | Non — `python cheetahclaws.py` |
| Extensibilité | Fermée (au moment de la compilation) | Ouverte — `register_tool()` à l'exécution, compétences Markdown, plugins git, MCP |
| Entrée vocale | WebSocket propriétaire (OAuth) | Whisper local / OpenAI — fonctionne hors ligne |

**Là où Claude Code gagne :** interface React/Ink plus riche, plus d'outils intégrés, fonctionnalités d'entreprise (MDM, synchronisation des permissions d'équipe, OAuth/keychain), extraction de mémoire pilotée par IA, fiabilité de production en binaire unique.

**Là où CheetahClaws gagne :** basculement vers n'importe quel modèle (`--model`/`/model`, sans recompilation) y compris une prise en charge complète locale/hors ligne ; une boucle d'agent lisible dans un seul fichier (`agent.py`, ~740 lignes) ; zéro build ; enregistrement d'outils à l'exécution + MCP + plugins git + compétences Markdown ; graphe de dépendances des tâches (`blocks`/`blocked_by`) ; compression de contexte à deux couches ; voix hors ligne ; synchronisation de session dans le cloud ; passerelles vers Telegram/WeChat/Slack/QQ.

**À qui s'adresse-t-il :** aux développeurs qui veulent un assistant de codage local/non-Anthropic, aux chercheurs qui étudient le fonctionnement des assistants agentiques, et aux équipes qui ont besoin d'une base modifiable — sans chaîne de build Node.js.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw) est un autre assistant open-source populaire (TypeScript/Node). Les deux ont des **objectifs principaux différents** — OpenClaw est un assistant personnel de la vie quotidienne à travers les canaux de messagerie ; CheetahClaws est un outil de développement/codage.

| Dimension | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| Lignes de code | ~245K (~10 349 fichiers) | ~90K cœur (~315 fichiers) |
| Objectif principal | Assistant personnel à travers les canaux | Assistant de codage IA / outil de dev |
| Architecture | Démon Gateway toujours actif + applications | REPL de terminal sans installation |
| Canaux de messagerie | 20+ (WhatsApp · Signal · iMessage · Discord · Matrix · …) | Terminal + passerelles Telegram · WeChat · Slack · QQ |
| Modèles locaux / hors ligne | Limité | Complet — Ollama · vLLM · LM Studio · tout compatible OpenAI |
| Outils d'édition de code | Contrôle du navigateur, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| Mobile / Live Canvas | Oui (barre de menu + iOS/Android, A2UI) | — |
| Prise en charge MCP | — | Oui (stdio/SSE/HTTP) |
| Modifiabilité | 245K lignes, plus difficile à modifier | ~90K lignes — boucle d'agent dans un seul fichier |

| Si vous voulez… | Utilisez |
|---|---|
| Un assistant personnel sur WhatsApp/Signal/Discord, orienté mobile, automatisation du navigateur + Canvas | **OpenClaw** |
| Un assistant de codage IA dans votre terminal, modèles entièrement hors ligne/locaux, basculement multi-fournisseurs, un code source lisible en une après-midi | **CheetahClaws** |

> Comparaison complète — les atouts des deux côtés + les principales différences de conception (boucle d'agent, enregistrement d'outils, compression de contexte, mémoire) : [../guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw).

---

## Fonctionnalités

| Fonctionnalité | Détails |
|---|---|
| Multi-fournisseurs | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · Point de terminaison personnalisé |
| Boucle d'agent | API en streaming + boucle automatique d'utilisation d'outils ; toute la boucle est dans `agent.py` |
| 28 outils intégrés | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(outils MCP + plugins ajoutés automatiquement)* |
| Intégration MCP | Connectez n'importe quel serveur MCP (stdio/SSE/HTTP) ; outils enregistrés automatiquement — voir le [guide des extensions](../guides/extensions.md) |
| Système de plugins | Installer/activer/mettre à jour des plugins depuis des URL git ou des chemins locaux ; multi-portée ; moteur de recommandation |
| Gestion des tâches | `TaskCreate/Update/Get/List`, IDs séquentiels, arêtes de dépendance, persistées dans `.cheetahclaws/tasks.json` |
| Compression de contexte | Quatre couches coopérantes — plafond dynamique de `max_tokens`, registre de fenêtre de contexte par modèle, découpage à deux couches + résumé par IA à 70 %, et éclatement automatique pour les sorties d'outils surdimensionnées. [Détails](../guides/reference.md) |
| Mémoire persistante | Double portée (utilisateur + projet), 4 types, métadonnées de confiance/source, détection de conflits, recherche pondérée par ancienneté, `/memory consolidate`. Obsolescence ancrée sur la vérification — la fraîcheur suit une date `last_verified` (et non le mtime du fichier), de sorte que lire une mémoire ne peut pas la rafraîchir faussement ; seul `MemoryVerify` réinitialise l'horloge. [Détails](../guides/features.md) |
| Multi-agent | Créer des sous-agents typés (coder/reviewer/researcher/…), isolation par git-worktree, mode arrière-plan |
| Système de permissions | La confirmation n'est demandée que pour les actions pouvant modifier vos fichiers, exécuter du code arbitraire ou sortir de la session. Tous les outils en lecture seule, les pipelines shell en lecture seule (`git log \| head`) et la création d'un **nouveau** fichier dans l'espace de travail s'exécutent sans invite. Répondre `s` accorde **cette seule commande ou ce seul fichier** jusqu'à la fin de la session — l'alternative circonscrite à accept-all (`/permissions clear` les supprime). Modes : `auto` / `accept-edits` / `accept-all` / `manual` / `plan` ; une liste de refus stricte bloque les commandes destructrices dans tous les modes. [Détails](../guides/security.md#what-runs-without-asking-auto-mode) |
| Points de contrôle & mode plan | Instantané automatique de la conversation + fichiers à chaque tour (`/checkpoint`, `/rewind`) ; mode d'analyse en lecture seule `/plan` |
| Commandes slash & thèmes | 50+ commandes slash avec complétion par Tab ; `/theme` propose 15 palettes soignées |
| Brainstorm → Worker | `/brainstorm` lance un débat à N personas → `todo_list.txt` ; `/worker` implémente automatiquement les tâches en attente |
| Mode développeur SSJ | `/ssj` — menu de puissance persistant enchaînant Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor, etc. |
| Agent de trading | `/trading` analyse multi-agents, backtesting, calibration en paper-trade, portefeuilles MV. [Guide](../guides/trading.md) |
| Monitor | `/monitor` s'abonne à des sujets surveillés par IA selon un calendrier (arxiv / bourse / crypto / actualités / personnalisé), pousse des rapports vers les passerelles/console |
| Recherche (multi-sources) | `/research` s'étale sur **20 sources** avec tableau de chaleur d'attention, extraction d'entités, sparkline de tendance, mode comparaison. [Guide](../guides/research.md) |
| Agents autonomes | `/agent` boucles en arrière-plan à partir de modèles Markdown ; résumés d'itérations poussés via passerelle ; garde-fou d'arrêt en cas de stagnation |
| Passerelles + contrôle à distance | Telegram · WeChat · Slack · QQ — aller-retour de chat, passthrough des commandes slash, file d'attente de jobs par passerelle (`!jobs`/`!retry`/`!cancel`). [Guide](../guides/bridges.md) |
| Voix / Vision / Vidéo / TTS | Whisper hors ligne `/voice` ; vision du presse-papiers `/image` (local + cloud) ; usines de contenu `/video` + `/tts`. [Guide](../guides/voice-and-video.md) |
| Interface Web | `--web` — chat multi-utilisateurs dans le navigateur + terminal PTY. [Guide](../guides/web-ui.md) |
| Plus | Intégration Tmux · échappement shell `!cmd` · surveillance proactive · arrêt forcé par 3×Ctrl+C · persistance de session · synchronisation GitHub-Gist `/cloudsave` · suivi des coûts · mode non interactif `--print` |

> **Référence complète des fonctionnalités** — chaque ligne ci-dessus avec tous les détails (couches de compression de contexte, éclatement automatique, 15 thèmes, les descriptifs complets Trading/Research/Agents, …) : [../guides/features.md](../guides/features.md).

---

## Modèles pris en charge

### Propriétaires (API)

| Fournisseur | Modèles d'exemple | Contexte | Variable d'env. de clé API |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (niveau gratuit) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ modèles, une seule clé)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | variable | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ modèles, une seule clé)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | variable | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(via litellm)_ | `litellm/<provider>/<model>` | variable | spécifique au fournisseur |

> **Passerelle `openrouter/` :** une seule clé pour plus de 400 modèles, tous fournisseurs confondus. L'ID du modèle conserve le chemin upstream `<vendor>/<model>` d'OpenRouter, l'appel porte donc un double préfixe : `openrouter/deepseek/deepseek-v4-flash`. Pour imposer le fournisseur upstream (et la quantification) qui traite la requête, ajoutez `@<provider>[/<quantization>]` — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — envoyé comme objet `provider` dans le corps de la requête plutôt que collé à l'ID du modèle. Voir [usage.md](../guides/usage.md#openrouter-400-models-one-key).

> **Passerelle `requesty/` :** même principe : tout ce qui suit `requesty/` est envoyé comme ID du modèle, soit un chemin de catalogue `<vendor>/<model>` (`requesty/openai/gpt-4o-mini`), soit un ID de politique gérée (`requesty/claude-sonnet-4-6`). Les ID de politique gérée terminés par `@eu` (`requesty/gpt-5-mini@eu`) ne passent que par des fournisseurs situés dans l'UE. Voir [usage.md](../guides/usage.md#requesty-700-models-one-key).

> **Adaptateur `litellm/` :** achemine vers 100+ fournisseurs derrière un seul SDK — principalement pour les upstreams à l'authentification délicate (SigV4 de Bedrock, routage de déploiement Azure, JWT de compte de service Vertex). Pour les points de terminaison standard au format OpenAI, préférez l'adaptateur `custom/` sans dépendance. Installez avec `pip install ".[litellm]"`. Voir [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

### Open-source (local via Ollama)

| Modèle | Taille | Points forts | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **Le meilleur pour le codage** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | Usage général | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | Raisonnement, maths | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | Rapide / MoE performant | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | Raisonnement / ouvert / code | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **Vision** | `ollama pull llava` |

> **L'appel d'outils** nécessite un modèle capable d'appeler des fonctions — recommandés : `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Les modèles qui émettent des appels d'outils sous forme de **texte** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) au lieu du champ structuré d'Ollama sont récupérés automatiquement, si bien qu'ils exécutent les outils d'emblée plutôt que de simplement en discuter. Les modèles de raisonnement (`deepseek-r1`, `qwen3`, `gemma4`) diffusent des blocs `<think>` natifs ; activez-les avec `/verbose` + `/thinking`.

---

## Installation

```bash
pip install cheetahclaws
```

Fonctionne sur **Linux, macOS, WSL2 et Android (Termux)** (Python 3.10+). Le premier lancement vous guide à travers la configuration du fournisseur + de la clé API ; relancez à tout moment avec `cheetahclaws --setup`.

> **Windows :** Windows natif n'est pas pris en charge — utilisez [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install). **Android/Termux :** `pkg install python git && pip install cheetahclaws`.

### Alternative : script d'installation en une ligne

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

Après l'installation, rechargez votre shell pour que `cheetahclaws` soit dans le PATH :

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### Alternative : installation avec `pip` depuis le code source

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### Extras optionnels

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

### Alternative : installation avec `uv`

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### Alternative : exécution directe depuis les sources (sans installation)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## Utilisation : modèles API propriétaires

Chaque fournisseur cloud suit le même schéma — exportez sa clé API (voir le tableau [Modèles pris en charge](#propriétaires-api) pour le nom de la variable d'environnement), puis sélectionnez un modèle :

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

Pages d'obtention de clé par fournisseur : [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat).

**AWS Bedrock / Azure / Vertex** utilisent la forme `litellm/<provider>/<model>` (`pip install ".[litellm]"`) — recettes complètes de variables d'environnement dans [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider).

> **Guide complet par fournisseur** — la page d'obtention de clé de chaque fournisseur + des exemples de commandes de modèle, ainsi que les recettes de variables d'environnement Bedrock/Azure/Vertex : [../guides/usage.md](../guides/usage.md).

---

## Utilisation : modèles open-source (locaux)

### Ollama (recommandé)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

Téléchargez [LM Studio](https://lmstudio.ai), récupérez un modèle GGUF, démarrez son **Local Server** (port 1234), puis :

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / serveur auto-hébergé compatible OpenAI

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

Le nom après `custom/` doit correspondre au `--served-model-name` du serveur. Pour l'interface Web, `--web --model custom/<name>` persiste le modèle avant le démarrage du serveur. Serveur distant ? Pointez `CUSTOM_BASE_URL` vers son IP.

> **Guide complet des modèles locaux** — Ollama pas à pas, LM Studio, vLLM + interface Web : [../guides/usage.md](../guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (hébergé, compatible OpenAI)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** sert DeepSeek, Qwen, GLM, Kimi, MiniMax et plus derrière un unique point de terminaison compatible OpenAI, via l'adaptateur `custom/` sans dépendance :

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> N'importe quel identifiant de modèle de chat Atlas fonctionne de la même manière — **liste complète des 59 modèles :** [../guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## Format du nom de modèle

Trois formes équivalentes sont acceptées :

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**Auto-détection par préfixe :** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

---

## Agent de trading

Un module intégré d'analyse de trading IA + backtesting (`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4 stratégies (`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), mémoire BM25 des situations passées, marchés US/HK/actions A + crypto avec repli de données sans clé API. Sous-menu guidé via `/ssj` → **Trading**.

> **Guide complet :** [../guides/trading.md](../guides/trading.md)

---

## Interface Web

Une interface de navigateur prête pour la production — véritables comptes utilisateurs (bcrypt + JWT), historique adossé à SQLite, points de terminaison d'exploitation — servie par la bibliothèque standard Python + dix modules JS vanilla (pas de Node.js / React / étape de build).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

Ouvrez `http://localhost:<port>/chat` — le premier compte devient administrateur. Inclut le chat en streaming (WS) + commandes slash SSE, sessions persistantes avec dossiers/recherche/export Markdown, cartes d'outils, approbation de permission en ligne, panneau de paramètres, thème clair/sombre/système, et points de terminaison `/health` + `/metrics`. Un terminal PTY complet xterm.js est disponible à `/` (parité CLI à 100 %).

> **Guide complet :** [../guides/web-ui.md](../guides/web-ui.md) · **Docker / serveur domestique :** [../guides/docker.md](../guides/docker.md) · **Application desktop native :** [desktop/README.md](../../desktop/README.md)

---

## Documentation

Des guides détaillés vivent dans [`docs/guides/`](../guides/) pour garder ce README concentré :

| Guide | Contenu |
|---|---|
| [**Fonctionnalités (complet)**](../guides/features.md) | Le tableau complet des fonctionnalités — chaque ligne avec tous les détails (compression de contexte, éclatement automatique, thèmes, descriptifs Trading/Research/Agents) |
| [**Utilisation (tous les fournisseurs)**](../guides/usage.md) | Configuration par fournisseur + commandes d'exemple : Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm, et Ollama/LM Studio/vLLM en local |
| [**Interface Web**](../guides/web-ui.md) | Interface de chat, terminal PTY, points de terminaison API, paramètres, authentification, streaming SSE |
| [**Application desktop**](../../desktop/README.md) | Coquille en fenêtre native (Electron) qui englobe l'interface web locale ; construisez un `.dmg`/`.exe`/`.AppImage` autonome |
| [**Docker / serveur domestique**](../guides/docker.md) | Dockerfile + compose : interface web + passerelles dans un seul conteneur, Ollama sur l'hôte, montage de l'espace de travail |
| [**Référence**](../guides/reference.md) | CLI, 50+ commandes, 33 outils intégrés, recherche de session, classification des erreurs, cache d'outils |
| [**Extensions**](../guides/extensions.md) | Mémoire, Compétences, Sous-agents, serveurs MCP, Plugins, Monitor, Agents autonomes |
| [**Passerelles**](../guides/bridges.md) | Configuration Telegram, WeChat, Slack, QQ + contrôle à distance depuis votre téléphone |
| [**Sécurité & variables d'env.**](../guides/security.md) | Modèle de menace, variables `CHEETAHCLAWS_*`, gestion des jetons de bot, liste noire Bash, bac à sable du système de fichiers, CSRF |
| [**Voix & Vidéo**](../guides/voice-and-video.md) | Entrée vocale Whisper hors ligne, usine à vidéos, usine TTS |
| [**Trading**](../guides/trading.md) | Analyse multi-agents, backtesting, mémoire BM25, replis de données, intégration SSJ |
| [**Avancé**](../guides/advanced.md) | Brainstorm, SSJ, Tmux, surveillance proactive, points de contrôle, mode plan, sessions, synchronisation cloud |
| [**Comparaison**](../guides/comparison.md) | Positionnement complet vs Claude Code et OpenClaw — tableaux en un coup d'œil, atouts des deux côtés, principales différences de conception |
| [**Recettes**](../guides/recipes.md) | 12 exemples pas à pas : revue de code, contrôle à distance, recherche, correction de bug, navigation, e-mail, PDF/Excel |
| [**FAQ**](../guides/faq.md) | La FAQ complète (MCP, modèles/fournisseurs, CLI/scripting, voix) |
| [**Création de plugins**](../guides/plugin-authoring.md) · [Exemple](../../examples/example-plugin/) | Construire un plugin : outils, commandes, compétences, MCP ; modèle de démarrage |
| [**Labo de recherche**](../guides/research-lab.md) | `/lab start <topic>` — rédaction autonome de papiers multi-agents avec expériences en bac à sable |
| [**Agent OS**](../agent-os.md) · [Index RFC](../RFC/) | La couche `kernel/` + toutes les notes de conception (RFC 0001-0032) |
| [**Contribuer**](../../CONTRIBUTING.md) | Structure du projet, guide d'architecture, checklist de PR |

---

## Référence rapide

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

Consultez le [guide de référence](../guides/reference.md) pour l'ensemble des 50+ commandes slash, outils et options de configuration.

---

## Contribuer

Nous accueillons les contributions ! Consultez le [guide de contribution](../../CONTRIBUTING.md) pour l'architecture, les conventions et la checklist de PR.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

Vous construisez un plugin ? Consultez le [guide de création de plugins](../guides/plugin-authoring.md) et le [modèle d'exemple](../../examples/example-plugin/).

---

## FAQ

Quelques questions courantes — la **FAQ complète** est dans [../guides/faq.md](../guides/faq.md).

**Q : Comment ajouter un serveur MCP ?**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**Q : Les appels d'outils ne fonctionnent pas avec mon modèle Ollama local (il ne fait que décrire ce qu'il ferait au lieu de le faire).**
CheetahClaws récupère désormais automatiquement les appels d'outils que les modèles locaux émettent sous forme de **texte** (`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`) au lieu du champ structuré d'Ollama, si bien que la plupart des modèles capables d'appeler des fonctions exécutent les outils d'emblée. Pour une fiabilité optimale, utilisez un modèle capable d'appeler des outils — `qwen2.5-coder`, `llama3.3`, `mistral` ou `phi4`. Les petits modèles sont également moins performants que les modèles cloud pour l'usage agentique des outils, alors attendez-vous à ce qu'ils aient besoin de prompts plus clairs et plus concrets.

**Q : Après l'installation sur macOS, `cheetahclaws: command not found` et aucun `~/.zshrc` n'a été créé.**
Rechargez d'abord votre shell : `source ~/.zshrc` (zsh) ou `source ~/.bash_profile` (bash). L'installateur crée `~/.zshrc` s'il est absent, crée un lien symbolique du binaire dans `~/.local/bin` et l'ajoute au PATH. Si vous avez installé une version plus ancienne, relancez l'installateur ou ajoutez vous-même cette ligne : `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

Plus — vLLM distant, coût de l'API (`/cost`), plusieurs clés par session, modèle par défaut entre projets, redirection d'entrée, configuration vocale, corrections de texte brouillé — sont tous traités dans [../guides/faq.md](../guides/faq.md).

---

## Citation
Si vous trouvez ce dépôt utile, merci de citer l'étude
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


## Merci à tous les contributeurs :

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
