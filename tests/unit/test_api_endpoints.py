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
