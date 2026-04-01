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

_NOTIFICATION_TYPE_EMOJI: dict[str, str] = {
    "receipt": ":inbox_tray:",
    "phase_start": ":arrow_forward:",
    "approval_accepted": ":thumbsup:",
    "hearing_question": ":speech_balloon:",
    "design_pr_created": ":pencil:",
    "impl_pr_created": ":rocket:",
    "fix_pr_created": ":wrench:",
    "plan_posted": ":clipboard:",
    "design_revised": ":pencil:",
    "impl_revised": ":pencil:",
    "split_proposal": ":scissors:",
    "split_complete": ":white_check_mark:",
    "done": ":white_check_mark:",
    "chain_start": ":link:",
    "impl_continuation": ":repeat:",
    "error": ":x:",
    "timeout": ":hourglass:",
    "health_check": ":stethoscope:",
    "system_start": ":robot_face:",
    "system_error": ":warning:",
    "suspended": ":pause_button:",
}

_HEADER_TEXT: dict[str, str] = {
    "receipt": "\U0001f4e5 Issue受付",
    "phase_start": "\u25b6\ufe0f フェーズ開始",
    "approval_accepted": "\U0001f44d 承認確認",
    "hearing_question": "\U0001f4ac ヒアリング質問",
    "design_pr_created": "\U0001f4dd 設計PR作成",
    "impl_pr_created": "\U0001f680 実装PR作成",
    "fix_pr_created": "\U0001f527 修正PR作成",
    "plan_posted": "\U0001f4cb 方針投稿",
    "design_revised": "\U0001f4dd 設計修正完了",
    "impl_revised": "\U0001f4dd 実装修正完了",
    "split_proposal": "\u2702\ufe0f 分割提案",
    "split_complete": "\u2705 分割完了",
    "done": "\u2705 処理完了",
    "chain_start": "\U0001f517 連鎖起動",
    "impl_continuation": "\U0001f504 実装継続",
    "error": "\u274c エラー発生",
    "timeout": "\u23f3 タイムアウト",
    "health_check": "\U0001fa7a ヘルスチェック異常",
    "system_start": "\U0001f916 システム起動",
    "system_error": "\u26a0\ufe0f システムエラー",
    "suspended": "\u23f8\ufe0f 一時停止",
}

_PHASE_SEQUENCES: dict[str, list[str]] = {
    "bug": ["type-detection", "analysis", "plan-review", "fix", "impl-review", "done"],
    "feature-s": [
        "type-detection",
        "plan-brief",
        "plan-review",
        "implement",
        "impl-review",
        "done",
    ],
    "feature-m": [
        "type-detection",
        "hearing",
        "design",
        "design-review",
        "planning",
        "implement",
        "impl-review",
        "done",
    ],
    "feature-l": [
        "type-detection",
        "hearing",
        "design",
        "design-review",
        "planning",
        "split-proposal",
        "split-execute",
        "done",
    ],
}


def _format_duration(seconds: float) -> str:
    """秒数を人間可読な形式にフォーマットする.

    Args:
        seconds: 秒数。

    Returns:
        フォーマットされた文字列。
    """
    if seconds < 60:
        return f"{seconds:.0f}秒"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}分{secs:02d}秒"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}時間{mins:02d}分"


def _compute_progress(issue_type: str, current_phase: str) -> str | None:
    """進捗サマリを計算する。タイプ未確定の場合は None.

    Args:
        issue_type: Issueタイプ (bug, feature-s, feature-m, feature-l)。
        current_phase: 現在のフェーズ名。

    Returns:
        進捗サマリ文字列。タイプ未確定の場合は None。
    """
    seq = _PHASE_SEQUENCES.get(issue_type)
    if not seq:
        return None
    try:
        idx = seq.index(current_phase)
    except ValueError:
        return None
    return f"[{idx}/{len(seq)}フェーズ完了]"


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
        payload = self._build_payload(message, channel=channel, level=level, metadata=metadata)
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
            response = await self._client.post(self._webhook_url, json=payload)
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
        meta = metadata or {}
        notification_type = meta.get("notification_type")

        blocks: list[dict[str, Any]] = []

        # 1. ヘッダーブロック (notification_type がある場合のみ)
        header_text = self._get_header_text(notification_type)
        if header_text:
            blocks.append(
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": header_text, "emoji": True},
                }
            )

        # 2. セクションブロック (メイン本文)
        emoji = self._resolve_emoji(notification_type, level)
        section_text = self._build_section_text(emoji, message, meta)
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": section_text},
            }
        )

        # 3. Divider (notification_type がある場合のみ)
        if header_text:
            blocks.append({"type": "divider"})

        # 4. アクションボタン (notification_type がある場合のみ)
        if notification_type:
            action_elements = self._build_action_buttons(meta)
            if action_elements:
                blocks.append({"type": "actions", "elements": action_elements})

        # 5. コンテキストブロック (既存ロジック維持)
        context_text = self._build_context_text(meta)
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
    def _resolve_emoji(notification_type: str | None, level: str) -> str:
        """notification_type > level > デフォルト の優先順位で絵文字を解決する.

        Args:
            notification_type: 通知タイプ。
            level: 通知レベル。

        Returns:
            Slack 絵文字コード。
        """
        if notification_type and notification_type in _NOTIFICATION_TYPE_EMOJI:
            return _NOTIFICATION_TYPE_EMOJI[notification_type]
        return _LEVEL_EMOJI.get(level, ":robot_face:")

    @staticmethod
    def _get_header_text(notification_type: str | None) -> str | None:
        """notification_type に対応するヘッダーテキストを返す.

        Args:
            notification_type: 通知タイプ。

        Returns:
            ヘッダーテキスト。該当なしの場合は None。
        """
        if notification_type is None:
            return None
        return _HEADER_TEXT.get(notification_type)

    @staticmethod
    def _build_section_text(emoji: str, message: str, meta: dict[str, Any]) -> str:
        """セクションブロック用のテキストを構築する.

        Args:
            emoji: 絵文字コード。
            message: メッセージ本文。
            meta: metadata 辞書。

        Returns:
            セクション用 mrkdwn テキスト。
        """
        issue_title: str | None = meta.get("issue_title")
        progress: str | None = meta.get("progress")
        duration_sec: float | None = meta.get("duration_sec")
        total_duration_sec: float | None = meta.get("total_duration_sec")
        next_action: str | None = meta.get("next_action")

        lines: list[str] = []
        if issue_title:
            lines.append(f"{emoji} *[{issue_title}]* {message}")
        else:
            lines.append(f"{emoji} {message}")

        info_parts: list[str] = []
        if progress:
            info_parts.append(f"進捗: {progress}")
        if duration_sec is not None:
            info_parts.append(f"フェーズ: {_format_duration(duration_sec)}")
        if total_duration_sec is not None:
            info_parts.append(f"全体: {_format_duration(total_duration_sec)}")
        if info_parts:
            lines.append(" | ".join(info_parts))

        if next_action:
            lines.append(f"_{next_action}_")

        return "\n".join(lines)

    @staticmethod
    def _build_action_buttons(meta: dict[str, Any]) -> list[dict[str, Any]]:
        """metadata からアクションボタン要素リストを構築する.

        Args:
            meta: metadata 辞書。

        Returns:
            アクションボタン要素リスト。
        """
        elements: list[dict[str, Any]] = []
        repo: str | None = meta.get("repo")
        issue: int | None = meta.get("issue")
        pr_url: str | None = meta.get("pr_url")

        if repo and issue is not None:
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Issueを見る", "emoji": True},
                    "url": f"https://github.com/{repo}/issues/{issue}",
                }
            )
        if pr_url:
            elements.append(
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "PRを見る", "emoji": True},
                    "url": pr_url,
                }
            )
        return elements

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
            parts.append(f":page_facing_up: <{issue_url}|Issue #{issue}>")
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
