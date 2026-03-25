"""簡易方針作成フェーズ (Feature-S)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class PlanBriefExecutor(PhaseExecutor):
    """Feature-S 簡易方針作成フェーズ。

    変更内容とテスト方針を Issue コメントで共有し、
    thumbsup リアクションで承認を待つ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """簡易方針プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "plan_brief",
        )
        comments = await client.list_comments(request.repo, request.issue_number)
        hearing_log = (
            "\n".join(
                f"[{getattr(c.user, 'login', 'unknown')}]: {c.body}"
                for c in comments
                if hasattr(c, "user") and hasattr(c, "body")
            )
            if comments
            else ""
        )

        extra = getattr(request, "extra", {}) or {}
        feedback = extra.get("feedback", "")
        feedback_section = f"\n## 前回の方針に対する指摘\n{feedback}" if feedback else ""

        return (
            f"以下のIssueの簡易実装方針を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n"
            f"{feedback_section}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 出力形式 (Markdownテキスト)\n"
            f"実装方針を出力してください。"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """方針をコメント投稿 -> PLAN_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        comment_body = (
            result.output.strip()
            if result.output.strip()
            else ("方針を作成しましたが、出力が空でした。再実行が必要です。")
        )
        await client.create_comment(request.repo, request.issue_number, comment_body)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:plan-review")
        await self._sm.transition(request.issue_number, "plan-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装方針を投稿しました。thumbsup で承認をお願いします",
            metadata={"issue": request.issue_number},
        )
