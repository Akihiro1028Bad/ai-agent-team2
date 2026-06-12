"""evidence エンドポイント (GET 一覧 / ファイル配信) の単体テスト."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.evidence.paths import evidence_dir


def _make_settings(workspace: Path) -> AppSettings:
    return AppSettings(
        repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
        workspace_dir=str(workspace),
    )


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


def _write_manifest(workspace: Path, issue_number: int, manifest: dict[str, object]) -> Path:
    ev_dir = evidence_dir(workspace, issue_number)
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return ev_dir


def test_get_evidence_builds_urls(client: TestClient, workspace: Path) -> None:
    """manifest があれば items に url が組み立てられる。"""
    _write_manifest(
        workspace,
        91,
        {
            "generated_at": "2026-06-12T00:00:00+00:00",
            "items": [
                {
                    "id": "screenshot-desktop",
                    "kind": "screenshot",
                    "title": "desktop",
                    "file": "screenshot-desktop.png",
                    "viewport": "desktop",
                    "created_at": "2026-06-12T00:00:00+00:00",
                }
            ],
            "notes": ["ok"],
        },
    )
    resp = client.get("/api/issues/91/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"][0]["url"] == "/api/issues/91/evidence/screenshot-desktop.png"
    assert body["notes"] == ["ok"]


def test_get_evidence_absent_returns_empty(client: TestClient) -> None:
    """manifest が無ければ 200 + 空レスポンス。"""
    resp = client.get("/api/issues/91/evidence")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["notes"] == []


def test_get_evidence_file_serves_with_content_type(client: TestClient, workspace: Path) -> None:
    """ファイル配信が 200 + 正しい Content-Type を返す。"""
    ev_dir = evidence_dir(workspace, 91)
    ev_dir.mkdir(parents=True, exist_ok=True)
    (ev_dir / "screenshot-desktop.png").write_bytes(b"\x89PNG")
    resp = client.get("/api/issues/91/evidence/screenshot-desktop.png")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/png")


def test_get_evidence_file_absent_404(client: TestClient) -> None:
    """不在ファイルは 404。"""
    resp = client.get("/api/issues/91/evidence/nope.png")
    assert resp.status_code == 404


def test_get_evidence_file_traversal_404(client: TestClient, workspace: Path) -> None:
    """トラバーサル試行は 404。"""
    ev_dir = evidence_dir(workspace, 91)
    ev_dir.mkdir(parents=True, exist_ok=True)
    resp = client.get("/api/issues/91/evidence/..%2f..%2fstate.json")
    assert resp.status_code == 404
