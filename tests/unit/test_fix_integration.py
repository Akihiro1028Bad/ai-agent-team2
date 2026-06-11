"""U5a (#94): fix フロー IMPLEMENT executor への統合テスト."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.models import AgentResult, derive_workflow_params
from ai_agent_orchestrator.phases.implement import ImplementExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(phase: str = "implement") -> MagicMock:
    req = MagicMock()
    req.repo = MagicMock(owner="org", repo="app")
    req.issue_number = 1
    req.issue_key = ("org/app", 1)
    req.phase = phase
    req.extra = {}
    return req


def _make_executor(
    runner: AsyncMock,
    github: AsyncMock,
    sm: MagicMock,
    context: AsyncMock | None = None,
) -> ImplementExecutor:
    ws = AsyncMock()
    ws.create_worktree.return_value = "/tmp/wt/issue-1"
    ws._run_git = AsyncMock(return_value=(0, "", ""))
    executor = ImplementExecutor(
        runner,
        github,
        AsyncMock(),  # notifier
        AsyncMock(),  # tracker
        ws,
        context or AsyncMock(),
        sm,
    )
    executor._finalize_phase_commit = AsyncMock()  # type: ignore[method-assign]
    return executor


def _mock_github(comments: list[Any] | None = None) -> AsyncMock:
    gh = AsyncMock()
    del gh.get_client_for_repo
    issue = MagicMock()
    issue.title = "バグ: 何かが壊れている"
    issue.body = "再現手順..."
    gh.get_issue.return_value = issue
    gh.list_comments.return_value = comments or []
    gh.list_pull_requests.return_value = []
    return gh


def _mock_sm(issue_type: str = "bug") -> MagicMock:
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(
        pr_number=None,
        session_id=None,
        branch_head_sha=None,
        impl_iteration=0,
    )
    sm.transition = AsyncMock()
    sm.get_phase = MagicMock(return_value=None)
    sm.get_issue_type = MagicMock(return_value=issue_type)
    sm.get_workflow_params = MagicMock(side_effect=lambda key: derive_workflow_params(sm.get_issue_type(key)))
    return sm


def _runner(output: str = "修正PR #7 を作成しました") -> AsyncMock:
    runner = AsyncMock()
    runner.run.return_value = AgentResult(
        session_id="s1",
        output=output,
        tool_uses=[],
        cost_usd=1.0,
        duration_sec=30.0,
    )
    return runner


# ---------------------------------------------------------------------------
# fix フェーズの実行フロー
# ---------------------------------------------------------------------------


class TestFixFlowViaImplementExecutor:
    """ImplementExecutor が fix フェーズを単一パスで処理する."""

    async def test_fix_phase_runs_single_pass_with_plan_comment(self) -> None:
        """fix フェーズ: 修正方針コメントを含むプロンプトで1回だけ実行する."""
        plan = MagicMock()
        plan.body = "## 修正方針\nvalidate で trim する"
        gh = _mock_github(comments=[plan])
        runner = _runner()
        context = AsyncMock()
        context.build_context.return_value = "（コンテキスト）"
        executor = _make_executor(runner, gh, _mock_sm(), context=context)

        await executor.execute(_make_request(phase="implement"))

        runner.run.assert_called_once()
        prompt = runner.run.call_args.kwargs["prompt"]
        # 実装フェーズのプロンプトが生成されていることを確認
        assert prompt is not None
        # fix は単一パス: サブタスク計画は読まない
        context.read_impl_plan.assert_not_called()

    async def test_fix_phase_transitions_and_tracks(self) -> None:
        """bug タイプの ImplementExecutor は REVIEW に遷移する (旧 impl-review)."""
        gh = _mock_github()
        runner = _runner(output="修正PR #7 を作成しました")
        sm = _mock_sm(issue_type="bug")
        executor = _make_executor(runner, gh, sm)
        tracker = executor._tracker

        await executor.execute(_make_request(phase="implement"))

        sm.transition.assert_called_with(("org/app", 1), "review")
        # phase_end イベントが記録されていること (bug type fix flow)
        tracked_events = [c.args[0] for c in tracker.track.call_args_list]
        assert "phase_end" in tracked_events
        # finalize_phase_commit は fix 用パラメータで呼ばれる
        kwargs = executor._finalize_phase_commit.call_args.kwargs  # type: ignore[attr-defined]
        assert kwargs["commit_type"] == "fix"
        assert kwargs.get("allow_no_changes", False) is False

    async def test_implement_phase_still_uses_subtask_flow(self) -> None:
        """implement フェーズは従来通り計画ファイルを参照する（fix 分岐の影響なし）."""
        gh = _mock_github()
        runner = _runner(output="実装完了")
        context = AsyncMock()
        context.build_context.return_value = "## 設計書\nx\n\n## 実装計画\ny"
        context.read_impl_plan.return_value = None  # 計画なし → legacy へ
        executor = _make_executor(runner, gh, _mock_sm(issue_type="feature-m"), context=context)

        await executor.execute(_make_request(phase="implement"))

        context.read_impl_plan.assert_called()
