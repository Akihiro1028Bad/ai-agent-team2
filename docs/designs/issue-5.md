# Issue #5: Slackメッセージ改善 設計書

## 1. 概要

Slack通知のタイミング・フォーマット・内容を全面的にアップグレードする。
現在の簡素な section + context 2ブロック構成から、Header Block + Section + Fields を用いたリッチフォーマットへ移行し、
通知タイミングの追加（フェーズ開始・Issue受付）、言語の日本語統一、エラー時の詳細情報表示を実現する。

## 2. 要件サマリー（ヒアリング結果）

| # | 項目 | 決定事項 |
|---|------|---------|
| 1 | 通知タイミング | フェーズ開始・Issue受付を追加（リマインドは不要） |
| 2 | フォーマット | リッチフォーマット（Header + Section + Fields） |
| 3 | メッセージ内容 | コスト・フェーズ名・アクション案内・Issueタイトル・エラー詳細を含める |
| 4 | 言語統一 | すべて日本語 |
| 5 | Slackスレッド | 不要（現在のWebhook方式を維持） |
| 6 | フェーズ進捗 | フェーズ名のみ表示（ステップ番号やプログレスバーは不要） |
| 7 | コスト表示 | フェーズ完了時のみ（そのフェーズのコスト・所要時間） |
| 8 | エラー詳細 | 詳細表示＋考えられる原因の推定を含める |

## 3. 現状分析

### 3.1 現在の通知タイミング（全18箇所）

| カテゴリ | 箇所数 | 言語 |
|---------|--------|------|
| フェーズ完了系 | 11 | 日本語 |
| エラー系（base.py） | 2 | 日本語 |
| オーケストレーター系 | 4 | **英語** |
| イベントルーター | 0（GitHub コメントのみ） | — |

### 3.2 現在の課題

1. 仕様書の `notification_type` 別絵文字（📋💬✏️🚀✅等）が**未使用**
2. **フェーズ開始時の通知がない**（完了時のみ）
3. **Issue受付時の通知がない**
4. `repo` 情報が metadata に含まれていない通知が多い
5. オーケストレーター系メッセージが**英語**
6. ユーザーアクション案内が**不統一**
7. コスト・所要時間の情報が**含まれない**
8. エラー時の詳細情報が**不十分**
9. フォーマットが section + context の簡素な2ブロック構成

---

## 4. 設計

### 4.1 通知タイプの定義

新しい `NotificationType` enum を `models.py` に追加する。

```python
class NotificationType(StrEnum):
    """Slack通知タイプ."""

    # ライフサイクル
    ISSUE_RECEIVED = "issue_received"          # Issue受付
    PHASE_START = "phase_start"                # フェーズ開始
    PHASE_COMPLETE = "phase_complete"          # フェーズ完了

    # アクション要求
    HEARING_QUESTION = "hearing_question"      # ヒアリング質問投稿
    PLAN_POSTED = "plan_posted"                # 方針投稿（承認待ち）
    DESIGN_PR_CREATED = "design_pr_created"    # 設計PR作成（レビュー待ち）
    IMPL_PR_CREATED = "impl_pr_created"        # 実装PR作成（レビュー待ち）
    FIX_PR_CREATED = "fix_pr_created"          # 修正PR作成（レビュー待ち）
    SPLIT_PROPOSED = "split_proposed"           # 分割提案（承認待ち）

    # 完了
    DESIGN_REVISED = "design_revised"          # 設計修正完了
    IMPL_REVISED = "impl_revised"              # 実装修正完了
    SPLIT_EXECUTED = "split_executed"           # 分割実行完了
    ISSUE_DONE = "issue_done"                  # Issue完了
    CASCADE_START = "cascade_start"            # 連鎖タスク開始

    # システム
    ORCHESTRATOR_STARTED = "orchestrator_started"  # オーケストレーター起動

    # エラー
    PHASE_TIMEOUT = "phase_timeout"            # フェーズタイムアウト
    PHASE_ERROR = "phase_error"                # フェーズエラー
    EVENT_ROUTING_ERROR = "event_routing_error" # イベントルーティングエラー
    TASK_SUSPENDED = "task_suspended"           # タスク停止
    HEALTH_CHECK_FAILURE = "health_check_failure" # ヘルスチェック失敗
```

### 4.2 通知タイプ別絵文字マッピング

```python
_NOTIFICATION_EMOJI: dict[str, str] = {
    # ライフサイクル
    "issue_received": ":inbox_tray:",
    "phase_start": ":arrow_forward:",
    "phase_complete": ":white_check_mark:",

    # アクション要求
    "hearing_question": ":speech_balloon:",
    "plan_posted": ":clipboard:",
    "design_pr_created": ":pencil:",
    "impl_pr_created": ":rocket:",
    "fix_pr_created": ":wrench:",
    "split_proposed": ":scissors:",

    # 完了
    "design_revised": ":pencil:",
    "impl_revised": ":hammer_and_wrench:",
    "split_executed": ":scissors:",
    "issue_done": ":tada:",
    "cascade_start": ":link:",

    # システム
    "orchestrator_started": ":robot_face:",

    # エラー
    "phase_timeout": ":hourglass:",
    "phase_error": ":x:",
    "event_routing_error": ":warning:",
    "task_suspended": ":pause_button:",
    "health_check_failure": ":rotating_light:",
}
```

### 4.3 リッチフォーマット設計

通知カテゴリに応じて3種類のフォーマットテンプレートを使い分ける。

#### 4.3.1 フォーマットA: 情報通知（フェーズ開始・完了・Issue受付等）

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📋 フェーズ完了: implement"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Issue #42 の実装PRを作成しました"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ*\n`owner/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ*\nimplement" },
                { "type": "mrkdwn", "text": "*コスト*\n$1.23" },
                { "type": "mrkdwn", "text": "*所要時間*\n3分45秒" }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":page_facing_up: <https://github.com/owner/repo/issues/42|Issue #42: Issueタイトル> | :memo: <https://github.com/owner/repo/pull/11|PR #11>"
                }
            ]
        }
    ]
}
```

#### 4.3.2 フォーマットB: アクション要求通知（承認・レビュー待ち）

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "📋 方針投稿: analysis"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Issue #42 の修正方針を投稿しました"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ*\n`owner/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ*\nanalysis" },
                { "type": "mrkdwn", "text": "*コスト*\n$0.45" },
                { "type": "mrkdwn", "text": "*所要時間*\n1分20秒" }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":point_right: *次のアクション*: コメントに👍リアクションで承認してください"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":page_facing_up: <https://github.com/owner/repo/issues/42|Issue #42: Issueタイトル>"
                }
            ]
        }
    ]
}
```

#### 4.3.3 フォーマットC: エラー通知

```json
{
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "❌ エラー発生: implement"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Issue #42 でエラーが発生しました"
            }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": "*リポジトリ*\n`owner/repo`" },
                { "type": "mrkdwn", "text": "*フェーズ*\nimplement" }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*エラー内容*\n```No transition defined from Phase.DESIGN to Phase.DESIGN```"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*考えられる原因*\n• 状態遷移の定義漏れ（VALID_TRANSITIONS に該当遷移が未登録）\n• 同一フェーズへの再遷移ロジックの不備\n• イベントルーターの遷移先判定の誤り"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":page_facing_up: <https://github.com/owner/repo/issues/42|Issue #42: Issueタイトル>"
                }
            ]
        }
    ]
}
```

### 4.4 `notify()` メソッドのインターフェース変更

metadata の構造を拡張し、リッチフォーマットに必要な情報をすべて渡せるようにする。

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

**メソッドシグネチャは変更しない**（後方互換性を維持）。
metadata の認識キーを拡張する：

| キー | 型 | 説明 | 新規 |
|------|-----|------|------|
| `repo` | `str` | リポジトリ名 (`owner/repo`) | 既存 |
| `issue` | `int` | Issue番号 | 既存 |
| `pr` | `int` | PR番号 | 既存 |
| `pr_url` | `str` | PRのURL | 既存 |
| `phase` | `str` | 現在のフェーズ名 | 既存 |
| `notification_type` | `str` | 通知タイプ（NotificationType値） | **新規** |
| `issue_title` | `str` | Issueタイトル | **新規** |
| `cost_usd` | `float` | フェーズのコスト（USD） | **新規** |
| `duration_sec` | `float` | フェーズの所要時間（秒） | **新規** |
| `next_action` | `str` | ユーザーへのアクション案内 | **新規** |
| `error_detail` | `str` | エラーの詳細情報 | **新規** |
| `error_cause` | `str` | 推定される原因 | **新規** |

### 4.5 `_build_payload()` の再設計

`notification_type` に基づいてフォーマットを自動選択する。

```python
def _build_payload(
    self,
    message: str,
    *,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """notification_type に基づいてリッチフォーマットのペイロードを構築する."""
    meta = metadata or {}
    notification_type = meta.get("notification_type", "")

    if self._is_error_type(notification_type):
        blocks = self._build_error_blocks(message, meta)
    elif self._is_action_type(notification_type):
        blocks = self._build_action_blocks(message, meta)
    else:
        blocks = self._build_info_blocks(message, level, meta)

    resolved_channel = channel or self._default_channel
    payload: dict[str, Any] = {"blocks": blocks}
    if resolved_channel is not None:
        payload["channel"] = resolved_channel
    return payload
```

#### 新規内部メソッド

```python
def _build_header_block(self, notification_type: str, phase: str) -> dict[str, Any]:
    """Header Block を構築する."""

def _build_fields_block(self, metadata: dict[str, Any]) -> dict[str, Any]:
    """Fields（リポジトリ・フェーズ・コスト・所要時間）ブロックを構築する."""

def _build_action_section(self, next_action: str) -> dict[str, Any]:
    """アクション案内セクションを構築する."""

def _build_error_detail_section(self, error_detail: str, error_cause: str) -> list[dict[str, Any]]:
    """エラー詳細＋推定原因セクションを構築する."""

def _build_context_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """リンク付きコンテキストブロックを構築する（Issueタイトル付き）."""

def _build_info_blocks(self, message: str, level: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """情報通知フォーマット（フォーマットA）のブロックリストを構築する."""

def _build_action_blocks(self, message: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """アクション要求フォーマット（フォーマットB）のブロックリストを構築する."""

def _build_error_blocks(self, message: str, meta: dict[str, Any]) -> list[dict[str, Any]]:
    """エラーフォーマット（フォーマットC）のブロックリストを構築する."""

@staticmethod
def _is_error_type(notification_type: str) -> bool:
    """エラー系通知タイプか判定する."""

@staticmethod
def _is_action_type(notification_type: str) -> bool:
    """アクション要求系通知タイプか判定する."""

@staticmethod
def _format_duration(seconds: float) -> str:
    """秒数を「X分Y秒」形式にフォーマットする."""

@staticmethod
def _format_cost(cost_usd: float) -> str:
    """コストを「$X.XX」形式にフォーマットする."""

@staticmethod
def _header_text(notification_type: str, phase: str) -> str:
    """Header Block 用テキストを構築する."""
```

### 4.6 `_level_emoji()` の廃止と `_notification_emoji()` への移行

通知レベル（info/error/critical）ベースの絵文字選択を廃止し、
`notification_type` ベースの絵文字選択に移行する。

```python
@staticmethod
def _notification_emoji(notification_type: str) -> str:
    """通知タイプに応じた絵文字を返す."""
    return _NOTIFICATION_EMOJI.get(notification_type, ":robot_face:")
```

後方互換性のため、`notification_type` が未指定の場合は従来の `level` ベース絵文字にフォールバックする。

### 4.7 Header Block のタイトル定義

| notification_type | Header テキスト |
|-------------------|----------------|
| `issue_received` | `📥 Issue受付` |
| `phase_start` | `▶️ フェーズ開始: {phase}` |
| `phase_complete` | `✅ フェーズ完了: {phase}` |
| `hearing_question` | `💬 ヒアリング質問投稿` |
| `plan_posted` | `📋 方針投稿: {phase}` |
| `design_pr_created` | `✏️ 設計PR作成` |
| `impl_pr_created` | `🚀 実装PR作成` |
| `fix_pr_created` | `🔧 修正PR作成` |
| `split_proposed` | `✂️ 分割提案` |
| `design_revised` | `✏️ 設計修正完了` |
| `impl_revised` | `🔨 実装修正完了` |
| `split_executed` | `✂️ 分割実行完了` |
| `issue_done` | `🎉 Issue完了` |
| `cascade_start` | `🔗 連鎖タスク開始` |
| `orchestrator_started` | `🤖 オーケストレーター起動` |
| `phase_timeout` | `⏳ タイムアウト: {phase}` |
| `phase_error` | `❌ エラー発生: {phase}` |
| `event_routing_error` | `⚠️ イベントルーティングエラー` |
| `task_suspended` | `⏸️ タスク停止` |
| `health_check_failure` | `🚨 ヘルスチェック失敗` |

### 4.8 アクション案内（`next_action`）の定義

| notification_type | next_action テキスト |
|-------------------|---------------------|
| `hearing_question` | `Issueコメントで回答してください` |
| `plan_posted` | `コメントに👍リアクションで承認してください` |
| `design_pr_created` | `設計PRをレビューしてApproveしてください` |
| `impl_pr_created` | `実装PRをレビューしてApproveしてください` |
| `fix_pr_created` | `修正PRをレビューしてApproveしてください` |
| `split_proposed` | `コメントに👍リアクションで承認、修正があればコメントで指示してください` |

### 4.9 エラー原因推定ロジック

`_estimate_error_cause()` 静的メソッドを新設し、エラーメッセージのパターンマッチングで考えられる原因を推定する。

```python
@staticmethod
def _estimate_error_cause(error_message: str) -> str:
    """エラーメッセージから考えられる原因を推定する."""
```

| エラーパターン | 推定原因 |
|--------------|---------|
| `No transition defined` | `• 状態遷移の定義漏れ（VALID_TRANSITIONS に該当遷移が未登録）\n• イベントルーターの遷移先判定の誤り` |
| `TimeoutError` | `• フェーズの実行時間が制限を超過\n• エージェントが応答しない\n• 外部APIのレスポンス遅延` |
| `AuthenticationError` / `401` / `403` | `• GitHubトークンの期限切れまたは権限不足\n• Slack Webhook URLの無効化` |
| `git conflict` / `merge conflict` | `• ブランチ間のコンフリクト\n• ベースブランチの変更との衝突` |
| `rate limit` / `429` | `• GitHub APIのレート制限\n• 短時間での大量リクエスト` |
| `PR作成に失敗` | `• ブランチが push されていない\n• 同名ブランチのPRが既に存在\n• ベースブランチの指定誤り` |
| その他 | `• 予期しないエラーです。ログを確認してください` |

---

## 5. 変更対象ファイル一覧

### 5.1 コア変更

| ファイル | 変更内容 |
|---------|---------|
| `src/ai_agent_orchestrator/models.py` | `NotificationType` enum の追加 |
| `src/ai_agent_orchestrator/notifications/slack.py` | `_build_payload()` のリッチフォーマット対応、`_notification_emoji()`、エラー原因推定、新規内部メソッド群 |

### 5.2 フェーズ変更（notify() 呼び出し側）

各フェーズで以下を共通で変更する：
- `notification_type` を metadata に追加
- `repo` を metadata に追加（欠落箇所）
- `issue_title` を metadata に追加
- `cost_usd` / `duration_sec` を metadata に追加（完了時）
- `next_action` を metadata に追加（アクション要求系）
- メッセージ文言を日本語に統一

| ファイル | 変更箇所 |
|---------|---------|
| `src/ai_agent_orchestrator/phases/base.py` | `execute()` にフェーズ開始通知を追加、`_handle_timeout()` / `_handle_error()` の metadata 拡張、エラー原因推定の呼び出し |
| `src/ai_agent_orchestrator/phases/hearing.py` | `notification_type="hearing_question"` + `next_action` |
| `src/ai_agent_orchestrator/phases/analysis.py` | `notification_type="plan_posted"` + `next_action` |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | `notification_type="plan_posted"` + `next_action` |
| `src/ai_agent_orchestrator/phases/design.py` | `notification_type="design_pr_created"` + `next_action` |
| `src/ai_agent_orchestrator/phases/design_revise.py` | `notification_type="design_revised"` |
| `src/ai_agent_orchestrator/phases/implement.py` | `notification_type="impl_pr_created"` + `next_action` |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | `notification_type="impl_revised"` |
| `src/ai_agent_orchestrator/phases/fix.py` | `notification_type="fix_pr_created"` + `next_action` |
| `src/ai_agent_orchestrator/phases/split.py` | `notification_type="split_proposed"` / `"split_executed"` |
| `src/ai_agent_orchestrator/phases/done.py` | `notification_type="issue_done"` / `"cascade_start"` |

### 5.3 オーケストレーター変更

| ファイル | 変更箇所 |
|---------|---------|
| `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | 起動通知の日本語化、Issue受付通知の追加、エラー系通知の metadata 拡張、全メッセージの日本語化 |

### 5.4 テスト変更

| ファイル | 変更箇所 |
|---------|---------|
| `tests/unit/test_slack.py` | リッチフォーマットのペイロード検証、新しい通知タイプの絵文字検証、エラー原因推定のテスト、後方互換性テスト |
| `tests/unit/test_phases.py` | notify() 呼び出し時の metadata 検証（notification_type, repo, issue_title 等） |

### 5.5 仕様書更新

| ファイル | 変更箇所 |
|---------|---------|
| `docs/specs/slack.md` | リッチフォーマット仕様、新規メソッド、通知タイプ定義の更新 |

---

## 6. 詳細変更設計

### 6.1 `base.py` — フェーズ開始通知の追加

`execute()` メソッド内で、エージェント実行前にフェーズ開始通知を送信する。

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        # 【新規】フェーズ開始通知
        repo_str = self._format_repo(request.repo)
        issue_title = await self._get_issue_title(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の {request.phase} フェーズを開始しました",
            metadata={
                "notification_type": "phase_start",
                "repo": repo_str,
                "issue": request.issue_number,
                "issue_title": issue_title,
                "phase": str(request.phase),
            },
        )

        prompt = await self.build_prompt(request)
        result = await self.run_agent(request, prompt)
        await self.process_result(request, result)
        # ...
```

#### ヘルパーメソッド追加

```python
def _format_repo(self, repo: object) -> str:
    """リポジトリ設定オブジェクトから 'owner/repo' 文字列を返す."""
    owner = getattr(repo, "owner", "")
    name = getattr(repo, "repo", "")
    return f"{owner}/{name}" if owner and name else ""

async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する（失敗時は空文字列）."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        return ""
```

### 6.2 `base.py` — エラー通知の改善

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: SUSPENDED 遷移 + Issue コメント + リッチ通知."""
    import traceback

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

    error_detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    # Slack Block Kit のコードブロック制限を考慮して3000文字に制限
    if len(error_detail) > 3000:
        error_detail = error_detail[:3000] + "\n... (truncated)"

    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    from ai_agent_orchestrator.notifications.slack import SlackNotifier

    error_cause = SlackNotifier._estimate_error_cause(str(error))
    repo_str = self._format_repo(request.repo)
    issue_title = await self._get_issue_title(request)

    await self._notifier.notify(
        f"Issue #{request.issue_number} でエラーが発生しました",
        level="error",
        metadata={
            "notification_type": "phase_error",
            "repo": repo_str,
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": str(request.phase),
            "error_detail": str(error),
            "error_cause": error_cause,
        },
    )
```

### 6.3 `base.py` — タイムアウト通知の改善

```python
async def _handle_timeout(self, request: TaskRequest) -> None:
    """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + リッチ通知."""
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

    from ai_agent_orchestrator.notifications.slack import SlackNotifier

    error_cause = SlackNotifier._estimate_error_cause("TimeoutError")
    repo_str = self._format_repo(request.repo)
    issue_title = await self._get_issue_title(request)

    await self._notifier.notify(
        f"Issue #{request.issue_number} の {request.phase} フェーズがタイムアウトしました",
        level="error",
        metadata={
            "notification_type": "phase_timeout",
            "repo": repo_str,
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": str(request.phase),
            "error_detail": f"{request.phase} フェーズの実行時間が制限を超過しました",
            "error_cause": error_cause,
        },
    )
```

### 6.4 各フェーズの notify() 呼び出し変更例

#### hearing.py（アクション要求系の例）

```python
# Before
await self._notifier.notify(
    f"Issue #{issue_number} に質問を投稿しました。回答をお願いします",
    metadata={"issue": issue_number},
)

# After
repo_str = self._format_repo(request.repo)
issue_title = await self._get_issue_title(request)
await self._notifier.notify(
    f"Issue #{issue_number} に質問を投稿しました",
    metadata={
        "notification_type": "hearing_question",
        "repo": repo_str,
        "issue": issue_number,
        "issue_title": issue_title,
        "phase": str(request.phase),
        "cost_usd": result.cost_usd,
        "duration_sec": result.duration_sec,
        "next_action": "Issueコメントで回答してください",
    },
)
```

#### implement.py（PR作成系の例）

```python
# Before
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
    metadata={"issue": request.issue_number, "pr": pr_number},
)

# After
repo_str = self._format_repo(request.repo)
issue_title = await self._get_issue_title(request)
pr_url = f"https://github.com/{repo_str}/pull/{pr_number}"
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
    metadata={
        "notification_type": "impl_pr_created",
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": issue_title,
        "phase": str(request.phase),
        "pr": pr_number,
        "pr_url": pr_url,
        "cost_usd": result.cost_usd,
        "duration_sec": result.duration_sec,
        "next_action": "実装PRをレビューしてApproveしてください",
    },
)
```

### 6.5 `orchestrator.py` — 日本語化＋Issue受付通知

```python
# 起動通知（日本語化）
await self._notifier.notify(
    "オーケストレーターが起動しました",
    metadata={
        "notification_type": "orchestrator_started",
        "repo": ", ".join(repo_names),
    },
)

# Issue受付通知（新規追加 — _enqueue_issue() 内）
await self._notifier.notify(
    f"Issue #{issue_number} を受け付けました: {issue_title}",
    metadata={
        "notification_type": "issue_received",
        "repo": repo_str,
        "issue": issue_number,
        "issue_title": issue_title,
    },
)

# イベントルーティングエラー（日本語化）
await self._notifier.notify(
    f"イベントルーティングエラー: {exc}",
    level="error",
    metadata={
        "notification_type": "event_routing_error",
        "error_detail": str(exc),
        "error_cause": SlackNotifier._estimate_error_cause(str(exc)),
    },
)

# タスク停止（日本語化）
await self._notifier.notify(
    f"Issue #{issue_number} がエラーにより停止しました: {error}",
    level="error",
    metadata={
        "notification_type": "task_suspended",
        "repo": repo_str,
        "issue": issue_number,
        "phase": str(phase),
        "error_detail": str(error),
        "error_cause": SlackNotifier._estimate_error_cause(str(error)),
    },
)

# ヘルスチェック失敗（日本語化）
await self._notifier.notify(
    f"ヘルスチェック失敗: {failed_components}",
    level="error",
    metadata={
        "notification_type": "health_check_failure",
        "error_detail": str(failed_components),
    },
)
```

---

## 7. 後方互換性

- `notify()` メソッドのシグネチャは変更しない
- `notification_type` が metadata に含まれない場合、従来の `level` ベース絵文字 + 旧フォーマット（section + context の2ブロック構成）にフォールバック
- `_level_emoji()` は内部的に残すが、`notification_type` 指定時は `_notification_emoji()` を優先
- NullNotifier に影響なし（metadata を無視してログ出力するのみ）

---

## 8. テスト計画

### 8.1 新規テストケース

| テストID | テスト内容 |
|---------|-----------|
| TC-SL-14 | `_build_info_blocks()` が Header + Section + Fields + Context の構成を返すこと |
| TC-SL-15 | `_build_action_blocks()` が next_action セクションを含むこと |
| TC-SL-16 | `_build_error_blocks()` が error_detail + error_cause セクションを含むこと |
| TC-SL-17 | `_notification_emoji()` が全 NotificationType に対して正しい絵文字を返すこと |
| TC-SL-18 | `_estimate_error_cause()` が既知パターンに対して適切な原因を返すこと |
| TC-SL-19 | `_format_duration()` が秒数を「X分Y秒」形式に正しくフォーマットすること |
| TC-SL-20 | `_format_cost()` がコストを「$X.XX」形式に正しくフォーマットすること |
| TC-SL-21 | `_header_text()` が notification_type + phase から正しいヘッダーテキストを生成すること |
| TC-SL-22 | notification_type 未指定時に旧フォーマットにフォールバックすること（後方互換性） |
| TC-SL-23 | issue_title がコンテキストブロックのリンクテキストに含まれること |
| TC-SL-24 | cost_usd / duration_sec が Fields ブロックに表示されること |
| TC-SL-25 | フェーズ開始通知が execute() 内で送信されること（base.py のテスト） |
| TC-SL-26 | エラー通知に error_cause が含まれること |

### 8.2 既存テストケースの更新

| テストID | 変更内容 |
|---------|---------|
| TC-SL-01〜04 | notification_type 指定時のリッチフォーマット検証に拡張 |
| TC-SL-10 | `_notification_emoji()` のマッピングテストに変更 |
| TC-SL-11 | metadata 拡張に対応したペイロード構造の検証 |

---

## 9. 実装手順

### Step 1: models.py — NotificationType enum 追加
- `NotificationType` StrEnum の定義

### Step 2: slack.py — コア変更
1. `_NOTIFICATION_EMOJI` マッピング追加
2. `_HEADER_TEXT` マッピング追加
3. `_build_payload()` の再設計
4. `_build_info_blocks()` / `_build_action_blocks()` / `_build_error_blocks()` の実装
5. `_build_header_block()` / `_build_fields_block()` / `_build_context_block()` の実装
6. `_notification_emoji()` の実装
7. `_estimate_error_cause()` の実装
8. `_format_duration()` / `_format_cost()` の実装
9. 旧フォーマットへのフォールバック実装

### Step 3: base.py — 共通変更
1. `_format_repo()` / `_get_issue_title()` ヘルパー追加
2. `execute()` にフェーズ開始通知を追加
3. `_handle_error()` のエラー詳細・原因推定対応
4. `_handle_timeout()` のリッチ通知対応

### Step 4: 各フェーズファイルの notify() 呼び出し更新
- hearing.py, analysis.py, plan_brief.py, design.py, design_revise.py,
  implement.py, impl_revise.py, fix.py, split.py, done.py

### Step 5: orchestrator.py — 日本語化 + Issue受付通知
1. 起動通知の日本語化
2. Issue受付通知の追加
3. エラー系通知の metadata 拡張・日本語化

### Step 6: テスト更新
1. test_slack.py — 新規テストケース追加 + 既存テスト更新
2. test_phases.py — notify() 呼び出し検証の更新

### Step 7: 仕様書更新
- docs/specs/slack.md の更新

---

## 10. 影響範囲・リスク

### 影響ファイル数: 約15ファイル
- コア: 2ファイル（models.py, slack.py）
- フェーズ: 11ファイル（base.py + 各フェーズ10ファイル）
- オーケストレーター: 1ファイル
- テスト: 2ファイル

### リスクと緩和策

| リスク | 影響 | 緩和策 |
|--------|------|--------|
| Block Kit の文字数制限（3001文字/ブロック） | エラー詳細が長すぎると送信失敗 | `error_detail` を3000文字に制限（truncate） |
| Webhook レスポンス遅延 | フェーズ開始通知の追加で通知量が約2倍 | best-effort 設計は維持。タイムアウト10秒で影響を制限 |
| `_get_issue_title()` のAPI呼び出し増加 | Issue タイトル取得のために追加のAPI呼び出しが発生 | 失敗時は空文字列にフォールバック。将来的にキャッシュ検討 |
| 後方互換性の破損 | NullNotifier や既存テストの失敗 | notification_type 未指定時の旧フォーマットフォールバックで対応 |
