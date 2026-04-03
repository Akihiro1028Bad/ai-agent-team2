"""Web サーバー起動コマンド."""

from __future__ import annotations

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

console = Console()


def web_command(
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="バインドホスト"),  # noqa: S104
    port: int = typer.Option(8080, "--port", "-p", help="ポート番号"),
    reload: bool = typer.Option(False, "--reload", help="ホットリロード(開発用)"),
) -> None:
    """Web UIサーバーを起動する."""
    console.print(
        Panel(
            f"[bold cyan]🌐  AI Agent Web Server[/bold cyan]\n"
            f"   URL: http://{host}:{port}\n"
            f"   Health: http://{host}:{port}/api/health",
            expand=False,
        )
    )
    uvicorn.run(
        "ai_agent_orchestrator.web.app:create_app",
        host=host,
        port=port,
        reload=reload,
        factory=True,
    )
