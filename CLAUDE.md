# CLAUDE.md - AI Multi-Agent Orchestrator

## プロジェクト概要

GitHub Issue を自動で処理する AI マルチエージェントオーケストレーター。
Issue の受付 → ヒアリング → 設計 → 実装 → PR作成 → レビュー対応を自動化する。

## 技術スタック

- **言語**: Python 3.13+
- **パッケージ管理**: uv
- **CLI**: Typer + Rich
- **GitHub API**: githubkit (非同期)
- **AI実行**: Claude Agent SDK (query, ClaudeSDKClient)
- **HTTP**: httpx
- **状態機械**: python-statemachine
- **設定**: pydantic-settings + YAML
- **認証**: keyring (OS Keychain)
- **テスト**: pytest + pytest-asyncio (auto mode) + respx + hypothesis

## ディレクトリ構成

```
src/ai_agent_orchestrator/     # メインパッケージ
├── models.py                  # Enum, dataclass (Phase, IssueState, TaskRequest等)
├── protocols.py               # Protocol定義 (AgentRunner, Notifier, Tracker等)
├── credential.py              # CredentialResolver (4段階トークン解決)
├── state_persistence.py       # Issue状態のファイルベース永続化
├── event_logger.py            # events.jsonl ログ + トークンサニタイズ
├── config/
│   └── settings.py            # pydantic-settings (AppSettings, AccountConfig等)
├── github/
│   └── client.py              # GitHubClient (githubkit ラッパー)
├── agents/
│   └── claude_runner.py       # ClaudeAgentRunner (SDK実行)
├── notifications/
│   └── slack.py               # SlackNotifier (Webhook)
├── workspace_manager.py       # git worktree 管理
├── context/
│   └── engine.py              # ContextEngine (リポマップ + 関連ファイル検索)
├── orchestrator/
│   ├── state_machine.py       # StateMachine (python-statemachine)
│   ├── task_queue.py          # TaskQueue (asyncio.PriorityQueue + Semaphore)
│   └── orchestrator.py        # メインオーケストレーター
├── poller/
│   ├── github_poller.py       # GitHubPoller (Polling)
│   └── event_router.py        # EventRouter (イベント→フェーズ遷移)
├── phases/                    # フェーズ実行ロジック
│   ├── base.py                # PhaseExecutor基底
│   ├── type_detection.py      # タイプ判定
│   ├── hearing.py             # ヒアリング
│   ├── analysis.py            # Bug原因分析
│   ├── plan_brief.py          # Feature-S簡易方針
│   ├── design.py              # Feature-M設計書
│   ├── planning.py            # 実装計画
│   ├── implement.py           # 実装
│   ├── fix.py                 # Bug修正
│   ├── ci_fix.py              # CI失敗修正
│   ├── revise.py              # レビュー対応
│   └── split.py               # Feature-L分割
├── knowledge/                 # 自己改善ループ
│   ├── episode_store.py
│   ├── pattern_extractor.py
│   └── skill_manager.py
├── cli.py                     # Typer メインapp
└── commands/                  # CLIサブコマンド
    ├── account.py
    ├── setup.py
    └── run.py

tests/
├── conftest.py                # 共通fixture (FakeGitHub, FakeClaude等)
├── unit/                      # 単体テスト (モック使用、高速)
└── integration/               # 結合テスト (実API)

docs/
├── design-python.md           # メイン設計書 (23章)
├── architecture-diagrams.md   # Mermaid図解 (24枚)
├── api-reference.md           # 型定義・Protocol仕様
├── setup-guide.md             # セットアップ手順
├── specs/                     # モジュール別実装仕様書 (実装時に生成)
└── templates/                 # プロンプトテンプレート (14種)
```

## コマンド

```bash
# 依存関係インストール
uv sync --all-extras

# テスト実行
uv run pytest tests/ -v

# 単体テストのみ
uv run pytest tests/unit/ -v

# 型チェック
uv run mypy src/

# lint + format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# CLI実行
uv run ai-agent --help
```

## コーディング規約

- **型**: mypy strict モード。全関数に型アノテーション必須
- **非同期**: `async def` + `await` を基本とする。ブロッキング呼び出し禁止
- **インターフェース**: `typing.Protocol` で定義。具象クラスは Protocol を実装
- **エラー処理**: 具体的な例外クラスを定義。裸の `except:` 禁止
- **テスト**: テスト先行（TDD）。pytest-asyncio auto mode。モックは respx + FakeClass
- **インポート順**: stdlib → 外部ライブラリ → 内部モジュール（ruff isort で自動整列）
- **命名**: snake_case（変数・関数）、PascalCase（クラス）、UPPER_CASE（定数）
- **docstring**: クラスと公開メソッドに必須。Google style

## 設計上の重要な決定事項

1. **Protocol ベース**: 全外部依存を Protocol で抽象化 → テスタビリティ確保
2. **タイプ別ワークフロー**: Bug / Feature-S / Feature-M / Feature-L で異なるフェーズ
3. **👍 リアクション承認**: Bug/Feature-S は Issue コメントへの👍で方針承認
4. **PR approve 承認**: Feature-M は設計PR/実装PR の GitHub approve で承認
5. **worktree 分離**: 並行 Issue 処理は git worktree で物理的に分離
6. **4段階トークン解決**: keyring → 環境変数 → token_command → gh auth token
7. **自己改善ループ**: エピソード記憶 → パターン抽出 → Skill検出 → メトリクス改善

## テストの書き方

```python
# tests/unit/test_example.py
import pytest
from ai_agent_orchestrator.models import Phase

# pytest-asyncio auto mode: async def は自動的にasyncテストになる
async def test_phase_transition():
    # Arrange
    sm = create_test_state_machine()
    # Act
    sm.transition(42, Phase.HEARING)
    # Assert
    assert sm.get_phase(42) == Phase.HEARING

# Protocol の Fake 実装を使う
async def test_with_fake_github(fake_github: FakeGitHubClient):
    fake_github.issues[42] = FakeIssue(title="Test", body="Test body")
    result = await some_service.process(42)
    assert result.success
```

## PR ルール

- タイトル: conventional commits 形式 (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`)
- テストが通ること (`uv run pytest`)
- mypy が通ること (`uv run mypy src/`)
- ruff が通ること (`uv run ruff check .`)
