"""Bug 修正フェーズ (Bug 専用)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class FixExecutor(PhaseExecutor):
    """Bug 修正フェーズ。

    承認された修正方針に基づいてバグを修正し、テストを作成して PR を作成する。

    重要: process_result() は IMPL_REVIEW に遷移しない。
    CI 結果を Poller が検知し、EventRouter が CI_PASSED なら IMPL_REVIEW に、
    CI_FAILED なら CI_FIX に遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """Bug 修正プロンプトを構築する。

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
            "fix",
        )

        # 方針コメントを取得
        comments = await self._github.list_comments(
            request.repo, request.issue_number
        )
        plan_comment = ""
        for c in reversed(comments):
            body = getattr(c, "body", "")
            user = getattr(c, "user", None)
            user_type = getattr(user, "type", "") if user else ""
            if user_type == "Bot" and "修正方針" in body:
                plan_comment = body
                break

        return (
            f"承認された修正方針に基づいてバグを修正してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## 承認された修正方針\n{plan_comment}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 修正方針に従ってコードを修正\n"
            f"2. 再現テスト・リグレッションテストを作成\n"
            f"3. テスト・lint を実行して確認\n"
            f"4. git commit して Push\n"
            f"5. PRを作成\n"
            f"6. PR descriptionに修正方針を再掲"
        )

    async def process_result(
        self, request: TaskRequest, result: AgentResult
    ) -> None:
        """修正結果を処理。遷移は行わず CI 結果を待つ。

        FixExecutor は IMPL_REVIEW への遷移を行わない。
        git push 後に CI が自動実行され、Poller が CI 結果を検知し、
        EventRouter が適切なフェーズに遷移する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        # 遷移は行わない。CI結果をPollerが検知してから遷移する。
        await self._tracker.track(
            "fix_complete",
            issue_number=request.issue_number,
            note="CI結果待ち",
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正PRを作成しました。"
            f"CI結果待ちです",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
