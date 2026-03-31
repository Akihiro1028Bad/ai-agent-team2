"""start/stop/status/health/logs サブコマンド."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_agent_orchestrator.config.settings import load_config

console = Console()

# PIDファイルのデフォルトパス
_PID_FILE = Path("~/.ai-agent-workspaces/.pid").expanduser()


def start_command(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="フォアグラウンド実行"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """オーケストレーターを起動する."""
    if foreground:
        asyncio.run(_start_foreground(config))
    else:
        asyncio.run(_start_foreground(config))


def stop_command() -> None:
    """オーケストレーターを停止する."""
    _send_stop_signal()


def status_command(
    json_output: bool = typer.Option(False, "--json", help="JSON形式で出力"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """稼働状況を表示する."""
    asyncio.run(_show_status(json_output, config))


def health_command(
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """認証・接続のヘルスチェックを実行する."""
    asyncio.run(_check_health(config))


def logs_command(
    repo: str | None = typer.Option(None, help="リポジトリでフィルタ"),
    issue: int | None = typer.Option(None, help="Issue番号でフィルタ"),
    follow: bool = typer.Option(False, "-f", help="リアルタイム表示"),
    lines: int = typer.Option(50, "-n", help="表示行数"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """ログを表示する."""
    asyncio.run(_show_logs(repo, issue, follow, lines, config))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _start_foreground(config_path: str) -> None:
    """フォアグラウンドでオーケストレーターを起動."""
    from ai_agent_orchestrator.orchestrator.orchestrator import Orchestrator

    try:
        settings = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]設定ファイルが見つかりません: {config_path}[/red]")
        console.print("'ai-agent setup <owner/repo> --account <name>' で初期設定を行ってください。")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console.print(f"[red]設定ファイルの読み込みに失敗しました: {e}[/red]")
        raise typer.Exit(code=1) from None

    # Orchestrator を生成 (Poller / EventRouter は内部で後から接続)
    orchestrator = Orchestrator(settings)

    # Poller / EventRouter を構築して注入 (start() 前に設定)
    from ai_agent_orchestrator.poller.event_router import EventRouter
    from ai_agent_orchestrator.poller.github_poller import GitHubPoller

    poller = GitHubPoller(
        account_manager=orchestrator.account_manager,
        repos=settings.repositories,
        interval_sec=settings.polling_interval_sec,
        approve_comment=settings.approve_comment,
    )
    router = EventRouter(
        state_machine=orchestrator.state_machine,
        task_queue=orchestrator.task_queue,
        account_manager=orchestrator.account_manager,
    )
    orchestrator.set_poller(poller)  # type: ignore[arg-type]
    orchestrator.set_event_router(router)  # type: ignore[arg-type]

    # PIDファイルを書き込み
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))

    console.print(Panel("[bold green]Orchestrator を起動します[/bold green]", title="ai-agent"))
    console.print(f"PID: {os.getpid()}")
    console.print(f"設定: {config_path}")
    console.print(f"リポジトリ: {[f'{r.owner}/{r.repo}' for r in settings.repositories]}")
    console.print("停止するには Ctrl+C または 'ai-agent stop' を実行してください。\n")

    # シグナルハンドラ設定
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        console.print("\n[yellow]停止シグナルを受信しました...[/yellow]")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        await orchestrator.start()
        # 停止シグナルを待機
        await stop_event.wait()
    finally:
        await orchestrator.stop()
        if _PID_FILE.exists():
            _PID_FILE.unlink()
        console.print("[bold]Orchestrator を停止しました。[/bold]")


def _send_stop_signal() -> None:
    """PIDファイルを読んで停止シグナルを送信."""
    if not _PID_FILE.exists():
        console.print("[yellow]稼働中のオーケストレーターが見つかりません。[/yellow]")
        raise typer.Exit(code=1) from None

    try:
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        console.print(f"[green]停止シグナルを送信しました (PID: {pid})[/green]")
    except ProcessLookupError:
        console.print("[yellow]プロセスが見つかりません。PIDファイルを削除します。[/yellow]")
        _PID_FILE.unlink(missing_ok=True)
    except ValueError:
        console.print("[red]PIDファイルが不正です。[/red]")
        _PID_FILE.unlink(missing_ok=True)
        raise typer.Exit(code=1) from None


async def _show_status(json_output: bool, config_path: str) -> None:
    """稼働状況を表示."""
    is_running = _PID_FILE.exists()
    pid: int | None = None
    if is_running:
        try:
            pid = int(_PID_FILE.read_text().strip())
            # プロセスが実際に存在するか確認
            os.kill(pid, 0)
        except (ProcessLookupError, ValueError):
            is_running = False
            pid = None

    status_data: dict[str, Any] = {
        "running": is_running,
        "pid": pid,
    }

    # 設定の読み込みを試みる
    try:
        settings = load_config(config_path)
        status_data["repositories"] = [f"{r.owner}/{r.repo}" for r in settings.repositories]
        status_data["concurrency"] = {
            "max_total": settings.concurrency.max_total,
            "max_per_repo": settings.concurrency.max_per_repo,
        }
    except Exception:
        status_data["repositories"] = []

    if json_output:
        console.print(json.dumps(status_data, indent=2))
        return

    # Rich 表示
    status_str = "[green]Running[/green]" if is_running else "[red]Stopped[/red]"
    console.print(Panel(f"ステータス: {status_str}", title="ai-agent status"))

    if pid:
        console.print(f"PID: {pid}")

    repos = status_data.get("repositories", [])
    if repos:
        table = Table(title="登録リポジトリ")
        table.add_column("リポジトリ", style="cyan")
        for r in repos:
            table.add_row(str(r))
        console.print(table)

    if not is_running:
        console.print("\n'ai-agent start' でオーケストレーターを起動できます。")


async def _check_health(config_path: str) -> None:
    """ヘルスチェック."""
    from ai_agent_orchestrator.credential import CredentialResolver

    try:
        settings = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]設定ファイルが見つかりません: {config_path}[/red]")
        raise typer.Exit(code=1) from None
    except Exception as e:
        console.print(f"[red]設定ファイルの読み込みに失敗しました: {e}[/red]")
        raise typer.Exit(code=1) from None

    console.print(Panel("[bold]ヘルスチェック実行中...[/bold]", title="ai-agent health"))
    resolver = CredentialResolver()

    table = Table(title="ヘルスチェック結果")
    table.add_column("チェック項目", style="cyan")
    table.add_column("ステータス")
    table.add_column("詳細", style="dim")

    # 設定ファイル
    table.add_row("設定ファイル", "[green]OK[/green]", config_path)

    # アカウント検証
    all_ok = True
    for account_name, account in settings.accounts.items():
        try:
            token = await resolver.resolve(account)
            user_info = await resolver.verify(token)
            login = user_info.get("login", "unknown")
            table.add_row(f"GitHub ({account_name})", "[green]OK[/green]", f"user={login}")
        except Exception as e:
            table.add_row(f"GitHub ({account_name})", "[red]NG[/red]", str(e))
            all_ok = False

    # PID check
    if _PID_FILE.exists():
        try:
            pid = int(_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            table.add_row("Orchestrator Process", "[green]Running[/green]", f"PID={pid}")
        except (ProcessLookupError, ValueError):
            table.add_row("Orchestrator Process", "[yellow]Stale PID[/yellow]", "PIDファイルが残っています")
    else:
        table.add_row("Orchestrator Process", "[dim]Not running[/dim]", "")

    console.print(table)

    if all_ok:
        console.print("\n[bold green]全てのチェックが正常です。[/bold green]")
    else:
        console.print("\n[bold red]一部のチェックに失敗しました。[/bold red]")
        raise typer.Exit(code=1) from None


async def _show_logs(
    repo: str | None,
    issue: int | None,
    follow: bool,
    lines: int,
    config_path: str,
) -> None:
    """ログの表示."""
    try:
        settings = load_config(config_path)
        log_dir = Path(settings.workspace_dir).expanduser() / "logs"
    except Exception:
        log_dir = Path("~/.ai-agent-workspaces/logs").expanduser()

    if not log_dir.exists():
        console.print("[yellow]ログディレクトリが見つかりません。[/yellow]")
        console.print(f"  {log_dir}")
        return

    # Issue が指定された場合はそのログを表示
    if issue is not None:
        events_file = log_dir / f"issue-{issue}" / "events.jsonl"
        if not events_file.exists():
            console.print(f"[yellow]Issue #{issue} のログが見つかりません。[/yellow]")
            return
        _tail_jsonl(events_file, lines)
        return

    # 全体のログを探索
    log_files: list[Path] = sorted(log_dir.glob("*/events.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not log_files:
        console.print("[yellow]ログファイルがありません。[/yellow]")
        return

    # 全ログをマージして最新 N 行を表示
    all_entries: list[dict[str, Any]] = []
    for log_file in log_files:
        try:
            with log_file.open() as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry: dict[str, Any] = json.loads(line)
                        if repo and entry.get("repo") != repo:
                            continue
                        all_entries.append(entry)
        except (json.JSONDecodeError, OSError):
            continue

    # タイムスタンプでソートして最新 N 件
    all_entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    display_entries = all_entries[:lines]
    display_entries.reverse()

    if not display_entries:
        console.print("[yellow]表示するログがありません。[/yellow]")
        return

    table = Table(title=f"最新ログ ({len(display_entries)} 件)")
    table.add_column("時刻", style="dim")
    table.add_column("Issue", style="cyan")
    table.add_column("Phase", style="green")
    table.add_column("Event", style="yellow")

    for entry in display_entries:
        ts = str(entry.get("ts", ""))[:19]
        issue_num = str(entry.get("issue", ""))
        phase = str(entry.get("phase", ""))
        event = str(entry.get("event", ""))
        table.add_row(ts, issue_num, phase, event)

    console.print(table)


def _tail_jsonl(file_path: Path, lines: int) -> None:
    """JSONLファイルの末尾を表示."""
    entries: list[dict[str, Any]] = []
    with file_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    display = entries[-lines:]

    table = Table(title=f"ログ: {file_path.parent.name} ({len(display)} 件)")
    table.add_column("時刻", style="dim")
    table.add_column("Phase", style="green")
    table.add_column("Event", style="yellow")
    table.add_column("Data", style="dim", max_width=60)

    for entry in display:
        ts = str(entry.get("ts", ""))[:19]
        phase = str(entry.get("phase", ""))
        event = str(entry.get("event", ""))
        data = json.dumps(entry.get("data", {}), ensure_ascii=False)[:60] if entry.get("data") else ""
        table.add_row(ts, phase, event, data)

    console.print(table)
