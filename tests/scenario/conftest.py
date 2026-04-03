"""Scenario test fixtures: real GitHub API + real Claude SDK."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
from ai_agent_orchestrator.config.settings import (
    AccountConfig,
    RepositoryConfig,
)
from ai_agent_orchestrator.context.engine import ContextEngine
from ai_agent_orchestrator.credential import CredentialResolver
from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.github.client import AccountManager, GitHubClient
from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue
from ai_agent_orchestrator.phases.base import NotifierProtocol
from ai_agent_orchestrator.poller.event_router import EventRouter
from ai_agent_orchestrator.state_persistence import StatePersistence
from ai_agent_orchestrator.workspace_manager import WorkspaceManager

from .helpers import (
    cleanup_branch,
    cleanup_issue,
    cleanup_pr,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skip guard: require GITHUB_TOKEN
# ---------------------------------------------------------------------------

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_HAS_TOKEN = bool(_GITHUB_TOKEN)

pytestmark = [
    pytest.mark.scenario,
    pytest.mark.skipif(not _HAS_TOKEN, reason="GITHUB_TOKEN not set"),
]

# ---------------------------------------------------------------------------
# Test repository configuration
# ---------------------------------------------------------------------------

TEST_OWNER = "Akihiro1028Bad"
TEST_REPO = "ai-agent-team2-test"


# ---------------------------------------------------------------------------
# Null notifier (Slack not needed for scenario tests)
# ---------------------------------------------------------------------------


class NullNotifier(NotifierProtocol):
    """No-op notifier for scenario tests."""

    async def notify(
        self,
        message: str,
        *,
        level: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None:
        logger.info("[NullNotifier] %s: %s", level, message[:200])


# ---------------------------------------------------------------------------
# Session-scoped fixtures (expensive, shared across all scenario tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def github_token() -> str:
    """Provide GITHUB_TOKEN, skip if not available."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        pytest.skip("GITHUB_TOKEN not set")
    return token


@pytest.fixture(scope="session")
def repo_config() -> RepositoryConfig:
    """Test repository configuration."""
    return RepositoryConfig(
        owner=TEST_OWNER,
        repo=TEST_REPO,
        label="ai-agent",
        base_branch="main",
    )


@pytest.fixture(scope="session")
def github_client(github_token) -> GitHubClient:
    """Real GitHub API client."""
    return GitHubClient(token=github_token)


@pytest.fixture(scope="session")
def account_config() -> AccountConfig:
    """Account config using GITHUB_TOKEN env var."""
    return AccountConfig(
        name="default",
        token_env="GITHUB_TOKEN",
        default=True,
    )


@pytest.fixture(scope="session")
def account_manager(
    account_config,
    repo_config,
) -> AccountManager:
    """Real AccountManager for phase executors."""
    resolver = CredentialResolver()
    return AccountManager(
        accounts={"default": account_config},
        resolver=resolver,
        repo_configs=[repo_config],
    )


@pytest.fixture(scope="session")
def notifier() -> NullNotifier:
    """No-op notifier."""
    return NullNotifier()


# ---------------------------------------------------------------------------
# Function-scoped fixtures (per-test isolation)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path) -> Path:
    """Temporary directory for state/logs."""
    return tmp_path


@pytest.fixture
def event_logger(tmp_dir) -> EventLogger:
    """Real event logger writing to temp directory."""
    log_dir = tmp_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return EventLogger(log_dir=log_dir)


@pytest.fixture
def state_persistence(tmp_dir) -> StatePersistence:
    """State persistence writing to temp directory."""
    state_file = tmp_dir / "state.json"
    return StatePersistence(state_file=state_file)


@pytest.fixture
def state_machine(state_persistence, event_logger) -> StateMachineManager:
    """Real state machine manager."""
    return StateMachineManager(
        persistence=state_persistence,
        tracker=event_logger,
    )


@pytest.fixture
def task_queue() -> TaskQueue:
    """Task queue with single-task concurrency for predictable test flow."""
    return TaskQueue(max_total=1, max_per_repo=1)


@pytest.fixture
def event_router(state_machine, task_queue, account_manager) -> EventRouter:
    """Real event router connected to state machine and task queue."""
    return EventRouter(
        state_machine=state_machine,
        task_queue=task_queue,
        account_manager=account_manager,
    )


@pytest.fixture
def claude_runner(event_logger) -> ClaudeAgentRunner:
    """Real Claude Agent SDK runner."""
    return ClaudeAgentRunner(tracker=event_logger)


@pytest.fixture
def workspace_manager() -> WorkspaceManager:
    """Real workspace manager using default workspace directory."""
    return WorkspaceManager()


@pytest.fixture
def context_engine() -> ContextEngine:
    """Real context engine."""
    return ContextEngine()


@pytest.fixture
def phase_executors(
    claude_runner,
    account_manager,
    notifier,
    event_logger,
    workspace_manager,
    context_engine,
    state_machine,
) -> dict[str, Any]:
    """Build all phase executors with real dependencies."""
    from ai_agent_orchestrator.orchestrator.orchestrator import (
        _build_phase_executors,
    )

    return _build_phase_executors(
        runner=claude_runner,
        github=account_manager,
        notifier=notifier,
        tracker=event_logger,
        workspace=workspace_manager,
        context_engine=context_engine,
        state_machine=state_machine,
    )


# ---------------------------------------------------------------------------
# Cleanup tracker (autouse for scenario tests)
# ---------------------------------------------------------------------------


class CleanupTracker:
    """Tracks created GitHub resources for cleanup."""

    def __init__(self, client: GitHubClient, repo: RepositoryConfig) -> None:
        self.client = client
        self.repo = repo
        self.issue_numbers: list[int] = []
        self.pr_numbers: list[int] = []
        self.branch_names: list[str] = []

    def track_issue(self, issue_number: int) -> None:
        self.issue_numbers.append(issue_number)

    def track_pr(self, pr_number: int) -> None:
        self.pr_numbers.append(pr_number)

    def track_branch(self, branch_name: str) -> None:
        self.branch_names.append(branch_name)

    async def cleanup_all(self) -> None:
        """Close all tracked issues, PRs, and delete branches."""
        for pr_number in self.pr_numbers:
            await cleanup_pr(self.client, self.repo, pr_number)

        for issue_number in self.issue_numbers:
            await cleanup_issue(self.client, self.repo, issue_number)

        for branch_name in self.branch_names:
            await cleanup_branch(self.client, self.repo, branch_name)

        logger.info(
            "Cleanup complete: %d issues, %d PRs, %d branches",
            len(self.issue_numbers),
            len(self.pr_numbers),
            len(self.branch_names),
        )


@pytest.fixture
async def cleanup_tracker(github_client, repo_config):
    """Track and cleanup all created GitHub resources after test."""
    tracker = CleanupTracker(github_client, repo_config)
    yield tracker
    await tracker.cleanup_all()
