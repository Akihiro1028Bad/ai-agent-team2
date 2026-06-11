"""GitHubPoller のユニットテスト."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.github.client import RateLimitStatus
from ai_agent_orchestrator.models import EventType
from ai_agent_orchestrator.poller.github_poller import GitHubPoller, _BoundedSet

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
    # 承認者許可リスト (#102)。空なら owner ("org") のみが承認者
    repo.approvers = []
    return repo


def _make_issue(
    number: int = 1,
    labels: list[str] | None = None,
    updated_at: datetime | None = None,
    is_pull_request: bool = False,
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
    if is_pull_request:
        issue.pull_request = MagicMock()
    else:
        issue.pull_request = None
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


def _make_reaction(content: str = "+1", login: str = "org") -> MagicMock:
    """テスト用 Reaction モック.

    login の既定は owner ("org") = 既定の承認者 (#102)。
    """
    reaction = MagicMock()
    reaction.content = content
    reaction.user = MagicMock()
    reaction.user.login = login
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
    # デフォルトはレート制限に余裕がある状態
    client.get_rate_limit = AsyncMock(return_value=RateLimitStatus(remaining=5000, limit=5000, reset=0))
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
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 1
        assert result[0].number == 42

    async def test_detect_new_issue_excludes_phase_labeled(self) -> None:
        """phase:* ラベル付きの Issue は検知されない."""
        client = _make_client()
        issue = _make_issue(number=42, labels=["ai-agent", "phase:hearing"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 0

    async def test_detect_new_issue_not_re_detected_on_second_poll(self) -> None:
        """BUG #1: 同じ Issue が2回目のポーリングで再検知されない."""
        client = _make_client()
        issue = _make_issue(number=42, labels=["ai-agent"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        # First poll detects the issue
        result1 = await poller._detect_new_issues(client, repo)
        assert len(result1) == 1

        # Second poll should NOT re-detect the same issue
        result2 = await poller._detect_new_issues(client, repo)
        assert len(result2) == 0

    async def test_detect_new_issue_excludes_pull_requests(self) -> None:
        """BUG #2: PR は新規 Issue として検知されない."""
        client = _make_client()
        pr_as_issue = _make_issue(number=99, labels=["ai-agent"], is_pull_request=True)
        real_issue = _make_issue(number=100, labels=["ai-agent"])
        client.get_issues_with_label = AsyncMock(return_value=[pr_as_issue, real_issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 1
        assert result[0].number == 100

    async def test_multiple_new_issues_detected(self) -> None:
        """複数の新規 Issue が一度に検知される."""
        client = _make_client()
        issue1 = _make_issue(number=1, labels=["ai-agent"])
        issue2 = _make_issue(number=2, labels=["ai-agent"])
        client.get_issues_with_label = AsyncMock(return_value=[issue1, issue2])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_new_issues(client, repo)
        assert len(result) == 2
        assert {r.number for r in result} == {1, 2}


# ---------------------------------------------------------------------------
# Tests: 検出経路の DEBUG ログ
# ---------------------------------------------------------------------------


class TestDetectionLogging:
    """検出経路 (poller) の DEBUG ログのテスト.

    「なぜ反応した/しなかったか」を追えることを担保する。
    """

    async def test_logs_fetched_count(self, caplog: pytest.LogCaptureFixture) -> None:
        """取得した Issue 件数を DEBUG ログに出す."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(
            return_value=[_make_issue(number=1, labels=["ai-agent"]), _make_issue(number=2, labels=["ai-agent"])]
        )
        repo = _make_repo()
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.github_poller"):
            await poller._detect_new_issues(client, repo)

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "fetched 2" in debug_text

    async def test_logs_detected_count(self, caplog: pytest.LogCaptureFixture) -> None:
        """検知した新規 Issue 件数を DEBUG ログに出す."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(return_value=[_make_issue(number=42, labels=["ai-agent"])])
        repo = _make_repo()
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.github_poller"):
            await poller._detect_new_issues(client, repo)

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "1 new" in debug_text
        assert "42" in debug_text

    async def test_logs_skip_phase_label(self, caplog: pytest.LogCaptureFixture) -> None:
        """phase ラベルでスキップした理由を DEBUG ログに出す."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(
            return_value=[_make_issue(number=42, labels=["ai-agent", "phase:hearing"])]
        )
        repo = _make_repo()
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.github_poller"):
            await poller._detect_new_issues(client, repo)

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "42" in debug_text
        assert "phase" in debug_text.lower()

    async def test_logs_skip_already_seen(self, caplog: pytest.LogCaptureFixture) -> None:
        """既検知でスキップした理由を DEBUG ログに出す."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(return_value=[_make_issue(number=42, labels=["ai-agent"])])
        repo = _make_repo()
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        await poller._detect_new_issues(client, repo)  # 1回目で seen 登録
        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.github_poller"):
            await poller._detect_new_issues(client, repo)  # 2回目はスキップ

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "42" in debug_text
        assert "seen" in debug_text.lower()

    async def test_logs_skip_pull_request(self, caplog: pytest.LogCaptureFixture) -> None:
        """PR でスキップした理由を DEBUG ログに出す."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(
            return_value=[_make_issue(number=99, labels=["ai-agent"], is_pull_request=True)]
        )
        repo = _make_repo()
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.github_poller"):
            await poller._detect_new_issues(client, repo)

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "99" in debug_text
        assert "pull request" in debug_text.lower() or "pr" in debug_text.lower()


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

        human_comment = _make_comment(comment_id=10, body="回答です", user_type="User")
        client.list_comments = AsyncMock(return_value=[human_comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 1
        assert result[0].body == "回答です"

    async def test_detect_hearing_reply_excludes_bot(self) -> None:
        """Bot マーカー付きコメントはヒアリング回答として検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:hearing-wait"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(
            comment_id=10,
            body="bot response\n\n<!-- ai-agent-bot -->",
            user_type="User",
        )
        client.list_comments = AsyncMock(return_value=[bot_comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 0

    async def test_detect_hearing_replies_watches_hearing_wait_label(self):
        """hearing-wait ラベルの Issue を監視する."""
        client = _make_client()
        comment = _make_comment(101, "回答です", "User", issue_url="https://api.github.com/repos/o/r/issues/42")
        issue = _make_issue(42, labels=["ai-agent", "phase:hearing-wait"])
        client.get_issues_with_label = AsyncMock(
            side_effect=lambda repo, labels, **kw: [issue] if "hearing-wait" in labels else [],
        )
        client.list_comments = AsyncMock(return_value=[comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 1

        # Verify the label used for lookup contains hearing-wait
        client.get_issues_with_label.assert_called()
        call_labels = client.get_issues_with_label.call_args[0][1]
        assert "hearing-wait" in call_labels

    async def test_hearing_reply_not_re_detected(self) -> None:
        """BUG #4: 同じヒアリング回答が2回目のポーリングで再検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:hearing"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        human_comment = _make_comment(comment_id=10, body="回答です", user_type="User")
        client.list_comments = AsyncMock(return_value=[human_comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result1 = await poller._detect_hearing_replies(client, repo, None)
        assert len(result1) == 1

        result2 = await poller._detect_hearing_replies(client, repo, None)
        assert len(result2) == 0


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

    async def test_hearing_timeout_not_re_detected(self) -> None:
        """BUG #4: 同じタイムアウトが2回目のポーリングで再検知されない."""
        client = _make_client()
        old_time = datetime.now(UTC) - timedelta(hours=25)
        issue = _make_issue(number=1, labels=["ai-agent", "phase:hearing"], updated_at=old_time)
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(
            account_manager=am,
            repos=[repo],
            interval_sec=60,
            hearing_timeout_hours=24,
        )

        result1 = await poller._detect_hearing_timeouts(client, repo)
        assert len(result1) == 1

        result2 = await poller._detect_hearing_timeouts(client, repo)
        assert len(result2) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_plan_reactions
# ---------------------------------------------------------------------------


class TestDetectPlanReactions:
    """方針承認リアクション検知のテスト."""

    async def test_detect_thumbsup_reaction(self) -> None:
        """方針コメントへの thumbsup が検知される."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:plan-review"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(comment_id=100, body="方針提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])

        thumbsup = _make_reaction(content="+1")
        client.get_reactions = AsyncMock(return_value=[thumbsup])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 1

    async def test_no_reaction_detected_without_thumbsup(self) -> None:
        """thumbsup 以外のリアクションでは検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:plan-review"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(comment_id=100, body="方針提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])

        heart = _make_reaction(content="heart")
        client.get_reactions = AsyncMock(return_value=[heart])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 0

    async def test_unauthorized_thumbsup_not_detected(self) -> None:
        """許可外ユーザーの 👍 は承認として検知されない (#102)."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:plan-review"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])
        bot_comment = _make_comment(comment_id=100, body="方針提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])
        # owner ("org") 以外のユーザーの 👍
        client.get_reactions = AsyncMock(return_value=[_make_reaction(content="+1", login="mallory")])

        repo = _make_repo()  # approvers=[] → owner "org" のみ
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 0

    async def test_configured_approver_thumbsup_detected(self) -> None:
        """approvers に明示された非 owner ユーザーの 👍 は承認として検知される (#102)."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:plan-review"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])
        bot_comment = _make_comment(comment_id=100, body="方針提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])
        client.get_reactions = AsyncMock(return_value=[_make_reaction(content="+1", login="reviewer1")])

        repo = _make_repo()
        repo.approvers = ["reviewer1"]
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)

        result = await poller._detect_plan_reactions(client, repo, None)
        assert len(result) == 1

    async def test_plan_reaction_not_re_detected(self) -> None:
        """BUG #3: 同じリアクションが2回目のポーリングで再検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:plan-review"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(comment_id=100, body="方針提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])

        thumbsup = _make_reaction(content="+1")
        client.get_reactions = AsyncMock(return_value=[thumbsup])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result1 = await poller._detect_plan_reactions(client, repo, None)
        assert len(result1) == 1

        result2 = await poller._detect_plan_reactions(client, repo, None)
        assert len(result2) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_ci_results
# ---------------------------------------------------------------------------


class TestDetectCIResults:
    """CI 結果検知のテスト."""

    async def test_detect_ci_failure(self) -> None:
        """CI 失敗が検知される."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:implement"])
        # implement returns issue, ci-fix and impl-review return empty
        client.get_issues_with_label = AsyncMock(side_effect=[[issue], [], []])

        pr = MagicMock()
        pr.number = 10
        pr.body = "Fixes #1"
        pr.title = "feat: implement"
        pr.head = MagicMock()
        pr.head.ref = "feature/issue-1"
        client.list_pull_requests = AsyncMock(return_value=[pr])

        client.get_check_runs = AsyncMock(
            return_value=[{"name": "test", "status": "completed", "conclusion": "failure"}]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_ci_results(client, repo)
        assert len(result) == 1
        assert result[0].type == EventType.CI_RESULT
        assert result[0].extra is not None
        assert result[0].extra["ci_status"] == "failure"

    async def test_detect_ci_success(self) -> None:
        """CI 成功が検知される."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:implement"])
        # implement returns issue, ci-fix and impl-review return empty
        client.get_issues_with_label = AsyncMock(side_effect=[[issue], [], []])

        pr = MagicMock()
        pr.number = 10
        pr.body = "Fixes #1"
        pr.title = "feat: implement"
        pr.head = MagicMock()
        pr.head.ref = "feature/issue-1"
        client.list_pull_requests = AsyncMock(return_value=[pr])

        client.get_check_runs = AsyncMock(
            return_value=[{"name": "test", "status": "completed", "conclusion": "success"}]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_ci_results(client, repo)
        assert len(result) == 1
        assert result[0].extra is not None
        assert result[0].extra["ci_status"] == "success"

    async def test_ci_result_not_re_detected(self) -> None:
        """BUG #4: 同じ CI 結果が2回目のポーリングで再検知されない."""
        client = _make_client()
        issue = _make_issue(number=1, labels=["ai-agent", "phase:implement"])
        client.get_issues_with_label = AsyncMock(side_effect=[[issue], [], [], [issue], [], []])

        pr = MagicMock()
        pr.number = 10
        pr.body = "Fixes #1"
        pr.title = "feat: implement"
        pr.head = MagicMock()
        pr.head.ref = "feature/issue-1"
        client.list_pull_requests = AsyncMock(return_value=[pr])

        client.get_check_runs = AsyncMock(
            return_value=[{"name": "test", "status": "completed", "conclusion": "success"}]
        )

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result1 = await poller._detect_ci_results(client, repo)
        assert len(result1) == 1

        result2 = await poller._detect_ci_results(client, repo)
        assert len(result2) == 0


# ---------------------------------------------------------------------------
# Tests: _detect_split_events
# ---------------------------------------------------------------------------


class TestDetectSplitEvents:
    """分割イベント検知のテスト."""

    async def test_split_reaction_not_re_detected(self) -> None:
        """BUG #3: 同じ分割承認リアクションが2回目で再検知されない."""
        client = _make_client()
        issue = _make_issue(number=5, labels=["ai-agent", "phase:split-proposal"])
        client.get_issues_with_label = AsyncMock(return_value=[issue])

        bot_comment = _make_comment(comment_id=200, body="<!-- ai-agent-bot -->分割提案", user_type="Bot")
        client.list_comments = AsyncMock(return_value=[bot_comment])

        thumbsup = _make_reaction(content="+1")
        client.get_reactions = AsyncMock(return_value=[thumbsup])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result1 = await poller._detect_split_events(client, repo, None)
        approved1 = [e for e in result1 if e.type == EventType.SPLIT_APPROVED]
        assert len(approved1) == 1

        result2 = await poller._detect_split_events(client, repo, None)
        approved2 = [e for e in result2 if e.type == EventType.SPLIT_APPROVED]
        assert len(approved2) == 0


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
        client.get_issues_with_label = AsyncMock(side_effect=[[issue], [], [], [], [], [], [], [], [], []])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        events = await poller._poll_repo(repo)
        new_issue_events = [e for e in events if e.type == EventType.NEW_ISSUE]
        assert len(new_issue_events) == 1
        assert new_issue_events[0].issue.number == 42

    async def test_poll_repo_no_duplicate_new_issues_across_polls(self) -> None:
        """BUG #1: _poll_repo を2回呼んでも同じ Issue は再検知されない."""
        client = _make_client()
        issue = _make_issue(number=42, labels=["ai-agent"])
        # 11 calls per poll, 2 polls = 22 calls
        side_effects = [
            [issue],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [issue],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
        ]
        client.get_issues_with_label = AsyncMock(side_effect=side_effects)

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        events1 = await poller._poll_repo(repo)
        new1 = [e for e in events1 if e.type == EventType.NEW_ISSUE]
        assert len(new1) == 1

        events2 = await poller._poll_repo(repo)
        new2 = [e for e in events2 if e.type == EventType.NEW_ISSUE]
        assert len(new2) == 0

    async def test_poll_error_is_caught_in_start(self) -> None:
        """ポーリング中のエラーが start で処理される."""
        client = _make_client()
        client.get_issues_with_label = AsyncMock(side_effect=RuntimeError("API error"))

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

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


# ---------------------------------------------------------------------------
# _trim_ci_logs
# ---------------------------------------------------------------------------


class TestTrimCiLogs:
    """_trim_ci_logs のユニットテスト."""

    def test_short_log_returned_unchanged(self) -> None:
        """max_chars 以下のログはそのまま返す."""
        from ai_agent_orchestrator.poller.github_poller import _trim_ci_logs

        log = "line1\nline2\nerror here\n"
        assert _trim_ci_logs(log, max_chars=10000) == log

    def test_long_log_trimmed_with_error_lines(self) -> None:
        """エラーキーワードを含む行が優先的に保持される."""
        from ai_agent_orchestrator.poller.github_poller import _trim_ci_logs

        # 大量のダミー行 + エラー行
        filler = ["normal line " * 10] * 2000
        filler.insert(1000, "Error: something went wrong")
        log = "\n".join(filler)
        result = _trim_ci_logs(log, max_chars=5000)
        assert "Error: something went wrong" in result
        assert len(result) <= 5000 + len("\n...(truncated)")

    def test_header_added_when_trimmed(self) -> None:
        """トリミング時にヘッダーが付与される."""
        from ai_agent_orchestrator.poller.github_poller import _trim_ci_logs

        filler = ["x" * 100] * 500
        filler[250] = "ERROR: critical failure"
        log = "\n".join(filler)
        result = _trim_ci_logs(log, max_chars=5000)
        assert result.startswith("[CI ログ: 全")

    def test_empty_log_returned_unchanged(self) -> None:
        """空のログはそのまま返す."""
        from ai_agent_orchestrator.poller.github_poller import _trim_ci_logs

        assert _trim_ci_logs("") == ""


# ---------------------------------------------------------------------------
# _detect_ci_results — ci-fix phase duplicate detection
# ---------------------------------------------------------------------------


class TestDetectCiResultsDuplicate:
    """_detect_ci_results の ci-fix フェーズ重複検知テスト."""

    def _make_poller(self) -> GitHubPoller:
        am = MagicMock()
        return GitHubPoller(account_manager=am, repos=[])

    async def test_ci_fix_allows_duplicate_detection(self) -> None:
        """ci-fix フェーズでは同じ CI failure を複数回検知できる."""
        poller = self._make_poller()
        repo = _make_repo()
        issue = _make_issue(number=99, labels=["ai-agent", "phase:ci-fix"])
        client = AsyncMock()

        # ci-fix ラベルの Issue を返す
        client.get_issues_with_label = AsyncMock(
            side_effect=[
                [issue],  # ci-fix
                [],  # impl-review
            ]
        )
        client.list_pull_requests = AsyncMock(return_value=[])

        async def fake_check_status(c: object, r: object, i: object) -> str:
            return "failure"

        async def fake_get_logs(c: object, r: object, i: object) -> str:
            return "some error log"

        poller._check_ci_status = fake_check_status  # type: ignore[method-assign]
        poller._get_ci_logs = fake_get_logs  # type: ignore[method-assign]

        # 1回目
        events1 = await poller._detect_ci_results(client, repo)  # type: ignore[arg-type]
        assert len(events1) == 1

        # 2回目: ci-fix は _seen_events を無視するため再検知される
        client.get_issues_with_label = AsyncMock(
            side_effect=[
                [issue],
                [],
            ]
        )
        events2 = await poller._detect_ci_results(client, repo)  # type: ignore[arg-type]
        assert len(events2) == 1

    async def test_impl_review_deduplicates(self) -> None:
        """impl-review フェーズでは同じ CI failure を重複検知しない."""
        poller = self._make_poller()
        repo = _make_repo()
        issue = _make_issue(number=88, labels=["ai-agent", "phase:impl-review"])
        client = AsyncMock()

        client.get_issues_with_label = AsyncMock(
            side_effect=[
                [],  # ci-fix
                [issue],  # impl-review
            ]
        )
        client.list_pull_requests = AsyncMock(return_value=[])

        async def fake_check_status(c: object, r: object, i: object) -> str:
            return "failure"

        async def fake_get_logs(c: object, r: object, i: object) -> str:
            return "some error log"

        poller._check_ci_status = fake_check_status  # type: ignore[method-assign]
        poller._get_ci_logs = fake_get_logs  # type: ignore[method-assign]

        # 1回目
        events1 = await poller._detect_ci_results(client, repo)  # type: ignore[arg-type]
        assert len(events1) == 1

        # 2回目: impl-review は _seen_events で重複排除される
        client.get_issues_with_label = AsyncMock(
            side_effect=[
                [],
                [issue],
            ]
        )
        events2 = await poller._detect_ci_results(client, repo)  # type: ignore[arg-type]
        assert len(events2) == 0


# ---------------------------------------------------------------------------
# Tests: _BoundedSet (再検知ストーム防止)
# ---------------------------------------------------------------------------


class TestBoundedSet:
    """_BoundedSet の挙動を検証する."""

    def test_add_and_contains(self) -> None:
        """追加した要素が含まれる."""
        s = _BoundedSet(max_size=3)
        s.add("a")
        assert "a" in s
        assert "b" not in s

    def test_evicts_oldest_when_over_capacity(self) -> None:
        """上限超過時に最古の要素が削除される."""
        s = _BoundedSet(max_size=2)
        s.add("a")
        s.add("b")
        s.add("c")  # "a" が押し出される
        assert "a" not in s
        assert "b" in s
        assert "c" in s
        assert len(s) == 2

    def test_re_add_refreshes_recency(self) -> None:
        """既存要素の再追加で最新扱いになり、削除対象から外れる."""
        s = _BoundedSet(max_size=2)
        s.add("a")
        s.add("b")
        s.add("a")  # "a" を最新へ
        s.add("c")  # 最古の "b" が押し出される
        assert "a" in s
        assert "b" not in s
        assert "c" in s


# ---------------------------------------------------------------------------
# Tests: PR 一覧キャッシュ (重複 list_pull_requests 削減)
# ---------------------------------------------------------------------------


class TestListPrsCached:
    """_list_prs_cached のキャッシュ挙動を検証する."""

    def _make_poller(self, client: AsyncMock) -> GitHubPoller:
        return GitHubPoller(account_manager=_make_account_manager(client), repos=[_make_repo()], interval_sec=60)

    async def test_caches_per_state(self) -> None:
        """同一 state は1回だけ API を呼び、結果を使い回す."""
        client = _make_client()
        client.list_pull_requests = AsyncMock(return_value=[])
        poller = self._make_poller(client)
        repo = _make_repo()

        await poller._list_prs_cached(client, repo, "open")  # type: ignore[arg-type]
        await poller._list_prs_cached(client, repo, "open")  # type: ignore[arg-type]
        await poller._list_prs_cached(client, repo, "closed")  # type: ignore[arg-type]

        # open 1回 + closed 1回 = 2回のみ
        assert client.list_pull_requests.call_count == 2

    async def test_cache_cleared_each_poll_cycle(self) -> None:
        """_poll_repo の先頭でキャッシュがクリアされ、次サイクルで再取得される."""
        client = _make_client()
        poller = self._make_poller(client)
        repo = _make_repo()

        await poller._list_prs_cached(client, repo, "open")  # type: ignore[arg-type]
        assert client.list_pull_requests.call_count == 1

        # ポーリングサイクルを回すとキャッシュがクリアされる
        await poller._poll_repo(repo)  # type: ignore[arg-type]
        await poller._list_prs_cached(client, repo, "open")  # type: ignore[arg-type]
        # _poll_repo 内でも open が取得されるため call_count は増えるが、
        # 重要なのはキャッシュがクリアされ再取得されていること
        assert ("org/app", "open") in poller._pr_cache


# ---------------------------------------------------------------------------
# Tests: レート制限ガード
# ---------------------------------------------------------------------------


class TestRateLimitGuard:
    """レート制限残量に応じたポーリングスキップを検証する."""

    async def test_skips_poll_when_rate_limit_low(self) -> None:
        """残量が閾値未満ならポーリングをスキップし検知を行わない."""
        client = _make_client()
        client.get_rate_limit = AsyncMock(return_value=RateLimitStatus(remaining=10, limit=5000, reset=0))
        poller = GitHubPoller(
            account_manager=_make_account_manager(client),
            repos=[_make_repo()],
            interval_sec=60,
            min_rate_limit_remaining=200,
        )
        repo = _make_repo()

        events = await poller._poll_repo(repo)  # type: ignore[arg-type]

        assert events == []
        client.get_issues_with_label.assert_not_called()

    async def test_polls_normally_when_rate_limit_ok(self) -> None:
        """残量が十分なら通常通り検知処理を行う."""
        client = _make_client()
        client.get_rate_limit = AsyncMock(return_value=RateLimitStatus(remaining=4000, limit=5000, reset=0))
        poller = GitHubPoller(
            account_manager=_make_account_manager(client),
            repos=[_make_repo()],
            interval_sec=60,
            min_rate_limit_remaining=200,
        )
        repo = _make_repo()

        await poller._poll_repo(repo)  # type: ignore[arg-type]

        # 検知メソッドが呼ばれている
        assert client.get_issues_with_label.call_count > 0

    async def test_continues_when_rate_limit_check_fails(self) -> None:
        """レート制限取得に失敗しても続行する."""
        client = _make_client()
        client.get_rate_limit = AsyncMock(side_effect=Exception("network error"))
        poller = GitHubPoller(
            account_manager=_make_account_manager(client),
            repos=[_make_repo()],
            interval_sec=60,
        )
        repo = _make_repo()

        await poller._poll_repo(repo)  # type: ignore[arg-type]

        assert client.get_issues_with_label.call_count > 0


# ---------------------------------------------------------------------------
# Tests: _detect_pr_events (インラインのみレビューの検知 / U2)
# ---------------------------------------------------------------------------


class TestGetPrReviewsApproverVerification:
    """PR approve / LGTM の承認者検証 (#102)."""

    def _setup(self, reviews: list[dict[str, object]], approvers: list[str]) -> tuple[AsyncMock, MagicMock, object]:
        client = _make_client()
        pr = MagicMock()
        pr.number = 50
        pr.title = "設計: #5"
        pr.body = "Closes #5"
        pr.merged_at = None
        pr.merged = False
        pr.head = MagicMock(ref="feature/issue-5")
        client.list_pull_requests = AsyncMock(return_value=[pr])
        client.get_pr_reviews = AsyncMock(return_value=reviews)
        client.list_comments = AsyncMock(return_value=[])
        repo = _make_repo()
        repo.approvers = approvers
        poller = GitHubPoller(account_manager=_make_account_manager(client), repos=[repo], interval_sec=60)
        issue = _make_issue(number=5, labels=["ai-agent", "phase:design-review"])
        return client, repo, poller, issue  # type: ignore[return-value]

    async def test_authorized_approve_is_counted(self) -> None:
        reviews = [{"id": 1, "state": "APPROVED", "body": "", "user": {"login": "org"}, "submitted_at": ""}]
        client, repo, poller, issue = self._setup(reviews, [])  # owner "org"
        result = await poller._get_pr_reviews(client, repo, issue)
        assert any(r["state"] == "approved" for r in result)

    async def test_unauthorized_approve_is_ignored(self) -> None:
        """許可外ユーザーの approve は承認として扱われない (#102)."""
        reviews = [{"id": 1, "state": "APPROVED", "body": "", "user": {"login": "mallory"}, "submitted_at": ""}]
        client, repo, poller, issue = self._setup(reviews, [])  # owner "org" のみ許可
        result = await poller._get_pr_reviews(client, repo, issue)
        assert all(r["state"] != "approved" for r in result)

    async def test_unauthorized_lgtm_review_is_ignored(self) -> None:
        """許可外ユーザーの LGTM レビューも無視される (#102)."""
        reviews = [{"id": 2, "state": "COMMENTED", "body": "LGTM", "user": {"login": "mallory"}, "submitted_at": ""}]
        client, repo, poller, issue = self._setup(reviews, [])
        result = await poller._get_pr_reviews(client, repo, issue)
        assert all(r["state"] != "approved" for r in result)


class TestDetectPrEventsInlineOnlyReview:
    """body 空の COMMENTED レビュー（インラインコメントのみ）の検知."""

    def _setup(
        self,
        reviews: list[dict[str, object]],
        review_comments: list[dict[str, object]],
    ) -> tuple[AsyncMock, MagicMock, GitHubPoller]:
        client = _make_client()
        impl_issue = _make_issue(number=131, labels=["ai-agent", "phase:impl-review"])
        # design-review(0件) → impl-review(1件) の順で呼ばれる
        client.get_issues_with_label = AsyncMock(side_effect=[[], [impl_issue]])
        pr = MagicMock()
        pr.number = 132
        pr.title = "修正: #131 テスト"
        pr.body = "Closes #131"
        pr.merged_at = None
        pr.merged = False
        pr.head = MagicMock(ref="feature/issue-131")
        client.list_pull_requests = AsyncMock(return_value=[pr])
        client.get_pr_reviews = AsyncMock(return_value=reviews)
        client.get_pr_review_comments = AsyncMock(return_value=review_comments)
        client.list_comments = AsyncMock(return_value=[])
        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)
        return client, repo, poller

    async def test_inline_only_review_is_detected(self) -> None:
        """body 空でもトップレベルのインラインコメントがあれば IMPL_PR_COMMENTED."""
        reviews = [{"id": 900, "state": "COMMENTED", "body": "", "submitted_at": "2026-06-10T09:00:00Z"}]
        comments = [
            {
                "id": 100,
                "body": "質問です: この実装の意図は？",
                "user": {"login": "alice"},
                "path": "a.py",
                "line": 3,
                "pull_request_review_id": 900,
                "in_reply_to_id": None,
            }
        ]
        client, repo, poller = self._setup(reviews, comments)

        events = await poller._detect_pr_events(client, repo, None)

        impl_events = [e for e in events if e.type == EventType.IMPL_PR_COMMENTED]
        assert len(impl_events) == 1
        assert impl_events[0].issue.number == 131

    async def test_reply_only_review_is_ignored(self) -> None:
        """返信（in_reply_to_id あり）だけのレビューは検知しない（bot 応答ループ防止）."""
        reviews = [{"id": 901, "state": "COMMENTED", "body": "", "submitted_at": "2026-06-10T09:01:00Z"}]
        comments = [
            {
                "id": 101,
                "body": "回答しました",
                "user": {"login": "bot"},
                "path": "a.py",
                "line": 3,
                "pull_request_review_id": 901,
                "in_reply_to_id": 100,
            }
        ]
        client, repo, poller = self._setup(reviews, comments)

        events = await poller._detect_pr_events(client, repo, None)

        assert [e for e in events if e.type == EventType.IMPL_PR_COMMENTED] == []

    async def test_body_review_still_detected_without_extra_fetch(self) -> None:
        """本文ありレビューは従来通り検知される（インライン照会は不要）."""
        reviews = [{"id": 902, "state": "COMMENTED", "body": "デバウンスを入れてください", "submitted_at": ""}]
        client, repo, poller = self._setup(reviews, [])

        events = await poller._detect_pr_events(client, repo, None)

        impl_events = [e for e in events if e.type == EventType.IMPL_PR_COMMENTED]
        assert len(impl_events) == 1

    async def test_review_id_in_extra_is_int_even_when_source_is_str(self) -> None:
        """_get_pr_reviews は id を str で返すため、extra では int に正規化される (#103)."""
        reviews = [{"id": "4466060437", "state": "COMMENTED", "body": "本文の質問", "submitted_at": ""}]
        client, repo, poller = self._setup(reviews, [])

        events = await poller._detect_pr_events(client, repo, None)

        impl_events = [e for e in events if e.type == EventType.IMPL_PR_COMMENTED]
        assert len(impl_events) == 1
        assert impl_events[0].extra["review_id"] == 4466060437
        assert isinstance(impl_events[0].extra["review_id"], int)
