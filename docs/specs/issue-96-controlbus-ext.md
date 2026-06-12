# #96 実装仕様: ControlBus 拡張 + queue.json + GET /api/queue

参照: docs/designs/web-ui-architecture.md §3.3 ／ 基盤: #87（ControlBus 基盤・control_bus.py）

## スコープ（#96）

#87（基盤 + pause/resume/abort/shutdown）の上に、残りの運用コマンドとキュー読み取り経路を実装する。

- 追加コマンド: **rewind / set_priority / reorder / enqueue_issue / poll_now / worktree_gc / retry_with_analysis**
- **queue.json** 書き出し（TaskQueue 状態: 待ち行列・優先度・投入時刻・待ち理由）
- **GET /api/queue**（キュー画面の読み取り側）

## 設計判断

### 1. キュー可視化の土台（TaskQueue のメタデータ）
`asyncio.PriorityQueue` は中身を覗けないため、TaskQueue に**並列メタ**を持たせる。
- `_queued_meta: dict[tuple[IssueKey, str], QueuedMeta]`（キー = (issue_key, phase)）
  - `QueuedMeta`: `repo`, `issue_number`, `phase`, `priority`, `enqueued_at`(ISO), `wait_reason`
- `wait_reason`: `"queued"`（投入直後）/ `"repo_busy"`（repo セマフォ待ちで再投入）/ `"paused"` 等
- `enqueue` で登録、`worker_loop` の実行開始/完了・park/drop で更新・除去
- 新規 `get_queue_snapshot() -> dict`:
  - `queued`: メタの一覧（priority 昇順 → enqueued_at 昇順）
  - `active`: `_active_tasks` の issue_key + phase
  - `paused` / `aborted` の issue_key 一覧、`max_total`/`max_per_repo`
- これが queue.json・GET /api/queue・set_priority/reorder の共通の真実源。

### 2. queue.json 書き出し（health.json と同パターン）
- orchestrator が `{workspace}/queue.json` に定期書き出し（`_health_check_loop` と同じ周期で同居 or 専用ループ）。`build_queue_snapshot()` → `_write_queue_json()`（atomic tmp+replace, asyncio.to_thread）
- 内容は `task_queue.get_queue_snapshot()` + `ts`。停止時も最後の内容が残る

### 3. GET /api/queue（read_health と同パターン）
- `api/readers.py` に `read_queue(workspace) -> QueueResponse`（不在/壊れは空キュー + reason）
- `api/schemas.py` に `QueueResponse` / `QueueEntry`
- `api/app.py` に `GET /api/queue`（常に 200）

### 4. set_priority / reorder（PriorityQueue 再構築）
- `set_priority(issue_key, phase, priority)`: メタの priority を更新し、**キューを drain → 再構築**
- `reorder(order: list[(issue_key, phase)])`: 指定順に priority を振り直して再構築
- 競合対策: `asyncio.Lock`（`_rebuild_lock`）下で `get_nowait()` を空になるまで実行 → 新 priority で re-put。worker_loop の `get()` とロックで排他（dequeue もロック取得）。drain 中に実行中のタスクは触らない

### 5. rewind（成果物保持の巻き戻し）
- `rewind(issue_key, target_phase)`:
  1. 現フェーズ → `Phase.SUSPENDED`（`*_to_suspended` は全アクティブ相から定義済み）
  2. `SUSPENDED` → `target_phase`（`resume_to_*` で intake/clarify/clarify_wait/split/plan/approve/implement/review/revise へ可）
  3. **worktree/PR は削除しない**（abort と違い成果物保持）
  4. 対象フェーズの `TaskRequest` を再エンキュー → そこから再実行
- target 妥当性: resume 可能な相のみ許可。不正 target は無視（warning）
- 受け入れ条件「rewind 後に対象フェーズから再実行」を満たす

### 6. poll_now / worktree_gc / enqueue_issue / retry_with_analysis
- **poll_now**: `GitHubPoller` に `request_poll_now()`（`asyncio.Event`）。poll ループの sleep を `wait_for(event, timeout=interval)` にし、セットされたら即ポーリング
- **worktree_gc**: 全 repo で `list_worktrees(repo)` → worktree 名から issue 番号を抽出 → その issue が DONE/未登録なら `remove_worktree`（孤児掃除）
- **enqueue_issue**: コマンドの issue（or URL から抽出した番号）に対し、トリガラベルを `add_label`。poller が次サイクルで拾う（control.jsonl 経由で直接キュー投入はしない＝既存検知フローに乗せる）
- **retry_with_analysis**: 対象 issue の直近エラー（events の error 系）を要約し、再実行プロンプトに含めて IMPLEMENT/REVISE を再エンキュー（#87 の abort と対で、成果物保持の再試行）

### 7. コマンド語彙の拡張（control_bus.py）
`_OPERATIONAL_ACTIONS` に 7 種追加。issue-scoped（rewind/set_priority/reorder/enqueue_issue/retry_with_analysis）と global 寄り（poll_now/worktree_gc）で分類。
- rewind は `target` フィールド（巻き戻し先 phase 文字列）を取る
- set_priority は `priority` フィールド、reorder は `order` フィールド（issue 番号リスト）
- 既存 `parse_operational_line` を拡張 or `parse_operational_line_v2`。認可は #87 と同じ actor 検証

## 実装ユニット（1 PR・内部分割。#87 と同じ進め方）

- **Unit A**: TaskQueue メタ + `get_queue_snapshot` + queue.json 書き出し + `read_queue` + `GET /api/queue` + schema（受け入れ条件「UI キュー画面が実データで動く」の読み取り土台）
- **Unit B**: poll_now / worktree_gc / enqueue_issue（単純コマンド）+ control_bus 語彙拡張 + ハンドラ
- **Unit C**: set_priority / reorder（メタ経由の再構築・ロック）
- **Unit D**: rewind（成果物保持の 2-hop 巻き戻し + 再エンキュー）+ retry_with_analysis

## テスト（TDD・80%+）
- `test_control_bus.py`: 拡張コマンドのパース（rewind の target / set_priority / reorder / 単純コマンド / 認可）
- `test_task_queue.py`: メタ登録・snapshot・set_priority/reorder の再構築（優先順位が反映される）
- `test_orchestrator_control.py`: 各ハンドラ（rewind は SUSPENDED→target→再エンキュー、worktree_gc は孤児のみ remove、poll_now は poller トリガ）
- `test_api_readers.py` / `test_api_endpoints.py`: read_queue（不在/正常/壊れ）・GET /api/queue 200
- 既存テスト全通過 / mypy strict / ruff

## 検証（レベル3 まで）
- ユニット（pytest/vitest）・ビルド（next build/tsc/ruff/mypy）に加え、queue.json + GET /api/queue 完成後に
  **フィクスチャ駆動のブラウザ目視**: workspace に state.json/health.json/queue.json を置き
  `uv run ai-agent api` + `cd web && npm run dev` → ブラウザでキュー画面の表示・並べ替え操作を確認

## 受け入れ条件（Issue 由来）
- [x] UI の実行キュー画面（表示+並べ替え）が実データで動く
  （Unit A: 表示をブラウザ目視で確認 / Unit C: reorder バックエンド。UI 操作配線は #88）
- [x] rewind 後に対象フェーズから再実行されることのテスト
  （Unit D: `test_rewind_resumes_target_and_reenqueues`）

## 非スコープ
- UI 側の操作配線（POST /api/control への接続・キュー画面の実接続）→ #88
- 認証 → #115 ／ systemd 実配線 → #92
