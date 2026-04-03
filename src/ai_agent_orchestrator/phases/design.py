"""設計書作成フェーズ (Feature-M)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest
    from ai_agent_orchestrator.phases.base import GitHubClientProtocol

logger = logging.getLogger(__name__)

_DESIGN_REVIEW_PROMPT = """\
@claude /review

## レビュー観点（設計レビュー）

以下の観点でこのPRの設計書をレビューしてください。

### チェック項目
- **Issue要件との整合性**: Issueで要求された機能・仕様が設計書に網羅されているか
- **設計の完全性・一貫性**: フェーズ遷移、データフロー、エラーハンドリングが設計書に明記されているか
- **CLAUDE.md規約との整合性**: Protocol ベース設計、非同期設計、型アノテーション方針との整合性
- **実装上の潜在的問題**: 依存関係の見落とし、循環参照、テスタビリティの問題
- **テスト方針の妥当性**: TDD の観点でテスト戦略が適切か
"""


class DesignExecutor(PhaseExecutor):
    """Feature-M 設計書作成フェーズ。

    設計書を docs/designs/issue-XX.md に作成し、設計 PR を作成する。
    設計・計画・実装は同一ブランチ (feature/issue-XX) で行い、
    1つのPRとして管理する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """設計書作成プロンプトを構築する。

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
            branch_prefix="feature",
        )
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "design",
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
            f"以下のIssueの設計書を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. docs/designs/issue-{request.issue_number}.md に設計書を作成\n"
            f"2. git commit して Push (コミットメッセージは日本語で)\n"
            f"3. PRを作成 (タイトル・本文は日本語で、Closes #{request.issue_number} を含める)\n"
            f"4. PRのURLを出力"
            f"\n\n## 重要な制約\n"
            f"- **設計書 (`docs/designs/` 配下の `.md` ファイル) のみ**を作成してください\n"
            f"- ソースコード (`.ts`, `.tsx`, `.js`, `.py` 等) の作成・変更は**禁止**です\n"
            f"- テストコードの作成も禁止です\n"
            f"- ソースコードの実装は後続の `implement` フェーズで行います\n"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """設計 PR 作成結果を処理 -> DESIGN_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        await self._recover_uncommitted_work(request, branch_prefix="feature")

        # 設計フェーズでソースコードが作成された場合の警告
        await self._warn_if_source_files_added(request)

        # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
        # 設計・実装は同一ブランチ (feature/) の同一PR
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="feat: ",
        )

        state = self._sm.get_state(request.issue_number)
        if state:
            state.design_pr_number = pr_number
            state.pr_number = pr_number  # 設計PR = 実装PR (同一ブランチ)
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:design-review")
        await self._sm.transition(request.issue_number, "design-review")
        await self._post_design_review_comment(request, pr_number, client)
        repo_full_name = self._get_repo_full_name(request)
        pr_url = self._build_pr_url(request, pr_number)
        issue = await client.get_issue(request.repo, request.issue_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計PR #{pr_number} を作成しました",
            metadata={
                "notification_type": "design_pr_created",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "pr": pr_number,
                "pr_url": pr_url,
                "repo": repo_full_name,
                "next_action": "→ 設計PRをレビューしてください",
            },
        )

    async def _post_design_review_comment(
        self,
        request: TaskRequest,
        pr_number: int,
        client: GitHubClientProtocol,
    ) -> None:
        """設計PRに @claude /review コメントを投稿する。

        Args:
            request: タスクリクエスト。
            pr_number: 設計 PR 番号。
            client: GitHub クライアント。
        """
        try:
            await client.create_comment(request.repo, pr_number, _DESIGN_REVIEW_PROMPT)
            logger.info(
                "Issue #%d: posted @claude /review comment to design PR #%d",
                request.issue_number,
                pr_number,
            )
        except Exception:
            logger.warning(
                "Issue #%d: failed to post @claude /review to design PR #%d",
                request.issue_number,
                pr_number,
                exc_info=True,
            )

    async def _warn_if_source_files_added(self, request: TaskRequest) -> None:
        """設計フェーズでソースコードが作成された場合に警告ログを出力する。"""
        try:
            worktree = await self._workspace.create_worktree(
                request.repo,
                request.issue_number,
                branch_prefix="feature",
            )
            base = getattr(request.repo, "base_branch", "main")
            rc, stdout, _ = await self._workspace._run_git(
                "diff",
                f"origin/{base}",
                "--name-only",
                cwd=str(worktree),
            )
            if rc != 0 or not stdout.strip():
                return
            source_exts = {".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java", ".kt"}
            source_files = [
                f
                for f in stdout.strip().splitlines()
                if any(f.endswith(ext) for ext in source_exts) and not f.startswith("docs/")
            ]
            if source_files:
                logger.warning(
                    "Issue #%d: design phase created source files (should be docs only): %s",
                    request.issue_number,
                    source_files,
                )
        except Exception:
            logger.debug("Failed to check source files for issue #%d", request.issue_number)
