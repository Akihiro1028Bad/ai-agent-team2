"""SlackNotifier (Webhook 通知)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_LEVEL_EMOJI: dict[str, str] = {
    "info": ":robot_face:",
    "error": ":x:",
    "critical": ":rotating_light:",
}


class SlackNotifier:
    """Slack Webhook による通知送信."""

    def __init__(
        self,
        webhook_url: str,
        default_channel: str | None = None,
    ) -> None:
        """SlackNotifier を初期化する.

        Args:
            webhook_url: Slack Incoming Webhook URL.
            default_channel: デフォルトの通知チャンネル。None の場合は Webhook の設定先に送信。
        """
        self._webhook_url = webhook_url
        self._default_channel = default_channel
        self._client = httpx.AsyncClient(timeout=10.0)

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Slack にメッセージを送信する.

        Block Kit 形式のペイロードを構築し、Webhook URL に POST する。
        送信失敗時はログに記録するが、例外は発生させない (通知は best-effort)。

        Args:
            message: 通知メッセージ本文。
            channel: 送信先チャンネル。None の場合は default_channel。
            level: 通知レベル ("info" | "error" | "critical")。
            metadata: 付加情報。repo, issue, pr, pr_url, phase, error,
                notification_type を認識する。
        """
        payload = self._build_payload(
            message, channel=channel, level=level, metadata=metadata
        )
        await self.send(payload)

    async def send(
        self,
        payload: dict[str, Any],
    ) -> bool:
        """Slack Webhook に JSON ペイロードを POST する.

        Args:
            payload: Slack Block Kit 形式の JSON ペイロード。

        Returns:
            送信成功時は True、失敗時は False。
        """
        try:
            response = await self._client.post(
                self._webhook_url, json=payload
            )
            if response.status_code == 200:
                return True
            logger.warning(
                "Slack webhook returned %d: %s",
                response.status_code,
                response.text,
            )
            return False
        except httpx.HTTPError as exc:
            logger.warning("Slack webhook request failed: %s", exc)
            return False

    async def close(self) -> None:
        """内部の httpx.AsyncClient を閉じる."""
        await self._client.aclose()

    # ── internal ──────────────────────────────────────

    def _build_payload(
        self,
        message: str,
        *,
        channel: str | None,
        level: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Slack Block Kit 形式のペイロードを構築する.

        Args:
            message: メッセージ本文。
            channel: 送信先チャンネル。
            level: 通知レベル。
            metadata: 付加情報。

        Returns:
            Slack Block Kit 形式の辞書。
        """
        emoji = self._level_emoji(level)
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} {message}",
                },
            },
        ]

        context_text = self._build_context_text(metadata)
        if context_text:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": context_text},
                    ],
                }
            )

        resolved_channel = channel or self._default_channel
        payload: dict[str, Any] = {"blocks": blocks}
        if resolved_channel is not None:
            payload["channel"] = resolved_channel
        return payload

    @staticmethod
    def _level_emoji(level: str) -> str:
        """通知レベルに応じた絵文字を返す.

        Args:
            level: 通知レベル ("info" | "error" | "critical")。

        Returns:
            Slack 絵文字コード (例: ":robot_face:")。
        """
        return _LEVEL_EMOJI.get(level, ":robot_face:")

    @staticmethod
    def _build_context_text(metadata: dict[str, Any] | None) -> str | None:
        """metadata からコンテキストブロック用テキストを構築する.

        Args:
            metadata: 付加情報辞書。

        Returns:
            コンテキスト用 mrkdwn テキスト。metadata が無い場合は None。
        """
        if not metadata:
            return None

        parts: list[str] = []
        repo: str | None = metadata.get("repo")
        issue: int | None = metadata.get("issue")
        pr: int | None = metadata.get("pr")
        pr_url: str | None = metadata.get("pr_url")
        phase: str | None = metadata.get("phase")

        if repo:
            parts.append(f":package: `{repo}`")

        if repo and issue is not None:
            issue_url = f"https://github.com/{repo}/issues/{issue}"
            parts.append(
                f":page_facing_up: <{issue_url}|Issue #{issue}>"
            )
        elif issue is not None:
            parts.append(f":page_facing_up: Issue #{issue}")

        if pr is not None and pr_url:
            parts.append(f":memo: <{pr_url}|PR #{pr}>")
        elif pr is not None:
            parts.append(f":memo: PR #{pr}")

        if phase:
            parts.append(f":memo: phase:{phase}")

        if not parts:
            return None
        return " | ".join(parts)
