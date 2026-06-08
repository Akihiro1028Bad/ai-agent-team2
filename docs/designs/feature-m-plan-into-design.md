# 設計書: feature-m ワークフローの計画フェーズを設計フェーズへ統合

**作成日**: 2026-06-08
**対象**: feature-m ワークフロー（bug / feature-s / feature-l は対象外）

## 1. 背景と目的

### 背景
現在の feature-m フローは以下の通り。

```
TYPE_DETECTION → HEARING → DESIGN → [設計PR承認] → PLANNING → PLAN_VALIDATION → IMPLEMENT → CI → IMPL_REVIEW → ...
```

調査の結果、`PLANNING → PLAN_VALIDATION` の遷移が状態機械に配線されておらず
（`Phase.PLAN_VALIDATION` は enum・`ALLOWED_TRANSITIONS`・`planning.py` には存在するが、
`IssueWorkflow` の State 定義と `TRANSITION_MAP` に欠落）、
planning 完了直後に `InvalidTransitionError` → SUSPENDED となり、
**feature-m が実装まで到達できない**状態だった。

### 目的
ワークフローを以下に変更し、設計段階で実装計画品質まで作り込んでから承認・実装に進む。

```
TYPE_DETECTION → HEARING → DESIGN★ → [設計PR承認] → IMPLEMENT → CI → IMPL_REVIEW → ...
```

★ DESIGN フェーズで「設計＋実装計画（サブタスク・依存関係・テスト）」を 1 本の設計書に作り込み、
生成後に構造を自己検証する（NG なら作り直し）。`PLANNING` / `PLAN_VALIDATION` は廃止する。

### 期待効果
- 承認ゲートが「設計PR承認」1 箇所に集約され、ユーザーの認識（設計＝計画の確定）と一致する
- 配線漏れバグの解消（feature-m が実装まで到達可能に）
- 高コストな IMPLEMENT の前に、安価な構造検証で不正な計画を弾く品質ゲートを維持

## 2. ドキュメント構成（決定事項）

| 項目 | 決定 |
|------|------|
| 設計書と計画書 | **1 本に統合**。`docs/designs/issue-N.md` に「設計」＋「## サブタスク（依存関係・ファイル・テスト）」を含める |
| `issue-N-plan.md` | **廃止** |
| IMPLEMENT が読むファイル | `issue-N.md`（統合設計書） |
| 構造検証 | **DESIGN フェーズ内に残す**（生成後・設計PR提出前に自己チェック、NG なら作り直し） |
| 旧コード | **完全削除**（`PLANNING` / `PLAN_VALIDATION` 関連） |

## 3. コンポーネント別変更

### 3.1 設計フェーズ（中核）
**対象**: `src/ai_agent_orchestrator/phases/design.py`, `docs/templates/02_design.md`,
`src/ai_agent_orchestrator/phases/prompt_enhancer.py`

- 設計テンプレート `02_design.md` に `04_planning.md` のサブタスク構造を統合する。
  生成物 `issue-N.md` が以下を含むこと:
  - 設計内容（既存）
  - `## サブタスク` セクション
  - 各サブタスク `### subtask-N:` ＋ `depends_on:` ＋ `files:`（テストファイルを含む）
- `prompt_enhancer` の `"design"` エンハンサに `_TEST_REQUIREMENTS` を追加する。
- `design.process_result` に**構造自己検証ループ**を組み込む:
  1. 生成された `issue-N.md` を読み込み `validate_plan()` で検証
  2. 検証 NG かつ差し戻し上限（2 回）未満 → 設計を再生成（DESIGN 再エンキュー、`replan_count` 相当をインクリメント）
  3. 検証 NG かつ上限到達 → 警告コメント付きで続行
  4. 検証 OK → 設計 PR を作成し `design_review` へ遷移、`@claude /review` を投稿（既存処理）

### 3.2 構造検証ロジック
**対象**: `src/ai_agent_orchestrator/phases/plan_validation.py`

- 純粋関数 `validate_plan(plan_text, worktree_path)` は**残して DESIGN から再利用**する。
- フェーズクラス `PlanValidationExecutor` は削除する。
- 検証内容（既存のまま）: サブタスク存在・連番・依存循環・未定義依存・テストファイル有無。
- ファイル配置は `plan_validation.py` のままでも、`design_validation.py` 等へ移設してもよい（実装時判断）。

### 3.3 状態機械
**対象**: `src/ai_agent_orchestrator/orchestrator/state_machine.py`

- `IssueWorkflow` の State / 遷移:
  - 追加: `design_review_to_implement = design_review.to(implement)`
  - 削除: `planning` / `plan_validation` State（後者は元々未定義）、
    `planning_to_implement`, `planning_to_suspended`, `design_review_to_planning` 等の planning 系遷移
- `TRANSITION_MAP`:
  - 追加: `(Phase.DESIGN_REVIEW, Phase.IMPLEMENT): "design_review_to_implement"`
  - 削除: `(DESIGN_REVIEW, PLANNING)`, `(PLANNING, IMPLEMENT)`, `(PLANNING, SUSPENDED)` 等
- `ALLOWED_TRANSITIONS`:
  - `Phase.DESIGN_REVIEW` の遷移先に `IMPLEMENT` を追加、`PLANNING` を削除
  - `Phase.PLANNING` / `Phase.PLAN_VALIDATION` の行を削除

### 3.4 イベントルーター
**対象**: `src/ai_agent_orchestrator/poller/event_router.py`

- `_handle_design_pr_approved`: `Phase.PLANNING` への遷移＋エンキューを
  **`Phase.IMPLEMENT`** に変更する。docstring / ルーティング表のコメントも更新。

### 3.5 実装フェーズ / コンテキスト
**対象**: `src/ai_agent_orchestrator/phases/implement.py`, `src/ai_agent_orchestrator/context/engine.py`

- `ContextEngine.read_impl_plan` の探索対象を `issue-N-plan.md` から
  **`issue-N.md`**（統合設計書）に変更する。
- `implement.py` の `parse_subtasks` / `extract_planned_files` は構造が同じならそのまま流用。

### 3.6 旧コードの完全削除
- `src/ai_agent_orchestrator/phases/planning.py`
- `PlanValidationExecutor`（`plan_validation.py` のクラス部分。`validate_plan` 関数は残す）
- `orchestrator.py` の executor 登録から `"planning"` / `"plan-validation"` を削除
- `docs/templates/04_planning.md`（内容は `02_design.md` へ統合後）
- `Phase.PLANNING` / `Phase.PLAN_VALIDATION`（`models.py`）

## 4. テスト計画

- **状態機械**: `design_review → implement` 遷移が成功し、`planning` 系遷移が存在しないことを検証。
- **設計フェーズ**: 検証 OK で PR 作成＋design_review 遷移 / 検証 NG で再生成 / 上限到達で警告続行、の各分岐。
- **実装フェーズ**: `read_impl_plan` が `issue-N.md` を読み、`parse_subtasks` が統合設計書から
  サブタスクを抽出できること。
- **イベントルーター**: `design_pr_approved` が IMPLEMENT をエンキューすること。
- **削除に伴う修正**: planning / plan_validation を参照する既存テストの削除・修正。
- 既存ユニットテストが全てパスすること（`uv run pytest tests/unit`）、mypy / ruff クリーン。

## 5. 後片付け・移行

- 永続化 state（`state.json`）に `planning` / `plan-validation` フェーズが残っている Issue の
  ロード対策（enum 削除に伴い、ロード時に未知フェーズを SUSPENDED 等へフォールバックするか、
  移行スクリプトで読み替える。実装時に方針確定）。
- テスト用 Issue **#127**（現在 SUSPENDED）はクローズまたはラベルリセット。

## 6. スコープ外

- bug / feature-s / feature-l の各ワークフロー（変更なし）
- レート制限・シークレット対応 PR #77（別件）
