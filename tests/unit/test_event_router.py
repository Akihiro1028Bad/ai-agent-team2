"""EventRouter のユニットテスト."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import (
    EventType,
    Phase,
    PollEvent,
    derive_workflow_params,
)
from ai_agent_orchestrator.orchestrator.task_queue import Priority
from ai_agent_orchestrator.poller.event_router import EventRouter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sm() -> AsyncMock:
    """StateMachineManager のモック."""
    sm = AsyncMock()
    sm.register_issue = MagicMock()
    sm.get_phase = MagicMock(return_value="approve")  # 同期メソッド
    sm.get_issue_type = MagicMock(return_value="bug")
    sm.set_issue_type = MagicMock()  # 同期メソッド
    sm.get_workflow_params = MagicMock(side_effect=lambda key: derive_workflow_params(sm.get_issue_type(key)))
    sm.get_state = MagicMock(return_value=None)  # 同期メソッド
    sm.backfill_issue_meta = MagicMock(return_value=False)  # 同期メソッド (#142)
    sm.get_ci_retry_count = AsyncMock(return_value=0)
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
        event.issue.title = "新規Issueのタイトル"
        event.issue.body = "本文の内容"
        await router.route(event)

        mock_sm.register_issue.assert_called_once()
        # 受付時に GitHub のタイトル/本文が state へ渡る (#142)
        assert mock_sm.register_issue.call_args.kwargs["title"] == "新規Issueのタイトル"
        assert mock_sm.register_issue.call_args.kwargs["body"] == "本文の内容"
        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase == "intake"

    async def test_new_issue_already_registered_backfills_meta(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """登録済み Issue は再登録せず title/body を backfill する (#142)."""
        mock_sm.get_phase = MagicMock(return_value=Phase.CLARIFY)  # 登録済み
        event = _make_event(EventType.NEW_ISSUE)
        event.issue.title = "補完タイトル"
        event.issue.body = "補完本文"
        await router.route(event)

        mock_sm.register_issue.assert_not_called()
        mock_sm.backfill_issue_meta.assert_called_once()
        assert mock_sm.backfill_issue_meta.call_args.kwargs["title"] == "補完タイトル"
        assert mock_sm.backfill_issue_meta.call_args.kwargs["body"] == "補完本文"


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
        assert args[1].value == "implement"


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
        assert args[1].value == "plan"


# ---------------------------------------------------------------------------
# Tests: DESIGN_PR_APPROVED / DESIGN_PR_COMMENTED
# ---------------------------------------------------------------------------


class TestEventRouterDesignPR:
    """設計 PR イベントのテスト."""

    async def test_design_pr_approved_routes_to_implement(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """設計 PR approve -> IMPLEMENT へ遷移する."""
        mock_sm.get_phase.return_value = Phase.APPROVE
        event = _make_event(EventType.DESIGN_PR_APPROVED)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "implement"
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase == Phase.IMPLEMENT.value

    async def test_design_pr_commented_routes_back_to_design(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """設計 PR の差し戻し (指摘) -> APPROVE ゲートとして plan (PLAN) へ戻す (U5)."""
        mock_sm.get_phase.return_value = Phase.APPROVE
        event = _make_event(
            EventType.DESIGN_PR_COMMENTED,
            extra={"comments": "アーキを見直して"},
        )
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "plan"
        # 指摘全文が feedback として再実行プロンプトに渡る (受け入れ条件2)
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase == Phase.PLAN.value
        assert "アーキを見直して" in enqueued.extra["feedback"]


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
        assert args[1].value == "revise"
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
        mock_sm.get_phase.return_value = Phase.REVIEW
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
        assert args[1].value == "revise"

    async def test_ci_failure_exceeds_limit_routes_to_suspended(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """CI 失敗 (3回超過) -> SUSPENDED へ遷移."""
        mock_sm.get_phase.return_value = Phase.REVIEW
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
        assert args[1].value == "review"
        mock_tq.enqueue.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: CI_RESULT success with @claude /review comment posting
# ---------------------------------------------------------------------------


class TestEventRouterCIResultWithReview:
    """CI_RESULT success 時の @claude /review コメント投稿テスト."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """GitHubClient のモック."""
        return AsyncMock()

    @pytest.fixture
    def mock_account_manager(self, mock_client: AsyncMock) -> AsyncMock:
        """AccountManager のモック。get_client_for_repo が GitHubClient を返す。"""
        am = AsyncMock()
        am.get_client_for_repo = AsyncMock(return_value=mock_client)
        return am

    @pytest.fixture
    def mock_sm_with_state(self) -> AsyncMock:
        """pr_number を持つ IssueState を返す StateMachineManager モック."""
        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value="approve")
        sm.get_issue_type = MagicMock(return_value="bug")
        sm.set_issue_type = MagicMock()
        sm.get_workflow_params = MagicMock(side_effect=lambda key: derive_workflow_params(sm.get_issue_type(key)))
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        state = MagicMock()
        state.pr_number = 10
        sm.get_state = MagicMock(return_value=state)
        return sm

    @pytest.fixture
    def router_with_am(
        self,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_account_manager: AsyncMock,
    ) -> EventRouter:
        """account_manager を持つ EventRouter インスタンス."""
        return EventRouter(
            state_machine=mock_sm_with_state,
            task_queue=mock_tq,
            account_manager=mock_account_manager,
        )

    async def test_ci_success_posts_claude_review_comment(
        self,
        router_with_am: EventRouter,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """CI 成功時に @claude /review コメントが実装 PR に投稿される。"""
        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})
        await router_with_am.route(event)

        mock_client.create_comment.assert_called_once()
        call_args = mock_client.create_comment.call_args
        # PR番号 10 にコメントが投稿される
        assert call_args.args[1] == 10
        # @claude /review を含むコメントが投稿される
        assert "@claude /review" in call_args.args[2]

    async def test_ci_success_already_impl_review_skips_comment(
        self,
        router_with_am: EventRouter,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """既に IMPL_REVIEW 状態の場合はコメントが投稿されない（冪等性）。"""
        mock_sm_with_state.get_phase.return_value = Phase.REVIEW
        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})
        await router_with_am.route(event)

        # 遷移はスキップされる
        mock_sm_with_state.transition.assert_not_called()
        # コメントも投稿されない
        mock_client.create_comment.assert_not_called()

    async def test_ci_success_idempotent_second_event_no_comment(
        self,
        router_with_am: EventRouter,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """CI success が2回来た場合、2回目はコメントが投稿されない。"""
        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})

        # 1回目: 遷移 + コメント投稿
        await router_with_am.route(event)
        assert mock_client.create_comment.call_count == 1

        # 2回目: 既に IMPL_REVIEW なのでスキップ
        mock_sm_with_state.get_phase.return_value = Phase.REVIEW
        await router_with_am.route(event)
        # create_comment は追加で呼ばれない
        assert mock_client.create_comment.call_count == 1

    async def test_ci_success_skips_comment_if_pr_number_none(
        self,
        router_with_am: EventRouter,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """state.pr_number が None の場合はコメント投稿がスキップされる。"""
        state = MagicMock()
        state.pr_number = None
        mock_sm_with_state.get_state.return_value = state

        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})
        await router_with_am.route(event)

        # 遷移は完了する
        mock_sm_with_state.transition.assert_called_once()
        args = mock_sm_with_state.transition.call_args[0]
        assert args[1].value == "review"
        # コメントは投稿されない
        mock_client.create_comment.assert_not_called()

    async def test_ci_success_comment_failure_does_not_block_transition(
        self,
        router_with_am: EventRouter,
        mock_sm_with_state: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """@claude /review コメント投稿失敗時も IMPL_REVIEW 遷移が完了する。"""
        mock_client.create_comment.side_effect = Exception("network error")

        event = _make_event(EventType.CI_RESULT, extra={"ci_status": "success"})
        # 例外が発生してもクラッシュしない
        await router_with_am.route(event)

        # REVIEW への遷移は完了している
        mock_sm_with_state.transition.assert_called_once()
        args = mock_sm_with_state.transition.call_args[0]
        assert args[1].value == "review"


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
        """分割承認 -> SPLIT フェーズ内で execute ステップをエンキュー (遷移なし, U5)."""
        mock_sm.get_phase.return_value = Phase.SPLIT
        event = _make_event(EventType.SPLIT_APPROVED)
        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        assert enqueued.phase == Phase.SPLIT.value
        assert enqueued.extra["step"] == "execute"

    async def test_split_modified_routes_to_hearing(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
        mock_tq: AsyncMock,
    ) -> None:
        """分割修正指示 -> CLARIFY (旧 HEARING) へ遷移 (U5)."""
        comment = MagicMock(body="こう分割して")
        event = _make_event(EventType.SPLIT_MODIFIED, comment=comment)
        await router.route(event)

        args = mock_sm.transition.call_args[0]
        assert args[1].value == "clarify"


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
        """ヒアリング回答 -> clarify エンキュー (遷移なし)."""
        from ai_agent_orchestrator.models import Phase

        mock_sm.get_phase.return_value = Phase.CLARIFY
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
        """SUSPENDED の Issue にヒアリング回答 -> CLARIFY に復帰してエンキュー."""
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
        assert args[1] == Phase.CLARIFY
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
        sm.get_phase = MagicMock(return_value=Phase.CLARIFY_WAIT)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_workflow_params = MagicMock(side_effect=lambda key: derive_workflow_params(sm.get_issue_type(key)))
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
        assert mock_sm.transition.call_args[0][1] == Phase.CLARIFY
        mock_tq.enqueue.assert_called_once()

    async def test_hearing_reply_during_hearing_enqueues_without_transition(self, router, mock_sm, mock_tq):
        """clarify 実行中にユーザーコメント → 遷移せずエンキューのみ."""
        mock_sm.get_phase.return_value = Phase.CLARIFY

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
# Tests: IMPL_PR_COMMENTED with multiple review comments (Issue #69)
# ---------------------------------------------------------------------------


class TestEventRouterImplPRCommentedMultiple:
    """複数レビューコメント同時対応のテスト (Issue #69)."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        """GitHubClient のモック."""
        client = AsyncMock()
        # デフォルト: 2件のレビューコメントを返す
        client.get_pr_review_comments.return_value = [
            {"id": 101, "user": {"login": "reviewer1"}, "body": "指摘A", "path": "a.py", "line": 1},
            {"id": 102, "user": {"login": "reviewer2"}, "body": "指摘B", "path": "b.py", "line": 2},
        ]
        return client

    @pytest.fixture
    def mock_account_manager(self, mock_client: AsyncMock) -> AsyncMock:
        """AccountManager のモック。"""
        am = AsyncMock()
        am.get_client_for_repo = AsyncMock(return_value=mock_client)
        return am

    @pytest.fixture
    def mock_sm_impl_review(self) -> AsyncMock:
        """IMPL_REVIEW フェーズの StateMachineManager モック (pr_number=10)."""
        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        state = MagicMock()
        state.pr_number = 10
        sm.get_state = MagicMock(return_value=state)
        return sm

    @pytest.fixture
    def router_with_am(
        self,
        mock_sm_impl_review: AsyncMock,
        mock_tq: AsyncMock,
        mock_account_manager: AsyncMock,
    ) -> EventRouter:
        """account_manager を持つ EventRouter インスタンス."""
        return EventRouter(
            state_machine=mock_sm_impl_review,
            task_queue=mock_tq,
            account_manager=mock_account_manager,
        )

    async def test_collects_all_review_comments_and_enqueues(
        self,
        router_with_am: EventRouter,
        mock_sm_impl_review: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """IMPL_PR_COMMENTED: 全レビューコメントを収集してエンキューする."""
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "フォールバック"})
        await router_with_am.route(event)

        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        # review_comment_ids に両コメントの ID が含まれる
        assert 101 in enqueued.extra["review_comment_ids"]
        assert 102 in enqueued.extra["review_comment_ids"]
        # comments テキストが生成されている
        assert "指摘A" in enqueued.extra["comments"]
        assert "指摘B" in enqueued.extra["comments"]

    async def test_sends_acknowledgment_after_transition_and_enqueue(
        self,
        router_with_am: EventRouter,
        mock_sm_impl_review: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """着手通知が遷移・エンキュー後に各コメントスレッドへ送られる."""
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "要修正"})
        await router_with_am.route(event)

        # 遷移・エンキューが完了していること
        mock_sm_impl_review.transition.assert_called_once()
        mock_tq.enqueue.assert_called_once()

        # 各レビューコメントに着手通知が送られる
        assert mock_client.reply_to_review_comment.call_count == 2
        # 着手通知の文言確認
        call_bodies = [mock_client.reply_to_review_comment.call_args_list[i].args[3] for i in range(2)]
        assert all("修正を開始します" in body for body in call_bodies)

    async def test_second_impl_pr_commented_is_skipped(
        self,
        mock_tq: AsyncMock,
        mock_account_manager: AsyncMock,
    ) -> None:
        """IMPL_REVISE 中の後発 IMPL_PR_COMMENTED はスキップされる."""
        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.REVISE)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        sm.get_state = MagicMock(return_value=None)
        router = EventRouter(
            state_machine=sm,
            task_queue=mock_tq,
            account_manager=mock_account_manager,
        )

        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "後発コメント"})
        await router.route(event)

        # 遷移もエンキューもされない
        sm.transition.assert_not_called()
        mock_tq.enqueue.assert_not_called()

    async def test_get_pr_review_comments_failure_falls_back_to_event_extra(
        self,
        mock_tq: AsyncMock,
        mock_account_manager: AsyncMock,
    ) -> None:
        """get_pr_review_comments 失敗時は event.extra['comments'] へフォールバックする."""
        # get_pr_review_comments が例外を送出するクライアント
        failing_client = AsyncMock()
        failing_client.get_pr_review_comments.side_effect = Exception("API error")
        mock_account_manager.get_client_for_repo = AsyncMock(return_value=failing_client)

        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        state = MagicMock()
        state.pr_number = 10
        sm.get_state = MagicMock(return_value=state)

        router = EventRouter(
            state_machine=sm,
            task_queue=mock_tq,
            account_manager=mock_account_manager,
        )

        fallback_text = "フォールバックコメント"
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": fallback_text})
        await router.route(event)

        # 遷移・エンキューは継続する
        sm.transition.assert_called_once()
        mock_tq.enqueue.assert_called_once()
        enqueued = mock_tq.enqueue.call_args[0][0]
        # フォールバックのコメントテキストが使われる
        assert fallback_text in enqueued.extra["comments"]

    async def test_acknowledgment_failure_does_not_block_transition(
        self,
        router_with_am: EventRouter,
        mock_sm_impl_review: AsyncMock,
        mock_tq: AsyncMock,
        mock_client: AsyncMock,
    ) -> None:
        """着手通知失敗時もフェーズ遷移・エンキューは継続する."""
        mock_client.reply_to_review_comment.side_effect = Exception("network error")

        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "要修正"})
        # 例外が発生してもクラッシュしない
        await router_with_am.route(event)

        # 遷移・エンキューは完了している
        mock_sm_impl_review.transition.assert_called_once()
        args = mock_sm_impl_review.transition.call_args[0]
        assert args[1].value == "revise"
        mock_tq.enqueue.assert_called_once()


class TestEventRouterLogging:
    """route のディスパッチ DEBUG ログのテスト."""

    async def test_route_logs_dispatch_with_issue_key(
        self,
        router: EventRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """route がイベント種別と issue_key を含む DEBUG ログを出す."""
        event = _make_event(EventType.NEW_ISSUE, issue_number=42)
        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.poller.event_router"):
            await router.route(event)

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "42" in debug_text
        assert "org/app" in debug_text


class TestImplPrCommentedDeferredReplayDedup:
    """延期イベント再生時、新規コメントが無ければ再エンキューしない (U2 実走で発見)."""

    @pytest.fixture
    def mock_client(self) -> AsyncMock:
        client = AsyncMock()
        client.get_pr_review_comments = AsyncMock(
            return_value=[
                {"id": 101, "user": {"login": "u"}, "body": "指摘A", "path": "a.py", "line": 1},
                {"id": 102, "user": {"login": "u"}, "body": "指摘B", "path": "b.py", "line": 2},
            ]
        )
        return client

    @pytest.fixture
    def router(self, mock_client: AsyncMock) -> tuple[EventRouter, AsyncMock, AsyncMock]:
        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        state = MagicMock()
        state.pr_number = 10
        sm.get_state = MagicMock(return_value=state)
        tq = AsyncMock()
        am = AsyncMock()
        am.get_client_for_repo = AsyncMock(return_value=mock_client)
        return EventRouter(sm, tq, account_manager=am), sm, tq

    async def test_replay_with_no_new_comments_is_skipped(
        self, router: tuple[EventRouter, AsyncMock, AsyncMock]
    ) -> None:
        """同じコメント集合での再ルーティングは遷移・エンキューしない."""
        r, sm, tq = router
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "x"})

        await r.route(event)  # 1回目: 通常処理
        await r.route(event)  # 2回目 (延期再生相当): 新規コメントなし

        assert tq.enqueue.call_count == 1
        assert sm.transition.call_count == 1

    async def test_replay_with_new_comment_is_processed(
        self,
        router: tuple[EventRouter, AsyncMock, AsyncMock],
        mock_client: AsyncMock,
    ) -> None:
        """新しいコメントが増えていれば再エンキューされる."""
        r, _sm, tq = router
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "x"})

        await r.route(event)
        mock_client.get_pr_review_comments.return_value = [
            *mock_client.get_pr_review_comments.return_value,
            {"id": 103, "user": {"login": "u"}, "body": "追加質問", "path": "c.py", "line": 3},
        ]
        await r.route(event)

        assert tq.enqueue.call_count == 2

    async def test_enqueue_duplicate_skip_does_not_mark_handled(
        self,
        router: tuple[EventRouter, AsyncMock, AsyncMock],
    ) -> None:
        """キューが重複スキップ (False) した場合は handled に記録せず、再生時に再試行する."""
        r, _sm, tq = router
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "x"})

        tq.enqueue.return_value = False  # 実行中のため重複スキップ
        await r.route(event)
        tq.enqueue.return_value = True  # タスク完了後の再生では受理される
        await r.route(event)

        # 2回目で実際にエンキューされる（handled 誤記録による喪失がない）
        assert tq.enqueue.call_count == 2


class TestReviewReplyDedupPersistence:
    """#103: 着手通知・再エンキューの重複防止（永続化された回答/通知済み ID を尊重）."""

    def _make(
        self,
        answered: list[int] | None = None,
        acknowledged: list[int] | None = None,
    ) -> tuple[EventRouter, MagicMock, AsyncMock, AsyncMock]:
        client = AsyncMock()
        client.get_pr_review_comments = AsyncMock(
            return_value=[
                {"id": 101, "user": {"login": "u"}, "body": "指摘A", "path": "a.py", "line": 1},
                {"id": 102, "user": {"login": "u"}, "body": "指摘B", "path": "b.py", "line": 2},
            ]
        )
        sm = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.REVIEW)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        state = MagicMock()
        state.pr_number = 10
        state.answered_review_comment_ids = list(answered or [])
        state.acknowledged_review_comment_ids = list(acknowledged or [])
        state.answered_review_ids = []
        sm.get_state = MagicMock(return_value=state)
        sm.persist = MagicMock()
        tq = AsyncMock()
        tq.enqueue.return_value = True
        am = AsyncMock()
        am.get_client_for_repo = AsyncMock(return_value=client)
        return EventRouter(sm, tq, account_manager=am), state, tq, client

    async def test_all_answered_skips_even_on_fresh_router(self) -> None:
        """全コメント回答済みなら、新インスタンス（再起動相当）でも再エンキューしない.

        インラインのみのレビューは event.extra の comments が空（review body 空）。
        """
        router, _state, tq, client = self._make(answered=[101, 102])
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": ""})

        await router.route(event)

        tq.enqueue.assert_not_called()
        client.reply_to_review_comment.assert_not_called()

    async def test_top_level_comment_prevents_skip(self) -> None:
        """インライン全件回答済みでも、トップレベル本文があればスキップしない（消失防止）."""
        router, _state, tq, _client = self._make(answered=[101, 102])
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "新しい質問です"})

        await router.route(event)

        tq.enqueue.assert_called_once()
        enqueued = tq.enqueue.call_args.args[0]
        assert enqueued.extra["review_comment_ids"] == []
        assert "新しい質問" in enqueued.extra["comments"]

    async def test_partial_ack_failure_records_only_succeeded(self) -> None:
        """着手通知が部分失敗した場合、成功した ID のみ記録される（失敗分は次回再送）."""
        router, state, _tq, client = self._make()
        client.reply_to_review_comment.side_effect = [Exception("api error"), None]
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": ""})

        await router.route(event)

        assert state.acknowledged_review_comment_ids == [102]

    async def test_ack_sent_only_to_unacknowledged(self) -> None:
        """着手通知は未通知のコメントにのみ送られ、state に記録される."""
        router, state, _tq, client = self._make(acknowledged=[101])
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "x"})

        await router.route(event)

        # 102 のみに着手通知
        assert client.reply_to_review_comment.call_count == 1
        assert client.reply_to_review_comment.call_args.args[2] == 102
        # 記録と永続化
        assert set(state.acknowledged_review_comment_ids) == {101, 102}

    async def test_answered_comments_excluded_from_task_extra(self) -> None:
        """回答済みコメントはタスクの対象（ids/構造化リスト）から除外される."""
        router, _state, tq, _client = self._make(answered=[101])
        event = _make_event(EventType.IMPL_PR_COMMENTED, extra={"comments": "x"})

        await router.route(event)

        enqueued = tq.enqueue.call_args.args[0]
        assert enqueued.extra["review_comment_ids"] == [102]
        assert [c["id"] for c in enqueued.extra["review_comments"]] == [102]

    async def test_answered_top_level_review_is_skipped(self) -> None:
        """応答済み review_id のトップレベル本文は再起動後もスキップされる."""
        router, state, tq, _client = self._make(answered=[101, 102])
        state.answered_review_ids = [777]
        event = _make_event(
            EventType.IMPL_PR_COMMENTED,
            extra={"comments": "本文の質問", "review_id": 777},
        )

        await router.route(event)

        tq.enqueue.assert_not_called()

    async def test_review_id_is_passed_to_task_extra(self) -> None:
        """review_id がタスク extra に透過される（revise 側の記録用）."""
        router, _state, tq, _client = self._make()
        event = _make_event(
            EventType.IMPL_PR_COMMENTED,
            extra={"comments": "", "review_id": 888},
        )

        await router.route(event)

        assert tq.enqueue.call_args.args[0].extra["review_id"] == 888


# ---------------------------------------------------------------------------
# Tests: _ensure_registered (再起動リカバリの自動登録)
# ---------------------------------------------------------------------------


class TestEnsureRegisteredTypeValidation:
    """不正な type:* ラベルのフォールバック (セキュリティレビュー Medium 対応)."""

    async def test_invalid_type_label_falls_back_to_bug(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
    ) -> None:
        """許可外の type ラベルは ValueError を出さず bug にフォールバックする."""
        mock_sm.get_phase = MagicMock(side_effect=KeyError(1))  # 未登録
        event = _make_event(EventType.PLAN_REACTION_ADDED)
        lbl_type = MagicMock()
        lbl_type.name = "type:arbitrary-value"
        lbl_phase = MagicMock()
        lbl_phase.name = "phase:approve"
        event.issue.labels = [lbl_type, lbl_phase]

        # ValueError が伝播しないこと
        await router._ensure_registered(event)
        mock_sm.set_issue_type.assert_called_once()
        assert mock_sm.set_issue_type.call_args.args[1] == "bug"

    async def test_valid_type_label_is_used(
        self,
        router: EventRouter,
        mock_sm: AsyncMock,
    ) -> None:
        """許可された type ラベルはそのまま使われる."""
        mock_sm.get_phase = MagicMock(side_effect=KeyError(1))
        event = _make_event(EventType.PLAN_REACTION_ADDED)
        lbl = MagicMock()
        lbl.name = "type:feature-m"
        event.issue.labels = [lbl]

        await router._ensure_registered(event)
        assert mock_sm.set_issue_type.call_args.args[1] == "feature-m"
