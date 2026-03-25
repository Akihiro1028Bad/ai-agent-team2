"""コード実装フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class ImplementExecutor(PhaseExecutor):
    """コード実装フェーズ。

    実装計画に基づいてコードを実装し、テスト・lint を実行した上で
    PR を作成する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """実装プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "implement",
        )

        return (
            f"実装計画に基づいてコードを実装してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 実装計画の順序に従ってコードを実装\n"
            f"2. テストコードも作成\n"
            f"3. テスト・lint・ビルドを実行して確認\n"
            f"4. git commit して Push\n"
            f"5. PRを作成\n"
            f"6. PR descriptionに変更概要を含める"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """PR 作成結果を処理 -> IMPL_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PRを作成しました",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
