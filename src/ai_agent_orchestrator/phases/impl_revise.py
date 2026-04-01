"""実装修正フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class ImplReviseExecutor(PhaseExecutor):
    """実装のレビュー指摘対応フェーズ (セッション継続)。

    既存セッションを resume してレビュー指摘に対応し、
    IMPL_REVIEW に再遷移する。
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

        # PR 番号を取得 (state から、なければ API 検索)
        state = self._sm.get_state(request.issue_number)
        pr_info = ""
        if state and state.pr_number:
            pr_info = f"PR #{state.pr_number}"
        else:
            repo_any = cast("Any", request.repo)
            prs = await client.list_pull_requests(
                request.repo,
                head=f"{repo_any.owner}:feature/issue-{request.issue_number}",
            )
            if prs:
                pr_info = f"PR #{cast('Any', prs[0]).number}"

        return (
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{pr_info} に対するレビュー指摘に対応してください。\n\n"
            f"## レビュー指摘内容\n{comments}\n\n"
            f"## 指示\n"
            f"1. レビュー指摘に基づいてコードを修正する\n"
            f"2. テスト・lint・ビルドを実行して確認する\n"
            f"3. git commit して push する (コミットメッセージは日本語で)\n"
        )

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """セッション継続で実行する。

        Args:
            request: タスクリクエスト。
            prompt: プロンプト。

        Returns:
            エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="impl_revise",
            resume_session_id=(state.session_id if state else None),
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正結果を処理 -> IMPL_REVIEW に再遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._recover_uncommitted_work(request, branch_prefix="feature")

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(request.issue_number, "impl-review")
        repo_full_name = self._get_repo_full_name(request)
        state_data = self._sm.get_state(request.issue_number)
        impl_pr = state_data.pr_number if state_data else None
        pr_url_val = None
        if impl_pr:
            owner = getattr(request.repo, "owner", "")
            repo_name = getattr(request.repo, "repo", "")
            if owner and repo_name:
                pr_url_val = f"https://github.com/{owner}/{repo_name}/pull/{impl_pr}"
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装を修正しました",
            metadata={
                "notification_type": "impl_revised",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "pr": impl_pr,
                "pr_url": pr_url_val,
                "repo": repo_full_name,
                "next_action": "→ 実装PRを再レビューしてください",
            },
        )
