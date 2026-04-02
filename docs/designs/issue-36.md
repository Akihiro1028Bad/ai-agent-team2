# 設計書: Issue #36 Slackメッセージの改善

## 1. 概要

Slack通知の「タイミング・フォーマット・内容」をすべてアップグレードする。
現状の通知はレベルベース（info/error/critical）の絵文字3種類のみで、Issueタイトルや進捗情報が含まれていない。
本設計では通知タイプ別の絵文字、リッチなBlock Kitフォーマット、アクションボタン、所要時間・進捗サマリを導入する。

## 2. 現状分析

### 2.1 現在の通知箇所（12箇所）

| # | ファイル | タイミング | 現在のメッセージ |
|---|---------|-----------|----------------|
| 1 | `orchestrator.py:617` | Orchestrator起動 | `Orchestrator started` |
| 2 | `hearing.py:117` | ヒアリング質問投稿 | `Issue #N に質問を投稿しました` |
| 3 | `analysis.py:79` | Bug方針投稿 | `Issue #N の修正方針を投稿しました` |
| 4 | `plan_brief.py:90` | Feature-S方針投稿 | `Issue #N の実装計画を投稿しました` |
| 5 | `design.py:97` | 設計PR作成 | `Issue #N の設計PRを作成しました` |
| 6 | `design_revise.py:89` | 設計書修正 | `Issue #N の設計書を修正しました` |
| 7 | `implement.py:144` | 実装パス継続 | `Issue #N 実装パス N 完了、継続中` |
| 8 | `implement.py:411` | 実装PR作成 | `Issue #N の実装PRを作成しました` |
| 9 | `impl_revise.py:101` | 実装修正完了 | `Issue #N のPRを修正しました` |
| 10 | `done.py:75` | Issue完了 | `Issue #N 完了しました` |
| 11 | `done.py:122` | 連鎖起動 | `Issue #N の処理を開始します` |
| 12 | `split.py:87,150` | 分割提案/完了 | `Issue #N の分割を提案/完了しました` |
| 13 | `base.py:392` | タイムアウト | `Issue #N がタイムアウトしました` |
| 14 | `base.py:414` | エラー | `Issue #N でエラー: ...` |
| 15 | `orchestrator.py:745` | イベントルーティングエラー | `Event routing error: ...` |
| 16 | `orchestrator.py:938` | Issue suspended | `Issue #N suspended due to error` |
| 17 | `orchestrator.py:1032` | ヘルスチェック失敗 | `Health check failures: ...` |
| 18 | `fix.py:100` | 修正PR作成 | `Issue #N の修正PRを作成しました` |

### 2.2 現在の課題

1. **notification_type 別の絵文字が未実装** - 仕様書に定義済みだが使用されていない
2. **Issueタイトルが含まれない** - Issue番号だけで内容が分からない
3. **フェーズ開始・受付確認の通知がない** - 処理開始を把握できない
4. **承認後の再開通知がない** - 自動遷移のフィードバックがない
5. **所要時間・進捗情報がない** - 処理状況が不明
6. **次のアクション案内がない** - ユーザーが何をすべきか不明
7. **アクションボタンがない** - Issue/PRへのリンクが不便
8. **ヘッダーブロック・dividerがない** - 視認性が低い

## 3. 設計方針

### 3.1 ヒアリングで確定した要件

| 項目 | 決定事項 |
|------|---------|
| フェーズ開始通知 | 必要 |
| 受付確認通知 | 必要 |
| 承認後の再開通知 | 必要 |
| Slackスレッド | 不要 |
| 通知タイプ別絵文字 | 実装する |
| ヘッダー・divider | 追加する |
| アクションボタン | 追加する |
| Issueタイトル | 含める |
| 所要時間 | フェーズ単位 + Issue全体の両方 |
| 次のアクション案内 | 含める |
| 進捗サマリ | タイプ確定後から表示（A案） |
| `notify` インターフェース | metadata拡張（A案） |

### 3.2 設計原則

- **後方互換性を維持**: `notify` の既存シグネチャは変更しない。metadata にキーを追加する
- **best-effort 維持**: 通知失敗は処理を止めない
- **段階的適用**: 各フェーズファイルでの metadata 拡充は個別に実施

## 4. 詳細設計

### 4.1 通知タイプと絵文字マッピング

既存の `_LEVEL_EMOJI` に加えて、`notification_type` 別の絵文字マッピングを新設する。

```python
_NOTIFICATION_TYPE_EMOJI: dict[str, str] = {
    # 新規タイミング
    "receipt": ":inbox_tray:",
    "phase_start": ":arrow_forward:",
    "approval_accepted": ":thumbsup:",
    # 既存タイミング（仕様書定義）
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
```

**絵文字解決の優先順位**: `notification_type` > `level` > デフォルト (`:robot_face:`)

### 4.2 metadata 拡張キー

既存の metadata キーに加え、以下のキーを認識する:

| キー | 型 | 説明 | 例 |
|-----|-----|------|-----|
| `notification_type` | `str` | 通知タイプ（絵文字解決用） | `"impl_pr_created"` |
| `issue_title` | `str` | Issueタイトル | `"Slackメッセージの改善"` |
| `duration_sec` | `float` | フェーズ所要時間（秒） | `323.5` |
| `total_duration_sec` | `float` | Issue全体の所要時間（秒） | `1935.2` |
| `next_action` | `str` | 次のアクション案内 | `"→ PRをレビューしてください"` |
| `progress` | `str` | 進捗サマリ | `"[3/8フェーズ完了]"` |
| `issue_type` | `str` | Issueタイプ | `"feature-m"` |

### 4.3 Block Kit ペイロード構造（新フォーマット）

```
┌─────────────────────────────────────────────┐
│ header: 絵文字 + メインメッセージ             │ ← header block (plain_text)
├─────────────────────────────────────────────┤
│ section: [Issue Title] Issue #N のXXXしました │ ← section block (mrkdwn)
│          進捗: [3/8] | 所要: 5分23秒         │
│          → 次のアクション案内                  │
├─────────────────────────────────────────────┤
│ divider                                      │ ← divider block
├─────────────────────────────────────────────┤
│ actions: [Issueを見る] [PRを見る]             │ ← actions block (buttons)
├─────────────────────────────────────────────┤
│ context: repo | Issue #N | PR #N | phase     │ ← context block
└─────────────────────────────────────────────┘
```

#### 4.3.1 ヘッダーブロック

```python
{
    "type": "header",
    "text": {
        "type": "plain_text",
        "text": "🚀 実装PR作成完了",
        "emoji": True,
    },
}
```

`notification_type` に応じたヘッダーテキストマッピングを新設:

```python
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
```

#### 4.3.2 セクションブロック（本文）

Issue タイトル付きのメッセージ + 補足情報:

```python
lines = []
if issue_title:
    lines.append(f"*[{issue_title}]* {message}")
else:
    lines.append(message)

# 進捗・所要時間
info_parts = []
if progress:
    info_parts.append(f"進捗: {progress}")
if duration_sec is not None:
    info_parts.append(f"フェーズ: {_format_duration(duration_sec)}")
if total_duration_sec is not None:
    info_parts.append(f"全体: {_format_duration(total_duration_sec)}")
if info_parts:
    lines.append(" | ".join(info_parts))

# 次のアクション
if next_action:
    lines.append(f"_{next_action}_")

section_text = "\n".join(lines)
```

#### 4.3.3 アクションボタン

```python
actions_block = {
    "type": "actions",
    "elements": [],
}
# Issue リンクボタン
if repo and issue is not None:
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Issueを見る", "emoji": True},
        "url": f"https://github.com/{repo}/issues/{issue}",
    })
# PR リンクボタン
if pr_url:
    elements.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "PRを見る", "emoji": True},
        "url": pr_url,
    })
```

### 4.4 `_build_payload` メソッドの改修

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

    # 1. ヘッダーブロック（notification_type がある場合）
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

    # 3. Divider
    if header_text:
        blocks.append({"type": "divider"})

    # 4. アクションボタン
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

### 4.5 新規通知タイミング

#### 4.5.1 受付確認通知（receipt）

**場所**: `orchestrator.py` の `_execute_task` 内、Issue初回処理時

```python
# type_detection フェーズの開始時に送信
await self._notifier.notify(
    f"Issue #{issue_number} を受け付けました",
    metadata={
        "notification_type": "receipt",
        "issue": issue_number,
        "issue_title": issue_title,
        "issue_type": issue_type,
        "repo": repo_full_name,
    },
)
```

#### 4.5.2 フェーズ開始通知（phase_start）

**場所**: `base.py` の `execute()` メソッド内、`build_prompt()` の前

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の{phase_display_name}を開始しました",
    metadata={
        "notification_type": "phase_start",
        "issue": request.issue_number,
        "issue_title": issue_title,  # 取得が必要
        "phase": str(request.phase),
        "progress": progress_text,
        "repo": repo_full_name,
    },
)
```

**注意**: `issue_title` の取得にはGitHub APIコールが必要。`execute()` で一度取得してインスタンス変数にキャッシュする。

#### 4.5.3 承認後の再開通知（approval_accepted）

**場所**: `event_router.py` の `_handle_plan_reaction` / `_handle_design_pr_approved` / `_handle_impl_pr_approved` 内

```python
await self._notifier.notify(
    f"Issue #{issue_number} の{phase_label}が承認されました。{next_phase_label}に進みます",
    metadata={
        "notification_type": "approval_accepted",
        "issue": issue_number,
        "issue_title": issue_title,
        "repo": repo_full_name,
    },
)
```

### 4.6 進捗サマリ計算

タイプ確定後に表示。タイプ別フェーズ一覧:

```python
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

計算ロジック:
```python
def _compute_progress(issue_type: str, current_phase: str) -> str | None:
    """進捗サマリを計算する。タイプ未確定の場合は None。"""
    seq = _PHASE_SEQUENCES.get(issue_type)
    if not seq:
        return None
    try:
        idx = seq.index(current_phase)
    except ValueError:
        return None
    return f"[{idx}/{len(seq)}フェーズ完了]"
```

### 4.7 所要時間フォーマット

```python
def _format_duration(seconds: float) -> str:
    """秒数を人間可読な形式にフォーマットする。"""
    if seconds < 60:
        return f"{seconds:.0f}秒"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}分{secs:02d}秒"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}時間{mins:02d}分"
```

### 4.8 通知タイプ別のアクションボタン・次のアクション

| notification_type | ボタン | next_action |
|-------------------|--------|-------------|
| `receipt` | Issueを見る | — |
| `phase_start` | Issueを見る | — |
| `hearing_question` | Issueを見る | `→ Issueに回答をお願いします` |
| `plan_posted` | Issueを見る | `→ 👍で承認をお願いします` |
| `design_pr_created` | Issueを見る, PRを見る | `→ 設計PRをレビューしてください` |
| `impl_pr_created` | Issueを見る, PRを見る | `→ 実装PRをレビューしてください` |
| `fix_pr_created` | Issueを見る, PRを見る | `→ 修正PRをレビューしてください` |
| `design_revised` | PRを見る | `→ 設計PRを再レビューしてください` |
| `impl_revised` | PRを見る | `→ 実装PRを再レビューしてください` |
| `done` | Issueを見る, PRを見る | — |
| `error` / `timeout` / `suspended` | Issueを見る | `→ 手動での確認をお願いします` |
| `approval_accepted` | Issueを見る | — |
| その他 | 該当リンクのみ | — |

## 5. 変更対象ファイル

### 5.1 主要変更（Slack通知本体）

| ファイル | 変更内容 |
|---------|---------|
| `notifications/slack.py` | `_NOTIFICATION_TYPE_EMOJI`, `_HEADER_TEXT` 追加、`_build_payload` 改修、`_resolve_emoji`, `_get_header_text`, `_build_section_text`, `_build_action_buttons`, `_format_duration`, `_compute_progress` 新設 |
| `tests/unit/test_slack.py` | 新フォーマット・絵文字・ボタン・進捗・所要時間のテスト追加 |

### 5.2 通知呼び出し側の変更（metadata拡充）

| ファイル | 変更内容 |
|---------|---------|
| `phases/base.py` | `execute()` にフェーズ開始通知追加、`_handle_timeout` / `_handle_error` の metadata 拡充 |
| `phases/hearing.py` | `notification_type`, `issue_title`, `next_action` を metadata に追加 |
| `phases/analysis.py` | 同上 |
| `phases/plan_brief.py` | 同上 |
| `phases/design.py` | 同上 + `pr_url` |
| `phases/design_revise.py` | 同上 |
| `phases/implement.py` | 同上 + `duration_sec` |
| `phases/impl_revise.py` | 同上 |
| `phases/fix.py` | 同上 + `pr_url` |
| `phases/done.py` | 同上 + `total_duration_sec` |
| `phases/split.py` | 同上 |
| `orchestrator/orchestrator.py` | 受付確認通知追加、既存通知の metadata 拡充 |
| `poller/event_router.py` | 承認後の再開通知追加（`_notify_plan_approved` 改修） |

### 5.3 仕様書更新

| ファイル | 変更内容 |
|---------|---------|
| `docs/specs/slack.md` | 新フォーマット・通知タイプ・テストケース反映 |

## 6. ペイロード例

### 6.1 実装PR作成通知

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🚀 実装PR作成",
                "emoji": true
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":rocket: *[Slackメッセージの改善]* Issue #36 の実装PRを作成しました: #42\n進捗: [6/8フェーズ完了] | フェーズ: 5分23秒 | 全体: 32分15秒\n_→ 実装PRをレビューしてください_"
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
                    "text": {"type": "plain_text", "text": "Issueを見る", "emoji": true},
                    "url": "https://github.com/org/repo/issues/36"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "PRを見る", "emoji": true},
                    "url": "https://github.com/org/repo/pull/42"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/36|Issue #36> | :memo: <https://github.com/org/repo/pull/42|PR #42> | :memo: phase:implement"
                }
            ]
        }
    ]
}
```

### 6.2 受付確認通知

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📥 Issue受付", "emoji": true}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":inbox_tray: *[Slackメッセージの改善]* Issue #36 を受け付けました（type: feature-m）"
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
                    "text": {"type": "plain_text", "text": "Issueを見る", "emoji": true},
                    "url": "https://github.com/org/repo/issues/36"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": ":package: `org/repo` | :page_facing_up: <https://github.com/org/repo/issues/36|Issue #36>"
                }
            ]
        }
    ]
}
```

### 6.3 エラー通知（notification_type なしのフォールバック）

`notification_type` が指定されていない既存の呼び出しは、現行通りの `level` ベース絵文字で表示される。
ヘッダーブロック・divider・アクションボタンは省略され、**後方互換性を完全に維持**する。

```json
{
    "channel": "#ai-agent",
    "blocks": [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":x: Event routing error: ..."
            }
        }
    ]
}
```

## 7. テスト計画

### 7.1 新規テストケース

| テストID | テスト内容 |
|---------|-----------|
| TC-SL-14 | `notification_type` 指定時に対応する絵文字が使われること |
| TC-SL-15 | `notification_type` 未指定時は `level` ベース絵文字にフォールバック |
| TC-SL-16 | ヘッダーブロックが `notification_type` 指定時のみ追加されること |
| TC-SL-17 | divider が `notification_type` 指定時のみ追加されること |
| TC-SL-18 | `issue_title` が section テキストに含まれること |
| TC-SL-19 | `duration_sec` / `total_duration_sec` がフォーマットされて表示されること |
| TC-SL-20 | `next_action` がイタリック表示されること |
| TC-SL-21 | `progress` が表示されること |
| TC-SL-22 | アクションボタンが Issue/PR URLから正しく生成されること |
| TC-SL-23 | アクションボタンが URL なしの場合は省略されること |
| TC-SL-24 | `_format_duration` の境界値テスト（59秒, 60秒, 3600秒） |
| TC-SL-25 | `_compute_progress` のタイプ別テスト |
| TC-SL-26 | `_compute_progress` がタイプ未確定で None を返すこと |
| TC-SL-27 | 後方互換: metadata なしの呼び出しが既存フォーマットで送信されること |
| TC-SL-28 | 全 `notification_type` に対してヘッダーテキストが存在すること |

### 7.2 既存テストへの影響

既存の TC-SL-01 〜 TC-SL-13 は **変更不要**。
`notification_type` を含まない呼び出しは従来と同じペイロードを生成するため、既存テストはそのままパスする。

## 8. 実装順序

1. **Phase 1: SlackNotifier 本体改修**（優先度: 高）
   - `_NOTIFICATION_TYPE_EMOJI`, `_HEADER_TEXT` 定数追加
   - `_resolve_emoji`, `_get_header_text`, `_build_section_text`, `_build_action_buttons` 新設
   - `_format_duration`, `_compute_progress` ユーティリティ新設
   - `_build_payload` 改修
   - テスト TC-SL-14 〜 TC-SL-28 追加

2. **Phase 2: 通知呼び出し側の metadata 拡充**（優先度: 高）
   - `base.py` にフェーズ開始通知追加
   - 各フェーズファイル (hearing, analysis, plan_brief, design, implement, fix, done, split 等) の `notify` 呼び出しに `notification_type`, `issue_title`, `next_action` 等を追加
   - `orchestrator.py` に受付確認通知追加
   - `event_router.py` に承認後再開通知追加

3. **Phase 3: 進捗・所要時間**（優先度: 中）
   - `IssueState` に `created_at` を活用した全体所要時間計算
   - 各フェーズに `duration_sec` / `total_duration_sec` / `progress` の metadata 追加

4. **Phase 4: 仕様書更新**
   - `docs/specs/slack.md` を新仕様に更新

## 9. リスク・考慮事項

| リスク | 対策 |
|-------|------|
| Block Kit ブロック数上限（50ブロック） | 最大5ブロック構成のため問題なし |
| Webhook ペイロードサイズ上限 | メッセージ本文の長さは既存と同等。超過リスクなし |
| 後方互換性破壊 | `notification_type` 未指定時は従来フォーマットにフォールバック |
| GitHub API 呼び出し増加（issue_title 取得） | `execute()` 内で1回取得しキャッシュ。既に `build_prompt()` で取得済みのフェーズが多い |
| アクションボタンの URL 不正 | URL 構築は既存の `_build_context_text` と同じロジック |
