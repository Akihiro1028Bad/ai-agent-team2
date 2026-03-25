"""GitHubPoller (Polling).

GitHub API をポーリングしてイベントを検知する。
設定された間隔で全リポジトリを巡回し、
新規 Issue、ヒアリング回答、PR レビュー、CI 結果、リアクション等を検知する。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_agent_orchestrator.models import EventType, PollEvent

if TYPE_CHECKING:
    from githubkit.versions.latest.models import Issue, IssueComment

    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.client import AccountManager, GitHubClient

logger = logging.getLogger(__name__)


class GitHubPoller:
    """GitHub API をポーリングしてイベントを検知する.

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
        """GitHubPoller を初期化する.

        Args:
            account_manager: GitHub アカウント管理.
            repos: 監視対象リポジトリのリスト.
            interval_sec: ポーリング間隔 (秒). デフォルト: 120.
            hearing_timeout_hours: ヒアリングタイムアウト (時間). デフォルト: 24.
        """
        self._account_manager = account_manager
        self._repos = repos
        self._interval_sec = interval_sec
        self._hearing_timeout_hours = hearing_timeout_hours
        self._last_poll: dict[str, datetime] = {}
        self._running = False
        # BUG #1: Track seen issue numbers to avoid re-detecting as "new"
        self._seen_issue_numbers: set[int] = set()
        # BUG #3: Track seen reactions (issue_number, comment_id)
        self._seen_reactions: set[tuple[int, int]] = set()
        # BUG #4: General event deduplication
        self._seen_events: set[str] = set()

    async def start(self, event_queue: asyncio.Queue[PollEvent]) -> None:
        """ポーリングループを開始する.

        無限ループで全リポジトリを巡回し、検知したイベントをキューに追加する。
        asyncio.TaskGroup 内で実行されることを想定。

        Args:
            event_queue: イベントを追加するキュー.
        """
        self._running = True
        while self._running:
            for repo in self._repos:
                try:
                    events = await self._poll_repo(repo)
                    for event in events:
                        await event_queue.put(event)
                except Exception as e:
                    logger.error(
                        "Poll error for %s/%s: %s",
                        repo.owner,
                        repo.repo,
                        e,
                    )
                    await event_queue.put(
                        PollEvent(
                            type=EventType.CI_RESULT,
                            repo=repo,
                            error=e,
                        )
                    )
            await asyncio.sleep(self._interval_sec)

    async def stop(self) -> None:
        """ポーリングループを停止する."""
        self._running = False

    async def _poll_repo(
        self,
        repo: RepositoryConfig,
    ) -> list[PollEvent]:
        """単一リポジトリのポーリング.

        以下の順序でイベントを検知:
        1. 新規 Issue (ai-agent ラベルあり、phase:* ラベルなし)
        2. ヒアリング回答 (phase:hearing の Issue に人間コメント追加)
        3. ヒアリングタイムアウト (phase:hearing で 24 時間無応答)
        4. 方針リアクション検知 (phase:plan-review の Issue に thumbsup リアクション)
        5. 方針指摘コメント検知 (phase:plan-review の Issue にコメント)
        6. PR レビューイベント (設計PR, 実装PR の approve/コメント)
        7. CI 結果 (実装PR の CI 成功/失敗)
        8. 分割承認/修正 (Feature-L の SPLIT_PROPOSAL への thumbsup/コメント)

        Args:
            repo: リポジトリ設定.

        Returns:
            検知された PollEvent のリスト.
        """
        events: list[PollEvent] = []
        repo_key = f"{repo.owner}/{repo.repo}"
        since = self._last_poll.get(repo_key)
        self._last_poll[repo_key] = datetime.now(UTC)

        client = await self._account_manager.get_client_for_repo(repo.owner, repo.repo)

        # 1. 新規 Issue 検知
        new_issues = await self._detect_new_issues(client, repo)
        events.extend(PollEvent(type=EventType.NEW_ISSUE, repo=repo, issue=issue) for issue in new_issues)

        # 2. ヒアリング回答検知
        hearing_replies = await self._detect_hearing_replies(client, repo, since)
        events.extend(
            PollEvent(type=EventType.ISSUE_COMMENT, repo=repo, comment=comment) for comment in hearing_replies
        )

        # 3. ヒアリングタイムアウト検知
        timeout_issues = await self._detect_hearing_timeouts(client, repo)
        events.extend(PollEvent(type=EventType.HEARING_TIMEOUT, repo=repo, issue=issue) for issue in timeout_issues)

        # 4. 方針リアクション検知 (thumbsup)
        plan_reactions = await self._detect_plan_reactions(client, repo, since)
        events.extend(PollEvent(type=EventType.PLAN_REACTION_ADDED, repo=repo, issue=issue) for issue in plan_reactions)

        # 5. 方針指摘コメント検知
        plan_comments = await self._detect_plan_comments(client, repo, since)
        events.extend(
            PollEvent(
                type=EventType.PLAN_COMMENT_ADDED,
                repo=repo,
                comment=comment,
            )
            for comment in plan_comments
        )

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

    # ------------------------------------------------------------------
    # Detection methods
    # ------------------------------------------------------------------

    async def _detect_new_issues(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
    ) -> list[Issue]:
        """新規 Issue を検知する.

        条件: ai-agent ラベルあり AND phase:* ラベルなし AND state=open.
        PR は除外し、既に検知済みの Issue も除外する (重複検知防止).
        """
        issues = await client.get_issues_with_label(repo, repo.label)
        new: list[Issue] = []
        for issue in issues:
            # BUG #2: Filter out PRs (GitHub API returns both issues and PRs)
            # githubkit uses UNSET sentinel for missing fields; check if it's a real PR object
            pr_field = getattr(issue, "pull_request", None)
            if pr_field is not None and type(pr_field).__name__ != "Unset":
                continue
            # BUG #1: Skip already-seen issues to prevent re-detection
            if self._has_phase_label(issue) or issue.number in self._seen_issue_numbers:
                continue
            self._seen_issue_numbers.add(issue.number)
            new.append(issue)
        return new

    async def _detect_hearing_replies(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[IssueComment]:
        """ヒアリング回答を検知する.

        条件: phase:hearing ラベル付き Issue に since 以降の人間コメント
        (bot コメントは除外).
        """
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
        replies: list[IssueComment] = []
        for issue in issues:
            since_str = since.isoformat() if since else None
            comments = await client.list_comments(repo, issue.number, since=since_str)
            for comment in comments:
                if comment.user and comment.user.type != "Bot":
                    # BUG #4: Deduplicate hearing reply events
                    event_key = f"hearing_reply:{issue.number}:{comment.id}"
                    if event_key not in self._seen_events:
                        self._seen_events.add(event_key)
                        replies.append(comment)
        return replies

    async def _detect_hearing_timeouts(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
    ) -> list[Issue]:
        """ヒアリングタイムアウトを検知する.

        条件: phase:hearing ラベル付き Issue で
              最後のコメントから hearing_timeout_hours 以上経過.
        """
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
        threshold = datetime.now(UTC) - timedelta(hours=self._hearing_timeout_hours)
        timed_out: list[Issue] = []
        for issue in issues:
            if issue.updated_at and issue.updated_at < threshold:
                # BUG #4: Deduplicate timeout events
                event_key = f"hearing_timeout:{issue.number}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    timed_out.append(issue)
        return timed_out

    async def _detect_plan_reactions(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[Issue]:
        """方針承認リアクション (thumbsup) を検知する.

        条件: phase:plan-review ラベル付き Issue のコメントに +1 リアクション.
        """
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:plan-review")
        approved_issues: list[Issue] = []
        for issue in issues:
            comments = await client.list_comments(repo, issue.number)
            for comment in comments:
                if comment.user and comment.user.type == "Bot":
                    # BUG #3: Skip already-processed reactions
                    reaction_key = (issue.number, comment.id)
                    if reaction_key in self._seen_reactions:
                        continue
                    reactions = await client.get_reactions(repo, comment.id)
                    has_thumbsup = any(r.content == "+1" for r in reactions)
                    if has_thumbsup:
                        self._seen_reactions.add(reaction_key)
                        approved_issues.append(issue)
                        break
        return approved_issues

    async def _detect_plan_comments(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[IssueComment]:
        """方針への指摘コメントを検知する.

        条件: phase:plan-review ラベル付き Issue に since 以降の人間コメント.
        """
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:plan-review")
        feedback: list[IssueComment] = []
        for issue in issues:
            since_str = since.isoformat() if since else None
            comments = await client.list_comments(repo, issue.number, since=since_str)
            for comment in comments:
                if comment.user and comment.user.type != "Bot":
                    # BUG #4: Deduplicate plan comment events
                    event_key = f"plan_comment:{issue.number}:{comment.id}"
                    if event_key not in self._seen_events:
                        self._seen_events.add(event_key)
                        feedback.append(comment)
        return feedback

    async def _detect_pr_events(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[PollEvent]:
        """PR レビューイベント (設計PR, 実装PR) を検知する.

        - 設計 PR: approve -> DESIGN_PR_APPROVED, コメント -> DESIGN_PR_COMMENTED
        - 実装 PR: approve -> IMPL_PR_APPROVED, コメント -> IMPL_PR_COMMENTED
        """
        events: list[PollEvent] = []
        label_configs: list[tuple[str, str, str]] = [
            (
                "design-review",
                EventType.DESIGN_PR_APPROVED,
                EventType.DESIGN_PR_COMMENTED,
            ),
            (
                "impl-review",
                EventType.IMPL_PR_APPROVED,
                EventType.IMPL_PR_COMMENTED,
            ),
        ]
        for label_suffix, approved_type, commented_type in label_configs:
            issues = await client.get_issues_with_label(repo, f"{repo.label},phase:{label_suffix}")
            for issue in issues:
                pr_reviews = await self._get_pr_reviews(client, repo, issue)
                for review_event in pr_reviews:
                    event_type = approved_type if review_event == "approved" else commented_type
                    # BUG #4: Deduplicate PR review events
                    event_key = f"pr_review:{event_type}:{issue.number}"
                    if event_key in self._seen_events:
                        continue
                    self._seen_events.add(event_key)
                    if review_event == "approved":
                        events.append(
                            PollEvent(
                                type=approved_type,
                                repo=repo,
                                issue=issue,
                            )
                        )
                    elif review_event == "commented":
                        events.append(
                            PollEvent(
                                type=commented_type,
                                repo=repo,
                                issue=issue,
                                extra={"comments": review_event},
                            )
                        )
        return events

    async def _detect_ci_results(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
    ) -> list[PollEvent]:
        """CI 結果を検知する.

        phase:implement または phase:ci-fix ラベルの Issue に紐づく PR の
        CI ステータスを確認する。
        """
        events: list[PollEvent] = []
        for label_suffix in ("implement", "ci-fix"):
            issues = await client.get_issues_with_label(repo, f"{repo.label},phase:{label_suffix}")
            for issue in issues:
                ci_status = await self._check_ci_status(client, repo, issue)
                if ci_status is None:
                    continue
                # BUG #4: Deduplicate CI result events
                event_key = f"ci_result:{issue.number}:{ci_status}"
                if event_key in self._seen_events:
                    continue
                self._seen_events.add(event_key)
                if ci_status == "failure":
                    ci_logs = await self._get_ci_logs(client, repo, issue)
                    events.append(
                        PollEvent(
                            type=EventType.CI_RESULT,
                            repo=repo,
                            issue=issue,
                            extra={
                                "ci_status": "failure",
                                "ci_logs": ci_logs,
                            },
                        )
                    )
                elif ci_status == "success":
                    events.append(
                        PollEvent(
                            type=EventType.CI_RESULT,
                            repo=repo,
                            issue=issue,
                            extra={"ci_status": "success"},
                        )
                    )
        return events

    async def _detect_split_events(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[PollEvent]:
        """分割承認/修正イベントを検知する.

        phase:split-proposal ラベル付き Issue の thumbsup リアクションまたはコメントを検知。
        """
        events: list[PollEvent] = []
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:split-proposal")
        for issue in issues:
            comments = await client.list_comments(repo, issue.number)
            for comment in comments:
                if comment.user and comment.user.type == "Bot":
                    # BUG #3: Skip already-processed reactions
                    reaction_key = (issue.number, comment.id)
                    if reaction_key in self._seen_reactions:
                        continue
                    reactions = await client.get_reactions(repo, comment.id)
                    has_thumbsup = any(r.content == "+1" for r in reactions)
                    if has_thumbsup:
                        self._seen_reactions.add(reaction_key)
                        events.append(
                            PollEvent(
                                type=EventType.SPLIT_APPROVED,
                                repo=repo,
                                issue=issue,
                            )
                        )
                        break

            # 人間のコメント (修正指示) を確認
            human_comments = [
                c for c in comments if c.user and c.user.type != "Bot" and (since is None or c.created_at > since)
            ]
            for hc in human_comments:
                # BUG #4: Deduplicate split modified events
                event_key = f"split_modified:{issue.number}:{hc.id}"
                if event_key in self._seen_events:
                    continue
                self._seen_events.add(event_key)
                events.append(
                    PollEvent(
                        type=EventType.SPLIT_MODIFIED,
                        repo=repo,
                        issue=issue,
                        comment=hc,
                    )
                )
        return events

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _has_phase_label(issue: Issue) -> bool:
        """Issue に phase:* ラベルが付いているかどうかを判定する."""
        for lbl in issue.labels or []:
            label_name: str | None = None
            if isinstance(lbl, str):
                label_name = lbl
            elif hasattr(lbl, "name"):
                name_val = getattr(lbl, "name", None)
                if isinstance(name_val, str):
                    label_name = name_val
            if label_name and label_name.startswith("phase:"):
                return True
        return False

    async def _get_pr_reviews(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        issue: Issue,
    ) -> list[str]:
        """PR のレビュー状態を取得する.

        Returns:
            "approved" または "commented" のリスト.
        """
        prs = await client.list_pull_requests(repo)
        results: list[str] = []
        for pr in prs:
            issue_ref = f"#{issue.number}"
            pr_body = getattr(pr, "body", "") or ""
            pr_title = getattr(pr, "title", "") or ""
            if issue_ref in pr_body or issue_ref in pr_title:
                reviews = await client.get_pr_reviews(repo.owner, repo.repo, pr.number)
                for review in reviews:
                    state = review.get("state", "")
                    if state == "APPROVED":
                        results.append("approved")
                    elif state == "CHANGES_REQUESTED" or (state == "COMMENTED" and review.get("body")):
                        results.append("commented")
        return results

    async def _check_ci_status(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        issue: Issue,
    ) -> str | None:
        """CI ステータスを取得する.

        Returns:
            "success" | "failure" | None
        """
        prs = await client.list_pull_requests(repo)
        for pr in prs:
            issue_ref = f"#{issue.number}"
            pr_body = getattr(pr, "body", "") or ""
            pr_title = getattr(pr, "title", "") or ""
            if issue_ref in pr_body or issue_ref in pr_title:
                head_ref = getattr(pr, "head", None)
                ref = getattr(head_ref, "ref", None) if head_ref else None
                if ref:
                    checks = await client.get_check_runs(repo, ref)
                    if not checks:
                        return None
                    all_success = all(c.get("conclusion") == "success" for c in checks)
                    any_failure = any(c.get("conclusion") == "failure" for c in checks)
                    if any_failure:
                        return "failure"
                    if all_success:
                        return "success"
        return None

    async def _get_ci_logs(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        issue: Issue,
    ) -> str:
        """CI 失敗ログを取得する."""
        # 簡易実装: ログの詳細は GitHub Actions API 経由で取得予定
        return "CI failure detected. Check GitHub Actions for details."
