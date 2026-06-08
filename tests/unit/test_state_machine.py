"""StateMachine のユニットテスト."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import IssueKey, IssueState, Phase
from ai_agent_orchestrator.orchestrator.state_machine import (
    InvalidTransitionError,
    IssueWorkflow,
    StateMachineManager,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_persistence() -> MagicMock:
    """Mock StatePersistence."""
    p = MagicMock()
    p.load.return_value = {}
    p.save = MagicMock()
    return p


@pytest.fixture
def mock_tracker() -> AsyncMock:
    """Mock Tracker."""
    return AsyncMock()


@pytest.fixture
def sm(mock_persistence: MagicMock, mock_tracker: AsyncMock) -> StateMachineManager:
    """StateMachineManager instance with mocked dependencies."""
    return StateMachineManager(
        persistence=mock_persistence,
        tracker=mock_tracker,
    )


def _key(issue_number: int, repo: str = "owner/repo") -> IssueKey:
    """テスト用 IssueKey ヘルパー."""
    return (repo, issue_number)


# ---------------------------------------------------------------------------
# IssueWorkflow direct tests
# ---------------------------------------------------------------------------


class TestIssueWorkflow:
    """IssueWorkflow の基本動作テスト."""

    def test_initial_state(self) -> None:
        """初期状態が type_detection であること."""
        wf = IssueWorkflow()
        assert wf.current_state_value == "type_detection"

    def test_bug_detection(self) -> None:
        """Bug タイプで detect_bug 遷移ができること."""
        wf = IssueWorkflow(issue_type="bug")
        wf.send("detect_bug")
        assert wf.current_state_value == "analysis"

    def test_feature_m_detection(self) -> None:
        """Feature-M タイプで detect_feature_m 遷移ができること."""
        wf = IssueWorkflow(issue_type="feature-m")
        wf.send("detect_feature_m")
        assert wf.current_state_value == "hearing"

    def test_feature_l_detection(self) -> None:
        """Feature-L タイプで detect_feature_l 遷移ができること."""
        wf = IssueWorkflow(issue_type="feature-l")
        wf.send("detect_feature_l")
        assert wf.current_state_value == "hearing"

    def test_start_value_restoration(self) -> None:
        """start_value でステートを復元できること."""
        wf = IssueWorkflow(issue_type="feature-m", start_value="design")
        assert wf.current_state_value == "design"

    def test_guard_prevents_wrong_type(self) -> None:
        """ガードが不一致のタイプを拒否すること."""
        from statemachine.exceptions import TransitionNotAllowed

        wf = IssueWorkflow(issue_type="feature-m")
        with pytest.raises(TransitionNotAllowed):
            wf.send("detect_bug")  # is_bug() returns False

    def test_issue_type_property(self) -> None:
        """issue_type プロパティの get/set."""
        wf = IssueWorkflow(issue_type="bug")
        assert wf.issue_type == "bug"
        wf.issue_type = "feature-m"
        assert wf.issue_type == "feature-m"


# ---------------------------------------------------------------------------
# Bug workflow
# ---------------------------------------------------------------------------


class TestBugWorkflow:
    """Bug タイプの全遷移パスをテスト."""

    @pytest.mark.asyncio
    async def test_bug_happy_path(self, sm: StateMachineManager) -> None:
        """Bug: TYPE_DETECTION -> ANALYSIS -> PLAN_REVIEW -> FIX -> IMPL_REVIEW -> DONE."""
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.ANALYSIS)
        assert sm.get_phase(key) == Phase.ANALYSIS

        await sm.transition(key, Phase.PLAN_REVIEW)
        assert sm.get_phase(key) == Phase.PLAN_REVIEW

        await sm.transition(key, Phase.FIX)
        assert sm.get_phase(key) == Phase.FIX

        await sm.transition(key, Phase.IMPL_REVIEW)
        assert sm.get_phase(key) == Phase.IMPL_REVIEW

        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_bug_with_ci_fix(self, sm: StateMachineManager) -> None:
        """Bug: FIX -> CI_FIX -> CI_FIX -> IMPL_REVIEW -> DONE."""
        sm.register_issue(2, "owner/repo")
        key = _key(2)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.ANALYSIS)
        await sm.transition(key, Phase.PLAN_REVIEW)
        await sm.transition(key, Phase.FIX)
        await sm.transition(key, Phase.CI_FIX)
        assert sm.get_phase(key) == Phase.CI_FIX

        await sm.transition(key, Phase.CI_FIX)  # self-transition
        await sm.transition(key, Phase.IMPL_REVIEW)
        await sm.transition(key, Phase.DONE)

    @pytest.mark.asyncio
    async def test_bug_plan_rejected(self, sm: StateMachineManager) -> None:
        """Bug: PLAN_REVIEW -> ANALYSIS (方針指摘 -> 再分析)."""
        sm.register_issue(3, "owner/repo")
        key = _key(3)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.ANALYSIS)
        await sm.transition(key, Phase.PLAN_REVIEW)
        await sm.transition(key, Phase.ANALYSIS)  # rejected
        assert sm.get_phase(key) == Phase.ANALYSIS

    @pytest.mark.asyncio
    async def test_bug_with_impl_revise(self, sm: StateMachineManager) -> None:
        """Bug: IMPL_REVIEW -> IMPL_REVISE -> IMPL_REVIEW -> DONE."""
        sm.register_issue(4, "owner/repo")
        key = _key(4)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.ANALYSIS)
        await sm.transition(key, Phase.PLAN_REVIEW)
        await sm.transition(key, Phase.FIX)
        await sm.transition(key, Phase.IMPL_REVIEW)
        await sm.transition(key, Phase.IMPL_REVISE)
        await sm.transition(key, Phase.IMPL_REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE


# ---------------------------------------------------------------------------
# Feature-M workflow
# ---------------------------------------------------------------------------


class TestFeatureMWorkflow:
    """Feature-M タイプの全遷移パスをテスト."""

    @pytest.mark.asyncio
    async def test_feature_m_happy_path(self, sm: StateMachineManager) -> None:
        """Feature-M: HEARING -> DESIGN -> DESIGN_REVIEW -> IMPLEMENT -> IMPL_REVIEW -> DONE."""
        sm.register_issue(20, "owner/repo")
        key = _key(20)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.DESIGN)
        await sm.transition(key, Phase.DESIGN_REVIEW)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.IMPL_REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_m_design_review_to_implement(self, sm: StateMachineManager) -> None:
        """Feature-M: DESIGN_REVIEW -> IMPLEMENT が成功すること（設計PR承認後の直接遷移）."""
        sm.register_issue(23, "owner/repo")
        key = _key(23)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.DESIGN)
        await sm.transition(key, Phase.DESIGN_REVIEW)
        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_feature_m_design_revise(self, sm: StateMachineManager) -> None:
        """Feature-M: DESIGN_REVIEW -> DESIGN_REVISE -> DESIGN_REVIEW -> IMPLEMENT."""
        sm.register_issue(21, "owner/repo")
        key = _key(21)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.DESIGN)
        await sm.transition(key, Phase.DESIGN_REVIEW)
        await sm.transition(key, Phase.DESIGN_REVISE)
        await sm.transition(key, Phase.DESIGN_REVIEW)
        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_feature_m_with_ci_fix(self, sm: StateMachineManager) -> None:
        """Feature-M: IMPLEMENT -> CI_FIX -> IMPL_REVIEW -> DONE."""
        sm.register_issue(22, "owner/repo")
        key = _key(22)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.DESIGN)
        await sm.transition(key, Phase.DESIGN_REVIEW)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.CI_FIX)
        await sm.transition(key, Phase.IMPL_REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE


# ---------------------------------------------------------------------------
# Feature-L workflow
# ---------------------------------------------------------------------------


class TestFeatureLWorkflow:
    """Feature-L タイプの全遷移パスをテスト."""

    @pytest.mark.asyncio
    async def test_feature_l_happy_path(self, sm: StateMachineManager) -> None:
        """Feature-L: HEARING -> SPLIT_PROPOSAL -> SPLIT_EXECUTE -> DONE."""
        sm.register_issue(30, "owner/repo")
        key = _key(30)
        sm.set_issue_type(key, "feature-l")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.SPLIT_PROPOSAL)
        await sm.transition(key, Phase.SPLIT_EXECUTE)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_l_split_modified(self, sm: StateMachineManager) -> None:
        """Feature-L: SPLIT_PROPOSAL -> HEARING (修正指示 -> ヒアリング再実行)."""
        sm.register_issue(31, "owner/repo")
        key = _key(31)
        sm.set_issue_type(key, "feature-l")

        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.SPLIT_PROPOSAL)
        await sm.transition(key, Phase.HEARING)  # modified
        assert sm.get_phase(key) == Phase.HEARING


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """許可されていない遷移が拒否されることをテスト."""

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, sm: StateMachineManager) -> None:
        """ANALYSIS -> IMPLEMENT は不正遷移として拒否される."""
        sm.register_issue(40, "owner/repo")
        key = _key(40)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, Phase.ANALYSIS)

        with pytest.raises(InvalidTransitionError):
            await sm.transition(key, Phase.IMPLEMENT)

    @pytest.mark.asyncio
    async def test_unregistered_issue_raises(self, sm: StateMachineManager) -> None:
        """未登録 Issue の遷移は KeyError."""
        with pytest.raises(KeyError):
            await sm.transition(("owner/repo", 999), Phase.HEARING)

    def test_duplicate_registration_raises(self, sm: StateMachineManager) -> None:
        """既に登録済みの Issue は ValueError."""
        sm.register_issue(41, "owner/repo")
        with pytest.raises(ValueError, match="already registered"):
            sm.register_issue(41, "owner/repo")

    def test_invalid_issue_type_raises(self, sm: StateMachineManager) -> None:
        """不正な issue_type は ValueError."""
        sm.register_issue(42, "owner/repo")
        with pytest.raises(ValueError, match="Invalid issue type"):
            sm.set_issue_type(_key(42), "invalid-type")

    @pytest.mark.asyncio
    async def test_type_detection_to_hearing_without_type_raises(self, sm: StateMachineManager) -> None:
        """issue_type 未設定で TYPE_DETECTION -> HEARING は失敗."""
        sm.register_issue(43, "owner/repo")
        # issue_type not set (empty string)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(_key(43), Phase.HEARING)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """StatePersistence との連携をテスト."""

    @pytest.mark.asyncio
    async def test_auto_save_on_transition(self, sm: StateMachineManager, mock_persistence: MagicMock) -> None:
        """遷移ごとに persistence.save() が呼ばれる."""
        sm.register_issue(50, "owner/repo")
        key = _key(50)
        sm.set_issue_type(key, "bug")
        initial_call_count = mock_persistence.save.call_count

        await sm.transition(key, Phase.ANALYSIS)
        assert mock_persistence.save.call_count > initial_call_count

    def test_auto_save_on_register(self, sm: StateMachineManager, mock_persistence: MagicMock) -> None:
        """register_issue() で persistence.save() が呼ばれる."""
        initial = mock_persistence.save.call_count
        sm.register_issue(51, "owner/repo")
        assert mock_persistence.save.call_count > initial

    def test_load_from_persistence(self, mock_persistence: MagicMock, mock_tracker: AsyncMock) -> None:
        """起動時に永続化データから状態を復元できる."""
        mock_persistence.load.return_value = {
            ("owner/repo", 1): IssueState(
                issue_number=1,
                phase=Phase.DESIGN,
                issue_type="feature-m",
                repo="owner/repo",
            )
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()
        assert manager.get_phase(_key(1)) == Phase.DESIGN
        assert manager.get_issue_type(_key(1)) == "feature-m"

    @pytest.mark.asyncio
    async def test_load_and_continue_workflow(self, mock_persistence: MagicMock, mock_tracker: AsyncMock) -> None:
        """復元後に遷移を継続できる."""
        mock_persistence.load.return_value = {
            ("owner/repo", 1): IssueState(
                issue_number=1,
                phase=Phase.DESIGN,
                issue_type="feature-m",
                repo="owner/repo",
            )
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()

        # DESIGN -> DESIGN_REVIEW should work
        await manager.transition(_key(1), Phase.DESIGN_REVIEW)
        assert manager.get_phase(_key(1)) == Phase.DESIGN_REVIEW

    def test_load_multiple_issues(self, mock_persistence: MagicMock, mock_tracker: AsyncMock) -> None:
        """複数 Issue を復元できる."""
        mock_persistence.load.return_value = {
            ("owner/repo", 1): IssueState(
                issue_number=1,
                phase=Phase.ANALYSIS,
                issue_type="bug",
                repo="owner/repo",
            ),
            ("owner/repo2", 2): IssueState(
                issue_number=2,
                phase=Phase.HEARING,
                issue_type="feature-m",
                repo="owner/repo2",
            ),
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()
        assert manager.get_phase(("owner/repo", 1)) == Phase.ANALYSIS
        assert manager.get_phase(("owner/repo2", 2)) == Phase.HEARING
        assert manager.get_issue_type(("owner/repo", 1)) == "bug"
        assert manager.get_issue_type(("owner/repo2", 2)) == "feature-m"


# ---------------------------------------------------------------------------
# Suspended / resume
# ---------------------------------------------------------------------------


class TestSuspendedResume:
    """SUSPENDED 状態からの復帰をテスト."""

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_hearing(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> HEARING に復帰できる."""
        sm.register_issue(60, "owner/repo")
        key = _key(60)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.SUSPENDED)
        assert sm.get_phase(key) == Phase.SUSPENDED

        await sm.transition(key, Phase.HEARING)
        assert sm.get_phase(key) == Phase.HEARING

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_analysis(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> ANALYSIS に復帰できる."""
        sm.register_issue(61, "owner/repo")
        key = _key(61)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, Phase.ANALYSIS)
        await sm.transition(key, Phase.SUSPENDED)

        await sm.transition(key, Phase.ANALYSIS)
        assert sm.get_phase(key) == Phase.ANALYSIS

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_implement(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> IMPLEMENT に復帰できる."""
        sm.register_issue(62, "owner/repo")
        key = _key(62)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.SUSPENDED)

        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_suspend_from_design(self, sm: StateMachineManager) -> None:
        """DESIGN -> SUSPENDED."""
        sm.register_issue(63, "owner/repo")
        key = _key(63)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.DESIGN)
        await sm.transition(key, Phase.SUSPENDED)
        assert sm.get_phase(key) == Phase.SUSPENDED


# ---------------------------------------------------------------------------
# CI retry counter
# ---------------------------------------------------------------------------


class TestCiRetry:
    """CI リトライ回数の管理をテスト."""

    @pytest.mark.asyncio
    async def test_ci_retry_counter(self, sm: StateMachineManager) -> None:
        """リトライカウンタが正しくインクリメントされる."""
        sm.register_issue(70, "owner/repo")
        key = _key(70)
        assert await sm.get_ci_retry_count(key) == 0

        await sm.increment_ci_retry(key)
        assert await sm.get_ci_retry_count(key) == 1

        await sm.increment_ci_retry(key)
        assert await sm.get_ci_retry_count(key) == 2

    @pytest.mark.asyncio
    async def test_ci_retry_unregistered_issue(self, sm: StateMachineManager) -> None:
        """未登録 Issue のリトライカウントは 0."""
        assert await sm.get_ci_retry_count(("owner/repo", 999)) == 0


# ---------------------------------------------------------------------------
# State accessors
# ---------------------------------------------------------------------------


class TestStateAccessors:
    """get_state / get_phase / get_issue_type のテスト."""

    def test_get_state_returns_issue_state(self, sm: StateMachineManager) -> None:
        """get_state() が IssueState を返す."""
        sm.register_issue(80, "owner/repo")
        key = _key(80)
        state = sm.get_state(key)
        assert state is not None
        assert state.issue_number == 80
        assert state.repo == "owner/repo"

    def test_get_state_unregistered_returns_none(self, sm: StateMachineManager) -> None:
        """未登録 Issue の get_state() は None."""
        assert sm.get_state(("owner/repo", 999)) is None

    def test_get_issue_type_unregistered(self, sm: StateMachineManager) -> None:
        """未登録 Issue の get_issue_type() は空文字列."""
        assert sm.get_issue_type(("owner/repo", 999)) == ""

    def test_transition_with_string_phase(self, sm: StateMachineManager) -> None:
        """文字列で Phase を指定して遷移できる."""
        sm.register_issue(81, "owner/repo")
        key = _key(81)
        sm.set_issue_type(key, "bug")
        # Use string instead of Phase enum - not async here, need to test in async
        assert sm.get_phase(key) == Phase.TYPE_DETECTION

    @pytest.mark.asyncio
    async def test_transition_with_string(self, sm: StateMachineManager) -> None:
        """文字列で Phase を指定して遷移できる."""
        sm.register_issue(82, "owner/repo")
        key = _key(82)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, "analysis")
        assert sm.get_phase(key) == Phase.ANALYSIS


# ---------------------------------------------------------------------------
# Tracker integration
# ---------------------------------------------------------------------------


class TestTrackerIntegration:
    """Tracker の呼び出しをテスト."""

    @pytest.mark.asyncio
    async def test_tracker_called_on_transition(self, sm: StateMachineManager, mock_tracker: AsyncMock) -> None:
        """遷移時に tracker.track() が呼ばれる."""
        sm.register_issue(90, "owner/repo")
        key = _key(90)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.ANALYSIS)

        mock_tracker.track.assert_called_once_with(
            "phase_transition",
            issue_number=90,
            phase="analysis",
            data={"from": "type-detection", "to": "analysis"},
        )


# ---------------------------------------------------------------------------
# HEARING_WAIT workflow
# ---------------------------------------------------------------------------


class TestHearingWaitWorkflow:
    """hearing-wait フェーズの遷移テスト."""

    @pytest.fixture
    def sm(self, mock_persistence, mock_tracker):
        return StateMachineManager(persistence=mock_persistence, tracker=mock_tracker)

    async def test_hearing_to_hearing_wait(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.HEARING_WAIT)
        assert sm.get_phase(key) == Phase.HEARING_WAIT

    async def test_hearing_wait_to_hearing(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.HEARING_WAIT)
        await sm.transition(key, Phase.HEARING)
        assert sm.get_phase(key) == Phase.HEARING

    async def test_hearing_wait_to_suspended(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.HEARING)
        await sm.transition(key, Phase.HEARING_WAIT)
        await sm.transition(key, Phase.SUSPENDED)
        assert sm.get_phase(key) == Phase.SUSPENDED
