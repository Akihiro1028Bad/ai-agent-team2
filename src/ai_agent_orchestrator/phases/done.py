"""完了処理フェーズ (共通)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ai_agent_orchestrator.models import AgentResult
from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import TaskRequest

logger = logging.getLogger(__name__)

# 子Issueタイトルの親Issue参照パターン: (#39-3) のような形式
_CHILD_ISSUE_PATTERN = re.compile(r"\(#(\d+)-(\d+)\)\s*$")


class DoneExecutor(PhaseExecutor):
    """完了フェーズ。

    PR マージ + Issue クローズ + worktree 削除を行う。
    エージェント実行は不要。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """プロンプトは不要。空文字列を返す。

        Args:
            request: タスクリクエスト。

        Returns:
            空文字列。
        """
        return ""

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """エージェント実行は不要。ダミーの AgentResult を返す。

        Args:
            request: タスクリクエスト。
            prompt: プロンプト (使用しない)。

        Returns:
            ダミーの AgentResult。
        """
        return AgentResult(
            session_id="",
            output="",
            tool_uses=[],
            cost_usd=0.0,
            duration_sec=0.0,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """PR マージ、Issue クローズ、worktree 削除を実行する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果 (使用しない)。
        """
        client = await self._get_client(request.repo)

        # フェーズラベルを更新
        await client.replace_phase_label(request.repo, request.issue_number, "phase:done")

        # Issue クローズ
        await client.close_issue(request.repo, request.issue_number)

        # worktree 削除
        await self._workspace.remove_worktree(request.repo, request.issue_number)

        repo_full_name = self._get_repo_full_name(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number} 完了しました",
            metadata={
                "notification_type": "done",
                "issue": request.issue_number,
                "repo": repo_full_name,
            },
        )

        # 子Issueの場合、次の子Issueに ai-agent ラベルを付けて連鎖起動
        await self._chain_next_child_issue(request, client)

    async def _chain_next_child_issue(self, request: TaskRequest, client: object) -> None:
        """完了した子Issueの次の子Issueに ai-agent ラベルを付ける.

        タイトルが「〜 (#親番号-N)」形式の場合、同じ親の (#親番号-(N+1)) を探して
        ai-agent ラベルを付与し、連鎖的に処理を開始する。

        Args:
            request: タスクリクエスト。
            client: GitHubClient。
        """
        issue = await client.get_issue(request.repo, request.issue_number)  # type: ignore[attr-defined]
        title = getattr(issue, "title", "") or ""
        match = _CHILD_ISSUE_PATTERN.search(title)
        if not match:
            return

        parent_number = int(match.group(1))
        current_order = int(match.group(2))
        next_suffix = f"(#{parent_number}-{current_order + 1})"

        # リポジトリの open Issue から次の子Issueを探す
        try:
            open_issues = await client.get_issues_with_label(  # type: ignore[attr-defined]
                request.repo,
                "",
                state="open",
            )
            for candidate in open_issues:
                candidate_title = getattr(candidate, "title", "") or ""
                if next_suffix in candidate_title:
                    # ai-agent ラベルがまだなければ付与
                    labels = [getattr(lbl, "name", str(lbl)) for lbl in (getattr(candidate, "labels", []) or [])]
                    if "ai-agent" not in labels:
                        await client.add_label(request.repo, candidate.number, "ai-agent")  # type: ignore[attr-defined]
                        logger.info(
                            "Chained next child issue: #%d -> #%d",
                            request.issue_number,
                            candidate.number,
                        )
                        repo_full_name = self._get_repo_full_name(request)
                        await self._notifier.notify(
                            f"Issue #{candidate.number} の処理を開始します (#{request.issue_number} 完了による連鎖)",
                            metadata={
                                "notification_type": "chain_start",
                                "issue": candidate.number,
                                "repo": repo_full_name,
                            },
                        )
                    return
        except Exception:
            logger.debug("Failed to chain next child issue", exc_info=True)
