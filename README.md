```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        AI Multi-Agent Orchestrator                           ║
║                                                              ║
║   ░█████╗░██╗  ░█████╗░░██████╗░███████╗███╗░░██╗████████╗  ║
║   ██╔══██╗██║  ██╔══██╗██╔════╝░██╔════╝████╗░██║╚══██╔══╝  ║
║   ███████║██║  ███████║██║░░██╗░█████╗░░██╔██╗██║░░░██║░░░  ║
║   ██╔══██║██║  ██╔══██║██║░░╚██╗██╔══╝░░██║╚████║░░░██║░░░  ║
║   ██║░░██║██║  ██║░░██║╚██████╔╝███████╗██║░╚███║░░░██║░░░  ║
║   ╚═╝░░╚═╝╚═╝  ╚═╝░░╚═╝░╚═════╝░╚══════╝╚═╝░░╚══╝░░░╚═╝░░░  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

> **あなたのリポジトリに、眠らないエンジニアを。**
> Issue を投げれば、ヒアリング → 設計 → 実装 → PR → レビュー対応まで全自動。
> しかも要所では **Web ダッシュボードから「動く UI プロトタイプ」を見ながらワンクリック承認**。
> AI チームメンバーをそのまま雇う感覚でお使いください。☕️

[![CI](https://github.com/Akihiro1028Bad/ai-agent-team2/actions/workflows/ci.yml/badge.svg)](https://github.com/Akihiro1028Bad/ai-agent-team2/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black.svg)](https://nextjs.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![uv](https://img.shields.io/badge/package%20manager-uv-blueviolet.svg)](https://docs.astral.sh/uv/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-orange.svg)](https://github.com/astral-sh/ruff)

---

## 🌟 概要

24 時間稼働する PC に AI マルチエージェントを配置し、**1 人のエンジニアとして自律的に働かせる**システムです。
GitHub Issue にラベルを 1 つ付けるだけで、要件ヒアリング・設計・実装計画・実装・CI 修正・レビュー対応までを自動で回し、Pull Request を仕上げます。

そして「全部おまかせ」では不安な要所 — **計画の承認・分割の承認・PR レビュー** — は、付属の **Web ダッシュボード**から人間がサクッと判断できます。設計段階では AI が**動く UI プロトタイプ**まで用意してくれるので、「コードになる前に画面を触って納得してから GO」が可能です。

### ✨ 主な特徴

| 機能 | 説明 |
|-----|------|
| 🏷️ **Issue 駆動** | `ai-agent` ラベルを付けるだけで全自動起動 |
| 🛤️ **統一パイプライン** | 全 Issue が `INTAKE → CLARIFY → (SPLIT) → PLAN → APPROVE → IMPLEMENT → REVIEW → (REVISE) → DONE` の一本道を流れる。タイプ差はフェーズではなく**パラメータ**で表現 |
| 🖥️ **Web ダッシュボード** | 処理中 Issue・キュー・ライブログ・コスト・承認待ちを一望。Next.js 製 |
| ✅ **画面からワンクリック承認** | 計画・分割の承認/差し戻しを Web から実行（GitHub の 👍 リアクションに行かなくてよい） |
| 🎨 **動く UI プロトタイプ** | 設計段階で AI がデザイナーとして自己完結 HTML を生成 → サンドボックス iframe で触って確認してから承認 |
| 🤝 **人間との協調** | 承認・レビューなど重要ポイントで人間が介入。それ以外は自走 |
| ⚡ **並行処理** | 複数 Issue を同時処理（git worktree で物理的に分離） |
| 🏢 **マルチリポジトリ / 🔑 マルチアカウント** | YAML 1 ファイルで複数リポ・複数 GitHub アカウントを一元管理 |
| 🧠 **自己改善ループ** | エピソード → パターン → Skill 抽出で、使うほど賢くなる |

---

## 🏛️ アーキテクチャ

オーケストレーター本体（常駐 asyncio プロセス）と、それが書き出すファイル成果物を読む **Web レイヤ（FastAPI + Next.js）** の二段構え。Web 側はオーケストレーターのプロセス状態に一切触らず、`state.json` / `events.jsonl` / `artifacts/` などのファイルだけを読み、操作は `control.jsonl` 経由で受け渡します（疎結合）。

```
╔════════════════════════════════════════════════════════════════╗
║                  AI Multi-Agent Orchestrator                   ║
║                       (asyncio 常駐プロセス)                    ║
╠════════════════════════════════════════════════════════════════╣
║                                                                ║
║  GitHub Poller ──→ Event Router ──→ Task Queue ──→ Dispatcher  ║
║   (既定 120秒)                      (Priority+Sem)     │        ║
║                                              Claude Agent SDK   ║
║                                                Runner  │        ║
║                         ┌──────────────┬───────────────┤        ║
║                         ▼              ▼               ▼        ║
║                     GitHub          Slack           Event      ║
║                     Client         Notifier         Logger     ║
║                                                                ║
║  ┌──────────────────────────────────────────────────────────┐ ║
║  │           Knowledge（自己改善ループ）                       │ ║
║  │   Episode Store → Pattern Extractor → Skill Manager       │ ║
║  └──────────────────────────────────────────────────────────┘ ║
╚════════════════════════════════════════════════════════════════╝
            │  state.json / events.jsonl / artifacts/   ▲ control.jsonl
            ▼  (ファイル成果物を読む)                     │ (承認・操作を書く)
╔════════════════════════════════════════════════════════════════╗
║   Web レイヤ                                                    ║
║   FastAPI (REST + SSE, :8000)  ◀──▶  Next.js Dashboard (:3000) ║
║   ・処理中 Issue / キュー / ライブログ / コスト                 ║
║   ・承認待ち一覧・計画/分割の承認・差し戻し                      ║
║   ・設計レビュー＋動く UI プロトタイプ（sandbox iframe）         ║
╚════════════════════════════════════════════════════════════════╝
```

---

## 🛤️ ワークフロー（統一パイプライン）

かつてはタイプごとに別フローでしたが、現在は **全 Issue が同じ 9 フェーズの一本道**を流れます。Bug / Feature-M / Feature-L の違いは、フェーズの分岐ではなく **3 つのパラメータ**に集約されています。

```
INTAKE ─→ CLARIFY ─┬─→ SPLIT ─┐
   │         │ (要分割のみ)    │
   │         ▼                 ▼
   └────→  PLAN ─→ APPROVE ─→ IMPLEMENT ─→ REVIEW ─→ DONE
              ▲        │(差し戻し)            │(指摘/CI失敗)
              └────────┘             REVISE ─┘
```

| パラメータ | 意味 | bug | feature-m | feature-l |
|-----------|------|:---:|:---------:|:---------:|
| `plan_depth` | 計画の深さ（light=方針 / full=設計書＋PR） | light | full | full |
| `needs_split` | SPLIT（子 Issue 分割）を通すか | – | – | ✅ |
| `approval_style` | 承認ゲートの方式 | 👍 reaction | PR approve | PR approve |

> 💡 タイプは `INTAKE` が Issue の規模・性質から自動判定し、以降は全タイプが同一コードパスを流れます。承認は **Web 画面 / 👍 リアクション / PR approve / LGTM コメント**のいずれでも OK。差し戻し（指摘）は計画フェーズ（PLAN）へ戻り、指摘全文を次の実行プロンプトに渡して作り直します。

---

## 🚀 クイックスタート

### 前提条件

| ソフトウェア | バージョン | 用途 |
|------------|-----------|------|
| Python | 3.13+ | オーケストレーター本体 |
| [uv](https://docs.astral.sh/uv/) | 最新版 | Python の依存・仮想環境管理 |
| Node.js | 20+ | Web ダッシュボード（任意） |
| git | 2.20+ | worktree 分離 |
| [gh (GitHub CLI)](https://cli.github.com/) | 2.0+ | トークンのフォールバック解決 |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | 最新版 | AI エージェント実行基盤 |

### ① インストール

```bash
git clone https://github.com/Akihiro1028Bad/ai-agent-team2.git
cd ai-agent-team2

# Python 依存をインストール
uv sync --all-extras

# 動作確認
uv run ai-agent --help
```

### ② 初期セットアップ

```bash
# GitHub アカウントを登録（トークンを OS keyring に保存）
uv run ai-agent account add my-org

# 対象リポジトリをセットアップ（clone + ラベル作成 + config.yaml 更新）
uv run ai-agent setup myorg/my-app --account my-org

# 認証・接続チェック
uv run ai-agent health
```

### ③ 起動

```bash
# オーケストレーター（フォアグラウンド）
uv run ai-agent start --foreground
```

### ④ 動作確認

対象リポジトリで `ai-agent` ラベルを付けた Issue を作成すると、ポーリング（既定 120 秒間隔）で検知され、自動処理が始まります。

### ⑤ Web ダッシュボード（任意・おすすめ）

「いま何が動いていて、何が承認待ちか」を画面で見たい・画面から承認したいときは、API と Web を起動します（オーケストレーターと合わせて **3 プロセス**構成）。

```bash
# ターミナル1: オーケストレーター本体
uv run ai-agent start --foreground

# ターミナル2: REST/SSE API（:8000）
uv run ai-agent api

# ターミナル3: Next.js ダッシュボード（:3000）
cd web && npm install && npm run dev
```

ブラウザで http://localhost:3000 を開くと、処理中 Issue・キュー・ライブログ・コスト・**承認待ち**が見られます。計画/分割の承認、設計レビュー、**動く UI プロトタイプのプレビュー**もここから。

---

## 🛠️ CLI コマンド

### 📦 アカウント管理

| コマンド | 説明 |
|---------|------|
| `ai-agent account add <name>` | GitHub アカウントを追加（keyring 保存） |
| `ai-agent account list` | 登録済みアカウント一覧 |
| `ai-agent account verify [name]` | トークンの有効性を検証 |
| `ai-agent account remove <name>` | アカウントを削除 |

### ⚙️ リポジトリ設定

| コマンド | 説明 |
|---------|------|
| `ai-agent setup <owner/repo>` | リポジトリの初期セットアップ（clone + ラベル + config） |
| `ai-agent unregister <owner/repo>` | リポジトリの登録解除 |

### 🚀 稼働操作

| コマンド | 説明 |
|---------|------|
| `ai-agent start [--foreground]` | オーケストレーターを起動 |
| `ai-agent stop` | オーケストレーターを停止 |
| `ai-agent status [--json]` | 稼働状況を表示 |
| `ai-agent logs [-f] [-n N]` | ログを表示 |
| `ai-agent health` | 認証・接続チェック |
| `ai-agent api [--port 8000]` | Web ダッシュボード用 REST/SSE API を起動 |

---

## ⚙️ 設定

`config.yaml` でリポジトリ・アカウント・動作パラメータを管理します。

### 最小構成

```yaml
accounts:
  my-org: {}

repositories:
  - owner: "myorg"
    repo: "my-app"
    account: "my-org"
```

### 推奨構成

```yaml
accounts:
  my-org: {}
  my-personal:
    token_command: "gh auth token --user personal"

polling_interval_sec: 120

repositories:
  - owner: "myorg"
    repo: "frontend-app"
    account: "my-org"
    label: "ai-agent"
    base_branch: "main"
    slack_channel: "#frontend-ai"
    # 承認できる人（既定はリポジトリ owner）
    approvers: ["alice", "bob"]

  - owner: "myorg"
    repo: "backend-api"
    account: "my-org"
    base_branch: "develop"

concurrency:
  max_total: 2      # 同時処理する Issue の最大数
  max_per_repo: 1   # 1 リポジトリあたりの同時処理数

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
  default_channel: "#ai-agent"
```

主な設定項目は [セットアップガイド](docs/setup-guide.md) を参照してください。

### 🔐 クレデンシャル解決順序

GitHub トークンは以下の優先順位で解決されます:

| 優先度 | 方式 | 説明 |
|-------|------|------|
| 1️⃣ | **keyring** | OS セキュアストレージ — `ai-agent account add` で登録。**推奨** |
| 2️⃣ | **環境変数** | `GITHUB_TOKEN_{NAME}` 形式 |
| 3️⃣ | **token_command** | 外部コマンド（1Password CLI / AWS Secrets Manager 等） |
| 4️⃣ | **gh auth token** | GitHub CLI のフォールバック |

> 🔒 承認は **承認者許可リスト**（既定はリポジトリ owner、`approvers` で設定可）に含まれるユーザーのみ有効。許可外の承認は無視されます。

---

## 🧰 技術スタック

### オーケストレーター本体 (Python)

| カテゴリ | 技術 | 用途 |
|---------|------|------|
| 言語 / パッケージ管理 | Python 3.13+ / uv | 実行環境・依存管理 |
| CLI | Typer + Rich | CLI フレームワーク |
| GitHub API | githubkit | 非同期・型付き GitHub API |
| HTTP | httpx | 非同期 HTTP クライアント |
| AI 基盤 | claude-agent-sdk | AI エージェント実行 |
| 状態機械 | python-statemachine | フェーズ遷移管理 |
| 設定 | pydantic-settings + PyYAML | YAML 設定 + 環境変数 |
| 認証 | keyring | OS Keychain トークン管理 |
| Web API | FastAPI + uvicorn | REST + SSE（ダッシュボード用） |
| テスト | pytest + pytest-asyncio + respx + hypothesis | テスト |
| 品質 | ruff（lint/format）/ mypy strict | 静的解析 |

### Web ダッシュボード (web/)

| カテゴリ | 技術 |
|---------|------|
| フレームワーク | Next.js 16 / React 19 |
| スタイル | Tailwind CSS 4 |
| 描画 | react-markdown + remark-gfm / mermaid |
| テスト | Vitest + Testing Library |

---

## 💻 開発

### コマンド

```bash
# 依存関係インストール
uv sync --all-extras

# テスト（単体は高速・モック使用）
uv run pytest tests/ -v
uv run pytest tests/unit/ -v

# 型チェック / lint / format
uv run mypy src/
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Web（web/ 配下）
cd web && npm test        # Vitest
cd web && npx tsc --noEmit # 型チェック
```

### プロジェクト構成

```
src/ai_agent_orchestrator/
├── cli.py / __main__.py        # Typer CLI エントリポイント
├── models.py                   # Enum/dataclass（Phase, IssueState, WorkflowParams 等）
├── protocols.py                # Protocol 定義（AgentRunner, Notifier, Tracker 等）
├── credential.py               # 4 段階トークン解決
├── state_persistence.py        # Issue 状態のファイル永続化（state.json）
├── event_logger.py             # events.jsonl ログ + トークンサニタイズ
├── workspace_manager.py        # git worktree 管理
├── config/settings.py          # pydantic-settings（AppSettings, RepositoryConfig）
├── github/client.py            # GitHubClient（githubkit ラッパー）
├── agents/claude_runner.py     # ClaudeAgentRunner（SDK 実行）
├── notifications/slack.py      # SlackNotifier（Webhook）
├── context/engine.py           # リポマップ + 関連ファイル検索
├── orchestrator/
│   ├── orchestrator.py         # メインオーケストレーター
│   ├── state_machine.py        # フェーズ遷移（python-statemachine）
│   ├── task_queue.py           # asyncio.PriorityQueue + Semaphore
│   ├── approval.py             # 承認判定の共通化 + 承認者検証
│   ├── control_file.py / control_bus.py # control.jsonl 受け口（Web 操作）
│   └── execution_guard.py      # 二重実行防止ガード
├── poller/
│   ├── github_poller.py        # GitHub Polling
│   └── event_router.py         # イベント → フェーズ遷移
├── phases/                     # フェーズ実行ロジック（統一パイプライン）
│   ├── base.py / dispatcher.py # PhaseExecutor 基底 / 振り分け
│   ├── type_detection.py       # タイプ判定（INTAKE）
│   ├── hearing.py              # CLARIFY（ヒアリング）
│   ├── plan.py / plan_artifact.py / plan_validation.py # PLAN（設計＋プロトタイプ生成）
│   ├── implement.py            # IMPLEMENT（実装）
│   ├── revise.py / ci_fix.py   # REVISE（レビュー対応 / CI 修正）
│   ├── review_classifier.py    # レビュー指摘の分類
│   ├── split.py                # SPLIT（Feature-L 分割・冪等）
│   └── done.py                 # DONE（完了処理）
│   └── （analysis/design/fix/* は統合先への後方互換 re-export）
├── api/                        # FastAPI（REST + SSE。ファイル成果物を読み Web へ）
│   ├── app.py / readers.py / schemas.py / stream.py / review.py
├── evidence/                   # IMPLEMENT 完了時のスクショ/録画/テストログ
├── prototype/                  # PLAN 生成 UI プロトタイプの収集・配信
├── knowledge/                  # 自己改善ループ（episode/pattern/skill）
└── commands/                   # CLI サブコマンド（account/setup/run/api）

web/                            # Next.js ダッシュボード
├── app/                        # ルート（/ ダッシュボード, /issues, /approvals, /queue, ...）
├── components/                 # UI（ApprovalGate, review/PrototypeGallery 等）
└── lib/                        # API アダプタ / hooks（usePolling, useLogStream）

tests/
├── unit/                       # 単体テスト（モック使用、高速）
└── integration/                # 結合テスト（実 API）
```

### 設計原則

| # | 原則 | 説明 |
|---|------|------|
| 🔌 1 | **Protocol ベース** | 全外部依存を `typing.Protocol` で抽象化し、テスタビリティを確保 |
| ⚡ 2 | **完全非同期** | `asyncio` ベース。ブロッキング呼び出し禁止 |
| 🧊 3 | **イミュータブル志向** | 状態は dataclass で表現し、不要な破壊的変更を避ける |
| 🧩 4 | **統一パイプライン** | タイプ差はフェーズではなくパラメータ（plan_depth / needs_split / approval_style）で表現 |
| 🪢 5 | **疎結合な Web レイヤ** | Web はプロセス状態に触れず、ファイル読み取り + control.jsonl 書き込みのみ |
| 🛡️ 6 | **Fail-safe** | タイムアウト・リトライ・エラー通知。収集系（evidence/prototype）は失敗を握り潰し本処理を止めない |
| 🔭 7 | **Observability** | 構造化イベントログ（`events.jsonl`）で全アクションを追跡 |

---

## 📚 ドキュメント

| ドキュメント | 説明 |
|------------|------|
| [CLAUDE.md](CLAUDE.md) | プロジェクト概要・規約（AI/開発者向けの単一の真実点） |
| [設計書](docs/design-python.md) | メイン設計書 |
| [アーキテクチャ図解](docs/architecture-diagrams.md) | Mermaid 図解 |
| [API リファレンス](docs/api-reference.md) | 型定義・Protocol 仕様 |
| [セットアップガイド](docs/setup-guide.md) | インストールから初回実行まで |

---

## 🏷️ GitHub Labels

オーケストレーターは GitHub Labels でタイプ・フェーズを管理します。`ai-agent setup` で自動作成されます。

| ラベル | 説明 |
|-------|------|
| `ai-agent` | AI に割り当てる Issue（これが全自動起動のトリガー） |
| `type:bug` / `type:feature-m` / `type:feature-l` | タイプ分類（INTAKE が自動判定） |
| `phase:intake` 〜 `phase:done` | 現在のフェーズ |
| `phase:suspended` | エラー等で保留中（手動復帰待ち） |

---

## 🤝 人間との協調ポイント

全自動の中でも、ここだけは人間が舵を握れます（Web 画面 / GitHub どちらでも）。

| タイミング | できること |
|-----------|-----------|
| 🎨 **計画承認（APPROVE）** | 設計内容と**動く UI プロトタイプ**を確認 → 承認 or 差し戻し（指摘は再設計へ） |
| 🧩 **分割承認（SPLIT）** | Feature-L の子 Issue 分割案を承認 or 差し戻し |
| 🔍 **PR レビュー（REVIEW）** | 実装 PR をレビュー。指摘は REVISE で自動対応 |
| 💬 **ヒアリング回答（CLARIFY）** | エージェントの質問に回答して要件を固める |

---

## 📄 ライセンス

MIT License — お好きにどうぞ。あなたの代わりに PR を書く相棒が、今日も眠らず待っています。🌙
