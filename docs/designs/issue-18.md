# Issue #18: Slack メッセージ改善 設計書

## 1. 概要

Slack 通知の **タイミング・フォーマット・内容** を全面的にアップグレードする。

### 1.1 現状の課題

| 項目 | 現状 | 課題 |
|------|------|------|
| タイミング | 18箇所（フェーズ終了時中心） | フェーズ開始通知が無く、処理中か停止中か判別不能 |
| フォーマット | 絵文字(3種) + テキスト + コンテキスト | リッチ感がなく、通知タイプの区別が困難 |
| 内容 | Issue番号 + 簡潔な説明のみ | Issueタイトル、経過時間、コスト、リンク等が不足 |

### 1.2 ゴール

- **全フェーズの開始・終了**に通知を送信（既存の終了通知も統一フォーマットに移行）
- **ヘッダー + ディバイダー + セクション + コンテキスト** の Block Kit リッチフォーマット
- **通知タイプ別の絵文字・色分け**（開始/完了/質問/PR作成/エラー等）
- **追加情報**: Issue タイトル、経過時間、コスト、変更ファイル数、リンク、Issue タイプ
- **エラー通知**: スタックトレース付き（最大5行）

---

## 2. ヒアリング結果サマリ

| 質問 | 回答 |
|------|------|
| 追加タイミング | 各フェーズの始まりと終わりを事細かに |
| 通知頻度制御 | 不要 |
| リッチフォーマット | 希望する（ヘッダー + ディバイダー + セクション構成） |
| 通知タイプ別絵文字・色分け | 必要 |
| スレッド化 | 不要 |
| 追加情報 | 全部含めたい（Issueタイトル、経過時間、リンク、コスト、変更ファイル数、Issueタイプ） |
| エラー詳細度 | スタックトレース付き（最大5行） |
| config.yaml 通知レベル設定 | 不要 |
| 複数チャンネル振り分け | 不要 |
| 全フェーズに開始+終了追加 | はい（type-detection 含む全フェーズ） |

---

## 3. 通知タイプ定義

### 3.1 NotificationType Enum

```python
class NotificationType(StrEnum):
    """Slack 通知タイプ."""

    PHASE_START = "phase_start"          # フェーズ開始
    PHASE_END = "phase_end"              # フェーズ正常終了
    HEARING_QUESTION = "hearing_question" # ヒアリング質問投稿
    PLAN_POSTED = "plan_posted"          # 方針投稿（承認待ち）
    DESIGN_PR_CREATED = "design_pr_created"    # 設計PR作成
    DESIGN_REVISED = "design_revised"    # 設計書修正
    IMPL_PR_CREATED = "impl_pr_created"  # 実装PR作成
    IMPL_REVISED = "impl_revised"        # 実装修正
    FIX_PR_CREATED = "fix_pr_created"    # Bug修正PR作成
    SPLIT_PROPOSED = "split_proposed"    # 分割提案
    SPLIT_COMPLETED = "split_completed"  # 分割完了
    ISSUE_DONE = "issue_done"           # Issue完了
    CHAIN_START = "chain_start"         # 連鎖処理開始
    ERROR = "error"                     # エラー発生
    TIMEOUT = "timeout"                 # タイムアウト
    ORCHESTRATOR_START = "orchestrator_start"  # オーケストレーター起動
    ORCHESTRATOR_ERROR = "orchestrator_error"  # オーケストレーターエラー
    HEALTH_CHECK_FAIL = "health_check_fail"    # ヘルスチェック失敗
    ISSUE_SUSPENDED = "issue_suspended"  # Issue中断
```

### 3.2 通知タイプ別絵文字・レベルマッピング

```python
_NOTIFICATION_CONFIG: dict[str, dict[str, str]] = {
    # フェーズ制御系
    "phase_start":        {"emoji": "▶️",  "level": "info"},
    "phase_end":          {"emoji": "⏹️",  "level": "info"},

    # アクション要求系
    "hearing_question":   {"emoji": "💬", "level": "info"},
    "plan_posted":        {"emoji": "📋", "level": "info"},

    # PR作成系
    "design_pr_created":  {"emoji": "📐", "level": "info"},
    "design_revised":     {"emoji": "✏️",  "level": "info"},
    "impl_pr_created":    {"emoji": "🚀", "level": "info"},
    "impl_revised":       {"emoji": "🔧", "level": "info"},
    "fix_pr_created":     {"emoji": "🐛", "level": "info"},

    # 分割系
    "split_proposed":     {"emoji": "✂️",  "level": "info"},
    "split_completed":    {"emoji": "📦", "level": "info"},

    # 完了系
    "issue_done":         {"emoji": "✅", "level": "info"},
    "chain_start":        {"emoji": "🔗", "level": "info"},

    # エラー系
    "error":              {"emoji": "❌", "level": "error"},
    "timeout":            {"emoji": "⏰", "level": "error"},
    "issue_suspended":    {"emoji": "⏸️",  "level": "error"},

    # オーケストレーター系
    "orchestrator_start": {"emoji": "🤖", "level": "info"},
    "orchestrator_error": {"emoji": "🚨", "level": "critical"},
    "health_check_fail":  {"emoji": "💔", "level": "critical"},
}
```

---

## 4. 新フォーマット設計

### 4.1 Block Kit 構成

全通知を以下の統一構成にする:

```
┌─────────────────────────────────────────────────┐
│ [header]  {emoji} {タイトル}                      │
├─────────────────────────────────────────────────┤
│ [divider]                                       │
├─────────────────────────────────────────────────┤
│ [section]  メッセージ本文                         │
│            （詳細情報、リンク等）                   │
├─────────────────────────────────────────────────┤
│ [context]  📦 repo | 📄 Issue #N | 🏷️ type |    │
│            ⏱️ 経過時間 | 💰 コスト | 📁 ファイル数  │
└─────────────────────────────────────────────────┘
```

### 4.2 ペイロード構造例

#### 正常系（実装PR作成）

```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "🚀 実装PR作成",
        "emoji": true
      }
    },
    {"type": "divider"},
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "<https://github.com/org/repo/issues/42|Issue #42>: *ログイン画面のバグ修正* の実装 <https://github.com/org/repo/pull/11|PR #11> を作成しました。\nレビューをお願いします。"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "📦 `org/repo` | 🏷️ `feature-m` | ⏱️ 5分32秒 | 💰 $0.15 | 📁 12 files changed"
        }
      ]
    }
  ]
}
```

#### フェーズ開始

```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "▶️ 実装フェーズ開始",
        "emoji": true
      }
    },
    {"type": "divider"},
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "<https://github.com/org/repo/issues/42|Issue #42>: *ログイン画面のバグ修正* の実装フェーズを開始します。"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "📦 `org/repo` | 🏷️ `feature-m`"
        }
      ]
    }
  ]
}
```

#### エラー系（スタックトレース付き）

```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "❌ エラー発生",
        "emoji": true
      }
    },
    {"type": "divider"},
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "<https://github.com/org/repo/issues/42|Issue #42>: *ログイン画面のバグ修正* でエラーが発生しました。\n*エラー種別:* `TimeoutError`\n*フェーズ:* `implement`\n```\nTraceback (most recent call last):\n  File \"phases/base.py\", line 296, in execute\n    result = await self.run_agent(request, prompt)\nTimeoutError: Agent execution timed out after 3600s\n```"
      }
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "📦 `org/repo` | 🏷️ `feature-m` | ⏱️ 60分0秒"
        }
      ]
    }
  ]
}
```

---

## 5. notify メソッド インターフェース変更

### 5.1 現行シグネチャ

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

### 5.2 新シグネチャ

```python
async def notify(
    self,
    message: str,
    *,
    notification_type: str = "phase_end",
    channel: str | None = None,
    level: str = "info",        # 後方互換のため残すが、notification_type が優先
    metadata: dict[str, Any] | None = None,
) -> None:
```

### 5.3 metadata 拡張キー

現行キーに加え、以下を新規に認識する:

| キー | 型 | 説明 | 使用箇所 |
|------|-----|------|---------|
| `repo` | `str` | リポジトリ名 (`owner/repo`) | 既存 |
| `issue` | `int` | Issue 番号 | 既存 |
| `pr` | `int` | PR 番号 | 既存 |
| `pr_url` | `str` | PR の URL | 既存 |
| `phase` | `str` | フェーズ名 | 既存 |
| `error` | `str` | エラーメッセージ | 既存 |
| `notification_type` | `str` | 通知タイプ (後方互換) | 既存 |
| **`issue_title`** | `str` | Issue タイトル | **新規** |
| **`issue_type`** | `str` | Issue タイプ (`bug`, `feature-m` 等) | **新規** |
| **`duration_sec`** | `float` | 経過時間（秒） | **新規** |
| **`cost_usd`** | `float` | Claude API コスト（USD） | **新規** |
| **`files_changed`** | `int` | 変更ファイル数 | **新規** |
| **`commit_count`** | `int` | コミット数 | **新規** |
| **`ci_url`** | `str` | CI結果 URL | **新規** |
| **`stacktrace`** | `str` | スタックトレース（最大5行） | **新規** |

---

## 6. SlackNotifier クラス変更

### 6.1 新メソッド: `notify_rich`

既存の `notify` メソッドは後方互換のため維持し、内部で `notify_rich` に委譲する。

```python
async def notify(
    self,
    message: str,
    *,
    notification_type: str = "phase_end",
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Slack にリッチフォーマットのメッセージを送信する."""
    payload = self._build_rich_payload(
        message,
        notification_type=notification_type,
        channel=channel,
        level=level,
        metadata=metadata,
    )
    await self.send(payload)
```

### 6.2 `_build_rich_payload` 実装方針

```python
def _build_rich_payload(
    self,
    message: str,
    *,
    notification_type: str,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """リッチフォーマットの Block Kit ペイロードを構築する."""
    meta = metadata or {}
    config = _NOTIFICATION_CONFIG.get(notification_type, _NOTIFICATION_CONFIG["phase_end"])
    emoji = config["emoji"]
    title = self._build_header_title(notification_type, meta)

    blocks: list[dict[str, Any]] = [
        # 1. ヘッダーブロック
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True},
        },
        # 2. ディバイダー
        {"type": "divider"},
        # 3. セクション（本文）
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": self._build_body(message, meta)},
        },
    ]

    # 4. コンテキストブロック
    context = self._build_rich_context(meta)
    if context:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context}],
        })

    payload: dict[str, Any] = {"blocks": blocks}
    resolved_channel = channel or self._default_channel
    if resolved_channel:
        payload["channel"] = resolved_channel
    return payload
```

### 6.3 ヘルパーメソッド

```python
@staticmethod
def _build_header_title(notification_type: str, meta: dict[str, Any]) -> str:
    """通知タイプに応じたヘッダータイトルを生成する."""
    phase = meta.get("phase", "")
    phase_label = _PHASE_LABELS.get(phase, phase)

    titles: dict[str, str] = {
        "phase_start": f"{phase_label}フェーズ開始",
        "phase_end": f"{phase_label}フェーズ完了",
        "hearing_question": "ヒアリング質問投稿",
        "plan_posted": "方針投稿",
        "design_pr_created": "設計PR作成",
        "design_revised": "設計書修正",
        "impl_pr_created": "実装PR作成",
        "impl_revised": "実装修正",
        "fix_pr_created": "Bug修正PR作成",
        "split_proposed": "分割提案",
        "split_completed": "分割完了",
        "issue_done": "Issue完了",
        "chain_start": "連鎖処理開始",
        "error": "エラー発生",
        "timeout": "タイムアウト",
        "orchestrator_start": "オーケストレーター起動",
        "orchestrator_error": "オーケストレーターエラー",
        "health_check_fail": "ヘルスチェック失敗",
        "issue_suspended": "Issue中断",
    }
    return titles.get(notification_type, "通知")

def _build_body(self, message: str, meta: dict[str, Any]) -> str:
    """メッセージ本文を構築する（Issue リンク・タイトル付き）."""
    parts: list[str] = []

    # Issue リンク + タイトル
    repo = meta.get("repo")
    issue = meta.get("issue")
    issue_title = meta.get("issue_title")
    if repo and issue is not None:
        issue_url = f"https://github.com/{repo}/issues/{issue}"
        issue_ref = f"<{issue_url}|Issue #{issue}>"
        if issue_title:
            parts.append(f"{issue_ref}: *{issue_title}*")
        else:
            parts.append(issue_ref)

    # メッセージ本文
    parts.append(message)

    # スタックトレース（エラー時）
    stacktrace = meta.get("stacktrace")
    if stacktrace:
        # 最大5行に制限
        lines = stacktrace.strip().split("\n")[:5]
        truncated = "\n".join(lines)
        parts.append(f"```\n{truncated}\n```")

    return "\n".join(parts)

def _build_rich_context(self, meta: dict[str, Any]) -> str | None:
    """リッチコンテキストブロックのテキストを構築する."""
    parts: list[str] = []

    repo = meta.get("repo")
    if repo:
        parts.append(f"📦 `{repo}`")

    issue = meta.get("issue")
    pr = meta.get("pr")
    pr_url = meta.get("pr_url")
    if pr is not None and pr_url:
        parts.append(f"🔗 <{pr_url}|PR #{pr}>")
    elif pr is not None and repo:
        pr_link = f"https://github.com/{repo}/pull/{pr}"
        parts.append(f"🔗 <{pr_link}|PR #{pr}>")

    issue_type = meta.get("issue_type")
    if issue_type:
        parts.append(f"🏷️ `{issue_type}`")

    duration_sec = meta.get("duration_sec")
    if duration_sec is not None:
        minutes = int(duration_sec) // 60
        seconds = int(duration_sec) % 60
        parts.append(f"⏱️ {minutes}分{seconds}秒")

    cost_usd = meta.get("cost_usd")
    if cost_usd is not None:
        parts.append(f"💰 ${cost_usd:.2f}")

    files_changed = meta.get("files_changed")
    if files_changed is not None:
        parts.append(f"📁 {files_changed} files changed")

    commit_count = meta.get("commit_count")
    if commit_count is not None:
        parts.append(f"📝 {commit_count} commits")

    ci_url = meta.get("ci_url")
    if ci_url:
        parts.append(f"🔄 <{ci_url}|CI>")

    if not parts:
        return None
    return " | ".join(parts)
```

### 6.4 フェーズ名ラベルマッピング

```python
_PHASE_LABELS: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "ヒアリング待機",
    "analysis": "Bug分析",
    "plan-brief": "簡易方針",
    "plan-review": "方針レビュー",
    "design": "設計",
    "design-review": "設計レビュー",
    "design-revise": "設計修正",
    "planning": "実装計画",
    "implement": "実装",
    "ci-fix": "CI修正",
    "impl-review": "実装レビュー",
    "impl-revise": "実装修正",
    "fix": "Bug修正",
    "split-proposal": "分割提案",
    "split-execute": "分割実行",
    "done": "完了",
    "suspended": "中断",
}
```

---

## 7. 通知タイミング全体マップ

### 7.1 フェーズ別通知一覧

全フェーズに **開始通知** + **終了（結果）通知** を設置する。

| フェーズ | 開始通知 | 終了通知 | 追加の通知 | 変更種別 |
|---------|---------|---------|-----------|---------|
| `type-detection` | `phase_start` | `phase_end` | — | **新規追加** |
| `hearing` | `phase_start` | `hearing_question` | — | 開始 **新規追加** |
| `analysis` | `phase_start` | `plan_posted` | — | 開始 **新規追加** |
| `plan-brief` | `phase_start` | `plan_posted` | — | 開始 **新規追加** |
| `design` | `phase_start` | `design_pr_created` | — | 開始 **新規追加** |
| `design-revise` | `phase_start` | `design_revised` | — | 開始 **新規追加** |
| `planning` | `phase_start` | `phase_end` | — | **新規追加** |
| `implement` | `phase_start` | `impl_pr_created` | — | 開始 **新規追加** |
| `impl-revise` | `phase_start` | `impl_revised` | — | 開始 **新規追加** |
| `fix` | `phase_start` | `fix_pr_created` | — | 開始 **新規追加** |
| `ci-fix` | `phase_start` | `phase_end` | — | **新規追加** |
| `revise` | `phase_start` | `phase_end` | — | **新規追加** |
| `split (proposal)` | `phase_start` | `split_proposed` | — | 開始 **新規追加** |
| `split (execute)` | `phase_start` | `split_completed` | — | 開始 **新規追加** |
| `done` | `phase_start` | `issue_done` | `chain_start` (連鎖時) | 開始 **新規追加** |
| 全フェーズ共通 | — | — | `timeout`, `error` (異常時) | フォーマット **改善** |

### 7.2 オーケストレーター通知

| タイミング | 通知タイプ | 変更種別 |
|-----------|-----------|---------|
| 起動時 | `orchestrator_start` | フォーマット **改善** |
| イベントルーティングエラー | `orchestrator_error` | フォーマット **改善** |
| Issue中断 | `issue_suspended` | フォーマット **改善** |
| ヘルスチェック失敗 | `health_check_fail` | フォーマット **改善** |

---

## 8. 実装計画

### 8.1 変更対象ファイル

| ファイル | 変更内容 | 影響度 |
|---------|---------|-------|
| `src/ai_agent_orchestrator/notifications/slack.py` | SlackNotifier 全面リファクタリング | **大** |
| `src/ai_agent_orchestrator/models.py` | `NotificationType` Enum 追加 | 小 |
| `src/ai_agent_orchestrator/phases/base.py` | 開始通知追加、エラー通知にスタックトレース追加、NotifierProtocol 拡張 | **中** |
| `src/ai_agent_orchestrator/phases/hearing.py` | notify 呼び出しに notification_type + metadata 追加 | 小 |
| `src/ai_agent_orchestrator/phases/analysis.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/design.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/design_revise.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/planning.py` | 開始+終了通知追加 | 小 |
| `src/ai_agent_orchestrator/phases/implement.py` | notify 呼び出しに notification_type + metadata 追加 | 小 |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/fix.py` | 同上 | 小 |
| `src/ai_agent_orchestrator/phases/ci_fix.py` | 開始+終了通知追加 | 小 |
| `src/ai_agent_orchestrator/phases/revise.py` | 開始+終了通知追加 | 小 |
| `src/ai_agent_orchestrator/phases/type_detection.py` | 開始+終了通知追加 | 小 |
| `src/ai_agent_orchestrator/phases/split.py` | notify 呼び出しに notification_type + metadata 追加 | 小 |
| `src/ai_agent_orchestrator/phases/done.py` | notify 呼び出しに notification_type + metadata 追加 | 小 |
| `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | 4箇所の notify 呼び出し改善 | **中** |
| `tests/unit/test_slack.py` | テスト全面更新 + 新規テスト追加 | **大** |
| `docs/specs/slack.md` | 仕様書更新 | 中 |

### 8.2 実装ステップ

#### Step 1: SlackNotifier リファクタリング（核心部分）

1. `models.py` に `NotificationType` Enum を追加
2. `slack.py` にリッチフォーマット構築ロジックを実装
   - `_NOTIFICATION_CONFIG` マッピング追加
   - `_PHASE_LABELS` マッピング追加
   - `_build_rich_payload()` 新規作成
   - `_build_header_title()` 新規作成
   - `_build_body()` 新規作成
   - `_build_rich_context()` 新規作成（既存 `_build_context_text` を置換）
3. `notify()` メソッドに `notification_type` パラメータ追加（後方互換）
4. テスト更新: `test_slack.py`

#### Step 2: base.py のフェーズ開始通知 + エラー通知改善

1. `execute()` テンプレートメソッド内にフェーズ開始通知を追加
2. `_handle_error()` にスタックトレース取得ロジック追加
3. `_handle_timeout()` に `notification_type="timeout"` 追加
4. `NotifierProtocol` に `notification_type` パラメータ追加

#### Step 3: 各フェーズファイルの notify 呼び出し更新

全13箇所の `notify()` 呼び出しに以下を追加:
- `notification_type` パラメータ
- `issue_title`, `issue_type`, `duration_sec`, `cost_usd` 等の metadata 拡充

#### Step 4: オーケストレーターの notify 呼び出し更新

4箇所の `notify()` 呼び出しを新フォーマットに対応。

#### Step 5: 仕様書 + テスト仕上げ

- `docs/specs/slack.md` を新仕様に更新
- 全テストケースの追加・更新

---

## 9. base.py の execute() 変更詳細

フェーズ開始通知を `execute()` テンプレートメソッドに一元的に追加する。
これにより、各フェーズの個別実装で開始通知を書く必要がなくなる。

```python
async def execute(self, request: TaskRequest) -> None:
    """フェーズを実行する (テンプレートメソッド)."""
    try:
        # --- 開始通知（新規追加）---
        await self._notify_phase_start(request)

        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        prompt = await self.build_prompt(request)
        result = await self.run_agent(request, prompt)
        await self.process_result(request, result)

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

async def _notify_phase_start(self, request: TaskRequest) -> None:
    """フェーズ開始通知を送信する."""
    meta: dict[str, Any] = {
        "issue": request.issue_number,
        "phase": str(request.phase),
    }
    # Issue タイトル・タイプを取得（取得失敗時は省略）
    try:
        repo_str = getattr(request.repo, "full_name", str(request.repo))
        meta["repo"] = repo_str
        issue_type = self._sm.get_issue_type(request.issue_number)
        if issue_type:
            meta["issue_type"] = issue_type
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        meta["issue_title"] = issue.title
    except Exception:
        pass  # best-effort

    await self._notifier.notify(
        f"{str(request.phase)} フェーズを開始します",
        notification_type="phase_start",
        metadata=meta,
    )
```

### 9.1 エラー通知改善

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: スタックトレース付き通知."""
    import traceback

    await self._sm.transition(request.issue_number, "suspended")
    client = await self._get_client(request.repo)
    try:
        await client.replace_phase_label(
            request.repo, request.issue_number, "phase:suspended"
        )
    except Exception:
        logger.warning(...)
    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    # スタックトレース取得（最大5行）
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    tb_text = "".join(tb_lines)
    tb_truncated = "\n".join(tb_text.strip().split("\n")[-5:])

    await self._notifier.notify(
        f"Issue #{request.issue_number} でエラーが発生しました",
        notification_type="error",
        level="error",
        metadata={
            "issue": request.issue_number,
            "phase": str(request.phase),
            "error": str(error),
            "stacktrace": tb_truncated,
        },
    )
```

---

## 10. 後方互換性

### 10.1 方針

- `notify()` の既存シグネチャ (`message`, `channel`, `level`, `metadata`) はそのまま動作する
- `notification_type` を渡さない場合は `"phase_end"` をデフォルトとし、リッチフォーマットで表示
- 既存の `level` パラメータは `notification_type` が指定された場合はマッピングから自動決定されるが、明示的な `level` 指定で上書き可能

### 10.2 Protocol 更新

`base.py` と `orchestrator.py` の `NotifierProtocol` に `notification_type` を追加:

```python
class NotifierProtocol:
    async def notify(
        self,
        message: str,
        *,
        notification_type: str = "phase_end",
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None: ...
```

---

## 11. テスト計画

> **目標: カバレッジ 100%** — 全メソッド・全分岐・全境界値を網羅する。

### 11.1 カバレッジ戦略

| 観点 | 方針 |
|------|------|
| ライン カバレッジ | 全メソッドの全行を少なくとも1つのテストで通過させる |
| ブランチ カバレッジ | 各 `if/else`・`try/except`・三項演算子の真偽両方を検証する |
| 境界値 | 空文字列・`None`・0・負数・超長文字列等のエッジケースを網羅 |
| パラメトリック テスト | `@pytest.mark.parametrize` で全 19 通知タイプ × 絵文字・タイトルを一括検証 |
| 計測 | CI で `pytest --cov=src/ai_agent_orchestrator/notifications --cov-report=term-missing --cov-fail-under=100` を実行し、100% 未満で失敗させる |

### 11.2 テストケース一覧

#### A. `_build_rich_payload` — ペイロード構造テスト

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-11 | `test_notify_rich_format_has_header` | ヘッダーブロック（type="header"）が含まれること |
| TC-SL-12 | `test_notify_rich_format_has_divider` | ディバイダー（type="divider"）が含まれること |
| TC-SL-13 | `test_notify_rich_format_has_section` | セクション（type="section", mrkdwn）が含まれること |
| TC-SL-14 | `test_notify_rich_format_has_context` | コンテキストブロック（type="context"）が含まれること |
| TC-SL-14b | `test_notify_rich_format_no_context_when_empty_meta` | metadata が空の場合コンテキストブロックが **省略** されること |
| TC-SL-14c | `test_payload_includes_channel_when_specified` | `channel` 指定時にペイロードに `channel` キーが含まれること |
| TC-SL-14d | `test_payload_uses_default_channel_when_none` | `channel=None` 時にデフォルトチャンネルが使われること |
| TC-SL-14e | `test_payload_no_channel_when_no_default` | デフォルトチャンネルも未設定の場合 `channel` キーが **存在しない** こと |

#### B. 通知タイプ — 絵文字・タイトル・レベルマッピング

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-15 | `test_notification_type_emoji_mapping[parametrize: 全19タイプ]` | 各通知タイプの絵文字がヘッダーに正しく反映されること |
| TC-SL-16 | `test_header_title_per_notification_type[parametrize: 全19タイプ]` | 各通知タイプのヘッダータイトルが正しいこと |
| TC-SL-16b | `test_header_title_unknown_type_fallback` | 未知の `notification_type` が渡された場合 `"通知"` にフォールバックすること |
| TC-SL-16c | `test_notification_config_unknown_type_fallback` | 未知の `notification_type` 時に `phase_end` の設定にフォールバックすること |
| TC-SL-16d | `test_level_auto_determined_by_notification_type` | `notification_type` からレベル（info/error/critical）が自動決定されること |
| TC-SL-16e | `test_level_explicit_override` | 明示的 `level` 指定が `notification_type` のデフォルトを上書きすること |

#### C. `_build_body` — 本文構築テスト

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-17 | `test_body_includes_issue_link_and_title` | `repo` + `issue` + `issue_title` 指定時にリンクとタイトルが含まれること |
| TC-SL-17b | `test_body_issue_link_without_title` | `issue_title` 省略時にリンクのみ（タイトルなし）が含まれること |
| TC-SL-17c | `test_body_no_issue_when_repo_missing` | `repo` が無い場合 Issue リンクが生成されないこと |
| TC-SL-17d | `test_body_no_issue_when_issue_none` | `issue` が `None` の場合 Issue リンクが生成されないこと |
| TC-SL-17e | `test_body_message_always_included` | metadata の有無にかかわらずメッセージ本文が常に含まれること |

#### D. `_build_body` — スタックトレース

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-24 | `test_error_notification_includes_stacktrace` | `stacktrace` 指定時にコードブロック（``` ```）付きで含まれること |
| TC-SL-25 | `test_stacktrace_truncated_to_5_lines` | 6行以上のスタックトレースが5行に切り詰められること |
| TC-SL-25b | `test_stacktrace_under_5_lines_not_truncated` | 5行以下のスタックトレースがそのまま出力されること |
| TC-SL-25c | `test_stacktrace_empty_string_ignored` | `stacktrace` が空文字列の場合にコードブロックが生成されないこと |
| TC-SL-25d | `test_stacktrace_whitespace_only_ignored` | `stacktrace` がスペース/改行のみの場合に空のコードブロックが生成されないこと |

#### E. `_build_rich_context` — コンテキストブロック

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-18 | `test_context_includes_duration` | `duration_sec` 指定時に `⏱️ X分Y秒` 形式で含まれること |
| TC-SL-18b | `test_context_duration_zero` | `duration_sec=0` 時に `⏱️ 0分0秒` と表示されること |
| TC-SL-18c | `test_context_duration_large_value` | `duration_sec=3661` 時に `⏱️ 61分1秒` と表示されること（時間単位への変換はしない） |
| TC-SL-19 | `test_context_includes_cost` | `cost_usd` 指定時に `💰 $X.XX` 形式で含まれること |
| TC-SL-19b | `test_context_cost_zero` | `cost_usd=0` 時に `💰 $0.00` と表示されること |
| TC-SL-20 | `test_context_includes_files_changed` | `files_changed` 指定時に `📁 N files changed` で含まれること |
| TC-SL-20b | `test_context_files_changed_zero` | `files_changed=0` 時に `📁 0 files changed` と表示されること |
| TC-SL-21 | `test_context_includes_issue_type` | `issue_type` 指定時に `🏷️` 付きで含まれること |
| TC-SL-22 | `test_context_includes_pr_link_with_url` | `pr` + `pr_url` 指定時に `pr_url` を使ったリンクが含まれること |
| TC-SL-22b | `test_context_includes_pr_link_without_url` | `pr` + `repo` 指定（`pr_url` なし）時に自動生成 URL のリンクが含まれること |
| TC-SL-22c | `test_context_pr_without_repo_or_url_omitted` | `pr` のみ（`repo`/`pr_url` なし）の場合 PR リンクが省略されること |
| TC-SL-23 | `test_context_includes_ci_url` | `ci_url` 指定時に `🔄 CI` リンクが含まれること |
| TC-SL-23b | `test_context_includes_commit_count` | `commit_count` 指定時に `📝 N commits` で含まれること |
| TC-SL-23c | `test_context_parts_joined_with_pipe` | 複数項目が ` \| ` 区切りで結合されること |
| TC-SL-23d | `test_context_returns_none_when_no_parts` | metadata にコンテキスト関連キーが無い場合 `None` を返すこと |

#### F. `_build_header_title` — フェーズラベル

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-28 | `test_phase_labels_mapping[parametrize: 全18フェーズ]` | 全フェーズ名が正しい日本語ラベルに変換されること |
| TC-SL-28b | `test_phase_labels_unknown_phase_passthrough` | 未知のフェーズ名がそのままラベルとして使われること |

#### G. 後方互換性

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-26 | `test_backward_compat_without_notification_type` | `notification_type` 省略時にデフォルト `phase_end` として動作すること |
| TC-SL-26b | `test_backward_compat_message_only` | `notify(message)` のみの呼び出しがエラーなく動作すること |
| TC-SL-26c | `test_backward_compat_with_legacy_metadata` | 既存の metadata キー（`repo`, `issue`, `phase` 等）のみで正しく動作すること |

#### H. `notify` メソッド統合テスト

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-30 | `test_notify_calls_send_with_built_payload` | `notify()` が `_build_rich_payload()` → `send()` の順で呼ばれること |
| TC-SL-31 | `test_notify_send_failure_does_not_raise` | `send()` が例外を投げても `notify()` は例外を伝搬しないこと（best-effort） |

#### I. `base.py` フェーズ開始通知・エラー処理

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-27 | `test_phase_start_notification_in_execute` | `execute()` でフェーズ開始通知が送信されること |
| TC-SL-27b | `test_phase_start_includes_issue_title` | 開始通知の metadata に `issue_title` が含まれること |
| TC-SL-27c | `test_phase_start_issue_title_fetch_failure_ignored` | Issue タイトル取得失敗時にも開始通知は送信されること（best-effort） |
| TC-SL-27d | `test_phase_start_includes_issue_type` | 開始通知の metadata に `issue_type` が含まれること |
| TC-SL-32 | `test_handle_error_sends_error_notification_type` | `_handle_error()` が `notification_type="error"` で通知すること |
| TC-SL-33 | `test_handle_error_includes_stacktrace` | `_handle_error()` の通知にスタックトレースが含まれること |
| TC-SL-33b | `test_handle_error_stacktrace_last_5_lines` | スタックトレースの **末尾5行** が使用されること |
| TC-SL-34 | `test_handle_timeout_sends_timeout_notification_type` | `_handle_timeout()` が `notification_type="timeout"` で通知すること |

#### J. `NotificationType` Enum

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-35 | `test_notification_type_enum_values` | 全 Enum メンバーの値が `_NOTIFICATION_CONFIG` のキーと一致すること |
| TC-SL-36 | `test_notification_type_is_str_enum` | `NotificationType` が `StrEnum` であり文字列比較が可能なこと |

#### K. 各フェーズ notify 呼び出し更新

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-40 | `test_hearing_phase_sends_hearing_question_type` | hearing フェーズが `hearing_question` タイプで通知すること |
| TC-SL-41 | `test_analysis_phase_sends_plan_posted_type` | analysis フェーズが `plan_posted` タイプで通知すること |
| TC-SL-42 | `test_design_phase_sends_design_pr_created_type` | design フェーズが `design_pr_created` タイプで通知すること |
| TC-SL-43 | `test_implement_phase_sends_impl_pr_created_type` | implement フェーズが `impl_pr_created` タイプで通知すること |
| TC-SL-44 | `test_fix_phase_sends_fix_pr_created_type` | fix フェーズが `fix_pr_created` タイプで通知すること |
| TC-SL-45 | `test_done_phase_sends_issue_done_type` | done フェーズが `issue_done` タイプで通知すること |
| TC-SL-46 | `test_done_phase_chain_sends_chain_start_type` | done フェーズ（連鎖あり）が `chain_start` タイプで通知すること |
| TC-SL-47 | `test_split_proposal_sends_split_proposed_type` | split(proposal) フェーズが `split_proposed` タイプで通知すること |
| TC-SL-48 | `test_split_execute_sends_split_completed_type` | split(execute) フェーズが `split_completed` タイプで通知すること |
| TC-SL-49 | `test_design_revise_sends_design_revised_type` | design-revise フェーズが `design_revised` タイプで通知すること |
| TC-SL-50 | `test_impl_revise_sends_impl_revised_type` | impl-revise フェーズが `impl_revised` タイプで通知すること |
| TC-SL-51 | `test_each_phase_includes_duration_and_cost_in_metadata` | 全フェーズの終了通知 metadata に `duration_sec`, `cost_usd` が含まれること |

#### L. オーケストレーター通知

| ID | テスト | 検証内容 |
|----|-------|---------|
| TC-SL-55 | `test_orchestrator_start_notification` | 起動時に `orchestrator_start` タイプで通知すること |
| TC-SL-56 | `test_orchestrator_error_notification` | ルーティングエラー時に `orchestrator_error` タイプで通知すること |
| TC-SL-57 | `test_issue_suspended_notification` | Issue 中断時に `issue_suspended` タイプで通知すること |
| TC-SL-58 | `test_health_check_fail_notification` | ヘルスチェック失敗時に `health_check_fail` タイプで通知すること |

### 11.3 既存テストの更新

TC-SL-01〜10 は新フォーマット（ヘッダー + ディバイダー + セクション構成）に合わせてアサーションを更新する。

### 11.4 カバレッジ計測・CI 設定

```yaml
# CI での実行コマンド
pytest tests/unit/test_slack.py tests/unit/test_base_phase.py \
  --cov=src/ai_agent_orchestrator/notifications \
  --cov=src/ai_agent_orchestrator/phases/base \
  --cov-branch \
  --cov-report=term-missing \
  --cov-fail-under=100
```

- `--cov-branch`: ブランチカバレッジも100%を目標とする
- `--cov-fail-under=100`: 100%未満でCIを失敗させる
- カバレッジ対象は `notifications/slack.py` および `phases/base.py` の変更箇所

---

## 12. 非機能要件

| 項目 | 要件 |
|------|------|
| パフォーマンス | 通知送信は `asyncio.create_task()` でバックグラウンド実行し、フェーズ処理をブロックしない |
| 耐障害性 | 通知送信失敗時は例外を発生させない（best-effort、既存方針を継続） |
| ペイロードサイズ | Slack Block Kit の上限（50ブロック / 3000文字 per text）を超えないようスタックトレースを5行に制限 |
| テスト | カバレッジ100%を目標とし、全メソッド・全分岐・全境界値を網羅する単体テストを実施。CI で `--cov-fail-under=100` を設定 |
