"""setup / unregister サブコマンド."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ai_agent_orchestrator.config.settings import load_config

console = Console()


def setup_command(
    repo: str = typer.Argument(help="owner/repo 形式のリポジトリ"),
    account: str = typer.Option(..., help="使用するGitHubアカウント名"),
    branch: str = typer.Option("main", help="ベースブランチ"),
    slack_channel: str | None = typer.Option(None, help="Slack通知チャンネル"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """リポジトリをクローンし初期設定を行う."""
    asyncio.run(_setup(repo, account, branch, slack_channel, config))


def unregister_command(
    repo: str = typer.Argument(help="owner/repo 形式のリポジトリ"),
    purge: bool = typer.Option(False, "--purge", help="ワークスペース + knowledge ディレクトリも削除"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """リポジトリをconfig.yamlから削除する."""
    asyncio.run(_unregister(repo, purge, config))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------


async def _setup(
    repo: str,
    account: str,
    branch: str,
    slack_channel: str | None,
    config_path: str,
) -> None:
    """リポジトリセットアップの非同期実装."""
    # バリデーション
    if "/" not in repo:
        console.print("[red]リポジトリは owner/repo 形式で指定してください。[/red]")
        raise typer.Exit(code=1) from None

    owner, name = repo.split("/", 1)

    console.print(Panel(f"[bold]セットアップ: {repo}[/bold]", title="ai-agent setup"))

    # Step 1: 設定ファイルの読み込みまたは作成
    config_file = Path(config_path)
    config_data: dict[str, Any] = {}
    if config_file.exists():
        with config_file.open() as f:
            config_data = yaml.safe_load(f) or {}
        console.print(f"[green]1/4[/green] 設定ファイルを読み込みました: {config_path}")
    else:
        console.print(f"[green]1/4[/green] 新規設定ファイルを作成します: {config_path}")

    # Step 2: アカウント確認
    accounts = config_data.get("accounts", {})
    if account not in accounts:
        console.print(
            f"[yellow]警告: アカウント '{account}' が設定にありません。"
            f"先に 'ai-agent account add {account}' を実行してください。[/yellow]"
        )
    console.print(f"[green]2/4[/green] アカウント: {account}")

    # Step 3: リポジトリ設定を追加
    repositories: list[dict[str, Any]] = config_data.get("repositories", [])

    # 既存チェック
    already_exists = any(r.get("owner") == owner and r.get("repo") == name for r in repositories)
    if already_exists:
        console.print(f"[yellow]リポジトリ '{repo}' は既に登録されています。設定を更新します。[/yellow]")
        repositories = [r for r in repositories if not (r.get("owner") == owner and r.get("repo") == name)]

    repo_config: dict[str, Any] = {
        "owner": owner,
        "repo": name,
        "account": account,
        "base_branch": branch,
        "label": "ai-agent",
    }
    if slack_channel:
        repo_config["slack_channel"] = slack_channel

    repositories.append(repo_config)
    config_data["repositories"] = repositories
    console.print("[green]3/4[/green] リポジトリ設定を追加しました")

    # Step 4: 設定ファイルを書き出し
    config_file.write_text(yaml.dump(config_data, allow_unicode=True, default_flow_style=False))
    console.print(f"[green]4/4[/green] 設定ファイルを保存しました: {config_path}")

    # Step 5: ラベルの確認・作成
    label_name = repo_config.get("label", "ai-agent")
    console.print(f"[bold]ラベル '{label_name}' を確認中...[/bold]")
    try:
        await _ensure_label(account, config_data.get("accounts", {}), owner, name, label_name)
        console.print(f"[green]✓[/green] ラベル '{label_name}' を確認しました")
    except Exception as e:
        console.print(
            f"[yellow]警告: ラベル '{label_name}' の自動作成に失敗しました: {e}[/yellow]"
        )
        console.print(
            f"  手動で作成してください: gh label create {label_name} --repo {owner}/{name}"
        )

    # サマリ表示
    table = Table(title="セットアップ完了")
    table.add_column("項目", style="cyan")
    table.add_column("値", style="green")
    table.add_row("リポジトリ", repo)
    table.add_row("アカウント", account)
    table.add_row("ベースブランチ", branch)
    table.add_row("Slackチャンネル", slack_channel or "(未設定)")
    table.add_row("設定ファイル", config_path)
    console.print(table)

    console.print("\n[bold green]セットアップが完了しました。[/bold green]")
    console.print("'ai-agent start' でオーケストレーターを起動できます。")


async def _unregister(repo: str, purge: bool, config_path: str) -> None:
    """リポジトリ登録解除の非同期実装."""
    if "/" not in repo:
        console.print("[red]リポジトリは owner/repo 形式で指定してください。[/red]")
        raise typer.Exit(code=1) from None

    owner, name = repo.split("/", 1)

    config_file = Path(config_path)
    if not config_file.exists():
        console.print(f"[red]設定ファイルが見つかりません: {config_path}[/red]")
        raise typer.Exit(code=1) from None

    with config_file.open() as f:
        config_data: dict[str, Any] = yaml.safe_load(f) or {}

    repositories: list[dict[str, Any]] = config_data.get("repositories", [])
    original_count = len(repositories)
    repositories = [r for r in repositories if not (r.get("owner") == owner and r.get("repo") == name)]

    if len(repositories) == original_count:
        console.print(f"[red]リポジトリ '{repo}' は登録されていません。[/red]")
        raise typer.Exit(code=1) from None

    config_data["repositories"] = repositories
    config_file.write_text(yaml.dump(config_data, allow_unicode=True, default_flow_style=False))
    console.print(f"[green]config.yaml から {repo} を削除しました。[/green]")

    # --purge: ワークスペース削除
    if purge:
        try:
            settings = load_config(config_path)
            base = Path(settings.workspace_dir).expanduser()
        except Exception:
            base = Path("~/.ai-agent-workspaces").expanduser()

        dirs_to_remove = [
            base / "repos" / f"{owner}-{name}",
            base / "knowledge" / f"{owner}-{name}",
            base / "skills" / f"{owner}-{name}",
            base / "logs" / f"{owner}-{name}",
        ]
        existing = [d for d in dirs_to_remove if d.exists()]

        if existing:
            console.print("以下のディレクトリを削除します:")
            for d in existing:
                console.print(f"  {d}")

            if typer.confirm("よろしいですか?"):
                import shutil

                for d in existing:
                    shutil.rmtree(d)
                    console.print(f"  [red]削除: {d}[/red]")
            else:
                console.print("削除をキャンセルしました。")

    console.print(f"[bold green]unregister完了: {repo}[/bold green]")


async def _ensure_label(
    account_name: str,
    accounts_data: dict[str, Any],
    owner: str,
    repo: str,
    label_name: str,
) -> None:
    """リポジトリにラベルが存在することを確認し、なければ作成する.

    Args:
        account_name: 使用するアカウント名.
        accounts_data: config の accounts セクション.
        owner: リポジトリオーナー.
        repo: リポジトリ名.
        label_name: 確認・作成するラベル名.
    """
    from ai_agent_orchestrator.config.settings import AccountConfig, RepositoryConfig
    from ai_agent_orchestrator.credential import CredentialResolver
    from ai_agent_orchestrator.github.client import GitHubClient

    # アカウント設定を構築
    acct_data = accounts_data.get(account_name, {})
    account = AccountConfig(
        name=account_name,
        token_env=acct_data.get("token_env"),
        token_command=acct_data.get("token_command"),
        default=acct_data.get("default", False),
    )

    resolver = CredentialResolver()
    token = await resolver.resolve(account)
    client = GitHubClient(token=token)

    repo_config = RepositoryConfig(owner=owner, repo=repo, label=label_name)
    await client.create_label(
        repo=repo_config,
        name=label_name,
        color="0E8A16",
        description="AI Agent が処理する Issue",
    )
