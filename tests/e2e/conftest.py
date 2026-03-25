"""E2E テスト用の共通フィクスチャ.

StateMachineManager, TaskQueue, EventRouter を実際のオブジェクトで構築し、
GitHub / Claude を Fake 実装で差し替える。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from ai_agent_orchestrator.config.settings import RepositoryConfig
from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue
from ai_agent_orchestrator.poller.event_router import EventRouter
from ai_agent_orchestrator.state_persistence import StatePersistence

# ---------------------------------------------------------------------------
# Fake data models
# ---------------------------------------------------------------------------


@dataclass
class FakeIssue:
    """Fake Issue for E2E tests."""

    number: int = 1
    title: str = "Test Issue"
    body: str | None = "Test body"
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    issue_url: str = ""

    def __post_init__(self) -> None:
        if not self.issue_url:
            self.issue_url = f"https://api.github.com/repos/test/repo/issues/{self.number}"


@dataclass
class FakeComment:
    """Fake comment for E2E tests."""

    id: int = 1
    body: str = ""
    issue_url: str = ""
    user: Any = None
    reactions: dict[str, int] = field(default_factory=dict)


@dataclass
class FakePullRequest:
    """Fake pull request for E2E tests."""

    number: int = 100
    title: str = "Test PR"
    state: str = "open"
    body: str = ""
    merged: bool = False


# ---------------------------------------------------------------------------
# Fake tracker (satisfies state_machine.Tracker protocol)
# ---------------------------------------------------------------------------


class FakeTracker:
    """In-memory event tracker that records all events."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Record an event."""
        self.events.append(
            {
                "event": event,
                "issue_number": issue_number,
                "phase": phase,
                "data": data or {},
            }
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_config() -> RepositoryConfig:
    """Standard test RepositoryConfig."""
    return RepositoryConfig(
        owner="test-owner",
        repo="test-repo",
        account="default",
        base_branch="main",
    )


@pytest.fixture
def tmp_persistence(tmp_path: Path) -> StatePersistence:
    """StatePersistence backed by a temp directory."""
    return StatePersistence(state_file=tmp_path / "state.json")


@pytest.fixture
def fake_tracker() -> FakeTracker:
    """In-memory tracker."""
    return FakeTracker()


@pytest.fixture
def state_machine(
    tmp_persistence: StatePersistence,
    fake_tracker: FakeTracker,
) -> StateMachineManager:
    """StateMachineManager wired to temp persistence and fake tracker."""
    return StateMachineManager(
        persistence=tmp_persistence,
        tracker=fake_tracker,
    )


@pytest.fixture
def task_queue() -> TaskQueue:
    """TaskQueue with permissive concurrency."""
    return TaskQueue(max_total=10, max_per_repo=5)


@pytest.fixture
def event_router(
    state_machine: StateMachineManager,
    task_queue: TaskQueue,
) -> EventRouter:
    """EventRouter wired to the real StateMachineManager and TaskQueue."""
    return EventRouter(
        state_machine=state_machine,
        task_queue=task_queue,
    )
