"""CLI コマンドのテスト."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from ai_agent_orchestrator.cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Help output tests
# ---------------------------------------------------------------------------


def test_main_help():
    """メインヘルプが表示されること."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "AI Multi-Agent Orchestrator" in result.output


def test_main_help_shows_japanese_descriptions():
    """メインヘルプに各コマンドの日本語説明が表示されること."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    # 各コマンドの日本語説明が表示される
    assert "リポジトリをクローンし初期設定を行う" in result.output
    assert "リポジトリをconfig.yamlから削除する" in result.output
    assert "オーケストレーターを起動する" in result.output
    assert "オーケストレーターを停止する" in result.output
    assert "稼働状況を表示する" in result.output
    assert "認証・接続のヘルスチェックを実行する" in result.output
    assert "ログを表示する" in result.output


def test_main_help_shows_account_description():
    """メインヘルプにaccountサブコマンドの日本語説明が表示されること."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "GitHubアカウント管理" in result.output


def test_account_help():
    """account サブコマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["account", "--help"])
    assert result.exit_code == 0
    assert "account" in result.output.lower()


def test_account_help_shows_japanese_descriptions():
    """account サブコマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["account", "--help"])
    assert result.exit_code == 0
    assert "GitHubアカウントを追加" in result.output
    assert "登録済みアカウント一覧を表示する" in result.output
    assert "アカウントのトークンを検証する" in result.output
    assert "アカウントを削除" in result.output


def test_setup_help():
    """setup コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "owner/repo" in result.output


def test_setup_help_shows_japanese_description():
    """setup コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0
    assert "リポジトリをクローンし初期設定を行う" in result.output


def test_start_help():
    """start コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "config" in result.output.lower()


def test_start_help_shows_japanese_description():
    """start コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["start", "--help"])
    assert result.exit_code == 0
    assert "オーケストレーターを起動する" in result.output
    assert "フォアグラウンド実行" in result.output


def test_stop_help():
    """stop コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["stop", "--help"])
    assert result.exit_code == 0


def test_stop_help_shows_japanese_description():
    """stop コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["stop", "--help"])
    assert result.exit_code == 0
    assert "オーケストレーターを停止する" in result.output


def test_status_help():
    """status コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "json" in result.output.lower()


def test_status_help_shows_japanese_description():
    """status コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["status", "--help"])
    assert result.exit_code == 0
    assert "稼働状況を表示する" in result.output


def test_health_help():
    """health コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["health", "--help"])
    assert result.exit_code == 0


def test_health_help_shows_japanese_description():
    """health コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["health", "--help"])
    assert result.exit_code == 0
    assert "認証・接続のヘルスチェックを実行する" in result.output


def test_logs_help():
    """logs コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["logs", "--help"])
    assert result.exit_code == 0


def test_logs_help_shows_japanese_description():
    """logs コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["logs", "--help"])
    assert result.exit_code == 0
    assert "ログを表示する" in result.output
    assert "リポジトリでフィルタ" in result.output
    assert "Issue番号でフィルタ" in result.output


def test_unregister_help():
    """unregister コマンドのヘルプが表示されること."""
    result = runner.invoke(app, ["unregister", "--help"])
    assert result.exit_code == 0


def test_unregister_help_shows_japanese_description():
    """unregister コマンドのヘルプに日本語説明が表示されること."""
    result = runner.invoke(app, ["unregister", "--help"])
    assert result.exit_code == 0
    assert "リポジトリをconfig.yamlから削除する" in result.output


# ---------------------------------------------------------------------------
# Account commands
# ---------------------------------------------------------------------------


def test_account_add_with_token(tmp_path):
    """account add でトークンをkeyringに保存できること."""
    mock_store = AsyncMock()
    mock_verify = AsyncMock(return_value={"login": "testuser", "scopes": ["repo"]})

    with (
        patch("ai_agent_orchestrator.commands.account.CredentialResolver.store", mock_store),
        patch("ai_agent_orchestrator.commands.account.CredentialResolver.verify", mock_verify),
    ):
        result = runner.invoke(app, ["account", "add", "myaccount", "--token", "ghp_test123"])
        assert result.exit_code == 0
        assert "myaccount" in result.output


def test_account_add_with_env():
    """account add で環境変数オプションを指定できること."""
    result = runner.invoke(app, ["account", "add", "myaccount", "--token-env", "MY_GH_TOKEN"])
    assert result.exit_code == 0
    assert "myaccount" in result.output


def test_account_list_no_config(tmp_path):
    """config未存在時にaccount listがエラーを返すこと."""
    config_path = str(tmp_path / "nonexistent.yaml")
    result = runner.invoke(app, ["account", "list", "--config", config_path])
    assert result.exit_code == 1


def test_account_list_with_config(tmp_path):
    """account list で登録済みアカウントが表示されること."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
repositories:
  - owner: "test-owner"
    repo: "test-repo"
    account: "default"
    base_branch: "main"

accounts:
  default:
    name: default
    token_env: "GITHUB_TOKEN_TEST"
    default: true
"""
    )
    result = runner.invoke(app, ["account", "list", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "default" in result.output


def test_account_verify_no_config(tmp_path):
    """config未存在時にaccount verifyがエラーを返すこと."""
    config_path = str(tmp_path / "nonexistent.yaml")
    result = runner.invoke(app, ["account", "verify", "--config", config_path])
    assert result.exit_code == 1


def test_account_remove():
    """account remove がkeyringからトークンを削除すること."""
    mock_delete = AsyncMock()
    with patch("ai_agent_orchestrator.commands.account.CredentialResolver.delete", mock_delete):
        result = runner.invoke(app, ["account", "remove", "myaccount"])
        assert result.exit_code == 0
        assert "myaccount" in result.output
        mock_delete.assert_called_once_with("myaccount")


# ---------------------------------------------------------------------------
# Setup / Unregister commands
# ---------------------------------------------------------------------------


def test_setup_creates_config(tmp_path):
    """setup でconfig.yamlが作成されること."""
    config_path = str(tmp_path / "config.yaml")
    result = runner.invoke(
        app,
        ["setup", "myorg/myrepo", "--account", "default", "--config", config_path],
    )
    assert result.exit_code == 0
    assert "myorg/myrepo" in result.output
    assert Path(config_path).exists()


def test_setup_invalid_repo_format(tmp_path):
    """owner/repo 形式でない場合にエラーになること."""
    config_path = str(tmp_path / "config.yaml")
    result = runner.invoke(app, ["setup", "invalidrepo", "--account", "default", "--config", config_path])
    assert result.exit_code == 1


def test_unregister_removes_repo(tmp_path):
    """unregister でリポジトリがconfig.yamlから削除されること."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
repositories:
  - owner: myorg
    repo: myrepo
    account: default
    base_branch: main
"""
    )
    result = runner.invoke(app, ["unregister", "myorg/myrepo", "--config", str(config_path)])
    assert result.exit_code == 0
    assert "myorg/myrepo" in result.output


def test_unregister_repo_not_found(tmp_path):
    """登録されていないリポジトリのunregisterがエラーを返すこと."""
    config_path = tmp_path / "config.yaml"
    config_path.write_text("repositories: []\n")
    result = runner.invoke(app, ["unregister", "myorg/unknown", "--config", str(config_path)])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------


def test_status_not_running(tmp_path, tmp_config):
    """停止中のstatus表示."""
    with patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "nonexistent.pid"):
        result = runner.invoke(app, ["status", "--config", str(tmp_config)])
        assert result.exit_code == 0
        assert "Stopped" in result.output or "status" in result.output.lower()


def test_status_json_output(tmp_path, tmp_config):
    """JSON形式のstatus表示."""
    with patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "nonexistent.pid"):
        result = runner.invoke(app, ["status", "--json", "--config", str(tmp_config)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "running" in data
        assert data["running"] is False


# ---------------------------------------------------------------------------
# Stop command
# ---------------------------------------------------------------------------


def test_stop_no_pid_file(tmp_path):
    """PIDファイルが存在しない場合にstopがエラーを返すこと."""
    with patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "nonexistent.pid"):
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Logs command
# ---------------------------------------------------------------------------


def test_logs_no_log_dir(tmp_path, tmp_config):
    """ログディレクトリが存在しない場合."""
    with patch("ai_agent_orchestrator.commands.run.load_config") as mock_config:
        mock_settings = mock_config.return_value
        mock_settings.workspace_dir = str(tmp_path / "nonexistent")
        result = runner.invoke(app, ["logs", "--config", str(tmp_config)])
        assert result.exit_code == 0


def test_logs_with_issue(tmp_path, tmp_config):
    """Issue指定のログ表示."""
    log_dir = tmp_path / "workspace" / "logs" / "issue-42"
    log_dir.mkdir(parents=True)
    events_file = log_dir / "events.jsonl"
    events_file.write_text(
        json.dumps({"ts": "2026-01-01T00:00:00", "issue": 42, "phase": "hearing", "event": "test_event"}) + "\n"
    )

    with patch("ai_agent_orchestrator.commands.run.load_config") as mock_config:
        mock_settings = mock_config.return_value
        mock_settings.workspace_dir = str(tmp_path / "workspace")
        result = runner.invoke(app, ["logs", "--issue", "42", "--config", str(tmp_config)])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Health command
# ---------------------------------------------------------------------------


def test_health_no_config(tmp_path):
    """設定ファイルがない場合にhealthがエラーを返すこと."""
    config_path = str(tmp_path / "nonexistent.yaml")
    result = runner.invoke(app, ["health", "--config", config_path])
    assert result.exit_code == 1
