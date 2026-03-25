"""完了処理フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.models import AgentResult
from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import TaskRequest

logger = logging.getLogger(__name__)


class DoneExecutor(PhaseExecutor):
    """完了フェーズ。

    PR マージ + Issue クローズ + worktree 削除を行う。
    エージェント実行は不要。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """プロンプトは不要。空文字列を返す。

        Args:
            request: タスクリクエスト。

        Returns:
            空文字列。
        """
        return ""

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """エージェント実行は不要。ダミーの AgentResult を返す。

        Args:
            request: タスクリクエスト。
            prompt: プロンプト (使用しない)。

        Returns:
            ダミーの AgentResult。
        """
        return AgentResult(
            session_id="",
            output="",
            tool_uses=[],
            cost_usd=0.0,
            duration_sec=0.0,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """PR マージ、Issue クローズ、worktree 削除を実行する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果 (使用しない)。
        """
        state = self._sm.get_state(request.issue_number)
        client = await self._get_client(request.repo)

        # PR マージ
        if state and state.pr_number is not None:
            await client.merge_pull_request(request.repo, state.pr_number)

        # Issue クローズ
        await client.close_issue(request.repo, request.issue_number)

        # worktree 削除
        await self._workspace.remove_worktree(request.repo, request.issue_number)

        await self._notifier.notify(
            f"Issue #{request.issue_number} 完了しました",
            metadata={"issue": request.issue_number},
        )
