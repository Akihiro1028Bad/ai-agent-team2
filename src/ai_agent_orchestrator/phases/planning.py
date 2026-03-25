"""実装計画作成フェーズ (Feature-M)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class PlanningExecutor(PhaseExecutor):
    """実装計画作成フェーズ。

    設計書に基づいてファイル変更順序と依存関係を整理し、
    実装計画を docs/designs/issue-XX-plan.md に保存する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """実装計画用プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "planning",
        )

        return (
            f"設計書に基づき、実装計画を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 設計書を読み込む\n"
            f"2. 変更するファイルの一覧と順序を決定\n"
            f"3. 各ファイルの変更内容を具体的に記述\n"
            f"4. 依存関係の順序 (先に変更すべきファイル) を明記\n"
            f"5. テスト方針を決定\n"
            f"6. docs/designs/issue-{request.issue_number}-plan.md に実装計画を保存\n"
            f"7. git commit して Push"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """実装計画作成結果を処理 -> IMPLEMENT 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:implement")
        await self._sm.transition(request.issue_number, "implement")
