"""TaskQueue (asyncio.PriorityQueue + Semaphore).

非同期タスクキュー。asyncio.PriorityQueue で優先度付きタスク管理を行い、
asyncio.Semaphore で全体並行数とリポジトリ単位並行数を制御する。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
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
# TaskRequest (U5 #83 で models.TaskRequest に一本化。後方互換 re-export)
# ---------------------------------------------------------------------------

from ai_agent_orchestrator.models import TaskRequest  # noqa: E402

__all__ = ["Priority", "TaskQueue", "TaskRequest"]


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
        # ControlBus (#87): pause された Issue とその退避タスク、drain フラグ、
        # abort された Issue (キュー滞留分も実行させないためのドロップ集合)
        self._paused: set[IssueKey] = set()
        self._parked: dict[IssueKey, TaskRequest] = {}
        self._draining = False
        self._aborted: set[IssueKey] = set()
        # キュー可視化用メタ (#96): (issue_key, phase) → {repo, issue_number, phase,
        # priority, enqueued_at, wait_reason}。queue.json / GET /api/queue の真実源。
        self._queued_meta: dict[tuple[IssueKey, str], dict[str, Any]] = {}

    # --- public methods ---

    async def enqueue(self, request: TaskRequest) -> bool:
        """タスクをキューに追加する。

        同一 Issue のタスクが既にキューにある場合は、
        新しいリクエストで置換される (priority が反映される)。
        既に実行中の Issue は重複投入しない。

        Args:
            request: 実行するタスクリクエスト

        Returns:
            キューに追加された場合 True、重複スキップされた場合 False。
            呼び出し側はこの戻り値で「タスクが実際に積まれたか」を判定できる
            (False を無視して処理済み扱いにすると、そのタスクの内容が失われる)。
        """
        ik = request.issue_key
        # 新規に積まれた = Issue が再びアクティブ化された → abort ドロップを解除する。
        self._aborted.discard(ik)
        task_key: tuple[IssueKey, str] = (ik, request.phase)
        if task_key in self._queued_tasks:
            logger.info(
                "Issue #%d phase=%s already queued, skipping duplicate",
                request.issue_number,
                request.phase,
            )
            return False

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
                return False

        if ik in self._queued_issues:
            logger.info(
                "Issue #%d already in queue, will be replaced on dequeue",
                request.issue_number,
            )

        self._queued_issues.add(ik)
        self._queued_tasks.add(task_key)
        self._record_queued_meta(request, "queued")
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
        return True

    async def dequeue(self) -> TaskRequest:
        """キューからタスクを取り出す。

        キューが空の場合はタスクが追加されるまでブロックする。

        Returns:
            最も優先度の高い TaskRequest
        """
        _, _, request = await self._queue.get()
        self._queued_issues.discard(request.issue_key)
        self._queued_meta.pop((request.issue_key, request.phase), None)
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
            # drain 中は新規タスクを拾わずワーカーを自然終了させる
            # (#87 graceful shutdown: 実行中フェーズは完走、新規は開始しない)。
            if self._draining:
                return
            _priority, _seq, request = await self._queue.get()
            try:
                self._queued_issues.discard(request.issue_key)
                # abort 済み Issue は、キュー滞留していた分も実行せず破棄する
                # (SUSPENDED から復活して走るのを防ぐ。再エンキューで解除される)。
                if request.issue_key in self._aborted:
                    self._queued_meta.pop((request.issue_key, request.phase), None)
                    logger.info(
                        "Issue #%d is aborted, dropping queued phase=%s",
                        request.issue_number,
                        request.phase,
                    )
                    continue
                # pause 中の Issue は実行せず park する (フェーズ境界で graceful に停止)。
                # resume で再エンキューされるまで待機。実行中フェーズは中断しない。
                if request.issue_key in self._paused:
                    self._parked[request.issue_key] = request
                    self._queued_meta.pop((request.issue_key, request.phase), None)
                    logger.info(
                        "Issue #%d is paused, parking phase=%s",
                        request.issue_number,
                        request.phase,
                    )
                    continue
                # drain がデキュー後に立った場合はキューへ戻してワーカーを終了する
                # (continue だと先頭の drain 判定まで戻るだけ。return で確実に退場)。
                # 注: finally が再投入分の _queued_tasks を discard するため dedup 集合と
                # 実キュー内容が一時的に乖離するが、drain は終端処理なので実害はない。
                if self._draining:
                    self._seq += 1
                    await self._queue.put((_priority, self._seq, request))
                    self._queued_issues.add(request.issue_key)
                    return
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
                self._record_queued_meta(request, "repo_busy")
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
                # 実行開始 = キュー待ちではなくなる。
                self._queued_meta.pop((request.issue_key, request.phase), None)
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

    def _record_queued_meta(self, request: TaskRequest, wait_reason: str) -> None:
        """キュー待ちメタを記録/更新する (enqueued_at は既存があれば保持)。"""
        key = (request.issue_key, request.phase)
        existing = self._queued_meta.get(key)
        enqueued_at = existing["enqueued_at"] if existing else datetime.now(UTC).isoformat()
        self._queued_meta[key] = {
            "repo": request.repo_key,
            "issue_number": request.issue_number,
            "phase": request.phase,
            "priority": request.priority,
            "enqueued_at": enqueued_at,
            "wait_reason": wait_reason,
        }

    def get_queue_snapshot(self) -> dict[str, Any]:
        """キューの可視化用スナップショットを返す (#96。queue.json / GET /api/queue)。

        Returns:
            {"queued": [...], "active": [...], "paused": [...],
             "max_total": int, "max_per_repo": int}。
            queued は priority 昇順 → enqueued_at 昇順。
        """
        queued = sorted(
            self._queued_meta.values(),
            key=lambda m: (m["priority"], m["enqueued_at"]),
        )
        active = [{"repo": key[0], "issue_number": key[1]} for key in self._active_tasks]
        paused = [
            {"repo": req.repo_key, "issue_number": req.issue_number, "phase": req.phase}
            for req in self._parked.values()
        ]
        return {
            "queued": queued,
            "active": active,
            "paused": paused,
            "max_total": self._max_total,
            "max_per_repo": self._max_per_repo,
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

    # --- ControlBus: pause / resume / drain (#87) ---

    def pause(self, issue_key: IssueKey) -> None:
        """指定 Issue を pause する (次フェーズの dequeue 時に park される)。

        実行中のフェーズは中断しない。フェーズ境界で停止する graceful pause。
        """
        self._paused.add(issue_key)

    async def resume(self, issue_key: IssueKey) -> None:
        """pause を解除し、park 済みタスクがあれば再エンキューする。"""
        self._paused.discard(issue_key)
        parked = self._parked.pop(issue_key, None)
        if parked is not None:
            await self.enqueue(parked)

    def is_paused(self, issue_key: IssueKey) -> bool:
        """指定 Issue が pause 中かどうかを返す。"""
        return issue_key in self._paused

    def mark_aborted(self, issue_key: IssueKey) -> None:
        """Issue を abort 扱いにする (cancel_task と併せて呼ぶ)。

        - pause / park 状態を破棄 (resume で復活させない)。
        - ``_aborted`` に登録し、キュー滞留中・将来 dequeue される分も
          worker_loop でドロップする (SUSPENDED からの復活を防ぐ)。
        再度 enqueue されると (Issue が再アクティブ化) abort ドロップは解除される。
        """
        self._paused.discard(issue_key)
        self._parked.pop(issue_key, None)
        self._aborted.add(issue_key)
        for key in [k for k in self._queued_meta if k[0] == issue_key]:
            self._queued_meta.pop(key, None)

    def request_drain(self) -> None:
        """drain を要求する (ワーカーは新規タスクを拾わず自然終了する)。"""
        self._draining = True

    @property
    def is_draining(self) -> bool:
        """drain 要求中かどうか。"""
        return self._draining
