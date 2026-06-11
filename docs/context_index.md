# コンテキスト索引

> サブエージェントに「最小限のコンテキスト」を渡すための地図。
> 「この作業はどこを読めばよいか」を引くために使う。詳細は各ファイルの docstring を参照。

## どこに何があるか

| 関心事 | 主なファイル |
|---|---|
| Enum・dataclass（Phase, IssueState, TaskRequest, ApprovalMethod） | `src/ai_agent_orchestrator/models.py` |
| Protocol 定義 | `src/ai_agent_orchestrator/protocols.py`, `phases/base.py` |
| 設定（AppSettings, RepositoryConfig, approvers, control_file） | `src/ai_agent_orchestrator/config/settings.py` |
| 状態機械（遷移定義・VALID_TRANSITIONS） | `src/ai_agent_orchestrator/orchestrator/state_machine.py`, `models.py` |
| メインループ・executor 登録 | `src/ai_agent_orchestrator/orchestrator/orchestrator.py` |
| タスクキュー | `src/ai_agent_orchestrator/orchestrator/task_queue.py` |
| 承認/差し戻し判定・承認者検証（#102） | `src/ai_agent_orchestrator/orchestrator/approval.py` |
| control.jsonl 受け口 | `src/ai_agent_orchestrator/orchestrator/control_file.py` |
| ポーリング・イベント検知 | `src/ai_agent_orchestrator/poller/github_poller.py` |
| イベント→フェーズ遷移 | `src/ai_agent_orchestrator/poller/event_router.py` |
| フェーズ実行ロジック | `src/ai_agent_orchestrator/phases/`（`base.py`, `plan.py`, `implement.py`, `revise.py` ほか） |
| PLAN 統合（analysis/design） | `phases/plan.py`, `plan_artifact.py`, `plan_validation.py` |
| GitHub API ラッパー | `src/ai_agent_orchestrator/github/client.py` |
| Claude 実行 | `src/ai_agent_orchestrator/agents/claude_runner.py` |
| git worktree | `src/ai_agent_orchestrator/workspace_manager.py` |
| CLI | `src/ai_agent_orchestrator/cli.py`, `commands/`（run/account/setup） |
| テスト（単体） | `tests/unit/`（`test_*.py`、`conftest.py` の Fake/fixture） |
| 設計ドキュメント | `docs/`（design-python.md ほか）、`docs/designs/`（Issue 別設計） |

## 後方互換 re-export（実体は統合先）

- `phases/analysis.py`, `phases/design.py` → `phases/plan.py` の `PlanExecutor`
- `phases/fix.py` → `phases/implement.py` の `ImplementExecutor`
- `phases/design_revise.py`, `phases/impl_revise.py` → REVISE 系（`revise.py` / `revise_common.py`）

## 最小コンテキストの渡し方

- 上表で関連ファイルを 1〜数個に絞ってからサブエージェントに渡す。
- 「全体像が要る」場合のみ Explore に範囲を指定して結論だけ受け取る（全文を Fable5 に載せない）。
