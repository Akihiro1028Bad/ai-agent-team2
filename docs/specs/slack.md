# SlackNotifier 実装仕様書

## 概要

`Notifier` Protocol の Slack Webhook 実装。`httpx.AsyncClient` を使用して Slack Incoming Webhook に
Block Kit 形式のメッセージを POST 送信する。通知タイプに応じた絵文字・フォーマットを適用する。

## 対象ファイル

- `src/ai_agent_orchestrator/notifications/slack.py`

## 依存パッケージ

```python
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)
```

---

## 通知タイプとフォーマット

| 通知タイプ | 絵文字 | メッセージ例 | トリガー |
|-----------|--------|------------|---------|
| `hearing_question` | :speech_balloon: | `Issue #42 に質問を投稿しました。回答をお願いします` | ヒアリングフェーズで質問投稿時 |
| `design_pr_created` | :pencil: | `Issue #42 の設計 PR を作成しました: #10` | 設計書 PR 作成時 |
| `impl_pr_created` | :rocket: | `Issue #42 の実装 PR を作成しました: #11` | 実装 PR 作成時 |
| `plan_posted` | :clipboard: | `Issue #42 の方針を投稿しました。承認をお願いします` | Bug/Feature-S 方針投稿時 |
| `error` | :x: | `Issue #42 でエラーが発生しました: {error}` | 処理中のエラー |
| `timeout` | :hourglass: | `Issue #42 の {phase} フェーズがタイムアウトしました` | フェーズタイムアウト時 |
| `done` | :white_check_mark: | `Issue #42 が完了しました。PR #11 をマージしました` | Issue 完了時 |

---

## クラス: `SlackNotifier`

### 説明

`Notifier` Protocol を実装する。Slack Incoming Webhook URL に対して `httpx.AsyncClient` で
JSON ペイロード (Block Kit 形式) を POST する。

### コンストラクタ

```python
class SlackNotifier:
    """Slack Webhook による通知送信."""

    def __init__(
        self,
        webhook_url: str,
        default_channel: str | None = None,
    ) -> None:
        """SlackNotifier を初期化する。

        Args:
            webhook_url: Slack Incoming Webhook URL。
            default_channel: デフォルトの通知チャンネル。None の場合は Webhook の設定先に送信。
        """
        self._webhook_url = webhook_url
        self._default_channel = default_channel
        self._client = httpx.AsyncClient(timeout=10.0)
```

### 公開メソッド

#### `notify`

```python
async def notify(
    self,
    message: str,
    *,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Slack にメッセージを送信する。

    Block Kit 形式のペイロードを構築し、Webhook URL に POST する。
    送信失敗時はログに記録するが、例外は発生させない (通知は best-effort)。

    Args:
        message: 通知メッセージ本文。
        channel: 送信先チャンネル。None の場合は default_channel。
        level: 通知レベル ("info" | "error" | "critical")。レベルに応じた絵文字を付与。
        metadata: 付加情報。以下のキーを認識する:
            - repo (str): リポジトリ名 ("owner/repo" 形式)
            - issue (int): Issue 番号
            - pr (int): PR 番号
            - pr_url (str): PR の URL
            - phase (str): 現在のフェーズ名
            - error (str): エラーメッセージ
            - notification_type (str): 通知タイプ (上表参照)
    """
```

#### `send`

```python
async def send(
    self,
    payload: dict[str, Any],
) -> bool:
    """Slack Webhook に JSON ペイロードを POST する。

    低レベルの送信メソッド。notify() の内部で使用されるが、
    カスタムペイロードの送信にも使用可能。

    Args:
        payload: Slack Block Kit 形式の JSON ペイロード。

    Returns:
        送信成功時は True、失敗時は False。
    """
```

#### `close`

```python
async def close(self) -> None:
    """内部の httpx.AsyncClient を閉じる。

    アプリケーション終了時に呼び出す。
    """
```

### 内部メソッド

#### `_build_payload`

```python
def _build_payload(
    self,
    message: str,
    *,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Slack Block Kit 形式のペイロードを構築する。

    構成:
    1. ヘッダーブロック: 絵文字 + メッセージ本文
    2. コンテキストブロック (metadata がある場合):
       - リポジトリ名
       - Issue 番号 (リンク付き)
       - PR 番号 (リンク付き)
       - フェーズ名

    level に応じた絵文字:
    - "info": :robot_face:
    - "error": :x:
    - "critical": :rotating_light:

    Args:
        message: メッセージ本文。
        channel: 送信先チャンネル。
        level: 通知レベル。
        metadata: 付加情報。

    Returns:
        Slack Block Kit 形式の辞書。
    """
```

#### `_level_emoji`

```python
@staticmethod
def _level_emoji(level: str) -> str:
    """通知レベルに応じた絵文字を返す。

    Args:
        level: 通知レベル ("info" | "error" | "critical")。

    Returns:
        Slack 絵文字コード (例: ":robot_face:")。
    """
```

---

## ペイロード構造の例

### info レベル (PR 作成通知)

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":rocket: Issue #42 の実装 PR を作成しました: <https://github.com/org/repo/pull/11|#11>"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :memo: phase:implement"
                }
            ]
        }
    ]
}
```

### error レベル

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":x: Issue #42 でエラーが発生しました: TimeoutError"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :memo: phase:implement"
                }
            ]
        }
    ]
}
```

---

## テストケース

テストファイル: `tests/unit/notifications/test_slack.py`

`respx` で Webhook URL へのリクエストをモックし、`pytest-asyncio` で非同期テストを実行する。

### テスト用の共通フィクスチャ

```python
import json

import httpx
import pytest
import respx

from ai_agent_orchestrator.notifications.slack import SlackNotifier

WEBHOOK_URL = "https://hooks.slack.com/services/T00/B00/XXXX"


@pytest.fixture
def notifier() -> SlackNotifier:
    return SlackNotifier(webhook_url=WEBHOOK_URL, default_channel="#ai-agent")
```

### テストケース一覧

#### TC-SL-01: `notify` -- info レベルの基本送信

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_sends_info_message(notifier: SlackNotifier) -> None:
    """info レベルのメッセージが Webhook に正しく送信されることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

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
```

#### TC-SL-02: `notify` -- error レベルの絵文字

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_error_level_uses_x_emoji(notifier: SlackNotifier) -> None:
    """error レベルで :x: 絵文字が使われることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

    await notifier.notify("エラーが発生しました", level="error")

    request_body = json.loads(route.calls[0].request.content)
    text_block = request_body["blocks"][0]["text"]["text"]
    assert ":x:" in text_block
```

#### TC-SL-03: `notify` -- critical レベルの絵文字

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_critical_level_uses_rotating_light_emoji(notifier: SlackNotifier) -> None:
    """critical レベルで :rotating_light: 絵文字が使われることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

    await notifier.notify("認証が切れました", level="critical")

    request_body = json.loads(route.calls[0].request.content)
    text_block = request_body["blocks"][0]["text"]["text"]
    assert ":rotating_light:" in text_block
```

#### TC-SL-04: `notify` -- metadata にリポジトリ・Issue・PR 情報が含まれる

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_includes_metadata_context(notifier: SlackNotifier) -> None:
    """metadata の repo, issue, pr がコンテキストブロックに含まれることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

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
```

#### TC-SL-05: `notify` -- Webhook 失敗時に例外を発生させない

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_does_not_raise_on_webhook_failure(notifier: SlackNotifier) -> None:
    """Webhook が 500 を返しても例外が発生しないことを検証する (best-effort)。"""
    respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(500, text="internal error")
    )

    # 例外が発生しないことを確認
    await notifier.notify("テストメッセージ")
```

#### TC-SL-06: `notify` -- チャンネル指定

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_uses_specified_channel(notifier: SlackNotifier) -> None:
    """channel 引数で指定したチャンネルがペイロードに含まれることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

    await notifier.notify("テスト", channel="#alerts")

    request_body = json.loads(route.calls[0].request.content)
    assert request_body.get("channel") == "#alerts"
```

#### TC-SL-07: `notify` -- デフォルトチャンネル使用

```python
@pytest.mark.asyncio
@respx.mock
async def test_notify_uses_default_channel_when_none(notifier: SlackNotifier) -> None:
    """channel が None の場合にデフォルトチャンネルが使われることを検証する。"""
    route = respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

    await notifier.notify("テスト")

    request_body = json.loads(route.calls[0].request.content)
    assert request_body.get("channel") == "#ai-agent"
```

#### TC-SL-08: `send` -- 低レベル送信の成否

```python
@pytest.mark.asyncio
@respx.mock
async def test_send_returns_true_on_success(notifier: SlackNotifier) -> None:
    """send() が 200 レスポンスで True を返すことを検証する。"""
    respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(200, text="ok")
    )

    result = await notifier.send({"text": "テスト"})

    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_send_returns_false_on_failure(notifier: SlackNotifier) -> None:
    """send() が 500 レスポンスで False を返すことを検証する。"""
    respx.post(WEBHOOK_URL).mock(
        return_value=httpx.Response(500, text="error")
    )

    result = await notifier.send({"text": "テスト"})

    assert result is False
```

#### TC-SL-09: `close` -- httpx クライアントの終了

```python
@pytest.mark.asyncio
async def test_close_closes_httpx_client(notifier: SlackNotifier) -> None:
    """close() で内部の httpx.AsyncClient が閉じられることを検証する。"""
    await notifier.close()

    assert notifier._client.is_closed
```

#### TC-SL-10: `_level_emoji` -- 各レベルの絵文字マッピング

```python
def test_level_emoji_mapping() -> None:
    """各通知レベルに対応する絵文字が正しいことを検証する。"""
    assert SlackNotifier._level_emoji("info") == ":robot_face:"
    assert SlackNotifier._level_emoji("error") == ":x:"
    assert SlackNotifier._level_emoji("critical") == ":rotating_light:"
    # 未知のレベルはデフォルト絵文字
    assert SlackNotifier._level_emoji("unknown") == ":robot_face:"
```
