# Issue #18: Slack メッセージ改善 — 実装計画

## 1. 変更ファイル一覧と実装順序

依存関係に基づき、以下の順序で実装する。

| 順序 | ファイル | 変更種別 | 影響度 | 依存先 |
|:----:|---------|---------|:------:|-------|
| 1 | `src/ai_agent_orchestrator/models.py` | 追加 | 小 | なし |
| 2 | `src/ai_agent_orchestrator/notifications/slack.py` | 全面改修 | **大** | Step 1 |
| 3 | `src/ai_agent_orchestrator/phases/base.py` | 改修 | **中** | Step 2 |
| 4-A | `src/ai_agent_orchestrator/phases/hearing.py` | 小修正 | 小 | Step 3 |
| 4-B | `src/ai_agent_orchestrator/phases/analysis.py` | 小修正 | 小 | Step 3 |
| 4-C | `src/ai_agent_orchestrator/phases/plan_brief.py` | 小修正 | 小 | Step 3 |
| 4-D | `src/ai_agent_orchestrator/phases/design.py` | 小修正 | 小 | Step 3 |
| 4-E | `src/ai_agent_orchestrator/phases/design_revise.py` | 小修正 | 小 | Step 3 |
| 4-F | `src/ai_agent_orchestrator/phases/planning.py` | 小修正 | 小 | Step 3 |
| 4-G | `src/ai_agent_orchestrator/phases/implement.py` | 小修正 | 小 | Step 3 |
| 4-H | `src/ai_agent_orchestrator/phases/impl_revise.py` | 小修正 | 小 | Step 3 |
| 4-I | `src/ai_agent_orchestrator/phases/fix.py` | 小修正 | 小 | Step 3 |
| 4-J | `src/ai_agent_orchestrator/phases/ci_fix.py` | 小修正 | 小 | Step 3 |
| 4-K | `src/ai_agent_orchestrator/phases/type_detection.py` | 小修正 | 小 | Step 3 |
| 4-L | `src/ai_agent_orchestrator/phases/split.py` | 小修正 | 小 | Step 3 |
| 4-M | `src/ai_agent_orchestrator/phases/done.py` | 小修正 | 小 | Step 3 |
| 5 | `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | 改修 | **中** | Step 2 |
| 6 | `tests/unit/test_slack.py` | 全面更新 | **大** | Step 2 |
| 7 | `tests/unit/test_phases.py` | 追加・更新 | **中** | Step 3 |
| 8 | `docs/specs/slack.md` | 更新 | 小 | 全ステップ完了後 |

---

## 2. Step 1: `models.py` — NotificationType Enum 追加

### 変更箇所
ファイル末尾（`ErrorCategory` / `ApprovalMethod` の直後）に `NotificationType` StrEnum を追加する。

### 具体的な変更内容

```python
class NotificationType(StrEnum):
    """Slack 通知タイプ."""

    PHASE_START = "phase_start"
    PHASE_END = "phase_end"
    HEARING_QUESTION = "hearing_question"
    PLAN_POSTED = "plan_posted"
    DESIGN_PR_CREATED = "design_pr_created"
    DESIGN_REVISED = "design_revised"
    IMPL_PR_CREATED = "impl_pr_created"
    IMPL_REVISED = "impl_revised"
    FIX_PR_CREATED = "fix_pr_created"
    SPLIT_PROPOSED = "split_proposed"
    SPLIT_COMPLETED = "split_completed"
    ISSUE_DONE = "issue_done"
    CHAIN_START = "chain_start"
    ERROR = "error"
    TIMEOUT = "timeout"
    ORCHESTRATOR_START = "orchestrator_start"
    ORCHESTRATOR_ERROR = "orchestrator_error"
    HEALTH_CHECK_FAIL = "health_check_fail"
    ISSUE_SUSPENDED = "issue_suspended"
```

**挿入位置**: `ApprovalMethod` クラス定義の直後（105行目以降）

---

## 3. Step 2: `slack.py` — SlackNotifier 全面リファクタリング

### 3.1 概要

既存の `_build_payload` + `_level_emoji` + `_build_context_text` を、リッチフォーマット対応の新メソッド群に置き換える。`send()` と `close()` は変更なし。

### 3.2 具体的な変更内容

#### 3.2.1 モジュールレベル定数の追加

既存の `_LEVEL_EMOJI` を削除し、以下の定数を追加する:

```python
_NOTIFICATION_CONFIG: dict[str, dict[str, str]] = {
    "phase_start":        {"emoji": "▶️",  "level": "info"},
    "phase_end":          {"emoji": "⏹️",  "level": "info"},
    "hearing_question":   {"emoji": "💬", "level": "info"},
    "plan_posted":        {"emoji": "📋", "level": "info"},
    "design_pr_created":  {"emoji": "📐", "level": "info"},
    "design_revised":     {"emoji": "✏️",  "level": "info"},
    "impl_pr_created":    {"emoji": "🚀", "level": "info"},
    "impl_revised":       {"emoji": "🔧", "level": "info"},
    "fix_pr_created":     {"emoji": "🐛", "level": "info"},
    "split_proposed":     {"emoji": "✂️",  "level": "info"},
    "split_completed":    {"emoji": "📦", "level": "info"},
    "issue_done":         {"emoji": "✅", "level": "info"},
    "chain_start":        {"emoji": "🔗", "level": "info"},
    "error":              {"emoji": "❌", "level": "error"},
    "timeout":            {"emoji": "⏰", "level": "error"},
    "issue_suspended":    {"emoji": "⏸️",  "level": "error"},
    "orchestrator_start": {"emoji": "🤖", "level": "info"},
    "orchestrator_error": {"emoji": "🚨", "level": "critical"},
    "health_check_fail":  {"emoji": "💔", "level": "critical"},
}

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

#### 3.2.2 `notify()` メソッドのシグネチャ変更

**現行:**
```python
async def notify(self, message, *, channel=None, level="info", metadata=None)
```

**新規:**
```python
async def notify(self, message, *, notification_type="phase_end", channel=None, level="info", metadata=None)
```

内部実装:
- `_build_payload` → `_build_rich_payload` に委譲
- `notification_type` パラメータを渡す

#### 3.2.3 新メソッド: `_build_rich_payload()`

Block Kit ペイロードを以下の構成で構築:
1. **header** ブロック: `{emoji} {タイトル}` (plain_text, emoji: true)
2. **divider** ブロック
3. **section** ブロック: mrkdwn 本文 (`_build_body()` で構築)
4. **context** ブロック (任意): `_build_rich_context()` で構築、パーツがない場合は省略

`channel` の解決ロジックは既存と同一。

#### 3.2.4 新メソッド: `_build_header_title(notification_type, meta)`

- `notification_type` → 日本語タイトル辞書から検索
- `phase_start` / `phase_end` の場合は `meta["phase"]` → `_PHASE_LABELS` で変換して `"{ラベル}フェーズ開始"` / `"{ラベル}フェーズ完了"` を生成
- 未知の `notification_type` は `"通知"` にフォールバック

#### 3.2.5 新メソッド: `_build_body(message, meta)`

構成:
1. Issue リンク + タイトル: `<{url}|Issue #N>: *{title}*` (repo + issue + issue_title がある場合)
   - `issue_title` がない場合はリンクのみ
   - `repo` がない場合は Issue リンクを省略
2. メッセージ本文 (`message` 引数)
3. スタックトレース (エラー時): ` ```\n{truncated}\n``` `
   - `meta["stacktrace"]` を最大5行に切り詰め
   - 空文字列・空白のみの場合は省略

各パーツを `"\n"` で結合。

#### 3.2.6 新メソッド: `_build_rich_context(meta)`

既存 `_build_context_text()` を置き換え。以下の順序でパーツを構築し `" | "` で結合:

1. `repo` → `📦 \`{repo}\``
2. `pr` + `pr_url` → `🔗 <{pr_url}|PR #{pr}>`
   - `pr_url` がない場合: `pr` + `repo` → 自動生成 URL
   - `pr` のみ（`repo`/`pr_url` なし）の場合は省略
3. `issue_type` → `🏷️ \`{issue_type}\``
4. `duration_sec` → `⏱️ {分}分{秒}秒` (int 変換、時間単位への変換はしない)
5. `cost_usd` → `💰 ${value:.2f}`
6. `files_changed` → `📁 {N} files changed`
7. `commit_count` → `📝 {N} commits`
8. `ci_url` → `🔄 <{ci_url}|CI>`

パーツが0個の場合は `None` を返す。

#### 3.2.7 削除するもの

- `_LEVEL_EMOJI` 定数
- `_level_emoji()` staticmethod
- `_build_payload()` メソッド
- `_build_context_text()` staticmethod

---

## 4. Step 3: `base.py` — フェーズ開始通知 + エラー通知改善

### 4.1 NotifierProtocol の更新

`notification_type` パラメータを追加:

```python
class NotifierProtocol:
    """Minimal notifier protocol."""

    async def notify(
        self,
        message: str,
        *,
        notification_type: str = "phase_end",
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Send a notification."""
        ...  # pragma: no cover
```

### 4.2 `execute()` テンプレートメソッドの変更

`phase_start` トラック呼び出しの**直前**に、フェーズ開始通知を追加:

```python
async def execute(self, request: TaskRequest) -> None:
    try:
        # --- 開始通知（新規追加）---
        await self._notify_phase_start(request)

        await self._tracker.track(
            "phase_start",
            issue_number=request.issue_number,
            phase=str(request.phase),
        )
        # ... 以下既存のまま
```

### 4.3 新メソッド: `_notify_phase_start(request)`

```python
async def _notify_phase_start(self, request: TaskRequest) -> None:
    """フェーズ開始通知を送信する."""
    meta: dict[str, Any] = {
        "issue": request.issue_number,
        "phase": str(request.phase),
    }
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

### 4.4 `_handle_timeout()` の変更

既存の `notify()` 呼び出しに `notification_type="timeout"` を追加:

```python
await self._notifier.notify(
    f"Issue #{request.issue_number} がタイムアウトしました (phase: {request.phase})",
    notification_type="timeout",
    level="error",
    metadata={
        "issue": request.issue_number,
        "phase": str(request.phase),
    },
)
```

### 4.5 `_handle_error()` の変更

スタックトレース取得ロジックを追加し、`notification_type="error"` + `stacktrace` metadata を付与:

```python
async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
    """エラー処理: SUSPENDED 遷移 + Issue コメント + 通知."""
    import traceback

    await self._sm.transition(request.issue_number, "suspended")
    client = await self._get_client(request.repo)
    try:
        await client.replace_phase_label(request.repo, request.issue_number, "phase:suspended")
    except Exception:
        logger.warning("Failed to update phase label to suspended for issue #%d", request.issue_number)
    await client.create_comment(
        request.repo,
        request.issue_number,
        f"エラーが発生しました: {error}",
    )

    # スタックトレース取得（末尾5行）
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    tb_text = "".join(tb_lines)
    tb_truncated = "\n".join(tb_text.strip().split("\n")[-5:])

    await self._notifier.notify(
        f"Issue #{request.issue_number} でエラー: {error} (phase: {request.phase})",
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

## 5. Step 4: 各フェーズファイルの notify 呼び出し更新

全フェーズの既存 `notify()` 呼び出しに `notification_type` と拡張 metadata を追加する。
**開始通知は base.py の `execute()` で一元的に送信されるため、各フェーズの個別対応は不要。**

### 5.1 hearing.py (L116)

```python
# 変更前:
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    metadata={"issue": request.issue_number, ...},
)

# 変更後:
await self._notifier.notify(
    f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
    notification_type="hearing_question",
    metadata={
        "issue": request.issue_number,
        "repo": getattr(request.repo, "full_name", str(request.repo)),
        "phase": str(request.phase),
        "issue_title": issue.title if hasattr(issue, "title") else None,
        "issue_type": self._sm.get_issue_type(request.issue_number) or None,
    },
)
```

> **注意**: `issue` 変数は `process_result` 内で既に取得済みかを確認し、取得済みの場合はそれを使う。未取得の場合は best-effort で取得する。

### 5.2 analysis.py (L78)

```python
notification_type="plan_posted"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.3 plan_brief.py (L89)

```python
notification_type="plan_posted"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.4 design.py (L89)

```python
notification_type="design_pr_created"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加（`pr`, `pr_url` は既存）。

### 5.5 design_revise.py (L85)

```python
notification_type="design_revised"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.6 planning.py

**終了通知を追加** (現在は通知なし):

`process_result` の末尾に以下を追加:
```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の実装計画を作成しました",
    notification_type="phase_end",
    metadata={
        "issue": request.issue_number,
        "repo": getattr(request.repo, "full_name", str(request.repo)),
        "phase": str(request.phase),
    },
)
```

### 5.7 implement.py (L100)

```python
notification_type="impl_pr_created"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加（`pr` は既存）。

### 5.8 impl_revise.py (L99)

```python
notification_type="impl_revised"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.9 fix.py (L97)

```python
notification_type="fix_pr_created"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加（`pr` は既存）。

### 5.10 ci_fix.py

**終了通知を追加** (現在は通知なし):

`process_result` の末尾に以下を追加:
```python
await self._notifier.notify(
    f"Issue #{request.issue_number} の CI 修正を実行しました",
    notification_type="phase_end",
    metadata={
        "issue": request.issue_number,
        "repo": getattr(request.repo, "full_name", str(request.repo)),
        "phase": str(request.phase),
    },
)
```

### 5.11 type_detection.py

**終了通知を追加** (現在は通知なし):

`process_result` の末尾に以下を追加:
```python
await self._notifier.notify(
    f"Issue #{request.issue_number} のタイプを判定しました: {detected_type}",
    notification_type="phase_end",
    metadata={
        "issue": request.issue_number,
        "repo": getattr(request.repo, "full_name", str(request.repo)),
        "phase": str(request.phase),
        "issue_type": detected_type,
    },
)
```

### 5.12 split.py — SplitProposalExecutor (L86)

```python
notification_type="split_proposed"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.13 split.py — SplitExecuteExecutor (L149)

```python
notification_type="split_completed"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.14 done.py — 完了通知 (L75)

```python
notification_type="issue_done"
```
metadata に `repo`, `phase`, `issue_title`, `issue_type` を追加。

### 5.15 done.py — 連鎖通知 (L122)

```python
notification_type="chain_start"
```
metadata に `repo`, `issue` (連鎖先の Issue 番号) を追加。

---

## 6. Step 5: `orchestrator.py` — オーケストレーター通知改善

### 6.1 Notifier Protocol の更新

`notification_type` パラメータを追加:

```python
class Notifier(Protocol):
    async def notify(
        self,
        message: str,
        *,
        notification_type: str = "phase_end",
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
```

### 6.2 NullNotifier の更新

`notification_type` パラメータを受け取るようにシグネチャを更新:

```python
class NullNotifier:
    async def notify(
        self,
        message: str,
        *,
        notification_type: str = "phase_end",
        channel: str | None = None,
        level: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        logger.info("[NullNotifier] %s (level=%s, type=%s)", message, level, notification_type)
```

### 6.3 `start()` 内の通知 (L617)

```python
# 変更前:
await self._notifier.notify(
    "Orchestrator started",
    level="info",
    metadata={"repos": [...]},
)

# 変更後:
await self._notifier.notify(
    "Orchestrator started",
    notification_type="orchestrator_start",
    level="info",
    metadata={"repos": [...]},
)
```

### 6.4 `_route_events()` 内のエラー通知 (L745)

```python
# 変更前:
await self._notifier.notify(
    f"Event routing error: {exc}",
    level="error",
)

# 変更後:
await self._notifier.notify(
    f"Event routing error: {exc}",
    notification_type="orchestrator_error",
    level="error",
    metadata={"error": str(exc)},
)
```

### 6.5 `_handle_task_error()` 内の Issue 中断通知 (L937)

```python
# 変更前:
await self._notifier.notify(
    f"Issue #{issue_number} suspended due to error: {error}",
    level="error",
    metadata={"issue": issue_number, "phase": task.phase, "error": str(error)},
)

# 変更後:
await self._notifier.notify(
    f"Issue #{issue_number} suspended due to error: {error}",
    notification_type="issue_suspended",
    level="error",
    metadata={"issue": issue_number, "phase": task.phase, "error": str(error)},
)
```

### 6.6 `_health_check_loop()` 内の通知 (L1031)

```python
# 変更前:
await self._notifier.notify(
    f"Health check failures: {', '.join(unhealthy)}",
    level="error",
)

# 変更後:
await self._notifier.notify(
    f"Health check failures: {', '.join(unhealthy)}",
    notification_type="health_check_fail",
    level="error",
    metadata={"unhealthy_components": unhealthy},
)
```

---

## 7. Step 6: テスト — `test_slack.py` 全面更新

### 7.1 方針

- 既存テスト TC-SL-01〜13 は新フォーマット（header + divider + section + context 構成）に合わせてアサーションを更新
- 設計書のテスト計画 (§11) に記載された全テストケースを実装
- `@pytest.mark.parametrize` を活用し、全19通知タイプの絵文字・タイトルを一括検証

### 7.2 テストケース実装一覧

#### A. ペイロード構造テスト (TC-SL-11〜14e)
- `_build_rich_payload` の戻り値に header/divider/section/context ブロックが含まれることを検証
- metadata 空のケース、channel 指定有無のケースを網羅

#### B. 通知タイプマッピング (TC-SL-15〜16e)
- `@pytest.mark.parametrize` で全19タイプ × 絵文字・タイトルを一括検証
- 未知タイプのフォールバック検証
- レベル自動決定・明示的上書き検証

#### C. 本文構築 (TC-SL-17〜17e)
- Issue リンク + タイトル有無の組み合わせ
- repo/issue が欠如するケース

#### D. スタックトレース (TC-SL-24〜25d)
- 5行超の切り詰め検証
- 空文字列・空白のみの除外検証

#### E. コンテキストブロック (TC-SL-18〜23d)
- 各 metadata キーの個別検証 (duration, cost, files_changed, issue_type, pr_link, ci_url, commit_count)
- 境界値 (0, 負数等) 検証
- パイプ区切り結合の検証

#### F. フェーズラベル (TC-SL-28〜28b)
- `@pytest.mark.parametrize` で全18フェーズ名を一括検証

#### G. 後方互換性 (TC-SL-26〜26c)
- `notification_type` 省略時のデフォルト動作
- メッセージのみの呼び出し
- 既存 metadata キーのみでの動作

#### H. 統合テスト (TC-SL-30〜31)
- `notify()` → `send()` の連携
- `send()` 例外時の安全性

### 7.3 テスト実装の技術的詳細

```python
# ペイロード構造の検証ヘルパー
def _get_payload_blocks(route) -> list[dict]:
    """respx mock から送信されたペイロードの blocks を取得する."""
    request_body = json.loads(route.calls[0].request.content)
    return request_body["blocks"]

def _find_block(blocks, block_type) -> dict | None:
    """指定タイプのブロックを探す."""
    return next((b for b in blocks if b["type"] == block_type), None)
```

---

## 8. Step 7: テスト — `test_phases.py` の更新

### 8.1 方針

既存テストのうち `notify` 呼び出しをアサートしている箇所を更新:
- `notification_type` パラメータの検証を追加
- `phase_start` 通知が `execute()` 内で送信されることの検証

### 8.2 追加テストケース

- TC-SL-27: `execute()` でフェーズ開始通知が送信されること
- TC-SL-27b: 開始通知の metadata に `issue_title` が含まれること
- TC-SL-27c: Issue タイトル取得失敗時にも開始通知は送信されること
- TC-SL-27d: 開始通知の metadata に `issue_type` が含まれること
- TC-SL-32: `_handle_error()` が `notification_type="error"` で通知すること
- TC-SL-33: `_handle_error()` の通知にスタックトレースが含まれること
- TC-SL-33b: スタックトレースの末尾5行が使用されること
- TC-SL-34: `_handle_timeout()` が `notification_type="timeout"` で通知すること
- TC-SL-40〜51: 各フェーズの notification_type 検証

---

## 9. Step 8: `docs/specs/slack.md` 仕様書更新

新しいフォーマット・メソッド・通知タイプの仕様を反映する。

---

## 10. 実装上の注意点

### 10.1 後方互換性の維持

- `notify()` の既存パラメータ (`message`, `channel`, `level`, `metadata`) はすべてそのまま動作する
- `notification_type` はデフォルト値 `"phase_end"` を持つため、既存呼び出しはリッチフォーマットに自動的にアップグレードされる
- 既存テストの TC-SL-01〜13 は新フォーマットに合わせてアサーションを更新する必要がある

### 10.2 best-effort 通知の原則

- 通知送信は既存方針を継続: 失敗しても例外を伝搬しない
- `_notify_phase_start()` 内の Issue タイトル/タイプ取得失敗は `pass` で無視
- metadata 拡張キーの取得失敗も無視し、取得できた情報のみで通知を構築

### 10.3 `_build_rich_payload` で `_NOTIFICATION_CONFIG` に未知の `notification_type` が渡された場合

`_NOTIFICATION_CONFIG.get(notification_type, _NOTIFICATION_CONFIG["phase_end"])` でフォールバック。

### 10.4 `import traceback` の位置

`_handle_error()` 内でローカルインポートとし、モジュールトップレベルの import は増やさない（既存の import 最小化方針に従う）。

---

## 11. 検証手順

### 11.1 各ステップ完了後

```bash
# テスト実行
uv run pytest tests/unit/test_slack.py tests/unit/test_phases.py -v

# 型チェック
uv run mypy src/ai_agent_orchestrator/notifications/slack.py src/ai_agent_orchestrator/phases/base.py src/ai_agent_orchestrator/models.py

# lint
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

### 11.2 最終検証

```bash
# 全テスト
uv run pytest tests/ -v

# カバレッジ
uv run pytest tests/unit/test_slack.py --cov=src/ai_agent_orchestrator/notifications --cov-branch --cov-report=term-missing

# 型チェック全体
uv run mypy src/
```
