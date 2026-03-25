"""Typer CLI メインアプリケーション."""

import typer

app = typer.Typer(
    name="ai-agent",
    help="AI Multi-Agent Orchestrator - GitHub Issueを自動処理するマルチエージェントシステム",
    add_completion=False,
)


@app.callback()
def main() -> None:
    """AI Multi-Agent Orchestrator."""


# TODO: サブコマンドの登録 (commands/account.py, commands/setup.py, commands/run.py)
