"""Bug 分析フェーズ."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class AnalysisExecutor(PhaseExecutor):
    """Bug 分析フェーズ。

    Issue 内容からバグの原因を特定し、修正方針をコメントとして投稿する。
    方針に対する thumbsup リアクションで承認を待つ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """Bug 分析用プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        issue = await self._github.get_issue(
            request.repo, request.issue_number
        )
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "analysis",
        )

        extra = getattr(request, "extra", {}) or {}
        feedback = extra.get("feedback", "")
        feedback_section = (
            f"\n## 前回の方針に対する指摘\n{feedback}" if feedback else ""
        )

        return (
            f"以下のバグIssueを分析し、修正方針を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n"
            f"{feedback_section}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 出力形式 (Markdownテキスト)\n"
            f"修正方針を出力してください。"
        )

    async def process_result(
        self, request: TaskRequest, result: AgentResult
    ) -> None:
        """分析結果を Issue コメント投稿 -> PLAN_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._github.create_comment(
            request.repo, request.issue_number, result.output
        )
        await self._sm.transition(request.issue_number, "plan-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正方針を投稿しました。"
            f"thumbsup で承認をお願いします",
            metadata={"issue": request.issue_number},
        )
