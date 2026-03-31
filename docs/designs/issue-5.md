# Issue #5: Slackメッセージ改善 設計書

## 1. 概要

Slack通知のタイミング・フォーマット・内容を全面的にアップグレードする。
現在のシンプルな section + context の2ブロック構成を、Header Block + Section + Fields を用いた
リッチフォーマットに刷新し、通知タイミングの追加、言語の日本語統一、エラー時の詳細情報表示を実現する。

### 1.1 スコープ

| 項目 | 内容 |
|------|------|
| 通知タイミング | フェーズ開始・完了・エラー・Issue受付を追加 |
| フォーマット | リッチフォーマット（Header + Section + Fields） |
| メッセージ内容 | コスト・フェーズ名・アクション案内・Issueタイトル・エラー詳細 |
| 言語 | すべて日本語に統一 |
| スレッド対応 | 不要（現行Webhook方式を維持） |
| リマインド通知 | 不要 |

### 1.2 スコープ外

- Slack Bot Token (`xoxb-`) への移行
- Slackスレッド対応（Issue単位のスレッドまとめ）
- 承認待ちリマインド通知

---

## 2. 現状分析

### 2.1 現在の通知アーキテクチャ

```
PhaseExecutor / Orchestrator
        │
        ▼
  NotifierProtocol.notify(message, level, metadata)
        │
        ▼
  SlackNotifier._build_payload()
        │
        ▼
  SlackNotifier.send() → Slack Webhook POST
```

### 2.2 現在の通知箇所（全18箇所）

| # | ファイル | タイミング | メッセージ例 | 言語 |
|---|---------|-----------|------------|------|
| 1 | `orchestrator.py` | オーケストレーター起動 | `Orchestrator started` | 英語 |
| 2 | `orchestrator.py` | イベントルーティングエラー | `Event routing error: {exc}` | 英語 |
| 3 | `orchestrator.py` | Issueエラー停止 | `Issue #{n} suspended due to error: {e}` | 英語 |
| 4 | `orchestrator.py` | ヘルスチェック失敗 | `Health check failures: {names}` | 英語 |
| 5 | `base.py` | タイムアウト | `Issue #{n} がタイムアウトしました (phase: {p})` | 日本語 |
| 6 | `base.py` | フェーズエラー | `Issue #{n} でエラー: {e} (phase: {p})` | 日本語 |
| 7 | `hearing.py` | ヒアリング質問投稿 | `Issue #{n} に質問を投稿しました。回答をお願いします` | 日本語 |
| 8 | `analysis.py` | 修正方針投稿 | `Issue #{n} の修正方針を投稿しました。thumbsup で承認をお願いします` | 日本語 |
| 9 | `plan_brief.py` | 実装方針投稿 | `Issue #{n} の実装方針を投稿しました。thumbsup で承認をお願いします` | 日本語 |
| 10 | `design.py` | 設計PR作成 | `Issue #{n} の設計PR #{pr} を作成しました。レビューをお願いします` | 日本語 |
| 11 | `implement.py` | 実装PR作成 | `Issue #{n} の実装PR #{pr} を作成しました` | 日本語 |
| 12 | `fix.py` | 修正PR作成 | `Issue #{n} の修正PR #{pr} を作成しました。レビュー待ちです` | 日本語 |
| 13 | `design_revise.py` | 設計修正完了 | `Issue #{n} の設計書を修正しました` | 日本語 |
| 14 | `impl_revise.py` | 実装修正完了 | `Issue #{n} の実装を修正しました` | 日本語 |
| 15 | `split.py` | 分割提案 | `Issue #{n} の分割を提案しました。判断をお願いします` | 日本語 |
| 16 | `split.py` | 分割完了 | `Issue #{n} の分割が完了しました` | 日本語 |
| 17 | `done.py` | Issue完了 | `Issue #{n} 完了しました` | 日本語 |
| 18 | `done.py` | 連鎖Issue開始 | `Issue #{n} の処理を開始します (#{m} 完了による連鎖)` | 日本語 |

### 2.3 現在のペイロード構造

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":robot_face: Issue #42 の実装 PR を作成しました"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <url|Issue #42> | :memo: phase:implement"
                }
            ]
        }
    ]
}
```

### 2.4 現在の課題

1. **絵文字が3種類のみ**（`info`→🤖、`error`→❌、`critical`→🚨）で通知タイプが区別できない
2. **フェーズ開始時の通知がない**（完了時のみ）
3. **Issue受付時の通知がない**
4. **言語が混在**（オーケストレーター系：英語、フェーズ系：日本語）
5. **repo情報がmetadataに含まれない通知が多い**
6. **コスト・所要時間がメッセージに含まれない**
7. **Issueタイトルが通知に含まれない**
8. **ユーザーアクション案内が不統一**
9. **エラー時の情報が不十分**（エラーメッセージ1行のみ）

---

## 3. 設計方針

### 3.1 通知カテゴリの定義

通知を以下の3カテゴリに分類し、カテゴリごとにフォーマットを定義する。

| カテゴリ | 説明 | 例 |
|---------|------|-----|
| **アクション要求** | ユーザーの操作が必要 | ヒアリング回答、方針承認、PRレビュー |
| **情報通知** | 進捗の報告 | フェーズ開始、フェーズ完了、Issue完了 |
| **エラー通知** | 異常の報告 | タイムアウト、フェーズエラー、ヘルスチェック失敗 |

### 3.2 通知タイプ（notification_type）の定義

```python
class NotificationType(StrEnum):
    """Slack通知タイプ."""

    # システム系
    SYSTEM_START = "system_start"          # オーケストレーター起動
    SYSTEM_HEALTH = "system_health"        # ヘルスチェック失敗

    # Issue ライフサイクル
    ISSUE_RECEIVED = "issue_received"      # Issue受付（NEW）
    ISSUE_COMPLETE = "issue_complete"      # Issue完了

    # フェーズ進行
    PHASE_START = "phase_start"            # フェーズ開始
    PHASE_COMPLETE = "phase_complete"      # フェーズ完了

    # アクション要求
    ACTION_HEARING = "action_hearing"      # ヒアリング回答要求
    ACTION_APPROVE = "action_approve"      # 方針承認要求（Bug/Feature-S）
    ACTION_REVIEW = "action_review"        # PRレビュー要求（Feature-M）
    ACTION_SPLIT = "action_split"          # 分割判断要求

    # エラー系
    ERROR_TIMEOUT = "error_timeout"        # タイムアウト
    ERROR_PHASE = "error_phase"            # フェーズ実行エラー
    ERROR_ROUTING = "error_routing"        # イベントルーティングエラー
    ERROR_SUSPENDED = "error_suspended"    # Issue停止
```

### 3.3 通知タイプ別 絵文字マッピング

```python
_NOTIFICATION_EMOJI: dict[str, str] = {
    # システム系
    "system_start": ":rocket:",
    "system_health": ":warning:",

    # Issue ライフサイクル
    "issue_received": ":eyes:",
    "issue_complete": ":white_check_mark:",

    # フェーズ進行
    "phase_start": ":arrow_forward:",
    "phase_complete": ":ballot_box_with_check:",

    # アクション要求
    "action_hearing": ":speech_balloon:",
    "action_approve": ":thumbsup:",
    "action_review": ":mag:",
    "action_split": ":scissors:",

    # エラー系
    "error_timeout": ":hourglass:",
    "error_phase": ":x:",
    "error_routing": ":warning:",
    "error_suspended": ":rotating_light:",
}
```

---

## 4. リッチフォーマット設計

### 4.1 新しいペイロード構造

全通知タイプで統一的に以下の構造を使用する:

```
┌─────────────────────────────────────────┐
│ 📝 Header Block                         │
│   「Issue #42: ユーザー認証の改善」       │
├─────────────────────────────────────────┤
│ 📄 Section Block (メインメッセージ)       │
│   「implement フェーズが完了しました」    │
├─────────────────────────────────────────┤
│ 📊 Fields Block (メタ情報)               │
│   リポジトリ: org/repo                   │
│   フェーズ: implement                    │
│   コスト: $0.45                          │
│   所要時間: 3分24秒                      │
├─────────────────────────────────────────┤
│ 🔗 Context Block (リンク)                │
│   Issue #42 | PR #11                     │
└─────────────────────────────────────────┘
```

### 4.2 新しいペイロード JSON 例

#### 情報通知（フェーズ完了）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "☑️ フェーズ完了: Issue #42",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "implement フェーズが完了しました"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ:*\n`org/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ:*\nimlement" },
                { "type": "mrkdwn", "text": "*コスト:*\n$0.45" },
                { "type": "mrkdwn", "text": "*所要時間:*\n3分24秒" }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :memo: <https://github.com/org/repo/pull/11|PR #11>"
                }
            ]
        }
    ]
}
```

#### アクション要求通知（ヒアリング回答要求）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "💬 回答をお願いします: Issue #42",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Issue #42 「ユーザー認証の改善」にヒアリング質問を投稿しました。\nIssueコメントで回答をお願いします。"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ:*\n`org/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ:*\nhearing" }
            ]
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": { "type": "plain_text", "text": "Issue を開く" },
                    "url": "https://github.com/org/repo/issues/42"
                }
            ]
        }
    ]
}
```

#### エラー通知（フェーズエラー）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "❌ エラー発生: Issue #42",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "implement フェーズでエラーが発生しました"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ:*\n`org/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ:*\nimplement" },
                { "type": "mrkdwn", "text": "*エラー種別:*\nRuntimeError" },
                { "type": "mrkdwn", "text": "*ステータス:*\nsuspended" }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*エラー詳細:*\n```No transition defined from Phase.DESIGN to Phase.DESIGN```"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*考えられる原因:*\n• ステートマシンの遷移定義に DESIGN → DESIGN が含まれていない\n• 同一フェーズへの再遷移が試行された可能性\n• 前のフェーズからの遷移先が正しく設定されていない可能性"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":page_facing_up: <https://github.com/org/repo/issues/42|Issue #42>"
                }
            ]
        }
    ]
}
```

---

## 5. notify() インターフェースの拡張

### 5.1 現在のインターフェース

```python
async def notify(
    self,
    message: str,
    *,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
```

### 5.2 新しいインターフェース

**後方互換性を維持**しつつ、`metadata` に新しいキーを追加する。
`notify()` のシグネチャ自体は変更しない。

```python
async def notify(
    self,
    message: str,
    *,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
```

### 5.3 metadata の拡張キー

| キー | 型 | 説明 | 必須 |
|------|-----|------|------|
| `repo` | `str` | リポジトリ名（`owner/repo`形式） | 推奨 |
| `issue` | `int` | Issue番号 | 推奨 |
| `issue_title` | `str` | Issueタイトル | 推奨 |
| `pr` | `int` | PR番号 | 任意 |
| `pr_url` | `str` | PR URL | 任意 |
| `phase` | `str` | 現在のフェーズ名 | 推奨 |
| `notification_type` | `str` | 通知タイプ（§3.2 参照） | 推奨 |
| `cost_usd` | `float` | フェーズ実行コスト（USD） | 任意 |
| `duration_sec` | `float` | フェーズ実行時間（秒） | 任意 |
| `error` | `str` | エラーメッセージ | エラー時 |
| `error_type` | `str` | エラークラス名 | エラー時 |
| `error_detail` | `str` | エラー詳細（トレースバック等） | エラー時 |
| `error_cause` | `str` | 推定原因 | エラー時（任意） |
| `next_action` | `str` | ユーザーに求めるアクション | アクション通知時 |

---

## 6. SlackNotifier クラスの改修設計

### 6.1 変更ファイル

`src/ai_agent_orchestrator/notifications/slack.py`

### 6.2 新しいクラス構造

```python
"""SlackNotifier (Webhook 通知)."""

from __future__ import annotations

import logging
import traceback
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── 通知タイプ別絵文字マッピング ──

_NOTIFICATION_EMOJI: dict[str, str] = {
    "system_start": ":rocket:",
    "system_health": ":warning:",
    "issue_received": ":eyes:",
    "issue_complete": ":white_check_mark:",
    "phase_start": ":arrow_forward:",
    "phase_complete": ":ballot_box_with_check:",
    "action_hearing": ":speech_balloon:",
    "action_approve": ":thumbsup:",
    "action_review": ":mag:",
    "action_split": ":scissors:",
    "error_timeout": ":hourglass:",
    "error_phase": ":x:",
    "error_routing": ":warning:",
    "error_suspended": ":rotating_light:",
}

# フォールバック（notification_type 未指定時の level ベース）
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
    ) -> None: ...

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def send(self, payload: dict[str, Any]) -> bool: ...

    async def close(self) -> None: ...

    # ── internal ──

    def _build_payload(
        self,
        message: str,
        *,
        channel: str | None,
        level: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """リッチフォーマットのペイロードを構築する."""
        ...

    def _build_header_block(
        self, emoji: str, message: str, metadata: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Header Block を構築する."""
        ...

    def _build_message_block(self, message: str) -> dict[str, Any]:
        """メインメッセージの Section Block を構築する."""
        ...

    def _build_fields_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """Fields 付き Section Block を構築する."""
        ...

    def _build_error_detail_block(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """エラー詳細ブロックを構築する."""
        ...

    def _build_action_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """Actions Block（リンクボタン）を構築する."""
        ...

    def _build_context_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """Context Block（リンク集）を構築する."""
        ...

    @staticmethod
    def _resolve_emoji(level: str, metadata: dict[str, Any] | None) -> str:
        """notification_type → level の優先順位で絵文字を解決する."""
        ...

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """秒数を「X分Y秒」形式にフォーマットする."""
        ...

    @staticmethod
    def _format_cost(cost_usd: float) -> str:
        """コストを「$X.XX」形式にフォーマットする."""
        ...
```

### 6.3 `_build_payload()` の詳細ロジック

```python
def _build_payload(self, message, *, channel, level, metadata):
    meta = metadata or {}
    emoji = self._resolve_emoji(level, metadata)
    blocks = []

    # 1. Header Block
    blocks.append(self._build_header_block(emoji, message, meta))

    # 2. Message Section Block
    blocks.append(self._build_message_block(message))

    # 3. Fields Block（metadata がある場合）
    fields = self._build_fields_block(meta)
    if fields:
        blocks.append(fields)

    # 4. エラー詳細ブロック（エラー系通知の場合）
    error_blocks = self._build_error_detail_block(meta)
    blocks.extend(error_blocks)

    # 5. Actions Block（アクション要求通知の場合）
    actions = self._build_action_block(meta)
    if actions:
        blocks.append(actions)

    # 6. Context Block（リンク）
    context = self._build_context_block(meta)
    if context:
        blocks.append(context)

    resolved_channel = channel or self._default_channel
    payload = {"blocks": blocks}
    if resolved_channel is not None:
        payload["channel"] = resolved_channel
    return payload
```

### 6.4 Header Block のフォーマットルール

| notification_type | ヘッダーテキスト |
|-------------------|-----------------|
| `system_start` | `🚀 オーケストレーター起動` |
| `system_health` | `⚠️ ヘルスチェック異常` |
| `issue_received` | `👀 Issue受付: Issue #{n}` |
| `issue_complete` | `✅ 完了: Issue #{n}` |
| `phase_start` | `▶️ {phase} 開始: Issue #{n}` |
| `phase_complete` | `☑️ {phase} 完了: Issue #{n}` |
| `action_hearing` | `💬 回答をお願いします: Issue #{n}` |
| `action_approve` | `👍 承認をお願いします: Issue #{n}` |
| `action_review` | `🔍 レビューをお願いします: Issue #{n}` |
| `action_split` | `✂️ 分割判断をお願いします: Issue #{n}` |
| `error_timeout` | `⏳ タイムアウト: Issue #{n}` |
| `error_phase` | `❌ エラー発生: Issue #{n}` |
| `error_routing` | `⚠️ ルーティングエラー` |
| `error_suspended` | `🚨 Issue停止: Issue #{n}` |

`notification_type` が未指定の場合は `level` ベースのフォールバック:
- `info`: `🤖 通知`
- `error`: `❌ エラー`
- `critical`: `🚨 重大エラー`

### 6.5 Fields Block の構成

metadata に含まれるキーに応じて動的にフィールドを構築する:

```python
def _build_fields_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    fields = []

    if "repo" in metadata:
        fields.append({"type": "mrkdwn", "text": f"*リポジトリ:*\n`{metadata['repo']}`"})

    if "phase" in metadata:
        fields.append({"type": "mrkdwn", "text": f"*フェーズ:*\n{metadata['phase']}"})

    if "cost_usd" in metadata:
        fields.append({"type": "mrkdwn", "text": f"*コスト:*\n{self._format_cost(metadata['cost_usd'])}"})

    if "duration_sec" in metadata:
        fields.append({"type": "mrkdwn", "text": f"*所要時間:*\n{self._format_duration(metadata['duration_sec'])}"})

    if "error_type" in metadata:
        fields.append({"type": "mrkdwn", "text": f"*エラー種別:*\n{metadata['error_type']}"})

    if not fields:
        return None

    return {"type": "section", "fields": fields}
```

### 6.6 エラー詳細ブロック

エラー系通知の場合、追加のブロックを生成する:

```python
def _build_error_detail_block(self, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []

    # エラーメッセージ
    error = metadata.get("error")
    if error:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*エラー詳細:*\n```{error}```",
            },
        })

    # エラー詳細（スタックトレース等）
    error_detail = metadata.get("error_detail")
    if error_detail:
        # Slackのブロックテキスト上限(3000文字)を考慮して切り詰め
        truncated = error_detail[:2500]
        if len(error_detail) > 2500:
            truncated += "\n... (truncated)"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*スタックトレース:*\n```{truncated}```",
            },
        })

    # 推定原因
    error_cause = metadata.get("error_cause")
    if error_cause:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*考えられる原因:*\n{error_cause}",
            },
        })

    return blocks
```

---

## 7. 通知呼び出し側の改修設計

### 7.1 PhaseExecutor 基底クラス (`base.py`)

#### 7.1.1 フェーズ開始通知の追加

`execute()` メソッドにフェーズ開始通知を追加する:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        # ★ 新規: フェーズ開始通知
        await self._notify_phase_start(request)

        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        prompt = await self.build_prompt(request)
        result = await self.run_agent(request, prompt)
        await self.process_result(request, result)

        # ★ 新規: フェーズ完了通知（コスト・時間付き）
        await self._notify_phase_complete(request, result)

        await self._tracker.track(
            "phase_end",
            issue_number=request.issue_number,
            phase=str(request.phase),
            data={
                "cost_usd": result.cost_usd,
                "duration_sec": result.duration_sec,
            },
        )
    except TimeoutError:
        await self._handle_timeout(request)
    except Exception as exc:
        await self._handle_error(request, exc)
```

#### 7.1.2 新規ヘルパーメソッド

```python
async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する（取得失敗時は空文字列）."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        return ""

def _build_repo_str(self, request: TaskRequest) -> str:
    """リポジトリ文字列（owner/repo）を構築する."""
    owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    return f"{owner}/{repo_name}" if owner and repo_name else ""

async def _notify_phase_start(self, request: TaskRequest) -> None:
    """フェーズ開始通知を送信する."""
    title = await self._get_issue_title(request)
    repo_str = self._build_repo_str(request)
    phase = str(request.phase)
    issue_num = request.issue_number

    title_part = f"「{title}」" if title else ""
    await self._notifier.notify(
        f"Issue #{issue_num} {title_part}の {phase} フェーズを開始します",
        level="info",
        metadata={
            "repo": repo_str,
            "issue": issue_num,
            "issue_title": title,
            "phase": phase,
            "notification_type": "phase_start",
        },
    )

async def _notify_phase_complete(
    self, request: TaskRequest, result: AgentResult
) -> None:
    """フェーズ完了通知を送信する（コスト・時間付き）."""
    repo_str = self._build_repo_str(request)
    phase = str(request.phase)
    issue_num = request.issue_number

    await self._notifier.notify(
        f"Issue #{issue_num} の {phase} フェーズが完了しました",
        level="info",
        metadata={
            "repo": repo_str,
            "issue": issue_num,
            "phase": phase,
            "notification_type": "phase_complete",
            "cost_usd": result.cost_usd,
            "duration_sec": result.duration_sec,
        },
    )
```

#### 7.1.3 エラー処理の改善

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: SUSPENDED 遷移 + Issue コメント + 詳細通知."""
    await self._sm.transition(request.issue_number, "suspended")
    client = await self._get_client(request.repo)
    try:
        await client.replace_phase_label(
            request.repo, request.issue_number, "phase:suspended"
        )
    except Exception:
        logger.warning(
            "Failed to update phase label to suspended for issue #%d",
            request.issue_number,
        )
    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    # ★ 改善: エラー詳細情報を含む通知
    repo_str = self._build_repo_str(request)
    error_detail = traceback.format_exception(type(error), error, error.__traceback__)
    error_detail_str = "".join(error_detail)
    error_cause = self._analyze_error_cause(error)

    await self._notifier.notify(
        f"Issue #{request.issue_number} の {request.phase} フェーズでエラーが発生しました",
        level="error",
        metadata={
            "repo": repo_str,
            "issue": request.issue_number,
            "phase": str(request.phase),
            "notification_type": "error_phase",
            "error": str(error),
            "error_type": type(error).__name__,
            "error_detail": error_detail_str,
            "error_cause": error_cause,
        },
    )

@staticmethod
def _analyze_error_cause(error: Exception) -> str:
    """エラーの推定原因を分析する."""
    error_msg = str(error).lower()

    if "no transition defined" in error_msg:
        return (
            "• ステートマシンの遷移定義に該当の遷移が含まれていない\n"
            "• 同一フェーズへの再遷移が試行された可能性\n"
            "• 前のフェーズからの遷移先が正しく設定されていない可能性"
        )
    if "timeout" in error_msg:
        return (
            "• エージェント実行が制限時間を超過した\n"
            "• 対象コードベースが大きすぎる可能性\n"
            "• APIレート制限に到達した可能性"
        )
    if "rate limit" in error_msg or "429" in error_msg:
        return (
            "• GitHub API または Claude API のレート制限に到達した\n"
            "• しばらく待ってからリトライしてください"
        )
    if "auth" in error_msg or "401" in error_msg or "403" in error_msg:
        return (
            "• 認証トークンが無効または期限切れ\n"
            "• トークンの権限が不足している可能性"
        )
    if "conflict" in error_msg or "merge" in error_msg:
        return (
            "• Gitのマージコンフリクトが発生した\n"
            "• ベースブランチが更新されている可能性"
        )

    return "• 詳細はスタックトレースを確認してください"
```

#### 7.1.4 タイムアウト処理の改善

```python
async def _handle_timeout(self, request: TaskRequest) -> None:
    """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + 詳細通知."""
    state = self._sm.get_state(request.issue_number)
    if state and state.session_id:
        await self._runner.interrupt(state.session_id)

    await self._sm.transition(request.issue_number, "suspended")
    try:
        client = await self._get_client(request.repo)
        await client.replace_phase_label(
            request.repo, request.issue_number, "phase:suspended"
        )
    except Exception:
        logger.warning(
            "Failed to update phase label to suspended for issue #%d",
            request.issue_number,
        )

    repo_str = self._build_repo_str(request)
    await self._notifier.notify(
        f"Issue #{request.issue_number} の {request.phase} フェーズがタイムアウトしました",
        level="error",
        metadata={
            "repo": repo_str,
            "issue": request.issue_number,
            "phase": str(request.phase),
            "notification_type": "error_timeout",
            "error": f"{request.phase} フェーズが制限時間内に完了しませんでした",
            "error_type": "TimeoutError",
            "error_cause": (
                "• エージェント実行が制限時間を超過した\n"
                "• 対象コードベースが大きすぎる可能性\n"
                "• APIレート制限に到達した可能性"
            ),
        },
    )
```

### 7.2 各フェーズファイルの改修

フェーズ個別の通知（アクション要求系）は、`notification_type` と追加メタデータを付与する形で改修する。
**フェーズ開始・完了通知は `base.py` で一括処理**するため、個別フェーズでは削除する。

#### 7.2.1 hearing.py

```python
# Before:
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    metadata={"issue": request.issue_number},
)

# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」にヒアリング質問を投稿しました。\n"
    f"Issueコメントで回答をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "hearing",
        "notification_type": "action_hearing",
        "next_action": "Issueコメントで回答してください",
    },
)
```

#### 7.2.2 analysis.py

```python
# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の修正方針を投稿しました。\n"
    f"👍リアクションで承認をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "analysis",
        "notification_type": "action_approve",
        "next_action": "コメントに👍リアクションで承認してください",
    },
)
```

#### 7.2.3 plan_brief.py

```python
# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の実装方針を投稿しました。\n"
    f"👍リアクションで承認をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "plan-brief",
        "notification_type": "action_approve",
        "next_action": "コメントに👍リアクションで承認してください",
    },
)
```

#### 7.2.4 design.py

```python
# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の設計PR #{pr_number} を作成しました。\n"
    f"PRをレビューして approve をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "pr": pr_number,
        "pr_url": f"https://github.com/{repo_str}/pull/{pr_number}",
        "phase": "design",
        "notification_type": "action_review",
        "next_action": "設計PRをレビューしてapproveしてください",
    },
)
```

#### 7.2.5 implement.py

```python
# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の実装PR #{pr_number} を作成しました。\n"
    f"PRをレビューして approve をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "pr": pr_number,
        "pr_url": f"https://github.com/{repo_str}/pull/{pr_number}",
        "phase": "implement",
        "notification_type": "action_review",
        "next_action": "実装PRをレビューしてapproveしてください",
    },
)
```

#### 7.2.6 fix.py

```python
# After:
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の修正PR #{pr_number} を作成しました。\n"
    f"PRをレビューして approve をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "pr": pr_number,
        "pr_url": f"https://github.com/{repo_str}/pull/{pr_number}",
        "phase": "fix",
        "notification_type": "action_review",
        "next_action": "修正PRをレビューしてapproveしてください",
    },
)
```

#### 7.2.7 design_revise.py / impl_revise.py

フェーズ完了通知は `base.py` の `_notify_phase_complete()` で処理されるため、
個別の notify 呼び出しは **再レビュー要求通知** に変更する:

```python
# design_revise.py
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の設計書を修正しました。\n"
    f"再レビューをお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "design-revise",
        "notification_type": "action_review",
        "next_action": "設計PRを再レビューしてapproveしてください",
    },
)

# impl_revise.py
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の実装を修正しました。\n"
    f"再レビューをお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "impl-revise",
        "notification_type": "action_review",
        "next_action": "実装PRを再レビューしてapproveしてください",
    },
)
```

#### 7.2.8 split.py

```python
# 分割提案
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の分割を提案しました。\n"
    f"判断をお願いします。",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "split-proposal",
        "notification_type": "action_split",
        "next_action": "分割案を確認し、👍リアクションで承認してください",
    },
)

# 分割完了
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」の分割が完了しました",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "split-execute",
        "notification_type": "phase_complete",
    },
)
```

#### 7.2.9 done.py

```python
# Issue 完了
repo_str = self._build_repo_str(request)
title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 「{title}」が完了しました 🎉",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": title,
        "phase": "done",
        "notification_type": "issue_complete",
    },
)

# 連鎖Issue開始
await self._notifier.notify(
    f"Issue #{candidate.number} の処理を開始します（#{request.issue_number} 完了による連鎖）",
    level="info",
    metadata={
        "repo": repo_str,
        "issue": candidate.number,
        "notification_type": "issue_received",
    },
)
```

### 7.3 Orchestrator の改修

`orchestrator.py` の通知呼び出しを日本語化し、`notification_type` を付与する:

```python
# 起動通知
await self._notifier.notify(
    "オーケストレーターが起動しました",
    level="info",
    metadata={
        "notification_type": "system_start",
        "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
    },
)

# イベントルーティングエラー
await self._notifier.notify(
    f"イベントルーティングでエラーが発生しました: {exc}",
    level="error",
    metadata={
        "notification_type": "error_routing",
        "error": str(exc),
        "error_type": type(exc).__name__,
    },
)

# Issue停止
await self._notifier.notify(
    f"Issue #{issue_number} がエラーにより停止しました",
    level="error",
    metadata={
        "issue": issue_number,
        "phase": task.phase,
        "notification_type": "error_suspended",
        "error": str(error),
        "error_type": type(error).__name__,
    },
)

# ヘルスチェック失敗
await self._notifier.notify(
    f"ヘルスチェックに失敗しました: {', '.join(unhealthy)}",
    level="error",
    metadata={
        "notification_type": "system_health",
        "error": f"異常コンポーネント: {', '.join(unhealthy)}",
    },
)
```

### 7.4 EventRouter での Issue 受付通知

`event_router.py` の `NEW_ISSUE` イベント処理に Issue 受付通知を追加:

```python
# NEW_ISSUE 処理内
await self._notifier.notify(
    f"Issue #{issue_number} 「{issue_title}」を受け付けました。処理を開始します。",
    level="info",
    metadata={
        "repo": f"{repo.owner}/{repo.repo}",
        "issue": issue_number,
        "issue_title": issue_title,
        "notification_type": "issue_received",
    },
)
```

---

## 8. 変更対象ファイル一覧

| # | ファイル | 変更内容 | 影響度 |
|---|---------|---------|--------|
| 1 | `notifications/slack.py` | リッチフォーマット対応、全面改修 | **大** |
| 2 | `phases/base.py` | フェーズ開始/完了通知追加、エラー詳細改善、ヘルパーメソッド追加 | **大** |
| 3 | `orchestrator/orchestrator.py` | 通知の日本語化、notification_type追加 | **中** |
| 4 | `poller/event_router.py` | Issue受付通知追加 | **小** |
| 5 | `phases/hearing.py` | 通知メタデータ拡充 | **小** |
| 6 | `phases/analysis.py` | 通知メタデータ拡充 | **小** |
| 7 | `phases/plan_brief.py` | 通知メタデータ拡充 | **小** |
| 8 | `phases/design.py` | 通知メタデータ拡充 | **小** |
| 9 | `phases/implement.py` | 通知メタデータ拡充 | **小** |
| 10 | `phases/fix.py` | 通知メタデータ拡充 | **小** |
| 11 | `phases/design_revise.py` | 通知メタデータ拡充 | **小** |
| 12 | `phases/impl_revise.py` | 通知メタデータ拡充 | **小** |
| 13 | `phases/split.py` | 通知メタデータ拡充 | **小** |
| 14 | `phases/done.py` | 通知メタデータ拡充 | **小** |
| 15 | `tests/unit/test_slack.py` | リッチフォーマット対応のテスト更新・追加 | **大** |
| 16 | `tests/unit/test_phases.py` | フェーズ開始/完了通知のテスト追加 | **中** |

---

## 9. テスト計画

### 9.1 SlackNotifier テスト更新 (`tests/unit/test_slack.py`)

#### 既存テストの更新

| テスト | 変更内容 |
|--------|---------|
| TC-SL-01 | Header Block の存在を検証に追加 |
| TC-SL-02 | `notification_type` ベースの絵文字解決を検証 |
| TC-SL-04 | Fields Block の構造を検証 |

#### 新規テスト

| テスト ID | テスト内容 |
|----------|-----------|
| TC-SL-14 | `notification_type` 指定時に正しい絵文字が使用される |
| TC-SL-15 | `notification_type` 未指定時に `level` ベースのフォールバックが動作する |
| TC-SL-16 | Header Block のテキストが `notification_type` に応じて正しい |
| TC-SL-17 | Fields Block に `repo`, `phase`, `cost_usd`, `duration_sec` が含まれる |
| TC-SL-18 | エラー通知時にエラー詳細ブロックが含まれる |
| TC-SL-19 | エラー通知時に推定原因ブロックが含まれる |
| TC-SL-20 | エラー詳細が3000文字を超える場合に切り詰められる |
| TC-SL-21 | Actions Block にリンクボタンが含まれる（アクション通知時） |
| TC-SL-22 | `_format_duration()` が正しいフォーマットを返す |
| TC-SL-23 | `_format_cost()` が正しいフォーマットを返す |
| TC-SL-24 | metadata が空の場合でも Header + Message の最小構成で送信される |

### 9.2 PhaseExecutor テスト更新 (`tests/unit/test_phases.py`)

| テスト ID | テスト内容 |
|----------|-----------|
| TC-PH-XX | フェーズ開始時に `phase_start` 通知が送信される |
| TC-PH-XX | フェーズ完了時に `phase_complete` 通知が送信される（コスト・時間付き） |
| TC-PH-XX | エラー時に `error_phase` 通知が送信される（詳細情報付き） |
| TC-PH-XX | タイムアウト時に `error_timeout` 通知が送信される |
| TC-PH-XX | `_analyze_error_cause()` が各エラーパターンを正しく分析する |

---

## 10. 実装手順

### Step 1: SlackNotifier の改修（`notifications/slack.py`）

1. `_NOTIFICATION_EMOJI` マッピングを追加
2. `_resolve_emoji()` メソッドを実装
3. `_build_header_block()` メソッドを実装
4. `_build_fields_block()` メソッドを実装
5. `_build_error_detail_block()` メソッドを実装
6. `_build_action_block()` メソッドを実装
7. `_build_context_block()` メソッドを既存の `_build_context_text()` から移行
8. `_format_duration()` / `_format_cost()` ユーティリティを実装
9. `_build_payload()` を新構造で再実装
10. テスト更新・追加

### Step 2: PhaseExecutor 基底クラスの改修（`phases/base.py`）

1. `_build_repo_str()` ヘルパーを追加
2. `_get_issue_title()` ヘルパーを追加
3. `_notify_phase_start()` を追加
4. `_notify_phase_complete()` を追加
5. `_analyze_error_cause()` を追加
6. `_handle_error()` を改善
7. `_handle_timeout()` を改善
8. `execute()` にフェーズ開始/完了通知を追加
9. テスト更新・追加

### Step 3: 各フェーズファイルの改修

1. `hearing.py` の通知改修
2. `analysis.py` の通知改修
3. `plan_brief.py` の通知改修
4. `design.py` の通知改修
5. `implement.py` の通知改修
6. `fix.py` の通知改修
7. `design_revise.py` の通知改修
8. `impl_revise.py` の通知改修
9. `split.py` の通知改修
10. `done.py` の通知改修

### Step 4: Orchestrator / EventRouter の改修

1. `orchestrator.py` の通知日本語化 + metadata拡充
2. `event_router.py` に Issue受付通知を追加

### Step 5: テスト実行・検証

1. `uv run pytest tests/unit/test_slack.py -v`
2. `uv run pytest tests/unit/test_phases.py -v`
3. `uv run pytest tests/ -v`（全テスト）
4. `uv run mypy src/`（型チェック）
5. `uv run ruff check src/ tests/`（lint）

---

## 11. 後方互換性

### 11.1 互換性を維持する設計

- `notify()` メソッドのシグネチャは変更しない
- `metadata` に新しいキーを追加する形で拡張（既存キーはそのまま）
- `notification_type` 未指定の場合は従来通り `level` ベースのフォールバック動作
- `NullNotifier` は変更不要（`notify()` シグネチャが同じ）

### 11.2 破壊的変更

- ペイロード構造の変更（`section` + `context` → `header` + `section` + `fields` + `context`）
  - ※ Slack Webhook の受信側（Slack）は Block Kit の任意構造を受け入れるため、受信側への影響なし
- テストでペイロード構造をアサートしている箇所は更新が必要

---

## 12. 見積もり

| ステップ | 作業内容 | 見積もり |
|---------|---------|---------|
| Step 1 | SlackNotifier 改修 + テスト | 中 |
| Step 2 | PhaseExecutor 基底クラス改修 + テスト | 中 |
| Step 3 | 各フェーズファイル改修（10ファイル） | 小〜中 |
| Step 4 | Orchestrator / EventRouter 改修 | 小 |
| Step 5 | 統合テスト・検証 | 小 |
| **合計** | | **feature-m 相当** |
