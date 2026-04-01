# Issue #34: Slackメッセージ改善 — 実装計画

## 概要

設計書 `docs/designs/issue-34.md` に基づき、Slack通知システムの全面的アップグレードを行う。
Block Kit リッチレイアウト（Header / Divider / Actions / カラーバー）の導入、
全フェーズの開始・完了通知、進捗ステータス・経過時間・変更ファイル数等のメタデータ拡充を実装する。

---

## 変更ファイル一覧と依存関係

### 依存関係グラフ（実装順序）

```
Step 1: slack.py          (定数・ペイロード構築の全面改修。他の全変更の基盤)
  ↓
Step 2: base.py           (開始通知・経過時間計測。slack.py の新メタデータに依存)
  ↓
Step 3: 各フェーズファイル  (metadata 拡張。base.py の新メソッドに依存)
  ↓
Step 4: test_slack.py     (Step 1 の新ペイロード構造に対応)
  ↓
Step 5: docs/specs/slack.md (仕様書更新)
```

---

## Step 1: `src/ai_agent_orchestrator/notifications/slack.py`

**優先度: 最高（全変更の基盤）**

### 1.1 定数の追加

ファイル冒頭の `_LEVEL_EMOJI` の後に以下の定数を追加する。

```python
# フェーズ別絵文字マッピング
PHASE_EMOJI: dict[str, str] = {
    "type-detection": ":label:",
    "hearing": ":speech_balloon:",
    "hearing-wait": ":speech_balloon:",
    "analysis": ":mag:",
    "plan-brief": ":clipboard:",
    "plan-review": ":clipboard:",
    "design": ":triangular_ruler:",
    "design-review": ":triangular_ruler:",
    "design-revise": ":arrows_counterclockwise:",
    "planning": ":memo:",
    "implement": ":rocket:",
    "fix": ":rocket:",
    "ci-fix": ":wrench:",
    "impl-review": ":arrows_counterclockwise:",
    "impl-revise": ":arrows_counterclockwise:",
    "split-proposal": ":scissors:",
    "split-execute": ":scissors:",
    "done": ":white_check_mark:",
    "error": ":x:",
    "timeout": ":hourglass:",
    "suspended": ":pause_button:",
}

# カラーバー定義
NOTIFICATION_COLORS: dict[str, str] = {
    "start": "#1E90FF",      # 青: 処理開始
    "success": "#2EB67D",    # 緑: 正常完了
    "waiting": "#ECB22E",    # 黄: ユーザー操作待ち
    "error": "#E01E5A",      # 赤: エラー
}

# 通知タイプ → カラー種別のマッピング
_NOTIFICATION_TYPE_COLOR: dict[str, str] = {
    "phase_start": "start",
    "phase_complete": "success",
    "hearing_question": "waiting",
    "plan_posted": "waiting",
    "design_pr_created": "waiting",
    "design_revised": "success",
    "planning_complete": "success",
    "impl_pr_created": "waiting",
    "fix_pr_created": "waiting",
    "ci_fix_complete": "success",
    "impl_revised": "success",
    "split_proposed": "waiting",
    "split_complete": "success",
    "done": "success",
    "error": "error",
    "timeout": "error",
}

# タイプ別ステップ定義
# 各タプル: (Phase値, ステップラベル)
# ※ Phase enum の値 ("type-detection" 等) をキーに使用
PHASE_STEPS: dict[str, list[tuple[str, str]]] = {
    "bug": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("analysis", "原因分析"),
        ("plan-brief", "方針提示"),
        ("fix", "修正実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-s": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("plan-brief", "方針提示"),
        ("implement", "実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-m": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("design", "設計"),
        ("planning", "実装計画"),
        ("implement", "実装"),
        ("ci-fix", "CI修正"),
        ("done", "完了"),
    ],
    "feature-l": [
        ("type-detection", "タイプ判定"),
        ("hearing", "ヒアリング"),
        ("split-proposal", "分割"),
        ("done", "完了"),
    ],
}

# フェーズの日本語ラベル
PHASE_LABELS: dict[str, str] = {
    "type-detection": "タイプ判定",
    "hearing": "ヒアリング",
    "hearing-wait": "回答待ち",
    "analysis": "原因分析",
    "plan-brief": "方針作成",
    "plan-review": "方針レビュー待ち",
    "design": "設計",
    "design-review": "設計レビュー待ち",
    "design-revise": "設計レビュー対応",
    "planning": "実装計画",
    "implement": "実装",
    "fix": "修正",
    "ci-fix": "CI修正",
    "impl-review": "実装レビュー待ち",
    "impl-revise": "実装レビュー対応",
    "split-proposal": "Issue分割提案",
    "split-execute": "Issue分割実行",
    "done": "完了",
}
```

**注意**: Phase enum の値は `"type-detection"` (ハイフン区切り) である。
設計書には `"type_detection"` (アンダースコア) と記載されているが、実際の `Phase` enum に合わせてハイフンを使用する。

### 1.2 `_build_payload()` の全面改修

現在の `blocks` 直下構造 → `attachments[0].blocks` 構造に変更する。

**変更前 (概要)**:
```python
def _build_payload(self, message, *, channel, level, metadata):
    emoji = self._level_emoji(level)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": f"{emoji} {message}"}}]
    # ... context 追加
    payload = {"blocks": blocks}
    # ... channel 設定
    return payload
```

**変更後 (概要)**:
```python
def _build_payload(self, message, *, channel, level, metadata):
    meta = metadata or {}
    notification_type = meta.get("notification_type", "")
    color = self._resolve_color(notification_type, level)
    blocks = self._build_blocks(message, level, meta)

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

### 1.3 新規内部メソッドの追加

以下のメソッドを `SlackNotifier` クラスに追加する。

#### `_build_blocks()`
```python
def _build_blocks(
    self, message: str, level: str, metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    """全ブロックを組み立てて返す."""
    blocks: list[dict[str, Any]] = []
    phase = metadata.get("phase")

    # 1. Header block
    blocks.append(self._build_header_block(phase, level, metadata))

    # 2. Divider
    blocks.append({"type": "divider"})

    # 3. Message section
    blocks.append(self._build_message_block(message, phase))

    # 4. Actions block (リンクボタン、URLがある場合のみ)
    actions = self._build_actions_block(metadata)
    if actions is not None:
        blocks.append(actions)

    # 5. Divider
    blocks.append({"type": "divider"})

    # 6. Stats section (進捗・経過時間・変更ファイル数)
    stats = self._build_stats_block(metadata)
    if stats is not None:
        blocks.append(stats)
        blocks.append({"type": "divider"})

    # 7. Context block (メタデータ)
    context = self._build_context_block(metadata)
    if context is not None:
        blocks.append(context)

    return blocks
```

#### `_resolve_color()`
```python
def _resolve_color(self, notification_type: str, level: str) -> str:
    """通知種別・レベルからカラーバーの色を決定する."""
    # 1. notification_type による判定
    color_key = _NOTIFICATION_TYPE_COLOR.get(notification_type)
    if color_key:
        return NOTIFICATION_COLORS[color_key]

    # 2. level によるフォールバック
    if level in ("error", "critical"):
        return NOTIFICATION_COLORS["error"]

    return NOTIFICATION_COLORS["start"]
```

#### `_build_header_block()`
```python
def _build_header_block(
    self, phase: str | None, level: str, metadata: dict[str, Any]
) -> dict[str, Any]:
    """Header block を構築する."""
    emoji = self._phase_emoji(phase) if phase else self._level_emoji(level)
    phase_label = PHASE_LABELS.get(phase or "", phase or "通知")
    notification_type = metadata.get("notification_type", "")

    if notification_type == "phase_start":
        title = f"{emoji} {phase_label}フェーズ開始"
    elif level in ("error", "critical"):
        title = f"{emoji} エラー発生"
    elif phase == "done":
        title = f"{emoji} Issue完了"
    else:
        title = f"{emoji} {phase_label}フェーズ完了"

    return {
        "type": "header",
        "text": {"type": "plain_text", "text": title},
    }
```

#### `_build_message_block()`
```python
def _build_message_block(self, message: str, phase: str | None) -> dict[str, Any]:
    """メッセージ本文の Section block を構築する."""
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": message},
    }
```

#### `_build_actions_block()`
```python
def _build_actions_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """リンクボタンの Actions block を構築する (URL がある場合のみ)."""
    elements: list[dict[str, Any]] = []
    repo = metadata.get("repo")
    issue = metadata.get("issue")
    pr = metadata.get("pr")
    pr_url = metadata.get("pr_url")
    design_pr = metadata.get("design_pr")
    design_pr_url = metadata.get("design_pr_url")

    # Issue ボタン
    if repo and issue is not None:
        issue_url = f"https://github.com/{repo}/issues/{issue}"
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Issue を見る"},
            "url": issue_url,
        })

    # PR ボタン
    if pr_url:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "PR を見る"},
            "url": pr_url,
        })
    elif repo and pr is not None:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "PR を見る"},
            "url": f"https://github.com/{repo}/pull/{pr}",
        })

    # 設計PR ボタン
    if design_pr_url:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "設計PR を見る"},
            "url": design_pr_url,
        })
    elif repo and design_pr is not None:
        elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "設計PR を見る"},
            "url": f"https://github.com/{repo}/pull/{design_pr}",
        })

    if not elements:
        return None

    return {"type": "actions", "elements": elements}
```

#### `_build_stats_block()`
```python
def _build_stats_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """進捗・経過時間・変更ファイル数の Section block を構築する."""
    parts: list[str] = []

    # 進捗
    progress = self._build_progress_text(metadata)
    if progress:
        parts.append(progress)

    # 経過時間
    duration = metadata.get("duration_sec")
    if duration is not None:
        parts.append(f":stopwatch: *経過:* {self._format_duration(duration)}")

    # 変更ファイル数
    files_changed = metadata.get("files_changed")
    if files_changed is not None:
        added = metadata.get("lines_added", 0)
        deleted = metadata.get("lines_deleted", 0)
        parts.append(
            f":file_folder: *変更:* {files_changed}ファイル (+{added} -{deleted})"
        )

    # CI結果
    ci_total = metadata.get("ci_total")
    if ci_total is not None:
        ci_passed = metadata.get("ci_passed", 0)
        ci_failed = metadata.get("ci_failed", 0)
        parts.append(
            f":test_tube: *CI:* {ci_passed}pass / {ci_failed}fail (計{ci_total})"
        )

    if not parts:
        return None

    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(parts)},
    }
```

#### `_build_context_block()`
```python
def _build_context_block(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
    """メタデータの Context block を構築する."""
    parts: list[str] = []

    issue_type = metadata.get("issue_type")
    if issue_type:
        parts.append(f":label: {issue_type}")

    repo = metadata.get("repo")
    if repo:
        parts.append(f":package: `{repo}`")

    parts.append(":robot_face: AI Agent")

    return {
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": " | ".join(parts)},
        ],
    }
```

#### ユーティリティメソッド
```python
@staticmethod
def _phase_emoji(phase: str | None) -> str:
    """フェーズに応じた絵文字を返す."""
    if phase is None:
        return ":robot_face:"
    return PHASE_EMOJI.get(phase, ":robot_face:")

@staticmethod
def _format_duration(seconds: float) -> str:
    """秒数を人間可読な文字列に変換する (例: '2分34秒')."""
    total = int(seconds)
    if total < 60:
        return f"{total}秒"
    minutes, secs = divmod(total, 60)
    if secs == 0:
        return f"{minutes}分"
    return f"{minutes}分{secs}秒"

@staticmethod
def _build_progress_text(metadata: dict[str, Any]) -> str | None:
    """進捗ステータスのテキストを構築する (例: '[3/7] 設計完了')."""
    step_current = metadata.get("step_current")
    step_total = metadata.get("step_total")
    step_label = metadata.get("step_label")

    if step_current is None or step_total is None:
        return None

    label_part = f" {step_label}" if step_label else ""
    return f":bar_chart: *進捗:* `[{step_current}/{step_total}]`{label_part}"
```

### 1.4 既存メソッドの変更

- `_level_emoji()`: 変更なし（後方互換のため残す）
- `_build_context_text()`: **削除**（`_build_context_block()` に置き換え）

### 1.5 公開ヘルパー関数の追加

`base.py` や各フェーズから利用するためのモジュールレベル関数を追加する。

```python
def resolve_step(
    phase: str, issue_type: str | None
) -> tuple[int | None, int | None, str | None]:
    """フェーズとIssueタイプからステップ情報を返す.

    Args:
        phase: Phase enum の値 (例: "implement").
        issue_type: IssueType の値 (例: "feature-m").

    Returns:
        (step_current, step_total, step_label) のタプル。
        不明な場合は (None, None, None)。
    """
    if not issue_type:
        return None, None, None
    steps = PHASE_STEPS.get(issue_type, [])
    for i, (phase_key, label) in enumerate(steps, 1):
        if phase_key == phase:
            return i, len(steps), label
    return None, None, None
```

---

## Step 2: `src/ai_agent_orchestrator/phases/base.py`

**依存: Step 1 完了後**

### 2.1 import の追加

```python
import time

from ai_agent_orchestrator.notifications.slack import (
    PHASE_LABELS,
    resolve_step,
)
```

### 2.2 `PhaseExecutor` クラスの変更

#### `execute()` メソッドの変更

`try` ブロックの先頭に開始通知を追加し、経過時間計測を導入する。

**変更箇所** (`execute()` メソッド、L284-321):

```python
async def execute(self, request: TaskRequest) -> None:
    self._phase_start_time = time.monotonic()

    try:
        # フェーズ開始通知（新規追加）
        await self._notify_phase_start(request)

        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )

        prompt = await self.build_prompt(request)
        await self._record_branch_baseline(request)
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
```

#### 新規メソッド: `_notify_phase_start()`

```python
async def _notify_phase_start(self, request: TaskRequest) -> None:
    """フェーズ開始通知を送信する."""
    phase_str = str(request.phase)
    phase_label = PHASE_LABELS.get(phase_str, phase_str)
    issue_type = self._sm.get_issue_type(request.issue_number)
    step_current, step_total, step_label = resolve_step(phase_str, issue_type or None)

    repo_owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    repo_full = f"{repo_owner}/{repo_name}" if repo_owner and repo_name else None

    await self._notifier.notify(
        f"Issue #{request.issue_number} の{phase_label}を開始します",
        metadata={
            "repo": repo_full,
            "issue": request.issue_number,
            "phase": phase_str,
            "notification_type": "phase_start",
            "issue_type": issue_type or None,
            "step_current": step_current,
            "step_total": step_total,
            "step_label": step_label,
        },
    )
```

#### 新規プロパティ: `elapsed_sec`

```python
@property
def elapsed_sec(self) -> float:
    """フェーズ開始からの経過時間（秒）."""
    if not hasattr(self, "_phase_start_time"):
        return 0.0
    return time.monotonic() - self._phase_start_time
```

#### 新規ヘルパー: `_build_notify_metadata()`

各フェーズから使いやすい共通メタデータ構築ヘルパー。

```python
def _build_notify_metadata(
    self,
    request: TaskRequest,
    *,
    notification_type: str = "phase_complete",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """通知用メタデータを構築するヘルパー."""
    phase_str = str(request.phase)
    issue_type = self._sm.get_issue_type(request.issue_number)
    step_current, step_total, step_label = resolve_step(phase_str, issue_type or None)
    repo_owner = getattr(request.repo, "owner", "")
    repo_name = getattr(request.repo, "repo", "")
    repo_full = f"{repo_owner}/{repo_name}" if repo_owner and repo_name else None

    meta: dict[str, Any] = {
        "repo": repo_full,
        "issue": request.issue_number,
        "phase": phase_str,
        "notification_type": notification_type,
        "issue_type": issue_type or None,
        "duration_sec": self.elapsed_sec,
        "step_current": step_current,
        "step_total": step_total,
        "step_label": step_label,
    }
    if extra:
        meta.update(extra)
    return meta
```

#### `_handle_timeout()` の改修

既存の notify 呼び出しに metadata を拡張する。

```python
async def _handle_timeout(self, request: TaskRequest) -> None:
    # ... 既存のセッション中断・遷移ロジックはそのまま ...
    await self._notifier.notify(
        f"Issue #{request.issue_number} がタイムアウトしました (phase: {request.phase})",
        level="error",
        metadata=self._build_notify_metadata(
            request,
            notification_type="timeout",
        ),
    )
```

#### `_handle_error()` の改修

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    # ... 既存の遷移・コメントロジックはそのまま ...
    await self._notifier.notify(
        f"Issue #{request.issue_number} でエラー: {error} (phase: {request.phase})",
        level="error",
        metadata=self._build_notify_metadata(
            request,
            notification_type="error",
            extra={"error": str(error)},
        ),
    )
```

---

## Step 3: 各フェーズファイルの `notify()` 呼び出し改修

**依存: Step 2 完了後**

全フェーズの完了通知で `self._build_notify_metadata()` を使い metadata を拡張する。
以下、各ファイルの具体的な変更内容を記載する。

### 3.1 `phases/type_detection.py`

**現状**: 通知なし
**変更**: `process_result()` 内に完了通知を追加

```python
# process_result() の末尾に追加
issue_type = self._sm.get_issue_type(request.issue_number)
await self._notifier.notify(
    f"Issue #{request.issue_number} のタイプ判定完了: {issue_type}",
    metadata=self._build_notify_metadata(
        request,
        notification_type="phase_complete",
    ),
)
```

### 3.2 `phases/hearing.py`

**現状**: `metadata={"issue": request.issue_number}`
**変更**: `_build_notify_metadata()` を使用

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    metadata=self._build_notify_metadata(
        request,
        notification_type="hearing_question",
    ),
)
```

### 3.3 `phases/analysis.py`

**現状**: `metadata={"issue": request.issue_number}`
**変更**:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の修正方針を投稿しました。thumbsup で承認をお願いします",
    metadata=self._build_notify_metadata(
        request,
        notification_type="plan_posted",
    ),
)
```

### 3.4 `phases/plan_brief.py`

**現状**: `metadata={"issue": request.issue_number}`
**変更**:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装方針を投稿しました。thumbsup で承認をお願いします",
    metadata=self._build_notify_metadata(
        request,
        notification_type="plan_posted",
    ),
)
```

### 3.5 `phases/design.py`

**現状**: `metadata={"issue": ..., "pr": pr_number}`
**変更**:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の設計PR #{pr_number} を作成しました。レビューをお願いします",
    metadata=self._build_notify_metadata(
        request,
        notification_type="design_pr_created",
        extra={
            "design_pr": pr_number,
            "design_pr_url": f"https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}",
        },
    ),
)
```

### 3.6 `phases/design_revise.py`

**現状**: `metadata={"issue": request.issue_number}`
**変更**:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の設計書を修正しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="design_revised",
    ),
)
```

### 3.7 `phases/planning.py`

**現状**: 通知なし
**変更**: `process_result()` 末尾に完了通知を追加

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装計画が完了しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="planning_complete",
    ),
)
```

### 3.8 `phases/implement.py`

**現状**: `metadata={"issue": ..., "pr": pr_number}`
**変更**: PR作成後に変更ファイル数・行数情報を追加

```python
# PR情報の取得（GitHub APIから。もしくはエージェント出力から取得可能であればそこから）
# ※ 取得が困難な場合は files_changed 等は None のまま送信
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装PR #{pr_number} を作成しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="impl_pr_created",
        extra={
            "pr": pr_number,
            "pr_url": f"https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}",
            "step_label": "実装完了",
        },
    ),
)
```

**補足**: 変更ファイル数・行数の取得は GitHub API の `get_pull()` が必要。
`GitHubClientProtocol` に `get_pull()` メソッドが存在しない場合は追加を検討するが、
**Phase 1 としては省略し、metadata キーは定義するが値は None にする**。
後続の改善で GitHub API 連携を追加する。

### 3.9 `phases/fix.py`

**現状**: `metadata={"issue": ..., "pr": pr_number}`
**変更**: `implement.py` と同様のパターン

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の修正PR #{pr_number} を作成しました。レビュー待ちです",
    metadata=self._build_notify_metadata(
        request,
        notification_type="fix_pr_created",
        extra={
            "pr": pr_number,
            "pr_url": f"https://github.com/{repo_owner}/{repo_name}/pull/{pr_number}",
        },
    ),
)
```

### 3.10 `phases/ci_fix.py`

**現状**: 通知なし
**変更**: `process_result()` 末尾に完了通知を追加

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} のCI修正が完了しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="ci_fix_complete",
    ),
)
```

### 3.11 `phases/impl_revise.py`

**現状**: `metadata={"issue": request.issue_number}`
**変更**:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装を修正しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="impl_revised",
    ),
)
```

### 3.12 `phases/split.py`

**SplitProposalExecutor**:
```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の分割を提案しました。判断をお願いします",
    metadata=self._build_notify_metadata(
        request,
        notification_type="split_proposed",
    ),
)
```

**SplitExecuteExecutor**:
```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の分割が完了しました",
    metadata=self._build_notify_metadata(
        request,
        notification_type="split_complete",
    ),
)
```

### 3.13 `phases/done.py`

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} 完了しました :tada:",
    metadata=self._build_notify_metadata(
        request,
        notification_type="done",
        extra={
            "pr": state.pr_number if state else None,
            "pr_url": f"https://github.com/{repo_owner}/{repo_name}/pull/{state.pr_number}"
                      if state and state.pr_number else None,
        },
    ),
)
```

---

## Step 4: `tests/unit/test_slack.py`

**依存: Step 1 完了後**

### 4.1 既存テストの更新 (TC-SL-01 〜 TC-SL-13)

ペイロード構造が `blocks` 直下 → `attachments[0].blocks` に変更されるため、
全アサーション箇所を修正する。

**パターン例**:

```python
# Before
request_body = json.loads(route.calls[0].request.content)
assert "blocks" in request_body
text_block = request_body["blocks"][0]["text"]["text"]

# After
request_body = json.loads(route.calls[0].request.content)
assert "attachments" in request_body
blocks = request_body["attachments"][0]["blocks"]
# Header が先頭なので message section は blocks[2] (header, divider, section)
```

**具体的な変更点**:

| テスト | 変更内容 |
|--------|---------|
| TC-SL-01 | `attachments[0].blocks` からメッセージセクションを検索。絵文字はヘッダーに移動 |
| TC-SL-02 | ヘッダーブロックの text に `:x:` が含まれることを確認 |
| TC-SL-03 | ヘッダーブロックの text に `:rotating_light:` が含まれることを確認 |
| TC-SL-04 | `attachments[0].blocks` からコンテキストブロックを検索 |
| TC-SL-05 | 変更なし（例外が出ないことの確認のみ） |
| TC-SL-06 | 変更なし（チャンネル検証のみ） |
| TC-SL-07 | 変更なし（チャンネル検証のみ） |
| TC-SL-08 | 変更なし（send() の低レベルテスト） |
| TC-SL-09 | 変更なし（close() テスト） |
| TC-SL-10 | 変更なし（_level_emoji は残す） |
| TC-SL-11 | 変更なし（ネットワークエラー） |
| TC-SL-12 | `attachments[0].blocks` からブロック数を確認 |
| TC-SL-13 | 変更なし（channel キーの有無） |

### 4.2 新規テストケースの追加

```python
# TC-SL-14: _phase_emoji のマッピング
def test_phase_emoji_mapping() -> None:
    assert SlackNotifier._phase_emoji("implement") == ":rocket:"
    assert SlackNotifier._phase_emoji("done") == ":white_check_mark:"
    assert SlackNotifier._phase_emoji("hearing") == ":speech_balloon:"
    assert SlackNotifier._phase_emoji(None) == ":robot_face:"
    assert SlackNotifier._phase_emoji("unknown") == ":robot_face:"

# TC-SL-15: _resolve_color のテスト
def test_resolve_color() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    assert n._resolve_color("phase_start", "info") == "#1E90FF"
    assert n._resolve_color("done", "info") == "#2EB67D"
    assert n._resolve_color("error", "error") == "#E01E5A"
    assert n._resolve_color("", "error") == "#E01E5A"  # level フォールバック
    assert n._resolve_color("", "info") == "#1E90FF"   # デフォルト

# TC-SL-16: _build_header_block のテスト
def test_build_header_block_phase_start() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    block = n._build_header_block("implement", "info", {"notification_type": "phase_start"})
    assert block["type"] == "header"
    assert ":rocket:" in block["text"]["text"]
    assert "開始" in block["text"]["text"]

# TC-SL-17: _build_actions_block の URL ボタン
def test_build_actions_block_with_urls() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    actions = n._build_actions_block({
        "repo": "org/repo",
        "issue": 42,
        "pr_url": "https://github.com/org/repo/pull/11",
    })
    assert actions is not None
    assert actions["type"] == "actions"
    assert len(actions["elements"]) == 2  # Issue + PR

# TC-SL-18: _build_actions_block が URL なしで None
def test_build_actions_block_returns_none_without_urls() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    assert n._build_actions_block({}) is None

# TC-SL-19: _build_stats_block のテスト
def test_build_stats_block_with_full_metadata() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    stats = n._build_stats_block({
        "step_current": 5,
        "step_total": 7,
        "step_label": "実装完了",
        "duration_sec": 312.5,
        "files_changed": 8,
        "lines_added": 250,
        "lines_deleted": 40,
    })
    assert stats is not None
    text = stats["text"]["text"]
    assert "[5/7]" in text
    assert "5分12秒" in text
    assert "8ファイル" in text

# TC-SL-20: _build_stats_block が情報なしで None
def test_build_stats_block_returns_none_without_data() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    assert n._build_stats_block({}) is None

# TC-SL-21: _format_duration のテスト
def test_format_duration() -> None:
    assert SlackNotifier._format_duration(30) == "30秒"
    assert SlackNotifier._format_duration(60) == "1分"
    assert SlackNotifier._format_duration(154.5) == "2分34秒"
    assert SlackNotifier._format_duration(0) == "0秒"

# TC-SL-22: _build_progress_text のテスト
def test_build_progress_text() -> None:
    assert SlackNotifier._build_progress_text({
        "step_current": 3, "step_total": 7, "step_label": "設計完了"
    }) == ":bar_chart: *進捗:* `[3/7]` 設計完了"
    assert SlackNotifier._build_progress_text({}) is None

# TC-SL-23: 全体ペイロードに attachments.color が含まれる
@respx.mock
async def test_payload_has_attachment_color(notifier: SlackNotifier) -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
    await notifier.notify("テスト", metadata={"phase": "implement"})
    body = json.loads(route.calls[0].request.content)
    assert "attachments" in body
    assert "color" in body["attachments"][0]

# TC-SL-24: 開始通知で青色カラーバー
@respx.mock
async def test_phase_start_has_blue_color(notifier: SlackNotifier) -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
    await notifier.notify("テスト", metadata={"notification_type": "phase_start"})
    body = json.loads(route.calls[0].request.content)
    assert body["attachments"][0]["color"] == "#1E90FF"

# TC-SL-25: エラー通知で赤色カラーバー
@respx.mock
async def test_error_has_red_color(notifier: SlackNotifier) -> None:
    route = respx.post(WEBHOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
    await notifier.notify("テスト", level="error", metadata={"notification_type": "error"})
    body = json.loads(route.calls[0].request.content)
    assert body["attachments"][0]["color"] == "#E01E5A"

# TC-SL-26: _build_context_block が issue_type を含む
def test_build_context_block_includes_issue_type() -> None:
    n = SlackNotifier(webhook_url=WEBHOOK_URL)
    ctx = n._build_context_block({"issue_type": "feature-m", "repo": "org/repo"})
    assert ctx is not None
    text = ctx["elements"][0]["text"]
    assert "feature-m" in text
    assert "org/repo" in text

# TC-SL-27: resolve_step のテスト
def test_resolve_step() -> None:
    from ai_agent_orchestrator.notifications.slack import resolve_step
    current, total, label = resolve_step("implement", "feature-m")
    assert current == 5
    assert total == 7
    assert label == "実装"

    # 不明な場合
    current, total, label = resolve_step("implement", None)
    assert current is None

# TC-SL-28: resolve_step のタイプ別テスト
def test_resolve_step_bug_type() -> None:
    from ai_agent_orchestrator.notifications.slack import resolve_step
    current, total, label = resolve_step("fix", "bug")
    assert current == 5
    assert total == 7
    assert label == "修正実装"
```

---

## Step 5: `docs/specs/slack.md`

**依存: Step 1 完了後**

以下を更新する:
- 通知タイプ表にフェーズ開始通知を追加
- ペイロード構造例を `attachments` ベースに刷新
- 新規メソッド一覧の追加
- 定数（`PHASE_EMOJI`, `NOTIFICATION_COLORS`, `PHASE_STEPS`, `PHASE_LABELS`）の記載
- テストケース一覧の更新（TC-SL-14 〜 TC-SL-28 追加）
- `NotificationMetadata` dataclass の記載（参考情報として）

---

## テスト方針

### 実行方法

```bash
# slack.py 関連のテストのみ実行
uv run pytest tests/unit/test_slack.py -v

# 全テスト
uv run pytest tests/ -v

# 型チェック
uv run mypy src/

# lint
uv run ruff check src/ tests/
```

### テスト戦略

1. **Step 1 完了後**: `test_slack.py` の既存テストを更新し、新規テストを追加。ここで `slack.py` 単体の動作を確認
2. **Step 2 完了後**: `base.py` の `_notify_phase_start` テストを `test_phases.py` に追加（FakeNotifier で検証）
3. **Step 3 完了後**: 各フェーズのテストで metadata が正しく拡張されていることを検証
4. **全 Step 完了後**: `uv run pytest tests/ -v && uv run mypy src/ && uv run ruff check src/ tests/` で全体確認

### テストのスコープ

- **ユニットテスト**: `slack.py` のメソッド単位テスト（TC-SL-14 〜 TC-SL-28）
- **既存テスト更新**: TC-SL-01 〜 TC-SL-13 のペイロード構造アサーション修正
- **統合テスト**: `base.py` の開始通知が `FakeNotifier` 経由で送信されることを確認
- **Phase ファイルの notify 検証**: 各フェーズの `process_result()` 内で拡張 metadata が渡されることの確認

---

## リスク対策

| リスク | 対策 |
|--------|------|
| `Phase` enum 値がハイフン区切り (`type-detection`) と設計書のアンダースコア (`type_detection`) の不一致 | 実装では `Phase` enum の実際の値 (ハイフン) を使用する。`PHASE_STEPS` 等の定数もハイフン区切りで定義する |
| `TaskRequest.repo` の型が `str` だが実際は `RepositoryConfig` オブジェクト | `getattr(request.repo, "owner", "")` で安全にアクセスする（既存の `base.py` パターンに従う） |
| `_build_context_text()` 削除による後方互換性 | `_build_context_text()` はプライベートメソッドで外部から呼ばれていないため安全に削除可能 |
| Header block が Webhook で表示されない場合 | `_build_header_block()` のフォールバックとして `section` + bold テキストを用意（Phase 2 で対応） |

---

## 見積もり

| Step | 工数 | ファイル数 |
|------|------|----------|
| Step 1: slack.py | 大 | 1 |
| Step 2: base.py | 中 | 1 |
| Step 3: 各フェーズ | 中 | 13 |
| Step 4: テスト | 大 | 1 |
| Step 5: 仕様書 | 小 | 1 |
| **合計** | | **17ファイル** |
