# Issue #69 実装計画: レビュー指摘コメントを複数同時にコメントしても全てに適切に対応できるようにする

## 概要

PRのレビュー指摘コメントが複数同時に投稿された場合でも全指摘に漏れなく対応できるよう、以下の3点を実装する。

1. `GitHubClient` / `GitHubClientProtocol` へのレビューコメント返信・一覧取得APIの追加
2. `event_router.py` の `_handle_impl_pr_commented` を修正し、全未対応コメントを収集して着手通知を送信
3. `impl_revise.py` の `build_prompt` 改善と `process_result` への完了通知追加

## サブタスク

### subtask-1: GitHubClient と Protocol への新メソッド追加
- files: [`src/ai_agent_orchestrator/github/client.py`, `src/ai_agent_orchestrator/protocols.py`]
- depends_on: []
- description: `GitHubClient` に `reply_to_review_comment(repo, pr_number, comment_id, body)` と `get_pr_review_comments(repo, pr_number)` を追加する。`reply_to_review_comment` は `pulls.async_create_reply_for_review_comment` APIを呼び出し、本文末尾に `<!-- ai-agent-bot -->` マーカーを付与する。`get_pr_review_comments` は `pulls.async_list_review_comments` を呼び出し、ボットコメント（`<!-- ai-agent-bot -->` を含む）を除外して `id`, `user`, `body`, `path`, `line`, `created_at` を含む辞書リストを返す（`per_page=100`）。`protocols.py` の `GitHubClientProtocol` にも同じシグネチャを追加し、FakeGitHubClient による型安全なテストを可能にする。既存の `get_pr_comments(owner, repo, pr_number)` とはシグネチャが異なる（`RepositoryConfig` を受け取る）ため、既存メソッドには手を加えない。

### subtask-2: event_router.py の `_handle_impl_pr_commented` 修正
- files: [`src/ai_agent_orchestrator/poller/event_router.py`]
- depends_on: [1]
- description: `_handle_impl_pr_commented` を修正し、イベント単体のコメントではなく `get_pr_review_comments` APIでPRの全未対応レビューコメントを収集する。`_get_client` は1回だけ呼び出して再利用する。収集したコメントをモジュールレベルの `_format_review_comments(comments)` ヘルパーでフォーマットし、`review_comment_ids` と `comments` を `TaskRequest.extra` に含めてエンキューする。フェーズ遷移・エンキュー成功後に `_reply_to_review_comments` ヘルパーメソッドで各コメントスレッドへ着手通知「レビュー指摘を確認しました。修正を開始します。」を返信する。`get_pr_review_comments` 失敗時は `logger.warning` + `event.extra["comments"]` へのフォールバック、着手通知失敗時は `logger.debug` + 継続のエラーハンドリングを実装する。`IMPL_REVISE` 中のスキップ処理は維持する（先発タスクが全コメントを包含済みのため）。`_reply_to_review_comments` ヘルパーはループ内で個別に try/except し、1件失敗しても残りのコメントへの返信を継続する。

### subtask-3: impl_revise.py の `build_prompt` 改善と完了通知追加
- files: [`src/ai_agent_orchestrator/phases/impl_revise.py`]
- depends_on: [1]
- description: `build_prompt` を修正し、`extra["review_comment_ids"]` が存在する場合に「今回は N 件のレビュー指摘があります。全ての指摘に対応してください。」という注意書きをプロンプトに追記する。`process_result` に完了通知処理を追加する: IMPL_REVIEW への遷移後、`extra["review_comment_ids"]` と `state_data.pr_number` が存在する場合に `_reply_completion_to_review_comments(request, pr_number, comment_ids)` ヘルパーを呼び出し、各コメントスレッドへ「修正が完了しました。コードをご確認ください。」を返信する。完了通知の失敗は `logger.debug` + 握り潰しとし、IMPL_REVIEW 遷移や Slack 通知は継続する。

### subtask-4: テストの追加
- files: [`tests/conftest.py`, `tests/unit/test_github_client.py`, `tests/unit/test_event_router.py`, `tests/unit/test_phases.py`]
- depends_on: [1, 2, 3]
- description: `tests/conftest.py` の `FakeGitHubClient` に `reply_to_review_comment` と `get_pr_review_comments` を追加する。`reply_to_review_comment` は `replied_comments: list[tuple[int, str]]` に呼び出し記録を保持する。`get_pr_review_comments` は `review_comments_data: list[dict]` フィールドを返す（テストごとに設定可能）。`test_github_client.py` では新メソッドのAPIパラメータ（`pulls.async_create_reply_for_review_comment` の呼び出し確認）とボットコメント除外ロジック（`<!-- ai-agent-bot -->` を含むコメントが除外されること）を検証する。`test_event_router.py` では複数コメント同時収集・着手通知送信（遷移・エンキュー後に送信されること）・`IMPL_REVISE` 中のスキップ処理・`get_pr_review_comments` 失敗時のフォールバック・着手通知失敗時のフェーズ遷移継続を検証する。`test_phases.py` では完了通知の送信・`review_comment_ids` が空の場合のスキップ・通知失敗時の IMPL_REVIEW 遷移継続・`build_prompt` の複数コメント件数表示を検証する。
