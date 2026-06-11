"""REVISE 共通実行器 (U2: REVISE 統合とレビュー質問への回答).

design_revise / impl_revise の共通ロジックを提供する。
レビューコメントを「修正要求 / 質問」として扱い、修正要求にはコード
（または設計書）修正を、質問にはコード変更なしの回答を返す。

Phase enum は変更しない（旧フェーズ名のまま実行器のみ共通化。
フェーズ名の統一は U5 #83 で一括実施）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest
    from ai_agent_orchestrator.phases.base import GitHubClientProtocol

logger = logging.getLogger(__name__)

# エージェントに要求する構造化出力の説明（プロンプト末尾に付与）
_OUTPUT_FORMAT_INSTRUCTION = """
## 出力フォーマット (必ず守ること)

全ての対応が終わったら、**出力の最後に** 以下の形式の JSON ブロックを必ず含めてください。
各コメントの `[ID:n]` に対応する返信文を書きます。

以下は**形式の例**です（値はそのまま使わず、実際の対応内容で置き換えること）:

```json
{
  "replies": [
    {"comment_id": 123, "kind": "fixed", "reply": "<修正内容の具体的な説明>"},
    {"comment_id": 456, "kind": "answered", "reply": "<質問への回答>"}
  ],
  "summary": "<今回の対応全体の要約 (1〜3文)>"
}
```

- `kind` は修正した場合 `fixed`、回答のみの場合 `answered`
- `reply` はレビュアーがそのまま読む文章です。具体的に書いてください
- ID の無いコメント（トップレベルレビュー等）への返信は `summary` に含めてください
"""


class ReviseExecutorBase(PhaseExecutor):
    """レビュー指摘対応の共通基底（セッション継続）。

    サブクラスはクラス属性で対象（設計書/コード）と遷移先を指定する。
    """

    # --- サブクラスで上書きする属性 ---
    phase_name: ClassVar[str] = "impl-revise"
    next_phase: ClassVar[str] = "impl-review"
    target_description: ClassVar[str] = "コード"
    commit_summary: ClassVar[str] = "実装レビュー指摘に対応"
    commit_type: ClassVar[str] = "fix"
    notification_type: ClassVar[str] = "impl_revised"
    notification_message: ClassVar[str] = "の実装を修正しました"
    next_action: ClassVar[str] = "→ 実装PRを再レビューしてください"
    # 返信先 PR 番号として参照する IssueState のフィールド名
    # (impl 系は pr_number、design 系は design_pr_number。混在させない)
    pr_attr: ClassVar[str] = "pr_number"

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    async def build_prompt(self, request: TaskRequest) -> str:
        """レビュー指摘対応プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        extra = getattr(request, "extra", {}) or {}
        comments_text, structured = self._normalize_comments(extra)

        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)

        pr_info = await self._resolve_pr_info(request)

        review_comment_ids = extra.get("review_comment_ids", []) or []
        count_note = ""
        if review_comment_ids:
            count_note = (
                f"\n\n**注意**: 今回は **{len(review_comment_ids)} 件**のレビュー指摘があります。"
                "全ての指摘に対応してください。"
            )

        classified_section = self._build_comments_section(comments_text, structured)

        raw = (
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{pr_info} に対するレビュー指摘に対応してください。{count_note}\n\n"
            f"{classified_section}\n\n"
            f"## 指示\n"
            f"1. 各コメントを「修正要求」か「質問」か判断する\n"
            f"2. **修正要求** → {self.target_description}を修正し、テスト・lint を実行して確認する\n"
            f"3. **質問** → コードを変更せず、出力フォーマットの `reply` に回答を書く"
            f"（質問のみの場合、{self.target_description}の変更は不要です）\n"
            f"4. **git commit / push は不要です** (システムが行います)\n"
            f"{_OUTPUT_FORMAT_INSTRUCTION}"
        )
        return enhance_prompt(raw, self.phase_name)

    @staticmethod
    def _build_comments_section(
        comments_text: str,
        structured: list[dict[str, Any]],
    ) -> str:
        """プロンプト用のコメントセクションを構築する。

        構造化リストがあれば優先度分類と ID マーカー一覧を付与する。

        Args:
            comments_text: コメントのテキスト表現。
            structured: 構造化コメントリスト。

        Returns:
            プロンプトに埋め込むセクション文字列。
        """
        from ai_agent_orchestrator.phases.review_classifier import (
            classify_review_comments,
            format_classified_comments,
        )

        if not structured:
            return f"## レビュー指摘内容\n{comments_text}"

        classified = classify_review_comments(structured)
        section = format_classified_comments(classified)
        # ID マーカーを付与した一覧（返信の対応付け用）
        id_lines = "\n".join(
            f"- [ID:{c.get('id')}] {(c.get('path') or '')}:{c.get('line') or ''} {(c.get('body') or '')[:200]}"
            for c in structured
            if c.get("id") is not None
        )
        if id_lines:
            section += f"\n\n## コメント ID 一覧（返信の対応付けに使用）\n{id_lines}"
        return section

    # ------------------------------------------------------------------
    # Agent execution (session resume)
    # ------------------------------------------------------------------

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
            phase=self.phase_name,
            resume_session_id=(state.session_id if state else None),
        )

    # ------------------------------------------------------------------
    # Result processing
    # ------------------------------------------------------------------

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """修正/回答結果を処理し、レビューフェーズへ再遷移する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        # REVISE 系: 質問への回答のみ等、変更ゼロでも正常
        await self._finalize_phase_commit(
            request,
            summary=self.commit_summary,
            commit_type=self.commit_type,
            allow_no_changes=True,
            branch_prefix="feature",
        )

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, f"phase:{self.next_phase}")
        await self._sm.transition(self._issue_key(request), self.next_phase)

        # レビューへの応答（生成された返信文を使用。定型文は廃止）
        replies, summary = self._parse_revise_output(result.output)
        await self._send_review_responses(request, replies, summary)

        # 遷移は完了済みのため、通知失敗でフェーズを失敗扱いにしない
        try:
            await self._notify_revised(request, client)
        except Exception:
            logger.warning(
                "Issue #%d: revise notification failed (transition already done)",
                request.issue_number,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Review responses
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_revise_output(output: str) -> tuple[dict[int, str], str | None]:
        """エージェント出力から返信マップとサマリを抽出する。

        Args:
            output: エージェントの出力テキスト。

        Returns:
            (comment_id → 返信文, サマリ) のタプル。JSON が無ければ ({}, None)。
        """
        data = PhaseExecutor._extract_json(output)
        if not isinstance(data, dict):
            return {}, None
        replies: dict[int, str] = {}
        for entry in data.get("replies") or []:
            if not isinstance(entry, dict):
                continue
            # LLM 出力の揺れに寛容化: 文字列 ID ("123") も受理する
            try:
                cid = int(entry.get("comment_id"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            reply = entry.get("reply")
            if isinstance(reply, str) and reply.strip():
                replies[cid] = reply.strip()
        summary = data.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            summary = None
        return replies, summary

    async def _send_review_responses(
        self,
        request: TaskRequest,
        replies: dict[int, str],
        summary: str | None,
    ) -> None:
        """レビューコメントへ返信する。ID なしの場合は PR コメントで応答する。

        Args:
            request: タスクリクエスト。
            replies: comment_id → 生成された返信文。
            summary: 対応全体のサマリ。
        """
        extra = getattr(request, "extra", {}) or {}
        review_comment_ids: list[int] = extra.get("review_comment_ids", []) or []
        comments_text, _ = self._normalize_comments(extra)
        pr_number = self._resolve_pr_number(request)

        # 回答済み ID を除外 (#103: router を経由しない呼び出しでも防御)
        state = self._sm.get_state(self._issue_key(request))
        answered_ids_ref = getattr(state, "answered_review_comment_ids", None) if state else None
        answered = set(answered_ids_ref) if isinstance(answered_ids_ref, list) else set()
        if answered:
            original_count = len(review_comment_ids)
            review_comment_ids = [i for i in review_comment_ids if i not in answered]
            if original_count > 0 and not review_comment_ids:
                # 全件回答済み: top-level 分岐に落として create_comment を
                # 再投稿しない（router 非経由の呼び出しでもスパムを防止）。
                # summary の投稿もスキップされるが、既回答前提のため意図通り
                logger.info(
                    "Issue #%d: all %d review comments already answered, skipping responses",
                    request.issue_number,
                    original_count,
                )
                return

        if pr_number is None:
            logger.debug(
                "Issue #%d: no PR number, skipping review responses",
                request.issue_number,
            )
            return

        try:
            client = await self._get_client(request.repo)
        except Exception:
            logger.debug(
                "Issue #%d: failed to get client for review responses",
                request.issue_number,
                exc_info=True,
            )
            return

        fallback = summary or "上記の指摘・質問に対応しました。"

        logger.info(
            "Issue #%d: sending review responses (inline=%d, generated=%d, summary=%s, pr=#%d)",
            request.issue_number,
            len(review_comment_ids),
            len(replies),
            "yes" if summary else "no",
            pr_number,
        )

        if review_comment_ids:
            succeeded = await self._reply_inline_comments(
                client, request, pr_number, review_comment_ids, replies, fallback
            )
            # 返信成功した ID を永続化（再起動を跨いだ再回答の防止 #103）
            if succeeded and isinstance(answered_ids_ref, list):
                answered_ids_ref.extend(succeeded)
                answered_ids_ref[:] = sorted(set(answered_ids_ref))  # 防御的な重複排除
                self._sm.persist()
        elif comments_text or summary:
            # トップレベルレビュー（comment ID なし）: PR コメントで応答
            try:
                await client.create_comment(request.repo, pr_number, fallback)
            except Exception:
                logger.debug(
                    "Issue #%d: failed to post top-level review response",
                    request.issue_number,
                    exc_info=True,
                )
            else:
                # 応答した review id を永続化（再起動を跨いだ本文応答の重複防止 #103）
                review_id = extra.get("review_id")
                answered_rids_ref = getattr(state, "answered_review_ids", None) if state else None
                if isinstance(review_id, int) and isinstance(answered_rids_ref, list):
                    answered_rids_ref.append(review_id)
                    answered_rids_ref[:] = sorted(set(answered_rids_ref))
                    self._sm.persist()

    async def _reply_inline_comments(
        self,
        client: GitHubClientProtocol,
        request: TaskRequest,
        pr_number: int,
        comment_ids: list[int],
        replies: dict[int, str],
        fallback: str,
    ) -> list[int]:
        """各インラインコメントへ生成返信文（無ければフォールバック）で返信する。

        Args:
            client: GitHub クライアント。
            request: タスクリクエスト。
            pr_number: 返信先 PR 番号。
            comment_ids: 返信対象のコメント ID 一覧。
            replies: comment_id → 生成された返信文。
            fallback: 該当返信が無い場合の文面。

        Returns:
            返信に成功したコメント ID のリスト（失敗分は次回リトライ可能なよう含めない）。
        """
        succeeded: list[int] = []
        for comment_id in comment_ids:
            body = replies.get(comment_id, fallback)
            try:
                await client.reply_to_review_comment(request.repo, pr_number, comment_id, body)
                succeeded.append(comment_id)
            except Exception:
                logger.debug(
                    "Issue #%d: failed to reply to review comment %d",
                    request.issue_number,
                    comment_id,
                    exc_info=True,
                )
        return succeeded

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_comments(extra: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        """extra からコメント本文と構造化リストを取り出す。

        ルーターの経路によって `comments` は str / dict / list のいずれか
        になり得るため、すべて許容する。

        Args:
            extra: TaskRequest.extra。

        Returns:
            (テキスト表現, 構造化コメントリスト) のタプル。
        """
        structured = extra.get("review_comments")
        structured_list = structured if isinstance(structured, list) else []

        raw = extra.get("comments", "")
        if isinstance(raw, list):
            structured_list = structured_list or raw
            text = "\n".join(str((c or {}).get("body", "")) for c in raw if isinstance(c, dict))
        elif isinstance(raw, dict):
            text = str(raw.get("comments", "") or raw.get("comment", "") or "")
        else:
            text = str(raw or "")
        return text, structured_list

    def _resolve_pr_number(self, request: TaskRequest) -> int | None:
        """state から返信先 PR 番号を取得する。

        サブクラスの ``pr_attr`` で指定されたフィールドのみを参照する
        （impl が design PR へ誤返信する経路を作らない）。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state is None:
            return None
        pr = getattr(state, self.pr_attr, None)
        return pr if isinstance(pr, int) else None

    async def _resolve_pr_info(self, request: TaskRequest) -> str:
        """プロンプト用の PR 表記を解決する。"""
        pr_number = self._resolve_pr_number(request)
        if pr_number:
            return f"PR #{pr_number}"
        try:
            client = await self._get_client(request.repo)
            repo_any: Any = request.repo
            prs = await client.list_pull_requests(
                request.repo,
                head=f"{repo_any.owner}:feature/issue-{request.issue_number}",
            )
            if prs:
                first_pr: Any = prs[0]
                return f"PR #{first_pr.number}"
        except Exception:
            logger.debug(
                "Issue #%d: failed to resolve PR info",
                request.issue_number,
                exc_info=True,
            )
        return "PR"

    async def _notify_revised(self, request: TaskRequest, client: GitHubClientProtocol) -> None:
        """修正完了を通知する。"""
        repo_full_name = self._get_repo_full_name(request)
        pr_number = self._resolve_pr_number(request)
        pr_url_val = self._build_pr_url(request, pr_number) if pr_number else None
        issue = await client.get_issue(request.repo, request.issue_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} {self.notification_message}",
            metadata={
                "notification_type": self.notification_type,
                "issue": request.issue_number,
                "issue_title": issue.title,
                "pr": pr_number,
                "pr_url": pr_url_val,
                "repo": repo_full_name,
                "next_action": self.next_action,
            },
        )
