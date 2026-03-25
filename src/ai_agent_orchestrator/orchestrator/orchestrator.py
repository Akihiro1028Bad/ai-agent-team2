"""メインオーケストレーター.

全コンポーネントを統合し、イベントループを管理する。
GitHubPoller / EventRouter / TaskQueue / StateMachineManager / ClaudeAgentRunner /
WorkspaceManager / ContextEngine / SlackNotifier / EventLogger を組み合わせて
Issue の自動処理パイプラインを駆動する。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
from ai_agent_orchestrator.context.engine import ContextEngine
from ai_agent_orchestrator.credential import CredentialResolver
from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.github.client import AccountManager
from ai_agent_orchestrator.models import ErrorCategory, Phase
from ai_agent_orchestrator.notifications.slack import SlackNotifier
from ai_agent_orchestrator.orchestrator.state_machine import (
    StateMachineManager,
)
from ai_agent_orchestrator.orchestrator.task_queue import (
    TaskQueue,
    TaskRequest,
)
from ai_agent_orchestrator.state_persistence import StatePersistence
from ai_agent_orchestrator.workspace_manager import WorkspaceManager

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import AppSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Protocols for optional / stub components
# ---------------------------------------------------------------------------


class Notifier(Protocol):
    """Notification protocol."""

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a notification."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...


class PhaseDispatcher(Protocol):
    """Protocol for dispatching phase execution."""

    async def dispatch(
        self,
        phase: str,
        *,
        issue_number: int,
        repo: str,
        worktree_path: str,
        context: str,
        resume_session_id: str | None = None,
    ) -> PhaseResultLike:
        """Execute a phase and return the result."""
        ...


class PhaseResultLike(Protocol):
    """Minimal phase result interface."""

    @property
    def next_phase(self) -> str | None:
        """Next phase to transition to, or None."""
        ...

    @property
    def output_summary(self) -> str:
        """Short summary of execution."""
        ...

    @property
    def cost_usd(self) -> float:
        """Cost in USD."""
        ...


class Poller(Protocol):
    """Protocol for GitHub polling."""

    async def start(self, event_queue: asyncio.Queue[object]) -> None:
        """Start polling loop, pushing events to queue."""
        ...

    async def stop(self) -> None:
        """Stop polling."""
        ...


class EventRouterProtocol(Protocol):
    """Protocol for event routing."""

    async def route(self, event: object) -> None:
        """Route an event to the appropriate handler."""
        ...


# ---------------------------------------------------------------------------
# Null implementations for optional components
# ---------------------------------------------------------------------------


class _AgentTrackerAdapter:
    """EventLogger を ClaudeAgentRunner.Tracker 互換にするアダプタ."""

    def __init__(self, event_logger: EventLogger) -> None:
        self._logger = event_logger

    async def track(self, event: str, data: dict[str, Any]) -> None:
        """ClaudeAgentRunner.Tracker protocol に適合する track 呼び出し."""
        await self._logger.track(
            event,
            issue_number=0,
            phase="agent",
            data=data,
        )


class NullNotifier:
    """No-op notifier when Slack is not configured."""

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Log instead of sending notification."""
        logger.info("[NullNotifier] %s (level=%s)", message, level)

    async def close(self) -> None:
        """No-op."""


class NullPoller:
    """No-op poller placeholder until GitHubPoller is implemented."""

    async def start(self, event_queue: asyncio.Queue[object]) -> None:
        """Block forever (no events produced)."""
        await asyncio.Event().wait()

    async def stop(self) -> None:
        """No-op."""


class NullEventRouter:
    """No-op event router placeholder."""

    async def route(self, event: object) -> None:
        """Log and discard."""
        logger.debug("[NullEventRouter] Received event: %s", event)


class NullPhaseDispatcher:
    """No-op phase dispatcher placeholder."""

    async def dispatch(
        self,
        phase: str,
        *,
        issue_number: int,
        repo: str,
        worktree_path: str,
        context: str,
        resume_session_id: str | None = None,
    ) -> _NullPhaseResult:
        """Return a no-op result."""
        logger.info("[NullPhaseDispatcher] phase=%s issue=#%d", phase, issue_number)
        return _NullPhaseResult()


class _NullPhaseResult:
    """Null phase result."""

    @property
    def next_phase(self) -> str | None:
        """No next phase."""
        return None

    @property
    def output_summary(self) -> str:
        """Empty summary."""
        return ""

    @property
    def cost_usd(self) -> float:
        """Zero cost."""
        return 0.0


# ---------------------------------------------------------------------------
# _OrchestratorTaskExecutor (adapts Orchestrator._execute_task to TaskExecutor)
# ---------------------------------------------------------------------------


class _OrchestratorTaskExecutor:
    """Adapter that satisfies TaskExecutor protocol for worker_loop."""

    def __init__(self, orchestrator: Orchestrator) -> None:
        self._orchestrator = orchestrator

    async def execute(self, request: TaskRequest) -> None:
        """Delegate to orchestrator's _execute_task."""
        await self._orchestrator._execute_task(request)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class Orchestrator:
    """メインオーケストレーター.

    全コンポーネントを統合し、イベントループを管理する。

    Attributes:
        _settings: アプリケーション設定。
        _account_manager: GitHub アカウント管理。
        _workspace_manager: git worktree 管理。
        _state_machine: 状態遷移管理。
        _task_queue: 非同期タスクキュー。
        _agent_runner: Claude Code SDK ランナー。
        _context_engine: コンテキスト構築エンジン。
        _notifier: 通知送信 (Slack or NullNotifier)。
        _event_logger: イベントログ記録。
        _phase_dispatcher: フェーズ実行ディスパッチャ。
        _poller: GitHub ポーリング。
        _event_router: イベントルーター。
    """

    def __init__(
        self,
        settings: AppSettings,
        *,
        notifier: Notifier | None = None,
        poller: Poller | None = None,
        event_router: EventRouterProtocol | None = None,
        phase_dispatcher: PhaseDispatcher | None = None,
        persistence: StatePersistence | None = None,
        event_logger: EventLogger | None = None,
        account_manager: AccountManager | None = None,
        workspace_manager: WorkspaceManager | None = None,
        agent_runner: ClaudeAgentRunner | None = None,
        context_engine: ContextEngine | None = None,
    ) -> None:
        """Orchestrator を初期化する.

        Args:
            settings: アプリケーション設定。
            notifier: 通知送信。None の場合は自動生成。
            poller: GitHub ポーラー。None の場合は NullPoller。
            event_router: イベントルーター。None の場合は NullEventRouter。
            phase_dispatcher: フェーズディスパッチャ。None の場合は NullPhaseDispatcher。
            persistence: 状態永続化。None の場合は自動生成。
            event_logger: イベントログ。None の場合は自動生成。
            account_manager: アカウントマネージャ。None の場合は自動生成。
            workspace_manager: ワークスペースマネージャ。None の場合は自動生成。
            agent_runner: エージェントランナー。None の場合は自動生成。
            context_engine: コンテキストエンジン。None の場合は自動生成。
        """
        self._settings = settings
        self._running = False
        self._worker_tasks: list[asyncio.Task[None]] = []
        self._health_task: asyncio.Task[None] | None = None
        self._route_task: asyncio.Task[None] | None = None
        self._poller_task: asyncio.Task[None] | None = None

        # Event queue for poller -> router communication
        self._event_queue: asyncio.Queue[object] = asyncio.Queue()

        # Workspace manager
        self._workspace_manager = workspace_manager or WorkspaceManager(
            base_dir=settings.workspace_dir,
        )

        # Persistence
        workspace_path = Path(settings.workspace_dir).expanduser()
        self._persistence = persistence or StatePersistence(
            state_file=workspace_path / "state.json",
        )

        # Event logger
        self._event_logger = event_logger or EventLogger(
            log_dir=workspace_path / "logs",
        )

        # State machine manager
        self._state_machine = StateMachineManager(
            persistence=self._persistence,
            tracker=self._event_logger,
        )

        # Task queue
        self._task_queue = TaskQueue(
            max_total=settings.concurrency.max_total,
            max_per_repo=settings.concurrency.max_per_repo,
        )

        # Account manager
        if account_manager is not None:
            self._account_manager = account_manager
        else:
            resolver = CredentialResolver()
            self._account_manager = AccountManager(
                accounts=settings.accounts,
                resolver=resolver,
                repo_configs=settings.repositories,
            )

        # Agent runner
        self._agent_runner = agent_runner or ClaudeAgentRunner(
            tracker=_AgentTrackerAdapter(self._event_logger),
        )

        # Context engine
        self._context_engine = context_engine or ContextEngine()

        # Notifier (Slack or NullNotifier)
        if notifier is not None:
            self._notifier: Notifier = notifier
        elif settings.slack is not None:
            self._notifier = SlackNotifier(
                webhook_url=settings.slack.webhook_url,
                default_channel=settings.slack.default_channel,
            )
        elif settings.slack_webhook_url is not None:
            self._notifier = SlackNotifier(
                webhook_url=settings.slack_webhook_url,
            )
        else:
            self._notifier = NullNotifier()

        # Phase dispatcher (placeholder until phases module is implemented)
        self._phase_dispatcher: PhaseDispatcher = phase_dispatcher or NullPhaseDispatcher()

        # Poller (placeholder until poller module is implemented)
        self._poller: Poller = poller or NullPoller()

        # Event router (placeholder until event_router module is implemented)
        self._event_router: EventRouterProtocol = event_router or NullEventRouter()

        # Task executor adapter
        self._executor = _OrchestratorTaskExecutor(self)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def settings(self) -> AppSettings:
        """アプリケーション設定を返す."""
        return self._settings

    @property
    def state_machine(self) -> StateMachineManager:
        """StateMachineManager を返す."""
        return self._state_machine

    @property
    def task_queue(self) -> TaskQueue:
        """TaskQueue を返す."""
        return self._task_queue

    @property
    def account_manager(self) -> AccountManager:
        """AccountManager を返す."""
        return self._account_manager

    @property
    def workspace_manager(self) -> WorkspaceManager:
        """WorkspaceManager を返す."""
        return self._workspace_manager

    @property
    def is_running(self) -> bool:
        """オーケストレーターが稼働中かどうかを返す."""
        return self._running

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """オーケストレーターを起動する.

        1. 永続化ストレージから状態を復元
        2. ヘルスチェックタスクを開始
        3. ポーラータスクを開始
        4. イベントルーティングタスクを開始
        5. ワーカーループタスクを開始 (concurrency.max_total 個)
        """
        if self._running:
            logger.warning("Orchestrator is already running")
            return

        logger.info("Starting orchestrator...")

        # 1. Load state from persistence
        self._state_machine.load_from_persistence()
        logger.info("State loaded from persistence")

        self._running = True

        # 2. Start health checker
        self._health_task = asyncio.create_task(self._health_check_loop(), name="health-checker")

        # 3. Start poller
        self._poller_task = asyncio.create_task(self._poller.start(self._event_queue), name="poller")

        # 4. Start event routing
        self._route_task = asyncio.create_task(self._route_events(), name="event-router")

        # 5. Start worker loops
        for i in range(self._settings.concurrency.max_total):
            task = asyncio.create_task(
                self._task_queue.worker_loop(self._executor),
                name=f"worker-{i}",
            )
            self._worker_tasks.append(task)

        await self._event_logger.track(
            "orchestrator_started",
            issue_number=0,
            phase="system",
            data={
                "max_total": self._settings.concurrency.max_total,
                "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
            },
        )

        await self._notifier.notify(
            "Orchestrator started",
            level="info",
            metadata={
                "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
            },
        )

        logger.info(
            "Orchestrator started with %d workers",
            self._settings.concurrency.max_total,
        )

    async def stop(self) -> None:
        """オーケストレーターを停止する.

        1. ポーラーを停止
        2. ワーカータスクをキャンセル
        3. ヘルスチェックをキャンセル
        4. 状態を永続化にフラッシュ
        5. 通知クライアントをクローズ
        """
        if not self._running:
            return

        logger.info("Stopping orchestrator...")
        self._running = False

        # Stop poller
        await self._poller.stop()

        # Cancel all managed tasks
        tasks_to_cancel: list[asyncio.Task[None]] = []
        if self._poller_task is not None:
            tasks_to_cancel.append(self._poller_task)
        if self._route_task is not None:
            tasks_to_cancel.append(self._route_task)
        if self._health_task is not None:
            tasks_to_cancel.append(self._health_task)
        tasks_to_cancel.extend(self._worker_tasks)

        for task in tasks_to_cancel:
            task.cancel()

        # Wait for cancellation with timeout
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        self._worker_tasks.clear()
        self._poller_task = None
        self._route_task = None
        self._health_task = None

        # Flush persistence
        await self._persistence.flush(self._state_machine._states)

        # Close notifier
        await self._notifier.close()

        await self._event_logger.track(
            "orchestrator_stopped",
            issue_number=0,
            phase="system",
        )

        logger.info("Orchestrator stopped")

    # ------------------------------------------------------------------
    # Event routing
    # ------------------------------------------------------------------

    async def _route_events(self) -> None:
        """イベントキューからイベントを取り出してルーティング."""
        while self._running:
            try:
                event = await self._event_queue.get()
                try:
                    await self._event_router.route(event)
                except Exception as exc:
                    logger.error("Event routing error: %s", exc, exc_info=True)
                    await self._notifier.notify(
                        f"Event routing error: {exc}",
                        level="error",
                    )
                finally:
                    self._event_queue.task_done()
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------
    # Task execution
    # ------------------------------------------------------------------

    async def _execute_task(self, task: TaskRequest) -> None:
        """タスクを実行する (worker_loop からのコールバック).

        1. フェーズディスパッチャからフェーズエクゼキュータを取得
        2. コンテキストを構築
        3. フェーズを実行
        4. エラー発生時は分類し、リトライまたはサスペンド

        Args:
            task: 実行するタスクリクエスト。
        """
        issue_number = task.issue_number
        repo_key = task.repo_key
        phase = task.phase

        logger.info(
            "Executing task: issue=#%d repo=%s phase=%s",
            issue_number,
            repo_key,
            phase,
        )

        try:
            # Build context (best-effort, use empty string on failure)
            context = ""
            worktree_path = task.extra.get("worktree_path", "")
            issue_body = task.extra.get("issue_body", "")

            if worktree_path:
                try:
                    context = await self._context_engine.build_context(
                        worktree_path=worktree_path,
                        issue_body=issue_body,
                        phase=phase,
                    )
                except Exception as ctx_err:
                    logger.warning(
                        "Failed to build context for issue #%d: %s",
                        issue_number,
                        ctx_err,
                    )

            # Dispatch phase execution
            result = await self._phase_dispatcher.dispatch(
                phase,
                issue_number=issue_number,
                repo=repo_key,
                worktree_path=worktree_path,
                context=context,
                resume_session_id=task.extra.get("resume_session_id"),
            )

            await self._event_logger.track(
                "phase_completed",
                issue_number=issue_number,
                phase=phase,
                data={
                    "output_summary": result.output_summary,
                    "cost_usd": result.cost_usd,
                    "next_phase": result.next_phase,
                },
            )

            # Transition to next phase if specified
            if result.next_phase is not None:
                next_phase = Phase(result.next_phase)
                await self._state_machine.transition(issue_number, next_phase)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._handle_task_error(task, exc)

    async def _handle_task_error(
        self,
        task: TaskRequest,
        error: Exception,
    ) -> None:
        """タスク実行エラーを処理する.

        エラーを分類し、一時的エラーはリトライ、それ以外は SUSPENDED に遷移する。

        Args:
            task: 実行に失敗したタスク。
            error: 発生した例外。
        """
        issue_number = task.issue_number
        category = self._classify_error(error)

        logger.error(
            "Task error: issue=#%d phase=%s category=%s error=%s",
            issue_number,
            task.phase,
            category,
            error,
            exc_info=True,
        )

        await self._event_logger.track(
            "phase_error",
            issue_number=issue_number,
            phase=task.phase,
            data={
                "error": str(error),
                "category": category,
            },
        )

        state = self._state_machine.get_state(issue_number)
        retry_count = state.retry_count if state else 0

        if category == ErrorCategory.TRANSIENT and retry_count < self._settings.retry.max_attempts:
            # Retry after backoff
            if state is not None:
                state.retry_count += 1
            backoff_idx = min(
                retry_count,
                len(self._settings.retry.backoff_minutes) - 1,
            )
            delay_min = self._settings.retry.backoff_minutes[backoff_idx]

            logger.info(
                "Retrying issue #%d in %d minutes (attempt %d/%d)",
                issue_number,
                delay_min,
                retry_count + 1,
                self._settings.retry.max_attempts,
            )

            await asyncio.sleep(delay_min * 60)
            await self._task_queue.enqueue(task)
        else:
            # Suspend the issue
            try:
                await self._state_machine.transition(issue_number, Phase.SUSPENDED)
            except Exception as transition_err:
                logger.error(
                    "Failed to suspend issue #%d: %s",
                    issue_number,
                    transition_err,
                )

            await self._notifier.notify(
                f"Issue #{issue_number} suspended due to error: {error}",
                level="error",
                metadata={
                    "issue": issue_number,
                    "phase": task.phase,
                    "error": str(error),
                },
            )

    @staticmethod
    def _classify_error(error: Exception) -> str:
        """エラーを分類する.

        Args:
            error: 分類する例外。

        Returns:
            ErrorCategory の値文字列。
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()

        # Transient errors (network, timeout, rate limit)
        transient_indicators = [
            "timeout",
            "rate limit",
            "429",
            "502",
            "503",
            "504",
            "connection",
            "temporary",
        ]
        if any(ind in error_msg for ind in transient_indicators):
            return ErrorCategory.TRANSIENT

        if "timeout" in error_type.lower():
            return ErrorCategory.TRANSIENT

        # Auth errors
        if any(kw in error_msg for kw in ["auth", "credential", "token", "401", "403"]):
            return ErrorCategory.AUTH

        # Git conflict
        if "conflict" in error_msg or "merge" in error_msg:
            return ErrorCategory.GIT_CONFLICT

        # CI failure
        if "ci" in error_msg and "fail" in error_msg:
            return ErrorCategory.CI_FAILURE

        # Default to output_invalid
        return ErrorCategory.OUTPUT_INVALID

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, bool]:
        """ヘルスチェックを実行する.

        GitHub トークンの有効性を検証する。

        Returns:
            コンポーネント名をキー、健全性を値とする辞書。
        """
        results: dict[str, bool] = {}

        # Check GitHub account tokens
        try:
            account_results = await self._account_manager.verify_all()
            for name, ok in account_results.items():
                results[f"github/{name}"] = ok
        except Exception as exc:
            logger.warning("Health check failed for accounts: %s", exc)
            results["github"] = False

        return results

    async def _health_check_loop(self) -> None:
        """定期的なヘルスチェックループ.

        5分間隔で health_check() を実行し、失敗時は通知する。
        """
        interval_sec = 300  # 5 minutes
        while self._running:
            try:
                await asyncio.sleep(interval_sec)
                if not self._running:
                    break
                results = await self.health_check()
                unhealthy = [k for k, v in results.items() if not v]
                if unhealthy:
                    await self._notifier.notify(
                        f"Health check failures: {', '.join(unhealthy)}",
                        level="error",
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Health check loop error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """オーケストレーターの稼働状態を返す.

        Returns:
            状態情報の辞書。
        """
        return {
            "running": self._running,
            "task_queue": self._task_queue.get_status(),
            "repositories": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
        }
