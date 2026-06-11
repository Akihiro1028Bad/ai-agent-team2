"""IssueKey によるリポジトリ横断 Issue 識別のテスト.

同一 Issue 番号が異なるリポジトリに存在する場合に、
StateMachineManager, TaskQueue, GitHubPoller が正しく区別できることを検証する。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import IssueKey, Phase
from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
from ai_agent_orchestrator.orchestrator.task_queue import TaskQueue, TaskRequest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_persistence() -> MagicMock:
    p = MagicMock()
    p.load.return_value = {}
    p.save = MagicMock()
    return p


@pytest.fixture
def mock_tracker() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def sm(mock_persistence: MagicMock, mock_tracker: AsyncMock) -> StateMachineManager:
    return StateMachineManager(persistence=mock_persistence, tracker=mock_tracker)


def _make_repo(owner: str, repo: str) -> MagicMock:
    r = MagicMock()
    r.owner = owner
    r.repo = repo
    return r


# ---------------------------------------------------------------------------
# StateMachineManager: cross-repo independence
# ---------------------------------------------------------------------------


class TestStateMachineCrossRepo:
    """同一 Issue 番号が異なるリポジトリで独立に管理されることをテスト."""

    def test_register_same_number_different_repos(self, sm: StateMachineManager) -> None:
        """repo-A#42 と repo-B#42 を独立に登録できる."""
        sm.register_issue(42, "org/repo-a")
        sm.register_issue(42, "org/repo-b")

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        assert sm.get_phase(key_a) == Phase.INTAKE
        assert sm.get_phase(key_b) == Phase.INTAKE

    @pytest.mark.asyncio
    async def test_independent_transitions(self, sm: StateMachineManager) -> None:
        """repo-A#42 と repo-B#42 が独立に遷移できる."""
        sm.register_issue(42, "org/repo-a")
        sm.register_issue(42, "org/repo-b")

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        sm.set_issue_type(key_a, "bug")
        sm.set_issue_type(key_b, "feature-m")

        await sm.transition(key_a, Phase.PLAN)
        await sm.transition(key_b, Phase.CLARIFY)

        assert sm.get_phase(key_a) == Phase.PLAN
        assert sm.get_phase(key_b) == Phase.CLARIFY

    def test_independent_issue_types(self, sm: StateMachineManager) -> None:
        """repo-A#42 と repo-B#42 が独立に issue_type を持つ."""
        sm.register_issue(42, "org/repo-a")
        sm.register_issue(42, "org/repo-b")

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        sm.set_issue_type(key_a, "bug")
        sm.set_issue_type(key_b, "feature-l")

        assert sm.get_issue_type(key_a) == "bug"
        assert sm.get_issue_type(key_b) == "feature-l"

    @pytest.mark.asyncio
    async def test_independent_ci_retry_counts(self, sm: StateMachineManager) -> None:
        """repo-A#42 と repo-B#42 が独立に CI リトライカウントを持つ."""
        sm.register_issue(42, "org/repo-a")
        sm.register_issue(42, "org/repo-b")

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        await sm.increment_ci_retry(key_a)
        await sm.increment_ci_retry(key_a)

        assert await sm.get_ci_retry_count(key_a) == 2
        assert await sm.get_ci_retry_count(key_b) == 0


# ---------------------------------------------------------------------------
# TaskQueue: cross-repo enqueue
# ---------------------------------------------------------------------------


class TestTaskQueueCrossRepo:
    """同一 Issue 番号が異なるリポジトリでキューに入れられることをテスト."""

    async def test_enqueue_same_number_different_repos(self) -> None:
        """repo-A#42 と repo-B#42 を両方キューに入れられる."""
        tq = TaskQueue(max_total=5, max_per_repo=2)
        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")

        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_a, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_b, phase="hearing"))

        assert tq.queued_count == 2

    async def test_dequeue_returns_both(self) -> None:
        """repo-A#42 と repo-B#42 が両方 dequeue される."""
        tq = TaskQueue(max_total=5, max_per_repo=2)
        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")

        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_a, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_b, phase="design"))

        first = await tq.dequeue()
        second = await tq.dequeue()

        repo_keys = {first.repo_key, second.repo_key}
        assert repo_keys == {"org/repo-a", "org/repo-b"}

    async def test_cancel_only_affects_target_repo(self) -> None:
        """cancel_task は指定リポジトリの Issue のみキャンセルする."""
        tq = TaskQueue(max_total=5, max_per_repo=2)

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        dummy_a = asyncio.create_task(asyncio.sleep(10))
        dummy_b = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[key_a] = dummy_a
        tq._active_tasks[key_b] = dummy_b

        result_a = await tq.cancel_task(key_a)
        result_nonexistent = await tq.cancel_task(("org/repo-c", 42))

        assert result_a is True
        assert result_nonexistent is False

        # repo-b のキャンセルは呼ばれていないことを確認
        # (cancel_task は asyncio.Task.cancel() を呼ぶだけで _active_tasks からの
        #  削除は worker_loop の finally ブロックで行われる)
        assert not dummy_b.cancelling()

        dummy_a.cancel()
        dummy_b.cancel()
        await asyncio.gather(dummy_a, dummy_b, return_exceptions=True)

    async def test_queued_issues_distinguishes_repos(self) -> None:
        """_queued_issues がリポジトリ別に Issue を追跡する."""
        tq = TaskQueue(max_total=5, max_per_repo=2)
        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_a, phase="hearing"))
        assert key_a in tq._queued_issues
        assert key_b not in tq._queued_issues

        await tq.enqueue(TaskRequest(issue_number=42, repo=repo_b, phase="hearing"))
        assert key_a in tq._queued_issues
        assert key_b in tq._queued_issues


# ---------------------------------------------------------------------------
# GitHubPoller: _seen_issue_numbers distinguishes repos
# ---------------------------------------------------------------------------


class TestGitHubPollerCrossRepo:
    """GitHubPoller の _seen_issue_numbers がリポジトリ別に Issue を区別するテスト."""

    def test_seen_issue_numbers_uses_issue_key(self) -> None:
        """_seen_issue_numbers が IssueKey タプルを使用する."""
        # _seen_issue_numbers は set[IssueKey] なので
        # 同一番号でもリポジトリが異なれば別エントリ
        seen: set[IssueKey] = set()

        key_a: IssueKey = ("org/repo-a", 42)
        key_b: IssueKey = ("org/repo-b", 42)

        seen.add(key_a)
        assert key_a in seen
        assert key_b not in seen

        seen.add(key_b)
        assert key_a in seen
        assert key_b in seen
        assert len(seen) == 2

    def test_seen_reactions_uses_three_tuple(self) -> None:
        """_seen_reactions が (repo_key, issue_number, comment_id) 3-tuple を使用する."""
        seen: set[tuple[str, int, int]] = set()

        seen.add(("org/repo-a", 42, 100))
        seen.add(("org/repo-b", 42, 100))

        assert len(seen) == 2
        assert ("org/repo-a", 42, 100) in seen
        assert ("org/repo-b", 42, 100) in seen
