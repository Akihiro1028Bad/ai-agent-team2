"""実装修正フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

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
        raw_comments = extra.get("comments", "")

        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)

        # PR 番号を取得 (state から、なければ API 検索)
        state = self._sm.get_state(self._issue_key(request))
        pr_info = ""
        if state and state.pr_number:
            pr_info = f"PR #{state.pr_number}"
        else:
            repo_any: Any = request.repo
            prs = await client.list_pull_requests(
                request.repo,
                head=f"{repo_any.owner}:feature/issue-{request.issue_number}",
            )
            if prs:
                first_pr: Any = prs[0]
                pr_info = f"PR #{first_pr.number}"

        # 複数コメントの件数をプロンプトに明示
        comment_count_note = ""
        review_comment_ids = extra.get("review_comment_ids", [])
        if review_comment_ids:
            comment_count_note = (
                f"\n\n**注意**: 今回は **{len(review_comment_ids)} 件**のレビュー指摘があります。"
                "全ての指摘に対応してください。"
            )

        # レビューコメントを優先度分類
        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt
        from ai_agent_orchestrator.phases.review_classifier import (
            classify_review_comments,
            format_classified_comments,
        )

        classified_section: str
        if isinstance(raw_comments, list):
            classified = classify_review_comments(raw_comments)
            classified_section = format_classified_comments(classified)
        else:
            classified_section = f"## レビュー指摘内容\n{raw_comments}"

        raw = (
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{pr_info} に対するレビュー指摘に対応してください。{comment_count_note}\n\n"
            f"{classified_section}\n\n"
            f"## 指示\n"
            f"1. 全てのレビュー指摘に基づいてコードを修正する\n"
            f"2. テスト・lint・ビルドを実行して確認する\n"
            f"3. git commit して push する (コミットメッセージは日本語で)\n"
        )
        return enhance_prompt(raw, "impl-revise")

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
            phase="impl-revise",
            resume_session_id=(state.session_id if state else None),
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正結果を処理 -> IMPL_REVIEW に再遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        await self._recover_uncommitted_work(request, branch_prefix="feature")

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(self._issue_key(request), "impl-review")
        repo_full_name = self._get_repo_full_name(request)
        state_data = self._sm.get_state(self._issue_key(request))
        impl_pr = state_data.pr_number if state_data else None
        pr_url_val = self._build_pr_url(request, impl_pr) if impl_pr else None

        # 完了通知: 各レビューコメントのスレッドに返信
        extra = getattr(request, "extra", {}) or {}
        review_comment_ids: list[int] = extra.get("review_comment_ids", [])
        if impl_pr and review_comment_ids:
            await self._reply_completion_to_review_comments(request, impl_pr, review_comment_ids)
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

    async def _reply_completion_to_review_comments(
        self,
        request: TaskRequest,
        pr_number: int,
        comment_ids: list[int],
    ) -> None:
        """修正完了を各レビューコメントのスレッドに返信する。

        Args:
            request: タスクリクエスト。
            pr_number: PR 番号。
            comment_ids: 返信先レビューコメント ID のリスト。
        """
        try:
            client = await self._get_client(request.repo)
        except Exception:
            logger.debug(
                "Issue #%d: failed to get client for review comment replies",
                request.issue_number,
                exc_info=True,
            )
            return
        for comment_id in comment_ids:
            try:
                await client.reply_to_review_comment(
                    request.repo,
                    pr_number,
                    comment_id,
                    "修正が完了しました。コードをご確認ください。",
                )
            except Exception:
                logger.debug(
                    "Issue #%d: failed to reply to review comment %d",
                    request.issue_number,
                    comment_id,
                    exc_info=True,
                )
