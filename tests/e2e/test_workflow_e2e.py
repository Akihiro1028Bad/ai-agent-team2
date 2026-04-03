"""E2E ワークフローテスト.

StateMachineManager + EventRouter + TaskQueue を実オブジェクトで使い、
PollEvent をシミュレートして Issue ライフサイクル全体を検証する。
外部 API 呼び出しは一切行わない (Fake / in-memory)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from ai_agent_orchestrator.models import EventType, Phase, PollEvent
from ai_agent_orchestrator.orchestrator.state_machine import (
    InvalidTransitionError,
    StateMachineManager,
)

from .conftest import FakeComment, FakeIssue, FakeTracker

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue
    from ai_agent_orchestrator.poller.event_router import EventRouter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    event_type: str,
    repo: RepositoryConfig,
    *,
    issue: FakeIssue | None = None,
    comment: FakeComment | None = None,
    extra: dict[str, Any] | None = None,
) -> PollEvent:
    """Create a PollEvent from fake data."""
    return PollEvent(
        type=event_type,
        repo=repo,
        issue=issue,  # type: ignore[arg-type]
        comment=comment,  # type: ignore[arg-type]
        extra=extra,
    )


async def _drain_queue(task_queue: TaskQueue) -> list[Any]:
    """Drain all items from the task queue without executing them."""
    items: list[Any] = []
    while task_queue.queued_count > 0:
        item = await task_queue.dequeue()
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Test: Bug workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=bug) -> ANALYSIS
#   -> PLAN_REVIEW -> (thumbsup) -> FIX -> CI pass -> IMPL_REVIEW
#   -> (PR merge) -> DONE
# ---------------------------------------------------------------------------


class TestBugWorkflowE2E:
    """Bug ワークフロー: TYPE_DETECTION -> ANALYSIS -> FIX -> DONE."""

    async def test_bug_workflow_e2e(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        issue = FakeIssue(number=42, title="Bug: NPE on login", body="Steps to reproduce...")

        # 1. NEW_ISSUE -> registers issue, enqueues TYPE_DETECTION
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        assert state_machine.get_phase(42) == Phase.TYPE_DETECTION
        tasks = await _drain_queue(task_queue)
        assert len(tasks) == 1
        assert tasks[0].phase == Phase.TYPE_DETECTION.value

        # 2. Simulate type detection result: set type to bug, transition to ANALYSIS
        state_machine.set_issue_type(42, "bug")
        await state_machine.transition(42, Phase.ANALYSIS)
        assert state_machine.get_phase(42) == Phase.ANALYSIS

        # 3. Simulate analysis complete: transition to PLAN_REVIEW
        await state_machine.transition(42, Phase.PLAN_REVIEW)
        assert state_machine.get_phase(42) == Phase.PLAN_REVIEW

        # 4. PLAN_REACTION_ADDED (thumbsup) -> Bug goes to FIX
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        assert state_machine.get_phase(42) == Phase.FIX
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.FIX.value for t in tasks)

        # 5. Simulate fix complete: transition to IMPL_REVIEW via CI success
        await state_machine.transition(42, Phase.IMPL_REVIEW)
        assert state_machine.get_phase(42) == Phase.IMPL_REVIEW

        # 6. IMPL_PR_MERGED -> DONE (merge で完了判定)
        await event_router.route(_make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue))
        assert state_machine.get_phase(42) == Phase.DONE
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.DONE.value for t in tasks)

        # Verify transition events were tracked
        transition_events = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        assert len(transition_events) >= 4

    async def test_bug_ci_failure_then_fix(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Bug workflow with CI failure -> CI_FIX -> IMPL_REVIEW."""
        issue = FakeIssue(number=50, title="Bug: crash", body="crash")

        # Setup: get issue through to FIX phase
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(50, "bug")
        await state_machine.transition(50, Phase.ANALYSIS)
        await state_machine.transition(50, Phase.PLAN_REVIEW)
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        await _drain_queue(task_queue)
        assert state_machine.get_phase(50) == Phase.FIX

        # FIX -> CI_FIX (simulate CI failure)
        await state_machine.transition(50, Phase.CI_FIX)
        assert state_machine.get_phase(50) == Phase.CI_FIX

        # CI_FIX -> IMPL_REVIEW (simulate CI passes after fix)
        await state_machine.transition(50, Phase.IMPL_REVIEW)
        assert state_machine.get_phase(50) == Phase.IMPL_REVIEW


# ---------------------------------------------------------------------------
# Test: Feature-M (small feature) workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=feature-m) -> HEARING
#   -> DESIGN -> DESIGN_REVIEW -> (PR approve) -> PLANNING -> IMPLEMENT
#   -> CI pass -> IMPL_REVIEW -> (PR merge) -> DONE
# ---------------------------------------------------------------------------


class TestSmallFeatureWorkflowE2E:
    """Small Feature ワークフロー (feature-m): TYPE_DETECTION -> HEARING -> DESIGN -> IMPLEMENT -> DONE."""

    async def test_small_feature_workflow_e2e(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        issue = FakeIssue(number=100, title="Add dark mode toggle", body="Add dark mode")

        # 1. NEW_ISSUE
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        assert state_machine.get_phase(100) == Phase.TYPE_DETECTION
        await _drain_queue(task_queue)

        # 2. Type detection -> feature-m -> HEARING
        state_machine.set_issue_type(100, "feature-m")
        await state_machine.transition(100, Phase.HEARING)
        assert state_machine.get_phase(100) == Phase.HEARING

        # 3. HEARING -> DESIGN
        await state_machine.transition(100, Phase.DESIGN)
        assert state_machine.get_phase(100) == Phase.DESIGN

        # 4. DESIGN -> DESIGN_REVIEW
        await state_machine.transition(100, Phase.DESIGN_REVIEW)
        assert state_machine.get_phase(100) == Phase.DESIGN_REVIEW

        # 5. DESIGN_PR_APPROVED -> PLANNING
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(100) == Phase.PLANNING
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.PLANNING.value for t in tasks)

        # 6. PLANNING -> IMPLEMENT
        await state_machine.transition(100, Phase.IMPLEMENT)
        assert state_machine.get_phase(100) == Phase.IMPLEMENT

        # 7. CI success -> IMPL_REVIEW
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "success"},
            )
        )
        assert state_machine.get_phase(100) == Phase.IMPL_REVIEW

        # 8. IMPL_PR_MERGED -> DONE (merge で完了判定)
        await event_router.route(_make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue))
        assert state_machine.get_phase(100) == Phase.DONE

        # Verify full transition path
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.HEARING.value in phases_visited
        assert Phase.DESIGN.value in phases_visited
        assert Phase.PLANNING.value in phases_visited
        assert Phase.IMPLEMENT.value in phases_visited
        assert Phase.DONE.value in phases_visited


# ---------------------------------------------------------------------------
# Test: Feature-M workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=feature-m) -> HEARING
#   -> DESIGN -> DESIGN_REVIEW -> (PR approve) -> PLANNING -> IMPLEMENT
#   -> CI pass -> IMPL_REVIEW -> (PR merge) -> DONE
# ---------------------------------------------------------------------------


class TestFeatureMWorkflowE2E:
    """Feature-M ワークフロー: TYPE_DETECTION -> HEARING -> DESIGN -> IMPLEMENT -> DONE."""

    async def test_feature_m_workflow_e2e(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        issue = FakeIssue(number=200, title="Major refactor", body="Refactor auth system")

        # 1. NEW_ISSUE
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        assert state_machine.get_phase(200) == Phase.TYPE_DETECTION
        await _drain_queue(task_queue)

        # 2. Type detection -> feature-m -> HEARING
        state_machine.set_issue_type(200, "feature-m")
        await state_machine.transition(200, Phase.HEARING)
        assert state_machine.get_phase(200) == Phase.HEARING

        # 3. HEARING -> DESIGN
        await state_machine.transition(200, Phase.DESIGN)
        assert state_machine.get_phase(200) == Phase.DESIGN

        # 4. DESIGN -> DESIGN_REVIEW
        await state_machine.transition(200, Phase.DESIGN_REVIEW)
        assert state_machine.get_phase(200) == Phase.DESIGN_REVIEW

        # 5. DESIGN_PR_APPROVED -> PLANNING
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(200) == Phase.PLANNING
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.PLANNING.value for t in tasks)

        # 6. PLANNING -> IMPLEMENT
        await state_machine.transition(200, Phase.IMPLEMENT)
        assert state_machine.get_phase(200) == Phase.IMPLEMENT

        # 7. CI success -> IMPL_REVIEW
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "success"},
            )
        )
        assert state_machine.get_phase(200) == Phase.IMPL_REVIEW

        # 8. IMPL_PR_MERGED -> DONE (merge で完了判定)
        await event_router.route(_make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue))
        assert state_machine.get_phase(200) == Phase.DONE

        # Verify the design review phase was visited
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.DESIGN.value in phases_visited
        assert Phase.DESIGN_REVIEW.value in phases_visited
        assert Phase.PLANNING.value in phases_visited

    async def test_feature_m_design_revision(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Feature-M: design PR gets review comments -> DESIGN_REVISE -> re-review."""
        issue = FakeIssue(number=201, title="Feature M with revision", body="desc")

        # Setup to DESIGN_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(201, "feature-m")
        await state_machine.transition(201, Phase.HEARING)
        await state_machine.transition(201, Phase.DESIGN)
        await state_machine.transition(201, Phase.DESIGN_REVIEW)
        await _drain_queue(task_queue)

        # DESIGN_PR_COMMENTED -> DESIGN_REVISE
        await event_router.route(
            _make_event(
                EventType.DESIGN_PR_COMMENTED,
                repo_config,
                issue=issue,
                extra={"comments": ["Fix the API schema"]},
            )
        )
        assert state_machine.get_phase(201) == Phase.DESIGN_REVISE
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.DESIGN_REVISE.value for t in tasks)

        # DESIGN_REVISE -> DESIGN_REVIEW (re-submit)
        await state_machine.transition(201, Phase.DESIGN_REVIEW)
        assert state_machine.get_phase(201) == Phase.DESIGN_REVIEW

        # Now approve
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(201) == Phase.PLANNING


# ---------------------------------------------------------------------------
# Test: SUSPENDED and resume
# ---------------------------------------------------------------------------


class TestSuspendedAndResume:
    """エラーで SUSPENDED に遷移し、resume で復帰するフロー."""

    async def test_suspended_and_resume_to_analysis(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        """Bug issue suspends during analysis, then resumes."""
        issue = FakeIssue(number=300, title="Bug with error", body="Error scenario")

        # Setup: register and get to ANALYSIS
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(300, "bug")
        await state_machine.transition(300, Phase.ANALYSIS)
        await _drain_queue(task_queue)

        # Simulate error -> SUSPENDED
        await state_machine.transition(300, Phase.SUSPENDED)
        assert state_machine.get_phase(300) == Phase.SUSPENDED

        # Resume -> back to ANALYSIS
        await state_machine.transition(300, Phase.ANALYSIS)
        assert state_machine.get_phase(300) == Phase.ANALYSIS

        # Verify suspension event was tracked
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        suspended_transitions = [t for t in transitions if t["data"]["to"] == Phase.SUSPENDED.value]
        assert len(suspended_transitions) >= 1

    async def test_hearing_timeout_suspends(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """HEARING_TIMEOUT event transitions to SUSPENDED."""
        issue = FakeIssue(number=301, title="Timeout test", body="timeout")

        # Setup: register and get to HEARING
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(301, "feature-m")
        await state_machine.transition(301, Phase.HEARING)
        await _drain_queue(task_queue)

        # HEARING_TIMEOUT -> SUSPENDED
        await event_router.route(_make_event(EventType.HEARING_TIMEOUT, repo_config, issue=issue))
        assert state_machine.get_phase(301) == Phase.SUSPENDED

    async def test_suspended_resume_to_implement(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Resume from SUSPENDED directly to IMPLEMENT."""
        issue = FakeIssue(number=302, title="Resume implement", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(302, "feature-m")
        await state_machine.transition(302, Phase.HEARING)
        await state_machine.transition(302, Phase.SUSPENDED)
        await _drain_queue(task_queue)

        assert state_machine.get_phase(302) == Phase.SUSPENDED

        # Resume to IMPLEMENT
        await state_machine.transition(302, Phase.IMPLEMENT)
        assert state_machine.get_phase(302) == Phase.IMPLEMENT


# ---------------------------------------------------------------------------
# Test: CI failure handling via EventRouter
# ---------------------------------------------------------------------------


class TestCIResultHandling:
    """CI_RESULT イベントによる CI_FIX / IMPL_REVIEW 遷移."""

    async def test_ci_failure_triggers_ci_fix(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """CI failure routes to CI_FIX phase."""
        issue = FakeIssue(number=400, title="CI fail test", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(400, "bug")
        await state_machine.transition(400, Phase.ANALYSIS)
        await state_machine.transition(400, Phase.PLAN_REVIEW)
        # PLAN_REACTION -> FIX
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        await _drain_queue(task_queue)
        assert state_machine.get_phase(400) == Phase.FIX

        # FIX -> IMPL_REVIEW (simulate agent created PR)
        await state_machine.transition(400, Phase.IMPL_REVIEW)

        # CI_RESULT failure -> CI_FIX (note: CI_FIX transitions from IMPL_REVIEW
        # are not defined, so we go from IMPLEMENT state instead)
        # Let's test from IMPLEMENT state
        issue2 = FakeIssue(number=401, title="CI fail test 2", body="desc")
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue2))
        state_machine.set_issue_type(401, "feature-m")
        await state_machine.transition(401, Phase.HEARING)
        await state_machine.transition(401, Phase.DESIGN)
        await state_machine.transition(401, Phase.DESIGN_REVIEW)
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue2))
        await _drain_queue(task_queue)
        await state_machine.transition(401, Phase.IMPLEMENT)
        assert state_machine.get_phase(401) == Phase.IMPLEMENT

        # CI failure -> CI_FIX
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue2,
                extra={"ci_status": "failure"},
            )
        )
        assert state_machine.get_phase(401) == Phase.CI_FIX
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.CI_FIX.value for t in tasks)

    async def test_ci_failure_exceeds_max_retries_suspends(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """CI failure after 3 retries -> SUSPENDED."""
        issue = FakeIssue(number=410, title="CI max retries", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(410, "feature-m")
        await state_machine.transition(410, Phase.HEARING)
        await state_machine.transition(410, Phase.DESIGN)
        await state_machine.transition(410, Phase.DESIGN_REVIEW)
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue))
        await _drain_queue(task_queue)
        await state_machine.transition(410, Phase.IMPLEMENT)
        assert state_machine.get_phase(410) == Phase.IMPLEMENT

        # Simulate 3 CI retries already happened
        await state_machine.increment_ci_retry(410)
        await state_machine.increment_ci_retry(410)
        await state_machine.increment_ci_retry(410)

        # Next CI failure should SUSPEND
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "failure"},
            )
        )
        assert state_machine.get_phase(410) == Phase.SUSPENDED


# ---------------------------------------------------------------------------
# Test: IMPL_REVISE (review comments on impl PR)
# ---------------------------------------------------------------------------


class TestImplRevise:
    """Implementation PR gets review comments -> IMPL_REVISE -> re-review."""

    async def test_impl_pr_commented_triggers_revise(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        issue = FakeIssue(number=500, title="Impl revise test", body="desc")

        # Setup to IMPL_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(500, "feature-m")
        await state_machine.transition(500, Phase.HEARING)
        await state_machine.transition(500, Phase.DESIGN)
        await state_machine.transition(500, Phase.DESIGN_REVIEW)
        await event_router.route(_make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue))
        await _drain_queue(task_queue)
        await state_machine.transition(500, Phase.IMPLEMENT)
        await state_machine.transition(500, Phase.IMPL_REVIEW)

        # IMPL_PR_COMMENTED -> IMPL_REVISE
        await event_router.route(
            _make_event(
                EventType.IMPL_PR_COMMENTED,
                repo_config,
                issue=issue,
                extra={"comments": ["Fix the variable naming"]},
            )
        )
        assert state_machine.get_phase(500) == Phase.IMPL_REVISE
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.IMPL_REVISE.value for t in tasks)

        # IMPL_REVISE -> IMPL_REVIEW (re-submit)
        await state_machine.transition(500, Phase.IMPL_REVIEW)
        assert state_machine.get_phase(500) == Phase.IMPL_REVIEW

        # IMPL_PR_MERGED -> DONE (merge で完了判定)
        await event_router.route(_make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue))
        assert state_machine.get_phase(500) == Phase.DONE


# ---------------------------------------------------------------------------
# Test: Invalid transitions are rejected
# ---------------------------------------------------------------------------


class TestInvalidTransitions:
    """State machine rejects invalid transitions."""

    async def test_cannot_skip_phases(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Cannot jump from TYPE_DETECTION directly to DONE."""
        issue = FakeIssue(number=600, title="Invalid", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(600, "bug")
        await _drain_queue(task_queue)

        with pytest.raises(InvalidTransitionError):
            await state_machine.transition(600, Phase.DONE)

    async def test_duplicate_issue_registration_rejected(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Registering the same issue number twice raises ValueError."""
        issue = FakeIssue(number=601, title="Duplicate", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        await _drain_queue(task_queue)

        with pytest.raises(ValueError, match="already registered"):
            state_machine.register_issue(601, "test-owner/test-repo")


# ---------------------------------------------------------------------------
# Test: Task queue enqueue verification
# ---------------------------------------------------------------------------


class TestTaskQueueIntegration:
    """EventRouter correctly enqueues tasks with right priority and metadata."""

    async def test_new_issue_enqueues_type_detection(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        issue = FakeIssue(number=700, title="Queue test", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))

        assert task_queue.queued_count == 1
        task = await task_queue.dequeue()
        assert task.issue_number == 700
        assert task.phase == Phase.TYPE_DETECTION.value

    async def test_design_pr_commented_enqueues_critical_priority(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Review comments get CRITICAL priority."""
        issue = FakeIssue(number=701, title="Priority test", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(701, "feature-m")
        await state_machine.transition(701, Phase.HEARING)
        await state_machine.transition(701, Phase.DESIGN)
        await state_machine.transition(701, Phase.DESIGN_REVIEW)
        await _drain_queue(task_queue)

        await event_router.route(
            _make_event(
                EventType.DESIGN_PR_COMMENTED,
                repo_config,
                issue=issue,
                extra={"comments": ["needs changes"]},
            )
        )
        task = await task_queue.dequeue()
        assert task.priority == 1  # CRITICAL


# ---------------------------------------------------------------------------
# Test: Feature-L workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=feature-l) -> HEARING
#   -> SPLIT_PROPOSAL -> (thumbsup) -> SPLIT_EXECUTE -> DONE
# ---------------------------------------------------------------------------


class TestFeatureLWorkflowE2E:
    """Feature-L ワークフロー: TYPE_DETECTION -> HEARING -> SPLIT -> DONE."""

    async def test_feature_l_workflow_e2e(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        """Feature-L 正常系フルフロー."""
        issue = FakeIssue(number=800, title="Large refactor", body="Rewrite entire auth system")

        # 1. NEW_ISSUE -> TYPE_DETECTION
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        assert state_machine.get_phase(800) == Phase.TYPE_DETECTION
        await _drain_queue(task_queue)

        # 2. Type detection -> feature-l -> HEARING
        state_machine.set_issue_type(800, "feature-l")
        await state_machine.transition(800, Phase.HEARING)
        assert state_machine.get_phase(800) == Phase.HEARING

        # 3. HEARING -> SPLIT_PROPOSAL
        await state_machine.transition(800, Phase.SPLIT_PROPOSAL)
        assert state_machine.get_phase(800) == Phase.SPLIT_PROPOSAL

        # 4. SPLIT_APPROVED -> SPLIT_EXECUTE
        await event_router.route(_make_event(EventType.SPLIT_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(800) == Phase.SPLIT_EXECUTE
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.SPLIT_EXECUTE.value for t in tasks)

        # 5. SPLIT_EXECUTE -> DONE
        await state_machine.transition(800, Phase.DONE)
        assert state_machine.get_phase(800) == Phase.DONE

        # Verify transition path
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.HEARING.value in phases_visited
        assert Phase.SPLIT_PROPOSAL.value in phases_visited
        assert Phase.SPLIT_EXECUTE.value in phases_visited
        assert Phase.DONE.value in phases_visited

    async def test_feature_l_split_modification(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Feature-L 分割修正: SPLIT_MODIFIED -> HEARING 再ヒアリング -> 再提案 -> 承認."""
        issue = FakeIssue(number=801, title="Large feature with revision", body="desc")
        comment = FakeComment(id=10, body="Split differently please", issue_url=f"https://api.github.com/repos/test/repo/issues/801")

        # Setup to SPLIT_PROPOSAL
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(801, "feature-l")
        await state_machine.transition(801, Phase.HEARING)
        await state_machine.transition(801, Phase.SPLIT_PROPOSAL)
        await _drain_queue(task_queue)

        # SPLIT_MODIFIED -> HEARING (re-gather requirements)
        await event_router.route(
            _make_event(EventType.SPLIT_MODIFIED, repo_config, issue=issue, comment=comment)
        )
        assert state_machine.get_phase(801) == Phase.HEARING
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.HEARING.value for t in tasks)
        # extra に modification_request が含まれる
        hearing_task = next(t for t in tasks if t.phase == Phase.HEARING.value)
        assert hearing_task.extra.get("modification_request") == "Split differently please"

        # 再ヒアリング -> 再提案 -> 承認 -> DONE
        await state_machine.transition(801, Phase.SPLIT_PROPOSAL)
        await event_router.route(_make_event(EventType.SPLIT_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(801) == Phase.SPLIT_EXECUTE
        await state_machine.transition(801, Phase.DONE)
        assert state_machine.get_phase(801) == Phase.DONE


# ---------------------------------------------------------------------------
# Test: HEARING_WAIT (user reply) workflow
# ---------------------------------------------------------------------------


class TestHearingWaitWorkflow:
    """HEARING_WAIT フロー: ヒアリング中のユーザー回答待ち・回答受信."""

    async def test_hearing_wait_reply_resumes_hearing(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """HEARING_WAIT でユーザーが回答 -> HEARING に復帰しタスクエンキュー."""
        issue = FakeIssue(number=810, title="Feature with questions", body="desc")
        comment = FakeComment(
            id=20,
            body="Here is my answer",
            issue_url="https://api.github.com/repos/test/repo/issues/810",
        )

        # Setup: NEW_ISSUE -> HEARING -> HEARING_WAIT
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(810, "feature-m")
        await state_machine.transition(810, Phase.HEARING)
        await state_machine.transition(810, Phase.HEARING_WAIT)
        await _drain_queue(task_queue)
        assert state_machine.get_phase(810) == Phase.HEARING_WAIT

        # ISSUE_COMMENT from HEARING_WAIT -> HEARING
        await event_router.route(
            _make_event(EventType.ISSUE_COMMENT, repo_config, comment=comment)
        )
        assert state_machine.get_phase(810) == Phase.HEARING
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.HEARING.value for t in tasks)
        # extra にコメント本文が含まれる
        hearing_task = next(t for t in tasks if t.phase == Phase.HEARING.value)
        assert hearing_task.extra.get("comment") == "Here is my answer"

    async def test_hearing_wait_full_cycle(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        """HEARING -> HEARING_WAIT -> 回答 -> HEARING -> DESIGN (Feature-M 完全フロー)."""
        issue = FakeIssue(number=811, title="Feature needing clarification", body="desc")
        comment = FakeComment(
            id=21,
            body="The feature should support dark mode",
            issue_url="https://api.github.com/repos/test/repo/issues/811",
        )

        # Setup: Feature-M -> HEARING -> HEARING_WAIT
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(811, "feature-m")
        await state_machine.transition(811, Phase.HEARING)
        await state_machine.transition(811, Phase.HEARING_WAIT)
        await _drain_queue(task_queue)

        # User replies -> HEARING
        await event_router.route(
            _make_event(EventType.ISSUE_COMMENT, repo_config, comment=comment)
        )
        assert state_machine.get_phase(811) == Phase.HEARING
        await _drain_queue(task_queue)

        # HEARING -> DESIGN (requirements complete)
        await state_machine.transition(811, Phase.DESIGN)
        assert state_machine.get_phase(811) == Phase.DESIGN

        # Verify HEARING_WAIT was visited
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.HEARING_WAIT.value in phases_visited
        assert Phase.HEARING.value in phases_visited
        assert Phase.DESIGN.value in phases_visited

    async def test_hearing_wait_timeout_then_resume_via_comment(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """HEARING_WAIT -> タイムアウト -> SUSPENDED -> コメントで HEARING 復帰."""
        issue = FakeIssue(number=812, title="Timeout then resume", body="desc")
        comment = FakeComment(
            id=22,
            body="Sorry for the delay, here is my answer",
            issue_url="https://api.github.com/repos/test/repo/issues/812",
        )

        # Setup: Feature-M -> HEARING -> HEARING_WAIT
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(812, "feature-m")
        await state_machine.transition(812, Phase.HEARING)
        await state_machine.transition(812, Phase.HEARING_WAIT)
        await _drain_queue(task_queue)

        # Timeout -> SUSPENDED
        await event_router.route(
            _make_event(EventType.HEARING_TIMEOUT, repo_config, issue=issue)
        )
        assert state_machine.get_phase(812) == Phase.SUSPENDED

        # Late reply -> HEARING (resume from SUSPENDED)
        await event_router.route(
            _make_event(EventType.ISSUE_COMMENT, repo_config, comment=comment)
        )
        assert state_machine.get_phase(812) == Phase.HEARING
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.HEARING.value for t in tasks)


# ---------------------------------------------------------------------------
# Test: Bug plan rejection cycle
# ---------------------------------------------------------------------------


class TestBugPlanRejection:
    """Bug 方針指摘 -> 再分析ループ."""

    async def test_plan_comment_triggers_reanalysis(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Bug PLAN_REVIEW -> 方針指摘コメント -> ANALYSIS (再分析)."""
        issue = FakeIssue(number=820, title="Bug: rejected plan", body="desc")
        comment = FakeComment(
            id=30,
            body="This approach won't work, try a different strategy",
            issue_url="https://api.github.com/repos/test/repo/issues/820",
        )

        # Setup: Bug -> PLAN_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(820, "bug")
        await state_machine.transition(820, Phase.ANALYSIS)
        await state_machine.transition(820, Phase.PLAN_REVIEW)
        await _drain_queue(task_queue)
        assert state_machine.get_phase(820) == Phase.PLAN_REVIEW

        # PLAN_COMMENT -> ANALYSIS (re-analyze)
        await event_router.route(
            _make_event(EventType.PLAN_COMMENT_ADDED, repo_config, issue=issue, comment=comment)
        )
        assert state_machine.get_phase(820) == Phase.ANALYSIS
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.ANALYSIS.value for t in tasks)
        # extra に feedback が含まれる
        analysis_task = next(t for t in tasks if t.phase == Phase.ANALYSIS.value)
        assert analysis_task.extra.get("feedback") == "This approach won't work, try a different strategy"

    async def test_plan_rejection_then_approval_cycle(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        """Bug: 方針指摘 -> 再分析 -> 再提案 -> 承認 -> FIX -> DONE (完全サイクル)."""
        issue = FakeIssue(number=821, title="Bug: full rejection cycle", body="desc")
        rejection_comment = FakeComment(
            id=31,
            body="Wrong approach",
            issue_url="https://api.github.com/repos/test/repo/issues/821",
        )

        # Setup: Bug -> PLAN_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(821, "bug")
        await state_machine.transition(821, Phase.ANALYSIS)
        await state_machine.transition(821, Phase.PLAN_REVIEW)
        await _drain_queue(task_queue)

        # 1. Rejection -> ANALYSIS
        await event_router.route(
            _make_event(EventType.PLAN_COMMENT_ADDED, repo_config, issue=issue, comment=rejection_comment)
        )
        assert state_machine.get_phase(821) == Phase.ANALYSIS
        await _drain_queue(task_queue)

        # 2. Re-analysis -> PLAN_REVIEW again
        await state_machine.transition(821, Phase.PLAN_REVIEW)
        assert state_machine.get_phase(821) == Phase.PLAN_REVIEW

        # 3. Approval -> FIX
        await event_router.route(
            _make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue)
        )
        assert state_machine.get_phase(821) == Phase.FIX
        await _drain_queue(task_queue)

        # 4. FIX -> IMPL_REVIEW -> merge -> DONE
        await state_machine.transition(821, Phase.IMPL_REVIEW)
        await event_router.route(
            _make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue)
        )
        assert state_machine.get_phase(821) == Phase.DONE

        # Verify ANALYSIS was visited twice
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        analysis_visits = [t for t in transitions if t["data"]["to"] == Phase.ANALYSIS.value]
        assert len(analysis_visits) >= 2


# ---------------------------------------------------------------------------
# Test: IMPL_PR_APPROVED is info-only (no DONE transition)
# ---------------------------------------------------------------------------


class TestImplPrApprovedInfoOnly:
    """IMPL_PR_APPROVED はログのみで DONE に遷移しない."""

    async def test_impl_pr_approved_does_not_transition_to_done(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """IMPL_PR_APPROVED -> IMPL_REVIEW のまま (merge を待つ)."""
        issue = FakeIssue(number=830, title="Approve vs merge", body="desc")

        # Setup: Bug -> IMPL_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(830, "bug")
        await state_machine.transition(830, Phase.ANALYSIS)
        await state_machine.transition(830, Phase.PLAN_REVIEW)
        await event_router.route(
            _make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue)
        )
        await _drain_queue(task_queue)
        await state_machine.transition(830, Phase.IMPL_REVIEW)
        assert state_machine.get_phase(830) == Phase.IMPL_REVIEW

        # IMPL_PR_APPROVED -> still IMPL_REVIEW (info only)
        await event_router.route(
            _make_event(EventType.IMPL_PR_APPROVED, repo_config, issue=issue)
        )
        assert state_machine.get_phase(830) == Phase.IMPL_REVIEW
        tasks = await _drain_queue(task_queue)
        assert len(tasks) == 0  # No task enqueued

        # Only IMPL_PR_MERGED completes the flow
        await event_router.route(
            _make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue)
        )
        assert state_machine.get_phase(830) == Phase.DONE


# ---------------------------------------------------------------------------
# Test: Feature-M with CI failure path
# ---------------------------------------------------------------------------


class TestFeatureMWithCI:
    """Feature-M: 実装 -> CI失敗 -> CI_FIX -> CI成功 -> レビュー -> DONE."""

    async def test_feature_m_implement_ci_failure_recovery(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
        fake_tracker: FakeTracker,
    ) -> None:
        """Feature-M: IMPLEMENT -> CI failure -> CI_FIX -> CI success -> IMPL_REVIEW -> merge -> DONE."""
        issue = FakeIssue(number=840, title="Feature with CI issues", body="desc")

        # Setup: Feature-M -> IMPLEMENT
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(840, "feature-m")
        await state_machine.transition(840, Phase.HEARING)
        await state_machine.transition(840, Phase.DESIGN)
        await state_machine.transition(840, Phase.DESIGN_REVIEW)
        await event_router.route(
            _make_event(EventType.DESIGN_PR_APPROVED, repo_config, issue=issue)
        )
        await _drain_queue(task_queue)
        await state_machine.transition(840, Phase.IMPLEMENT)
        assert state_machine.get_phase(840) == Phase.IMPLEMENT

        # CI failure -> CI_FIX
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "failure"},
            )
        )
        assert state_machine.get_phase(840) == Phase.CI_FIX
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.CI_FIX.value for t in tasks)

        # CI success -> IMPL_REVIEW
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "success"},
            )
        )
        assert state_machine.get_phase(840) == Phase.IMPL_REVIEW

        # merge -> DONE
        await event_router.route(
            _make_event(EventType.IMPL_PR_MERGED, repo_config, issue=issue)
        )
        assert state_machine.get_phase(840) == Phase.DONE

        # Verify CI_FIX was visited
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.CI_FIX.value in phases_visited
        assert Phase.IMPL_REVIEW.value in phases_visited
        assert Phase.DONE.value in phases_visited


# ---------------------------------------------------------------------------
# Test: Guard conditions (issue_type branching)
# ---------------------------------------------------------------------------


class TestGuardConditions:
    """issue_type によるガード分岐テスト."""

    async def test_type_detection_feature_l_to_hearing(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """TYPE_DETECTION (feature-l) -> HEARING (feature-l ガード)."""
        issue = FakeIssue(number=850, title="Large feature", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(850, "feature-l")
        await _drain_queue(task_queue)

        # feature-l -> HEARING (detect_feature_l transition)
        await state_machine.transition(850, Phase.HEARING)
        assert state_machine.get_phase(850) == Phase.HEARING

    async def test_hearing_bug_to_analysis(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """HEARING (bug) -> ANALYSIS (bug ガードでヒアリング後に分析へ)."""
        issue = FakeIssue(number=851, title="Bug after hearing", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(851, "bug")
        await state_machine.transition(851, Phase.ANALYSIS)
        # Bug は TYPE_DETECTION → ANALYSIS が通常パスだが、
        # HEARING 経由 (例: SUSPENDED から復帰後) の場合:
        await state_machine.transition(851, Phase.SUSPENDED)
        await state_machine.transition(851, Phase.HEARING)
        await _drain_queue(task_queue)

        # HEARING -> ANALYSIS (bug guard)
        await state_machine.transition(851, Phase.ANALYSIS)
        assert state_machine.get_phase(851) == Phase.ANALYSIS

    async def test_hearing_feature_l_to_split_proposal(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """HEARING (feature-l) -> SPLIT_PROPOSAL (feature-l ガード)."""
        issue = FakeIssue(number=852, title="Large feature to split", body="desc")

        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(852, "feature-l")
        await state_machine.transition(852, Phase.HEARING)
        await _drain_queue(task_queue)

        # HEARING -> SPLIT_PROPOSAL (feature-l guard)
        await state_machine.transition(852, Phase.SPLIT_PROPOSAL)
        assert state_machine.get_phase(852) == Phase.SPLIT_PROPOSAL
