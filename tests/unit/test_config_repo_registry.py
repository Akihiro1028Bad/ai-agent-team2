"""config.yaml リポジトリ追加/削除 + Web 書き込み API の単体テスト (#138)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.repo_registry import (
    RepoRegistryError,
    add_repository,
    list_repositories,
    remove_repository,
)
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig


def _write_config(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")


# ── repo_registry (pure) ──
def test_add_repository_preserves_secrets(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(
        cfg,
        {
            "accounts": {"acc": {"token_command": "secret-cmd"}},
            "repositories": [{"owner": "o0", "repo": "r0", "account": "acc"}],
        },
    )
    add_repository(cfg, owner="o1", repo="r1", account="acc", base_branch="develop")
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    # accounts (機密) は温存
    assert data["accounts"]["acc"]["token_command"] == "secret-cmd"
    owners = [(r["owner"], r["repo"]) for r in data["repositories"]]
    assert ("o1", "r1") in owners
    assert ("o0", "r0") in owners


def test_add_repository_rejects_bad_names(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, {"accounts": {}, "repositories": []})
    with pytest.raises(RepoRegistryError):
        add_repository(cfg, owner="../evil", repo="r")


def test_add_repository_rejects_unknown_account(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, {"accounts": {"known": {}}, "repositories": []})
    with pytest.raises(RepoRegistryError):
        add_repository(cfg, owner="o", repo="r", account="ghost")


def test_add_repository_rejects_duplicate(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, {"accounts": {}, "repositories": [{"owner": "o", "repo": "r"}]})
    with pytest.raises(RepoRegistryError):
        add_repository(cfg, owner="o", repo="r")


def test_remove_repository(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, {"repositories": [{"owner": "o", "repo": "r"}]})
    assert remove_repository(cfg, "o", "r") is True
    assert remove_repository(cfg, "o", "r") is False
    assert list_repositories(cfg) == []


# ── endpoints ──
@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    _write_config(
        cfg,
        {
            "workspace_dir": str(tmp_path / "ws"),
            "accounts": {"acc": {"token_command": "secret"}},
            "repositories": [{"owner": "o0", "repo": "r0", "account": "acc"}],
        },
    )
    (tmp_path / "ws").mkdir()
    return cfg


@pytest.fixture
def client(config_path: Path, tmp_path: Path) -> Iterator[TestClient]:
    settings = AppSettings(
        workspace_dir=str(tmp_path / "ws"),
        accounts={"acc": {}},
        repositories=[RepositoryConfig(owner="o0", repo="r0", account="acc")],
    )
    app = create_app(settings)
    app.state.config_path = config_path
    with TestClient(app) as c:
        yield c


def test_post_repository_adds_and_get_reflects(client: TestClient, config_path: Path) -> None:
    r = client.post("/api/config/repositories", json={"owner": "o1", "repo": "r1", "account": "acc"})
    assert r.status_code == 201
    assert r.json()["restart_required"] is True
    # GET はファイルを都度読むので即反映
    rows = client.get("/api/config/repositories").json()["repositories"]
    assert any(x["owner"] == "o1" and x["repo"] == "r1" for x in rows)


def test_post_repository_duplicate_409(client: TestClient) -> None:
    assert client.post("/api/config/repositories", json={"owner": "o0", "repo": "r0"}).status_code == 409


def test_post_repository_bad_owner_400(client: TestClient) -> None:
    assert client.post("/api/config/repositories", json={"owner": "../x", "repo": "r"}).status_code == 400


def test_post_repository_rejects_extra_secret_field(client: TestClient) -> None:
    """token 等の未知フィールドは extra=forbid で 422 (機密を受け取らない)."""
    r = client.post("/api/config/repositories", json={"owner": "o2", "repo": "r2", "token": "x"})
    assert r.status_code == 422


def test_delete_repository(client: TestClient) -> None:
    assert client.delete("/api/config/repositories/o0/r0").status_code == 200
    assert client.delete("/api/config/repositories/o0/r0").status_code == 404
