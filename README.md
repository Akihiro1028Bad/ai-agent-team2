# AI Multi-Agent Orchestrator

GitHub Issue を自動で処理する AI マルチエージェントオーケストレーター。
Issue の受付 → ヒアリング → 設計 → 実装 → PR作成 → レビュー対応を自動化します。

[![CI](https://github.com/Akihiro1028Bad/ai-agent-team2/actions/workflows/ci.yml/badge.svg)](https://github.com/Akihiro1028Bad/ai-agent-team2/actions/workflows/ci.yml)
[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](https://www.python.org/downloads/)

---

## 概要

24時間稼働するPCにAIマルチエージェントを配置し、**1人のエンジニアとして自律的に稼働**させるシステムです。
GitHub Issue ベースでタスクをアサインし、要件ヒアリング・設計・実装計画・実装・レビュー対応までを自動で行い、Pull Request を作成します。

### 主な特徴

- **Issue 駆動**: `ai-agent` ラベルを付けるだけで自動処理開始
- **タイプ別ワークフロー**: Bug / Feature-S / Feature-M / Feature-L を自動判定し、最適なフローで処理
- **人間との協調**: 設計承認・PR レビューなど重要なポイントで人間の判断を介入
- **並行処理**: 最大2 Issue を同時処理（git worktree による物理的分離）
- **マルチリポジトリ対応**: YAML 設定で複数リポジトリを一元監視
- **マルチアカウント対応**: リポジトリごとに異なる GitHub アカウントを使用可能
- **自己改善**: エピソード記憶・パターン抽出により、使うほど精度が向上

---

## アーキテクチャ

```
┌──────────────────────────────────────────────────────┐
│              Orchestrator (asyncio 常駐)              │
│                                                      │
│  Poller ──→ Event Router ──→ Task Queue              │
│  (2分間隔)                    (Priority + Semaphore)  │
│                                   │                  │
│                            ┌──────┴──────┐           │
│                            │ Claude Agent │           │
│                            │  SDK Runner  │           │
│                            └──────┬──────┘           │
│                                   │                  │
│                       ┌───────────┼───────────┐      │
│                       ▼           ▼           ▼      │
│                   GitHub      Slack       Event      │
│                   Client     Notifier     Logger     │
└──────────────────────────────────────────────────────┘
```

---

## ワークフロー

Issue は内容に応じて4つのタイプに自動分類され、タイプごとに最適化されたワークフローで処理されます。

| タイプ | 判定基準 | フロー | コスト目安 |
|-------|---------|-------|-----------|
| 🐛 **Bug** | エラー・不具合 | ANALYSIS → 👍承認 → FIX → PR | ~$0.80 |
| ⚡ **Feature-S** | 1-3ファイル変更 | HEARING → PLAN_BRIEF → 👍承認 → IMPLEMENT → PR | ~$0.90 |
| 🏗️ **Feature-M** | 複数ファイル、設計必要 | HEARING → DESIGN PR → approve → PLANNING → IMPLEMENT → PR | ~$1.50 |
| 🏢 **Feature-L** | 大規模、分割必要 | HEARING → 分割提案 → 子Issue作成 → 各子をタイプ別処理 | $2.0 + N×$1.50 |

---

## クイックスタート

### 前提条件

| ソフトウェア | バージョン |
|------------|-----------|
| Python | 3.13+ |
| [uv](https://docs.astral.sh/uv/) | 最新版 |
| git | 2.20+ |
| [gh (GitHub CLI)](https://cli.github.com/) | 2.0+ |
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | 最新版 |

### インストール

```bash
# リポジトリのクローン
git clone https://github.com/Akihiro1028Bad/ai-agent-team2.git
cd ai-agent-team2

# 依存関係のインストール
uv sync --all-extras

# インストール確認
uv run ai-agent --help
```

### 初期セットアップ

```bash
# 1. GitHub アカウントを登録 (トークンを keyring に保存)
uv run ai-agent account add my-org

# 2. 対象リポジトリをセットアップ (clone + ラベル作成 + config.yaml 更新)
uv run ai-agent setup myorg/my-app --account my-org

# 3. 認証・接続チェック
uv run ai-agent health

# 4. オーケストレーターを起動
uv run ai-agent start --foreground
```

### 動作確認

対象リポジトリで `ai-agent` ラベルを付けた Issue を作成すると、2分以内にポーリングで検知され、自動処理が開始されます。

---

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `ai-agent account add <name>` | GitHub アカウントを追加 |
| `ai-agent account list` | 登録済みアカウント一覧 |
| `ai-agent account verify [name]` | トークンの有効性を検証 |
| `ai-agent account remove <name>` | アカウントを削除 |
| `ai-agent setup <owner/repo>` | リポジトリの初期セットアップ |
| `ai-agent unregister <owner/repo>` | リポジトリの登録解除 |
| `ai-agent start [--foreground]` | オーケストレーターを起動 |
| `ai-agent stop` | オーケストレーターを停止 |
| `ai-agent status [--json]` | 稼働状況を表示 |
| `ai-agent logs [-f] [-n N]` | ログを表示 |
| `ai-agent health` | 認証・接続チェック |

---

## 設定

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

  - owner: "myorg"
    repo: "backend-api"
    account: "my-org"
    base_branch: "develop"

concurrency:
  max_total: 2
  max_per_repo: 1

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
  default_channel: "#ai-agent"
```

主な設定項目については [セットアップガイド](docs/setup-guide.md) を参照してください。

### クレデンシャル

GitHub トークンは以下の優先順位で解決されます:

1. **keyring** (OS セキュアストレージ) — `ai-agent account add` で登録。推奨
2. **環境変数** — `GITHUB_TOKEN_{NAME}` 形式
3. **token_command** — 外部コマンド (1Password CLI, AWS Secrets Manager 等)
4. **gh auth token** — GitHub CLI のフォールバック

---

## 技術スタック

| カテゴリ | 技術 | 用途 |
|---------|------|------|
| 言語 | Python 3.13+ | 実行環境 |
| パッケージ管理 | uv | 依存関係管理・仮想環境 |
| CLI | Typer + Rich | CLI フレームワーク |
| GitHub API | githubkit | 非同期 GitHub API 操作 (型付き) |
| HTTP | httpx | 非同期 HTTP クライアント |
| AI 基盤 | Claude Agent SDK | AI エージェント実行 |
| 状態機械 | python-statemachine | フェーズ遷移管理 |
| 設定 | pydantic-settings + PyYAML | YAML 設定 + 環境変数 |
| 認証 | keyring | OS Keychain によるトークン管理 |
| テスト | pytest + pytest-asyncio + respx + hypothesis | テストフレームワーク |
| Lint / Format | ruff | Linter + Formatter |
| 型チェック | mypy (strict) | 静的型チェック |

---

## 開発

### コマンド

```bash
# 依存関係インストール
uv sync --all-extras

# テスト実行
uv run pytest tests/ -v

# 単体テストのみ
uv run pytest tests/unit/ -v

# 型チェック
uv run mypy src/

# lint + format チェック
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

### プロジェクト構成

```
src/ai_agent_orchestrator/
├── cli.py                    # Typer CLI エントリポイント
├── models.py                 # Enum, dataclass (Phase, IssueState 等)
├── protocols.py              # Protocol 定義 (AgentRunner, Notifier, Tracker)
├── credential.py             # 4段階トークン解決
├── state_persistence.py      # Issue 状態のファイルベース永続化
├── event_logger.py           # events.jsonl ログ
├── workspace_manager.py      # git worktree 管理
├── config/settings.py        # pydantic-settings (AppSettings)
├── github/client.py          # GitHubClient (githubkit ラッパー)
├── agents/claude_runner.py   # ClaudeAgentRunner (SDK 実行)
├── notifications/slack.py    # SlackNotifier (Webhook)
├── context/engine.py         # リポマップ + 関連ファイル検索
├── orchestrator/
│   ├── orchestrator.py       # メインオーケストレーター
│   ├── state_machine.py      # フェーズ遷移ロジック
│   └── task_queue.py         # asyncio.PriorityQueue + Semaphore
├── poller/
│   ├── github_poller.py      # GitHub Polling (2分間隔)
│   └── event_router.py       # イベント → フェーズ遷移
├── phases/                   # フェーズ実行ロジック
│   ├── base.py               # PhaseExecutor 基底
│   ├── hearing.py            # ヒアリング
│   ├── design.py             # 設計書作成
│   ├── planning.py           # 実装計画
│   ├── implement.py          # 実装
│   └── ...                   # その他フェーズ
├── knowledge/                # 自己改善ループ
│   ├── episode_store.py      # エピソード記憶
│   ├── pattern_extractor.py  # パターン抽出
│   └── skill_manager.py      # Skill 管理
└── commands/                 # CLI サブコマンド
    ├── account.py
    ├── setup.py
    └── run.py

tests/
├── unit/                     # 単体テスト (モック使用、高速)
├── integration/              # 結合テスト
└── e2e/                      # E2E テスト
```

### 設計原則

1. **Protocol ベース** — 全外部依存を `typing.Protocol` で抽象化し、テスタビリティを確保
2. **完全非同期** — `asyncio` ベースの非同期設計。ブロッキング呼び出し禁止
3. **イミュータブルデータ** — `dataclass(frozen=True)` で状態を表現
4. **Fail-safe** — 全フェーズでタイムアウト・リトライ・エラー通知を実装
5. **Observability** — 構造化イベントログ (`events.jsonl`) による全アクション追跡

---

## ドキュメント

| ドキュメント | 説明 |
|------------|------|
| [設計書](docs/design-python.md) | メイン設計書 (23章) |
| [アーキテクチャ図解](docs/architecture-diagrams.md) | Mermaid 図解 |
| [API リファレンス](docs/api-reference.md) | 型定義・Protocol 仕様 |
| [セットアップガイド](docs/setup-guide.md) | インストールから初回実行まで |
| [プロンプトテンプレート](docs/templates/README.md) | AI に渡す14種のテンプレート |

---

## GitHub Labels

オーケストレーターは GitHub Labels でフェーズを管理します。`ai-agent setup` で自動作成されます。

| ラベル | 説明 |
|-------|------|
| `ai-agent` | AI に割り当てる Issue |
| `type:bug` / `type:feature-s` / `type:feature-m` / `type:feature-l` | タイプ分類 |
| `phase:hearing` ~ `phase:done` | 現在のフェーズ |
| `plan:pending` / `plan:approved` | 方針承認状態 |
| `needs-split` | Issue 分割の判断待ち |
| `phase:suspended` | エラー等で保留中 |

全ラベル一覧は `--full-labels` オプションで作成できます (全28ラベル)。

---

## 検証結果

実際のテストリポジトリでの検証結果:

| 検証項目 | 結果 | 実コスト |
|---------|------|---------|
| タイプ自動判定 (Bug/Feature-S/Feature-M/Feature-L) | 4/4 正解 | $0.055 |
| Bug ワークフロー (ANALYSIS → 👍 → FIX → PR) | 6/6 PASS | $0.33 |
| Feature-S ワークフロー (HEARING → PLAN_BRIEF → 👍 → PR) | 6/6 PASS | $0.46 |
| Feature-L 分割 (提案 → 子Issue 11個 → ラベル) | 38/38 PASS | $0.32 |
| E2E (子Issue → PR → 完了 → ブロック解除 → PR) | 20/22 PASS | $1.32 |
| **合計** | **91/93 PASS** | **$2.72** |

---

## ライセンス

MIT License
