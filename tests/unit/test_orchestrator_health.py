"""Orchestrator の health.json 書き出し関連テスト (#97)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.config.settings import (
    AppSettings,
    ConcurrencyConfig,
    RepositoryConfig,
)
from ai_agent_orchestrator.github.client import RateLimitStatus
from ai_agent_orchestrator.orchestrator.orchestrator import (
    NullEventRouter,
    NullNotifier,
    NullPhaseDispatcher,
    NullPoller,
    Orchestrator,
)


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


class TestBuildHealthSnapshot:
    """build_health_snapshot のテスト."""

    async def test_includes_queue_repositories_accounts(self, tmp_path: Path) -> None:
        """queue / repositories / accounts が含まれること."""
        orch = _make_orchestrator(tmp_path)
        snapshot = await orch.build_health_snapshot({"github/default": True})

        assert set(snapshot["queue"].keys()) == {"active", "queued", "max_total"}
        assert snapshot["queue"]["max_total"] == 2
        assert snapshot["repositories"] == ["test-owner/test-repo"]
        assert snapshot["accounts"] == {"github/default": True}
        assert "ts" in snapshot
        assert snapshot["running"] is False

    async def test_accounts_defaults_to_empty(self, tmp_path: Path) -> None:
        """accounts 未指定なら {} になること."""
        orch = _make_orchestrator(tmp_path)
        snapshot = await orch.build_health_snapshot()
        assert snapshot["accounts"] == {}

    async def test_best_effort_sources_do_not_raise(self, tmp_path: Path) -> None:
        """rate_limit / worktrees / last_poll が Fake/None でも例外を出さないこと."""
        orch = _make_orchestrator(tmp_path)
        snapshot = await orch.build_health_snapshot()
        # NullPoller は get_last_poll_times を持たない → {}
        assert snapshot["last_poll"] == {}
        # rate_limit はアカウント解決に失敗 → None に倒れる
        assert snapshot["rate_limit"] is None
        # worktrees は repo dir 不在 → 0 (空集計)
        assert snapshot["worktrees"] == 0

    async def test_rate_limit_collected_when_available(self, tmp_path: Path) -> None:
        """rate_limit が取得できれば dict で入ること."""
        account_mgr = AsyncMock()
        client = MagicMock()
        client.get_rate_limit = AsyncMock(return_value=RateLimitStatus(remaining=4990, limit=5000, reset=123))
        account_mgr.get_client_for_repo = AsyncMock(return_value=client)

        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        snapshot = await orch.build_health_snapshot()
        assert snapshot["rate_limit"] == {"remaining": 4990, "limit": 5000, "reset": 123}

    async def test_rate_limit_failure_falls_back_to_none(self, tmp_path: Path) -> None:
        """rate_limit 取得が例外でも None に倒れて全体は成功すること."""
        account_mgr = AsyncMock()
        account_mgr.get_client_for_repo = AsyncMock(side_effect=Exception("boom"))

        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        snapshot = await orch.build_health_snapshot()
        assert snapshot["rate_limit"] is None

    async def test_last_poll_collected_from_poller(self, tmp_path: Path) -> None:
        """poller が get_last_poll_times を持てば反映されること."""

        class _PollerWithLastPoll(NullPoller):
            def get_last_poll_times(self) -> dict[str, str]:
                return {"test-owner/test-repo": "2026-06-11T09:59:30+00:00"}

        orch = _make_orchestrator(tmp_path, poller=_PollerWithLastPoll())
        snapshot = await orch.build_health_snapshot()
        assert snapshot["last_poll"] == {"test-owner/test-repo": "2026-06-11T09:59:30+00:00"}


class TestWriteHealthJson:
    """_write_health_json のテスト."""

    async def test_writes_atomically(self, tmp_path: Path) -> None:
        """health.json が書け、読み戻せること (tmp が残らない)."""
        orch = _make_orchestrator(tmp_path)
        snapshot = await orch.build_health_snapshot({"github/default": True})
        await orch._write_health_json(snapshot)

        health_file = tmp_path / "workspaces" / "health.json"
        assert health_file.exists()
        loaded = json.loads(health_file.read_text(encoding="utf-8"))
        assert loaded["accounts"] == {"github/default": True}
        assert not (tmp_path / "workspaces" / "health.tmp").exists()

    async def test_write_failure_is_swallowed(self, tmp_path: Path) -> None:
        """書き出し失敗 (非シリアライズ可能) でも例外を投げないこと."""
        orch = _make_orchestrator(tmp_path)
        # json 化できない値を含む snapshot
        await orch._write_health_json({"bad": object()})
        # 例外が出なければ合格 (ファイルは作られない)
        assert not (tmp_path / "workspaces" / "health.json").exists()


class TestWorktreeCollection:
    """_collect_worktree_count のフォールバックテスト."""

    async def test_worktree_failure_falls_back_to_none(self, tmp_path: Path) -> None:
        """list_worktrees が例外でも None に倒れること."""
        wm = MagicMock()
        wm.list_worktrees = AsyncMock(side_effect=Exception("git boom"))
        orch = _make_orchestrator(tmp_path, workspace_manager=wm)
        snapshot = await orch.build_health_snapshot()
        assert snapshot["worktrees"] is None


class TestEmitHealthSnapshot:
    """_emit_health_snapshot のテスト."""

    async def test_emit_writes_health_json(self, tmp_path: Path) -> None:
        """health_check → snapshot → 書き出しの一連が成功すること."""
        account_mgr = AsyncMock()
        account_mgr.verify_all = AsyncMock(return_value={"default": True})
        # rate_limit は best-effort で None に倒す (AsyncMock の非シリアライズ回避)
        account_mgr.get_client_for_repo = AsyncMock(side_effect=Exception("no client"))
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)

        await orch._emit_health_snapshot()
        health_file = tmp_path / "workspaces" / "health.json"
        loaded = json.loads(health_file.read_text(encoding="utf-8"))
        assert loaded["accounts"] == {"github/default": True}

    async def test_emit_running_override(self, tmp_path: Path) -> None:
        """running=False を渡すと snapshot の running が上書きされること."""
        orch = _make_orchestrator(tmp_path)
        orch._running = True
        await orch._emit_health_snapshot(running=False)
        health_file = tmp_path / "workspaces" / "health.json"
        loaded = json.loads(health_file.read_text(encoding="utf-8"))
        assert loaded["running"] is False

    async def test_emit_swallows_health_check_failure(self, tmp_path: Path) -> None:
        """health_check が例外でも snapshot を書き出すこと (accounts={})."""
        account_mgr = AsyncMock()
        account_mgr.verify_all = AsyncMock(side_effect=Exception("boom"))
        # verify_all 例外は health_check 内で握られ {"github": False} になるため、
        # health_check 自体を例外化して _emit の except 経路を通す。
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)

        async def _raise() -> dict[str, bool]:
            raise RuntimeError("health_check exploded")

        account_mgr.get_client_for_repo = AsyncMock(side_effect=Exception("no client"))
        orch.health_check = _raise  # type: ignore[method-assign]
        await orch._emit_health_snapshot()
        health_file = tmp_path / "workspaces" / "health.json"
        loaded = json.loads(health_file.read_text(encoding="utf-8"))
        assert loaded["accounts"] == {}


class TestHealthCheckLoopWrites:
    """_health_check_loop の health.json 書き出しテスト."""

    async def test_loop_writes_on_startup_and_running_false_on_exit(self, tmp_path: Path) -> None:
        """起動直後に書き出し、停止後に running=False の snapshot を残すこと."""
        import asyncio

        account_mgr = AsyncMock()
        account_mgr.verify_all = AsyncMock(return_value={"default": True})
        account_mgr.get_client_for_repo = AsyncMock(side_effect=Exception("no client"))
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr)
        orch._running = True

        health_file = tmp_path / "workspaces" / "health.json"
        task = asyncio.create_task(orch._health_check_loop())

        # 起動直後の書き出しを待つ
        for _ in range(50):
            if health_file.exists():
                break
            await asyncio.sleep(0.01)
        assert health_file.exists()
        assert json.loads(health_file.read_text(encoding="utf-8"))["running"] is True

        # 停止 → finally で running=False が書かれる
        import contextlib

        orch._running = False
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        loaded = json.loads(health_file.read_text(encoding="utf-8"))
        assert loaded["running"] is False

    async def test_loop_periodic_write_and_unhealthy_notify(self, tmp_path: Path) -> None:
        """1 周回で unhealthy 通知 + health.json を書き出すこと."""
        import asyncio

        account_mgr = AsyncMock()
        # 1 アカウント不健全 → notify が呼ばれる
        account_mgr.verify_all = AsyncMock(return_value={"default": False})
        account_mgr.get_client_for_repo = AsyncMock(side_effect=Exception("no client"))
        notifier = AsyncMock()
        orch = _make_orchestrator(tmp_path, account_manager=account_mgr, notifier=notifier)
        orch._running = True

        # sleep を即時化し、1 回呼ばれたら停止させてループを 1 周だけ回す。
        calls = {"n": 0}
        real_sleep = asyncio.sleep

        async def _fast_sleep(_sec: float) -> None:
            calls["n"] += 1
            # 2 回目の sleep で停止 → 1 周回は完全に実行される
            if calls["n"] >= 2:
                orch._running = False
            await real_sleep(0)

        orig = asyncio.sleep
        asyncio.sleep = _fast_sleep  # type: ignore[assignment]
        try:
            await orch._health_check_loop()
        finally:
            asyncio.sleep = orig  # type: ignore[assignment]

        notifier.notify.assert_awaited()
        loaded = json.loads((tmp_path / "workspaces" / "health.json").read_text(encoding="utf-8"))
        # finally で running=False が最終的に書かれる
        assert loaded["running"] is False


class TestLastPollCollection:
    """_collect_last_poll の例外フォールバックテスト."""

    async def test_last_poll_getter_exception_returns_empty(self, tmp_path: Path) -> None:
        """get_last_poll_times が例外でも {} に倒れること."""

        class _BadPoller(NullPoller):
            def get_last_poll_times(self) -> dict[str, str]:
                raise RuntimeError("boom")

        orch = _make_orchestrator(tmp_path, poller=_BadPoller())
        snapshot = await orch.build_health_snapshot()
        assert snapshot["last_poll"] == {}


class TestLightweightSnapshot:
    """停止経路 (lightweight) のテスト: ネットワーク/subprocess を呼ばないこと."""

    async def test_lightweight_skips_network_collectors(self, tmp_path: Path) -> None:
        """lightweight=True は rate_limit/worktrees を収集せず None にする (停止遅延防止).

        account_manager / workspace_manager が呼ばれたら例外を投げるよう仕込み、
        呼ばれないことを保証する。
        """
        boom_account = MagicMock()
        boom_account.get_client_for_repo = AsyncMock(side_effect=AssertionError("network called"))
        boom_ws = MagicMock()
        boom_ws.list_worktrees = AsyncMock(side_effect=AssertionError("subprocess called"))

        orch = _make_orchestrator(tmp_path, account_manager=boom_account, workspace_manager=boom_ws)
        snapshot = await orch.build_health_snapshot({}, lightweight=True)

        assert snapshot["rate_limit"] is None
        assert snapshot["worktrees"] is None
        # queue/repositories/last_poll は in-memory なので含まれる
        assert snapshot["repositories"] == ["test-owner/test-repo"]
        assert "queue" in snapshot

    async def test_emit_final_running_false_is_lightweight(self, tmp_path: Path) -> None:
        """停止直前 emit は health_check も呼ばない (停止遅延防止)."""
        boom_account = MagicMock()
        boom_account.verify_all = AsyncMock(side_effect=AssertionError("health_check called"))
        boom_account.get_client_for_repo = AsyncMock(side_effect=AssertionError("network called"))

        orch = _make_orchestrator(tmp_path, account_manager=boom_account)
        # 例外を投げずに running=False の health.json を書けること
        await orch._emit_health_snapshot(running=False, lightweight=True)

        health_file = tmp_path / "workspaces" / "health.json"
        data = json.loads(health_file.read_text(encoding="utf-8"))
        assert data["running"] is False
