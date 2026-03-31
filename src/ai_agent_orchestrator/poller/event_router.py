"""EventRouter (イベント→フェーズ遷移).

PollEvent を受け取り、StateMachineManager で遷移を実行し、
TaskQueue にタスクをエンキューする。
Issue タイプに応じたルーティング (Bug -> ANALYSIS, Feature-S -> PLAN_BRIEF 等) を行う。
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from ai_agent_orchestrator.models import EventType, Phase, PollEvent
from ai_agent_orchestrator.orchestrator.task_queue import Priority, TaskRequest

if TYPE_CHECKING:
    from ai_agent_orchestrator.github.client import GitHubClient
    from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
    from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue

logger = logging.getLogger(__name__)


class EventRouter:
    """イベントをフェーズ遷移アクションに変換する.

    PollEvent を受け取り、StateMachineManager で遷移を実行し、
    TaskQueue にタスクをエンキューする。
    Issue タイプに応じたルーティング (Bug -> FIX, Feature-S -> IMPLEMENT 等) を行う。
    """

    def __init__(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        account_manager: object | None = None,
    ) -> None:
        """EventRouter を初期化する.

        Args:
            state_machine: ステートマシンマネージャ.
            task_queue: タスクキュー.
            account_manager: AccountManager (GitHub ラベル更新用、省略可).
        """
        self._sm = state_machine
        self._tq = task_queue
        self._account_manager = account_manager

    async def _get_client(self, repo: object) -> GitHubClient | None:
        """リポジトリに対応する GitHubClient を取得する (省略可能).

        account_manager が設定されていない場合は None を返す。

        Args:
            repo: リポジトリ設定オブジェクト.

        Returns:
            GitHubClient または None.
        """
        if self._account_manager is None:
            return None
        if hasattr(self._account_manager, "get_client_for_repo"):
            owner = getattr(repo, "owner", "")
            repo_name = getattr(repo, "repo", "")
            result: Any = await self._account_manager.get_client_for_repo(owner, repo_name)
            return result  # type: ignore[no-any-return]
        return None

    async def route(self, event: PollEvent) -> None:
        """イベントを処理し、適切な遷移とエンキューを行う.

        Args:
            event: 処理するポーリングイベント.

        イベントとアクションの対応:
            NEW_ISSUE           -> register_issue + TYPE_DETECTION エンキュー
            ISSUE_COMMENT       -> hearing_continue エンキュー (遷移なし)
            HEARING_TIMEOUT     -> SUSPENDED 遷移
            PLAN_REACTION_ADDED -> タイプ別: Bug->FIX, Feature-S->IMPLEMENT
            PLAN_COMMENT_ADDED  -> タイプ別: Bug->ANALYSIS, Feature-S->PLAN_BRIEF
            DESIGN_PR_APPROVED  -> PLANNING 遷移 + エンキュー
            DESIGN_PR_COMMENTED -> DESIGN_REVISE 遷移 + エンキュー
            IMPL_PR_APPROVED    -> DONE 遷移 + エンキュー
            IMPL_PR_COMMENTED   -> IMPL_REVISE 遷移 + エンキュー
            CI_RESULT (failed)  -> CI_FIX (3回以内) or SUSPENDED
            CI_RESULT (passed)  -> IMPL_REVIEW 遷移
            SPLIT_APPROVED      -> SPLIT_EXECUTE 遷移 + エンキュー
            SPLIT_MODIFIED      -> HEARING 遷移 + エンキュー
        """
        logger.info(
            "Routing event: type=%s issue=#%s",
            event.type,
            event.issue.number if event.issue else "N/A",
        )

        # 検知したイベントに👀リアクションを付ける
        await self._add_eyes_reaction(event)

        match event.type:
            case EventType.NEW_ISSUE:
                await self._handle_new_issue(event)
            case EventType.ISSUE_COMMENT:
                await self._handle_hearing_reply(event)
            case EventType.HEARING_TIMEOUT:
                await self._handle_hearing_timeout(event)
            case EventType.PLAN_REACTION_ADDED:
                await self._handle_plan_reaction(event)
            case EventType.PLAN_COMMENT_ADDED:
                await self._handle_plan_comment(event)
            case EventType.DESIGN_PR_APPROVED:
                await self._handle_design_pr_approved(event)
            case EventType.DESIGN_PR_COMMENTED:
                await self._handle_design_pr_commented(event)
            case EventType.IMPL_PR_APPROVED:
                await self._handle_impl_pr_approved(event)
            case EventType.IMPL_PR_COMMENTED:
                await self._handle_impl_pr_commented(event)
            case EventType.CI_RESULT:
                await self._handle_ci_result(event)
            case EventType.SPLIT_APPROVED:
                await self._handle_split_approved(event)
            case EventType.SPLIT_MODIFIED:
                await self._handle_split_modified(event)
            case _:
                logger.warning("Unknown event type: %s", event.type)

    # ------------------------------------------------------------------
    # Reaction helper
    # ------------------------------------------------------------------

    async def _add_eyes_reaction(self, event: PollEvent) -> None:
        """検知したイベントに👀リアクションを付ける."""
        try:
            client = await self._get_client(event.repo)
            if client is None:
                return
            if event.comment is not None:
                await client.add_comment_reaction(
                    event.repo,
                    event.comment.id,
                    "eyes",
                )
            elif event.issue is not None:
                await client.add_issue_reaction(
                    event.repo,
                    event.issue.number,
                    "eyes",
                )
        except Exception:
            logger.debug(
                "Failed to add reaction for event %s",
                event.type,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Recovery helper
    # ------------------------------------------------------------------

    async def _ensure_registered(self, event: PollEvent) -> None:
        """Issue が未登録の場合、ラベルからタイプ・フェーズを推定して自動登録する.

        オーケストレーター再起動後に state.json が消失した場合のリカバリ。
        """
        assert event.issue is not None
        try:
            self._sm.get_phase(event.issue.number)
            return  # 登録済み
        except KeyError:
            pass

        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        labels = [str(lbl.name) if hasattr(lbl, "name") else str(lbl) for lbl in (event.issue.labels or [])]

        # タイプをラベルから推定
        issue_type = "bug"  # デフォルト
        for lbl in labels:
            if lbl.startswith("type:"):
                issue_type = lbl.replace("type:", "")
                break

        # フェーズをラベルから推定
        current_phase = Phase.PLAN_REVIEW  # デフォルト(plan_reaction の呼び出し元)
        for lbl in labels:
            if lbl.startswith("phase:"):
                phase_str = lbl.replace("phase:", "")
                with contextlib.suppress(ValueError):
                    current_phase = Phase(phase_str)
                break

        logger.info(
            "Auto-registering Issue #%d (recovered): type=%s, phase=%s",
            event.issue.number,
            issue_type,
            current_phase.value,
        )
        self._sm.register_issue(
            issue_number=event.issue.number,
            repo=repo_key,
            initial_phase=current_phase,
        )
        self._sm.set_issue_type(event.issue.number, issue_type)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    async def _handle_new_issue(self, event: PollEvent) -> None:
        """新規 Issue: ステートマシンに登録し、TYPE_DETECTION をエンキュー."""
        assert event.issue is not None
        repo_key = f"{event.repo.owner}/{event.repo.repo}"
        # 既に登録済みの場合はスキップ (再ポーリングで重複検知される)
        try:
            self._sm.get_phase(event.issue.number)
            return  # 登録済み
        except KeyError:
            pass  # 未登録 -> 登録に進む
        self._sm.register_issue(
            issue_number=event.issue.number,
            repo=repo_key,
            initial_phase=Phase.TYPE_DETECTION,
        )
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.TYPE_DETECTION.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_hearing_reply(self, event: PollEvent) -> None:
        """ヒアリング回答: HEARING_WAIT → HEARING 遷移して再実行."""
        assert event.comment is not None
        issue_number = int(str(event.comment.issue_url).split("/")[-1])

        # 現在のフェーズを確認
        try:
            current_phase = self._sm.get_phase(issue_number)
        except KeyError:
            logger.warning("Issue #%d is not registered, skipping hearing reply", issue_number)
            return

        if current_phase == Phase.HEARING_WAIT:
            # 回答待ち → hearing に遷移して再実行
            await self._sm.transition(issue_number, Phase.HEARING)
            # ラベル更新
            try:
                client = await self._get_client(event.repo)
                if client:
                    await client.replace_phase_label(event.repo, issue_number, "phase:hearing")
            except Exception:
                logger.warning("Failed to update phase label to hearing for issue #%d", issue_number)
        elif current_phase == Phase.HEARING:
            # AI 実行中にユーザーが回答 → 遷移せずキューイングのみ
            pass
        elif current_phase == Phase.SUSPENDED:
            # SUSPENDED → HEARING に復帰
            await self._sm.transition(issue_number, Phase.HEARING)
            logger.info("Issue #%d resumed from SUSPENDED to HEARING", issue_number)
        else:
            # HEARING/HEARING_WAIT 以外のフェーズなら無視
            logger.info("Issue #%d is in phase %s, ignoring hearing reply", issue_number, current_phase)
            return

        await self._tq.enqueue(
            TaskRequest(
                issue_number=issue_number,
                repo=event.repo,
                phase=Phase.HEARING.value,
                priority=Priority.HIGH,
                extra={"comment": event.comment.body},
            )
        )

    async def _handle_hearing_timeout(self, event: PollEvent) -> None:
        """ヒアリングタイムアウト: SUSPENDED に遷移."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.SUSPENDED)
        try:
            client = await self._get_client(event.repo)
            if client:
                await client.replace_phase_label(event.repo, event.issue.number, "phase:suspended")
        except Exception:
            logger.warning("Failed to update phase label to suspended for issue #%d", event.issue.number)

    async def _handle_plan_reaction(self, event: PollEvent) -> None:
        """方針承認 (thumbsup リアクション): タイプ別に次フェーズへ遷移.

        Bug       -> FIX へ遷移
        Feature-S -> IMPLEMENT へ遷移
        """
        assert event.issue is not None
        # 未登録の場合は自動登録(再起動後のリカバリ)
        await self._ensure_registered(event)
        issue_type = self._sm.get_issue_type(event.issue.number)
        next_phase = Phase.FIX if issue_type == "bug" else Phase.IMPLEMENT

        await self._sm.transition(event.issue.number, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_plan_comment(self, event: PollEvent) -> None:
        """方針指摘コメント: タイプ別に修正フェーズへ遷移.

        Bug       -> ANALYSIS (再分析)
        Feature-S -> PLAN_BRIEF (方針再作成)

        既に ANALYSIS / PLAN_BRIEF にいる場合は遷移をスキップする (重複防止)。
        """
        assert event.issue is not None
        # 現在のフェーズを確認し、既に修正フェーズにいる場合はスキップ
        try:
            current_phase = self._sm.get_phase(event.issue.number)
        except KeyError:
            logger.warning("Issue #%d is not registered, skipping plan comment", event.issue.number)
            return

        issue_type = self._sm.get_issue_type(event.issue.number)
        next_phase = Phase.ANALYSIS if issue_type == "bug" else Phase.PLAN_BRIEF

        if current_phase == next_phase:
            logger.info(
                "Issue #%d already in %s, skipping duplicate plan comment",
                event.issue.number,
                next_phase.value,
            )
            return
        if current_phase != Phase.PLAN_REVIEW:
            logger.info(
                "Issue #%d is in %s (not plan-review), ignoring plan comment",
                event.issue.number,
                current_phase.value,
            )
            return

        await self._sm.transition(event.issue.number, next_phase)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=next_phase.value,
                priority=Priority.NORMAL,
                extra={
                    "feedback": event.comment.body if event.comment else "",
                },
            )
        )

    async def _handle_design_pr_approved(self, event: PollEvent) -> None:
        """設計 PR approve: PLANNING へ遷移してエンキュー."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.PLANNING)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.PLANNING.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_design_pr_commented(self, event: PollEvent) -> None:
        """設計 PR コメント (指摘): DESIGN_REVISE へ遷移してエンキュー."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.DESIGN_REVISE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.DESIGN_REVISE.value,
                priority=Priority.CRITICAL,
                extra={"comments": event.extra or {}},
            )
        )

    async def _handle_impl_pr_approved(self, event: PollEvent) -> None:
        """実装 PR approve: DONE へ遷移し、DoneExecutor をエンキュー."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.DONE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.DONE.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_impl_pr_commented(self, event: PollEvent) -> None:
        """実装 PR コメント (指摘): IMPL_REVISE へ遷移してエンキュー."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.IMPL_REVISE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.IMPL_REVISE.value,
                priority=Priority.CRITICAL,
                extra={"comments": event.extra or {}},
            )
        )

    async def _handle_ci_result(self, event: PollEvent) -> None:
        """CI 結果: extra の ci_status に応じて分岐.

        ci_status == "failure":
            3 回以内 -> CI_FIX へ遷移してエンキュー
            3 回超過 -> SUSPENDED へ遷移 (手動対応が必要)
        ci_status == "success":
            -> IMPL_REVIEW 遷移 (エンキュー不要、PR approve/comment をポーリングで待つ)
        """
        assert event.issue is not None
        ci_status = (event.extra or {}).get("ci_status", "")

        if ci_status == "failure":
            retry_count = await self._sm.get_ci_retry_count(event.issue.number)
            if retry_count < 3:
                await self._sm.transition(event.issue.number, Phase.CI_FIX)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=Phase.CI_FIX.value,
                        priority=Priority.HIGH,
                        extra={
                            "ci_logs": (event.extra or {}).get("ci_logs", ""),
                            "retry_count": retry_count + 1,
                        },
                    )
                )
            else:
                await self._sm.transition(event.issue.number, Phase.SUSPENDED)
                try:
                    client = await self._get_client(event.repo)
                    if client:
                        await client.replace_phase_label(event.repo, event.issue.number, "phase:suspended")
                except Exception:
                    logger.warning("Failed to update phase label to suspended for issue #%d", event.issue.number)
        elif ci_status == "success":
            await self._sm.transition(event.issue.number, Phase.IMPL_REVIEW)
            # IMPL_REVIEW はポーリングで PR approve/comment を待つため、エンキュー不要

    async def _handle_split_approved(self, event: PollEvent) -> None:
        """分割承認 (Feature-L): SPLIT_EXECUTE へ遷移してエンキュー."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.SPLIT_EXECUTE)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.SPLIT_EXECUTE.value,
                priority=Priority.NORMAL,
            )
        )

    async def _handle_split_modified(self, event: PollEvent) -> None:
        """分割修正指示 (Feature-L): HEARING へ遷移して再ヒアリング."""
        assert event.issue is not None
        await self._sm.transition(event.issue.number, Phase.HEARING)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.HEARING.value,
                priority=Priority.NORMAL,
                extra={
                    "modification_request": (event.comment.body if event.comment else ""),
                },
            )
        )
