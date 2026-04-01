# 実装計画: Issue #9 - Slackメッセージの改善

## 変更ファイル一覧（実装順）

### Step 1: データモデル追加（依存なし）

1. **`src/ai_agent_orchestrator/models.py`** - `NotificationType` Enum 追加
   - 依存: なし
   - 変更内容:
     - `NotificationType(StrEnum)` を新規追加（16通知タイプ）
     - `phase_start`, `hearing_question`, `design_pr_created`, `impl_pr_created`, `fix_pr_created`, `plan_posted`, `design_revised`, `impl_revised`, `split_proposed`, `split_completed`, `issue_completed`, `chain_started`, `system_start`, `health_check_failure`, `error`, `timeout`, `suspended`
   - 変更規模: 小（Enum定義の追加のみ）

### Step 2: SlackNotifier のリッチペイロード構築（依存: Step 1）

2. **`src/ai_agent_orchestrator/notifications/slack.py`** - リッチペイロード構築メソッド群追加
   - 依存: Step 1 (`NotificationType`)
   - 変更内容:
     - **定数追加**:
       - `_TYPE_EMOJI: dict[str, str]` — 通知タイプ別絵文字（16エントリ）
       - `_TYPE_COLOR: dict[str, str]` — 通知タイプ別カラー（16エントリ、青/黄/緑/赤の4色体系）
       - `_PHASE_DISPLAY_NAME: dict[str, str]` — フェーズ表示名（日本語、18エントリ）
     - **`notify()` メソッドの変更**:
       - `metadata.get("notification_type")` の有無で分岐
       - あり → `_build_rich_payload()` を呼び出し
       - なし → 従来の `_build_payload()` を呼び出し（後方互換）
     - **新規メソッド追加**:
       - `_build_rich_payload()` — Attachment + Block Kit 形式のペイロード構築
       - `_build_header_text()` — Header ブロック用テキスト（Issue# + タイトル or メッセージ）
       - `_build_fields()` — 2カラム Fields（フェーズ/進捗/所要時間/ブランチ）
       - `_build_body_text()` — 本文テキスト（スタックトレース抜粋、error_analysis対応）
       - `_build_actions()` — Action Buttons（Issue/PR/コメントへのリンク）
       - `_build_rich_context()` — リッチ Context（repo + notification_type）
     - **既存メソッドの維持**:
       - `_build_payload()` はそのまま残す（後方互換）
       - `_build_context_text()` もそのまま残す
       - `_level_emoji()` もそのまま残す
   - 変更規模: 大（約150行追加）

### Step 3: テスト追加 — SlackNotifier（依存: Step 2）

3. **`tests/unit/test_slack.py`** - リッチペイロードのテスト追加
   - 依存: Step 2
   - 変更内容:
     - 既存13テストケース（TC-SL-01 〜 TC-SL-13）はそのまま維持
     - 以下のテストケースを追加:
       - **リッチペイロード構築テスト** (TC-SL-14 〜 TC-SL-30): 17ケース
         - `notification_type` ありでリッチペイロード生成（attachments構造）
         - Header の3パターン（Issue#+タイトル / Issue#のみ / システム通知）
         - Fields の全フィールド表示・空パターン
         - Body のスタックトレース切り詰め（5行以下 / 5行超）
         - Actions の3ボタン / 1ボタン / なし
         - Context の各パターン
       - **マッピングテスト** (TC-SL-31 〜 TC-SL-38): 8ケース
         - 全通知タイプの絵文字・カラーマッピング
         - デフォルトフォールバック
         - カラー値検証（青/黄/緑/赤）
       - **後方互換性テスト** (TC-SL-39 〜 TC-SL-41): 3ケース
         - `notification_type` なし / 空文字 / metadata None
       - **フェーズ表示名テスト** (TC-SL-55 〜 TC-SL-56): 2ケース
     - 合計: 既存13 + 新規30 = **43テストケース**
   - 変更規模: 大（約400行追加）

### Step 4: base.py — フェーズ開始通知・進捗計算・エラー通知改善（依存: Step 2）

4. **`src/ai_agent_orchestrator/phases/base.py`** - フェーズ開始通知 + 進捗計算 + エラー改善
   - 依存: Step 2（`_PHASE_DISPLAY_NAME` を slack.py からインポート or base.py に定義）
   - 変更内容:
     - **定数追加**:
       - `_WORKFLOW_PHASES: dict[str, list[str]]` — タイプ別ワークフローフェーズリスト（bug/feature-s/feature-m/feature-l）
     - **`execute()` メソッドの変更**:
       - `phase_start` トラッキングの後に `await self._notify_phase_start(request)` を追加
     - **新規メソッド追加**:
       - `_notify_phase_start()` — フェーズ開始のリッチ通知（`notification_type: "phase_start"`）
       - `_get_repo_key()` — `repo` オブジェクトから `"owner/repo"` 文字列を取得（staticmethod）
       - `_get_issue_title()` — Issue タイトルを best-effort で取得
       - `_get_progress()` — 全体進捗文字列を計算（例: "3/8 フェーズ完了"）
     - **`_handle_error()` の改善**:
       - スタックトレースを取得して metadata に含める
       - `notification_type: "error"` を追加
       - `repo`, `issue_title` を追加
     - **`_handle_timeout()` の改善**:
       - `notification_type: "timeout"` を追加
       - `repo`, `issue_title` を追加
   - 変更規模: 中（約60行追加・変更）

### Step 5: 各フェーズファイルの metadata 拡充（依存: Step 4）

以下の各ファイルで `notify()` 呼び出しの metadata を拡充する。変更パターンは統一的:
- `notification_type` の追加
- `repo` (`_get_repo_key()` 使用) の追加
- `issue_title` の追加
- PR作成系は `pr_url` の追加
- `phase` の追加
- `duration_sec`, `branch` の追加（該当する場合）

5. **`src/ai_agent_orchestrator/phases/hearing.py`** - metadata 拡充
   - 依存: Step 4
   - 変更内容:
     - `notify()` 呼び出しに以下を追加:
       - `notification_type: "hearing_question"`
       - `repo: repo_key`
       - `issue_title`
       - `phase: "hearing"`
     - `_get_repo_key()` は base.py から継承して使用
   - 変更規模: 小（5-10行変更）

6. **`src/ai_agent_orchestrator/phases/design.py`** - metadata 拡充
   - 依存: Step 4
   - 変更内容:
     - `notify()` 呼び出しに以下を追加:
       - `notification_type: "design_pr_created"`
       - `repo: repo_key`
       - `issue_title`
       - `pr_url`（GitHub PR URL を構築）
       - `phase: "design"`
       - `duration_sec: result.duration_sec`
   - 変更規模: 小（5-10行変更）

7. **`src/ai_agent_orchestrator/phases/implement.py`** - metadata 拡充
   - 依存: Step 4
   - 変更内容:
     - `notify()` 呼び出しに以下を追加:
       - `notification_type: "impl_pr_created"`
       - `repo: repo_key`
       - `issue_title`
       - `pr_url`
       - `phase: "implement"`
       - `duration_sec: result.duration_sec`
       - `branch: f"feature/issue-{request.issue_number}"`
   - 変更規模: 小（5-10行変更）

8. **`src/ai_agent_orchestrator/phases/fix.py`** - metadata 拡充
   - 依存: Step 4
   - 変更内容:
     - `notify()` 呼び出しに以下を追加:
       - `notification_type: "fix_pr_created"`
       - `repo: repo_key`
       - `issue_title`
       - `pr_url`
       - `phase: "fix"`
       - `duration_sec: result.duration_sec`
   - 変更規模: 小（5-10行変更）

9. **`src/ai_agent_orchestrator/phases/design_revise.py`** - metadata 拡充
   - 依存: Step 4
   - 変更内容:
     - `notify()` 呼び出しに以下を追加:
       - `notification_type: "design_revised"`
       - `repo: repo_key`
       - `issue_title`
       - `phase: "design-revise"`
   - 変更規模: 小（5行変更）

10. **`src/ai_agent_orchestrator/phases/impl_revise.py`** - metadata 拡充
    - 依存: Step 4
    - 変更内容:
      - `notify()` 呼び出しに以下を追加:
        - `notification_type: "impl_revised"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "impl-revise"`
    - 変更規模: 小（5行変更）

11. **`src/ai_agent_orchestrator/phases/analysis.py`** - metadata 拡充
    - 依存: Step 4
    - 変更内容:
      - `notify()` 呼び出しに以下を追加:
        - `notification_type: "plan_posted"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "analysis"`
    - 変更規模: 小（5行変更）

12. **`src/ai_agent_orchestrator/phases/plan_brief.py`** - metadata 拡充
    - 依存: Step 4
    - 変更内容:
      - `notify()` 呼び出しに以下を追加:
        - `notification_type: "plan_posted"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "plan-brief"`
    - 変更規模: 小（5行変更）

13. **`src/ai_agent_orchestrator/phases/split.py`** - metadata 拡充
    - 依存: Step 4
    - 変更内容:
      - SplitProposalExecutor の `notify()`:
        - `notification_type: "split_proposed"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "split-proposal"`
      - SplitExecuteExecutor の `notify()`:
        - `notification_type: "split_completed"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "split-execute"`
    - 変更規模: 小（10行変更）

14. **`src/ai_agent_orchestrator/phases/done.py`** - metadata 拡充
    - 依存: Step 4
    - 変更内容:
      - DoneExecutor.process_result の `notify()`:
        - `notification_type: "issue_completed"`
        - `repo: repo_key`
        - `issue_title`
        - `phase: "done"`
      - DoneExecutor._chain_next_child_issue の `notify()`:
        - `notification_type: "chain_started"`
        - `repo: repo_key`
        - `issue_title`
    - 変更規模: 小（10行変更）

### Step 6: orchestrator.py のシステム通知改善（依存: Step 2）

15. **`src/ai_agent_orchestrator/orchestrator/orchestrator.py`** - システム通知改善
    - 依存: Step 2
    - 変更内容:
      - `start()` 通知:
        - `notification_type: "system_start"` 追加
      - `_route_events()` エラー通知:
        - `notification_type: "error"` 追加
      - `_handle_task_error()` 通知:
        - `notification_type: "suspended"` 追加
        - `repo` 追加
      - `_health_check_loop()` 通知:
        - `notification_type: "health_check_failure"` 追加
    - 変更規模: 小（各 notify 呼び出しに metadata フィールド追加）

### Step 7: テスト追加 — base.py・フェーズファイル（依存: Step 4, 5）

16. **`tests/unit/test_phases.py`** (既存ファイルに追加 or 新規ファイル) - フェーズ通知テスト
    - 依存: Step 4, 5
    - 変更内容:
      - **base.py テスト** (TC-SL-42 〜 TC-SL-54): 13ケース
        - `_notify_phase_start()` が `phase_start` type で通知すること
        - `_get_repo_key()` の正常系・異常系
        - `_get_issue_title()` の正常系・例外時フォールバック
        - `_get_progress()` の各タイプ別・未知タイプ・未知フェーズ
        - `_handle_error()` のスタックトレース付きリッチ通知
        - `_handle_timeout()` のリッチ通知
      - **各フェーズの通知 metadata テスト** (TC-SL-57 〜 TC-SL-70): 14ケース
        - 各フェーズの `notify()` が正しい `notification_type` と必須フィールドを含むこと
    - 変更規模: 大（約300行追加）

### Step 8: 仕様書の更新（依存: Step 1-6）

17. **`docs/specs/slack.md`** - 仕様書の更新
    - 依存: Step 1-6（実装完了後に最新の状態を反映）
    - 変更内容:
      - 通知タイプ体系の記載追加
      - リッチペイロード構造の説明追加
      - 各通知タイプの絵文字・カラー・フォーマット一覧
      - フェーズ開始通知の仕様追加
      - 後方互換性の説明
    - 変更規模: 中

---

## 依存関係グラフ

```
Step 1: models.py (NotificationType)
  │
  ▼
Step 2: slack.py (リッチペイロード構築)
  │
  ├──────────────────────┐
  ▼                      ▼
Step 3: test_slack.py   Step 4: base.py (フェーズ開始通知 + 進捗)
                          │
                          ├──────────────────────┐
                          ▼                      ▼
                        Step 5: 各フェーズ       Step 6: orchestrator.py
                        (hearing, design, ...)
                          │
                          ▼
                        Step 7: テスト追加 (フェーズ通知)
                          │
                          ▼
                        Step 8: docs/specs/slack.md
```

## テスト方針

### ユニットテスト対象

| 対象 | テストファイル | テスト内容 |
|------|-------------|----------|
| `slack.py` | `tests/unit/test_slack.py` | リッチペイロード構築、定数マッピング、後方互換性 |
| `models.py` | `tests/unit/test_models.py` | `NotificationType` Enum の値一覧 |
| `base.py` | `tests/unit/test_phases.py` | フェーズ開始通知、進捗計算、ヘルパーメソッド |
| 各フェーズ | `tests/unit/test_phases.py` | metadata に正しい `notification_type` と必須フィールドが含まれること |

### テスト実行方法

```bash
# 全テスト実行
uv run pytest tests/ -v

# Slack関連テストのみ
uv run pytest tests/unit/test_slack.py tests/unit/test_phases.py -v

# カバレッジ計測
uv run pytest tests/unit/test_slack.py tests/unit/test_phases.py \
  --cov=src/ai_agent_orchestrator/notifications/slack \
  --cov=src/ai_agent_orchestrator/models \
  --cov=src/ai_agent_orchestrator/phases/base \
  --cov-report=term-missing
```

### テスト戦略

1. **後方互換テスト**: 既存13テスト（TC-SL-01〜13）が全て PASS すること
2. **リッチペイロードテスト**: `notification_type` ありの場合に attachments 構造で送信されること
3. **マッピング網羅テスト**: 全16通知タイプの絵文字・カラーが正しいこと
4. **フェーズ通知テスト**: 各フェーズの `notify()` が正しい metadata を含むこと
5. **エッジケーステスト**: 空文字列、None、未知のタイプ等のフォールバック動作

## リスク・確認事項

| リスク | 対策 |
|-------|------|
| Block Kit の文字数制限 (section: 3000文字) | スタックトレースを最後5行に切り詰め |
| Webhook レート制限 | フェーズ開始通知の追加で頻度が倍増するが、1 Issue あたり数分間隔なので問題なし |
| 後方互換性の破壊 | `notification_type` の有無で分岐する設計により回避 |
| Issue タイトル取得の追加API呼び出し | best-effort で取得、失敗時は空文字にフォールバック |
| `_PHASE_DISPLAY_NAME` の配置場所 | `slack.py` に定義し、`base.py` からは import して使用（循環参照を避ける） |
| 既存テストへの影響 | `notification_type` なしの呼び出しは従来パスを通るため既存テストは全て PASS |
