# Issue #63 設計書: Claude /review 自動実行機能

## 概要

DESIGN_REVIEW および IMPL_REVIEW フェーズへの遷移時に、関連 PR に `@claude /review` を自動コメントし、Claude Code GitHub Actions によるコードレビューを自動実行する機能を追加する。

Claude のレビューコメントは人間が確認するための参考情報として扱い、ボットコメントによる自動フェーズ遷移は行わない（人間のコメントのみ IMPL_REVISE / DESIGN_REVISE への遷移をトリガーする）。

---

## 要件整理

| 項目 | 内容 |
|------|------|
| `/review` の正体 | Claude Code GitHub Actions 連携（PR に `@claude /review` とコメントすると Claude Code がレビューを実行） |
| 自動コメントのタイミング | CI 成功 → `IMPL_REVIEW` 遷移時 / 設計 PR 作成 → `DESIGN_REVIEW` 遷移時 |
| コメント先 | 実装 PR / 設計 PR |
| ボットコメントの扱い | `github-actions[bot]` のコメントは無視（IMPL_REVISE / DESIGN_REVISE への遷移をトリガーしない） |
| 人間レビューとの関係 | Claude レビューを先に実施 → 人間が Claude の指摘を参考にレビュー → 人間がコメントで修正指示 |
| GitHub Actions 認証 | `CLAUDE_CODE_OAUTH_TOKEN`（設定済み）を使用 |

---

## アーキテクチャ概要

```
CI成功イベント
    │
    ▼
EventRouter._handle_ci_result()
    │  CI成功 → IMPL_REVIEWへ遷移
    ▼
StateMachineManager.transition(IMPL_REVIEW)
    │  遷移成功後にフック起動
    ▼
EventRouter._on_review_phase_entered()  ← NEW
    │
    ▼
GitHubClient.create_pr_comment(pr_number, "@claude /review")  ← NEW
    │
    ▼
GitHub Actions: claude-review.yml が起動
    │  (@claude を含むコメントを検知)
    ▼
anthropics/claude-code-action がレビュー実施
    │
    ▼
github-actions[bot] がレビューコメントを PR に投稿
    │
    ▼
EventRouter: IMPL_PR_COMMENTED を受信
    │  github-actions[bot] のコメント → 無視 (NEW)
    │  人間のコメント → IMPL_REVISE へ遷移（既存動作）
    ▼
人間レビュアーが Claude の指摘を確認 → 必要に応じてコメント → IMPL_REVISE
```

同様のフローが DESIGN_REVIEW / DESIGN_REVISE にも適用される。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 概要 |
|----------|----------|------|
| `.github/workflows/claude-review.yml` | **新規作成** | Claude Code GitHub Actions ワークフロー |
| `src/ai_agent_orchestrator/orchestrator/state_machine.py` | **変更** | `register_transition_hook()` メソッドを追加 |
| `src/ai_agent_orchestrator/poller/event_router.py` | **変更** | IMPL_REVIEW / DESIGN_REVIEW 遷移後に `@claude /review` を自動投稿 |
| `src/ai_agent_orchestrator/poller/event_router.py` | **変更** | `github-actions[bot]` コメントを PR_COMMENTED イベントで無視 |
| `docs/specs/event-router.md` | **変更** | 設計変更を仕様書に反映 |

---

## 詳細設計

### 1. `.github/workflows/claude-review.yml` (新規作成)

Claude Code が PR コメントの `@claude` トリガーに応答するための GitHub Actions ワークフロー。

```yaml
name: Claude Code Review

on:
  issue_comment:
    types: [created]

jobs:
  claude-review:
    if: |
      github.event.issue.pull_request != null &&
      contains(github.event.comment.body, '@claude')
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
      issues: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 1

      - uses: anthropics/claude-code-action@beta
        with:
          claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

**ポイント:**
- `issue_comment` イベントをトリガーとし、PR コメントのみに限定する（`github.event.issue.pull_request != null`）
- `contains(github.event.comment.body, '@claude')` で `@claude /review` を含む任意のコメントに対応
- `CLAUDE_CODE_OAUTH_TOKEN` シークレットを使用（設定済み）
- `pull-requests: write` / `issues: write` 権限が Claude のレビューコメント投稿に必要

---

### 2. `StateMachineManager` — transition フック機能の追加

指定フェーズへの遷移後にコールバックを非同期実行できる `register_transition_hook()` メソッドを追加する。

#### 追加するメソッド・フィールド

```python
class StateMachineManager:
    def __init__(self, ...) -> None:
        # 既存の初期化処理...
        self._transition_hooks: dict[
            Phase, list[Callable[[int, Phase], Awaitable[None]]]
        ] = {}

    def register_transition_hook(
        self,
        target_phases: list[Phase],
        callback: Callable[[int, Phase], Awaitable[None]],
    ) -> None:
        """指定フェーズへの遷移後に呼び出されるコールバックを登録する。

        Args:
            target_phases: フックを設定するターゲットフェーズのリスト
            callback: 遷移後に呼び出す非同期コールバック (issue_number, phase) -> None
        """
        for phase in target_phases:
            self._transition_hooks.setdefault(phase, []).append(callback)

    async def transition(
        self, issue_number: int, target_phase: Phase
    ) -> bool:
        # 既存の遷移処理...
        success = await self._execute_transition(issue_number, target_phase)

        # 遷移成功後にフックを実行
        if success and target_phase in self._transition_hooks:
            for hook in self._transition_hooks[target_phase]:
                try:
                    await hook(issue_number, target_phase)
                except Exception as e:
                    logger.error(
                        "transition hook failed",
                        issue_number=issue_number,
                        target_phase=target_phase,
                        error=str(e),
                    )
                    # フック失敗は遷移の成否に影響しない

        return success
```

**設計方針:**
- フック失敗は遷移の成否に影響しない（`@claude /review` 投稿失敗でワークフローが止まることを防ぐ）
- 複数フックが登録された場合、登録順に全て実行する

---

### 3. `event_router.py` — IMPL_REVIEW / DESIGN_REVIEW 遷移後の自動コメント

#### `EventRouter.__init__()` でのフック登録

```python
class EventRouter:
    def __init__(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        github_client: GitHubClient,
        ...
    ) -> None:
        # 既存の初期化処理...

        # IMPL_REVIEW / DESIGN_REVIEW 遷移後に @claude /review を自動投稿
        self.state_machine.register_transition_hook(
            target_phases=[Phase.IMPL_REVIEW, Phase.DESIGN_REVIEW],
            callback=self._on_review_phase_entered,
        )

    async def _on_review_phase_entered(
        self, issue_number: int, phase: Phase
    ) -> None:
        """IMPL_REVIEW または DESIGN_REVIEW フェーズ遷移後のフック。"""
        review_type = "impl" if phase == Phase.IMPL_REVIEW else "design"
        await self._post_claude_review_comment(issue_number, review_type)
```

#### `_post_claude_review_comment()` メソッドの追加

```python
# ボットコメントの判定定数
_BOT_COMMENT_AUTHORS: frozenset[str] = frozenset({
    "github-actions[bot]",
    "claude[bot]",
})

async def _post_claude_review_comment(
    self, issue_number: int, review_type: str
) -> None:
    """IMPL_REVIEW または DESIGN_REVIEW 遷移後に @claude /review を PR に投稿する。

    Args:
        issue_number: Issue番号
        review_type: "impl" または "design"
    """
    issue_state = self.state_machine.get_state(issue_number)
    if issue_state is None:
        logger.warning(
            "issue_state not found for auto claude review",
            issue_number=issue_number,
        )
        return

    pr_number = (
        issue_state.pr_number
        if review_type == "impl"
        else issue_state.design_pr_number
    )
    if pr_number is None:
        logger.warning(
            "pr_number not found for auto claude review",
            issue_number=issue_number,
            review_type=review_type,
        )
        return

    try:
        await self.github_client.create_pr_comment(
            repo=issue_state.repo,
            pr_number=pr_number,
            body="@claude /review",
        )
        logger.info(
            "posted @claude /review comment",
            issue_number=issue_number,
            pr_number=pr_number,
            review_type=review_type,
        )
    except Exception as e:
        # レビューコメント投稿失敗はワークフロー継続を妨げない
        logger.error(
            "failed to post @claude /review comment",
            issue_number=issue_number,
            pr_number=pr_number,
            error=str(e),
        )
```

---

### 4. `event_router.py` — ボットコメントの無視

#### `_handle_impl_pr_commented()` への変更

```python
async def _handle_impl_pr_commented(self, event: PollEvent) -> None:
    """実装PRへのコメントイベントを処理する。"""
    # ボットコメントは無視する（@claude /review の応答が IMPL_REVISE を
    # トリガーしないようにする）
    comment_author = event.comment.user.login if event.comment else None
    if comment_author in _BOT_COMMENT_AUTHORS:
        logger.debug(
            "ignoring bot comment on impl PR",
            author=comment_author,
            issue_number=event.issue.number if event.issue else None,
        )
        return

    # 既存の IMPL_REVISE 遷移処理（変更なし）...
```

#### `_handle_design_pr_commented()` への変更

```python
async def _handle_design_pr_commented(self, event: PollEvent) -> None:
    """設計PRへのコメントイベントを処理する。"""
    # ボットコメントは無視する（@claude /review の応答が DESIGN_REVISE を
    # トリガーしないようにする）
    comment_author = event.comment.user.login if event.comment else None
    if comment_author in _BOT_COMMENT_AUTHORS:
        logger.debug(
            "ignoring bot comment on design PR",
            author=comment_author,
            issue_number=event.issue.number if event.issue else None,
        )
        return

    # 既存の DESIGN_REVISE 遷移処理（変更なし）...
```

---

## データフロー詳細

### IMPL_REVIEW フェーズへの遷移フロー（完全版）

```
1. CI チェック完了イベント受信 (EventRouter._handle_ci_result)
2. CI 成功判定
3. StateMachineManager.transition(issue_number, Phase.IMPL_REVIEW) 実行
4. 遷移成功 → _transition_hooks[Phase.IMPL_REVIEW] が起動
5. EventRouter._on_review_phase_entered(issue_number, Phase.IMPL_REVIEW) 呼び出し
6. IssueState から pr_number を取得
7. GitHubClient.create_pr_comment(repo, pr_number, "@claude /review") 実行
8. GitHub Actions の claude-review.yml がトリガー
9. anthropics/claude-code-action がコードレビューを実施
10. github-actions[bot] がレビューコメントを PR に投稿
11. EventRouter が IMPL_PR_COMMENTED イベントを受信
12. comment.user.login == "github-actions[bot]" → スキップ（無視）
13. 人間レビュアーが Claude の指摘を確認
14. 人間レビュアーがコメントを投稿
15. EventRouter が IMPL_PR_COMMENTED イベントを受信
16. 人間コメント → StateMachineManager.transition(issue_number, Phase.IMPL_REVISE)
17. TaskQueue に IMPL_REVISE タスクをエンキュー
```

### DESIGN_REVIEW フェーズへの遷移フロー（完全版）

```
1. DesignExecutor が設計書 PR を作成
2. StateMachineManager.transition(issue_number, Phase.DESIGN_REVIEW) 実行
3. 遷移成功 → _transition_hooks[Phase.DESIGN_REVIEW] が起動
4. EventRouter._on_review_phase_entered(issue_number, Phase.DESIGN_REVIEW) 呼び出し
5. IssueState から design_pr_number を取得
6. GitHubClient.create_pr_comment(repo, design_pr_number, "@claude /review") 実行
7. GitHub Actions の claude-review.yml がトリガー
8. anthropics/claude-code-action が設計書をレビュー
9. github-actions[bot] がレビューコメントを設計 PR に投稿
10. EventRouter が DESIGN_PR_COMMENTED イベントを受信
11. comment.user.login == "github-actions[bot]" → スキップ（無視）
12. 人間レビュアーが Claude の指摘を確認
13. 人間レビュアーがコメントを投稿
14. EventRouter が DESIGN_PR_COMMENTED イベントを受信
15. 人間コメント → StateMachineManager.transition(issue_number, Phase.DESIGN_REVISE)
16. TaskQueue に DESIGN_REVISE タスクをエンキュー
```

---

## エラーハンドリング方針

| シナリオ | 対応 |
|----------|------|
| `@claude /review` コメント投稿失敗 | ログに ERROR を記録し、ワークフローを継続（フェーズ遷移はすでに完了済み） |
| `pr_number` / `design_pr_number` が None | ログに WARNING を記録し、コメント投稿をスキップ |
| `issue_state` が None | ログに WARNING を記録し、コメント投稿をスキップ |
| transition フック内の例外 | ログに ERROR を記録し、遷移の成否には影響しない |
| GitHub Actions ワークフローが起動しない | Claude からのレビューがないだけで、ワークフローに影響なし |

---

## テスト方針

### 単体テスト (`tests/unit/test_event_router.py`)

| テストケース | 内容 |
|-------------|------|
| TC-63-01 | CI 成功時に `_post_claude_review_comment("impl")` が呼ばれること |
| TC-63-02 | `github-actions[bot]` の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーしないこと |
| TC-63-03 | 人間の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーすること |
| TC-63-04 | `pr_number` が None の場合、コメント投稿をスキップしてもエラーにならないこと |
| TC-63-05 | `github-actions[bot]` の DESIGN_PR_COMMENTED は DESIGN_REVISE 遷移をトリガーしないこと |
| TC-63-06 | `create_pr_comment` が例外を投げても CI 成功フローが継続すること |
| TC-63-07 | DESIGN_REVIEW 遷移フックで `design_pr_number` の PR に `@claude /review` が投稿されること |

### 単体テスト (`tests/unit/test_state_machine.py`)

| テストケース | 内容 |
|-------------|------|
| TC-63-08 | `register_transition_hook()` で登録したコールバックが遷移後に呼ばれること |
| TC-63-09 | フック内の例外が遷移の成否に影響しないこと |
| TC-63-10 | 複数フックが登録された場合、全て呼ばれること |
| TC-63-11 | 対象フェーズ以外への遷移ではフックが呼ばれないこと |

---

## 実装手順

1. `.github/workflows/claude-review.yml` を新規作成
2. `StateMachineManager` に `_transition_hooks` フィールドと `register_transition_hook()` メソッドを追加
3. `StateMachineManager.transition()` にフック実行ロジックを追加
4. `EventRouter` に `_BOT_COMMENT_AUTHORS` 定数と `_post_claude_review_comment()` メソッドを追加
5. `EventRouter.__init__()` でトランジションフックを登録（`_on_review_phase_entered`）
6. `EventRouter._handle_impl_pr_commented()` にボットフィルタリングを追加
7. `EventRouter._handle_design_pr_commented()` にボットフィルタリングを追加
8. 単体テストを追加
9. `docs/specs/event-router.md` を更新

---

## 影響範囲

- `.github/workflows/claude-review.yml`（新規）
- `src/ai_agent_orchestrator/orchestrator/state_machine.py`
- `src/ai_agent_orchestrator/poller/event_router.py`
- `tests/unit/test_event_router.py`
- `tests/unit/test_state_machine.py`
- `docs/specs/event-router.md`

既存の承認フロー（PR approve → DONE）、CI 修正フロー、ヒアリングフロー等への影響はない。
