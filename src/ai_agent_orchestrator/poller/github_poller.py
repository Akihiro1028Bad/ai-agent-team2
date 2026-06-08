"""GitHubPoller (Polling).

GitHub API をポーリングしてイベントを検知する。
設定された間隔で全リポジトリを巡回し、
新規 Issue、ヒアリング回答、PR レビュー、CI 結果、リアクション等を検知する。
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Hashable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from ai_agent_orchestrator.models import EventType, IssueKey, PollEvent

if TYPE_CHECKING:
    from githubkit.versions.latest.models import Issue, IssueComment, PullRequestSimple

    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.client import AccountManager, GitHubClient

logger = logging.getLogger(__name__)

_BOT_MARKER = "<!-- ai-agent-bot -->"

# 重複排除キャッシュの上限。超過時は古い要素から削除される。
_SEEN_CACHE_MAX_SIZE = 10_000
# レート制限の残量がこの値を下回るとポーリングを一時停止する (デフォルト)。
_DEFAULT_MIN_RATE_LIMIT_REMAINING = 200


class _BoundedSet:
    """挿入順を保持し、上限超過時に最古の要素から削除する集合.

    無制限に成長する `set` を毎時クリアすると、過去の全イベントが
    再検知されてコメント再投稿などの書き込みループを引き起こす。
    上限付きの LRU 的な集合にすることで、メモリリークと再検知ストームの
    両方を防ぐ。
    """

    def __init__(self, max_size: int = _SEEN_CACHE_MAX_SIZE) -> None:
        """上限サイズを指定して初期化する.

        Args:
            max_size: 保持する最大要素数.
        """
        self._max_size = max_size
        self._data: OrderedDict[Hashable, None] = OrderedDict()

    def __contains__(self, key: Hashable) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def add(self, key: Hashable) -> None:
        """要素を追加する。既存なら最新位置へ移動し、上限超過時は最古を削除する."""
        if key in self._data:
            self._data.move_to_end(key)
            return
        self._data[key] = None
        if len(self._data) > self._max_size:
            self._data.popitem(last=False)


_CI_LOG_MAX_CHARS = 30_000
_CI_LOG_CONTEXT_LINES = 5
_CI_LOG_ERROR_KEYWORDS = frozenset(
    ["error", "Error", "ERROR", "FAILED", "failed", "AssertionError", "Traceback", "FAIL", "exception"]
)


def _trim_ci_logs(logs: str, max_chars: int = _CI_LOG_MAX_CHARS) -> str:
    """CI ログをトークン制限に収まるようにトリミングする.

    ログ全体が max_chars 以内ならそのまま返す。
    超過する場合はエラー行とその前後 _CI_LOG_CONTEXT_LINES 行を優先的に抽出する。

    Args:
        logs: 元の CI ログ文字列.
        max_chars: 最大文字数 (デフォルト 30,000).

    Returns:
        トリミングされたログ文字列.
    """
    if len(logs) <= max_chars:
        return logs

    lines = logs.splitlines()
    total_lines = len(lines)
    # エラー行のインデックスを収集
    error_indices: set[int] = set()
    for i, line in enumerate(lines):
        if any(kw in line for kw in _CI_LOG_ERROR_KEYWORDS):
            for j in range(
                max(0, i - _CI_LOG_CONTEXT_LINES),
                min(total_lines, i + _CI_LOG_CONTEXT_LINES + 1),
            ):
                error_indices.add(j)

    kept_lines: list[str] = [lines[i] for i in sorted(error_indices)]
    extracted = "\n".join(kept_lines)

    header = f"[CI ログ: 全 {total_lines} 行中 {len(kept_lines)} 行を抽出]\n"
    result = header + extracted
    # それでも超える場合は末尾を切り詰める
    if len(result) > max_chars:
        result = result[:max_chars] + "\n...(truncated)"
    return result


def _is_bot_comment(body: str) -> bool:
    """AI agent が投稿したコメントかどうかを判定する."""
    return _BOT_MARKER in body


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
        approve_comment: str = "LGTM",
        min_rate_limit_remaining: int = _DEFAULT_MIN_RATE_LIMIT_REMAINING,
    ) -> None:
        """GitHubPoller を初期化する.

        Args:
            account_manager: GitHub アカウント管理.
            repos: 監視対象リポジトリのリスト.
            interval_sec: ポーリング間隔 (秒). デフォルト: 120.
            hearing_timeout_hours: ヒアリングタイムアウト (時間). デフォルト: 24.
            approve_comment: コメントによる承認の完全一致文字列. デフォルト: "LGTM".
            min_rate_limit_remaining: この残量を下回るとそのリポジトリの
                ポーリングをスキップする閾値. デフォルト: 200.
        """
        self._account_manager = account_manager
        self._repos = repos
        self._interval_sec = interval_sec
        self._hearing_timeout_hours = hearing_timeout_hours
        self._approve_comment = approve_comment
        self._min_rate_limit_remaining = min_rate_limit_remaining
        self._last_poll: dict[str, datetime] = {}
        self._running = False
        # BUG #1: Track seen issue keys to avoid re-detecting as "new"
        self._seen_issue_numbers: _BoundedSet = _BoundedSet()
        # BUG #3: Track seen reactions (repo_key, issue_number, comment_id)
        self._seen_reactions: _BoundedSet = _BoundedSet()
        # BUG #4: General event deduplication
        self._seen_events: _BoundedSet = _BoundedSet()
        # 1サイクル内で list_pull_requests の結果をキャッシュ (state ごと)
        self._pr_cache: dict[tuple[str, str], list[PullRequestSimple]] = {}

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
        # 1サイクルごとに PR 一覧キャッシュをリセット (重複 list_pull_requests を防止)
        self._pr_cache.clear()

        client = await self._account_manager.get_client_for_repo(repo.owner, repo.repo)

        # レート制限の残量が閾値を下回る場合はこのリポジトリのポーリングをスキップ
        if not await self._has_rate_budget(client, repo_key):
            return []

        since = self._last_poll.get(repo_key)
        self._last_poll[repo_key] = datetime.now(UTC)
        logger.debug("poll [%s]: start (since=%s)", repo_key, since.isoformat() if since else "first-run")

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
                issue=issue,
                comment=comment,
            )
            for issue, comment in plan_comments
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

        if events:
            event_summary = ", ".join(f"{e.type}#{e.issue.number if e.issue else '?'}" for e in events)
            logger.debug("poll [%s]: %d event(s) detected → %s", repo_key, len(events), event_summary)
        else:
            logger.debug("poll [%s]: no events detected", repo_key)
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
        repo_key = f"{repo.owner}/{repo.repo}"
        logger.debug("new-issue detection [%s]: fetched %d labeled issue(s)", repo_key, len(issues))
        for issue in issues:
            # BUG #2: Filter out PRs (GitHub API returns both issues and PRs)
            # githubkit uses UNSET sentinel for missing fields; check if it's a real PR object
            pr_field = getattr(issue, "pull_request", None)
            if pr_field is not None and type(pr_field).__name__ != "Unset":
                logger.debug("new-issue detection [%s] #%d: skip (pull request)", repo_key, issue.number)
                continue
            ik: IssueKey = (repo_key, issue.number)
            if self._has_phase_label(issue):
                logger.debug("new-issue detection [%s] #%d: skip (phase label present)", repo_key, issue.number)
                continue
            # BUG #1: Skip already-seen issues to prevent re-detection
            if ik in self._seen_issue_numbers:
                logger.debug("new-issue detection [%s] #%d: skip (already seen)", repo_key, issue.number)
                continue
            self._seen_issue_numbers.add(ik)
            new.append(issue)
        logger.debug(
            "new-issue detection [%s]: %d new issue(s) detected → %s",
            repo_key,
            len(new),
            [i.number for i in new],
        )
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
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
        replies: list[IssueComment] = []
        repo_key = f"{repo.owner}/{repo.repo}"
        logger.debug("hearing-reply detection [%s]: %d hearing-wait issue(s)", repo_key, len(issues))
        for issue in issues:
            since_str = since.isoformat() if since else None
            comments = await client.list_comments(repo, issue.number, since=since_str)
            for comment in comments:
                body = comment.body or ""
                if _is_bot_comment(body):
                    logger.debug(
                        "hearing-reply detection [%s] #%d: skip comment %s (bot)",
                        repo_key,
                        issue.number,
                        comment.id,
                    )
                    continue
                # BUG #4: Deduplicate hearing reply events
                event_key = f"hearing_reply:{repo_key}:{issue.number}:{comment.id}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    replies.append(comment)
        logger.debug("hearing-reply detection [%s]: %d repl(ies) detected", repo_key, len(replies))
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
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
        threshold = datetime.now(UTC) - timedelta(hours=self._hearing_timeout_hours)
        timed_out: list[Issue] = []
        repo_key = f"{repo.owner}/{repo.repo}"
        for issue in issues:
            if issue.updated_at and issue.updated_at < threshold:
                # BUG #4: Deduplicate timeout events
                event_key = f"hearing_timeout:{repo_key}:{issue.number}"
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
        Bot コメントまたは方針コメント (## 修正方針, ## 方針 等) を対象とする。
        PAT 経由で投稿された場合 user.type が "User" になるため、
        コメント内容も併せてチェックする。
        """
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:plan-review")
        approved_issues: list[Issue] = []
        repo_key = f"{repo.owner}/{repo.repo}"
        logger.debug("plan-reaction detection [%s]: %d plan-review issue(s)", repo_key, len(issues))
        # 方針コメントを識別するパターン (Markdown 見出し)
        plan_markers = ("## 修正方針", "## 方針", "## Analysis", "## Plan", "## 分析結果")
        bot_marker = "<!-- ai-agent-bot -->"
        for issue in issues:
            comments = await client.list_comments(repo, issue.number)
            for comment in comments:
                body = comment.body or ""
                is_bot = (comment.user and comment.user.type == "Bot") or bot_marker in body
                is_plan_comment = any(marker in body for marker in plan_markers)
                if is_bot or is_plan_comment:
                    # BUG #3: Skip already-processed reactions
                    reaction_key = (repo_key, issue.number, comment.id)
                    if reaction_key in self._seen_reactions:
                        continue
                    reactions = await client.get_reactions(repo, comment.id)
                    has_thumbsup = any(r.content == "+1" for r in reactions)
                    if has_thumbsup:
                        self._seen_reactions.add(reaction_key)
                        approved_issues.append(issue)
                        break
        logger.debug("plan-reaction detection [%s]: %d approval(s) detected", repo_key, len(approved_issues))
        return approved_issues

    async def _detect_plan_comments(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[tuple[Issue, IssueComment]]:
        """方針への指摘コメントを検知する.

        条件: phase:plan-review ラベル付き Issue に since 以降の人間コメント.
        初回ポーリング (since=None) では検知しない (過去の全コメントを誤検知するため)。

        Returns:
            (Issue, IssueComment) タプルのリスト.
        """
        repo_key = f"{repo.owner}/{repo.repo}"
        if since is None:
            logger.debug("plan-comment detection [%s]: skip (first-run, since=None)", repo_key)
            return []
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:plan-review")
        feedback: list[tuple[Issue, IssueComment]] = []
        for issue in issues:
            since_str = since.isoformat()
            comments = await client.list_comments(repo, issue.number, since=since_str)
            for comment in comments:
                body = comment.body or ""
                if _is_bot_comment(body):
                    continue
                # BUG #4: Deduplicate plan comment events
                event_key = f"plan_comment:{repo_key}:{issue.number}:{comment.id}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    feedback.append((issue, comment))
        logger.debug("plan-comment detection [%s]: %d feedback comment(s) detected", repo_key, len(feedback))
        return feedback

    async def _detect_pr_events(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        since: datetime | None,
    ) -> list[PollEvent]:
        """PR レビューイベント (設計PR, 実装PR) を検知する.

        - 設計 PR (design-review): LGTM/approve → DESIGN_PR_APPROVED, コメント → DESIGN_PR_COMMENTED
        - 実装 PR (impl-review): PRマージ → IMPL_PR_MERGED, レビューコメント → IMPL_PR_COMMENTED
          (実装PRは手動マージで完了とする。LGTM/approve では DONE に遷移しない)
        """
        events: list[PollEvent] = []
        repo_key = f"{repo.owner}/{repo.repo}"

        # --- 設計PR: レビュー (LGTM/approve) で承認検知 ---
        design_issues = await client.get_issues_with_label(repo, f"{repo.label},phase:design-review")
        for issue in design_issues:
            pr_reviews = await self._get_pr_reviews(client, repo, issue)
            for review_info in pr_reviews:
                review_state = review_info["state"]
                review_body = review_info["body"]
                review_id = review_info.get("id", "")
                event_type = (
                    EventType.DESIGN_PR_APPROVED if review_state == "approved" else EventType.DESIGN_PR_COMMENTED
                )
                event_key = f"pr_review:{repo_key}:{event_type}:{issue.number}:{review_id}"
                if event_key in self._seen_events:
                    continue
                self._seen_events.add(event_key)
                if review_state == "approved":
                    events.append(PollEvent(type=EventType.DESIGN_PR_APPROVED, repo=repo, issue=issue))
                else:
                    events.append(
                        PollEvent(
                            type=EventType.DESIGN_PR_COMMENTED,
                            repo=repo,
                            issue=issue,
                            extra={"comments": review_body},
                        )
                    )

        # --- 実装PR: マージで完了検知、レビューコメントで修正検知 ---
        impl_issues = await client.get_issues_with_label(repo, f"{repo.label},phase:impl-review", state="all")
        for issue in impl_issues:
            # マージ検知 (最優先)
            merged = await self._check_pr_merged(client, repo, issue)
            if merged:
                event_key = f"pr_merged:{repo_key}:{issue.number}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    events.append(PollEvent(type=EventType.IMPL_PR_MERGED, repo=repo, issue=issue))
                continue  # マージ済みならコメント検知は不要

            # レビューコメント検知 (修正指摘)
            pr_reviews = await self._get_pr_reviews(client, repo, issue)
            for review_info in pr_reviews:
                review_state = review_info["state"]
                review_body = review_info["body"]
                review_id = review_info.get("id", "")
                if review_state != "approved":
                    event_key = f"pr_review:{repo_key}:{EventType.IMPL_PR_COMMENTED}:{issue.number}:{review_id}"
                    if event_key not in self._seen_events:
                        self._seen_events.add(event_key)
                        events.append(
                            PollEvent(
                                type=EventType.IMPL_PR_COMMENTED,
                                repo=repo,
                                issue=issue,
                                extra={"comments": review_body},
                            )
                        )
                # approve/LGTM は無視 (実装PRはマージで完了)

        return events

    async def _check_pr_merged(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        issue: Issue,
    ) -> bool:
        """Issue に紐づく PR がマージ済みかどうかを確認する.

        Returns:
            マージ済みの場合 True。
        """
        # closed PR からマージ済みを探す
        closed_prs = await self._list_prs_cached(client, repo, "closed")
        for pr in closed_prs:
            if self._pr_references_issue(pr, issue.number):
                merged_at = getattr(pr, "merged_at", None)
                if merged_at is not None:
                    return True
        return False

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
        repo_key = f"{repo.owner}/{repo.repo}"
        for label_suffix in ("ci-fix", "impl-review"):
            issues = await client.get_issues_with_label(repo, f"{repo.label},phase:{label_suffix}")
            logger.debug("ci-result detection [%s] (phase:%s): %d issue(s)", repo_key, label_suffix, len(issues))
            for issue in issues:
                ci_status = await self._check_ci_status(client, repo, issue)
                logger.debug("ci-result detection [%s] #%d: status=%s", repo_key, issue.number, ci_status or "none")
                if ci_status is None:
                    continue
                # BUG #4: Deduplicate CI result events
                # ci-fix フェーズはリトライのため同じ CI failure を複数回検知する必要がある
                event_key = f"ci_result:{repo_key}:{issue.number}:{ci_status}"
                if label_suffix != "ci-fix" and event_key in self._seen_events:
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
        repo_key = f"{repo.owner}/{repo.repo}"
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:split-proposal")
        logger.debug("split-event detection [%s]: %d split-proposal issue(s)", repo_key, len(issues))
        for issue in issues:
            comments = await client.list_comments(repo, issue.number)
            for comment in comments:
                body = comment.body or ""
                if _is_bot_comment(body):
                    # BUG #3: Skip already-processed reactions
                    reaction_key = (repo_key, issue.number, comment.id)
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
            # 分割提案コメント以降の人間コメントのみを対象とする
            # (ヒアリング回答など分割提案前のコメントを誤検知しないようにする)
            split_proposal_time = self._find_latest_bot_comment_time(comments, "分割提案")
            # 分割提案コメントがまだなければ、最後の Bot コメント以降を対象とする
            cutoff_time = split_proposal_time or self._find_latest_bot_comment_time(comments)
            human_comments = [
                c
                for c in comments
                if not _is_bot_comment(c.body or "") and (cutoff_time is None or c.created_at > cutoff_time)
            ]
            for hc in human_comments:
                # BUG #4: Deduplicate split modified events
                event_key = f"split_modified:{repo_key}:{issue.number}:{hc.id}"
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
    # Cache / utility helpers
    # ------------------------------------------------------------------

    async def _has_rate_budget(self, client: GitHubClient, repo_key: str) -> bool:
        """レート制限の残量が閾値以上あるかを確認する.

        `/rate_limit` エンドポイントはレート制限を消費しないため、毎サイクル
        呼び出してもコストはない。残量が閾値を下回る場合はポーリングを控え、
        レート制限超過による GitHub の不正利用検知を回避する。

        Args:
            client: GitHub クライアント.
            repo_key: "owner/repo" 形式のリポジトリキー (ログ用).

        Returns:
            残量が閾値以上、または取得に失敗した場合 True (続行)。
            残量が閾値未満の場合 False (スキップ)。
        """
        try:
            status = await client.get_rate_limit()
        except Exception:
            logger.debug("rate limit check failed for %s, continuing", repo_key, exc_info=True)
            return True
        if status.remaining < self._min_rate_limit_remaining:
            logger.warning(
                "Rate limit low for %s: remaining=%d (< %d). Skipping this poll cycle.",
                repo_key,
                status.remaining,
                self._min_rate_limit_remaining,
            )
            return False
        logger.debug("rate limit OK for %s: remaining=%d", repo_key, status.remaining)
        return True

    async def _list_prs_cached(
        self,
        client: GitHubClient,
        repo: RepositoryConfig,
        state: str = "open",
    ) -> list[PullRequestSimple]:
        """1サイクル内で PR 一覧をキャッシュして返す.

        同一サイクル内では複数の検知メソッドが PR 一覧を必要とするため、
        state ごとに1回だけ API を呼び出し、結果を使い回す。
        キャッシュは `_poll_repo` の先頭でクリアされる。

        Args:
            client: GitHub クライアント.
            repo: リポジトリ設定.
            state: PR の状態フィルタ ("open" | "closed" | "all").

        Returns:
            PullRequestSimple のリスト.
        """
        repo_key = f"{repo.owner}/{repo.repo}"
        cache_key = (repo_key, state)
        cached = self._pr_cache.get(cache_key)
        if cached is None:
            cached = await client.list_pull_requests(repo, state=state)
            self._pr_cache[cache_key] = cached
        return cached

    @staticmethod
    def _pr_references_issue(pr: object, issue_number: int) -> bool:
        """PR が指定 Issue を参照しているか判定する."""
        issue_ref = f"#{issue_number}"
        pr_body = getattr(pr, "body", "") or ""
        pr_title = getattr(pr, "title", "") or ""
        return issue_ref in pr_body or issue_ref in pr_title

    @staticmethod
    def _find_latest_bot_comment_time(
        comments: Sequence[IssueComment],
        content_marker: str | None = None,
    ) -> datetime | None:
        """Bot コメントの最新投稿時刻を取得する."""
        return max(
            (
                c.created_at
                for c in comments
                if _is_bot_comment(c.body or "") and (content_marker is None or content_marker in (c.body or ""))
            ),
            default=None,
        )

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
    ) -> list[dict[str, str]]:
        """PR のレビュー状態を取得する.

        PR レビュー (Approve/Changes Requested) に加え、
        PR の一般コメントに approve_comment と完全一致するものがあれば承認とみなす。
        承認が1つでもあれば承認のみ返す(コメントと承認の混在による遷移競合を防止)。
        open PR で見つからなければ、最近マージされた PR もチェックする。

        Returns:
            {"state": "approved"|"commented", "body": "review body"} のリスト.
        """
        # open PR を優先的にチェックし、見つからなければマージ済みもチェック
        prs = await self._list_prs_cached(client, repo, "open")
        matching_prs = [pr for pr in prs if self._pr_references_issue(pr, issue.number)]
        if not matching_prs:
            # マージ済み PR も検索 (設計PRがマージされた場合の検知用)
            closed_prs = await self._list_prs_cached(client, repo, "closed")
            matching_prs = [pr for pr in closed_prs if self._pr_references_issue(pr, issue.number)]
        approved: list[dict[str, str]] = []
        commented: list[dict[str, str]] = []
        for pr in matching_prs:
            # マージ済みPRはそれ自体が承認済みとみなす
            merged = getattr(pr, "merged_at", None) is not None or getattr(pr, "merged", False)
            if merged:
                approved.append({"state": "approved", "body": "PR merged", "id": f"merged-{pr.number}"})
                continue
            reviews = await client.get_pr_reviews(repo.owner, repo.repo, pr.number)
            last_approved_at: str = ""
            last_commented_at: str = ""
            for review in reviews:
                state = review.get("state", "")
                body = review.get("body", "") or ""
                review_id = str(review.get("id", ""))
                submitted_at = review.get("submitted_at", "") or ""
                is_approved = state == "APPROVED"
                is_lgtm = state == "COMMENTED" and body.strip().upper() == self._approve_comment.upper()
                if is_approved or is_lgtm:
                    approved.append({"state": "approved", "body": body, "id": review_id})
                    if submitted_at > last_approved_at:
                        last_approved_at = submitted_at
                elif state == "CHANGES_REQUESTED" or (state == "COMMENTED" and body):
                    commented.append({"state": "commented", "body": body, "id": review_id})
                    if submitted_at > last_commented_at:
                        last_commented_at = submitted_at
            # コメントによる承認: PR の一般コメントを確認
            pr_comments = await client.list_comments(repo, pr.number)
            for comment in pr_comments:
                body = comment.body or ""
                if _is_bot_comment(body):
                    continue
                if body.strip() == self._approve_comment:
                    approved.append({"state": "approved", "body": body, "id": str(comment.id)})
                    break
        # 承認後に新たなコメントレビューがある場合はコメントを優先(修正要求の検知)
        if approved and commented and last_commented_at > last_approved_at:
            return commented
        # 承認があればコメントは無視(遷移競合を防止)
        return approved if approved else commented

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
        prs = await self._list_prs_cached(client, repo, "open")
        for pr in prs:
            if self._pr_references_issue(pr, issue.number):
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
        """CI 失敗ログを GitHub Actions API から取得する.

        Issue に紐づく PR のブランチを特定し、最新の失敗 workflow run から
        失敗ジョブのログを取得して返す。取得失敗時は簡易サマリにフォールバック。

        Returns:
            CI 失敗ログ文字列 (最大 30,000 文字にトリミング済み).
        """
        try:
            # Issue に紐づく PR のブランチ名を取得
            branch: str | None = None
            prs = await self._list_prs_cached(client, repo, "open")
            for pr in prs:
                if self._pr_references_issue(pr, issue.number):
                    head_ref = getattr(pr, "head", None)
                    branch = getattr(head_ref, "ref", None) if head_ref else None
                    break

            if not branch:
                return "CI failure detected. (PR not found — check GitHub Actions for details.)"

            # 最新の失敗 workflow run を取得
            runs = await client.get_workflow_runs(repo, branch)
            failed_runs = [r for r in runs if r.get("conclusion") == "failure"]
            if not failed_runs:
                return f"CI failure detected on branch '{branch}'. (No failed workflow runs found.)"

            latest_run = failed_runs[0]
            run_id: int = latest_run["id"]

            # 失敗ジョブを取得してログを収集
            failed_jobs = await client.get_workflow_run_jobs(repo, run_id)
            if not failed_jobs:
                return (
                    f"CI failed (run_id={run_id}, branch='{branch}'). "
                    f"(No failed jobs found — check GitHub Actions for details.)"
                )

            log_parts: list[str] = []
            for job in failed_jobs:
                job_id: int = job["id"]
                job_name: str = job["name"]
                log_text = await client.download_job_logs(repo, job_id)
                if log_text:
                    log_parts.append(f"=== Job: {job_name} ===\n{log_text}")
                else:
                    # ログ取得失敗時はステップ情報だけ出力
                    failed_steps = [s["name"] for s in job.get("steps", []) if s.get("conclusion") == "failure"]
                    log_parts.append(
                        f"=== Job: {job_name} (log unavailable) ===\n"
                        f"Failed steps: {', '.join(failed_steps) or 'unknown'}"
                    )

            combined = "\n\n".join(log_parts)
            return _trim_ci_logs(combined)

        except Exception:
            logger.warning(
                "Failed to fetch CI logs for issue #%d, falling back to summary",
                issue.number,
                exc_info=True,
            )
            return "CI failure detected. (Log retrieval failed — check GitHub Actions for details.)"
