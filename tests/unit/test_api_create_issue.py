"""POST /api/issues (Web からの起票) の単体テスト (#137)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig


class _FakeIssue:
    def __init__(self, number: int, owner: str, repo: str) -> None:
        self.number = number
        self.html_url = f"https://github.com/{owner}/{repo}/issues/{number}"


class _FakeClient:
    def __init__(self, owner: str, repo: str) -> None:
        self._owner = owner
        self._repo = repo
        self.calls: list[dict[str, Any]] = []

    async def create_issue(
        self, repo: object, title: str, body: str = "", labels: list[str] | None = None
    ) -> _FakeIssue:
        self.calls.append({"title": title, "body": body, "labels": labels})
        return _FakeIssue(123, self._owner, self._repo)


def _make_app(tmp_path, repositories):
    settings = AppSettings(workspace_dir=str(tmp_path), repositories=repositories)
    app = create_app(settings)
    created: dict[str, _FakeClient] = {}

    async def _factory(owner: str, name: str) -> _FakeClient:
        c = _FakeClient(owner, name)
        created[f"{owner}/{name}"] = c
        return c

    app.state.github_client_factory = _factory
    return app, created


@pytest.fixture
def single_repo(tmp_path):
    app, created = _make_app(tmp_path, [RepositoryConfig(owner="o", repo="r", account="acc", label="ai-agent")])
    with TestClient(app) as c:
        yield c, created


def test_create_issue_single_repo(single_repo) -> None:
    client, created = single_repo
    r = client.post("/api/issues", json={"title": "新機能が欲しい", "body": "詳細"})
    assert r.status_code == 201
    data = r.json()
    assert data["number"] == 123
    assert data["repo"] == "o/r"
    assert data["url"].endswith("/issues/123")
    # ai-agent ラベルが自動付与される
    assert created["o/r"].calls[0]["labels"] == ["ai-agent"]
    assert created["o/r"].calls[0]["title"] == "新機能が欲しい"


def test_create_issue_title_required(single_repo) -> None:
    client, _ = single_repo
    assert client.post("/api/issues", json={"body": "x"}).status_code == 422
    assert client.post("/api/issues", json={"title": ""}).status_code == 422


def test_create_issue_rejects_extra_field(single_repo) -> None:
    client, _ = single_repo
    assert client.post("/api/issues", json={"title": "t", "labels": ["x"]}).status_code == 422


def test_create_issue_multi_repo_requires_repo(tmp_path) -> None:
    app, _ = _make_app(
        tmp_path,
        [RepositoryConfig(owner="o", repo="r1", account="a"), RepositoryConfig(owner="o", repo="r2", account="a")],
    )
    with TestClient(app) as client:
        assert client.post("/api/issues", json={"title": "t"}).status_code == 400
        r = client.post("/api/issues", json={"title": "t", "repo": "o/r2"})
        assert r.status_code == 201
        assert r.json()["repo"] == "o/r2"


def test_create_issue_unknown_repo_404(single_repo) -> None:
    client, _ = single_repo
    assert client.post("/api/issues", json={"title": "t", "repo": "x/y"}).status_code == 404
