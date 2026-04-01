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

        Raises:
            RuntimeError: 設計書または実装計画がコンテキストに含まれない場合。
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
            "implement",
        )

        # 設計書・実装計画がコンテキストに含まれているか検証
        if "## 設計書" not in context:
            msg = (
                f"Issue #{request.issue_number}: "
                "設計書がコンテキストに含まれていません。"
                "設計フェーズが完了しているか確認してください。"
            )
            raise RuntimeError(msg)
        if "## 実装計画" not in context:
            msg = (
                f"Issue #{request.issue_number}: "
                "実装計画がコンテキストに含まれていません。"
                "計画フェーズが完了しているか確認してください。"
            )
            raise RuntimeError(msg)

        return (
            f"以下の設計書と実装計画に基づいてコードを実装してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{context}\n\n"
            f"## 実装指示\n"
            f"1. 実装計画の順序に従ってコードを実装\n"
            f"2. テストコードも作成\n"
            f"3. テスト・lint・ビルドを実行して確認\n"
            f"4. git commit して Push (コミットメッセージは日本語で)\n"
            f"5. PRを作成 (タイトル・本文は日本語で)\n"
            f"6. PR descriptionに変更概要を含める"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """PR 作成結果を処理 -> IMPL_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="機能: ",
        )

        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
