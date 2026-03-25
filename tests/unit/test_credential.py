"""CredentialResolver のユニットテスト."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import keyring.errors
import pytest
import respx

from ai_agent_orchestrator.config.settings import AccountConfig
from ai_agent_orchestrator.credential import CredentialError, CredentialResolver


@pytest.fixture
def resolver() -> CredentialResolver:
    return CredentialResolver()


@pytest.fixture
def account_config() -> AccountConfig:
    """テスト用AccountConfig."""
    return AccountConfig(
        name="test-account",
        token_env="GITHUB_TOKEN_TEST",
        token_command="echo ghp_test123",
    )


@pytest.mark.asyncio
async def test_resolve_from_keyring(
    resolver: CredentialResolver, account_config: AccountConfig
) -> None:
    """keyringにトークンが存在する場合、keyringから取得されること."""
    with patch("keyring.get_password", return_value="ghp_from_keyring"):
        token = await resolver.resolve(account_config)
    assert token == "ghp_from_keyring"


@pytest.mark.asyncio
async def test_resolve_fallback_to_env(
    resolver: CredentialResolver, account_config: AccountConfig
) -> None:
    """keyringが空の場合、環境変数から取得されること."""
    with (
        patch("keyring.get_password", return_value=None),
        patch.dict("os.environ", {"GITHUB_TOKEN_TEST": "ghp_from_env"}),
    ):
        token = await resolver.resolve(account_config)
    assert token == "ghp_from_env"


@pytest.mark.asyncio
async def test_resolve_fallback_to_command(
    resolver: CredentialResolver, account_config: AccountConfig
) -> None:
    """keyring・環境変数が空の場合、token_commandから取得されること."""
    with (
        patch("keyring.get_password", return_value=None),
        patch.dict("os.environ", {}, clear=True),
    ):
        token = await resolver.resolve(account_config)
    assert token == "ghp_test123"


@pytest.mark.asyncio
async def test_resolve_fallback_to_gh_cli(resolver: CredentialResolver) -> None:
    """全て失敗した場合、gh auth tokenにフォールバックすること."""
    config = AccountConfig(name="minimal")  # token_env, token_command 未設定

    with patch("keyring.get_password", return_value=None), patch.object(
        resolver, "_resolve_command", return_value="ghp_from_gh_cli"
    ) as mock_cmd:
        token = await resolver.resolve(config)

    assert token == "ghp_from_gh_cli"
    mock_cmd.assert_called_once_with("gh auth token")


@pytest.mark.asyncio
async def test_resolve_all_fail_raises_error(resolver: CredentialResolver) -> None:
    """全てのフォールバックが失敗した場合、CredentialErrorが送出されること."""
    config = AccountConfig(name="fail-account")

    with (
        patch("keyring.get_password", return_value=None),
        patch.object(resolver, "_resolve_command", return_value=None),
    ):
        with pytest.raises(CredentialError, match="トークンを解決できません"):
            await resolver.resolve(config)


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


@pytest.mark.asyncio
async def test_verify_invalid_token_raises_error(
    resolver: CredentialResolver,
) -> None:
    """無効なトークンの場合、CredentialErrorが送出されること."""
    with respx.mock:
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(401, json={"message": "Bad credentials"})
        )
        with pytest.raises(CredentialError, match="status=401"):
            await resolver.verify("ghp_invalid_token")


@pytest.mark.asyncio
async def test_store_saves_to_keyring(resolver: CredentialResolver) -> None:
    """store()がkeyring.set_passwordを正しいサービス名で呼び出すこと."""
    with patch("keyring.set_password") as mock_set:
        await resolver.store("myaccount", "ghp_new_token")

    mock_set.assert_called_once_with(
        "ai-agent/myaccount", "github_token", "ghp_new_token"
    )


@pytest.mark.asyncio
async def test_delete_removes_from_keyring(resolver: CredentialResolver) -> None:
    """delete()がkeyring.delete_passwordを呼び出すこと."""
    with patch("keyring.delete_password") as mock_del:
        await resolver.delete("myaccount")

    mock_del.assert_called_once_with("ai-agent/myaccount", "github_token")


@pytest.mark.asyncio
async def test_delete_nonexistent_does_not_raise(
    resolver: CredentialResolver,
) -> None:
    """存在しないトークンのdelete()がエラーにならないこと."""
    with patch(
        "keyring.delete_password",
        side_effect=keyring.errors.PasswordDeleteError("not found"),
    ):
        await resolver.delete("nonexistent")  # 例外が送出されないことを確認


@pytest.mark.asyncio
async def test_resolve_command_failure_returns_none(
    resolver: CredentialResolver,
) -> None:
    """外部コマンドが失敗した場合、Noneが返されること."""
    result = await resolver._resolve_command("exit 1")
    assert result is None
