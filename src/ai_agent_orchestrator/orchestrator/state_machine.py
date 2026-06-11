"""StateMachine (python-statemachine).

IssueWorkflow: python-statemachine ベースの Issue ワークフロー。
StateMachineManager: 複数 Issue の IssueWorkflow を管理し、永続化・イベントログを統括。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from statemachine import State, StateMachine
from statemachine.exceptions import TransitionNotAllowed

from ai_agent_orchestrator.models import IssueKey, IssueState, Phase, make_issue_key

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ai_agent_orchestrator.state_persistence import StatePersistence


# ---------------------------------------------------------------------------
# Tracker Protocol (minimal, for decoupling)
# ---------------------------------------------------------------------------


class Tracker(Protocol):
    """Event tracking protocol."""

    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict[str, Any],
    ) -> None:
        """Record an event."""
        ...


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InvalidTransitionError(Exception):
    """不正な遷移を試みた場合の例外."""


# ---------------------------------------------------------------------------
# Phase <-> State attribute name mapping
# ---------------------------------------------------------------------------

# Phase enum value (e.g. "type-detection") -> State attribute name (e.g. "type_detection")
_PHASE_TO_ATTR: dict[str, str] = {phase.value: phase.value.replace("-", "_") for phase in Phase}

# State attribute name (e.g. "type_detection") -> Phase enum
_ATTR_TO_PHASE: dict[str, Phase] = {phase.value.replace("-", "_"): phase for phase in Phase}


# ---------------------------------------------------------------------------
# TRANSITION_MAP: (current_phase, target_phase) -> transition_event_name
# ---------------------------------------------------------------------------

TRANSITION_MAP: dict[tuple[Phase, Phase], str] = {
    # INTAKE: 情報十分なら PLAN へ直行、曖昧なら CLARIFY
    (Phase.INTAKE, Phase.CLARIFY): "intake_to_clarify",
    (Phase.INTAKE, Phase.PLAN): "intake_to_plan",
    (Phase.INTAKE, Phase.SUSPENDED): "intake_to_suspended",
    # CLARIFY
    (Phase.CLARIFY, Phase.PLAN): "clarify_to_plan",
    (Phase.CLARIFY, Phase.SPLIT): "clarify_to_split",
    (Phase.CLARIFY, Phase.CLARIFY_WAIT): "clarify_to_clarify_wait",
    (Phase.CLARIFY, Phase.SUSPENDED): "clarify_to_suspended",
    (Phase.CLARIFY_WAIT, Phase.CLARIFY): "clarify_wait_to_clarify",
    (Phase.CLARIFY_WAIT, Phase.SUSPENDED): "clarify_wait_to_suspended",
    # SPLIT (提案→承認→実行はフェーズ内で完結)
    (Phase.SPLIT, Phase.DONE): "split_to_done",
    (Phase.SPLIT, Phase.CLARIFY): "split_to_clarify",
    (Phase.SPLIT, Phase.BLOCKED): "split_to_blocked",
    (Phase.SPLIT, Phase.SUSPENDED): "split_to_suspended",
    # PLAN -> APPROVE ゲート
    (Phase.PLAN, Phase.APPROVE): "plan_to_approve",
    (Phase.PLAN, Phase.SUSPENDED): "plan_to_suspended",
    # APPROVE: 承認 -> IMPLEMENT / 差し戻し -> PLAN
    (Phase.APPROVE, Phase.IMPLEMENT): "approve_to_implement",
    (Phase.APPROVE, Phase.PLAN): "approve_to_plan",
    (Phase.APPROVE, Phase.SUSPENDED): "approve_to_suspended",
    # IMPLEMENT: 完了 -> REVIEW / CI失敗 -> REVISE
    (Phase.IMPLEMENT, Phase.REVIEW): "implement_to_review",
    (Phase.IMPLEMENT, Phase.REVISE): "implement_to_revise",
    (Phase.IMPLEMENT, Phase.SUSPENDED): "implement_to_suspended",
    # REVIEW: マージ -> DONE / 指摘・CI失敗 -> REVISE
    (Phase.REVIEW, Phase.DONE): "review_to_done",
    (Phase.REVIEW, Phase.REVISE): "review_to_revise",
    (Phase.REVIEW, Phase.SUSPENDED): "review_to_suspended",
    # REVISE: 対応後 REVIEW へ。連続 CI 失敗等の自己ループを許可
    (Phase.REVISE, Phase.REVIEW): "revise_to_review",
    (Phase.REVISE, Phase.REVISE): "revise_to_revise",
    (Phase.REVISE, Phase.SUSPENDED): "revise_to_suspended",
    # BLOCKED
    (Phase.BLOCKED, Phase.CLARIFY): "blocked_to_clarify",
    (Phase.BLOCKED, Phase.PLAN): "blocked_to_plan",
    (Phase.BLOCKED, Phase.IMPLEMENT): "blocked_to_implement",
    # SUSPENDED -> resume
    (Phase.SUSPENDED, Phase.INTAKE): "resume_to_intake",
    (Phase.SUSPENDED, Phase.CLARIFY): "resume_to_clarify",
    (Phase.SUSPENDED, Phase.CLARIFY_WAIT): "resume_to_clarify_wait",
    (Phase.SUSPENDED, Phase.SPLIT): "resume_to_split",
    (Phase.SUSPENDED, Phase.PLAN): "resume_to_plan",
    (Phase.SUSPENDED, Phase.APPROVE): "resume_to_approve",
    (Phase.SUSPENDED, Phase.IMPLEMENT): "resume_to_implement",
    (Phase.SUSPENDED, Phase.REVIEW): "resume_to_review",
    (Phase.SUSPENDED, Phase.REVISE): "resume_to_revise",
}


# ---------------------------------------------------------------------------
# IssueWorkflow (StateMachine)
# ---------------------------------------------------------------------------


class IssueWorkflow(StateMachine):
    """python-statemachine ベースの Issue ワークフロー (U5 #83: 統一パイプライン).

    9 フェーズ + 補助状態 (clarify-wait / blocked / suspended) の 12 State。
    タイプ別の分岐はフェーズではなくパラメータで表現するため、ガード関数は
    持たない (遷移先はルーター/executor が明示的に指定する)。
    """

    # --- States (12) ---
    intake = State("Intake", initial=True)
    clarify = State("Clarify")
    clarify_wait = State("Clarify wait")
    split = State("Split")
    plan = State("Plan")
    approve = State("Approve")
    implement = State("Implement")
    review = State("Review")
    revise = State("Revise")
    blocked = State("Blocked")
    done = State("Done", final=True)
    suspended = State("Suspended")

    # --- INTAKE ---
    intake_to_clarify = intake.to(clarify)
    intake_to_plan = intake.to(plan)
    intake_to_suspended = intake.to(suspended)

    # --- CLARIFY ---
    clarify_to_plan = clarify.to(plan)
    clarify_to_split = clarify.to(split)
    clarify_to_clarify_wait = clarify.to(clarify_wait)
    clarify_to_suspended = clarify.to(suspended)
    clarify_wait_to_clarify = clarify_wait.to(clarify)
    clarify_wait_to_suspended = clarify_wait.to(suspended)

    # --- SPLIT ---
    split_to_done = split.to(done)
    split_to_clarify = split.to(clarify)
    split_to_blocked = split.to(blocked)
    split_to_suspended = split.to(suspended)

    # --- PLAN -> APPROVE ---
    plan_to_approve = plan.to(approve)
    plan_to_suspended = plan.to(suspended)

    # --- APPROVE (ゲート) ---
    approve_to_implement = approve.to(implement)
    approve_to_plan = approve.to(plan)
    approve_to_suspended = approve.to(suspended)

    # --- IMPLEMENT ---
    implement_to_review = implement.to(review)
    implement_to_revise = implement.to(revise)
    implement_to_suspended = implement.to(suspended)

    # --- REVIEW (ゲート) ---
    review_to_done = review.to(done)
    review_to_revise = review.to(revise)
    review_to_suspended = review.to(suspended)

    # --- REVISE ---
    revise_to_review = revise.to(review)
    revise_to_revise = revise.to(revise)
    revise_to_suspended = revise.to(suspended)

    # --- BLOCKED ---
    blocked_to_clarify = blocked.to(clarify)
    blocked_to_plan = blocked.to(plan)
    blocked_to_implement = blocked.to(implement)

    # --- SUSPENDED -> resume ---
    resume_to_intake = suspended.to(intake)
    resume_to_clarify = suspended.to(clarify)
    resume_to_clarify_wait = suspended.to(clarify_wait)
    resume_to_split = suspended.to(split)
    resume_to_plan = suspended.to(plan)
    resume_to_approve = suspended.to(approve)
    resume_to_implement = suspended.to(implement)
    resume_to_review = suspended.to(review)
    resume_to_revise = suspended.to(revise)

    def __init__(
        self,
        issue_type: str = "",
        start_value: str | None = None,
    ) -> None:
        """初期化.

        Args:
            issue_type: Issue タイプ ("bug", "feature-m", "feature-l")。
                フェーズ分岐には使わず、plan_depth 等のパラメータ導出に使う。
            start_value: 復元時の初期ステート値 (State の value = attribute name)
        """
        self._issue_type = issue_type
        super().__init__(start_value=start_value)

    @property
    def issue_type(self) -> str:
        """Issue タイプを取得."""
        return self._issue_type

    @issue_type.setter
    def issue_type(self, value: str) -> None:
        """Issue タイプを設定."""
        self._issue_type = value


# ---------------------------------------------------------------------------
# StateMachineManager
# ---------------------------------------------------------------------------


class StateMachineManager:
    """複数 Issue の IssueWorkflow インスタンスを管理し、永続化・イベントログ記録を統括する.

    Attributes:
        _persistence: 状態永続化ストレージ。
        _tracker: イベントトラッカー。
        _states: IssueKey -> IssueState のマッピング。
        _workflows: IssueKey -> IssueWorkflow のマッピング。
    """

    def __init__(
        self,
        persistence: StatePersistence,
        tracker: Tracker,
    ) -> None:
        """初期化.

        Args:
            persistence: 状態永続化ストレージ。
            tracker: イベントトラッカー。
        """
        self._persistence = persistence
        self._tracker = tracker
        self._states: dict[IssueKey, IssueState] = {}
        self._workflows: dict[IssueKey, IssueWorkflow] = {}
        self._locks: dict[IssueKey, asyncio.Lock] = {}

    def register_issue(
        self,
        issue_number: int,
        repo: str,
        initial_phase: Phase = Phase.INTAKE,
    ) -> None:
        """新規 Issue をステートマシンに登録する.

        Args:
            issue_number: Issue 番号。
            repo: "owner/repo" 形式のリポジトリキー。
            initial_phase: 初期フェーズ (デフォルト: INTAKE)。

        Raises:
            ValueError: 既に登録済みの Issue を指定した場合。
        """
        key = make_issue_key(repo, issue_number)
        if key in self._states:
            msg = f"Issue #{issue_number} ({repo}) is already registered"
            raise ValueError(msg)

        now = datetime.now(UTC).isoformat()
        state = IssueState(
            issue_number=issue_number,
            phase=initial_phase,
            repo=repo,
            created_at=now,
            updated_at=now,
        )
        self._states[key] = state
        self._workflows[key] = IssueWorkflow(
            start_value=self._phase_to_state_id(initial_phase),
        )
        self._auto_save()

    def _get_lock(self, issue_key: IssueKey) -> asyncio.Lock:
        """Issue 単位のロックを取得する。存在しなければ作成."""
        if issue_key not in self._locks:
            self._locks[issue_key] = asyncio.Lock()
        return self._locks[issue_key]

    async def transition(
        self,
        issue_key: IssueKey,
        new_phase: Phase | str,
    ) -> None:
        """フェーズ遷移を実行する.

        内部で python-statemachine の遷移メソッドを呼び出し、
        イベントログ記録・永続化を自動実行する。
        Issue 単位の asyncio.Lock で排他制御を行い、
        ポーラーとワーカーの同時遷移による競合を防止する。

        Args:
            issue_key: IssueKey (repo, issue_number)。
            new_phase: 遷移先のフェーズ (Phase enum or str)。

        Raises:
            KeyError: 未登録の Issue。
            InvalidTransitionError: 許可されていない遷移。
        """
        async with self._get_lock(issue_key):
            await self._transition_inner(issue_key, new_phase)

    async def _transition_inner(
        self,
        issue_key: IssueKey,
        new_phase: Phase | str,
    ) -> None:
        """ロック保持下でフェーズ遷移を実行する内部メソッド."""
        if issue_key not in self._states:
            msg = f"Issue #{issue_key[1]} ({issue_key[0]}) is not registered"
            raise KeyError(msg)

        state = self._states[issue_key]
        workflow = self._workflows[issue_key]
        old_phase = state.phase
        target = Phase(new_phase) if isinstance(new_phase, str) else new_phase

        # 同一フェーズへの遷移は no-op (再起動後の重複検出対策)
        if old_phase == target:
            logger.info(
                "Issue #%d is already in %s, skipping no-op transition",
                issue_key[1],
                target.value,
            )
            return

        try:
            self._execute_transition(workflow, old_phase, target)
        except InvalidTransitionError:
            raise
        except TransitionNotAllowed as e:
            raise InvalidTransitionError(
                f"Cannot transition Issue #{issue_key[1]} ({issue_key[0]}) from {old_phase} to {target}: {e}"
            ) from e

        state.phase = target
        state.updated_at = datetime.now(UTC).isoformat()
        self._auto_save()

        await self._tracker.track(
            "phase_transition",
            issue_number=issue_key[1],
            phase=target.value,
            data={"from": old_phase.value, "to": target.value},
        )

    def _execute_transition(
        self,
        workflow: IssueWorkflow,
        current: Phase,
        target: Phase,
    ) -> None:
        """python-statemachine の遷移メソッドを動的に呼び出す.

        current -> target に対応する遷移名を _resolve_transition() で解決し、
        send() で遷移を実行する。
        """
        transition_name = self._resolve_transition(workflow, current, target)
        workflow.send(transition_name)

    def _resolve_transition(
        self,
        wf: IssueWorkflow,
        current: Phase,
        target: Phase,
    ) -> str:
        """(current, target) に対応する遷移名を解決する.

        統一パイプライン (U5 #83) では遷移先をルーター/executor が明示的に
        指定するため、issue_type による動的解決は不要になった。
        """
        transition_name = TRANSITION_MAP.get((current, target))
        if transition_name is None:
            msg = f"No transition defined from {current} to {target}"
            raise InvalidTransitionError(msg)
        return transition_name

    def get_phase(self, issue_key: IssueKey) -> Phase:
        """Issue の現在のフェーズを取得する.

        Args:
            issue_key: IssueKey (repo, issue_number)。

        Returns:
            現在の Phase。

        Raises:
            KeyError: 未登録の Issue。
        """
        return self._states[issue_key].phase

    def get_issue_type(self, issue_key: IssueKey) -> str:
        """Issue のタイプを取得する.

        Args:
            issue_key: IssueKey (repo, issue_number)。

        Returns:
            Issue タイプ文字列 ("bug" | "feature-m" | "feature-l" | "")。
        """
        state = self._states.get(issue_key)
        return state.issue_type if state else ""

    def set_issue_type(self, issue_key: IssueKey, issue_type: str) -> None:
        """Issue のタイプを設定する.

        plan_depth 等のパラメータ導出に使う issue_type を更新する。

        Args:
            issue_key: IssueKey (repo, issue_number)。
            issue_type: "bug" | "feature-m" | "feature-l"。

        Raises:
            KeyError: 未登録の Issue。
            ValueError: 不正なタイプ文字列。
        """
        valid_types = {"bug", "feature-m", "feature-l"}
        if issue_type not in valid_types:
            msg = f"Invalid issue type: {issue_type}. Must be one of {valid_types}"
            raise ValueError(msg)
        self._states[issue_key].issue_type = issue_type
        self._workflows[issue_key].issue_type = issue_type
        self._auto_save()

    async def get_ci_retry_count(self, issue_key: IssueKey) -> int:
        """CI 修正リトライ回数を取得する."""
        state = self._states.get(issue_key)
        return state.retry_count if state else 0

    async def increment_ci_retry(self, issue_key: IssueKey) -> None:
        """CI 修正リトライ回数をインクリメントする."""
        if issue_key in self._states:
            self._states[issue_key].retry_count += 1
            self._auto_save()

    def get_state(self, issue_key: IssueKey) -> IssueState | None:
        """IssueState を取得する。未登録の場合は None."""
        return self._states.get(issue_key)

    def load_from_persistence(self) -> None:
        """永続化ストレージから状態を復元する。起動時に呼び出す.

        python-statemachine の公式 API である start_value を使用して
        初期状態を指定する。
        """
        self._states = self._persistence.load()
        # マイグレーション: feature-s → feature-m (廃止タイプの読み替え)。
        # phase の読み替えは persistence 層 (PHASE_MIGRATION) に一本化済みのため
        # ここでは issue_type のみ変更する
        for state in self._states.values():
            if state.issue_type == "feature-s":
                state.issue_type = "feature-m"
                logger.info(
                    "Migrated issue #%d from feature-s to feature-m (phase=%s)",
                    state.issue_number,
                    state.phase.value,
                )
        for issue_key, state in self._states.items():
            wf = IssueWorkflow(
                issue_type=state.issue_type,
                start_value=self._phase_to_state_id(state.phase),
            )
            self._workflows[issue_key] = wf

    @staticmethod
    def _phase_to_state_id(phase: Phase) -> str:
        """Phase enum を python-statemachine の State value に変換する.

        State の value は attribute name (e.g. "type_detection")。
        Phase.value (e.g. "type-detection") からハイフンをアンダースコアに変換する。
        """
        return _PHASE_TO_ATTR[phase.value]

    def persist(self) -> None:
        """現在の状態を明示的に永続化する.

        遷移を伴わない IssueState フィールドの更新
        (acknowledged/answered_review_comment_ids 等) の保存に使用する。
        デバウンスなしで即時にファイル書き込みを行う (呼び出しは
        1イベントあたり高々数回を想定)。
        """
        self._auto_save()

    def _auto_save(self) -> None:
        """状態変更時に自動的に永続化する."""
        self._persistence.save(self._states)
