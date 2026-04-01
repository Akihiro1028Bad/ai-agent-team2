"""pydantic-settings 設定モデル."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


@dataclass
class AccountConfig:
    """GitHubアカウント設定."""

    name: str
    token_env: str | None = None
    token_command: str | None = None
    default: bool = False


class RepositoryConfig(BaseModel):
    """リポジトリ設定."""

    owner: str
    repo: str
    account: str | None = None
    label: str = "ai-agent"
    base_branch: str = "main"
    slack_channel: str | None = None


class ConcurrencyConfig(BaseModel):
    """並行処理設定."""

    max_total: int = Field(default=2, ge=1, le=10)
    max_per_repo: int = Field(default=1, ge=1, le=5)


class TimeoutsConfig(BaseModel):
    """タイムアウト設定."""

    hearing_hours: int = 24
    hearing_phase_sec: int = 600
    design_phase_sec: int = 1800
    planning_phase_sec: int = 600
    implement_phase_sec: int = 3600
    ci_fix_phase_sec: int = 1200
    revise_phase_sec: int = 1800


class RetryConfig(BaseModel):
    """リトライ設定."""

    max_attempts: int = 3
    backoff_minutes: list[int] = [1, 5, 15]


class CiFixConfig(BaseModel):
    """CI修正設定."""

    max_retries: int = 3


class CostLimitsConfig(BaseModel):
    """フェーズごとのコスト上限設定."""

    hearing_usd: float = 1.0
    design_usd: float = 3.0
    planning_usd: float = 1.0
    implement_usd: float = 10.0
    ci_fix_usd: float = 3.0
    revise_usd: float = 5.0


class SlackConfig(BaseModel):
    """Slack通知設定."""

    webhook_url: str
    default_channel: str = "#ai-agent"


class AppSettings(BaseSettings):
    """アプリケーション設定 (YAML + 環境変数)."""

    model_config = SettingsConfigDict(
        env_prefix="",
        yaml_file="config.yaml",
        populate_by_name=True,
    )

    polling_interval_sec: int = Field(default=120, ge=5)
    accounts: dict[str, AccountConfig] = {}
    repositories: list[RepositoryConfig]
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()
    retry: RetryConfig = RetryConfig()
    ci_fix: CiFixConfig = CiFixConfig()
    cost_limits: CostLimitsConfig = CostLimitsConfig()
    slack: SlackConfig | None = None
    workspace_dir: str = "~/.ai-agent-workspaces"
    approve_comment: str = "LGTM"

    # Env vars (secrets)
    slack_webhook_url: str | None = Field(default=None, alias="SLACK_WEBHOOK_URL")
    claude_code_oauth_token: str | None = Field(default=None, alias="CLAUDE_CODE_OAUTH_TOKEN")

    @model_validator(mode="before")
    @classmethod
    def _convert_accounts(cls, values: dict[str, object]) -> dict[str, object]:
        """accounts の dict を AccountConfig に変換する."""
        if isinstance(values, dict) and "accounts" in values:
            raw = values["accounts"]
            if isinstance(raw, dict):
                converted: dict[str, AccountConfig] = {}
                for key, val in raw.items():
                    if isinstance(val, dict):
                        val.setdefault("name", key)
                        converted[key] = AccountConfig(**val)
                    elif isinstance(val, AccountConfig):
                        converted[key] = val
                    else:
                        converted[key] = val  # pragma: no cover
                values["accounts"] = converted
        return values

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """設定ソースの優先順位をカスタマイズ."""
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


def load_config(config_path: str | Path | None = None) -> AppSettings:
    """設定ファイルを読み込んで AppSettings を生成する.

    Args:
        config_path: YAML設定ファイルのパス。None の場合はデフォルト
                     ("config.yaml") を使用。

    Returns:
        AppSettings インスタンス。

    Raises:
        FileNotFoundError: 設定ファイルが存在しない場合。
        pydantic.ValidationError: 設定値のバリデーションエラー。
    """
    if config_path is not None:
        path = Path(config_path)
        if not path.exists():
            msg = f"Config file not found: {path}"
            raise FileNotFoundError(msg)
        with path.open() as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return AppSettings(**data)
    return AppSettings()  # type: ignore[call-arg]
