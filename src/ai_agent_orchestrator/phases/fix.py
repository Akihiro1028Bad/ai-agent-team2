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
            issue_number=request.issue_number,
        )

        # 方針コメントを取得
        comments = await client.list_comments(request.repo, request.issue_number)
        plan_comment = ""
        for c in reversed(comments):
            body = getattr(c, "body", "")
            if "修正方針" in body:
                plan_comment = body
                break

        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        raw = (
            f"承認された修正方針に基づいてバグを修正してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## 承認された修正方針\n{plan_comment}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 修正方針に従ってコードを修正\n"
            f"2. 再現テスト・リグレッションテストを作成\n"
            f"3. テスト・lint を実行して確認\n"
            f"4. git commit して Push (コミットメッセージは日本語で)\n"
            f"5. PRを作成 (タイトル・本文は日本語で)\n"
            f"6. PR descriptionに修正方針を再掲"
        )
        return enhance_prompt(raw, "fix")

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正結果を処理し IMPL_REVIEW に遷移する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        await self._recover_uncommitted_work(request, branch_prefix="feature")

        # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="修正: ",
        )

        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        # IMPL_REVIEW に遷移してラベルを更新
        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(self._issue_key(request), "impl-review")
        await self._tracker.track(
            "fix_complete",
            issue_number=request.issue_number,
            phase="fix",
            data={"note": "impl-review に遷移", "pr_number": pr_number},
        )
        repo_full_name = self._get_repo_full_name(request)
        pr_url = self._build_pr_url(request, pr_number)
        issue = await client.get_issue(request.repo, request.issue_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正PR #{pr_number} を作成しました",
            metadata={
                "notification_type": "fix_pr_created",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "pr": pr_number,
                "pr_url": pr_url,
                "repo": repo_full_name,
                "next_action": "→ 修正PRをレビューしてください",
            },
        )
