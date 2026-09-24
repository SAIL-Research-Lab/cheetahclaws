[English](../../README.md) | [中文](README.CN.MD) | 한국어 | [日本語](README.JP.MD) | [Français](README.FR.MD) | [Deutsch](README.DE.MD) | [Español](README.ES.MD) | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: 장기 과제, 멀티 모델, 도구 사용 AI 시스템을 위한 빠르고 사용하기 쉬운 에이전트 하네스 인프라</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">웹사이트</a>
    ·
    <a href="https://arxiv.org/pdf/2605.26112">하네스 스케일링</a>
    ·
    <a href="https://github.com/SafeRL-Lab/cheetahclaws/issues">이슈</a>
    ·
    <a href="https://pypi.org/project/cheetahclaws/">
      <img src="https://img.shields.io/badge/downloads-9.6K-blue" alt="Downloads 9.6K" align="absmiddle">
    </a>
  </p>
</div>


### 빠른 설치

```bash
pip install cheetahclaws
```

그런 다음 그냥 실행하세요:

```bash
cheetahclaws        # start chatting!
```

다른 설치 방법: [원라인 설치 스크립트](#대안-원라인-설치-스크립트) | [소스에서 설치](#대안-소스-코드에서-pip으로-설치) | [uv 설치](#대안-uv로-설치) | [소스에서 직접 실행](#대안-소스에서-직접-실행-설치-불필요) | [전체 설치 안내](#설치)

> 🖥️ **네이티브 앱을 선호하시나요?** 데스크톱 빌드(Electron)는 전체 채팅 UI를 하나의 창에 담아 제공하며 터미널이 필요 없습니다. [`desktop/`](../../desktop/README.md)를 참고하세요.

## 🔥🔥🔥 뉴스 (태평양 시간)

- 2026년 7월 9일: **공식 Docker 이미지 + 원커맨드 배포.** Docker Hub에 사전 빌드된 이미지(`docker pull chauncygu/cheetahclaws`)를 제공하여 클론 없이 웹 UI를 실행할 수 있습니다. 비루트 사용자가 소유하는 `.cheetahclaws`/`workspace` 디렉터리를 사전 생성하여 첫 실행 시 발생하던 `PermissionError`를 수정했고, compose의 `image`를 `CHEETAH_IMAGE`로 재정의할 수 있게 했으며, `scripts/docker-publish.sh`(버전 자동 인식, 멀티/싱글 아키텍처)를 추가했습니다. 새 문서 섹션: **Docker Hub에서 가져오기** 및 **대화형 설정 / CLI 모드**. [자세히](../news.md)
- 2026년 7월 8일: 새 **`/workspace`** 명령이 `~/.cheetahclaws/workspaces` 아래의 격리된 작업 디렉터리를 관리합니다(`list`/`switch`/`default`/`create`/`delete`) (PR #162). 시작 시 자동 전환은 `workspace_auto`로 **선택적 활성화**되며(기본값 꺼짐, 따라서 프로젝트 디렉터리에서 실행해도 동작이 변하지 않음), `default`는 이제 마지막 사용 값과 분리된 고정 키가 되었습니다. [자세히](../news.md)
- 2026년 7월 6일 (**v3.5.84**): **`/image`가 이제 로컬 OCR 텍스트로 프롬프트를 보강**하여 비전 모델이 아니어도 클립보드 스크린샷(오류 덤프, 코드, 표)을 처리할 수 있습니다. `pytesseract`/`tesseract`가 설치된 경우에만 실행되며 `CHEETAHCLAWS_IMAGE_OCR=0`으로 완전히 비활성화할 수 있습니다. [자세히](../news.md)
- 2026년 6월 28일: 새 **`accept-edits`** 권한 모드(파일 편집은 자동 실행하되 허용 목록에 없는 Bash는 여전히 확인) — `auto`와 `accept-all` 사이의 중간 지점입니다. 또한 `/permissions`에 기존 `plan` 모드를 노출하고 프롬프트의 오해를 부르는 `auto` 설명을 수정했습니다. [자세히](../news.md)
- 2026년 6월 28일: **메모리 노후화**가 이제 파일 mtime 대신 `last_verified` 날짜를 기준으로 하여, 메모리를 읽는 것만으로 노후된 메모리를 거짓으로 갱신할 수 없습니다(PR #150). 새 **`MemoryVerify`** 도구만이 이 시계를 재설정하며, 프롬프트는 재확인 후 이를 호출하도록 에이전트에게 지시하고, 주입되는 메모리 매니페스트는 검증 최신순으로 정렬됩니다. [자세히](../news.md)
- 2026년 6월 23일 (**v3.5.83**): 문서 간소화(README 뉴스 → 항목당 한 줄, Atlas 59개 모델 목록 → usage.md, FAQ 축소) 및 네이티브 **데스크톱 앱**(웹 UI를 감싸는 Electron 셸)을 `desktop/` 아래에 추가했으며, 버전 문자열 형식을 `v3.5.x`로 통일했습니다. [자세히](../news.md)
- 2026년 6월 16일: 이제 모든 내부 모듈이 단일 `cheetahclaws` 패키지 아래에 위치하여(`from cheetahclaws import kernel`) 시작 시 발생하던 `sys.path` 이름 충돌 크래시를 제거했습니다 — 내부를 직접 임포트하는 경우에만 호환성이 깨집니다. 전체 테스트 통과(2449개 통과). [자세히](../news.md)
- 2026년 6월 6일 (**v3.5.82**): macOS 설치 시 이제 `cheetahclaws`가 안정적으로 PATH에 등록되며, 도구 호출을 텍스트로 내보내던 로컬 Ollama 모델이 이제 실제로 이를 실행합니다(#131의 두 가지 수정). [자세히](../news.md)
- 2026년 6월 5일: 사용자가 제어할 수 있는 토큰/비용 예산 — `/budget $5` / `/budget daily $20`으로 세션 또는 일별 지출 상한을 설정하며, 각 모델 호출 전에 적용됩니다. [자세히](../news.md)
- 2026년 6월 5일: 적응형 Markdown 스트리밍이 기기별 등급을 자동 선택하여 모든 기기에서 실시간 출력을 올바르게 유지합니다. 또한 시각적 `/context` 그리드와 `deepseek-v4-flash`용 1M 컨텍스트를 추가했습니다. [자세히](../news.md)


더 많은 뉴스는 [여기](../news.md)를 참고하세요.

---

## 스폰서

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **빠르고** **사용하기 쉬운** Python 네이티브 에이전트 하네스 인프라로, Claude, GPT, Gemini, Kimi, Qwen, Zhipu, DeepSeek, MiniMax와 같은 **모든 모델을 지원**하며, Ollama나 OpenAI 호환 엔드포인트를 통해 로컬 오픈소스 모델도 지원합니다.

---

## 목차
  * [CheetahClaws를 선택하는 이유](#cheetahclaws를-선택하는-이유)
  * [CheetahClaws vs OpenClaw](#cheetahclaws-vs-openclaw)
  * [기능](#기능)
  * [지원 모델](#지원-모델)
  * [설치](#설치)
  * [사용법: 비공개 소스 API 모델](#사용법-비공개-소스-api-모델)
  * [사용법: 오픈소스 모델 (로컬)](#사용법-오픈소스-모델-로컬)
  * [모델 이름 형식](#모델-이름-형식)
  * [트레이딩 에이전트](#트레이딩-에이전트)
  * [웹 UI](#웹-ui)
  * [문서](#문서) (모든 기능에 대한 가이드)
  * [기여하기](#기여하기) · [자주 묻는 질문](#자주-묻는-질문) · [인용](#인용)


### 데모

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>터미널에서의 작업 실행</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>웹 UI: 브라우저 채팅 — 사이드바, 도구 카드, 승인 프롬프트, Markdown 스트리밍</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>자율 트레이딩 에이전트</i></sub></div>

> 더 많은 애니메이션 데모(코드 리뷰, `/research`, `/brainstorm`, `/lab`, Telegram/WeChat/Slack 브리지)는 [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/)에 있습니다.

---

## CheetahClaws를 선택하는 이유

Claude Code는 강력한 프로덕션 등급 AI 코딩 어시스턴트입니다 — 하지만 그 소스는 컴파일된 약 12MB의 TypeScript/Node 번들(약 1,300개 파일, 약 28.3만 줄)로, Anthropic API에 강하게 결합되어 있어 수정하기 어렵고 로컬 또는 대체 모델로 실행하는 것이 불가능합니다.

**CheetahClaws**는 동일한 핵심 루프를 약 9만 줄의 읽기 쉬운 Python으로 다시 구현합니다 — 필요한 것은 유지하고 불필요한 것은 버리며, 멀티 프로바이더 + 로컬 모델 지원을 추가했습니다. 전체 비교: [../guides/comparison.md](../guides/comparison.md).

| 항목 | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| 언어 | TypeScript + React/Ink | Python 3.8+ |
| 소스 파일 / 코드 줄 수 | 약 1,332개 파일 / 약 28.3만 | 약 315개 파일 / 약 9만 (코어; 테스트 포함 시 약 12.7만) |
| 내장 도구 / 명령 | 44개 이상 / 88개 | 27개 / 50개 이상 |
| 모델 프로바이더 | Anthropic만 | 8개 이상 (Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …) |
| 로컬 모델 | 없음 | 있음 — Ollama, LM Studio, vLLM, 모든 OpenAI 호환 엔드포인트 |
| 빌드 단계 | 있음 (Bun + esbuild) | 없음 — `python cheetahclaws.py` |
| 확장성 | 폐쇄적 (컴파일 타임) | 개방적 — 런타임에서 `register_tool()`, Markdown 스킬, git 플러그인, MCP |
| 음성 입력 | 독점 WebSocket (OAuth) | 로컬 Whisper / OpenAI — 오프라인 작동 |

**Claude Code가 앞서는 부분:** 더 풍부한 React/Ink UI, 더 많은 내장 도구, 엔터프라이즈 기능(MDM, 팀 권한 동기화, OAuth/키체인), AI 기반 메모리 추출, 단일 바이너리 프로덕션 안정성.

**CheetahClaws가 앞서는 부분:** 완전한 로컬/오프라인 지원을 포함한 모든 모델 전환(`--model`/`/model`, 재컴파일 불필요); 하나의 파일에 담긴 읽기 쉬운 에이전트 루프(`agent.py`, 약 740줄); 빌드 불필요; 런타임 도구 등록 + MCP + git 플러그인 + Markdown 스킬; 작업 의존성 그래프(`blocks`/`blocked_by`); 2계층 컨텍스트 압축; 오프라인 음성; 클라우드 세션 동기화; Telegram/WeChat/Slack/QQ 브리지.

**대상 사용자:** 로컬/비-Anthropic 코딩 어시스턴트를 원하는 개발자, 에이전트형 어시스턴트가 어떻게 작동하는지 연구하는 연구자, 그리고 Node.js 빌드 체인 없이 해킹 가능한 베이스라인이 필요한 팀.

---

## CheetahClaws vs OpenClaw

[OpenClaw](https://github.com/openclaw/openclaw)는 또 다른 인기 있는 오픈소스 어시스턴트(TypeScript/Node)입니다. 두 프로젝트는 **주요 목표가 다릅니다** — OpenClaw는 메시징 채널 전반에 걸친 개인 생활 어시스턴트이고, CheetahClaws는 개발자/코딩 도구입니다.

| 항목 | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| 코드 줄 수 | 약 24.5만 (약 10,349개 파일) | 약 9만 코어 (약 315개 파일) |
| 주요 초점 | 채널 전반의 개인 어시스턴트 | AI 코딩 어시스턴트 / 개발 도구 |
| 아키텍처 | 상시 실행 Gateway 데몬 + 앱 | 설치 불필요 터미널 REPL |
| 메시징 채널 | 20개 이상 (WhatsApp · Signal · iMessage · Discord · Matrix · …) | 터미널 + Telegram · WeChat · Slack · QQ 브리지 |
| 로컬 / 오프라인 모델 | 제한적 | 완전 지원 — Ollama · vLLM · LM Studio · 모든 OpenAI 호환 |
| 코드 편집 도구 | 브라우저 제어, Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| 모바일 / Live Canvas | 있음 (메뉴 바 + iOS/Android, A2UI) | — |
| MCP 지원 | — | 있음 (stdio/SSE/HTTP) |
| 해킹 가능성 | 24.5만 줄, 수정 더 어려움 | 약 9만 줄 — 에이전트 루프가 하나의 파일에 |

| 원하는 것이… | 선택 |
|---|---|
| WhatsApp/Signal/Discord의 개인 어시스턴트, 모바일 우선, 브라우저 자동화 + Canvas | **OpenClaw** |
| 터미널의 AI 코딩 어시스턴트, 완전한 오프라인/로컬 모델, 멀티 프로바이더 전환, 하루 오후면 읽을 수 있는 소스 | **CheetahClaws** |

> 전체 비교 — 양측의 강점 + 핵심 설계 차이(에이전트 루프, 도구 등록, 컨텍스트 압축, 메모리): [../guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw).

---

## 기능

| 기능 | 상세 |
|---|---|
| 멀티 프로바이더 | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · 커스텀 엔드포인트 |
| 에이전트 루프 | 스트리밍 API + 자동 도구 사용 루프; 전체 루프가 `agent.py`에 있음 |
| 28개 내장 도구 | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *(MCP + 플러그인 도구 자동 추가)* |
| MCP 통합 | 모든 MCP 서버 연결(stdio/SSE/HTTP); 도구 자동 등록 — [확장 가이드](../guides/extensions.md) 참고 |
| 플러그인 시스템 | git URL 또는 로컬 경로에서 플러그인 설치/활성화/업데이트; 멀티 스코프; 추천 엔진 |
| 작업 관리 | `TaskCreate/Update/Get/List`, 순차 ID, 의존성 엣지, `.cheetahclaws/tasks.json`에 영속화 |
| 컨텍스트 압축 | 협력하는 네 개의 계층 — 동적 `max_tokens` 상한, 모델별 컨텍스트 윈도우 레지스트리, 70%에서의 2계층 축약 + AI 요약, 과대 도구 출력에 대한 자동 팬아웃. [자세히](../guides/reference.md) |
| 영속 메모리 | 이중 스코프(사용자 + 프로젝트), 4가지 유형, 신뢰도/출처 메타데이터, 충돌 감지, 최신성 가중 검색, `/memory consolidate`. 검증 기준 노후화 — 최신성은 파일 mtime이 아닌 `last_verified` 날짜를 추적하므로, 메모리를 읽는 것만으로 거짓 갱신할 수 없고 `MemoryVerify`만이 시계를 재설정합니다. [자세히](../guides/features.md) |
| 멀티 에이전트 | 유형화된 서브 에이전트(coder/reviewer/researcher/…) 생성, git-worktree 격리, 백그라운드 모드 |
| 권한 시스템 | 파일을 변경하거나, 임의의 코드를 실행하거나, 세션 밖에 접근할 수 있는 동작에 대해서만 묻습니다. 읽기 전용 도구, 읽기 전용 셸 파이프라인(`git log \| head`), 작업 공간 안에서의 새 파일 생성은 모두 조용히 실행됩니다. 프롬프트에서 `s`를 선택하면 **그 명령 하나 또는 그 파일 하나**만 세션 동안 허용합니다(accept-all의 범위 제한 대안, `/permissions clear`로 해제). 모드: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`. 하드 거부 목록은 모든 모드에서 호스트 파괴 명령을 차단합니다. [자세히](../guides/security.md#what-runs-without-asking-auto-mode) |
| 체크포인트 & 플랜 모드 | 매 턴 대화 + 파일 자동 스냅샷(`/checkpoint`, `/rewind`); `/plan` 읽기 전용 분석 모드 |
| 슬래시 명령 & 테마 | Tab 자동 완성이 되는 50개 이상의 슬래시 명령; `/theme`가 엄선된 15개 팔레트 제공 |
| Brainstorm → Worker | `/brainstorm`이 N-페르소나 토론을 실행 → `todo_list.txt`; `/worker`가 대기 중인 작업을 자동 구현 |
| SSJ 개발자 모드 | `/ssj` — Brainstorm, Worker, Review, Trading, Agent, Video/TTS, Monitor 등을 연결하는 영속적 파워 메뉴 |
| 트레이딩 에이전트 | `/trading` 멀티 에이전트 분석, 백테스팅, 모의 거래 보정, MV 포트폴리오. [가이드](../guides/trading.md) |
| Monitor | `/monitor`가 예약된 스케줄로 AI 모니터링 주제(arxiv / 주식 / 암호화폐 / 뉴스 / 커스텀)를 구독하고 보고서를 브리지/콘솔로 푸시 |
| Research (멀티 소스) | `/research`가 **20개 소스**로 팬아웃하며 관심도 히트 표, 개체 추출, 트렌드 스파크라인, 비교 모드 제공. [가이드](../guides/research.md) |
| 자율 에이전트 | `/agent` Markdown 템플릿 기반 백그라운드 루프; 반복 요약을 브리지로 푸시; 정체 중단 가드 |
| 브리지 + 원격 제어 | Telegram · WeChat · Slack · QQ — 채팅 왕복, 슬래시 패스스루, 브리지별 작업 큐(`!jobs`/`!retry`/`!cancel`). [가이드](../guides/bridges.md) |
| 음성 / 비전 / 비디오 / TTS | 오프라인 Whisper `/voice`; `/image` 클립보드 비전(로컬 + 클라우드); `/video` + `/tts` 콘텐츠 팩토리. [가이드](../guides/voice-and-video.md) |
| 웹 UI | `--web` — 멀티 사용자 브라우저 채팅 + PTY 터미널. [가이드](../guides/web-ui.md) |
| 그 외 | Tmux 통합 · `!cmd` 셸 이스케이프 · 능동적 모니터링 · 3×Ctrl+C 강제 종료 · 세션 영속성 · `/cloudsave` GitHub-Gist 동기화 · 비용 추적 · `--print` 비대화형 모드 |

> **전체 기능 레퍼런스** — 위의 모든 항목을 완전한 상세와 함께(컨텍스트 압축 계층, 자동 팬아웃, 15개 테마, Trading/Research/Agents 전체 설명 …): [../guides/features.md](../guides/features.md).

---

## 지원 모델

### 비공개 소스 (API)

| 프로바이더 | 예시 모델 | 컨텍스트 | API 키 환경 변수 |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash` (무료 티어) | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ 모델, 키 하나)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | 다양 | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ 모델, 키 하나)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | 다양 | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(litellm 경유)_ | `litellm/<provider>/<model>` | 다양 | 프로바이더별 상이 |

> **`openrouter/` 게이트웨이:** 키 하나로 여러 벤더의 400개 이상 모델을 사용합니다. 모델 ID는 OpenRouter의 업스트림 `<vendor>/<model>` 경로를 그대로 유지하므로 호출은 접두사가 두 겹입니다: `openrouter/deepseek/deepseek-v4-flash`. 어떤 업스트림 프로바이더(및 양자화)가 요청을 처리할지 고정하려면 `@<provider>[/<quantization>]`를 덧붙이세요 — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — 이는 모델 ID에 붙는 대신 OpenRouter의 `provider` 요청 본문 객체로 전송됩니다. [usage.md](../guides/usage.md#openrouter-400-models-one-key) 참고.

> **`requesty/` 게이트웨이:** 사용 방식은 같습니다. `requesty/` 뒤의 모든 내용이 모델 ID로 전송되며, 카탈로그의 `<vendor>/<model>` 경로(`requesty/openai/gpt-4o-mini`)나 관리형 정책 ID(`requesty/claude-sonnet-4-6`)를 쓸 수 있습니다. `@eu`로 끝나는 관리형 정책 ID(`requesty/gpt-5-mini@eu`)는 EU 프로바이더만 거칩니다. [usage.md](../guides/usage.md#requesty-700-models-one-key)를 참고하세요.

> **`litellm/` 어댑터:** 하나의 SDK 뒤에서 100개 이상의 프로바이더로 라우팅합니다 — 주로 까다로운 인증이 필요한 업스트림(Bedrock SigV4, Azure 배포 라우팅, Vertex 서비스 계정 JWT)을 위한 것입니다. 일반적인 OpenAI 형태의 엔드포인트에는 의존성이 없는 `custom/` 어댑터를 선호하세요. `pip install ".[litellm]"`로 설치합니다. [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider) 참고.

### 오픈소스 (Ollama 경유 로컬)

| 모델 | 크기 | 강점 | Pull |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **코딩에 최적** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | 범용 | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | 추론, 수학 | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | 빠름 / 강력한 MoE | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | 추론 / 오픈 / 코드 | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **비전** | `ollama pull llava` |

> **도구 호출**에는 함수 호출 모델이 필요합니다 — 권장: `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4`. Ollama의 구조화된 필드 대신 도구 호출을 **텍스트**(`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`)로 내보내는 모델은 자동 복구되어, 이에 대해 그저 이야기만 하는 것이 아니라 즉시 도구를 실행합니다. 추론 모델(`deepseek-r1`, `qwen3`, `gemma4`)은 네이티브 `<think>` 블록을 스트리밍합니다; `/verbose` + `/thinking`으로 활성화하세요.

---

## 설치

```bash
pip install cheetahclaws
```

**Linux, macOS, WSL2, Android(Termux)**에서 작동합니다(Python 3.10+). 첫 실행 시 프로바이더 + API 키 설정을 안내하며, `cheetahclaws --setup`으로 언제든 다시 실행할 수 있습니다.

> **Windows:** 네이티브 Windows는 지원되지 않습니다 — [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install)를 사용하세요. **Android/Termux:** `pkg install python git && pip install cheetahclaws`.

### 대안: 원라인 설치 스크립트

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

설치 후 `cheetahclaws`가 PATH에 등록되도록 셸을 다시 로드하세요:

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### 대안: 소스 코드에서 `pip`으로 설치

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### 선택적 추가 패키지

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

### 대안: `uv`로 설치

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### 대안: 소스에서 직접 실행 (설치 불필요)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## 사용법: 비공개 소스 API 모델

모든 클라우드 프로바이더는 동일한 패턴을 따릅니다 — API 키를 export하고([지원 모델](#비공개-소스-api) 표에서 환경 변수 이름 확인) 모델을 선택하세요:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

프로바이더 키 발급 페이지: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat).

**AWS Bedrock / Azure / Vertex**는 `litellm/<provider>/<model>` 형식을 사용합니다(`pip install ".[litellm]"`) — 전체 환경 변수 레시피는 [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider)에 있습니다.

> **프로바이더별 전체 가이드** — 각 프로바이더의 키 발급 페이지 + 예시 모델 명령, 그리고 Bedrock/Azure/Vertex 환경 변수 레시피: [../guides/usage.md](../guides/usage.md).

---

## 사용법: 오픈소스 모델 (로컬)

### Ollama (권장)

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

[LM Studio](https://lmstudio.ai)를 다운로드하고, GGUF 모델을 받은 다음, **로컬 서버**(포트 1234)를 시작하고 실행하세요:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / 자체 호스팅 OpenAI 호환 서버

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

`custom/` 뒤의 이름은 서버의 `--served-model-name`과 일치해야 합니다. 웹 UI의 경우 `--web --model custom/<name>`이 서버 시작 전에 모델을 영속화합니다. 원격 서버인가요? `CUSTOM_BASE_URL`을 해당 IP로 지정하세요.

> **로컬 모델 전체 가이드** — Ollama 단계별 안내, LM Studio, vLLM + 웹 UI: [../guides/usage.md](../guides/usage.md#usage-open-source-models-local).

### Atlas Cloud (호스팅형, OpenAI 호환)

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)**는 의존성이 없는 `custom/` 어댑터를 통해 하나의 OpenAI 호환 엔드포인트 뒤에서 DeepSeek, Qwen, GLM, Kimi, MiniMax 등을 제공합니다:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> 모든 Atlas 채팅 모델 ID가 동일한 방식으로 작동합니다 — **전체 59개 모델 목록:** [../guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible).

---

## 모델 이름 형식

세 가지 동등한 형식이 허용됩니다:

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**접두사에 의한 자동 감지:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama.

---

## 트레이딩 에이전트

내장 AI 트레이딩 분석 + 백테스팅 모듈입니다(`pip install "cheetahclaws[trading]"`).

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4가지 전략(`dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`), 과거 상황에 대한 BM25 메모리, API 키가 필요 없는 데이터 폴백을 갖춘 미국/홍콩/A주 + 암호화폐 시장. `/ssj` → **Trading**을 통한 안내형 서브 메뉴.

> **전체 가이드:** [../guides/trading.md](../guides/trading.md)

---

## 웹 UI

프로덕션 준비가 된 브라우저 인터페이스 — 실제 사용자 계정(bcrypt + JWT), SQLite 기반 기록, 운영 엔드포인트 — Python 표준 라이브러리 + 10개의 바닐라 JS 모듈로 제공됩니다(Node.js / React / 빌드 단계 없음).

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

`http://localhost:<port>/chat`을 여세요 — 첫 계정이 관리자가 됩니다. 스트리밍 채팅(WS) + SSE 슬래시 명령, 폴더/검색/Markdown 내보내기가 있는 영속 세션, 도구 카드, 인라인 권한 승인, 설정 패널, 라이트/다크/시스템 테마, 그리고 `/health` + `/metrics` 엔드포인트를 포함합니다. 완전한 xterm.js PTY 터미널이 `/`에 있습니다(100% CLI 동등성).

> **전체 가이드:** [../guides/web-ui.md](../guides/web-ui.md) · **Docker / 홈 서버:** [../guides/docker.md](../guides/docker.md) · **네이티브 데스크톱 앱:** [../../desktop/README.md](../../desktop/README.md)

---

## 문서

이 README를 집중력 있게 유지하기 위해 상세 가이드는 [`docs/guides/`](../guides/)에 있습니다:

| 가이드 | 내용 |
|---|---|
| [**기능 (전체)**](../guides/features.md) | 완전한 기능 표 — 모든 항목을 상세히(컨텍스트 압축, 자동 팬아웃, 테마, Trading/Research/Agents 설명) |
| [**사용법 (전체 프로바이더)**](../guides/usage.md) | 프로바이더별 설정 + 예시 명령: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm, 그리고 로컬 Ollama/LM Studio/vLLM |
| [**웹 UI**](../guides/web-ui.md) | 채팅 UI, PTY 터미널, API 엔드포인트, 설정, 인증, SSE 스트리밍 |
| [**데스크톱 앱**](../../desktop/README.md) | 로컬 웹 UI를 감싸는 네이티브 창 셸(Electron); 자체 완결형 `.dmg`/`.exe`/`.AppImage` 빌드 |
| [**Docker / 홈 서버**](../guides/docker.md) | Dockerfile + compose: 하나의 컨테이너에 웹 UI + 브리지, 호스트 Ollama, 워크스페이스 마운트 |
| [**레퍼런스**](../guides/reference.md) | CLI, 50개 이상의 명령, 33개 내장 도구, 세션 검색, 오류 분류, 도구 캐시 |
| [**확장**](../guides/extensions.md) | 메모리, 스킬, 서브 에이전트, MCP 서버, 플러그인, Monitor, 자율 에이전트 |
| [**브리지**](../guides/bridges.md) | Telegram, WeChat, Slack, QQ 설정 + 휴대폰에서의 원격 제어 |
| [**보안 & 환경 변수**](../guides/security.md) | 위협 모델, `CHEETAHCLAWS_*` 변수, 봇 토큰 처리, Bash 거부 목록, 파일 시스템 샌드박스, CSRF |
| [**음성 & 비디오**](../guides/voice-and-video.md) | 오프라인 Whisper 음성 입력, 비디오 팩토리, TTS 팩토리 |
| [**트레이딩**](../guides/trading.md) | 멀티 에이전트 분석, 백테스팅, BM25 메모리, 데이터 폴백, SSJ 통합 |
| [**고급**](../guides/advanced.md) | Brainstorm, SSJ, Tmux, 능동적 모니터링, 체크포인트, 플랜 모드, 세션, 클라우드 동기화 |
| [**비교**](../guides/comparison.md) | Claude Code 및 OpenClaw 대비 전체 포지셔닝 — 한눈에 보는 표, 양측의 강점, 핵심 설계 차이 |
| [**레시피**](../guides/recipes.md) | 12가지 단계별 예제: 코드 리뷰, 원격 제어, 리서치, 버그 수정, 브라우징, 이메일, PDF/Excel |
| [**자주 묻는 질문**](../guides/faq.md) | 전체 FAQ (MCP, 모델/프로바이더, CLI/스크립팅, 음성) |
| [**플러그인 작성**](../guides/plugin-authoring.md) · [예제](../../examples/example-plugin/) | 플러그인 만들기: 도구, 명령, 스킬, MCP; 스타터 템플릿 |
| [**리서치 랩**](../guides/research-lab.md) | `/lab start <topic>` — 샌드박스 실험을 통한 자율 멀티 에이전트 논문 작성 |
| [**Agent OS**](../agent-os.md) · [RFC 인덱스](../RFC/) | `kernel/` 계층 + 모든 설계 노트(RFC 0001-0032) |
| [**기여하기**](../../CONTRIBUTING.md) | 프로젝트 구조, 아키텍처 가이드, PR 체크리스트 |

---

## 빠른 레퍼런스

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

모든 50개 이상의 슬래시 명령, 도구, 설정 옵션은 [레퍼런스 가이드](../guides/reference.md)를 참고하세요.

---

## 기여하기

기여를 환영합니다! 아키텍처, 컨벤션, PR 체크리스트는 [기여 가이드](../../CONTRIBUTING.md)를 참고하세요.

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

플러그인을 만드시나요? [플러그인 작성 가이드](../guides/plugin-authoring.md)와 [예제 템플릿](../../examples/example-plugin/)을 참고하세요.

---

## 자주 묻는 질문

몇 가지 자주 묻는 질문입니다 — **전체 FAQ**는 [../guides/faq.md](../guides/faq.md)에 있습니다.

**Q: MCP 서버는 어떻게 추가하나요?**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**Q: 로컬 Ollama 모델에서 도구 호출이 작동하지 않습니다(실제로 실행하지 않고 무엇을 할지 계속 설명만 합니다).**
CheetahClaws는 이제 로컬 모델이 Ollama의 구조화된 필드 대신 **텍스트**(`<tool_call>…</tool_call>`, `[TOOL_CALLS]…`)로 내보내는 도구 호출을 자동 복구하므로, 대부분의 함수 호출 모델이 즉시 도구를 실행합니다. 최고의 안정성을 위해서는 도구 호출 모델 — `qwen2.5-coder`, `llama3.3`, `mistral`, `phi4` — 을 사용하세요. 작은 모델은 또한 클라우드 모델보다 에이전트형 도구 사용에 약하므로, 더 명확하고 구체적인 프롬프트가 필요할 수 있습니다.

**Q: macOS에 설치한 후 `cheetahclaws: command not found`가 뜨고 `~/.zshrc`가 생성되지 않았습니다.**
먼저 셸을 다시 로드하세요: `source ~/.zshrc`(zsh) 또는 `source ~/.bash_profile`(bash). 설치 프로그램은 `~/.zshrc`가 없으면 생성하고, 바이너리를 `~/.local/bin`에 심볼릭 링크하며, PATH에 추가합니다. 이전 버전을 설치했다면, 설치 프로그램을 다시 실행하거나 이 줄을 직접 추가하세요: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`.

그 외 — 원격 vLLM, API 비용(`/cost`), 세션당 여러 키, 프로젝트 전반의 기본 모델, 입력 파이핑, 음성 설정, 깨진 텍스트 수정 — 은 모두 [../guides/faq.md](../guides/faq.md)에서 답변되어 있습니다.

---

## 인용
저장소가 유용하다고 생각되면 이 연구를 인용해 주세요
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


## 모든 기여자분들께 감사드립니다:

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
