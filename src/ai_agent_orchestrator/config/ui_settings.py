"""UI 設定オーバーレイ settings.ui.yaml (#90).

``config.yaml`` (機密含む・API 不可侵) とは独立した **非機密の UI 可変設定**。Web UI の
設定画面が GET/PUT する対象で、フェーズ別のモデル / 拡張思考 / 最大ターン数の上書きのみを
保持する。読み込み時に PHASE_CONFIG の既定値へ重ねて effective なフェーズ設定を得る。

設計判断 (#90):
  - config.yaml に機密 (Slack Webhook 等) が含まれるため、UI から書き込む設定は本ファイルへ
    分離し、config.yaml は API から読み取りも書き込みもしない。
  - 本ファイルは非機密のみ。phase_models 以外 (polling / cost_limits 等の UI 編集) は将来
    本モデルへ追加する。
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ai_agent_orchestrator.io_safety import (
    MAX_STATUS_FILE_BYTES,
    atomic_write_text,
    read_text_capped,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ai_agent_orchestrator.models import PhaseConfig

logger = logging.getLogger(__name__)

# エージェントを起動する正準フェーズ (approve 等の待機フェーズは含めない)。
# claude_runner.PHASE_CONFIG のキーと一致させる。
CANONICAL_PHASES: tuple[str, ...] = (
    "intake",
    "clarify",
    "plan",
    "split",
    "implement",
    "revise",
)

# UI/API が許可するモデル別名 (Claude Agent SDK のエイリアス)。
ALLOWED_MODELS: frozenset[str] = frozenset({"haiku", "sonnet", "opus"})

_MAX_TURNS_MIN = 1
_MAX_TURNS_MAX = 500

_PHASE_MODEL_FIELDS = ("phase", "model", "thinking", "max_turns")


class ValidationError(ValueError):
    """UI 設定の検証エラー (API 層で 400 に変換する)."""


class PhaseModelOverride(BaseModel):
    """1 フェーズ分の上書き。未設定 (None) のフィールドは既定値を維持する."""

    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    model: str | None = None
    thinking: bool | None = None
    max_turns: int | None = None


class UiSettings(BaseModel):
    """settings.ui.yaml の構造 (非機密の UI 可変設定)."""

    model_config = ConfigDict(extra="ignore")

    phase_models: dict[str, PhaseModelOverride] = Field(default_factory=dict)


def load_ui_settings(path: Path) -> UiSettings:
    """settings.ui.yaml を読み込む。不在 / 破損 / 上限超過は空設定へ安全に倒す.

    未知フィールド・未知フェーズは無視する (前方互換 + バリデーション漏れ防御)。

    Args:
        path: settings.ui.yaml のパス。

    Returns:
        UiSettings。読めない場合は空 (phase_models={})。
    """
    if not path.exists():
        return UiSettings()
    try:
        raw = read_text_capped(path, MAX_STATUS_FILE_BYTES)
        data = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError):
        logger.warning("settings.ui.yaml の読み取りに失敗: %s", path, exc_info=True)
        return UiSettings()

    if not isinstance(data, dict):
        return UiSettings()

    raw_models = data.get("phase_models")
    phase_models: dict[str, PhaseModelOverride] = {}
    if isinstance(raw_models, dict):
        for phase, override in raw_models.items():
            if phase not in CANONICAL_PHASES or not isinstance(override, dict):
                continue
            try:
                phase_models[phase] = PhaseModelOverride.model_validate(override)
            except ValueError:
                logger.warning("settings.ui.yaml の phase_models[%s] が不正のため無視", phase)
    return UiSettings(phase_models=phase_models)


def save_ui_settings(path: Path, ui: UiSettings) -> None:
    """settings.ui.yaml へ原子的・0o600 で書き出す (#90, 機密ではないが他ユーザー不可読)."""
    payload: dict[str, Any] = {
        "phase_models": {phase: override.model_dump(exclude_none=True) for phase, override in ui.phase_models.items()}
    }
    atomic_write_text(path, yaml.safe_dump(payload, allow_unicode=True, sort_keys=True))


def merge_phase_configs(base: dict[str, PhaseConfig], ui: UiSettings) -> dict[str, PhaseConfig]:
    """PHASE_CONFIG 既定値に UI の上書きを重ねた新しい辞書を返す (base は不変).

    base に存在しないフェーズの上書きは無視する。上書きが None のフィールドは base を維持。

    Args:
        base: 既定の PHASE_CONFIG。
        ui: UI 設定オーバーレイ。

    Returns:
        マージ済みのフェーズ設定辞書 (新規オブジェクト)。
    """
    merged = dict(base)
    for phase, override in ui.phase_models.items():
        if phase not in merged:
            continue
        changes: dict[str, Any] = {}
        if override.model is not None:
            changes["model"] = override.model
        if override.thinking is not None:
            changes["thinking"] = override.thinking
        if override.max_turns is not None:
            changes["max_turns"] = override.max_turns
        if changes:
            merged[phase] = replace(merged[phase], **changes)
    return merged


def effective_phase_models(base: dict[str, PhaseConfig], ui: UiSettings) -> list[dict[str, Any]]:
    """API 応答用に、正準フェーズ順の effective なモデル設定行を返す.

    Returns:
        ``[{"phase", "model", "thinking", "max_turns"}, ...]`` (CANONICAL_PHASES 順、
        base に存在するフェーズのみ)。
    """
    merged = merge_phase_configs(base, ui)
    rows: list[dict[str, Any]] = []
    for phase in CANONICAL_PHASES:
        cfg = merged.get(phase)
        if cfg is None:
            continue
        rows.append(
            {
                "phase": phase,
                "model": cfg.model,
                "thinking": cfg.thinking,
                "max_turns": cfg.max_turns,
            }
        )
    return rows


def validate_phase_models(rows: list[dict[str, Any]]) -> None:
    """PUT 受信ペイロード (フェーズ行のリスト) を検証する。不正なら ValidationError.

    各行は ``phase`` / ``model`` / ``thinking`` / ``max_turns`` のキーを必須とする。
    ``max_turns`` は None を許容し、その場合は「上書きなし (SDK デフォルト)」を意味する。
    PUT は全置換セマンティクスのため、同一フェーズの重複はエラーとする。

    Raises:
        ValidationError: 未知フェーズ / 未知モデル / 型不一致 / 範囲外 / フィールド欠落 / 重複フェーズ。
    """
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("各エントリはオブジェクトである必要があります")
        for field in _PHASE_MODEL_FIELDS:
            if field not in row:
                raise ValidationError(f"必須フィールドが不足しています: {field}")
        phase = row["phase"]
        if phase not in CANONICAL_PHASES:
            raise ValidationError(f"未知のフェーズ: {phase}")
        if phase in seen:
            raise ValidationError(f"フェーズが重複しています: {phase}")
        seen.add(phase)
        if row["model"] not in ALLOWED_MODELS:
            raise ValidationError(f"未知のモデル: {row['model']}")
        if not isinstance(row["thinking"], bool):
            raise ValidationError("thinking は真偽値である必要があります")
        max_turns = row["max_turns"]
        # None = 上書きなし (SDK デフォルト)。指定時のみ範囲・型を検証する。
        if max_turns is not None and (
            not isinstance(max_turns, int)
            or isinstance(max_turns, bool)
            or not (_MAX_TURNS_MIN <= max_turns <= _MAX_TURNS_MAX)
        ):
            raise ValidationError(f"max_turns は {_MAX_TURNS_MIN}〜{_MAX_TURNS_MAX} の整数である必要があります")


def ui_settings_from_rows(rows: list[dict[str, Any]]) -> UiSettings:
    """検証済みのフェーズ行リストを UiSettings へ変換する (PUT 保存用)."""
    return UiSettings(
        phase_models={
            row["phase"]: PhaseModelOverride(
                model=row["model"],
                thinking=row["thinking"],
                max_turns=row["max_turns"],
            )
            for row in rows
        }
    )
