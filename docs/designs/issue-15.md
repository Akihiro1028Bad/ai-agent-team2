# Issue #15: Slack メッセージ改善 設計書

## 1. 概要

Slack 通知の「タイミング・フォーマット・内容」を全面的にアップグレードする。
現在の単一フォーマット通知を、**通知タイプ別テンプレート** + **Block Kit リッチレイアウト**に刷新し、**フェーズ開始通知**・**CI 結果通知**・**PR レビューコメント受信通知**を追加する。

### スコープ

- **通知タイミング追加**: フェーズ開始時、CI 実行開始/結果、PR レビューコメント受信時
- **メッセージフォーマット**: 通知タイプ別絵文字 + Block Kit ヘッダー・divider・カラーバー付き attachment（レベル B）
- **メッセージ内容拡充**: 処理時間、Issue タイトル、変更ファイル数/差分サマリ、次のステップ案内、エラースタックトレース（500文字切り詰め）
- **言語**: 日本語
- **チャンネル**: 同一チャンネル（現状維持）
- **Webhook**: Incoming Webhook のまま（Slack App 移行なし）
- **承認待ちリマインダー**: 不要（スコープ外）

---

## 2. 現状分析

### 2.1 現在の通知ポイント（計20箇所）

| カテゴリ | 箇所 | 内容 |
|---------|------|------|
| **フェーズ通知** | `hearing.py` | 質問投稿時 |
| | `analysis.py` | 修正方針投稿時 |
| | `design.py` | 設計 PR 作成時 |
| | `implement.py` | 実装 PR 作成時 |
| | `fix.py` | 修正 PR 作成時 |
| | `plan_brief.py` | 実装方針投稿時 |
| | `design_revise.py` | 設計修正時 |
| | `impl_revise.py` | 実装修正時 |
| | `split.py` | 分割提案時・分割完了時 |
| | `done.py` | 完了時・連鎖処理開始時 |
| **エラー通知** | `base.py` | タイムアウト・エラー発生時 |
| | `orchestrator.py` | ルーティングエラー・ヘルスチェック失敗 |
| **システム通知** | `orchestrator.py` | Orchestrator 起動時 |

### 2.2 現在の課題

1. **通知タイプ別の差別化がない** — すべて info レベルで同じフォーマット
2. **仕様書の `notification_type` が未実装** — `hearing_question`, `design_pr_created` 等のテンプレートが使われていない
3. **repo 情報が metadata に含まれていない箇所が多い** — リンクが不完全
4. **フェーズ開始の通知がない** — 完了時のみで進捗が見えにくい
5. **処理時間や進捗情報がない**
6. **CI 結果や PR レビューコメントの通知がない**

---

## 3. 設計方針

### 3.1 アーキテクチャ方針

- **後方互換性を維持**: `notify()` の既存シグネチャを変更せず、`metadata` キーの拡充で対応
- **通知タイプ駆動**: `metadata["notification_type"]` でテンプレートを切り替え
- **Block Kit リッチレイアウト**: ヘッダーブロック + セクション + divider + カラーバー付き attachment
- **best-effort 通知**: 送信失敗時は例外を発生させない（現状維持）

### 3.2 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `src/ai_agent_orchestrator/notifications/slack.py` | **大幅改修** | テンプレートエンジン、リッチレイアウト、新メソッド追加 |
| `src/ai_agent_orchestrator/phases/base.py` | **改修** | フェーズ開始通知、処理時間記録、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/hearing.py` | **改修** | `notification_type` + Issue タイトル追加 |
| `src/ai_agent_orchestrator/phases/analysis.py` | **改修** | `notification_type` + Issue タイトル追加 |
| `src/ai_agent_orchestrator/phases/design.py` | **改修** | `notification_type` + Issue タイトル追加 |
| `src/ai_agent_orchestrator/phases/implement.py` | **改修** | `notification_type` + Issue タイトル + 差分サマリ追加 |
| `src/ai_agent_orchestrator/phases/fix.py` | **改修** | `notification_type` + Issue タイトル追加 |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | **改修** | `notification_type` + Issue タイトル追加 |
| `src/ai_agent_orchestrator/phases/design_revise.py` | **改修** | `notification_type` 追加 |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | **改修** | `notification_type` 追加 |
| `src/ai_agent_orchestrator/phases/split.py` | **改修** | `notification_type` 追加 |
| `src/ai_agent_orchestrator/phases/done.py` | **改修** | `notification_type` + 処理時間追加 |
| `src/ai_agent_orchestrator/phases/ci_fix.py` | **改修** | CI 結果通知追加 |
| `src/ai_agent_orchestrator/poller/event_router.py` | **改修** | PR レビューコメント受信通知追加 |
| `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | **改修** | 起動通知のリッチ化 |
| `docs/specs/slack.md` | **更新** | 仕様書を新フォーマットに合わせて更新 |
| `tests/unit/test_slack.py` | **大幅追加** | 新テンプレート・リッチレイアウトのテスト追加 |

---

## 4. 通知タイプ定義

### 4.1 通知タイプ一覧

| `notification_type` | カテゴリ | 絵文字 | カラーバー | トリガー |
|---------------------|---------|--------|-----------|---------|
| `phase_start` | 進捗 | :arrow_forward: | `#2196F3` (青) | フェーズ開始時 |
| `hearing_question` | 完了 | :speech_balloon: | `#FF9800` (橙) | ヒアリング質問投稿時 |
| `analysis_posted` | 完了 | :mag: | `#9C27B0` (紫) | Bug 原因分析投稿時 |
| `plan_posted` | 完了 | :clipboard: | `#FF9800` (橙) | 方針投稿時（Bug/Feature-S） |
| `design_pr_created` | 完了 | :pencil: | `#4CAF50` (緑) | 設計 PR 作成時 |
| `impl_pr_created` | 完了 | :rocket: | `#4CAF50` (緑) | 実装 PR 作成時 |
| `fix_pr_created` | 完了 | :wrench: | `#4CAF50` (緑) | 修正 PR 作成時 |
| `design_revised` | 完了 | :pencil2: | `#2196F3` (青) | 設計修正時 |
| `impl_revised` | 完了 | :hammer_and_wrench: | `#2196F3` (青) | 実装修正時 |
| `split_proposed` | 完了 | :scissors: | `#FF9800` (橙) | 分割提案時 |
| `split_completed` | 完了 | :white_check_mark: | `#4CAF50` (緑) | 分割完了時 |
| `ci_started` | CI | :gear: | `#2196F3` (青) | CI 実行開始時 |
| `ci_passed` | CI | :white_check_mark: | `#4CAF50` (緑) | CI 成功時 |
| `ci_failed` | CI | :warning: | `#F44336` (赤) | CI 失敗時 |
| `review_comment` | レビュー | :eyes: | `#FF9800` (橙) | PR レビューコメント受信時 |
| `done` | 完了 | :tada: | `#4CAF50` (緑) | Issue 完了時 |
| `chain_start` | 進捗 | :link: | `#2196F3` (青) | 連鎖処理開始時 |
| `error` | エラー | :x: | `#F44336` (赤) | 処理エラー時 |
| `timeout` | エラー | :hourglass: | `#F44336` (赤) | タイムアウト時 |
| `critical` | エラー | :rotating_light: | `#F44336` (赤) | 重大エラー時 |
| `system_start` | システム | :robot_face: | `#2196F3` (青) | Orchestrator 起動時 |

### 4.2 通知タイプ Enum 定義

```python
class NotificationType(StrEnum):
    """Slack 通知タイプ."""

    PHASE_START = "phase_start"
    HEARING_QUESTION = "hearing_question"
    ANALYSIS_POSTED = "analysis_posted"
    PLAN_POSTED = "plan_posted"
    DESIGN_PR_CREATED = "design_pr_created"
    IMPL_PR_CREATED = "impl_pr_created"
    FIX_PR_CREATED = "fix_pr_created"
    DESIGN_REVISED = "design_revised"
    IMPL_REVISED = "impl_revised"
    SPLIT_PROPOSED = "split_proposed"
    SPLIT_COMPLETED = "split_completed"
    CI_STARTED = "ci_started"
    CI_PASSED = "ci_passed"
    CI_FAILED = "ci_failed"
    REVIEW_COMMENT = "review_comment"
    DONE = "done"
    CHAIN_START = "chain_start"
    ERROR = "error"
    TIMEOUT = "timeout"
    CRITICAL = "critical"
    SYSTEM_START = "system_start"
```

---

## 5. メッセージフォーマット設計

### 5.1 Block Kit リッチレイアウト構造

すべての通知メッセージは以下の統一構造を持つ:

```
┌─────────────────────────────────────────┐
│ [header] 絵文字 タイトル                  │
├─────────────────────────────────────────┤
│ [divider]                               │
├─────────────────────────────────────────┤
│ [section] メッセージ本文                  │
│   - Issue タイトル                       │
│   - 処理時間（該当時）                    │
│   - 差分サマリ（該当時）                  │
│   - 次のステップ案内（該当時）             │
│   - スタックトレース（エラー時）           │
├─────────────────────────────────────────┤
│ [context] リポジトリ | Issue | PR | phase │
├─────────────────────────────────────────┤
│ [attachment] カラーバー（レベル別色）      │
└─────────────────────────────────────────┘
```

### 5.2 ペイロード構造の例

#### 通常通知（実装 PR 作成時）

```json
{
    "attachments": [
        {
            "color": "#4CAF50",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚀 実装 PR を作成しました",
                        "emoji": true
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Issue #42* \"ログイン画面のバグ修正\"\n\n<https://github.com/org/repo/pull/11|PR #11> を作成しました。\n\n:bar_chart: *差分サマリ*: 5ファイル変更 (+120 -30)\n:stopwatch: *所要時間*: 3分24秒\n\n:next_track_button: *次のアクション*: PR をレビューして approve してください"
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :memo: <https://github.com/org/repo/pull/11|PR #11> | :gear: phase: implement"
                        }
                    ]
                }
            ]
        }
    ]
}
```

#### エラー通知（スタックトレース付き）

```json
{
    "attachments": [
        {
            "color": "#F44336",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ エラーが発生しました",
                        "emoji": true
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Issue #42* \"ログイン画面のバグ修正\"\n\nphase: implement でエラーが発生しました。\n\n```\nTraceback (most recent call last):\n  File \"phases/implement.py\", line 45\n    ...\nRuntimeError: PR作成に失敗しました\n```"
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :gear: phase: implement"
                        }
                    ]
                }
            ]
        }
    ]
}
```

#### フェーズ開始通知

```json
{
    "attachments": [
        {
            "color": "#2196F3",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "▶️ 設計フェーズを開始しました",
                        "emoji": true
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Issue #42* \"ログイン画面のバグ修正\"\n\n設計フェーズの処理を開始します。"
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :gear: phase: design"
                        }
                    ]
                }
            ]
        }
    ]
}
```

---

## 6. 詳細設計

### 6.1 `SlackNotifier` クラスの改修

#### 6.1.1 新規定数・テンプレート定義

```python
from enum import StrEnum

class NotificationType(StrEnum):
    """Slack 通知タイプ."""
    PHASE_START = "phase_start"
    HEARING_QUESTION = "hearing_question"
    ANALYSIS_POSTED = "analysis_posted"
    PLAN_POSTED = "plan_posted"
    DESIGN_PR_CREATED = "design_pr_created"
    IMPL_PR_CREATED = "impl_pr_created"
    FIX_PR_CREATED = "fix_pr_created"
    DESIGN_REVISED = "design_revised"
    IMPL_REVISED = "impl_revised"
    SPLIT_PROPOSED = "split_proposed"
    SPLIT_COMPLETED = "split_completed"
    CI_STARTED = "ci_started"
    CI_PASSED = "ci_passed"
    CI_FAILED = "ci_failed"
    REVIEW_COMMENT = "review_comment"
    DONE = "done"
    CHAIN_START = "chain_start"
    ERROR = "error"
    TIMEOUT = "timeout"
    CRITICAL = "critical"
    SYSTEM_START = "system_start"


# 通知タイプ → 絵文字マッピング
_TYPE_EMOJI: dict[str, str] = {
    "phase_start": ":arrow_forward:",
    "hearing_question": ":speech_balloon:",
    "analysis_posted": ":mag:",
    "plan_posted": ":clipboard:",
    "design_pr_created": ":pencil:",
    "impl_pr_created": ":rocket:",
    "fix_pr_created": ":wrench:",
    "design_revised": ":pencil2:",
    "impl_revised": ":hammer_and_wrench:",
    "split_proposed": ":scissors:",
    "split_completed": ":white_check_mark:",
    "ci_started": ":gear:",
    "ci_passed": ":white_check_mark:",
    "ci_failed": ":warning:",
    "review_comment": ":eyes:",
    "done": ":tada:",
    "chain_start": ":link:",
    "error": ":x:",
    "timeout": ":hourglass:",
    "critical": ":rotating_light:",
    "system_start": ":robot_face:",
}

# 通知タイプ → カラーバー色マッピング
_TYPE_COLOR: dict[str, str] = {
    "phase_start": "#2196F3",
    "hearing_question": "#FF9800",
    "analysis_posted": "#9C27B0",
    "plan_posted": "#FF9800",
    "design_pr_created": "#4CAF50",
    "impl_pr_created": "#4CAF50",
    "fix_pr_created": "#4CAF50",
    "design_revised": "#2196F3",
    "impl_revised": "#2196F3",
    "split_proposed": "#FF9800",
    "split_completed": "#4CAF50",
    "ci_started": "#2196F3",
    "ci_passed": "#4CAF50",
    "ci_failed": "#F44336",
    "review_comment": "#FF9800",
    "done": "#4CAF50",
    "chain_start": "#2196F3",
    "error": "#F44336",
    "timeout": "#F44336",
    "critical": "#F44336",
    "system_start": "#2196F3",
}

# レベル別フォールバック色
_LEVEL_COLOR: dict[str, str] = {
    "info": "#2196F3",
    "error": "#F44336",
    "critical": "#F44336",
}

# スタックトレースの最大文字数
_MAX_STACKTRACE_LEN = 500
```

#### 6.1.2 `notify()` メソッドの変更

シグネチャは変更しない。`metadata` 内の新キーを認識するように拡張:

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

**新たに認識する metadata キー:**

| キー | 型 | 説明 |
|------|------|------|
| `notification_type` | `str` | 通知タイプ（`NotificationType` の値） |
| `issue_title` | `str` | Issue タイトル |
| `duration_sec` | `float` | 処理時間（秒） |
| `diff_summary` | `str` | 差分サマリ（例: "5ファイル変更 (+120 -30)"） |
| `next_action` | `str` | 次のステップ案内テキスト |
| `stacktrace` | `str` | エラースタックトレース |
| `repo` | `str` | リポジトリ名（既存） |
| `issue` | `int` | Issue 番号（既存） |
| `pr` | `int` | PR 番号（既存） |
| `pr_url` | `str` | PR URL（既存） |
| `phase` | `str` | フェーズ名（既存） |

#### 6.1.3 `_build_payload()` の全面改修

新しい `_build_payload()` は以下の処理を行う:

1. `notification_type` から絵文字・カラーバー色を解決（フォールバック: `level` から解決）
2. ヘッダーブロックを構築（通知タイプ絵文字 + メッセージ本文の1行目）
3. divider ブロック
4. セクションブロック（本文 + 追加情報）:
   - Issue タイトル（`issue_title` があれば `*Issue #XX* "タイトル"` 形式）
   - 処理時間（`duration_sec` があれば `⏱ 所要時間: X分Y秒` 形式）
   - 差分サマリ（`diff_summary` があれば `📊 差分サマリ: ...` 形式）
   - 次のステップ案内（`next_action` があれば `⏭ 次のアクション: ...` 形式）
   - スタックトレース（`stacktrace` があれば末尾500文字をコードブロックで表示）
5. divider ブロック（エラー時のみ、セクションとコンテキストの間に追加）
6. コンテキストブロック（既存の `_build_context_text()` を改良）
7. 全体を `attachments` でラップしてカラーバーを適用

```python
def _build_payload(
    self,
    message: str,
    *,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    meta = metadata or {}
    notification_type = meta.get("notification_type", "")

    # 絵文字とカラーの解決
    emoji = _TYPE_EMOJI.get(notification_type, _LEVEL_EMOJI.get(level, ":robot_face:"))
    color = _TYPE_COLOR.get(notification_type, _LEVEL_COLOR.get(level, "#2196F3"))

    blocks: list[dict[str, Any]] = []

    # 1. ヘッダーブロック
    header_text = f"{emoji} {message}".split("\n")[0]  # 1行目のみ
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": header_text[:150],  # Slack header 上限
            "emoji": True,
        },
    })

    # 2. divider
    blocks.append({"type": "divider"})

    # 3. セクション（詳細情報）
    body_parts: list[str] = []
    body_parts.append(self._build_issue_line(meta))
    body_parts.append(self._build_message_body(message, meta))
    body_parts.append(self._build_duration_line(meta))
    body_parts.append(self._build_diff_line(meta))
    body_parts.append(self._build_next_action_line(meta))
    body_parts.append(self._build_stacktrace_block(meta))

    body_text = "\n".join(p for p in body_parts if p)
    if body_text:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": body_text[:3000]},
        })

    # 4. コンテキストブロック
    context_text = self._build_context_text(meta)
    if context_text:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context_text}],
        })

    # attachments でカラーバーを適用
    payload: dict[str, Any] = {
        "attachments": [{"color": color, "blocks": blocks}],
    }

    resolved_channel = channel or self._default_channel
    if resolved_channel is not None:
        payload["channel"] = resolved_channel

    return payload
```

#### 6.1.4 新規ヘルパーメソッド

```python
@staticmethod
def _build_issue_line(meta: dict[str, Any]) -> str:
    """Issue タイトル行を構築する."""
    issue = meta.get("issue")
    title = meta.get("issue_title")
    if issue is not None and title:
        return f'*Issue #{issue}* "{title}"'
    if issue is not None:
        return f"*Issue #{issue}*"
    return ""

@staticmethod
def _build_message_body(message: str, meta: dict[str, Any]) -> str:
    """メッセージ本文（ヘッダーに含まれない部分）を構築する."""
    lines = message.split("\n")
    # ヘッダーに1行目を使うので、残りを返す
    remaining = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return remaining

@staticmethod
def _build_duration_line(meta: dict[str, Any]) -> str:
    """処理時間行を構築する."""
    duration = meta.get("duration_sec")
    if duration is None:
        return ""
    minutes = int(duration) // 60
    seconds = int(duration) % 60
    if minutes > 0:
        return f":stopwatch: *所要時間*: {minutes}分{seconds}秒"
    return f":stopwatch: *所要時間*: {seconds}秒"

@staticmethod
def _build_diff_line(meta: dict[str, Any]) -> str:
    """差分サマリ行を構築する."""
    diff = meta.get("diff_summary")
    if not diff:
        return ""
    return f":bar_chart: *差分サマリ*: {diff}"

@staticmethod
def _build_next_action_line(meta: dict[str, Any]) -> str:
    """次のアクション行を構築する."""
    action = meta.get("next_action")
    if not action:
        return ""
    return f":next_track_button: *次のアクション*: {action}"

@staticmethod
def _build_stacktrace_block(meta: dict[str, Any]) -> str:
    """スタックトレースブロックを構築する（最大500文字に切り詰め）."""
    trace = meta.get("stacktrace")
    if not trace:
        return ""
    if len(trace) > _MAX_STACKTRACE_LEN:
        trace = "..." + trace[-_MAX_STACKTRACE_LEN:]
    return f"```\n{trace}\n```"
```

#### 6.1.5 `_build_context_text()` の改良

既存メソッドに phase 表示の改善を追加:

```python
@staticmethod
def _build_context_text(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None

    parts: list[str] = []
    repo = metadata.get("repo")
    issue = metadata.get("issue")
    pr = metadata.get("pr")
    pr_url = metadata.get("pr_url")
    phase = metadata.get("phase")

    if repo:
        parts.append(f":package: `{repo}`")

    if repo and issue is not None:
        issue_url = f"https://github.com/{repo}/issues/{issue}"
        parts.append(f":page_facing_up: <{issue_url}|Issue #{issue}>")
    elif issue is not None:
        parts.append(f":page_facing_up: Issue #{issue}")

    if pr is not None and pr_url:
        parts.append(f":memo: <{pr_url}|PR #{pr}>")
    elif pr is not None and repo:
        pr_url_gen = f"https://github.com/{repo}/pull/{pr}"
        parts.append(f":memo: <{pr_url_gen}|PR #{pr}>")
    elif pr is not None:
        parts.append(f":memo: PR #{pr}")

    if phase:
        parts.append(f":gear: phase: {phase}")

    return " | ".join(parts) if parts else None
```

### 6.2 `PhaseExecutor` 基底クラスの改修

#### 6.2.1 フェーズ開始通知の追加

`execute()` テンプレートメソッドにフェーズ開始時の通知を追加:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        # --- 新規: フェーズ開始通知 ---
        issue_title = await self._get_issue_title(request)
        repo_full = self._get_repo_fullname(request)
        await self._notifier.notify(
            f"{self._phase_display_name(request.phase)} フェーズを開始しました",
            metadata={
                "notification_type": "phase_start",
                "issue": request.issue_number,
                "issue_title": issue_title,
                "repo": repo_full,
                "phase": str(request.phase),
            },
        )
        # --- ここまで新規 ---

        import time
        start_time = time.monotonic()

        prompt = await self.build_prompt(request)
        result = await self.run_agent(request, prompt)
        await self.process_result(request, result)

        elapsed = time.monotonic() - start_time

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

#### 6.2.2 新規ヘルパーメソッド

```python
async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する（失敗時は空文字列）."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        return ""

@staticmethod
def _get_repo_fullname(request: TaskRequest) -> str:
    """リポジトリのフルネーム (owner/repo) を取得する."""
    if isinstance(request.repo, str):
        return request.repo
    owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    if owner and repo_name:
        return f"{owner}/{repo_name}"
    return ""

@staticmethod
def _phase_display_name(phase: object) -> str:
    """フェーズの日本語表示名を返す."""
    display_names: dict[str, str] = {
        "type-detection": "タイプ判定",
        "hearing": "ヒアリング",
        "analysis": "原因分析",
        "plan-brief": "方針策定",
        "design": "設計",
        "design-review": "設計レビュー",
        "design-revise": "設計修正",
        "planning": "実装計画",
        "implement": "実装",
        "fix": "修正",
        "ci-fix": "CI修正",
        "impl-review": "実装レビュー",
        "impl-revise": "実装修正",
        "split-proposal": "分割提案",
        "split-execute": "分割実行",
        "done": "完了",
    }
    phase_str = str(phase)
    return display_names.get(phase_str, phase_str)
```

#### 6.2.3 エラーハンドラの改修

```python
async def _handle_timeout(self, request: TaskRequest) -> None:
    """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + 通知."""
    state = self._sm.get_state(request.issue_number)
    if state and state.session_id:
        await self._runner.interrupt(state.session_id)

    await self._sm.transition(request.issue_number, "suspended")
    try:
        client = await self._get_client(request.repo)
        await client.replace_phase_label(request.repo, request.issue_number, "phase:suspended")
    except Exception:
        logger.warning("Failed to update phase label for issue #%d", request.issue_number)

    issue_title = await self._get_issue_title(request)
    repo_full = self._get_repo_fullname(request)
    await self._notifier.notify(
        f"{self._phase_display_name(request.phase)} フェーズがタイムアウトしました",
        level="error",
        metadata={
            "notification_type": "timeout",
            "issue": request.issue_number,
            "issue_title": issue_title,
            "repo": repo_full,
            "phase": str(request.phase),
        },
    )

async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: SUSPENDED 遷移 + Issue コメント + 通知."""
    import traceback

    await self._sm.transition(request.issue_number, "suspended")
    client = await self._get_client(request.repo)
    try:
        await client.replace_phase_label(request.repo, request.issue_number, "phase:suspended")
    except Exception:
        logger.warning("Failed to update phase label for issue #%d", request.issue_number)
    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    issue_title = await self._get_issue_title(request)
    repo_full = self._get_repo_fullname(request)
    stacktrace = traceback.format_exception(type(error), error, error.__traceback__)
    stacktrace_str = "".join(stacktrace)

    await self._notifier.notify(
        f"エラーが発生しました",
        level="error",
        metadata={
            "notification_type": "error",
            "issue": request.issue_number,
            "issue_title": issue_title,
            "repo": repo_full,
            "phase": str(request.phase),
            "error": str(error),
            "stacktrace": stacktrace_str,
        },
    )
```

### 6.3 各フェーズの改修

#### 6.3.1 共通パターン

各フェーズの `process_result()` 内で `notify()` を呼ぶ際に、以下の情報を `metadata` に追加:

- `notification_type`: 通知タイプ
- `issue_title`: Issue タイトル（`_get_issue_title()` で取得）
- `repo`: リポジトリフルネーム
- `duration_sec`: `result.duration_sec`（AgentResult から取得）
- `next_action`: 次のステップ案内テキスト
- `diff_summary`: 差分情報（PR 作成系のみ）

#### 6.3.2 各フェーズの変更詳細

**hearing.py:**
```python
await self._notifier.notify(
    "ヒアリング質問を投稿しました",
    metadata={
        "notification_type": "hearing_question",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "コメントで回答してください",
    },
)
```

**analysis.py:**
```python
await self._notifier.notify(
    "修正方針を投稿しました",
    metadata={
        "notification_type": "analysis_posted",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "コメントに👍リアクションで承認してください",
    },
)
```

**design.py:**
```python
await self._notifier.notify(
    "設計 PR を作成しました",
    metadata={
        "notification_type": "design_pr_created",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "設計 PR をレビューして approve してください",
    },
)
```

**implement.py:**
```python
await self._notifier.notify(
    "実装 PR を作成しました",
    metadata={
        "notification_type": "impl_pr_created",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "diff_summary": diff_summary,
        "next_action": "PR をレビューして approve してください",
    },
)
```

**fix.py:**
```python
await self._notifier.notify(
    "修正 PR を作成しました",
    metadata={
        "notification_type": "fix_pr_created",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "PR をレビューして approve してください",
    },
)
```

**plan_brief.py:**
```python
await self._notifier.notify(
    "実装方針を投稿しました",
    metadata={
        "notification_type": "plan_posted",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "コメントに👍リアクションで承認してください",
    },
)
```

**design_revise.py:**
```python
await self._notifier.notify(
    "設計書を修正しました",
    metadata={
        "notification_type": "design_revised",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "設計 PR で再レビューをお願いします",
    },
)
```

**impl_revise.py:**
```python
await self._notifier.notify(
    "実装を修正しました",
    metadata={
        "notification_type": "impl_revised",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "実装 PR で再レビューをお願いします",
    },
)
```

**split.py (SplitProposalExecutor):**
```python
await self._notifier.notify(
    "分割を提案しました",
    metadata={
        "notification_type": "split_proposed",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
        "next_action": "コメントに👍リアクションで承認してください",
    },
)
```

**split.py (SplitExecuteExecutor):**
```python
await self._notifier.notify(
    "分割が完了しました",
    metadata={
        "notification_type": "split_completed",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
    },
)
```

**done.py (完了通知):**
```python
await self._notifier.notify(
    "Issue が完了しました",
    metadata={
        "notification_type": "done",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": str(request.phase),
        "duration_sec": result.duration_sec,
    },
)
```

**done.py (連鎖処理開始通知):**
```python
await self._notifier.notify(
    f"連鎖処理を開始します",
    metadata={
        "notification_type": "chain_start",
        "issue": candidate.number,
        "repo": repo_full,
    },
)
```

### 6.4 CI 通知の追加

#### 6.4.1 `ci_fix.py` の改修

CI 結果の通知を `process_result()` に追加:

```python
async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
    issue_title = await self._get_issue_title(request)
    repo_full = self._get_repo_fullname(request)

    # CI 修正開始を通知
    await self._notifier.notify(
        "CI 修正を実行しています",
        metadata={
            "notification_type": "ci_started",
            "issue": request.issue_number,
            "issue_title": issue_title,
            "repo": repo_full,
            "phase": str(request.phase),
        },
    )

    # ... 既存の CI 修正ロジック ...
```

#### 6.4.2 `event_router.py` での CI 結果通知

EventRouter 内で CI 結果イベント処理時に通知を追加:

```python
# CI 成功時
await self._notifier.notify(
    "CI が成功しました",
    metadata={
        "notification_type": "ci_passed",
        "issue": issue_number,
        "repo": repo_full,
        "pr": pr_number,
        "phase": "ci-fix",
    },
)

# CI 失敗時
await self._notifier.notify(
    "CI が失敗しました。修正を開始します",
    metadata={
        "notification_type": "ci_failed",
        "issue": issue_number,
        "repo": repo_full,
        "pr": pr_number,
        "phase": "ci-fix",
    },
)
```

### 6.5 PR レビューコメント受信通知

#### 6.5.1 `event_router.py` の改修

PR コメント受信時に通知を追加:

```python
# 設計 PR コメント受信時
await self._notifier.notify(
    "設計 PR にレビューコメントが届きました",
    metadata={
        "notification_type": "review_comment",
        "issue": issue_number,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": "design-review",
    },
)

# 実装 PR コメント受信時
await self._notifier.notify(
    "実装 PR にレビューコメントが届きました",
    metadata={
        "notification_type": "review_comment",
        "issue": issue_number,
        "repo": repo_full,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": "impl-review",
    },
)
```

### 6.6 差分サマリの取得

PR 作成系フェーズ（implement, fix）で差分サマリを取得するヘルパー:

```python
@staticmethod
def _extract_diff_summary(agent_output: str) -> str:
    """エージェント出力から差分サマリを抽出する.

    エージェント出力に含まれる git diff --stat の結果や
    ファイル変更数の情報を抽出する。

    Args:
        agent_output: エージェントの出力テキスト。

    Returns:
        差分サマリ文字列。抽出できない場合は空文字列。
    """
    # "X files changed, Y insertions(+), Z deletions(-)" パターン
    match = re.search(
        r"(\d+)\s+files?\s+changed(?:,\s+(\d+)\s+insertions?\(\+\))?(?:,\s+(\d+)\s+deletions?\(-\))?",
        agent_output,
    )
    if match:
        files = match.group(1)
        insertions = match.group(2) or "0"
        deletions = match.group(3) or "0"
        return f"{files}ファイル変更 (+{insertions} -{deletions})"
    return ""
```

---

## 7. テスト計画

### 7.1 新規テストケース

既存の `tests/unit/test_slack.py` に以下のテストを追加:

| テストID | テスト内容 |
|---------|----------|
| TC-SL-14 | `notification_type` による絵文字の切り替え（`impl_pr_created` → `:rocket:`） |
| TC-SL-15 | `notification_type` によるカラーバー色の適用 |
| TC-SL-16 | ヘッダーブロック + divider + セクション + コンテキストの構造検証 |
| TC-SL-17 | `attachments` ラッパーの存在検証 |
| TC-SL-18 | `issue_title` がセクションに含まれること |
| TC-SL-19 | `duration_sec` の表示フォーマット（分秒変換） |
| TC-SL-20 | `diff_summary` のセクション表示 |
| TC-SL-21 | `next_action` のセクション表示 |
| TC-SL-22 | `stacktrace` の500文字切り詰め |
| TC-SL-23 | `stacktrace` が500文字以下の場合はそのまま表示 |
| TC-SL-24 | `notification_type` 未指定時のフォールバック（`level` からの解決） |
| TC-SL-25 | フェーズ開始通知のペイロード構造 |
| TC-SL-26 | エラー通知のリッチフォーマット（ヘッダー + スタックトレース） |
| TC-SL-27 | セクションテキストの3000文字上限 |
| TC-SL-28 | ヘッダーテキストの150文字上限 |
| TC-SL-29 | `_build_issue_line()` の各パターン |
| TC-SL-30 | `_build_duration_line()` の分秒フォーマット |
| TC-SL-31 | `_build_context_text()` の PR URL 自動生成（`pr_url` 未指定 + `repo` あり） |
| TC-SL-32 | `NotificationType` Enum の全値テスト |

### 7.2 既存テストへの影響

既存テスト（TC-SL-01 〜 TC-SL-13）は、ペイロード構造の変更により一部修正が必要:

- **TC-SL-01**: `blocks` → `attachments[0].blocks` に変更
- **TC-SL-02, 03**: 同上
- **TC-SL-04**: コンテキスト取得パスの変更
- **TC-SL-06, 07**: channel キーの位置は変わらない
- **TC-SL-12**: 変更なし（metadata なしのケース）

---

## 8. 実装手順

### Phase 1: SlackNotifier コアの改修

1. `NotificationType` Enum の追加（`slack.py` 内）
2. `_TYPE_EMOJI`, `_TYPE_COLOR` 辞書の追加
3. `_build_payload()` の全面改修
4. 新規ヘルパーメソッドの追加
5. `_build_context_text()` の改良
6. 既存テストの修正 + 新規テスト追加

### Phase 2: PhaseExecutor 基底クラスの改修

1. `_get_issue_title()`, `_get_repo_fullname()`, `_phase_display_name()` の追加
2. `execute()` にフェーズ開始通知を追加
3. `_handle_timeout()`, `_handle_error()` の改修
4. テスト追加

### Phase 3: 各フェーズの metadata 拡充

1. 全フェーズの `notify()` 呼び出しに `notification_type` + 追加メタデータを設定
2. `_extract_diff_summary()` の追加（implement.py, fix.py）
3. 各フェーズのテスト更新

### Phase 4: 新規通知ポイントの追加

1. `event_router.py` に CI 結果通知を追加
2. `event_router.py` に PR レビューコメント受信通知を追加
3. `ci_fix.py` に CI 修正開始通知を追加
4. テスト追加

### Phase 5: 仕様書・ドキュメント更新

1. `docs/specs/slack.md` を新仕様に合わせて更新

---

## 9. リスクと緩和策

| リスク | 影響 | 緩和策 |
|-------|------|--------|
| Slack Block Kit テキスト上限（3000文字） | 長いスタックトレースで切り詰め | 500文字上限 + コードブロック内表示 |
| ヘッダーブロックの plain_text 上限（150文字） | 長いメッセージが切れる | 1行目のみ抽出 + 150文字で切り詰め |
| `_get_issue_title()` の API 呼び出し増加 | レートリミットの懸念 | 失敗時は空文字列でフォールバック、キャッシュは将来検討 |
| 既存テストの大量修正 | テスト工数の増加 | ペイロード構造のアサーションをヘルパー関数化 |
| attachments ベースのカラーバー | Incoming Webhook での互換性 | Slack 公式ドキュメントで対応を確認済み |

---

## 10. 非スコープ（将来検討）

- Slack App 移行（ボタン等のインタラクティブ要素）
- 承認待ちリマインダー
- 通知チャンネルの分離
- Issue タイトルのキャッシュ機構
- 多言語対応
- スレッド返信による Issue 単位のメッセージグルーピング
