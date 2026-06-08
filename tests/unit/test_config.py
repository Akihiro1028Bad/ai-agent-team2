"""Tests for ai_agent_orchestrator.config.settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_agent_orchestrator.config.settings import (
    AccountConfig,
    AppSettings,
    CiFixConfig,
    ConcurrencyConfig,
    CostLimitsConfig,
    RepositoryConfig,
    RetryConfig,
    SlackConfig,
    TimeoutsConfig,
    load_config,
)


# ---------------------------------------------------------------------------
# TC-C01: デフォルト値でのネストモデル生成
# ---------------------------------------------------------------------------
class TestTCC01Defaults:
    def test_concurrency_config_defaults(self):
        config = ConcurrencyConfig()
        assert config.max_total == 2
        assert config.max_per_repo == 1

    def test_timeouts_config_defaults(self):
        config = TimeoutsConfig()
        assert config.hearing_hours == 24
        assert config.hearing_phase_sec == 600
        assert config.design_phase_sec == 1800
        assert config.implement_phase_sec == 3600
        assert config.ci_fix_phase_sec == 1200
        assert config.revise_phase_sec == 1800

    def test_cost_limits_config_defaults(self):
        config = CostLimitsConfig()
        assert config.hearing_usd == 1.0
        assert config.design_usd == 3.0
        assert config.implement_usd == 10.0
        assert config.ci_fix_usd == 3.0
        assert config.revise_usd == 5.0

    def test_retry_config_defaults(self):
        config = RetryConfig()
        assert config.max_attempts == 3
        assert config.backoff_minutes == [1, 5, 15]

    def test_ci_fix_config_defaults(self):
        config = CiFixConfig()
        assert config.max_retries == 3


# ---------------------------------------------------------------------------
# TC-C02: バリデーションエラーの検出
# ---------------------------------------------------------------------------
class TestTCC02Validation:
    def test_concurrency_max_total_below_min(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_total=0)

    def test_concurrency_max_total_above_max(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_total=11)

    def test_concurrency_max_per_repo_below_min(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_per_repo=0)

    def test_concurrency_max_per_repo_above_max(self):
        with pytest.raises(ValidationError):
            ConcurrencyConfig(max_per_repo=6)

    def test_polling_interval_below_min(self):
        """polling_interval_sec が 5 未満の場合にバリデーションエラー."""
        with pytest.raises(ValidationError):
            AppSettings(polling_interval_sec=3, repositories=[])


# ---------------------------------------------------------------------------
# TC-C03: RepositoryConfig の生成
# ---------------------------------------------------------------------------
class TestTCC03RepositoryConfig:
    def test_repository_config_minimal(self):
        repo = RepositoryConfig(owner="myorg", repo="myapp")
        assert repo.owner == "myorg"
        assert repo.repo == "myapp"
        assert repo.account is None
        assert repo.label == "ai-agent"
        assert repo.base_branch == "main"
        assert repo.slack_channel is None

    def test_repository_config_full(self):
        repo = RepositoryConfig(
            owner="myorg",
            repo="myapp",
            account="work",
            label="custom-label",
            base_branch="develop",
            slack_channel="#custom",
        )
        assert repo.account == "work"
        assert repo.label == "custom-label"
        assert repo.base_branch == "develop"
        assert repo.slack_channel == "#custom"


# ---------------------------------------------------------------------------
# TC-C04: AccountConfig の生成
# ---------------------------------------------------------------------------
class TestTCC04AccountConfig:
    def test_account_config_minimal(self):
        acc = AccountConfig(name="work")
        assert acc.name == "work"
        assert acc.token_env is None
        assert acc.token_command is None
        assert acc.default is False

    def test_account_config_full(self):
        acc = AccountConfig(
            name="work",
            token_env="GITHUB_TOKEN_WORK",
            token_command="gh auth token",
            default=True,
        )
        assert acc.token_env == "GITHUB_TOKEN_WORK"
        assert acc.token_command == "gh auth token"
        assert acc.default is True


# ---------------------------------------------------------------------------
# TC-C05: YAML設定ファイルからの読み込み
# ---------------------------------------------------------------------------
class TestTCC05YamlLoading:
    def test_load_config_from_yaml(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
polling_interval_sec: 60
repositories:
  - owner: testorg
    repo: testrepo
    label: ai-agent
    base_branch: main
concurrency:
  max_total: 3
  max_per_repo: 2
cost_limits:
  implement_usd: 15.0
""")
        settings = load_config(config_yaml)
        assert settings.polling_interval_sec == 60
        assert len(settings.repositories) == 1
        assert settings.repositories[0].owner == "testorg"
        assert settings.repositories[0].repo == "testrepo"
        assert settings.concurrency.max_total == 3
        assert settings.concurrency.max_per_repo == 2
        assert settings.cost_limits.implement_usd == 15.0
        # 未指定フィールドはデフォルト値
        assert settings.cost_limits.hearing_usd == 1.0
        assert settings.timeouts.hearing_hours == 24


# ---------------------------------------------------------------------------
# TC-C06: 環境変数によるオーバーライド
# ---------------------------------------------------------------------------
class TestTCC06EnvOverride:
    def test_env_override_slack_webhook(self, tmp_path, monkeypatch):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
repositories:
  - owner: org
    repo: app
""")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/override")
        settings = load_config(config_yaml)
        assert settings.slack_webhook_url == "https://hooks.slack.com/override"

    def test_env_override_claude_token(self, tmp_path, monkeypatch):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
repositories:
  - owner: org
    repo: app
""")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token-123")
        settings = load_config(config_yaml)
        assert settings.claude_code_oauth_token == "test-token-123"


# ---------------------------------------------------------------------------
# TC-C07: SlackConfig のオプション性
# ---------------------------------------------------------------------------
class TestTCC07SlackConfig:
    def test_slack_config_optional(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
repositories:
  - owner: org
    repo: app
""")
        settings = load_config(config_yaml)
        assert settings.slack is None

    def test_slack_config_provided(self):
        slack = SlackConfig(webhook_url="https://hooks.slack.com/test")
        assert slack.webhook_url == "https://hooks.slack.com/test"
        assert slack.default_channel == "#ai-agent"


# ---------------------------------------------------------------------------
# TC-C08: load_config() に存在しないファイルパスを渡した場合
# ---------------------------------------------------------------------------
class TestTCC08FileNotFound:
    def test_load_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")


# ---------------------------------------------------------------------------
# TC-C09: 不正なYAML内容の場合
# ---------------------------------------------------------------------------
class TestTCC09InvalidYaml:
    def test_load_config_invalid_yaml(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
polling_interval_sec: "not_a_number"
repositories: "invalid"
""")
        with pytest.raises(ValidationError):
            load_config(config_yaml)


# ---------------------------------------------------------------------------
# TC-C10: accounts セクション付きYAMLの読み込み + AccountConfig変換テスト
# ---------------------------------------------------------------------------
class TestTCC10AccountsLoading:
    def test_load_config_with_accounts(self, tmp_path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("""\
repositories:
  - owner: myorg
    repo: myapp

accounts:
  work:
    name: work
    token_env: GITHUB_TOKEN_WORK
    default: true
  personal:
    name: personal
    token_env: GITHUB_TOKEN_PERSONAL
""")
        settings = load_config(config_yaml)
        assert "work" in settings.accounts
        assert "personal" in settings.accounts
        work_acc = settings.accounts["work"]
        assert isinstance(work_acc, AccountConfig)
        assert work_acc.name == "work"
        assert work_acc.token_env == "GITHUB_TOKEN_WORK"
        assert work_acc.default is True
        personal_acc = settings.accounts["personal"]
        assert isinstance(personal_acc, AccountConfig)
        assert personal_acc.name == "personal"
        assert personal_acc.token_env == "GITHUB_TOKEN_PERSONAL"
        assert personal_acc.default is False
