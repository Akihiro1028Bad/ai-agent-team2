"""Typer CLI メインアプリケーション."""

from __future__ import annotations

import typer

from ai_agent_orchestrator.commands import (
    account_app,
    health_command,
    logs_command,
    setup_command,
    start_command,
    status_command,
    stop_command,
    unregister_command,
)

app = typer.Typer(
    name="ai-agent",
    help="AI Multi-Agent Orchestrator - GitHub Issueを自動処理するマルチエージェントシステム",
    add_completion=False,
)

# サブコマンドグループ
app.add_typer(account_app, name="account", help="GitHubアカウント管理")

# トップレベルコマンド
app.command("setup", help="リポジトリをクローンし初期設定を行う")(setup_command)
app.command("unregister", help="リポジトリをconfig.yamlから削除する")(unregister_command)
app.command("start", help="オーケストレーターを起動する")(start_command)
app.command("stop", help="オーケストレーターを停止する")(stop_command)
app.command("status", help="稼働状況を表示する")(status_command)
app.command("health", help="認証・接続のヘルスチェックを実行する")(health_command)
app.command("logs", help="ログを表示する")(logs_command)


@app.callback()
def main() -> None:
    """AI Multi-Agent Orchestrator."""
