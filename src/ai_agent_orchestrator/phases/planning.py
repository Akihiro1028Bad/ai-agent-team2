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
            issue_number=request.issue_number,
        )

        return (
            f"設計書に基づき、実装計画を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 設計書を読み込む\n"
            f"2. 変更するファイルを **サブタスク単位** (1サブタスク = 2〜4ファイル) に分割する\n"
            f"3. 依存関係に従ってサブタスクの順序を決定する\n"
            f"   (例: 型定義 → リポジトリ層 → サービス層 → コンポーネント → テスト)\n"
            f"4. 各サブタスクの変更内容を具体的に記述する\n"
            f"5. 実装計画を docs/designs/issue-{request.issue_number}-plan.md に保存する\n"
            f"6. git commit して Push\n\n"
            f"## 実装計画ファイルのフォーマット (必ず守ること)\n\n"
            f"計画ファイルには以下の `## サブタスク` セクションを含めること。\n"
            f"このセクションは実装フェーズが自動的に読み取るため、フォーマットを正確に守ること。\n\n"
            f"```markdown\n"
            f"## サブタスク\n\n"
            f"### subtask-1: <タイトル>\n"
            f"- files: [`path/to/a.py`, `path/to/b.py`]\n"
            f"- depends_on: []\n"
            f"- description: このサブタスクで行う作業の説明\n\n"
            f"### subtask-2: <タイトル>\n"
            f"- files: [`path/to/c.py`, `path/to/d.py`]\n"
            f"- depends_on: [1]\n"
            f"- description: このサブタスクで行う作業の説明\n"
            f"```\n\n"
            f"## サブタスク分割の原則\n"
            f"- 1サブタスクに含めるファイルは **2〜4ファイル** を目安にする\n"
            f"- 依存する型・インターフェースを先のサブタスクで定義する\n"
            f"- テストファイルは最後のサブタスクにまとめる\n"
            f"- `depends_on` には依存するサブタスクの番号 (整数) を列挙する\n"
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

        await self._recover_uncommitted_work(request, branch_prefix="feature")

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:implement")
        await self._sm.transition(request.issue_number, "implement")
