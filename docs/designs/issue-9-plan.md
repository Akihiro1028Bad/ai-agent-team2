# 実装計画: Issue #9 - Slackメッセージの改善

## 変更ファイル一覧（実装順）

### Step 1: データモデル追加（依存なし）

1. **`src/ai_agent_orchestrator/models.py`** - `NotificationType` Enum 追加
   - 依存: なし
   - 変更内容:
     - 既存の `ApprovalMethod` Enum の直後（105行目付近）に `NotificationType(StrEnum)` を新規追加
     - 17 通知タイプを定義:
       - フェーズ開始系: `PHASE_START = "phase_start"`
       - フェーズ完了系: `HEARING_QUESTION`, `DESIGN_PR_CREATED`, `IMPL_PR_CREATED`, `FIX_PR_CREATED`, `PLAN_POSTED`, `DESIGN_REVISED`, `IMPL_REVISED`, `SPLIT_PROPOSED`, `SPLIT_COMPLETED`, `ISSUE_COMPLETED`, `CHAIN_STARTED`
       - システム系: `SYSTEM_START`, `HEALTH_CHECK_FAILURE`, `ERROR`, `TIMEOUT`, `SUSPENDED`
   - 変更規模: 小（約25行追加）
   - 具体的な変更箇所:
     ```python
     # ApprovalMethod の直後に追加
     class NotificationType(StrEnum):
         """通知タイプ."""
         PHASE_START = "phase_start"
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
         SYSTEM_START = "system_start"
         HEALTH_CHECK_FAILURE = "health_check_failure"
         ERROR = "error"
         TIMEOUT = "timeout"
         SUSPENDED = "suspended"
     ```

### Step 2: SlackNotifier のリッチペイロード構築（依存: Step 1）

2. **`src/ai_agent_orchestrator/notifications/slack.py`** - リッチペイロード構築メソッド群追加
   - 依存: Step 1 (`NotificationType` — 直接 import はしないが metadata の値として使用)
   - 変更内容:
     - **定数追加** (既存 `_LEVEL_EMOJI` の直後、17行目以降):
       - `_TYPE_EMOJI: dict[str, str]` — 通知タイプ別絵文字（17エントリ）
         - 設計書 §4.1.1 に定義された全マッピング
       - `_TYPE_COLOR: dict[str, str]` — 通知タイプ別カラー（17エントリ）
         - 青 `#439FE0`: 進行中系 (phase_start, design_revised, impl_revised, chain_started)
         - 黄 `#E8A317`: ユーザーアクション待ち系 (hearing_question, design_pr_created, impl_pr_created, fix_pr_created, plan_posted, split_proposed)
         - 緑 `#2EB67D`: 成功系 (split_completed, issue_completed, system_start)
         - 赤 `#E01E5A`: エラー系 (health_check_failure, error, timeout, suspended)
       - `_PHASE_DISPLAY_NAME: dict[str, str]` — フェーズ表示名（日本語、18エントリ）
         - 全 Phase enum 値に対応する日本語名（"type-detection" → "タイプ判定" 等）
         - `hearing-wait` も含める（現行コードに存在するフェーズ）
     - **`notify()` メソッドの変更** (37-58行目):
       - `metadata.get("notification_type")` の有無で分岐
       - あり → `_build_rich_payload()` を呼び出し
       - なし → 従来の `_build_payload()` を呼び出し（後方互換）
     - **新規メソッド追加** (全て SlackNotifier のメソッドとして):
       - `_build_rich_payload(message, *, channel, level, metadata)` → `dict[str, Any]`
         - Attachment + Block Kit 形式のペイロード構築
         - Header → Section (Fields) → Section (Body) → Divider → Actions → Context
         - 全体を `attachments[0].blocks` に配置し、`attachments[0].color` でカラーバー
       - `_build_header_text(emoji, message, meta)` → `str` (staticmethod)
         - issue + issue_title あり → `"{emoji} Issue #{issue}: {issue_title}"`
         - issue のみ → `"{emoji} Issue #{issue}"`
         - issue なし → `"{emoji} {message}"`
       - `_build_fields(meta)` → `list[dict[str, Any]]` (staticmethod)
         - phase → `_PHASE_DISPLAY_NAME` で日本語化
         - progress → そのまま表示
         - duration_sec → `"{minutes}分{seconds}秒"` 形式
         - branch → バッククォートで囲む
       - `_build_body_text(message, meta)` → `str | None` (staticmethod)
         - message を常に含める
         - stacktrace あり → 最後5行を ```コードブロック``` で追加
         - error_analysis あり → `:mag: *調査結果:*` で追加
       - `_build_actions(meta)` → `list[dict[str, Any]]` (staticmethod)
         - repo + issue → `:clipboard: Issueを見る` ボタン
         - pr_url → `:twisted_rightwards_arrows: PRを見る` ボタン
         - comment_url → `:speech_balloon: 質問を見る` ボタン
       - `_build_rich_context(meta)` → `list[dict[str, Any]]` (staticmethod)
         - repo → `:package: \`{repo}\``
         - notification_type → `type: {notification_type}`
     - **既存メソッドの維持** (変更なし):
       - `_build_payload()` — 後方互換用（notification_type なし時に使用）
       - `_build_context_text()` — 後方互換用
       - `_level_emoji()` — リッチペイロードでもフォールバック用に使用
       - `send()` — 変更なし
       - `close()` — 変更なし
   - 変更規模: 大（約180行追加）

### Step 3: テスト追加 — SlackNotifier（依存: Step 2）

3. **`tests/unit/test_slack.py`** - リッチペイロードのテスト追加
   - 依存: Step 2
   - 変更内容:
     - 既存テストケースは全てそのまま維持（既存テストは respx + FakeSlack パターン）
     - 以下のテストケースを追加:
       - **リッチペイロード構築テスト** (約17ケース):
         - `notification_type` ありで `attachments` 構造のペイロードが生成されること
         - `attachments[0].color` が通知タイプに応じた色であること
         - `attachments[0].blocks` に Header ブロックが含まれること
         - Header の3パターン（Issue#+タイトル / Issue#のみ / システム通知）
         - Fields の全フィールド表示（phase, progress, duration_sec, branch）
         - Fields が空の場合 section ブロックが省略されること
         - Body テキストに message が含まれること
         - スタックトレース切り詰め（5行以下はそのまま / 5行超は最後5行のみ）
         - error_analysis 付きの body テキスト
         - Actions の3ボタン（Issue + PR + コメント）/ 1ボタン / なし
         - Context にリポジトリとタイプが含まれること
         - Divider ブロックが含まれること
       - **マッピングテスト** (約8ケース):
         - 全17通知タイプの絵文字マッピングが正しいこと
         - 全17通知タイプのカラーマッピングが正しいこと
         - 未知の notification_type のフォールバック（_level_emoji / デフォルト色）
         - カラー値が青/黄/緑/赤の4色体系に収まること
       - **後方互換性テスト** (約3ケース):
         - `notification_type` なし → `_build_payload()` 経由で送信
         - `notification_type` 空文字 → `_build_payload()` 経由（falsy なので）
         - `metadata` が None → `_build_payload()` 経由
       - **フェーズ表示名テスト** (約2ケース):
         - 全 Phase enum 値に対応する表示名が存在すること
         - 未知フェーズ名のフォールバック（元の値をそのまま表示）
     - 合計: 既存テスト + 新規約30 = **約43テストケース**
   - 変更規模: 大（約400行追加）

### Step 4: base.py — フェーズ開始通知・進捗計算・エラー通知改善（依存: Step 2）

4. **`src/ai_agent_orchestrator/phases/base.py`** - フェーズ開始通知 + 進捗計算 + エラー改善
   - 依存: Step 2（`_PHASE_DISPLAY_NAME` を `slack.py` からインポート）
   - 変更内容:
     - **import 追加**:
       - `from ai_agent_orchestrator.notifications.slack import _PHASE_DISPLAY_NAME`
       - `import traceback`（`_handle_error` 用）
     - **定数追加** (PhaseExecutor クラスの外、モジュールレベルに):
       - `_WORKFLOW_PHASES: dict[str, list[str]]` — タイプ別ワークフローフェーズリスト
         - `"bug"`: `["type-detection", "analysis", "plan-review", "fix", "impl-review", "done"]`
         - `"feature-s"`: `["type-detection", "hearing", "plan-brief", "plan-review", "implement", "impl-review", "done"]`
         - `"feature-m"`: `["type-detection", "hearing", "design", "design-review", "planning", "implement", "impl-review", "done"]`
         - `"feature-l"`: `["type-detection", "hearing", "split-proposal", "split-execute", "done"]`
     - **`execute()` メソッドの変更** (274-310行目):
       - `phase_start` トラッキングの後、`build_prompt()` の前に `await self._notify_phase_start(request)` を追加
     - **新規メソッド追加** (PhaseExecutor クラスに):
       - `_notify_phase_start(request: TaskRequest) -> None`:
         - `_get_repo_key()`, `_get_issue_title()`, `_get_progress()` を呼び出し
         - `notification_type: "phase_start"` で通知
         - metadata に issue, issue_title, phase, repo, branch, progress を含める
       - `_get_repo_key(repo: object) -> str` (staticmethod):
         - `getattr(repo, "owner", "")` と `getattr(repo, "repo", "")` から `"owner/repo"` を構築
         - 空の場合は `""` を返す
       - `_get_issue_title(request: TaskRequest) -> str`:
         - `_get_client()` → `get_issue()` で best-effort 取得
         - 例外時は `""` にフォールバック（通知は best-effort）
       - `_get_progress(issue_number: int, current_phase: str) -> str | None`:
         - `_sm.get_issue_type()` でタイプ取得
         - `_WORKFLOW_PHASES` から該当フェーズリスト取得
         - `phases.index(current_phase)` で現在位置を特定
         - `"{idx}/{len(phases)} フェーズ完了"` を返す
         - タイプ未知 or フェーズ未知の場合は `None`
     - **`_handle_error()` の改善** (383-403行目):
       - `import traceback` を使ってスタックトレースを取得
       - `_get_repo_key()`, `_get_issue_title()` を呼び出し
       - metadata に追加: `notification_type: "error"`, `repo`, `issue_title`, `error`, `stacktrace`
     - **`_handle_timeout()` の改善** (362-381行目):
       - `_get_repo_key()`, `_get_issue_title()` を呼び出し
       - metadata に追加: `notification_type: "timeout"`, `repo`, `issue_title`
   - 変更規模: 中（約80行追加・変更）

### Step 5: 各フェーズファイルの metadata 拡充（依存: Step 4）

以下の各ファイルで `notify()` 呼び出しの metadata を拡充する。変更パターンは統一的:
- `notification_type` の追加
- `repo` (`self._get_repo_key(request.repo)` 使用) の追加
- `issue_title` の追加（`build_prompt()` で取得済みの `issue` オブジェクトから取得）
- PR作成系は `pr_url` の追加 (`f"https://github.com/{repo_key}/pull/{pr_number}"`)
- `phase` の追加
- `duration_sec`, `branch` の追加（該当する場合）

**注意**: 各フェーズの `process_result()` では `build_prompt()` で既に `issue` を取得しているが、`process_result()` のスコープでは利用できない。そのため `_get_issue_title(request)` を使って再取得するか、`build_prompt()` 内で `issue.title` をインスタンス変数にキャッシュする設計とする。コスト（追加API呼び出し）を考慮し、`_get_issue_title()` （best-effort）を使用する。

5. **`src/ai_agent_orchestrator/phases/hearing.py`** - metadata 拡充
   - 依存: Step 4
   - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し（116-121行目）
   - 変更内容:
     ```python
     # 変更前
     await self._notifier.notify(
         f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
         metadata={"issue": request.issue_number},
     )
     # 変更後
     repo_key = self._get_repo_key(request.repo)
     issue_title = await self._get_issue_title(request)
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
   - 変更規模: 小（10行変更）

6. **`src/ai_agent_orchestrator/phases/design.py`** - metadata 拡充
   - 依存: Step 4
   - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し（89-95行目）
   - 変更内容:
     ```python
     # 変更後
     repo_key = self._get_repo_key(request.repo)
     issue_title = await self._get_issue_title(request)
     pr_url = f"https://github.com/{repo_key}/pull/{pr_number}" if repo_key else ""
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
   - 変更規模: 小（10行変更）

7. **`src/ai_agent_orchestrator/phases/implement.py`** - metadata 拡充
   - 依存: Step 4
   - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
   - 変更内容:
     - `notification_type: "impl_pr_created"` 追加
     - `repo`, `issue_title`, `pr_url`, `phase: "implement"`, `duration_sec`, `branch` 追加
   - 変更規模: 小（10行変更）

8. **`src/ai_agent_orchestrator/phases/fix.py`** - metadata 拡充
   - 依存: Step 4
   - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
   - 変更内容:
     - `notification_type: "fix_pr_created"` 追加
     - `repo`, `issue_title`, `pr_url`, `phase: "fix"`, `duration_sec` 追加
   - 変更規模: 小（10行変更）

9. **`src/ai_agent_orchestrator/phases/design_revise.py`** - metadata 拡充
   - 依存: Step 4
   - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
   - 変更内容:
     - `notification_type: "design_revised"` 追加
     - `repo`, `issue_title`, `phase: "design-revise"` 追加
   - 変更規模: 小（5行変更）

10. **`src/ai_agent_orchestrator/phases/impl_revise.py`** - metadata 拡充
    - 依存: Step 4
    - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
    - 変更内容:
      - `notification_type: "impl_revised"` 追加
      - `repo`, `issue_title`, `phase: "impl-revise"` 追加
    - 変更規模: 小（5行変更）

11. **`src/ai_agent_orchestrator/phases/analysis.py`** - metadata 拡充
    - 依存: Step 4
    - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
    - 変更内容:
      - `notification_type: "plan_posted"` 追加
      - `repo`, `issue_title`, `phase: "analysis"` 追加
    - 変更規模: 小（5行変更）

12. **`src/ai_agent_orchestrator/phases/plan_brief.py`** - metadata 拡充
    - 依存: Step 4
    - 変更箇所: `process_result()` 内の `self._notifier.notify()` 呼び出し
    - 変更内容:
      - `notification_type: "plan_posted"` 追加
      - `repo`, `issue_title`, `phase: "plan-brief"` 追加
    - 変更規模: 小（5行変更）

13. **`src/ai_agent_orchestrator/phases/split.py`** - metadata 拡充
    - 依存: Step 4
    - 変更箇所: `SplitProposalExecutor.process_result()` と `SplitExecuteExecutor.process_result()` の `notify()` 呼び出し
    - 変更内容:
      - SplitProposalExecutor: `notification_type: "split_proposed"`, `repo`, `issue_title`, `phase: "split-proposal"`
      - SplitExecuteExecutor: `notification_type: "split_completed"`, `repo`, `issue_title`, `phase: "split-execute"`
    - 変更規模: 小（10行変更）

14. **`src/ai_agent_orchestrator/phases/done.py`** - metadata 拡充
    - 依存: Step 4
    - 変更箇所: `DoneExecutor.process_result()` と `_chain_next_child_issue()` の `notify()` 呼び出し
    - 変更内容:
      - `process_result`: `notification_type: "issue_completed"`, `repo`, `issue_title`, `phase: "done"`
      - `_chain_next_child_issue`: `notification_type: "chain_started"`, `repo`, `issue_title`
    - 変更規模: 小（10行変更）

### Step 6: orchestrator.py のシステム通知改善（依存: Step 2）

15. **`src/ai_agent_orchestrator/orchestrator/orchestrator.py`** - システム通知改善
    - 依存: Step 2
    - 変更箇所: 4箇所の `notify()` 呼び出し
    - 変更内容:
      - `run()` メソッド内の起動通知:
        - metadata に `notification_type: "system_start"` 追加
        - `repos` は既に含まれているのでそのまま
      - `_route_events()` のエラー通知:
        - metadata に `notification_type: "error"` 追加
      - `_handle_task_error()` の通知:
        - metadata に `notification_type: "suspended"`, `repo` 追加
      - `_health_check_loop()` の通知:
        - metadata に `notification_type: "health_check_failure"` 追加
    - 変更規模: 小（各 notify 呼び出しに metadata フィールド追加、計20行程度）

### Step 7: テスト追加 — base.py・フェーズファイル（依存: Step 4, 5）

16. **`tests/unit/test_phases.py`** - フェーズ通知テスト追加
    - 依存: Step 4, 5
    - 変更内容:
      - **base.py ヘルパーメソッドテスト** (約13ケース):
        - `_get_repo_key()`: owner + repo あり → `"owner/repo"`, 空属性 → `""`
        - `_get_issue_title()`: 正常取得 → タイトル文字列, API 例外 → `""`
        - `_get_progress()`: bug タイプ analysis フェーズ → `"1/6 フェーズ完了"` 等
        - `_get_progress()`: 未知タイプ → `None`, 未知フェーズ → `None`
        - `_notify_phase_start()`: notifier.notify が `notification_type: "phase_start"` で呼ばれること
        - `_handle_error()`: スタックトレース付き、`notification_type: "error"` で通知されること
        - `_handle_timeout()`: `notification_type: "timeout"` で通知されること
      - **各フェーズの通知 metadata テスト** (約14ケース):
        - 各フェーズの `process_result()` 実行後に notifier.notify が正しい metadata で呼ばれること
        - 必須フィールド: `notification_type`, `issue`, `repo` が含まれること
        - PR 作成系: `pr_url` が含まれること
        - テスト対象: hearing, design, implement, fix, design_revise, impl_revise, analysis, plan_brief, split (proposal + execute), done (completed + chain)
    - テスト方法: 既存の conftest.py の `FakeGitHubClient`, `FakeNotifier` パターンに従う
    - 変更規模: 大（約350行追加）

### Step 8: 仕様書の更新（依存: Step 1-7）

17. **`docs/specs/slack.md`** - 仕様書の更新
    - 依存: Step 1-7（実装完了後に最新の状態を反映）
    - 変更内容:
      - 通知タイプ体系の記載追加（`NotificationType` Enum の全値と説明）
      - リッチペイロード構造の説明追加（Attachment + Block Kit 構成図）
      - 各通知タイプの絵文字・カラー・フォーマット一覧表
      - `_build_rich_payload()` のフロー説明
      - フェーズ開始通知の仕様追加
      - 後方互換性の説明（notification_type の有無による分岐）
      - `_PHASE_DISPLAY_NAME` マッピング一覧
    - 変更規模: 中（約100行追加）

---

## 依存関係グラフ

```
Step 1: models.py (NotificationType Enum)
  │
  ▼
Step 2: slack.py (リッチペイロード構築 + 定数マッピング)
  │
  ├──────────────────────┬──────────────────────┐
  ▼                      ▼                      ▼
Step 3: test_slack.py   Step 4: base.py        Step 6: orchestrator.py
(SlackNotifierテスト)    (フェーズ開始通知       (システム通知改善)
                         + 進捗計算 + エラー改善)
                          │
                          ▼
                        Step 5: 各フェーズファイル (10ファイル)
                        (hearing, design, implement, fix,
                         design_revise, impl_revise, analysis,
                         plan_brief, split, done)
                          │
                          ▼
                        Step 7: test_phases.py (フェーズ通知テスト)
                          │
                          ▼
                        Step 8: docs/specs/slack.md (仕様書更新)
```

### 並行実行可能なステップ

- Step 3 (test_slack.py) と Step 4 (base.py) は並行実行可能
- Step 5 (各フェーズ) と Step 6 (orchestrator.py) は並行実行可能

---

## 変更ファイル一覧サマリ

| # | ファイル | 変更種別 | 変更規模 | Step |
|---|---------|---------|---------|------|
| 1 | `src/ai_agent_orchestrator/models.py` | 追加 | 小 (25行) | 1 |
| 2 | `src/ai_agent_orchestrator/notifications/slack.py` | 追加+変更 | 大 (180行) | 2 |
| 3 | `tests/unit/test_slack.py` | 追加 | 大 (400行) | 3 |
| 4 | `src/ai_agent_orchestrator/phases/base.py` | 追加+変更 | 中 (80行) | 4 |
| 5 | `src/ai_agent_orchestrator/phases/hearing.py` | 変更 | 小 (10行) | 5 |
| 6 | `src/ai_agent_orchestrator/phases/design.py` | 変更 | 小 (10行) | 5 |
| 7 | `src/ai_agent_orchestrator/phases/implement.py` | 変更 | 小 (10行) | 5 |
| 8 | `src/ai_agent_orchestrator/phases/fix.py` | 変更 | 小 (10行) | 5 |
| 9 | `src/ai_agent_orchestrator/phases/design_revise.py` | 変更 | 小 (5行) | 5 |
| 10 | `src/ai_agent_orchestrator/phases/impl_revise.py` | 変更 | 小 (5行) | 5 |
| 11 | `src/ai_agent_orchestrator/phases/analysis.py` | 変更 | 小 (5行) | 5 |
| 12 | `src/ai_agent_orchestrator/phases/plan_brief.py` | 変更 | 小 (5行) | 5 |
| 13 | `src/ai_agent_orchestrator/phases/split.py` | 変更 | 小 (10行) | 5 |
| 14 | `src/ai_agent_orchestrator/phases/done.py` | 変更 | 小 (10行) | 5 |
| 15 | `src/ai_agent_orchestrator/orchestrator/orchestrator.py` | 変更 | 小 (20行) | 6 |
| 16 | `tests/unit/test_phases.py` | 追加 | 大 (350行) | 7 |
| 17 | `docs/specs/slack.md` | 変更 | 中 (100行) | 8 |

**合計: 17ファイル、約1,135行変更**

---

## テスト方針

### ユニットテスト対象

| 対象 | テストファイル | テスト内容 | ケース数 |
|------|-------------|----------|---------|
| `models.py` | `tests/unit/test_models.py` | `NotificationType` Enum の値一覧・StrEnum 互換 | 2 |
| `slack.py` | `tests/unit/test_slack.py` | リッチペイロード構築、定数マッピング、後方互換性 | 30 |
| `base.py` | `tests/unit/test_phases.py` | フェーズ開始通知、進捗計算、ヘルパーメソッド、エラー通知 | 13 |
| 各フェーズ | `tests/unit/test_phases.py` | metadata に正しい `notification_type` と必須フィールドが含まれること | 14 |

### テスト実行方法

```bash
# 全テスト実行（回帰テスト含む）
uv run pytest tests/ -v

# Slack関連テストのみ
uv run pytest tests/unit/test_slack.py tests/unit/test_phases.py tests/unit/test_models.py -v -k "slack or notification or phase_start or rich"

# カバレッジ計測
uv run pytest tests/unit/test_slack.py tests/unit/test_phases.py \
  --cov=src/ai_agent_orchestrator/notifications/slack \
  --cov=src/ai_agent_orchestrator/models \
  --cov=src/ai_agent_orchestrator/phases/base \
  --cov-report=term-missing
```

### テスト戦略

1. **後方互換テスト**: 既存テスト（test_slack.py, test_phases.py）が全て PASS すること
2. **リッチペイロードテスト**: `notification_type` ありの場合に `attachments` 構造で送信されること
3. **マッピング網羅テスト**: 全17通知タイプの絵文字・カラーが正しいこと
4. **フェーズ通知テスト**: 各フェーズの `notify()` が正しい metadata を含むこと
5. **エッジケーステスト**: 空文字列、None、未知のタイプ等のフォールバック動作
6. **進捗計算テスト**: 各タイプ・各フェーズの進捗表示が正しいこと

### 品質チェック

```bash
# 型チェック
uv run mypy src/

# lint + format
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

---

## リスク・確認事項

| リスク | 影響度 | 対策 |
|-------|--------|------|
| Block Kit の文字数制限 (section: 3000文字) | 中 | スタックトレースを最後5行に切り詰め |
| Webhook レート制限 | 低 | フェーズ開始通知の追加で頻度が倍増するが、1 Issue あたり数分間隔なので問題なし |
| 後方互換性の破壊 | 高 | `notification_type` の有無で分岐する設計により回避。既存テストで検証 |
| Issue タイトル取得の追加API呼び出し | 低 | best-effort で取得、失敗時は空文字にフォールバック。通知の欠落は許容 |
| `_PHASE_DISPLAY_NAME` の配置場所 | 低 | `slack.py` に定義し、`base.py` からは import して使用（通知モジュール → フェーズの一方向依存で循環参照を回避） |
| 既存テストへの影響 | 高 | `notification_type` なしの呼び出しは従来パスを通るため既存テストは全て PASS。Step 実装ごとに `uv run pytest` で回帰確認 |
| Header の `plain_text` 制限 (150文字) | 低 | Issue タイトルが長い場合の切り詰めは未対応（150文字超のタイトルは稀） |
