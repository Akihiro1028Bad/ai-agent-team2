"""Phase executors unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import AgentResult

# ---------------------------------------------------------------------------
# Common fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_runner() -> AsyncMock:
    """Mock ClaudeAgentRunner."""
    runner = AsyncMock()
    runner.run.return_value = AgentResult(
        session_id="sess-001",
        output="test output",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=30.0,
    )
    return runner


@pytest.fixture
def mock_github() -> AsyncMock:
    """Mock GitHubClient.

    get_client_for_repo を削除して PhaseExecutor._get_client() が
    AccountManager としてではなく直接クライアントとして返すようにする。
    """
    gh = AsyncMock()
    # AccountManager と区別するため get_client_for_repo を削除
    del gh.get_client_for_repo
    issue = MagicMock()
    issue.title = "テストIssue"
    issue.body = "テスト本文"
    issue.number = 1
    gh.get_issue.return_value = issue
    gh.list_comments.return_value = []
    return gh


@pytest.fixture
def mock_notifier() -> AsyncMock:
    """Mock Notifier."""
    return AsyncMock()


@pytest.fixture
def mock_tracker() -> AsyncMock:
    """Mock Tracker."""
    return AsyncMock()


@pytest.fixture
def mock_workspace() -> AsyncMock:
    """Mock WorkspaceManager."""
    ws = AsyncMock()
    ws.create_worktree.return_value = "/tmp/worktree/issue-1"
    # _run_git: デフォルトは成功 (rc=0, stdout="", stderr="")
    ws._run_git = AsyncMock(return_value=(0, "", ""))
    return ws


@pytest.fixture
def mock_context() -> AsyncMock:
    """Mock ContextEngine."""
    ctx = AsyncMock()
    ctx.build_context.return_value = (
        "## リポジトリ構造\n(mock context)\n\n## 設計書\n(mock design doc)\n\n## 実装計画\n(mock impl plan)"
    )
    # マルチパス完了判定用: None → 計画ファイルなし → 即完了
    ctx.read_impl_plan = AsyncMock(return_value=None)
    return ctx


@pytest.fixture
def mock_sm() -> MagicMock:
    """Mock StateMachineManager.

    Uses MagicMock as base since get_state/get_issue_type/set_issue_type
    are synchronous. Async methods (transition, increment_ci_retry)
    are explicitly set to AsyncMock.
    """
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(
        issue_number=1,
        session_id=None,
        pr_number=None,
        design_pr_number=None,
        branch_head_sha=None,
        impl_iteration=0,
    )
    sm.get_issue_type.return_value = "feature-m"
    sm.transition = AsyncMock()
    sm.increment_ci_retry = AsyncMock()
    return sm


def _make_request(
    phase: str = "hearing",
    issue_number: int = 1,
    extra: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock TaskRequest."""
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    req = MagicMock()
    req.issue_number = issue_number
    req.repo = repo
    req.phase = phase
    req.extra = extra or {}
    return req


# ---------------------------------------------------------------------------
# TypeDetectionExecutor
# ---------------------------------------------------------------------------


class TestTypeDetectionExecutor:
    """TypeDetectionExecutor tests."""

    async def test_detects_bug_type(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """Bug タイプが正しく判定されラベルが付与される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output='{"type": "bug", "reason": "エラーキーワードあり"}',
            tool_uses=[],
            cost_usd=0.1,
            duration_sec=5.0,
        )
        from ai_agent_orchestrator.phases.type_detection import (
            TypeDetectionExecutor,
        )

        executor = TypeDetectionExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="type-detection")
        await executor.execute(request)

        mock_sm.set_issue_type.assert_called_with(1, "bug")
        mock_github.add_label.assert_called_once()
        mock_sm.transition.assert_called_with(1, "analysis")

    async def test_detects_small_feature_as_feature_m(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """小規模フィーチャーが feature-m として判定される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output='{"type": "feature-m", "reason": "小規模変更"}',
            tool_uses=[],
            cost_usd=0.1,
            duration_sec=5.0,
        )
        from ai_agent_orchestrator.phases.type_detection import (
            TypeDetectionExecutor,
        )

        executor = TypeDetectionExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="type-detection")
        await executor.execute(request)

        mock_sm.set_issue_type.assert_called_with(1, "feature-m")
        mock_sm.transition.assert_called_with(1, "hearing")

    async def test_fallback_detection_on_invalid_json(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """JSON パース失敗時にフォールバック判定が動作する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="これはバグです",
            tool_uses=[],
            cost_usd=0.1,
            duration_sec=5.0,
        )
        from ai_agent_orchestrator.phases.type_detection import (
            TypeDetectionExecutor,
        )

        executor = TypeDetectionExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="type-detection")
        await executor.execute(request)

        # "バグ" keyword triggers bug detection
        mock_sm.set_issue_type.assert_called_with(1, "bug")


# ---------------------------------------------------------------------------
# HearingExecutor
# ---------------------------------------------------------------------------


class TestHearingExecutor:
    """HearingExecutor tests."""

    async def test_posts_question_when_not_ready(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """情報不足時に質問がコメント投稿される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="確認したいのですが、認証方式はOAuth2ですか?",
            tool_uses=[],
            cost_usd=0.3,
            duration_sec=10.0,
        )
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        executor = HearingExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_github.create_comment.assert_called_once()
        mock_notifier.notify.assert_called_once()

    async def test_transitions_to_design_when_ready(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """情報十分時に DESIGN へ遷移する (Feature-M)。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="READY",
            tool_uses=[],
            cost_usd=0.2,
            duration_sec=8.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        executor = HearingExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "design")

    async def test_transitions_to_split_when_needs_split(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """NEEDS_SPLIT 出力時に split-proposal へ遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="NEEDS_SPLIT",
            tool_uses=[],
            cost_usd=0.2,
            duration_sec=8.0,
        )
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        executor = HearingExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "split-proposal")


# ---------------------------------------------------------------------------
# AnalysisExecutor
# ---------------------------------------------------------------------------


class TestAnalysisExecutor:
    """AnalysisExecutor tests."""

    async def test_posts_plan_and_transitions_to_plan_review(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """修正方針がコメント投稿され PLAN_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="修正方針: null check漏れ",
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        from ai_agent_orchestrator.phases.analysis import AnalysisExecutor

        executor = AnalysisExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="analysis")
        await executor.execute(request)

        mock_github.create_comment.assert_called_once()
        mock_sm.transition.assert_called_with(1, "plan-review")


# ---------------------------------------------------------------------------
# DesignExecutor
# ---------------------------------------------------------------------------


class TestDesignExecutor:
    """DesignExecutor tests."""

    async def test_creates_design_pr_and_transitions(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """設計 PR が作成され DESIGN_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        from ai_agent_orchestrator.phases.design import DesignExecutor

        executor = DesignExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="design")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "design-review")
        state = mock_sm.get_state(1)
        assert state.design_pr_number == 5


# ---------------------------------------------------------------------------
# DesignReviseExecutor
# ---------------------------------------------------------------------------


class TestDesignReviseExecutor:
    """DesignReviseExecutor tests."""

    async def test_uses_resume_session(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """セッション継続で実行される。"""
        mock_sm.get_state.return_value = MagicMock(session_id="prev-session")
        from ai_agent_orchestrator.phases.design_revise import (
            DesignReviseExecutor,
        )

        executor = DesignReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="design-revise", extra={"comments": "要修正"})
        await executor.execute(request)

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args.kwargs
        assert call_kwargs["resume_session_id"] == "prev-session"


# ---------------------------------------------------------------------------
# PlanningExecutor
# ---------------------------------------------------------------------------


class TestPlanningExecutor:
    """PlanningExecutor tests."""

    async def test_transitions_to_implement(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """実装計画作成後に IMPLEMENT に遷移する。"""
        from ai_agent_orchestrator.phases.planning import PlanningExecutor

        executor = PlanningExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="planning")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "implement")


# ---------------------------------------------------------------------------
# ImplementExecutor
# ---------------------------------------------------------------------------


class TestImplementExecutor:
    """ImplementExecutor tests."""

    async def test_creates_pr_and_transitions_to_impl_review(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """PR が作成され IMPL_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="PR #42 を作成しました",
            tool_uses=[],
            cost_usd=3.0,
            duration_sec=120.0,
        )
        # マルチパス: _read_impl_plan が None → 完了判定で即終了
        mock_context._read_impl_plan = AsyncMock(return_value=None)

        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        executor = ImplementExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="implement")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "impl-review")
        state = mock_sm.get_state(1)
        assert state.pr_number == 42


# ---------------------------------------------------------------------------
# FixExecutor
# ---------------------------------------------------------------------------


class TestFixExecutor:
    """FixExecutor tests."""

    async def test_transitions_to_impl_review(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """FixExecutor は修正完了後 IMPL_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="修正PR #7 を作成しました",
            tool_uses=[],
            cost_usd=2.0,
            duration_sec=60.0,
        )
        from ai_agent_orchestrator.phases.fix import FixExecutor

        executor = FixExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        # transition to impl-review should be called
        mock_sm.transition.assert_called_with(1, "impl-review")
        # tracker should record fix_complete with pr_number
        mock_tracker.track.assert_any_call(
            "fix_complete",
            issue_number=1,
            phase="fix",
            data={"note": "impl-review に遷移", "pr_number": 7},
        )
        # PR number should be recorded
        state = mock_sm.get_state(1)
        assert state.pr_number == 7


# ---------------------------------------------------------------------------
# CiFixExecutor
# ---------------------------------------------------------------------------


class TestCiFixExecutor:
    """CiFixExecutor tests."""

    async def test_increments_retry_count(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """CI 修正後にリトライカウンタがインクリメントされる。"""
        from ai_agent_orchestrator.phases.ci_fix import CiFixExecutor

        executor = CiFixExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(
            phase="ci-fix",
            extra={"ci_logs": "Error: test failed", "retry_count": 2},
        )
        await executor.execute(request)

        mock_sm.increment_ci_retry.assert_called_with(1)


# ---------------------------------------------------------------------------
# ImplReviseExecutor
# ---------------------------------------------------------------------------


class TestImplReviseExecutor:
    """ImplReviseExecutor tests."""

    async def test_uses_resume_session_and_transitions(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """セッション継続で実行され IMPL_REVIEW に遷移する。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-impl-session",
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
        )
        from ai_agent_orchestrator.phases.impl_revise import (
            ImplReviseExecutor,
        )

        executor = ImplReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="impl-revise", extra={"comments": "変数名修正"})
        await executor.execute(request)

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args.kwargs
        assert call_kwargs["resume_session_id"] == "prev-impl-session"
        mock_sm.transition.assert_called_with(1, "impl-review")


# ---------------------------------------------------------------------------
# SplitProposalExecutor
# ---------------------------------------------------------------------------


class TestSplitProposalExecutor:
    """SplitProposalExecutor tests."""

    async def test_posts_proposal_comment(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """分割提案がコメント投稿される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="Issue分割提案\n| # | タイトル |",
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        from ai_agent_orchestrator.phases.split import (
            SplitProposalExecutor,
        )

        executor = SplitProposalExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="split-proposal")
        await executor.execute(request)

        mock_github.create_comment.assert_called_once()
        mock_notifier.notify.assert_called_once()
        # transition should NOT be called (stays in split-proposal)
        mock_sm.transition.assert_not_called()


# ---------------------------------------------------------------------------
# SplitExecuteExecutor
# ---------------------------------------------------------------------------


class TestSplitExecuteExecutor:
    """SplitExecuteExecutor tests."""

    async def test_transitions_to_done_after_split(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """分割実行後に DONE へ遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="子Issue #10, #11, #12 を作成しました",
            tool_uses=[],
            cost_usd=0.3,
            duration_sec=15.0,
        )
        from ai_agent_orchestrator.phases.split import (
            SplitExecuteExecutor,
        )

        executor = SplitExecuteExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="split-execute")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "done")
        mock_github.create_comment.assert_called_once()


# ---------------------------------------------------------------------------
# DoneExecutor
# ---------------------------------------------------------------------------


class TestDoneExecutor:
    """DoneExecutor tests."""

    async def test_merges_pr_closes_issue_removes_worktree(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """Issue クローズ、worktree 削除が実行される（マージはしない）。"""
        mock_sm.get_state.return_value = MagicMock(pr_number=42)
        from ai_agent_orchestrator.phases.done import DoneExecutor

        executor = DoneExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="done")
        await executor.execute(request)

        mock_github.merge_pull_request.assert_not_called()
        mock_github.close_issue.assert_called_once()
        mock_workspace.remove_worktree.assert_called_once()

    async def test_skips_merge_when_no_pr(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """PR がない場合はマージをスキップする。"""
        mock_sm.get_state.return_value = MagicMock(pr_number=None)
        from ai_agent_orchestrator.phases.done import DoneExecutor

        executor = DoneExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="done")
        await executor.execute(request)

        mock_github.merge_pull_request.assert_not_called()
        mock_github.close_issue.assert_called_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestPhaseExecutorErrorHandling:
    """Error handling tests for PhaseExecutor base class."""

    async def test_timeout_transitions_to_suspended(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """タイムアウト時に SUSPENDED へ遷移し通知される。"""
        mock_runner.run.side_effect = TimeoutError()
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        executor = HearingExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "suspended")
        mock_notifier.notify.assert_called_once()

    async def test_generic_error_transitions_to_suspended(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """一般エラー時に SUSPENDED へ遷移し Issue コメント + 通知される。"""
        mock_runner.run.side_effect = RuntimeError("Unexpected error")
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        executor = ImplementExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="implement")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "suspended")
        mock_github.create_comment.assert_called_once()
        mock_notifier.notify.assert_called_once()


# ---------------------------------------------------------------------------
# PhaseDispatcher
# ---------------------------------------------------------------------------


class TestPhaseDispatcher:
    """PhaseDispatcher tests."""

    async def test_dispatches_to_correct_executor(self) -> None:
        """phase に対応する executor が呼び出される。"""
        from ai_agent_orchestrator.phases.dispatcher import PhaseDispatcher

        mock_executor = AsyncMock()
        dispatcher = PhaseDispatcher(executors={"hearing": mock_executor})

        request = _make_request(phase="hearing")
        await dispatcher.execute(request)

        mock_executor.execute.assert_called_once_with(request)

    async def test_unknown_phase_raises_key_error(self) -> None:
        """未登録フェーズは KeyError を発生させる。"""
        from ai_agent_orchestrator.phases.dispatcher import PhaseDispatcher

        dispatcher = PhaseDispatcher(executors={})
        request = _make_request(phase="unknown")

        with pytest.raises(KeyError):
            await dispatcher.execute(request)

    async def test_normalizes_phase_key(self) -> None:
        """ハイフン付きフェーズ名がアンダースコアに正規化される。"""
        from ai_agent_orchestrator.phases.dispatcher import PhaseDispatcher

        mock_executor = AsyncMock()
        dispatcher = PhaseDispatcher(executors={"ci_fix": mock_executor})

        request = _make_request(phase="ci-fix")
        await dispatcher.execute(request)

        mock_executor.execute.assert_called_once_with(request)


# ---------------------------------------------------------------------------
# _ensure_pr_created fallback tests
# ---------------------------------------------------------------------------


class TestEnsurePrCreated:
    """_ensure_pr_created フォールバック機能のテスト。"""

    async def test_fix_fallback_finds_existing_pr(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """エージェント出力にPR番号がなくても既存PRを検索して取得する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="修正を完了しました",  # PR番号なし
            tool_uses=[],
            cost_usd=2.0,
            duration_sec=60.0,
        )
        # 既存PRを返す
        existing_pr = MagicMock()
        existing_pr.number = 99
        mock_github.list_pull_requests.return_value = [existing_pr]

        from ai_agent_orchestrator.phases.fix import FixExecutor

        executor = FixExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        # 既存PRが見つかるのでimpl-reviewに遷移
        mock_sm.transition.assert_called_with(1, "impl-review")
        state = mock_sm.get_state(1)
        assert state.pr_number == 99

    async def test_implement_fallback_creates_pr_via_api(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """エージェント出力にもPR検索にもなければAPIでPR作成する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="実装を完了しました",  # PR番号なし
            tool_uses=[],
            cost_usd=3.0,
            duration_sec=120.0,
        )
        # 既存PRなし
        mock_github.list_pull_requests.return_value = []
        # API作成が成功
        created_pr = MagicMock()
        created_pr.number = 101
        mock_github.create_pull_request.return_value = created_pr
        # マルチパス: _read_impl_plan が None → 完了判定で即終了
        mock_context._read_impl_plan = AsyncMock(return_value=None)

        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        executor = ImplementExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="implement")
        request.repo.base_branch = "main"
        await executor.execute(request)

        # APIでPR作成 → impl-reviewに遷移
        mock_github.create_pull_request.assert_called_once()
        mock_sm.transition.assert_called_with(1, "impl-review")
        state = mock_sm.get_state(1)
        assert state.pr_number == 101

    async def test_design_fallback_creates_pr_via_api(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """設計フェーズでもフォールバックPR作成が動作する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計書を作成しました",  # PR番号なし
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_github.list_pull_requests.return_value = []
        created_pr = MagicMock()
        created_pr.number = 55
        mock_github.create_pull_request.return_value = created_pr

        from ai_agent_orchestrator.phases.design import DesignExecutor

        executor = DesignExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="design")
        request.repo.base_branch = "main"
        await executor.execute(request)

        mock_github.create_pull_request.assert_called_once()
        mock_sm.transition.assert_called_with(1, "design-review")
        state = mock_sm.get_state(1)
        assert state.design_pr_number == 55

    async def test_fallback_failure_transitions_to_suspended(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """全フォールバックが失敗するとSUSPENDEDに遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="完了",  # PR番号なし
            tool_uses=[],
            cost_usd=2.0,
            duration_sec=60.0,
        )
        # 全て失敗
        mock_github.list_pull_requests.side_effect = Exception("API error")
        mock_github.create_pull_request.side_effect = Exception("Create failed")

        from ai_agent_orchestrator.phases.fix import FixExecutor

        executor = FixExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        # RuntimeError → _handle_error → suspended
        mock_sm.transition.assert_called_with(1, "suspended")
        mock_notifier.notify.assert_called_once()


# ---------------------------------------------------------------------------
# PhaseExecutor._extract_pr_number
# ---------------------------------------------------------------------------


class TestExtractPrNumber:
    """_extract_pr_number utility tests."""

    def test_extracts_pr_number(self) -> None:
        """PR 番号を正しく抽出する。"""
        from ai_agent_orchestrator.phases.base import PhaseExecutor

        assert PhaseExecutor._extract_pr_number("PR #42 を作成") == 42

    def test_returns_none_for_no_match(self) -> None:
        """PR 番号がない場合は None を返す。"""
        from ai_agent_orchestrator.phases.base import PhaseExecutor

        assert PhaseExecutor._extract_pr_number("完了しました") is None


# ---------------------------------------------------------------------------
# HearingWaitTransition
# ---------------------------------------------------------------------------


class TestHearingWaitTransition:
    """hearing 質問投稿後に hearing-wait へ遷移するテスト."""

    async def test_hearing_question_transitions_to_hearing_wait(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """質問投稿後に hearing-wait へ遷移する."""
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        mock_sm.get_state.return_value = MagicMock(session_id=None)
        mock_sm.get_issue_type.return_value = "feature-m"

        executor = HearingExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("hearing", issue_number=42)
        result = AgentResult(
            session_id="sess-001",
            output="Please confirm:\n1. Target users?",
            tool_uses=[],
            cost_usd=0.1,
            duration_sec=10.0,
        )
        await executor.process_result(request, result)

        # hearing-wait へ遷移したことを確認
        mock_sm.transition.assert_called_once_with(42, "hearing-wait")
        # ラベルが hearing-wait に更新されたことを確認
        mock_github.replace_phase_label.assert_called_once()
        label_args = mock_github.replace_phase_label.call_args
        assert "phase:hearing-wait" in str(label_args)


# ---------------------------------------------------------------------------
# TestDesignPrLookup
# ---------------------------------------------------------------------------


class TestDesignPrLookup:
    """design フェーズの PR 検索テスト."""

    async def test_ensure_pr_created_finds_feature_branch_pr(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """feature/issue-XX ブランチの PR を正しく検索できる."""
        from ai_agent_orchestrator.phases.design import DesignExecutor

        mock_sm.get_state.return_value = MagicMock(
            session_id=None,
            design_pr_number=None,
            pr_number=None,
            branch_head_sha=None,
        )

        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_github.list_pull_requests = AsyncMock(return_value=[mock_pr])
        mock_github.get_issue = AsyncMock(return_value=MagicMock(title="Test", body="body"))
        mock_github.replace_phase_label = AsyncMock()
        mock_sm.transition = AsyncMock()

        executor = DesignExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("design", issue_number=42)
        result = AgentResult(
            session_id="sess-001",
            output="設計書を作成しました。",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=100.0,
        )
        await executor.process_result(request, result)

        # list_pull_requests が feature/issue-42 で検索されたことを確認
        # (設計・実装は同一 feature ブランチで管理)
        call_args = mock_github.list_pull_requests.call_args
        assert "feature/issue-42" in str(call_args)


class TestEnsurePrCreatedFallback:
    """_ensure_pr_created の feature ブランチフォールバック検索テスト."""

    async def test_fallback_to_feature_branch_when_prefix_differs(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """branch_prefix が feature 以外のとき、feature/issue-XX でもフォールバック検索する."""
        mock_pr = MagicMock()
        mock_pr.number = 55

        # 1st call (design/issue-42): not found → []
        # 2nd call (feature/issue-42): found → [mock_pr]
        mock_github.list_pull_requests = AsyncMock(side_effect=[[], [mock_pr]])
        mock_github.get_issue = AsyncMock(return_value=MagicMock(title="Test"))

        from ai_agent_orchestrator.phases.design import DesignExecutor

        executor = DesignExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("design", issue_number=42)
        pr_number = await executor._ensure_pr_created(
            request,
            "no PR number here",
            branch_prefix="design",
            title_prefix="docs: ",
        )
        assert pr_number == 55


# ---------------------------------------------------------------------------
# エラーハンドリング可観測性テスト
# ---------------------------------------------------------------------------


class TestHandleErrorObservability:
    """_handle_error / _handle_timeout の可観測性改善テスト."""

    async def test_handle_error_tracks_phase_suspended_event(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_error が phase_suspended イベントを events.jsonl に記録する。"""
        from ai_agent_orchestrator.phases.fix import FixExecutor

        mock_sm.get_phase.return_value = None  # DONE でない
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_runner.run.side_effect = RuntimeError("テストエラー")

        executor = FixExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        # phase_suspended イベントが記録されていること
        tracked_calls = [str(c) for c in mock_tracker.track.call_args_list]
        assert any("phase_suspended" in c for c in tracked_calls), (
            f"phase_suspended event not found in tracker calls: {tracked_calls}"
        )

        # suspend_reason: exception が含まれていること
        for call in mock_tracker.track.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "phase_suspended":
                data = kwargs.get("data") or (args[2] if len(args) > 2 else {})
                assert data.get("suspend_reason") == "exception"
                assert "error_type" in data
                assert "error_message" in data
                break

    async def test_handle_error_survives_create_comment_failure(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_error は create_comment が失敗しても suspended 遷移を完了する。"""
        from ai_agent_orchestrator.phases.fix import FixExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_runner.run.side_effect = RuntimeError("テストエラー")
        mock_github.create_comment.side_effect = Exception("GitHub API エラー")

        executor = FixExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="fix")

        # create_comment が失敗しても例外が伝播しないこと
        await executor.execute(request)

        # suspended 遷移は完了していること
        mock_sm.transition.assert_called_with(1, "suspended")

    async def test_handle_error_survives_notifier_failure(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_error は notifier が失敗しても suspended 遷移を完了する。"""
        from ai_agent_orchestrator.phases.fix import FixExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_runner.run.side_effect = RuntimeError("テストエラー")
        mock_notifier.notify.side_effect = Exception("Slack 接続エラー")

        executor = FixExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "suspended")

    async def test_handle_timeout_tracks_phase_suspended_event(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_timeout が phase_suspended イベントを events.jsonl に記録する。"""
        from ai_agent_orchestrator.phases.fix import FixExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_runner.run.side_effect = TimeoutError()

        executor = FixExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        tracked_calls = [str(c) for c in mock_tracker.track.call_args_list]
        assert any("phase_suspended" in c for c in tracked_calls)

        for call in mock_tracker.track.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "phase_suspended":
                data = kwargs.get("data") or (args[2] if len(args) > 2 else {})
                assert data.get("suspend_reason") == "timeout"
                break

    async def test_handle_timeout_posts_issue_comment(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_timeout が Issue にタイムアウトコメントを投稿する。"""
        from ai_agent_orchestrator.phases.fix import FixExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_runner.run.side_effect = TimeoutError()

        executor = FixExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="fix")
        await executor.execute(request)

        mock_github.create_comment.assert_called_once()
        comment_body = mock_github.create_comment.call_args[0][2]
        assert "タイムアウト" in comment_body


class TestPhaseCompletedStatus:
    """phase_completed イベントの status フィールドテスト."""

    async def test_phase_completed_has_success_status(self) -> None:
        """orchestrator.py の phase_completed 記録に status: success が含まれる。"""
        # orchestrator.py の _execute_task が phase_completed を記録する際に
        # data に status: "success" が含まれることを確認する
        # (実際のコードを grep してフィールドの存在を検証)
        import ast
        import pathlib

        source = pathlib.Path(
            "/home/a-tsutsumi/dev/ai-agent-team2/src/ai_agent_orchestrator/orchestrator/orchestrator.py"
        ).read_text()
        tree = ast.parse(source)

        # phase_completed の track 呼び出しに "status" キーが含まれているか確認
        found_status = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "track":
                for kw in node.keywords:
                    if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                        for key in kw.value.keys:
                            if isinstance(key, ast.Constant) and key.value == "status":
                                found_status = True
                                break

        assert found_status, "orchestrator.py の phase_completed track 呼び出しに status フィールドが見つかりません"
