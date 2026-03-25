# 実装仕様書: CredentialResolver

## 概要

GitHubトークンを4段階フォールバックで解決するクラス。OS keychain、環境変数、外部コマンド、gh CLIの順に試行し、最初に成功した方法でトークンを返す。

**モジュール**: `src/ai_agent_orchestrator/credential.py`
**テストファイル**: `tests/unit/test_credential.py`

> **Note**: 配置パスは `src/ai_agent_orchestrator/credential.py` に配置。API Reference の `ai_agent_orchestrator.github.credential_resolver` は旧パス。

---

## 依存パッケージ

```python
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
import keyring
import keyring.errors
```

---

## データモデル

### AccountConfig（外部参照）

`ai_agent_orchestrator.config.settings` で定義済み。本モジュールからインポートして使用する。

```python
@dataclass
class AccountConfig:
    """GitHubアカウント設定."""
    name: str
    token_env: str | None = None
    token_command: str | None = None
    default: bool = False
```

---

## 例外クラス

```python
class CredentialError(Exception):
    """トークン解決に失敗した場合の例外.

    4段階すべてのフォールバックが失敗した場合、またはトークン検証に失敗した場合に送出する。
    """
    pass

# Note: API Reference では AuthError を使用しているが、本設計では CredentialError に統一する。
# 互換性のため、必要に応じて以下のエイリアスを定義してもよい:
# AuthError = CredentialError
```

---

## クラス定義

```python
class CredentialResolver:
    """4段階フォールバックでGitHubトークンを解決する.

    解決順序:
      1. keyring   — OS keychain (macOS Keychain, Windows Credential Manager 等)
      2. env       — 環境変数 (AccountConfig.token_env で指定)
      3. token_command — 外部コマンド実行 (AccountConfig.token_command の stdout)
      4. gh auth token — GitHub CLI のフォールバック

    Attributes:
        KEYRING_SERVICE_PREFIX: keyring のサービス名プレフィックス。
            キーは "{KEYRING_SERVICE_PREFIX}/{account_name}" の形式。
    """

    KEYRING_SERVICE_PREFIX: str = "ai-agent"
```

---

## メソッド仕様

### `async resolve(account: AccountConfig) -> str`

**説明**: 4段階フォールバックでトークンを解決する。最初に成功した段階の値を返す。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account` | `AccountConfig` | アカウント設定（name, token_env, token_command を含む） |

**戻り値**: `str` — 解決されたGitHubトークン

**例外**: `CredentialError` — 4段階すべてで解決できなかった場合

**処理フロー**:

```
1. _resolve_keyring(account.name) → 値があればreturn
2. account.token_env が指定されていれば _resolve_env(account.token_env) → 値があればreturn
3. account.token_command が指定されていれば _resolve_command(account.token_command) → 値があればreturn
4. _resolve_gh_cli() → 値があればreturn、なければ CredentialError
```

**実装**:

```python
async def resolve(self, account: AccountConfig) -> str:
    """トークンを解決する. 失敗時は CredentialError を送出."""
    # 1. keyring
    token = await self._resolve_keyring(account.name)
    if token:
        return token

    # 2. 環境変数
    if account.token_env:
        token = self._resolve_env(account.token_env)
        if token:
            return token

    # 3. 外部コマンド
    if account.token_command:
        token = await self._resolve_command(account.token_command)
        if token:
            return token

    # 4. フォールバック: gh auth token
    return await self._resolve_gh_cli()
```

---

### `async store(account_name: str, token: str) -> None`

**説明**: トークンをOS keychainに保存する。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account_name` | `str` | アカウント名 |
| `token` | `str` | 保存するGitHubトークン |

**戻り値**: `None`

**実装**:

```python
async def store(self, account_name: str, token: str) -> None:
    """トークンをkeyringに保存."""
    service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
    await asyncio.to_thread(keyring.set_password, service, "github_token", token)
```

**補足**: `keyring.set_password` は同期APIのため、`asyncio.to_thread` でブロッキングを回避する。

---

### `async verify(token: str) -> dict[str, Any]`

**説明**: GitHub API (`GET /user`) を呼び出してトークンの有効性を検証する。成功時はユーザー情報を返す。

> **Note**: 設計書では bool 返却だが、API Reference に合わせ dict を返す。呼び出し側で bool 判定は truthy チェックで可能。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `token` | `str` | 検証するGitHubトークン |

**戻り値**: `dict[str, Any]` — ユーザー情報（`login`, `id`, `scopes` 等を含む）

**例外**: `CredentialError` — トークンが無効な場合（401応答、ネットワークエラー等）

**実装**:

```python
async def verify(self, token: str) -> dict[str, Any]:
    """トークンの有効性を確認. ユーザー情報を返す."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        if resp.status_code != 200:
            raise CredentialError(
                f"トークン検証に失敗しました (status={resp.status_code})"
            )
        result = resp.json()
        # スコープ情報をヘッダから取得
        scopes = resp.headers.get("x-oauth-scopes", "")
        result["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]
        return result
```

---

### `async delete(account_name: str) -> None`

**説明**: OS keychainからトークンを削除する。トークンが存在しない場合はエラーを無視する。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account_name` | `str` | アカウント名 |

**戻り値**: `None`

**実装**:

```python
async def delete(self, account_name: str) -> None:
    """keyringからトークンを削除."""
    service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
    try:
        await asyncio.to_thread(keyring.delete_password, service, "github_token")
    except keyring.errors.PasswordDeleteError:
        pass  # トークンが存在しない場合は無視
```

---

### 内部メソッド

#### `async _resolve_keyring(account_name: str) -> str | None`

```python
async def _resolve_keyring(self, account_name: str) -> str | None:
    """OS keychainからトークンを取得. ブロッキング回避のため asyncio.to_thread を使用."""
    import logging

    service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
    try:
        return await asyncio.to_thread(keyring.get_password, service, "github_token")
    except keyring.errors.KeyringError:
        logging.getLogger(__name__).warning(
            "keyring へのアクセスに失敗しました (service=%s)", service
        )
        return None
```

**補足**: `keyring.get_password` は同期APIのため、`asyncio.to_thread` でイベントループのブロッキングを回避する。`keyring.errors.KeyringError` が発生した場合は警告ログを出力し、次のフォールバックに進む。

#### `_resolve_env(env_var: str) -> str | None`

```python
def _resolve_env(self, env_var: str) -> str | None:
    """環境変数からトークンを取得."""
    return os.environ.get(env_var) or None
```

#### `async _resolve_command(command: str) -> str | None`

```python
async def _resolve_command(self, command: str) -> str | None:
    """外部コマンドを実行してトークンを取得. 失敗時はNone. タイムアウト10秒."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()
    except asyncio.TimeoutError:
        proc.kill()  # タイムアウト時はプロセスを強制終了
        return None
    except OSError:
        pass
    return None
```

**補足**: `asyncio.wait_for(..., timeout=10.0)` により、外部コマンドが応答しない場合のハングを防止する。

#### `async _resolve_gh_cli() -> str`

```python
async def _resolve_gh_cli(self) -> str:
    """gh auth token にフォールバック. 失敗時は CredentialError."""
    token = await self._resolve_command("gh auth token")
    if not token:
        raise CredentialError(
            "トークンを解決できません。"
            "keyring, 環境変数, token_command, gh CLI のいずれかを設定してください"
        )
    return token
```

---

## テストケース

テストファイル: `tests/unit/test_credential.py`

使用ライブラリ: `pytest`, `pytest-asyncio`, `respx`, `unittest.mock`

### 共通フィクスチャ

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from ai_agent_orchestrator.credential import CredentialResolver, CredentialError


@pytest.fixture
def resolver() -> CredentialResolver:
    return CredentialResolver()


@pytest.fixture
def account_config():
    """テスト用AccountConfig."""
    from ai_agent_orchestrator.config.settings import AccountConfig
    return AccountConfig(
        name="test-account",
        token_env="GITHUB_TOKEN_TEST",
        token_command="echo ghp_test123",
    )
```

---

### テスト1: keyringからトークン解決が成功する

```python
@pytest.mark.asyncio
async def test_resolve_from_keyring(resolver: CredentialResolver, account_config) -> None:
    """keyringにトークンが存在する場合、keyringから取得されること."""
    with patch("keyring.get_password", return_value="ghp_from_keyring"):
        token = await resolver.resolve(account_config)
    assert token == "ghp_from_keyring"
```

**検証ポイント**: keyringが最優先で使用される。環境変数やコマンドは呼ばれない。

---

### テスト2: keyring失敗時に環境変数にフォールバックする

```python
@pytest.mark.asyncio
async def test_resolve_fallback_to_env(resolver: CredentialResolver, account_config) -> None:
    """keyringが空の場合、環境変数から取得されること."""
    with (
        patch("keyring.get_password", return_value=None),
        patch.dict("os.environ", {"GITHUB_TOKEN_TEST": "ghp_from_env"}),
    ):
        token = await resolver.resolve(account_config)
    assert token == "ghp_from_env"
```

**検証ポイント**: keyring → env の順にフォールバックする。

---

### テスト3: token_commandによるトークン解決

```python
@pytest.mark.asyncio
async def test_resolve_fallback_to_command(resolver: CredentialResolver, account_config) -> None:
    """keyring・環境変数が空の場合、token_commandから取得されること."""
    with (
        patch("keyring.get_password", return_value=None),
        patch.dict("os.environ", {}, clear=True),
    ):
        # account_config.token_command = "echo ghp_test123"
        token = await resolver.resolve(account_config)
    assert token == "ghp_test123"
```

**検証ポイント**: subprocess経由でコマンドが実行される。stdout の strip が行われる。

---

### テスト4: gh auth tokenへのフォールバック

```python
@pytest.mark.asyncio
async def test_resolve_fallback_to_gh_cli(resolver: CredentialResolver) -> None:
    """全て失敗した場合、gh auth tokenにフォールバックすること."""
    from ai_agent_orchestrator.config.settings import AccountConfig
    config = AccountConfig(name="minimal")  # token_env, token_command 未設定

    with patch("keyring.get_password", return_value=None):
        with patch.object(
            resolver, "_resolve_command", return_value="ghp_from_gh_cli"
        ) as mock_cmd:
            token = await resolver.resolve(config)

    assert token == "ghp_from_gh_cli"
    mock_cmd.assert_called_once_with("gh auth token")
```

**検証ポイント**: token_env, token_command が未設定の場合、gh auth token が呼ばれる。

---

### テスト5: 全段階失敗時にCredentialErrorが送出される

```python
@pytest.mark.asyncio
async def test_resolve_all_fail_raises_error(resolver: CredentialResolver) -> None:
    """全てのフォールバックが失敗した場合、CredentialErrorが送出されること."""
    from ai_agent_orchestrator.config.settings import AccountConfig
    config = AccountConfig(name="fail-account")

    with (
        patch("keyring.get_password", return_value=None),
        patch.object(resolver, "_resolve_command", return_value=None),
    ):
        with pytest.raises(CredentialError, match="トークンを解決できません"):
            await resolver.resolve(config)
```

**検証ポイント**: CredentialErrorのメッセージに案内が含まれる。

---

### テスト6: verify — 有効なトークンでユーザー情報が返される

```python
import respx

@pytest.mark.asyncio
async def test_verify_valid_token(resolver: CredentialResolver) -> None:
    """有効なトークンの場合、ユーザー情報dictが返されること."""
    with respx.mock:
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(
                200,
                json={"login": "testuser", "id": 12345},
                headers={"x-oauth-scopes": "repo, read:org"},
            )
        )
        result = await resolver.verify("ghp_valid_token")

    assert result["login"] == "testuser"
    assert result["id"] == 12345
    assert "repo" in result["scopes"]
    assert "read:org" in result["scopes"]
```

**検証ポイント**: レスポンスJSONとscopesヘッダの両方が正しくパースされる。

---

### テスト7: verify — 無効なトークンでCredentialErrorが送出される

```python
@pytest.mark.asyncio
async def test_verify_invalid_token_raises_error(resolver: CredentialResolver) -> None:
    """無効なトークンの場合、CredentialErrorが送出されること."""
    with respx.mock:
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        with pytest.raises(CredentialError, match="status=401"):
            await resolver.verify("ghp_invalid_token")
```

**検証ポイント**: 401応答でCredentialErrorが送出される。

---

### テスト8: store — keyringにトークンが保存される

```python
@pytest.mark.asyncio
async def test_store_saves_to_keyring(resolver: CredentialResolver) -> None:
    """store()がkeyring.set_passwordを正しいサービス名で呼び出すこと."""
    with patch("keyring.set_password") as mock_set:
        await resolver.store("myaccount", "ghp_new_token")

    mock_set.assert_called_once_with(
        "ai-agent/myaccount", "github_token", "ghp_new_token"
    )
```

**検証ポイント**: サービス名が `{PREFIX}/{account_name}` の形式になる。

---

### テスト9: delete — keyringからトークンが削除される

```python
@pytest.mark.asyncio
async def test_delete_removes_from_keyring(resolver: CredentialResolver) -> None:
    """delete()がkeyring.delete_passwordを呼び出すこと."""
    with patch("keyring.delete_password") as mock_del:
        await resolver.delete("myaccount")

    mock_del.assert_called_once_with("ai-agent/myaccount", "github_token")
```

---

### テスト10: delete — トークンが存在しない場合にエラーにならない

```python
@pytest.mark.asyncio
async def test_delete_nonexistent_does_not_raise(resolver: CredentialResolver) -> None:
    """存在しないトークンのdelete()がエラーにならないこと."""
    with patch(
        "keyring.delete_password",
        side_effect=keyring.errors.PasswordDeleteError("not found"),
    ):
        await resolver.delete("nonexistent")  # 例外が送出されないことを確認
```

**検証ポイント**: `PasswordDeleteError` が握りつぶされる。

---

### テスト11: _resolve_command — コマンド失敗時にNoneが返される

```python
@pytest.mark.asyncio
async def test_resolve_command_failure_returns_none(resolver: CredentialResolver) -> None:
    """外部コマンドが失敗した場合、Noneが返されること."""
    result = await resolver._resolve_command("exit 1")
    assert result is None
```

**検証ポイント**: returncode != 0 の場合にNoneが返る。

---

## 依存関係

| 依存 | 用途 |
|------|------|
| `keyring` | OS keychain への読み書き |
| `httpx` | GitHub API (`/user`) への非同期HTTP通信 |
| `asyncio` | subprocess実行、`to_thread` によるブロッキング回避 |
| `respx` | テスト用 httpx モック |
