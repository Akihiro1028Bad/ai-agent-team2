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
#   -> (PR approve) -> DONE
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

        # 6. IMPL_PR_APPROVED -> DONE
        await event_router.route(_make_event(EventType.IMPL_PR_APPROVED, repo_config, issue=issue))
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
# Test: Feature-S workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=feature-s) -> HEARING
#   -> PLAN_BRIEF -> PLAN_REVIEW -> (thumbsup) -> IMPLEMENT
#   -> CI pass -> IMPL_REVIEW -> (PR approve) -> DONE
# ---------------------------------------------------------------------------


class TestFeatureSWorkflowE2E:
    """Feature-S ワークフロー: TYPE_DETECTION -> HEARING -> IMPLEMENT -> DONE."""

    async def test_feature_s_workflow_e2e(
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

        # 2. Type detection -> feature-s -> HEARING
        state_machine.set_issue_type(100, "feature-s")
        await state_machine.transition(100, Phase.HEARING)
        assert state_machine.get_phase(100) == Phase.HEARING

        # 3. HEARING -> PLAN_BRIEF
        await state_machine.transition(100, Phase.PLAN_BRIEF)
        assert state_machine.get_phase(100) == Phase.PLAN_BRIEF

        # 4. PLAN_BRIEF -> PLAN_REVIEW
        await state_machine.transition(100, Phase.PLAN_REVIEW)
        assert state_machine.get_phase(100) == Phase.PLAN_REVIEW

        # 5. PLAN_REACTION_ADDED (thumbsup) -> Feature-S goes to IMPLEMENT
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        assert state_machine.get_phase(100) == Phase.IMPLEMENT
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.IMPLEMENT.value for t in tasks)

        # 6. CI success -> IMPL_REVIEW
        await event_router.route(
            _make_event(
                EventType.CI_RESULT,
                repo_config,
                issue=issue,
                extra={"ci_status": "success"},
            )
        )
        assert state_machine.get_phase(100) == Phase.IMPL_REVIEW

        # 7. IMPL_PR_APPROVED -> DONE
        await event_router.route(_make_event(EventType.IMPL_PR_APPROVED, repo_config, issue=issue))
        assert state_machine.get_phase(100) == Phase.DONE

        # Verify full transition path
        transitions = [e for e in fake_tracker.events if e["event"] == "phase_transition"]
        phases_visited = [e["data"]["to"] for e in transitions]
        assert Phase.HEARING.value in phases_visited
        assert Phase.IMPLEMENT.value in phases_visited
        assert Phase.DONE.value in phases_visited

    async def test_feature_s_plan_rejected_and_revised(
        self,
        state_machine: StateMachineManager,
        task_queue: TaskQueue,
        event_router: EventRouter,
        repo_config: RepositoryConfig,
    ) -> None:
        """Feature-S: plan comment (rejection) -> re-do PLAN_BRIEF."""
        issue = FakeIssue(number=101, title="Feature small", body="desc")
        comment = FakeComment(
            id=10,
            body="Please reconsider the approach",
            issue_url=f"https://api.github.com/repos/test/repo/issues/{issue.number}",
        )

        # Setup to PLAN_REVIEW
        await event_router.route(_make_event(EventType.NEW_ISSUE, repo_config, issue=issue))
        state_machine.set_issue_type(101, "feature-s")
        await state_machine.transition(101, Phase.HEARING)
        await state_machine.transition(101, Phase.PLAN_BRIEF)
        await state_machine.transition(101, Phase.PLAN_REVIEW)
        await _drain_queue(task_queue)

        # PLAN_COMMENT_ADDED -> Feature-S goes back to PLAN_BRIEF
        await event_router.route(
            _make_event(
                EventType.PLAN_COMMENT_ADDED,
                repo_config,
                issue=issue,
                comment=comment,
            )
        )
        assert state_machine.get_phase(101) == Phase.PLAN_BRIEF
        tasks = await _drain_queue(task_queue)
        assert any(t.phase == Phase.PLAN_BRIEF.value for t in tasks)


# ---------------------------------------------------------------------------
# Test: Feature-M workflow E2E
#   NEW_ISSUE -> TYPE_DETECTION -> (set type=feature-m) -> HEARING
#   -> DESIGN -> DESIGN_REVIEW -> (PR approve) -> PLANNING -> IMPLEMENT
#   -> CI pass -> IMPL_REVIEW -> (PR approve) -> DONE
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

        # 8. IMPL_PR_APPROVED -> DONE
        await event_router.route(_make_event(EventType.IMPL_PR_APPROVED, repo_config, issue=issue))
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
        state_machine.set_issue_type(301, "feature-s")
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
        state_machine.set_issue_type(302, "feature-s")
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
        state_machine.set_issue_type(401, "feature-s")
        await state_machine.transition(401, Phase.HEARING)
        await state_machine.transition(401, Phase.PLAN_BRIEF)
        await state_machine.transition(401, Phase.PLAN_REVIEW)
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue2))
        await _drain_queue(task_queue)
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
        state_machine.set_issue_type(410, "feature-s")
        await state_machine.transition(410, Phase.HEARING)
        await state_machine.transition(410, Phase.PLAN_BRIEF)
        await state_machine.transition(410, Phase.PLAN_REVIEW)
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        await _drain_queue(task_queue)
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
        state_machine.set_issue_type(500, "feature-s")
        await state_machine.transition(500, Phase.HEARING)
        await state_machine.transition(500, Phase.PLAN_BRIEF)
        await state_machine.transition(500, Phase.PLAN_REVIEW)
        await event_router.route(_make_event(EventType.PLAN_REACTION_ADDED, repo_config, issue=issue))
        await _drain_queue(task_queue)
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

        # IMPL_PR_APPROVED -> DONE
        await event_router.route(_make_event(EventType.IMPL_PR_APPROVED, repo_config, issue=issue))
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
