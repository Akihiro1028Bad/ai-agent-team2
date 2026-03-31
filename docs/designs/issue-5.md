# Issue #5: Slackメッセージ改善 設計書

## 1. 概要

Slack通知メッセージのタイミング・フォーマット・内容を全面的にアップグレードする。

### 1.1 確定要件（ヒアリング結果）

| # | 項目 | 決定事項 |
|---|------|---------|
| 1 | 通知タイミング | フェーズ開始・Issue受付を追加（リマインドは不要） |
| 2 | フォーマット | リッチフォーマット（Header Block + Section + Fields） |
| 3 | メッセージ内容 | コスト・フェーズ名・アクション案内・Issueタイトル・エラー詳細を含める |
| 4 | 言語統一 | すべて日本語 |
| 5 | Slackスレッド | 不要（Webhook方式を維持） |
| 6 | フェーズ進捗 | フェーズ名のみ表示 |
| 7 | コスト表示 | フェーズ完了時のみ |
| 8 | エラー詳細 | 詳細表示＋考えられる原因の分析を含める |

### 1.2 スコープ外

- Slack Bot Token (`xoxb-`) への移行
- Slackスレッド対応（Issue単位のスレッドまとめ）
- 承認待ちリマインド通知
- Issue タイトルのキャッシュ機構
- 通知のON/OFF設定（設定ファイルで通知タイプ別に制御）
- DM通知（チャンネルではなく担当者への直接通知）

---

## 2. 現状分析

### 2.1 現在のアーキテクチャ

```
PhaseExecutor / Orchestrator
        │
        ▼
  NotifierProtocol.notify(message, level, metadata)
        │
        ▼
  SlackNotifier._build_payload()   ← section + context の2ブロック構成
        │
        ▼
  SlackNotifier.send() → Slack Webhook POST
```

### 2.2 現在の通知箇所（全18箇所）

| # | ファイル | タイミング | メッセージ | 問題点 |
|---|---------|-----------|-----------|--------|
| 1 | `orchestrator.py` | 起動時 | `"Orchestrator started"` | 英語 |
| 2 | `orchestrator.py` | イベントルーティングエラー | `"Event routing error: {exc}"` | 英語 |
| 3 | `orchestrator.py` | Issue中断時 | `"Issue #{n} suspended due to error: {error}"` | 英語 |
| 4 | `orchestrator.py` | ヘルスチェック失敗 | `"Health check failures: {names}"` | 英語 |
| 5 | `base.py` | タイムアウト | `"Issue #{n} がタイムアウトしました (phase: {p})"` | repo未設定 |
| 6 | `base.py` | エラー | `"Issue #{n} でエラー: {e} (phase: {p})"` | repo未設定、原因分析なし |
| 7 | `hearing.py` | 質問投稿後 | `"Issue #{n} に質問を投稿しました..."` | 開始通知なし |
| 8 | `analysis.py` | 方針投稿後 | `"Issue #{n} の修正方針を投稿しました..."` | 開始通知なし |
| 9 | `plan_brief.py` | 方針投稿後 | `"Issue #{n} の実装方針を投稿しました..."` | 開始通知なし |
| 10 | `design.py` | 設計PR作成後 | `"Issue #{n} の設計PR #{pr} を作成しました..."` | 開始通知なし |
| 11 | `design_revise.py` | 設計修正後 | `"Issue #{n} の設計書を修正しました"` | 開始通知なし |
| 12 | `implement.py` | 実装PR作成後 | `"Issue #{n} の実装PR #{pr} を作成しました"` | 開始通知なし |
| 13 | `fix.py` | 修正PR作成後 | `"Issue #{n} の修正PR #{pr} を作成しました..."` | 開始通知なし |
| 14 | `impl_revise.py` | 実装修正後 | `"Issue #{n} の実装を修正しました"` | 開始通知なし |
| 15 | `split.py` | 分割提案後 | `"Issue #{n} の分割を提案しました..."` | 開始通知なし |
| 16 | `split.py` | 分割完了 | `"Issue #{n} の分割が完了しました"` | |
| 17 | `done.py` | Issue完了 | `"Issue #{n} 完了しました"` | コスト情報なし |
| 18 | `done.py` | 連鎖開始 | `"Issue #{n} の処理を開始します (連鎖)"` | |

### 2.3 現状の課題まとめ

1. **絵文字が未活用**: 仕様書定義の `notification_type` 別絵文字（📋💬✏️🚀✅等）が未使用。3種類のレベル絵文字のみ
2. **フェーズ開始通知がない**: 完了時のみ通知。ユーザーは進捗が見えない
3. **Issue受付通知がない**: 新規Issue検出時の通知がない
4. **repo情報の欠落**: 多くのフェーズ通知で `repo` が metadata に含まれていない
5. **言語混在**: オーケストレーターは英語、フェーズは日本語
6. **アクション案内の不統一**: 次アクション（👍承認、レビュー等）が通知に含まれたり含まれなかったり
7. **コスト・所要時間なし**: 実行コスト情報がメッセージに含まれない
8. **Issueタイトル未表示**: Issue番号のみでタイトルが不明
9. **フォーマットが簡素**: section + context の2ブロック構成のみ
10. **エラー詳細が不十分**: エラーメッセージ1行のみで原因分析がない

---

## 3. 設計方針

### 3.1 設計原則

1. **後方互換性**: `notify()` の既存シグネチャは変更しない。新機能は metadata のキー追加で対応
2. **段階的改善**: まず `_build_payload()` のリッチ化 → 各呼び出し元のメッセージ・metadata 改善
3. **DRY**: 通知タイプ別のフォーマットロジックを `SlackNotifier` に集約
4. **best-effort維持**: 通知失敗は引き続きログのみ。例外は発生させない

### 3.2 変更対象ファイル

| ファイル | 変更内容 | 影響度 |
|---------|---------|--------|
| `notifications/slack.py` | フォーマット全面改修、通知タイプ別絵文字、リッチブロック構築 | **大** |
| `models.py` | `NotificationType` Enum 追加 | 小 |
| `phases/base.py` | フェーズ開始通知追加、エラー詳細改善、repo情報追加、ヘルパー追加 | 中 |
| `phases/hearing.py` | メッセージ改善、metadata充実 | 小 |
| `phases/analysis.py` | メッセージ改善、metadata充実 | 小 |
| `phases/plan_brief.py` | メッセージ改善、metadata充実 | 小 |
| `phases/design.py` | メッセージ改善、metadata充実 | 小 |
| `phases/design_revise.py` | メッセージ改善、metadata充実 | 小 |
| `phases/implement.py` | メッセージ改善、metadata充実 | 小 |
| `phases/fix.py` | メッセージ改善、metadata充実 | 小 |
| `phases/impl_revise.py` | メッセージ改善、metadata充実 | 小 |
| `phases/split.py` | メッセージ改善、metadata充実 | 小 |
| `phases/done.py` | メッセージ改善、metadata充実 | 小 |
| `orchestrator/orchestrator.py` | メッセージ日本語化、metadata充実、Issue受付通知追加 | 中 |
| `tests/unit/test_slack.py` | テスト全面更新 | 中 |
| `tests/unit/test_phases.py` | フェーズ開始通知のテスト追加 | 小 |
| `docs/specs/slack.md` | 仕様書更新 | 小 |

---

## 4. 詳細設計

### 4.1 NotificationType Enum 追加（models.py）

```python
class NotificationType(StrEnum):
    """Slack通知タイプ."""

    # システム系
    SYSTEM_START = "system_start"           # オーケストレーター起動
    SYSTEM_HEALTH = "system_health"         # ヘルスチェック失敗

    # Issue ライフサイクル
    ISSUE_RECEIVED = "issue_received"       # Issue受付
    ISSUE_DONE = "issue_done"               # Issue完了
    ISSUE_CHAIN = "issue_chain"             # 連鎖Issue開始

    # フェーズ進行
    PHASE_START = "phase_start"             # フェーズ開始
    PHASE_COMPLETE = "phase_complete"       # フェーズ完了

    # ユーザーアクション要求
    HEARING_QUESTION = "hearing_question"   # ヒアリング質問投稿
    PLAN_POSTED = "plan_posted"             # 方針投稿（承認待ち）
    DESIGN_PR_CREATED = "design_pr_created" # 設計PR作成（レビュー待ち）
    IMPL_PR_CREATED = "impl_pr_created"     # 実装PR作成（レビュー待ち）
    FIX_PR_CREATED = "fix_pr_created"       # 修正PR作成（レビュー待ち）
    SPLIT_PROPOSED = "split_proposed"       # 分割提案（承認待ち）
    DESIGN_REVISED = "design_revised"       # 設計修正（再レビュー待ち）
    IMPL_REVISED = "impl_revised"           # 実装修正（再レビュー待ち）
    SPLIT_DONE = "split_done"               # 分割完了

    # エラー系
    ERROR = "error"                         # 処理中エラー
    TIMEOUT = "timeout"                     # タイムアウト
    EVENT_ERROR = "event_error"             # イベントルーティングエラー
```

### 4.2 通知タイプ別絵文字マッピング（slack.py）

```python
_NOTIFICATION_TYPE_EMOJI: dict[str, str] = {
    # システム系
    "system_start": ":rocket:",
    "system_health": ":warning:",

    # Issue ライフサイクル
    "issue_received": ":new:",
    "issue_done": ":white_check_mark:",
    "issue_chain": ":link:",

    # フェーズ進行
    "phase_start": ":arrow_forward:",
    "phase_complete": ":ballot_box_with_check:",

    # ユーザーアクション要求
    "hearing_question": ":speech_balloon:",
    "plan_posted": ":clipboard:",
    "design_pr_created": ":pencil:",
    "impl_pr_created": ":rocket:",
    "fix_pr_created": ":wrench:",
    "split_proposed": ":scissors:",
    "design_revised": ":pencil:",
    "impl_revised": ":hammer_and_wrench:",
    "split_done": ":white_check_mark:",

    # エラー系
    "error": ":x:",
    "timeout": ":hourglass:",
    "event_error": ":rotating_light:",
}
```

### 4.3 リッチフォーマット設計

#### 4.3.1 通知カテゴリ別レイアウト

通知を3つのカテゴリに分け、それぞれ異なるレイアウトを適用する。

**A. ユーザーアクション要求系**（ヒアリング回答、方針承認、PRレビュー等）

```
┌─────────────────────────────────────────┐
│ 📝 Header: "Issue #42: 設計PR作成"       │
├─────────────────────────────────────────┤
│ ✏️ Issue #42 の設計PR #10 を作成しました   │
│                                         │
│ *Issueタイトル*: ログイン画面のリデザイン    │
├─────────────────────────────────────────┤
│ 📋 フェーズ: design                      │
│ ⏱️ 所要時間: 3分24秒                     │
│ 💰 コスト: $1.23                         │
├─────────────────────────────────────────┤
│ ─────────── divider ────────────         │
│ 👉 *次のアクション*: 設計PRをレビューして    │
│    approve してください                   │
├─────────────────────────────────────────┤
│ 📦 org/repo | 📄 Issue #42 | 📝 PR #10  │
└─────────────────────────────────────────┘
```

**B. 情報通知系**（フェーズ開始、完了、連鎖等）

```
┌─────────────────────────────────────────┐
│ ▶️ Issue #42: implement フェーズ開始      │
│                                         │
│ *Issueタイトル*: ログイン画面のリデザイン    │
├─────────────────────────────────────────┤
│ 📋 フェーズ: implement                   │
├─────────────────────────────────────────┤
│ 📦 org/repo | 📄 Issue #42              │
└─────────────────────────────────────────┘
```

**C. エラー系**（エラー、タイムアウト）

```
┌──────────────────────────────────────────┐
│ ❌ Header: "Issue #42: エラー発生"        │
├──────────────────────────────────────────┤
│ ❌ Issue #42 でエラーが発生しました         │
│                                          │
│ *Issueタイトル*: ログイン画面のリデザイン     │
├──────────────────────────────────────────┤
│ *エラー内容*:                              │
│ ```                                       │
│ No transition defined from Phase.DESIGN   │
│ to Phase.DESIGN                           │
│ ```                                       │
├──────────────────────────────────────────┤
│ *考えられる原因*:                           │
│ • ステートマシンの遷移定義に不足がある        │
│ • 同一フェーズへの再遷移ガードが必要          │
├──────────────────────────────────────────┤
│ 📋 フェーズ: design                        │
├──────────────────────────────────────────┤
│ 📦 org/repo | 📄 Issue #42               │
└──────────────────────────────────────────┘
```

#### 4.3.2 Block Kit ペイロード構築（_build_payload 改修）

```python
def _build_payload(
    self,
    message: str,
    *,
    channel: str | None,
    level: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """リッチフォーマットの Block Kit ペイロードを構築する."""
    metadata = metadata or {}
    notification_type = metadata.get("notification_type", "")
    emoji = self._resolve_emoji(notification_type, level)

    blocks: list[dict[str, Any]] = []

    # 1. Header Block（ユーザーアクション要求系・エラー系のみ）
    header_text = metadata.get("header")
    if header_text:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        })

    # 2. メインメッセージ Section
    main_text = f"{emoji} {message}"
    issue_title = metadata.get("issue_title")
    if issue_title:
        main_text += f"\n\n*Issueタイトル*: {issue_title}"
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": main_text},
    })

    # 3. エラー詳細 Section（エラー系のみ）
    error_detail = metadata.get("error_detail")
    if error_detail:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*エラー内容*:\n```{error_detail}```"},
        })
    error_analysis = metadata.get("error_analysis")
    if error_analysis:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*考えられる原因*:\n{error_analysis}"},
        })

    # 4. Fields Section（コスト・所要時間・フェーズ）
    fields = self._build_fields(metadata)
    if fields:
        blocks.append({
            "type": "section",
            "fields": fields,
        })

    # 5. アクション案内 Section（ユーザーアクション要求系のみ）
    next_action = metadata.get("next_action")
    if next_action:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"👉 *次のアクション*: {next_action}"},
        })

    # 6. Context Block（共通: repo, issue, PR リンク）
    context_text = self._build_context_text(metadata)
    if context_text:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": context_text}],
        })

    resolved_channel = channel or self._default_channel
    payload: dict[str, Any] = {"blocks": blocks}
    if resolved_channel is not None:
        payload["channel"] = resolved_channel
    return payload
```

#### 4.3.3 新規メソッド: 絵文字解決

```python
def _resolve_emoji(self, notification_type: str, level: str) -> str:
    """notification_type を優先し、fallback として level ベースの絵文字を返す.

    Args:
        notification_type: 通知タイプ文字列。
        level: 通知レベル ("info" | "error" | "critical")。

    Returns:
        Slack 絵文字コード。
    """
    if notification_type and notification_type in _NOTIFICATION_TYPE_EMOJI:
        return _NOTIFICATION_TYPE_EMOJI[notification_type]
    return _LEVEL_EMOJI.get(level, ":robot_face:")
```

#### 4.3.4 新規メソッド: Fields 構築

```python
@staticmethod
def _build_fields(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """metadata からフィールドブロック用のフィールドリストを構築する.

    Args:
        metadata: 付加情報辞書。

    Returns:
        Slack Block Kit fields 用の辞書リスト。空の場合もある。
    """
    fields: list[dict[str, Any]] = []

    phase = metadata.get("phase")
    if phase:
        fields.append({
            "type": "mrkdwn",
            "text": f"*フェーズ*\n{phase}",
        })

    duration_sec = metadata.get("duration_sec")
    if duration_sec is not None:
        minutes, seconds = divmod(int(duration_sec), 60)
        time_str = f"{minutes}分{seconds}秒" if minutes else f"{seconds}秒"
        fields.append({
            "type": "mrkdwn",
            "text": f"*所要時間*\n⏱️ {time_str}",
        })

    cost_usd = metadata.get("cost_usd")
    if cost_usd is not None:
        fields.append({
            "type": "mrkdwn",
            "text": f"*コスト*\n💰 ${cost_usd:.2f}",
        })

    return fields
```

### 4.4 metadata キーの拡張

現在の metadata キーに加え、以下を新規追加する:

| キー | 型 | 説明 | 使用場面 |
|------|-----|------|---------|
| `notification_type` | `str` | 通知タイプ（既存だが未活用→活用開始） | 全通知 |
| `issue_title` | `str` | Issueタイトル | 全Issue関連通知 |
| `header` | `str` | Headerブロック用テキスト | アクション要求系・エラー系 |
| `next_action` | `str` | 次アクション案内テキスト | アクション要求系 |
| `cost_usd` | `float` | 実行コスト（USD） | フェーズ完了時 |
| `duration_sec` | `float` | 所要時間（秒） | フェーズ完了時 |
| `error_detail` | `str` | エラーの詳細情報 | エラー系 |
| `error_analysis` | `str` | 考えられる原因の分析 | エラー系 |

既存キー（`repo`, `issue`, `pr`, `pr_url`, `phase`, `error`）は引き続き利用。

### 4.5 フェーズ開始通知の追加（base.py）

`PhaseExecutor.execute()` テンプレートメソッド内に開始通知を追加:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        # ★ 新規: フェーズ開始通知
        repo_str = self._get_repo_str(request.repo)
        issue_title = await self._get_issue_title(request)
        await self._notifier.notify(
            f"Issue #{request.issue_number}: {request.phase} フェーズを開始しました",
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
        # ... (以降は既存のまま)
```

### 4.6 ヘルパーメソッドの追加（base.py）

```python
def _get_repo_str(self, repo: object) -> str:
    """リポジトリオブジェクトから 'owner/repo' 文字列を取得する.

    Args:
        repo: リポジトリ設定オブジェクト。

    Returns:
        'owner/repo' 形式の文字列。取得できない場合は空文字列。
    """
    owner = getattr(repo, "owner", "")
    repo_name = getattr(repo, "repo", "")
    if owner and repo_name:
        return f"{owner}/{repo_name}"
    return ""

async def _get_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する.

    Args:
        request: タスクリクエスト。

    Returns:
        Issueタイトル。取得失敗時は空文字列。
    """
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        logger.warning("Failed to get issue title for #%d", request.issue_number)
        return ""
```

### 4.7 エラー原因分析ロジック（base.py）

```python
@staticmethod
def _analyze_error(error: Exception, phase: str) -> str:
    """エラーの考えられる原因を分析する.

    Args:
        error: 発生した例外。
        phase: エラー発生時のフェーズ。

    Returns:
        考えられる原因のマークダウンテキスト（箇条書き）。
    """
    error_str = str(error)
    causes: list[str] = []

    # ステートマシン遷移エラー
    if "No transition defined" in error_str or "transition" in error_str.lower():
        causes.append("ステートマシンの遷移定義に不足がある可能性があります")
        causes.append("同一フェーズへの再遷移が試行されている可能性があります")

    # 認証エラー
    elif "401" in error_str or "403" in error_str or "auth" in error_str.lower():
        causes.append("GitHub トークンが期限切れまたは権限不足の可能性があります")
        causes.append("`credential` の設定を確認してください")

    # Git 関連
    elif "git" in error_str.lower() or "conflict" in error_str.lower():
        causes.append("Gitの競合が発生している可能性があります")
        causes.append("worktreeのクリーンアップが必要な可能性があります")

    # タイムアウト関連
    elif "timeout" in error_str.lower():
        causes.append("エージェント実行が制限時間を超過しました")
        causes.append(f"`PHASE_CONFIG['{phase}'].timeout_sec` の調整を検討してください")

    # PR関連
    elif "pr" in error_str.lower() or "pull request" in error_str.lower():
        causes.append("PR作成/検索に失敗しています")
        causes.append("ブランチが正しくpushされていない可能性があります")

    # API レート制限
    elif "rate limit" in error_str.lower() or "429" in error_str:
        causes.append("GitHub API のレート制限に達しています")
        causes.append("しばらく待ってからリトライしてください")

    # デフォルト
    if not causes:
        causes.append("予期しないエラーです。ログを確認してください")
        causes.append(f"フェーズ `{phase}` の実行中に発生しました")

    return "\n".join(f"• {c}" for c in causes)
```

### 4.8 エラー通知の改善（base.py）

#### _handle_error 改修

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
    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    repo_str = self._get_repo_str(request.repo)
    issue_title = await self._get_issue_title(request)
    error_detail = "".join(
        traceback.format_exception(type(error), error, error.__traceback__)
    )
    # スタックトレースが長すぎる場合は末尾を切り詰め
    if len(error_detail) > 1500:
        error_detail = error_detail[:1500] + "\n... (truncated)"
    error_analysis = self._analyze_error(error, str(request.phase))

    await self._notifier.notify(
        f"Issue #{request.issue_number} でエラーが発生しました",
        level="error",
        metadata={
            "notification_type": "error",
            "repo": repo_str,
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": str(request.phase),
            "header": f"Issue #{request.issue_number}: エラー発生",
            "error_detail": str(error),
            "error_analysis": error_analysis,
        },
    )
```

#### _handle_timeout 改修

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

    repo_str = self._get_repo_str(request.repo)
    issue_title = await self._get_issue_title(request)

    await self._notifier.notify(
        f"Issue #{request.issue_number} の {request.phase} フェーズがタイムアウトしました",
        level="error",
        metadata={
            "notification_type": "timeout",
            "repo": repo_str,
            "issue": request.issue_number,
            "issue_title": issue_title,
            "phase": str(request.phase),
            "header": f"Issue #{request.issue_number}: タイムアウト",
            "error_detail": f"{request.phase} フェーズが制限時間を超過しました",
            "error_analysis": (
                f"• エージェント実行が制限時間を超過しました\n"
                f"• `PHASE_CONFIG['{request.phase}'].timeout_sec` の調整を検討してください"
            ),
        },
    )
```

### 4.9 各フェーズの通知メッセージ改善

#### 4.9.1 共通パターン

全フェーズで以下のパターンに統一する。`process_result()` 内の `notify()` 呼び出しで
repo, issue_title, notification_type, cost_usd, duration_sec, header, next_action を設定する。

```python
# process_result() 内の共通パターン例
repo_str = self._get_repo_str(request.repo)
issue_title = await self._get_issue_title(request)

await self._notifier.notify(
    f"Issue #{request.issue_number} の設計PR #{pr_number} を作成しました。レビューをお願いします",
    metadata={
        "notification_type": "design_pr_created",
        "repo": repo_str,
        "issue": request.issue_number,
        "issue_title": issue_title,
        "pr": pr_number,
        "pr_url": f"https://github.com/{repo_str}/pull/{pr_number}",
        "phase": str(request.phase),
        "cost_usd": result.cost_usd,
        "duration_sec": result.duration_sec,
        "header": f"Issue #{request.issue_number}: 設計PR作成",
        "next_action": "設計PRをレビューして approve してください",
    },
)
```

#### 4.9.2 各フェーズの通知定義一覧

| フェーズ | notification_type | メッセージ | next_action | header |
|---------|------------------|-----------|-------------|--------|
| hearing | `hearing_question` | `Issue #{n} に質問を投稿しました。回答をお願いします` | `Issueコメントで回答してください` | `Issue #{n}: ヒアリング質問` |
| analysis | `plan_posted` | `Issue #{n} の修正方針を投稿しました` | `👍リアクションで承認、修正はコメントで指摘してください` | `Issue #{n}: 修正方針投稿` |
| plan_brief | `plan_posted` | `Issue #{n} の実装方針を投稿しました` | `👍リアクションで承認、修正はコメントで指摘してください` | `Issue #{n}: 実装方針投稿` |
| design | `design_pr_created` | `Issue #{n} の設計PR #{pr} を作成しました` | `設計PRをレビューして approve してください` | `Issue #{n}: 設計PR作成` |
| design_revise | `design_revised` | `Issue #{n} の設計書を修正しました` | `設計PRで再レビューをお願いします` | `Issue #{n}: 設計修正` |
| implement | `impl_pr_created` | `Issue #{n} の実装PR #{pr} を作成しました` | `実装PRをレビューして approve してください` | `Issue #{n}: 実装PR作成` |
| fix | `fix_pr_created` | `Issue #{n} の修正PR #{pr} を作成しました` | `修正PRをレビューして approve してください` | `Issue #{n}: 修正PR作成` |
| impl_revise | `impl_revised` | `Issue #{n} の実装を修正しました` | `実装PRで再レビューをお願いします` | `Issue #{n}: 実装修正` |
| split (提案) | `split_proposed` | `Issue #{n} の分割を提案しました` | `👍リアクションで承認、修正はコメントで指示してください` | `Issue #{n}: 分割提案` |
| split (完了) | `split_done` | `Issue #{n} の分割が完了しました` | _(なし)_ | `Issue #{n}: 分割完了` |
| done | `issue_done` | `Issue #{n} が完了しました` | _(なし)_ | `Issue #{n}: 完了` |

### 4.10 オーケストレーターの通知改善（orchestrator.py）

すべてのメッセージを日本語に統一し、metadata を充実させる。

```python
# 起動時
await self._notifier.notify(
    "オーケストレーターを起動しました",
    level="info",
    metadata={
        "notification_type": "system_start",
        "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
        "header": "オーケストレーター起動",
    },
)

# イベントルーティングエラー
await self._notifier.notify(
    f"イベントルーティングでエラーが発生しました: {exc}",
    level="error",
    metadata={
        "notification_type": "event_error",
        "header": "イベントルーティングエラー",
        "error_detail": str(exc),
    },
)

# Issue中断時
await self._notifier.notify(
    f"Issue #{issue_number} をエラーにより中断しました",
    level="error",
    metadata={
        "notification_type": "error",
        "repo": repo_str,
        "issue": issue_number,
        "header": f"Issue #{issue_number}: 中断",
        "error_detail": str(error),
    },
)

# ヘルスチェック失敗
await self._notifier.notify(
    f"ヘルスチェック失敗: {', '.join(unhealthy)}",
    level="error",
    metadata={
        "notification_type": "system_health",
        "header": "ヘルスチェック失敗",
        "error_detail": f"異常検知: {', '.join(unhealthy)}",
    },
)
```

### 4.11 Issue受付通知の追加（orchestrator.py）

`EventRouter` で `NEW_ISSUE` イベント処理時に通知を追加:

```python
# NEW_ISSUE イベント処理内
await self._notifier.notify(
    f"Issue #{issue_number} を受け付けました",
    metadata={
        "notification_type": "issue_received",
        "repo": f"{repo.owner}/{repo.repo}",
        "issue": issue_number,
        "issue_title": issue_title,
        "header": f"Issue #{issue_number}: 新規Issue受付",
    },
)
```

---

## 5. ペイロード例

### 5.1 フェーズ開始通知（情報通知系）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":arrow_forward: Issue #42: implement フェーズを開始しました\n\n*Issueタイトル*: ログイン画面のリデザイン"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*フェーズ*\nimplement"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42>"
                }
            ]
        }
    ]
}
```

### 5.2 設計PR作成通知（ユーザーアクション要求系）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Issue #42: 設計PR作成", "emoji": true}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":pencil: Issue #42 の設計PR #10 を作成しました。レビューをお願いします\n\n*Issueタイトル*: ログイン画面のリデザイン"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*フェーズ*\ndesign"},
                {"type": "mrkdwn", "text": "*所要時間*\n⏱️ 3分24秒"},
                {"type": "mrkdwn", "text": "*コスト*\n💰 $1.23"}
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "👉 *次のアクション*: 設計PRをレビューして approve してください"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42> | :memo: <https://github.com/org/repo/pull/10|PR #10>"
                }
            ]
        }
    ]
}
```

### 5.3 エラー通知（エラー系）

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Issue #42: エラー発生", "emoji": true}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":x: Issue #42 でエラーが発生しました\n\n*Issueタイトル*: ログイン画面のリデザイン"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*エラー内容*:\n```No transition defined from Phase.DESIGN to Phase.DESIGN```"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*考えられる原因*:\n• ステートマシンの遷移定義に不足がある可能性があります\n• 同一フェーズへの再遷移が試行されている可能性があります"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": "*フェーズ*\ndesign"}
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42>"
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
    "blocks": [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Issue #42: 完了", "emoji": true}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: Issue #42 が完了しました\n\n*Issueタイトル*: ログイン画面のリデザイン"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/42|Issue #42>"
                }
            ]
        }
    ]
}
```

### 5.5 後方互換（metadata なし）

```json
{
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":robot_face: シンプルなメッセージ"
            }
        }
    ]
}
```

---

## 6. 実装計画

### ステップ1: SlackNotifier コア改修（slack.py）
1. `_NOTIFICATION_TYPE_EMOJI` 辞書を追加
2. `_resolve_emoji()` メソッドを追加
3. `_build_fields()` メソッドを追加
4. `_build_payload()` をリッチフォーマット対応に改修
5. `_build_context_text()` は既存ロジックを維持（後方互換）

### ステップ2: models.py に NotificationType 追加
1. `NotificationType` StrEnum を追加

### ステップ3: base.py 改修
1. `_get_repo_str()` ヘルパーメソッド追加
2. `_get_issue_title()` ヘルパーメソッド追加
3. `_analyze_error()` 静的メソッド追加
4. `execute()` にフェーズ開始通知を追加
5. `_handle_error()` をリッチ通知に改修
6. `_handle_timeout()` をリッチ通知に改修

### ステップ4: 各フェーズの通知改善
1. `hearing.py` - notification_type, repo, issue_title, next_action, cost_usd, duration_sec 追加
2. `analysis.py` - 同上
3. `plan_brief.py` - 同上
4. `design.py` - 同上
5. `design_revise.py` - 同上
6. `implement.py` - 同上
7. `fix.py` - 同上
8. `impl_revise.py` - 同上
9. `split.py` - 同上
10. `done.py` - 同上

### ステップ5: orchestrator.py 改修
1. 起動メッセージを日本語化
2. イベントルーティングエラーを日本語化
3. Issue中断メッセージを日本語化
4. ヘルスチェック失敗メッセージを日本語化
5. Issue受付通知を追加

### ステップ6: テスト更新（カバレッジ率100%目標）
1. `test_slack.py` - リッチフォーマットのテスト追加
   - TC-SL-14: notification_type 別絵文字テスト（全19タイプ網羅）
   - TC-SL-15: Header ブロックが含まれることのテスト（header あり/なし）
   - TC-SL-16: Fields ブロック（phase のみ / duration_sec のみ / cost_usd のみ / 全組み合わせ / 空）
   - TC-SL-17: next_action セクションテスト（あり/なし、divider の有無）
   - TC-SL-18: error_detail + error_analysis テスト（両方あり / error_detail のみ / error_analysis のみ / 両方なし）
   - TC-SL-19: issue_title がメインテキストに含まれるテスト（あり/なし）
   - TC-SL-20: _resolve_emoji の優先度テスト（notification_type 優先 / level フォールバック / 両方未指定時デフォルト）
   - TC-SL-21: _build_fields のテスト（duration_sec の分秒変換: 0秒 / 59秒 / 60秒 / 複数分）
   - TC-SL-22: metadata なしの後方互換テスト（metadata=None / metadata={} / notification_type 未指定）
   - TC-SL-23: _build_context_text テスト（repo のみ / repo+issue / repo+issue+pr / 全なし）
   - TC-SL-24: channel 解決テスト（明示指定 / デフォルト / 両方 None）
   - TC-SL-25: 全通知カテゴリのペイロード構造検証（ユーザーアクション要求系 / 情報通知系 / エラー系）
   - TC-SL-26: _NOTIFICATION_TYPE_EMOJI に未登録のタイプが渡された場合の fallback テスト
2. `test_phases.py` - フェーズ通知のテスト追加（カバレッジ100%）
   - TC-PH-01: フェーズ開始通知が送信されることのテスト（metadata の全キー検証）
   - TC-PH-02: フェーズ開始通知で `_get_issue_title()` が失敗した場合に空文字列で通知が送信されること
   - TC-PH-03: `_get_repo_str()` テスト（owner/repo 正常 / owner 欠落 / repo 欠落 / 両方欠落）
   - TC-PH-04: `_get_issue_title()` テスト（正常取得 / 例外発生時に空文字列）
   - TC-PH-05: `_analyze_error()` テスト（遷移エラー / 認証エラー / Git エラー / タイムアウト / PR エラー / レート制限 / 不明エラー）
   - TC-PH-06: `_handle_error()` テスト（リッチ通知の metadata 全キー検証、スタックトレース切り詰め検証）
   - TC-PH-07: `_handle_error()` でスタックトレースが1500文字超の場合に切り詰めされること
   - TC-PH-08: `_handle_timeout()` テスト（リッチ通知の metadata 全キー検証）
   - TC-PH-09: `_handle_timeout()` でセッションIDがある場合に interrupt が呼ばれること
   - TC-PH-10: `_handle_timeout()` でセッションIDがない場合に interrupt が呼ばれないこと
   - TC-PH-11: `_handle_error()` でラベル更新失敗時もログ出力して通知が継続されること
   - TC-PH-12: `_handle_timeout()` でラベル更新失敗時もログ出力して通知が継続されること
3. `test_orchestrator.py` - オーケストレーター通知のテスト追加（カバレッジ100%）
   - TC-OR-01: 起動通知が日本語で送信されること（metadata の notification_type, repos, header 検証）
   - TC-OR-02: イベントルーティングエラー通知のテスト（metadata の notification_type, header, error_detail 検証）
   - TC-OR-03: Issue中断通知のテスト（metadata の notification_type, repo, issue, header, error_detail 検証）
   - TC-OR-04: ヘルスチェック失敗通知のテスト（metadata の notification_type, header, error_detail 検証）
   - TC-OR-05: Issue受付通知のテスト（metadata の notification_type, repo, issue, issue_title, header 検証）
4. `test_phase_notifications.py` - 各フェーズの通知メッセージ検証（カバレッジ100%）
   - TC-PN-01〜10: 各フェーズ（hearing, analysis, plan_brief, design, design_revise, implement, fix, impl_revise, split, done）の `process_result()` で正しい notification_type, メッセージ, next_action, header, repo, issue_title, cost_usd, duration_sec が設定されること
   - TC-PN-11: split フェーズの分割提案時と分割完了時で異なる notification_type が使われること
   - TC-PN-12: done フェーズで連鎖Issue開始時に issue_chain タイプが使われること

### ステップ7: 仕様書更新
1. `docs/specs/slack.md` を新フォーマットに合わせて更新

---

## 7. テスト方針（カバレッジ率100%目標）

本改修では、変更対象のすべてのメソッド・分岐・パスに対してテストを作成し、**カバレッジ率100%**を目指す。

### 7.1 カバレッジ対象と戦略

| 対象ファイル | テストファイル | カバレッジ目標 | 戦略 |
|------------|-------------|-------------|------|
| `notifications/slack.py` | `test_slack.py` | 100% | 全メソッド・全分岐を網羅。既存TC-SL-01〜13 + 新規TC-SL-14〜26 |
| `phases/base.py` | `test_phases.py` | 100% | 新規メソッド3つ + 改修メソッド3つの全分岐。TC-PH-01〜12 |
| `orchestrator/orchestrator.py` | `test_orchestrator.py` | 100% | 全通知箇所5箇所の metadata 検証。TC-OR-01〜05 |
| 各フェーズファイル（10ファイル） | `test_phase_notifications.py` | 100% | 各フェーズの process_result() 内 notify 呼び出し検証。TC-PN-01〜12 |
| `models.py` | `test_models.py` | 100% | NotificationType Enum の全メンバーが正しい値を持つことを検証 |

### 7.2 SlackNotifier テスト詳細（test_slack.py）

#### 7.2.1 `_resolve_emoji()` の全分岐テスト

| TC | 入力 | 期待値 | カバレッジ |
|----|------|--------|-----------|
| TC-SL-20a | notification_type="system_start", level="info" | `:rocket:` | notification_type 優先パス |
| TC-SL-20b | notification_type="", level="error" | `:x:` | level フォールバックパス |
| TC-SL-20c | notification_type=None, level="info" | `:information_source:` | notification_type が falsy パス |
| TC-SL-20d | notification_type="unknown_type", level="info" | `:information_source:` | 未登録タイプのフォールバック |
| TC-SL-20e | notification_type="", level="unknown" | `:robot_face:` | level も未登録時のデフォルト |

#### 7.2.2 `_build_fields()` の全分岐テスト

| TC | 入力metadata | 期待値 | カバレッジ |
|----|-------------|--------|-----------|
| TC-SL-21a | `{"phase": "design"}` | fields に phase のみ | phase のみ分岐 |
| TC-SL-21b | `{"duration_sec": 45}` | `"45秒"` | 60秒未満（分なし）分岐 |
| TC-SL-21c | `{"duration_sec": 204}` | `"3分24秒"` | 60秒以上（分あり）分岐 |
| TC-SL-21d | `{"duration_sec": 60}` | `"1分0秒"` | ちょうど60秒の境界値 |
| TC-SL-21e | `{"cost_usd": 1.5}` | `"$1.50"` | cost_usd のみ分岐 |
| TC-SL-21f | `{"phase": "design", "duration_sec": 204, "cost_usd": 1.23}` | 3フィールド | 全フィールド分岐 |
| TC-SL-21g | `{}` | 空リスト | フィールドなし分岐 |
| TC-SL-21h | `{"duration_sec": 0}` | `"0秒"` | duration_sec が0（None ではない）分岐 |
| TC-SL-21i | `{"cost_usd": 0.0}` | `"$0.00"` | cost_usd が0（None ではない）分岐 |

#### 7.2.3 `_build_payload()` の全分岐テスト

| TC | 条件 | 検証内容 | カバレッジ |
|----|------|---------|-----------|
| TC-SL-14 | 全19種の notification_type | 各タイプに対応する絵文字がメインテキストに含まれる | 絵文字マッピング全網羅 |
| TC-SL-15a | header あり | Header ブロックが blocks[0] に含まれる | header 分岐 true |
| TC-SL-15b | header なし | Header ブロックが含まれない | header 分岐 false |
| TC-SL-16 | fields 構成パターン | fields セクションの有無と内容 | fields 分岐 |
| TC-SL-17a | next_action あり | divider + next_action セクションが含まれる | next_action 分岐 true |
| TC-SL-17b | next_action なし | divider も next_action も含まれない | next_action 分岐 false |
| TC-SL-18a | error_detail + error_analysis 両方あり | 両セクション含まれる | エラー分岐 both |
| TC-SL-18b | error_detail のみ | error_detail セクションのみ | エラー分岐 detail only |
| TC-SL-18c | error_analysis のみ | error_analysis セクションのみ | エラー分岐 analysis only |
| TC-SL-18d | 両方なし | エラーセクションなし | エラー分岐 none |
| TC-SL-19a | issue_title あり | メインテキストに `*Issueタイトル*:` が含まれる | issue_title 分岐 true |
| TC-SL-19b | issue_title なし | メインテキストに `*Issueタイトル*:` が含まれない | issue_title 分岐 false |
| TC-SL-22a | metadata=None | section + 絵文字のみのシンプル構成 | 後方互換 null |
| TC-SL-22b | metadata={} | section + 絵文字のみのシンプル構成 | 後方互換 empty |
| TC-SL-23a | repo のみ | context に repo 表示 | context repo only |
| TC-SL-23b | repo + issue | context に repo と issue リンク | context repo+issue |
| TC-SL-23c | repo + issue + pr | context に repo, issue, PR リンク | context 全表示 |
| TC-SL-23d | 全なし | context ブロックなし | context なし |
| TC-SL-24a | channel 明示指定 | payload に指定 channel | channel 明示 |
| TC-SL-24b | channel=None, デフォルトあり | payload にデフォルト channel | channel デフォルト |
| TC-SL-24c | channel=None, デフォルト=None | payload に channel なし | channel なし |
| TC-SL-25a | ユーザーアクション要求系フルセット | header + main + fields + divider + next_action + context | カテゴリA全体 |
| TC-SL-25b | 情報通知系フルセット | main + fields + context（header なし） | カテゴリB全体 |
| TC-SL-25c | エラー系フルセット | header + main + error_detail + error_analysis + fields + context | カテゴリC全体 |

### 7.3 base.py テスト詳細（test_phases.py）

#### 7.3.1 `_get_repo_str()` の全分岐テスト

| TC | 入力 | 期待値 | カバレッジ |
|----|------|--------|-----------|
| TC-PH-03a | owner="org", repo="repo" | `"org/repo"` | 正常パス |
| TC-PH-03b | owner="", repo="repo" | `""` | owner 欠落 |
| TC-PH-03c | owner="org", repo="" | `""` | repo 欠落 |
| TC-PH-03d | owner="", repo="" | `""` | 両方欠落 |
| TC-PH-03e | owner 属性なし | `""` | getattr フォールバック |

#### 7.3.2 `_get_issue_title()` の全分岐テスト

| TC | 条件 | 期待値 | カバレッジ |
|----|------|--------|-----------|
| TC-PH-04a | API正常応答 | Issueタイトル文字列 | 正常パス |
| TC-PH-04b | API例外発生 | `""` | except パス + logger.warning 呼び出し |

#### 7.3.3 `_analyze_error()` の全分岐テスト

| TC | エラーメッセージ | 期待マッチ | カバレッジ |
|----|---------------|-----------|-----------|
| TC-PH-05a | `"No transition defined"` | 遷移定義不足 + 再遷移 | 遷移エラー分岐 |
| TC-PH-05b | `"transition failed"` | 遷移定義不足 + 再遷移 | 遷移エラー分岐（lower） |
| TC-PH-05c | `"HTTP 401 Unauthorized"` | トークン期限切れ + credential確認 | 認証エラー 401 |
| TC-PH-05d | `"HTTP 403 Forbidden"` | トークン期限切れ + credential確認 | 認証エラー 403 |
| TC-PH-05e | `"auth token invalid"` | トークン期限切れ + credential確認 | 認証エラー auth |
| TC-PH-05f | `"git push failed"` | Git競合 + worktree | Git 分岐 |
| TC-PH-05g | `"merge conflict detected"` | Git競合 + worktree | conflict 分岐 |
| TC-PH-05h | `"operation timeout"` | 制限時間超過 + PHASE_CONFIG | タイムアウト分岐 |
| TC-PH-05i | `"PR creation failed"` | PR失敗 + ブランチpush | PR 分岐 |
| TC-PH-05j | `"pull request not found"` | PR失敗 + ブランチpush | pull request 分岐 |
| TC-PH-05k | `"rate limit exceeded"` | レート制限 + リトライ | レート制限分岐 |
| TC-PH-05l | `"HTTP 429"` | レート制限 + リトライ | 429 分岐 |
| TC-PH-05m | `"unexpected error xyz"` | 予期しないエラー + フェーズ情報 | デフォルト分岐 |

#### 7.3.4 `_handle_error()` の全分岐テスト

| TC | 条件 | 検証内容 | カバレッジ |
|----|------|---------|-----------|
| TC-PH-06a | 正常系 | suspended 遷移 + コメント + notify の metadata 全キー | メインパス |
| TC-PH-06b | ラベル更新失敗 | logger.warning + 処理継続 | except 分岐 |
| TC-PH-07a | スタックトレース 1500文字以下 | 切り詰めなし | len <= 1500 分岐 |
| TC-PH-07b | スタックトレース 1500文字超 | `"... (truncated)"` 付加 | len > 1500 分岐 |

#### 7.3.5 `_handle_timeout()` の全分岐テスト

| TC | 条件 | 検証内容 | カバレッジ |
|----|------|---------|-----------|
| TC-PH-08 | 正常系 | suspended 遷移 + notify の metadata 全キー | メインパス |
| TC-PH-09 | session_id あり | `_runner.interrupt()` が呼ばれる | session_id 分岐 true |
| TC-PH-10 | session_id なし | `_runner.interrupt()` が呼ばれない | session_id 分岐 false |
| TC-PH-12 | ラベル更新失敗 | logger.warning + 処理継続 | except 分岐 |

#### 7.3.6 `execute()` フェーズ開始通知テスト

| TC | 条件 | 検証内容 | カバレッジ |
|----|------|---------|-----------|
| TC-PH-01 | 正常実行 | notify に notification_type="phase_start", repo, issue, issue_title, phase が渡される | 開始通知パス |
| TC-PH-02 | _get_issue_title() 失敗 | issue_title="" で通知が送信される | 例外時フォールバック |

### 7.4 オーケストレーター テスト詳細（test_orchestrator.py）

| TC | 通知箇所 | 検証内容 |
|----|---------|---------|
| TC-OR-01 | 起動通知 | メッセージが日本語、notification_type="system_start"、repos リスト、header |
| TC-OR-02 | イベントルーティングエラー | メッセージが日本語、notification_type="event_error"、header、error_detail |
| TC-OR-03 | Issue中断 | メッセージが日本語、notification_type="error"、repo、issue、header、error_detail |
| TC-OR-04 | ヘルスチェック失敗 | メッセージが日本語、notification_type="system_health"、header、error_detail |
| TC-OR-05 | Issue受付 | メッセージが日本語、notification_type="issue_received"、repo、issue、issue_title、header |

### 7.5 各フェーズ通知テスト詳細（test_phase_notifications.py）

各フェーズの `process_result()` 内の `notify()` 呼び出しで、以下の全キーが正しく設定されることを検証する:

| TC | フェーズ | 検証する metadata キー |
|----|---------|---------------------|
| TC-PN-01 | hearing | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-02 | analysis | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-03 | plan_brief | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-04 | design | notification_type, repo, issue, issue_title, pr, pr_url, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-05 | design_revise | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-06 | implement | notification_type, repo, issue, issue_title, pr, pr_url, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-07 | fix | notification_type, repo, issue, issue_title, pr, pr_url, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-08 | impl_revise | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-09 | split（提案） | notification_type, repo, issue, issue_title, phase, cost_usd, duration_sec, header, next_action |
| TC-PN-10 | split（完了） | notification_type, repo, issue, issue_title, phase, header |
| TC-PN-11 | done | notification_type, repo, issue, issue_title, phase, header |
| TC-PN-12 | done（連鎖） | notification_type="issue_chain", repo, issue, issue_title |

### 7.6 models.py テスト（test_models.py）

| TC | 検証内容 |
|----|---------|
| TC-MD-01 | NotificationType の全メンバー数が19であること |
| TC-MD-02 | 各メンバーの値が文字列として正しいこと（StrEnum の動作検証） |
| TC-MD-03 | NotificationType が StrEnum を継承していること |

### 7.7 後方互換テスト

- 既存の13テストケース（TC-SL-01〜TC-SL-13）が**すべてそのままパス**することを確認
- 新テストは既存テストとは独立して追加（既存テストの修正は最小限に留める）

### 7.8 統合テスト

- 実際の Slack Webhook にテストメッセージを送信し、表示を目視確認（手動）
- 全3カテゴリ（ユーザーアクション要求系・情報通知系・エラー系）のレイアウトを確認

### 7.9 カバレッジ計測

- `pytest --cov=notifications --cov=phases --cov=orchestrator --cov-report=term-missing` で計測
- カバレッジ率100%未達の場合は、未カバーの行を特定し追加テストを作成
- CI パイプラインに `--cov-fail-under=100` を設定し、カバレッジ低下を防止

---

## 8. リスクと対策

| リスク | 影響 | 対策 |
|-------|------|------|
| `_get_issue_title()` のAPI呼び出しが通知速度を低下させる | 通知遅延 | best-effort で失敗時は空文字列。キャッシュは将来対応 |
| Block Kit のブロック数制限に抵触 | 通知失敗 | Slack制限は最大50ブロック。本設計では最大7ブロック程度のため問題なし |
| エラー原因分析が的外れな場合がある | ユーザー混乱 | 「考えられる原因」として可能性を列挙。断定しない表現を使用 |
| 既存テストの破損 | CI失敗 | `_build_payload()` の後方互換を維持。新フィールドは追加のみ |
| フェーズ開始通知で通知量が倍増 | Slackチャンネルのノイズ増加 | 開始通知はシンプルなレイアウト（Header なし）で情報量を抑制 |
| スタックトレースがSlackメッセージ長制限を超える | 通知失敗 | 1500文字で切り詰め処理を入れる |
