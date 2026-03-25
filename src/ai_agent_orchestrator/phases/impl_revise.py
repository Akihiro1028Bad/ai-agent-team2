"""実装修正フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class ImplReviseExecutor(PhaseExecutor):
    """実装のレビュー指摘対応フェーズ (セッション継続)。

    既存セッションを resume してレビュー指摘に対応し、
    IMPL_REVIEW に再遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """レビュー指摘対応プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        extra = getattr(request, "extra", {}) or {}
        comments = extra.get("comments", "")
        return f"以下のレビュー指摘に対応してください:\n{comments}"

    async def run_agent(
        self, request: TaskRequest, prompt: str
    ) -> AgentResult:
        """セッション継続で実行する。

        Args:
            request: タスクリクエスト。
            prompt: プロンプト。

        Returns:
            エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="impl_revise",
            resume_session_id=(
                state.session_id if state else None
            ),
        )

    async def process_result(
        self, request: TaskRequest, result: AgentResult
    ) -> None:
        """修正結果を処理 -> IMPL_REVIEW に再遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装を修正しました",
            metadata={"issue": request.issue_number},
        )
