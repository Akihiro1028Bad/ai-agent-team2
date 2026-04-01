# 実装計画: Issue #36 Slackメッセージの改善

## 1. 変更ファイル一覧と依存関係

### 依存関係グラフ

```
Step 1: notifications/slack.py (本体改修 - 他の全変更の前提)
  ↓
Step 2: tests/unit/test_slack.py (Step 1 のテスト)
  ↓
Step 3: phases/base.py (フェーズ開始通知・エラー/タイムアウト metadata 拡充)
  ↓
Step 4: 各フェーズファイル (並行して変更可能)
  ├── phases/hearing.py
  ├── phases/analysis.py
  ├── phases/plan_brief.py
  ├── phases/design.py
  ├── phases/design_revise.py
  ├── phases/implement.py
  ├── phases/impl_revise.py
  ├── phases/fix.py
  ├── phases/done.py
  └── phases/split.py
  ↓
Step 5: orchestrator/orchestrator.py (受付確認通知・既存通知 metadata 拡充)
  ↓
Step 6: poller/event_router.py (承認後再開通知)
  ↓
Step 7: docs/specs/slack.md (仕様書更新)
```

---

## 2. Step 1: `notifications/slack.py` — SlackNotifier 本体改修

### 2.1 新規定数の追加

ファイル先頭 (`_LEVEL_EMOJI` の後) に以下を追加:

```python
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
    "receipt": "📥 Issue受付",
    "phase_start": "▶️ フェーズ開始",
    "approval_accepted": "👍 承認確認",
    "hearing_question": "💬 ヒアリング質問",
    "design_pr_created": "📝 設計PR作成",
    "impl_pr_created": "🚀 実装PR作成",
    "fix_pr_created": "🔧 修正PR作成",
    "plan_posted": "📋 方針投稿",
    "design_revised": "📝 設計修正完了",
    "impl_revised": "📝 実装修正完了",
    "split_proposal": "✂️ 分割提案",
    "split_complete": "✅ 分割完了",
    "done": "✅ 処理完了",
    "chain_start": "🔗 連鎖起動",
    "impl_continuation": "🔄 実装継続",
    "error": "❌ エラー発生",
    "timeout": "⏳ タイムアウト",
    "health_check": "🩺 ヘルスチェック異常",
    "system_start": "🤖 システム起動",
    "system_error": "⚠️ システムエラー",
    "suspended": "⏸️ 一時停止",
}

_PHASE_SEQUENCES: dict[str, list[str]] = {
    "bug": ["type-detection", "analysis", "plan-review", "fix", "impl-review", "done"],
    "feature-s": ["type-detection", "plan-brief", "plan-review", "implement", "impl-review", "done"],
    "feature-m": [
        "type-detection", "hearing", "design", "design-review",
        "planning", "implement", "impl-review", "done",
    ],
    "feature-l": [
        "type-detection", "hearing", "design", "design-review",
        "planning", "split-proposal", "split-execute", "done",
    ],
}
```

### 2.2 新規ユーティリティ関数（モジュールレベル）

```python
def _format_duration(seconds: float) -> str:
    """秒数を人間可読な形式にフォーマットする."""
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
    """進捗サマリを計算する。タイプ未確定の場合は None."""
    seq = _PHASE_SEQUENCES.get(issue_type)
    if not seq:
        return None
    try:
        idx = seq.index(current_phase)
    except ValueError:
        return None
    return f"[{idx}/{len(seq)}フェーズ完了]"
```

### 2.3 SlackNotifier クラスへの新規メソッド追加

```python
@staticmethod
def _resolve_emoji(notification_type: str | None, level: str) -> str:
    """notification_type > level > デフォルト の優先順位で絵文字を解決する."""
    if notification_type and notification_type in _NOTIFICATION_TYPE_EMOJI:
        return _NOTIFICATION_TYPE_EMOJI[notification_type]
    return _LEVEL_EMOJI.get(level, ":robot_face:")

@staticmethod
def _get_header_text(notification_type: str | None) -> str | None:
    """notification_type に対応するヘッダーテキストを返す."""
    if notification_type is None:
        return None
    return _HEADER_TEXT.get(notification_type)

@staticmethod
def _build_section_text(emoji: str, message: str, meta: dict[str, Any]) -> str:
    """セクションブロック用のテキストを構築する."""
    issue_title = meta.get("issue_title")
    progress = meta.get("progress")
    duration_sec = meta.get("duration_sec")
    total_duration_sec = meta.get("total_duration_sec")
    next_action = meta.get("next_action")

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
    """metadata からアクションボタン要素リストを構築する."""
    elements: list[dict[str, Any]] = []
    repo = meta.get("repo")
    issue = meta.get("issue")
    pr_url = meta.get("pr_url")

    if repo and issue is not None:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Issueを見る", "emoji": True},
            "url": f"https://github.com/{repo}/issues/{issue}",
        })
    if pr_url:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "PRを見る", "emoji": True},
            "url": pr_url,
        })
    return elements
```

### 2.4 `_build_payload` メソッドの改修

既存の `_build_payload` を全面改修。**後方互換性**: `notification_type` が未指定の場合は従来と同じ構造 (section + context のみ) を生成する。

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
    notification_type = meta.get("notification_type")

    blocks: list[dict[str, Any]] = []

    # 1. ヘッダーブロック（notification_type がある場合のみ）
    header_text = self._get_header_text(notification_type)
    if header_text:
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": header_text, "emoji": True},
        })

    # 2. セクションブロック（メイン本文）
    emoji = self._resolve_emoji(notification_type, level)
    section_text = self._build_section_text(emoji, message, meta)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": section_text},
    })

    # 3. Divider（notification_type がある場合のみ）
    if header_text:
        blocks.append({"type": "divider"})

    # 4. アクションボタン（notification_type がある場合のみ）
    if notification_type:
        action_elements = self._build_action_buttons(meta)
        if action_elements:
            blocks.append({"type": "actions", "elements": action_elements})

    # 5. コンテキストブロック（既存ロジック維持）
    context_text = self._build_context_text(meta)
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

**注意**: `_level_emoji` メソッドは `_resolve_emoji` に内部的に取り込まれるが、既存テスト互換のため `_level_emoji` 自体はそのまま残す。

---

## 3. Step 2: `tests/unit/test_slack.py` — テスト追加

既存テスト (TC-SL-01〜TC-SL-13) は **変更不要**。以下のテストを追加:

### 3.1 追加テスト一覧

| テストID | テスト関数名 | テスト内容 |
|---------|-------------|-----------|
| TC-SL-14 | `test_notification_type_emoji_used` | `notification_type` 指定時に対応する絵文字が使われること |
| TC-SL-15 | `test_notification_type_fallback_to_level` | `notification_type` 未指定時は level ベース絵文字にフォールバック |
| TC-SL-16 | `test_header_block_added_for_notification_type` | ヘッダーブロックが `notification_type` 指定時のみ追加されること |
| TC-SL-17 | `test_divider_added_for_notification_type` | divider が `notification_type` 指定時のみ追加されること |
| TC-SL-18 | `test_issue_title_in_section` | `issue_title` が section テキストに含まれること |
| TC-SL-19 | `test_duration_formatting` | `duration_sec` / `total_duration_sec` がフォーマットされて表示されること |
| TC-SL-20 | `test_next_action_italic` | `next_action` がイタリック表示されること |
| TC-SL-21 | `test_progress_displayed` | `progress` が表示されること |
| TC-SL-22 | `test_action_buttons_generated` | アクションボタンが Issue/PR URLから正しく生成されること |
| TC-SL-23 | `test_action_buttons_omitted_without_url` | アクションボタンが URL なしの場合は省略されること |
| TC-SL-24 | `test_format_duration_boundaries` | `_format_duration` の境界値テスト（59秒, 60秒, 3600秒） |
| TC-SL-25 | `test_compute_progress_by_type` | `_compute_progress` のタイプ別テスト |
| TC-SL-26 | `test_compute_progress_unknown_type` | `_compute_progress` がタイプ未確定で None を返すこと |
| TC-SL-27 | `test_backward_compat_no_metadata` | 後方互換: metadata なしの呼び出しが既存フォーマットで送信されること |
| TC-SL-28 | `test_all_notification_types_have_header` | 全 `notification_type` に対してヘッダーテキストが存在すること |

### 3.2 テスト実装の要点

```python
# TC-SL-14: notification_type → 対応絵文字
@respx.mock
async def test_notification_type_emoji_used(notifier: SlackNotifier) -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
    await notifier.notify(
        "PR作成しました",
        metadata={"notification_type": "impl_pr_created", "issue": 42},
    )
    body = json.loads(route.calls[0].request.content)
    # section block のテキストに :rocket: が含まれること
    section = body["blocks"][1]  # [0]=header, [1]=section
    assert ":rocket:" in section["text"]["text"]

# TC-SL-24: _format_duration の境界値
def test_format_duration_boundaries() -> None:
    from ai_agent_orchestrator.notifications.slack import _format_duration
    assert _format_duration(59) == "59秒"
    assert _format_duration(60) == "1分00秒"
    assert _format_duration(3600) == "1時間00分"
    assert _format_duration(3661) == "1時間01分"

# TC-SL-25: _compute_progress
def test_compute_progress_by_type() -> None:
    from ai_agent_orchestrator.notifications.slack import _compute_progress
    assert _compute_progress("bug", "analysis") == "[1/6フェーズ完了]"
    assert _compute_progress("feature-m", "implement") == "[5/8フェーズ完了]"

# TC-SL-27: 後方互換
@respx.mock
async def test_backward_compat_no_metadata(notifier: SlackNotifier) -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
    await notifier.notify("テスト")
    body = json.loads(route.calls[0].request.content)
    assert len(body["blocks"]) == 1  # section のみ
    assert body["blocks"][0]["type"] == "section"
    assert "header" not in json.dumps(body)

# TC-SL-28: 全 notification_type にヘッダー存在
def test_all_notification_types_have_header() -> None:
    from ai_agent_orchestrator.notifications.slack import (
        _HEADER_TEXT,
        _NOTIFICATION_TYPE_EMOJI,
    )
    for nt in _NOTIFICATION_TYPE_EMOJI:
        assert nt in _HEADER_TEXT, f"{nt} has emoji but no header text"
```

---

## 4. Step 3: `phases/base.py` — フェーズ開始通知・エラー/タイムアウト metadata 拡充

### 4.1 `execute()` メソッドにフェーズ開始通知を追加

`build_prompt()` の前に以下を追加:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        await self._tracker.track(...)  # 既存

        # === 新規: フェーズ開始通知 ===
        issue_title = await self._fetch_issue_title(request)
        repo_full_name = self._get_repo_full_name(request)
        issue_type = self._sm.get_issue_type(request.issue_number)
        progress = None
        if issue_type:
            from ai_agent_orchestrator.notifications.slack import _compute_progress
            progress = _compute_progress(issue_type, str(request.phase))
        await self._notifier.notify(
            f"Issue #{request.issue_number} の{self._phase_display_name}を開始します",
            metadata={
                "notification_type": "phase_start",
                "issue": request.issue_number,
                "issue_title": issue_title,
                "phase": str(request.phase),
                "progress": progress,
                "repo": repo_full_name,
                "issue_type": issue_type,
            },
        )
        # === ここまで新規 ===

        prompt = await self.build_prompt(request)
        ...
```

### 4.2 新規ヘルパーメソッド

```python
async def _fetch_issue_title(self, request: TaskRequest) -> str:
    """Issue タイトルを取得する（エラー時は空文字）."""
    try:
        client = await self._get_client(request.repo)
        issue = await client.get_issue(request.repo, request.issue_number)
        return issue.title
    except Exception:
        logger.debug("Failed to fetch issue title for #%d", request.issue_number)
        return ""

def _get_repo_full_name(self, request: TaskRequest) -> str:
    """リポジトリのフルネーム (owner/repo) を取得する."""
    owner = getattr(request.repo, "owner", "")
    repo = getattr(request.repo, "repo", "")
    if owner and repo:
        return f"{owner}/{repo}"
    return ""

@property
def _phase_display_name(self) -> str:
    """フェーズの表示名。サブクラスでオーバーライド可能."""
    return "処理"
```

### 4.3 `_handle_timeout` の metadata 拡充

```python
# 変更前:
metadata={
    "issue": request.issue_number,
    "phase": str(request.phase),
},

# 変更後:
metadata={
    "notification_type": "timeout",
    "issue": request.issue_number,
    "phase": str(request.phase),
    "repo": self._get_repo_full_name(request),
    "next_action": "→ 手動での確認をお願いします",
},
```

### 4.4 `_handle_error` の metadata 拡充

```python
# 変更前:
metadata={
    "issue": request.issue_number,
    "phase": str(request.phase),
},

# 変更後:
metadata={
    "notification_type": "error",
    "issue": request.issue_number,
    "phase": str(request.phase),
    "repo": self._get_repo_full_name(request),
    "next_action": "→ 手動での確認をお願いします",
},
```

---

## 5. Step 4: 各フェーズファイルの metadata 拡充

### 5.1 共通パターン

全フェーズの `notify` 呼び出しに以下のキーを追加:
- `notification_type`: 対応する通知タイプ
- `issue_title`: 取得済みの `issue.title` を利用（※ `implement.py` は別途取得が必要）
- `repo`: `self._get_repo_full_name(request)` (base.py で定義)
- `next_action`: 該当する場合のみ
- `pr_url`: PR作成系の場合

### 5.2 ファイル別の変更内容

#### `hearing.py` (L117-122)

```python
# 変更前:
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    metadata={"issue": request.issue_number},
)

# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました",
    metadata={
        "notification_type": "hearing_question",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "repo": repo_full_name,
        "next_action": "→ Issueに回答をお願いします",
    },
)
```

#### `analysis.py` (L79-82)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} の修正方針を投稿しました",
    metadata={
        "notification_type": "plan_posted",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "repo": repo_full_name,
        "next_action": "→ 👍で承認をお願いします",
    },
)
```

#### `plan_brief.py` (L90-93)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装方針を投稿しました",
    metadata={
        "notification_type": "plan_posted",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "repo": repo_full_name,
        "next_action": "→ 👍で承認をお願いします",
    },
)
```

#### `design.py` (L97-103)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
owner = getattr(request.repo, "owner", "")
repo_name = getattr(request.repo, "repo", "")
pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}" if owner and repo_name else None
await self._notifier.notify(
    f"Issue #{request.issue_number} の設計PR #{pr_number} を作成しました",
    metadata={
        "notification_type": "design_pr_created",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "pr": pr_number,
        "pr_url": pr_url,
        "repo": repo_full_name,
        "next_action": "→ 設計PRをレビューしてください",
    },
)
```

#### `design_revise.py` (L89-92)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
state = self._sm.get_state(request.issue_number)
pr_number = state.design_pr_number if state else None
pr_url = None
if pr_number:
    owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}" if owner and repo_name else None
await self._notifier.notify(
    f"Issue #{request.issue_number} の設計書を修正しました",
    metadata={
        "notification_type": "design_revised",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "pr": pr_number,
        "pr_url": pr_url,
        "repo": repo_full_name,
        "next_action": "→ 設計PRを再レビューしてください",
    },
)
```

#### `implement.py` — 継続通知 (L144-150)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 実装パス {iteration + 1} 完了、継続中",
    metadata={
        "notification_type": "impl_continuation",
        "issue": request.issue_number,
        "repo": repo_full_name,
    },
)
```

**注意**: `issue_title` はこの時点で未取得。`execute()` のフェーズ開始通知で `_fetch_issue_title` が呼ばれるので、結果をインスタンス変数 `self._cached_issue_title` にキャッシュする設計も検討するが、現時点では省略して `issue_title` なしとする（セクションテキストは従来形式にフォールバック）。

#### `implement.py` — PR作成通知 (L411-417)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
owner = getattr(request.repo, "owner", "")
repo_name = getattr(request.repo, "repo", "")
pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}" if owner and repo_name else None
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
    metadata={
        "notification_type": "impl_pr_created",
        "issue": request.issue_number,
        "pr": pr_number,
        "pr_url": pr_url,
        "repo": repo_full_name,
        "duration_sec": result.duration_sec,  # AgentResult から取得
        "next_action": "→ 実装PRをレビューしてください",
    },
)
```

#### `impl_revise.py` (L101-104)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
state = self._sm.get_state(request.issue_number)
pr_number = state.pr_number if state else None
pr_url = None
if pr_number:
    owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}" if owner and repo_name else None
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装を修正しました",
    metadata={
        "notification_type": "impl_revised",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "pr": pr_number,
        "pr_url": pr_url,
        "repo": repo_full_name,
        "next_action": "→ 実装PRを再レビューしてください",
    },
)
```

#### `fix.py` (L100-106)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
owner = getattr(request.repo, "owner", "")
repo_name = getattr(request.repo, "repo", "")
pr_url = f"https://github.com/{owner}/{repo_name}/pull/{pr_number}" if owner and repo_name else None
await self._notifier.notify(
    f"Issue #{request.issue_number} の修正PR #{pr_number} を作成しました",
    metadata={
        "notification_type": "fix_pr_created",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "pr": pr_number,
        "pr_url": pr_url,
        "repo": repo_full_name,
        "next_action": "→ 修正PRをレビューしてください",
    },
)
```

#### `done.py` — 完了通知 (L75-78)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} 完了しました",
    metadata={
        "notification_type": "done",
        "issue": request.issue_number,
        "repo": repo_full_name,
    },
)
```

#### `done.py` — 連鎖起動 (L122-125)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{candidate.number} の処理を開始します (#{request.issue_number} 完了による連鎖)",
    metadata={
        "notification_type": "chain_start",
        "issue": candidate.number,
        "repo": repo_full_name,
    },
)
```

#### `split.py` — 分割提案 (L87-90)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} の分割を提案しました",
    metadata={
        "notification_type": "split_proposal",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "repo": repo_full_name,
        "next_action": "→ 👍で承認をお願いします",
    },
)
```

#### `split.py` — 分割完了 (L150-153)

```python
# 変更後:
repo_full_name = self._get_repo_full_name(request)
await self._notifier.notify(
    f"Issue #{request.issue_number} の分割が完了しました",
    metadata={
        "notification_type": "split_complete",
        "issue": request.issue_number,
        "issue_title": issue.title,
        "repo": repo_full_name,
    },
)
```

---

## 6. Step 5: `orchestrator/orchestrator.py` — 受付確認・既存通知の metadata 拡充

### 6.1 `start()` 内のシステム起動通知 (L617-623)

```python
# 変更後:
await self._notifier.notify(
    "Orchestrator started",
    level="info",
    metadata={
        "notification_type": "system_start",
        "repos": [f"{r.owner}/{r.repo}" for r in self._settings.repositories],
    },
)
```

### 6.2 イベントルーティングエラー (L745-748)

```python
# 変更後:
await self._notifier.notify(
    f"Event routing error: {exc}",
    level="error",
    metadata={
        "notification_type": "system_error",
    },
)
```

### 6.3 Issue suspended (L938-946)

```python
# 変更後:
await self._notifier.notify(
    f"Issue #{issue_number} suspended due to error: {error}",
    level="error",
    metadata={
        "notification_type": "suspended",
        "issue": issue_number,
        "phase": task.phase,
        "error": str(error),
        "next_action": "→ 手動での確認をお願いします",
    },
)
```

### 6.4 ヘルスチェック失敗 (L1032-1035)

```python
# 変更後:
await self._notifier.notify(
    f"Health check failures: {', '.join(unhealthy)}",
    level="error",
    metadata={
        "notification_type": "health_check",
    },
)
```

### 6.5 受付確認通知の追加

`_execute_task()` 内の `self._phase_dispatcher.dispatch()` 呼び出し前に、タイプ検出フェーズの場合のみ受付通知を送信:

```python
# _execute_task() 内、dispatch の前に追加
phase_normalized = phase.replace("_", "-")
if phase_normalized == "type-detection":
    repo_key_parts = repo_key.split("/")
    repo_full_name = repo_key if "/" in repo_key else ""
    await self._notifier.notify(
        f"Issue #{issue_number} を受け付けました",
        metadata={
            "notification_type": "receipt",
            "issue": issue_number,
            "repo": repo_full_name,
        },
    )
```

---

## 7. Step 6: `poller/event_router.py` — 承認後再開通知

承認ハンドラー（`_handle_plan_reaction`, `_handle_design_pr_approved`, `_handle_impl_pr_approved`）内に通知を追加:

```python
await self._notifier.notify(
    f"Issue #{issue_number} の方針が承認されました。次のフェーズに進みます",
    metadata={
        "notification_type": "approval_accepted",
        "issue": issue_number,
        "repo": repo_full_name,
    },
)
```

**注意**: `event_router.py` の具体的な実装を確認し、承認処理メソッド内の適切な位置（遷移呼び出しの直前）に挿入する。

---

## 8. Step 7: `docs/specs/slack.md` — 仕様書更新

以下のセクションを更新・追加:
- 通知タイプ別絵文字マッピング表
- Block Kit ペイロード構造図
- metadata 拡張キー一覧
- テストケース一覧 (TC-SL-14〜TC-SL-28)

---

## 9. テスト方針

### 9.1 テスト実行戦略

1. **Step 1 + Step 2 完了後**: `uv run pytest tests/unit/test_slack.py -v` で SlackNotifier のテストを実行
2. **Step 3 完了後**: `uv run pytest tests/unit/test_phases.py -v` で base.py 変更の影響確認
3. **Step 4〜6 完了後**: `uv run pytest tests/ -v` で全テスト実行
4. **最終**: `uv run mypy src/` + `uv run ruff check src/ tests/` で型チェック・lint

### 9.2 テストの原則

- **既存テスト不変**: TC-SL-01〜TC-SL-13 は一切変更しない
- **後方互換テスト**: `notification_type` なしの呼び出しが従来と同じペイロードを生成することを検証
- **ユーティリティ関数のテスト**: `_format_duration`, `_compute_progress` は直接テスト
- **フェーズ側のテスト**: 各フェーズのテストで metadata に `notification_type` が含まれることを検証（既存テストの mock 検証を拡張）

### 9.3 リスク軽減

- `_build_payload` の改修は後方互換フォールバックを最初に実装・テスト
- 各フェーズファイルの変更は独立しているため、1ファイルずつ変更→テストのサイクルで進める
