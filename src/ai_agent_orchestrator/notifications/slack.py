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

# ---------------------------------------------------------------------------
# フェーズ別絵文字マッピング
# ---------------------------------------------------------------------------

PHASE_EMOJI: dict[str, str] = {
    "type-detection": ":label:",
    "hearing": ":speech_balloon:",
    "hearing-wait": ":speech_balloon:",
    "analysis": ":mag:",
    "plan-brief": ":clipboard:",
    "plan-review": ":clipboard:",
    "design": ":triangular_ruler:",
    "design-review": ":triangular_ruler:",
    "design-revise": ":arrows_counterclockwise:",
    "planning": ":memo:",
    "implement": ":rocket:",
    "fix": ":rocket:",
    "ci-fix": ":wrench:",
    "impl-review": ":arrows_counterclockwise:",
    "impl-revise": ":arrows_counterclockwise:",
    "split-proposal": ":scissors:",
    "split-execute": ":scissors:",
    "done": ":white_check_mark:",
    "error": ":x:",
    "timeout": ":hourglass:",
    "suspended": ":pause_button:",
}

# ---------------------------------------------------------------------------
# カラーバー定義
# ---------------------------------------------------------------------------

NOTIFICATION_COLORS: dict[str, str] = {
    "start": "#1E90FF",
    "success": "#2EB67D",
    "waiting": "#ECB22E",
    "error": "#E01E5A",
}

# 通知タイプ → カラー種別のマッピング
_NOTIFICATION_TYPE_COLOR: dict[str, str] = {
    "phase_start": "start",
    "phase_complete": "success",
    "hearing_question": "waiting",
    "plan_posted": "waiting",
    "design_pr_created": "waiting",
    "design_revised": "success",
    "planning_complete": "success",
    "impl_pr_created": "waiting",
    "fix_pr_created": "waiting",
    "ci_fix_complete": "success",
    "impl_revised": "success",
    "split_proposed": "waiting",
    "split_complete": "success",
    "done": "success",
    "error": "error",
    "timeout": "error",
}

# ---------------------------------------------------------------------------
# タイプ別ステップ定義
# ---------------------------------------------------------------------------

PHASE_STEPS: dict[str, list[tuple[str, str]]] = {
    "bug": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("analysis", "原因分析"),
        ("plan-brief", "方針提示"),
        ("fix", "修正実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-s": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("plan-brief", "方針提示"),
        ("implement", "実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-m": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("design", "設計"),
        ("planning", "実装計画"),
        ("implement", "実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-l": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("split-proposal", "分割"),
        ("done", "完了"),
    ],
}

# ---------------------------------------------------------------------------
# フェーズの日本語ラベル
# ---------------------------------------------------------------------------

PHASE_LABELS: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "回答待ち",
    "analysis": "原因分析",
    "plan-brief": "方針作成",
    "plan-review": "方針レビュー待ち",
    "design": "設計",
    "design-review": "設計レビュー待ち",
    "design-revise": "設計レビュー対応",
    "planning": "実装計画",
    "implement": "実装",
    "fix": "修正",
    "ci-fix": "CI修正",
    "impl-review": "実装レビュー待ち",
    "impl-revise": "実装レビュー対応",
    "split-proposal": "Issue分割提案",
    "split-execute": "Issue分割実行",
    "done": "完了",
}


# ---------------------------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------------------------


def resolve_step(
    phase: str, issue_type: str | None
) -> tuple[int | None, int | None, str | None]:
    """フェーズと Issue タイプからステップ情報を返す.

    Args:
        phase: Phase enum の値 (例: "implement").
        issue_type: IssueType の値 (例: "feature-m").

    Returns:
        (step_current, step_total, step_label) のタプル。
        不明な場合は (None, None, None)。
    """
    if not issue_type:
        return None, None, None
    steps = PHASE_STEPS.get(issue_type, [])
    for i, (phase_key, label) in enumerate(steps, 1):
        if phase_key == phase:
            return i, len(steps), label
    return None, None, None


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

        attachments ベースのリッチレイアウト (カラーバー + Header + Actions 等) を構築する。

        Args:
            message: メッセージ本文。
            channel: 送信先チャンネル。
            level: 通知レベル。
            metadata: 付加情報。

        Returns:
            Slack Block Kit 形式の辞書。
        """
        meta = metadata or {}
        notification_type = meta.get("notification_type", "")
        color = self._resolve_color(notification_type, level)
        blocks = self._build_blocks(message, level, meta)

        payload: dict[str, Any] = {
            "attachments": [
                {
                    "color": color,
                    "blocks": blocks,
                }
            ]
        }
        resolved_channel = channel or self._default_channel
        if resolved_channel is not None:
            payload["channel"] = resolved_channel
        return payload

    def _build_blocks(
        self, message: str, level: str, metadata: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """全ブロックを組み立てて返す."""
        blocks: list[dict[str, Any]] = []
        phase = metadata.get("phase")

        # 1. Header block
        blocks.append(self._build_header_block(phase, level, metadata))

        # 2. Divider
        blocks.append({"type": "divider"})

        # 3. Message section
        blocks.append(self._build_message_block(message, phase))

        # 4. Actions block (リンクボタン、URLがある場合のみ)
        actions = self._build_actions_block(metadata)
        if actions is not None:
            blocks.append(actions)

        # 5. Divider
        blocks.append({"type": "divider"})

        # 6. Stats section (進捗・経過時間・変更ファイル数)
        stats = self._build_stats_block(metadata)
        if stats is not None:
            blocks.append(stats)
            blocks.append({"type": "divider"})

        # 7. Context block (メタデータ)
        context = self._build_context_block(metadata)
        if context is not None:
            blocks.append(context)

        return blocks

    def _resolve_color(self, notification_type: str, level: str) -> str:
        """通知種別・レベルからカラーバーの色を決定する."""
        # 1. notification_type による判定
        color_key = _NOTIFICATION_TYPE_COLOR.get(notification_type)
        if color_key:
            return NOTIFICATION_COLORS[color_key]

        # 2. level によるフォールバック
        if level in ("error", "critical"):
            return NOTIFICATION_COLORS["error"]

        return NOTIFICATION_COLORS["start"]

    def _build_header_block(
        self, phase: str | None, level: str, metadata: dict[str, Any]
    ) -> dict[str, Any]:
        """Header block を構築する."""
        emoji = self._phase_emoji(phase) if phase else self._level_emoji(level)
        phase_label = PHASE_LABELS.get(phase or "", phase or "通知")
        notification_type = metadata.get("notification_type", "")

        if notification_type == "phase_start":
            title = f"{emoji} {phase_label}フェーズ開始"
        elif level in ("error", "critical"):
            title = f"{emoji} エラー発生"
        elif phase == "done":
            title = f"{emoji} Issue完了"
        else:
            title = f"{emoji} {phase_label}フェーズ完了"

        return {
            "type": "header",
            "text": {"type": "plain_text", "text": title},
        }

    def _build_message_block(self, message: str, phase: str | None) -> dict[str, Any]:
        """メッセージ本文の Section block を構築する."""
        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": message},
        }

    def _build_actions_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """リンクボタンの Actions block を構築する (URL がある場合のみ)."""
        elements: list[dict[str, Any]] = []
        repo = metadata.get("repo")
        issue = metadata.get("issue")
        pr_url = metadata.get("pr_url")
        pr = metadata.get("pr")
        design_pr_url = metadata.get("design_pr_url")
        design_pr = metadata.get("design_pr")

        # Issue ボタン
        if repo and issue is not None:
            issue_url = f"https://github.com/{repo}/issues/{issue}"
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Issue を見る"},
                "url": issue_url,
            })

        # PR ボタン
        if pr_url:
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "PR を見る"},
                "url": pr_url,
            })
        elif repo and pr is not None:
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "PR を見る"},
                "url": f"https://github.com/{repo}/pull/{pr}",
            })

        # 設計PR ボタン
        if design_pr_url:
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "設計PR を見る"},
                "url": design_pr_url,
            })
        elif repo and design_pr is not None:
            elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": "設計PR を見る"},
                "url": f"https://github.com/{repo}/pull/{design_pr}",
            })

        if not elements:
            return None

        return {"type": "actions", "elements": elements}

    def _build_stats_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """進捗・経過時間・変更ファイル数の Section block を構築する."""
        parts: list[str] = []

        # 進捗
        progress = self._build_progress_text(metadata)
        if progress:
            parts.append(progress)

        # 経過時間
        duration = metadata.get("duration_sec")
        if duration is not None:
            parts.append(f":stopwatch: *経過:* {self._format_duration(duration)}")

        # 変更ファイル数
        files_changed = metadata.get("files_changed")
        if files_changed is not None:
            added = metadata.get("lines_added", 0)
            deleted = metadata.get("lines_deleted", 0)
            parts.append(
                f":file_folder: *変更:* {files_changed}ファイル (+{added} -{deleted})"
            )

        # CI結果
        ci_total = metadata.get("ci_total")
        if ci_total is not None:
            ci_passed = metadata.get("ci_passed", 0)
            ci_failed = metadata.get("ci_failed", 0)
            parts.append(
                f":test_tube: *CI:* {ci_passed}pass / {ci_failed}fail (計{ci_total})"
            )

        if not parts:
            return None

        return {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(parts)},
        }

    def _build_context_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """メタデータの Context block を構築する."""
        parts: list[str] = []

        issue_type = metadata.get("issue_type")
        if issue_type:
            parts.append(f":label: {issue_type}")

        repo = metadata.get("repo")
        if repo:
            parts.append(f":package: `{repo}`")

        parts.append(":robot_face: AI Agent")

        return {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": " | ".join(parts)},
            ],
        }

    @staticmethod
    def _phase_emoji(phase: str | None) -> str:
        """フェーズに応じた絵文字を返す."""
        if phase is None:
            return ":robot_face:"
        return PHASE_EMOJI.get(phase, ":robot_face:")

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
    def _format_duration(seconds: float) -> str:
        """秒数を人間可読な文字列に変換する (例: '2分34秒')."""
        total = int(seconds)
        if total < 60:
            return f"{total}秒"
        minutes, secs = divmod(total, 60)
        if secs == 0:
            return f"{minutes}分"
        return f"{minutes}分{secs}秒"

    @staticmethod
    def _build_progress_text(metadata: dict[str, Any]) -> str | None:
        """進捗ステータスのテキストを構築する (例: '[3/7] 設計完了')."""
        step_current = metadata.get("step_current")
        step_total = metadata.get("step_total")
        step_label = metadata.get("step_label")

        if step_current is None or step_total is None:
            return None

        label_part = f" {step_label}" if step_label else ""
        return f":bar_chart: *進捗:* `[{step_current}/{step_total}]`{label_part}"
