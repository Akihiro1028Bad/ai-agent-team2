"""Orchestrator の単体テスト."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.config.settings import (
    AppSettings,
    ConcurrencyConfig,
    RepositoryConfig,
    RetryConfig,
)
from ai_agent_orchestrator.models import ErrorCategory, Phase
from ai_agent_orchestrator.orchestrator.orchestrator import (
    NullEventRouter,
    NullNotifier,
    NullPhaseDispatcher,
    NullPoller,
    Orchestrator,
    _NullPhaseResult,
    _OrchestratorTaskExecutor,
)
from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest
from ai_agent_orchestrator.state_persistence import StatePersistence

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path) -> AppSettings:
    """最小限の AppSettings を生成する."""
    return AppSettings(
        repositories=[
            RepositoryConfig(owner="test-owner", repo="test-repo"),
        ],
        concurrency=ConcurrencyConfig(max_total=1, max_per_repo=1),
        retry=RetryConfig(max_attempts=2, backoff_minutes=[0, 0]),
        workspace_dir=str(tmp_path / "workspaces"),
        polling_interval_sec=30,
    )


class FakeRepo:
    """TaskRequest.repo に渡す最小限のオブジェクト."""

    def __init__(self, owner: str = "test-owner", repo: str = "test-repo") -> None:
        self._owner = owner
        self._repo = repo

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def repo(self) -> str:
        return self._repo


@pytest.fixture
def tmp_settings(tmp_path: Path) -> AppSettings:
    """テスト用の AppSettings を返す."""
    return _make_settings(tmp_path)


@pytest.fixture
def orchestrator(tmp_path: Path) -> Orchestrator:
    """最小構成の Orchestrator を返す."""
    settings = _make_settings(tmp_path)
    return Orchestrator(
        settings,
        notifier=NullNotifier(),
        poller=NullPoller(),
        event_router=NullEventRouter(),
        phase_dispatcher=NullPhaseDispatcher(),
    )


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestOrchestratorInit:
    """Orchestrator.__init__ のテスト."""

    def test_init_with_minimal_config(self, tmp_settings: AppSettings) -> None:
        """最小構成で初期化できること."""
        orch = Orchestrator(tmp_settings)
        assert orch.settings is tmp_settings
        assert not orch.is_running

    def test_init_creates_task_queue_with_concurrency(self, tmp_settings: AppSettings) -> None:
        """concurrency 設定が TaskQueue に反映されること."""
        orch = Orchestrator(tmp_settings)
        status = orch.task_queue.get_status()
        assert status["max_total"] == 1
        assert status["active"] == 0
        assert status["queued"] == 0

    def test_init_with_slack_config(self, tmp_path: Path) -> None:
        """Slack 設定ありで SlackNotifier が使われること."""
        from ai_agent_orchestrator.config.settings import SlackConfig
        from ai_agent_orchestrator.notifications.slack import SlackNotifier

        settings = _make_settings(tmp_path)
        settings.slack = SlackConfig(
            webhook_url="https://hooks.slack.com/test",
            default_channel="#test",
        )
        orch = Orchestrator(settings)
        assert isinstance(orch._notifier, SlackNotifier)

    def test_init_with_null_notifier(self, orchestrator: Orchestrator) -> None:
        """NullNotifier が使われること."""
        assert isinstance(orchestrator._notifier, NullNotifier)

    def test_init_with_injected_dependencies(self, tmp_settings: AppSettings) -> None:
        """依存性注入でカスタムコンポーネントを使えること."""
        mock_notifier = NullNotifier()
        mock_poller = NullPoller()
        orch = Orchestrator(
            tmp_settings,
            notifier=mock_notifier,
            poller=mock_poller,
        )
        assert orch._notifier is mock_notifier
        assert orch._poller is mock_poller

    def test_get_status(self, orchestrator: Orchestrator) -> None:
        """get_status が正しい構造を返すこと."""
        status = orchestrator.get_status()
        assert status["running"] is False
        assert "task_queue" in status
        assert status["repositories"] == ["test-owner/test-repo"]


# ---------------------------------------------------------------------------
# Start / Stop lifecycle tests
# ---------------------------------------------------------------------------


class TestOrchestratorLifecycle:
    """start() / stop() のライフサイクルテスト."""

    async def test_start_sets_running(self, orchestrator: Orchestrator) -> None:
        """start() 後に is_running が True になること."""
        await orchestrator.start()
        try:
            assert orchestrator.is_running
        finally:
            await orchestrator.stop()

    async def test_stop_clears_running(self, orchestrator: Orchestrator) -> None:
        """stop() 後に is_running が False になること."""
        await orchestrator.start()
        await orchestrator.stop()
        assert not orchestrator.is_running

    async def test_start_loads_persistence(self, tmp_path: Path) -> None:
        """start() で永続化ストレージから状態を復元すること."""
        settings = _make_settings(tmp_path)
        persistence = StatePersistence(state_file=tmp_path / "workspaces" / "state.json")
        orch = Orchestrator(
            settings,
            persistence=persistence,
            notifier=NullNotifier(),
            poller=NullPoller(),
        )

        # Should not raise even with empty state file
        await orch.start()
        try:
            assert orch.is_running
        finally:
            await orch.stop()

    async def test_double_start_is_noop(self, orchestrator: Orchestrator) -> None:
        """二重起動は無視されること."""
        await orchestrator.start()
        try:
            await orchestrator.start()  # should not raise
            assert orchestrator.is_running
        finally:
            await orchestrator.stop()

    async def test_stop_without_start_is_noop(self, orchestrator: Orchestrator) -> None:
        """start() 前の stop() は無視されること."""
        await orchestrator.stop()  # should not raise
        assert not orchestrator.is_running

    async def test_start_creates_worker_tasks(self, tmp_path: Path) -> None:
        """start() でワーカータスクが concurrency.max_total 個作られること."""
        settings = _make_settings(tmp_path)
        settings.concurrency.max_total = 2
        orch = Orchestrator(
            settings,
            notifier=NullNotifier(),
            poller=NullPoller(),
        )
        await orch.start()
        try:
            assert len(orch._worker_tasks) == 2
        finally:
            await orch.stop()

    async def test_stop_cancels_tasks(self, orchestrator: Orchestrator) -> None:
        """stop() で全タスクがキャンセルされること."""
        await orchestrator.start()
        assert orchestrator._health_task is not None
        await orchestrator.stop()
        assert orchestrator._health_task is None
        assert len(orchestrator._worker_tasks) == 0


# ---------------------------------------------------------------------------
# _execute_task tests
# ---------------------------------------------------------------------------


class TestExecuteTask:
    """_execute_task のテスト."""

    async def test_execute_task_dispatches_to_phase_dispatcher(self, tmp_path: Path) -> None:
        """_execute_task がフェーズディスパッチャに委譲すること."""
        settings = _make_settings(tmp_path)
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock(return_value=_NullPhaseResult())

        orch = Orchestrator(
            settings,
            phase_dispatcher=dispatcher,
            notifier=NullNotifier(),
        )
        # Register issue so transitions work
        orch.state_machine.register_issue(42, "test-owner/test-repo")

        task = TaskRequest(
            issue_number=42,
            repo=FakeRepo(),
            phase="type_detection",
            extra={"worktree_path": "", "issue_body": ""},
        )

        await orch._execute_task(task)

        call_kwargs = dispatcher.dispatch.call_args.kwargs
        assert call_kwargs["issue_number"] == 42
        assert call_kwargs["worktree_path"] == ""
        assert call_kwargs["context"] == ""
        assert call_kwargs["resume_session_id"] is None
        # repo is now the RepositoryConfig object, not a string
        assert hasattr(call_kwargs["repo"], "owner")

    async def test_execute_task_transitions_on_next_phase(self, tmp_path: Path) -> None:
        """dispatch の結果に next_phase がある場合に遷移すること."""
        settings = _make_settings(tmp_path)

        phase_result = MagicMock()
        phase_result.next_phase = Phase.ANALYSIS.value
        phase_result.output_summary = "done"
        phase_result.cost_usd = 0.1

        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock(return_value=phase_result)

        orch = Orchestrator(
            settings,
            phase_dispatcher=dispatcher,
            notifier=NullNotifier(),
        )
        orch.state_machine.register_issue(42, "test-owner/test-repo")
        orch.state_machine.set_issue_type(("test-owner/test-repo", 42), "bug")

        task = TaskRequest(
            issue_number=42,
            repo=FakeRepo(),
            phase="type_detection",
            extra={},
        )

        await orch._execute_task(task)

        assert orch.state_machine.get_phase(("test-owner/test-repo", 42)) == Phase.ANALYSIS

    async def test_execute_task_handles_error_and_suspends(self, tmp_path: Path) -> None:
        """dispatch でエラーが発生した場合に SUSPENDED に遷移すること."""
        settings = _make_settings(tmp_path)

        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock(side_effect=RuntimeError("unexpected error"))

        notifier = AsyncMock()
        notifier.notify = AsyncMock()
        notifier.close = AsyncMock()

        orch = Orchestrator(
            settings,
            phase_dispatcher=dispatcher,
            notifier=notifier,
        )
        # Register issue and move to ANALYSIS (which can transition to SUSPENDED)
        orch.state_machine.register_issue(42, "test-owner/test-repo")
        orch.state_machine.set_issue_type(("test-owner/test-repo", 42), "bug")
        await orch.state_machine.transition(("test-owner/test-repo", 42), Phase.ANALYSIS)

        task = TaskRequest(
            issue_number=42,
            repo=FakeRepo(),
            phase="analysis",
            extra={},
        )

        await orch._execute_task(task)

        assert orch.state_machine.get_phase(("test-owner/test-repo", 42)) == Phase.SUSPENDED
        notifier.notify.assert_awaited()

    async def test_execute_task_builds_context(self, tmp_path: Path) -> None:
        """worktree_path が指定されている場合にコンテキストを構築すること."""
        settings = _make_settings(tmp_path)

        # Create a fake worktree directory
        worktree = tmp_path / "worktree"
        worktree.mkdir()

        context_engine = AsyncMock()
        context_engine.build_context = AsyncMock(return_value="## Context\ntest context")

        phase_result = _NullPhaseResult()
        dispatcher = AsyncMock()
        dispatcher.dispatch = AsyncMock(return_value=phase_result)

        orch = Orchestrator(
            settings,
            phase_dispatcher=dispatcher,
            notifier=NullNotifier(),
            context_engine=context_engine,
        )
        orch.state_machine.register_issue(42, "test-owner/test-repo")

        task = TaskRequest(
            issue_number=42,
            repo=FakeRepo(),
            phase="type_detection",
            extra={
                "worktree_path": str(worktree),
                "issue_body": "test body",
            },
        )

        await orch._execute_task(task)

        context_engine.build_context.assert_awaited_once_with(
            worktree_path=str(worktree),
            issue_body="test body",
            phase="type_detection",
            issue_number=42,
        )

        # Context should be passed to dispatcher
        call_kwargs = dispatcher.dispatch.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs["context"] == "## Context\ntest context"


# ---------------------------------------------------------------------------
# Error classification tests
# ---------------------------------------------------------------------------


class TestErrorClassification:
    """_classify_error のテスト."""

    def test_timeout_error(self) -> None:
        assert Orchestrator._classify_error(TimeoutError("connection timeout")) == ErrorCategory.TRANSIENT

    def test_rate_limit_error(self) -> None:
        assert Orchestrator._classify_error(Exception("rate limit exceeded")) == ErrorCategory.TRANSIENT

    def test_auth_error(self) -> None:
        assert Orchestrator._classify_error(Exception("401 Unauthorized")) == ErrorCategory.AUTH

    def test_git_conflict_error(self) -> None:
        assert Orchestrator._classify_error(Exception("merge conflict")) == ErrorCategory.GIT_CONFLICT

    def test_ci_failure_error(self) -> None:
        assert Orchestrator._classify_error(Exception("CI check failed")) == ErrorCategory.CI_FAILURE

    def test_unknown_error_is_output_invalid(self) -> None:
        assert Orchestrator._classify_error(Exception("something weird")) == ErrorCategory.OUTPUT_INVALID


# ---------------------------------------------------------------------------
# Health check tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """health_check のテスト."""

    async def test_health_check_returns_results(self, tmp_path: Path) -> None:
        """health_check がアカウント検証結果を返すこと."""
        settings = _make_settings(tmp_path)
        account_mgr = AsyncMock()
        account_mgr.verify_all = AsyncMock(return_value={"default": True})

        orch = Orchestrator(
            settings,
            account_manager=account_mgr,
            notifier=NullNotifier(),
        )

        results = await orch.health_check()
        assert results == {"github/default": True}

    async def test_health_check_handles_failure(self, tmp_path: Path) -> None:
        """health_check が例外時に False を返すこと."""
        settings = _make_settings(tmp_path)
        account_mgr = AsyncMock()
        account_mgr.verify_all = AsyncMock(side_effect=Exception("network error"))

        orch = Orchestrator(
            settings,
            account_manager=account_mgr,
            notifier=NullNotifier(),
        )

        results = await orch.health_check()
        assert results == {"github": False}


# ---------------------------------------------------------------------------
# Null component tests
# ---------------------------------------------------------------------------


class TestNullComponents:
    """Null 実装のテスト."""

    async def test_null_notifier(self) -> None:
        notifier = NullNotifier()
        await notifier.notify("test message")
        await notifier.close()

    async def test_null_event_router(self) -> None:
        router = NullEventRouter()
        await router.route({"type": "test"})

    async def test_null_phase_dispatcher(self) -> None:
        dispatcher = NullPhaseDispatcher()
        result = await dispatcher.dispatch(
            "test",
            issue_number=1,
            repo="owner/repo",
            worktree_path="/tmp",
            context="",
        )
        assert result.next_phase is None
        assert result.output_summary == ""
        assert result.cost_usd == 0.0

    async def test_null_phase_result(self) -> None:
        result = _NullPhaseResult()
        assert result.next_phase is None
        assert result.output_summary == ""
        assert result.cost_usd == 0.0


# ---------------------------------------------------------------------------
# OrchestratorTaskExecutor tests
# ---------------------------------------------------------------------------


class TestOrchestratorTaskExecutor:
    """_OrchestratorTaskExecutor のテスト."""

    async def test_delegates_to_orchestrator(self, tmp_path: Path) -> None:
        """execute が orchestrator._execute_task に委譲すること."""
        settings = _make_settings(tmp_path)
        orch = Orchestrator(settings, notifier=NullNotifier())
        orch._execute_task = AsyncMock()  # type: ignore[method-assign]

        executor = _OrchestratorTaskExecutor(orch)
        task = TaskRequest(
            issue_number=1,
            repo=FakeRepo(),
            phase="test",
        )
        await executor.execute(task)
        orch._execute_task.assert_awaited_once_with(task)
