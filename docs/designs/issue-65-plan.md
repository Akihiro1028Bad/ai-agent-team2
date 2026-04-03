# Issue #65 実装計画: claudeの/reviewを使えるようにしたい

## 概要

Claude Code の `/review` コマンドを PR レビューに活用する。
以下の3点を実装する。

1. `.github/workflows/claude-review.yml` — `@claude /review` を検知して Claude Code を起動する GitHub Actions ワークフロー
2. `src/ai_agent_orchestrator/phases/design.py` — 設計 PR 作成後に `@claude /review` コメントを自動投稿
3. `src/ai_agent_orchestrator/poller/event_router.py` — CI success 後に実装 PR へ `@claude /review` コメントを自動投稿

---

## サブタスク

### subtask-1: GitHub Actions ワークフロー追加
- files: [`.github/workflows/claude-review.yml`]
- depends_on: []
- description: |
    `.github/workflows/claude-review.yml` を新規作成する。
    - トリガー: `issue_comment` (types: [created])
    - 実行条件: PRコメント (`github.event.issue.pull_request != null`) かつ `@claude /review` を含む かつ ボットコメント除外 (`github.event.comment.user.type != 'Bot'`)
    - concurrency: `claude-review-${{ github.event.issue.number }}`、`cancel-in-progress: false`
    - permissions: `contents: read`、`pull-requests: write`
    - ステップ: `actions/checkout@v4` (fetch-depth: 0) → `anthropics/claude-code-action@v1` (claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }})

### subtask-2: design.py に設計レビュー用コメント投稿を追加
- files: [`src/ai_agent_orchestrator/phases/design.py`]
- depends_on: []
- description: |
    `process_result()` の末尾に `@claude /review` コメント投稿処理を追加する。
    - ファイル先頭に定数 `_DESIGN_REVIEW_PROMPT` を定義（設計レビュー観点のプロンプト）
    - `_post_design_review_comment(request, pr_number)` メソッドを追加
      - `client.create_comment(request.repo, pr_number, _DESIGN_REVIEW_PROMPT)` を呼び出す
      - 投稿失敗は `logger.warning` でログを残し例外を握り潰す（フェーズ遷移を止めない）
    - `process_result()` の `await self._sm.transition(...)` 直後に `await self._post_design_review_comment(request, pr_number)` を呼び出す

### subtask-3: event_router.py に実装レビュー用コメント投稿を追加
- files: [`src/ai_agent_orchestrator/poller/event_router.py`]
- depends_on: []
- description: |
    `_handle_ci_result()` の `ci_status == "success"` ブロックを拡張する。
    - ファイル先頭に定数 `_IMPL_REVIEW_PROMPT` を定義（実装レビュー観点のプロンプト）
    - `_post_impl_review_comment(event)` メソッドを追加
      - `self._sm.get_state(event.issue.number)` で `pr_number` を取得
      - `pr_number` が None の場合は警告ログを出してスキップ
      - `client.create_comment(event.repo, state.pr_number, _IMPL_REVIEW_PROMPT)` を呼び出す
      - 投稿失敗は `logger.warning` でログを残し例外を握り潰す
    - 既存の `ci_status == "success"` ブロックを変更:
      - `current != Phase.IMPL_REVIEW` の場合のみ遷移 + `_post_impl_review_comment` 呼び出し（冪等性保証）
      - `current == Phase.IMPL_REVIEW` の場合はコメント投稿をスキップ

### subtask-4: テスト追加
- files: [`tests/unit/test_phases.py`, `tests/unit/test_event_router.py`]
- depends_on: [2, 3]
- description: |
    **test_phases.py への追加**:
    - `DesignExecutor.process_result()` が `create_comment` を呼び出し `@claude /review` を含むコメントを投稿することを確認
    - `create_comment` が例外を投げた場合も DESIGN_REVIEW 遷移が完了することを確認

    **test_event_router.py への追加**:
    - `_handle_ci_result()` の `ci_status == "success"` 時に `create_comment` で `@claude /review` が投稿されることを確認
    - CI success が2回来た場合（2回目は既に IMPL_REVIEW 状態）は `create_comment` が1回のみ呼ばれることを確認（冪等性テスト）
    - `state.pr_number` が None の場合はコメント投稿がスキップされることを確認
    - `create_comment` が例外を投げた場合も IMPL_REVIEW 遷移が完了することを確認
    - 既存の `test_ci_success_routes_to_impl_review` に `create_comment` モックを追加して更新
