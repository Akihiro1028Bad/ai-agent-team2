"""account サブコマンド (add/list/verify/remove)."""

from __future__ import annotations

import asyncio
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ai_agent_orchestrator.config.settings import AccountConfig, load_config
from ai_agent_orchestrator.credential import CredentialError, CredentialResolver

console = Console()
account_app = typer.Typer(help="GitHubアカウント管理")


@account_app.command("add")
def account_add(
    name: str = typer.Argument(help="アカウント名 (config.yaml の accounts キー)"),
    token: str | None = typer.Option(None, help="GitHubトークン (keyringに保存)"),
    token_env: str | None = typer.Option(None, "--token-env", help="トークンの環境変数名"),
    token_command: str | None = typer.Option(None, "--token-command", help="トークン取得コマンド"),
    default: bool = typer.Option(False, "--default", help="デフォルトアカウントに設定"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """GitHubアカウントを追加し、トークンをkeyringに保存する."""
    asyncio.run(_account_add(name, token, token_env, token_command, default, config))


@account_app.command("list")
def account_list(
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """登録済みアカウント一覧を表示する."""
    asyncio.run(_account_list(config))


@account_app.command("verify")
def account_verify(
    name: str | None = typer.Argument(None, help="検証するアカウント名 (省略時は全アカウント)"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """アカウントのトークンを検証する."""
    asyncio.run(_account_verify(name, config))


@account_app.command("remove")
def account_remove(
    name: str = typer.Argument(help="削除するアカウント名"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """アカウントを削除し、keyringからトークンを除去する."""
    asyncio.run(_account_remove(name, config))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _account_add(
    name: str,
    token: str | None,
    token_env: str | None,
    token_command: str | None,
    default: bool,
    config_path: str,
) -> None:
    """アカウント追加の非同期実装."""
    resolver = CredentialResolver()

    # トークンが直接指定された場合はkeyringに保存
    if token:
        await resolver.store(name, token)
        console.print(f"[green]トークンをkeyringに保存しました: {name}[/green]")

        # 検証
        try:
            user_info = await resolver.verify(token)
            login: str = user_info.get("login", "unknown")
            console.print(f"[green]認証成功: {login}[/green]")
        except CredentialError as e:
            console.print(f"[yellow]警告: トークン検証に失敗しました: {e}[/yellow]")

    # 設定情報の表示
    account_info: dict[str, str | bool] = {"name": name}
    if token_env:
        account_info["token_env"] = token_env
    if token_command:
        account_info["token_command"] = token_command
    if default:
        account_info["default"] = default

    console.print(f"\n[bold]アカウント '{name}' を登録しました。[/bold]")
    console.print("config.yaml に以下を追加してください:")
    console.print("  accounts:")
    console.print(f"    {name}:")
    console.print(f"      name: {name}")
    if token_env:
        console.print(f"      token_env: {token_env}")
    if token_command:
        console.print(f"      token_command: {token_command}")
    if default:
        console.print("      default: true")


async def _account_list(config_path: str) -> None:
    """アカウント一覧の非同期実装."""
    try:
        settings = load_config(config_path)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]設定ファイルの読み込みに失敗しました: {e}[/red]")
        raise typer.Exit(code=1) from None

    if not settings.accounts:
        console.print("[yellow]登録済みアカウントはありません。[/yellow]")
        return

    table = Table(title="登録済みアカウント")
    table.add_column("名前", style="cyan")
    table.add_column("トークンソース", style="green")
    table.add_column("デフォルト", style="yellow")

    for account_name, account in settings.accounts.items():
        source = _get_token_source(account)
        is_default = "Yes" if account.default else ""
        table.add_row(account_name, source, is_default)

    console.print(table)


async def _account_verify(name: str | None, config_path: str) -> None:
    """アカウント検証の非同期実装."""
    try:
        settings = load_config(config_path)
    except (FileNotFoundError, Exception) as e:
        console.print(f"[red]設定ファイルの読み込みに失敗しました: {e}[/red]")
        raise typer.Exit(code=1) from None

    resolver = CredentialResolver()

    accounts_to_verify: dict[str, AccountConfig] = {}
    if name:
        if name not in settings.accounts:
            console.print(f"[red]アカウント '{name}' が見つかりません。[/red]")
            raise typer.Exit(code=1) from None
        accounts_to_verify[name] = settings.accounts[name]
    else:
        accounts_to_verify = dict(settings.accounts)

    if not accounts_to_verify:
        console.print("[yellow]検証するアカウントがありません。[/yellow]")
        return

    table = Table(title="アカウント検証結果")
    table.add_column("名前", style="cyan")
    table.add_column("ステータス")
    table.add_column("ユーザー", style="green")
    table.add_column("スコープ", style="dim")

    for account_name, account in accounts_to_verify.items():
        try:
            token = await resolver.resolve(account)
            user_info: dict[str, Any] = await resolver.verify(token)
            login = user_info.get("login", "unknown")
            scopes = ", ".join(user_info.get("scopes", []))
            table.add_row(account_name, "[green]OK[/green]", str(login), scopes)
        except (CredentialError, Exception) as e:
            table.add_row(account_name, f"[red]NG: {e}[/red]", "", "")

    console.print(table)


async def _account_remove(name: str, config_path: str) -> None:
    """アカウント削除の非同期実装."""
    resolver = CredentialResolver()

    # keyringからトークンを削除
    await resolver.delete(name)
    console.print(f"[green]keyringからトークンを削除しました: {name}[/green]")
    console.print(f"config.yaml から accounts.{name} を手動で削除してください。")


def _get_token_source(account: AccountConfig) -> str:
    """トークンソースの表示文字列を取得する."""
    sources: list[str] = ["keyring"]
    if account.token_env:
        sources.append(f"env:{account.token_env}")
    if account.token_command:
        sources.append(f"cmd:{account.token_command}")
    sources.append("gh-cli")
    return " -> ".join(sources)
