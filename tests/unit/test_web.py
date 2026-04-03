"""FastAPI Webサーバー基盤のユニットテスト."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """テスト用 TestClient フィクスチャ."""
    from ai_agent_orchestrator.web.app import create_app

    return TestClient(create_app())


def test_health_returns_200(client: TestClient) -> None:
    """GET /api/health がステータスコード 200 を返すこと."""
    response = client.get("/api/health")
    assert response.status_code == 200


def test_health_response_body(client: TestClient) -> None:
    """レスポンス JSON の status フィールドが "ok" であること."""
    response = client.get("/api/health")
    assert response.json()["status"] == "ok"


def test_health_response_version(client: TestClient) -> None:
    """レスポンス JSON の version フィールドが "0.1.0" であること."""
    response = client.get("/api/health")
    assert response.json()["version"] == "0.1.0"


def test_cors_header_present(client: TestClient) -> None:
    """Origin ヘッダー付きリクエストに対して Access-Control-Allow-Origin ヘッダーが返ること."""
    response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert "access-control-allow-origin" in response.headers


def test_unknown_route_returns_404(client: TestClient) -> None:
    """GET /api/unknown がステータスコード 404 を返すこと."""
    response = client.get("/api/unknown")
    assert response.status_code == 404
