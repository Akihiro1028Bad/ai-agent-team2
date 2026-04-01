# 設計書: Issue #21 スラックメッセージの改善

## 1. 概要

Slack 通知の「タイミング・フォーマット・内容」すべてをアップグレードする。
現在の単純なテキスト + context ブロック構成を、通知タイプ別テンプレート・Block Kit リッチフォーマット・
フェーズ開始/完了の両方向通知に進化させる。

## 2. 現状分析

### 2.1 現在の通知箇所 (14箇所)

| ファイル | 通知内容 | タイミング |
|---------|---------|-----------|
| `base.py` (×2) | タイムアウト / エラー | フェーズ異常終了時 |
| `hearing.py` | 質問投稿 | 完了時 |
| `analysis.py` | 修正方針投稿 | 完了時 |
| `plan_brief.py` | 実装方針投稿 | 完了時 |
| `design.py` | 設計PR作成 | 完了時 |
| `design_revise.py` | 設計書修正 | 完了時 |
| `planning.py` | *(通知なし)* | — |
| `implement.py` | 実装PR作成 | 完了時 |
| `impl_revise.py` | 実装修正 | 完了時 |
| `fix.py` | 修正PR作成 | 完了時 |
| `ci_fix.py` | *(通知なし)* | — |
| `type_detection.py` | *(通知なし)* | — |
| `done.py` (×2) | 完了 / 連鎖開始 | 完了時 |
| `split.py` (×2) | 分割提案 / 分割完了 | 完了時 |
| `orchestrator.py` (×3) | 起動 / ルーティングエラー / ヘルスチェック失敗 | 各種 |

### 2.2 現在の課題

1. **フォーマット**: `emoji + テキスト` の1行構成。Block Kit の活用が最小限
2. **内容**: repo 情報・PR URL・Issue タイトルが渡されていないケースが多い。日英混在
3. **タイミング**: フェーズ完了時のみ。開始時・承認待ちの通知がない
4. **通知タイプ**: `docs/specs/slack.md` に7種定義済みだが実装では未使用

## 3. 設計方針

ヒアリングで「全てお任せ」の回答を得たため、以下の方針で設計する:

- **タイミング**: フェーズ開始 + 完了 + ユーザーアクション要求時 (ヒアリング質問C)
- **フォーマット**: 通知タイプ別テンプレート + リンクボタン付き Block Kit (ヒアリング質問A+B)
- **内容**: Issue タイトル・フェーズ進捗・所要時間を追加
- **言語**: 日本語に統一
- **通知タイプ**: `docs/specs/slack.md` の7種を拡張して実装

## 4. 通知タイプ定義

### 4.1 NotificationType Enum

```python
class NotificationType(StrEnum):
    """Slack 通知タイプ."""

    # フェーズライフサイクル
    PHASE_START = "phase_start"
    PHASE_COMPLETE = "phase_complete"

    # ユーザーアクション要求
    HEARING_QUESTION = "hearing_question"
    APPROVAL_REQUIRED = "approval_required"
    REVIEW_REQUESTED = "review_requested"

    # PR 関連
    DESIGN_PR_CREATED = "design_pr_created"
    IMPL_PR_CREATED = "impl_pr_created"
    FIX_PR_CREATED = "fix_pr_created"

    # 完了・エラー
    DONE = "done"
    ERROR = "error"
    TIMEOUT = "timeout"

    # システム
    SYSTEM_START = "system_start"
    SYSTEM_ERROR = "system_error"
    HEALTH_CHECK_FAIL = "health_check_fail"
```

### 4.2 通知タイプ別テンプレート

| 通知タイプ | 絵文字 | カラー | メッセージテンプレート |
|-----------|--------|--------|---------------------|
| `phase_start` | :gear: | `#2196F3` (青) | `Issue #{n} 「{title}」の{phase_label}を開始しました` |
| `phase_complete` | :white_check_mark: | `#4CAF50` (緑) | `Issue #{n} 「{title}」の{phase_label}が完了しました ({duration})` |
| `hearing_question` | :speech_balloon: | `#FF9800` (橙) | `Issue #{n} 「{title}」に質問を投稿しました。回答をお願いします` |
| `approval_required` | :thumbsup: | `#FF9800` (橙) | `Issue #{n} 「{title}」の方針を投稿しました。承認をお願いします` |
| `review_requested` | :eyes: | `#FF9800` (橙) | `Issue #{n} 「{title}」のPRレビューをお願いします` |
| `design_pr_created` | :pencil: | `#4CAF50` (緑) | `Issue #{n} 「{title}」の設計PRを作成しました` |
| `impl_pr_created` | :rocket: | `#4CAF50` (緑) | `Issue #{n} 「{title}」の実装PRを作成しました` |
| `fix_pr_created` | :wrench: | `#4CAF50` (緑) | `Issue #{n} 「{title}」の修正PRを作成しました` |
| `done` | :tada: | `#4CAF50` (緑) | `Issue #{n} 「{title}」が完了しました！` |
| `error` | :x: | `#F44336` (赤) | `Issue #{n} でエラーが発生しました` |
| `timeout` | :hourglass: | `#F44336` (赤) | `Issue #{n} の{phase_label}がタイムアウトしました` |
| `system_start` | :robot_face: | `#2196F3` (青) | `オーケストレーターが起動しました` |
| `system_error` | :rotating_light: | `#F44336` (赤) | `システムエラーが発生しました` |
| `health_check_fail` | :warning: | `#FF9800` (橙) | `ヘルスチェックに失敗しました: {details}` |

## 5. Block Kit ペイロード設計

### 5.1 標準レイアウト

すべての通知は以下の3層構造を基本とする:

```
┌─────────────────────────────────────────┐
│ [Header] :emoji: タイトルメッセージ       │
├─────────────────────────────────────────┤
│ [Section] 詳細情報                       │
│  - Issue タイトル / PR リンク / 進捗     │
│  - [ボタン: Issue を見る] [PR を見る]     │
├─────────────────────────────────────────┤
│ [Context] repo | phase | 所要時間        │
└─────────────────────────────────────────┘
```

### 5.2 ペイロード例: 実装PR作成通知

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":rocket: Issue #42 「ログイン機能の追加」の実装PRを作成しました",
                "emoji": true
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*Issue:*\n<https://github.com/org/repo/issues/42|#42 ログイン機能の追加>"
                },
                {
                    "type": "mrkdwn",
                    "text": "*PR:*\n<https://github.com/org/repo/pull/55|#55>"
                },
                {
                    "type": "mrkdwn",
                    "text": "*フェーズ:*\n実装 (5/7 完了)"
                },
                {
                    "type": "mrkdwn",
                    "text": "*所要時間:*\n3分42秒"
                }
            ]
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "PRを見る",
                        "emoji": true
                    },
                    "url": "https://github.com/org/repo/pull/55",
                    "action_id": "view_pr"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Issueを見る",
                        "emoji": true
                    },
                    "url": "https://github.com/org/repo/issues/42",
                    "action_id": "view_issue"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :gear: implement | :stopwatch: 3m42s"
                }
            ]
        }
    ]
}
```

### 5.3 ペイロード例: エラー通知

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": ":x: Issue #42 でエラーが発生しました",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*エラー内容:*\n```TimeoutError: Agent execution exceeded 30 minutes```"
            }
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": "*Issue:*\n<https://github.com/org/repo/issues/42|#42 ログイン機能の追加>"
                },
                {
                    "type": "mrkdwn",
                    "text": "*フェーズ:*\nimplment"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :x: error | :stopwatch: 30m00s"
                }
            ]
        }
    ]
}
```

## 6. SlackNotifier クラス設計

### 6.1 クラス図

```
SlackNotifier
├── __init__(webhook_url, default_channel)
├── notify(message, *, notification_type, channel, level, metadata) -> None
├── send(payload) -> bool
├── close() -> None
├── _build_rich_payload(notification_type, message, metadata) -> dict
├── _build_header_block(emoji, message) -> dict
├── _build_fields_block(metadata) -> dict
├── _build_actions_block(metadata) -> dict
├── _build_context_block(metadata) -> dict
├── _format_duration(seconds) -> str
└── _get_template(notification_type) -> NotificationTemplate

NotificationTemplate (dataclass)
├── emoji: str
├── color: str
├── message_template: str
└── include_actions: bool
```

### 6.2 `notify()` メソッドの変更

```python
async def notify(
    self,
    message: str,
    *,
    notification_type: NotificationType | str | None = None,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
```

**後方互換性**: `notification_type` が `None` の場合は従来の `level` ベースのシンプルフォーマットを使用。
これにより既存の呼び出しコードが段階的に移行可能。

### 6.3 metadata に追加するフィールド

| フィールド | 型 | 説明 |
|-----------|-----|------|
| `repo` | `str` | リポジトリ名 (`owner/repo`) |
| `issue` | `int` | Issue 番号 |
| `issue_title` | `str` | **新規** Issue タイトル |
| `issue_url` | `str` | **新規** Issue URL |
| `pr` | `int` | PR 番号 |
| `pr_url` | `str` | PR URL |
| `phase` | `str` | 現在のフェーズ |
| `phase_label` | `str` | **新規** フェーズの日本語表示名 |
| `phase_index` | `int` | **新規** 現在のフェーズ番号 (1-based) |
| `phase_total` | `int` | **新規** 総フェーズ数 |
| `duration_sec` | `float` | **新規** 所要時間（秒） |
| `error` | `str` | エラーメッセージ |
| `notification_type` | `str` | 通知タイプ |

## 7. フェーズ日本語ラベルマッピング

```python
PHASE_LABELS: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "ヒアリング回答待ち",
    "analysis": "原因分析",
    "plan-brief": "実装方針策定",
    "plan-review": "方針レビュー待ち",
    "design": "設計書作成",
    "design-review": "設計レビュー待ち",
    "design-revise": "設計書修正",
    "planning": "実装計画策定",
    "implement": "実装",
    "fix": "バグ修正",
    "ci-fix": "CI修正",
    "impl-review": "実装レビュー待ち",
    "impl-revise": "実装修正",
    "split-proposal": "分割提案",
    "split-execute": "分割実行",
    "done": "完了",
    "suspended": "一時停止",
    "blocked": "ブロック中",
}
```

## 8. フェーズ進捗マッピング

Issue タイプ別のフェーズ順序を定義し、「3/7 完了」のような進捗表示を可能にする:

```python
WORKFLOW_PHASES: dict[str, list[str]] = {
    "bug": [
        "type-detection", "analysis", "plan-review",
        "fix", "ci-fix", "impl-review", "done",
    ],
    "feature-s": [
        "type-detection", "plan-brief", "plan-review",
        "implement", "ci-fix", "impl-review", "done",
    ],
    "feature-m": [
        "type-detection", "hearing", "design", "design-review",
        "planning", "implement", "ci-fix", "impl-review", "done",
    ],
    "feature-l": [
        "type-detection", "hearing", "design", "design-review",
        "split-proposal", "split-execute", "done",
    ],
}
```

## 9. 各フェーズの通知タイミング変更

### 9.1 変更一覧

| フェーズ | 現在 | 変更後 |
|---------|------|-------|
| `type_detection.py` | 通知なし | **開始時**: `phase_start` |
| `hearing.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `hearing_question` |
| `analysis.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `approval_required` |
| `plan_brief.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `approval_required` |
| `design.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `design_pr_created` + `review_requested` |
| `design_revise.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `phase_complete` |
| `planning.py` | 通知なし | **開始時**: `phase_start`, **完了時**: `phase_complete` |
| `implement.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `impl_pr_created` |
| `impl_revise.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `phase_complete` |
| `fix.py` | 完了時のみ | **開始時**: `phase_start`, **完了時**: `fix_pr_created` |
| `ci_fix.py` | 通知なし | **開始時**: `phase_start`, **完了時**: `phase_complete` |
| `done.py` | 完了時のみ | **完了時**: `done` (開始通知は不要) |
| `split.py` | 提案+完了 | **開始時**: `phase_start`, **提案時**: `approval_required`, **完了時**: `phase_complete` |
| `base.py` (タイムアウト) | エラー時 | `timeout` (変更なし、フォーマット改善) |
| `base.py` (エラー) | エラー時 | `error` (変更なし、フォーマット改善) |
| `orchestrator.py` (起動) | 起動時 | `system_start` (フォーマット改善) |
| `orchestrator.py` (エラー) | エラー時 | `system_error` (フォーマット改善) |
| `orchestrator.py` (ヘルスチェック) | 失敗時 | `health_check_fail` (フォーマット改善) |

### 9.2 開始通知の実装箇所

フェーズ開始通知は `base.py` の `execute()` テンプレートメソッド内に共通化する:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        await self._tracker.track("phase_start", ...)

        # --- 新規: フェーズ開始通知 ---
        await self._notify_phase_start(request)

        prompt = await self.build_prompt(request)
        result = await self.run_agent(request, prompt)
        await self.process_result(request, result)

        await self._tracker.track("phase_end", ...)
    except TimeoutError:
        await self._handle_timeout(request)
    except Exception as exc:
        await self._handle_error(request, exc)
```

```python
async def _notify_phase_start(self, request: TaskRequest) -> None:
    """フェーズ開始通知を送信する."""
    # done フェーズは開始通知不要
    if str(request.phase) == "done":
        return

    issue_title = await self._get_issue_title(request)
    phase_label = PHASE_LABELS.get(str(request.phase), str(request.phase))
    issue_type = self._sm.get_issue_type(request.issue_number)
    phase_index, phase_total = self._get_phase_progress(
        str(request.phase), issue_type
    )

    await self._notifier.notify(
        f"Issue #{request.issue_number} 「{issue_title}」の{phase_label}を開始しました",
        notification_type=NotificationType.PHASE_START,
        metadata={
            "repo": self._get_repo_fullname(request),
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": str(request.phase),
            "phase_label": phase_label,
            "phase_index": phase_index,
            "phase_total": phase_total,
        },
    )
```

## 10. ヘルパーメソッド追加 (base.py)

```python
async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する (失敗時は空文字列)."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        return ""

def _get_repo_fullname(self, request: TaskRequest) -> str:
    """リポジトリのフルネーム (owner/repo) を取得する."""
    owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    return f"{owner}/{repo_name}" if owner and repo_name else ""

@staticmethod
def _get_phase_progress(phase: str, issue_type: str) -> tuple[int, int]:
    """現在フェーズの進捗 (index, total) を返す."""
    workflow = WORKFLOW_PHASES.get(issue_type, [])
    if phase in workflow:
        return workflow.index(phase) + 1, len(workflow)
    return 0, 0
```

## 11. 変更対象ファイル一覧

| ファイル | 変更内容 | 影響度 |
|---------|---------|--------|
| `notifications/slack.py` | リッチペイロード構築、テンプレート化、NotificationType 対応 | **大** |
| `models.py` | `NotificationType` Enum 追加、`PHASE_LABELS` / `WORKFLOW_PHASES` 定数追加 | **中** |
| `phases/base.py` | `_notify_phase_start()` 追加、エラー/タイムアウト通知改善、ヘルパー追加 | **大** |
| `phases/hearing.py` | `notification_type=HEARING_QUESTION` + metadata 拡充 | **小** |
| `phases/analysis.py` | `notification_type=APPROVAL_REQUIRED` + metadata 拡充 | **小** |
| `phases/plan_brief.py` | `notification_type=APPROVAL_REQUIRED` + metadata 拡充 | **小** |
| `phases/design.py` | `notification_type=DESIGN_PR_CREATED` + metadata 拡充 | **小** |
| `phases/design_revise.py` | `notification_type=PHASE_COMPLETE` + metadata 拡充 | **小** |
| `phases/planning.py` | 完了通知追加 `notification_type=PHASE_COMPLETE` | **小** |
| `phases/implement.py` | `notification_type=IMPL_PR_CREATED` + metadata 拡充 | **小** |
| `phases/impl_revise.py` | `notification_type=PHASE_COMPLETE` + metadata 拡充 | **小** |
| `phases/fix.py` | `notification_type=FIX_PR_CREATED` + metadata 拡充 | **小** |
| `phases/ci_fix.py` | 完了通知追加 `notification_type=PHASE_COMPLETE` | **小** |
| `phases/type_detection.py` | (開始通知は base.py で共通化するため変更なし) | **なし** |
| `phases/done.py` | `notification_type=DONE` + metadata 拡充 | **小** |
| `phases/split.py` | `notification_type=APPROVAL_REQUIRED` / `PHASE_COMPLETE` + metadata 拡充 | **小** |
| `orchestrator/orchestrator.py` | `notification_type` 付き通知に変更 (起動/エラー/ヘルスチェック) | **中** |
| `tests/unit/test_slack.py` | リッチペイロード検証テスト追加 | **大** |
| `docs/specs/slack.md` | 仕様書を新設計に合わせて更新 | **中** |

**合計: 18ファイル** (フェーズ13 + slack.py + models.py + orchestrator.py + test_slack.py + specs/slack.md)

## 12. NotifierProtocol の更新

`phases/base.py` の `NotifierProtocol` を更新:

```python
class NotifierProtocol:
    """Minimal notifier protocol."""

    async def notify(
        self,
        message: str,
        *,
        notification_type: str | None = None,
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Send a notification."""
        ...
```

`orchestrator.py` の `Notifier` Protocol も同様に更新する。

## 13. テスト計画

### 13.1 既存テスト (後方互換性の維持)

既存の 13 テストケース (TC-SL-01〜13) はすべてそのまま PASS すること。
`notification_type=None` 時は従来のシンプルフォーマットを使用する。

### 13.2 新規テストケース

| ID | テスト名 | 検証内容 |
|----|---------|---------|
| TC-SL-14 | `test_notify_with_notification_type_uses_rich_format` | `notification_type` 指定時に header + fields + context の3層ブロック構造 |
| TC-SL-15 | `test_notification_type_emoji_mapping` | 各 `NotificationType` に正しい絵文字がマッピングされている |
| TC-SL-16 | `test_rich_format_includes_issue_title` | `issue_title` が metadata にある場合にメッセージに含まれる |
| TC-SL-17 | `test_rich_format_includes_action_buttons` | PR 通知時にボタンブロックが含まれる |
| TC-SL-18 | `test_rich_format_includes_phase_progress` | `phase_index` / `phase_total` がコンテキストに含まれる |
| TC-SL-19 | `test_rich_format_includes_duration` | `duration_sec` がフォーマットされてコンテキストに含まれる |
| TC-SL-20 | `test_format_duration_helper` | `_format_duration(222)` → `"3m42s"` |
| TC-SL-21 | `test_error_notification_includes_error_block` | エラー通知時にエラー内容がコードブロックで表示される |
| TC-SL-22 | `test_backward_compat_no_notification_type` | `notification_type=None` で従来フォーマットが維持される |
| TC-SL-23 | `test_phase_labels_mapping` | `PHASE_LABELS` の全フェーズに日本語ラベルが定義されている |
| TC-SL-24 | `test_workflow_phases_progress` | `_get_phase_progress("implement", "feature-m")` → `(6, 9)` |
| TC-SL-25 | `test_base_execute_sends_phase_start_notification` | `base.execute()` でフェーズ開始通知が送信される |
| TC-SL-26 | `test_done_phase_skips_start_notification` | `done` フェーズでは開始通知がスキップされる |

## 14. 実装順序

1. **Step 1**: `models.py` に `NotificationType`, `PHASE_LABELS`, `WORKFLOW_PHASES` を追加
2. **Step 2**: `notifications/slack.py` にリッチペイロード構築ロジックを追加 (後方互換性維持)
3. **Step 3**: `phases/base.py` に `NotifierProtocol` 更新 + `_notify_phase_start()` + ヘルパー追加
4. **Step 4**: 各フェーズファイルの `notify()` 呼び出しを `notification_type` + 拡充 metadata に更新
5. **Step 5**: `orchestrator/orchestrator.py` の通知を `notification_type` 付きに更新
6. **Step 6**: `tests/unit/test_slack.py` にテスト追加
7. **Step 7**: `docs/specs/slack.md` を更新

## 15. 後方互換性

- `notification_type` パラメータはオプショナル (`None` デフォルト)
- `notification_type=None` 時は従来の `level` ベースの簡易フォーマット
- 既存テスト13件はすべて変更なしで PASS
- `NullNotifier` は新パラメータを `**kwargs` で無視するため変更不要

## 16. リスクと対策

| リスク | 影響 | 対策 |
|-------|------|------|
| Webhook ペイロードサイズ増大 | Block Kit の制限 (50 blocks) に近づく可能性 | 1通知あたり最大5ブロックに制限。header/section/actions/context のみ |
| Issue タイトル取得の追加 API コール | フェーズ開始時の遅延 | best-effort: 失敗時は空文字列でフォールバック |
| Block Kit ボタンの Incoming Webhook 制限 | Incoming Webhook はインタラクティブ機能非対応 | ボタンは `url` リンクのみ使用 (action callback 不使用) |
| 通知頻度の増加 (開始+完了で2倍) | ユーザーへの通知過多 | 短時間フェーズ (type-detection 等) は開始通知のみ、完了通知は重要フェーズに限定も検討 |
