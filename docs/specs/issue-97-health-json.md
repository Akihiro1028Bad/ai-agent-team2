# #97 実装仕様: health.json 書き出しと GET /api/health

参照: web-ui-architecture §3.1 / orchestrator.py:1061 `_health_check_loop` / #84 API パターン

## スコープ

1. orchestrator が `{workspace}/health.json` に稼働統計を定期書き出し（既存の
   `_health_check_loop` を拡張、5分間隔）+ 起動直後に1回 + graceful stop 時に running=false
2. `GET /api/health` … health.json を読んで返す。不在/古い場合は「停止中」と判定

API プロセス側の readers/schemas/app は #84 のパターンを踏襲。

## 1. orchestrator 側（health.json 書き出し）

### 変更点

- `__init__`: ローカル変数 `workspace_path` を `self._health_file = workspace_path / "health.json"`
  として保持（既存の workspace_path 算出を流用、新規 expanduser はしない）
- 新規 `async def build_health_snapshot(self, accounts: dict[str, bool] | None = None) -> dict[str, Any]`:
  各ソースを **best-effort**（個別 try/except → 失敗時は None/空）で収集して dict を返す。
  - `ts`: `datetime.now(UTC).isoformat()`（書き出し時刻）
  - `running`: `self._running`
  - `queue`: `self._task_queue.get_status()` から `{"active", "queued", "max_total"}`
    （実行枠=max_total / キュー深さ=queued）
  - `repositories`: `[f"{r.owner}/{r.repo}" for r in self._settings.repositories]`
  - `accounts`: 引数 accounts（loop が health_check 結果を渡す）。None なら `{}`
  - `rate_limit`: best-effort。最初の repo の client を
    `await self._account_manager.get_client_for_repo(owner, repo)` で取得し
    `await client.get_rate_limit()` → `{"remaining", "limit", "reset"}`。失敗時 None
  - `worktrees`: best-effort。全 repo の `await self._workspace_manager.list_worktrees(repo)`
    を合算した件数（int）。失敗時 None
  - `last_poll`: best-effort。`getattr(self._poller, "get_last_poll_times", None)` が
    callable なら呼んで `dict[str, str]`、なければ `{}`
- 新規 `async def _write_health_json(self, snapshot: dict[str, Any]) -> None`:
  atomic write（tmp + replace、StatePersistence.save と同方式）。`asyncio.to_thread` で
  ファイル I/O。失敗は warning ログのみ（停止させない）
- `_health_check_loop` の改修:
  - ループ先頭で（sleep 前に）一度 `health_check()` → snapshot → write（起動直後に
    health.json を出す）
  - 以降は従来どおり 300s sleep → health_check → 失敗通知、**加えて毎周回 snapshot を write**
  - `_running` が落ちてループを抜ける直前に `running=False` の snapshot を1回 write
    （graceful stop の即時検知用）。CancelledError 経路でも best-effort で試みる
- `GitHubPoller` に `def get_last_poll_times(self) -> dict[str, str]` を追加:
  `self._last_poll`（`dict[str, datetime]`）を `{repo_key: dt.isoformat()}` に変換して返す
  （新規 dict、内部状態は変更しない）。NullPoller には追加しない（hasattr で吸収）

### health.json スキーマ（例）

```json
{
  "ts": "2026-06-11T10:00:00+00:00",
  "running": true,
  "queue": {"active": 1, "queued": 3, "max_total": 2},
  "repositories": ["owner/repo"],
  "rate_limit": {"remaining": 4990, "limit": 5000, "reset": 1718100000},
  "worktrees": 2,
  "last_poll": {"owner/repo": "2026-06-11T09:59:30+00:00"},
  "accounts": {"github/default": true}
}
```

## 2. API 側（GET /api/health）

- `api/readers.py` に `read_health(workspace, *, stale_after_sec: float = 900.0) -> HealthResponse`:
  - health.json 不在 → `HealthResponse(running=False, stale=False, reason="health.json が無い（orchestrator 未起動）", ...)`
  - 読めるが ts が `now - stale_after_sec` より古い → `running=False, stale=True,
    reason="health.json が古い（orchestrator 停止/ハングの可能性）"`、ただし統計値は
    ファイル内容を引き継いで返す
  - 正常 → ファイル内容 + `stale=False`。`running` はファイルの値
  - ts のパースは UTC ISO8601 前提（#85 と同じ前提）。パース失敗時は stale 扱い
  - 壊れ JSON / OSError → 不在と同じ扱い（running=False, reason に理由）
- `api/schemas.py` に `HealthResponse`:
  - `running: bool`, `stale: bool = False`, `reason: str | None = None`,
    `ts: str | None = None`, `queue: dict[str, int] | None = None`,
    `repositories: list[str] = []`, `rate_limit: dict[str, int] | None = None`,
    `worktrees: int | None = None`, `last_poll: dict[str, str] = {}`,
    `accounts: dict[str, bool] = {}`
  - `model_config = ConfigDict(extra="ignore")`（health.json の追加キーに寛容）
- `api/app.py` に `GET /api/health` → `read_health(workspace)` を返す（response_model=HealthResponse）
  - 常に 200（停止中も「停止中である」という事実を 200 で返す。#84 の「停止中でも応答」方針）

## テスト（TDD・カバレッジ 80%+）

- tests/unit/test_api_readers.py（or 新規 test_api_health）:
  - 不在 → running=False, reason あり
  - 正常 health.json → running=True, 各フィールド反映
  - 古い ts（stale_after_sec 超過）→ running=False, stale=True, 統計は引き継ぎ
  - 壊れ JSON → running=False
- tests/unit/test_api_endpoints.py: `GET /api/health` が 200 で HealthResponse 形状
- tests/unit/test_orchestrator_health.py（or 既存 orchestrator テストに追記）:
  - `build_health_snapshot` が queue/repositories/accounts を含む（rate_limit/worktrees/
    last_poll は Fake/None でも例外を出さない）
  - `_write_health_json` が atomic に書ける（tmp_path）
  - `GitHubPoller.get_last_poll_times` が isoformat 文字列の dict を返す
- 既存テスト全通過（mypy strict / ruff）

## 受け入れ条件（Issue 由来）

- [ ] orchestrator 稼働中に health.json が定期更新される
- [ ] 停止後（不在/古い/running=false）に API が「停止中」を返す
- [ ] GET /api/health が orchestrator 停止中でも 200 で応答
