"""TaskQueue の単体テスト."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.orchestrator.task_queue import (
    Priority,
    TaskQueue,
    TaskRequest,
)

if TYPE_CHECKING:
    import pytest


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
            execution_log.append(("start", request.repo_key, request.issue_number))
            await asyncio.sleep(0.05)
            execution_log.append(("end", request.repo_key, request.issue_number))

        executor = AsyncMock()
        executor.execute = mock_execute

        # repo-a に 2 タスク、repo-b に 1 タスク
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo_a, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo_a, phase="design"))
        await tq.enqueue(TaskRequest(issue_number=3, repo=repo_b, phase="hearing"))

        workers = [asyncio.create_task(tq.worker_loop(executor)) for _ in range(3)]

        await asyncio.sleep(1.0)
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        # repo-a の start が 2 つ同時にならないことを検証
        repo_a_starts = [(i, e) for i, e in enumerate(execution_log) if e[0] == "start" and e[1] == "org/repo-a"]
        if len(repo_a_starts) >= 2:
            second_start_idx = repo_a_starts[1][0]
            first_end_idx = next(i for i, e in enumerate(execution_log) if e[0] == "end" and e[1] == "org/repo-a")
            assert first_end_idx < second_start_idx

        # repo-b は repo-a のブロックとは独立に実行される
        repo_b_events = [e for e in execution_log if e[1] == "org/repo-b"]
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
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo_a, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo_b, phase="hearing"))

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
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))

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

    async def test_next_phase_enqueue_for_active_issue(self) -> None:
        """実行中でも次フェーズはキューに入り、2回目はスキップ。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        issue_key = ("org/app", 1)

        # Issue #1 を実行中にする
        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[issue_key] = dummy_task

        # 1回目: 次フェーズとしてキューに入る
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))
        assert tq.queued_count == 1

        # 2回目: 既にキュー済みなのでスキップ
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="design"))
        assert tq.queued_count == 1

        dummy_task.cancel()
        await asyncio.gather(dummy_task, return_exceptions=True)

    async def test_queued_issues_tracked(self) -> None:
        """キューに入った Issue が _queued_issues で追跡される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        issue_key = ("org/app", 42)

        await tq.enqueue(TaskRequest(issue_number=42, repo=repo, phase="hearing"))
        assert issue_key in tq._queued_issues

        _ = await tq.dequeue()
        assert issue_key not in tq._queued_issues


# ---------------------------------------------------------------------------
# Status / cancel
# ---------------------------------------------------------------------------


class TestGetStatus:
    """get_status() の動作をテスト。"""

    async def test_status_reflects_queue_state(self) -> None:
        """ステータスがキュー状態を正しく反映する。"""
        tq = TaskQueue(max_total=3, max_per_repo=2)
        repo = _make_repo()

        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="design"))

        status = tq.get_status()
        assert status["active"] == 0
        assert status["max_total"] == 3
        assert status["queued"] == 2

    async def test_cancel_task(self) -> None:
        """実行中タスクをキャンセルできる。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        issue_key = ("org/app", 1)
        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[issue_key] = dummy_task

        result = await tq.cancel_task(issue_key)
        assert result is True

        result = await tq.cancel_task(("org/app", 999))
        assert result is False

        dummy_task.cancel()
        await asyncio.gather(dummy_task, return_exceptions=True)

    async def test_is_issue_active(self) -> None:
        """is_issue_active() が正しく動作する。"""
        tq = TaskQueue()
        issue_key = ("org/app", 1)
        assert tq.is_issue_active(issue_key) is False

        dummy_task = asyncio.create_task(asyncio.sleep(10))
        tq._active_tasks[issue_key] = dummy_task
        assert tq.is_issue_active(issue_key) is True

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


class TestQueueLifecycleLogging:
    """エンキュー/デキューのライフサイクル DEBUG ログのテスト。"""

    async def test_enqueue_logs_debug_with_depth(self, caplog: pytest.LogCaptureFixture) -> None:
        """エンキュー時にキュー深さを含む DEBUG ログを出す。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.orchestrator.task_queue"):
            await tq.enqueue(TaskRequest(issue_number=42, repo=repo, phase="hearing"))

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "42" in debug_text
        assert "depth" in debug_text.lower()

    async def test_dequeue_logs_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        """デキュー時に DEBUG ログを出す。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=7, repo=repo, phase="design"))
        with caplog.at_level(logging.DEBUG, logger="ai_agent_orchestrator.orchestrator.task_queue"):
            await tq.dequeue()

        debug_text = "\n".join(r.message for r in caplog.records if r.levelno == logging.DEBUG)
        assert "7" in debug_text
        assert "dequeue" in debug_text.lower()


# ---------------------------------------------------------------------------
# ControlBus: pause / resume / drain (#87)
# ---------------------------------------------------------------------------


class _RecordingExecutor:
    """execute された TaskRequest を記録し、呼び出しを Event で通知する。"""

    def __init__(self) -> None:
        self.calls: list[TaskRequest] = []
        self.event = asyncio.Event()

    async def execute(self, request: TaskRequest) -> None:
        self.calls.append(request)
        self.event.set()


async def _cancel(task: asyncio.Task[None]) -> None:
    import contextlib

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class TestPauseResumeDrain:
    """pause/resume(park 方式) と drain の挙動。"""

    async def test_paused_issue_is_parked_then_resumed(self) -> None:
        """pause 中はフェーズを実行せず park、resume で再エンキュー → 実行される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=5, repo=repo, phase="implement", priority=Priority.NORMAL)

        tq.pause(req.issue_key)
        assert tq.is_paused(req.issue_key)

        ex = _RecordingExecutor()
        await tq.enqueue(req)
        worker = asyncio.create_task(tq.worker_loop(ex))
        try:
            await asyncio.sleep(0.05)
            # pause 中 → 実行されず park される
            assert ex.calls == []

            # resume すると再エンキューされ実行される
            await tq.resume(req.issue_key)
            assert not tq.is_paused(req.issue_key)
            await asyncio.wait_for(ex.event.wait(), timeout=1.0)
            assert [r.issue_number for r in ex.calls] == [5]
        finally:
            await _cancel(worker)

    async def test_drain_stops_worker_without_executing(self) -> None:
        """drain 中のワーカーは新規タスクを実行せずループを抜ける。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=9, repo=repo, phase="implement", priority=Priority.NORMAL)

        tq.request_drain()
        assert tq.is_draining

        ex = _RecordingExecutor()
        await tq.enqueue(req)
        worker = asyncio.create_task(tq.worker_loop(ex))
        try:
            await asyncio.sleep(0.05)
            assert ex.calls == []  # drain → 実行されない
            assert worker.done()  # ワーカーは自然終了
        finally:
            await _cancel(worker)

    async def test_discard_control_state_prevents_resume_resurrection(self) -> None:
        """abort 相当: pause/park を破棄すると resume しても再実行されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=11, repo=repo, phase="implement", priority=Priority.NORMAL)

        tq.pause(req.issue_key)
        ex = _RecordingExecutor()
        await tq.enqueue(req)
        worker = asyncio.create_task(tq.worker_loop(ex))
        try:
            await asyncio.sleep(0.05)
            assert ex.calls == []  # park 済み

            tq.mark_aborted(req.issue_key)  # abort 相当
            assert not tq.is_paused(req.issue_key)

            await tq.resume(req.issue_key)
            await asyncio.sleep(0.05)
            assert ex.calls == []  # park 破棄済み → 復活しない
        finally:
            await _cancel(worker)

    async def test_aborted_issue_queued_task_is_dropped(self) -> None:
        """キュー滞留中に abort された Issue は dequeue 時に破棄され実行されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=13, repo=repo, phase="implement", priority=Priority.NORMAL)

        await tq.enqueue(req)  # 先にキューへ滞留させる
        tq.mark_aborted(req.issue_key)  # 実行前に abort

        ex = _RecordingExecutor()
        worker = asyncio.create_task(tq.worker_loop(ex))
        try:
            await asyncio.sleep(0.05)
            assert ex.calls == []  # abort 済み → 実行されず破棄
        finally:
            await _cancel(worker)

    async def test_reenqueue_clears_abort(self) -> None:
        """abort 後に再エンキューすると abort ドロップが解除され実行される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=14, repo=repo, phase="implement", priority=Priority.NORMAL)

        tq.mark_aborted(req.issue_key)
        ex = _RecordingExecutor()
        await tq.enqueue(req)  # 再アクティブ化 → abort 解除

        worker = asyncio.create_task(tq.worker_loop(ex))
        try:
            await asyncio.wait_for(ex.event.wait(), timeout=1.0)
            assert [r.issue_number for r in ex.calls] == [14]
        finally:
            await _cancel(worker)


# ---------------------------------------------------------------------------
# キュー可視化スナップショット (#96)
# ---------------------------------------------------------------------------


class TestQueueSnapshot:
    """get_queue_snapshot のメタデータと並び順。"""

    async def test_snapshot_lists_queued_sorted_with_metadata(self) -> None:
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="implement", priority=Priority.NORMAL))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="plan", priority=Priority.CRITICAL))

        snap = tq.get_queue_snapshot()
        assert snap["max_total"] == 2
        assert snap["max_per_repo"] == 1
        q = snap["queued"]
        assert len(q) == 2
        # CRITICAL(1) が先頭
        assert q[0]["issue_number"] == 2
        assert q[0]["phase"] == "plan"
        assert q[1]["issue_number"] == 1
        for entry in q:
            assert {"repo", "issue_number", "phase", "priority", "enqueued_at", "wait_reason"} <= set(entry)
            assert entry["wait_reason"] == "queued"

    async def test_dequeue_removes_from_snapshot(self) -> None:
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=7, repo=repo, phase="implement"))
        assert len(tq.get_queue_snapshot()["queued"]) == 1
        await tq.dequeue()
        assert tq.get_queue_snapshot()["queued"] == []

    async def test_abort_removes_queued_meta(self) -> None:
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()
        req = TaskRequest(issue_number=8, repo=repo, phase="implement")
        await tq.enqueue(req)
        tq.mark_aborted(req.issue_key)
        assert tq.get_queue_snapshot()["queued"] == []


# ---------------------------------------------------------------------------
# set_priority / reorder (#96 Unit C)
# ---------------------------------------------------------------------------


class TestSetPriorityReorder:
    async def test_set_priority_changes_dequeue_order(self) -> None:
        tq = TaskQueue(max_total=1, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="a", priority=Priority.NORMAL))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="b", priority=Priority.NORMAL))
        # 同 priority → FIFO で #1 が先。#2 を CRITICAL に引き上げる
        changed = tq.set_priority(("org/app", 2), "b", Priority.CRITICAL)
        assert changed
        first = await tq.dequeue()
        assert first.issue_number == 2
        assert first.priority == Priority.CRITICAL

    async def test_set_priority_updates_snapshot(self) -> None:
        tq = TaskQueue(max_total=1, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=5, repo=repo, phase="implement", priority=Priority.NORMAL))
        tq.set_priority(("org/app", 5), "implement", Priority.HIGH)
        entry = tq.get_queue_snapshot()["queued"][0]
        assert entry["priority"] == Priority.HIGH

    async def test_set_priority_unknown_returns_false(self) -> None:
        tq = TaskQueue(max_total=1, max_per_repo=1)
        assert tq.set_priority(("org/app", 99), "x", Priority.CRITICAL) is False

    async def test_reorder_assigns_sequential_priority(self) -> None:
        tq = TaskQueue(max_total=1, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="a", priority=Priority.NORMAL))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="b", priority=Priority.NORMAL))
        await tq.enqueue(TaskRequest(issue_number=3, repo=repo, phase="c", priority=Priority.NORMAL))
        # 希望順: 3 → 1 → 2
        tq.reorder([(("org/app", 3), "c"), (("org/app", 1), "a"), (("org/app", 2), "b")])
        order = [(await tq.dequeue()).issue_number for _ in range(3)]
        assert order == [3, 1, 2]

    async def test_reorder_ignores_unknown_entries(self) -> None:
        tq = TaskQueue(max_total=1, max_per_repo=1)
        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="a", priority=Priority.NORMAL))
        # 未知エントリのみ → 何もしない (例外を出さない)
        tq.reorder([(("org/app", 99), "z")])
        first = await tq.dequeue()
        assert first.issue_number == 1
