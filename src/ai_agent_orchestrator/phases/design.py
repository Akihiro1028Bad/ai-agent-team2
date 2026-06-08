"""設計書作成フェーズ (Feature-M)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor
from ai_agent_orchestrator.phases.plan_validation import validate_plan

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest
    from ai_agent_orchestrator.phases.base import GitHubClientProtocol

logger = logging.getLogger(__name__)

# 設計書内の実装計画 (## サブタスク) の再生成上限 (無限ループ防止)
_MAX_DESIGN_REVALIDATE = 2

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

        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        raw = (
            f"以下のIssueの設計書を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. docs/designs/issue-{request.issue_number}.md に設計書を作成\n"
            f"   設計書には設計内容に加え、**末尾に `## サブタスク` セクション** "
            f"(実装計画) を必ず含めること\n"
            f"2. git commit して Push (コミットメッセージは日本語で)\n"
            f"3. PRを作成 (タイトル・本文は日本語で、Closes #{request.issue_number} を含める)\n"
            f"4. PRのURLを出力"
            f"\n\n## 設計書末尾の `## サブタスク` セクション (必ず守ること)\n\n"
            f"設計書の末尾に以下のフォーマットで `## サブタスク` セクションを含めること。\n"
            f"このセクションは後続フェーズが自動的に読み取り構造を検証するため、"
            f"フォーマットを正確に守ること。\n\n"
            f"```markdown\n"
            f"## サブタスク\n\n"
            f"### subtask-1: <タイトル>\n"
            f"- files: [`path/to/a.py`, `path/to/b.py`]\n"
            f"- depends_on: []\n"
            f"- description: このサブタスクで行う作業の説明\n\n"
            f"### subtask-2: <タイトル>\n"
            f"- files: [`path/to/c.py`, `path/to/test_c.py`]\n"
            f"- depends_on: [1]\n"
            f"- description: このサブタスクで行う作業の説明\n"
            f"```\n\n"
            f"### サブタスク分割の原則\n"
            f"- subtask 番号は **1 から連番** で振ること (欠番・重複・循環依存は禁止)\n"
            f"- 1サブタスクに含めるファイルは **2〜4ファイル** を目安にする\n"
            f"- 依存する型・インターフェースを先のサブタスクで定義する\n"
            f"- **テストファイルを必ずいずれかのサブタスクに含める** "
            f"(`files` にテストファイルを含めること)\n"
            f"- `depends_on` には依存するサブタスクの番号 (整数) を列挙する\n"
            f"\n## 重要な制約\n"
            f"- **設計書 (`docs/designs/` 配下の `.md` ファイル) のみ**を作成してください\n"
            f"- ソースコード (`.ts`, `.tsx`, `.js`, `.py` 等) の作成・変更は**禁止**です\n"
            f"- テストコードの作成も禁止です (`## サブタスク` での計画記述のみ)\n"
            f"- ソースコードの実装は後続の `implement` フェーズで行います\n"
        )
        return enhance_prompt(raw, "design")

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """設計 PR 作成結果を処理 -> DESIGN_REVIEW 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        await self._recover_uncommitted_work(request, branch_prefix="feature")

        # 設計フェーズでソースコードが作成された場合の警告
        await self._warn_if_source_files_added(request)

        # 設計書末尾の ## サブタスク (実装計画) の構造を自己検証し、NGなら再生成
        await self._revalidate_design(request)

        # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
        # 設計・実装は同一ブランチ (feature/) の同一PR
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="feat: ",
        )

        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.design_pr_number = pr_number
            state.pr_number = pr_number  # 設計PR = 実装PR (同一ブランチ)
            state.session_id = result.session_id

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:design-review")
        await self._sm.transition(self._issue_key(request), "design-review")
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

    async def _revalidate_design(self, request: TaskRequest) -> None:
        """生成された設計書の ## サブタスク構造を検証し、NG なら再生成する。

        上限 (`_MAX_DESIGN_REVALIDATE`) 回まで再生成を試み、上限到達後も
        問題が残る場合は警告コメントを投稿して処理を続行する。

        Args:
            request: タスクリクエスト。
        """
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )
        design_path = Path(str(worktree)) / "docs" / "designs" / f"issue-{request.issue_number}.md"
        for attempt in range(_MAX_DESIGN_REVALIDATE):
            errors = self._validate_design_doc(design_path, str(worktree))
            if not errors:
                return
            logger.info(
                "Issue #%d: 設計書の計画検証NG (%d/%d) → 再生成",
                request.issue_number,
                attempt + 1,
                _MAX_DESIGN_REVALIDATE,
            )
            fix_prompt = (
                f"docs/designs/issue-{request.issue_number}.md を作成または修正し、"
                f"## サブタスク セクション（### subtask-N: ＋ files/depends_on/description、"
                f"連番・循環なし・テストファイル必須）を含めて commit/push してください。\n"
                f"現在の問題点:\n"
                + "\n".join(f"- {e}" for e in errors)
            )
            await self.run_agent(request, fix_prompt)
            await self._recover_uncommitted_work(request, branch_prefix="feature")

        remaining = self._validate_design_doc(design_path, str(worktree))
        if remaining:
            logger.warning(
                "Issue #%d: 設計書の計画検証が上限到達後も NG、警告付きで続行",
                request.issue_number,
            )
            try:
                client = await self._get_client(request.repo)
                await client.create_comment(
                    request.repo,
                    request.issue_number,
                    "⚠️ 設計書の実装計画に検証警告がありますが、上限到達のため続行します。\n\n"
                    + "\n".join(f"- {e}" for e in remaining),
                )
            except Exception:
                logger.warning(
                    "Issue #%d: failed to post design plan validation warning comment",
                    request.issue_number,
                    exc_info=True,
                )

    @staticmethod
    def _validate_design_doc(design_path: Path, worktree: str) -> list[str]:
        """設計書ファイルを読み込み、## サブタスク構造を検証する。

        Args:
            design_path: 設計書ファイルのパス。
            worktree: worktree のルートパス。

        Returns:
            エラーメッセージのリスト。空リストなら検証OK。
        """
        if not design_path.exists():
            return [f"設計書 {design_path.name} が見つかりません"]
        return validate_plan(design_path.read_text(encoding="utf-8"), worktree)

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
