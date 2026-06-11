"""PLAN フェーズ (U3 #81: analysis / design の統合).

旧 AnalysisExecutor (Bug 分析) と旧 DesignExecutor (Feature-M 設計) を
plan_depth (light / full) で分岐する共通 PlanExecutor に統合する。
Phase enum / 遷移表は変更せず、旧フェーズ名 (analysis / design) のまま動く
(enum の付け替えは #83 で一括実施)。

- light (旧 analysis): 原因と対策の短い方針を Issue コメント投稿
- full (旧 design): 設計書 + サブタスクを作成し設計 PR を作成

どちらの depth でも構造化 plan JSON を生成して state に永続化し、
full では worktree の docs/designs/issue-N.plan.json にも書き出す。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_agent_orchestrator.phases.base import PhaseExecutor
from ai_agent_orchestrator.phases.plan_artifact import (
    build_plan_record,
    extract_plan_json,
    plan_json_prompt_section,
)
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


def plan_depth_for(request: TaskRequest) -> str:
    """リクエストの plan_depth を導出する。

    Phase enum を変更しない U3 段階では旧フェーズ名から導出する
    (analysis → light / design → full)。#83 でパラメータ駆動に切り替える。

    Args:
        request: タスクリクエスト。

    Returns:
        "light" または "full"。
    """
    value = request.phase.value if hasattr(request.phase, "value") else str(request.phase)
    return "light" if value.replace("_", "-").lower() == "analysis" else "full"


class PlanExecutor(PhaseExecutor):
    """PLAN フェーズ (analysis / design 統合)。

    plan_depth に応じて成果物の深さ・投稿先・次フェーズを切り替える。

    - light: 修正方針を Issue コメント投稿 → plan-review (👍承認)
    - full: 設計書 + 設計 PR 作成 → design-review (PR approve 承認)
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """plan_depth に応じたプロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        if plan_depth_for(request) == "light":
            return await self._build_light_prompt(request)
        return await self._build_full_prompt(request)

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """plan_depth に応じて成果物を処理し次フェーズへ遷移する。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        if plan_depth_for(request) == "light":
            await self._process_light_result(request, result)
        else:
            await self._process_full_result(request, result)

    # ------------------------------------------------------------------
    # light (旧 analysis) フロー
    # ------------------------------------------------------------------

    async def _build_light_prompt(self, request: TaskRequest) -> str:
        """Bug 分析用プロンプトを構築する (旧 AnalysisExecutor.build_prompt)。"""
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(
            str(worktree),
            getattr(issue, "body", "") or "",
            "analysis",
            issue_number=request.issue_number,
        )

        extra = getattr(request, "extra", {}) or {}
        feedback = extra.get("feedback", "")
        feedback_section = f"\n## 前回の方針に対する指摘\n{feedback}" if feedback else ""

        return (
            f"以下のバグIssueを分析し、修正方針を作成してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n"
            f"{feedback_section}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 出力形式 (Markdownテキスト)\n"
            f"修正方針を出力してください。"
        ) + plan_json_prompt_section("light")

    async def _process_light_result(self, request: TaskRequest, result: AgentResult) -> None:
        """分析結果を Issue コメント投稿 -> plan-review 遷移 (旧 AnalysisExecutor)。"""
        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        comment_text, parsed = extract_plan_json(result.output)
        self._store_plan_record(request, "light", parsed)

        from ai_agent_orchestrator.phases.base import next_action_footer

        client = await self._get_client(request.repo)
        comment_body = (
            comment_text.strip()
            if comment_text.strip()
            else ("AI分析を実行しましたが、出力が空でした。再実行が必要です。")
        )
        comment_body += next_action_footer("analysis")
        await client.create_comment(request.repo, request.issue_number, comment_body)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:plan-review")
        await self._sm.transition(self._issue_key(request), "plan-review")
        issue = await client.get_issue(request.repo, request.issue_number)
        repo_full_name = self._get_repo_full_name(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正方針を投稿しました",
            metadata={
                "notification_type": "plan_posted",
                "issue": request.issue_number,
                "issue_title": issue.title,
                "repo": repo_full_name,
                "next_action": "→ 👍で承認をお願いします",
            },
        )

    # ------------------------------------------------------------------
    # full (旧 design) フロー
    # ------------------------------------------------------------------

    async def _build_full_prompt(self, request: TaskRequest) -> str:
        """設計書作成プロンプトを構築する (旧 DesignExecutor.build_prompt)。"""
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
            f"2. **git commit / push / PR 作成は不要です** (システムが行います)"
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
        ) + plan_json_prompt_section("full")
        return enhance_prompt(raw, "design")

    async def _process_full_result(self, request: TaskRequest, result: AgentResult) -> None:
        """設計 PR 作成結果を処理 -> design-review 遷移 (旧 DesignExecutor)。"""
        _, parsed = extract_plan_json(result.output)
        record = self._store_plan_record(request, "full", parsed)
        # plan JSON を worktree に書き出してから phase commit に乗せる。
        # この record は初回エージェント出力の JSON ブロック由来であり、後続の
        # _revalidate_design が設計書を再生成しても plan.json の subtasks は
        # 更新されない (設計書本文と乖離し得る点に留意)。
        await self._write_plan_json_file(request, record)

        await self._finalize_phase_commit(
            request,
            summary="設計書を作成",
            commit_type="docs",
            branch_prefix="feature",
        )

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

    # ------------------------------------------------------------------
    # plan JSON の保存
    # ------------------------------------------------------------------

    def _store_plan_record(
        self,
        request: TaskRequest,
        plan_depth: str,
        parsed: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """plan レコードを構築して state に永続化する。

        Args:
            request: タスクリクエスト。
            plan_depth: "light" または "full"。
            parsed: エージェント出力からパースした JSON (なければ None)。

        Returns:
            構築した plan レコード。
        """
        record = build_plan_record(plan_depth, parsed)
        state = self._sm.get_state(self._issue_key(request))
        if state is not None:
            state.plan_json = record
            self._sm.persist()
        if record["ui_impact"] is None:
            logger.warning(
                "Issue #%d: plan JSON missing or unparsable, ui_impact is unknown",
                request.issue_number,
            )
        return record

    async def _write_plan_json_file(self, request: TaskRequest, record: dict[str, Any]) -> None:
        """plan レコードを worktree の docs/designs/issue-N.plan.json に書き出す。

        書き出し失敗は警告に留めフローを止めない (state 側には保存済み)。

        Args:
            request: タスクリクエスト。
            record: 構築済み plan レコード。
        """
        try:
            worktree = await self._workspace.create_worktree(
                request.repo,
                request.issue_number,
                branch_prefix="feature",
            )
            designs_dir = Path(str(worktree)) / "docs" / "designs"
            designs_dir.mkdir(parents=True, exist_ok=True)
            plan_path = designs_dir / f"issue-{request.issue_number}.plan.json"
            plan_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.warning(
                "Issue #%d: failed to write plan JSON file",
                request.issue_number,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # full フローのヘルパ (旧 DesignExecutor から移植)
    # ------------------------------------------------------------------

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
                f"連番・循環なし・テストファイル必須）を含めてください。"
                f"commit / push は不要です (システムが行います)。\n"
                f"現在の問題点:\n" + "\n".join(f"- {e}" for e in errors)
            )
            await self.run_agent(request, fix_prompt)
            await self._finalize_phase_commit(
                request,
                summary="設計書を修正（再検証対応）",
                commit_type="docs",
                branch_prefix="feature",
            )

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
