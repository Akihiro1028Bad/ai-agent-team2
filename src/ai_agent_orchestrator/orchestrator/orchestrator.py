"""メインオーケストレーター.

全コンポーネントを統合し、イベントループを管理する。
GitHubPoller / EventRouter / TaskQueue / StateMachineManager / ClaudeAgentRunner /
WorkspaceManager / ContextEngine / SlackNotifier / EventLogger を組み合わせて
Issue の自動処理パイプラインを駆動する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ai_agent_orchestrator.agents.agent_log import AgentLogWriter
from ai_agent_orchestrator.agents.claude_runner import PHASE_CONFIG, ClaudeAgentRunner
from ai_agent_orchestrator.config.ui_settings import load_ui_settings, merge_phase_configs
from ai_agent_orchestrator.context.engine import ContextEngine
from ai_agent_orchestrator.credential import CredentialResolver
from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.github.client import AccountManager
from ai_agent_orchestrator.io_safety import atomic_write_text
from ai_agent_orchestrator.models import (
    ErrorCategory,
    IssueKey,
    Phase,
    PhaseConfig,
    make_issue_key,
)
from ai_agent_orchestrator.notifications.slack import SlackNotifier
from ai_agent_orchestrator.orchestrator.approval import resolve_approvers
from ai_agent_orchestrator.orchestrator.control_bus import (
    REWIND_TARGETS,
    OperationalCommand,
    read_new_operational_commands,
)
from ai_agent_orchestrator.orchestrator.control_file import (
    ControlCommand,
    read_new_control_commands,
)
from ai_agent_orchestrator.orchestrator.execution_guard import ExecutionGuard
from ai_agent_orchestrator.orchestrator.state_machine import (
    InvalidTransitionError,
    StateMachineManager,
)
from ai_agent_orchestrator.orchestrator.task_queue import (
    Priority,
    TaskQueue,
    TaskRequest,
)
from ai_agent_orchestrator.state_persistence import StatePersistence
from ai_agent_orchestrator.workspace_manager import WorkspaceManager

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
    from ai_agent_orchestrator.phases.base import PhaseExecutor as PhaseExecutorBase  # noqa: F401
    from ai_agent_orchestrator.phases.dispatcher import (
        PhaseDispatcher as ConcretePhaseDispatcher,
    )
    from ai_agent_orchestrator.phases.dispatcher import PhaseExecutorLike

logger = logging.getLogger(__name__)

# worktree ディレクトリ名 (例: "feature-issue-42" / "docs-issue-42") から issue 番号を抽出する。
_WORKTREE_ISSUE_RE = re.compile(r"-issue-(\d+)$")


def _extract_worktree_issue_number(name: str) -> int | None:
    """worktree ディレクトリ名から issue 番号を抽出する (#96 worktree_gc).

    Args:
        name: worktree ディレクトリ名 (``feature-issue-42`` 等)。

    Returns:
        抽出した issue 番号。命名規則に一致しなければ None。
    """
    match = _WORKTREE_ISSUE_RE.search(name)
    return int(match.group(1)) if match else None


# retry_with_analysis で現フェーズのまま再試行できる実行フェーズ。
_RETRYABLE_PHASES: frozenset[Phase] = frozenset({Phase.PLAN, Phase.IMPLEMENT, Phase.REVISE})


def _parse_rewind_target(target: str) -> Phase | None:
    """rewind の target 文字列を、resume 可能な Phase へ変換する (#96).

    許可語彙は control_bus.REWIND_TARGETS (state machine の resume_to_* と一致) を
    共有参照する。不正・未許可は None。
    """
    if target not in REWIND_TARGETS:
        return None
    return Phase(target)


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
        extra: dict[str, Any] | None = None,
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
        extra: dict[str, Any] | None = None,
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
        extra: dict[str, Any] | None = None,
    ) -> _NullPhaseResult:
        """Dispatch phase execution via the real PhaseDispatcher.

        A ``models.TaskRequest`` is constructed from the parameters and
        forwarded to the concrete dispatcher.  The concrete executor takes
        full responsibility for state transitions, so the returned result
        reports ``next_phase=None``.
        """
        from ai_agent_orchestrator.models import TaskRequest as ModelsTaskRequest

        # U5 (#83): TaskRequest は一本化され phase は str (ハイフン区切り)
        request = ModelsTaskRequest(
            issue_number=issue_number,
            repo=repo,
            phase=phase.replace("_", "-"),
            extra=extra or {},
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
) -> dict[str, PhaseExecutorLike]:
    """Create executor instances for every known phase.

    Returns:
        Mapping of phase key (underscored) to executor instance.
    """
    from ai_agent_orchestrator.phases import (
        CiFixExecutor,
        DoneExecutor,
        HearingExecutor,
        ImplementExecutor,
        PlanExecutor,
        ReviseExecutor,
        RevisePhaseExecutor,
        SplitExecuteExecutor,
        SplitPhaseExecutor,
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

    # U5 (#83): 統一パイプラインの 9 フェーズ。APPROVE / REVIEW / CLARIFY_WAIT は
    # 人間/ポーリング待ちのゲートで executor を持たない。
    return {
        "intake": TypeDetectionExecutor(**common_kwargs),  # type: ignore[arg-type]
        "clarify": HearingExecutor(**common_kwargs),  # type: ignore[arg-type]
        "plan": PlanExecutor(**common_kwargs),  # type: ignore[arg-type]
        "implement": ImplementExecutor(**common_kwargs),  # type: ignore[arg-type]
        "revise": RevisePhaseExecutor(
            review_revise=ReviseExecutor(**common_kwargs),  # type: ignore[arg-type]
            ci_fix=CiFixExecutor(**common_kwargs),  # type: ignore[arg-type]
        ),
        "split": SplitPhaseExecutor(
            proposal=SplitProposalExecutor(**common_kwargs),  # type: ignore[arg-type]
            execute_step=SplitExecuteExecutor(**common_kwargs),  # type: ignore[arg-type]
        ),
        "done": DoneExecutor(**common_kwargs),  # type: ignore[arg-type]
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
        # ControlBus (#87): control.jsonl 消費ループと shutdown 用の detached タスク
        self._control_task: asyncio.Task[None] | None = None
        self._shutdown_task: asyncio.Task[None] | None = None
        self._control_offset = 0
        # 承認/差し戻し (control_file の approve/reject) は別系統・別 offset で消費する (#89)。
        self._review_offset = 0

        # Event queue for poller -> router communication
        self._event_queue: asyncio.Queue[object] = asyncio.Queue()

        # Workspace manager
        self._workspace_manager = workspace_manager or WorkspaceManager(
            base_dir=settings.workspace_dir,
        )

        # Persistence
        workspace_path = Path(settings.workspace_dir).expanduser()
        self._health_file = workspace_path / "health.json"
        # ControlBus (#87): control.jsonl と消費済み offset の永続化先。
        self._control_file = (
            Path(settings.control_file).expanduser() if settings.control_file else workspace_path / "control.jsonl"
        )
        # offset は control_file と同じディレクトリに置く (custom パス時のズレ防止)。
        self._control_offset_file = self._control_file.with_name(self._control_file.name + ".offset")
        # 承認/差し戻し消費の offset (operational とは独立に同一ファイルを併読する, #89)。
        self._review_offset_file = self._control_file.with_name(self._control_file.name + ".review-offset")
        # キュー可視化 (#96): TaskQueue 状態の書き出し先。
        self._queue_file = workspace_path / "queue.json"
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

        # Agent runner。フェーズ設定は UI 設定 (settings.ui.yaml) の上書きを
        # run() ごとに反映する provider 経由で渡す (#90)。
        ui_settings_path = Path(settings.ui_settings_file).expanduser()

        def _phase_config_provider() -> dict[str, PhaseConfig]:
            return merge_phase_configs(PHASE_CONFIG, load_ui_settings(ui_settings_path))

        self._agent_runner = agent_runner or ClaudeAgentRunner(
            tracker=_AgentTrackerAdapter(self._event_logger),
            agent_log_writer=AgentLogWriter(log_dir=workspace_path / "logs"),
            phase_config_provider=_phase_config_provider,
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

        # Execution guard: prevents EventRouter from transitioning state mid-execution
        self._execution_guard = ExecutionGuard()

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
    def execution_guard(self) -> ExecutionGuard:
        """ExecutionGuard を返す."""
        return self._execution_guard

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

        # ControlBus 消費ループ (#87)。停止中に積まれたコマンドを起動時から消費する
        # ため、永続化した offset を復元する (処理済みは再適用しない)。
        self._control_offset = self._load_control_offset()
        self._review_offset = self._load_review_offset()
        self._control_task = asyncio.create_task(self._control_loop(), name="control-bus")

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
                "notification_type": "system_start",
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
        if self._control_task is not None:
            tasks_to_cancel.append(self._control_task)
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
        self._control_task = None

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
    # ControlBus (#87): control.jsonl の運用コマンド消費
    # ------------------------------------------------------------------

    _CONTROL_POLL_INTERVAL_SEC = 2.0
    _SHUTDOWN_DRAIN_TIMEOUT_SEC = 600.0

    def _load_control_offset(self) -> int:
        """永続化済みの control.jsonl 消費 offset を読む (失敗時 0)."""
        try:
            return int(self._control_offset_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def _save_control_offset(self) -> None:
        """消費済み offset を永続化する (再起動時の重複適用防止)."""
        try:
            self._control_offset_file.write_text(str(self._control_offset), encoding="utf-8")
        except OSError:
            logger.warning("failed to persist control offset", exc_info=True)

    def _load_review_offset(self) -> int:
        """永続化済みの承認/差し戻し消費 offset を読む (失敗時 0, #89)."""
        try:
            return int(self._review_offset_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    def _save_review_offset(self) -> None:
        """承認/差し戻し消費 offset を永続化する (#89)."""
        try:
            self._review_offset_file.write_text(str(self._review_offset), encoding="utf-8")
        except OSError:
            logger.warning("failed to persist review offset", exc_info=True)

    def _control_authorized_actors(self) -> list[str]:
        """運用コマンドを発行できる actor の許可集合 (全リポの承認者和集合)."""
        actors: set[str] = set()
        for repo in self._settings.repositories:
            actors.update(resolve_approvers(repo.owner, repo.approvers))
        return list(actors)

    def _resolve_issue_key(self, issue_number: int) -> IssueKey | None:
        """issue 番号から一意な IssueKey を解決する (複数一致/不在は None)."""
        matches = [key for key in self._state_machine._states if key[1] == issue_number]
        if len(matches) != 1:
            logger.warning(
                "control: issue #%d は %d 件一致のため解決できません",
                issue_number,
                len(matches),
            )
            return None
        return matches[0]

    def _repo_config_for(self, repo_key: str) -> RepositoryConfig | None:
        """repo_key ("owner/repo") に対応する RepositoryConfig を返す."""
        for repo in self._settings.repositories:
            if f"{repo.owner}/{repo.repo}" == repo_key:
                return repo
        return None

    async def _control_loop(self) -> None:
        """control.jsonl をポーリングし、運用コマンドを適用する背景ループ.

        併せて毎周回 queue.json を書き出す (#96。UI のキュー画面が ~2s で追従)。
        """
        while self._running:
            try:
                await self._consume_control_commands()
                await self._consume_review_commands()
                await self._write_queue_json()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("control loop iteration failed: %s", exc)
            await asyncio.sleep(self._CONTROL_POLL_INTERVAL_SEC)

    def build_queue_snapshot(self) -> dict[str, Any]:
        """queue.json 用のスナップショットを構築する (#96)."""
        snapshot = self._task_queue.get_queue_snapshot()
        snapshot["ts"] = datetime.now(UTC).isoformat()
        snapshot["running"] = self._running
        return snapshot

    async def _write_queue_json(self) -> None:
        """queue.json を atomic (tmp + replace) に書き出す (#96。失敗は warning)."""
        try:
            await asyncio.to_thread(self._write_queue_json_sync, self.build_queue_snapshot())
        except Exception as exc:
            logger.warning("queue.json の書き出しに失敗: %s", exc)

    def _write_queue_json_sync(self, snapshot: dict[str, Any]) -> None:
        """queue.json の同期書き出し (tmp + replace + 0o600, #115)."""
        atomic_write_text(self._queue_file, json.dumps(snapshot, ensure_ascii=False, indent=2))

    async def _consume_control_commands(self) -> None:
        """未処理の運用コマンドを読み取り、順に適用して offset を進める."""
        commands, new_offset = read_new_operational_commands(
            self._control_file,
            self._control_offset,
            self._control_authorized_actors(),
        )
        # 適用してから offset を進める (at-least-once)。途中クラッシュ時は
        # 再起動後に再適用されるが、各コマンドは冪等なので abort 等を取りこぼさない。
        for cmd in commands:
            await self._apply_control_command(cmd)
        if new_offset != self._control_offset:
            self._control_offset = new_offset
            self._save_control_offset()

    async def _consume_review_commands(self) -> None:
        """未処理の承認/差し戻し (approve/reject) を読み取り、順に適用する (#89).

        operational コマンドと同一ファイルを別 offset で併読する (control_file は
        approve/reject のみ、operational は pause 等のみを拾い、互いの行は無視する)。
        承認者検証は read_new_control_commands が許可リストで行う。
        """
        commands, new_offset = read_new_control_commands(
            self._control_file,
            self._review_offset,
            self._control_authorized_actors(),
        )
        for cmd in commands:
            await self._apply_review_command(cmd)
        if new_offset != self._review_offset:
            self._review_offset = new_offset
            self._save_review_offset()

    async def _apply_review_command(self, cmd: ControlCommand) -> None:
        """承認/差し戻しを APPROVE ゲートとして適用する (#89).

        - approve          → APPROVE→IMPLEMENT 遷移 + IMPLEMENT 再エンキュー
        - reject           → APPROVE→PLAN 遷移 + feedback 付き PLAN 再エンキュー
        - prototype_revise → APPROVE→PLAN 遷移 + prototype_feedback 付き PLAN 再エンキュー
          (#145 Phase2: 設計書は維持し UI プロトタイプのみ更新する反復ループ)

        APPROVE 相にない Issue は誤遷移防止のため無視する (poller 経由の承認と同方針)。
        """
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        current = self._state_machine.get_phase(issue_key)
        repo_config = self._repo_config_for(issue_key[0])
        if repo_config is None:
            logger.warning("review: repo を解決できません (#%d)", cmd.issue_number)
            return

        # SPLIT 分割提案の承認待ちは APPROVE ゲートとは別経路で処理する (#150)。
        state = self._state_machine.get_state(issue_key)
        if current is Phase.SPLIT and state is not None and state.awaiting_split_approval:
            await self._apply_split_review_command(cmd, issue_key, repo_config)
            return

        if current is not Phase.APPROVE:
            logger.info(
                "review: #%d は APPROVE 相でないため無視 (現在 %s)",
                cmd.issue_number,
                current.value,
            )
            return

        next_phase = Phase.IMPLEMENT if cmd.action == "approve" else Phase.PLAN
        try:
            await self._state_machine.transition(issue_key, next_phase)
        except (InvalidTransitionError, KeyError) as exc:
            logger.warning("review: %s への遷移に失敗 (#%d): %s", next_phase.value, cmd.issue_number, exc)
            return

        # 遷移と再エンキューは await を挟まず連続させる: 間に GitHub 呼び出し等の
        # await を置くと、その途中でクラッシュした場合に「遷移済みだがキューに無い」
        # 状態 (再適用時は APPROVE 相でないため再エンキューがスキップ) を招く。
        # ラベル更新 (best-effort) はキュー投入後に行う。
        extra: dict[str, Any] = {}
        if cmd.action == "reject" and cmd.feedback:
            extra["feedback"] = cmd.feedback
        elif cmd.action == "prototype_revise" and cmd.feedback:
            # 設計書を維持しつつ UI プロトタイプのみ更新する反復 (#145 Phase2)。
            extra["prototype_feedback"] = cmd.feedback
        await self._task_queue.enqueue(
            TaskRequest(
                issue_number=cmd.issue_number,
                repo=repo_config,
                phase=next_phase.value,
                priority=Priority.NORMAL,
                extra=extra,
            )
        )
        # ラベル更新は best-effort (失敗しても状態+キューは確定済み)。
        try:
            client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
            await client.replace_phase_label(repo_config, cmd.issue_number, f"phase:{next_phase.value}")
        except Exception as exc:
            logger.warning("review: ラベル更新に失敗 (#%d): %s", cmd.issue_number, exc)

        event_name = {
            "approve": "plan_approved",
            "reject": "plan_rejected",
            "prototype_revise": "prototype_revise_requested",
        }.get(cmd.action, "plan_rejected")
        await self._event_logger.track(
            event_name,
            issue_number=cmd.issue_number,
            phase="system",
            data={"action": cmd.action, "approver": cmd.approver},
        )

    async def _apply_split_review_command(
        self,
        cmd: ControlCommand,
        issue_key: IssueKey,
        repo_config: RepositoryConfig,
    ) -> None:
        """SPLIT 分割提案の承認/差し戻しを Web 経由で適用する (#150).

        - approve → 承認待ち解除 + SPLIT 実行ステップをエンキュー (子Issue作成へ)
        - reject  → 承認待ち解除 + SPLIT→CLARIFY 遷移 + 修正指示付き再エンキュー

        poller 経由の 👍 承認 (_handle_split_approved) / コメント修正
        (_handle_split_modified) と同じ振る舞いに合わせる。
        """
        # 承認待ちを解除してから処理する (二重適用防止)。
        self._state_machine.set_awaiting_split_approval(issue_key, False)

        if cmd.action == "approve":
            await self._task_queue.enqueue(
                TaskRequest(
                    issue_number=cmd.issue_number,
                    repo=repo_config,
                    phase=Phase.SPLIT.value,
                    priority=Priority.NORMAL,
                    extra={"step": "execute"},
                )
            )
            await self._event_logger.track(
                "split_approved",
                issue_number=cmd.issue_number,
                phase="system",
                data={"action": cmd.action, "approver": cmd.approver},
            )
            return

        # reject → CLARIFY へ戻して修正指示を渡す
        try:
            await self._state_machine.transition(issue_key, Phase.CLARIFY)
        except (InvalidTransitionError, KeyError) as exc:
            logger.warning("split-review: CLARIFY への遷移に失敗 (#%d): %s", cmd.issue_number, exc)
            return
        await self._task_queue.enqueue(
            TaskRequest(
                issue_number=cmd.issue_number,
                repo=repo_config,
                phase=Phase.CLARIFY.value,
                priority=Priority.NORMAL,
                extra={"modification_request": cmd.feedback or ""},
            )
        )
        try:
            client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
            await client.replace_phase_label(repo_config, cmd.issue_number, "phase:clarify")
        except Exception as exc:
            logger.warning("split-review: ラベル更新に失敗 (#%d): %s", cmd.issue_number, exc)
        await self._event_logger.track(
            "split_rejected",
            issue_number=cmd.issue_number,
            phase="system",
            data={"action": cmd.action, "approver": cmd.approver},
        )

    async def _apply_control_command(self, cmd: OperationalCommand) -> None:
        """1 件の運用コマンドを適用する."""
        if cmd.action == "shutdown":
            await self._handle_shutdown(cmd)
        elif cmd.action == "pause":
            await self._handle_pause(cmd)
        elif cmd.action == "resume":
            await self._handle_resume(cmd)
        elif cmd.action == "abort":
            await self._handle_abort(cmd)
        elif cmd.action == "poll_now":
            await self._handle_poll_now(cmd)
        elif cmd.action == "worktree_gc":
            await self._handle_worktree_gc(cmd)
        elif cmd.action == "enqueue_issue":
            await self._handle_enqueue_issue(cmd)
        elif cmd.action == "set_priority":
            await self._handle_set_priority(cmd)
        elif cmd.action == "reorder":
            await self._handle_reorder(cmd)
        elif cmd.action == "rewind":
            await self._handle_rewind(cmd)
        elif cmd.action == "retry_with_analysis":
            await self._handle_retry_with_analysis(cmd)

    async def _audit_control(self, event: str, cmd: OperationalCommand) -> None:
        """運用コマンドの適用を events.jsonl に監査記録する."""
        await self._event_logger.track(
            event,
            issue_number=cmd.issue_number or 0,
            phase="system",
            data={"action": cmd.action, "actor": cmd.actor},
        )

    async def _handle_pause(self, cmd: OperationalCommand) -> None:
        if cmd.issue_number is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        self._task_queue.pause(issue_key)
        await self._audit_control("issue_paused", cmd)

    async def _handle_resume(self, cmd: OperationalCommand) -> None:
        if cmd.issue_number is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        await self._task_queue.resume(issue_key)
        await self._audit_control("issue_resumed", cmd)

    async def _handle_abort(self, cmd: OperationalCommand) -> None:
        """abort: 実行中タスクを即時キャンセルし、worktree 掃除・SUSPENDED・ラベル付与."""
        if cmd.issue_number is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return

        await self._task_queue.cancel_task(issue_key)
        # pause/park を破棄し、キュー滞留中の分も含め以後の実行をドロップする
        # (park の resume 復活・キュー滞留タスクによる SUSPENDED 復活を防ぐ)。
        self._task_queue.mark_aborted(issue_key)

        repo_config = self._repo_config_for(issue_key[0])
        if repo_config is not None:
            try:
                await self._workspace_manager.remove_worktree(repo_config, cmd.issue_number)
            except Exception as exc:
                logger.warning("abort: worktree 掃除に失敗 (#%d): %s", cmd.issue_number, exc)
            try:
                client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
                await client.replace_phase_label(repo_config, cmd.issue_number, "phase:suspended")
            except Exception as exc:
                logger.warning("abort: ラベル付与に失敗 (#%d): %s", cmd.issue_number, exc)

        try:
            await self._state_machine.transition(issue_key, Phase.SUSPENDED)
        except (InvalidTransitionError, KeyError) as exc:
            logger.warning("abort: SUSPENDED への遷移に失敗 (#%d): %s", cmd.issue_number, exc)

        await self._audit_control("issue_aborted", cmd)

    async def _handle_poll_now(self, cmd: OperationalCommand) -> None:
        """poll_now: poller の待機を起こし、次のポーリングを前倒しする (#96)."""
        trigger = getattr(self._poller, "request_poll_now", None)
        if callable(trigger):
            trigger()
        else:
            logger.debug("poll_now: poller が request_poll_now 未対応のため無視")
        await self._audit_control("poll_now_requested", cmd)

    async def _handle_worktree_gc(self, cmd: OperationalCommand) -> None:
        """worktree_gc: 全 repo の孤児 worktree (未登録 or DONE) を掃除する (#96)."""
        removed = 0
        for repo in self._settings.repositories:
            repo_key = f"{repo.owner}/{repo.repo}"
            try:
                worktrees = await self._workspace_manager.list_worktrees(repo)
            except Exception as exc:
                logger.warning("worktree_gc: 一覧取得に失敗 (%s): %s", repo_key, exc)
                continue
            for path in worktrees:
                issue_number = _extract_worktree_issue_number(path.name)
                if issue_number is None or not self._is_orphan_worktree(repo_key, issue_number):
                    continue
                try:
                    await self._workspace_manager.remove_worktree(repo, issue_number)
                    removed += 1
                except Exception as exc:
                    logger.warning("worktree_gc: 削除に失敗 (%s #%d): %s", repo_key, issue_number, exc)
        logger.info("worktree_gc: 孤児 worktree %d 件を削除", removed)
        await self._audit_control("worktree_gc", cmd)

    def _is_orphan_worktree(self, repo_key: str, issue_number: int) -> bool:
        """worktree が孤児 (未登録 or DONE) かを判定する (#96 worktree_gc)."""
        issue_key = make_issue_key(repo_key, issue_number)
        if issue_key not in self._state_machine._states:
            return True
        return self._state_machine.get_phase(issue_key) is Phase.DONE

    async def _handle_enqueue_issue(self, cmd: OperationalCommand) -> None:
        """enqueue_issue: issue にトリガラベルを付与し、poller の検知フローへ載せる (#96).

        control.jsonl から直接キューへ投入せず、既存の「ラベル → poller 検知」経路に
        乗せることで、新規検知と再投入を同一フローへ集約する。
        """
        if cmd.issue_number is None:
            return
        repo_config = self._repo_for_enqueue(cmd.issue_number)
        if repo_config is None:
            logger.warning("enqueue_issue: repo を解決できません (#%d)", cmd.issue_number)
            return
        try:
            client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
            await client.add_label(repo_config, cmd.issue_number, repo_config.label)
        except Exception as exc:
            logger.warning("enqueue_issue: ラベル付与に失敗 (#%d): %s", cmd.issue_number, exc)
            return
        await self._audit_control("issue_enqueued", cmd)

    def _repo_for_enqueue(self, issue_number: int) -> RepositoryConfig | None:
        """enqueue_issue 対象の repo を解決する (#96).

        登録済み issue は state machine から repo を引く。未登録 (新規) でも、
        設定リポジトリが 1 件なら一意に決まるためそれを使う。複数 repo で未登録の
        場合は repo を特定できないため None (将来 #88 で repo 指定を追加予定)。
        """
        matches = [key for key in self._state_machine._states if key[1] == issue_number]
        if len(matches) == 1:
            return self._repo_config_for(matches[0][0])
        if len(self._settings.repositories) == 1:
            return self._settings.repositories[0]
        return None

    async def _handle_set_priority(self, cmd: OperationalCommand) -> None:
        """set_priority: キュー待ちタスクの優先度を変更する (#96)."""
        if cmd.issue_number is None or cmd.phase is None or cmd.priority is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        if self._task_queue.set_priority(issue_key, cmd.phase, cmd.priority):
            await self._audit_control("priority_changed", cmd)
        else:
            logger.info("set_priority: 対象がキュー待ちにありません (#%d %s)", cmd.issue_number, cmd.phase)

    async def _handle_reorder(self, cmd: OperationalCommand) -> None:
        """reorder: 指定順にキュー待ちタスクの優先度を振り直す (#96)."""
        if not cmd.order:
            return
        resolved: list[tuple[IssueKey, str]] = []
        for issue_number, phase in cmd.order:
            issue_key = self._resolve_issue_key(issue_number)
            if issue_key is not None:
                resolved.append((issue_key, phase))
        if resolved:
            self._task_queue.reorder(resolved)
            await self._audit_control("queue_reordered", cmd)

    async def _handle_rewind(self, cmd: OperationalCommand) -> None:
        """rewind: 成果物を保持したまま target フェーズへ巻き戻し再エンキューする (#96).

        abort と異なり worktree/PR は削除しない (成果物保持)。現フェーズ →
        SUSPENDED → target の 2-hop で遷移し、target の TaskRequest を積み直す。
        """
        if cmd.issue_number is None or cmd.target is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        target_phase = _parse_rewind_target(cmd.target)
        if target_phase is None:
            logger.warning("rewind: 不正な target '%s' (#%d)", cmd.target, cmd.issue_number)
            return

        # 2-hop: current → SUSPENDED → target。成果物 (worktree/PR) は消さない。
        try:
            await self._state_machine.transition(issue_key, Phase.SUSPENDED)
            await self._state_machine.transition(issue_key, target_phase)
        except (InvalidTransitionError, KeyError) as exc:
            logger.warning("rewind: 遷移に失敗 (#%d → %s): %s", cmd.issue_number, cmd.target, exc)
            return

        repo_config = self._repo_config_for(issue_key[0])
        if repo_config is None:
            logger.warning("rewind: repo を解決できません (#%d)", cmd.issue_number)
            return
        try:
            client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
            await client.replace_phase_label(repo_config, cmd.issue_number, f"phase:{target_phase.value}")
        except Exception as exc:
            logger.warning("rewind: ラベル更新に失敗 (#%d): %s", cmd.issue_number, exc)
        await self._task_queue.enqueue(
            TaskRequest(issue_number=cmd.issue_number, repo=repo_config, phase=target_phase.value)
        )
        await self._audit_control("issue_rewound", cmd)

    async def _handle_retry_with_analysis(self, cmd: OperationalCommand) -> None:
        """retry_with_analysis: 直近エラーを要約し再実行プロンプトに添えて再試行する (#96).

        abort と対で成果物を保持したまま再試行する。直近の phase_error イベントの
        要約を ``extra["feedback"]`` に載せ、既存の再実行プロンプト経路 (feedback)
        でエージェントへ渡す。

        再試行フェーズと state machine の相を一致させる:
        - 実行相 (PLAN/IMPLEMENT/REVISE) で滞留中ならそのフェーズを再試行。
        - 失敗して SUSPENDED 済みなら IMPLEMENT へ resume してから積む
          (state は SUSPENDED のまま IMPLEMENT を走らせる乖離を防ぐ)。
        - それ以外の相は再試行対象外 (誤った相の実行を防ぐ)。
        """
        if cmd.issue_number is None:
            return
        issue_key = self._resolve_issue_key(cmd.issue_number)
        if issue_key is None:
            return
        repo_config = self._repo_config_for(issue_key[0])
        if repo_config is None:
            logger.warning("retry_with_analysis: repo を解決できません (#%d)", cmd.issue_number)
            return

        current_phase = self._state_machine.get_phase(issue_key)
        if current_phase in _RETRYABLE_PHASES:
            retry_phase = current_phase
        elif current_phase is Phase.SUSPENDED:
            retry_phase = Phase.IMPLEMENT
            try:
                await self._state_machine.transition(issue_key, retry_phase)
            except (InvalidTransitionError, KeyError) as exc:
                logger.warning("retry_with_analysis: 再開遷移に失敗 (#%d): %s", cmd.issue_number, exc)
                return
            try:
                client = await self._account_manager.get_client_for_repo(repo_config.owner, repo_config.repo)
                await client.replace_phase_label(repo_config, cmd.issue_number, f"phase:{retry_phase.value}")
            except Exception as exc:
                logger.warning("retry_with_analysis: ラベル更新に失敗 (#%d): %s", cmd.issue_number, exc)
        else:
            logger.info(
                "retry_with_analysis: 再試行できない相のため無視 (#%d %s)",
                cmd.issue_number,
                current_phase.value,
            )
            return

        error_summary = self._read_last_error_summary(cmd.issue_number)
        extra: dict[str, Any] = {"retry_with_analysis": True}
        if error_summary:
            extra["feedback"] = f"前回の失敗を踏まえて再実行してください。直近のエラー:\n{error_summary}"
        await self._task_queue.enqueue(
            TaskRequest(
                issue_number=cmd.issue_number,
                repo=repo_config,
                phase=retry_phase.value,
                priority=Priority.HIGH,
                extra=extra,
            )
        )
        await self._audit_control("issue_retry_with_analysis", cmd)

    def _read_last_error_summary(self, issue_number: int, max_chars: int = 1000) -> str | None:
        """Issue の events.jsonl から直近の phase_error 要約を best-effort で読む (#96).

        失敗 (不在/壊れ) は None。詳細プロンプト整形は prompt_enhancer 側に委ねる。
        """
        events_file = self._event_logger.log_dir / f"issue-{issue_number}" / "events.jsonl"
        try:
            lines = events_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("event") != "phase_error":
                continue
            data = record.get("data")
            message = data.get("error") if isinstance(data, dict) else None
            if isinstance(message, str) and message:
                return message[:max_chars]
            return None
        return None

    async def _handle_shutdown(self, cmd: OperationalCommand) -> None:
        """shutdown: drain を要求し、in-flight 完了後に graceful stop する."""
        await self._audit_control("orchestrator_shutdown_requested", cmd)
        self._task_queue.request_drain()
        # stop() は control ループ自身を cancel するため、detached タスクで実行する。
        self._shutdown_task = asyncio.create_task(self._drain_then_stop(), name="control-shutdown")

    async def _drain_then_stop(self) -> None:
        """in-flight タスクの完了を待ってから (上限付き) 停止する.

        detached タスクとして実行されるため、例外はここでログに留め
        "Task exception was never retrieved" を避ける。stop() は _running
        ガードで冪等。
        """
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._SHUTDOWN_DRAIN_TIMEOUT_SEC
            while self._task_queue.get_status()["active"] > 0 and loop.time() < deadline:
                await asyncio.sleep(1.0)
            await self.stop()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("drain-then-stop に失敗", exc_info=True)

    # ------------------------------------------------------------------
    async def _reenqueue_pending_tasks(self) -> None:
        """起動時に未完了フェーズのタスクを再エンキューする.

        前回のセッションで中断されたタスクを再開するため、
        永続化されたIssue状態から「レビュー待ち」以外のアクティブフェーズを
        タスクキューに投入する。
        """
        # Phases that need active processing (not waiting for human input)
        # U5 (#83): 12 フェーズに統合済み
        active_phases = {
            Phase.INTAKE,
            Phase.CLARIFY,
            Phase.PLAN,
            Phase.IMPLEMENT,
            Phase.REVISE,
            Phase.SPLIT,
        }

        for issue_key, state in self._state_machine._states.items():
            if state.phase in active_phases:
                # Find the repo config for this issue
                repo_config = None
                for repo in self._settings.repositories:
                    if f"{repo.owner}/{repo.repo}" == state.repo:
                        repo_config = repo
                        break

                issue_number = issue_key[1]
                if repo_config is not None:
                    await self._task_queue.enqueue(
                        TaskRequest(
                            issue_number=issue_number,
                            repo=repo_config,
                            phase=state.phase.value,
                        )
                    )
                    logger.info(
                        "Re-enqueued pending task: issue=#%s phase=%s",
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
                except KeyError as exc:
                    logger.warning("Event routing skipped (unregistered issue): %s", exc)
                except Exception as exc:
                    logger.error("Event routing error: %s", exc, exc_info=True)
                    await self._notifier.notify(
                        f"Event routing error: {exc}",
                        level="error",
                        metadata={
                            "notification_type": "system_error",
                        },
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
        issue_key: IssueKey = make_issue_key(repo_key, issue_number)

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
                logger.debug(
                    "issue #%d: building context (worktree=%s, phase=%s)",
                    issue_number,
                    worktree_path,
                    phase,
                )
                try:
                    context = await self._context_engine.build_context(
                        worktree_path=worktree_path,
                        issue_body=issue_body,
                        phase=phase,
                        issue_number=issue_number,
                    )
                    logger.debug("issue #%d: context built (%d chars)", issue_number, len(context))
                except Exception as ctx_err:
                    logger.warning(
                        "Failed to build context for issue #%d: %s",
                        issue_number,
                        ctx_err,
                    )

            # Dispatch phase execution (guard prevents EventRouter from
            # transitioning state while the executor is running)
            logger.debug("issue #%d: dispatching phase=%s (guard acquired)", issue_number, phase)
            async with self._execution_guard.guard(issue_key):
                result = await self._phase_dispatcher.dispatch(
                    phase,
                    issue_number=issue_number,
                    repo=task.repo,
                    worktree_path=worktree_path,
                    context=context,
                    resume_session_id=task.extra.get("resume_session_id"),
                    extra=task.extra,
                )
            logger.debug(
                "issue #%d: phase=%s dispatch returned (next_phase=%s, cost=$%s)",
                issue_number,
                phase,
                result.next_phase,
                result.cost_usd,
            )

            await self._event_logger.track(
                "phase_completed",
                issue_number=issue_number,
                phase=phase,
                data={
                    "status": "success",
                    "output_summary": result.output_summary,
                    "cost_usd": result.cost_usd,
                    "next_phase": result.next_phase,
                },
            )

            # Transition to next phase if specified (for NullPhaseDispatcher)
            if result.next_phase is not None:
                next_phase = Phase(result.next_phase)
                await self._state_machine.transition(issue_key, next_phase)

            # Auto-enqueue next task if the phase changed to an active phase
            # (Real executors handle transitions internally, so we check current phase)
            current_phase = self._state_machine.get_phase(issue_key)
            # U5 (#83): 12 フェーズに統合済み
            active_phases = {
                Phase.INTAKE,
                Phase.CLARIFY,
                Phase.PLAN,
                Phase.IMPLEMENT,
                Phase.REVISE,
                Phase.SPLIT,
            }
            # Compare with current task's phase (handle both hyphen and underscore)
            try:
                task_phase = Phase(phase.replace("_", "-"))
            except ValueError:
                task_phase = None
            if (
                current_phase in active_phases
                and current_phase != task_phase
                and not self._task_queue.is_task_queued(issue_key, current_phase.value)
            ):
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

            # Replay any events that were deferred while the guard was held
            deferred = await self._execution_guard.drain_deferred(issue_key)
            for deferred_event in deferred:
                await self._event_router.route(deferred_event)

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
        repo_key = task.repo_key
        issue_key: IssueKey = make_issue_key(repo_key, issue_number)
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

        state = self._state_machine.get_state(issue_key)
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
                await self._state_machine.transition(issue_key, Phase.SUSPENDED)
            except Exception as transition_err:
                logger.error(
                    "Failed to suspend issue #%d: %s",
                    issue_number,
                    transition_err,
                )

            try:
                await self._notifier.notify(
                    f"Issue #{issue_number} suspended due to error: {error}",
                    level="error",
                    metadata={
                        "notification_type": "suspended",
                        "issue": issue_number,
                        "phase": task.phase,
                        "error": str(error),
                        "next_action": "→ 手動での確認をお願いします",
                    },
                )
            except Exception as notify_err:
                logger.warning(
                    "Failed to send suspension notification for issue #%d: %s",
                    issue_number,
                    notify_err,
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

    async def build_health_snapshot(
        self,
        accounts: dict[str, bool] | None = None,
        *,
        lightweight: bool = False,
    ) -> dict[str, Any]:
        """health.json に書き出す稼働統計を構築する (#97).

        各ソースは best-effort で収集し、失敗したものは None/空に倒す。
        health.json の書き出し自体は必ず成功させるため、ここで例外は投げない。

        Args:
            accounts: health_check() の結果 (コンポーネント名→健全性)。None なら {}。
            lightweight: True の場合、ネットワーク (rate_limit) / subprocess
                (worktrees) の収集をスキップして None にする。停止経路で graceful
                stop を GitHub 応答待ちでブロックさせないために使う。

        Returns:
            health.json のスキーマに沿った dict。
        """
        queue_status = self._task_queue.get_status()
        snapshot: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "running": self._running,
            "queue": {
                "active": queue_status.get("active", 0),
                "queued": queue_status.get("queued", 0),
                "max_total": queue_status.get("max_total", 0),
            },
            "repositories": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
            "accounts": accounts or {},
            # lightweight 時はネットワーク/subprocess を呼ばない (in-memory のみ)。
            "rate_limit": None if lightweight else await self._collect_rate_limit(),
            "worktrees": None if lightweight else await self._collect_worktree_count(),
            "last_poll": self._collect_last_poll(),
        }
        return snapshot

    async def _collect_rate_limit(self) -> dict[str, int] | None:
        """最初の repo のレート制限を best-effort で取得する (失敗時 None)."""
        repos = self._settings.repositories
        if not repos:
            return None
        try:
            repo = repos[0]
            client = await self._account_manager.get_client_for_repo(repo.owner, repo.repo)
            status = await client.get_rate_limit()
            # reset (Unix 秒) はトークン消費タイミングのフィンガープリントになり
            # 得るため snapshot には含めない。Web UI は remaining/limit のみ参照 (#115)。
            return {
                "remaining": status.remaining,
                "limit": status.limit,
            }
        except Exception as exc:
            logger.warning("health snapshot: rate_limit 取得に失敗: %s", exc)
            return None

    async def _collect_worktree_count(self) -> int | None:
        """全 repo の worktree 件数を best-effort で合算する (失敗時 None)."""
        try:
            total = 0
            for repo in self._settings.repositories:
                worktrees = await self._workspace_manager.list_worktrees(repo)
                total += len(worktrees)
            return total
        except Exception as exc:
            logger.warning("health snapshot: worktrees 取得に失敗: %s", exc)
            return None

    def _collect_last_poll(self) -> dict[str, str]:
        """poller の最終ポーリング時刻を best-effort で取得する (失敗/未対応で {})."""
        getter = getattr(self._poller, "get_last_poll_times", None)
        if not callable(getter):
            return {}
        try:
            result = getter()
            if isinstance(result, dict):
                return result
        except Exception as exc:
            logger.warning("health snapshot: last_poll 取得に失敗: %s", exc)
        return {}

    async def _write_health_json(self, snapshot: dict[str, Any]) -> None:
        """health.json を atomic (tmp + replace) に書き出す (#97).

        書き出し失敗は warning ログのみ。ループ/停止処理を止めない。

        Args:
            snapshot: build_health_snapshot() が返した dict。
        """
        try:
            await asyncio.to_thread(self._write_health_json_sync, snapshot)
        except Exception as exc:
            logger.warning("health.json の書き出しに失敗: %s", exc)

    def _write_health_json_sync(self, snapshot: dict[str, Any]) -> None:
        """health.json の同期書き出し (tmp + replace + 0o600, #115)."""
        atomic_write_text(self._health_file, json.dumps(snapshot, ensure_ascii=False, indent=2))

    async def _emit_health_snapshot(self, *, running: bool | None = None, lightweight: bool = False) -> None:
        """health_check 実行 → snapshot 構築 → health.json 書き出し (best-effort).

        Args:
            running: True/False を渡すと snapshot の running を上書きする
                (停止直前の running=False 書き出し用)。None なら現在値。
            lightweight: True の場合、health_check (アカウント検証ネットワーク) も
                rate_limit / worktrees の収集もスキップする。停止経路で graceful
                stop を GitHub 応答待ちでブロックさせないために使う。
        """
        if lightweight:
            results: dict[str, bool] = {}
        else:
            try:
                results = await self.health_check()
            except Exception as exc:
                logger.warning("health snapshot: health_check に失敗: %s", exc)
                results = {}
        snapshot = await self.build_health_snapshot(results, lightweight=lightweight)
        if running is not None:
            snapshot["running"] = running
        await self._write_health_json(snapshot)

    async def _health_check_loop(self) -> None:
        """定期的なヘルスチェックループ.

        起動直後に1回 health.json を出し、以降 5分間隔で health_check() を
        実行する。失敗時は通知し、毎周回 health.json を書き出す。ループを
        抜ける直前に running=False の snapshot を best-effort で書き出す。
        """
        interval_sec = 300  # 5 minutes
        try:
            # 起動直後 (sleep 前) に 1 回 health.json を出す。
            await self._emit_health_snapshot()
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
                            metadata={
                                "notification_type": "health_check",
                            },
                        )
                    # 毎周回 health.json を書き出す (health_check 結果を引き継ぐ)。
                    snapshot = await self.build_health_snapshot(results)
                    await self._write_health_json(snapshot)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("Health check loop error: %s", exc, exc_info=True)
        finally:
            # graceful stop / CancelledError 経路でも running=False を書き出す。
            # lightweight: 停止時にネットワーク/subprocess を呼ばず、GitHub 応答待ちで
            # stop() の gather (タイムアウトなし) をブロックさせない。
            await self._emit_health_snapshot(running=False, lightweight=True)

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
