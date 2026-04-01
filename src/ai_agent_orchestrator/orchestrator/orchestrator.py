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
    from ai_agent_orchestrator.phases.base import PhaseExecutor as PhaseExecutorBase
    from ai_agent_orchestrator.phases.dispatcher import (
        PhaseDispatcher as ConcretePhaseDispatcher,
    )

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
# _RealPhaseDispatcherAdapter
# ---------------------------------------------------------------------------


class _RealPhaseDispatcherAdapter:
    """Adapter: real PhaseDispatcher -> orchestrator dispatch() protocol.

    The real PhaseDispatcher.execute(TaskRequest) invokes a PhaseExecutor
    which handles prompt building, agent execution, result processing, and
    state transitions internally.  This adapter wraps that into the
    ``dispatch()`` signature expected by ``Orchestrator._execute_task``,
    returning a lightweight result.  Because the executor already manages
    transitions, the adapter always returns ``next_phase=None`` so that the
    orchestrator does not attempt a duplicate transition.
    """

    def __init__(self, concrete: ConcretePhaseDispatcher) -> None:
        self._concrete = concrete

    async def dispatch(
        self,
        phase: str,
        *,
        issue_number: int,
        repo: object,
        worktree_path: str,
        context: str,
        resume_session_id: str | None = None,
    ) -> _NullPhaseResult:
        """Dispatch phase execution via the real PhaseDispatcher.

        A ``models.TaskRequest`` is constructed from the parameters and
        forwarded to the concrete dispatcher.  The concrete executor takes
        full responsibility for state transitions, so the returned result
        reports ``next_phase=None``.
        """
        from ai_agent_orchestrator.models import Phase as PhaseEnum
        from ai_agent_orchestrator.models import TaskRequest as ModelsTaskRequest

        # Convert phase string to Phase enum; use as-is if not a valid enum value
        try:
            phase_enum = PhaseEnum(phase.replace("_", "-"))
        except ValueError:
            phase_enum = PhaseEnum(phase)

        request = ModelsTaskRequest(
            issue_number=issue_number,
            repo=repo,  # type: ignore[arg-type]
            phase=phase_enum,
        )
        await self._concrete.execute(request)
        return _NullPhaseResult()


def _build_phase_executors(
    runner: ClaudeAgentRunner,
    github: object,
    notifier: object,
    tracker: object,
    workspace: object,
    context_engine: ContextEngine,
    state_machine: object,
) -> dict[str, PhaseExecutorBase]:
    """Create executor instances for every known phase.

    Returns:
        Mapping of phase key (underscored) to executor instance.
    """
    from ai_agent_orchestrator.phases import (
        AnalysisExecutor,
        CiFixExecutor,
        DesignExecutor,
        DesignReviseExecutor,
        DoneExecutor,
        FixExecutor,
        HearingExecutor,
        ImplementExecutor,
        ImplReviseExecutor,
        PlanBriefExecutor,
        PlanningExecutor,
        SplitExecuteExecutor,
        SplitProposalExecutor,
        TypeDetectionExecutor,
    )

    common_kwargs: dict[str, object] = {
        "runner": runner,
        "account_manager": github,
        "notifier": notifier,
        "tracker": tracker,
        "workspace": workspace,
        "context_engine": context_engine,
        "state_machine": state_machine,
    }

    return {
        "type_detection": TypeDetectionExecutor(**common_kwargs),  # type: ignore[arg-type]
        "analysis": AnalysisExecutor(**common_kwargs),  # type: ignore[arg-type]
        "fix": FixExecutor(**common_kwargs),  # type: ignore[arg-type]
        "hearing": HearingExecutor(**common_kwargs),  # type: ignore[arg-type]
        "plan_brief": PlanBriefExecutor(**common_kwargs),  # type: ignore[arg-type]
        "design": DesignExecutor(**common_kwargs),  # type: ignore[arg-type]
        "design_revise": DesignReviseExecutor(**common_kwargs),  # type: ignore[arg-type]
        "planning": PlanningExecutor(**common_kwargs),  # type: ignore[arg-type]
        "implement": ImplementExecutor(**common_kwargs),  # type: ignore[arg-type]
        "ci_fix": CiFixExecutor(**common_kwargs),  # type: ignore[arg-type]
        "impl_revise": ImplReviseExecutor(**common_kwargs),  # type: ignore[arg-type]
        "done": DoneExecutor(**common_kwargs),  # type: ignore[arg-type]
        "split_proposal": SplitProposalExecutor(**common_kwargs),  # type: ignore[arg-type]
        "split_execute": SplitExecuteExecutor(**common_kwargs),  # type: ignore[arg-type]
    }


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

        # Phase dispatcher: use injected one, or build real dispatcher
        if phase_dispatcher is not None:
            self._phase_dispatcher: PhaseDispatcher = phase_dispatcher
        else:
            self._phase_dispatcher = self._build_real_phase_dispatcher()

        # Poller (placeholder until poller module is implemented)
        self._poller: Poller = poller or NullPoller()

        # Event router (placeholder until event_router module is implemented)
        self._event_router: EventRouterProtocol = event_router or NullEventRouter()

        # Task executor adapter
        self._executor = _OrchestratorTaskExecutor(self)

    def _build_real_phase_dispatcher(self) -> _RealPhaseDispatcherAdapter:
        """Build a real PhaseDispatcher with all concrete executors.

        Returns:
            An adapter wrapping the concrete PhaseDispatcher.
        """
        from ai_agent_orchestrator.phases.dispatcher import (
            PhaseDispatcher as ConcretePhaseDispatcherCls,
        )

        executors = _build_phase_executors(
            runner=self._agent_runner,
            github=self._account_manager,
            notifier=self._notifier,
            tracker=self._event_logger,
            workspace=self._workspace_manager,
            context_engine=self._context_engine,
            state_machine=self._state_machine,
        )
        concrete = ConcretePhaseDispatcherCls(executors=executors)
        return _RealPhaseDispatcherAdapter(concrete)

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

    def set_poller(self, poller: Poller) -> None:
        """ポーラーを差し替える (start() 前に呼ぶこと).

        Args:
            poller: 新しいポーラー。
        """
        self._poller = poller

    def set_event_router(self, router: EventRouterProtocol) -> None:
        """イベントルーターを差し替える (start() 前に呼ぶこと).

        Args:
            router: 新しいイベントルーター。
        """
        self._event_router = router

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

        # 1. Load state from persistence and re-enqueue pending tasks
        self._state_machine.load_from_persistence()
        logger.info("State loaded from persistence")

        # Re-enqueue tasks for issues that were in-progress when stopped
        await self._reenqueue_pending_tasks()

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
    async def _reenqueue_pending_tasks(self) -> None:
        """起動時に未完了フェーズのタスクを再エンキューする.

        前回のセッションで中断されたタスクを再開するため、
        永続化されたIssue状態から「レビュー待ち」以外のアクティブフェーズを
        タスクキューに投入する。
        """
        # Phases that need active processing (not waiting for human input)
        active_phases = {
            Phase("type-detection"),
            Phase("hearing"),
            Phase("analysis"),
            Phase("plan-brief"),
            Phase("design"),
            Phase("design-revise"),
            Phase("planning"),
            Phase("implement"),
            Phase("fix"),
            Phase("ci-fix"),
            Phase("impl-revise"),
            Phase("split-proposal"),
            Phase("split-execute"),
        }

        for issue_number, state in self._state_machine._states.items():
            if state.phase in active_phases:
                # Find the repo config for this issue
                repo_config = None
                for repo in self._settings.repositories:
                    if f"{repo.owner}/{repo.repo}" == state.repo:
                        repo_config = repo
                        break

                if repo_config is not None:
                    await self._task_queue.enqueue(
                        TaskRequest(
                            issue_number=issue_number,
                            repo=repo_config,
                            phase=state.phase.value,
                        )
                    )
                    logger.info(
                        "Re-enqueued pending task: issue=#%d phase=%s",
                        issue_number,
                        state.phase.value,
                    )

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
                        issue_number=issue_number,
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
                repo=task.repo,
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

            # Transition to next phase if specified (for NullPhaseDispatcher)
            if result.next_phase is not None:
                next_phase = Phase(result.next_phase)
                await self._state_machine.transition(issue_number, next_phase)

            # Auto-enqueue next task if the phase changed to an active phase
            # (Real executors handle transitions internally, so we check current phase)
            current_phase = self._state_machine.get_phase(issue_number)
            active_phases = {
                Phase("type-detection"),
                Phase("hearing"),
                Phase("analysis"),
                Phase("plan-brief"),
                Phase("design"),
                Phase("design-revise"),
                Phase("planning"),
                Phase("implement"),
                Phase("fix"),
                Phase("ci-fix"),
                Phase("impl-revise"),
                Phase("split-proposal"),
                Phase("split-execute"),
            }
            # Compare with current task's phase (handle both hyphen and underscore)
            try:
                task_phase = Phase(phase.replace("_", "-"))
            except ValueError:
                task_phase = None
            if current_phase in active_phases and current_phase != task_phase:
                await self._task_queue.enqueue(
                    TaskRequest(
                        issue_number=issue_number,
                        repo=task.repo,
                        phase=current_phase.value,
                    )
                )
                logger.info(
                    "Auto-enqueued next task: issue=#%d phase=%s",
                    issue_number,
                    current_phase.value,
                )

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
