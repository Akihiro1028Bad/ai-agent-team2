"""GET /api/config/repositories（監視リポジトリ）の単体テスト (#144)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig


def _settings(tmp_path) -> AppSettings:
    return AppSettings(
        workspace_dir=str(tmp_path),
        repositories=[
            RepositoryConfig(
                owner="o1", repo="r1", account="acc1", label="ai-agent",
                base_branch="main", slack_channel="#a",
            ),
            RepositoryConfig(owner="o2", repo="r2", base_branch="develop"),
        ],
    )


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    with TestClient(create_app(_settings(tmp_path))) as c:
        yield c


def test_returns_configured_repositories(client: TestClient) -> None:
    r = client.get("/api/config/repositories")
    assert r.status_code == 200
    repos = r.json()["repositories"]
    assert [(x["owner"], x["repo"], x["base_branch"]) for x in repos] == [
        ("o1", "r1", "main"),
        ("o2", "r2", "develop"),
    ]
    assert repos[0]["account"] == "acc1"
    assert repos[0]["slack_channel"] == "#a"


def test_response_contains_no_secret_fields(client: TestClient) -> None:
    """token 等の機密フィールドを含まないこと (#144)."""
    repos = client.get("/api/config/repositories").json()["repositories"]
    allowed = {"owner", "repo", "account", "label", "base_branch", "slack_channel"}
    for row in repos:
        assert set(row.keys()) <= allowed


def test_empty_when_no_repositories(tmp_path) -> None:
    settings = AppSettings(workspace_dir=str(tmp_path), repositories=[])
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/config/repositories").json()["repositories"] == []
