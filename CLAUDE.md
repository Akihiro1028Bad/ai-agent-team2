# CLAUDE.md - AI Multi-Agent Orchestrator

## プロジェクト概要

GitHub Issue を自動で処理する AI マルチエージェントオーケストレーター。
Issue の受付 → ヒアリング → 設計 → 実装 → PR作成 → レビュー対応を自動化する。

## モデルルーティング / トークン ROI

メインが Fable5 のとき、全作業を Fable5 で実行しない。Fable5 は**設計・判断・監査・レビュー・
最終品質担保**に集中し、中間作業は Opus/Sonnet のサブエージェントに委譲する。
節約対象は中間作業のみで、最終成果物の品質は絶対に下げない（節約の目的化はしない）。

- **Fable5 が直接扱う**: 設計判断、アーキ/UX/事業への影響、手戻りの大きい箇所、実装難所、最終レビュー・品質確認
- **サブエージェントに委譲**: 調査・コード読解・整理、単純実装、テスト追加、差分確認、軽微な修正
- サブエージェントには**最小限のコンテキスト**だけ渡す（→ [docs/context_index.md](docs/context_index.md)）
- 委譲結果は「変更内容・判断理由・懸念点・Fable5 が判断すべきこと」に圧縮して返させる
- 最終的な設計整合性・UX・実装リスク・品質は必ず Fable5 が確認（→ [docs/quality_checklist.md](docs/quality_checklist.md)）

詳細: [モデルルーティング方針](docs/ai_model_routing.md) ／ [サブエージェント・プロンプト雛形](docs/subagent_prompt_templates.md)

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
├── logging_config.py          # ロギング設定
├── cli.py                     # Typer メインapp
├── __main__.py                # python -m エントリポイント
├── config/
│   └── settings.py            # pydantic-settings (AppSettings, RepositoryConfig等)
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
│   ├── orchestrator.py        # メインオーケストレーター
│   ├── approval.py            # 承認判定の共通化 + 承認者検証 (U4 #82 / #102)
│   ├── control_file.py        # control.jsonl 受け口 (Web UI 承認の最小スタブ)
│   └── execution_guard.py     # 実行ガード
├── poller/
│   ├── github_poller.py       # GitHubPoller (Polling)
│   └── event_router.py        # EventRouter (イベント→フェーズ遷移)
├── phases/                    # フェーズ実行ロジック (PhaseExecutor 実装)
│   ├── base.py                # PhaseExecutor基底
│   ├── dispatcher.py          # PhaseDispatcher (フェーズ→executor 振り分け)
│   ├── type_detection.py      # タイプ判定 (bug / feature-m / feature-l)
│   ├── hearing.py             # ヒアリング
│   ├── plan.py                # PLAN (analysis/design 統合, plan_depth=light/full) ※U3
│   ├── plan_artifact.py       # 構造化 plan JSON 生成 (ui_impact 等)
│   ├── plan_validation.py     # 設計書の ## サブタスク 構造検証
│   ├── analysis.py            # 後方互換 re-export → PlanExecutor (light)
│   ├── design.py              # 後方互換 re-export → PlanExecutor (full)
│   ├── implement.py           # 実装 (fix 統合, サブタスク対応) ※U5a
│   ├── fix.py / fix_flow.py   # 後方互換 re-export + fix 固有フロー
│   ├── ci_fix.py / ci_log_parser.py  # CI失敗修正
│   ├── revise.py / revise_common.py  # REVISE 統合 (レビュー対応・質問回答) ※U2
│   ├── design_revise.py / impl_revise.py  # 後方互換 re-export
│   ├── review_classifier.py   # レビュー指摘の分類 (質問/修正/nit)
│   ├── prompt_enhancer.py     # プロンプト補強
│   ├── done.py                # 完了処理
│   └── split.py               # Feature-L 分割
├── knowledge/                 # 自己改善ループ
│   ├── episode_store.py
│   ├── pattern_extractor.py
│   └── skill_manager.py
└── commands/                  # CLIサブコマンド
    ├── account.py             # アカウント管理
    ├── setup.py               # 初期セットアップ
    └── run.py                 # start/stop/status/health/logs

# 注: パイプライン再設計 (統一パイプライン) を U1〜U5 として段階実施中。
#     フェーズ統合は旧フェーズ名のまま進め、Phase enum/遷移の刷新は U5 (#83) で
#     一括実施予定。analysis/design/fix/design_revise/impl_revise は統合先への
#     後方互換 re-export として残置中。

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
2. **タイプ別ワークフロー**: Bug / Feature-M / Feature-L で異なるフェーズ。統一パイプライン
   化を進行中で、タイプ差は `plan_depth`（light/full）等のパラメータへ集約しつつある
3. **承認の統一 (U4 #82)**: 👍リアクション / PR approve / LGTM コメントを `approval.py` の
   共通判定（`classify_pr_review` 等）で一本化。差し戻し（指摘）は PLAN（analysis/design）へ
   戻し、指摘全文を feedback として再実行プロンプトに渡す
4. **承認者検証 (#102)**: 承認は許可リスト（既定はリポジトリ owner、`RepositoryConfig.approvers`
   で設定可）に含まれるユーザーのみ有効。許可外の承認は無視。コメント/指摘・PRマージには非適用
5. **worktree 分離**: 並行 Issue 処理は git worktree で物理的に分離
6. **4段階トークン解決**: keyring → 環境変数 → token_command → gh auth token
7. **commit 一本化 (U1)**: エージェントはファイル変更のみ。コミット/push は orchestrator が
   成果物除外（denylist）付きで実行
8. **自己改善ループ**: エピソード記憶 → パターン抽出 → Skill検出 → メトリクス改善

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
