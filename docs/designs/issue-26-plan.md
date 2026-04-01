# Issue #26: 実装計画 — ヘルスチェックコマンドにリポジトリごとのAPI接続テストを追加

## 変更ファイル一覧と実装順序

| 順序 | ファイル | 変更種別 | 概要 |
|------|----------|----------|------|
| 1 | `src/ai_agent_orchestrator/github/client.py` | 変更 | `get_repository()`, `list_labels()` メソッド追加 |
| 2 | `tests/unit/test_github_client.py` | 変更 | 上記メソッドのユニットテスト追加 (4件) |
| 3 | `src/ai_agent_orchestrator/commands/run.py` | 変更 | `RepoHealthResult`, `_check_repo_health()`, `_print_repo_health_table()`, `_check_health()` 拡張 |
| 4 | `tests/unit/test_cli.py` | 変更 | health コマンドのリポジトリ別チェックテスト追加 (4件) |

### 依存関係

```
Step 1 (client.py) → Step 2 (test_github_client.py)
                   → Step 3 (run.py) → Step 4 (test_cli.py)
```

- Step 1 が全ての起点。`GitHubClient` に新メソッドを追加しないと後続が書けない
- Step 2 と Step 3 は Step 1 完了後に並行実施可能
- Step 4 は Step 3 完了後に実施

---

## Step 1: `src/ai_agent_orchestrator/github/client.py`

### 変更箇所

`GitHubClient` クラスの `# ── CI/CD 操作 ──` セクション直前（`get_check_runs` の前、562行目付近）に2メソッドを追加する。

### 追加内容

#### 1-1. `get_repository()` メソッド

```python
async def get_repository(
    self,
    repo: RepositoryConfig,
) -> dict[str, Any]:
    """リポジトリ情報を取得する.

    Args:
        repo: リポジトリ設定.

    Returns:
        リポジトリ情報の辞書 (name, full_name, private, permissions 等).

    Raises:
        githubkit.exception.RequestFailed: API リクエスト失敗時.
    """
    response = await self._github.rest.repos.async_get(
        owner=repo.owner,
        repo=repo.repo,
    )
    data = response.parsed_data
    return {
        "name": data.name,
        "full_name": data.full_name,
        "private": data.private,
        "permissions": {
            "admin": data.permissions.admin if data.permissions else False,
            "push": data.permissions.push if data.permissions else False,
            "pull": data.permissions.pull if data.permissions else False,
        },
    }
```

**配置場所**: `get_issues_with_label()` の後、`get_check_runs()` の前。
`# ── リポジトリ情報 ──` セクションヘッダを新設する。

#### 1-2. `list_labels()` メソッド

```python
async def list_labels(
    self,
    repo: RepositoryConfig,
) -> list[str]:
    """リポジトリのラベル名一覧を取得する.

    Args:
        repo: リポジトリ設定.

    Returns:
        ラベル名のリスト.
    """
    response = await self._github.rest.issues.async_list_labels_for_repo(
        owner=repo.owner,
        repo=repo.repo,
        per_page=100,
    )
    return [label.name for label in response.parsed_data if label.name]
```

**配置場所**: `get_repository()` の直後。

### 既存コードへの影響

- 既存メソッド・クラスに変更なし
- import の追加なし（`Any` は既にインポート済み）

---

## Step 2: `tests/unit/test_github_client.py`

### 追加テストケース (4件)

ファイル末尾（`test_add_label` テストの後）に追加。

#### 2-1. `test_get_repository_success`

```python
@respx.mock
async def test_get_repository_success(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """リポジトリ情報を正常に取得でき permissions を含むこと."""
    repo_data = _repo_json()
    repo_data["permissions"] = {"admin": True, "push": True, "pull": True}
    respx.get("https://api.github.com/repos/test-org/test-repo").mock(
        return_value=httpx.Response(200, json=repo_data)
    )

    result = await client.get_repository(repo_config)

    assert result["full_name"] == "test-org/test-repo"
    assert result["permissions"]["push"] is True
    assert result["permissions"]["admin"] is True
```

#### 2-2. `test_get_repository_not_found`

```python
@respx.mock
async def test_get_repository_not_found(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """存在しないリポジトリで RequestFailed(404) が送出されること."""
    from githubkit.exception import RequestFailed

    respx.get("https://api.github.com/repos/test-org/test-repo").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    with pytest.raises(RequestFailed):
        await client.get_repository(repo_config)
```

#### 2-3. `test_list_labels_success`

```python
@respx.mock
async def test_list_labels_success(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """ラベル名リストが正しく返ること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/labels").mock(
        return_value=httpx.Response(
            200,
            json=[_label("ai-agent"), _label("phase:hearing"), _label("bug")],
        )
    )

    labels = await client.list_labels(repo_config)

    assert len(labels) == 3
    assert "ai-agent" in labels
    assert "phase:hearing" in labels
```

#### 2-4. `test_list_labels_empty`

```python
@respx.mock
async def test_list_labels_empty(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """ラベルが0件の場合に空リストが返ること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/labels").mock(
        return_value=httpx.Response(200, json=[])
    )

    labels = await client.list_labels(repo_config)

    assert labels == []
```

### 既存テストへの影響

- 既存テストに変更なし
- `RequestFailed` の import は `test_get_repository_not_found` 内でローカルインポート

---

## Step 3: `src/ai_agent_orchestrator/commands/run.py`

### 変更箇所一覧

1. `dataclass` を import に追加 (冒頭)
2. `RepoHealthResult` dataclass を定義 (`console = Console()` の後)
3. `REQUIRED_PHASE_LABELS` 定数を定義
4. `_check_repo_health()` 非同期関数を追加
5. `_print_repo_health_table()` 関数を追加
6. `_check_health()` 関数を拡張

### 3-1. import の追加

```python
from dataclasses import dataclass
```

既存の `from __future__ import annotations` の後のブロックに追加。

### 3-2. `RepoHealthResult` dataclass

`console = Console()` の直後、`_PID_FILE` の前に配置。

```python
@dataclass(frozen=True)
class RepoHealthResult:
    """リポジトリごとのヘルスチェック結果."""

    repo_full_name: str
    auth_ok: bool
    auth_detail: str
    access_ok: bool
    access_detail: str
    label_ok: bool
    label_detail: str
    missing_labels: list[str]


REQUIRED_PHASE_LABELS: list[str] = [
    "phase:type-detection",
    "phase:hearing",
    "phase:hearing-wait",
    "phase:design",
    "phase:design-review",
    "phase:planning",
    "phase:implement",
    "phase:ci-fix",
    "phase:impl-review",
    "phase:impl-revise",
    "phase:done",
]
```

### 3-3. `_check_repo_health()` 関数

`_check_health()` の前に配置。

```python
async def _check_repo_health(
    repo_config: RepositoryConfig,
    client: GitHubClient,
) -> RepoHealthResult:
    """単一リポジトリの接続テストを実行する.

    Args:
        repo_config: リポジトリ設定.
        client: 認証済み GitHubClient.

    Returns:
        ヘルスチェック結果.
    """
    from githubkit.exception import RequestFailed

    repo_full_name = f"{repo_config.owner}/{repo_config.repo}"

    # Step 1 & 2: 認証 + リポジトリアクセス確認
    try:
        repo_info = await client.get_repository(repo_config)
    except RequestFailed as exc:
        status_code = exc.response.status_code
        if status_code == 401:
            detail = "認証失敗"
        elif status_code == 403:
            detail = "権限不足"
        elif status_code == 404:
            detail = "リポジトリが見つかりません"
        else:
            detail = f"APIエラー (status={status_code})"
        return RepoHealthResult(
            repo_full_name=repo_full_name,
            auth_ok=False,
            auth_detail=detail,
            access_ok=False,
            access_detail="認証失敗のためスキップ",
            label_ok=False,
            label_detail="認証失敗のためスキップ",
            missing_labels=[],
        )
    except Exception as exc:
        return RepoHealthResult(
            repo_full_name=repo_full_name,
            auth_ok=False,
            auth_detail=f"接続に失敗しました: {exc}",
            access_ok=False,
            access_detail="認証失敗のためスキップ",
            label_ok=False,
            label_detail="認証失敗のためスキップ",
            missing_labels=[],
        )

    # 認証OK
    auth_ok = True
    permissions = repo_info.get("permissions", {})
    push_ok = permissions.get("push", False)
    admin_ok = permissions.get("admin", False)

    access_ok = bool(push_ok)
    if access_ok:
        access_detail = f"push=✓ admin={'✓' if admin_ok else '✗'}"
    else:
        access_detail = "push権限がありません"

    # Step 3: ラベル存在確認
    try:
        existing_labels = await client.list_labels(repo_config)
    except Exception:
        return RepoHealthResult(
            repo_full_name=repo_full_name,
            auth_ok=auth_ok,
            auth_detail="OK",
            access_ok=access_ok,
            access_detail=access_detail,
            label_ok=False,
            label_detail="ラベル一覧の取得に失敗しました",
            missing_labels=[],
        )

    required = [repo_config.label] + REQUIRED_PHASE_LABELS
    missing = [lbl for lbl in required if lbl not in existing_labels]
    label_ok = len(missing) == 0

    return RepoHealthResult(
        repo_full_name=repo_full_name,
        auth_ok=auth_ok,
        auth_detail="OK",
        access_ok=access_ok,
        access_detail=access_detail,
        label_ok=label_ok,
        label_detail="OK" if label_ok else f"{len(missing)}件のラベルが未作成",
        missing_labels=missing,
    )
```

**必要なローカルインポート**:
- `from ai_agent_orchestrator.config.settings import RepositoryConfig` — 型アノテーション用（`TYPE_CHECKING` で囲む）
- `from ai_agent_orchestrator.github.client import GitHubClient` — 型アノテーション用

冒頭の `TYPE_CHECKING` ブロックに追加:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.client import GitHubClient
```

### 3-4. `_print_repo_health_table()` 関数

`_check_repo_health()` の直後に配置。設計書のコードをそのまま使用。

```python
def _print_repo_health_table(results: list[RepoHealthResult]) -> None:
    """リポジトリ別ヘルスチェック結果をテーブル表示."""
    table = Table(title="リポジトリ別 API 接続テスト")
    table.add_column("リポジトリ", style="cyan")
    table.add_column("認証", justify="center")
    table.add_column("アクセス権限", justify="center")
    table.add_column("ラベル", justify="center")
    table.add_column("詳細", style="dim")

    for r in results:
        auth_status = "[green]OK[/green]" if r.auth_ok else "[red]NG[/red]"
        access_status = (
            "[green]OK[/green]" if r.access_ok
            else "[dim]--[/dim]" if not r.auth_ok
            else "[red]NG[/red]"
        )
        label_status = (
            "[green]OK[/green]" if r.label_ok
            else "[dim]--[/dim]" if not r.auth_ok
            else "[yellow]WARN[/yellow]"
        )

        details: list[str] = []
        if r.auth_ok:
            details.append(r.access_detail)
        else:
            details.append(r.auth_detail)
        if r.missing_labels:
            details.append(f"欠損: {', '.join(r.missing_labels)}")

        table.add_row(
            r.repo_full_name,
            auth_status,
            access_status,
            label_status,
            " / ".join(d for d in details if d),
        )

    console.print(table)
```

### 3-5. `_check_health()` の拡張

既存の `_check_health()` 関数の末尾を修正する。

**変更前** (L257-263):
```python
    console.print(table)

    if all_ok:
        console.print("\n[bold green]全てのチェックが正常です。[/bold green]")
    else:
        console.print("\n[bold red]一部のチェックに失敗しました。[/bold red]")
        raise typer.Exit(code=1) from None
```

**変更後**:
```python
    console.print(table)

    # --- リポジトリ別 API 接続テスト ---
    from ai_agent_orchestrator.github.client import AccountManager

    account_manager = AccountManager(
        accounts=settings.accounts,
        resolver=resolver,
        repo_configs=settings.repositories,
    )

    repo_results: list[RepoHealthResult] = []
    for repo_config in settings.repositories:
        try:
            client = await account_manager.get_client_for_repo(
                repo_config.owner, repo_config.repo,
            )
            result = await _check_repo_health(repo_config, client)
        except Exception as e:
            result = RepoHealthResult(
                repo_full_name=f"{repo_config.owner}/{repo_config.repo}",
                auth_ok=False,
                auth_detail=str(e),
                access_ok=False,
                access_detail="認証失敗のためスキップ",
                label_ok=False,
                label_detail="認証失敗のためスキップ",
                missing_labels=[],
            )
        repo_results.append(result)

    _print_repo_health_table(repo_results)

    # リポジトリチェックの認証・アクセス失敗を all_ok に反映
    repo_critical_ok = all(r.auth_ok and r.access_ok for r in repo_results)
    all_ok = all_ok and repo_critical_ok

    if all_ok:
        console.print("\n[bold green]全てのチェックが正常です。[/bold green]")
    else:
        console.print("\n[bold red]一部のチェックに失敗しました。[/bold red]")
        raise typer.Exit(code=1) from None
```

**注意点**:
- `resolver` は既存コードで L224 で生成済み。再利用する
- `settings` も既存コードで L215 で取得済み
- ラベル欠損のみの場合は `exit(0)` となる（設計書の仕様通り）

---

## Step 4: `tests/unit/test_cli.py`

### 追加テストケース (4件)

ファイル末尾（`test_health_no_config` の後）に追加。

#### テストの共通パターン

全テストで以下をモック化する:
- `load_config` → テスト用の `AppSettings` を返す
- `CredentialResolver.resolve` → 固定トークンを返す
- `CredentialResolver.verify` → 固定ユーザー情報を返す
- `AccountManager.get_client_for_repo` → モック `GitHubClient` を返す
- `_PID_FILE` → 存在しないパスに向ける

#### 4-1. `test_health_repo_check_all_ok`

```python
def test_health_repo_check_all_ok(tmp_path, tmp_config):
    """全リポジトリ正常時にリポジトリ別テーブルが表示されること."""
    mock_client = AsyncMock()
    mock_client.get_repository = AsyncMock(return_value={
        "name": "test-repo",
        "full_name": "test-owner/test-repo",
        "private": False,
        "permissions": {"admin": True, "push": True, "pull": True},
    })
    mock_client.list_labels = AsyncMock(return_value=[
        "ai-agent",
        "phase:type-detection", "phase:hearing", "phase:hearing-wait",
        "phase:design", "phase:design-review", "phase:planning",
        "phase:implement", "phase:ci-fix", "phase:impl-review",
        "phase:impl-revise", "phase:done",
    ])

    with (
        patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "no.pid"),
        patch("ai_agent_orchestrator.commands.run.CredentialResolver") as mock_resolver_cls,
        patch("ai_agent_orchestrator.commands.run.AccountManager") as mock_am_cls,
    ):
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve = AsyncMock(return_value="ghp_test")
        mock_resolver.verify = AsyncMock(return_value={"login": "testuser"})
        mock_am_cls.return_value.get_client_for_repo = AsyncMock(return_value=mock_client)

        result = runner.invoke(app, ["health", "--config", str(tmp_config)])
        assert result.exit_code == 0
        assert "OK" in result.output
```

#### 4-2. `test_health_repo_check_auth_failure`

```python
def test_health_repo_check_auth_failure(tmp_path, tmp_config):
    """認証失敗リポジトリがある場合に NG 表示かつ exit(1)."""
    with (
        patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "no.pid"),
        patch("ai_agent_orchestrator.commands.run.CredentialResolver") as mock_resolver_cls,
        patch("ai_agent_orchestrator.commands.run.AccountManager") as mock_am_cls,
    ):
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve = AsyncMock(return_value="ghp_test")
        mock_resolver.verify = AsyncMock(return_value={"login": "testuser"})
        mock_am_cls.return_value.get_client_for_repo = AsyncMock(
            side_effect=Exception("Token resolution failed")
        )

        result = runner.invoke(app, ["health", "--config", str(tmp_config)])
        assert result.exit_code == 1
        assert "NG" in result.output
```

#### 4-3. `test_health_repo_check_missing_labels`

```python
def test_health_repo_check_missing_labels(tmp_path, tmp_config):
    """ラベル欠損時に WARN 表示かつ exit(0)."""
    mock_client = AsyncMock()
    mock_client.get_repository = AsyncMock(return_value={
        "name": "test-repo",
        "full_name": "test-owner/test-repo",
        "private": False,
        "permissions": {"admin": True, "push": True, "pull": True},
    })
    mock_client.list_labels = AsyncMock(return_value=["ai-agent"])  # フェーズラベルなし

    with (
        patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "no.pid"),
        patch("ai_agent_orchestrator.commands.run.CredentialResolver") as mock_resolver_cls,
        patch("ai_agent_orchestrator.commands.run.AccountManager") as mock_am_cls,
    ):
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve = AsyncMock(return_value="ghp_test")
        mock_resolver.verify = AsyncMock(return_value={"login": "testuser"})
        mock_am_cls.return_value.get_client_for_repo = AsyncMock(return_value=mock_client)

        result = runner.invoke(app, ["health", "--config", str(tmp_config)])
        assert result.exit_code == 0  # ラベル欠損は警告のみ
```

#### 4-4. `test_health_repo_check_access_denied`

```python
def test_health_repo_check_access_denied(tmp_path, tmp_config):
    """push権限がない場合に exit(1)."""
    mock_client = AsyncMock()
    mock_client.get_repository = AsyncMock(return_value={
        "name": "test-repo",
        "full_name": "test-owner/test-repo",
        "private": False,
        "permissions": {"admin": False, "push": False, "pull": True},
    })
    mock_client.list_labels = AsyncMock(return_value=["ai-agent"])

    with (
        patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "no.pid"),
        patch("ai_agent_orchestrator.commands.run.CredentialResolver") as mock_resolver_cls,
        patch("ai_agent_orchestrator.commands.run.AccountManager") as mock_am_cls,
    ):
        mock_resolver = mock_resolver_cls.return_value
        mock_resolver.resolve = AsyncMock(return_value="ghp_test")
        mock_resolver.verify = AsyncMock(return_value={"login": "testuser"})
        mock_am_cls.return_value.get_client_for_repo = AsyncMock(return_value=mock_client)

        result = runner.invoke(app, ["health", "--config", str(tmp_config)])
        assert result.exit_code == 1
```

---

## テスト方針

### 全体方針

- **TDD**: 各 Step の実装コードを書いた後、即座にテストを実行して通ることを確認
- **モック戦略**: `respx` で HTTP レベルをモック (Step 2)、`unittest.mock.patch` + `AsyncMock` でモジュールレベルをモック (Step 4)
- **既存テスト保護**: 既存テストが全件パスすることを各 Step 完了時に確認

### テスト実行コマンド

```bash
# Step 2 完了後
uv run pytest tests/unit/test_github_client.py -v

# Step 4 完了後
uv run pytest tests/unit/test_cli.py -v

# 全テスト確認
uv run pytest tests/ -v

# 型チェック
uv run mypy src/

# lint
uv run ruff check src/ tests/
```

### テストカバレッジ対象

| テスト | カバーする機能 |
|--------|--------------|
| `test_get_repository_success` | `GitHubClient.get_repository()` 正常系 |
| `test_get_repository_not_found` | `GitHubClient.get_repository()` 404 エラー |
| `test_list_labels_success` | `GitHubClient.list_labels()` 正常系 |
| `test_list_labels_empty` | `GitHubClient.list_labels()` 空リスト |
| `test_health_repo_check_all_ok` | `_check_health()` 全リポジトリ正常 + テーブル表示 |
| `test_health_repo_check_auth_failure` | `_check_health()` 認証失敗ハンドリング |
| `test_health_repo_check_missing_labels` | `_check_repo_health()` ラベル欠損 (WARN, exit=0) |
| `test_health_repo_check_access_denied` | `_check_repo_health()` push 権限なし (exit=1) |

---

## 実装上の注意点

1. **`_check_health()` 内の `CredentialResolver` の再利用**: 既に L224 で `resolver = CredentialResolver()` が生成されているので、`AccountManager` 生成時にこれを渡す。新たに `CredentialResolver` を import する必要はない（既にローカルインポート済み）

2. **`TYPE_CHECKING` ガード**: `run.py` に追加する型アノテーション (`RepositoryConfig`, `GitHubClient`) は `TYPE_CHECKING` ガード内でインポート。ランタイムでの循環インポートを防ぐ

3. **`AccountManager` のインポート**: `_check_health()` 内でローカルインポートする（既存の `CredentialResolver` と同じパターン）

4. **`frozen=True`**: `RepoHealthResult` は `frozen=True` で定義（設計書の仕様通り）。不変データモデルとして扱う

5. **exit code ロジック**: `repo_critical_ok = all(r.auth_ok and r.access_ok for r in repo_results)` で判定。ラベル欠損 (`label_ok=False`) は `all_ok` に影響しない
