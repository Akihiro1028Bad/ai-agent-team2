# 実装仕様書: TaskQueue

**対象モジュール**: `src/ai_agent_orchestrator/orchestrator/task_queue.py`

---

## 1. 概要

非同期タスクキュー。`asyncio.PriorityQueue` で優先度付きタスク管理を行い、
`asyncio.Semaphore` で全体並行数 (max_total) とリポジトリ単位並行数 (max_per_repo) を制御する。
レビュー応答は高優先度 (priority=1)、新規 Issue は通常優先度 (priority=5) として処理順序を最適化する。

---

## 2. 依存パッケージ

```
# 標準ライブラリのみ
asyncio
```

---

## 3. Imports

```python
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.orchestrator.state_machine import Phase
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.phases.executor import PhaseExecutor

logger = logging.getLogger(__name__)
```

---

## 4. 優先度レベル定義

```python
class Priority:
    """タスク優先度定数。値が小さいほど優先される。"""

    CRITICAL = 1       # レビュー応答 (impl_revise, design_revise)
    HIGH = 2           # CI 修正 (ci_fix)
    NORMAL = 5         # 新規 Issue, 通常フェーズ実行
    LOW = 10           # ヘルスチェック等のバックグラウンド処理
```

---

## 5. TaskRequest データクラス

```python
@dataclass
class TaskRequest:
    """タスク実行リクエスト。

    asyncio.PriorityQueue で比較可能にするため __lt__ を実装。
    """

    issue_number: int
    repo: RepositoryConfig
    phase: Phase | str
    priority: int = Priority.NORMAL
    extra: dict = field(default_factory=dict)

    def __lt__(self, other: TaskRequest) -> bool:
        """PriorityQueue 用の比較。priority が小さいほど優先。"""
        return self.priority < other.priority

    @property
    def repo_key(self) -> str:
        """リポジトリを一意に識別するキー。"""
        return f"{self.repo.owner}/{self.repo.repo}"
```

---

## 6. TaskQueue クラス

### 6.1 クラス定義

```python
class TaskQueue:
    """asyncio.PriorityQueue + Semaphore による同時実行制御付きタスクキュー。

    - 全体の同時実行数を global_sem で制限 (デフォルト: 2)
    - リポジトリ単位の同時実行数を repo_sems で制限 (デフォルト: 1)
    - 同一 Issue 番号のタスクは重複排除 (最新のみ保持)
    """

    def __init__(
        self,
        max_total: int = 2,
        max_per_repo: int = 1,
    ) -> None:
        """TaskQueue を初期化する。

        Args:
            max_total: 全体の最大同時実行数
            max_per_repo: リポジトリ単位の最大同時実行数
        """
        self._max_total = max_total
        self._max_per_repo = max_per_repo
        self._seq = 0  # FIFO 保証用シーケンスカウンタ
        self._queue: asyncio.PriorityQueue[tuple[int, int, TaskRequest]] = (
            asyncio.PriorityQueue()
        )
        self._global_sem = asyncio.Semaphore(max_total)
        self._repo_sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(max_per_repo)
        )
        self._active_tasks: dict[int, asyncio.Task] = {}
        self._queued_issues: set[int] = set()  # 重複排除用
```

### 6.2 公開メソッド

```python
    async def enqueue(self, request: TaskRequest) -> None:
        """タスクをキューに追加する。

        同一 Issue 番号のタスクが既にキューにある場合は、
        新しいリクエストで置換される (priority が反映される)。
        既に実行中の Issue は重複投入しない。

        Args:
            request: 実行するタスクリクエスト

        Note:
            PriorityQueue は (priority, seq, request) の 3-tuple で管理。
            priority 値が小さいほど先に dequeue される。
            同一 priority の場合は seq (投入順) で FIFO を保証する。
        """
        if request.issue_number in self._active_tasks:
            logger.warning(
                "Issue #%d is already executing, skipping enqueue",
                request.issue_number,
            )
            return

        if request.issue_number in self._queued_issues:
            logger.info(
                "Issue #%d already in queue, will be replaced on dequeue",
                request.issue_number,
            )

        self._queued_issues.add(request.issue_number)
        self._seq += 1
        await self._queue.put((request.priority, self._seq, request))
        logger.info(
            "Enqueued Issue #%d phase=%s priority=%d",
            request.issue_number,
            request.phase,
            request.priority,
        )

    async def dequeue(self) -> TaskRequest:
        """キューからタスクを取り出す。

        キューが空の場合はタスクが追加されるまでブロックする。

        Returns:
            最も優先度の高い TaskRequest
        """
        _, _, request = await self._queue.get()
        self._queued_issues.discard(request.issue_number)
        return request

    async def worker_loop(self, executor: PhaseExecutor) -> None:
        """ワーカーループ: キューからタスクを取り出して実行する。

        全体セマフォ (global_sem) とリポジトリ単位セマフォ (repo_sem) の
        両方を取得してから PhaseExecutor.execute() を呼び出す。

        このメソッドは無限ループであり、通常は asyncio.TaskGroup 内で実行される。

        Note:
            task_done() は dequeue 後に必ず呼び出す (finally ブロック)。
            セマフォ取得のブロック中に task_done() が呼ばれない問題を防ぐ。

            head-of-line blocking 対策: repo_sem が取得できない場合でも
            global_sem を長時間保持しないよう、global_sem を先に取得し、
            repo_sem が取得できなければ global_sem を解放してリトライする。

        Args:
            executor: フェーズ実行エンジン
        """
        while True:
            priority, seq, request = await self._queue.get()
            try:
                await self._try_execute(executor, request)
            except Exception as e:
                logger.error(
                    "Task failed for Issue #%d: %s",
                    request.issue_number,
                    e,
                )
            finally:
                self._active_tasks.pop(request.issue_number, None)
                self._queue.task_done()  # always called after get()

    async def _try_execute(
        self,
        executor: PhaseExecutor,
        request: TaskRequest,
    ) -> None:
        """タスク実行を試みる。repo_sem が取得できない場合は再キューイングする。"""
        repo_key = request.repo_key
        repo_sem = self._repo_sems[repo_key]

        # repo_sem を非ブロッキングで試行
        try:
            async with asyncio.timeout(0.1):
                async with repo_sem:
                    async with self._global_sem:
                        task = asyncio.create_task(
                            self._execute_task(executor, request),
                            name=f"issue-{request.issue_number}-{request.phase}",
                        )
                        self._active_tasks[request.issue_number] = task
                        await task
        except TimeoutError:
            # repo_sem が取れない場合は再キューイング（少し待ってから）
            logger.info(
                "Repo semaphore busy for %s, re-enqueuing Issue #%d",
                repo_key,
                request.issue_number,
            )
            await asyncio.sleep(1.0)
            await self.enqueue(request)

    @property
    def active_count(self) -> int:
        """現在実行中のタスク数。"""
        return len(self._active_tasks)

    @property
    def queued_count(self) -> int:
        """キュー待ちのタスク数。"""
        return self._queue.qsize()

    def get_status(self) -> dict:
        """キューの状態を辞書形式で返す。

        Returns:
            {"active": int, "max_total": int, "queued": int,
             "active_issues": list[int]}
        """
        return {
            "active": self.active_count,
            "max_total": self._max_total,
            "queued": self.queued_count,
            "active_issues": list(self._active_tasks.keys()),
        }

    def is_issue_active(self, issue_number: int) -> bool:
        """指定 Issue が現在実行中かどうかを返す。"""
        return issue_number in self._active_tasks

    async def cancel_task(self, issue_number: int) -> bool:
        """実行中のタスクをキャンセルする。

        Args:
            issue_number: キャンセルする Issue 番号

        Returns:
            キャンセルに成功した場合 True
        """
        task = self._active_tasks.get(issue_number)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled task for Issue #%d", issue_number)
            return True
        return False
```

### 6.3 内部メソッド

```python
    async def _execute_task(
        self,
        executor: PhaseExecutor,
        request: TaskRequest,
    ) -> None:
        """タスクを実行する (エラーハンドリングは executor 内で行う)。

        Args:
            executor: フェーズ実行エンジン
            request: 実行するタスクリクエスト
        """
        logger.info(
            "Executing Issue #%d phase=%s",
            request.issue_number,
            request.phase,
        )
        await executor.execute(request)
        logger.info(
            "Completed Issue #%d phase=%s",
            request.issue_number,
            request.phase,
        )
```

---

## 7. 優先度運用ルール

| シナリオ | priority 値 | 理由 |
|---------|------------|------|
| レビュー応答 (impl_revise, design_revise) | `Priority.CRITICAL = 1` | 人間が待っているため最優先 |
| CI 修正 (ci_fix) | `Priority.HIGH = 2` | PR がブロックされているため高優先 |
| 新規 Issue (type_detection, hearing) | `Priority.NORMAL = 5` | 通常のタスク |
| 方針承認後の実行 (implement, fix) | `Priority.NORMAL = 5` | 通常のタスク |

---

## 8. テストケース

**テストファイル**: `tests/unit/orchestrator/test_task_queue.py`

### 8.1 優先度順序テスト

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.orchestrator.task_queue import (
    TaskQueue,
    TaskRequest,
    Priority,
)


def _make_repo(owner: str = "org", repo: str = "app") -> MagicMock:
    r = MagicMock()
    r.owner = owner
    r.repo = repo
    return r


class TestPriorityOrdering:
    """優先度に基づく取り出し順序をテスト。"""

    @pytest.mark.asyncio
    async def test_higher_priority_dequeued_first(self):
        """priority が小さいタスクが先に dequeue される。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()

        await tq.enqueue(TaskRequest(
            issue_number=1, repo=repo, phase="hearing", priority=Priority.NORMAL,
        ))
        await tq.enqueue(TaskRequest(
            issue_number=2, repo=repo, phase="impl_revise", priority=Priority.CRITICAL,
        ))
        await tq.enqueue(TaskRequest(
            issue_number=3, repo=repo, phase="ci_fix", priority=Priority.HIGH,
        ))

        first = await tq.dequeue()
        second = await tq.dequeue()
        third = await tq.dequeue()

        assert first.issue_number == 2    # CRITICAL (1)
        assert second.issue_number == 3   # HIGH (2)
        assert third.issue_number == 1    # NORMAL (5)

    @pytest.mark.asyncio
    async def test_same_priority_fifo(self):
        """同一優先度では FIFO 順。"""
        tq = TaskQueue(max_total=5, max_per_repo=5)
        repo = _make_repo()

        for i in range(5):
            await tq.enqueue(TaskRequest(
                issue_number=i, repo=repo, phase="hearing", priority=Priority.NORMAL,
            ))

        results = []
        for _ in range(5):
            r = await tq.dequeue()
            results.append(r.issue_number)

        assert results == [0, 1, 2, 3, 4]
```

### 8.2 並行制御テスト

```python
class TestConcurrencyLimits:
    """Semaphore による同時実行制御をテスト。"""

    @pytest.mark.asyncio
    async def test_global_semaphore_limits_concurrency(self):
        """max_total=2 の場合、同時に 2 タスクまでしか実行されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=2)
        concurrent_count = 0
        max_concurrent = 0
        lock = asyncio.Lock()

        async def mock_execute(request):
            nonlocal concurrent_count, max_concurrent
            async with lock:
                concurrent_count += 1
                max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.1)
            async with lock:
                concurrent_count -= 1

        executor = AsyncMock()
        executor.execute = mock_execute

        repo = _make_repo()
        for i in range(5):
            await tq.enqueue(TaskRequest(
                issue_number=i, repo=repo, phase="hearing",
            ))

        # ワーカーを 4 つ起動
        workers = [
            asyncio.create_task(tq.worker_loop(executor))
            for _ in range(4)
        ]

        await asyncio.sleep(0.5)

        for w in workers:
            w.cancel()

        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_per_repo_semaphore_limits_concurrency(self):
        """max_per_repo=1 の場合、同一リポジトリのタスクは直列実行される。"""
        tq = TaskQueue(max_total=5, max_per_repo=1)
        repo_a = _make_repo("org", "repo-a")
        repo_b = _make_repo("org", "repo-b")
        execution_log = []

        async def mock_execute(request):
            execution_log.append(("start", request.repo_key, request.issue_number))
            await asyncio.sleep(0.1)
            execution_log.append(("end", request.repo_key, request.issue_number))

        executor = AsyncMock()
        executor.execute = mock_execute

        # repo-a に 2 タスク、repo-b に 1 タスク
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo_a, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo_a, phase="design"))
        await tq.enqueue(TaskRequest(issue_number=3, repo=repo_b, phase="hearing"))

        workers = [
            asyncio.create_task(tq.worker_loop(executor))
            for _ in range(3)
        ]

        await asyncio.sleep(0.5)
        for w in workers:
            w.cancel()

        # repo-a の start が 2 つ同時にならないことを検証
        repo_a_starts = [
            (i, e) for i, e in enumerate(execution_log)
            if e[0] == "start" and e[1] == "org/repo-a"
        ]
        if len(repo_a_starts) >= 2:
            first_start_idx = repo_a_starts[0][0]
            second_start_idx = repo_a_starts[1][0]
            # 2 番目の start の前に 1 番目の end がある
            first_end_idx = next(
                i for i, e in enumerate(execution_log)
                if e[0] == "end" and e[1] == "org/repo-a"
            )
            assert first_end_idx < second_start_idx
```

### 8.3 エラーハンドリングテスト

```python
class TestErrorHandling:
    """タスク実行エラー時の挙動をテスト。"""

    @pytest.mark.asyncio
    async def test_task_error_does_not_crash_worker(self):
        """タスク実行中のエラーがワーカーをクラッシュさせない。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        call_count = 0

        async def mock_execute(request):
            nonlocal call_count
            call_count += 1
            if request.issue_number == 1:
                raise RuntimeError("Simulated error")

        executor = AsyncMock()
        executor.execute = mock_execute

        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="hearing"))

        worker = asyncio.create_task(tq.worker_loop(executor))
        await asyncio.sleep(0.3)
        worker.cancel()

        assert call_count == 2  # エラー後も 2 番目のタスクが実行される

    @pytest.mark.asyncio
    async def test_active_count_after_completion(self):
        """タスク完了後に active_count が正しくデクリメントされる。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)

        async def mock_execute(request):
            await asyncio.sleep(0.05)

        executor = AsyncMock()
        executor.execute = mock_execute

        repo = _make_repo()
        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))

        worker = asyncio.create_task(tq.worker_loop(executor))
        await asyncio.sleep(0.2)
        worker.cancel()

        assert tq.active_count == 0
```

### 8.4 重複排除テスト

```python
class TestDuplicateHandling:
    """同一 Issue の重複排除をテスト。"""

    @pytest.mark.asyncio
    async def test_skip_enqueue_for_active_issue(self):
        """実行中の Issue は重複投入されない。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        repo = _make_repo()

        # Issue #1 を実行中にする (手動で _active_tasks にセット)
        tq._active_tasks[1] = asyncio.create_task(asyncio.sleep(10))

        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))
        assert tq.queued_count == 0  # キューに入らない

        tq._active_tasks[1].cancel()
```

### 8.5 ステータス取得テスト

```python
class TestGetStatus:
    """get_status() の動作をテスト。"""

    @pytest.mark.asyncio
    async def test_status_reflects_queue_state(self):
        """ステータスがキュー状態を正しく反映する。"""
        tq = TaskQueue(max_total=3, max_per_repo=2)
        repo = _make_repo()

        await tq.enqueue(TaskRequest(issue_number=1, repo=repo, phase="hearing"))
        await tq.enqueue(TaskRequest(issue_number=2, repo=repo, phase="design"))

        status = tq.get_status()
        assert status["active"] == 0
        assert status["max_total"] == 3
        assert status["queued"] == 2

    @pytest.mark.asyncio
    async def test_cancel_task(self):
        """実行中タスクをキャンセルできる。"""
        tq = TaskQueue(max_total=2, max_per_repo=1)
        tq._active_tasks[1] = asyncio.create_task(asyncio.sleep(10))

        result = await tq.cancel_task(1)
        assert result is True

        result = await tq.cancel_task(999)
        assert result is False
```
