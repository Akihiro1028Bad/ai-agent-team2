"""設計書作成フェーズ (Feature-M)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class DesignExecutor(PhaseExecutor):
    """Feature-M 設計書作成フェーズ。

    設計書を docs/designs/issue-XX.md に作成し、設計 PR を作成する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """設計書作成プロンプトを構築する。

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
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "design",
            issue_number=request.issue_number,
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

        return (
            f"以下のIssueの設計書を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. docs/designs/issue-{request.issue_number}.md に設計書を作成\n"
            f"2. git commit して Push (コミットメッセージは日本語で)\n"
            f"3. PRを作成 (タイトル・本文は日本語で)\n"
            f"4. PRのURLを出力"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """設計 PR 作成結果を処理 -> DESIGN_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="設計: ",
        )

        state = self._sm.get_state(request.issue_number)
        if state:
            state.design_pr_number = pr_number
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:design-review")
        await self._sm.transition(request.issue_number, "design-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計PR #{pr_number} を作成しました。レビューをお願いします",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
