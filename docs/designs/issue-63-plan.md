# Issue #63 実装計画: Claude /review 自動実行機能

## 概要

DESIGN_REVIEW および IMPL_REVIEW フェーズへの遷移時に、関連 PR に `@claude /review-impl` または `@claude /review-design` を自動コメントし、Claude Code GitHub Actions によるコードレビューを自動実行する機能を追加する。

ボットコメント（`github-actions[bot]`）による自動フェーズ遷移は行わず、人間のコメントのみ IMPL_REVISE / DESIGN_REVISE への遷移をトリガーする。

---

## 変更ファイル一覧

| ファイル | 変更種別 |
|----------|----------|
| `.github/workflows/claude-impl-review.yml` | 新規作成 |
| `.github/workflows/claude-design-review.yml` | 新規作成 |
| `src/ai_agent_orchestrator/orchestrator/state_machine.py` | 変更 |
| `src/ai_agent_orchestrator/poller/event_router.py` | 変更 |
| `docs/specs/event-router.md` | 変更 |
| `tests/unit/test_state_machine.py` | 変更 |
| `tests/unit/test_event_router.py` | 変更 |

---

## サブタスク

### subtask-1: GitHub Actions ワークフロー新規作成
- files: [`.github/workflows/claude-impl-review.yml`, `.github/workflows/claude-design-review.yml`]
- depends_on: []
- description: |
    実装レビュー用と設計レビュー用の Claude Code GitHub Actions ワークフローを新規作成する。

    **claude-impl-review.yml:**
    - トリガー: `issue_comment` (created) で `@claude /review-impl` を含むコメント
    - 条件: `github.event.issue.pull_request != null`（PR へのコメントのみ）
    - 権限: `contents: read`, `pull-requests: write`, `issues: write`
    - ステップ: `actions/checkout@v4` → `anthropics/claude-code-action@beta`
    - プロンプト: バグ・ロジックエラー（最重要）、コード品質、エラーハンドリング、テスト、セキュリティの観点でレビュー
    - シークレット: `CLAUDE_CODE_OAUTH_TOKEN`

    **claude-design-review.yml:**
    - トリガー: `issue_comment` (created) で `@claude /review-design` を含むコメント
    - 条件: `github.event.issue.pull_request != null`
    - 権限: `contents: read`, `pull-requests: write`, `issues: write`
    - ステップ: `actions/checkout@v4` → `anthropics/claude-code-action@beta`
    - プロンプト: 設計の妥当性（最重要）、アーキテクチャ・構造、インターフェース設計、実現可能性・リスク、ドキュメント品質の観点でレビュー
    - シークレット: `CLAUDE_CODE_OAUTH_TOKEN`

### subtask-2: StateMachineManager にトランジションフック機能を追加
- files: [`src/ai_agent_orchestrator/orchestrator/state_machine.py`]
- depends_on: []
- description: |
    `StateMachineManager` に遷移後コールバック機能を追加する。

    **追加フィールド:**
    ```python
    self._transition_hooks: dict[
        Phase, list[Callable[[int, Phase], Awaitable[None]]]
    ] = {}
    ```

    **追加メソッド `register_transition_hook()`:**
    - 引数: `target_phases: list[Phase]`, `callback: Callable[[int, Phase], Awaitable[None]]`
    - 指定フェーズへの遷移後に呼び出されるコールバックを `_transition_hooks` に登録する
    - 複数フックの登録をサポート（`setdefault` で追加）

    **`transition()` メソッドへの変更:**
    - 既存の遷移処理が成功した後、`_transition_hooks[target_phase]` に登録されたフックを順に `await` で呼び出す
    - フック内の例外はログに ERROR を記録してスキップ（遷移の成否に影響しない）
    - フック実行は遷移成功時のみ（`success == True` の場合）

### subtask-3: EventRouter にボットフィルタと自動レビューコメント投稿を追加
- files: [`src/ai_agent_orchestrator/poller/event_router.py`, `docs/specs/event-router.md`]
- depends_on: [2]
- description: |
    **定数の追加（モジュールレベル）:**
    ```python
    _BOT_COMMENT_AUTHORS: frozenset[str] = frozenset({
        "github-actions[bot]",
        "claude[bot]",
    })
    _REVIEW_COMMANDS: dict[str, str] = {
        "impl": "@claude /review-impl",
        "design": "@claude /review-design",
    }
    ```

    **`EventRouter.__init__()` での フック登録:**
    - `self.state_machine.register_transition_hook()` を呼び出し、
      `[Phase.IMPL_REVIEW, Phase.DESIGN_REVIEW]` フェーズへの遷移後に
      `self._on_review_phase_entered` を登録する

    **`_on_review_phase_entered()` メソッドの追加:**
    - 引数: `issue_number: int`, `phase: Phase`
    - `phase == Phase.IMPL_REVIEW` なら `review_type = "impl"`, それ以外は `"design"`
    - `self._post_claude_review_comment(issue_number, review_type)` を呼び出す

    **`_post_claude_review_comment()` メソッドの追加:**
    - `issue_state = self.state_machine.get_state(issue_number)` で状態取得
    - `issue_state` が None の場合: WARNING ログ出力 → return
    - `review_type == "impl"` なら `pr_number = issue_state.pr_number`,
      それ以外は `pr_number = issue_state.design_pr_number`
    - `pr_number` が None の場合: WARNING ログ出力 → return
    - `comment_body = _REVIEW_COMMANDS[review_type]` を `github_client.create_pr_comment()` で投稿
    - 例外発生時: ERROR ログ出力（ワークフロー継続）

    **`_handle_impl_pr_commented()` へのボットフィルタ追加:**
    - `event.comment.user.login` が `_BOT_COMMENT_AUTHORS` に含まれる場合は
      DEBUG ログを出力して早期 return（IMPL_REVISE 遷移をトリガーしない）

    **`_handle_design_pr_commented()` へのボットフィルタ追加:**
    - 同様に `_BOT_COMMENT_AUTHORS` 判定を追加し、
      `github-actions[bot]` コメントで DESIGN_REVISE 遷移が発生しないようにする

    **`docs/specs/event-router.md` の更新:**
    - `_BOT_COMMENT_AUTHORS` / `_REVIEW_COMMANDS` 定数の説明を追加
    - `_on_review_phase_entered()` / `_post_claude_review_comment()` メソッドの仕様を追加
    - ボットコメントフィルタの動作説明を追記
    - IMPL_REVIEW / DESIGN_REVIEW フェーズ遷移後の自動レビューコメントフローを追記

### subtask-4: 単体テストの追加
- files: [`tests/unit/test_state_machine.py`, `tests/unit/test_event_router.py`]
- depends_on: [2, 3]
- description: |
    **`tests/unit/test_state_machine.py` への追加テスト:**

    | ID | テストケース |
    |----|-------------|
    | TC-63-08 | `register_transition_hook()` で登録したコールバックが遷移後に呼ばれること |
    | TC-63-09 | フック内の例外が遷移の成否に影響しないこと（`transition()` は `True` を返す） |
    | TC-63-10 | 複数フックが登録された場合、全て登録順に呼ばれること |
    | TC-63-11 | 対象フェーズ以外への遷移ではフックが呼ばれないこと |

    **`tests/unit/test_event_router.py` への追加テスト:**

    | ID | テストケース |
    |----|-------------|
    | TC-63-01 | CI 成功時に `create_pr_comment` が `@claude /review-impl` で呼ばれること |
    | TC-63-02 | `github-actions[bot]` の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーしないこと |
    | TC-63-03 | 人間の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーすること（既存動作の維持確認） |
    | TC-63-04 | `pr_number` が None の場合、コメント投稿をスキップしてもエラーにならないこと |
    | TC-63-05 | `github-actions[bot]` の DESIGN_PR_COMMENTED は DESIGN_REVISE 遷移をトリガーしないこと |
    | TC-63-06 | `create_pr_comment` が例外を投げても CI 成功フローが継続すること |
    | TC-63-07 | DESIGN_REVIEW 遷移フックで `design_pr_number` の PR に `@claude /review-design` が投稿されること |

    各テストは既存の `FakeGitHubClient` / `FakeStateMachine` / `AsyncMock` パターンに準拠して実装する。
