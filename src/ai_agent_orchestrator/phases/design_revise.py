"""設計書修正フェーズ (Feature-M)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class DesignReviseExecutor(PhaseExecutor):
    """設計書のレビュー指摘対応フェーズ (セッション継続)。

    既存セッションを resume して設計書を修正し、
    DESIGN_REVIEW に再遷移する。
    設計・実装は同一ブランチ (feature/issue-XX) で管理する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """レビュー指摘対応プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        extra = getattr(request, "extra", {}) or {}
        comments = extra.get("comments", "")

        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)

        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        raw = (
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"設計書 (docs/designs/issue-{request.issue_number}.md) に対する"
            f"レビュー指摘に対応してください。\n\n"
            f"## レビュー指摘内容\n{comments}\n\n"
            f"## 指示\n"
            f"1. 設計書を修正する\n"
            f"2. git add && git commit (コミットメッセージは日本語で)\n"
            f"3. git push origin feature/issue-{request.issue_number}\n"
        )
        return enhance_prompt(raw, "design-revise")

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """セッション継続で実行する。

        Args:
            request: タスクリクエスト。
            prompt: プロンプト。

        Returns:
            エージェント実行結果。
        """
        state = self._sm.get_state(self._issue_key(request))
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="design-revise",
            resume_session_id=(state.session_id if state else None),
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正結果を処理 -> DESIGN_REVIEW に再遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        await self._recover_uncommitted_work(request, branch_prefix="feature")

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:design-review")
        await self._sm.transition(self._issue_key(request), "design-review")
        repo_full_name = self._get_repo_full_name(request)
        state_data = self._sm.get_state(self._issue_key(request))
        design_pr = state_data.design_pr_number if state_data else None
        pr_url_val = self._build_pr_url(request, design_pr) if design_pr else None
        issue = await client.get_issue(request.repo, request.issue_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計書を修正しました",
            metadata={
                "notification_type": "design_revised",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "pr": design_pr,
                "pr_url": pr_url_val,
                "repo": repo_full_name,
                "next_action": "→ 設計PRを再レビューしてください",
            },
        )
