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

    process_result() は IMPL_REVIEW に遷移し、state.json を更新する。
    これにより再起動時の再実行を防止する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """Bug 修正プロンプトを構築する。

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
            "fix",
        )

        # 方針コメントを取得
        comments = await client.list_comments(request.repo, request.issue_number)
        plan_comment = ""
        for c in reversed(comments):
            body = getattr(c, "body", "")
            if "修正方針" in body:
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

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正結果を処理し IMPL_REVIEW に遷移する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        # IMPL_REVIEW に遷移してラベルを更新
        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(request.issue_number, "impl-review")
        await self._tracker.track(
            "fix_complete",
            issue_number=request.issue_number,
            phase="fix",
            data={"note": "impl-review に遷移"},
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正PRを作成しました。レビュー待ちです",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
