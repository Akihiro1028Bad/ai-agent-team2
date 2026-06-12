# #87 実装仕様: ControlBus（control.jsonl コマンドキューと消費ループ）

参照: docs/designs/web-ui-architecture.md §3.3 §7 / Issue #87（6巡レビューでスコープ確定）

## スコープ（#87）

ControlBus の**基盤 + 基本コマンド**のみ。拡張（rewind/priority/enqueue/poll_now/worktree_gc/retry + queue.json + GET /api/queue）は #96。

- control.jsonl から運用コマンドを読み、orchestrator のメインループが安全に適用する消費ループ
- コマンド: **shutdown / pause / resume / abort**
- `POST /api/control`（書き込み側、API プロセス）
- 起動/停止 API（`POST /api/orchestrator/{start,stop}` → systemctl の**薄いラッパ**。実運用配線は #92）
- 適用結果を events.jsonl に監査記録

## 設計判断

### 1. 承認(approve/reject)と運用(shutdown/pause/resume/abort)の分離
control.jsonl は既存の approve/reject（U4 #82・`control_file.py`・未配線スタブ）と同居するが、
**運用コマンドは別系統**として扱う。新規 `control_bus.py` に運用コマンドの型とパーサを置き、
専用 offset で消費する。approve/reject 行は運用ループでは無視（将来の承認消費ループが別 offset で処理）。

運用コマンドの JSONL 形式::

    {"action": "pause",    "issue": 5, "actor": "alice"}
    {"action": "resume",   "issue": 5, "actor": "alice"}
    {"action": "abort",    "issue": 5, "actor": "alice"}
    {"action": "shutdown",             "actor": "alice"}

- `action` ∈ {pause, resume, abort, shutdown}（`_OPERATIONAL_ACTIONS`）
- issue-scoped（pause/resume/abort）は `issue` 必須（正整数）。global（shutdown）は `issue` 不要
- `actor`: 実行者 login（承認者検証に使用）
- 不正行・未知 action・型不正は読み飛ばす（offset には数える）

### 2. 承認者検証（なりすまし防止 / #102 流用）
運用コマンドは**全リポジトリの `resolve_approvers(owner, approvers)` の和集合**を許可アクター集合とし、
`is_authorized_approver(actor, allowed)` を通らないコマンドは無視（監査ログに ignored を残す）。
単一運用者・localhost 前提（web-ui-architecture §1）。専用運用者リストは follow-up。

### 3. pause/resume（per-issue・graceful）
`TaskQueue` に `_paused: set[IssueKey]` と `_parked: dict[IssueKey, QueuedTask]` を持たせる。
- `pause(issue_key)`: `_paused` に追加
- worker_loop の dequeue 直後、`issue_key in _paused` なら**実行せず `_parked` に退避**して次のループへ
  （＝実行中フェーズは中断しない。次フェーズの開始手前で止まる＝フェーズ境界 graceful pause）
- `resume(issue_key)`: `_paused` から除去し、`_parked` にあれば再エンキュー
- busy-spin しない（park は再エンキューしないため）

「実行中ターンを kill しない」受け入れ条件は **pause/resume に適用**（abort は即時 cancel で別挙動）。

### 4. abort（per-issue・即時）
1. `task_queue.cancel_task(issue_key)` で実行中タスクを `task.cancel()`
2. `workspace_manager.remove_worktree(repo, issue_number)`（冪等・force）
3. 状態を `Phase.SUSPENDED` へ（未定義遷移に備え、state_machine に**強制 suspend 経路**を用意 or 不足遷移を追加）
4. `replace_phase_label(repo, issue_number, "phase:suspended")`
5. `event_logger.track("issue_aborted", issue_number=N, phase=..., data={"actor":...})`

### 5. shutdown（graceful drain → stop）
`TaskQueue` に `_draining: bool` を追加。
- worker_loop は各イテレーション冒頭で「draining かつ自分が拾える新規タスクが無い」なら return
- 消費ループが shutdown 受信 → `task_queue.request_drain()` → orchestrator が
  in-flight 完了を待って（`get_status()["active"]==0` または worker 自然終了）→ 既存 `stop()` の
  残処理へ。最大待ち時間（既定 600s）超過で hard cancel フォールバック
- プロセス終了自体は systemd（#92）。#87 の shutdown は「graceful に自分の loop を畳む」まで

### 6. 消費ループ
`orchestrator._control_loop()`（`_health_check_loop` 同型の背景タスク）。
- `start()` で `asyncio.create_task(..., name="control-bus")`、`stop()` の cancel 対象に追加
- 既定パス: `settings.control_file` があればそれ、無ければ `workspace_path / "control.jsonl"`
- ループ: `read_new_operational_commands(path, offset, allowed_actors)` をポーリング（既定 2s）→
  各コマンドを適用 → offset 更新。offset はループ内 state（再起動時は 0 から＝積まれたコマンドを起動時に消費、受け入れ条件）
- DoS 上限は既存 `_MAX_CONTROL_FILE_BYTES`（10MiB）を踏襲

### 7. API（POST、書き込み）
- `POST /api/control`: body `{action, issue?, actor?}` を検証し control.jsonl に**追記**（API プロセスが書く）。
  202 Accepted + `{accepted: true}`。`actor` は将来の認証主体から（現状 AuthMiddleware は no-op）
- `POST /api/orchestrator/{start,stop}`: systemctl --user の薄いラッパ（`ControlSystemd` Protocol で抽象化し、
  実装はベストエフォート subprocess、テストはモック）。stop は control.jsonl に shutdown を積んでから systemctl stop の2段階（設計書 §3.3）
- schemas に `ControlRequest` / `ControlAcceptedResponse`

## テスト（TDD・カバレッジ 80%+）

- `tests/unit/test_control_bus.py`: 運用コマンドのパース（各 action / issue 必須・global / 不正 / actor）
- `tests/unit/test_task_queue.py`: pause→park→resume 再エンキュー、abort 中の cancel、drain 終了
- `tests/unit/test_orchestrator_control.py`: 消費ループが pause/resume/abort/shutdown を適用、
  承認者検証（許可外 actor は無視）、起動時に積まれたコマンドを消費、監査イベント記録
- `tests/unit/test_api_endpoints.py`: POST /api/control が control.jsonl に追記・202、不正 body は 422
- 既存テスト全通過 / mypy strict / ruff

## 受け入れ条件（Issue 由来）
- [ ] 実行中ターンを強制 kill しない（pause/resume はフェーズ完了後に停止）ことのテスト
- [ ] オーケストレーター停止中に積んだコマンドが起動時に消費される
- [ ] abort は cancel_task による即時キャンセル（pause と挙動が違うことを明記）

## 非スコープ（移管先）
- rewind / set_priority / reorder / enqueue_issue / poll_now / worktree_gc / retry_with_analysis / queue.json / GET /api/queue → **#96**
- 承認/差し戻しの書き込み（POST /api/issues/{n}/review）→ **#89**
- systemd 常駐の実運用配線 → **#92**
- control.jsonl のローテーション（10MiB 超で全スキップの解消）→ follow-up
