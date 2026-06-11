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
    # TYPE_DETECTION branches
    (Phase.TYPE_DETECTION, Phase.ANALYSIS): "detect_bug",
    (Phase.TYPE_DETECTION, Phase.SUSPENDED): "type_detection_to_suspended",
    # NOTE: (TYPE_DETECTION, HEARING) is resolved dynamically by _resolve_transition
    # Bug workflow
    (Phase.ANALYSIS, Phase.PLAN_REVIEW): "analysis_to_plan_review",
    (Phase.ANALYSIS, Phase.SUSPENDED): "analysis_to_suspended",
    (Phase.PLAN_REVIEW, Phase.FIX): "plan_review_to_fix",
    (Phase.PLAN_REVIEW, Phase.ANALYSIS): "plan_review_to_analysis",
    (Phase.FIX, Phase.CI_FIX): "fix_to_ci_fix",
    (Phase.FIX, Phase.IMPL_REVIEW): "fix_to_impl_review",
    (Phase.FIX, Phase.SUSPENDED): "fix_to_suspended",
    # HEARING branches
    (Phase.HEARING, Phase.DESIGN): "hearing_to_design",
    (Phase.HEARING, Phase.SPLIT_PROPOSAL): "hearing_to_split_proposal",
    (Phase.HEARING, Phase.ANALYSIS): "hearing_to_analysis",
    (Phase.HEARING, Phase.SUSPENDED): "hearing_to_suspended",
    (Phase.HEARING, Phase.HEARING_WAIT): "hearing_to_hearing_wait",
    (Phase.HEARING_WAIT, Phase.HEARING): "hearing_wait_to_hearing",
    (Phase.HEARING_WAIT, Phase.SUSPENDED): "hearing_wait_to_suspended",
    # Feature-M workflow
    (Phase.DESIGN, Phase.DESIGN_REVIEW): "design_to_design_review",
    (Phase.DESIGN, Phase.SUSPENDED): "design_to_suspended",
    (Phase.DESIGN_REVIEW, Phase.IMPLEMENT): "design_review_to_implement",
    (Phase.DESIGN_REVIEW, Phase.DESIGN_REVISE): "design_review_to_design_revise",
    (Phase.DESIGN_REVIEW, Phase.SUSPENDED): "design_review_to_suspended",
    (Phase.DESIGN_REVISE, Phase.DESIGN_REVIEW): "design_revise_to_design_review",
    (Phase.DESIGN_REVISE, Phase.SUSPENDED): "design_revise_to_suspended",
    # Feature-L workflow
    (Phase.SPLIT_PROPOSAL, Phase.SPLIT_EXECUTE): "split_proposal_to_split_execute",
    (Phase.SPLIT_PROPOSAL, Phase.HEARING): "split_proposal_to_hearing",
    (Phase.SPLIT_PROPOSAL, Phase.SUSPENDED): "split_proposal_to_suspended",
    (Phase.SPLIT_EXECUTE, Phase.DONE): "split_execute_to_done",
    (Phase.SPLIT_EXECUTE, Phase.BLOCKED): "split_execute_to_blocked",
    (Phase.SPLIT_EXECUTE, Phase.SUSPENDED): "split_execute_to_suspended",
    # Common: implement / review
    (Phase.IMPLEMENT, Phase.CI_FIX): "implement_to_ci_fix",
    (Phase.IMPLEMENT, Phase.IMPL_REVIEW): "implement_to_impl_review",
    (Phase.IMPLEMENT, Phase.SUSPENDED): "implement_to_suspended",
    (Phase.CI_FIX, Phase.IMPL_REVIEW): "ci_fix_to_impl_review",
    (Phase.CI_FIX, Phase.CI_FIX): "ci_fix_to_ci_fix",
    (Phase.CI_FIX, Phase.SUSPENDED): "ci_fix_to_suspended",
    (Phase.IMPL_REVIEW, Phase.DONE): "impl_review_to_done",
    (Phase.IMPL_REVIEW, Phase.IMPL_REVISE): "impl_review_to_impl_revise",
    (Phase.IMPL_REVIEW, Phase.CI_FIX): "impl_review_to_ci_fix",
    (Phase.IMPL_REVIEW, Phase.SUSPENDED): "impl_review_to_suspended",
    (Phase.IMPL_REVISE, Phase.IMPL_REVIEW): "impl_revise_to_impl_review",
    (Phase.IMPL_REVISE, Phase.SUSPENDED): "impl_revise_to_suspended",
    # BLOCKED
    (Phase.BLOCKED, Phase.HEARING): "blocked_to_hearing",
    (Phase.BLOCKED, Phase.ANALYSIS): "blocked_to_analysis",
    (Phase.BLOCKED, Phase.IMPLEMENT): "blocked_to_implement",
    # SUSPENDED -> resume
    (Phase.SUSPENDED, Phase.TYPE_DETECTION): "resume_to_type_detection",
    (Phase.SUSPENDED, Phase.HEARING): "resume_to_hearing",
    (Phase.SUSPENDED, Phase.ANALYSIS): "resume_to_analysis",
    (Phase.SUSPENDED, Phase.DESIGN): "resume_to_design",
    (Phase.SUSPENDED, Phase.IMPLEMENT): "resume_to_implement",
    (Phase.SUSPENDED, Phase.FIX): "resume_to_fix",
    (Phase.SUSPENDED, Phase.PLAN_REVIEW): "resume_to_plan_review",
    (Phase.SUSPENDED, Phase.CI_FIX): "resume_to_ci_fix",
    (Phase.SUSPENDED, Phase.IMPL_REVIEW): "resume_to_impl_review",
    (Phase.SUSPENDED, Phase.IMPL_REVISE): "resume_to_impl_revise",
}


# ---------------------------------------------------------------------------
# IssueWorkflow (StateMachine)
# ---------------------------------------------------------------------------


class IssueWorkflow(StateMachine):
    """python-statemachine ベースの Issue ワークフロー.

    18 の State を定義し、タイプ別のガード関数で遷移を制御する。
    """

    # --- States (17) ---
    type_detection = State("Type detection", initial=True)
    analysis = State("Analysis")
    fix = State("Fix")
    plan_review = State("Plan review")
    hearing = State("Hearing")
    design = State("Design")
    design_review = State("Design review")
    design_revise = State("Design revise")
    split_proposal = State("Split proposal")
    split_execute = State("Split execute")
    blocked = State("Blocked")
    implement = State("Implement")
    ci_fix = State("CI fix")
    impl_review = State("Impl review")
    impl_revise = State("Impl revise")
    done = State("Done", final=True)
    suspended = State("Suspended")

    # --- TYPE_DETECTION branches ---
    detect_bug = type_detection.to(analysis, cond="is_bug")
    detect_feature_m = type_detection.to(hearing, cond="is_feature_m")
    detect_feature_l = type_detection.to(hearing, cond="is_feature_l")
    type_detection_to_suspended = type_detection.to(suspended)

    # --- Bug workflow ---
    analysis_to_plan_review = analysis.to(plan_review)
    analysis_to_suspended = analysis.to(suspended)

    plan_review_to_fix = plan_review.to(fix, cond="is_bug")
    plan_review_to_analysis = plan_review.to(analysis, cond="is_bug")

    fix_to_ci_fix = fix.to(ci_fix)
    fix_to_impl_review = fix.to(impl_review)
    fix_to_suspended = fix.to(suspended)

    # --- HEARING (Feature-M/L common entry) ---
    hearing_to_design = hearing.to(design, cond="is_feature_m")
    hearing_to_split_proposal = hearing.to(split_proposal, cond="is_feature_l")
    hearing_to_analysis = hearing.to(analysis, cond="is_bug")
    hearing_to_suspended = hearing.to(suspended)

    # --- HEARING_WAIT (waiting for user reply) ---
    hearing_wait = State("Hearing wait")
    hearing_to_hearing_wait = hearing.to(hearing_wait)
    hearing_wait_to_hearing = hearing_wait.to(hearing)
    hearing_wait_to_suspended = hearing_wait.to(suspended)

    # --- Feature-M workflow ---
    design_to_design_review = design.to(design_review)
    design_to_suspended = design.to(suspended)

    design_review_to_implement = design_review.to(implement)
    design_review_to_design_revise = design_review.to(design_revise)
    design_review_to_suspended = design_review.to(suspended)

    design_revise_to_design_review = design_revise.to(design_review)
    design_revise_to_suspended = design_revise.to(suspended)

    # --- Feature-L workflow ---
    split_proposal_to_split_execute = split_proposal.to(split_execute)
    split_proposal_to_hearing = split_proposal.to(hearing)
    split_proposal_to_suspended = split_proposal.to(suspended)

    split_execute_to_done = split_execute.to(done)
    split_execute_to_blocked = split_execute.to(blocked)
    split_execute_to_suspended = split_execute.to(suspended)

    # --- Common: implement / review ---
    implement_to_ci_fix = implement.to(ci_fix)
    implement_to_impl_review = implement.to(impl_review)
    implement_to_suspended = implement.to(suspended)

    ci_fix_to_impl_review = ci_fix.to(impl_review)
    ci_fix_to_ci_fix = ci_fix.to(ci_fix)
    ci_fix_to_suspended = ci_fix.to(suspended)

    impl_review_to_done = impl_review.to(done)
    impl_review_to_impl_revise = impl_review.to(impl_revise)
    impl_review_to_ci_fix = impl_review.to(ci_fix)
    impl_review_to_suspended = impl_review.to(suspended)

    impl_revise_to_impl_review = impl_revise.to(impl_review)
    impl_revise_to_suspended = impl_revise.to(suspended)

    # --- BLOCKED ---
    blocked_to_hearing = blocked.to(hearing)
    blocked_to_analysis = blocked.to(analysis)
    blocked_to_implement = blocked.to(implement)

    # --- SUSPENDED -> resume ---
    resume_to_type_detection = suspended.to(type_detection)
    resume_to_hearing = suspended.to(hearing)
    resume_to_analysis = suspended.to(analysis)
    resume_to_design = suspended.to(design)
    resume_to_implement = suspended.to(implement)
    resume_to_fix = suspended.to(fix)
    resume_to_plan_review = suspended.to(plan_review)
    resume_to_ci_fix = suspended.to(ci_fix)
    resume_to_impl_review = suspended.to(impl_review)
    resume_to_impl_revise = suspended.to(impl_revise)

    def __init__(
        self,
        issue_type: str = "",
        start_value: str | None = None,
    ) -> None:
        """初期化.

        Args:
            issue_type: Issue タイプ ("bug", "feature-m", "feature-l")
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

    def is_bug(self) -> bool:
        """Bug タイプの場合に True を返すガード."""
        return self._issue_type == "bug"

    def is_feature_m(self) -> bool:
        """Feature-M タイプの場合に True を返すガード."""
        return self._issue_type == "feature-m"

    def is_feature_l(self) -> bool:
        """Feature-L タイプの場合に True を返すガード."""
        return self._issue_type == "feature-l"


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
        initial_phase: Phase = Phase.TYPE_DETECTION,
    ) -> None:
        """新規 Issue をステートマシンに登録する.

        Args:
            issue_number: Issue 番号。
            repo: "owner/repo" 形式のリポジトリキー。
            initial_phase: 初期フェーズ (デフォルト: TYPE_DETECTION)。

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
        """issue_type を考慮して正しい遷移名を解決する.

        TRANSITION_MAP のキー衝突を回避するため、
        (TYPE_DETECTION, HEARING) のように同一キーで複数の遷移名が必要な場合は
        issue_type に基づいて動的に解決する。
        """
        # TYPE_DETECTION -> HEARING: issue_type で遷移名を切り替え
        if current == Phase.TYPE_DETECTION and target == Phase.HEARING:
            issue_type = wf.issue_type
            type_map: dict[str, str] = {
                "feature-m": "detect_feature_m",
                "feature-l": "detect_feature_l",
            }
            name = type_map.get(issue_type)
            if name is None:
                msg = f"No transition from TYPE_DETECTION to HEARING for issue_type={issue_type!r}"
                raise InvalidTransitionError(msg)
            return name

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

        IssueWorkflow のガード関数で使用される issue_type も同時に更新する。

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
        # マイグレーション: feature-s → feature-m
        for state in self._states.values():
            if state.issue_type == "feature-s":
                state.issue_type = "feature-m"
                if state.phase.value == "plan-brief" or state.phase.value == "plan-review":
                    state.phase = Phase("hearing")
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
