# Issue #26: ヘルスチェックコマンドにリポジトリごとのAPI接続テストを追加

## 概要

現在の `health` コマンドは以下の3項目のみを検証している:

1. 設定ファイルの存在・読み込み
2. GitHub アカウントの認証確認（`CredentialResolver.verify`）
3. オーケストレータープロセスの稼働状態（PID チェック）

本設計では、設定ファイルに登録された **各リポジトリ** に対して以下の API 接続テストを追加する:

- **認証確認**: 該当リポジトリに紐づくアカウントのトークンが有効か
- **リポジトリアクセス確認**: `GET /repos/{owner}/{repo}` でリポジトリへのアクセス権があるか
- **ラベル存在確認**: `ai-agent` ラベルおよび必要なフェーズラベルが存在するか

結果はリポジトリごとに **テーブル形式** で表示する。

---

## 現状分析

### 現在の `health` コマンドの流れ

```
health_command() → asyncio.run(_check_health(config_path))
  1. load_config(config_path)
  2. CredentialResolver で各アカウントのトークン検証
  3. PID ファイルによるプロセス状態チェック
  4. Rich Table で結果表示
```

### 不足している検証

| 検証項目 | 現状 | 追加後 |
|---|---|---|
| トークン有効性 | アカウント単位で検証 | 変更なし（既存） |
| リポジトリアクセス権 | **未検証** | リポジトリ単位で検証 |
| ラベル存在 | **未検証** | リポジトリ単位で検証 |
| API Rate Limit | **未検証** | レスポンスヘッダから表示 |

---

## 設計

### 1. GitHubClient に検証用メソッドを追加

#### `get_repository()` メソッド

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

#### `list_labels()` メソッド

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

### 2. ヘルスチェック用データモデル

`commands/run.py` 内にローカルな dataclass として定義する（`models.py` に追加するほどの汎用性はないため）。

```python
@dataclass
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
```

### 3. リポジトリ別ヘルスチェック関数

```python
async def _check_repo_health(
    repo_config: RepositoryConfig,
    client: GitHubClient,
) -> RepoHealthResult:
    """単一リポジトリの接続テストを実行する."""
```

この関数は以下の3ステップを順に実行する:

#### Step 1: 認証確認

`client.get_repository(repo_config)` を呼び出し、認証トークンがリポジトリに対して有効か確認。
- 成功 → `auth_ok = True`
- `RequestFailed(401)` → 認証失敗
- `RequestFailed(403)` → 権限不足

#### Step 2: リポジトリアクセス確認

Step 1 の `get_repository()` レスポンスから `permissions` を確認。
- `push: True` → `access_ok = True`（Issue 操作・PR 作成に必要）
- `push: False` → `access_ok = False, access_detail = "push権限がありません"`
- `RequestFailed(404)` → リポジトリが存在しないまたはアクセス不可

#### Step 3: ラベル存在確認

`client.list_labels(repo_config)` でリポジトリのラベル一覧を取得し、必要なラベルの存在を検証。

**必須ラベル:**
- `{repo_config.label}`（デフォルト: `ai-agent`）

**確認対象のフェーズラベル:**
```python
REQUIRED_PHASE_LABELS = [
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

- 全ラベル存在 → `label_ok = True`
- 一部欠損 → `label_ok = False, missing_labels = [欠損ラベルリスト]`

> **Note:** ラベルが存在しない場合、エラーではなく **警告** として表示する。
> ラベルは初回の Issue 処理時に `create_label()` で自動作成されるため、
> 存在しないこと自体は致命的ではない。

### 4. `_check_health()` の拡張

既存の `_check_health()` 関数を拡張し、アカウント検証の後にリポジトリ別チェックを追加する。

```python
async def _check_health(config_path: str) -> None:
    """ヘルスチェック."""
    # --- 既存処理 (変更なし) ---
    # 1. 設定ファイル読み込み
    # 2. アカウント認証検証
    # 3. プロセス状態チェック
    # 4. 結果テーブル表示

    # --- 追加処理 ---
    # 5. リポジトリ別 API 接続テスト
    from ai_agent_orchestrator.credential import CredentialResolver
    from ai_agent_orchestrator.github.client import AccountManager

    resolver = CredentialResolver()
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

    # 6. リポジトリ別テーブル表示
    _print_repo_health_table(repo_results)
```

### 5. テーブル表示

リポジトリごとの結果を Rich Table で表示する。

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┓
┃ リポジトリ                     ┃ 認証 ┃ アクセス権限 ┃ ラベル  ┃ 詳細                   ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━┩
│ Akihiro1028Bad/ai-agent-team2 │  OK  │     OK     │   OK   │ push=✓ admin=✓         │
│ Akihiro1028Bad/test-repo      │  OK  │     OK     │  WARN  │ 欠損: phase:hearing-wait│
│ other-org/private-repo        │  NG  │     --     │   --   │ 404: リポジトリ不明     │
└─────────────────────────────────┴──────┴────────────┴────────┴─────────────────────────┘
```

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

---

## 変更対象ファイル一覧

| ファイル | 変更内容 | 新規/変更 |
|---|---|---|
| `src/ai_agent_orchestrator/github/client.py` | `get_repository()`, `list_labels()` メソッド追加 | 変更 |
| `src/ai_agent_orchestrator/commands/run.py` | `RepoHealthResult` dataclass 追加、`_check_repo_health()` 追加、`_check_health()` 拡張、`_print_repo_health_table()` 追加 | 変更 |
| `tests/unit/test_github_client.py` | `get_repository()`, `list_labels()` のユニットテスト追加 | 変更 |
| `tests/unit/test_cli.py` | `health` コマンドのリポジトリ別チェックテスト追加 | 変更 |

---

## 詳細設計

### GitHubClient 変更 (`github/client.py`)

#### 追加メソッド

1. **`get_repository(repo: RepositoryConfig) -> dict[str, Any]`**
   - `self._github.rest.repos.async_get()` を呼び出し
   - `name`, `full_name`, `private`, `permissions` を辞書で返す
   - 認証エラー（401）、権限エラー（403）、未発見（404）は `RequestFailed` として伝播

2. **`list_labels(repo: RepositoryConfig) -> list[str]`**
   - `self._github.rest.issues.async_list_labels_for_repo()` を呼び出し
   - ラベル名のリストを返す
   - per_page=100 で最大100件取得（通常は十分）

### health コマンド変更 (`commands/run.py`)

#### 追加要素

1. **`RepoHealthResult` dataclass** (frozen=True)
   - `repo_full_name: str` — リポジトリフルネーム
   - `auth_ok: bool` — 認証成否
   - `auth_detail: str` — 認証結果の詳細
   - `access_ok: bool` — リポジトリアクセス成否
   - `access_detail: str` — アクセス結果の詳細
   - `label_ok: bool` — ラベル存在チェック成否
   - `label_detail: str` — ラベルチェックの詳細
   - `missing_labels: list[str]` — 欠損ラベルのリスト

2. **`REQUIRED_PHASE_LABELS: list[str]`** — 必要なフェーズラベルの定数

3. **`_check_repo_health(repo_config, client) -> RepoHealthResult`**
   - 認証 → アクセス権限 → ラベルの3段階チェックを実行
   - 各ステップの結果を `RepoHealthResult` に格納して返す
   - 認証失敗時は後続チェックをスキップ（早期リターン）

4. **`_print_repo_health_table(results) -> None`**
   - Rich Table で結果をフォーマット表示

5. **`_check_health()` の拡張**
   - 既存のアカウント検証・PID チェックの後に `AccountManager` を生成
   - 各リポジトリに対して `_check_repo_health()` を呼び出し
   - 結果を `_print_repo_health_table()` で表示
   - リポジトリチェックの成否も最終判定（`all_ok`）に反映

---

## エラーハンドリング

| エラー | 処理 | 表示 |
|---|---|---|
| `RequestFailed(401)` | 認証NG、後続スキップ | `[red]NG[/red]` + "認証失敗" |
| `RequestFailed(403)` | 認証NG（権限不足）、後続スキップ | `[red]NG[/red]` + "権限不足" |
| `RequestFailed(404)` | リポジトリ不存在 | `[red]NG[/red]` + "リポジトリが見つかりません" |
| `ConfigError` | アカウント解決失敗 | `[red]NG[/red]` + エラーメッセージ |
| `CredentialError` | トークン解決失敗 | `[red]NG[/red]` + エラーメッセージ |
| ネットワークエラー | 接続失敗 | `[red]NG[/red]` + "接続に失敗しました" |
| ラベル欠損 | 警告として表示 | `[yellow]WARN[/yellow]` + 欠損リスト |

---

## テスト計画

### ユニットテスト (`test_github_client.py`)

1. **`test_get_repository_success`** — 正常系、permissions を含む辞書が返ること
2. **`test_get_repository_not_found`** — 404 で `RequestFailed` が送出されること
3. **`test_list_labels_success`** — ラベル名リストが返ること
4. **`test_list_labels_empty`** — ラベルが0件でも空リストが返ること

### ユニットテスト (`test_cli.py`)

5. **`test_health_repo_check_all_ok`** — 全リポジトリ正常時の表示確認
6. **`test_health_repo_check_auth_failure`** — 認証失敗リポジトリがある場合の表示確認
7. **`test_health_repo_check_missing_labels`** — ラベル欠損時の警告表示確認
8. **`test_health_repo_check_access_denied`** — push 権限がない場合の表示確認

### テスト方針

- `respx` で GitHub API レスポンスをモック
- `AccountManager` は `patch` でモック化
- `_check_repo_health()` は関数単体でもテスト可能な設計

---

## 実装の注意点

1. **既存テストへの影響を最小化**: `_check_health()` の既存ロジックは変更せず、末尾に追加する形で拡張
2. **AccountManager の再利用**: `_check_health()` 内で `AccountManager` を生成し、アカウント→リポジトリのマッピングを正しく解決
3. **非同期の並行実行は見送り**: リポジトリ数は通常少数（〜10）のため、`asyncio.gather` ではなく逐次実行で十分。将来的に並行化可能な設計にはしておく
4. **ラベル欠損は警告扱い**: ラベルは `create_label()` で自動作成される設計のため、欠損自体はエラーではなく `WARN` 表示にとどめる
5. **exit code**: リポジトリの認証失敗・アクセス不可がある場合は `exit(1)` を返す。ラベル欠損のみの場合は `exit(0)` とする
