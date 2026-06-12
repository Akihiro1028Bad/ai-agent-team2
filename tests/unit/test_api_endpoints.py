"""api.app の FastAPI エンドポイント単体テスト (TestClient)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.github.client import ConfigError


# ──────────────────────────────────────
# ヘルパ / フィクスチャ
# ──────────────────────────────────────
def _state_entry(*, number: int, repo: str, phase: str, pr_number: int | None = None) -> dict[str, Any]:
    return {
        "issue_number": number,
        "phase": phase,
        "issue_type": "bug",
        "repo": repo,
        "pr_number": pr_number,
        "design_pr_number": None,
        "retry_count": 0,
        "branch_head_sha": None,
        "impl_iteration": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }


def _make_settings(workspace: Path) -> AppSettings:
    return AppSettings(
        repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
        workspace_dir=str(workspace),
    )


class _FakeDiffClient:
    """get_pull_request_files を持つ Fake クライアント."""

    def __init__(self, files: list[dict[str, Any]]) -> None:
        self._files = files

    async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, Any]]:
        return list(self._files)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def client(workspace: Path) -> Iterator[TestClient]:
    app = create_app(_make_settings(workspace))
    with TestClient(app) as c:
        yield c


def _write_state(workspace: Path, entries: dict[str, dict[str, Any]]) -> None:
    (workspace / "state.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _write_events(workspace: Path, issue_number: int, records: list[dict[str, Any]]) -> None:
    issue_dir = workspace / "logs" / f"issue-{issue_number}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "events.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ──────────────────────────────────────
# GET /api/issues
# ──────────────────────────────────────
def test_list_issues_empty_workspace_returns_200(client: TestClient) -> None:
    """オーケストレーター停止中相当: state.json 不在でも 200 空リスト."""
    resp = client.get("/api/issues")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_issues_returns_summaries(client: TestClient, workspace: Path) -> None:
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="done")})
    resp = client.get("/api/issues")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["number"] == 1
    assert body[0]["repo"] == "o/r"
    assert body[0]["status"] == "done"
    assert body[0]["title"] is None


# ──────────────────────────────────────
# GET /api/issues/{n}
# ──────────────────────────────────────
def test_get_issue_detail(client: TestClient, workspace: Path) -> None:
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="implement")})
    resp = client.get("/api/issues/1")
    assert resp.status_code == 200
    assert resp.json()["number"] == 1
    assert resp.json()["status"] == "running"


def test_get_issue_not_found_returns_404(client: TestClient) -> None:
    resp = client.get("/api/issues/999")
    assert resp.status_code == 404


def test_get_issue_ambiguous_without_repo_returns_400(client: TestClient, workspace: Path) -> None:
    _write_state(
        workspace,
        {
            "o/r:1": _state_entry(number=1, repo="o/r", phase="done"),
            "o/other:1": _state_entry(number=1, repo="o/other", phase="done"),
        },
    )
    resp = client.get("/api/issues/1")
    assert resp.status_code == 400


def test_get_issue_ambiguous_with_repo_resolves(client: TestClient, workspace: Path) -> None:
    _write_state(
        workspace,
        {
            "o/r:1": _state_entry(number=1, repo="o/r", phase="done"),
            "o/other:1": _state_entry(number=1, repo="o/other", phase="implement"),
        },
    )
    resp = client.get("/api/issues/1", params={"repo": "o/other"})
    assert resp.status_code == 200
    assert resp.json()["repo"] == "o/other"
    assert resp.json()["status"] == "running"


# ──────────────────────────────────────
# GET /api/issues/{n}/events
# ──────────────────────────────────────
def test_get_issue_events_empty_returns_200(client: TestClient) -> None:
    resp = client.get("/api/issues/1/events")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_issue_events_limit(client: TestClient, workspace: Path) -> None:
    _write_events(
        workspace,
        1,
        [
            {"ts": "2026-01-01T00:00:01+00:00", "issue": 1, "phase": "plan", "event": "a"},
            {"ts": "2026-01-01T00:00:02+00:00", "issue": 1, "phase": "plan", "event": "b"},
        ],
    )
    resp = client.get("/api/issues/1/events", params={"limit": 1})
    assert resp.status_code == 200
    assert [e["event"] for e in resp.json()] == ["b"]


# ──────────────────────────────────────
# GET /api/activity
# ──────────────────────────────────────
def test_activity_empty_returns_200(client: TestClient) -> None:
    resp = client.get("/api/activity")
    assert resp.status_code == 200
    assert resp.json() == []


def test_activity_merges(client: TestClient, workspace: Path) -> None:
    _write_events(workspace, 1, [{"ts": "2026-01-01T00:00:01+00:00", "issue": 1, "phase": "p", "event": "x"}])
    _write_events(workspace, 2, [{"ts": "2026-01-01T00:00:09+00:00", "issue": 2, "phase": "p", "event": "y"}])
    resp = client.get("/api/activity")
    assert resp.status_code == 200
    assert [e["issue"] for e in resp.json()] == [2, 1]


# ──────────────────────────────────────
# GET /api/costs
# ──────────────────────────────────────
def test_costs_empty_returns_200(client: TestClient) -> None:
    resp = client.get("/api/costs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_usd"] == 0.0
    assert body["issues"] == []


def test_costs_aggregates(client: TestClient, workspace: Path) -> None:
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="done")})
    _write_events(
        workspace,
        1,
        [
            {"ts": "t", "issue": 1, "phase": "plan", "event": "phase_completed", "data": {"cost_usd": 0.5}},
            {"ts": "t", "issue": 1, "phase": "implement", "event": "phase_completed", "data": {"cost_usd": 1.0}},
        ],
    )
    resp = client.get("/api/costs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_usd"] == pytest.approx(1.5)
    assert body["issues"][0]["phases"]["plan"] == pytest.approx(0.5)


# ──────────────────────────────────────
# GET /api/issues/{n}/diff
# ──────────────────────────────────────
def test_diff_no_pr_returns_404(client: TestClient, workspace: Path) -> None:
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="implement", pr_number=None)})
    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 404


def test_diff_issue_not_found_returns_404(client: TestClient) -> None:
    resp = client.get("/api/issues/5/diff")
    assert resp.status_code == 404


def test_diff_returns_files_with_fake_client(client: TestClient, workspace: Path) -> None:
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="review", pr_number=42)})

    fake = _FakeDiffClient(
        [
            {"filename": "a.py", "status": "modified", "additions": 3, "deletions": 1, "patch": "@@ ..."},
            {"filename": "b.py", "status": "added", "additions": 10, "deletions": 0, "patch": None},
        ]
    )

    async def factory(owner: str, repo: str) -> _FakeDiffClient:
        assert (owner, repo) == ("o", "r")
        return fake

    client.app.state.github_client_factory = factory  # type: ignore[attr-defined]

    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 200
    body = resp.json()
    assert body["pr_number"] == 42
    assert len(body["files"]) == 2
    assert body["files"][0]["filename"] == "a.py"
    assert body["files"][1]["patch"] is None


def test_diff_ambiguous_without_repo_returns_400(client: TestClient, workspace: Path) -> None:
    _write_state(
        workspace,
        {
            "o/r:1": _state_entry(number=1, repo="o/r", phase="review", pr_number=42),
            "o/other:1": _state_entry(number=1, repo="o/other", phase="review", pr_number=7),
        },
    )
    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 400


def test_diff_repo_not_configured_returns_404(client: TestClient, workspace: Path) -> None:
    """config 未登録 repo (ConfigError) は 500 ではなく 404 に整形する."""
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="review", pr_number=42)})

    async def factory(owner: str, repo: str) -> _FakeDiffClient:
        raise ConfigError(f"リポジトリ {owner}/{repo} が config に存在しません")

    client.app.state.github_client_factory = factory  # type: ignore[attr-defined]

    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 404
    assert "config" in resp.json()["detail"]


def test_diff_github_error_returns_502(client: TestClient, workspace: Path) -> None:
    """GitHub API 呼び出し失敗は 500 ではなく 502 に整形する."""
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="review", pr_number=42)})

    class _FailingClient:
        async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, object]]:
            raise RuntimeError("GitHub API request failed")

    async def factory(owner: str, repo: str) -> _FailingClient:
        return _FailingClient()

    client.app.state.github_client_factory = factory  # type: ignore[attr-defined]

    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 502


def test_events_limit_above_cap_returns_422(client: TestClient) -> None:
    """limit はサービス拒否余地を絞るため上限 1000 でバリデーションする."""
    assert client.get("/api/issues/1/events?limit=1001").status_code == 422
    assert client.get("/api/activity?limit=1001").status_code == 422


def test_diff_github_error_detail_hides_internal_message(client: TestClient, workspace: Path) -> None:
    """502 の detail に内部例外の文字列を含めない (情報漏えい防止)."""
    _write_state(workspace, {"o/r:1": _state_entry(number=1, repo="o/r", phase="review", pr_number=42)})

    class _FailingClient:
        async def get_pull_request_files(self, owner: str, repo: str, pr_number: int) -> list[dict[str, object]]:
            raise RuntimeError("secret-internal-url https://internal")

    async def factory(owner: str, repo: str) -> _FailingClient:
        return _FailingClient()

    client.app.state.github_client_factory = factory  # type: ignore[attr-defined]

    resp = client.get("/api/issues/1/diff")
    assert resp.status_code == 502
    assert "secret-internal-url" not in resp.json()["detail"]


# ──────────────────────────────────────
# GET /api/health (#97)
# ──────────────────────────────────────
def test_get_health_absent_returns_200_stopped(client: TestClient) -> None:
    """health.json 不在でも 200 で running=False を返す."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["reason"] is not None


def test_get_health_normal_shape(client: TestClient, workspace: Path) -> None:
    """新鮮な health.json → 200, HealthResponse 形状で running=True."""
    from datetime import UTC, datetime

    payload = {
        "ts": datetime.now(UTC).isoformat(),
        "running": True,
        "queue": {"active": 0, "queued": 0, "max_total": 2},
        "repositories": ["o/r"],
        "rate_limit": {"remaining": 5000, "limit": 5000, "reset": 0},
        "worktrees": 0,
        "last_poll": {},
        "accounts": {"github/default": True},
    }
    (workspace / "health.json").write_text(json.dumps(payload), encoding="utf-8")

    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is True
    assert body["stale"] is False
    assert body["queue"] == {"active": 0, "queued": 0, "max_total": 2}
    assert body["accounts"] == {"github/default": True}


# ──────────────────────────────────────
# POST /api/control (#87 ControlBus 書き込み)
# ──────────────────────────────────────
def test_post_control_pause_appends_to_jsonl(client: TestClient, workspace: Path) -> None:
    """pause コマンド → 202 かつ control.jsonl に該当行が追記される."""
    resp = client.post("/api/control", json={"action": "pause", "issue": 5, "actor": "alice"})
    assert resp.status_code == 202
    assert resp.json()["accepted"] is True
    lines = (workspace / "control.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record == {"action": "pause", "issue": 5, "actor": "alice"}


def test_post_control_shutdown_no_issue_key(client: TestClient, workspace: Path) -> None:
    """shutdown コマンド → 202, control.jsonl の行に issue キーが含まれない."""
    resp = client.post("/api/control", json={"action": "shutdown", "actor": "alice"})
    assert resp.status_code == 202
    lines = (workspace / "control.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    assert "issue" not in record
    assert record["action"] == "shutdown"
    assert record["actor"] == "alice"


def test_post_control_pause_missing_issue_returns_422(client: TestClient) -> None:
    """pause で issue 省略 → 422 バリデーションエラー."""
    resp = client.post("/api/control", json={"action": "pause", "actor": "alice"})
    assert resp.status_code == 422


def test_post_control_pause_zero_issue_returns_422(client: TestClient) -> None:
    """pause で issue=0 (非正整数) → 422."""
    resp = client.post("/api/control", json={"action": "pause", "issue": 0, "actor": "alice"})
    assert resp.status_code == 422


def test_post_control_appends_multiple_lines(client: TestClient, workspace: Path) -> None:
    """複数回 POST すると control.jsonl に複数行追記される."""
    client.post("/api/control", json={"action": "pause", "issue": 1, "actor": "a"})
    client.post("/api/control", json={"action": "resume", "issue": 1, "actor": "a"})
    lines = (workspace / "control.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "pause"
    assert json.loads(lines[1])["action"] == "resume"


# ──────────────────────────────────────
# POST /api/orchestrator/{action}
# ──────────────────────────────────────
class _MockSystemd:
    """テスト用モック ControlSystemd."""

    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    async def start(self) -> None:
        self.started += 1

    async def stop(self) -> None:
        self.stopped += 1


def test_post_orchestrator_start_calls_systemd(client: TestClient) -> None:
    """POST /api/orchestrator/start → モック systemd の start が呼ばれ 200."""
    mock = _MockSystemd()
    client.app.state.systemd = mock  # type: ignore[attr-defined]
    resp = client.post("/api/orchestrator/start")
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert mock.started == 1
    assert mock.stopped == 0


def test_post_orchestrator_stop_appends_shutdown_and_calls_systemd(
    client: TestClient,
    workspace: Path,
) -> None:
    """POST /api/orchestrator/stop → control.jsonl に shutdown 追記 + モック systemd.stop 呼び出し."""
    mock = _MockSystemd()
    client.app.state.systemd = mock  # type: ignore[attr-defined]
    resp = client.post("/api/orchestrator/stop")
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert mock.stopped == 1
    assert mock.started == 0
    lines = (workspace / "control.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "shutdown"
    assert "issue" not in record


def test_post_orchestrator_unknown_action_returns_404(client: TestClient) -> None:
    """未知の action → 404."""
    resp = client.post("/api/orchestrator/restart")
    assert resp.status_code == 404


# ──────────────────────────────────────
# GET /api/queue (#96)
# ──────────────────────────────────────
def test_get_queue_absent_returns_200_empty(client: TestClient) -> None:
    """queue.json 不在でも 200 で空キュー + reason."""
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["queued"] == []
    assert body["reason"] is not None


def test_get_queue_returns_entries(client: TestClient, workspace: Path) -> None:
    """queue.json の内容を返す."""
    payload = {
        "running": True,
        "ts": "2026-06-12T00:00:00+00:00",
        "queued": [
            {
                "repo": "o/r",
                "issue_number": 5,
                "phase": "implement",
                "priority": 5,
                "enqueued_at": "x",
                "wait_reason": "queued",
            },
        ],
        "active": [{"repo": "o/r", "issue_number": 3}],
        "paused": [],
        "max_total": 2,
        "max_per_repo": 1,
    }
    (workspace / "queue.json").write_text(json.dumps(payload), encoding="utf-8")
    resp = client.get("/api/queue")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is True
    assert body["queued"][0]["issue_number"] == 5
    assert body["max_total"] == 2
