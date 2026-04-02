# 設計書: Issue #29 ヘルスチェックコマンドにリポジトリごとのAPI接続テストを追加

## 1. 概要

既存の `_check_health()` 関数（`src/ai_agent_orchestrator/commands/run.py` L211-264）に、リポジトリごとの GitHub API 接続テスト（認証確認・リポジトリアクセス確認・ラベル存在確認）を追加し、結果をテーブル形式で表示する。

現在のhealthコマンドは「設定ファイルの存在確認」「アカウント単位の認証確認」「プロセス状態確認」のみだが、実際の運用ではリポジトリへのアクセス権限やラベルの事前設定が正しいかを確認する需要がある。本変更でリポジトリごとの接続テストを追加し、運用開始前のトラブルシューティングを容易にする。

## 2. 現状分析

### 2.1 現在の `_check_health()` の処理フロー

```
1. 設定ファイルの読み込み確認
2. アカウントごとの認証検証（CredentialResolver.resolve → verify）
3. PIDファイルによるプロセス稼働確認
4. 結果テーブル表示
```

### 2.2 現在のテーブル出力例

```
┌─────────────────────────┬────────────┬─────────────────────┐
│ チェック項目             │ ステータス │ 詳細                │
├─────────────────────────┼────────────┼─────────────────────┤
│ 設定ファイル            │ OK         │ config.yaml         │
│ GitHub (default)        │ OK         │ user=testuser       │
│ Orchestrator Process    │ Not running│                     │
└─────────────────────────┴────────────┴─────────────────────┘
```

### 2.3 不足している確認項目

| 項目 | 重要度 | 理由 |
|------|--------|------|
| リポジトリアクセス確認 | 高 | トークンにrepoスコープがあっても、該当リポジトリへのアクセス権がない場合がある |
| ラベル存在確認 | 高 | `ai-agent` ラベルやフェーズラベルが未作成だとポーリングやフェーズ遷移が動作しない |
| リポジトリ × アカウント紐付け確認 | 中 | `AccountManager.resolve_account()` の解決が正しく行われるか事前確認 |

## 3. 変更対象ファイル

| ファイル | 変更種別 | 変更内容 |
|----------|----------|----------|
| `src/ai_agent_orchestrator/github/client.py` | メソッド追加 | `list_labels()` メソッドを追加（ラベル一覧取得用） |
| `src/ai_agent_orchestrator/commands/run.py` | 機能拡張 | `_check_health()` にリポジトリごとの接続テストを追加 |
| `tests/unit/test_cli.py` | テスト追加 | ヘルスチェックの新機能に対するテストを追加 |

## 4. 詳細設計

### 4.1 `GitHubClient` に `list_labels()` メソッドを追加

**ファイル:** `src/ai_agent_orchestrator/github/client.py`

**追加位置:** ラベル操作セクション（L188 `# ── ラベル操作 ──` 付近）

```python
async def list_labels(
    self,
    repo: RepositoryConfig,
) -> list[Label]:
    """リポジトリのラベル一覧を取得する.

    Args:
        repo: リポジトリ設定.

    Returns:
        Label オブジェクトのリスト.

    Raises:
        githubkit.exception.RequestFailed: API リクエスト失敗時.
    """
    response = await self._github.rest.issues.async_list_labels_for_repo(
        owner=repo.owner,
        repo=repo.repo,
        per_page=100,
    )
    return list(response.parsed_data)
```

**設計理由:**
- 既存の `create_label()` と同じセクションに配置し、一貫性を保つ
- `per_page=100` で十分（通常リポジトリのラベル数は100以下）
- 戻り値は `list[Label]` とし、呼び出し側でラベル名の抽出を行う

### 4.2 `_check_health()` の拡張

**ファイル:** `src/ai_agent_orchestrator/commands/run.py`

**処理フロー（拡張後）:**

```
1. 設定ファイルの読み込み確認（既存）
2. アカウントごとの認証検証（既存）
3. PIDファイルによるプロセス稼働確認（既存）
4. 既存テーブル表示（既存）
5. 【新規】リポジトリごとの接続テスト
   5a. AccountManager を生成
   5b. 各リポジトリに対して:
       - API認証: AccountManager.get_client() で認証済みクライアント取得
       - リポジトリアクセス: repos.async_get() でリポジトリ情報取得
       - ラベル確認: list_labels() でラベル一覧取得し、必須ラベルの存在チェック
6. 【新規】リポジトリ接続テストのテーブル表示
```

**リポジトリ接続テストのテーブル出力例:**

```
┌──────────────────────────┬────────────┬──────────────┬──────────────────────┐
│ リポジトリ               │ API認証    │ リポジトリ   │ ラベル               │
│                          │            │ アクセス     │                      │
├──────────────────────────┼────────────┼──────────────┼──────────────────────┤
│ owner/repo-a             │ ✅ OK      │ ✅ OK        │ ✅ OK (8/8)          │
│ owner/repo-b             │ ✅ OK      │ ✅ OK        │ ⚠️ 不足 (6/8)        │
│ owner/repo-c             │ ✅ OK      │ ❌ NG (404)  │ —                    │
│ owner/repo-d             │ ❌ NG      │ —            │ —                    │
└──────────────────────────┴────────────┴──────────────┴──────────────────────┘
```

**ラベル不足時の詳細表示:**

```
⚠️ owner/repo-b: 不足ラベル: phase:design, phase:ci-fix
```

#### 4.2.1 確認対象ラベル

各リポジトリに対して以下のラベルの存在を確認する:

| ラベル | 用途 |
|--------|------|
| `{repo.label}` (デフォルト: `ai-agent`) | トリガーラベル（ポーリングで検知） |
| `phase:hearing` | ヒアリングフェーズ |
| `phase:design` | 設計フェーズ |
| `phase:planning` | 計画フェーズ |
| `phase:implement` | 実装フェーズ |
| `phase:ci-fix` | CI修正フェーズ |
| `phase:revise` | レビュー対応フェーズ |
| `phase:done` | 完了フェーズ |

#### 4.2.2 接続テストの依存関係

テスト項目間には依存関係があり、前段が失敗した場合は後続をスキップする:

```
API認証 → リポジトリアクセス → ラベル確認
  ❌        → "—"              → "—"
  ✅        → ❌               → "—"
  ✅        → ✅               → 実行
```

#### 4.2.3 新規追加する import と依存

```python
# run.py に追加する import
from ai_agent_orchestrator.github.client import AccountManager, GitHubClient
```

`AccountManager` の生成には `CredentialResolver` と `settings.accounts`, `settings.repositories` が必要だが、いずれも `_check_health()` のスコープ内で既に利用可能。

#### 4.2.4 リポジトリアクセス確認の方法

`githubkit` の `repos.async_get()` を使用する:

```python
response = await client._github.rest.repos.async_get(
    owner=repo.owner,
    repo=repo.repo,
)
```

**設計理由:**
- Issue取得（`get_issue(repo, 1)`）よりも軽量
- Issueが0件のリポジトリでも動作する
- リポジトリのアクセス権限を直接確認できる

ただし `_github` はプライベート属性のため、`GitHubClient` に `get_repo()` ヘルパーメソッドを追加する:

```python
async def get_repo(self, repo: RepositoryConfig) -> Any:
    """リポジトリ情報を取得する.

    Args:
        repo: リポジトリ設定.

    Returns:
        リポジトリ情報.
    """
    response = await self._github.rest.repos.async_get(
        owner=repo.owner,
        repo=repo.repo,
    )
    return response.parsed_data
```

### 4.3 エラーハンドリング

各テスト項目は `try/except` で個別にキャッチし、1つの失敗が他のリポジトリのテストをブロックしないようにする。

```python
for repo_config in settings.repositories:
    repo_name = f"{repo_config.owner}/{repo_config.repo}"
    auth_status = "—"
    access_status = "—"
    label_status = "—"

    # 1. API認証
    try:
        account = account_manager.resolve_account(repo_config)
        client = await account_manager.get_client(account.name)
        auth_status = "[green]✅ OK[/green]"
    except Exception as e:
        auth_status = f"[red]❌ NG[/red]"
        repo_table.add_row(repo_name, auth_status, access_status, label_status)
        all_ok = False
        continue

    # 2. リポジトリアクセス
    try:
        await client.get_repo(repo_config)
        access_status = "[green]✅ OK[/green]"
    except RequestFailed as e:
        access_status = f"[red]❌ NG ({e.response.status_code})[/red]"
        repo_table.add_row(repo_name, auth_status, access_status, label_status)
        all_ok = False
        continue
    except Exception:
        access_status = "[red]❌ NG[/red]"
        repo_table.add_row(repo_name, auth_status, access_status, label_status)
        all_ok = False
        continue

    # 3. ラベル確認
    try:
        labels = await client.list_labels(repo_config)
        label_names = {lbl.name for lbl in labels if hasattr(lbl, 'name')}
        required = {repo_config.label} | REQUIRED_PHASE_LABELS
        missing = required - label_names
        total = len(required)
        found = total - len(missing)
        if not missing:
            label_status = f"[green]✅ OK ({found}/{total})[/green]"
        else:
            label_status = f"[yellow]⚠️ 不足 ({found}/{total})[/yellow]"
            missing_labels[repo_name] = missing
            all_ok = False
    except Exception:
        label_status = "[red]❌ NG[/red]"
        all_ok = False

    repo_table.add_row(repo_name, auth_status, access_status, label_status)
```

### 4.4 定数定義

```python
# _check_health() の前に定義
REQUIRED_PHASE_LABELS: frozenset[str] = frozenset({
    "phase:hearing",
    "phase:design",
    "phase:planning",
    "phase:implement",
    "phase:ci-fix",
    "phase:revise",
    "phase:done",
})
```

## 5. テスト設計

**ファイル:** `tests/unit/test_cli.py`

### 5.1 テストケース一覧

| # | テスト名 | 内容 | 期待結果 |
|---|----------|------|----------|
| 1 | `test_health_repo_api_all_ok` | 全リポジトリでAPI接続成功 | exit_code=0, 出力に「OK」とリポジトリ名が含まれる |
| 2 | `test_health_repo_access_failure` | 1つのリポジトリでアクセス失敗（RequestFailed） | exit_code=1, 出力に「NG」が含まれる |
| 3 | `test_health_repo_labels_missing` | ラベル一覧にフェーズラベルが不足 | exit_code=1, 不足ラベル名が出力に含まれる |

### 5.2 モック戦略

テストでは以下をモックする:

- `CredentialResolver.resolve` → トークン文字列を返す `AsyncMock`
- `CredentialResolver.verify` → `{"login": "testuser"}` を返す `AsyncMock`
- `AccountManager.get_client` → モック化された `GitHubClient` を返す `AsyncMock`
- `AccountManager.resolve_account` → `AccountConfig` を返す `Mock`
- `GitHubClient.get_repo` → 成功時は `AsyncMock()`、失敗時は `RequestFailed` を発生
- `GitHubClient.list_labels` → ラベルオブジェクトのリストを返す `AsyncMock`

### 5.3 テスト実装方針

```python
def test_health_repo_api_all_ok(tmp_path, tmp_config):
    """全リポジトリのAPI接続テストが成功するケース."""
    mock_resolver = AsyncMock()
    mock_resolver.resolve.return_value = "ghp_test"
    mock_resolver.verify.return_value = {"login": "testuser"}

    mock_client = AsyncMock()
    mock_client.get_repo.return_value = ...
    mock_client.list_labels.return_value = [
        # 全必須ラベルを含むモックラベルオブジェクト
    ]

    with (
        patch("ai_agent_orchestrator.commands.run.CredentialResolver", return_value=mock_resolver),
        patch("ai_agent_orchestrator.commands.run.AccountManager") as MockAM,
        patch("ai_agent_orchestrator.commands.run._PID_FILE", tmp_path / "no.pid"),
    ):
        mock_am = MockAM.return_value
        mock_am.resolve_account.return_value = AccountConfig(name="default")
        mock_am.get_client.return_value = mock_client

        result = runner.invoke(app, ["health", "--config", str(tmp_config)])
        assert result.exit_code == 0
        assert "test-owner/test-repo" in result.output
        assert "OK" in result.output
```

## 6. 実装手順

1. `GitHubClient` に `list_labels()` と `get_repo()` メソッドを追加
2. `_check_health()` にリポジトリ接続テストのロジックを追加（`REQUIRED_PHASE_LABELS` 定数含む）
3. テストを追加して `uv run pytest tests/unit/test_cli.py -v` で確認
4. `uv run mypy src/` と `uv run ruff check src/ tests/` で品質チェック

## 7. 影響範囲

- **既存機能への影響**: なし。既存のヘルスチェック処理は変更せず、テーブル表示の後にリポジトリ接続テストを追加するのみ
- **パフォーマンス**: リポジトリ数 × 3回のAPIコール（認証・アクセス・ラベル）が追加される。通常1-5リポジトリ程度なので問題なし
- **後方互換性**: CLI の出力フォーマットが変わる（テーブルが1つ追加される）が、exit code の意味は変わらない（0=全OK, 1=一部NG）
