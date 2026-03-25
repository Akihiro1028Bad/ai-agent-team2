"""TaskQueue の単体テスト."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.orchestrator.task_queue import (
    Priority,
    TaskQueue,
    TaskRequest,
)


def _make_repo(owner: str = "org", repo: str = "app") -> MagicMock:
    """テスト用の RepoLike モックを生成する。"""
    r = MagicMock()
    r.owner = owner
    r.repo = repo
    return r


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


class TestPriorityOrdering:
    """優先度に基づく取り出し順序をテスト。"""

    async def test_higher_priority_dequeued_first(self) -> None:
        """priority が小さいタスクが先に dequeue される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()

        await tq.enqueue(
            TaskRequest(
                issue_number=1,
                repo=repo,
                phase="hearing",
                priority=Priority.NORMAL,
            )
        )
        await tq.enqueue(
            TaskRequest(
                issue_number=2,
                repo=repo,
                phase="impl_revise",
                priority=Priority.CRITICAL,
            )
        )
        await tq.enqueue(
            TaskRequest(
                issue_number=3,
                repo=repo,
                phase="ci_fix",
                priority=Priority.HIGH,
            )
        )

        first = await tq.dequeue()
        second = await tq.dequeue()
        third = await tq.dequeue()

        assert first.issue_number == 2  # CRITICAL (1)
        assert second.issue_number == 3  # HIGH (2)
        assert third.issue_number == 1  # NORMAL (5)

    async def test_same_priority_fifo(self) -> None:
        """同一優先度では FIFO 順。"""
        tq = TaskQueue(max_total=5, max_per_repo=5)
        repo = _make_repo()

        for i in range(5):
            await tq.enqueue(
                TaskRequest(
                    issue_number=i,
                    repo=repo,
                    phase="hearing",
                    priority=Priority.NORMAL,
                )
            )

        results = []
        for _ in range(5):
            r = await tq.dequeue()
            results.append(r.issue_number)

        assert results == [0, 1, 2, 3, 4]

    async def test_priority_constants(self) -> None:
        """Priority 定数の値が正しい。"""
        assert Priority.CRITICAL == 1
        assert Priority.HIGH == 2
        assert Priority.NORMAL == 5
        assert Priority.LOW == 10
        assert Priority.CRITICAL < Priority.HIGH < Priority.NORMAL < Priority.LOW


# ---------------------------------------------------------------------------
# Concurrency limits
# ---------------------------------------------------------------------------


class TestConcurrencyLimits:
    """Semaphore による同時実行制御をテスト。"""

    async def test_global_semaphore_limits_concurrency(self) -> None:
        """max_total=2 の場合、同時に 2 タスクまでしか実行されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=2)
        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def mock_execute(request: TaskRequest) -> None:
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.05)
            async with lock:
                concurrent_count -= 1

        executor = AsyncMock()
        executor.execute = mock_execute

        # Use different repos so per-repo sem doesn't interfere
        for i in range(5):
            repo = _make_repo("org", f"repo-{i}")
            await tq.enqueue(
                TaskRequest(
                    issue_number=i,
                    repo=repo,
                    phase="hearing",
                )
            )

        workers = [asyncio.create_task(tq.worker_loop(executor)) for _ in range(4)]

        await asyncio.sleep(0.8)

        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        assert max_concurrent <= 2

    async def test_per_repo_semaphore_limits_concurrency(self) -> None:
        """max_per_repo=1 の場合、同一リポジトリのタスクは直列実行される。"""
        tq = TaskQueue(max_total=5, max_per_repo=1)
        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")
        execution_log: list[tuple[str, str, int]] = []

        async def mock_execute(request: TaskRequest) -> None:
            execution_log.append(
                ("start", request.repo_key, request.issue_number)
            )
            await asyncio.sleep(0.05)
            execution_log.append(
                ("end", request.repo_key, request.issue_number)
            )

        executor = AsyncMock()
        executor.execute = mock_execute

        # repo-a に 2 タスク、repo-b に 1 タスク
        await tq.enqueue(
            TaskRequest(issue_number=1, repo=repo_a, phase="hearing")
        )
        await tq.enqueue(
            TaskRequest(issue_number=2, repo=repo_a, phase="design")
        )
        await tq.enqueue(
            TaskRequest(issue_number=3, repo=repo_b, phase="hearing")
        )

        workers = [asyncio.create_task(tq.worker_loop(executor)) for _ in range(3)]

        await asyncio.sleep(1.0)
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        # repo-a の start が 2 つ同時にならないことを検証
        repo_a_starts = [
            (i, e)
            for i, e in enumerate(execution_log)
            if e[0] == "start" and e[1] == "org/repo-a"
        ]
        if len(repo_a_starts) >= 2:
            second_start_idx = repo_a_starts[1][0]
            first_end_idx = next(
                i
                for i, e in enumerate(execution_log)
                if e[0] == "end" and e[1] == "org/repo-a"
            )
            assert first_end_idx < second_start_idx

        # repo-b は repo-a のブロックとは独立に実行される
        repo_b_events = [
            e for e in execution_log if e[1] == "org/repo-b"
        ]
        assert len(repo_b_events) >= 1


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """タスク実行エラー時の挙動をテスト。"""

    async def test_task_error_does_not_crash_worker(self) -> None:
        """タスク実行中のエラーがワーカーをクラッシュさせない。"""
        tq = TaskQueue(max_total=2, max_per_repo=2)
        call_count = 0

        async def mock_execute(request: TaskRequest) -> None:
            nonlocal call_count
            call_count += 1
            if request.issue_number == 1:
                raise RuntimeError("Simulated error")

        executor = AsyncMock()
        executor.execute = mock_execute

        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")
        await tq.enqueue(
            TaskRequest(issue_number=1, repo=repo_a, phase="hearing")
        )
        await tq.enqueue(
            TaskRequest(issue_number=2, repo=repo_b, phase="hearing")
        )

        worker = asyncio.create_task(tq.worker_loop(executor))
        await asyncio.sleep(0.5)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

        assert call_count == 2  # エラー後も 2 番目のタスクが実行される

    async def test_active_count_after_completion(self) -> None:
        """タスク完了後に active_count が正しくデクリメントされる。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)

        async def mock_execute(request: TaskRequest) -> None:
            await asyncio.sleep(0.02)

        executor = AsyncMock()
        executor.execute = mock_execute

        repo = _make_repo()
        await tq.enqueue(
            TaskRequest(issue_number=1, repo=repo, phase="hearing")
        )

        worker = asyncio.create_task(tq.worker_loop(executor))
        await asyncio.sleep(0.3)
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)

        assert tq.active_count == 0


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------


class TestDuplicateHandling:
    """同一 Issue の重複排除をテスト。"""

    async def test_skip_enqueue_for_active_issue(self) -> None:
        """実行中の Issue は重複投入されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()

        # Issue #1 を実行中にする (手動で _active_tasks にセット)
        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[1] = dummy_task

        await tq.enqueue(
            TaskRequest(issue_number=1, repo=repo, phase="hearing")
        )
        assert tq.queued_count == 0  # キューに入らない

        dummy_task.cancel()
        await asyncio.gather(dummy_task, return_exceptions=True)

    async def test_queued_issues_tracked(self) -> None:
        """キューに入った Issue が _queued_issues で追跡される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()

        await tq.enqueue(
            TaskRequest(issue_number=42, repo=repo, phase="hearing")
        )
        assert 42 in tq._queued_issues

        _ = await tq.dequeue()
        assert 42 not in tq._queued_issues


# ---------------------------------------------------------------------------
# Status / cancel
# ---------------------------------------------------------------------------


class TestGetStatus:
    """get_status() の動作をテスト。"""

    async def test_status_reflects_queue_state(self) -> None:
        """ステータスがキュー状態を正しく反映する。"""
        tq = TaskQueue(max_total=3, max_per_repo=2)
        repo = _make_repo()

        await tq.enqueue(
            TaskRequest(issue_number=1, repo=repo, phase="hearing")
        )
        await tq.enqueue(
            TaskRequest(issue_number=2, repo=repo, phase="design")
        )

        status = tq.get_status()
        assert status["active"] == 0
        assert status["max_total"] == 3
        assert status["queued"] == 2

    async def test_cancel_task(self) -> None:
        """実行中タスクをキャンセルできる。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[1] = dummy_task

        result = await tq.cancel_task(1)
        assert result is True

        result = await tq.cancel_task(999)
        assert result is False

        dummy_task.cancel()
        await asyncio.gather(dummy_task, return_exceptions=True)

    async def test_is_issue_active(self) -> None:
        """is_issue_active() が正しく動作する。"""
        tq = TaskQueue()
        assert tq.is_issue_active(1) is False

        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[1] = dummy_task
        assert tq.is_issue_active(1) is True

        dummy_task.cancel()
        await asyncio.gather(dummy_task, return_exceptions=True)


class TestTaskRequest:
    """TaskRequest のテスト。"""

    def test_lt_comparison(self) -> None:
        """__lt__ が priority に基づく比較を行う。"""
        repo = _make_repo()
        high = TaskRequest(issue_number=1, repo=repo, phase="a", priority=1)
        low = TaskRequest(issue_number=2, repo=repo, phase="b", priority=10)
        assert high < low
        assert not low < high

    def test_repo_key(self) -> None:
        """repo_key が owner/repo 形式の文字列を返す。"""
        repo = _make_repo("my-org", "my-repo")
        req = TaskRequest(issue_number=1, repo=repo, phase="hearing")
        assert req.repo_key == "my-org/my-repo"
