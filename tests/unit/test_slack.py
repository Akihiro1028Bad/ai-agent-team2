"""SlackNotifier のユニットテスト."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from ai_agent_orchestrator.notifications.slack import SlackNotifier

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/XXXX"


@pytest.fixture
def notifier() -> SlackNotifier:
    """テスト用の SlackNotifier を返す."""
    return SlackNotifier(webhook_url=WEBHOOK_URL, default_channel="#ai-agent")


# ── TC-SL-01: info レベルの基本送信 ──


@respx.mock
async def test_notify_sends_info_message(notifier: SlackNotifier) -> None:
    """info レベルのメッセージが Webhook に正しく送信されることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify(
        "Issue #42 の実装 PR を作成しました",
        level="info",
        metadata={"repo": "org/repo", "issue": 42},
    )

    assert route.called
    request_body = json.loads(route.calls[0].request.content)
    assert "blocks" in request_body
    text_block = request_body["blocks"][0]["text"]["text"]
    assert ":robot_face:" in text_block
    assert "Issue #42" in text_block


# ── TC-SL-02: error レベルの絵文字 ──


@respx.mock
async def test_notify_error_level_uses_x_emoji(notifier: SlackNotifier) -> None:
    """error レベルで :x: 絵文字が使われることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify("エラーが発生しました", level="error")

    request_body = json.loads(route.calls[0].request.content)
    text_block = request_body["blocks"][0]["text"]["text"]
    assert ":x:" in text_block


# ── TC-SL-03: critical レベルの絵文字 ──


@respx.mock
async def test_notify_critical_level_uses_rotating_light_emoji(
    notifier: SlackNotifier,
) -> None:
    """critical レベルで :rotating_light: 絵文字が使われることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify("認証が切れました", level="critical")

    request_body = json.loads(route.calls[0].request.content)
    text_block = request_body["blocks"][0]["text"]["text"]
    assert ":rotating_light:" in text_block


# ── TC-SL-04: metadata コンテキストブロック ──


@respx.mock
async def test_notify_includes_metadata_context(notifier: SlackNotifier) -> None:
    """metadata の repo, issue, pr がコンテキストブロックに含まれることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify(
        "PR 作成しました",
        metadata={
            "repo": "org/repo",
            "issue": 42,
            "pr": 11,
            "pr_url": "https://github.com/org/repo/pull/11",
            "phase": "implement",
        },
    )

    request_body = json.loads(route.calls[0].request.content)
    assert len(request_body["blocks"]) >= 2  # section + context
    context_text = request_body["blocks"][1]["elements"][0]["text"]
    assert "org/repo" in context_text
    assert "42" in context_text


# ── TC-SL-05: Webhook 失敗時に例外を発生させない ──


@respx.mock
async def test_notify_does_not_raise_on_webhook_failure(
    notifier: SlackNotifier,
) -> None:
    """Webhook が 500 を返しても例外が発生しないことを検証する (best-effort)."""
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500, text="internal error"))

    # 例外が発生しないことを確認
    await notifier.notify("テストメッセージ")


# ── TC-SL-06: チャンネル指定 ──


@respx.mock
async def test_notify_uses_specified_channel(notifier: SlackNotifier) -> None:
    """channel 引数で指定したチャンネルがペイロードに含まれることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify("テスト", channel="#alerts")

    request_body = json.loads(route.calls[0].request.content)
    assert request_body.get("channel") == "#alerts"


# ── TC-SL-07: デフォルトチャンネル使用 ──


@respx.mock
async def test_notify_uses_default_channel_when_none(
    notifier: SlackNotifier,
) -> None:
    """channel が None の場合にデフォルトチャンネルが使われることを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify("テスト")

    request_body = json.loads(route.calls[0].request.content)
    assert request_body.get("channel") == "#ai-agent"


# ── TC-SL-08: send() の成否 ──


@respx.mock
async def test_send_returns_true_on_success(notifier: SlackNotifier) -> None:
    """send() が 200 レスポンスで True を返すことを検証する."""
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    result = await notifier.send({"text": "テスト"})

    assert result is True


@respx.mock
async def test_send_returns_false_on_failure(notifier: SlackNotifier) -> None:
    """send() が 500 レスポンスで False を返すことを検証する."""
    respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(500, text="error"))

    result = await notifier.send({"text": "テスト"})

    assert result is False


# ── TC-SL-09: close() ──


async def test_close_closes_httpx_client(notifier: SlackNotifier) -> None:
    """close() で内部の httpx.AsyncClient が閉じられることを検証する."""
    await notifier.close()

    assert notifier._client.is_closed


# ── TC-SL-10: _level_emoji マッピング ──


def test_level_emoji_mapping() -> None:
    """各通知レベルに対応する絵文字が正しいことを検証する."""
    assert SlackNotifier._level_emoji("info") == ":robot_face:"
    assert SlackNotifier._level_emoji("error") == ":x:"
    assert SlackNotifier._level_emoji("critical") == ":rotating_light:"
    # 未知のレベルはデフォルト絵文字
    assert SlackNotifier._level_emoji("unknown") == ":robot_face:"


# ── TC-SL-11: ネットワークエラー時に例外を発生させない ──


@respx.mock
async def test_send_returns_false_on_network_error(
    notifier: SlackNotifier,
) -> None:
    """ネットワークエラー時に send() が False を返すことを検証する."""
    respx.post(WEBHOOK_URL).mock(side_effect=httpx.ConnectError("connection refused"))

    result = await notifier.send({"text": "テスト"})

    assert result is False


# ── TC-SL-12: metadata なしの場合コンテキストブロックがない ──


@respx.mock
async def test_notify_without_metadata_has_no_context_block(
    notifier: SlackNotifier,
) -> None:
    """metadata なしの場合、コンテキストブロックが含まれないことを検証する."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify("シンプルなメッセージ")

    request_body = json.loads(route.calls[0].request.content)
    assert len(request_body["blocks"]) == 1  # section only


# ── TC-SL-13: default_channel が None の場合 channel キーがない ──


@respx.mock
async def test_no_channel_key_when_both_none() -> None:
    """default_channel も channel も None の場合、payload に channel が無い."""
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await n.notify("テスト")

    request_body = json.loads(route.calls[0].request.content)
    assert "channel" not in request_body
