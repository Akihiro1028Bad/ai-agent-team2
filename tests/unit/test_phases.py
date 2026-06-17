"""Phase executors unit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import AgentResult, derive_workflow_params
from ai_agent_orchestrator.phases.base import NoChangesError

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
    sm.get_workflow_params = MagicMock(side_effect=lambda key: derive_workflow_params(sm.get_issue_type(key)))
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
    req.repo_key = "org/app"
    req.issue_key = ("org/app", issue_number)
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

        mock_sm.set_issue_type.assert_called_with(("org/app", 1), "bug")
        mock_github.add_label.assert_called_once()
        mock_sm.transition.assert_called_with(("org/app", 1), "plan")

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

        mock_sm.set_issue_type.assert_called_with(("org/app", 1), "feature-m")
        mock_sm.transition.assert_called_with(("org/app", 1), "clarify")

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
        mock_sm.set_issue_type.assert_called_with(("org/app", 1), "bug")


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

        mock_sm.transition.assert_called_with(("org/app", 1), "plan")

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
        """NEEDS_SPLIT 出力時に SPLIT へ遷移する (U5c #95 動的エスカレーション)。

        mock_sm の既定 issue_type は feature-m (needs_split=False) だが、CLARIFY 中に
        エージェントが NEEDS_SPLIT を返したら INTAKE 判定を上書きして SPLIT へ昇格する。
        """
        mock_sm.get_issue_type.return_value = "feature-m"  # needs_split=False
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

        mock_sm.transition.assert_called_with(("org/app", 1), "split")


# ---------------------------------------------------------------------------
# AnalysisExecutor
# ---------------------------------------------------------------------------


class TestAnalysisExecutor:
    """PlanExecutor (light/bug) tests — 旧 AnalysisExecutor に相当."""

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
        """修正方針がコメント投稿され APPROVE に遷移する (旧 plan-review)。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="修正方針: null check漏れ",
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        mock_sm.get_issue_type.return_value = "bug"  # light モード
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        await executor.execute(request)

        mock_github.create_comment.assert_called_once()
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")


# ---------------------------------------------------------------------------
# DesignExecutor
# ---------------------------------------------------------------------------


class TestDesignExecutor:
    """PlanExecutor (full/feature-m) tests — 旧 DesignExecutor に相当."""

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
        """設計 PR が作成され APPROVE に遷移する (旧 DESIGN_REVIEW)。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(("org/app", 1), "approve")
        state = mock_sm.get_state(1)
        assert state.design_pr_number == 5

    async def test_full_prompt_includes_prototype_instruction(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """full プロンプトに UI プロトタイプ生成の指示が含まれる (#145)."""
        mock_sm.get_issue_type.return_value = "feature-m"
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        prompt = await executor.build_prompt(_make_request(phase="plan"))

        # Phase3: 2〜3 案 + サイドカー JSON 生成の指示が含まれる
        assert "prototype.<id>.html" in prompt
        assert "prototypes.json" in prompt
        assert "2〜3 案" in prompt
        assert "プロトタイプ" in prompt

    async def test_full_prompt_includes_prototype_feedback_section(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """prototype_feedback があると「設計書維持・プロトタイプのみ更新」節が入る (#145 Phase2)."""
        mock_sm.get_issue_type.return_value = "feature-m"
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        prompt = await executor.build_prompt(
            _make_request(phase="plan", extra={"prototype_feedback": "ボタンを大きく"})
        )

        assert "UI プロトタイプへの修正依頼" in prompt
        assert "ボタンを大きく" in prompt
        assert "原則そのまま維持" in prompt

    async def test_process_result_posts_claude_review_comment(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """設計 PR 作成後に @claude /review コメントが投稿される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        await executor.execute(request)

        # create_comment が呼ばれ、@claude /review を含むコメントが投稿される
        assert mock_github.create_comment.call_count >= 1
        review_calls = [
            call for call in mock_github.create_comment.call_args_list if "@claude /review" in str(call.args[2])
        ]
        assert len(review_calls) == 1
        # PR番号 5 に投稿されていることを確認
        assert review_calls[0].args[1] == 5

    async def test_process_result_comment_failure_does_not_block_transition(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """@claude /review コメント投稿失敗時も APPROVE 遷移が完了する (旧 DESIGN_REVIEW)。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_github.create_comment.side_effect = Exception("network error")
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        # 例外が発生してもクラッシュしない
        await executor.execute(request)

        # APPROVE への遷移は完了している
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")

    async def test_design_process_result_creates_pr_when_plan_valid(
        self,
        tmp_path: Any,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """有効な ## サブタスク計画がある場合、再生成なしで PR 作成・遷移する。"""
        worktree = tmp_path / "worktree"
        design_dir = worktree / "docs" / "designs"
        design_dir.mkdir(parents=True)
        (design_dir / "issue-1.md").write_text(
            "# 設計書\n\n本文。\n\n"
            "## サブタスク\n\n"
            "### subtask-1: 型定義\n"
            "- files: [`src/a.py`, `tests/test_a.py`]\n"
            "- depends_on: []\n"
            "- description: 型を定義する\n",
            encoding="utf-8",
        )
        mock_workspace.create_worktree.return_value = str(worktree)
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        result = mock_runner.run.return_value
        await executor.process_result(request, result)

        # 計画が有効なので再生成 (run_agent) は呼ばれない
        mock_runner.run.assert_not_called()
        # phase:approve ラベル設定・approve 遷移・PR 作成
        mock_github.replace_phase_label.assert_called_with(request.repo, 1, "phase:approve")
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")
        state = mock_sm.get_state(1)
        assert state.design_pr_number == 5
        # 警告コメントは投稿されない (@claude /review のみ)
        warn_calls = [call for call in mock_github.create_comment.call_args_list if "検証警告" in str(call.args[2])]
        assert warn_calls == []

    async def test_design_process_result_regenerates_when_plan_invalid(
        self,
        tmp_path: Any,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """## サブタスクが無い (検証NG) 場合、再生成され上限到達で警告続行する。"""
        worktree = tmp_path / "worktree"
        design_dir = worktree / "docs" / "designs"
        design_dir.mkdir(parents=True)
        # ## サブタスク を含まない → 検証NG (再生成しても直らない設定)
        (design_dir / "issue-1.md").write_text("# 設計書\n\n本文のみ。\n", encoding="utf-8")
        mock_workspace.create_worktree.return_value = str(worktree)
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import _MAX_DESIGN_REVALIDATE, PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        result = mock_runner.run.return_value
        await executor.process_result(request, result)

        # 再生成のため run_agent (FakeRunner.run) が呼ばれる (上限回数分)
        assert mock_runner.run.call_count == _MAX_DESIGN_REVALIDATE
        # 上限到達後は警告コメントが投稿される
        warn_calls = [call for call in mock_github.create_comment.call_args_list if "検証警告" in str(call.args[2])]
        assert len(warn_calls) == 1
        # approve へ進む
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")

    async def test_design_process_result_file_not_found_triggers_regeneration(
        self,
        tmp_path: Any,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """worktree に issue-N.md が存在しない場合、_validate_design_doc がファイル未検出エラーを返し、
        _revalidate_design が run_agent による再生成を試み、上限到達後に警告コメントを投稿する。"""
        worktree = tmp_path / "worktree_no_file"
        # docs/designs ディレクトリは存在するが issue-1.md は作成しない
        (worktree / "docs" / "designs").mkdir(parents=True)
        mock_workspace.create_worktree.return_value = str(worktree)
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #7 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full モード
        from ai_agent_orchestrator.phases.plan import (
            _MAX_DESIGN_REVALIDATE,
            PlanExecutor,
        )

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan", issue_number=1)
        result = mock_runner.run.return_value
        await executor.process_result(request, result)

        # ファイル未検出 → 再生成が上限回数分試行される
        assert mock_runner.run.call_count == _MAX_DESIGN_REVALIDATE

        # 上限到達後は警告コメントが投稿される
        warn_calls = [call for call in mock_github.create_comment.call_args_list if "検証警告" in str(call.args[2])]
        assert len(warn_calls) == 1, f"Expected 1 warning comment, got {len(warn_calls)}"

        # それでも approve への遷移は完了する
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")


# ---------------------------------------------------------------------------
# DesignReviseExecutor
# ---------------------------------------------------------------------------


class TestDesignReviseExecutor:
    """ReviseExecutor tests — 旧 DesignReviseExecutor / ImplReviseExecutor に相当."""

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
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-session",
            pr_number=None,
            design_pr_number=None,
            branch_head_sha=None,
        )
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="revise", extra={"comments": "要修正"})
        await executor.execute(request)

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args.kwargs
        assert call_kwargs["resume_session_id"] == "prev-session"


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

        mock_sm.transition.assert_called_with(("org/app", 1), "review")
        state = mock_sm.get_state(1)
        assert state.pr_number == 42

    def test_selected_prototype_hint(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
        tmp_path: Path,
    ) -> None:
        """選択済みなら採用案を実装プロンプトへ引き継ぐ節を返す (#145 Phase3)。"""
        from ai_agent_orchestrator.phases.implement import ImplementExecutor
        from ai_agent_orchestrator.prototype.selection import write_selection

        executor = ImplementExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        mock_workspace.base_dir = tmp_path

        # 未選択なら空文字
        assert executor._selected_prototype_hint(1) == ""

        # 選択済みなら採用案 id とファイルを示す
        write_selection(tmp_path, 1, "simple")
        hint = executor._selected_prototype_hint(1)
        assert "simple" in hint
        assert "issue-1.prototype.simple.html" in hint

    async def test_collect_evidence_called_in_finalize(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """_finalize から注入された evidence_collector.collect が呼ばれる。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="PR #42 を作成しました",
            tool_uses=[],
            cost_usd=3.0,
            duration_sec=120.0,
        )
        mock_context._read_impl_plan = AsyncMock(return_value=None)

        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        executor = ImplementExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        collector = AsyncMock()
        executor.evidence_collector = collector

        await executor.execute(_make_request(phase="implement"))

        collector.collect.assert_awaited_once()

    async def test_finalize_continues_when_evidence_fails(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """evidence_collector が例外を投げても PR 作成・遷移は継続する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="PR #42 を作成しました",
            tool_uses=[],
            cost_usd=3.0,
            duration_sec=120.0,
        )
        mock_context._read_impl_plan = AsyncMock(return_value=None)

        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        executor = ImplementExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        collector = AsyncMock()
        collector.collect.side_effect = RuntimeError("boom")
        executor.evidence_collector = collector

        await executor.execute(_make_request(phase="implement"))

        # エビデンス失敗を握り潰し review へ遷移する
        mock_sm.transition.assert_called_with(("org/app", 1), "review")


# ---------------------------------------------------------------------------
# FixExecutor
# ---------------------------------------------------------------------------


class TestFixExecutor:
    """ImplementExecutor (bug type / fix flow) tests — 旧 FixExecutor に相当."""

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
        """bug タイプの ImplementExecutor は修正完了後 REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="修正PR #7 を作成しました",
            tool_uses=[],
            cost_usd=2.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "bug"  # fix フローを通す
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

        # transition to review should be called (旧 impl-review)
        mock_sm.transition.assert_called_with(("org/app", 1), "review")
        # tracker should record phase_end (bug type fix flow)
        tracked_events = [c.args[0] for c in mock_tracker.track.call_args_list]
        assert "phase_end" in tracked_events
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

        mock_sm.increment_ci_retry.assert_called_with(("org/app", 1))

    def _make_ci_fix_executor(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> Any:
        from ai_agent_orchestrator.phases.ci_fix import CiFixExecutor

        return CiFixExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )

    async def test_increment_ci_retry_called_before_recover(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """increment_ci_retry が _finalize_phase_commit より先に呼ばれる."""
        call_order: list[str] = []

        async def fake_increment(issue_number: int) -> None:
            call_order.append("increment")

        mock_sm.increment_ci_retry = AsyncMock(side_effect=fake_increment)
        mock_workspace._run_git = AsyncMock(return_value=(0, "", ""))

        executor = self._make_ci_fix_executor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )

        async def patched_recover(*args: Any, **kwargs: Any) -> None:
            call_order.append("recover")

        executor._finalize_phase_commit = patched_recover  # type: ignore[method-assign]

        request = _make_request(phase="ci-fix")
        result = AgentResult(session_id="s1", output="fixed", tool_uses=[], cost_usd=0.1, duration_sec=5.0)
        await executor.process_result(request, result)

        assert call_order.index("increment") < call_order.index("recover")

    async def test_no_commit_under_retry_limit_does_not_suspend(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """エージェントがコミットしなくてもリトライ回数 < 3 なら RuntimeError が伝播しない."""
        state = mock_sm.get_state.return_value
        state.retry_count = 1

        executor = self._make_ci_fix_executor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )

        async def raise_runtime(*args: Any, **kwargs: Any) -> None:
            raise NoChangesError("no commit")

        executor._finalize_phase_commit = raise_runtime  # type: ignore[method-assign]

        request = _make_request(phase="ci-fix")
        result = AgentResult(session_id="s1", output="", tool_uses=[], cost_usd=0.1, duration_sec=5.0)

        await executor.process_result(request, result)
        mock_github.create_comment.assert_called_once()

    async def test_no_commit_at_retry_limit_raises(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """リトライ回数が 3 に達した場合は RuntimeError が伝播する."""
        state = mock_sm.get_state.return_value
        state.retry_count = 3

        executor = self._make_ci_fix_executor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )

        async def raise_runtime(*args: Any, **kwargs: Any) -> None:
            raise NoChangesError("no commit")

        executor._finalize_phase_commit = raise_runtime  # type: ignore[method-assign]

        request = _make_request(phase="ci-fix")
        result = AgentResult(session_id="s1", output="", tool_uses=[], cost_usd=0.1, duration_sec=5.0)

        with pytest.raises(RuntimeError, match="no commit"):
            await executor.process_result(request, result)

    async def test_successful_commit_keeps_ci_fix_label(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """正常コミット時に phase:ci-fix ラベルを維持する (ラベル変更しない)."""
        executor = self._make_ci_fix_executor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )

        async def ok_recover(*args: Any, **kwargs: Any) -> None:
            return

        executor._finalize_phase_commit = ok_recover  # type: ignore[method-assign]

        request = _make_request(phase="ci-fix")
        result = AgentResult(session_id="s1", output="fixed", tool_uses=[], cost_usd=0.1, duration_sec=5.0)
        await executor.process_result(request, result)

        # phase:ci-fix を維持するため replace_phase_label は呼ばれない
        mock_github.replace_phase_label.assert_not_called()


# ---------------------------------------------------------------------------
# ImplReviseExecutor
# ---------------------------------------------------------------------------


class TestImplReviseExecutor:
    """ReviseExecutor tests — 旧 ImplReviseExecutor に相当."""

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
        """セッション継続で実行され REVIEW に遷移する (旧 IMPL_REVIEW)。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-impl-session",
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
            answered_review_comment_ids=[],
            answered_review_ids=[],
        )
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="revise", extra={"comments": "変数名修正"})
        await executor.execute(request)

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args.kwargs
        assert call_kwargs["resume_session_id"] == "prev-impl-session"
        mock_sm.transition.assert_called_with(("org/app", 1), "review")

    async def test_process_result_sends_completion_reply_to_each_comment(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """process_result が各 review_comment_ids に完了通知を送る。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-impl-session",
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
            answered_review_comment_ids=[],
            answered_review_ids=[],
        )
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(
            phase="revise",
            extra={"comments": "変数名修正", "review_comment_ids": [101, 102]},
        )
        await executor.execute(request)

        # reply_to_review_comment が 2 回呼ばれる
        assert mock_github.reply_to_review_comment.call_count == 2
        call_ids = [mock_github.reply_to_review_comment.call_args_list[i].args[2] for i in range(2)]
        assert 101 in call_ids
        assert 102 in call_ids
        # U2: 定型文「修正が完了しました」は廃止。生成文 or サマリのフォールバックで返信する
        call_bodies = [mock_github.reply_to_review_comment.call_args_list[i].args[3] for i in range(2)]
        assert all("修正が完了しました。コードをご確認ください。" not in body for body in call_bodies)
        assert all(body.strip() for body in call_bodies)

    async def test_process_result_no_reply_when_review_comment_ids_empty(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """review_comment_ids が空の場合は reply_to_review_comment を呼ばない。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-impl-session",
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
            answered_review_comment_ids=[],
            answered_review_ids=[],
        )
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(
            phase="revise",
            extra={"comments": "変数名修正", "review_comment_ids": []},
        )
        await executor.execute(request)

        mock_github.reply_to_review_comment.assert_not_called()
        # REVIEW 遷移は継続する (旧 impl-review)
        mock_sm.transition.assert_called_with(("org/app", 1), "review")

    async def test_process_result_completion_reply_failure_does_not_block_transition(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """完了通知の失敗時も REVIEW 遷移・Slack 通知は継続する (旧 IMPL_REVIEW)。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id="prev-impl-session",
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
            answered_review_comment_ids=[],
            answered_review_ids=[],
        )
        mock_github.reply_to_review_comment.side_effect = Exception("network error")
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(
            phase="revise",
            extra={"comments": "変数名修正", "review_comment_ids": [101]},
        )
        # 例外が発生してもクラッシュしない
        await executor.execute(request)

        # REVIEW 遷移は完了している
        mock_sm.transition.assert_called_with(("org/app", 1), "review")
        # Slack 通知も送られている
        mock_notifier.notify.assert_called_once()

    async def test_build_prompt_includes_comment_count_note(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """build_prompt が複数コメントの件数注記を含むプロンプトを生成する。"""
        mock_sm.get_state.return_value = MagicMock(
            session_id=None,
            pr_number=10,
            design_pr_number=10,
            branch_head_sha=None,
        )
        from ai_agent_orchestrator.phases.revise import ReviseExecutor

        executor = ReviseExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(
            phase="revise",
            extra={
                "comments": "指摘A\n指摘B",
                "review_comment_ids": [101, 102, 103],
            },
        )
        prompt = await executor.build_prompt(request)

        # 件数注記が含まれる
        assert "3 件" in prompt
        assert "全ての指摘に対応" in prompt


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
        # 投稿本文に冪等化マーカーが埋め込まれる (#141)
        from ai_agent_orchestrator.phases.split import SPLIT_PROPOSAL_MARKER

        posted_body = mock_github.create_comment.call_args[0][2]
        assert SPLIT_PROPOSAL_MARKER in posted_body

    async def test_skips_repost_when_proposal_exists_without_modification(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """既存の分割提案があり修正指示も無ければ再投稿しない (#141)."""
        from ai_agent_orchestrator.phases.split import (
            SPLIT_PROPOSAL_MARKER,
            SplitProposalExecutor,
        )

        existing = MagicMock()
        existing.body = f"分割案です\n\n{SPLIT_PROPOSAL_MARKER}"
        existing.user = MagicMock(type="Bot", login="bot")
        mock_github.list_comments.return_value = [existing]

        executor = SplitProposalExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        await executor.execute(_make_request(phase="split-proposal"))

        mock_github.create_comment.assert_not_called()
        mock_notifier.notify.assert_not_called()

    async def test_reposts_when_human_modification_after_proposal(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_notifier: AsyncMock,
        mock_tracker: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: AsyncMock,
    ) -> None:
        """最新提案より後に人間の修正コメントがあれば再投稿する (#141)."""
        from ai_agent_orchestrator.phases.split import (
            SPLIT_PROPOSAL_MARKER,
            SplitProposalExecutor,
        )

        proposal = MagicMock()
        proposal.body = f"分割案です\n\n{SPLIT_PROPOSAL_MARKER}"
        proposal.user = MagicMock(type="Bot", login="bot")
        modification = MagicMock()
        modification.body = "サブタスクをもっと細かく分けてください"
        modification.user = MagicMock(type="User", login="human")
        mock_github.list_comments.return_value = [proposal, modification]

        executor = SplitProposalExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
        )
        await executor.execute(_make_request(phase="split-proposal"))

        mock_github.create_comment.assert_called_once()


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

        mock_sm.transition.assert_called_with(("org/app", 1), "done")
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

        mock_sm.transition.assert_called_with(("org/app", 1), "suspended")
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

        mock_sm.transition.assert_called_with(("org/app", 1), "suspended")
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
        mock_sm.get_issue_type.return_value = "bug"

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

        # 既存PRが見つかるのでreviewに遷移 (旧 impl-review)
        mock_sm.transition.assert_called_with(("org/app", 1), "review")
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

        # APIでPR作成 → reviewに遷移 (旧 impl-review)
        mock_github.create_pull_request.assert_called_once()
        mock_sm.transition.assert_called_with(("org/app", 1), "review")
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
        """設計フェーズ（PlanExecutor/feature-m）でもフォールバックPR作成が動作する。"""
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
        mock_sm.get_issue_type.return_value = "feature-m"

        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            mock_runner,
            mock_github,
            mock_notifier,
            mock_tracker,
            mock_workspace,
            mock_context,
            mock_sm,
        )
        request = _make_request(phase="plan")
        request.repo.base_branch = "main"
        await executor.execute(request)

        mock_github.create_pull_request.assert_called_once()
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")
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
        mock_sm.get_issue_type.return_value = "bug"

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

        # RuntimeError → _handle_error → suspended
        mock_sm.transition.assert_called_with(("org/app", 1), "suspended")
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
    """hearing 質問投稿後に clarify-wait へ遷移するテスト (旧 hearing-wait)."""

    async def test_hearing_question_transitions_to_hearing_wait(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """質問投稿後に clarify-wait へ遷移する (旧 hearing-wait)."""
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

        # clarify-wait へ遷移したことを確認 (旧 hearing-wait)
        mock_sm.transition.assert_called_once_with(("org/app", 42), "clarify-wait")
        # ラベルが clarify-wait に更新されたことを確認
        mock_github.replace_phase_label.assert_called_once()
        label_args = mock_github.replace_phase_label.call_args
        assert "phase:clarify-wait" in str(label_args)


# ---------------------------------------------------------------------------
# TestDesignPrLookup
# ---------------------------------------------------------------------------


class TestDesignPrLookup:
    """plan フェーズ (feature-m) の PR 検索テスト — 旧 design フェーズ."""

    async def test_ensure_pr_created_finds_feature_branch_pr(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """feature/issue-XX ブランチの PR を正しく検索できる."""
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        mock_sm.get_state.return_value = MagicMock(
            session_id=None,
            design_pr_number=None,
            pr_number=None,
            branch_head_sha=None,
        )
        mock_sm.get_issue_type.return_value = "feature-m"

        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_github.list_pull_requests = AsyncMock(return_value=[mock_pr])
        mock_github.get_issue = AsyncMock(return_value=MagicMock(title="Test", body="body"))
        mock_github.replace_phase_label = AsyncMock()
        mock_sm.transition = AsyncMock()

        executor = PlanExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("plan", issue_number=42)
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
        mock_sm.get_issue_type.return_value = "feature-m"

        from ai_agent_orchestrator.phases.plan import PlanExecutor

        executor = PlanExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("plan", issue_number=42)
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
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        mock_sm.get_phase.return_value = None  # DONE でない
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_sm.get_issue_type.return_value = "bug"
        mock_runner.run.side_effect = RuntimeError("テストエラー")

        executor = ImplementExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="implement")
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
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_sm.get_issue_type.return_value = "bug"
        mock_runner.run.side_effect = RuntimeError("テストエラー")
        mock_github.create_comment.side_effect = Exception("GitHub API エラー")

        executor = ImplementExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="implement")

        # create_comment が失敗しても例外が伝播しないこと
        await executor.execute(request)

        # suspended 遷移は完了していること
        mock_sm.transition.assert_called_with(("org/app", 1), "suspended")

    async def test_handle_error_survives_notifier_failure(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_error は notifier が失敗しても suspended 遷移を完了する。"""
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_sm.get_issue_type.return_value = "bug"
        mock_runner.run.side_effect = RuntimeError("テストエラー")
        mock_notifier.notify.side_effect = Exception("Slack 接続エラー")

        executor = ImplementExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="implement")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(("org/app", 1), "suspended")

    async def test_handle_timeout_tracks_phase_suspended_event(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """_handle_timeout が phase_suspended イベントを events.jsonl に記録する。"""
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_sm.get_issue_type.return_value = "bug"
        mock_runner.run.side_effect = TimeoutError()

        executor = ImplementExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="implement")
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
        from ai_agent_orchestrator.phases.implement import ImplementExecutor

        mock_sm.get_phase.return_value = None
        mock_sm.get_state.return_value = MagicMock(session_id=None, branch_head_sha=None)
        mock_sm.get_issue_type.return_value = "bug"
        mock_runner.run.side_effect = TimeoutError()

        executor = ImplementExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )
        request = _make_request(phase="implement")
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

        # パッケージの場所を動的に解決
        import ai_agent_orchestrator.orchestrator.orchestrator as _orch_mod

        source = pathlib.Path(_orch_mod.__file__).read_text()
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


# ---------------------------------------------------------------------------
# SPLIT 冪等化ヘルパ (#141)
# ---------------------------------------------------------------------------


class TestSplitReproposalHelpers:
    """_should_skip_reproposal / _is_proposal_comment の単体テスト (#141)."""

    @staticmethod
    def _comment(body: str, user_type: str = "User") -> MagicMock:
        c = MagicMock()
        c.body = body
        c.user = MagicMock(type=user_type, login="u")
        return c

    def test_no_existing_proposal_does_not_skip(self) -> None:
        from ai_agent_orchestrator.phases.split import _should_skip_reproposal

        comments = [self._comment("ヒアリング回答です", "User")]
        assert _should_skip_reproposal(comments) is False

    def test_existing_proposal_without_modification_skips(self) -> None:
        from ai_agent_orchestrator.phases.split import (
            SPLIT_PROPOSAL_MARKER,
            _should_skip_reproposal,
        )

        comments = [self._comment(f"案\n{SPLIT_PROPOSAL_MARKER}", "Bot")]
        assert _should_skip_reproposal(comments) is True

    def test_modification_after_proposal_does_not_skip(self) -> None:
        from ai_agent_orchestrator.phases.split import (
            SPLIT_PROPOSAL_MARKER,
            _should_skip_reproposal,
        )

        comments = [
            self._comment(f"案\n{SPLIT_PROPOSAL_MARKER}", "Bot"),
            self._comment("もっと細かく", "User"),
        ]
        assert _should_skip_reproposal(comments) is False

    def test_human_modification_mentioning_keyword_still_reposts(self) -> None:
        """人間の修正コメントが『分割案』等を含んでも提案と誤判定せず再投稿する (#141)."""
        from ai_agent_orchestrator.phases.split import (
            SPLIT_PROPOSAL_MARKER,
            _should_skip_reproposal,
        )

        comments = [
            self._comment(f"案\n{SPLIT_PROPOSAL_MARKER}", "Bot"),
            self._comment("この分割案をもっと細かく分けてください", "User"),
        ]
        assert _should_skip_reproposal(comments) is False

    def test_legacy_proposal_without_marker_is_detected(self) -> None:
        """マーカー導入前 (#141 以前) の提案も後方互換キーワードで検出する."""
        from ai_agent_orchestrator.phases.split import _should_skip_reproposal

        comments = [self._comment("Issue分割提案\n| # | タイトル |", "Bot")]
        assert _should_skip_reproposal(comments) is True

    def test_empty_comments_does_not_skip(self) -> None:
        from ai_agent_orchestrator.phases.split import _should_skip_reproposal

        assert _should_skip_reproposal([]) is False
