"""ai-agent api サブコマンド (読み取り API サーバー起動).

listen は 127.0.0.1 に固定する (仕様 §設計判断5)。host はハードコードし、
公開可能なオプションは --port と --config のみとする。uvicorn.run はテスト不能
なので本モジュールは薄く保ち、ロジックは api パッケージ側に置く。
"""

from __future__ import annotations

import typer
from rich.console import Console

from ai_agent_orchestrator.config.settings import load_config

console = Console()

# listen ホストは localhost に固定 (外部公開しない)。
_API_HOST = "127.0.0.1"


def api_command(
    port: int = typer.Option(8000, "--port", "-p", help="待ち受けポート"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """読み取り API サーバーを 127.0.0.1 で起動する."""
    import uvicorn

    from ai_agent_orchestrator.api.app import create_app

    try:
        settings = load_config(config)
    except FileNotFoundError:
        console.print(f"[red]設定ファイルが見つかりません: {config}[/red]")
        raise typer.Exit(code=1) from None
    except Exception as e:  # 設定読み込み失敗は全て握って終了コード 1 で終わる
        console.print(f"[red]設定ファイルの読み込みに失敗しました: {e}[/red]")
        raise typer.Exit(code=1) from None

    app = create_app(settings)
    # config 書き込み系 (#138) が実ファイルを編集できるよう、起動時の config パスを渡す。
    from pathlib import Path

    app.state.config_path = Path(config).expanduser()
    console.print(f"[green]API を起動します:[/green] http://{_API_HOST}:{port}")
    uvicorn.run(app, host=_API_HOST, port=port)
