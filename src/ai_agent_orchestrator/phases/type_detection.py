"""タイプ判定フェーズ."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class TypeDetectionExecutor(PhaseExecutor):
    """Issue のタイプを自動判定するフェーズ。

    Issue 内容を AI が分析し、bug / feature-s / feature-m / feature-l の
    いずれかに分類する。判定結果を Issue コメントとラベルで通知し、
    タイプ別の次フェーズへ遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """タイプ判定用プロンプトを構築する。

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
            "type_detection",
            issue_number=request.issue_number,
        )

        return (
            f"以下のIssueのタイプを判定してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 判定基準\n"
            f"- bug: エラー・不具合・動かない・壊れた等のキーワード、バグ修正の依頼\n"
            f"- feature-m: 1-10ファイルの変更が必要な小〜中規模の機能追加\n"
            f"- feature-l: 10ファイル以上の変更が見込まれる大規模な機能追加・刷新\n\n"
            f"## 出力形式 (JSON)\n"
            f'{{"type": "bug|feature-m|feature-l", "reason": "判定理由"}}'
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """判定結果を処理: ラベル付与 -> コメント投稿 -> 次フェーズ遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        parsed = self._extract_json(result.output)
        if parsed and "type" in parsed:
            issue_type: str = parsed["type"]
            reason: str = parsed.get("reason", "AIが判定")
        else:
            issue_type = self._fallback_detection(result.output)
            reason = "AI出力のパースに失敗、フォールバック判定"

        # ステートマシンにタイプを設定
        self._sm.set_issue_type(request.issue_number, issue_type)

        # GitHub ラベル付与
        client = await self._get_client(request.repo)
        await client.add_label(request.repo, request.issue_number, f"type:{issue_type}")

        # Issue コメント投稿
        await client.create_comment(
            request.repo,
            request.issue_number,
            f"このIssueを **type:{issue_type}** として処理します。\n\n"
            f"**判定理由:** {reason}\n\n"
            f"異なる場合はコメントでお知らせください。",
        )

        # タイプ別次フェーズへ遷移
        next_phase_map: dict[str, str] = {
            "bug": "analysis",
            "feature-m": "hearing",
            "feature-l": "hearing",
        }
        next_phase = next_phase_map.get(issue_type, "hearing")
        await client.replace_phase_label(request.repo, request.issue_number, f"phase:{next_phase}")
        await self._sm.transition(request.issue_number, next_phase)

    @staticmethod
    def _fallback_detection(output: str) -> str:
        """AI 出力パース失敗時のフォールバック判定。

        Args:
            output: AI の出力テキスト。

        Returns:
            判定されたタイプ文字列。
        """
        output_lower = output.lower()
        if any(kw in output_lower for kw in ["bug", "バグ", "エラー", "修正"]):
            return "bug"
        if any(kw in output_lower for kw in ["feature-l", "大規模", "分割"]):
            return "feature-l"
        if any(kw in output_lower for kw in ["feature-m", "中規模", "設計"]):
            return "feature-m"
        return "feature-m"
