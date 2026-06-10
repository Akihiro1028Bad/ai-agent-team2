"""U5a (#94): fix.py の IMPLEMENT executor への統合テスト."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.models import AgentResult
from ai_agent_orchestrator.phases.fix import FixExecutor
from ai_agent_orchestrator.phases.implement import ImplementExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(phase: str = "fix") -> MagicMock:
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


def _mock_sm() -> MagicMock:
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(
        pr_number=None,
        session_id=None,
        branch_head_sha=None,
        impl_iteration=0,
    )
    sm.transition = AsyncMock()
    sm.get_phase = MagicMock(return_value=None)
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
# Re-export
# ---------------------------------------------------------------------------


class TestFixReExport:
    """fix.py は後方互換 re-export（revise.py 方式）."""

    def test_fix_executor_is_implement_executor(self) -> None:
        assert FixExecutor is ImplementExecutor


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

        await executor.execute(_make_request(phase="fix"))

        runner.run.assert_called_once()
        prompt = runner.run.call_args.kwargs["prompt"]
        assert "承認された修正方針" in prompt
        assert "validate で trim する" in prompt
        # fix は単一パス: サブタスク計画は読まない
        context.read_impl_plan.assert_not_called()

    async def test_fix_phase_transitions_and_tracks_like_before(self) -> None:
        """従来の FixExecutor と同じ遷移・tracker・PR タイトルになる."""
        gh = _mock_github()
        runner = _runner(output="修正PR #7 を作成しました")
        sm = _mock_sm()
        executor = _make_executor(runner, gh, sm)
        tracker = executor._tracker

        await executor.execute(_make_request(phase="fix"))

        sm.transition.assert_called_with(("org/app", 1), "impl-review")
        tracker.track.assert_any_call(
            "fix_complete",
            issue_number=1,
            phase="fix",
            data={"note": "impl-review に遷移", "pr_number": 7},
        )
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
        executor = _make_executor(runner, gh, _mock_sm(), context=context)

        await executor.execute(_make_request(phase="implement"))

        context.read_impl_plan.assert_called()
