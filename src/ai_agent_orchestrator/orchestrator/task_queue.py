"""TaskQueue (asyncio.PriorityQueue + Semaphore).

非同期タスクキュー。asyncio.PriorityQueue で優先度付きタスク管理を行い、
asyncio.Semaphore で全体並行数とリポジトリ単位並行数を制御する。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import IssueKey

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority constants
# ---------------------------------------------------------------------------


class Priority:
    """タスク優先度定数。値が小さいほど優先される。"""

    CRITICAL: int = 1  # レビュー応答 (impl_revise, design_revise)
    HIGH: int = 2  # CI 修正 (ci_fix)
    NORMAL: int = 5  # 新規 Issue, 通常フェーズ実行
    LOW: int = 10  # ヘルスチェック等のバックグラウンド処理


# ---------------------------------------------------------------------------
# Protocols for dependency injection
# ---------------------------------------------------------------------------


@runtime_checkable
class RepoLike(Protocol):
    """Repository-like object with owner and repo attributes."""

    @property
    def owner(self) -> str: ...

    @property
    def repo(self) -> str: ...


class TaskExecutor(Protocol):
    """Protocol for task execution callback."""

    async def execute(self, request: TaskRequest) -> None:
        """Execute a task request."""
        ...


# ---------------------------------------------------------------------------
# TaskRequest dataclass
# ---------------------------------------------------------------------------


@dataclass
class TaskRequest:
    """タスク実行リクエスト。

    asyncio.PriorityQueue で比較可能にするため __lt__ を実装。
    """

    issue_number: int
    repo: Any  # RepoLike (has .owner and .repo)
    phase: str
    priority: int = Priority.NORMAL
    extra: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: TaskRequest) -> bool:
        """PriorityQueue 用の比較。priority が小さいほど優先。"""
        return self.priority < other.priority

    @property
    def repo_key(self) -> str:
        """リポジトリを一意に識別するキー。"""
        return f"{self.repo.owner}/{self.repo.repo}"

    @property
    def issue_key(self) -> IssueKey:
        """リポジトリ横断で Issue を一意に識別するキー。"""
        return (self.repo_key, self.issue_number)


# ---------------------------------------------------------------------------
# TaskQueue
# ---------------------------------------------------------------------------


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
        self._queue: asyncio.PriorityQueue[tuple[int, int, TaskRequest]] = asyncio.PriorityQueue()
        self._global_sem = asyncio.Semaphore(max_total)
        self._repo_sems: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(max_per_repo))
        self._active_tasks: dict[IssueKey, asyncio.Task[None]] = {}
        self._queued_issues: set[IssueKey] = set()  # 重複排除用
        self._queued_tasks: set[tuple[IssueKey, str]] = set()  # (issue_key, phase) 重複排除用

    # --- public methods ---

    async def enqueue(self, request: TaskRequest) -> None:
        """タスクをキューに追加する。

        同一 Issue のタスクが既にキューにある場合は、
        新しいリクエストで置換される (priority が反映される)。
        既に実行中の Issue は重複投入しない。

        Args:
            request: 実行するタスクリクエスト
        """
        ik = request.issue_key
        task_key: tuple[IssueKey, str] = (ik, request.phase)
        if task_key in self._queued_tasks:
            logger.info(
                "Issue #%d phase=%s already queued, skipping duplicate",
                request.issue_number,
                request.phase,
            )
            return

        # 同一Issueが実行中でも、フェーズが変わった場合は
        # 次フェーズのタスクとしてエンキューを許可する
        # (auto-enqueue は _execute_task 完了直前に呼ばれるため)
        if ik in self._active_tasks:
            if ik not in self._queued_issues:
                # 実行中だが未キューイング -> 次フェーズとしてキューに入れる
                logger.info(
                    "Issue #%d is executing, queueing next phase=%s",
                    request.issue_number,
                    request.phase,
                )
            else:
                logger.warning(
                    "Issue #%d is already queued and executing, skipping",
                    request.issue_number,
                )
                return

        if ik in self._queued_issues:
            logger.info(
                "Issue #%d already in queue, will be replaced on dequeue",
                request.issue_number,
            )

        self._queued_issues.add(ik)
        self._queued_tasks.add(task_key)
        self._seq += 1
        await self._queue.put((request.priority, self._seq, request))
        logger.info(
            "Enqueued Issue #%d phase=%s priority=%d",
            request.issue_number,
            request.phase,
            request.priority,
        )
        logger.debug(
            "queue state after enqueue: issue=#%d repo=%s phase=%s depth=%d active=%d",
            request.issue_number,
            request.repo_key,
            request.phase,
            self._queue.qsize(),
            len(self._active_tasks),
        )

    async def dequeue(self) -> TaskRequest:
        """キューからタスクを取り出す。

        キューが空の場合はタスクが追加されるまでブロックする。

        Returns:
            最も優先度の高い TaskRequest
        """
        _, _, request = await self._queue.get()
        self._queued_issues.discard(request.issue_key)
        logger.debug(
            "dequeued: issue=#%d repo=%s phase=%s remaining=%d",
            request.issue_number,
            request.repo_key,
            request.phase,
            self._queue.qsize(),
        )
        # _queued_tasks はタスク完了時に除去する (実行中の重複防止)
        return request

    async def worker_loop(self, executor: TaskExecutor) -> None:
        """ワーカーループ: キューからタスクを取り出して実行する。

        全体セマフォ (global_sem) とリポジトリ単位セマフォ (repo_sem) の
        両方を取得してから executor.execute() を呼び出す。

        このメソッドは無限ループであり、通常は asyncio.TaskGroup 内で実行される。

        Note:
            task_done() は dequeue 後に必ず呼び出す (finally ブロック)。

            head-of-line blocking 対策: global_sem を先に取得し、
            repo_sem が取得できなければ global_sem を解放してリトライする。

        Args:
            executor: フェーズ実行エンジン
        """
        while True:
            _priority, _seq, request = await self._queue.get()
            try:
                self._queued_issues.discard(request.issue_key)
                # _queued_tasks はデキュー時に除去しない (実行中の重複防止)
                await self._try_execute(executor, request)
            except Exception as e:
                logger.error(
                    "Task failed for Issue #%d: %s",
                    request.issue_number,
                    e,
                )
            finally:
                self._queued_tasks.discard((request.issue_key, request.phase))
                self._active_tasks.pop(request.issue_key, None)
                self._queue.task_done()  # always called after get()

    async def _try_execute(
        self,
        executor: TaskExecutor,
        request: TaskRequest,
    ) -> None:
        """タスク実行を試みる。

        head-of-line blocking 対策:
        1. global_sem を取得
        2. repo_sem を非ブロッキングで試行
        3. 取得できなければ global_sem を解放してキューに戻す
        """
        repo_key = request.repo_key
        repo_sem = self._repo_sems[repo_key]

        await self._global_sem.acquire()
        global_sem_held = True
        try:
            # repo_sem を非ブロッキングで試行 (locked() は公開 API)
            if repo_sem.locked():
                # global_sem を解放して再キューイング
                self._global_sem.release()
                global_sem_held = False
                logger.info(
                    "Repo semaphore busy for %s, re-enqueuing Issue #%d",
                    repo_key,
                    request.issue_number,
                )
                await asyncio.sleep(5)
                self._seq += 1
                await self._queue.put((request.priority, self._seq, request))
                self._queued_issues.add(request.issue_key)
                return

            await repo_sem.acquire()
            try:
                logger.debug(
                    "acquired semaphores (global+repo[%s]): executing issue=#%d phase=%s",
                    repo_key,
                    request.issue_number,
                    request.phase,
                )
                task = asyncio.current_task()
                if task is not None:
                    self._active_tasks[request.issue_key] = task
                await self._execute_task(executor, request)
            finally:
                repo_sem.release()
        finally:
            if global_sem_held:
                self._global_sem.release()

    async def _execute_task(
        self,
        executor: TaskExecutor,
        request: TaskRequest,
    ) -> None:
        """タスクを実行する。

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

    @property
    def active_count(self) -> int:
        """現在実行中のタスク数。"""
        return len(self._active_tasks)

    @property
    def queued_count(self) -> int:
        """キュー待ちのタスク数。"""
        return self._queue.qsize()

    def get_status(self) -> dict[str, Any]:
        """キューの状態を辞書形式で返す。

        Returns:
            {"active": int, "max_total": int, "queued": int,
             "active_issues": list[IssueKey]}
        """
        return {
            "active": self.active_count,
            "max_total": self._max_total,
            "queued": self.queued_count,
            "active_issues": list(self._active_tasks.keys()),
        }

    def is_issue_active(self, issue_key: IssueKey) -> bool:
        """指定 Issue が現在実行中かどうかを返す。"""
        return issue_key in self._active_tasks

    def is_task_queued(self, issue_key: IssueKey, phase: str) -> bool:
        """指定 Issue + phase がキューまたは実行中かどうかを返す。"""
        return (issue_key, phase) in self._queued_tasks

    async def cancel_task(self, issue_key: IssueKey) -> bool:
        """実行中のタスクをキャンセルする。

        Args:
            issue_key: キャンセルする IssueKey (repo, issue_number)

        Returns:
            キャンセルに成功した場合 True
        """
        task = self._active_tasks.get(issue_key)
        if task and not task.done():
            task.cancel()
            logger.info("Cancelled task for Issue #%d (%s)", issue_key[1], issue_key[0])
            return True
        return False
