"""Feature-L 分割フェーズ (提案 + 実行)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class SplitProposalExecutor(PhaseExecutor):
    """Feature-L 分割提案フェーズ。

    大規模 Issue を複数の子 Issue に分割する提案を作成し、
    コメントとして投稿して承認を待つ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """分割提案プロンプトを構築する。

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
            "split_proposal",
        )
        comments = await client.list_comments(request.repo, request.issue_number)
        hearing_log = (
            "\n".join(
                f"[{getattr(c.user, 'login', 'unknown')}]: {c.body}"
                for c in comments
                if hasattr(c, "user") and hasattr(c, "body")
            )
            if comments
            else ""
        )

        return (
            f"以下の大規模Issueを複数の子Issueに分割する提案を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. 機能を論理的に分割可能なサブタスクに分解\n"
            f"2. 各サブタスクの依存関係を明記\n"
            f"3. 各サブタスクのタイプ (feature-s / feature-m) を判定\n"
            f"4. 実装順序を決定"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """分割提案をコメント投稿。承認待ち。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        comment_body = (
            result.output.strip()
            if result.output.strip()
            else ("分割提案を作成しましたが、出力が空でした。再実行が必要です。")
        )
        await client.create_comment(request.repo, request.issue_number, comment_body)
        # 承認待ち (SPLIT_PROPOSAL フェーズのまま)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割を提案しました。判断をお願いします",
            metadata={"issue": request.issue_number},
        )


class SplitExecuteExecutor(PhaseExecutor):
    """Feature-L 分割実行フェーズ。

    承認された分割案に基づいて子 Issue を作成する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """分割実行プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        comments = await client.list_comments(request.repo, request.issue_number)

        # 分割提案コメントを取得
        split_proposal = ""
        for c in reversed(comments):
            body = getattr(c, "body", "")
            user = getattr(c, "user", None)
            user_type = getattr(user, "type", "") if user else ""
            if user_type == "Bot" and "Issue分割提案" in body:
                split_proposal = body
                break

        return (
            f"承認された分割案に基づいて子Issueを作成してください。\n\n"
            f"## 親Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## 承認された分割案\n{split_proposal}\n\n"
            f"## 指示\n"
            f"1. 分割案の各サブタスクについて子Issueを作成\n"
            f"2. 各子Issueにラベルを付与\n"
            f"3. 親Issueに分割完了コメントを投稿\n"
            f"4. 作成した子Issue番号のリストを出力"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """分割完了 -> DONE 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        client = await self._get_client(request.repo)
        output_text = result.output.strip() if result.output.strip() else ("(出力なし)")
        await client.create_comment(
            request.repo,
            request.issue_number,
            f"分割が完了しました。子Issueが作成されています。\n\n{output_text}",
        )
        await client.replace_phase_label(request.repo, request.issue_number, "phase:done")
        await self._sm.transition(request.issue_number, "done")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割が完了しました",
            metadata={"issue": request.issue_number},
        )
