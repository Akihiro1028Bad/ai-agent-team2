# 実装仕様書: EventRouter / GitHubPoller

**対象モジュール**:
- `src/ai_agent_orchestrator/poller/event_router.py`
- `src/ai_agent_orchestrator/poller/github_poller.py`

---

## 1. 概要

GitHub API をポーリングしてイベントを検知し (GitHubPoller)、
検知されたイベントをステートマシン遷移とタスクキューへのエンキューに変換する (EventRouter)。
Issue タイプに応じたルーティング (Bug → ANALYSIS, Feature-S → PLAN_BRIEF 等) を行い、
方針承認 (thumbsup リアクション)、設計PR approve、実装PR approve、CI結果、分割承認などの
全イベントタイプを処理する。

---

## 2. 依存パッケージ

```
githubkit>=0.11.0
```

---

## 3. EventRouter モジュール

### 3.1 Imports

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from ai_agent_orchestrator.config.settings import RepositoryConfig

if TYPE_CHECKING:
    from githubkit.versions.latest.models import Issue, IssueComment, PullRequest

    from ai_agent_orchestrator.orchestrator.state_machine import (
        Phase,
        StateMachineManager,
    )
    from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue, TaskRequest

logger = logging.getLogger(__name__)

# ボットコメントの判定定数（IMPL_PR_COMMENTED / DESIGN_PR_COMMENTED のフィルタに使用）
_BOT_COMMENT_AUTHORS: frozenset[str] = frozenset({
    "github-actions[bot]",
    "claude[bot]",
})

# レビュータイプごとのトリガーコマンド
_REVIEW_COMMANDS: dict[str, str] = {
    "impl": "@claude /review-impl",    # claude-impl-review.yml をトリガー
    "design": "@claude /review-design", # claude-design-review.yml をトリガー
}
```

### 3.2 EventType Enum

```python
class EventType(Enum):
    """ポーリングイベントの種別。"""

    NEW_ISSUE = auto()
    HEARING_REPLY = auto()
    HEARING_TIMEOUT = auto()

    # Bug/Feature-S 方針承認
    PLAN_REACTION_ADDED = auto()      # 👍 リアクション検知
    PLAN_COMMENT_ADDED = auto()       # 方針への指摘コメント

    # Feature-M 設計PR
    DESIGN_PR_APPROVED = auto()
    DESIGN_PR_COMMENTED = auto()

    # 共通: 実装PR
    IMPL_PR_APPROVED = auto()
    IMPL_PR_COMMENTED = auto()

    # CI
    CI_FAILED = auto()
    CI_PASSED = auto()

    # Feature-L
    SPLIT_APPROVED = auto()
    SPLIT_MODIFIED = auto()

    # エラー
    ERROR = auto()
```

### 3.3 PollEvent データクラス

```python
@dataclass(frozen=True)
class PollEvent:
    """ポーリングで検知されたイベント。

    Attributes:
        type: イベント種別 (EventType の値)
        repo: 対象リポジトリ設定
        issue: 関連する Issue (githubkit 型)
        comment: 関連するコメント (githubkit 型)
        pr: 関連する PR (githubkit 型)
        extra: イベント固有の追加データ (ci_logs, comments 等)
        error: エラー情報
    """

    type: EventType
    repo: RepositoryConfig
    issue: Issue | None = None
    comment: IssueComment | None = None
    pr: PullRequest | None = None
    extra: dict | None = None
    error: Exception | None = None
```

### 3.4 EventRouter クラス

```python
class EventRouter:
    """イベントをフェーズ遷移アクションに変換する。

    PollEvent を受け取り、StateMachineManager で遷移を実行し、
    TaskQueue にタスクをエンキューする。
    Issue タイプに応じたルーティング (Bug → ANALYSIS, Feature-S → PLAN_BRIEF 等) を行う。
    """

    def __init__(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        account_manager: object | None = None,
        notifier: Notifier | None = None,
        execution_guard: ExecutionGuard | None = None,
    ) -> None:
        """EventRouter を初期化する。

        Args:
            state_machine: ステートマシンマネージャ
            task_queue: タスクキュー
            account_manager: AccountManager (GitHub ラベル更新用、省略可)
            notifier: 通知送信 (Slack 等、省略可)
            execution_guard: フェーズ実行中の状態遷移を防止するガード (省略可)
        """
        self._sm = state_machine
        self._tq = task_queue
        self._account_manager = account_manager
        self._notifier = notifier
        self._guard = execution_guard

        # IMPL_REVIEW / DESIGN_REVIEW 遷移後に @claude /review を自動投稿
        self._sm.register_transition_hook(
            target_phases=[Phase.IMPL_REVIEW, Phase.DESIGN_REVIEW],
            callback=self._on_review_phase_entered,
        )
```

### 3.5 公開メソッド: route()

```python
    async def route(self, event: PollEvent) -> None:
        """イベントを処理し、適切な遷移とエンキューを行う。

        Args:
            event: 処理するポーリングイベント

        イベントとアクションの対応:
            NEW_ISSUE          → register_issue + TYPE_DETECTION エンキュー
            HEARING_REPLY      → hearing_continue エンキュー (遷移なし)
            HEARING_TIMEOUT    → SUSPENDED 遷移
            PLAN_REACTION_ADDED → タイプ別: Bug→FIX, Feature-S→IMPLEMENT
            PLAN_COMMENT_ADDED  → タイプ別: Bug→ANALYSIS, Feature-S→PLAN_BRIEF
            DESIGN_PR_APPROVED  → PLANNING 遷移 + エンキュー
            DESIGN_PR_COMMENTED → DESIGN_REVISE 遷移 + エンキュー
            IMPL_PR_APPROVED    → DONE 遷移
            IMPL_PR_COMMENTED   → IMPL_REVISE 遷移 + エンキュー
            CI_FAILED           → CI_FIX (3回以内) or SUSPENDED
            CI_PASSED           → IMPL_REVIEW 遷移 (エンキュー不要、PR approve/comment をポーリングで待つ)
            SPLIT_APPROVED      → SPLIT_EXECUTE 遷移 + エンキュー
            SPLIT_MODIFIED      → HEARING 遷移 + エンキュー (再ヒアリング)
            ERROR               → ログ出力のみ
        """
        logger.info(
            "Routing event: type=%s issue=#%s",
            event.type,
            event.issue.number if event.issue else "N/A",
        )

        match event.type:
            case EventType.NEW_ISSUE:
                await self._handle_new_issue(event)
            case EventType.HEARING_REPLY:
                await self._handle_hearing_reply(event)
            case EventType.HEARING_TIMEOUT:
                await self._handle_hearing_timeout(event)
            case EventType.PLAN_REACTION_ADDED:
                await self._handle_plan_reaction(event)
            case EventType.PLAN_COMMENT_ADDED:
                await self._handle_plan_comment(event)
            case EventType.DESIGN_PR_APPROVED:
                await self._handle_design_pr_approved(event)
            case EventType.DESIGN_PR_COMMENTED:
                await self._handle_design_pr_commented(event)
            case EventType.IMPL_PR_APPROVED:
                await self._handle_impl_pr_approved(event)
            case EventType.IMPL_PR_COMMENTED:
                await self._handle_impl_pr_commented(event)
            case EventType.CI_FAILED:
                await self._handle_ci_failure(event)
            case EventType.CI_PASSED:
                await self._handle_ci_passed(event)
            case EventType.SPLIT_APPROVED:
                await self._handle_split_approved(event)
            case EventType.SPLIT_MODIFIED:
                await self._handle_split_modified(event)
            case EventType.ERROR:
                logger.error("Poll error for repo %s: %s", event.repo, event.error)
            case _:
                logger.warning("Unknown event type: %s", event.type)
```

### 3.6 内部メソッド (イベント別ハンドラ)

```python
    async def _handle_new_issue(self, event: PollEvent) -> None:
        """新規 Issue: ステートマシンに登録し、TYPE_DETECTION をエンキュー。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        self._sm.register_issue(
            issue_number=event.issue.number,
            repo=repo_key,
            initial_phase=Phase.TYPE_DETECTION,
        )
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.TYPE_DETECTION,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_hearing_reply(self, event: PollEvent) -> None:
        """ヒアリング回答: hearing_continue をエンキュー (遷移なし)。"""
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._tq.enqueue(
            TaskRequest(
                issue_number=int(event.comment.issue_url.split("/")[-1]),  # Issue番号抽出
                repo=event.repo,
                phase="hearing_continue",
                priority=Priority.HIGH,
                extra={"comment": event.comment.body},
            )
        )

    async def _handle_hearing_timeout(self, event: PollEvent) -> None:
        """ヒアリングタイムアウト: SUSPENDED に遷移。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase

        await self._sm.transition(event.issue.number, Phase.SUSPENDED)

    async def _handle_plan_reaction(self, event: PollEvent) -> None:
        """方針承認 (👍リアクション): タイプ別に次フェーズへ遷移。

        Bug    → FIX へ遷移
        Feature-S → IMPLEMENT へ遷移
        """
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        issue_type = self._sm.get_issue_type(event.issue.number)
        if issue_type == "bug":
            next_phase = Phase.FIX
        else:
            next_phase = Phase.IMPLEMENT

        await self._sm.transition(event.issue.number, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_plan_comment(self, event: PollEvent) -> None:
        """方針指摘コメント: タイプ別に修正フェーズへ遷移。

        Bug       → ANALYSIS (再分析)
        Feature-S → PLAN_BRIEF (方針再作成)
        """
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        issue_type = self._sm.get_issue_type(event.issue.number)
        if issue_type == "bug":
            next_phase = Phase.ANALYSIS
        else:
            next_phase = Phase.PLAN_BRIEF

        await self._sm.transition(event.issue.number, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase,
                priority=Priority.NORMAL,
                extra={"feedback": event.comment.body if event.comment else ""},
            )
        )

    async def _handle_design_pr_approved(self, event: PollEvent) -> None:
        """設計 PR approve: PLANNING へ遷移してエンキュー。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.PLANNING)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.PLANNING,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_design_pr_commented(self, event: PollEvent) -> None:
        """設計 PR コメント (指摘): DESIGN_REVISE へ遷移してエンキュー。

        ボットコメント（github-actions[bot] 等）は無視する。
        @claude /review-design の応答コメントが DESIGN_REVISE を
        トリガーしないようにする。
        """
        # ボットコメントは無視する
        comment_author = event.comment.user.login if event.comment else None
        if comment_author in _BOT_COMMENT_AUTHORS:
            logger.debug("ignoring bot comment on design PR: author=%s", comment_author)
            return

        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.DESIGN_REVISE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.DESIGN_REVISE,
                priority=Priority.CRITICAL,
                extra={"comments": event.extra or {}},
            )
        )

    async def _handle_impl_pr_approved(self, event: PollEvent) -> None:
        """実装 PR approve: DONE へ遷移し、DoneExecutor をエンキュー。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.DONE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.DONE,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_impl_pr_commented(self, event: PollEvent) -> None:
        """実装 PR コメント (指摘): IMPL_REVISE へ遷移してエンキュー。

        ボットコメント（github-actions[bot] 等）は無視する。
        @claude /review-impl の応答コメントが IMPL_REVISE を
        トリガーしないようにする。
        """
        # ボットコメントは無視する
        comment_author = event.comment.user.login if event.comment else None
        if comment_author in _BOT_COMMENT_AUTHORS:
            logger.debug("ignoring bot comment on impl PR: author=%s", comment_author)
            return

        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.IMPL_REVISE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.IMPL_REVISE,
                priority=Priority.CRITICAL,
                extra={"comments": event.extra or {}},
            )
        )

    async def _on_review_phase_entered(
        self, issue_number: int, phase: Phase
    ) -> None:
        """IMPL_REVIEW または DESIGN_REVIEW フェーズ遷移後のフック。

        IMPL_REVIEW の場合は "@claude /review-impl" を、
        DESIGN_REVIEW の場合は "@claude /review-design" を投稿し、
        それぞれ専用のワークフロー（claude-impl-review.yml / claude-design-review.yml）
        をトリガーする。

        Args:
            issue_number: Issue 番号。
            phase: 遷移先フェーズ (IMPL_REVIEW または DESIGN_REVIEW)。
        """
        review_type = "impl" if phase == Phase.IMPL_REVIEW else "design"
        await self._post_claude_review_comment(issue_number, review_type)

    async def _post_claude_review_comment(
        self, issue_number: int, review_type: str
    ) -> None:
        """IMPL_REVIEW または DESIGN_REVIEW 遷移後に @claude /review-* を PR に投稿する。

        Args:
            issue_number: Issue 番号。
            review_type: "impl" または "design"。
                - "impl"   → "@claude /review-impl"   を投稿（実装レビュー用ワークフロー起動）
                - "design" → "@claude /review-design" を投稿（設計レビュー用ワークフロー起動）

        エラーハンドリング:
            - issue_state が None → WARNING ログ出力 → return
            - pr_number が None → WARNING ログ出力 → return
            - repo 形式が不正 → WARNING ログ出力 → return
            - GitHub クライアント取得失敗 → WARNING ログ出力 → return
            - コメント投稿失敗 → ERROR ログ出力（ワークフロー継続）
        """
        issue_state = self._sm.get_state(issue_number)
        if issue_state is None:
            logger.warning(
                "issue_state not found for auto claude review: issue_number=%d",
                issue_number,
            )
            return

        pr_number = (
            issue_state.pr_number
            if review_type == "impl"
            else issue_state.design_pr_number
        )
        if pr_number is None:
            logger.warning(
                "pr_number not found for auto claude review: issue_number=%d, review_type=%s",
                issue_number,
                review_type,
            )
            return

        # issue_state.repo は "owner/repo" 形式の文字列
        repo_parts = issue_state.repo.split("/", 1)
        if len(repo_parts) != 2:
            logger.warning(
                "invalid repo format for auto claude review: issue_number=%d, repo=%s",
                issue_number,
                issue_state.repo,
            )
            return

        repo_config = RepositoryConfig(owner=repo_parts[0], repo=repo_parts[1])
        comment_body = _REVIEW_COMMANDS[review_type]
        try:
            client = await self._get_client(repo_config)
            if client is None:
                logger.warning(
                    "github_client not available for auto claude review: issue_number=%d",
                    issue_number,
                )
                return
            await client.create_comment(repo_config, pr_number, comment_body)
            logger.info(
                "posted @claude /review comment: issue_number=%d, pr_number=%d, review_type=%s",
                issue_number,
                pr_number,
                review_type,
            )
        except Exception as e:
            # レビューコメント投稿失敗はワークフロー継続を妨げない
            logger.error(
                "failed to post @claude /review comment: issue_number=%d, pr_number=%d, error=%s",
                issue_number,
                pr_number,
                str(e),
            )

    async def _handle_ci_failure(self, event: PollEvent) -> None:
        """CI 失敗: リトライ回数に応じて CI_FIX or SUSPENDED。

        3 回以内 → CI_FIX へ遷移してエンキュー
        3 回超過 → SUSPENDED へ遷移 (手動対応が必要)
        """
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        retry_count = await self._sm.get_ci_retry_count(event.issue.number)
        if retry_count < 3:
            await self._sm.transition(event.issue.number, Phase.CI_FIX)
            await self._tq.enqueue(
                TaskRequest(
                    issue_number=event.issue.number,
                    repo=event.repo,
                    phase=Phase.CI_FIX,
                    priority=Priority.HIGH,
                    extra={
                        "ci_logs": event.extra.get("ci_logs", "") if event.extra else "",
                        "retry_count": retry_count + 1,
                    },
                )
            )
        else:
            await self._sm.transition(event.issue.number, Phase.SUSPENDED)

    async def _handle_ci_passed(self, event: PollEvent) -> None:
        """CI成功 → IMPL_REVIEW に遷移."""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase

        await self._sm.transition(event.issue.number, Phase.IMPL_REVIEW)
        # IMPL_REVIEW はポーリングで PR approve/comment を待つため、エンキュー不要

    async def _handle_split_approved(self, event: PollEvent) -> None:
        """分割承認 (Feature-L): SPLIT_EXECUTE へ遷移してエンキュー。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.SPLIT_EXECUTE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.SPLIT_EXECUTE,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_split_modified(self, event: PollEvent) -> None:
        """分割修正指示 (Feature-L): HEARING へ遷移して再ヒアリング。"""
        from ai_agent_orchestrator.orchestrator.state_machine import Phase
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest, Priority

        await self._sm.transition(event.issue.number, Phase.HEARING)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.HEARING,
                priority=Priority.NORMAL,
                extra={"modification_request": event.comment.body if event.comment else ""},
            )
        )
```

---

## 4. GitHubPoller モジュール

### 4.1 Imports

```python
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from githubkit import GitHub

if TYPE_CHECKING:
    from githubkit.versions.latest.models import Issue, IssueComment, PullRequest

    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.account_manager import AccountManager
    from ai_agent_orchestrator.poller.event_router import EventType, PollEvent

logger = logging.getLogger(__name__)
```

### 4.2 GitHubPoller クラス

```python
class GitHubPoller:
    """GitHub API をポーリングしてイベントを検知する。

    設定された間隔 (interval_sec) で全リポジトリを巡回し、
    新規 Issue、ヒアリング回答、PR レビュー、CI 結果、リアクション等を検知する。
    """

    def __init__(
        self,
        account_manager: AccountManager,
        repos: list[RepositoryConfig],
        interval_sec: int = 120,
        hearing_timeout_hours: int = 24,
    ) -> None:
        """GitHubPoller を初期化する。

        Args:
            account_manager: GitHub アカウント管理
            repos: 監視対象リポジトリのリスト
            interval_sec: ポーリング間隔 (秒)。デフォルト: 120
            hearing_timeout_hours: ヒアリングタイムアウト (時間)。デフォルト: 24
        """
        self._account_manager = account_manager
        self._repos = repos
        self._interval_sec = interval_sec
        self._hearing_timeout_hours = hearing_timeout_hours
        self._last_poll: dict[str, datetime] = {}
```

### 4.3 公開メソッド

```python
    async def start(self, event_queue: asyncio.Queue[PollEvent]) -> None:
        """ポーリングループを開始する。

        無限ループで全リポジトリを巡回し、検知したイベントをキューに追加する。
        asyncio.TaskGroup 内で実行されることを想定。

        Args:
            event_queue: イベントを追加するキュー
        """
        while True:
            for repo in self._repos:
                try:
                    events = await self._poll_repo(repo)
                    for event in events:
                        await event_queue.put(event)
                except Exception as e:
                    logger.error("Poll error for %s/%s: %s", repo.owner, repo.repo, e)
                    await event_queue.put(
                        PollEvent(type=EventType.ERROR, repo=repo, error=e)
                    )
            await asyncio.sleep(self._interval_sec)
```

### 4.4 内部メソッド: _poll_repo()

```python
    async def _poll_repo(self, repo: RepositoryConfig) -> list[PollEvent]:
        """単一リポジトリのポーリング。

        以下の順序でイベントを検知:
        1. 新規 Issue (ai-agent ラベルあり、phase:* ラベルなし)
        2. ヒアリング回答 (phase:hearing の Issue に人間コメント追加)
        3. ヒアリングタイムアウト (phase:hearing で 24 時間無応答)
        4. 方針リアクション検知 (phase:plan-review の Issue に 👍 リアクション)
        5. 方針指摘コメント検知 (phase:plan-review の Issue にコメント)
        6. PR レビューイベント (設計PR, 実装PR の approve/コメント)
        7. CI 結果 (実装PR の CI 成功/失敗)
        8. 分割承認/修正 (Feature-L の SPLIT_PROPOSAL への 👍/コメント)

        Args:
            repo: リポジトリ設定

        Returns:
            検知された PollEvent のリスト
        """
        events: list[PollEvent] = []
        repo_key = f"{repo.owner}/{repo.repo}"
        since = self._last_poll.get(repo_key)
        self._last_poll[repo_key] = datetime.now(timezone.utc)

        client = await self._account_manager.get_client_for_repo(repo.owner, repo.repo)

        # 1. 新規 Issue 検知
        new_issues = await self._detect_new_issues(client, repo)
        for issue in new_issues:
            events.append(PollEvent(type=EventType.NEW_ISSUE, repo=repo, issue=issue))

        # 2. ヒアリング回答検知
        hearing_replies = await self._detect_hearing_replies(client, repo, since)
        for comment in hearing_replies:
            events.append(PollEvent(type=EventType.HEARING_REPLY, repo=repo, comment=comment))

        # 3. ヒアリングタイムアウト検知
        timeout_issues = await self._detect_hearing_timeouts(client, repo)
        for issue in timeout_issues:
            events.append(PollEvent(type=EventType.HEARING_TIMEOUT, repo=repo, issue=issue))

        # 4. 方針リアクション検知 (👍)
        plan_reactions = await self._detect_plan_reactions(client, repo, since)
        for issue in plan_reactions:
            events.append(PollEvent(type=EventType.PLAN_REACTION_ADDED, repo=repo, issue=issue))

        # 5. 方針指摘コメント検知
        plan_comments = await self._detect_plan_comments(client, repo, since)
        for comment in plan_comments:
            events.append(PollEvent(type=EventType.PLAN_COMMENT_ADDED, repo=repo, comment=comment))

        # 6. PR レビューイベント検知
        pr_events = await self._detect_pr_events(client, repo, since)
        events.extend(pr_events)

        # 7. CI 結果検知
        ci_events = await self._detect_ci_results(client, repo)
        events.extend(ci_events)

        # 8. 分割承認/修正検知
        split_events = await self._detect_split_events(client, repo, since)
        events.extend(split_events)

        return events
```

### 4.5 内部メソッド: 各種検知

```python
    async def _detect_new_issues(
        self, client: GitHub, repo: RepositoryConfig,
    ) -> list[Issue]:
        """新規 Issue を検知する。

        条件: ai-agent ラベルあり AND phase:* ラベルなし AND state=open
        """
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=repo.label,  # "ai-agent"
            state="open",
        )
        return [
            issue for issue in issues.parsed_data
            if not any(
                label.name.startswith("phase:") for label in (issue.labels or [])
            )
        ]

    async def _detect_hearing_replies(
        self, client: GitHub, repo: RepositoryConfig, since: datetime | None,
    ) -> list[IssueComment]:
        """ヒアリング回答を検知する。

        条件: phase:hearing ラベル付き Issue に since 以降の人間コメント
        (bot コメントは除外)
        """
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=f"{repo.label},phase:hearing",
            state="open",
        )
        replies = []
        for issue in issues.parsed_data:
            comments = await client.rest.issues.async_list_comments(
                owner=repo.owner,
                repo=repo.repo,
                issue_number=issue.number,
                since=since.isoformat() if since else None,
            )
            for comment in comments.parsed_data:
                if comment.user and comment.user.type != "Bot":
                    replies.append(comment)
        return replies

    async def _detect_hearing_timeouts(
        self, client: GitHub, repo: RepositoryConfig,
    ) -> list[Issue]:
        """ヒアリングタイムアウトを検知する。

        条件: phase:hearing ラベル付き Issue で
              最後のコメントから hearing_timeout_hours 以上経過
        """
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=f"{repo.label},phase:hearing",
            state="open",
        )
        threshold = datetime.now(timezone.utc) - timedelta(
            hours=self._hearing_timeout_hours
        )
        timeout_issues = []
        for issue in issues.parsed_data:
            if issue.updated_at and issue.updated_at < threshold:
                timeout_issues.append(issue)
        return timeout_issues

    async def _detect_plan_reactions(
        self, client: GitHub, repo: RepositoryConfig, since: datetime | None,
    ) -> list[Issue]:
        """方針承認リアクション (👍) を検知する。

        条件: phase:plan-review ラベル付き Issue のコメントに +1 リアクション
        """
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=f"{repo.label},phase:plan-review",
            state="open",
        )
        approved_issues = []
        for issue in issues.parsed_data:
            comments = await client.rest.issues.async_list_comments(
                owner=repo.owner, repo=repo.repo, issue_number=issue.number,
            )
            for comment in comments.parsed_data:
                if comment.user and comment.user.type == "Bot":
                    # AI が投稿した方針コメントのリアクションを確認
                    reactions = await client.rest.reactions.async_list_for_issue_comment(
                        owner=repo.owner, repo=repo.repo, comment_id=comment.id,
                    )
                    has_thumbsup = any(
                        r.content == "+1" for r in reactions.parsed_data
                    )
                    if has_thumbsup:
                        approved_issues.append(issue)
                        break
        return approved_issues

    async def _detect_plan_comments(
        self, client: GitHub, repo: RepositoryConfig, since: datetime | None,
    ) -> list[IssueComment]:
        """方針への指摘コメントを検知する。

        条件: phase:plan-review ラベル付き Issue に since 以降の人間コメント
        """
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=f"{repo.label},phase:plan-review",
            state="open",
        )
        feedback = []
        for issue in issues.parsed_data:
            comments = await client.rest.issues.async_list_comments(
                owner=repo.owner, repo=repo.repo, issue_number=issue.number,
                since=since.isoformat() if since else None,
            )
            for comment in comments.parsed_data:
                if comment.user and comment.user.type != "Bot":
                    feedback.append(comment)
        return feedback

    async def _detect_pr_events(
        self, client: GitHub, repo: RepositoryConfig, since: datetime | None,
    ) -> list[PollEvent]:
        """PR レビューイベント (設計PR, 実装PR) を検知する。

        - 設計 PR: approve → DESIGN_PR_APPROVED, コメント → DESIGN_PR_COMMENTED
        - 実装 PR: approve → IMPL_PR_APPROVED, コメント → IMPL_PR_COMMENTED
        """
        events: list[PollEvent] = []
        # phase:design-review と phase:impl-review の Issue を取得
        for label_suffix, approved_type, commented_type in [
            ("design-review", EventType.DESIGN_PR_APPROVED, EventType.DESIGN_PR_COMMENTED),
            ("impl-review", EventType.IMPL_PR_APPROVED, EventType.IMPL_PR_COMMENTED),
        ]:
            issues = await client.rest.issues.async_list_for_repo(
                owner=repo.owner, repo=repo.repo,
                labels=f"{repo.label},phase:{label_suffix}",
                state="open",
            )
            for issue in issues.parsed_data:
                # IssueState から PR 番号を取得してレビュー状態を確認
                # (StateMachineManager 経由で PR 番号を取得する設計)
                pr_reviews = await self._get_pr_reviews(client, repo, issue)
                for review_event in pr_reviews:
                    if review_event == "approved":
                        events.append(PollEvent(
                            type=approved_type, repo=repo, issue=issue,
                        ))
                    elif review_event == "commented":
                        events.append(PollEvent(
                            type=commented_type, repo=repo, issue=issue,
                            extra={"comments": review_event},
                        ))
        return events

    async def _detect_ci_results(
        self, client: GitHub, repo: RepositoryConfig,
    ) -> list[PollEvent]:
        """CI 結果を検知する。

        phase:implement または phase:ci-fix ラベルの Issue に紐づく PR の
        CI ステータスを確認する。
        """
        events: list[PollEvent] = []
        for label_suffix in ("implement", "ci-fix"):
            issues = await client.rest.issues.async_list_for_repo(
                owner=repo.owner, repo=repo.repo,
                labels=f"{repo.label},phase:{label_suffix}",
                state="open",
            )
            for issue in issues.parsed_data:
                ci_status = await self._check_ci_status(client, repo, issue)
                if ci_status == "failure":
                    ci_logs = await self._get_ci_logs(client, repo, issue)
                    events.append(PollEvent(
                        type=EventType.CI_FAILED, repo=repo, issue=issue,
                        extra={"ci_logs": ci_logs},
                    ))
                elif ci_status == "success":
                    events.append(PollEvent(
                        type=EventType.CI_PASSED, repo=repo, issue=issue,
                    ))
        return events

    async def _detect_split_events(
        self, client: GitHub, repo: RepositoryConfig, since: datetime | None,
    ) -> list[PollEvent]:
        """分割承認/修正イベントを検知する。

        phase:split-proposal ラベル付き Issue の 👍 リアクションまたはコメントを検知。
        """
        events: list[PollEvent] = []
        issues = await client.rest.issues.async_list_for_repo(
            owner=repo.owner, repo=repo.repo,
            labels=f"{repo.label},phase:split-proposal",
            state="open",
        )
        for issue in issues.parsed_data:
            comments = await client.rest.issues.async_list_comments(
                owner=repo.owner, repo=repo.repo, issue_number=issue.number,
            )
            for comment in comments.parsed_data:
                if comment.user and comment.user.type == "Bot":
                    reactions = await client.rest.reactions.async_list_for_issue_comment(
                        owner=repo.owner, repo=repo.repo, comment_id=comment.id,
                    )
                    has_thumbsup = any(r.content == "+1" for r in reactions.parsed_data)
                    if has_thumbsup:
                        events.append(PollEvent(
                            type=EventType.SPLIT_APPROVED, repo=repo, issue=issue,
                        ))
                        break

            # 人間のコメント (修正指示) を確認
            human_comments = [
                c for c in comments.parsed_data
                if c.user and c.user.type != "Bot"
                and (since is None or c.created_at > since)
            ]
            if human_comments:
                events.append(PollEvent(
                    type=EventType.SPLIT_MODIFIED, repo=repo, issue=issue,
                    comment=human_comments[-1],
                ))
        return events

    async def _get_pr_reviews(
        self, client: GitHub, repo: RepositoryConfig, issue: Issue,
    ) -> list[str]:
        """PR のレビュー状態を取得する。"""
        # 実装時: IssueState から PR 番号を取得し、reviews API を呼ぶ
        ...

    async def _check_ci_status(
        self, client: GitHub, repo: RepositoryConfig, issue: Issue,
    ) -> str | None:
        """CI ステータスを取得する。"success" | "failure" | None"""
        # 実装時: PR の commit status / check runs API を呼ぶ
        ...

    async def _get_ci_logs(
        self, client: GitHub, repo: RepositoryConfig, issue: Issue,
    ) -> str:
        """CI 失敗ログを取得する。"""
        # 実装時: GitHub Actions のログを取得
        ...
```

---

## 5. テストケース

**テストファイル**:
- `tests/unit/poller/test_event_router.py`
- `tests/unit/poller/test_github_poller.py`

### 5.1 EventRouter: イベントタイプ別ルーティングテスト

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ai_agent_orchestrator.poller.event_router import (
    EventRouter,
    EventType,
    PollEvent,
)


@pytest.fixture
def mock_sm():
    sm = AsyncMock()
    sm.register_issue = MagicMock()
    sm.get_issue_type = MagicMock(return_value="bug")
    sm.get_ci_retry_count = AsyncMock(return_value=0)
    return sm


@pytest.fixture
def mock_tq():
    return AsyncMock()


@pytest.fixture
def router(mock_sm, mock_tq):
    return EventRouter(state_machine=mock_sm, task_queue=mock_tq)


def _make_event(event_type, issue_number=1, **kwargs):
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    issue = MagicMock()
    issue.number = issue_number
    return PollEvent(
        type=event_type,
        repo=repo,
        issue=issue,
        **kwargs,
    )


class TestEventRouterNewIssue:
    @pytest.mark.asyncio
    async def test_new_issue_registers_and_enqueues(self, router, mock_sm, mock_tq):
        """NEW_ISSUE → register_issue + TYPE_DETECTION エンキュー。"""
        event = _make_event(EventType.NEW_ISSUE)
        await router.route(event)

        mock_sm.register_issue.assert_called_once()
        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase.value == "type-detection" or enqueued.phase == "type-detection"


class TestEventRouterPlanReaction:
    @pytest.mark.asyncio
    async def test_bug_plan_reaction_routes_to_fix(self, router, mock_sm, mock_tq):
        """Bug の 👍 リアクション → FIX へ遷移。"""
        mock_sm.get_issue_type.return_value = "bug"
        event = _make_event(EventType.PLAN_REACTION_ADDED)
        await router.route(event)

        mock_sm.transition.assert_called_once()
        args = mock_sm.transition.call_args[0]
        assert args[1].value == "fix" or str(args[1]) == "fix"

    @pytest.mark.asyncio
    async def test_feature_s_plan_reaction_routes_to_implement(self, router, mock_sm, mock_tq):
        """Feature-S の 👍 リアクション → IMPLEMENT へ遷移。"""
        mock_sm.get_issue_type.return_value = "feature-s"
        event = _make_event(EventType.PLAN_REACTION_ADDED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "implement" or str(args[1]) == "implement"


class TestEventRouterPlanComment:
    @pytest.mark.asyncio
    async def test_bug_plan_comment_routes_to_analysis(self, router, mock_sm, mock_tq):
        """Bug の方針指摘 → ANALYSIS へ遷移。"""
        mock_sm.get_issue_type.return_value = "bug"
        event = _make_event(EventType.PLAN_COMMENT_ADDED, comment=MagicMock(body="修正してください"))
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "analysis" or str(args[1]) == "analysis"

    @pytest.mark.asyncio
    async def test_feature_s_plan_comment_routes_to_plan_brief(self, router, mock_sm, mock_tq):
        """Feature-S の方針指摘 → PLAN_BRIEF へ遷移。"""
        mock_sm.get_issue_type.return_value = "feature-s"
        event = _make_event(EventType.PLAN_COMMENT_ADDED, comment=MagicMock(body="修正してください"))
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "plan-brief" or str(args[1]) == "plan-brief"


class TestEventRouterDesignPR:
    @pytest.mark.asyncio
    async def test_design_pr_approved_routes_to_planning(self, router, mock_sm, mock_tq):
        """設計 PR approve → PLANNING へ遷移。"""
        event = _make_event(EventType.DESIGN_PR_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "planning" or str(args[1]) == "planning"

    @pytest.mark.asyncio
    async def test_design_pr_commented_routes_to_design_revise(self, router, mock_sm, mock_tq):
        """設計 PR コメント → DESIGN_REVISE へ遷移。"""
        event = _make_event(EventType.DESIGN_PR_COMMENTED, extra={"comments": "要修正"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "design-revise" or str(args[1]) == "design-revise"


class TestEventRouterImplPR:
    @pytest.mark.asyncio
    async def test_impl_pr_approved_routes_to_done(self, router, mock_sm, mock_tq):
        """実装 PR approve → DONE へ遷移。"""
        event = _make_event(EventType.IMPL_PR_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "done" or str(args[1]) == "done"

    @pytest.mark.asyncio
    async def test_impl_pr_commented_routes_to_impl_revise(self, router, mock_sm, mock_tq):
        """実装 PR コメント → IMPL_REVISE へ遷移。"""
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "要修正"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "impl-revise" or str(args[1]) == "impl-revise"
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.priority == 1  # CRITICAL


class TestEventRouterCIFailure:
    @pytest.mark.asyncio
    async def test_ci_failure_within_limit_routes_to_ci_fix(self, router, mock_sm, mock_tq):
        """CI 失敗 (3回以内) → CI_FIX へ遷移。"""
        mock_sm.get_ci_retry_count.return_value = 1
        event = _make_event(EventType.CI_FAILED, extra={"ci_logs": "Error: test failed"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "ci-fix" or str(args[1]) == "ci-fix"

    @pytest.mark.asyncio
    async def test_ci_failure_exceeds_limit_routes_to_suspended(self, router, mock_sm, mock_tq):
        """CI 失敗 (3回超過) → SUSPENDED へ遷移。"""
        mock_sm.get_ci_retry_count.return_value = 3
        event = _make_event(EventType.CI_FAILED, extra={"ci_logs": "Error"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "suspended" or str(args[1]) == "suspended"


class TestEventRouterSplit:
    @pytest.mark.asyncio
    async def test_split_approved_routes_to_split_execute(self, router, mock_sm, mock_tq):
        """分割承認 → SPLIT_EXECUTE へ遷移。"""
        event = _make_event(EventType.SPLIT_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "split-execute" or str(args[1]) == "split-execute"

    @pytest.mark.asyncio
    async def test_split_modified_routes_to_hearing(self, router, mock_sm, mock_tq):
        """分割修正指示 → HEARING へ遷移。"""
        event = _make_event(EventType.SPLIT_MODIFIED, comment=MagicMock(body="こう分割して"))
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "hearing" or str(args[1]) == "hearing"


class TestEventRouterHearing:
    @pytest.mark.asyncio
    async def test_hearing_timeout_routes_to_suspended(self, router, mock_sm, mock_tq):
        """ヒアリングタイムアウト → SUSPENDED へ遷移。"""
        event = _make_event(EventType.HEARING_TIMEOUT)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "suspended" or str(args[1]) == "suspended"

    @pytest.mark.asyncio
    async def test_hearing_reply_enqueues_continue(self, router, mock_sm, mock_tq):
        """ヒアリング回答 → hearing_continue エンキュー (遷移なし)。"""
        comment = MagicMock()
        comment.body = "回答です"
        comment.issue_url = "https://api.github.com/repos/org/app/issues/1"
        event = PollEvent(
            type=EventType.HEARING_REPLY,
            repo=MagicMock(owner="org", repo="app"),
            comment=comment,
        )
        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_called_once()


class TestEventRouterError:
    @pytest.mark.asyncio
    async def test_error_event_does_not_crash(self, router, mock_sm, mock_tq):
        """ERROR イベントはクラッシュしない。"""
        event = PollEvent(
            type=EventType.ERROR,
            repo=MagicMock(owner="org", repo="app"),
            error=RuntimeError("API error"),
        )
        await router.route(event)
        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()
```

### 5.2 GitHubPoller: ポーリング検知テスト

```python
class TestGitHubPollerDetection:
    """ポーリングで正しくイベントが検知されることをテスト。"""

    @pytest.mark.asyncio
    async def test_detect_new_issue(self):
        """ai-agent ラベルあり & phase:* なしの Issue が NEW_ISSUE として検知される。"""
        # テスト実装: モックの GitHub client で Issues API をスタブ化
        ...

    @pytest.mark.asyncio
    async def test_detect_hearing_reply_excludes_bot(self):
        """Bot コメントはヒアリング回答として検知されない。"""
        ...

    @pytest.mark.asyncio
    async def test_detect_hearing_timeout(self):
        """24 時間無応答の Issue が HEARING_TIMEOUT として検知される。"""
        ...

    @pytest.mark.asyncio
    async def test_detect_thumbsup_reaction(self):
        """方針コメントへの 👍 リアクションが PLAN_REACTION_ADDED として検知される。"""
        ...

    @pytest.mark.asyncio
    async def test_detect_ci_failure(self):
        """CI 失敗が CI_FAILED として検知される。"""
        ...

    @pytest.mark.asyncio
    async def test_poll_error_produces_error_event(self):
        """ポーリング中のエラーが ERROR イベントとしてキューに入る。"""
        ...
```
