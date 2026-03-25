# 実装仕様書: `src/ai_agent_orchestrator/config/settings.py`

## 概要

YAML設定ファイルと環境変数からアプリケーション設定を読み込むモジュール。
`pydantic-settings` の `BaseSettings` を使用し、複数の設定ソースを統合する。
GitHubマルチアカウント設定、リポジトリ監視設定、並行処理・タイムアウト・コスト制限の設定を管理する。

---

## 依存モジュール

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, YamlConfigSettingsSource
```

**外部パッケージ依存:**
- `pydantic` (>=2.0)
- `pydantic-settings` (>=2.0)
- `pyyaml`

**内部依存:** なし（このモジュールは Layer 0 であり他の内部モジュールに依存しない）

---

## 1. AccountConfig

GitHubアカウント設定。マルチアカウント運用時にアカウントごとのトークン取得方法を定義する。
**dataclass** として定義する（pydantic BaseModel ではない）。

```python
@dataclass
class AccountConfig:
    """GitHubアカウント設定."""

    name: str
    token_env: str | None = None
    token_command: str | None = None
    default: bool = False
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `name` | `str` | (必須) | アカウント名（accounts セクションのキーと一致） |
| `token_env` | `str \| None` | `None` | トークンを格納する環境変数名（例: `GITHUB_TOKEN_WORK`） |
| `token_command` | `str \| None` | `None` | トークン取得用の外部コマンド |
| `default` | `bool` | `False` | デフォルトアカウントとして使用するかどうか |

**設計意図:** `CredentialResolver` がこの設定を基に4段階フォールバック（keyring -> env -> token_command -> gh auth token）でトークンを解決する。

---

## 2. RepositoryConfig

リポジトリ単位の監視設定。pydantic `BaseModel` として定義する。

```python
class RepositoryConfig(BaseModel):
    """リポジトリ設定."""

    owner: str
    repo: str
    account: str | None = None    # accounts セクションのキーを参照
    label: str = "ai-agent"
    base_branch: str = "main"
    slack_channel: str | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `owner` | `str` | (必須) | リポジトリオーナー（例: `"myorg"`） |
| `repo` | `str` | (必須) | リポジトリ名（例: `"myapp"`） |
| `account` | `str \| None` | `None` | 使用するアカウント名。`None` の場合はデフォルトアカウントを使用 |
| `label` | `str` | `"ai-agent"` | AIに割り当てるIssueのラベル名 |
| `base_branch` | `str` | `"main"` | PR作成時のベースブランチ |
| `slack_channel` | `str \| None` | `None` | Slack通知チャンネル。`None` の場合は `SlackConfig.default_channel` を使用 |

**注意:** APIリファレンスでは `account` フィールドが `str | None` だが、設計書の一部では `str` (必須) となっている。APIリファレンスの定義（`str | None = None`）を正とする。

---

## 3. ConcurrencyConfig

並行処理の制約設定。

```python
class ConcurrencyConfig(BaseModel):
    """並行処理設定."""

    max_total: int = Field(default=2, ge=1, le=10)
    max_per_repo: int = Field(default=1, ge=1, le=5)
```

| フィールド | 型 | デフォルト | バリデーション | 説明 |
|-----------|---|---------|-------------|------|
| `max_total` | `int` | `2` | `1 <= x <= 10` | 全体の最大同時実行Issue数 |
| `max_per_repo` | `int` | `1` | `1 <= x <= 5` | リポジトリあたりの最大同時実行Issue数 |

---

## 4. TimeoutsConfig

各種タイムアウトの設定。

```python
class TimeoutsConfig(BaseModel):
    """タイムアウト設定."""

    hearing_hours: int = 24
    hearing_phase_sec: int = 600
    design_phase_sec: int = 1800
    planning_phase_sec: int = 600
    implement_phase_sec: int = 3600
    ci_fix_phase_sec: int = 1200
    revise_phase_sec: int = 1800
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `hearing_hours` | `int` | `24` | ヒアリング回答待ちタイムアウト（時間）。超過時に SUSPENDED |
| `hearing_phase_sec` | `int` | `600` | ヒアリングフェーズの実行タイムアウト（秒） |
| `design_phase_sec` | `int` | `1800` | 設計フェーズの実行タイムアウト（秒） |
| `planning_phase_sec` | `int` | `600` | 実装計画フェーズの実行タイムアウト（秒） |
| `implement_phase_sec` | `int` | `3600` | 実装フェーズの実行タイムアウト（秒） |
| `ci_fix_phase_sec` | `int` | `1200` | CI修正フェーズの実行タイムアウト（秒） |
| `revise_phase_sec` | `int` | `1800` | 修正フェーズ（設計修正・実装修正）のタイムアウト（秒） |

---

## 5. RetryConfig

リトライの設定。

```python
class RetryConfig(BaseModel):
    """リトライ設定."""

    max_attempts: int = 3
    backoff_minutes: list[int] = [1, 5, 15]
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `max_attempts` | `int` | `3` | 最大リトライ回数 |
| `backoff_minutes` | `list[int]` | `[1, 5, 15]` | リトライ間隔（分）。インデックスがリトライ回数に対応 |

---

## 6. CiFixConfig

CI修正の設定。

```python
class CiFixConfig(BaseModel):
    """CI修正設定."""

    max_retries: int = 3
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `max_retries` | `int` | `3` | CI修正の最大リトライ回数 |

---

## 7. CostLimitsConfig

フェーズごとのコスト上限設定。

```python
class CostLimitsConfig(BaseModel):
    """フェーズごとのコスト上限設定."""

    hearing_usd: float = 1.0
    design_usd: float = 3.0
    planning_usd: float = 1.0
    implement_usd: float = 10.0
    ci_fix_usd: float = 3.0
    revise_usd: float = 5.0
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `hearing_usd` | `float` | `1.0` | ヒアリングフェーズのコスト上限 (USD) |
| `design_usd` | `float` | `3.0` | 設計フェーズのコスト上限 (USD) |
| `planning_usd` | `float` | `1.0` | 計画フェーズのコスト上限 (USD) |
| `implement_usd` | `float` | `10.0` | 実装フェーズのコスト上限 (USD) |
| `ci_fix_usd` | `float` | `3.0` | CI修正フェーズのコスト上限 (USD) |
| `revise_usd` | `float` | `5.0` | 修正フェーズのコスト上限 (USD) |

---

## 8. SlackConfig

Slack通知の設定。

```python
class SlackConfig(BaseModel):
    """Slack通知設定."""

    webhook_url: str
    default_channel: str = "#ai-agent"
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `webhook_url` | `str` | (必須) | Slack Webhook URL |
| `default_channel` | `str` | `"#ai-agent"` | デフォルト通知チャンネル |

---

## 9. AppSettings

アプリケーション全体の設定。pydantic-settings の `BaseSettings` を継承し、YAML + 環境変数の統合設定を提供する。

```python
class AppSettings(BaseSettings):
    """アプリケーション設定 (YAML + 環境変数)."""

    polling_interval_sec: int = Field(default=120, ge=30)
    accounts: dict[str, AccountConfig] = {}
    repositories: list[RepositoryConfig]
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()
    retry: RetryConfig = RetryConfig()
    ci_fix: CiFixConfig = CiFixConfig()
    cost_limits: CostLimitsConfig = CostLimitsConfig()
    slack: SlackConfig | None = None
    workspace_dir: str = "~/.ai-agent-workspaces"

    # 環境変数（機密情報）
    slack_webhook_url: str | None = Field(default=None, alias="SLACK_WEBHOOK_URL")
    claude_code_oauth_token: str | None = Field(default=None, alias="CLAUDE_CODE_OAUTH_TOKEN")

    model_config = {
        "env_prefix": "",
        "yaml_file": "config.yaml",
    }

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        """設定ソースの優先順位をカスタマイズ."""
        return (
            kwargs.get("init_settings"),
            kwargs.get("env_settings"),
            YamlConfigSettingsSource(settings_cls),
            kwargs.get("dotenv_settings"),
            kwargs.get("file_secret_settings"),
        )
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `polling_interval_sec` | `int` | `120` | ポーリング間隔（秒）。最低30秒 |
| `accounts` | `dict[str, AccountConfig]` | `{}` | GitHubアカウント設定マップ |
| `repositories` | `list[RepositoryConfig]` | (必須) | 監視対象リポジトリリスト |
| `concurrency` | `ConcurrencyConfig` | `ConcurrencyConfig()` | 並行処理設定 |
| `timeouts` | `TimeoutsConfig` | `TimeoutsConfig()` | タイムアウト設定 |
| `retry` | `RetryConfig` | `RetryConfig()` | リトライ設定 |
| `ci_fix` | `CiFixConfig` | `CiFixConfig()` | CI修正設定 |
| `cost_limits` | `CostLimitsConfig` | `CostLimitsConfig()` | コスト制限設定 |
| `slack` | `SlackConfig \| None` | `None` | Slack通知設定（オプション） |
| `workspace_dir` | `str` | `"~/.ai-agent-workspaces"` | ワークスペースディレクトリ |
| `slack_webhook_url` | `str \| None` | `None` | Slack Webhook URL（環境変数 `SLACK_WEBHOOK_URL`） |
| `claude_code_oauth_token` | `str \| None` | `None` | Claude Code OAuthトークン（環境変数 `CLAUDE_CODE_OAUTH_TOKEN`） |

**設定ソースの優先順位** (上が高):
1. コンストラクタ引数 (`init_settings`)
2. 環境変数 (`env_settings`)
3. YAMLファイル (`YamlConfigSettingsSource`)
4. .env ファイル (`dotenv_settings`)
5. ファイルシークレット (`file_secret_settings`)

---

## 10. load_config() 関数

設定ファイルのパスを受け取り `AppSettings` インスタンスを生成するファクトリ関数。

```python
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
        import os
        os.environ["YAML_FILE"] = str(config_path)
    return AppSettings()
```

**動作:**
1. `config_path` が指定されていれば、`model_config` の `yaml_file` を上書きする
2. `AppSettings()` を生成し、`settings_customise_sources` で定義された優先順位で設定を読み込む
3. バリデーションエラーは `pydantic.ValidationError` として伝播する

**注意:** `load_config` の実装方法は、pydantic-settings の `yaml_file` 設定を動的に変更する方法に依存する。上記は簡易実装例であり、実装時に `model_config` をオーバーライドする方法（例: `AppSettings.model_config["yaml_file"] = str(config_path)` またはコンストラクタ引数での指定）を検討すること。

---

## 11. YAML設定ファイルの例

```yaml
# config.yaml
polling_interval_sec: 120

accounts:
  work:
    name: work
    token_env: GITHUB_TOKEN_WORK
    default: true
  personal:
    name: personal
    token_env: GITHUB_TOKEN_PERSONAL

repositories:
  - owner: myorg
    repo: myapp
    account: work
    label: ai-agent
    base_branch: main
    slack_channel: "#myapp-dev"
  - owner: myuser
    repo: side-project
    account: personal

concurrency:
  max_total: 2
  max_per_repo: 1

timeouts:
  hearing_hours: 24
  hearing_phase_sec: 600
  design_phase_sec: 1800
  planning_phase_sec: 600
  implement_phase_sec: 3600
  ci_fix_phase_sec: 1200
  revise_phase_sec: 1800

retry:
  max_attempts: 3
  backoff_minutes: [1, 5, 15]

ci_fix:
  max_retries: 3

cost_limits:
  hearing_usd: 1.0
  design_usd: 3.0
  planning_usd: 1.0
  implement_usd: 10.0
  ci_fix_usd: 3.0
  revise_usd: 5.0

slack:
  webhook_url: "https://hooks.slack.com/services/T.../B.../xxx"
  default_channel: "#ai-agent"

workspace_dir: "~/.ai-agent-workspaces"
```

---

## 12. テストケース

テストファイル: `tests/unit/test_config.py`

### TC-C01: デフォルト値でのネストモデル生成

**目的**: 必須フィールドのみ指定し、他のフィールドがデフォルト値で初期化されることを検証する。

```python
def test_concurrency_config_defaults():
    config = ConcurrencyConfig()
    assert config.max_total == 2
    assert config.max_per_repo == 1

def test_timeouts_config_defaults():
    config = TimeoutsConfig()
    assert config.hearing_hours == 24
    assert config.hearing_phase_sec == 600
    assert config.design_phase_sec == 1800
    assert config.planning_phase_sec == 600
    assert config.implement_phase_sec == 3600
    assert config.ci_fix_phase_sec == 1200
    assert config.revise_phase_sec == 1800

def test_cost_limits_config_defaults():
    config = CostLimitsConfig()
    assert config.hearing_usd == 1.0
    assert config.design_usd == 3.0
    assert config.planning_usd == 1.0
    assert config.implement_usd == 10.0
    assert config.ci_fix_usd == 3.0
    assert config.revise_usd == 5.0

def test_retry_config_defaults():
    config = RetryConfig()
    assert config.max_attempts == 3
    assert config.backoff_minutes == [1, 5, 15]

def test_ci_fix_config_defaults():
    config = CiFixConfig()
    assert config.max_retries == 3
```

**期待結果**: 全デフォルト値が設計書通り。

---

### TC-C02: バリデーションエラーの検出

**目的**: `Field` 制約（`ge`, `le`）のバリデーションが正しく動作することを検証する。

```python
import pytest
from pydantic import ValidationError

def test_concurrency_max_total_below_min():
    with pytest.raises(ValidationError):
        ConcurrencyConfig(max_total=0)

def test_concurrency_max_total_above_max():
    with pytest.raises(ValidationError):
        ConcurrencyConfig(max_total=11)

def test_concurrency_max_per_repo_below_min():
    with pytest.raises(ValidationError):
        ConcurrencyConfig(max_per_repo=0)

def test_concurrency_max_per_repo_above_max():
    with pytest.raises(ValidationError):
        ConcurrencyConfig(max_per_repo=6)

def test_polling_interval_below_min():
    """polling_interval_sec が 30 未満の場合にバリデーションエラー."""
    with pytest.raises(ValidationError):
        AppSettings(polling_interval_sec=10, repositories=[])
```

**期待結果**: 制約範囲外の値で `ValidationError` が発生する。

---

### TC-C03: RepositoryConfig の生成

**目的**: `RepositoryConfig` の必須・オプションフィールドが正しく設定されることを検証する。

```python
def test_repository_config_minimal():
    repo = RepositoryConfig(owner="myorg", repo="myapp")
    assert repo.owner == "myorg"
    assert repo.repo == "myapp"
    assert repo.account is None
    assert repo.label == "ai-agent"
    assert repo.base_branch == "main"
    assert repo.slack_channel is None

def test_repository_config_full():
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
```

**期待結果**: デフォルト値とカスタム値が正しく反映される。

---

### TC-C04: AccountConfig の生成

**目的**: `AccountConfig` dataclass の初期化を検証する。

```python
def test_account_config_minimal():
    acc = AccountConfig(name="work")
    assert acc.name == "work"
    assert acc.token_env is None
    assert acc.token_command is None
    assert acc.default is False

def test_account_config_full():
    acc = AccountConfig(
        name="work",
        token_env="GITHUB_TOKEN_WORK",
        token_command="gh auth token",
        default=True,
    )
    assert acc.token_env == "GITHUB_TOKEN_WORK"
    assert acc.token_command == "gh auth token"
    assert acc.default is True
```

**期待結果**: フィールドが正しく初期化される。

---

### TC-C05: YAML設定ファイルからの読み込み

**目的**: `load_config()` が YAML ファイルを正しく読み込むことを検証する。

```python
def test_load_config_from_yaml(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
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
```

**期待結果**: YAML の値が正しく読み込まれ、未指定フィールドはデフォルト値が使用される。

---

### TC-C06: 環境変数によるオーバーライド

**目的**: 環境変数が YAML 設定より優先されることを検証する。

```python
def test_env_override_slack_webhook(tmp_path, monkeypatch):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
repositories:
  - owner: org
    repo: app
""")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/override")
    settings = load_config(config_yaml)
    assert settings.slack_webhook_url == "https://hooks.slack.com/override"

def test_env_override_claude_token(tmp_path, monkeypatch):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
repositories:
  - owner: org
    repo: app
""")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test-token-123")
    settings = load_config(config_yaml)
    assert settings.claude_code_oauth_token == "test-token-123"
```

**期待結果**: 環境変数の値が YAML の値を上書きする。

---

### TC-C07: SlackConfig のオプション性

**目的**: `slack` フィールドが `None` の場合（Slack未設定）にエラーにならないことを検証する。

```python
def test_slack_config_optional(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
repositories:
  - owner: org
    repo: app
""")
    settings = load_config(config_yaml)
    assert settings.slack is None

def test_slack_config_provided():
    slack = SlackConfig(webhook_url="https://hooks.slack.com/test")
    assert slack.webhook_url == "https://hooks.slack.com/test"
    assert slack.default_channel == "#ai-agent"
```

**期待結果**: Slack未設定時は `None`、設定時はデフォルトチャンネルが `#ai-agent`。

---

### TC-C08: load_config() に存在しないファイルパスを渡した場合

**目的**: 存在しないファイルパスを `load_config()` に渡した場合に `FileNotFoundError` が発生することを検証する。

```python
import pytest

def test_load_config_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/config.yaml")
```

**期待結果**: `FileNotFoundError` が発生する。

---

### TC-C09: 不正なYAML内容の場合

**目的**: 不正なYAML内容（バリデーション不可）の場合に `ValidationError` が発生することを検証する。

```python
import pytest
from pydantic import ValidationError

def test_load_config_invalid_yaml(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
polling_interval_sec: "not_a_number"
repositories: "invalid"
""")
    with pytest.raises(ValidationError):
        load_config(config_yaml)
```

**期待結果**: `ValidationError` が発生する。

---

### TC-C10: accounts セクション付きYAMLの読み込み + AccountConfig変換テスト

**目的**: `accounts` セクションを含むYAMLファイルを読み込み、`AccountConfig` オブジェクトに正しく変換されることを検証する。

```python
def test_load_config_with_accounts(tmp_path):
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("""
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
```

**期待結果**: `accounts` セクションの各エントリが `AccountConfig` インスタンスとして正しく変換される。

---

## 13. 実装メモ

- `AccountConfig` は `dataclass` として定義する。YAML読み込み時に `dict` から手動で変換する必要がある場合は、`AppSettings` のバリデータで `AccountConfig(**v)` を呼ぶか、pydantic の `model_validator` を使用する。
- `RepositoryConfig` の `account` フィールドは `str | None = None` とする。`None` の場合は `AccountManager.resolve_account()` がデフォルトアカウントを使用する。
- `settings_customise_sources` の引数名は pydantic-settings v2 の仕様に合わせる。`settings_cls` が第1引数、残りは `**kwargs` で受け取る。
- `yaml_file` の model_config 設定は pydantic-settings の `YamlConfigSettingsSource` が参照する。パスは `load_config()` で動的に変更可能にする。
- `AppSettings.repositories` は必須フィールド（デフォルト値なし）。設定ファイルに `repositories` が未定義の場合はバリデーションエラーとなる。
