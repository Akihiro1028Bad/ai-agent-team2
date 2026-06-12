"""Orchestrator の ControlBus 消費ループ関連テスト (#87)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.config.settings import (
    AppSettings,
    ConcurrencyConfig,
    RepositoryConfig,
)
from ai_agent_orchestrator.models import Phase, make_issue_key
from ai_agent_orchestrator.orchestrator.orchestrator import (
    NullEventRouter,
    NullNotifier,
    NullPhaseDispatcher,
    NullPoller,
    Orchestrator,
)

REPO = "test-owner/test-repo"


def _make_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        repositories=[RepositoryConfig(owner="test-owner", repo="test-repo")],
        concurrency=ConcurrencyConfig(max_total=2, max_per_repo=1),
        workspace_dir=str(tmp_path / "workspaces"),
    )


def _make_orchestrator(tmp_path: Path, **kwargs: object) -> Orchestrator:
    settings = _make_settings(tmp_path)
    defaults: dict[str, object] = {
        "notifier": NullNotifier(),
        "poller": NullPoller(),
        "event_router": NullEventRouter(),
        "phase_dispatcher": NullPhaseDispatcher(),
    }
    defaults.update(kwargs)
    return Orchestrator(settings, **defaults)  # type: ignore[arg-type]


def _write_control(orch: Orchestrator, *lines: dict[str, object]) -> None:
    path = orch._control_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


class TestControlConsume:
    async def test_pause_marks_issue_paused(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(orch, {"action": "pause", "issue": 5, "actor": "test-owner"})

        await orch._consume_control_commands()

        assert orch._task_queue.is_paused(make_issue_key(REPO, 5))
        assert orch._control_offset == 1

    async def test_resume_clears_pause(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(
            orch,
            {"action": "pause", "issue": 5, "actor": "test-owner"},
            {"action": "resume", "issue": 5, "actor": "test-owner"},
        )

        await orch._consume_control_commands()

        assert not orch._task_queue.is_paused(make_issue_key(REPO, 5))

    async def test_unauthorized_actor_ignored(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(orch, {"action": "pause", "issue": 5, "actor": "mallory"})

        await orch._consume_control_commands()

        # 認可外 actor は無視されるが offset は進む (再処理しない)
        assert not orch._task_queue.is_paused(make_issue_key(REPO, 5))
        assert orch._control_offset == 1

    async def test_abort_cancels_cleans_and_suspends(self, tmp_path: Path) -> None:
        workspace = AsyncMock()
        account_mgr = AsyncMock()
        client = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(return_value=client)
        orch = _make_orchestrator(tmp_path, workspace_manager=workspace, account_manager=account_mgr)
        orch._state_machine.register_issue(7, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(orch, {"action": "abort", "issue": 7, "actor": "test-owner"})

        await orch._consume_control_commands()

        workspace.remove_worktree.assert_awaited_once()
        client.replace_phase_label.assert_awaited_once()
        assert orch._state_machine.get_phase(make_issue_key(REPO, 7)) is Phase.SUSPENDED

    async def test_shutdown_requests_drain(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        _write_control(orch, {"action": "shutdown", "actor": "test-owner"})

        await orch._consume_control_commands()

        assert orch._task_queue.is_draining
        # detached の停止タスクは後始末する (テスト環境で stop を完走させない)
        if orch._shutdown_task is not None:
            orch._shutdown_task.cancel()

    async def test_offset_persisted_across_instances(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(orch, {"action": "pause", "issue": 5, "actor": "test-owner"})

        await orch._consume_control_commands()
        assert orch._control_offset == 1

        # 同じ workspace の新インスタンスは offset を引き継ぐ (処理済みを再適用しない)
        orch2 = _make_orchestrator(tmp_path)
        assert orch2._load_control_offset() == 1


class TestExtendedCommands:
    """#96 Unit B: poll_now / worktree_gc / enqueue_issue."""

    async def test_poll_now_triggers_poller(self, tmp_path: Path) -> None:
        poller = MagicMock()
        orch = _make_orchestrator(tmp_path, poller=poller)
        _write_control(orch, {"action": "poll_now", "actor": "test-owner"})

        await orch._consume_control_commands()

        poller.request_poll_now.assert_called_once()

    async def test_poll_now_noop_when_poller_lacks_hook(self, tmp_path: Path) -> None:
        # NullPoller は request_poll_now を持たない → 例外を出さず素通り
        orch = _make_orchestrator(tmp_path)
        _write_control(orch, {"action": "poll_now", "actor": "test-owner"})

        await orch._consume_control_commands()

        assert orch._control_offset == 1

    async def test_enqueue_issue_adds_trigger_label(self, tmp_path: Path) -> None:
        account_mgr = AsyncMock()
        client = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(return_value=client)
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        _write_control(orch, {"action": "enqueue_issue", "issue": 9, "actor": "test-owner"})

        await orch._consume_control_commands()

        repo = orch._settings.repositories[0]
        client.add_label.assert_awaited_once_with(repo, 9, repo.label)

    async def test_worktree_gc_removes_only_orphans(self, tmp_path: Path) -> None:
        workspace = AsyncMock()
        workspace.list_worktrees = AsyncMock(
            return_value=[
                Path("/wt/feature-issue-7"),  # 未登録 → 孤児 → 削除
                Path("/wt/feature-issue-8"),  # 実行中 (登録済み) → 保持
                Path("/wt/feature-issue-9"),  # DONE → 孤児 → 削除
            ]
        )
        orch = _make_orchestrator(tmp_path, workspace_manager=workspace)
        orch._state_machine.register_issue(8, REPO, initial_phase=Phase.IMPLEMENT)
        orch._state_machine.register_issue(9, REPO, initial_phase=Phase.DONE)
        _write_control(orch, {"action": "worktree_gc", "actor": "test-owner"})

        await orch._consume_control_commands()

        repo = orch._settings.repositories[0]
        removed = {call.args[1] for call in workspace.remove_worktree.await_args_list}
        assert removed == {7, 9}
        for call in workspace.remove_worktree.await_args_list:
            assert call.args[0] is repo


class TestPriorityCommands:
    """#96 Unit C: set_priority / reorder."""

    async def test_set_priority_changes_queued_priority(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.models import TaskRequest

        orch = _make_orchestrator(tmp_path)
        repo = orch._settings.repositories[0]
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        await orch._task_queue.enqueue(TaskRequest(issue_number=5, repo=repo, phase="implement", priority=5))
        _write_control(
            orch, {"action": "set_priority", "issue": 5, "phase": "implement", "priority": 1, "actor": "test-owner"}
        )

        await orch._consume_control_commands()

        entry = orch._task_queue.get_queue_snapshot()["queued"][0]
        assert entry["priority"] == 1

    async def test_reorder_changes_dequeue_order(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.models import TaskRequest

        orch = _make_orchestrator(tmp_path)
        repo = orch._settings.repositories[0]
        for n, phase in ((1, "plan"), (2, "implement")):
            orch._state_machine.register_issue(n, REPO, initial_phase=Phase.IMPLEMENT)
            await orch._task_queue.enqueue(TaskRequest(issue_number=n, repo=repo, phase=phase, priority=5))
        _write_control(
            orch,
            {
                "action": "reorder",
                "order": [{"issue": 2, "phase": "implement"}, {"issue": 1, "phase": "plan"}],
                "actor": "test-owner",
            },
        )

        await orch._consume_control_commands()

        first = await orch._task_queue.dequeue()
        assert first.issue_number == 2


class TestRewind:
    """#96 Unit D: rewind (成果物保持の 2-hop 巻き戻し + 再エンキュー)."""

    async def test_rewind_resumes_target_and_reenqueues(self, tmp_path: Path) -> None:
        workspace = AsyncMock()
        account_mgr = AsyncMock()
        client = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(return_value=client)
        orch = _make_orchestrator(tmp_path, workspace_manager=workspace, account_manager=account_mgr)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        _write_control(orch, {"action": "rewind", "issue": 5, "target": "plan", "actor": "test-owner"})

        await orch._consume_control_commands()

        # 受け入れ条件: target フェーズへ戻り、そのフェーズが再エンキューされる
        assert orch._state_machine.get_phase(make_issue_key(REPO, 5)) is Phase.PLAN
        queued = orch._task_queue.get_queue_snapshot()["queued"]
        assert any(q["phase"] == "plan" and q["issue_number"] == 5 for q in queued)
        # 成果物保持: abort と違い worktree は削除しない
        workspace.remove_worktree.assert_not_called()
        client.replace_phase_label.assert_awaited_once()

    async def test_rewind_invalid_target_ignored(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        # "done" は resume 不可な target → 無視
        _write_control(orch, {"action": "rewind", "issue": 5, "target": "done", "actor": "test-owner"})

        await orch._consume_control_commands()

        assert orch._state_machine.get_phase(make_issue_key(REPO, 5)) is Phase.IMPLEMENT
        assert orch._task_queue.get_queue_snapshot()["queued"] == []

    async def test_retry_with_analysis_reenqueues_with_feedback(self, tmp_path: Path) -> None:
        account_mgr = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(return_value=AsyncMock())
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        await orch._event_logger.track(
            "phase_error", issue_number=5, phase="implement", data={"error": "boom failure", "category": "unknown"}
        )
        _write_control(orch, {"action": "retry_with_analysis", "issue": 5, "actor": "test-owner"})

        await orch._consume_control_commands()

        req = await orch._task_queue.dequeue()
        assert req.issue_number == 5
        assert req.phase == "implement"
        assert req.extra.get("retry_with_analysis") is True
        assert "boom failure" in req.extra["feedback"]

    async def test_retry_with_analysis_resumes_suspended_issue(self, tmp_path: Path) -> None:
        # 失敗して SUSPENDED 済みの Issue は IMPLEMENT へ resume してから積む
        account_mgr = AsyncMock()
        client = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(return_value=client)
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.IMPLEMENT)
        await orch._state_machine.transition(make_issue_key(REPO, 5), Phase.SUSPENDED)
        _write_control(orch, {"action": "retry_with_analysis", "issue": 5, "actor": "test-owner"})

        await orch._consume_control_commands()

        # state machine も IMPLEMENT へ戻り、キューと相が一致する
        assert orch._state_machine.get_phase(make_issue_key(REPO, 5)) is Phase.IMPLEMENT
        client.replace_phase_label.assert_awaited_once()
        req = await orch._task_queue.dequeue()
        assert req.phase == "implement"

    async def test_retry_with_analysis_ignores_non_retryable_phase(self, tmp_path: Path) -> None:
        # APPROVE のような実行相でない/SUSPENDED でもない相は再試行対象外
        orch = _make_orchestrator(tmp_path)
        orch._state_machine.register_issue(5, REPO, initial_phase=Phase.APPROVE)
        _write_control(orch, {"action": "retry_with_analysis", "issue": 5, "actor": "test-owner"})

        await orch._consume_control_commands()

        assert orch._state_machine.get_phase(make_issue_key(REPO, 5)) is Phase.APPROVE
        assert orch._task_queue.get_queue_snapshot()["queued"] == []


class TestQueueJson:
    async def test_build_and_write_queue_json(self, tmp_path: Path) -> None:
        orch = _make_orchestrator(tmp_path)
        repo = orch._settings.repositories[0]
        from ai_agent_orchestrator.models import TaskRequest

        await orch._task_queue.enqueue(TaskRequest(issue_number=5, repo=repo, phase="implement", priority=5))
        await orch._write_queue_json()

        written = json.loads(orch._queue_file.read_text(encoding="utf-8"))
        assert written["max_total"] == 2
        assert len(written["queued"]) == 1
        assert written["queued"][0]["issue_number"] == 5
        assert "ts" in written
