"""UI プロトタイプ (#145) の収集・読取・配信エンドポイントの単体テスト."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.api.readers import read_prototypes
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.prototype.collector import collect_prototype
from ai_agent_orchestrator.prototype.paths import prototype_dir, worktree_prototype_file


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


def _write_worktree_prototype(worktree: Path, issue_number: int, html: str) -> None:
    target = worktree_prototype_file(worktree, issue_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


# ──────────────────────────────────────
# collector
# ──────────────────────────────────────
def test_collect_prototype_copies_and_writes_manifest(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<!doctype html><h1>proto</h1>")

    assert collect_prototype(workspace, 145, worktree) is True

    pdir = prototype_dir(workspace, 145)
    assert (pdir / "index.html").read_text(encoding="utf-8") == "<!doctype html><h1>proto</h1>"
    manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"] == [{"id": "prototype", "title": "UI プロトタイプ", "file": "index.html"}]


def test_collect_prototype_absent_writes_empty_manifest(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()

    assert collect_prototype(workspace, 145, worktree) is False

    manifest = json.loads((prototype_dir(workspace, 145) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"] == []
    assert manifest["notes"]  # 未生成の note が入る


def test_collect_prototype_too_large_is_skipped(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "x" * (2 * 1024 * 1024 + 1))

    assert collect_prototype(workspace, 145, worktree) is False
    assert not (prototype_dir(workspace, 145) / "index.html").exists()


# ──────────────────────────────────────
# read_prototypes
# ──────────────────────────────────────
def test_read_prototypes_absent_returns_empty(workspace: Path) -> None:
    res = read_prototypes(workspace, 999)
    assert res.items == []
    assert res.generated_at is None


def test_read_prototypes_builds_url(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>p</h1>")
    collect_prototype(workspace, 145, worktree)

    res = read_prototypes(workspace, 145)
    assert len(res.items) == 1
    assert res.items[0].url == "/api/issues/145/prototypes/index.html"


# ──────────────────────────────────────
# endpoints
# ──────────────────────────────────────
def test_get_prototypes_endpoint(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>p</h1>")
    collect_prototype(workspace, 145, worktree)

    r = client.get("/api/issues/145/prototypes")
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["url"] == "/api/issues/145/prototypes/index.html"


def test_serve_prototype_html_with_sandbox_headers(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<!doctype html><h1>proto</h1>")
    collect_prototype(workspace, 145, worktree)

    r = client.get("/api/issues/145/prototypes/index.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    # エージェント生成 HTML の隔離ヘッダ
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<h1>proto</h1>" in r.text


def test_serve_prototype_path_traversal_blocked(client: TestClient, workspace: Path) -> None:
    prototype_dir(workspace, 145).mkdir(parents=True, exist_ok=True)
    r = client.get("/api/issues/145/prototypes/..%2F..%2Fstate.json")
    assert r.status_code == 404


def test_serve_prototype_missing_file_404(client: TestClient, workspace: Path) -> None:
    r = client.get("/api/issues/145/prototypes/index.html")
    assert r.status_code == 404
