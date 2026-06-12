"""UI 設定オーバーレイ (settings.ui.yaml) の単体テスト (#90).

config.yaml とは独立した非機密の UI 可変設定。フェーズ別モデル/拡張思考/最大ターンを
保持し、PHASE_CONFIG の既定値へ上書きする。バリデーション・ロード・保存・マージを検証。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_agent_orchestrator.config.ui_settings import (
    ALLOWED_MODELS,
    CANONICAL_PHASES,
    PhaseModelOverride,
    UiSettings,
    ValidationError,
    effective_phase_models,
    load_ui_settings,
    merge_phase_configs,
    save_ui_settings,
    validate_phase_models,
)
from ai_agent_orchestrator.models import PhaseConfig

_BASE: dict[str, PhaseConfig] = {
    "plan": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
}


class TestLoad:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        ui = load_ui_settings(tmp_path / "settings.ui.yaml")
        assert ui.phase_models == {}

    def test_roundtrip_save_load(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.ui.yaml"
        ui = UiSettings(phase_models={"plan": PhaseModelOverride(model="opus", thinking=True, max_turns=20)})
        save_ui_settings(path, ui)
        assert path.exists()
        loaded = load_ui_settings(path)
        assert loaded.phase_models["plan"].model == "opus"
        assert loaded.phase_models["plan"].thinking is True
        assert loaded.phase_models["plan"].max_turns == 20

    def test_corrupt_yaml_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.ui.yaml"
        path.write_text("{ this is: not valid: yaml :::", encoding="utf-8")
        assert load_ui_settings(path).phase_models == {}

    def test_unknown_phase_in_file_is_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.ui.yaml"
        path.write_text("phase_models:\n  bogus:\n    model: opus\n", encoding="utf-8")
        assert "bogus" not in load_ui_settings(path).phase_models

    def test_saved_file_is_private_0o600(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.ui.yaml"
        save_ui_settings(path, UiSettings(phase_models={"plan": PhaseModelOverride(model="opus")}))
        assert (path.stat().st_mode & 0o777) == 0o600


class TestMerge:
    def test_override_applies_model_thinking_turns(self) -> None:
        ui = UiSettings(phase_models={"plan": PhaseModelOverride(model="opus", thinking=True, max_turns=25)})
        merged = merge_phase_configs(_BASE, ui)
        assert merged["plan"].model == "opus"
        assert merged["plan"].thinking is True
        assert merged["plan"].max_turns == 25
        # 上書きしていない値は維持。
        assert merged["plan"].max_budget_usd == 3.0
        assert merged["plan"].timeout_sec == 1800

    def test_unset_override_fields_keep_base(self) -> None:
        # model だけ上書き。thinking/max_turns は None なので base 値を保持。
        ui = UiSettings(phase_models={"implement": PhaseModelOverride(model="haiku")})
        merged = merge_phase_configs(_BASE, ui)
        assert merged["implement"].model == "haiku"
        assert merged["implement"].thinking is False
        assert merged["implement"].max_turns is None

    def test_no_override_returns_base_equivalent(self) -> None:
        merged = merge_phase_configs(_BASE, UiSettings(phase_models={}))
        assert merged["plan"].model == _BASE["plan"].model

    def test_merge_does_not_mutate_base(self) -> None:
        ui = UiSettings(phase_models={"plan": PhaseModelOverride(model="opus")})
        merge_phase_configs(_BASE, ui)
        assert _BASE["plan"].model == "sonnet"


class TestValidation:
    def test_valid_payload_passes(self) -> None:
        rows = [{"phase": "plan", "model": "opus", "thinking": True, "max_turns": 20}]
        validate_phase_models(rows)  # raises なし

    def test_unknown_phase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models([{"phase": "nope", "model": "opus", "thinking": False, "max_turns": 10}])

    def test_unknown_model_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models([{"phase": "plan", "model": "gpt-4", "thinking": False, "max_turns": 10}])

    @pytest.mark.parametrize("turns", [0, -1, 1000])
    def test_out_of_range_max_turns_rejected(self, turns: int) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models([{"phase": "plan", "model": "opus", "thinking": False, "max_turns": turns}])

    def test_non_bool_thinking_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models([{"phase": "plan", "model": "opus", "thinking": "yes", "max_turns": 10}])

    def test_duplicate_phase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models(
                [
                    {"phase": "plan", "model": "opus", "thinking": True, "max_turns": 10},
                    {"phase": "plan", "model": "sonnet", "thinking": False, "max_turns": 20},
                ]
            )

    def test_null_max_turns_allowed(self) -> None:
        # None = 上書きなし (SDK デフォルト) として許容。
        validate_phase_models([{"phase": "plan", "model": "opus", "thinking": False, "max_turns": None}])

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_phase_models([{"phase": "plan", "model": "opus"}])

    def test_allowed_models_and_phases_exposed(self) -> None:
        assert "sonnet" in ALLOWED_MODELS
        assert "plan" in CANONICAL_PHASES


class TestEffective:
    def test_effective_returns_all_canonical_phases(self) -> None:
        rows = effective_phase_models(_BASE, UiSettings(phase_models={}))
        phases = {r["phase"] for r in rows}
        # base に含まれる phase は必ず出力される。
        assert {"plan", "implement"} <= phases

    def test_effective_reflects_override(self) -> None:
        ui = UiSettings(phase_models={"plan": PhaseModelOverride(model="opus", thinking=True, max_turns=22)})
        rows = effective_phase_models(_BASE, ui)
        plan = next(r for r in rows if r["phase"] == "plan")
        assert plan == {"phase": "plan", "model": "opus", "thinking": True, "max_turns": 22}
