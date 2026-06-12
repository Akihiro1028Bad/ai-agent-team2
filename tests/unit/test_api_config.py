"""GET/PUT /api/config/phase-models のエンドポイント単体テスト (#90).

UI から書き込む非機密設定 (フェーズ別モデル) のみを扱い、settings.ui.yaml へ保存する。
config.yaml の機密は一切露出しない。バリデーション (未知フェーズ/モデル・範囲外) は 400。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig


@pytest.fixture
def ui_file(tmp_path: Path) -> Path:
    return tmp_path / "settings.ui.yaml"


@pytest.fixture
def client(tmp_path: Path, ui_file: Path) -> Iterator[TestClient]:
    settings = AppSettings(
        repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
        workspace_dir=str(tmp_path / "ws"),
        ui_settings_file=str(ui_file),
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_get_returns_canonical_phases_and_allowed_models(client: TestClient) -> None:
    res = client.get("/api/config/phase-models")
    assert res.status_code == 200
    body = res.json()
    phases = {row["phase"] for row in body["phases"]}
    assert {"intake", "clarify", "plan", "split", "implement", "revise"} == phases
    assert sorted(body["allowed_models"]) == ["haiku", "opus", "sonnet"]
    # 既定では plan は sonnet・thinking False (上書き前)。
    plan = next(r for r in body["phases"] if r["phase"] == "plan")
    assert plan["model"] == "sonnet"
    assert plan["thinking"] is False


def test_put_persists_and_reflects(client: TestClient, ui_file: Path) -> None:
    payload = {
        "phases": [
            {"phase": "plan", "model": "opus", "thinking": True, "max_turns": 25},
            {"phase": "implement", "model": "haiku", "thinking": False, "max_turns": 60},
        ]
    }
    res = client.put("/api/config/phase-models", json=payload)
    assert res.status_code == 200
    plan = next(r for r in res.json()["phases"] if r["phase"] == "plan")
    assert plan == {"phase": "plan", "model": "opus", "thinking": True, "max_turns": 25}

    # ファイルへ永続化されている。
    assert ui_file.exists()
    saved = yaml.safe_load(ui_file.read_text(encoding="utf-8"))
    assert saved["phase_models"]["plan"]["model"] == "opus"

    # 後続 GET にも反映される。
    again = client.get("/api/config/phase-models")
    plan2 = next(r for r in again.json()["phases"] if r["phase"] == "plan")
    assert plan2["model"] == "opus"
    assert plan2["thinking"] is True


def test_put_saved_file_is_private(client: TestClient, ui_file: Path) -> None:
    client.put(
        "/api/config/phase-models",
        json={"phases": [{"phase": "plan", "model": "opus", "thinking": True, "max_turns": 20}]},
    )
    assert (ui_file.stat().st_mode & 0o777) == 0o600


@pytest.mark.parametrize(
    "bad_row",
    [
        {"phase": "nope", "model": "opus", "thinking": False, "max_turns": 10},
        {"phase": "plan", "model": "gpt-4", "thinking": False, "max_turns": 10},
        {"phase": "plan", "model": "opus", "thinking": False, "max_turns": 0},
        {"phase": "plan", "model": "opus", "thinking": False, "max_turns": 9999},
    ],
)
def test_put_invalid_returns_400(client: TestClient, bad_row: dict[str, object]) -> None:
    res = client.put("/api/config/phase-models", json={"phases": [bad_row]})
    assert res.status_code == 400


def test_put_rejects_duplicate_phase(client: TestClient) -> None:
    payload = {
        "phases": [
            {"phase": "plan", "model": "opus", "thinking": True, "max_turns": 20},
            {"phase": "plan", "model": "sonnet", "thinking": False, "max_turns": 30},
        ]
    }
    res = client.put("/api/config/phase-models", json=payload)
    assert res.status_code == 400


def test_put_null_max_turns_means_no_override(client: TestClient, ui_file: Path) -> None:
    # max_turns=null は SDK デフォルト委任。422 にならず、effective も null。
    res = client.put(
        "/api/config/phase-models",
        json={"phases": [{"phase": "plan", "model": "opus", "thinking": True, "max_turns": None}]},
    )
    assert res.status_code == 200
    plan = next(r for r in res.json()["phases"] if r["phase"] == "plan")
    assert plan["model"] == "opus"
    assert plan["max_turns"] is None
    # overlay には max_turns を含めない (exclude_none)。
    saved = yaml.safe_load(ui_file.read_text(encoding="utf-8"))
    assert "max_turns" not in saved["phase_models"]["plan"]


def test_put_rejects_unknown_field(client: TestClient) -> None:
    # extra="forbid" によりスキーマ段階で 422。
    res = client.put(
        "/api/config/phase-models",
        json={"phases": [{"phase": "plan", "model": "opus", "thinking": False, "max_turns": 10, "x": 1}]},
    )
    assert res.status_code == 422


def test_put_does_not_touch_config_yaml(client: TestClient, tmp_path: Path) -> None:
    # config.yaml が CWD に無くても PUT は settings.ui.yaml のみ書く (機密不可侵)。
    client.put(
        "/api/config/phase-models",
        json={"phases": [{"phase": "plan", "model": "opus", "thinking": True, "max_turns": 20}]},
    )
    assert not (tmp_path / "config.yaml").exists()
