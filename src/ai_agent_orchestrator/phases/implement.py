"""コード実装フェーズ (サブタスク対応)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ai_agent_orchestrator.context.engine import (
    _SOURCE_EXTENSIONS as _ALL_SOURCE_EXTENSIONS,
)
from ai_agent_orchestrator.context.engine import (
    DESIGN_DOC_HEADING,
    IMPL_PLAN_HEADING,
)
from ai_agent_orchestrator.models import AgentResult, Phase, Subtask
from ai_agent_orchestrator.phases.base import NoChangesError, PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import TaskRequest

logger = logging.getLogger(__name__)

# マルチパス設定
_MAX_IMPL_ITERATIONS = 5
_COMPLETION_THRESHOLD = 0.8  # 計画ファイルの 80% 以上が変更済みなら完了

# 実装計画からファイルパスを抽出するパターン (ドキュメント拡張子は除外)
_FILE_PATH_PATTERN = re.compile(r"[`*]*([a-zA-Z_][\w./\-]*\.\w{1,5})[`*]*")
_IMPL_SOURCE_EXTENSIONS = _ALL_SOURCE_EXTENSIONS - {".md", ".rst"}


def extract_planned_files(impl_plan_text: str) -> set[str]:
    """実装計画テキストからファイルパスを抽出する。

    Args:
        impl_plan_text: 実装計画のMarkdownテキスト。

    Returns:
        ソースファイルパスの集合。
    """
    candidates = set(_FILE_PATH_PATTERN.findall(impl_plan_text))
    return {f for f in candidates if any(f.endswith(ext) for ext in _IMPL_SOURCE_EXTENSIONS)}


# ## サブタスク セクションのパターン
# group(1)=id, group(2)=title(1行), group(3)=ブロック本文
_SUBTASK_HEADING_PATTERN = re.compile(
    r"###\s+subtask-(\d+)\s*[:：]\s*([^\n]+)\n(.*?)(?=###\s+subtask-|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_FILES_INLINE_PATTERN = re.compile(r"files\s*[:：]\s*\[([^\]]*)\]", re.IGNORECASE)
_FILES_BULLET_PATTERN = re.compile(r"files\s*[:：]\s*\n((?:\s*[-*]\s*.+\n?)+)", re.IGNORECASE)
_DEPENDS_ON_PATTERN = re.compile(r"depends_on\s*[:：]\s*\[([^\]]*)\]", re.IGNORECASE)
_DESCRIPTION_PATTERN = re.compile(r"description\s*[:：]\s*(.+?)(?=\n\s*-\s*\w|\Z)", re.DOTALL | re.IGNORECASE)


def parse_subtasks(impl_plan_text: str) -> list[Subtask]:
    """実装計画テキストから ## サブタスク セクションをパースする。

    計画ファイルに以下のフォーマットの ``## サブタスク`` セクションが
    含まれる場合にサブタスクリストを返す。セクションがない場合や
    パースに失敗した場合は空リストを返す (旧フォーマット互換)。

    フォーマット例::

        ## サブタスク

        ### subtask-1: Core Types
        - files: [`src/types.py`, `src/protocols.py`]
        - depends_on: []
        - description: 型定義とプロトコルを追加する

        ### subtask-2: Repository Layer
        - files: [`src/repository.py`]
        - depends_on: [1]
        - description: リポジトリクラスを実装する

    Args:
        impl_plan_text: 実装計画のMarkdownテキスト。

    Returns:
        Subtask オブジェクトのリスト。サブタスクセクションがない場合は空リスト。
    """
    # ## サブタスク セクションが存在するか確認
    subtask_section_match = re.search(r"##\s+サブタスク(.+?)(?=\n##\s|\Z)", impl_plan_text, re.DOTALL)
    if not subtask_section_match:
        return []

    section_text = subtask_section_match.group(1)
    subtasks: list[Subtask] = []

    for heading_match in _SUBTASK_HEADING_PATTERN.finditer(section_text):
        subtask_id = int(heading_match.group(1))
        title = heading_match.group(2).strip()
        block = heading_match.group(3)  # ブロック本文 (タイトル行の次から)

        # files を抽出 (インライン形式: files: [`a.py`, `b.py`])
        files: list[str] = []
        inline = _FILES_INLINE_PATTERN.search(block)
        if inline:
            raw = inline.group(1)
            files = [f.strip("`'\"").strip() for f in re.split(r"[,\s]+", raw) if f.strip("`'\"").strip()]
        else:
            # 箇条書き形式: files:\n  - `a.py`
            bullet = _FILES_BULLET_PATTERN.search(block)
            if bullet:
                for line in bullet.group(1).splitlines():
                    stripped = line.strip().lstrip("-* ").strip().strip("`'\"")
                    if stripped:
                        files.append(stripped)

        # depends_on を抽出
        depends_on: list[int] = []
        dep_match = _DEPENDS_ON_PATTERN.search(block)
        if dep_match:
            raw_deps = dep_match.group(1).strip()
            if raw_deps:
                for d in re.split(r"[,\s]+", raw_deps):
                    d = d.strip()
                    if d.isdigit():
                        depends_on.append(int(d))

        # description を抽出
        description = ""
        desc_match = _DESCRIPTION_PATTERN.search(block)
        if desc_match:
            description = desc_match.group(1).strip()

        if not files:
            logger.debug("parse_subtasks: subtask-%d has no files, skipping", subtask_id)
            continue

        subtasks.append(
            Subtask(
                id=subtask_id,
                title=title,
                files=tuple(files),
                description=description,
                depends_on=tuple(depends_on),
            )
        )

    return subtasks


class ImplementExecutor(PhaseExecutor):
    """コード実装フェーズ (サブタスク対応)。

    実装計画に基づいてコードを実装し、テスト・lint を実行した上で
    PR を作成する。計画にサブタスクが含まれる場合はサブタスク単位で
    エージェントを実行する。サブタスクがない場合は旧来のマルチパスループにフォールバック。
    """

    async def execute(self, request: TaskRequest) -> None:
        """実装を実行する。

        計画ファイルにサブタスクセクションがあればサブタスクイテレータで実行し、
        なければ旧来のマルチパスループ (_execute_legacy_multipass) にフォールバックする。

        Args:
            request: タスクリクエスト。
        """
        try:
            await self._tracker.track(
                "phase_start",
                issue_number=request.issue_number,
                phase=str(request.phase),
            )

            wt_path = str(
                await self._workspace.create_worktree(
                    request.repo,
                    request.issue_number,
                    branch_prefix="feature",
                )
            )
            impl_plan = await self._context.read_impl_plan(wt_path, request.issue_number)
            subtasks = parse_subtasks(impl_plan) if impl_plan else []

            if subtasks:
                logger.info(
                    "Issue #%d: subtask mode (%d subtasks)",
                    request.issue_number,
                    len(subtasks),
                )
                total_cost, total_duration, last_result = await self._execute_subtasks(request, subtasks, wt_path)
            else:
                logger.info(
                    "Issue #%d: legacy multipass mode (no subtasks found)",
                    request.issue_number,
                )
                total_cost, total_duration, last_result = await self._execute_legacy_multipass(
                    request, wt_path, impl_plan
                )

            if last_result is None:
                msg = f"Issue #{request.issue_number}: 実装フェーズが結果を返しませんでした。"
                raise RuntimeError(msg)

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
                data={"cost_usd": total_cost, "duration_sec": total_duration},
            )
        except TimeoutError:
            await self._handle_timeout(request)
        except Exception as exc:
            await self._handle_error(request, exc)

    # ------------------------------------------------------------------
    # Subtask execution
    # ------------------------------------------------------------------

    async def _execute_subtasks(
        self,
        request: TaskRequest,
        subtasks: list[Subtask],
        wt_path: str,
    ) -> tuple[float, float, AgentResult | None]:
        """サブタスクを順番に実行する。

        各サブタスクを独立したエージェントセッションで実行し、
        前のサブタスクの git diff をコンテキストとして次に渡す。
        全サブタスク完了後に PR を作成する (PR 作成はここでは行わない)。

        Args:
            request: タスクリクエスト。
            subtasks: サブタスクリスト。
            wt_path: worktree パス。

        Returns:
            (total_cost, total_duration, last_result) のタプル。
        """
        state = self._sm.get_state(self._issue_key(request))
        start_index = state.impl_iteration if state else 0

        total_cost = 0.0
        total_duration = 0.0
        last_result: AgentResult | None = None
        completed_ids: list[int] = []

        for idx, subtask in enumerate(subtasks):
            # resume: 完了済みサブタスクをスキップ
            if idx < start_index:
                completed_ids.append(subtask.id)
                logger.info(
                    "Issue #%d: skipping subtask %d/%d (already done)",
                    request.issue_number,
                    idx + 1,
                    len(subtasks),
                )
                continue

            # 外部遷移検知
            current_phase = self._sm.get_phase(self._issue_key(request))
            if isinstance(current_phase, Phase) and current_phase != Phase.IMPLEMENT:
                logger.warning(
                    "Issue #%d: phase changed externally to %s, aborting subtask loop",
                    request.issue_number,
                    current_phase,
                )
                return total_cost, total_duration, last_result

            logger.info(
                "Issue #%d: subtask %d/%d — %s",
                request.issue_number,
                idx + 1,
                len(subtasks),
                subtask.title,
            )

            prompt = await self._build_subtask_prompt(request, subtask, idx, len(subtasks), wt_path, completed_ids)
            await self._record_branch_baseline(request)

            result = await self.run_agent(request, prompt)
            total_cost += result.cost_usd
            total_duration += result.duration_sec
            last_result = result

            # 変更なしでも次のサブタスクへ進む (suspended にしない)
            try:
                await self._finalize_phase_commit(
                    request,
                    summary=f"subtask-{subtask.id} {subtask.title}",
                    commit_type="feat",
                    branch_prefix="feature",
                )
            except NoChangesError:
                logger.warning(
                    "Issue #%d: subtask %d/%d made no changes, continuing to next",
                    request.issue_number,
                    idx + 1,
                    len(subtasks),
                )

            completed_ids.append(subtask.id)

            # 状態を更新してクラッシュ時のリカバリに備える
            if state:
                state.session_id = result.session_id
                state.impl_iteration = idx + 1

            await self._tracker.track(
                "subtask_complete",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={"subtask_index": idx + 1, "subtask_title": subtask.title},
            )

        return total_cost, total_duration, last_result

    async def _build_subtask_prompt(
        self,
        request: TaskRequest,
        subtask: Subtask,
        subtask_index: int,
        total_subtasks: int,
        wt_path: str,
        completed_ids: list[int],
    ) -> str:
        """サブタスク単位のスコープを絞ったプロンプトを構築する。

        Args:
            request: タスクリクエスト。
            subtask: 実行するサブタスク。
            subtask_index: サブタスクのインデックス (0始まり)。
            total_subtasks: サブタスクの総数。
            wt_path: worktree パス。
            completed_ids: 完了済みサブタスクの ID リスト。

        Returns:
            プロンプト文字列。
        """
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        context = await self._context.build_context(
            wt_path,
            getattr(issue, "body", "") or "",
            "implement",
            issue_number=request.issue_number,
        )

        # 前のサブタスクの変更サマリーを取得
        base_branch = getattr(request.repo, "base_branch", "main")
        rc, diff_stat, _ = await self._workspace._run_git("diff", f"origin/{base_branch}", "--stat", cwd=wt_path)
        prior_diff = diff_stat.strip() if rc == 0 and diff_stat.strip() else "(変更なし)"

        files_list = "\n".join(f"  - `{f}`" for f in subtask.files)

        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        raw = (
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"## サブタスク {subtask_index + 1}/{total_subtasks}: {subtask.title}\n\n"
            f"{context}\n\n"
            f"## 実装スコープ (このパスで実装するファイルのみ)\n"
            f"{files_list}\n\n"
            f"## サブタスクの説明\n"
            f"{subtask.description}\n\n"
            f"## これまでの変更サマリー\n"
            f"```\n{prior_diff}\n```\n\n"
            f"## 実装指示\n"
            f"1. 上記スコープのファイル **のみ** を実装してください\n"
            f"2. スコープ外のファイルは変更しないでください\n"
            f"3. テスト・lint を実行して確認してください\n"
            f"4. **git commit / push は不要です** (システムが行います)\n"
            f"5. **PR は作成しないでください** (全サブタスク完了後にシステムが作成します)\n"
        )
        return enhance_prompt(raw, "implement")

    # ------------------------------------------------------------------
    # Legacy multipass (backward compatibility)
    # ------------------------------------------------------------------

    async def _execute_legacy_multipass(
        self,
        request: TaskRequest,
        wt_path: str,
        impl_plan: str | None,
    ) -> tuple[float, float, AgentResult | None]:
        """旧来のマルチパスループ実行 (サブタスクなし計画のフォールバック)。

        Args:
            request: タスクリクエスト。
            wt_path: worktree パス。
            impl_plan: 実装計画テキスト (None の場合は空集合を使用)。

        Returns:
            (total_cost, total_duration, last_result) のタプル。
        """
        state = self._sm.get_state(self._issue_key(request))
        start_iteration = state.impl_iteration if state else 0
        planned_files = extract_planned_files(impl_plan) if impl_plan else set()

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

            current_phase = self._sm.get_phase(self._issue_key(request))
            if isinstance(current_phase, Phase) and current_phase != Phase.IMPLEMENT:
                logger.warning(
                    "Issue #%d: phase changed externally to %s during implement loop, aborting",
                    request.issue_number,
                    current_phase,
                )
                return total_cost, total_duration, last_result

            prompt = await self._build_pass_prompt(request, iteration, wt_path, planned_files)
            await self._record_branch_baseline(request)

            result = await self.run_agent(request, prompt)
            total_cost += result.cost_usd
            total_duration += result.duration_sec
            last_result = result

            try:
                await self._finalize_phase_commit(
                    request,
                    summary=f"実装パス {iteration + 1}",
                    commit_type="feat",
                    branch_prefix="feature",
                )
            except NoChangesError:
                logger.warning(
                    "Issue #%d: no changes in pass %d, stopping and finalizing with current progress",
                    request.issue_number,
                    iteration + 1,
                )
                break

            if state:
                state.session_id = result.session_id
                state.impl_iteration = iteration + 1

            cur_modified = await self._get_modified_files(request, wt_path)

            cur_planned_done = len(planned_files & cur_modified) if planned_files else 0
            prev_planned_done = len(planned_files & prev_modified) if planned_files else 0
            if iteration > start_iteration and cur_planned_done == prev_planned_done:
                logger.warning(
                    "Issue #%d: no planned files added in pass %d (%d/%d), stopping",
                    request.issue_number,
                    iteration + 1,
                    cur_planned_done,
                    len(planned_files) if planned_files else 0,
                )
                break

            prev_modified = cur_modified

            if not self._should_continue(request, cur_modified, planned_files):
                logger.info(
                    "Issue #%d: implementation sufficiently complete at pass %d",
                    request.issue_number,
                    iteration + 1,
                )
                break

            repo_full_name = self._get_repo_full_name(request)
            await self._notifier.notify(
                f"Issue #{request.issue_number} 実装パス {iteration + 1} 完了、継続中",
                metadata={
                    "notification_type": "impl_continuation",
                    "issue": request.issue_number,
                    "iteration": iteration + 1,
                    "repo": repo_full_name,
                },
            )
            await self._tracker.track(
                "impl_continuation",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={"iteration": iteration + 1},
            )

        return total_cost, total_duration, last_result

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

        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        raw = (
            f"以下の設計書と実装計画に基づいてコードを実装してください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n\n"
            f"{context}\n\n"
            f"## 実装指示\n"
            f"1. 実装計画の順序に従ってコードを実装\n"
            f"2. テストコードも作成\n"
            f"3. テスト・lint・ビルドを実行して確認\n"
            f"4. **git commit / push / PR 作成は不要です** (システムが行います)"
        )
        return enhance_prompt(raw, "implement")

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """互換性のため残す。execute() から直接は呼ばれない。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        await self._finalize_phase_commit(
            request,
            summary="実装を完了",
            commit_type="feat",
            branch_prefix="feature",
        )
        await self._finalize(request, result)

    # ------------------------------------------------------------------
    # Multi-pass helpers
    # ------------------------------------------------------------------

    async def _build_pass_prompt(
        self,
        request: TaskRequest,
        iteration: int,
        wt_path: str,
        planned_files: set[str],
    ) -> str:
        """パスに応じたプロンプトを構築する。

        Args:
            request: タスクリクエスト。
            iteration: 現在のイテレーション番号 (0始まり)。
            wt_path: worktree のパス。
            planned_files: 計画ファイル集合。

        Returns:
            プロンプト文字列。
        """
        if iteration == 0:
            return await self.build_prompt(request)

        # 継続パス: 進捗コンテキスト付き
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        context = await self._context.build_context(
            wt_path,
            getattr(issue, "body", "") or "",
            "implement",
            issue_number=request.issue_number,
        )
        modified = await self._get_modified_files(request, wt_path)
        continuation = self._build_continuation_context(modified, planned_files)

        return (
            f"## Issue #{request.issue_number}: {issue.title} (実装継続パス {iteration + 1})\n\n"
            f"{context}\n\n"
            f"{continuation}\n\n"
            f"## 実装指示\n"
            f"1. 上記の未実装ファイルを実装計画の順序に従って実装\n"
            f"2. 既にコミット済みの内容は変更不要\n"
            f"3. テストコードも作成\n"
            f"4. テスト・lint・ビルドを実行して確認\n"
            f"5. **git commit / push は不要です** (システムが行います)\n"
        )

    @staticmethod
    def _build_continuation_context(
        modified_files: set[str],
        planned_files: set[str],
    ) -> str:
        """継続パス用の進捗コンテキストを構築する。

        Args:
            modified_files: 変更済みファイル集合。
            planned_files: 計画ファイル集合。

        Returns:
            進捗コンテキスト文字列。
        """
        done_files = sorted(modified_files & planned_files)
        remaining_files = sorted(planned_files - modified_files)

        done_list = "\n".join(f"- [x] `{f}`" for f in done_files) or "(なし)"
        remaining_list = "\n".join(f"- [ ] `{f}`" for f in remaining_files) or "(なし)"

        return (
            f"## 実装進捗\n\n"
            f"### 完了済みファイル\n{done_list}\n\n"
            f"### 未実装ファイル (今回実装してください)\n{remaining_list}"
        )

    @staticmethod
    def _should_continue(
        request: TaskRequest,
        modified_files: set[str],
        planned_files: set[str],
    ) -> bool:
        """実装を継続すべきか判定する。

        Args:
            request: タスクリクエスト。
            modified_files: 現在の変更済みファイル集合。
            planned_files: 計画ファイル集合。

        Returns:
            継続すべきなら True。
        """
        if not planned_files:
            return False

        touched = len(planned_files & modified_files)
        ratio = touched / len(planned_files)

        logger.info(
            "Issue #%d: implementation progress %.0f%% (%d/%d planned files)",
            request.issue_number,
            ratio * 100,
            touched,
            len(planned_files),
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

        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id
            state.impl_iteration = 0  # リセット

        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:impl-review")
        await self._sm.transition(self._issue_key(request), "impl-review")
        repo_full_name = self._get_repo_full_name(request)
        pr_url = self._build_pr_url(request, pr_number)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
            metadata={
                "notification_type": "impl_pr_created",
                "issue": request.issue_number,
                "pr": pr_number,
                "pr_url": pr_url,
                "repo": repo_full_name,
                "duration_sec": result.duration_sec,
                "next_action": "→ 実装PRをレビューしてください",
            },
        )
