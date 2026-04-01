"""コード実装フェーズ (マルチパス対応)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ai_agent_orchestrator.context.engine import DESIGN_DOC_HEADING, IMPL_PLAN_HEADING
from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)

# マルチパス設定
_MAX_IMPL_ITERATIONS = 5
_COMPLETION_THRESHOLD = 0.8  # 計画ファイルの 80% 以上が変更済みなら完了

# 実装計画からファイルパスを抽出するパターン
_FILE_PATH_PATTERN = re.compile(r"[`*]*([a-zA-Z_][\w./\-]*\.\w{1,5})[`*]*")
_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".sql",
        ".sh",
    }
)


def extract_planned_files(impl_plan_text: str) -> set[str]:
    """実装計画テキストからファイルパスを抽出する。

    Args:
        impl_plan_text: 実装計画のMarkdownテキスト。

    Returns:
        ソースファイルパスの集合。
    """
    candidates = set(_FILE_PATH_PATTERN.findall(impl_plan_text))
    return {f for f in candidates if any(f.endswith(ext) for ext in _SOURCE_EXTENSIONS)}


class ImplementExecutor(PhaseExecutor):
    """コード実装フェーズ (マルチパス対応)。

    実装計画に基づいてコードを実装し、テスト・lint を実行した上で
    PR を作成する。大規模な計画の場合、エージェントが1回で完了できなくても
    自動的に継続パスを実行して残りを実装する。
    """

    async def execute(self, request: TaskRequest) -> None:
        """マルチパス実装を実行する。

        1回のエージェント実行後に完了判定を行い、
        計画の80%以上のファイルが変更されるまでループする。
        進捗がなくなった場合やMAX回数に達した場合は現状でPRを作成する。

        Args:
            request: タスクリクエスト。
        """
        try:
            await self._tracker.track(
                "phase_start",
                issue_number=request.issue_number,
                phase=str(request.phase),
            )

            state = self._sm.get_state(request.issue_number)
            start_iteration = state.impl_iteration if state else 0
            total_cost = 0.0
            total_duration = 0.0
            last_result: AgentResult | None = None
            prev_modified: set[str] = set()

            for iteration in range(start_iteration, _MAX_IMPL_ITERATIONS):
                logger.info(
                    "Issue #%d: implementation pass %d/%d",
                    request.issue_number,
                    iteration + 1,
                    _MAX_IMPL_ITERATIONS,
                )

                # プロンプト構築 (継続パスなら進捗コンテキスト付き)
                prompt = await self._build_pass_prompt(request, iteration)
                await self._record_branch_baseline(request)

                # エージェント実行
                result = await self.run_agent(request, prompt)
                total_cost += result.cost_usd
                total_duration += result.duration_sec
                last_result = result

                # 未コミット作業の回復
                await self._recover_uncommitted_work(request, branch_prefix="feature")

                # 状態更新
                if state:
                    state.session_id = result.session_id
                    state.impl_iteration = iteration + 1

                # 完了判定
                worktree = await self._workspace.create_worktree(
                    request.repo,
                    request.issue_number,
                    branch_prefix="feature",
                )
                cur_modified = await self._get_modified_files(request, str(worktree))

                # 進捗なし検知 (前回と同じファイル集合 = スタル)
                if iteration > start_iteration and cur_modified == prev_modified:
                    logger.warning(
                        "Issue #%d: no new files modified in pass %d, stopping",
                        request.issue_number,
                        iteration + 1,
                    )
                    break

                prev_modified = cur_modified

                # 完了率チェック
                should_continue = await self._should_continue(
                    request,
                    str(worktree),
                    cur_modified,
                )
                if not should_continue:
                    logger.info(
                        "Issue #%d: implementation sufficiently complete at pass %d",
                        request.issue_number,
                        iteration + 1,
                    )
                    break

                # 継続通知
                await self._notifier.notify(
                    f"Issue #{request.issue_number} 実装パス {iteration + 1} 完了、継続中",
                    metadata={
                        "issue": request.issue_number,
                        "iteration": iteration + 1,
                    },
                )

                await self._tracker.track(
                    "impl_continuation",
                    issue_number=request.issue_number,
                    phase=str(request.phase),
                    data={"iteration": iteration + 1},
                )

            # 最終処理: PR作成 → impl-review 遷移
            if last_result is None:
                msg = f"Issue #{request.issue_number}: 実装フェーズが結果を返しませんでした。"
                raise RuntimeError(msg)

            # コスト・時間を集約した結果で finalize
            from ai_agent_orchestrator.models import AgentResult

            aggregated = AgentResult(
                session_id=last_result.session_id,
                output=last_result.output,
                tool_uses=last_result.tool_uses,
                cost_usd=total_cost,
                duration_sec=total_duration,
            )
            await self._finalize(request, aggregated)

            await self._tracker.track(
                "phase_end",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={
                    "cost_usd": total_cost,
                    "duration_sec": total_duration,
                },
            )
        except TimeoutError:
            await self._handle_timeout(request)
        except Exception as exc:
            await self._handle_error(request, exc)

    async def build_prompt(self, request: TaskRequest) -> str:
        """初回実装プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。

        Raises:
            RuntimeError: 設計書または実装計画がコンテキストに含まれない場合。
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
            "implement",
            issue_number=request.issue_number,
        )

        if DESIGN_DOC_HEADING not in context:
            msg = (
                f"Issue #{request.issue_number}: "
                "設計書がコンテキストに含まれていません。"
                "設計フェーズが完了しているか確認してください。"
            )
            raise RuntimeError(msg)
        if IMPL_PLAN_HEADING not in context:
            msg = (
                f"Issue #{request.issue_number}: "
                "実装計画がコンテキストに含まれていません。"
                "計画フェーズが完了しているか確認してください。"
            )
            raise RuntimeError(msg)

        return (
            f"以下の設計書と実装計画に基づいてコードを実装してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{context}\n\n"
            f"## 実装指示\n"
            f"1. 実装計画の順序に従ってコードを実装\n"
            f"2. テストコードも作成\n"
            f"3. テスト・lint・ビルドを実行して確認\n"
            f"4. git commit して Push (コミットメッセージは日本語で)\n"
            f"5. PRを作成 (タイトル・本文は日本語で)\n"
            f"6. PR descriptionに変更概要を含める"
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """互換性のため残す。execute() から直接は呼ばれない。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        await self._recover_uncommitted_work(request, branch_prefix="feature")
        await self._finalize(request, result)

    # ------------------------------------------------------------------
    # Multi-pass helpers
    # ------------------------------------------------------------------

    async def _build_pass_prompt(self, request: TaskRequest, iteration: int) -> str:
        """パスに応じたプロンプトを構築する。

        Args:
            request: タスクリクエスト。
            iteration: 現在のイテレーション番号 (0始まり)。

        Returns:
            プロンプト文字列。
        """
        if iteration == 0:
            return await self.build_prompt(request)

        # 継続パス: 進捗コンテキスト付き
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
            "implement",
            issue_number=request.issue_number,
        )
        continuation = await self._build_continuation_context(request, str(worktree))

        return (
            f"## Issue #{request.issue_number}: {issue.title} (実装継続パス {iteration + 1})\n\n"
            f"{context}\n\n"
            f"{continuation}\n\n"
            f"## 実装指示\n"
            f"1. 上記の未実装ファイルを実装計画の順序に従って実装\n"
            f"2. 既にコミット済みの内容は変更不要\n"
            f"3. テストコードも作成\n"
            f"4. テスト・lint・ビルドを実行して確認\n"
            f"5. git commit して Push (コミットメッセージは日本語で)\n"
        )

    async def _build_continuation_context(
        self,
        request: TaskRequest,
        worktree_path: str,
    ) -> str:
        """継続パス用の進捗コンテキストを構築する。

        Args:
            request: タスクリクエスト。
            worktree_path: worktree のパス。

        Returns:
            進捗コンテキスト文字列。
        """
        modified = await self._get_modified_files(request, worktree_path)
        impl_plan = await self._context._read_impl_plan(worktree_path, request.issue_number)
        planned = extract_planned_files(impl_plan) if impl_plan else set()

        done_files = sorted(modified & planned)
        remaining_files = sorted(planned - modified)

        done_list = "\n".join(f"- [x] `{f}`" for f in done_files) or "(なし)"
        remaining_list = "\n".join(f"- [ ] `{f}`" for f in remaining_files) or "(なし)"

        return (
            f"## 実装進捗\n\n"
            f"### 完了済みファイル\n{done_list}\n\n"
            f"### 未実装ファイル (今回実装してください)\n{remaining_list}"
        )

    async def _should_continue(
        self,
        request: TaskRequest,
        worktree_path: str,
        modified_files: set[str],
    ) -> bool:
        """実装を継続すべきか判定する。

        Args:
            request: タスクリクエスト。
            worktree_path: worktree のパス。
            modified_files: 現在の変更済みファイル集合。

        Returns:
            継続すべきなら True。
        """
        impl_plan = await self._context._read_impl_plan(worktree_path, request.issue_number)
        if not impl_plan:
            return False

        planned = extract_planned_files(impl_plan)
        if not planned:
            return False

        touched = len(planned & modified_files)
        ratio = touched / len(planned)

        logger.info(
            "Issue #%d: implementation progress %.0f%% (%d/%d planned files)",
            request.issue_number,
            ratio * 100,
            touched,
            len(planned),
        )

        return ratio < _COMPLETION_THRESHOLD

    async def _get_modified_files(
        self,
        request: TaskRequest,
        worktree_path: str,
    ) -> set[str]:
        """origin/main からの変更ファイル一覧を取得する。

        Args:
            request: タスクリクエスト。
            worktree_path: worktree のパス。

        Returns:
            変更ファイルパスの集合。
        """
        base_branch = getattr(request.repo, "base_branch", "main")
        rc, stdout, _ = await self._workspace._run_git(
            "diff",
            f"origin/{base_branch}",
            "--name-only",
            cwd=worktree_path,
        )
        if rc == 0 and stdout.strip():
            return set(stdout.strip().splitlines())
        return set()

    async def _finalize(self, request: TaskRequest, result: AgentResult) -> None:
        """PR作成 → impl-review 遷移。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        if result.cost_usd == 0.0 and not result.output.strip():
            msg = f"Issue #{request.issue_number}: 実装フェーズが空の結果を返しました。"
            raise RuntimeError(msg)

        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="機能: ",
        )

        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id
            state.impl_iteration = 0  # リセット

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
            metadata={
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )
