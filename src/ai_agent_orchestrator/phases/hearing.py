"""ヒアリングフェーズ."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class HearingExecutor(PhaseExecutor):
    """要件ヒアリングフェーズ。

    Issue 内容を分析し、不明点があれば質問を投稿する。
    情報が十分であれば、タイプに応じた次フェーズへ自動遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """ヒアリング用プロンプトを構築する。

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
            branch_prefix="design",
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "hearing",
        )

        # 過去のコメント (ヒアリング回答) も含める
        comments = await client.list_comments(request.repo, request.issue_number)
        hearing_log = (
            "\n".join(
                f"[{getattr(c.user, 'login', 'unknown')}]: {c.body}"
                for c in comments
                if hasattr(c, "user") and hasattr(c, "body")
            )
            if comments
            else "(なし)"
        )

        return (
            f"以下のIssueについて要件ヒアリングを行ってください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## これまでのやりとり\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. Issueの内容を分析し、実装に必要な情報が十分か判断\n"
            f"2. 不明点がある場合は具体的な質問をリストアップ\n"
            f'3. 情報が十分な場合は "READY" と出力\n'
            f'4. Issueが大きすぎて分割すべき場合は "NEEDS_SPLIT" と出力\n\n'
            f"出力形式:\n"
            f"- 質問がある場合: Issueコメントとして投稿する質問テキスト\n"
            f'- 準備完了: "READY"\n'
            f'- 分割推奨: "NEEDS_SPLIT"'
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """ヒアリング結果を処理: 質問投稿 or 次フェーズ遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        # セッションID を記録
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        issue_type = self._sm.get_issue_type(request.issue_number)
        client = await self._get_client(request.repo)

        if "READY" in result.output:
            # タイプ別の次フェーズへ遷移
            next_phase_map: dict[str, str] = {
                "bug": "analysis",
                "feature-s": "plan-brief",
                "feature-m": "design",
                "feature-l": "split-proposal",
            }
            next_phase = next_phase_map.get(issue_type, "design")
            await client.replace_phase_label(request.repo, request.issue_number, f"phase:{next_phase}")
            await self._sm.transition(request.issue_number, next_phase)
        elif "NEEDS_SPLIT" in result.output:
            await client.replace_phase_label(request.repo, request.issue_number, "phase:split-proposal")
            await self._sm.transition(request.issue_number, "split-proposal")
        else:
            # 質問を Issue コメントとして投稿
            comment_body = (
                result.output.strip()
                if result.output.strip()
                else ("ヒアリングを実行しましたが、出力が空でした。再実行が必要です。")
            )
            await client.create_comment(request.repo, request.issue_number, comment_body)
            # hearing-wait へ遷移（ユーザー回答待ち）
            await client.replace_phase_label(request.repo, request.issue_number, "phase:hearing-wait")
            await self._sm.transition(request.issue_number, "hearing-wait")
            await self._notifier.notify(
                f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
                metadata={
                    "issue": request.issue_number,
                },
            )
