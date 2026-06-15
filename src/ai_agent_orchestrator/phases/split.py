"""Feature-L 分割フェーズ (提案 + 実行)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)

# 分割提案コメントを機械的に識別するための安定マーカー (#141)。
# 本文末尾に埋め込み、再実行・再起動時の重複投稿検出と SplitExecuteExecutor の
# 提案検出の双方で使う。HTML コメントなので GitHub 上では非表示。
SPLIT_PROPOSAL_MARKER = "<!-- ai-agent:split-proposal -->"

# マーカー導入前 (#141 以前) に投稿された提案コメントを拾うための後方互換キーワード。
_LEGACY_PROPOSAL_KEYWORDS = ("Issue分割提案", "分割提案", "分割案")


def _is_human_comment(comment: object) -> bool:
    """コメントが人間 (Bot 以外) によるものかを判定する (#141)."""
    user = getattr(comment, "user", None)
    user_type = getattr(user, "type", "") if user else ""
    return user_type != "Bot"


def _is_proposal_comment(comment: object) -> bool:
    """コメントが分割提案コメントかどうかを判定する (#141).

    マーカー一致を最優先する。マーカー導入前 (#141 以前) の提案は後方互換
    キーワードで拾うが、人間が「この分割案を直して」等と書いた修正指示を提案と
    誤判定しないよう、キーワード判定は Bot 投稿に限定する。
    """
    body = getattr(comment, "body", "") or ""
    if SPLIT_PROPOSAL_MARKER in body:
        return True
    if _is_human_comment(comment):
        return False
    return any(keyword in body for keyword in _LEGACY_PROPOSAL_KEYWORDS)


def _should_skip_reproposal(comments: list[object]) -> bool:
    """既存提案があり、かつ新しい修正指示が無ければ再投稿をスキップすべきか判定する (#141).

    分割提案は Issue ごとに 1 件のみとし、再起動での再ディスパッチや
    split↔clarify の往復で提案が積み増されるのを防ぐ。最新の提案コメント以降に
    人間の修正コメントがある場合のみ「修正反映の再提案」として再投稿を許す。

    Args:
        comments: Issue のコメント一覧 (時系列昇順)。

    Returns:
        既存提案があり修正指示も無ければ True (スキップ)、それ以外は False (投稿)。
    """
    last_proposal_idx = -1
    for i, comment in enumerate(comments):
        if _is_proposal_comment(comment):
            last_proposal_idx = i
    if last_proposal_idx == -1:
        return False  # 既存提案なし → 投稿する
    # 最新提案より後に人間の (提案以外の) コメントがあれば修正指示とみなし再投稿する
    for comment in comments[last_proposal_idx + 1 :]:
        if _is_human_comment(comment) and not _is_proposal_comment(comment):
            return False
    return True  # 既存提案あり・修正指示なし → スキップ


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
            issue_number=request.issue_number,
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
            f"3. 各サブタスクのタイプ (feature-m) を判定\n"
            f"4. 実装順序を決定"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """分割提案をコメント投稿。承認待ち。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        from ai_agent_orchestrator.phases.base import next_action_footer

        client = await self._get_client(request.repo)

        # 冪等化 (#141): 既存の分割提案があり、新しい修正指示が無ければ再投稿しない。
        # 再起動での再ディスパッチや split↔clarify の往復による重複投稿を防ぐ。
        existing_comments = await client.list_comments(request.repo, request.issue_number)
        if _should_skip_reproposal(list(existing_comments or [])):
            # 既存提案あり = 承認待ち。再起動再ディスパッチでもフラグを立て直す (#150)。
            self._sm.set_awaiting_split_approval(self._issue_key(request), True)
            logger.info(
                "Issue #%d: 既存の分割提案があり修正指示も無いため再投稿をスキップ",
                request.issue_number,
            )
            return

        comment_body = (
            result.output.strip()
            if result.output.strip()
            else ("分割提案を作成しましたが、出力が空でした。再実行が必要です。")
        )
        comment_body += next_action_footer("split-proposal")
        comment_body += f"\n\n{SPLIT_PROPOSAL_MARKER}"
        await client.create_comment(request.repo, request.issue_number, comment_body)
        # 提案投稿 = 承認待ち。Web 画面の承認導線が拾えるようフラグを立てる (#150)。
        self._sm.set_awaiting_split_approval(self._issue_key(request), True)
        # 承認待ち (SPLIT_PROPOSAL フェーズのまま)
        issue = await client.get_issue(request.repo, request.issue_number)
        repo_full_name = self._get_repo_full_name(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割を提案しました",
            metadata={
                "notification_type": "split_proposal",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "repo": repo_full_name,
                "next_action": "→ 👍で承認をお願いします",
            },
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

        # 分割提案コメントを取得。マーカー一致を最優先し (#141)、
        # 見つからなければ後方互換 (Bot かつ旧キーワード) で拾う。
        split_proposal = ""
        for c in reversed(comments):
            if SPLIT_PROPOSAL_MARKER in (getattr(c, "body", "") or ""):
                split_proposal = getattr(c, "body", "")
                break
        if not split_proposal:
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
            f"1. 分割案の各サブタスクについて子Issueを作成(依存順に番号付与: (#39-1), (#39-2)...)\n"
            f"2. **最初のIssue(依存なし)だけに `ai-agent` ラベルを付与**。残りの子Issueにはラベルを付けない\n"
            f"3. 親Issueに分割完了コメントを投稿\n"
            f"4. 作成した子Issue番号のリストを**依存順(実装順序)**で出力"
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
        # 実行に入ったので承認待ちを解除する (#150)。
        self._sm.set_awaiting_split_approval(self._issue_key(request), False)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:done")
        await self._sm.transition(self._issue_key(request), "done")
        issue = await client.get_issue(request.repo, request.issue_number)
        repo_full_name = self._get_repo_full_name(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割が完了しました",
            metadata={
                "notification_type": "split_complete",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "repo": repo_full_name,
            },
        )
