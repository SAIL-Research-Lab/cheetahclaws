[English](../../README.md) | [中文](README.CN.MD) | [한국어](README.KO.MD) | 日本語 | [Français](README.FR.MD) | [Deutsch](README.DE.MD) | [Español](README.ES.MD) | [Português](README.PT.MD)

<br>  

<div align="center">
  <a href="[https://github.com/SafeRL-Lab/Robust-Gymnasium](https://github.com/SafeRL-Lab/cheetahclaws)">
    <img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/logos/logo-5.png" alt="Logo" width="280"> 
  </a>

  
<h2 align="center" style="font-size: 30px;"><strong><em>CheetahClaws</em></strong>: 長期タスク・マルチモデル・ツール利用型 AI システムのための、高速で使いやすいエージェントハーネス基盤</h2>
<p align="center">
    <a href="https://cheetahclaws.github.io/">ウェブサイト</a>
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


### クイックインストール

```bash
pip install cheetahclaws
```

あとは実行するだけです:

```bash
cheetahclaws        # start chatting!
```

その他のインストール方法: [ワンラインインストールスクリプト](#代替方法-ワンライン-インストールスクリプト) | [ソースからインストール](#代替方法-ソースコードから-pip-でインストール) | [uv でインストール](#代替方法-uv-でインストール) | [ソースから直接実行](#代替方法-ソースから直接実行-インストール不要) | [インストールの詳細](#インストール)

> 🖥️ **ネイティブアプリがお好みですか？** デスクトップ版（Electron）はチャット UI 全体をウィンドウにまとめ、ターミナルを不要にします。[`desktop/`](../../desktop/README.md) を参照してください。

## 🔥🔥🔥 ニュース（太平洋時間）

- 2026年7月9日: **公式 Docker イメージ + ワンコマンド公開。** Docker Hub 上のビルド済みイメージ（`docker pull chauncygu/cheetahclaws`）により、クローンせずに Web UI を実行できます。非 root ユーザーが所有する `.cheetahclaws`/`workspace` ディレクトリを事前作成することで初回実行時の `PermissionError` を修正し、compose の `image` を `CHEETAH_IMAGE` で上書き可能にし、`scripts/docker-publish.sh`（バージョン自動読み取り、マルチ/シングルアーキ対応）を追加しました。新しいドキュメントセクション: **Docker Hub からプル** と **対話式セットアップ / CLI モード**。[詳細](../news.md)
- 2026年7月8日: 新しい **`/workspace`** コマンドは `~/.cheetahclaws/workspaces` 配下の独立した作業ディレクトリを管理します（`list`/`switch`/`default`/`create`/`delete`）（PR #162）。起動時の自動切り替えは `workspace_auto` による **オプトイン**（デフォルトはオフなので、プロジェクトディレクトリでの起動は従来通り）で、`default` は最後に使用したものとは別のスティッキーなキーになりました。[詳細](../news.md)
- 2026年7月6日（**v3.5.84**）: **`/image` がローカル OCR テキストでプロンプトを補強** するようになり、非ビジョンモデルでもクリップボードのスクリーンショット（エラーダンプ、コード、テーブル）を扱えるようになりました。`pytesseract`/`tesseract` がインストールされている場合のみ動作し、`CHEETAHCLAWS_IMAGE_OCR=0` で完全にオプトアウト可能です。[詳細](../news.md)
- 2026年6月28日: 新しい **`accept-edits`** 権限モード（ファイル編集は自動実行し、許可リストにない Bash は引き続き確認）— `auto` と `accept-all` の中間です。また既存の `plan` モードを `/permissions` に公開し、プロンプトの誤解を招く `auto` の説明を修正しました。[詳細](../news.md)
- 2026年6月28日: **メモリの陳腐化** はファイルの mtime ではなく `last_verified` の日付を基準にするようになり、メモリを読むだけでは古いメモリを偽って更新できなくなりました（PR #150）。新しい **`MemoryVerify`** ツールだけがこのタイマーをリセットし、プロンプトはエージェントに再確認後に呼び出すよう指示し、注入されるメモリマニフェストは検証の新しさで順位付けされます。[詳細](../news.md)
- 2026年6月23日（**v3.5.83**）: ドキュメントを軽量化（README のニュース → それぞれ1行に、Atlas の59モデルリスト → usage.md へ、FAQ を整理）し、`desktop/` 配下にネイティブの **デスクトップアプリ**（Web UI をラップする Electron シェル）を追加。バージョン文字列のフォーマットを `v3.5.x` に統一しました。[詳細](../news.md)
- 2026年6月16日: すべての内部モジュールが単一の `cheetahclaws` パッケージ配下に配置され（`from cheetahclaws import kernel`）、起動時の `sys.path` 名前衝突によるクラッシュがなくなりました。内部を直接インポートしている場合のみ破壊的変更となります。全テストスイートがグリーン（2449 件成功）。[詳細](../news.md)
- 2026年6月6日（**v3.5.82**）: macOS のインストールで `cheetahclaws` が確実に PATH に配置されるようになり、ツール呼び出しをテキストとして出力するローカル Ollama モデルが実際にそれを実行するようになりました（#131 からの2件の修正）。[詳細](../news.md)
- 2026年6月5日: ユーザーが制御可能なトークン/コスト予算 — `/budget $5` / `/budget daily $20` はセッションまたは1日あたりの支出に上限を設定し、各モデル呼び出しの前に強制されます。[詳細](../news.md)
- 2026年6月5日: 適応型 Markdown ストリーミングは、デバイスごとのティアを自動選択することで、あらゆるデバイスでライブ出力を正しく保ちます。また、視覚的な `/context` グリッドと `deepseek-v4-flash` の 1M コンテキストも追加します。[詳細](../news.md)


その他のニュースは [こちら](../news.md) を参照してください。

---

## スポンサー

<div align="center">
  <a href="https://www.atlascloud.ai/">
    <img src="https://github.com/SafeRL-Lab/cheetahclaws/blob/main/docs/sponsors/atlas_cloud/ATLAS_CLOUD_LOGO_BLACK.svg" alt="Atlas Cloud" width="180"> 
  </a>
</div>

---

# CheetahClaws

CheetahClaws: **高速** で **使いやすい** Python ネイティブのエージェントハーネス基盤。**あらゆるモデルをサポート** します。Claude、GPT、Gemini、Kimi、Qwen、Zhipu、DeepSeek、MiniMax などのほか、Ollama や任意の OpenAI 互換エンドポイント経由のローカルオープンソースモデルにも対応します。

---

## 目次
  * [なぜ CheetahClaws なのか](#なぜ-cheetahclaws-なのか)
  * [CheetahClaws と OpenClaw の比較](#cheetahclaws-と-openclaw-の比較)
  * [機能](#機能)
  * [サポートするモデル](#サポートするモデル)
  * [インストール](#インストール)
  * [使い方: クローズドソース API モデル](#使い方-クローズドソース-api-モデル)
  * [使い方: オープンソースモデル (ローカル)](#使い方-オープンソースモデル-ローカル)
  * [モデル名の形式](#モデル名の形式)
  * [トレーディングエージェント](#トレーディングエージェント)
  * [Web UI](#web-ui)
  * [ドキュメント](#ドキュメント)（全機能のガイド）
  * [コントリビューション](#コントリビューション) · [FAQ](#faq) · [引用](#引用)


### デモ

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/demo.gif" width="850"/>
</div>
<div align=center><sub><i>ターミナルでのタスク実行</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/web_demo.gif" width="850"/>
</div>
<div align=center><sub><i>Web UI: ブラウザチャット — サイドバー、ツールカード、承認プロンプト、Markdown ストリーミング</i></sub></div>

<br/>

<div align=center>
<img src="https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/docs/media/demos/trading_demo.gif" width="850"/>
</div>
<div align=center><sub><i>自律型トレーディングエージェント</i></sub></div>

> さらに多くのアニメーションデモ（コードレビュー、`/research`、`/brainstorm`、`/lab`、Telegram/WeChat/Slack ブリッジ）は [`docs/media/`](https://github.com/SafeRL-Lab/cheetahclaws/tree/main/docs/media/) にあります。

---

## なぜ CheetahClaws なのか

Claude Code は強力で本番グレードの AI コーディングアシスタントですが、そのソースはコンパイルされた約12 MB の TypeScript/Node バンドル（約1,300ファイル、約28.3万行）で、Anthropic API と密結合しており、変更が難しく、ローカルまたは代替モデルに対して実行することは不可能です。

**CheetahClaws** は同じコアループを約9万行の読みやすい Python で再実装しています。必要なものを残し、不要なものを削ぎ落とし、マルチプロバイダー + ローカルモデルのサポートを追加しました。完全な比較: [../guides/comparison.md](../guides/comparison.md)。

| 観点 | Claude Code (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| 言語 | TypeScript + React/Ink | Python 3.8+ |
| ソースファイル数 / 行数 | 約1,332ファイル / 約28.3万 | 約315ファイル / 約9万（コア。テスト込みで約12.7万） |
| 組み込みツール / コマンド | 44+ / 88 | 27 / 50+ |
| モデルプロバイダー | Anthropic のみ | 8+（Anthropic · OpenAI · Gemini · Kimi · Qwen · DeepSeek · MiniMax · …） |
| ローカルモデル | 不可 | 可 — Ollama、LM Studio、vLLM、任意の OpenAI 互換エンドポイント |
| ビルドステップ | 必要（Bun + esbuild） | 不要 — `python cheetahclaws.py` |
| 拡張性 | クローズド（コンパイル時） | オープン — 実行時の `register_tool()`、Markdown スキル、git プラグイン、MCP |
| 音声入力 | 独自 WebSocket（OAuth） | ローカル Whisper / OpenAI — オフラインで動作 |

**Claude Code が優れている点:** より充実した React/Ink UI、より多くの組み込みツール、エンタープライズ機能（MDM、チーム権限同期、OAuth/キーチェーン）、AI 主導のメモリ抽出、単一バイナリの本番信頼性。

**CheetahClaws が優れている点:** 完全なローカル/オフラインサポートを含む、あらゆるモデルの切り替え（`--model`/`/model`、再コンパイル不要）。1ファイルに収まった読みやすいエージェントループ（`agent.py`、約740行）。ビルド不要。実行時のツール登録 + MCP + git プラグイン + Markdown スキル。タスク依存グラフ（`blocks`/`blocked_by`）。2層コンテキスト圧縮。オフライン音声。クラウドセッション同期。Telegram/WeChat/Slack/QQ へのブリッジ。

**対象ユーザー:** ローカル/非 Anthropic のコーディングアシスタントを求める開発者、エージェント型アシスタントの仕組みを研究する研究者、そして Node.js のビルドチェーンなしにハック可能なベースラインを必要とするチーム。

---

## CheetahClaws と OpenClaw の比較

[OpenClaw](https://github.com/openclaw/openclaw) はもう一つの人気のあるオープンソースアシスタント（TypeScript/Node）です。両者には **異なる主要目標** があります — OpenClaw はメッセージングチャネルをまたぐ個人向けライフアシスタントであり、CheetahClaws は開発者/コーディングツールです。

| 観点 | OpenClaw (TypeScript) | CheetahClaws (Python) |
|---|---|---|
| コード行数 | 約24.5万（約10,349ファイル） | 約9万コア（約315ファイル） |
| 主な焦点 | チャネルをまたぐ個人アシスタント | AI コーディングアシスタント / 開発ツール |
| アーキテクチャ | 常時稼働の Gateway デーモン + アプリ | インストール不要のターミナル REPL |
| メッセージングチャネル | 20+（WhatsApp · Signal · iMessage · Discord · Matrix · …） | ターミナル + Telegram · WeChat · Slack · QQ ブリッジ |
| ローカル / オフラインモデル | 限定的 | 完全対応 — Ollama · vLLM · LM Studio · 任意の OpenAI 互換 |
| コード編集ツール | ブラウザ操作、Canvas | Read · Write · Edit · Bash · Glob · Grep · NotebookEdit · GetDiagnostics |
| モバイル / Live Canvas | 可（メニューバー + iOS/Android、A2UI） | — |
| MCP サポート | — | 可（stdio/SSE/HTTP） |
| ハック性 | 24.5万行、変更がより困難 | 約9万行 — エージェントループが1ファイルに |

| こうしたい場合… | 使うべきもの |
|---|---|
| WhatsApp/Signal/Discord 上のモバイルファーストの個人アシスタント、ブラウザ自動化 + Canvas | **OpenClaw** |
| ターミナル内の AI コーディングアシスタント、完全なオフライン/ローカルモデル、マルチプロバイダー切り替え、一日で読めるソース | **CheetahClaws** |

> 完全な比較 — 両者の優位点 + 主要な設計の違い（エージェントループ、ツール登録、コンテキスト圧縮、メモリ）: [../guides/comparison.md](../guides/comparison.md#cheetahclaws-vs-openclaw)。

---

## 機能

| 機能 | 詳細 |
|---|---|
| マルチプロバイダー | Anthropic · OpenAI · Gemini · Kimi · Qwen · Zhipu · DeepSeek · MiniMax · Ollama · LM Studio · カスタムエンドポイント |
| エージェントループ | ストリーミング API + 自動ツール利用ループ。ループ全体が `agent.py` に収まっています |
| 28個の組み込みツール | Read · Write · Edit · Bash · Glob · Grep · WebFetch · WebSearch · NotebookEdit · GetDiagnostics · Memory* · Agent/SendMessage · Skill · AskUserQuestion · Task* · SleepTimer · EnterPlanMode/ExitPlanMode · *（MCP + プラグインツールを自動追加）* |
| MCP 統合 | 任意の MCP サーバー（stdio/SSE/HTTP）に接続。ツールは自動登録されます — [拡張ガイド](../guides/extensions.md) を参照 |
| プラグインシステム | git URL またはローカルパスからプラグインをインストール/有効化/更新。マルチスコープ、レコメンデーションエンジン |
| タスク管理 | `TaskCreate/Update/Get/List`、連番 ID、依存エッジ、`.cheetahclaws/tasks.json` に永続化 |
| コンテキスト圧縮 | 協調する4つのレイヤー — 動的な `max_tokens` の上限、モデルごとのコンテキストウィンドウレジストリ、70% で2層の切り取り + AI 要約、そして肥大化したツール出力の自動ファンアウト。[詳細](../guides/reference.md) |
| 永続メモリ | デュアルスコープ（ユーザー + プロジェクト）、4種類、信頼度/ソースのメタデータ、競合検出、新しさ重み付け検索、`/memory consolidate`。検証を基準とした陳腐化 — 鮮度は（ファイルの mtime ではなく）`last_verified` の日付を追跡するため、メモリを読むだけでは偽って更新できません。`MemoryVerify` だけがタイマーをリセットします。[詳細](../guides/features.md) |
| マルチエージェント | 型付きサブエージェント（coder/reviewer/researcher/…）を起動、git-worktree による分離、バックグラウンドモード |
| 権限システム | 確認を求めるのは、ファイルを変更する・任意のコードを実行する・セッションの外に到達する可能性のある操作だけです。読み取り専用ツール、読み取り専用のシェルパイプライン（`git log \| head`）、ワークスペース内での新規ファイル作成はすべて確認なしで実行されます。プロンプトで `s` を選ぶと、**そのコマンド 1 つ／そのファイル 1 つ**だけをセッション中に限り許可できます（accept-all のスコープ付き代替、`/permissions clear` で解除）。モード: `auto` / `accept-edits` / `accept-all` / `manual` / `plan`。ハードな拒否リストはあらゆるモードでホスト破壊コマンドをブロックします。[詳細](../guides/security.md#what-runs-without-asking-auto-mode) |
| チェックポイント & プランモード | ターンごとに会話 + ファイルを自動スナップショット（`/checkpoint`、`/rewind`）。`/plan` は読み取り専用の分析モード |
| スラッシュコマンド & テーマ | Tab 補完付きの50以上のスラッシュコマンド。`/theme` は15の厳選パレットを提供 |
| Brainstorm → Worker | `/brainstorm` は N ペルソナの討論を実行 → `todo_list.txt`。`/worker` は保留中のタスクを自動実装 |
| SSJ 開発者モード | `/ssj` — Brainstorm、Worker、Review、Trading、Agent、Video/TTS、Monitor などを連鎖させる永続的なパワーメニュー |
| トレーディングエージェント | `/trading` によるマルチエージェント分析、バックテスト、ペーパートレードのキャリブレーション、MV ポートフォリオ。[ガイド](../guides/trading.md) |
| Monitor | `/monitor` はスケジュールに沿って AI 監視トピック（arxiv / stock / crypto / news / custom）を購読し、レポートをブリッジ/コンソールにプッシュ |
| Research（マルチソース） | `/research` は **20のソース** にファンアウトし、注目度ヒートテーブル、エンティティ抽出、トレンドスパークライン、比較モードを提供。[ガイド](../guides/research.md) |
| 自律エージェント | `/agent` は Markdown テンプレートからバックグラウンドループを実行。反復サマリーをブリッジ経由でプッシュ。停滞停止ガード付き |
| ブリッジ + リモート制御 | Telegram · WeChat · Slack · QQ — チャットの往復、スラッシュのパススルー、ブリッジごとのジョブキュー（`!jobs`/`!retry`/`!cancel`）。[ガイド](../guides/bridges.md) |
| 音声 / ビジョン / ビデオ / TTS | オフライン Whisper `/voice`。`/image` クリップボードビジョン（ローカル + クラウド）。`/video` + `/tts` コンテンツファクトリー。[ガイド](../guides/voice-and-video.md) |
| Web UI | `--web` — マルチユーザーのブラウザチャット + PTY ターミナル。[ガイド](../guides/web-ui.md) |
| その他 | Tmux 統合 · `!cmd` シェルエスケープ · プロアクティブ監視 · 3×Ctrl+C 強制終了 · セッション永続化 · `/cloudsave` GitHub-Gist 同期 · コスト追跡 · `--print` 非対話モード |

> **完全な機能リファレンス** — 上記の各行を完全な詳細付きで（コンテキスト圧縮レイヤー、自動ファンアウト、15のテーマ、Trading/Research/Agents の完全な解説など）: [../guides/features.md](../guides/features.md)。

---

## サポートするモデル

### クローズドソース (API)

| プロバイダー | モデル例 | コンテキスト | API キー環境変数 |
|---|---|---|---|
| **Anthropic** | `claude-opus-4-6` · `claude-sonnet-4-6` · `claude-haiku-4-5-20251001` | 200k | `ANTHROPIC_API_KEY` |
| **OpenAI** | `gpt-4o` · `gpt-4.1` · `gpt-5` · `o3` · `o4-mini` | 128–200k | `OPENAI_API_KEY` |
| **Google** | `gemini-2.5-pro` · `gemini-2.0-flash` · `gemini-1.5-pro` | 1–2M | `GEMINI_API_KEY` |
| **Moonshot (Kimi)** | `moonshot-v1-8k` / `-32k` / `-128k` | 8–128k | `MOONSHOT_API_KEY` |
| **Alibaba (Qwen)** | `qwen-max` · `qwen-plus` · `qwen-turbo` · `qwq-32b` | 32k–1M | `DASHSCOPE_API_KEY` |
| **Zhipu (GLM)** | `glm-4-plus` · `glm-4` · `glm-4-flash`（無料枠） | 128k | `ZHIPU_API_KEY` |
| **DeepSeek** | `deepseek-chat` · `deepseek-reasoner` | 64k | `DEEPSEEK_API_KEY` |
| **MiniMax** | `MiniMax-Text-01` · `MiniMax-VL-01` · `abab6.5s-chat` | 256k–1M | `MINIMAX_API_KEY` |
| **OpenRouter** _(400+ モデル、キー1つ)_ | `openrouter/deepseek/deepseek-v4-flash` · `openrouter/anthropic/claude-sonnet-4-6` · `openrouter/openai/gpt-5` | 様々 | `OPENROUTER_API_KEY` |
| **Requesty** _(700+ モデル、キー1つ)_ | `requesty/openai/gpt-4o-mini` · `requesty/anthropic/claude-sonnet-4-6` · `requesty/claude-sonnet-4-6` | 様々 | `REQUESTY_API_KEY` |
| **AWS Bedrock / Azure / Vertex** _(litellm 経由)_ | `litellm/<provider>/<model>` | 様々 | プロバイダー固有 |

> **`openrouter/` ゲートウェイ:** 1つのキーでベンダーをまたぐ400以上のモデルにアクセスできます。モデル ID は OpenRouter のアップストリーム `<vendor>/<model>` パスをそのまま保持するため、呼び出しは二重プレフィックスになります: `openrouter/deepseek/deepseek-v4-flash`。どのアップストリームプロバイダー（および量子化）がリクエストを処理するかを固定するには、`@<provider>[/<quantization>]` を付加します — `openrouter/deepseek/deepseek-v4-flash@gmicloud/fp8` — これはモデル ID に連結されるのではなく、OpenRouter の `provider` リクエストボディオブジェクトとして送信されます。[usage.md](../guides/usage.md#openrouter-400-models-one-key) を参照。

> **`requesty/` ゲートウェイ:** 使い方は同じです。`requesty/` 以降はすべてモデル ID として送信されます。カタログの `<vendor>/<model>` パス（`requesty/openai/gpt-4o-mini`）でも、マネージドポリシー ID（`requesty/claude-sonnet-4-6`）でも構いません。`@eu` で終わるマネージドポリシー ID（`requesty/gpt-5-mini@eu`）は EU のプロバイダーのみを経由します。[usage.md](../guides/usage.md#requesty-700-models-one-key) を参照してください。

> **`litellm/` アダプター:** 1つの SDK の背後で100以上のプロバイダーにルーティングします — 主に扱いにくい認証を持つアップストリーム（Bedrock SigV4、Azure のデプロイメントルーティング、Vertex のサービスアカウント JWT）向けです。素の OpenAI 形式のエンドポイントには、依存関係ゼロの `custom/` アダプターを推奨します。`pip install ".[litellm]"` でインストールしてください。[recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider) を参照。

### オープンソース（Ollama 経由のローカル）

| モデル | サイズ | 強み | プル |
|---|---|---|---|
| `qwen2.5-coder` | 7B / 32B | **コーディングに最適** | `ollama pull qwen2.5-coder` |
| `llama3.3` / `llama3.2` | 70B / 3B–11B | 汎用 | `ollama pull llama3.3` |
| `deepseek-r1` | 7B–70B | 推論、数学 | `ollama pull deepseek-r1` |
| `mistral` / `mixtral` | 7B / 8x7B | 高速 / 強力な MoE | `ollama pull mistral` |
| `phi4` · `gemma3` · `codellama` | 14B · 4–27B · 7–34B | 推論 / オープン / コード | `ollama pull phi4` |
| `llava` · `llama3.2-vision` | 7–13B · 11B | **ビジョン** | `ollama pull llava` |

> **ツール呼び出し** には関数呼び出し対応のモデルが必要です — 推奨: `qwen2.5-coder`、`llama3.3`、`mistral`、`phi4`。Ollama の構造化フィールドの代わりにツール呼び出しを **テキスト** として出力するモデル（`<tool_call>…</tool_call>`、`[TOOL_CALLS]…`）は自動的にリカバリされるため、単にそれについて話すのではなく、そのままツールを実行します。推論モデル（`deepseek-r1`、`qwen3`、`gemma4`）はネイティブの `<think>` ブロックをストリーミングします。`/verbose` + `/thinking` で有効にできます。

---

## インストール

```bash
pip install cheetahclaws
```

**Linux、macOS、WSL2、Android (Termux)** で動作します（Python 3.10+）。初回実行時にプロバイダー + API キーのセットアップをガイドします。`cheetahclaws --setup` でいつでも再実行できます。

> **Windows:** ネイティブ Windows はサポートされていません — [WSL2](https://learn.microsoft.com/en-us/windows/wsl/install) を使用してください。**Android/Termux:** `pkg install python git && pip install cheetahclaws`。

### 代替方法: ワンライン インストールスクリプト

```bash
curl -fsSL https://raw.githubusercontent.com/SafeRL-Lab/cheetahclaws/main/scripts/install.sh | bash
```

インストール後、`cheetahclaws` を PATH に反映させるためにシェルを再読み込みしてください:

```bash
source ~/.zshrc     # macOS
# or: source ~/.bashrc   # Linux
cheetahclaws        # start chatting!
```

### 代替方法: ソースコードから `pip` でインストール

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git
cd cheetahclaws
pip install .                       # then: cheetahclaws
git pull && pip install --force-reinstall .   # to update
```

#### オプションの追加機能

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

### 代替方法: `uv` でインストール

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
uv tool install ".[all]"            # minimal: uv tool install .
uv tool install ".[all]" --reinstall   # update   ·   uv tool uninstall cheetahclaws
```

### 代替方法: ソースから直接実行 (インストール不要)

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt
python cheetahclaws.py              # changes take effect immediately
```

---

## 使い方: クローズドソース API モデル

すべてのクラウドプロバイダーは同じパターンに従います — API キーをエクスポートし（環境変数名は [サポートするモデル](#クローズドソース-api) の表を参照）、モデルを選択します:

```bash
export ANTHROPIC_API_KEY=sk-ant-...     # or OPENAI_API_KEY / GEMINI_API_KEY / DEEPSEEK_API_KEY / …
cheetahclaws                            # default model
cheetahclaws --model gpt-4o             # pick any model
cheetahclaws --model deepseek-chat --thinking --verbose
```

プロバイダーのキー取得ページ: [Anthropic](https://console.anthropic.com) · [OpenAI](https://platform.openai.com) · [Gemini](https://aistudio.google.com) · [Kimi](https://platform.moonshot.cn) · [Qwen](https://dashscope.aliyun.com) · [Zhipu](https://open.bigmodel.cn) · [DeepSeek](https://platform.deepseek.com) · [MiniMax](https://platform.minimaxi.chat)。

**AWS Bedrock / Azure / Vertex** は `litellm/<provider>/<model>` 形式を使用します（`pip install ".[litellm]"`）— 完全な環境変数のレシピは [recipes.md](../guides/recipes.md#alternative-cloud-providers-with-non-trivial-auth-via-the-litellm-provider) にあります。

> **プロバイダーごとの完全ガイド** — 各プロバイダーのキー取得ページ + モデルコマンドの例、および Bedrock/Azure/Vertex の環境変数レシピ: [../guides/usage.md](../guides/usage.md)。

---

## 使い方: オープンソースモデル (ローカル)

### Ollama（推奨）

```bash
curl -fsSL https://ollama.com/install.sh | sh   # install
ollama pull qwen2.5-coder                        # pull a tool-calling model
ollama serve                                     # http://localhost:11434 (auto-starts on macOS)
cheetahclaws --model ollama/qwen2.5-coder        # run (use `ollama list` to see local models)
```

### LM Studio

[LM Studio](https://lmstudio.ai) をダウンロードし、GGUF モデルを入手し、その **Local Server**（ポート 1234）を起動してから:

```bash
cheetahclaws --model lmstudio/<model-name>
```

### vLLM / セルフホストの OpenAI 互換サーバー

```bash
python -m vllm.entrypoints.openai.api_server \
    --model Qwen/Qwen2.5-Coder-32B-Instruct --port 8000 \
    --enable-auto-tool-choice --tool-call-parser hermes

export CUSTOM_BASE_URL=http://localhost:8000/v1
export CUSTOM_API_KEY=token-abc123      # any non-empty string if the server has no auth
cheetahclaws --model custom/Qwen2.5-Coder-32B-Instruct
```

`custom/` の後の名前はサーバーの `--served-model-name` と一致する必要があります。Web UI の場合、`--web --model custom/<name>` はサーバー起動前にモデルを永続化します。リモートサーバーですか？ `CUSTOM_BASE_URL` をその IP に向けてください。

> **ローカルモデルの完全ガイド** — Ollama のステップバイステップ、LM Studio、vLLM + Web UI: [../guides/usage.md](../guides/usage.md#usage-open-source-models-local)。

### Atlas Cloud（ホスト型、OpenAI 互換）

> 🎁 **[Atlas Cloud](https://www.atlascloud.ai/?utm_source=github&utm_medium=link&utm_campaign=cheetahclaws)** は、依存関係ゼロの `custom/` アダプター経由で、DeepSeek、Qwen、GLM、Kimi、MiniMax などを1つの OpenAI 互換エンドポイントの背後で提供します:

```bash
export CUSTOM_BASE_URL=https://api.atlascloud.ai/v1
export CUSTOM_API_KEY=your_atlascloud_api_key
cheetahclaws --model custom/deepseek-ai/deepseek-v4-pro
```

> 任意の Atlas チャットモデル ID も同じように動作します — **全59モデルの完全なリスト:** [../guides/usage.md](../guides/usage.md#option-d--atlas-cloud-hosted-openai-compatible)。

---

## モデル名の形式

3つの等価な形式が受け付けられます:

```bash
cheetahclaws --model gpt-4o                  # 1. auto-detect by prefix
cheetahclaws --model ollama/qwen2.5-coder    # 2. provider/model
cheetahclaws --model kimi:moonshot-v1-32k    # 3. provider:model
```

**プレフィックスによる自動検出:** `claude-`→anthropic · `gpt-`/`o1`/`o3`→openai · `gemini-`→gemini · `moonshot-`/`kimi-`→kimi · `qwen`/`qwq-`→qwen · `glm-`→zhipu · `deepseek-`→deepseek · `MiniMax-`/`abab`→minimax · `llama`/`mistral`/`phi`/`gemma`/`mixtral`/`codellama`→ollama。

---

## トレーディングエージェント

組み込みの AI トレーディング分析 + バックテストモジュール（`pip install "cheetahclaws[trading]"`）。

```bash
/trading analyze NVDA            # 5-phase pipeline: data → Bull/Bear debate → Judge → Risk panel → PM decision
/trading backtest AAPL dual_ma   # backtest a strategy (or let AI pick); Sharpe/Sortino/Calmar/drawdown/win-rate
```

4つの戦略（`dual_ma`、`rsi_mean_reversion`、`bollinger_breakout`、`macd_crossover`）、過去の状況に関する BM25 メモリ、API キー不要のデータフォールバックを備えた米国/香港/A株 + 暗号資産市場に対応。`/ssj` → **Trading** からガイド付きサブメニューを利用できます。

> **完全ガイド:** [../guides/trading.md](../guides/trading.md)

---

## Web UI

本番対応のブラウザインターフェース — 実際のユーザーアカウント（bcrypt + JWT）、SQLite バックエンドの履歴、運用エンドポイントを備え、Python 標準ライブラリ + 10個のバニラ JS モジュールで提供されます（Node.js / React / ビルドステップ不要）。

```bash
pip install 'cheetahclaws[web]'
cheetahclaws --web                  # auto-picks a free port (tries 8080)
cheetahclaws --web --port 9000 --host 0.0.0.0   # bind explicitly / open to LAN
cheetahclaws --web --no-auth        # skip login (localhost dev only)
```

`http://localhost:<port>/chat` を開くと、最初のアカウントが管理者になります。ストリーミングチャット（WS）+ SSE スラッシュコマンド、フォルダ/検索/Markdown エクスポート付きの永続セッション、ツールカード、インライン権限承認、設定パネル、ライト/ダーク/システムテーマ、`/health` + `/metrics` エンドポイントを含みます。完全な xterm.js PTY ターミナルが `/` にあります（CLI と100%同等）。

> **完全ガイド:** [../guides/web-ui.md](../guides/web-ui.md) · **Docker / ホームサーバー:** [../guides/docker.md](../guides/docker.md) · **ネイティブデスクトップアプリ:** [../../desktop/README.md](../../desktop/README.md)

---

## ドキュメント

この README を焦点の絞られたものに保つため、詳細なガイドは [`docs/guides/`](../guides/) にあります:

| ガイド | 内容 |
|---|---|
| [**機能（完全版）**](../guides/features.md) | 完全な機能テーブル — 各行を完全な詳細付きで（コンテキスト圧縮、自動ファンアウト、テーマ、Trading/Research/Agents の解説） |
| [**使い方（全プロバイダー）**](../guides/usage.md) | プロバイダーごとのセットアップ + コマンド例: Anthropic/OpenAI/Gemini/Kimi/Qwen/Zhipu/DeepSeek/MiniMax/litellm、およびローカル Ollama/LM Studio/vLLM |
| [**Web UI**](../guides/web-ui.md) | チャット UI、PTY ターミナル、API エンドポイント、設定、認証、SSE ストリーミング |
| [**デスクトップアプリ**](../../desktop/README.md) | ローカル Web UI をラップするネイティブウィンドウシェル（Electron）。自己完結型の `.dmg`/`.exe`/`.AppImage` をビルド |
| [**Docker / ホームサーバー**](../guides/docker.md) | Dockerfile + compose: 1つのコンテナに Web UI + ブリッジ、ホストの Ollama、ワークスペースのマウント |
| [**リファレンス**](../guides/reference.md) | CLI、50以上のコマンド、33個の組み込みツール、セッション検索、エラー分類、ツールキャッシュ |
| [**拡張機能**](../guides/extensions.md) | メモリ、スキル、サブエージェント、MCP サーバー、プラグイン、Monitor、自律エージェント |
| [**ブリッジ**](../guides/bridges.md) | Telegram、WeChat、Slack、QQ のセットアップ + スマホからのリモート制御 |
| [**セキュリティ & 環境変数**](../guides/security.md) | 脅威モデル、`CHEETAHCLAWS_*` 変数、ボットトークンの取り扱い、Bash 拒否リスト、fs サンドボックス、CSRF |
| [**音声 & ビデオ**](../guides/voice-and-video.md) | オフライン Whisper 音声入力、ビデオファクトリー、TTS ファクトリー |
| [**トレーディング**](../guides/trading.md) | マルチエージェント分析、バックテスト、BM25 メモリ、データフォールバック、SSJ 統合 |
| [**上級**](../guides/advanced.md) | Brainstorm、SSJ、Tmux、プロアクティブ監視、チェックポイント、プランモード、セッション、クラウド同期 |
| [**比較**](../guides/comparison.md) | Claude Code と OpenClaw に対する完全なポジショニング — 一目でわかる表、両者の優位点、主要な設計の違い |
| [**レシピ**](../guides/recipes.md) | ステップバイステップの12の例: コードレビュー、リモート制御、リサーチ、バグ修正、ブラウズ、メール、PDF/Excel |
| [**FAQ**](../guides/faq.md) | 完全な FAQ（MCP、モデル/プロバイダー、CLI/スクリプティング、音声） |
| [**プラグイン作成**](../guides/plugin-authoring.md) · [例](../../examples/example-plugin/) | プラグインの構築: ツール、コマンド、スキル、MCP。スターターテンプレート |
| [**リサーチラボ**](../guides/research-lab.md) | `/lab start <topic>` — サンドボックス化された実験による自律型マルチエージェント論文執筆 |
| [**Agent OS**](../agent-os.md) · [RFC インデックス](../RFC/) | `kernel/` レイヤー + すべての設計ノート（RFC 0001-0032） |
| [**コントリビューション**](../../CONTRIBUTING.md) | プロジェクト構造、アーキテクチャガイド、PR チェックリスト |

---

## クイックリファレンス

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

50以上のすべてのスラッシュコマンド、ツール、設定オプションについては [リファレンスガイド](../guides/reference.md) を参照してください。

---

## コントリビューション

コントリビューションを歓迎します！ アーキテクチャ、規約、PR チェックリストについては [コントリビューションガイド](../../CONTRIBUTING.md) を参照してください。

```bash
git clone https://github.com/SafeRL-Lab/cheetahclaws.git && cd cheetahclaws
pip install -r requirements.txt && pip install pytest
python -m pytest tests/ -x -q       # 341+ tests should pass
python cheetahclaws.py              # run the REPL
```

プラグインを構築しますか？ [プラグイン作成ガイド](../guides/plugin-authoring.md) と [サンプルテンプレート](../../examples/example-plugin/) を参照してください。

---

## FAQ

いくつかのよくある質問 — **完全な FAQ** は [../guides/faq.md](../guides/faq.md) にあります。

**Q: MCP サーバーを追加するにはどうすればいいですか？**
```
/mcp add git uvx mcp-server-git          # or create .mcp.json in your project, then /mcp reload
```

**Q: ローカルの Ollama モデルでツール呼び出しが動きません（実行する代わりに、何をするかを説明し続けるだけです）。**
CheetahClaws は、ローカルモデルが Ollama の構造化フィールドの代わりに **テキスト** として出力するツール呼び出し（`<tool_call>…</tool_call>`、`[TOOL_CALLS]…`）を自動的にリカバリするようになったため、ほとんどの関数呼び出しモデルはそのままツールを実行します。最良の信頼性を得るには、ツール呼び出し対応のモデル — `qwen2.5-coder`、`llama3.3`、`mistral`、`phi4` を使用してください。小さなモデルはクラウドモデルよりもエージェント的なツール利用が弱いため、より明確で具体的なプロンプトが必要になることを想定してください。

**Q: macOS にインストールした後、`cheetahclaws: command not found` となり、`~/.zshrc` が作成されていません。**
まずシェルを再読み込みしてください: `source ~/.zshrc`（zsh）または `source ~/.bash_profile`（bash）。インストーラーは `~/.zshrc` がなければ作成し、バイナリを `~/.local/bin` にシンボリックリンクし、それを PATH に追加します。古いバージョンをインストールした場合は、インストーラーを再実行するか、次の行を自分で追加してください: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc`。

その他 — リモート vLLM、API コスト（`/cost`）、セッションごとの複数キー、プロジェクトをまたぐデフォルトモデル、入力のパイプ、音声セットアップ、文字化けの修正 — はすべて [../guides/faq.md](../guides/faq.md) で回答されています。

---

## 引用
リポジトリが役に立った場合は、この研究を引用してください
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


## すべてのコントリビューターに感謝します:

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
