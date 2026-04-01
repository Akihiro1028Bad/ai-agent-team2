# Issue #34: Slackメッセージ改善 設計書

## 概要

Slack通知システムの「タイミング・フォーマット・内容」を全面的にアップグレードする。
Incoming Webhook 方式を維持しつつ、Block Kit のリッチレイアウト（ヘッダー、ディバイダー、カラーバー）を活用し、
フェーズ別絵文字・進捗ステータス・詳細メタデータを含むメッセージに刷新する。

## 決定事項（ヒアリング結果）

| 項目 | 決定 |
|------|------|
| API方式 | Incoming Webhook を維持（Slack App への移行は行わない） |
| フォーマット | (A) 絵文字・テキスト充実 + (B) リッチレイアウト（ヘッダー・ディバイダー・カラーバー） |
| ボタン | リンクボタンのみ（URL遷移。アクションボタンは対象外） |
| スレッドまとめ | 対象外（Webhook では `thread_ts` を取得できないため） |
| 通知タイミング | 全フェーズの開始時・完了時に通知を追加 |
| メッセージ内容 | リポジトリ名、Issue/PRリンク、経過時間、変更ファイル数/行数、CI結果、タイプ判定結果、進捗ステータスを追加 |
| 通知集約・抑制 | 不要 |
| チャンネル分け | 不要（単一チャンネル） |

---

## 1. 通知タイミング設計

### 1.1 現状（6箇所）

| フェーズ | タイミング | メッセージ |
|----------|-----------|-----------|
| hearing | 完了時 | `Issue #42 に質問を投稿しました。回答をお願いします` |
| plan_brief | 完了時 | `Issue #42 の実装方針を投稿しました。thumbsup で承認をお願いします` |
| design | 完了時 | `Issue #42 の設計PR #11 を作成しました。レビューをお願いします` |
| implement | 完了時 | `Issue #42 の実装PR #11 を作成しました` |
| done | 完了時 | `Issue #42 完了しました` |
| error/timeout | 発生時 | `Issue #42 でエラー: ... (phase: ...)` |

### 1.2 改善後（全フェーズ開始・完了通知）

| フェーズ | 開始通知 | 完了通知 |
|----------|---------|---------|
| type_detection | :label: `タイプ判定を開始します` | :label: `タイプ判定完了: Feature-M` |
| hearing | :speech_balloon: `ヒアリングを開始します` | :speech_balloon: `質問を投稿しました。回答をお願いします` |
| analysis | :mag: `原因分析を開始します` | :mag: `原因分析が完了しました。修正方針を投稿しました` |
| plan_brief | :clipboard: `方針作成を開始します` | :clipboard: `実装方針を投稿しました。:thumbsup: で承認をお願いします` |
| design | :triangular_ruler: `設計を開始します` | :triangular_ruler: `設計PR #N を作成しました。レビューをお願いします` |
| design_revise | :arrows_counterclockwise: `設計レビュー対応を開始します` | :arrows_counterclockwise: `設計書を修正しました` |
| planning | :memo: `実装計画を作成中です` | :memo: `実装計画が完了しました` |
| implement | :rocket: `実装を開始します` | :rocket: `実装PR #N を作成しました` |
| fix | :rocket: `修正を開始します` | :rocket: `修正PR #N を作成しました` |
| ci_fix | :wrench: `CI修正を開始します` | :wrench: `CI修正が完了しました` |
| impl_revise | :arrows_counterclockwise: `実装レビュー対応を開始します` | :arrows_counterclockwise: `実装を修正しました` |
| split | :scissors: `Issue分割を開始します` | :scissors: `分割が完了しました（N件の子Issue作成）` |
| done | ― | :white_check_mark: `完了しました` |
| error | ― | :x: `エラーが発生しました: {error}` |
| timeout | ― | :hourglass: `タイムアウトしました (phase: {phase})` |

### 1.3 通知追加箇所

開始通知は `PhaseExecutor` 基底クラスの `execute()` メソッド冒頭で統一的に送信する。
各フェーズの `_run()` メソッド先頭に個別の開始通知を追加する必要はない。

```python
# base.py の execute() メソッド内
async def execute(self, context: PhaseContext) -> PhaseResult:
    # フェーズ開始通知（新規追加）
    await self._notify_phase_start(context)
    try:
        result = await self._run(context)
        return result
    except TimeoutError:
        await self._notify_timeout(context)
        raise
    except Exception as exc:
        await self._notify_error(context, exc)
        raise
```

---

## 2. フォーマット設計

### 2.1 Block Kit レイアウト構造

現在の `section + context` 構造を、以下のリッチレイアウトに変更する。

```
┌─────────────────────────────────────────┐
│ [カラーバー]                              │
│                                         │
│ 📐 設計フェーズ完了                        │  ← Header block
│                                         │
│ ─────────────────────────────────────── │  ← Divider
│                                         │
│ Issue #42 の設計PR #11 を作成しました。     │  ← Section block (本文)
│ レビューをお願いします                      │
│                                         │
│ [Issue を見る]  [PR を見る]               │  ← Actions block (リンクボタン)
│                                         │
│ ─────────────────────────────────────── │  ← Divider
│                                         │
│ 📊 進捗: [3/7] 設計完了                   │  ← Section block (進捗)
│ ⏱️ 経過: 2分34秒                         │
│ 📁 変更: 5ファイル (+120 -30)             │
│                                         │
│ ─────────────────────────────────────── │  ← Divider
│                                         │
│ 🏷️ Feature-M | 📦 org/repo | 🤖 AI Agent │  ← Context block (メタデータ)
│                                         │
└─────────────────────────────────────────┘
```

### 2.2 カラーバー（Attachment color）

Webhook では `attachments` の `color` フィールドでカラーバーを付与できる。

| 通知種別 | カラー | 意味 |
|---------|--------|------|
| 開始（info） | `#1E90FF`（青） | 処理中 |
| 完了（success） | `#2EB67D`（緑） | 正常完了 |
| 待ち（waiting） | `#ECB22E`（黄） | ユーザー操作待ち |
| エラー | `#E01E5A`（赤） | エラー・タイムアウト |

### 2.3 リンクボタン

Webhook でもリンクボタン（`url` type の button）は使用可能。`actions` block で実現する。

```json
{
    "type": "actions",
    "elements": [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Issue を見る"},
            "url": "https://github.com/org/repo/issues/42"
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "PR を見る"},
            "url": "https://github.com/org/repo/pull/11"
        }
    ]
}
```

**注意**: Incoming Webhook での `actions` block のリンクボタンは Slack の仕様上サポートされている。
ただし、インタラクティブなアクション（クリック時のコールバック）は Slack App が必要なため対象外。

---

## 3. メッセージ内容設計

### 3.1 metadata の拡張

現在の metadata キーに加え、以下を追加する。

```python
@dataclass
class NotificationMetadata:
    """通知に含めるメタデータ."""

    # 既存
    repo: str | None = None           # "owner/repo"
    issue: int | None = None          # Issue番号
    pr: int | None = None             # PR番号
    pr_url: str | None = None         # PR URL
    phase: str | None = None          # フェーズ名

    # 新規追加
    issue_type: str | None = None     # "bug" | "feature-s" | "feature-m" | "feature-l"
    duration_sec: float | None = None # フェーズの経過時間（秒）
    files_changed: int | None = None  # 変更ファイル数
    lines_added: int | None = None    # 追加行数
    lines_deleted: int | None = None  # 削除行数
    ci_passed: int | None = None      # CI成功テスト数
    ci_failed: int | None = None      # CI失敗テスト数
    ci_total: int | None = None       # CI全テスト数
    step_current: int | None = None   # 現在のステップ番号
    step_total: int | None = None     # 全ステップ数
    step_label: str | None = None     # ステップラベル（例: "設計完了"）
    error: str | None = None          # エラーメッセージ
    design_pr: int | None = None      # 設計PR番号
    design_pr_url: str | None = None  # 設計PR URL
```

**実装方針**: `NotificationMetadata` は dataclass として定義するが、
`notify()` の `metadata` 引数は既存の `dict[str, Any]` を維持し、後方互換性を保つ。
`NotificationMetadata` は辞書変換用のヘルパーとして `to_dict()` メソッドを持つ。

### 3.2 進捗ステータス（ステップ表示）

タイプ別のステップ定義:

| タイプ | ステップ |
|--------|---------|
| **Bug** | 1.タイプ判定 → 2.ヒアリング → 3.原因分析 → 4.方針提示 → 5.修正実装 → 6.CI修正 → 7.完了 |
| **Feature-S** | 1.タイプ判定 → 2.ヒアリング → 3.方針提示 → 4.実装 → 5.CI修正 → 6.完了 |
| **Feature-M** | 1.タイプ判定 → 2.ヒアリング → 3.設計 → 4.実装計画 → 5.実装 → 6.CI修正 → 7.完了 |
| **Feature-L** | 1.タイプ判定 → 2.ヒアリング → 3.分割 → 4.完了（子Issueへ） |

- レビュー対応（revise）やCI修正の繰り返しはステップ数にカウントしない
- 表示例: `[5/7] CI修正中 (2回目)` のようにリトライ回数を付記

```python
# ステップ定義
PHASE_STEPS: dict[str, list[tuple[str, str]]] = {
    "bug": [
        ("type_detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("analysis", "原因分析"),
        ("plan_brief", "方針提示"),
        ("fix", "修正実装"),
        ("ci_fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-s": [
        ("type_detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("plan_brief", "方針提示"),
        ("implement", "実装"),
        ("ci_fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-m": [
        ("type_detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("design", "設計"),
        ("planning", "実装計画"),
        ("implement", "実装"),
        ("ci_fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-l": [
        ("type_detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("split", "分割"),
        ("done", "完了"),
    ],
}
```

### 3.3 フェーズ別絵文字マッピング

```python
PHASE_EMOJI: dict[str, str] = {
    "type_detection": ":label:",                # 🏷️
    "hearing": ":speech_balloon:",              # 💬
    "analysis": ":mag:",                        # 🔍
    "plan_brief": ":clipboard:",                # 📋
    "design": ":triangular_ruler:",             # 📐
    "design_revise": ":arrows_counterclockwise:",  # 🔄
    "planning": ":memo:",                       # 📝
    "implement": ":rocket:",                    # 🚀
    "fix": ":rocket:",                          # 🚀
    "ci_fix": ":wrench:",                       # 🔧
    "impl_revise": ":arrows_counterclockwise:", # 🔄
    "split": ":scissors:",                      # ✂️
    "done": ":white_check_mark:",               # ✅
    "error": ":x:",                             # ❌
    "timeout": ":hourglass:",                   # ⏳
}
```

---

## 4. 実装設計

### 4.1 変更対象ファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/ai_agent_orchestrator/notifications/slack.py` | `SlackNotifier` の `_build_payload` を大幅改修。絵文字マッピング・ステップ定義・リッチレイアウト構築を追加 |
| `src/ai_agent_orchestrator/phases/base.py` | `_notify_phase_start()` メソッド追加。`execute()` で開始通知を送信 |
| `src/ai_agent_orchestrator/phases/type_detection.py` | 完了通知にタイプ判定結果を含める |
| `src/ai_agent_orchestrator/phases/hearing.py` | metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/analysis.py` | metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/plan_brief.py` | metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/design.py` | metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/design_revise.py` | 開始通知追加、metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/planning.py` | 完了通知追加、metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/implement.py` | metadata に変更ファイル数・行数・進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/fix.py` | metadata に変更ファイル数・行数・進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/ci_fix.py` | 開始・完了通知追加、CI結果サマリを含める |
| `src/ai_agent_orchestrator/phases/impl_revise.py` | 開始通知追加、metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/split.py` | metadata に進捗ステータスを追加 |
| `src/ai_agent_orchestrator/phases/done.py` | metadata に進捗ステータスを追加 |
| `tests/unit/test_slack.py` | 新フォーマットに対応したテストケース追加・更新 |
| `docs/specs/slack.md` | 仕様書を更新 |

### 4.2 `SlackNotifier` クラスの改修

#### 4.2.1 新しい定数

```python
# フェーズ別絵文字
PHASE_EMOJI: dict[str, str] = { ... }  # 上記参照

# カラーバー
NOTIFICATION_COLORS: dict[str, str] = {
    "start": "#1E90FF",    # 青: 処理開始
    "success": "#2EB67D",  # 緑: 正常完了
    "waiting": "#ECB22E",  # 黄: ユーザー操作待ち
    "error": "#E01E5A",    # 赤: エラー
}

# タイプ別ステップ定義
PHASE_STEPS: dict[str, list[tuple[str, str]]] = { ... }  # 上記参照
```

#### 4.2.2 `notify()` メソッド改修

シグネチャは変更なし（後方互換性維持）。内部で metadata の新キーを認識してリッチペイロードを構築。

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

#### 4.2.3 `_build_payload()` の改修

以下のブロックを順に構築する:

1. **Header block** - フェーズ絵文字 + フェーズ名
2. **Divider**
3. **Section block** - メッセージ本文
4. **Actions block** - リンクボタン（Issue/PRのURLがある場合）
5. **Divider**
6. **Section block** - 進捗ステータス + 経過時間 + 変更ファイル数（該当する場合）
7. **Divider**
8. **Context block** - タイプ判定結果 + リポジトリ名

カラーバーは `attachments` で実現:

```python
def _build_payload(self, message, *, channel, level, metadata):
    meta = metadata or {}
    notification_type = meta.get("notification_type", "info")
    color = self._resolve_color(notification_type, level)
    blocks = self._build_blocks(message, meta)

    payload: dict[str, Any] = {
        "attachments": [
            {
                "color": color,
                "blocks": blocks,
            }
        ]
    }
    resolved_channel = channel or self._default_channel
    if resolved_channel is not None:
        payload["channel"] = resolved_channel
    return payload
```

#### 4.2.4 新規内部メソッド

```python
def _resolve_color(self, notification_type: str, level: str) -> str:
    """通知種別・レベルからカラーバーの色を決定する."""

def _build_header_block(self, phase: str | None, level: str) -> dict[str, Any]:
    """Header block を構築する."""

def _build_message_block(self, message: str, phase: str | None) -> dict[str, Any]:
    """メッセージ本文の Section block を構築する."""

def _build_actions_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """リンクボタンの Actions block を構築する（URL がある場合のみ）."""

def _build_stats_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """進捗・経過時間・変更ファイル数の Section block を構築する."""

def _build_context_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """メタデータの Context block を構築する."""

@staticmethod
def _phase_emoji(phase: str | None) -> str:
    """フェーズに応じた絵文字を返す."""

@staticmethod
def _format_duration(seconds: float) -> str:
    """秒数を人間可読な文字列に変換する（例: '2分34秒'）."""

@staticmethod
def _build_progress_text(metadata: dict[str, Any]) -> str | None:
    """進捗ステータスのテキストを構築する（例: '[3/7] 設計完了'）."""
```

### 4.3 `PhaseExecutor` 基底クラスの改修

#### 4.3.1 `_notify_phase_start()` の追加

```python
async def _notify_phase_start(self, context: PhaseContext) -> None:
    """フェーズ開始通知を送信する."""
    phase_label = PHASE_LABELS.get(context.phase, context.phase)
    step_current, step_total = self._resolve_step(context)

    await self._notifier.notify(
        f"Issue #{context.issue_number} の{phase_label}を開始します",
        metadata={
            "repo": f"{context.repo_owner}/{context.repo_name}",
            "issue": context.issue_number,
            "phase": context.phase,
            "notification_type": "phase_start",
            "step_current": step_current,
            "step_total": step_total,
            "issue_type": self._get_issue_type(context),
        },
    )
```

#### 4.3.2 `_resolve_step()` の追加

```python
def _resolve_step(
    self, context: PhaseContext
) -> tuple[int | None, int | None]:
    """現在のフェーズに対応するステップ番号を返す."""
    issue_type = self._get_issue_type(context)
    if not issue_type:
        return None, None
    steps = PHASE_STEPS.get(issue_type, [])
    for i, (phase_key, _label) in enumerate(steps, 1):
        if phase_key == context.phase:
            return i, len(steps)
    return None, None
```

#### 4.3.3 `execute()` メソッドの変更

```python
async def execute(self, context: PhaseContext) -> PhaseResult:
    start_time = time.monotonic()

    # 新規: フェーズ開始通知
    await self._notify_phase_start(context)

    try:
        result = await self._run(context)
        # 既存の完了通知はそのまま（各フェーズの _run() 内で送信）
        # duration_sec を metadata に含めるためのヘルパーを提供
        return result
    except TimeoutError:
        ...
    except Exception:
        ...
```

### 4.4 各フェーズの `notify()` 呼び出し改修

各フェーズの完了通知で、以下の metadata キーを追加する:

```python
# 例: implement.py
await self._notifier.notify(
    f"Issue #{issue_number} の実装PR #{pr_number} を作成しました",
    metadata={
        "repo": f"{ctx.repo_owner}/{ctx.repo_name}",
        "issue": issue_number,
        "pr": pr_number,
        "pr_url": pr_url,
        "phase": "implement",
        "notification_type": "impl_pr_created",
        "issue_type": issue_type,
        "duration_sec": elapsed,
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_deleted": lines_deleted,
        "step_current": step_current,
        "step_total": step_total,
        "step_label": "実装完了",
    },
)
```

### 4.5 経過時間の計測

`PhaseExecutor.execute()` で `time.monotonic()` を使ってフェーズの経過時間を計測し、
`PhaseContext.extra` 経由で各フェーズに渡す、または `_run()` の戻り値 `PhaseResult.duration_sec` を利用する。

```python
# base.py
import time

async def execute(self, context: PhaseContext) -> PhaseResult:
    self._phase_start_time = time.monotonic()
    ...

@property
def elapsed_sec(self) -> float:
    """フェーズ開始からの経過時間（秒）."""
    return time.monotonic() - self._phase_start_time
```

### 4.6 変更ファイル数・行数の取得

`implement.py` / `fix.py` でPR作成後、GitHub APIから差分情報を取得する。

```python
# GitHubClient に追加（もしくは既存メソッド活用）
pr_data = await self._github.get_pull(repo_owner, repo_name, pr_number)
files_changed = pr_data.changed_files
lines_added = pr_data.additions
lines_deleted = pr_data.deletions
```

### 4.7 CI結果サマリの取得

`ci_fix.py` で CI ジョブの結果を取得し、metadata に含める。

```python
metadata={
    ...
    "ci_passed": passed_count,
    "ci_failed": failed_count,
    "ci_total": total_count,
}
```

---

## 5. ペイロード例

### 5.1 フェーズ開始通知（実装開始）

```json
{
    "attachments": [
        {
            "color": "#1E90FF",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": ":rocket: 実装フェーズ開始"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Issue #42 の実装を開始します"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Issue を見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":bar_chart: *進捗:* `[5/7]` 実装\n:stopwatch: *経過:* -"
                    }
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":label: Feature-M | :package: `org/repo` | :robot_face: AI Agent"
                        }
                    ]
                }
            ]
        }
    ]
}
```

### 5.2 フェーズ完了通知（実装PR作成）

```json
{
    "attachments": [
        {
            "color": "#ECB22E",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": ":rocket: 実装フェーズ完了"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Issue #42 の実装PR #11 を作成しました。レビューをお願いします"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Issue を見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "PR を見る"},
                            "url": "https://github.com/org/repo/pull/11"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":bar_chart: *進捗:* `[5/7]` 実装完了\n:stopwatch: *経過:* 5分12秒\n:file_folder: *変更:* 8ファイル (+250 -40)"
                    }
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":label: Feature-M | :package: `org/repo` | :robot_face: AI Agent"
                        }
                    ]
                }
            ]
        }
    ]
}
```

### 5.3 エラー通知

```json
{
    "attachments": [
        {
            "color": "#E01E5A",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": ":x: エラー発生"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Issue #42 でエラーが発生しました: TimeoutError (phase: implement)"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Issue を見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":label: Feature-M | :package: `org/repo` | :robot_face: AI Agent"
                        }
                    ]
                }
            ]
        }
    ]
}
```

### 5.4 完了通知

```json
{
    "attachments": [
        {
            "color": "#2EB67D",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": ":white_check_mark: Issue完了"}
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Issue #42 完了しました :tada:"
                    }
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Issue を見る"},
                            "url": "https://github.com/org/repo/issues/42"
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "PR を見る"},
                            "url": "https://github.com/org/repo/pull/11"
                        }
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":bar_chart: *進捗:* `[7/7]` 完了\n:stopwatch: *総経過:* 15分42秒"
                    }
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": ":label: Feature-M | :package: `org/repo` | :robot_face: AI Agent"
                        }
                    ]
                }
            ]
        }
    ]
}
```

---

## 6. テスト計画

### 6.1 既存テストの更新

既存の TC-SL-01 〜 TC-SL-13 を新しいペイロード構造に合わせて更新する。
`attachments` ベースの構造に変更されるため、アサーション箇所を修正。

### 6.2 新規テストケース

| テストID | テスト内容 |
|---------|-----------|
| TC-SL-14 | `_phase_emoji` がフェーズごとに正しい絵文字を返す |
| TC-SL-15 | `_resolve_color` が通知種別・レベルに応じた色を返す |
| TC-SL-16 | `_build_header_block` がヘッダーブロックを正しく構築する |
| TC-SL-17 | `_build_actions_block` がIssue/PR URLからリンクボタンを構築する |
| TC-SL-18 | `_build_actions_block` がURLなしの場合 `None` を返す |
| TC-SL-19 | `_build_stats_block` が進捗・経過時間・変更ファイル数を正しく表示する |
| TC-SL-20 | `_build_stats_block` が情報なしの場合 `None` を返す |
| TC-SL-21 | `_format_duration` が秒数を正しく変換する（例: 154.5 → "2分34秒"） |
| TC-SL-22 | `_build_progress_text` がステップ情報を正しく構築する |
| TC-SL-23 | 全体ペイロードに `attachments.color` が含まれる |
| TC-SL-24 | 開始通知の `notification_type=phase_start` で青色カラーバーが設定される |
| TC-SL-25 | エラー通知で赤色カラーバーが設定される |
| TC-SL-26 | `_build_context_block` が `issue_type` を含む |
| TC-SL-27 | `PhaseExecutor._notify_phase_start` が開始通知を送信する |
| TC-SL-28 | `PhaseExecutor._resolve_step` がタイプ別に正しいステップ番号を返す |

---

## 7. 後方互換性

### 7.1 `notify()` シグネチャ

変更なし。`metadata` は引き続き `dict[str, Any] | None` を受け取る。
新しいキーが含まれない場合は従来通りの簡易フォーマットにフォールバックする。

### 7.2 `Notifier` Protocol

`notify()` のシグネチャは変更しないため、Protocol の変更は不要。
`NullNotifier` も変更不要。

### 7.3 ペイロード構造

`blocks` 直下 → `attachments[0].blocks` に変更されるため、
ペイロード構造の破壊的変更が発生する。ただし Slack Webhook の受信側は
`attachments` 形式を標準的にサポートしているため、問題ない。

---

## 8. 実装順序

1. **Phase 1**: `slack.py` の定数追加（絵文字マッピング、カラー、ステップ定義）
2. **Phase 2**: `_build_payload()` のリファクタ（リッチレイアウト構築）
3. **Phase 3**: `base.py` に `_notify_phase_start()` / `_resolve_step()` 追加
4. **Phase 4**: 各フェーズの `notify()` 呼び出しに metadata 拡張を追加
5. **Phase 5**: テスト更新・追加
6. **Phase 6**: `docs/specs/slack.md` 仕様書更新

---

## 9. リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| Webhook でリンクボタンが動作しない可能性 | ボタンが表示されない | Slack の `actions` block のリンクボタンは Webhook でサポートされているが、動作確認を実施。フォールバックとして mrkdwn リンクを用意 |
| Header block が Webhook で使えない可能性 | ヘッダーが表示されない | `header` block は Webhook でサポートされている。万一の場合は `section` block + bold テキストで代替 |
| metadata のキーが増えすぎて可読性低下 | コード保守性の低下 | `NotificationMetadata` dataclass を導入し、型安全性を確保 |
| 全フェーズ開始通知による通知量増加 | Slack チャンネルがノイジーに | 開始通知は簡潔なフォーマット（ヘッダー + 進捗のみ）にする |
