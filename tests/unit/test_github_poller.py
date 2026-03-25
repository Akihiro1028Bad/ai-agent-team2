"""GitHubPoller のユニットテスト."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import EventType
from ai_agent_orchestrator.poller.github_poller import GitHubPoller

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo() -> MagicMock:
    """テスト用の RepositoryConfig モック."""
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    repo.label = "ai-agent"
    repo.base_branch = "main"
    return repo


def _make_issue(
    number: int = 1,
    labels: list[str] | None = None,
    updated_at: datetime | None = None,
) -> MagicMock:
    """テスト用 Issue モック."""
    issue = MagicMock()
    issue.number = number
    label_mocks = []
    for name in labels or []:
        lbl = MagicMock()
        lbl.name = name
        label_mocks.append(lbl)
    issue.labels = label_mocks
    issue.updated_at = updated_at or datetime.now(UTC)
    return issue


def _make_comment(
    comment_id: int = 1,
    body: str = "comment body",
    user_type: str = "User",
    created_at: datetime | None = None,
    issue_url: str = "https://api.github.com/repos/org/app/issues/1",
) -> MagicMock:
    """テスト用 IssueComment モック."""
    comment = MagicMock()
    comment.id = comment_id
    comment.body = body
    comment.user = MagicMock()
    comment.user.type = user_type
    comment.created_at = created_at or datetime.now(UTC)
    comment.issue_url = issue_url
    return comment


def _make_reaction(content: str = "+1") -> MagicMock:
    """テスト用 Reaction モック."""
    reaction = MagicMock()
    reaction.content = content
    return reaction


def _make_client() -> AsyncMock:
    """テスト用 GitHubClient モック."""
    client = AsyncMock()
    client.get_issues_with_label = AsyncMock(return_value=[])
    client.list_comments = AsyncMock(return_value=[])
    client.get_reactions = AsyncMock(return_value=[])
    client.list_pull_requests = AsyncMock(return_value=[])
    client.get_pr_reviews = AsyncMock(return_value=[])
    client.get_check_runs = AsyncMock(return_value=[])
    return client


def _make_account_manager(client: AsyncMock) -> AsyncMock:
    """テスト用 AccountManager モック."""
    am = AsyncMock()
    am.get_client_for_repo = AsyncMock(return_value=client)
    return am


# ---------------------------------------------------------------------------
# Tests: _detect_new_issues
# ---------------------------------------------------------------------------


class TestDetectNewIssues:
    """新規 Issue 検知のテスト."""

    async def test_detect_new_issue_without_phase_label(self) -> None:
        """ai-agent ラベルあり & phase:* なしの Issue が検知される."""
        client = _make_client()
        issue = _make_issue(number=42, labels=["ai-agent"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 1
        assert result[0].number == 42

    async def test_detect_new_issue_excludes_phase_labeled(self) -> None:
        """phase:* ラベル付きの Issue は検知されない."""
        client = _make_client()
        issue = _make_issue(
            number=42, labels=["ai-agent", "phase:hearing"]
        )
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_hearing_replies
# ---------------------------------------------------------------------------


class TestDetectHearingReplies:
    """ヒアリング回答検知のテスト."""

    async def test_detect_hearing_reply_from_human(self) -> None:
        """人間のコメントがヒアリング回答として検知される."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:hearing"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        human_comment = _make_comment(
            comment_id=10, body="回答です", user_type="User"
        )
        client.list_comments = AsyncMock(return_value=[human_comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 1
        assert result[0].body == "回答です"

    async def test_detect_hearing_reply_excludes_bot(self) -> None:
        """Bot コメントはヒアリング回答として検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:hearing"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(
            comment_id=10, body="bot response", user_type="Bot"
        )
        client.list_comments = AsyncMock(return_value=[bot_comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_hearing_timeouts
# ---------------------------------------------------------------------------


class TestDetectHearingTimeouts:
    """ヒアリングタイムアウト検知のテスト."""

    async def test_detect_hearing_timeout(self) -> None:
        """24 時間無応答の Issue が HEARING_TIMEOUT として検知される."""
        client = _make_client()
        old_time = datetime.now(UTC) - timedelta(hours=25)
        issue = _make_issue(
            number=1,
            labels=["ai-agent", "phase:hearing"],
            updated_at=old_time,
        )
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am,
            repos=[repo],
            interval_sec=60,
            hearing_timeout_hours=24,
        )

        result = await poller._detect_hearing_timeouts(client, repo)
        assert len(result) == 1

    async def test_no_timeout_for_recent_issue(self) -> None:
        """最近更新された Issue はタイムアウトしない."""
        client = _make_client()
        recent_time = datetime.now(UTC) - timedelta(hours=1)
        issue = _make_issue(
            number=1,
            labels=["ai-agent", "phase:hearing"],
            updated_at=recent_time,
        )
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am,
            repos=[repo],
            interval_sec=60,
            hearing_timeout_hours=24,
        )

        result = await poller._detect_hearing_timeouts(client, repo)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_plan_reactions
# ---------------------------------------------------------------------------


class TestDetectPlanReactions:
    """方針承認リアクション検知のテスト."""

    async def test_detect_thumbsup_reaction(self) -> None:
        """方針コメントへの thumbsup が検知される."""
        client = _make_client()
        issue = _make_issue(
            number=1, labels=["ai-agent", "phase:plan-review"]
        )
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(
            comment_id=100, body="方針提案", user_type="Bot"
        )
        client.list_comments = AsyncMock(return_value=[bot_comment])

        thumbsup = _make_reaction(content="+1")
        client.get_reactions = AsyncMock(return_value=[thumbsup])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 1

    async def test_no_reaction_detected_without_thumbsup(self) -> None:
        """thumbsup 以外のリアクションでは検知されない."""
        client = _make_client()
        issue = _make_issue(
            number=1, labels=["ai-agent", "phase:plan-review"]
        )
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(
            comment_id=100, body="方針提案", user_type="Bot"
        )
        client.list_comments = AsyncMock(return_value=[bot_comment])

        heart = _make_reaction(content="heart")
        client.get_reactions = AsyncMock(return_value=[heart])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_ci_results
# ---------------------------------------------------------------------------


class TestDetectCIResults:
    """CI 結果検知のテスト."""

    async def test_detect_ci_failure(self) -> None:
        """CI 失敗が検知される."""
        client = _make_client()
        issue = _make_issue(
            number=1, labels=["ai-agent", "phase:implement"]
        )
        # First call (implement) returns issue, second call (ci-fix) returns empty
        client.get_issues_with_label = AsyncMock(
            side_effect=[[issue], []]
        )

        pr = MagicMock()
        pr.number = 10
        pr.body = "Fixes #1"
        pr.title = "feat: implement"
        pr.head = MagicMock()
        pr.head.ref = "feature/issue-1"
        client.list_pull_requests = AsyncMock(return_value=[pr])

        client.get_check_runs = AsyncMock(
            return_value=[
                {"name": "test", "status": "completed", "conclusion": "failure"}
            ]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_ci_results(client, repo)
        assert len(result) == 1
        assert result[0].type == EventType.CI_RESULT
        assert result[0].extra is not None
        assert result[0].extra["ci_status"] == "failure"

    async def test_detect_ci_success(self) -> None:
        """CI 成功が検知される."""
        client = _make_client()
        issue = _make_issue(
            number=1, labels=["ai-agent", "phase:implement"]
        )
        # First call (implement) returns issue, second call (ci-fix) returns empty
        client.get_issues_with_label = AsyncMock(
            side_effect=[[issue], []]
        )

        pr = MagicMock()
        pr.number = 10
        pr.body = "Fixes #1"
        pr.title = "feat: implement"
        pr.head = MagicMock()
        pr.head.ref = "feature/issue-1"
        client.list_pull_requests = AsyncMock(return_value=[pr])

        client.get_check_runs = AsyncMock(
            return_value=[
                {"name": "test", "status": "completed", "conclusion": "success"}
            ]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        result = await poller._detect_ci_results(client, repo)
        assert len(result) == 1
        assert result[0].extra is not None
        assert result[0].extra["ci_status"] == "success"


# ---------------------------------------------------------------------------
# Tests: _poll_repo integration
# ---------------------------------------------------------------------------


class TestPollRepo:
    """_poll_repo の統合テスト."""

    async def test_poll_repo_returns_new_issue_events(self) -> None:
        """_poll_repo が新規 Issue イベントを返す."""
        client = _make_client()
        issue = _make_issue(number=42, labels=["ai-agent"])
        # First call returns the new issue; rest return empty
        # Detection methods call get_issues_with_label:
        # new_issues(1) + hearing_replies(1) + hearing_timeouts(1) +
        # plan_reactions(1) + plan_comments(1) + pr_events(2) +
        # ci_results(2) + split_events(1) = 10 calls
        client.get_issues_with_label = AsyncMock(
            side_effect=[[issue], [], [], [], [], [], [], [], [], []]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        events = await poller._poll_repo(repo)
        new_issue_events = [
            e for e in events if e.type == EventType.NEW_ISSUE
        ]
        assert len(new_issue_events) == 1
        assert new_issue_events[0].issue.number == 42

    async def test_poll_error_is_caught_in_start(self) -> None:
        """ポーリング中のエラーが start で処理される."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am, repos=[repo], interval_sec=60
        )

        # _poll_repo should raise, which is caught in start()
        with pytest.raises(RuntimeError, match="API error"):
            await poller._poll_repo(repo)


# ---------------------------------------------------------------------------
# Tests: _has_phase_label static method
# ---------------------------------------------------------------------------


class TestHasPhaseLabel:
    """_has_phase_label の単体テスト."""

    def test_no_phase_label(self) -> None:
        """phase: ラベルがなければ False."""
        issue = _make_issue(labels=["ai-agent", "bug"])
        assert GitHubPoller._has_phase_label(issue) is False

    def test_has_phase_label(self) -> None:
        """phase: ラベルがあれば True."""
        issue = _make_issue(labels=["ai-agent", "phase:hearing"])
        assert GitHubPoller._has_phase_label(issue) is True
