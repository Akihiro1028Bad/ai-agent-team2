"""CredentialResolver - 4段階トークン解決."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx
import keyring
import keyring.errors

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import AccountConfig

logger = logging.getLogger(__name__)

_keyring_warned: set[str] = set()


class CredentialError(Exception):
    """トークン解決に失敗した場合の例外.

    4段階すべてのフォールバックが失敗した場合、またはトークン検証に失敗した場合に送出する。
    """


class CredentialResolver:
    """4段階フォールバックでGitHubトークンを解決する.

    解決順序:
      1. keyring   -- OS keychain (macOS Keychain, Windows Credential Manager 等)
      2. env       -- 環境変数 (AccountConfig.token_env で指定)
      3. token_command -- 外部コマンド実行 (AccountConfig.token_command の stdout)
      4. gh auth token -- GitHub CLI のフォールバック

    Attributes:
        KEYRING_SERVICE_PREFIX: keyring のサービス名プレフィックス。
            キーは "{KEYRING_SERVICE_PREFIX}/{account_name}" の形式。
    """

    KEYRING_SERVICE_PREFIX: str = "ai-agent"

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

    async def store(self, account_name: str, token: str) -> None:
        """トークンをkeyringに保存."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        await asyncio.to_thread(keyring.set_password, service, "github_token", token)

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
                raise CredentialError(f"トークン検証に失敗しました (status={resp.status_code})")
            result: dict[str, Any] = resp.json()
            # スコープ情報をヘッダから取得
            scopes = resp.headers.get("x-oauth-scopes", "")
            result["scopes"] = [s.strip() for s in scopes.split(",") if s.strip()]
            return result

    async def delete(self, account_name: str) -> None:
        """keyringからトークンを削除."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            await asyncio.to_thread(keyring.delete_password, service, "github_token")

    async def _resolve_keyring(self, account_name: str) -> str | None:
        """OS keychainからトークンを取得."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        try:
            token: str | None = await asyncio.to_thread(keyring.get_password, service, "github_token")
            return token
        except keyring.errors.KeyringError:
            if service not in _keyring_warned:
                logger.warning("keyring へのアクセスに失敗しました (service=%s)。以降は抑制します。", service)
                _keyring_warned.add(service)
            else:
                logger.debug("keyring へのアクセスに失敗しました (service=%s)", service)
            return None

    def _resolve_env(self, env_var: str) -> str | None:
        """環境変数からトークンを取得."""
        return os.environ.get(env_var) or None

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
        except TimeoutError:
            proc.kill()
            return None
        except OSError:
            pass
        return None

    async def _resolve_gh_cli(self) -> str:
        """gh auth token にフォールバック. 失敗時は CredentialError."""
        token = await self._resolve_command("gh auth token")
        if not token:
            raise CredentialError(
                "トークンを解決できません。keyring, 環境変数, token_command, gh CLI のいずれかを設定してください"
            )
        return token
