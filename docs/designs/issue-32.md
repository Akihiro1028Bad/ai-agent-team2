# Issue #32: Slack メッセージ改善 設計書

## 1. 概要

Slack 通知の **タイミング・フォーマット・内容** を全面的にアップグレードする。
現状は「フェーズ完了後のみ」「シンプルテキスト+コンテキスト」「最低限の情報」に留まっており、
ユーザーが処理状況を把握しにくい。本改善により、リッチで情報密度の高い通知体験を実現する。

## 2. 現状分析

### 2.1 現在の通知ポイント（18箇所）

| カテゴリ | ファイル | 通知内容 |
|---------|---------|---------|
| フェーズ完了 | `hearing.py` | 質問投稿完了 |
| フェーズ完了 | `design.py` | 設計PR作成 |
| フェーズ完了 | `implement.py` | 実装PR作成 |
| フェーズ完了 | `done.py` | Issue完了 / 子Issue連鎖開始 |
| フェーズ完了 | `design_revise.py` | 設計修正完了 |
| フェーズ完了 | `impl_revise.py` | 実装修正完了 |
| フェーズ完了 | `plan_brief.py` | 実装方針投稿 |
| フェーズ完了 | `analysis.py` | 修正方針投稿 |
| フェーズ完了 | `fix.py` | 修正PR作成 |
| フェーズ完了 | `split.py` | 分割提案 / 分割完了 |
| エラー | `base.py` | タイムアウト / エラー |
| システム | `orchestrator.py` | 起動 / イベントルーティングエラー / タスク失敗 / ヘルスチェック |

### 2.2 現在の課題

| 観点 | 現状 | 問題点 |
|------|------|--------|
| **タイミング** | フェーズ完了後のみ | フェーズ開始通知がない。中間報告がない。完了サマリーがない |
| **フォーマット** | section + context の2ブロック | 通知タイプ別絵文字なし。ボタンなし。ヘッダーなし。色分けなし |
| **内容** | 最低限のテキスト | repo 情報欠落多数。PR URL 欠落。所要時間なし。進捗表示なし |

## 3. 要件（ヒアリング結果）

### 3.1 タイミング

| 要件 | 説明 |
|------|------|
| **フェーズ開始通知** | 各フェーズ開始時に「〜を開始しました」を通知 |
| **承認待ち通知** | 既存維持 + 改善 |
| **フェーズ完了通知** | 既存維持 + 改善 |
| **中間報告** | フェーズ内ステップベースの概算進捗（例: ステップ 2/3） |
| **Issue完了サマリー** | 全フェーズの統計情報を含む完了レポート |

### 3.2 フォーマット

| 要件 | 説明 |
|------|------|
| **通知タイプ別絵文字** | 🗨️ヒアリング / ✏️設計PR / 🚀実装PR / 📋方針 / ❌エラー / ⏳タイムアウト / ✅完了 |
| **PRリンクのボタン化** | Block Kit `actions` ブロックで「PRを見る」ボタン追加 |
| **ヘッダーブロック** | Issue番号+タイトルを `header` ブロックで分離表示 |
| **divider** | ブロック間を視覚的に区切る |
| **色付きサイドバー** | `attachments` の `color` フィールド（成功=緑、エラー=赤、進行中=青） |

### 3.3 内容

| 要件 | 説明 |
|------|------|
| **リポジトリ名** | 全通知に `repo` を含める |
| **Issueタイトル** | 番号だけでなくタイトルも表示 |
| **PR URL** | クリック可能リンクとして全PR通知に含める |
| **進捗表示** | `[hearing] → [design] → **[implement]** → [done]` 形式 |
| **所要時間** | フェーズごとの経過時間を表示 |
| **変更ファイル一覧** | PR作成通知時にファイルリストを含める |
| **エラー要約** | エラー種類・発生箇所・原因のテンプレートベース要約 + AI調査結果 |
| **次アクション指示** | 具体的なURLリンク付きの明確な指示 |

### 3.4 完了サマリーの内容

- フェーズごとの所要時間
- 総所要時間
- 総コスト（USD）
- 変更ファイル数・行数
- PR URL一覧（設計PR + 実装PR）

### 3.5 スコープ外

- 通知のまとめ送信（バッチ化）
- 通知レベルのフィルタリング
- チャンネル振り分けルール

## 4. 設計

### 4.1 アーキテクチャ概要

```
SlackNotifier (通知基盤)
├── NotificationType enum        # 通知タイプ定義
├── NotificationTemplate         # テンプレートレジストリ
├── BlockKitBuilder              # ペイロード構築
├── ProgressTracker              # 進捗・所要時間追跡
└── ErrorSummarizer              # エラー要約生成
```

### 4.2 新規 Enum: `NotificationType`

**ファイル**: `src/ai_agent_orchestrator/models.py`

```python
class NotificationType(StrEnum):
    """Slack通知タイプ."""

    # フェーズ開始
    PHASE_START = "phase_start"

    # フェーズ完了系
    HEARING_QUESTION = "hearing_question"
    DESIGN_PR_CREATED = "design_pr_created"
    IMPL_PR_CREATED = "impl_pr_created"
    FIX_PR_CREATED = "fix_pr_created"
    PLAN_POSTED = "plan_posted"
    DESIGN_REVISED = "design_revised"
    IMPL_REVISED = "impl_revised"
    SPLIT_PROPOSED = "split_proposed"
    SPLIT_EXECUTED = "split_executed"

    # 承認待ち
    APPROVAL_NEEDED = "approval_needed"

    # 中間報告
    PROGRESS_UPDATE = "progress_update"

    # 完了
    DONE = "done"
    DONE_SUMMARY = "done_summary"

    # エラー系
    ERROR = "error"
    TIMEOUT = "timeout"

    # システム
    SYSTEM_START = "system_start"
    SYSTEM_ERROR = "system_error"
    HEALTH_CHECK = "health_check"
```

### 4.3 通知テンプレートレジストリ

**ファイル**: `src/ai_agent_orchestrator/notifications/templates.py`（新規）

通知タイプごとの絵文字・色・メッセージテンプレートを管理する。

```python
@dataclass(frozen=True)
class NotificationTemplate:
    """通知テンプレート定義."""

    emoji: str
    color: str  # Slack attachments color (#hex)
    default_message: str
    show_progress_bar: bool = False
    show_actions: bool = False  # 「PRを見る」ボタン等
    show_next_action: bool = False

TEMPLATES: dict[NotificationType, NotificationTemplate] = {
    NotificationType.PHASE_START: NotificationTemplate(
        emoji="🚀",
        color="#2196F3",  # 青
        default_message="{phase_label}を開始しました",
        show_progress_bar=True,
    ),
    NotificationType.HEARING_QUESTION: NotificationTemplate(
        emoji="🗨️",
        color="#FF9800",  # オレンジ
        default_message="質問を投稿しました。回答をお願いします",
        show_next_action=True,
    ),
    NotificationType.DESIGN_PR_CREATED: NotificationTemplate(
        emoji="✏️",
        color="#4CAF50",  # 緑
        default_message="設計PRを作成しました。レビューをお願いします",
        show_actions=True,
        show_next_action=True,
    ),
    NotificationType.IMPL_PR_CREATED: NotificationTemplate(
        emoji="🚀",
        color="#4CAF50",  # 緑
        default_message="実装PRを作成しました",
        show_actions=True,
        show_next_action=True,
    ),
    NotificationType.FIX_PR_CREATED: NotificationTemplate(
        emoji="🔧",
        color="#4CAF50",  # 緑
        default_message="修正PRを作成しました。レビュー待ちです",
        show_actions=True,
        show_next_action=True,
    ),
    NotificationType.PLAN_POSTED: NotificationTemplate(
        emoji="📋",
        color="#FF9800",  # オレンジ
        default_message="方針を投稿しました。承認をお願いします",
        show_next_action=True,
    ),
    NotificationType.DESIGN_REVISED: NotificationTemplate(
        emoji="📝",
        color="#2196F3",  # 青
        default_message="設計書を修正しました",
        show_actions=True,
    ),
    NotificationType.IMPL_REVISED: NotificationTemplate(
        emoji="📝",
        color="#2196F3",  # 青
        default_message="実装を修正しました",
        show_actions=True,
    ),
    NotificationType.SPLIT_PROPOSED: NotificationTemplate(
        emoji="✂️",
        color="#FF9800",  # オレンジ
        default_message="分割を提案しました。判断をお願いします",
        show_next_action=True,
    ),
    NotificationType.SPLIT_EXECUTED: NotificationTemplate(
        emoji="✅",
        color="#4CAF50",  # 緑
        default_message="分割が完了しました",
    ),
    NotificationType.PROGRESS_UPDATE: NotificationTemplate(
        emoji="⏳",
        color="#2196F3",  # 青
        default_message="{phase_label}実行中… ステップ {step}/{total_steps}",
        show_progress_bar=True,
    ),
    NotificationType.DONE: NotificationTemplate(
        emoji="✅",
        color="#4CAF50",  # 緑
        default_message="完了しました",
    ),
    NotificationType.DONE_SUMMARY: NotificationTemplate(
        emoji="📊",
        color="#4CAF50",  # 緑
        default_message="全フェーズ完了レポート",
    ),
    NotificationType.ERROR: NotificationTemplate(
        emoji="❌",
        color="#F44336",  # 赤
        default_message="エラーが発生しました",
    ),
    NotificationType.TIMEOUT: NotificationTemplate(
        emoji="⏳",
        color="#F44336",  # 赤
        default_message="タイムアウトしました",
    ),
    NotificationType.SYSTEM_START: NotificationTemplate(
        emoji="🤖",
        color="#2196F3",  # 青
        default_message="Orchestrator が起動しました",
    ),
    NotificationType.SYSTEM_ERROR: NotificationTemplate(
        emoji="🚨",
        color="#F44336",  # 赤
        default_message="システムエラーが発生しました",
    ),
    NotificationType.HEALTH_CHECK: NotificationTemplate(
        emoji="🏥",
        color="#F44336",  # 赤
        default_message="ヘルスチェック異常",
    ),
}
```

### 4.4 フェーズラベルマッピング

```python
PHASE_LABELS: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "回答待ち",
    "analysis": "原因分析",
    "plan-brief": "簡易方針策定",
    "plan-review": "方針レビュー",
    "design": "設計",
    "design-review": "設計レビュー",
    "design-revise": "設計修正",
    "planning": "実装計画",
    "implement": "実装",
    "fix": "Bug修正",
    "ci-fix": "CI修正",
    "impl-review": "実装レビュー",
    "impl-revise": "実装修正",
    "split-proposal": "分割提案",
    "split-execute": "分割実行",
    "done": "完了",
}
```

### 4.5 進捗トラッカー

**ファイル**: `src/ai_agent_orchestrator/notifications/progress.py`（新規）

フェーズの進捗・所要時間を追跡し、中間報告と完了サマリーのデータを提供する。

```python
@dataclass
class PhaseProgress:
    """フェーズの進捗状態."""

    phase: str
    started_at: float  # time.monotonic()
    steps: list[str]  # ステップ名一覧
    current_step: int = 0
    completed_at: float | None = None
    cost_usd: float = 0.0


class ProgressTracker:
    """Issue単位の進捗追跡."""

    def __init__(self) -> None:
        self._issues: dict[int, dict[str, PhaseProgress]] = {}

    def start_phase(self, issue_number: int, phase: str, steps: list[str]) -> None:
        """フェーズ開始を記録."""
        ...

    def update_step(self, issue_number: int, phase: str, step: int) -> None:
        """ステップ進捗を更新."""
        ...

    def complete_phase(
        self, issue_number: int, phase: str, cost_usd: float = 0.0
    ) -> PhaseProgress:
        """フェーズ完了を記録し、結果を返す."""
        ...

    def get_progress(self, issue_number: int, phase: str) -> PhaseProgress | None:
        """現在の進捗を取得."""
        ...

    def get_summary(self, issue_number: int) -> dict[str, Any]:
        """Issue全体のサマリーを生成."""
        # Returns: {
        #   "phases": [{"phase": "hearing", "duration_sec": 120, "cost_usd": 0.5}, ...],
        #   "total_duration_sec": 1200,
        #   "total_cost_usd": 5.0,
        # }
        ...

    def cleanup(self, issue_number: int) -> None:
        """Issue の追跡データを削除."""
        ...
```

#### フェーズ別ステップ定義

```python
PHASE_STEPS: dict[str, list[str]] = {
    "type-detection": ["Issue分析", "タイプ判定"],
    "hearing": ["Issue読み込み", "質問生成", "コメント投稿"],
    "analysis": ["コード調査", "原因分析", "方針策定", "コメント投稿"],
    "plan-brief": ["Issue分析", "方針策定", "コメント投稿"],
    "design": ["要件整理", "設計書作成", "PR作成"],
    "design-revise": ["レビュー確認", "設計修正", "コミット"],
    "planning": ["設計書読み込み", "タスク分解", "計画策定"],
    "implement": ["コード生成", "テスト作成", "テスト実行", "PR作成"],
    "fix": ["コード修正", "テスト実行", "PR作成"],
    "ci-fix": ["CI結果分析", "修正", "テスト再実行"],
    "impl-revise": ["レビュー確認", "コード修正", "テスト実行", "コミット"],
    "split-proposal": ["Issue分析", "分割案作成", "コメント投稿"],
    "split-execute": ["子Issue作成", "ラベル設定"],
}
```

### 4.6 エラー要約生成

**ファイル**: `src/ai_agent_orchestrator/notifications/error_summarizer.py`（新規）

```python
@dataclass(frozen=True)
class ErrorSummary:
    """エラー要約."""

    error_type: str       # 例: "TimeoutError"
    location: str         # 例: "implement フェーズ"
    cause: str            # 例: "60分のタイムアウト制限を超過"
    suggestion: str       # 例: "タイムアウト値の引き上げ、またはIssueの分割を検討"
    traceback_tail: str   # 最後の3行


class ErrorSummarizer:
    """エラーからSlack通知向けの要約を生成する."""

    # エラータイプ別のテンプレート
    _TEMPLATES: dict[str, dict[str, str]] = {
        "TimeoutError": {
            "cause": "{phase}フェーズが{timeout}分のタイムアウト制限を超過しました",
            "suggestion": "タイムアウト値の引き上げ、またはIssueの分割を検討してください",
        },
        "RuntimeError": {
            "cause": "実行時エラーが発生しました: {message}",
            "suggestion": "エラー内容を確認し、再実行またはIssueで報告してください",
        },
        "AuthError": {
            "cause": "認証エラー: トークンが無効または期限切れです",
            "suggestion": "トークンを再設定してください",
        },
        "GitConflictError": {
            "cause": "Gitコンフリクトが発生しました",
            "suggestion": "手動でコンフリクトを解消してください",
        },
    }
    _DEFAULT = {
        "cause": "予期しないエラーが発生しました: {message}",
        "suggestion": "ログを確認し、必要に応じてIssueで報告してください",
    }

    @classmethod
    def summarize(
        cls,
        error: Exception,
        *,
        phase: str = "",
        issue_number: int | None = None,
    ) -> ErrorSummary:
        """エラーを要約する."""
        ...

    @classmethod
    def format_for_slack(cls, summary: ErrorSummary) -> str:
        """Slack mrkdwn 形式にフォーマットする."""
        # Returns:
        # *エラー種別*: TimeoutError
        # *発生箇所*: implement フェーズ (Issue #42)
        # *原因*: 60分のタイムアウト制限を超過
        # *対応案*: タイムアウト値の引き上げ、またはIssueの分割を検討
        ...
```

### 4.7 Block Kit ペイロード構築の刷新

**ファイル**: `src/ai_agent_orchestrator/notifications/slack.py`（改修）

#### 4.7.1 `notify` メソッドのシグネチャ拡張

```python
async def notify(
    self,
    message: str,
    *,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
    notification_type: NotificationType | None = None,  # 追加
) -> None:
```

**後方互換性**: `notification_type=None` の場合は従来の `level` ベース動作を維持する。

#### 4.7.2 新しいペイロード構造

`notification_type` が指定された場合の構造:

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
                        "text": "✏️ Issue #42: Slackメッセージの改善"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "設計PRを作成しました。レビューをお願いします"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*進捗*: `hearing` → `design` → *`implement`* → `done`"
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*リポジトリ*\n`org/repo`"},
                        {"type": "mrkdwn", "text": "*フェーズ*\n設計"},
                        {"type": "mrkdwn", "text": "*所要時間*\n3分20秒"},
                        {"type": "mrkdwn", "text": "*変更ファイル*\n5ファイル"}
                    ]
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📋 PRを見る"},
                            "url": "https://github.com/org/repo/pull/10",
                            "style": "primary"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📝 Issueを見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        }
                    ]
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "🤖 AI Agent | 次のアクション: PRをレビューしてapproveしてください"
                        }
                    ]
                }
            ]
        }
    ]
}
```

#### 4.7.3 完了サマリーのペイロード構造

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
                        "text": "📊 Issue #42: Slackメッセージの改善 — 完了レポート"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "全フェーズが正常に完了しました"
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*フェーズ別実績*\n| フェーズ | 所要時間 | コスト |\n|---|---|---|\n| ヒアリング | 2分10秒 | $0.50 |\n| 設計 | 5分30秒 | $2.10 |\n| 実装 | 15分00秒 | $8.50 |"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*総所要時間*\n22分40秒"},
                        {"type": "mrkdwn", "text": "*総コスト*\n$11.10"},
                        {"type": "mrkdwn", "text": "*変更ファイル数*\n12ファイル (+340/-120)"},
                        {"type": "mrkdwn", "text": "*PR一覧*\n<url|設計PR #10> / <url|実装PR #15>"}
                    ]
                },
                {
                    "type": "divider"
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📋 設計PRを見る"},
                            "url": "https://github.com/org/repo/pull/10"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🚀 実装PRを見る"},
                            "url": "https://github.com/org/repo/pull/15",
                            "style": "primary"
                        }
                    ]
                }
            ]
        }
    ]
}
```

#### 4.7.4 エラー通知のペイロード構造

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
                        "text": "❌ Issue #42: Slackメッセージの改善 — エラー"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*エラー種別*: `TimeoutError`\n*発生箇所*: implement フェーズ\n*原因*: 60分のタイムアウト制限を超過\n*対応案*: タイムアウト値の引き上げ、またはIssueの分割を検討"
                    }
                },
                {
                    "type": "divider"
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📝 Issueを見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        }
                    ]
                }
            ]
        }
    ]
}
```

### 4.8 進捗バー生成

```python
def build_progress_bar(
    current_phase: str,
    issue_type: str,
) -> str:
    """現在のフェーズに基づく進捗バーを mrkdwn で返す.

    例: `hearing` → `design` → *`implement`* → `done`
    """
```

ワークフロータイプ別のフェーズ順序を定義し、現在のフェーズを太字にする:

```python
WORKFLOW_PHASES: dict[str, list[str]] = {
    "bug": ["analysis", "plan-review", "fix", "impl-review", "done"],
    "feature-s": ["plan-brief", "plan-review", "implement", "impl-review", "done"],
    "feature-m": ["hearing", "design", "design-review", "planning", "implement", "impl-review", "done"],
    "feature-l": ["hearing", "design", "split-proposal", "split-execute", "done"],
}
```

### 4.9 変更ファイル一覧の取得

PR作成通知時に `git diff --stat` をworktreeで実行して変更ファイル情報を取得する（ローカル完結、API呼び出し不要）。

```python
async def get_diff_stats(worktree_path: str, base_branch: str = "main") -> dict[str, Any]:
    """worktreeのgit diffから変更統計を取得する.

    Returns:
        {
            "files": ["src/foo.py", "tests/test_foo.py"],
            "file_count": 2,
            "insertions": 150,
            "deletions": 30,
        }
    """
```

### 4.10 `notify` メソッドの metadata 拡張

現在の `metadata` キーに加え、以下のキーを新たに認識する:

| キー | 型 | 説明 |
|------|-----|------|
| `notification_type` | `str` | 通知タイプ（既存だが未活用） |
| `issue_title` | `str` | Issue タイトル |
| `issue_type` | `str` | Issue タイプ（bug/feature-s/m/l） |
| `duration_sec` | `float` | 所要時間（秒） |
| `step` | `int` | 現在のステップ番号 |
| `total_steps` | `int` | 総ステップ数 |
| `files_changed` | `list[str]` | 変更ファイル一覧 |
| `file_count` | `int` | 変更ファイル数 |
| `insertions` | `int` | 追加行数 |
| `deletions` | `int` | 削除行数 |
| `error_summary` | `ErrorSummary` | エラー要約 |
| `cost_usd` | `float` | コスト |
| `phase_stats` | `list[dict]` | フェーズ別統計（完了サマリー用） |
| `total_duration_sec` | `float` | 総所要時間 |
| `total_cost_usd` | `float` | 総コスト |
| `design_pr_number` | `int` | 設計PR番号 |
| `design_pr_url` | `str` | 設計PR URL |
| `next_action` | `str` | 次のアクション指示テキスト |

## 5. 変更対象ファイル一覧

### 5.1 新規作成

| ファイル | 説明 |
|---------|------|
| `src/ai_agent_orchestrator/notifications/templates.py` | 通知テンプレートレジストリ |
| `src/ai_agent_orchestrator/notifications/progress.py` | 進捗トラッカー |
| `src/ai_agent_orchestrator/notifications/error_summarizer.py` | エラー要約生成 |

### 5.2 改修

| ファイル | 変更内容 |
|---------|---------|
| `src/ai_agent_orchestrator/models.py` | `NotificationType` enum 追加 |
| `src/ai_agent_orchestrator/notifications/slack.py` | `_build_payload` 全面刷新、`notify` シグネチャ拡張 |
| `src/ai_agent_orchestrator/notifications/__init__.py` | 新モジュールの re-export |
| `src/ai_agent_orchestrator/phases/base.py` | フェーズ開始通知追加、metadata に `repo`/`issue_title` 追加、エラー通知改善 |
| `src/ai_agent_orchestrator/phases/hearing.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/design.py` | `notification_type` 指定、PR URL・変更ファイル追加 |
| `src/ai_agent_orchestrator/phases/implement.py` | `notification_type` 指定、PR URL・変更ファイル追加 |
| `src/ai_agent_orchestrator/phases/done.py` | 完了サマリー通知追加 |
| `src/ai_agent_orchestrator/phases/design_revise.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/analysis.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/phases/fix.py` | `notification_type` 指定、PR URL・変更ファイル追加 |
| `src/ai_agent_orchestrator/phases/split.py` | `notification_type` 指定、metadata 拡充 |
| `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | `ProgressTracker` 統合、システム通知改善 |
| `docs/specs/slack.md` | 仕様書を本設計に合わせて更新 |
| `tests/unit/test_slack.py` | 新フォーマットに合わせたテスト追加・更新 |

## 6. 実装計画

### Phase 1: 基盤構築

1. `NotificationType` enum を `models.py` に追加
2. `notifications/templates.py` を新規作成（テンプレートレジストリ）
3. `notifications/progress.py` を新規作成（進捗トラッカー）
4. `notifications/error_summarizer.py` を新規作成（エラー要約）

### Phase 2: SlackNotifier 改修

5. `slack.py` の `notify` メソッドシグネチャ拡張
6. `_build_payload` を全面刷新（Block Kit の header / divider / actions / attachments 対応）
7. 後方互換性を維持（`notification_type=None` 時は従来動作）

### Phase 3: フェーズ側の通知呼び出し改修

8. `base.py` に フェーズ開始通知・エラー通知改善を追加
9. 各フェーズファイル（12ファイル）の `notify` 呼び出しを改修
   - `notification_type` パラメータ追加
   - `metadata` に `repo`, `issue_title`, `pr_url`, `duration_sec` 等を追加

### Phase 4: 完了サマリー・中間報告

10. `orchestrator.py` に `ProgressTracker` を統合
11. `done.py` に完了サマリー通知を追加
12. 中間報告（ステップベース進捗）の仕組みを `base.py` の `execute` に組み込み

### Phase 5: テスト・仕様書更新

13. `test_slack.py` の既存テスト更新 + 新テスト追加
14. 新モジュールのユニットテスト作成
15. `docs/specs/slack.md` の仕様書を更新

## 7. 後方互換性

- `notify(message, level=..., metadata=...)` の既存呼び出しは **そのまま動作** する
- `notification_type` が `None`（デフォルト）の場合、従来の level ベースの絵文字 + シンプルペイロードを使用
- `notification_type` が指定された場合のみ、リッチなペイロードに切り替わる
- これにより、段階的な移行が可能

## 8. テスト方針

> **目標: カバレッジ率 100%** — 全新規モジュール・改修箇所に対してテストを網羅し、カバレッジ率 100% を目指す。

### 8.1 テストファイル構成

| テストファイル | 対象モジュール |
|--------------|--------------|
| `tests/unit/test_notification_templates.py`（新規） | `notifications/templates.py` |
| `tests/unit/test_progress_tracker.py`（新規） | `notifications/progress.py` |
| `tests/unit/test_error_summarizer.py`（新規） | `notifications/error_summarizer.py` |
| `tests/unit/test_slack.py`（更新） | `notifications/slack.py` |
| `tests/unit/test_models.py`（更新） | `models.py`（NotificationType 追加分） |

### 8.2 テンプレートレジストリ (`test_notification_templates.py`)

| テスト | 検証内容 |
|-------|---------|
| `test_all_notification_types_have_template` | 全 `NotificationType` メンバーに対応するテンプレートが `TEMPLATES` に存在すること |
| `test_notification_type_emoji_mapping` | 各 `NotificationType` に対応する絵文字が正しいこと |
| `test_color_format_is_valid_hex` | 全テンプレートの `color` が `#` + 6桁16進数であること |
| `test_default_message_not_empty` | 全テンプレートの `default_message` が空でないこと |
| `test_template_immutability` | `NotificationTemplate` が frozen dataclass であり変更不可であること |
| `test_phase_labels_cover_all_phases` | `PHASE_LABELS` が全フェーズキーをカバーしていること |
| `test_workflow_phases_valid_keys` | `WORKFLOW_PHASES` の各フェーズキーが `PHASE_LABELS` に存在すること |

### 8.3 進捗トラッカー (`test_progress_tracker.py`)

| テスト | 検証内容 |
|-------|---------|
| `test_start_phase` | `start_phase` でフェーズが登録され、`started_at` がセットされること |
| `test_start_phase_duplicate` | 同一フェーズの二重開始時の挙動（上書き or エラー） |
| `test_update_step` | `update_step` で `current_step` が更新されること |
| `test_update_step_invalid_phase` | 未登録フェーズへの `update_step` がエラーにならないこと |
| `test_complete_phase` | `complete_phase` で `completed_at` がセットされ、`PhaseProgress` が返ること |
| `test_complete_phase_with_cost` | `cost_usd` が正しく記録されること |
| `test_get_progress_existing` | 登録済みフェーズの進捗が取得できること |
| `test_get_progress_nonexistent` | 未登録フェーズに対して `None` が返ること |
| `test_get_summary` | 複数フェーズ完了後のサマリーに `total_duration_sec`, `total_cost_usd`, 全フェーズが含まれること |
| `test_get_summary_empty` | フェーズ未登録の Issue に対するサマリーが空であること |
| `test_get_summary_partial` | 一部未完了フェーズがある場合のサマリーが正しいこと |
| `test_cleanup` | `cleanup` 後に当該 Issue のデータが削除されること |
| `test_cleanup_nonexistent_issue` | 未登録 Issue の `cleanup` がエラーにならないこと |
| `test_multiple_issues_isolation` | 異なる Issue 間でデータが干渉しないこと |
| `test_phase_steps_definition` | `PHASE_STEPS` の全エントリが空でないリストであること |

### 8.4 エラー要約 (`test_error_summarizer.py`)

| テスト | 検証内容 |
|-------|---------|
| `test_summarize_timeout_error` | `TimeoutError` が正しいテンプレートで要約されること |
| `test_summarize_runtime_error` | `RuntimeError` のメッセージが `cause` に含まれること |
| `test_summarize_auth_error` | 認証エラーの要約が正しいこと |
| `test_summarize_git_conflict_error` | Git コンフリクトエラーの要約が正しいこと |
| `test_summarize_unknown_error` | テンプレート未定義のエラーがデフォルトテンプレートで要約されること |
| `test_summarize_with_phase` | `phase` パラメータが `location` に反映されること |
| `test_summarize_with_issue_number` | `issue_number` が `location` に反映されること |
| `test_summarize_traceback_tail` | `traceback_tail` に最後の3行が含まれること |
| `test_format_for_slack` | Slack mrkdwn 形式が正しくフォーマットされること（全フィールド含む） |
| `test_format_for_slack_all_fields_present` | `format_for_slack` の出力にエラー種別・発生箇所・原因・対応案が全て含まれること |

### 8.5 SlackNotifier ペイロード構築 (`test_slack.py`)

| テスト | 検証内容 |
|-------|---------|
| `test_backward_compatibility` | `notification_type=None` で従来の level ベースペイロードが生成されること |
| `test_header_block_includes_issue_title` | ヘッダーブロックに Issue 番号とタイトルが含まれること |
| `test_header_block_without_issue_title` | Issue タイトルなしの場合のフォールバック表示 |
| `test_color_sidebar_by_type` | 通知タイプに応じた `attachments.color` がセットされること |
| `test_color_sidebar_all_types` | 全 `NotificationType` で色が正しく設定されること |
| `test_pr_button_action` | PR URL がある場合に `actions` ブロックにボタンが生成されること |
| `test_pr_button_absent_without_url` | PR URL がない場合にボタンが生成されないこと |
| `test_issue_button_always_present` | Issue URL がある場合に「Issueを見る」ボタンが含まれること |
| `test_divider_present` | divider ブロックが含まれること |
| `test_progress_bar_rendering` | 進捗バーが正しくレンダリングされること |
| `test_progress_bar_all_workflow_types` | 全ワークフロータイプ（bug/feature-s/m/l）で進捗バーが正しいこと |
| `test_duration_format` | 所要時間が「X分Y秒」形式でフォーマットされること |
| `test_duration_format_edge_cases` | 0秒、60秒ちょうど、3600秒超のフォーマットが正しいこと |
| `test_done_summary_payload` | 完了サマリーにフェーズ別統計・総コスト・PR一覧が含まれること |
| `test_done_summary_with_missing_phases` | 一部フェーズ欠損時のサマリーが「N/A」で表示されること |
| `test_error_notification_payload` | エラー通知に `ErrorSummary` の全フィールドが含まれること |
| `test_error_notification_without_summary` | `error_summary` なしのエラー通知のフォールバック |
| `test_phase_start_notification` | フェーズ開始通知が正しい絵文字・色・メッセージで生成されること |
| `test_files_changed_in_metadata` | 変更ファイル一覧がペイロードの fields に含まれること |
| `test_files_changed_empty` | 変更ファイルが空の場合にフィールドが省略されること |
| `test_next_action_in_context` | 次のアクション指示が context ブロックに含まれること |
| `test_next_action_absent` | `next_action` なしの場合に context ブロックが省略されること |
| `test_block_count_within_limit` | 生成されるブロック数が Slack の 50 ブロック制限内であること |
| `test_notify_sends_to_slack_api` | `notify` が Slack API を正しく呼び出すこと（mock） |
| `test_notify_with_custom_channel` | カスタムチャンネル指定時に正しいチャンネルに送信されること |
| `test_metadata_keys_all_recognized` | 4.10 で定義した全 metadata キーがペイロード構築で認識されること |

### 8.6 変更ファイル取得 (`test_slack.py` 内)

| テスト | 検証内容 |
|-------|---------|
| `test_get_diff_stats_success` | 正常時に `file_count`, `insertions`, `deletions`, `files` が返ること |
| `test_get_diff_stats_empty_diff` | 変更なしの場合に空の結果が返ること |
| `test_get_diff_stats_git_failure` | git コマンド失敗時に例外でなく空の結果が返ること（best-effort） |

### 8.7 NotificationType Enum (`test_models.py` 内)

| テスト | 検証内容 |
|-------|---------|
| `test_notification_type_values_unique` | 全メンバーの値が一意であること |
| `test_notification_type_is_str_enum` | `StrEnum` を継承しており、文字列比較が可能であること |
| `test_notification_type_member_count` | メンバー数が設計通り（18個）であること |

### 8.8 フェーズ側の通知呼び出し

| テスト | 検証内容 |
|-------|---------|
| `test_base_phase_sends_start_notification` | `base.py` の `execute` がフェーズ開始時に `PHASE_START` 通知を送信すること |
| `test_base_phase_sends_error_notification` | エラー発生時に `ERROR` タイプで `error_summary` 付き通知が送信されること |
| `test_base_phase_sends_timeout_notification` | タイムアウト時に `TIMEOUT` タイプで通知が送信されること |
| `test_hearing_sends_hearing_question_type` | ヒアリングフェーズが `HEARING_QUESTION` タイプで通知すること |
| `test_design_sends_design_pr_created_type` | 設計フェーズが `DESIGN_PR_CREATED` タイプ + PR URL 付きで通知すること |
| `test_implement_sends_impl_pr_created_type` | 実装フェーズが `IMPL_PR_CREATED` タイプ + PR URL・変更ファイル付きで通知すること |
| `test_fix_sends_fix_pr_created_type` | 修正フェーズが `FIX_PR_CREATED` タイプ + PR URL 付きで通知すること |
| `test_done_sends_done_summary` | 完了フェーズが `DONE_SUMMARY` タイプでサマリー付き通知を送信すること |
| `test_design_revise_sends_revised_type` | 設計修正が `DESIGN_REVISED` タイプで通知すること |
| `test_impl_revise_sends_revised_type` | 実装修正が `IMPL_REVISED` タイプで通知すること |
| `test_plan_brief_sends_plan_posted_type` | 方針策定が `PLAN_POSTED` タイプで通知すること |
| `test_analysis_sends_plan_posted_type` | 原因分析が `PLAN_POSTED` タイプで通知すること |
| `test_split_sends_proposed_type` | 分割提案が `SPLIT_PROPOSED` タイプで通知すること |
| `test_split_sends_executed_type` | 分割実行が `SPLIT_EXECUTED` タイプで通知すること |
| `test_all_phases_include_repo_in_metadata` | 全フェーズの通知に `repo` が metadata に含まれること |
| `test_all_phases_include_issue_title_in_metadata` | 全フェーズの通知に `issue_title` が metadata に含まれること |

### 8.9 Orchestrator 統合

| テスト | 検証内容 |
|-------|---------|
| `test_orchestrator_initializes_progress_tracker` | Orchestrator 起動時に `ProgressTracker` が初期化されること |
| `test_orchestrator_system_start_notification` | 起動時に `SYSTEM_START` タイプで通知されること |
| `test_orchestrator_system_error_notification` | システムエラー時に `SYSTEM_ERROR` タイプで通知されること |
| `test_orchestrator_health_check_notification` | ヘルスチェック異常時に `HEALTH_CHECK` タイプで通知されること |
| `test_orchestrator_progress_tracker_cleanup` | Issue 完了後に `ProgressTracker.cleanup` が呼ばれること |

### 8.10 既存テストの更新

- `TC-SL-01` ～ `TC-SL-10`: 既存テストは後方互換性により引き続きパスすることを確認
- 必要に応じてアサーションを追加

### 8.11 カバレッジ計測

- `pytest --cov=src/ai_agent_orchestrator/notifications --cov=src/ai_agent_orchestrator/models --cov-report=term-missing` でカバレッジを計測
- 新規モジュール (`templates.py`, `progress.py`, `error_summarizer.py`) は **行カバレッジ 100%** を必須とする
- 改修モジュール (`slack.py`, `models.py`) は **変更行のカバレッジ 100%** を必須とする
- 各フェーズファイルの通知呼び出し箇所は **分岐カバレッジ 100%** を必須とする
- CI パイプラインで `--cov-fail-under=100` を新規モジュールに対して適用し、カバレッジ低下を防止する

## 9. リスクと対策

| リスク | 影響 | 対策 |
|-------|------|------|
| Slack Block Kit の制限超過 | ペイロードが50ブロック制限に達する | ブロック数を常にカウントし、制限内に収める truncation ロジックを実装 |
| 中間報告の頻度が高すぎる | Slack rate limit (1msg/sec) | 最低送信間隔を30秒に設定。同一フェーズの重複通知を抑制 |
| 後方互換性の破壊 | 既存テストの失敗 | `notification_type=None` で従来パスを維持。段階的移行 |
| `git diff --stat` の実行失敗 | 変更ファイル取得不可 | best-effort で取得。失敗時は変更ファイル情報を省略 |
| 完了サマリーのデータ不整合 | ProgressTracker にデータが揃わない | 欠損フェーズは「N/A」で表示。クリーンアップを確実に実行 |
