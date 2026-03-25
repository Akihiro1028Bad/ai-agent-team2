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
app.add_typer(account_app, name="account")

# トップレベルコマンド
app.command("setup")(setup_command)
app.command("unregister")(unregister_command)
app.command("start")(start_command)
app.command("stop")(stop_command)
app.command("status")(status_command)
app.command("health")(health_command)
app.command("logs")(logs_command)


@app.callback()
def main() -> None:
    """AI Multi-Agent Orchestrator."""
