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
# get_workflow_params: issue_type からのパラメータ導出 (U5c #95)
# ---------------------------------------------------------------------------


class TestGetWorkflowParams:
    """set_issue_type 後に get_workflow_params が正しいパラメータを返す."""

    @pytest.mark.parametrize(
        ("issue_type", "plan_depth", "needs_split", "approval_style"),
        [
            ("bug", "light", False, "reaction"),
            ("feature-m", "full", False, "pr"),
            ("feature-l", "full", True, "pr"),
        ],
    )
    def test_params_follow_issue_type(
        self,
        sm: StateMachineManager,
        issue_type: str,
        plan_depth: str,
        needs_split: bool,
        approval_style: str,
    ) -> None:
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, issue_type)

        params = sm.get_workflow_params(key)
        assert params.plan_depth == plan_depth
        assert params.needs_split == needs_split
        assert params.approval_style == approval_style

    def test_unregistered_issue_falls_back_to_full(self, sm: StateMachineManager) -> None:
        """未登録 Issue は安全側 (full / 分割なし / PR) を返す."""
        params = sm.get_workflow_params(_key(999))
        assert params.plan_depth == "full"
        assert params.needs_split is False
        assert params.approval_style == "pr"


# ---------------------------------------------------------------------------
# IssueWorkflow direct tests
# ---------------------------------------------------------------------------


class TestIssueWorkflow:
    """IssueWorkflow の基本動作テスト."""

    def test_initial_state(self) -> None:
        """初期状態が intake であること."""
        wf = IssueWorkflow()
        assert wf.current_state.id == "intake"

    def test_bug_detection(self) -> None:
        """intake -> plan 遷移ができること（bug はヒアリング不要で直接 plan へ）."""
        wf = IssueWorkflow(issue_type="bug")
        wf.send("intake_to_plan")
        assert wf.current_state.id == "plan"

    def test_feature_m_detection(self) -> None:
        """intake -> clarify 遷移ができること（feature-m はヒアリング必要）."""
        wf = IssueWorkflow(issue_type="feature-m")
        wf.send("intake_to_clarify")
        assert wf.current_state.id == "clarify"

    def test_feature_l_detection(self) -> None:
        """intake -> clarify 遷移ができること（feature-l はヒアリング必要）."""
        wf = IssueWorkflow(issue_type="feature-l")
        wf.send("intake_to_clarify")
        assert wf.current_state.id == "clarify"

    def test_start_value_restoration(self) -> None:
        """start_value でステートを復元できること."""
        wf = IssueWorkflow(issue_type="feature-m", start_value="plan")
        assert wf.current_state.id == "plan"

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
        """Bug: INTAKE -> PLAN -> APPROVE -> IMPLEMENT -> REVIEW -> DONE."""
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.PLAN)
        assert sm.get_phase(key) == Phase.PLAN

        await sm.transition(key, Phase.APPROVE)
        assert sm.get_phase(key) == Phase.APPROVE

        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

        await sm.transition(key, Phase.REVIEW)
        assert sm.get_phase(key) == Phase.REVIEW

        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_bug_with_ci_fix(self, sm: StateMachineManager) -> None:
        """Bug: IMPLEMENT -> REVISE -> REVISE -> REVIEW -> DONE (CI 失敗 -> REVISE)."""
        sm.register_issue(2, "owner/repo")
        key = _key(2)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.REVISE)
        assert sm.get_phase(key) == Phase.REVISE

        await sm.transition(key, Phase.REVISE)  # self-transition
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.DONE)

    @pytest.mark.asyncio
    async def test_bug_plan_rejected(self, sm: StateMachineManager) -> None:
        """Bug: APPROVE -> PLAN (方針指摘 -> 再計画)."""
        sm.register_issue(3, "owner/repo")
        key = _key(3)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.PLAN)  # rejected -> back to plan
        assert sm.get_phase(key) == Phase.PLAN

    @pytest.mark.asyncio
    async def test_bug_with_impl_revise(self, sm: StateMachineManager) -> None:
        """Bug: REVIEW -> REVISE -> REVIEW -> DONE (レビュー指摘)."""
        sm.register_issue(4, "owner/repo")
        key = _key(4)
        sm.set_issue_type(key, "bug")

        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.REVISE)
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE


# ---------------------------------------------------------------------------
# Feature-M workflow
# ---------------------------------------------------------------------------


class TestFeatureMWorkflow:
    """Feature-M タイプの全遷移パスをテスト."""

    @pytest.mark.asyncio
    async def test_feature_m_happy_path(self, sm: StateMachineManager) -> None:
        """Feature-M: CLARIFY -> PLAN -> APPROVE -> IMPLEMENT -> REVIEW -> DONE."""
        sm.register_issue(20, "owner/repo")
        key = _key(20)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_m_design_review_to_implement(self, sm: StateMachineManager) -> None:
        """Feature-M: APPROVE -> IMPLEMENT が成功すること（計画承認後の遷移）."""
        sm.register_issue(23, "owner/repo")
        key = _key(23)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_feature_m_design_review_to_design_on_rejection(self, sm: StateMachineManager) -> None:
        """Feature-M: APPROVE -> PLAN (差し戻しは PLAN へ戻す)."""
        sm.register_issue(24, "owner/repo")
        key = _key(24)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.PLAN)
        assert sm.get_phase(key) == Phase.PLAN
        # 再計画後に再び APPROVE へ進めること
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_feature_m_design_revise(self, sm: StateMachineManager) -> None:
        """Feature-M: REVIEW -> REVISE -> REVIEW -> DONE (レビュー指摘対応)."""
        sm.register_issue(21, "owner/repo")
        key = _key(21)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.REVISE)
        await sm.transition(key, Phase.REVIEW)
        assert sm.get_phase(key) == Phase.REVIEW

    @pytest.mark.asyncio
    async def test_feature_m_with_ci_fix(self, sm: StateMachineManager) -> None:
        """Feature-M: IMPLEMENT -> REVISE -> REVIEW -> DONE (CI 失敗 -> REVISE)."""
        sm.register_issue(22, "owner/repo")
        key = _key(22)
        sm.set_issue_type(key, "feature-m")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.APPROVE)
        await sm.transition(key, Phase.IMPLEMENT)
        await sm.transition(key, Phase.REVISE)
        await sm.transition(key, Phase.REVIEW)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE


# ---------------------------------------------------------------------------
# Feature-L workflow
# ---------------------------------------------------------------------------


class TestFeatureLWorkflow:
    """Feature-L タイプの全遷移パスをテスト."""

    @pytest.mark.asyncio
    async def test_feature_l_happy_path(self, sm: StateMachineManager) -> None:
        """Feature-L: CLARIFY -> SPLIT -> DONE."""
        sm.register_issue(30, "owner/repo")
        key = _key(30)
        sm.set_issue_type(key, "feature-l")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.SPLIT)
        await sm.transition(key, Phase.DONE)
        assert sm.get_phase(key) == Phase.DONE

    @pytest.mark.asyncio
    async def test_feature_l_split_modified(self, sm: StateMachineManager) -> None:
        """Feature-L: SPLIT -> CLARIFY (修正指示 -> ヒアリング再実行)."""
        sm.register_issue(31, "owner/repo")
        key = _key(31)
        sm.set_issue_type(key, "feature-l")

        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.SPLIT)
        await sm.transition(key, Phase.CLARIFY)  # modified
        assert sm.get_phase(key) == Phase.CLARIFY


# ---------------------------------------------------------------------------
# Invalid transitions
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """許可されていない遷移が拒否されることをテスト."""

    @pytest.mark.asyncio
    async def test_invalid_transition_raises(self, sm: StateMachineManager) -> None:
        """PLAN -> IMPLEMENT は不正遷移として拒否される（APPROVE ゲートを通過していない）."""
        sm.register_issue(40, "owner/repo")
        key = _key(40)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, Phase.PLAN)

        with pytest.raises(InvalidTransitionError):
            await sm.transition(key, Phase.IMPLEMENT)

    @pytest.mark.asyncio
    async def test_unregistered_issue_raises(self, sm: StateMachineManager) -> None:
        """未登録 Issue の遷移は KeyError."""
        with pytest.raises(KeyError):
            await sm.transition(("owner/repo", 999), Phase.CLARIFY)

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
        """INTAKE -> DONE は不正遷移として拒否される（中間フェーズをスキップ）."""
        sm.register_issue(43, "owner/repo")
        # issue_type not set (empty string)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(_key(43), Phase.DONE)


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

        await sm.transition(key, Phase.PLAN)
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
                phase=Phase.PLAN,
                issue_type="feature-m",
                repo="owner/repo",
            )
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()
        assert manager.get_phase(_key(1)) == Phase.PLAN
        assert manager.get_issue_type(_key(1)) == "feature-m"

    @pytest.mark.asyncio
    async def test_load_and_continue_workflow(self, mock_persistence: MagicMock, mock_tracker: AsyncMock) -> None:
        """復元後に遷移を継続できる."""
        mock_persistence.load.return_value = {
            ("owner/repo", 1): IssueState(
                issue_number=1,
                phase=Phase.PLAN,
                issue_type="feature-m",
                repo="owner/repo",
            )
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()

        # PLAN -> APPROVE should work
        await manager.transition(_key(1), Phase.APPROVE)
        assert manager.get_phase(_key(1)) == Phase.APPROVE

    def test_load_multiple_issues(self, mock_persistence: MagicMock, mock_tracker: AsyncMock) -> None:
        """複数 Issue を復元できる."""
        mock_persistence.load.return_value = {
            ("owner/repo", 1): IssueState(
                issue_number=1,
                phase=Phase.PLAN,
                issue_type="bug",
                repo="owner/repo",
            ),
            ("owner/repo2", 2): IssueState(
                issue_number=2,
                phase=Phase.CLARIFY,
                issue_type="feature-m",
                repo="owner/repo2",
            ),
        }
        manager = StateMachineManager(
            persistence=mock_persistence,
            tracker=mock_tracker,
        )
        manager.load_from_persistence()
        assert manager.get_phase(("owner/repo", 1)) == Phase.PLAN
        assert manager.get_phase(("owner/repo2", 2)) == Phase.CLARIFY
        assert manager.get_issue_type(("owner/repo", 1)) == "bug"
        assert manager.get_issue_type(("owner/repo2", 2)) == "feature-m"


# ---------------------------------------------------------------------------
# Suspended / resume
# ---------------------------------------------------------------------------


class TestSuspendedResume:
    """SUSPENDED 状態からの復帰をテスト."""

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_hearing(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> CLARIFY に復帰できる."""
        sm.register_issue(60, "owner/repo")
        key = _key(60)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.SUSPENDED)
        assert sm.get_phase(key) == Phase.SUSPENDED

        await sm.transition(key, Phase.CLARIFY)
        assert sm.get_phase(key) == Phase.CLARIFY

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_analysis(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> PLAN に復帰できる."""
        sm.register_issue(61, "owner/repo")
        key = _key(61)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, Phase.PLAN)
        await sm.transition(key, Phase.SUSPENDED)

        await sm.transition(key, Phase.PLAN)
        assert sm.get_phase(key) == Phase.PLAN

    @pytest.mark.asyncio
    async def test_resume_from_suspended_to_implement(self, sm: StateMachineManager) -> None:
        """SUSPENDED -> IMPLEMENT に復帰できる."""
        sm.register_issue(62, "owner/repo")
        key = _key(62)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.SUSPENDED)

        await sm.transition(key, Phase.IMPLEMENT)
        assert sm.get_phase(key) == Phase.IMPLEMENT

    @pytest.mark.asyncio
    async def test_suspend_from_design(self, sm: StateMachineManager) -> None:
        """PLAN -> SUSPENDED."""
        sm.register_issue(63, "owner/repo")
        key = _key(63)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.PLAN)
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
        """register 後の初期フェーズは Phase.INTAKE であること."""
        sm.register_issue(81, "owner/repo")
        key = _key(81)
        sm.set_issue_type(key, "bug")
        assert sm.get_phase(key) == Phase.INTAKE

    @pytest.mark.asyncio
    async def test_transition_with_string(self, sm: StateMachineManager) -> None:
        """文字列で Phase を指定して遷移できる."""
        sm.register_issue(82, "owner/repo")
        key = _key(82)
        sm.set_issue_type(key, "bug")
        await sm.transition(key, "plan")
        assert sm.get_phase(key) == Phase.PLAN


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

        await sm.transition(key, Phase.PLAN)

        mock_tracker.track.assert_called_once_with(
            "phase_transition",
            issue_number=90,
            phase="plan",
            data={"from": "intake", "to": "plan"},
        )


# ---------------------------------------------------------------------------
# HEARING_WAIT workflow (CLARIFY_WAIT)
# ---------------------------------------------------------------------------


class TestHearingWaitWorkflow:
    """clarify-wait フェーズの遷移テスト."""

    @pytest.fixture
    def sm(self, mock_persistence, mock_tracker):
        return StateMachineManager(persistence=mock_persistence, tracker=mock_tracker)

    async def test_hearing_to_hearing_wait(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.CLARIFY_WAIT)
        assert sm.get_phase(key) == Phase.CLARIFY_WAIT

    async def test_hearing_wait_to_hearing(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.CLARIFY_WAIT)
        await sm.transition(key, Phase.CLARIFY)
        assert sm.get_phase(key) == Phase.CLARIFY

    async def test_hearing_wait_to_suspended(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        sm.set_issue_type(key, "feature-m")
        await sm.transition(key, Phase.CLARIFY)
        await sm.transition(key, Phase.CLARIFY_WAIT)
        await sm.transition(key, Phase.SUSPENDED)
        assert sm.get_phase(key) == Phase.SUSPENDED


# ---------------------------------------------------------------------------
# Issue メタ (title/body) の保存・補完 (#142)
# ---------------------------------------------------------------------------


class TestIssueMeta:
    """register_issue の title/body 保存と backfill_issue_meta の補完."""

    def test_register_stores_title_and_body(self, sm):
        sm.register_issue(1, "owner/repo", title="ログインバグ", body="再現手順あり")
        state = sm.get_state(_key(1))
        assert state is not None
        assert state.title == "ログインバグ"
        assert state.body == "再現手順あり"

    def test_register_truncates_long_title_and_body(self, sm):
        sm.register_issue(1, "owner/repo", title="あ" * 500, body="い" * 5000)
        state = sm.get_state(_key(1))
        assert state is not None
        assert len(state.title) == 256
        assert len(state.body) == 2000

    def test_register_none_meta_becomes_empty(self, sm):
        sm.register_issue(1, "owner/repo", title=None, body=None)
        state = sm.get_state(_key(1))
        assert state is not None
        assert state.title == ""
        assert state.body == ""

    def test_backfill_fills_missing_meta(self, sm):
        sm.register_issue(1, "owner/repo")  # title/body 未指定
        key = _key(1)
        changed = sm.backfill_issue_meta(key, title="後から補完", body="本文も補完")
        assert changed is True
        state = sm.get_state(key)
        assert state is not None
        assert state.title == "後から補完"
        assert state.body == "本文も補完"

    def test_backfill_does_not_overwrite_existing(self, sm):
        sm.register_issue(1, "owner/repo", title="正本", body="正本本文")
        key = _key(1)
        changed = sm.backfill_issue_meta(key, title="別タイトル", body="別本文")
        assert changed is False
        state = sm.get_state(key)
        assert state is not None
        assert state.title == "正本"
        assert state.body == "正本本文"

    def test_backfill_unregistered_returns_false(self, sm):
        assert sm.backfill_issue_meta(_key(999), title="x") is False


class TestAwaitingSplitApproval:
    """set_awaiting_split_approval の単体テスト (#150)."""

    def test_set_and_clear_flag(self, sm):
        sm.register_issue(1, "owner/repo")
        key = _key(1)
        assert sm.get_state(key).awaiting_split_approval is False
        sm.set_awaiting_split_approval(key, True)
        assert sm.get_state(key).awaiting_split_approval is True
        sm.set_awaiting_split_approval(key, False)
        assert sm.get_state(key).awaiting_split_approval is False

    def test_unregistered_is_noop(self, sm):
        sm.set_awaiting_split_approval(_key(999), True)  # 例外を出さない
