# 実装仕様書: StateMachine

**対象モジュール**: `src/ai_agent_orchestrator/orchestrator/state_machine.py`

---

## 1. 概要

Issue のフェーズ遷移を管理するステートマシン。`python-statemachine` ライブラリを使用し、
19 種類の Phase 状態と、タイプ別に許可された遷移を定義する。
遷移時には GitHub ラベルの更新、イベントログの記録、ファイルベースの状態永続化を自動的に行う。

---

## 2. 依存パッケージ

```
python-statemachine>=2.3.0
```

---

## 3. Imports

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from statemachine import StateMachine, State
from statemachine.exceptions import TransitionNotAllowed

if TYPE_CHECKING:
    from ai_agent_orchestrator.orchestrator.state_persistence import StatePersistence
    from ai_agent_orchestrator.protocols import Tracker
```

---

## 4. Phase Enum (全19状態)

```python
class Phase(StrEnum):
    """Issue のフェーズを表す列挙型。"""

    # タイプ判定
    TYPE_DETECTION = "type-detection"

    # Bug 専用
    ANALYSIS = "analysis"
    FIX = "fix"

    # Feature-S 専用
    PLAN_BRIEF = "plan-brief"
    PLAN_REVIEW = "plan-review"

    # Feature-M/L 共通
    HEARING = "hearing"
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"
    PLANNING = "planning"

    # Feature-L 専用
    SPLIT_PROPOSAL = "split-proposal"
    SPLIT_EXECUTE = "split-execute"

    # 依存待ち
    BLOCKED = "blocked"

    # 共通フェーズ
    IMPLEMENT = "implement"
    CI_FIX = "ci-fix"
    IMPL_REVIEW = "impl-review"
    IMPL_REVISE = "impl-revise"
    DONE = "done"
    SUSPENDED = "suspended"
```

---

## 5. IssueState データクラス

```python
@dataclass
class IssueState:
    """Issue 単位の状態を管理するデータクラス。

    Note:
        IssueState は設計原則の Immutable Data に反してミュータブルだが、
        状態管理の特性上（phase, session_id 等が頻繁に更新される）、
        frozen=False が実用的。代替案として replace() パターンも検討可能だが、
        パフォーマンスと可読性の観点からミュータブルを採用。
    """

    issue_number: int
    phase: Phase
    issue_type: str = ""            # "bug" | "feature-s" | "feature-m" | "feature-l"
    repo: str = ""                  # "owner/repo" 形式
    session_id: str | None = None
    pr_number: int | None = None
    design_pr_number: int | None = None
    retry_count: int = 0
    created_at: str = ""            # ISO 8601
    updated_at: str = ""            # ISO 8601
```

---

## 6. IssueWorkflow クラス (StateMachine)

### 6.1 クラス定義

```python
class IssueWorkflow(StateMachine):
    """python-statemachine ベースの Issue ワークフロー。

    19 の State を定義し、タイプ別のガード関数で遷移を制御する。
    """

    # --- States (19) ---
    type_detection = State("type-detection", initial=True)
    analysis = State("analysis")
    fix = State("fix")
    plan_brief = State("plan-brief")
    plan_review = State("plan-review")
    hearing = State("hearing")
    design = State("design")
    design_review = State("design-review")
    design_revise = State("design-revise")
    planning = State("planning")
    split_proposal = State("split-proposal")
    split_execute = State("split-execute")
    blocked = State("blocked")
    implement = State("implement")
    ci_fix = State("ci-fix")
    impl_review = State("impl-review")
    impl_revise = State("impl-revise")
    done = State("done", final=True)
    suspended = State("suspended")
```

### 6.2 遷移 (Transitions)

```python
    # --- TYPE_DETECTION からの分岐 ---
    detect_bug = type_detection.to(analysis, cond="is_bug")
    detect_feature_s = type_detection.to(hearing, cond="is_feature_s")
    detect_feature_m = type_detection.to(hearing, cond="is_feature_m")
    detect_feature_l = type_detection.to(hearing, cond="is_feature_l")

    # --- Bug ワークフロー ---
    analysis_to_plan_review = analysis.to(plan_review)
    analysis_to_suspended = analysis.to(suspended)

    plan_review_to_fix = plan_review.to(fix, cond="is_bug")           # 👍承認
    plan_review_to_implement = plan_review.to(implement, cond="is_feature_s")  # 👍承認
    plan_review_to_analysis = plan_review.to(analysis, cond="is_bug")  # 指摘 → 再分析
    plan_review_to_plan_brief = plan_review.to(plan_brief, cond="is_feature_s")  # 指摘 → 再作成

    fix_to_ci_fix = fix.to(ci_fix)
    fix_to_impl_review = fix.to(impl_review)
    fix_to_suspended = fix.to(suspended)

    # --- Feature-S ワークフロー ---
    plan_brief_to_plan_review = plan_brief.to(plan_review)
    plan_brief_to_suspended = plan_brief.to(suspended)

    # --- HEARING (Feature-S/M/L 共通起点) ---
    hearing_to_design = hearing.to(design, cond="is_feature_m")
    hearing_to_plan_brief = hearing.to(plan_brief, cond="is_feature_s")
    hearing_to_split_proposal = hearing.to(split_proposal, cond="is_feature_l")
    hearing_to_analysis = hearing.to(analysis, cond="is_bug")
    hearing_to_suspended = hearing.to(suspended)

    # --- Feature-M ワークフロー ---
    design_to_design_review = design.to(design_review)
    design_to_suspended = design.to(suspended)

    design_review_to_planning = design_review.to(planning)       # PR approve
    design_review_to_design_revise = design_review.to(design_revise)  # 指摘コメント
    design_review_to_suspended = design_review.to(suspended)

    design_revise_to_design_review = design_revise.to(design_review)
    design_revise_to_suspended = design_revise.to(suspended)

    planning_to_implement = planning.to(implement)
    planning_to_suspended = planning.to(suspended)

    # --- Feature-L ワークフロー ---
    split_proposal_to_split_execute = split_proposal.to(split_execute)   # 👍承認
    split_proposal_to_hearing = split_proposal.to(hearing)               # 修正指示
    split_proposal_to_suspended = split_proposal.to(suspended)

    split_execute_to_done = split_execute.to(done)
    split_execute_to_suspended = split_execute.to(suspended)

    # --- 共通: 実装・レビュー ---
    implement_to_ci_fix = implement.to(ci_fix)
    implement_to_impl_review = implement.to(impl_review)
    implement_to_suspended = implement.to(suspended)

    ci_fix_to_impl_review = ci_fix.to(impl_review)
    ci_fix_to_ci_fix = ci_fix.to(ci_fix)             # CI再失敗 → 再修正
    ci_fix_to_suspended = ci_fix.to(suspended)

    impl_review_to_done = impl_review.to(done)        # PR approve
    impl_review_to_impl_revise = impl_review.to(impl_revise)  # 指摘コメント
    impl_review_to_suspended = impl_review.to(suspended)

    impl_revise_to_impl_review = impl_revise.to(impl_review)
    impl_revise_to_suspended = impl_revise.to(suspended)

    # --- BLOCKED (Feature-L 子Issue 依存待ち) ---
    blocked_to_hearing = blocked.to(hearing)
    blocked_to_analysis = blocked.to(analysis)
    blocked_to_implement = blocked.to(implement)

    # --- SUSPENDED (どのフェーズにも復帰可能) ---
    resume_to_type_detection = suspended.to(type_detection)
    resume_to_hearing = suspended.to(hearing)
    resume_to_analysis = suspended.to(analysis)
    resume_to_plan_brief = suspended.to(plan_brief)
    resume_to_design = suspended.to(design)
    resume_to_implement = suspended.to(implement)
    resume_to_fix = suspended.to(fix)
```

### 6.3 ガード関数 (Type-based Routing)

```python
    def __init__(self, issue_type: str = "") -> None:
        self._issue_type = issue_type
        super().__init__()

    @property
    def issue_type(self) -> str:
        return self._issue_type

    @issue_type.setter
    def issue_type(self, value: str) -> None:
        self._issue_type = value

    def is_bug(self) -> bool:
        """Bug タイプの場合に True を返すガード。"""
        return self._issue_type == "bug"

    def is_feature_s(self) -> bool:
        """Feature-S タイプの場合に True を返すガード。"""
        return self._issue_type == "feature-s"

    def is_feature_m(self) -> bool:
        """Feature-M タイプの場合に True を返すガード。"""
        return self._issue_type == "feature-m"

    def is_feature_l(self) -> bool:
        """Feature-L タイプの場合に True を返すガード。"""
        return self._issue_type == "feature-l"
```

### 6.4 遷移時フック (on_enter / on_exit)

```python
    def on_enter_state(self, target: State, event: str) -> None:
        """全 State 共通: 遷移ログの出力用フック。
        StateMachineManager 側から Tracker / GitHub ラベル更新を呼び出す。
        """
        pass  # StateMachineManager がリスナーとして処理
```

---

## 7. StateMachineManager クラス

ステートマシンインスタンスの管理、永続化連携、GitHub ラベル更新を統括する上位クラス。

### 7.1 クラス定義

```python
class InvalidTransitionError(Exception):
    """不正な遷移を試みた場合の例外。"""
    pass


class StateMachineManager:
    """複数 Issue の IssueWorkflow インスタンスを管理し、
    永続化・GitHub ラベル更新・イベントログ記録を統括する。
    """

    def __init__(
        self,
        persistence: StatePersistence,
        tracker: Tracker,
    ) -> None:
        self._persistence = persistence
        self._tracker = tracker
        self._states: dict[int, IssueState] = {}
        self._workflows: dict[int, IssueWorkflow] = {}
```

### 7.2 公開メソッド

```python
    def register_issue(
        self,
        issue_number: int,
        repo: str,
        initial_phase: Phase = Phase.TYPE_DETECTION,
    ) -> None:
        """新規 Issue をステートマシンに登録する。

        Args:
            issue_number: Issue 番号
            repo: "owner/repo" 形式のリポジトリキー
            initial_phase: 初期フェーズ (デフォルト: TYPE_DETECTION)

        Raises:
            ValueError: 既に登録済みの Issue 番号を指定した場合
        """
        if issue_number in self._states:
            raise ValueError(f"Issue #{issue_number} is already registered")

        now = datetime.now(timezone.utc).isoformat()
        state = IssueState(
            issue_number=issue_number,
            phase=initial_phase,
            repo=repo,
            created_at=now,
            updated_at=now,
        )
        self._states[issue_number] = state
        self._workflows[issue_number] = IssueWorkflow()
        self._auto_save()

    async def transition(
        self,
        issue_number: int,
        new_phase: Phase | str,
    ) -> None:
        """フェーズ遷移を実行する。

        内部で python-statemachine の遷移メソッドを呼び出し、
        GitHub ラベル更新・イベントログ記録・永続化を自動実行する。

        Args:
            issue_number: Issue 番号
            new_phase: 遷移先のフェーズ (Phase enum or str)

        Raises:
            KeyError: 未登録の Issue 番号
            InvalidTransitionError: 許可されていない遷移
        """
        if issue_number not in self._states:
            raise KeyError(f"Issue #{issue_number} is not registered")

        state = self._states[issue_number]
        workflow = self._workflows[issue_number]
        old_phase = state.phase
        target = Phase(new_phase) if isinstance(new_phase, str) else new_phase

        try:
            # python-statemachine の遷移を実行
            self._execute_transition(workflow, old_phase, target)
        except TransitionNotAllowed as e:
            raise InvalidTransitionError(
                f"Cannot transition Issue #{issue_number} "
                f"from {old_phase} to {target}: {e}"
            ) from e

        state.phase = target
        state.updated_at = datetime.now(timezone.utc).isoformat()
        self._auto_save()

        await self._tracker.track(
            "phase_transition",
            issue_number=issue_number,
            phase=target.value,
            data={"from": old_phase.value, "to": target.value},
        )

    def _execute_transition(
        self,
        workflow: IssueWorkflow,
        current: Phase,
        target: Phase,
    ) -> None:
        """python-statemachine の遷移メソッドを動的に呼び出す。

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
        """issue_type を考慮して正しい遷移名を解決する。

        TRANSITION_MAP のキー衝突を回避するため、
        (TYPE_DETECTION, HEARING) のように同一キーで複数の遷移名が必要な場合は
        issue_type に基づいて動的に解決する。
        """
        # TYPE_DETECTION → HEARING の分岐: issue_type で遷移名を切り替え
        if current == Phase.TYPE_DETECTION and target == Phase.HEARING:
            issue_type = wf.issue_type
            type_map = {
                "feature-s": "detect_feature_s",
                "feature-m": "detect_feature_m",
                "feature-l": "detect_feature_l",
            }
            return type_map.get(issue_type, "detect_feature_m")

        # その他は既存の TRANSITION_MAP を使用
        transition_name = TRANSITION_MAP.get((current, target))
        if transition_name is None:
            raise TransitionNotAllowed(
                f"No transition defined from {current} to {target}"
            )
        return transition_name

    def get_phase(self, issue_number: int) -> Phase:
        """Issue の現在のフェーズを取得する。

        Args:
            issue_number: Issue 番号

        Returns:
            現在の Phase

        Raises:
            KeyError: 未登録の Issue 番号
        """
        return self._states[issue_number].phase

    def get_issue_type(self, issue_number: int) -> str:
        """Issue のタイプを取得する。

        Args:
            issue_number: Issue 番号

        Returns:
            Issue タイプ文字列 ("bug" | "feature-s" | "feature-m" | "feature-l" | "")
        """
        state = self._states.get(issue_number)
        return state.issue_type if state else ""

    def set_issue_type(self, issue_number: int, issue_type: str) -> None:
        """Issue のタイプを設定する。

        IssueWorkflow のガード関数で使用される issue_type も同時に更新する。

        Args:
            issue_number: Issue 番号
            issue_type: "bug" | "feature-s" | "feature-m" | "feature-l"

        Raises:
            KeyError: 未登録の Issue 番号
            ValueError: 不正なタイプ文字列
        """
        valid_types = {"bug", "feature-s", "feature-m", "feature-l"}
        if issue_type not in valid_types:
            raise ValueError(
                f"Invalid issue type: {issue_type}. Must be one of {valid_types}"
            )
        self._states[issue_number].issue_type = issue_type
        self._workflows[issue_number].issue_type = issue_type
        self._auto_save()

    async def get_ci_retry_count(self, issue_number: int) -> int:
        """CI 修正リトライ回数を取得する。"""
        state = self._states.get(issue_number)
        return state.retry_count if state else 0

    async def increment_ci_retry(self, issue_number: int) -> None:
        """CI 修正リトライ回数をインクリメントする。"""
        if issue_number in self._states:
            self._states[issue_number].retry_count += 1
            self._auto_save()

    def get_state(self, issue_number: int) -> IssueState | None:
        """IssueState を取得する。未登録の場合は None。"""
        return self._states.get(issue_number)

    def load_from_persistence(self) -> None:
        """永続化ストレージから状態を復元する。起動時に呼び出す。

        python-statemachine の公式 API である start_value を使用して
        初期状態を指定する (_set_current_state は非公開 API のため使用しない)。
        """
        self._states = self._persistence.load()
        for issue_number, state in self._states.items():
            # python-statemachine の公式APIで初期状態を指定
            wf = IssueWorkflow(
                issue_type=state.issue_type,
                start_value=self._phase_to_state_id(state.phase),
            )
            self._workflows[issue_number] = wf

    @staticmethod
    def _phase_to_state_id(phase: Phase) -> str:
        """Phase enum を python-statemachine の State ID 文字列に変換する。

        State("type-detection") の ID は "type-detection" (State のコンストラクタ第1引数)。
        """
        return phase.value
```

### 7.3 内部メソッド

```python
    def _auto_save(self) -> None:
        """状態変更時に自動的に永続化する。"""
        self._persistence.save(self._states)

    @staticmethod
    def _phase_to_state(wf: IssueWorkflow, phase: Phase) -> State:
        """Phase enum を IssueWorkflow の State オブジェクトに変換する。"""
        mapping = {
            Phase.TYPE_DETECTION: wf.type_detection,
            Phase.ANALYSIS: wf.analysis,
            Phase.FIX: wf.fix,
            Phase.PLAN_BRIEF: wf.plan_brief,
            Phase.PLAN_REVIEW: wf.plan_review,
            Phase.HEARING: wf.hearing,
            Phase.DESIGN: wf.design,
            Phase.DESIGN_REVIEW: wf.design_review,
            Phase.DESIGN_REVISE: wf.design_revise,
            Phase.PLANNING: wf.planning,
            Phase.SPLIT_PROPOSAL: wf.split_proposal,
            Phase.SPLIT_EXECUTE: wf.split_execute,
            Phase.BLOCKED: wf.blocked,
            Phase.IMPLEMENT: wf.implement,
            Phase.CI_FIX: wf.ci_fix,
            Phase.IMPL_REVIEW: wf.impl_review,
            Phase.IMPL_REVISE: wf.impl_revise,
            Phase.DONE: wf.done,
            Phase.SUSPENDED: wf.suspended,
        }
        return mapping[phase]
```

---

## 8. TRANSITION_MAP

遷移名のルックアップテーブル。`(current_phase, target_phase) -> transition_event_name` のマッピング。

```python
TRANSITION_MAP: dict[tuple[Phase, Phase], str] = {
    # TYPE_DETECTION 分岐
    (Phase.TYPE_DETECTION, Phase.ANALYSIS): "detect_bug",
    # NOTE: (TYPE_DETECTION, HEARING) は issue_type によって遷移名が異なるため
    # TRANSITION_MAP には含めず、_resolve_transition() で動的に解決する

    # Bug ワークフロー
    (Phase.ANALYSIS, Phase.PLAN_REVIEW): "analysis_to_plan_review",
    (Phase.ANALYSIS, Phase.SUSPENDED): "analysis_to_suspended",
    (Phase.PLAN_REVIEW, Phase.FIX): "plan_review_to_fix",
    (Phase.PLAN_REVIEW, Phase.IMPLEMENT): "plan_review_to_implement",
    (Phase.PLAN_REVIEW, Phase.ANALYSIS): "plan_review_to_analysis",
    (Phase.PLAN_REVIEW, Phase.PLAN_BRIEF): "plan_review_to_plan_brief",
    (Phase.FIX, Phase.CI_FIX): "fix_to_ci_fix",
    (Phase.FIX, Phase.IMPL_REVIEW): "fix_to_impl_review",
    (Phase.FIX, Phase.SUSPENDED): "fix_to_suspended",

    # Feature-S ワークフロー
    (Phase.PLAN_BRIEF, Phase.PLAN_REVIEW): "plan_brief_to_plan_review",
    (Phase.PLAN_BRIEF, Phase.SUSPENDED): "plan_brief_to_suspended",

    # HEARING 分岐
    (Phase.HEARING, Phase.DESIGN): "hearing_to_design",
    (Phase.HEARING, Phase.PLAN_BRIEF): "hearing_to_plan_brief",
    (Phase.HEARING, Phase.SPLIT_PROPOSAL): "hearing_to_split_proposal",
    (Phase.HEARING, Phase.ANALYSIS): "hearing_to_analysis",
    (Phase.HEARING, Phase.SUSPENDED): "hearing_to_suspended",

    # Feature-M ワークフロー
    (Phase.DESIGN, Phase.DESIGN_REVIEW): "design_to_design_review",
    (Phase.DESIGN, Phase.SUSPENDED): "design_to_suspended",
    (Phase.DESIGN_REVIEW, Phase.PLANNING): "design_review_to_planning",
    (Phase.DESIGN_REVIEW, Phase.DESIGN_REVISE): "design_review_to_design_revise",
    (Phase.DESIGN_REVIEW, Phase.SUSPENDED): "design_review_to_suspended",
    (Phase.DESIGN_REVISE, Phase.DESIGN_REVIEW): "design_revise_to_design_review",
    (Phase.DESIGN_REVISE, Phase.SUSPENDED): "design_revise_to_suspended",
    (Phase.PLANNING, Phase.IMPLEMENT): "planning_to_implement",
    (Phase.PLANNING, Phase.SUSPENDED): "planning_to_suspended",

    # Feature-L ワークフロー
    (Phase.SPLIT_PROPOSAL, Phase.SPLIT_EXECUTE): "split_proposal_to_split_execute",
    (Phase.SPLIT_PROPOSAL, Phase.HEARING): "split_proposal_to_hearing",
    (Phase.SPLIT_PROPOSAL, Phase.SUSPENDED): "split_proposal_to_suspended",
    (Phase.SPLIT_EXECUTE, Phase.DONE): "split_execute_to_done",
    (Phase.SPLIT_EXECUTE, Phase.SUSPENDED): "split_execute_to_suspended",

    # 共通: 実装・レビュー
    (Phase.IMPLEMENT, Phase.CI_FIX): "implement_to_ci_fix",
    (Phase.IMPLEMENT, Phase.IMPL_REVIEW): "implement_to_impl_review",
    (Phase.IMPLEMENT, Phase.SUSPENDED): "implement_to_suspended",
    (Phase.CI_FIX, Phase.IMPL_REVIEW): "ci_fix_to_impl_review",
    (Phase.CI_FIX, Phase.CI_FIX): "ci_fix_to_ci_fix",
    (Phase.CI_FIX, Phase.SUSPENDED): "ci_fix_to_suspended",
    (Phase.IMPL_REVIEW, Phase.DONE): "impl_review_to_done",
    (Phase.IMPL_REVIEW, Phase.IMPL_REVISE): "impl_review_to_impl_revise",
    (Phase.IMPL_REVIEW, Phase.SUSPENDED): "impl_review_to_suspended",
    (Phase.IMPL_REVISE, Phase.IMPL_REVIEW): "impl_revise_to_impl_review",
    (Phase.IMPL_REVISE, Phase.SUSPENDED): "impl_revise_to_suspended",

    # BLOCKED
    (Phase.BLOCKED, Phase.HEARING): "blocked_to_hearing",
    (Phase.BLOCKED, Phase.ANALYSIS): "blocked_to_analysis",
    (Phase.BLOCKED, Phase.IMPLEMENT): "blocked_to_implement",

    # SUSPENDED → 復帰
    (Phase.SUSPENDED, Phase.TYPE_DETECTION): "resume_to_type_detection",
    (Phase.SUSPENDED, Phase.HEARING): "resume_to_hearing",
    (Phase.SUSPENDED, Phase.ANALYSIS): "resume_to_analysis",
    (Phase.SUSPENDED, Phase.PLAN_BRIEF): "resume_to_plan_brief",
    (Phase.SUSPENDED, Phase.DESIGN): "resume_to_design",
    (Phase.SUSPENDED, Phase.IMPLEMENT): "resume_to_implement",
    (Phase.SUSPENDED, Phase.FIX): "resume_to_fix",
}
```

---

## 9. テストケース

**テストファイル**: `tests/unit/orchestrator/test_state_machine.py`

### 9.1 Bug ワークフロー全遷移パス

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.orchestrator.state_machine import (
    Phase,
    IssueState,
    IssueWorkflow,
    StateMachineManager,
    InvalidTransitionError,
)


@pytest.fixture
def mock_persistence():
    p = MagicMock()
    p.load.return_value = {}
    p.save = MagicMock()
    return p


@pytest.fixture
def mock_tracker():
    return AsyncMock()


@pytest.fixture
def sm(mock_persistence, mock_tracker):
    return StateMachineManager(
        persistence=mock_persistence,
        tracker=mock_tracker,
    )


class TestBugWorkflow:
    """Bug タイプの全遷移パスをテスト。"""

    @pytest.mark.asyncio
    async def test_bug_happy_path(self, sm):
        """Bug: TYPE_DETECTION → ANALYSIS → PLAN_REVIEW → FIX → IMPL_REVIEW → DONE"""
        sm.register_issue(1, "owner/repo")
        sm.set_issue_type(1, "bug")

        await sm.transition(1, Phase.ANALYSIS)
        assert sm.get_phase(1) == Phase.ANALYSIS

        await sm.transition(1, Phase.PLAN_REVIEW)
        assert sm.get_phase(1) == Phase.PLAN_REVIEW

        await sm.transition(1, Phase.FIX)
        assert sm.get_phase(1) == Phase.FIX

        await sm.transition(1, Phase.IMPL_REVIEW)
        assert sm.get_phase(1) == Phase.IMPL_REVIEW

        await sm.transition(1, Phase.DONE)
        assert sm.get_phase(1) == Phase.DONE

    @pytest.mark.asyncio
    async def test_bug_with_ci_fix(self, sm):
        """Bug: FIX → CI_FIX → CI_FIX → IMPL_REVIEW → DONE"""
        sm.register_issue(2, "owner/repo")
        sm.set_issue_type(2, "bug")

        await sm.transition(2, Phase.ANALYSIS)
        await sm.transition(2, Phase.PLAN_REVIEW)
        await sm.transition(2, Phase.FIX)
        await sm.transition(2, Phase.CI_FIX)
        assert sm.get_phase(2) == Phase.CI_FIX

        await sm.transition(2, Phase.CI_FIX)   # 再修正
        await sm.transition(2, Phase.IMPL_REVIEW)
        await sm.transition(2, Phase.DONE)

    @pytest.mark.asyncio
    async def test_bug_plan_rejected(self, sm):
        """Bug: PLAN_REVIEW → ANALYSIS (方針指摘 → 再分析)"""
        sm.register_issue(3, "owner/repo")
        sm.set_issue_type(3, "bug")

        await sm.transition(3, Phase.ANALYSIS)
        await sm.transition(3, Phase.PLAN_REVIEW)
        await sm.transition(3, Phase.ANALYSIS)   # 指摘 → 再分析
        assert sm.get_phase(3) == Phase.ANALYSIS
```

### 9.2 Feature-S ワークフロー全遷移パス

```python
class TestFeatureSWorkflow:
    """Feature-S タイプの全遷移パスをテスト。"""

    @pytest.mark.asyncio
    async def test_feature_s_happy_path(self, sm):
        """Feature-S: TYPE_DETECTION → HEARING → PLAN_BRIEF → PLAN_REVIEW → IMPLEMENT → IMPL_REVIEW → DONE"""
        sm.register_issue(10, "owner/repo")
        sm.set_issue_type(10, "feature-s")

        await sm.transition(10, Phase.HEARING)
        await sm.transition(10, Phase.PLAN_BRIEF)
        await sm.transition(10, Phase.PLAN_REVIEW)
        await sm.transition(10, Phase.IMPLEMENT)
        await sm.transition(10, Phase.IMPL_REVIEW)
        await sm.transition(10, Phase.DONE)
        assert sm.get_phase(10) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_s_plan_rejected(self, sm):
        """Feature-S: PLAN_REVIEW → PLAN_BRIEF (方針指摘 → 再作成)"""
        sm.register_issue(11, "owner/repo")
        sm.set_issue_type(11, "feature-s")

        await sm.transition(11, Phase.HEARING)
        await sm.transition(11, Phase.PLAN_BRIEF)
        await sm.transition(11, Phase.PLAN_REVIEW)
        await sm.transition(11, Phase.PLAN_BRIEF)   # 指摘 → 再作成
        assert sm.get_phase(11) == Phase.PLAN_BRIEF

    @pytest.mark.asyncio
    async def test_feature_s_impl_revise(self, sm):
        """Feature-S: IMPL_REVIEW → IMPL_REVISE → IMPL_REVIEW → DONE"""
        sm.register_issue(12, "owner/repo")
        sm.set_issue_type(12, "feature-s")

        await sm.transition(12, Phase.HEARING)
        await sm.transition(12, Phase.PLAN_BRIEF)
        await sm.transition(12, Phase.PLAN_REVIEW)
        await sm.transition(12, Phase.IMPLEMENT)
        await sm.transition(12, Phase.IMPL_REVIEW)
        await sm.transition(12, Phase.IMPL_REVISE)
        await sm.transition(12, Phase.IMPL_REVIEW)
        await sm.transition(12, Phase.DONE)
```

### 9.3 Feature-M ワークフロー全遷移パス

```python
class TestFeatureMWorkflow:
    """Feature-M タイプの全遷移パスをテスト。"""

    @pytest.mark.asyncio
    async def test_feature_m_happy_path(self, sm):
        """Feature-M: HEARING → DESIGN → DESIGN_REVIEW → PLANNING → IMPLEMENT → IMPL_REVIEW → DONE"""
        sm.register_issue(20, "owner/repo")
        sm.set_issue_type(20, "feature-m")

        await sm.transition(20, Phase.HEARING)
        await sm.transition(20, Phase.DESIGN)
        await sm.transition(20, Phase.DESIGN_REVIEW)
        await sm.transition(20, Phase.PLANNING)
        await sm.transition(20, Phase.IMPLEMENT)
        await sm.transition(20, Phase.IMPL_REVIEW)
        await sm.transition(20, Phase.DONE)
        assert sm.get_phase(20) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_m_design_revise(self, sm):
        """Feature-M: DESIGN_REVIEW → DESIGN_REVISE → DESIGN_REVIEW → PLANNING"""
        sm.register_issue(21, "owner/repo")
        sm.set_issue_type(21, "feature-m")

        await sm.transition(21, Phase.HEARING)
        await sm.transition(21, Phase.DESIGN)
        await sm.transition(21, Phase.DESIGN_REVIEW)
        await sm.transition(21, Phase.DESIGN_REVISE)    # 設計指摘
        await sm.transition(21, Phase.DESIGN_REVIEW)    # 再レビュー
        await sm.transition(21, Phase.PLANNING)
        assert sm.get_phase(21) == Phase.PLANNING
```

### 9.4 Feature-L ワークフロー全遷移パス

```python
class TestFeatureLWorkflow:
    """Feature-L タイプの全遷移パスをテスト。"""

    @pytest.mark.asyncio
    async def test_feature_l_happy_path(self, sm):
        """Feature-L: HEARING → SPLIT_PROPOSAL → SPLIT_EXECUTE → DONE"""
        sm.register_issue(30, "owner/repo")
        sm.set_issue_type(30, "feature-l")

        await sm.transition(30, Phase.HEARING)
        await sm.transition(30, Phase.SPLIT_PROPOSAL)
        await sm.transition(30, Phase.SPLIT_EXECUTE)
        await sm.transition(30, Phase.DONE)
        assert sm.get_phase(30) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_l_split_modified(self, sm):
        """Feature-L: SPLIT_PROPOSAL → HEARING (修正指示 → ヒアリング再実行)"""
        sm.register_issue(31, "owner/repo")
        sm.set_issue_type(31, "feature-l")

        await sm.transition(31, Phase.HEARING)
        await sm.transition(31, Phase.SPLIT_PROPOSAL)
        await sm.transition(31, Phase.HEARING)   # 修正指示
        assert sm.get_phase(31) == Phase.HEARING
```

### 9.5 不正遷移テスト

```python
class TestInvalidTransitions:
    """許可されていない遷移が拒否されることをテスト。"""

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, sm):
        """ANALYSIS → IMPLEMENT は不正遷移として拒否される。"""
        sm.register_issue(40, "owner/repo")
        sm.set_issue_type(40, "bug")
        await sm.transition(40, Phase.ANALYSIS)

        with pytest.raises(InvalidTransitionError):
            await sm.transition(40, Phase.IMPLEMENT)

    @pytest.mark.asyncio
    async def test_unregistered_issue_raises(self, sm):
        """未登録 Issue の遷移は KeyError。"""
        with pytest.raises(KeyError):
            await sm.transition(999, Phase.HEARING)
```

### 9.6 永続化連携テスト

```python
class TestPersistence:
    """StatePersistence との連携をテスト。"""

    @pytest.mark.asyncio
    async def test_auto_save_on_transition(self, sm, mock_persistence):
        """遷移ごとに persistence.save() が呼ばれる。"""
        sm.register_issue(50, "owner/repo")
        sm.set_issue_type(50, "bug")
        initial_call_count = mock_persistence.save.call_count

        await sm.transition(50, Phase.ANALYSIS)
        assert mock_persistence.save.call_count > initial_call_count

    def test_load_from_persistence(self, mock_persistence, mock_tracker):
        """起動時に永続化データから状態を復元できる。"""
        mock_persistence.load.return_value = {
            1: IssueState(
                issue_number=1,
                phase=Phase.DESIGN,
                issue_type="feature-m",
                repo="owner/repo",
            )
        }
        sm = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        sm.load_from_persistence()
        assert sm.get_phase(1) == Phase.DESIGN
        assert sm.get_issue_type(1) == "feature-m"
```

### 9.7 SUSPENDED 復帰テスト

```python
class TestSuspendedResume:
    """SUSPENDED 状態からの復帰をテスト。"""

    @pytest.mark.asyncio
    async def test_resume_from_suspended(self, sm):
        """SUSPENDED → HEARING に復帰できる。"""
        sm.register_issue(60, "owner/repo")
        sm.set_issue_type(60, "feature-m")
        await sm.transition(60, Phase.HEARING)
        await sm.transition(60, Phase.SUSPENDED)
        assert sm.get_phase(60) == Phase.SUSPENDED

        await sm.transition(60, Phase.HEARING)
        assert sm.get_phase(60) == Phase.HEARING
```

### 9.8 CI リトライカウンターテスト

```python
class TestCiRetry:
    """CI リトライ回数の管理をテスト。"""

    @pytest.mark.asyncio
    async def test_ci_retry_counter(self, sm):
        """リトライカウンタが正しくインクリメントされる。"""
        sm.register_issue(70, "owner/repo")
        assert await sm.get_ci_retry_count(70) == 0

        await sm.increment_ci_retry(70)
        assert await sm.get_ci_retry_count(70) == 1

        await sm.increment_ci_retry(70)
        assert await sm.get_ci_retry_count(70) == 2
```
