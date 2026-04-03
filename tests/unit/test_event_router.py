"""EventRouter のユニットテスト."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import EventType, Phase, PollEvent
from ai_agent_orchestrator.orchestrator.task_queue import Priority
from ai_agent_orchestrator.poller.event_router import EventRouter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sm() -> MagicMock:
    """StateMachineManager のモック.

    MagicMock ベースで、非同期メソッドのみ AsyncMock で上書きする。
    AsyncMock をベースにすると EventRouter.__init__ 内で同期メソッド
    register_transition_hook() を呼び出した際に unawaited coroutine 警告が発生するため。
    """
    sm = MagicMock()
    sm.transition = AsyncMock()
    sm.register_issue = MagicMock()
    sm.get_phase = MagicMock(return_value="plan-review")  # 同期メソッド
    sm.get_issue_type = MagicMock(return_value="bug")
    sm.set_issue_type = MagicMock()  # 同期メソッド
    sm.get_ci_retry_count = AsyncMock(return_value=0)
    sm.get_state = MagicMock(return_value=None)
    sm.register_transition_hook = MagicMock()
    return sm


@pytest.fixture
def mock_tq() -> AsyncMock:
    """TaskQueue のモック."""
    return AsyncMock()


@pytest.fixture
def router(mock_sm: AsyncMock, mock_tq: AsyncMock) -> EventRouter:
    """EventRouter インスタンス."""
    return EventRouter(state_machine=mock_sm, task_queue=mock_tq)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_repo() -> MagicMock:
    """テスト用の RepositoryConfig モック."""
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    return repo


def _make_event(
    event_type: str,
    issue_number: int = 1,
    **kwargs: object,
) -> PollEvent:
    """テスト用 PollEvent を作成する."""
    repo = _make_repo()
    issue = MagicMock()
    issue.number = issue_number
    return PollEvent(
        type=event_type,
        repo=repo,
        issue=issue,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests: NEW_ISSUE
# ---------------------------------------------------------------------------


class TestEventRouterNewIssue:
    """NEW_ISSUE イベントのテスト."""

    async def test_new_issue_registers_and_enqueues(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """NEW_ISSUE -> register_issue + TYPE_DETECTION エンキュー."""
        mock_sm.get_phase = MagicMock(side_effect=KeyError(42))  # 未登録 -> KeyError
        event = _make_event(EventType.NEW_ISSUE)
        await router.route(event)

        mock_sm.register_issue.assert_called_once()
        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase == "type-detection"


# ---------------------------------------------------------------------------
# Tests: PLAN_REACTION_ADDED
# ---------------------------------------------------------------------------


class TestEventRouterPlanReaction:
    """PLAN_REACTION_ADDED イベントのテスト."""

    async def test_bug_plan_reaction_routes_to_fix(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """Bug の thumbsup リアクション -> FIX へ遷移."""
        mock_sm.get_issue_type.return_value = "bug"
        event = _make_event(EventType.PLAN_REACTION_ADDED)
        await router.route(event)

        mock_sm.transition.assert_called_once()
        args = mock_sm.transition.call_args[0]
        assert args[1].value == "fix"


# ---------------------------------------------------------------------------
# Tests: PLAN_COMMENT_ADDED
# ---------------------------------------------------------------------------


class TestEventRouterPlanComment:
    """PLAN_COMMENT_ADDED イベントのテスト."""

    async def test_bug_plan_comment_routes_to_analysis(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """Bug の方針指摘 -> ANALYSIS へ遷移."""
        mock_sm.get_issue_type.return_value = "bug"
        comment = MagicMock(body="修正してください")
        event = _make_event(EventType.PLAN_COMMENT_ADDED, comment=comment)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "analysis"


# ---------------------------------------------------------------------------
# Tests: DESIGN_PR_APPROVED / DESIGN_PR_COMMENTED
# ---------------------------------------------------------------------------


class TestEventRouterDesignPR:
    """設計 PR イベントのテスト."""

    async def test_design_pr_approved_routes_to_planning(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """設計 PR approve -> PLANNING へ遷移."""
        mock_sm.get_phase.return_value = Phase.DESIGN_REVIEW
        event = _make_event(EventType.DESIGN_PR_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "planning"

    async def test_design_pr_commented_routes_to_design_revise(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """設計 PR コメント -> DESIGN_REVISE へ遷移."""
        mock_sm.get_phase.return_value = Phase.DESIGN_REVIEW
        event = _make_event(
            EventType.DESIGN_PR_COMMENTED,
            extra={"comments": "要修正"},
        )
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "design-revise"


# ---------------------------------------------------------------------------
# Tests: IMPL_PR_APPROVED / IMPL_PR_COMMENTED
# ---------------------------------------------------------------------------


class TestEventRouterImplPR:
    """実装 PR イベントのテスト."""

    async def test_impl_pr_approved_does_not_route_to_done(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """実装 PR approve -> DONE に遷移しない (マージで完了)."""
        event = _make_event(EventType.IMPL_PR_APPROVED)
        await router.route(event)

        mock_sm.transition.assert_not_called()

    async def test_impl_pr_merged_routes_to_done(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """実装 PR マージ -> DONE へ遷移."""
        event = _make_event(EventType.IMPL_PR_MERGED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "done"

    async def test_impl_pr_commented_routes_to_impl_revise(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """実装 PR コメント -> IMPL_REVISE へ遷移."""
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "要修正"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "impl-revise"
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.priority == Priority.CRITICAL


# ---------------------------------------------------------------------------
# Tests: CI_RESULT
# ---------------------------------------------------------------------------


class TestEventRouterCIResult:
    """CI_RESULT イベントのテスト."""

    async def test_ci_failure_within_limit_routes_to_ci_fix(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """CI 失敗 (3回以内) -> CI_FIX へ遷移."""
        mock_sm.get_phase.return_value = Phase.IMPL_REVIEW
        mock_sm.get_ci_retry_count.return_value = 1
        event = _make_event(
            EventType.CI_RESULT,
            extra={
                "ci_status": "failure",
                "ci_logs": "Error: test failed",
            },
        )
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "ci-fix"

    async def test_ci_failure_exceeds_limit_routes_to_suspended(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """CI 失敗 (3回超過) -> SUSPENDED へ遷移."""
        mock_sm.get_phase.return_value = Phase.IMPL_REVIEW
        mock_sm.get_ci_retry_count.return_value = 3
        event = _make_event(
            EventType.CI_RESULT,
            extra={"ci_status": "failure", "ci_logs": "Error"},
        )
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "suspended"

    async def test_ci_success_routes_to_impl_review(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """CI 成功 -> IMPL_REVIEW に遷移 (エンキューなし)."""
        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "impl-review"
        mock_tq.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: SPLIT_APPROVED / SPLIT_MODIFIED
# ---------------------------------------------------------------------------


class TestEventRouterSplit:
    """分割イベントのテスト."""

    async def test_split_approved_routes_to_split_execute(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """分割承認 -> SPLIT_EXECUTE へ遷移."""
        mock_sm.get_phase.return_value = Phase.SPLIT_PROPOSAL
        event = _make_event(EventType.SPLIT_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "split-execute"

    async def test_split_modified_routes_to_hearing(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """分割修正指示 -> HEARING へ遷移."""
        comment = MagicMock(body="こう分割して")
        event = _make_event(EventType.SPLIT_MODIFIED, comment=comment)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "hearing"


# ---------------------------------------------------------------------------
# Tests: HEARING_TIMEOUT / ISSUE_COMMENT (hearing reply)
# ---------------------------------------------------------------------------


class TestEventRouterHearing:
    """ヒアリング関連イベントのテスト."""

    async def test_hearing_timeout_routes_to_suspended(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """ヒアリングタイムアウト -> SUSPENDED へ遷移."""
        event = _make_event(EventType.HEARING_TIMEOUT)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "suspended"

    async def test_hearing_reply_enqueues_continue(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """ヒアリング回答 -> hearing エンキュー (遷移なし)."""
        from ai_agent_orchestrator.models import Phase

        mock_sm.get_phase.return_value = Phase.HEARING
        comment = MagicMock()
        comment.body = "回答です"
        comment.issue_url = "https://api.github.com/repos/org/app/issues/1"
        event = PollEvent(
            type=EventType.ISSUE_COMMENT,
            repo=_make_repo(),
            comment=comment,
        )
        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_called_once()

    async def test_hearing_reply_resumes_suspended(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """SUSPENDED の Issue にヒアリング回答 -> HEARING に復帰してエンキュー."""
        from ai_agent_orchestrator.models import Phase

        mock_sm.get_phase.return_value = Phase.SUSPENDED
        comment = MagicMock()
        comment.body = "回答です"
        comment.issue_url = "https://api.github.com/repos/org/app/issues/1"
        event = PollEvent(
            type=EventType.ISSUE_COMMENT,
            repo=_make_repo(),
            comment=comment,
        )
        await router.route(event)

        mock_sm.transition.assert_called_once()
        args = mock_sm.transition.call_args[0]
        assert args[1] == Phase.HEARING
        mock_tq.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Unknown / Error events
# ---------------------------------------------------------------------------


class TestEventRouterError:
    """エラー/未知のイベントのテスト."""

    async def test_unknown_event_does_not_crash(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """未知のイベントタイプはクラッシュしない."""
        event = PollEvent(
            type="some_unknown_type",
            repo=_make_repo(),
        )
        await router.route(event)
        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()


class TestEventRouterHearingWait:
    """hearing-wait フェーズのイベントルーティングテスト."""

    @pytest.fixture
    def mock_sm(self):
        sm = MagicMock()
        sm.transition = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.HEARING_WAIT)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        return sm

    @pytest.fixture
    def mock_tq(self):
        tq = AsyncMock()
        return tq

    @pytest.fixture
    def router(self, mock_sm, mock_tq):
        return EventRouter(state_machine=mock_sm, task_queue=mock_tq)

    async def test_hearing_reply_from_hearing_wait_transitions_to_hearing(self, router, mock_sm, mock_tq):
        """hearing-wait 中にユーザーコメント → hearing に遷移."""
        comment = MagicMock()
        comment.issue_url = "https://api.github.com/repos/o/r/issues/42"
        comment.body = "回答です"
        event = PollEvent(
            type=EventType.ISSUE_COMMENT,
            repo=_make_repo(),
            comment=comment,
        )

        await router.route(event)

        mock_sm.transition.assert_called_once()
        assert mock_sm.transition.call_args[0][1] == Phase.HEARING
        mock_tq.enqueue.assert_called_once()

    async def test_hearing_reply_during_hearing_enqueues_without_transition(self, router, mock_sm, mock_tq):
        """hearing 実行中にユーザーコメント → 遷移せずエンキューのみ."""
        mock_sm.get_phase.return_value = Phase.HEARING

        comment = MagicMock()
        comment.issue_url = "https://api.github.com/repos/o/r/issues/42"
        comment.body = "回答です"
        event = PollEvent(
            type=EventType.ISSUE_COMMENT,
            repo=_make_repo(),
            comment=comment,
        )

        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: ボットコメントフィルタ (TC-63-02, TC-63-03, TC-63-05)
# ---------------------------------------------------------------------------


class TestBotCommentFiltering:
    """TC-63-02, TC-63-03, TC-63-05: ボットコメントが IMPL_REVISE/DESIGN_REVISE をトリガーしないことを確認."""

    @pytest.fixture
    def mock_sm(self) -> MagicMock:
        # AsyncMock() を使うと register_transition_hook() が AsyncMock になり
        # EventRouter.__init__ 内の同期呼び出しで unawaited coroutine 警告が出るため
        # MagicMock() を使い、非同期メソッドだけ AsyncMock で上書きする
        sm = MagicMock()
        sm.transition = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.IMPL_REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        sm.get_state = MagicMock(return_value=None)
        sm.register_transition_hook = MagicMock()
        return sm

    @pytest.fixture
    def mock_tq(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def router(self, mock_sm: MagicMock, mock_tq: AsyncMock) -> EventRouter:
        return EventRouter(state_machine=mock_sm, task_queue=mock_tq)

    async def test_bot_impl_pr_commented_not_routed_to_impl_revise(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """TC-63-02: github-actions[bot] の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーしないこと."""
        comment = MagicMock()
        comment.user = MagicMock()
        comment.user.login = "github-actions[bot]"
        event = _make_event(EventType.IMPL_PR_COMMENTED, comment=comment)

        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()

    async def test_human_impl_pr_commented_routes_to_impl_revise(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """TC-63-03: 人間の IMPL_PR_COMMENTED は IMPL_REVISE 遷移をトリガーすること (既存動作の維持確認)."""
        comment = MagicMock()
        comment.user = MagicMock()
        comment.user.login = "human-reviewer"
        event = _make_event(
            EventType.IMPL_PR_COMMENTED,
            comment=comment,
            extra={"comments": "要修正"},
        )

        await router.route(event)

        mock_sm.transition.assert_called_once()
        args = mock_sm.transition.call_args[0]
        assert args[1].value == "impl-revise"

    async def test_bot_design_pr_commented_not_routed_to_design_revise(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """TC-63-05: github-actions[bot] の DESIGN_PR_COMMENTED は DESIGN_REVISE 遷移をトリガーしないこと."""
        mock_sm.get_phase.return_value = Phase.DESIGN_REVIEW
        comment = MagicMock()
        comment.user = MagicMock()
        comment.user.login = "github-actions[bot]"
        event = _make_event(EventType.DESIGN_PR_COMMENTED, comment=comment)

        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()

    async def test_claude_bot_impl_pr_commented_also_ignored(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """claude[bot] の IMPL_PR_COMMENTED も IMPL_REVISE 遷移をトリガーしないこと."""
        comment = MagicMock()
        comment.user = MagicMock()
        comment.user.login = "claude[bot]"
        event = _make_event(EventType.IMPL_PR_COMMENTED, comment=comment)

        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: @claude /review 自動投稿 (TC-63-01, TC-63-04, TC-63-06, TC-63-07)
# ---------------------------------------------------------------------------


class TestClaudeReviewHook:
    """TC-63-01, TC-63-04, TC-63-06, TC-63-07: @claude /review-* 自動投稿のテスト."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """GitHubClient のモック."""
        return AsyncMock()

    @pytest.fixture
    def mock_account_manager(self, mock_client: AsyncMock) -> AsyncMock:
        """AccountManager のモック。get_client_for_repo が mock_client を返す."""
        am = AsyncMock()
        am.get_client_for_repo = AsyncMock(return_value=mock_client)
        return am

    @pytest.fixture
    def mock_sm(self) -> MagicMock:
        """StateMachineManager のモック。MagicMock ベースで非同期メソッドのみ AsyncMock。"""
        sm = MagicMock()
        sm.transition = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.IMPL_REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        sm.get_state = MagicMock(return_value=None)
        sm.register_transition_hook = MagicMock()
        return sm

    @pytest.fixture
    def mock_tq(self) -> AsyncMock:
        return AsyncMock()

    @pytest.fixture
    def router(
        self,
        mock_sm: MagicMock,
        mock_tq: AsyncMock,
        mock_account_manager: AsyncMock,
    ) -> EventRouter:
        return EventRouter(
            state_machine=mock_sm,
            task_queue=mock_tq,
            account_manager=mock_account_manager,
        )

    async def test_impl_review_hook_posts_review_impl_comment(
        self,
        router: EventRouter,
        mock_sm: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """TC-63-01: IMPL_REVIEW 遷移後のフックで @claude /review-impl が PR に投稿されること."""
        from ai_agent_orchestrator.models import IssueState

        mock_sm.get_state.return_value = IssueState(
            issue_number=1,
            phase=Phase.IMPL_REVIEW,
            repo="owner/repo",
            pr_number=42,
        )

        await router._on_review_phase_entered(1, Phase.IMPL_REVIEW)

        mock_client.create_comment.assert_called_once()
        call_args = mock_client.create_comment.call_args
        # create_comment(repo_config, pr_number, body) の第3引数を確認
        assert call_args[0][2] == "@claude /review-impl"
        assert call_args[0][1] == 42

    async def test_pr_number_none_skips_comment_without_error(
        self,
        router: EventRouter,
        mock_sm: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """TC-63-04: pr_number が None の場合、コメント投稿をスキップしてもエラーにならないこと."""
        from ai_agent_orchestrator.models import IssueState

        mock_sm.get_state.return_value = IssueState(
            issue_number=1,
            phase=Phase.IMPL_REVIEW,
            repo="owner/repo",
            pr_number=None,
        )

        # 例外が発生しないこと
        await router._post_claude_review_comment(1, "impl")

        mock_client.create_comment.assert_not_called()

    async def test_create_comment_exception_does_not_propagate(
        self,
        router: EventRouter,
        mock_sm: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """TC-63-06: create_comment が例外を投げても CI 成功フローが継続すること."""
        from ai_agent_orchestrator.models import IssueState

        mock_sm.get_state.return_value = IssueState(
            issue_number=1,
            phase=Phase.IMPL_REVIEW,
            repo="owner/repo",
            pr_number=42,
        )
        mock_client.create_comment.side_effect = Exception("GitHub API error")

        # 例外が伝播しないこと
        await router._on_review_phase_entered(1, Phase.IMPL_REVIEW)
        # ここに到達できれば OK

    async def test_design_review_hook_posts_review_design_comment(
        self,
        router: EventRouter,
        mock_sm: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """TC-63-07: DESIGN_REVIEW 遷移フックで design_pr_number の PR に @claude /review-design が投稿されること."""
        from ai_agent_orchestrator.models import IssueState

        mock_sm.get_state.return_value = IssueState(
            issue_number=1,
            phase=Phase.DESIGN_REVIEW,
            repo="owner/repo",
            design_pr_number=99,
        )

        await router._on_review_phase_entered(1, Phase.DESIGN_REVIEW)

        mock_client.create_comment.assert_called_once()
        call_args = mock_client.create_comment.call_args
        # create_comment(repo_config, design_pr_number, body)
        assert call_args[0][2] == "@claude /review-design"
        assert call_args[0][1] == 99

    async def test_issue_state_none_skips_comment_without_error(
        self,
        router: EventRouter,
        mock_sm: MagicMock,
        mock_client: AsyncMock,
    ) -> None:
        """issue_state が None の場合、コメント投稿をスキップしてもエラーにならないこと."""
        mock_sm.get_state.return_value = None

        # 例外が発生しないこと
        await router._post_claude_review_comment(1, "impl")

        mock_client.create_comment.assert_not_called()
