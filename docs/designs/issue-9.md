# 設計書: Issue #9 - Slackメッセージの改善

## 1. 概要

Slack通知システムの全面的なアップグレードを行う。送信タイミング・フォーマット・内容の3軸すべてを改善し、
ユーザーがIssue処理の進行状況をリアルタイムに把握できるようにする。

### 1.1 スコープ

| 項目 | スコープ |
|------|---------|
| 送信タイミング | フェーズ開始通知の追加、既存完了通知の改善 |
| フォーマット | Block Kit リッチフォーマット (Header, Divider, Fields, Action Buttons, Color Attachment) |
| 内容 | Issueタイトル、経過時間、全体進捗、ブランチ名、エラー時スタックトレース抜粋 |
| 言語 | 日本語 |

### 1.2 スコープ外（別Issue）

- CI実行開始 / CI失敗検知のポーリング追加（新規イベント検知ロジック）
- PRマージ完了のポーリング追加
- レビューコメント検知のポーリング追加
- 承認待ちリマインダー通知

> 上記の新規イベント検知ロジックは別Issueに分離する。本Issueでは通知フォーマット・内容の改善と、
> 既存のフェーズ実行フローにおけるタイミング追加に集中する。

---

## 2. 現状分析

### 2.1 現在の通知箇所（全15箇所）

| ファイル | メッセージ | level | metadata |
|---------|----------|-------|----------|
| orchestrator.py | "Orchestrator started" | info | repos |
| orchestrator.py | "Event routing error: {exc}" | error | - |
| orchestrator.py | "Health check failures: ..." | error | - |
| orchestrator.py | "Issue #{n} suspended due to error: {err}" | error | issue, phase, error |
| base.py | "Issue #{n} がタイムアウトしました" | error | issue, phase |
| base.py | "Issue #{n} でエラー: {err}" | error | issue, phase |
| hearing.py | "Issue #{n} に質問を投稿しました" | info | issue |
| design.py | "Issue #{n} の設計PR #{pr} を作成しました" | info | issue, pr |
| implement.py | "Issue #{n} の実装PR #{pr} を作成しました" | info | issue, pr |
| fix.py | "Issue #{n} の修正PR #{pr} を作成しました" | info | issue, pr |
| design_revise.py | "Issue #{n} の設計書を修正しました" | info | issue |
| impl_revise.py | "Issue #{n} の実装を修正しました" | info | issue |
| analysis.py | "Issue #{n} の修正方針を投稿しました" | info | issue |
| plan_brief.py | "Issue #{n} の実装方針を投稿しました" | info | issue |
| split.py | "Issue #{n} の分割を提案しました" / "分割完了" | info | issue |
| done.py | "Issue #{n} 完了しました" / "連鎖処理開始" | info | issue |

### 2.2 現在の課題

1. **タイミング**: フェーズ「開始」時の通知がない（完了時のみ）
2. **フォーマット**: 全通知が同一レイアウト（section + context のみ）。視覚的区別が弱い
3. **内容**: PR URL未設定箇所あり。Issueタイトル・経過時間・進捗情報なし
4. **絵文字**: `notification_type` は仕様書に定義済みだが実装では未活用（3種類のみ）
5. **metadata不足**: `repo` が渡されていない箇所が多く、Issueリンクが生成されない

---

## 3. 設計方針

### 3.1 アーキテクチャ変更

既存の `SlackNotifier` クラスを拡張し、通知タイプ別のリッチペイロード構築機能を追加する。
既存の `notify()` インターフェースは後方互換を維持しつつ、新たに `notification_type` による
メッセージ分岐を実装する。

```
変更前:
  notify(message, level, metadata)
    → _build_payload() → 一律 section + context

変更後:
  notify(message, level, metadata)
    → _resolve_notification_type(metadata)
    → _build_rich_payload() → type別リッチブロック構築
       ├── Header ブロック
       ├── Section (本文 + Fields)
       ├── Divider
       ├── Actions (ボタン)
       └── Context (メタ情報)
    → Attachment (カラーバー) で全体をラップ
```

### 3.2 通知タイプ体系

`NotificationType` Enumを新設し、各通知を分類する。

```python
class NotificationType(StrEnum):
    """通知タイプ."""
    # フェーズ開始系（新規追加）
    PHASE_START = "phase_start"

    # フェーズ完了系（既存改善）
    HEARING_QUESTION = "hearing_question"
    DESIGN_PR_CREATED = "design_pr_created"
    IMPL_PR_CREATED = "impl_pr_created"
    FIX_PR_CREATED = "fix_pr_created"
    PLAN_POSTED = "plan_posted"
    DESIGN_REVISED = "design_revised"
    IMPL_REVISED = "impl_revised"
    SPLIT_PROPOSED = "split_proposed"
    SPLIT_COMPLETED = "split_completed"
    ISSUE_COMPLETED = "issue_completed"
    CHAIN_STARTED = "chain_started"

    # システム系（既存改善）
    SYSTEM_START = "system_start"
    HEALTH_CHECK_FAILURE = "health_check_failure"
    ERROR = "error"
    TIMEOUT = "timeout"
    SUSPENDED = "suspended"
```

---

## 4. 詳細設計

### 4.1 `SlackNotifier` クラスの変更

#### 4.1.1 新規定数

```python
# 通知タイプ別の絵文字マッピング
_TYPE_EMOJI: dict[str, str] = {
    "phase_start": ":arrow_forward:",
    "hearing_question": ":speech_balloon:",
    "design_pr_created": ":pencil:",
    "impl_pr_created": ":rocket:",
    "fix_pr_created": ":wrench:",
    "plan_posted": ":clipboard:",
    "design_revised": ":pencil:",
    "impl_revised": ":hammer_and_wrench:",
    "split_proposed": ":scissors:",
    "split_completed": ":scissors:",
    "issue_completed": ":white_check_mark:",
    "chain_started": ":link:",
    "system_start": ":green_circle:",
    "health_check_failure": ":rotating_light:",
    "error": ":x:",
    "timeout": ":hourglass:",
    "suspended": ":pause_button:",
}

# 通知タイプ別カラー（Attachment の color）
_TYPE_COLOR: dict[str, str] = {
    "phase_start": "#439FE0",       # 青: 進行中
    "hearing_question": "#E8A317",  # 黄: ユーザーアクション待ち
    "design_pr_created": "#E8A317", # 黄: レビュー待ち
    "impl_pr_created": "#E8A317",   # 黄: レビュー待ち
    "fix_pr_created": "#E8A317",    # 黄: レビュー待ち
    "plan_posted": "#E8A317",       # 黄: 承認待ち
    "design_revised": "#439FE0",    # 青: 進行中
    "impl_revised": "#439FE0",      # 青: 進行中
    "split_proposed": "#E8A317",    # 黄: 承認待ち
    "split_completed": "#2EB67D",   # 緑: 成功
    "issue_completed": "#2EB67D",   # 緑: 成功
    "chain_started": "#439FE0",     # 青: 進行中
    "system_start": "#2EB67D",      # 緑: 成功
    "health_check_failure": "#E01E5A", # 赤: エラー
    "error": "#E01E5A",             # 赤: エラー
    "timeout": "#E01E5A",           # 赤: エラー
    "suspended": "#E01E5A",         # 赤: エラー
}

# フェーズ表示名（日本語）
_PHASE_DISPLAY_NAME: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "ヒアリング回答待ち",
    "analysis": "原因分析",
    "plan-brief": "簡易方針策定",
    "plan-review": "方針レビュー",
    "design": "設計書作成",
    "design-review": "設計レビュー",
    "design-revise": "設計修正",
    "planning": "実装計画",
    "implement": "実装",
    "impl-review": "実装レビュー",
    "impl-revise": "実装修正",
    "ci-fix": "CI修正",
    "fix": "バグ修正",
    "split-proposal": "分割提案",
    "split-execute": "分割実行",
    "done": "完了",
}
```

#### 4.1.2 `_build_rich_payload()` メソッド（新規）

既存の `_build_payload()` を置き換える新しいペイロード構築メソッド。

```python
def _build_rich_payload(
    self,
    message: str,
    *,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """通知タイプに応じたリッチ Block Kit ペイロードを構築する."""
    meta = metadata or {}
    notification_type = meta.get("notification_type", "")
    emoji = _TYPE_EMOJI.get(notification_type, self._level_emoji(level))
    color = _TYPE_COLOR.get(notification_type, "#439FE0")

    blocks: list[dict[str, Any]] = []

    # 1. Header ブロック
    header_text = self._build_header_text(emoji, message, meta)
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": header_text, "emoji": True},
    })

    # 2. Section + Fields (2カラム情報)
    fields = self._build_fields(meta)
    if fields:
        blocks.append({
            "type": "section",
            "fields": fields,
        })

    # 3. 本文 Section（エラー詳細やサマリー）
    body_text = self._build_body_text(message, meta)
    if body_text:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": body_text},
        })

    # 4. Divider
    blocks.append({"type": "divider"})

    # 5. Action Buttons
    actions = self._build_actions(meta)
    if actions:
        blocks.append({
            "type": "actions",
            "elements": actions,
        })

    # 6. Context（タイムスタンプ等）
    context_elements = self._build_rich_context(meta)
    if context_elements:
        blocks.append({
            "type": "context",
            "elements": context_elements,
        })

    # Attachment でカラーバーを付与
    resolved_channel = channel or self._default_channel
    payload: dict[str, Any] = {
        "attachments": [{
            "color": color,
            "blocks": blocks,
        }],
    }
    if resolved_channel is not None:
        payload["channel"] = resolved_channel
    return payload
```

#### 4.1.3 `_build_header_text()` メソッド（新規）

```python
@staticmethod
def _build_header_text(
    emoji: str,
    message: str,
    meta: dict[str, Any],
) -> str:
    """Header ブロック用のテキストを構築する."""
    issue = meta.get("issue")
    issue_title = meta.get("issue_title", "")
    if issue is not None and issue_title:
        return f"{emoji} Issue #{issue}: {issue_title}"
    if issue is not None:
        return f"{emoji} Issue #{issue}"
    # Issue情報がない場合（システム通知等）は message をそのまま使う
    return f"{emoji} {message}"
```

#### 4.1.4 `_build_fields()` メソッド（新規）

```python
@staticmethod
def _build_fields(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """2カラム Fields を構築する."""
    fields: list[dict[str, Any]] = []

    phase = meta.get("phase")
    if phase:
        display_name = _PHASE_DISPLAY_NAME.get(phase, phase)
        fields.append({
            "type": "mrkdwn",
            "text": f"*フェーズ*\n{display_name}",
        })

    progress = meta.get("progress")
    if progress:
        fields.append({
            "type": "mrkdwn",
            "text": f"*進捗*\n{progress}",
        })

    duration = meta.get("duration_sec")
    if duration is not None:
        minutes = int(duration) // 60
        seconds = int(duration) % 60
        fields.append({
            "type": "mrkdwn",
            "text": f"*所要時間*\n{minutes}分{seconds}秒",
        })

    branch = meta.get("branch")
    if branch:
        fields.append({
            "type": "mrkdwn",
            "text": f"*ブランチ*\n`{branch}`",
        })

    return fields
```

#### 4.1.5 `_build_body_text()` メソッド（新規）

```python
@staticmethod
def _build_body_text(message: str, meta: dict[str, Any]) -> str | None:
    """本文テキストを構築する."""
    parts: list[str] = [message]

    # エラー時のスタックトレース抜粋（最後5行）
    stacktrace = meta.get("stacktrace")
    if stacktrace:
        lines = stacktrace.strip().splitlines()
        last_lines = lines[-5:] if len(lines) > 5 else lines
        trace_text = "\n".join(last_lines)
        parts.append(f"\n```\n{trace_text}\n```")

    # エラー調査結果
    error_analysis = meta.get("error_analysis")
    if error_analysis:
        parts.append(f"\n:mag: *調査結果:*\n{error_analysis}")

    return "\n".join(parts) if parts else None
```

#### 4.1.6 `_build_actions()` メソッド（新規）

```python
@staticmethod
def _build_actions(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """Action Buttons を構築する."""
    actions: list[dict[str, Any]] = []
    repo = meta.get("repo")
    issue = meta.get("issue")
    pr_url = meta.get("pr_url")
    comment_url = meta.get("comment_url")

    if repo and issue is not None:
        issue_url = f"https://github.com/{repo}/issues/{issue}"
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":clipboard: Issueを見る", "emoji": True},
            "url": issue_url,
        })

    if pr_url:
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":twisted_rightwards_arrows: PRを見る", "emoji": True},
            "url": pr_url,
        })

    if comment_url:
        actions.append({
            "type": "button",
            "text": {"type": "plain_text", "text": ":speech_balloon: 質問を見る", "emoji": True},
            "url": comment_url,
        })

    return actions
```

#### 4.1.7 `_build_rich_context()` メソッド（新規）

```python
@staticmethod
def _build_rich_context(meta: dict[str, Any]) -> list[dict[str, Any]]:
    """リッチ Context ブロック要素を構築する."""
    elements: list[dict[str, Any]] = []

    repo = meta.get("repo")
    if repo:
        elements.append({
            "type": "mrkdwn",
            "text": f":package: `{repo}`",
        })

    notification_type = meta.get("notification_type", "")
    if notification_type:
        elements.append({
            "type": "mrkdwn",
            "text": f"type: {notification_type}",
        })

    return elements
```

#### 4.1.8 `notify()` メソッドの変更

```python
async def notify(
    self,
    message: str,
    *,
    channel: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Slack にメッセージを送信する（リッチフォーマット対応）.

    metadata に notification_type が含まれる場合はリッチペイロードを構築。
    含まれない場合は後方互換のため従来フォーマットで送信。
    """
    meta = metadata or {}
    if meta.get("notification_type"):
        payload = self._build_rich_payload(
            message, channel=channel, level=level, metadata=metadata,
        )
    else:
        payload = self._build_payload(
            message, channel=channel, level=level, metadata=metadata,
        )
    await self.send(payload)
```

### 4.2 Notifier Protocol の拡張

`orchestrator.py` の `Notifier` Protocol と `base.py` の `NotifierProtocol` は
シグネチャ変更なし（metadata 経由で拡張するため後方互換）。

`NullNotifier` も変更不要（metadata の中身を見ないため）。

### 4.3 フェーズ開始通知の追加

`PhaseExecutor.execute()` の先頭でフェーズ開始通知を送信する。

#### base.py の変更

```python
async def execute(self, request: TaskRequest) -> None:
    """フェーズを実行する (テンプレートメソッド)."""
    try:
        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        # --- 追加: フェーズ開始通知 ---
        await self._notify_phase_start(request)

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
    """フェーズ開始を通知する."""
    phase_str = str(request.phase)
    phase_display = _PHASE_DISPLAY_NAME.get(phase_str, phase_str)
    repo_key = self._get_repo_key(request.repo)
    issue_title = await self._get_issue_title(request)

    await self._notifier.notify(
        f"{phase_display}を開始します",
        metadata={
            "notification_type": "phase_start",
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": phase_str,
            "repo": repo_key,
            "branch": f"feature/issue-{request.issue_number}",
        },
    )
```

#### 新規ヘルパーメソッド（base.py）

```python
@staticmethod
def _get_repo_key(repo: object) -> str:
    """リポジトリの 'owner/repo' 文字列を取得する."""
    owner = getattr(repo, "owner", "")
    name = getattr(repo, "repo", "")
    if owner and name:
        return f"{owner}/{name}"
    return ""

async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する (best-effort)."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        return ""
```

### 4.4 既存通知の改善（各フェーズファイル）

各フェーズの `process_result()` で `metadata` に以下を追加する:

| 追加フィールド | 型 | 説明 |
|--------------|-----|------|
| `notification_type` | str | 通知タイプ識別子 |
| `repo` | str | "owner/repo" 形式 |
| `issue_title` | str | Issue タイトル |
| `pr_url` | str | PR の URL（PR作成時） |
| `branch` | str | ブランチ名 |
| `duration_sec` | float | フェーズ所要時間 |
| `progress` | str | 全体進捗表示（例: "3/5 フェーズ完了"） |

#### 4.4.1 hearing.py の変更例

```python
# 変更前
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    metadata={"issue": request.issue_number},
)

# 変更後
repo_key = self._get_repo_key(request.repo)
issue_title = issue.title  # build_prompt() で取得済み
comment_url = f"https://github.com/{repo_key}/issues/{request.issue_number}#issuecomment-..."
await self._notifier.notify(
    "ヒアリング質問を投稿しました。回答をお願いします",
    metadata={
        "notification_type": "hearing_question",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_key,
        "phase": "hearing",
    },
)
```

#### 4.4.2 design.py の変更例

```python
# 変更後
repo_key = self._get_repo_key(request.repo)
pr_url = f"https://github.com/{repo_key}/pull/{pr_number}"
await self._notifier.notify(
    f"設計PR #{pr_number} を作成しました。レビューをお願いします",
    metadata={
        "notification_type": "design_pr_created",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_key,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": "design",
        "duration_sec": result.duration_sec,
    },
)
```

#### 4.4.3 implement.py の変更例

```python
# 変更後
repo_key = self._get_repo_key(request.repo)
pr_url = f"https://github.com/{repo_key}/pull/{pr_number}"
await self._notifier.notify(
    f"実装PR #{pr_number} を作成しました。レビューをお願いします",
    metadata={
        "notification_type": "impl_pr_created",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_key,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": "implement",
        "duration_sec": result.duration_sec,
        "branch": f"feature/issue-{request.issue_number}",
    },
)
```

#### 4.4.4 base.py エラーハンドラの変更

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: SUSPENDED 遷移 + Issue コメント + リッチ通知."""
    import traceback

    await self._sm.transition(request.issue_number, "suspended")
    client = await self._get_client(request.repo)
    try:
        await client.replace_phase_label(
            request.repo, request.issue_number, "phase:suspended",
        )
    except Exception:
        logger.warning(
            "Failed to update phase label to suspended for issue #%d",
            request.issue_number,
        )
    await client.create_comment(
        request.repo, request.issue_number,
        f"エラーが発生しました: {error}",
    )

    # スタックトレース取得
    tb = traceback.format_exception(type(error), error, error.__traceback__)
    stacktrace = "".join(tb)

    repo_key = self._get_repo_key(request.repo)
    issue_title = await self._get_issue_title(request)

    await self._notifier.notify(
        f"エラーが発生しました: {error}",
        level="error",
        metadata={
            "notification_type": "error",
            "issue": request.issue_number,
            "issue_title": issue_title,
            "repo": repo_key,
            "phase": str(request.phase),
            "error": str(error),
            "stacktrace": stacktrace,
        },
    )
```

#### 4.4.5 done.py の変更例

```python
# 変更後
repo_key = self._get_repo_key(request.repo)
await self._notifier.notify(
    "Issue が完了しました",
    metadata={
        "notification_type": "issue_completed",
        "issue": request.issue_number,
        "issue_title": issue_title,
        "repo": repo_key,
        "phase": "done",
    },
)
```

### 4.5 orchestrator.py の通知改善

```python
# start() 通知の改善
await self._notifier.notify(
    "オーケストレーターを起動しました",
    level="info",
    metadata={
        "notification_type": "system_start",
        "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
    },
)

# _handle_task_error() の改善
await self._notifier.notify(
    f"Issue #{issue_number} がエラーにより中断されました",
    level="error",
    metadata={
        "notification_type": "suspended",
        "issue": issue_number,
        "phase": task.phase,
        "error": str(error),
        "repo": task.repo_key,
    },
)

# health_check_loop の改善
await self._notifier.notify(
    f"ヘルスチェック失敗: {', '.join(unhealthy)}",
    level="error",
    metadata={
        "notification_type": "health_check_failure",
    },
)
```

### 4.6 進捗トラッキング

フェーズ進捗を通知に含めるため、`IssueType` に応じたフェーズリストを定義する。

```python
# base.py に追加
_WORKFLOW_PHASES: dict[str, list[str]] = {
    "bug": ["type-detection", "analysis", "plan-review", "fix", "impl-review", "done"],
    "feature-s": ["type-detection", "hearing", "plan-brief", "plan-review", "implement", "impl-review", "done"],
    "feature-m": [
        "type-detection", "hearing", "design", "design-review",
        "planning", "implement", "impl-review", "done",
    ],
    "feature-l": [
        "type-detection", "hearing", "split-proposal", "split-execute", "done",
    ],
}

def _get_progress(self, issue_number: int, current_phase: str) -> str | None:
    """全体進捗文字列を返す (例: '3/8 フェーズ完了')."""
    issue_type = self._sm.get_issue_type(issue_number)
    phases = _WORKFLOW_PHASES.get(issue_type)
    if not phases:
        return None
    try:
        idx = phases.index(current_phase)
        return f"{idx}/{len(phases)} フェーズ完了"
    except ValueError:
        return None
```

---

## 5. ペイロード構造の例

### 5.1 フェーズ開始通知

```json
{
  "channel": "#ai-agent",
  "attachments": [
    {
      "color": "#439FE0",
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": ":arrow_forward: Issue #42: Slackメッセージの改善",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*フェーズ*\n設計書作成" },
            { "type": "mrkdwn", "text": "*進捗*\n3/8 フェーズ完了" }
          ]
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "設計書作成を開始します" }
        },
        { "type": "divider" },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": { "type": "plain_text", "text": ":clipboard: Issueを見る", "emoji": true },
              "url": "https://github.com/org/repo/issues/42"
            }
          ]
        },
        {
          "type": "context",
          "elements": [
            { "type": "mrkdwn", "text": ":package: `org/repo`" },
            { "type": "mrkdwn", "text": "type: phase_start" }
          ]
        }
      ]
    }
  ]
}
```

### 5.2 PR作成通知（実装完了）

```json
{
  "channel": "#ai-agent",
  "attachments": [
    {
      "color": "#E8A317",
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": ":rocket: Issue #42: Slackメッセージの改善",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*フェーズ*\n実装" },
            { "type": "mrkdwn", "text": "*所要時間*\n12分30秒" },
            { "type": "mrkdwn", "text": "*進捗*\n6/8 フェーズ完了" },
            { "type": "mrkdwn", "text": "*ブランチ*\n`feature/issue-42`" }
          ]
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "実装PR #55 を作成しました。レビューをお願いします" }
        },
        { "type": "divider" },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": { "type": "plain_text", "text": ":clipboard: Issueを見る", "emoji": true },
              "url": "https://github.com/org/repo/issues/42"
            },
            {
              "type": "button",
              "text": { "type": "plain_text", "text": ":twisted_rightwards_arrows: PRを見る", "emoji": true },
              "url": "https://github.com/org/repo/pull/55"
            }
          ]
        },
        {
          "type": "context",
          "elements": [
            { "type": "mrkdwn", "text": ":package: `org/repo`" },
            { "type": "mrkdwn", "text": "type: impl_pr_created" }
          ]
        }
      ]
    }
  ]
}
```

### 5.3 エラー通知（スタックトレース付き）

```json
{
  "channel": "#ai-agent",
  "attachments": [
    {
      "color": "#E01E5A",
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": ":x: Issue #42: Slackメッセージの改善",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*フェーズ*\n実装" }
          ]
        },
        {
          "type": "section",
          "text": {
            "type": "mrkdwn",
            "text": "エラーが発生しました: RuntimeError: PR作成に失敗しました\n```\n  File \"implement.py\", line 67\n    pr_number = await self._ensure_pr_created(...)\n  File \"base.py\", line 519\n    raise RuntimeError(msg)\nRuntimeError: PR作成に失敗しました\n```"
          }
        },
        { "type": "divider" },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": { "type": "plain_text", "text": ":clipboard: Issueを見る", "emoji": true },
              "url": "https://github.com/org/repo/issues/42"
            }
          ]
        },
        {
          "type": "context",
          "elements": [
            { "type": "mrkdwn", "text": ":package: `org/repo`" },
            { "type": "mrkdwn", "text": "type: error" }
          ]
        }
      ]
    }
  ]
}
```

### 5.4 Issue完了通知

```json
{
  "channel": "#ai-agent",
  "attachments": [
    {
      "color": "#2EB67D",
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": ":white_check_mark: Issue #42: Slackメッセージの改善",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*フェーズ*\n完了" },
            { "type": "mrkdwn", "text": "*進捗*\n8/8 フェーズ完了" }
          ]
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "Issue が完了しました" }
        },
        { "type": "divider" },
        {
          "type": "actions",
          "elements": [
            {
              "type": "button",
              "text": { "type": "plain_text", "text": ":clipboard: Issueを見る", "emoji": true },
              "url": "https://github.com/org/repo/issues/42"
            }
          ]
        },
        {
          "type": "context",
          "elements": [
            { "type": "mrkdwn", "text": ":package: `org/repo`" },
            { "type": "mrkdwn", "text": "type: issue_completed" }
          ]
        }
      ]
    }
  ]
}
```

---

## 6. 変更対象ファイル一覧

| ファイル | 変更内容 | 変更規模 |
|---------|---------|---------|
| `src/ai_agent_orchestrator/notifications/slack.py` | リッチペイロード構築、通知タイプ別絵文字・カラー | 大 |
| `src/ai_agent_orchestrator/models.py` | `NotificationType` Enum 追加 | 小 |
| `src/ai_agent_orchestrator/phases/base.py` | フェーズ開始通知、進捗計算、エラー通知改善 | 中 |
| `src/ai_agent_orchestrator/phases/hearing.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/design.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/implement.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/fix.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/design_revise.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/analysis.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/split.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/phases/done.py` | metadata 拡充 | 小 |
| `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | システム通知改善 | 小 |
| `tests/unit/test_slack.py` | リッチペイロードのテスト追加 | 大 |
| `docs/specs/slack.md` | 仕様書の更新 | 中 |

合計: **16ファイル**

---

## 7. テスト計画

### 7.1 既存テストの維持

既存の13テストケース (TC-SL-01 ～ TC-SL-13) は後方互換のため全て維持する。
`notification_type` なしの `notify()` 呼び出しは従来フォーマットで送信される。

### 7.2 追加テストケース

| ID | テスト内容 | 検証ポイント |
|----|----------|------------|
| TC-SL-14 | `notification_type` ありでリッチペイロード生成 | attachments + color + blocks 構造 |
| TC-SL-15 | Header ブロックに Issue番号・タイトルが含まれる | header.text の内容 |
| TC-SL-16 | Fields に フェーズ・進捗・所要時間・ブランチ | fields 配列の内容 |
| TC-SL-17 | Action Buttons - Issueリンク | button の url |
| TC-SL-18 | Action Buttons - PRリンク | pr_url 指定時のボタン |
| TC-SL-19 | Action Buttons - 質問コメントリンク | comment_url 指定時のボタン |
| TC-SL-20 | エラー通知のスタックトレース抜粋 | 最後5行が code block に含まれる |
| TC-SL-21 | カラーバーの色が通知タイプに応じて変わる | attachments[0].color |
| TC-SL-22 | 通知タイプ別の絵文字マッピング | 全タイプの絵文字が正しいこと |
| TC-SL-23 | 進捗計算 `_get_progress()` | フェーズリスト内のインデックス計算 |
| TC-SL-24 | `notification_type` なしで従来フォーマット維持 | blocks 直配列（attachments なし） |
| TC-SL-25 | metadata に `repo` なしでもエラーにならない | ボタンが生成されないこと |
| TC-SL-26 | フェーズ開始通知の基本動作 | `phase_start` type でリッチ通知 |
| TC-SL-27 | スタックトレースが3000文字制限を超えない | 長大トレースの切り詰め |

### 7.3 テストコード例

```python
@respx.mock
async def test_rich_payload_with_notification_type(notifier: SlackNotifier) -> None:
    """notification_type ありでリッチペイロードが生成されることを検証."""
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))

    await notifier.notify(
        "実装PR #55 を作成しました",
        metadata={
            "notification_type": "impl_pr_created",
            "issue": 42,
            "issue_title": "Slackメッセージの改善",
            "repo": "org/repo",
            "pr": 55,
            "pr_url": "https://github.com/org/repo/pull/55",
            "phase": "implement",
            "duration_sec": 750.0,
            "branch": "feature/issue-42",
        },
    )

    request_body = json.loads(route.calls[0].request.content)
    # Attachment 構造
    assert "attachments" in request_body
    attachment = request_body["attachments"][0]
    assert attachment["color"] == "#E8A317"  # 黄: レビュー待ち

    blocks = attachment["blocks"]
    # Header
    header = blocks[0]
    assert header["type"] == "header"
    assert ":rocket:" in header["text"]["text"]
    assert "Issue #42" in header["text"]["text"]

    # Actions にPRボタンがある
    action_block = next(b for b in blocks if b["type"] == "actions")
    urls = [e["url"] for e in action_block["elements"]]
    assert "https://github.com/org/repo/pull/55" in urls
```

---

## 8. 移行戦略

### 8.1 後方互換性

- `notification_type` が metadata に含まれない場合、従来の `_build_payload()` を使用する
- 既存の `notify()` シグネチャは変更しない
- `NullNotifier` は変更不要

### 8.2 実装順序

1. **Step 1**: `slack.py` にリッチペイロード構築メソッド群を追加 + テスト
2. **Step 2**: `models.py` に `NotificationType` Enum 追加
3. **Step 3**: `base.py` にフェーズ開始通知 + 進捗計算 + エラー改善
4. **Step 4**: 各フェーズファイルの metadata 拡充（hearing → design → implement → 残り）
5. **Step 5**: `orchestrator.py` のシステム通知改善
6. **Step 6**: `docs/specs/slack.md` の仕様書更新

### 8.3 リスク

| リスク | 対策 |
|-------|------|
| Block Kit の文字数制限 (section: 3000文字) | スタックトレースを最後5行に切り詰め |
| Webhook レート制限 | フェーズ開始通知の追加で頻度が倍増するが、1 Issue あたり数分間隔なので問題なし |
| 後方互換性の破壊 | `notification_type` の有無で分岐する設計により回避 |
| Issue タイトル取得の追加API呼び出し | best-effort で取得、失敗時は空文字にフォールバック |

---

## 9. 将来の拡張（別Issue）

本Issueのスコープ外だが、以下の拡張を別Issueで対応予定:

1. **新規イベント検知 (ポーリング追加)**
   - CI実行開始 / CI失敗検知（`check_run` / `check_suite` ポーリング）
   - PRマージ完了（PR state ポーリング）
   - レビューコメント検知（`reviews` / `review_comments` ポーリング）

2. **エラー自動調査**
   - エラー発生時にスタックトレースを分析
   - 調査結果を `error_analysis` としてSlack通知に含める

3. **スレッド返信**
   - 同一Issueの通知をSlackスレッドにまとめる
   - Issue開始時の通知に対する返信として後続通知を送信
