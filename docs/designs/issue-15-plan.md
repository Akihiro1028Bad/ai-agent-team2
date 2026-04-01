# 実装計画: Issue #15 - Slack メッセージ改善

## 変更ファイル一覧（実装順）

### Phase 1: SlackNotifier コアの改修（依存なし）

#### 1. `src/ai_agent_orchestrator/notifications/slack.py` — 大幅改修

- 依存: なし（他のすべての変更がこのファイルに依存）

**変更内容:**

1. **`NotificationType` StrEnum の追加** (新規)
   - 21種の通知タイプを定義
   - `PHASE_START`, `HEARING_QUESTION`, `ANALYSIS_POSTED`, `PLAN_POSTED`,
     `DESIGN_PR_CREATED`, `IMPL_PR_CREATED`, `FIX_PR_CREATED`,
     `DESIGN_REVISED`, `IMPL_REVISED`, `SPLIT_PROPOSED`, `SPLIT_COMPLETED`,
     `CI_STARTED`, `CI_PASSED`, `CI_FAILED`, `REVIEW_COMMENT`,
     `DONE`, `CHAIN_START`, `ERROR`, `TIMEOUT`, `CRITICAL`, `SYSTEM_START`

2. **新規定数辞書の追加**
   - `_TYPE_EMOJI: dict[str, str]` — 通知タイプ → 絵文字マッピング (21エントリ)
   - `_TYPE_COLOR: dict[str, str]` — 通知タイプ → カラーバー色マッピング (21エントリ)
   - `_LEVEL_COLOR: dict[str, str]` — レベル別フォールバック色 (`info`→青, `error`→赤, `critical`→赤)
   - `_MAX_STACKTRACE_LEN = 500` — スタックトレース切り詰め上限

3. **`_build_payload()` の全面改修**
   - 現在: `blocks` 直下に section + context
   - 変更後: `attachments[0].blocks` に header + divider + section + divider + context
   - 処理フロー:
     1. `notification_type` から絵文字・カラーバー色を解決（フォールバック: `level` → `_LEVEL_EMOJI`/`_LEVEL_COLOR`）
     2. ヘッダーブロック構築（`plain_text` 型、絵文字+メッセージ1行目、150文字上限）
     3. divider ブロック
     4. セクションブロック（`mrkdwn` 型、詳細情報、3000文字上限）:
        - `_build_issue_line()` → Issue タイトル行
        - `_build_message_body()` → メッセージ本文（2行目以降）
        - `_build_duration_line()` → 処理時間
        - `_build_diff_line()` → 差分サマリ
        - `_build_next_action_line()` → 次のアクション
        - `_build_stacktrace_block()` → スタックトレース
     5. divider ブロック（コンテキストがある場合）
     6. コンテキストブロック（`_build_context_text()` で構築）
     7. 全体を `attachments` でラップしてカラーバーを適用
   - channel の設定は `attachments` と同階層に配置（現状維持）

4. **新規ヘルパーメソッド追加** (すべて `@staticmethod`)
   - `_build_issue_line(meta)` → `*Issue #XX* "タイトル"` or `*Issue #XX*` or `""`
   - `_build_message_body(message, meta)` → メッセージの2行目以降を返す
   - `_build_duration_line(meta)` → `:stopwatch: *所要時間*: X分Y秒`（`duration_sec` がある場合）
   - `_build_diff_line(meta)` → `:bar_chart: *差分サマリ*: ...`（`diff_summary` がある場合）
   - `_build_next_action_line(meta)` → `:next_track_button: *次のアクション*: ...`（`next_action` がある場合）
   - `_build_stacktrace_block(meta)` → コードブロック内スタックトレース（500文字切り詰め）

5. **`_build_context_text()` の改良**
   - 変更点: `pr` があり `pr_url` がなく `repo` がある場合、PR URL を自動生成
   - 変更点: `:memo: phase:{phase}` → `:gear: phase: {phase}` にアイコン変更

6. **既存 `_level_emoji()` は残す**（フォールバック用として `_build_payload` 内で使用）

---

### Phase 2: テストの更新（Phase 1 に依存）

#### 2. `tests/unit/test_slack.py` — 大幅改修・追加

- 依存: #1 (`slack.py` の変更)

**変更内容:**

1. **既存テスト修正** (TC-SL-01 〜 TC-SL-13)
   - ペイロード構造が `blocks` → `attachments[0]["blocks"]` に変更されるため、
     アサーションのアクセスパスを修正
   - TC-SL-01: `request_body["blocks"][0]` → `request_body["attachments"][0]["blocks"]` 内のブロックを検証
   - TC-SL-02, TC-SL-03: 同上
   - TC-SL-04: コンテキストブロックのアクセスパス変更
   - TC-SL-06, TC-SL-07: `channel` キーの位置はペイロード直下のままなので変更なし
   - TC-SL-08, TC-SL-09: `send()` / `close()` は変更なし
   - TC-SL-10: `_level_emoji()` テストは変更なし
   - TC-SL-12: context ブロック有無の検証パス変更
   - TC-SL-13: `channel` キーの検証は変更なし

2. **新規テスト追加** (TC-SL-14 〜 TC-SL-32)
   - TC-SL-14: `notification_type="impl_pr_created"` → 絵文字 `:rocket:` の検証
   - TC-SL-15: `notification_type="ci_failed"` → カラーバー色 `#F44336` の検証
   - TC-SL-16: ヘッダー + divider + セクション + context の構造検証（ブロックタイプの順序）
   - TC-SL-17: `attachments` ラッパーの存在と構造検証
   - TC-SL-18: `issue_title` がセクションテキストに含まれること
   - TC-SL-19: `duration_sec=204` → `"3分24秒"` 表示フォーマット検証
   - TC-SL-20: `diff_summary` のセクション表示検証
   - TC-SL-21: `next_action` のセクション表示検証
   - TC-SL-22: `stacktrace` 600文字 → 500文字切り詰め + `"..."` プレフィクス検証
   - TC-SL-23: `stacktrace` 300文字 → そのまま表示検証
   - TC-SL-24: `notification_type` 未指定 + `level="error"` → `_LEVEL_EMOJI`/`_LEVEL_COLOR` フォールバック検証
   - TC-SL-25: フェーズ開始通知のペイロード構造検証
   - TC-SL-26: エラー通知のリッチフォーマット（ヘッダー + スタックトレース）検証
   - TC-SL-27: セクションテキスト 3000 文字超 → 切り詰め検証
   - TC-SL-28: ヘッダーテキスト 150 文字超 → 切り詰め検証
   - TC-SL-29: `_build_issue_line()` — issue+title あり / issue のみ / なし の3パターン
   - TC-SL-30: `_build_duration_line()` — 0秒 / 45秒 / 125秒 / None の4パターン
   - TC-SL-31: `_build_context_text()` — `pr` あり + `pr_url` なし + `repo` あり → PR URL 自動生成
   - TC-SL-32: `NotificationType` Enum の全値が `_TYPE_EMOJI` と `_TYPE_COLOR` に含まれること

---

### Phase 3: PhaseExecutor 基底クラスの改修（Phase 1 に依存）

#### 3. `src/ai_agent_orchestrator/phases/base.py` — 改修

- 依存: #1 (`slack.py` の `NotificationType`)

**変更内容:**

1. **新規ヘルパーメソッド追加**

   - `_get_issue_title(request) -> str`:
     - `_get_client()` → `get_issue()` でタイトル取得
     - 失敗時は空文字列を返す（best-effort）
   - `_get_repo_fullname(request) -> str`:
     - `request.repo` の `owner`/`repo` 属性から `"owner/repo"` 形式を返す
   - `_phase_display_name(phase) -> str` (`@staticmethod`):
     - フェーズ名 → 日本語表示名の辞書マッピング（15項目）
     - 未知のフェーズはそのまま返す

2. **`execute()` メソッドの改修**
   - `phase_start` トラッキングの直後にフェーズ開始通知を追加:
     ```python
     issue_title = await self._get_issue_title(request)
     repo_full = self._get_repo_fullname(request)
     await self._notifier.notify(
         f"{self._phase_display_name(request.phase)} フェーズを開始しました",
         metadata={
             "notification_type": "phase_start",
             "issue": request.issue_number,
             "issue_title": issue_title,
             "repo": repo_full,
             "phase": str(request.phase),
         },
     )
     ```
   - `time.monotonic()` で処理時間を計測（`start_time` 変数を追加）
   - `import time` を追加

3. **`_handle_timeout()` の改修**
   - `_get_issue_title()`, `_get_repo_fullname()` でメタデータを取得
   - metadata に `notification_type="timeout"`, `issue_title`, `repo` を追加
   - メッセージを `"{フェーズ名} フェーズがタイムアウトしました"` に変更

4. **`_handle_error()` の改修**
   - `import traceback` でスタックトレースを取得
   - `_get_issue_title()`, `_get_repo_fullname()` でメタデータを取得
   - metadata に `notification_type="error"`, `issue_title`, `repo`, `stacktrace` を追加
   - メッセージを `"エラーが発生しました"` に変更

5. **`_extract_diff_summary()` ヘルパー追加** (`@staticmethod`)
   - エージェント出力から `"X files changed, Y insertions(+), Z deletions(-)"` パターンを抽出
   - マッチ時: `"Xファイル変更 (+Y -Z)"` 形式で返す
   - マッチしない場合: 空文字列を返す

---

### Phase 4: 各フェーズの metadata 拡充（Phase 3 に依存）

以下のファイルは互いに独立しており、並行して変更可能。
すべて Phase 3 の `base.py` ヘルパーメソッドに依存。

#### 4. `src/ai_agent_orchestrator/phases/hearing.py` — 改修

- 依存: #3 (`base.py` のヘルパーメソッド)

**変更内容:**
- `process_result()` 内の `notify()` 呼び出しを改修:
  - `_get_issue_title()`, `_get_repo_fullname()` でメタデータ取得
  - metadata に追加: `notification_type="hearing_question"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="コメントで回答してください"`
  - メッセージを `"ヒアリング質問を投稿しました"` に変更

#### 5. `src/ai_agent_orchestrator/phases/analysis.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - metadata に追加: `notification_type="analysis_posted"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="コメントに👍リアクションで承認してください"`
  - メッセージを `"修正方針を投稿しました"` に変更

#### 6. `src/ai_agent_orchestrator/phases/design.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - PR URL を構築して `pr_url` に設定
  - metadata に追加: `notification_type="design_pr_created"`, `issue_title`, `repo`, `pr_url`, `phase`, `duration_sec`, `next_action="設計 PR をレビューして approve してください"`
  - メッセージを `"設計 PR を作成しました"` に変更

#### 7. `src/ai_agent_orchestrator/phases/implement.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - `_extract_diff_summary(result.output)` で差分サマリを取得
  - PR URL を構築して `pr_url` に設定
  - metadata に追加: `notification_type="impl_pr_created"`, `issue_title`, `repo`, `pr_url`, `phase`, `duration_sec`, `diff_summary`, `next_action="PR をレビューして approve してください"`
  - メッセージを `"実装 PR を作成しました"` に変更

#### 8. `src/ai_agent_orchestrator/phases/fix.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - PR URL を構築して `pr_url` に設定
  - metadata に追加: `notification_type="fix_pr_created"`, `issue_title`, `repo`, `pr_url`, `phase`, `duration_sec`, `next_action="PR をレビューして approve してください"`
  - メッセージを `"修正 PR を作成しました"` に変更

#### 9. `src/ai_agent_orchestrator/phases/plan_brief.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - metadata に追加: `notification_type="plan_posted"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="コメントに👍リアクションで承認してください"`
  - メッセージを `"実装方針を投稿しました"` に変更

#### 10. `src/ai_agent_orchestrator/phases/design_revise.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - metadata に追加: `notification_type="design_revised"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="設計 PR で再レビューをお願いします"`
  - メッセージを `"設計書を修正しました"` に変更

#### 11. `src/ai_agent_orchestrator/phases/impl_revise.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` 内の `notify()` を改修:
  - metadata に追加: `notification_type="impl_revised"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="実装 PR で再レビューをお願いします"`
  - メッセージを `"実装を修正しました"` に変更

#### 12. `src/ai_agent_orchestrator/phases/split.py` — 改修

- 依存: #3

**変更内容:**
- **SplitProposalExecutor の `process_result()`:**
  - metadata に追加: `notification_type="split_proposed"`, `issue_title`, `repo`, `phase`, `duration_sec`, `next_action="コメントに👍リアクションで承認してください"`
  - メッセージを `"分割を提案しました"` に変更
- **SplitExecuteExecutor の `process_result()`:**
  - metadata に追加: `notification_type="split_completed"`, `issue_title`, `repo`, `phase`, `duration_sec`
  - メッセージを `"分割が完了しました"` に変更

#### 13. `src/ai_agent_orchestrator/phases/done.py` — 改修

- 依存: #3

**変更内容:**
- **完了通知:**
  - metadata に追加: `notification_type="done"`, `issue_title`, `repo`, `pr`, `pr_url`, `phase`, `duration_sec`
  - メッセージを `"Issue が完了しました"` に変更
- **連鎖処理開始通知:**
  - metadata に追加: `notification_type="chain_start"`, `repo`
  - メッセージを `"連鎖処理を開始します"` に変更

#### 14. `src/ai_agent_orchestrator/phases/ci_fix.py` — 改修

- 依存: #3

**変更内容:**
- `process_result()` に CI 修正開始通知を追加:
  - `notification_type="ci_started"`, `issue_title`, `repo`, `phase`
  - メッセージ: `"CI 修正を実行しています"`

---

### Phase 5: 新規通知ポイントの追加（Phase 1 に依存）

#### 15. `src/ai_agent_orchestrator/poller/event_router.py` — 改修

- 依存: #1 (`slack.py` の `NotificationType`)

**変更内容:**

1. **CI 結果通知の追加**
   - CI 成功イベント処理部分 (`_handle_ci_passed` 相当) に Slack 通知を追加:
     - `notification_type="ci_passed"`, `issue`, `repo`, `pr`, `phase="ci-fix"`
     - メッセージ: `"CI が成功しました"`
   - CI 失敗イベント処理部分 (`_handle_ci_failure` 相当) に Slack 通知を追加:
     - `notification_type="ci_failed"`, `issue`, `repo`, `pr`, `phase="ci-fix"`
     - メッセージ: `"CI が失敗しました。修正を開始します"`

2. **PR レビューコメント受信通知の追加**
   - 設計 PR コメント受信時 (`_handle_design_pr_commented` 相当):
     - `notification_type="review_comment"`, `issue`, `repo`, `pr`, `pr_url`, `phase="design-review"`
     - メッセージ: `"設計 PR にレビューコメントが届きました"`
   - 実装 PR コメント受信時 (`_handle_impl_pr_commented` 相当):
     - `notification_type="review_comment"`, `issue`, `repo`, `pr`, `pr_url`, `phase="impl-review"`
     - メッセージ: `"実装 PR にレビューコメントが届きました"`

#### 16. `src/ai_agent_orchestrator/orchestrator/orchestrator.py` — 改修

- 依存: #1

**変更内容:**
- 起動通知のリッチ化:
  - `notification_type="system_start"` を metadata に追加
  - 既存の `repos` 情報は維持

---

### Phase 6: ドキュメント更新（Phase 1〜5 に依存）

#### 17. `docs/specs/slack.md` — 更新

- 依存: #1 〜 #16 の全変更完了後

**変更内容:**
- 通知タイプ一覧テーブルの更新（21種）
- ペイロード構造の更新（attachments ラッパー、Block Kit リッチレイアウト）
- 新規 metadata キーの追加（`notification_type`, `issue_title`, `duration_sec`, `diff_summary`, `next_action`, `stacktrace`）
- 新規通知ポイントの記載（フェーズ開始、CI 結果、PR レビューコメント受信）

---

## 依存関係グラフ

```
#1 slack.py (コア)
├── #2 test_slack.py
├── #3 base.py
│   ├── #4  hearing.py
│   ├── #5  analysis.py
│   ├── #6  design.py
│   ├── #7  implement.py
│   ├── #8  fix.py
│   ├── #9  plan_brief.py
│   ├── #10 design_revise.py
│   ├── #11 impl_revise.py
│   ├── #12 split.py
│   ├── #13 done.py
│   └── #14 ci_fix.py
├── #15 event_router.py
├── #16 orchestrator.py
└── #17 docs/specs/slack.md
```

---

## テスト方針

### ユニットテスト対象

| ファイル | テスト対象 | テスト手法 |
|---------|----------|----------|
| `slack.py` | `_build_payload()` リッチレイアウト構造 | `_build_payload()` を直接呼び出し、返り値の構造を検証 |
| `slack.py` | `_build_issue_line()` 各パターン | `@staticmethod` を直接テスト |
| `slack.py` | `_build_duration_line()` 分秒変換 | `@staticmethod` を直接テスト |
| `slack.py` | `_build_diff_line()` | `@staticmethod` を直接テスト |
| `slack.py` | `_build_next_action_line()` | `@staticmethod` を直接テスト |
| `slack.py` | `_build_stacktrace_block()` 切り詰め | `@staticmethod` を直接テスト |
| `slack.py` | `_build_context_text()` PR URL 自動生成 | `@staticmethod` を直接テスト |
| `slack.py` | `notify()` 統合 (respx mock) | Webhook へのリクエストペイロード全体を検証 |
| `slack.py` | `NotificationType` Enum の網羅性 | 全値が `_TYPE_EMOJI`, `_TYPE_COLOR` に存在するか検証 |
| `base.py` | `_phase_display_name()` | `@staticmethod` を直接テスト |
| `base.py` | `_extract_diff_summary()` | `@staticmethod` を直接テスト |

### 既存テストの修正方針

- ペイロード構造のアクセスパス変更箇所をすべて `attachments[0]["blocks"]` に更新
- テストヘルパー関数 `_get_blocks(request_body)` の導入を検討:
  ```python
  def _get_blocks(request_body: dict) -> list:
      return request_body["attachments"][0]["blocks"]
  ```

### テスト実行確認

```bash
# 全テスト実行
uv run pytest tests/ -v

# Slack テストのみ
uv run pytest tests/unit/test_slack.py -v

# 型チェック
uv run mypy src/

# lint
uv run ruff check src/ tests/
```

---

## リスク・確認事項

| リスク | 影響 | 緩和策 |
|-------|------|--------|
| 既存テスト 13 件の一括修正 | テスト漏れの可能性 | ヘルパー関数で構造アクセスを共通化 |
| `_get_issue_title()` の API 呼び出し増加 | Polling 頻度への影響、レートリミット | 失敗時は空文字列フォールバック、将来キャッシュ検討 |
| Slack Block Kit の `plain_text` 上限 150 文字 | 長いメッセージが途切れる | `[:150]` で切り詰め |
| Section テキスト 3000 文字上限 | 長いスタックトレース+詳細情報 | `[:3000]` 切り詰め + スタックトレース 500 文字上限 |
| `attachments` ベースのカラーバー | Slack 公式は `blocks` 直接配置を推奨 | Incoming Webhook では `attachments` が最も確実 |
| `event_router.py` への Notifier 注入 | 現在 EventRouter に `notifier` がない可能性 | コンストラクタに `notifier` パラメータを追加、または Orchestrator 経由で注入 |
