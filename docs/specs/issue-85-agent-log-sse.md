# #85 実装仕様: 実行ログのファイル出力と SSE ストリーム配信

参照: web-ui-architecture §3.2, §7 G3 / #84 仕様 (docs/specs/issue-84-api-read-endpoints.md)

## スコープ

1. claude_runner の SDK メッセージを `logs/issue-{n}/agent.jsonl` に逐次追記
2. `GET /api/issues/{n}/logs` … agent.jsonl の過去分読み出し（ページング）
3. `GET /api/stream?issue={n}` … events.jsonl + agent.jsonl の tail を SSE 配信
   （Last-Event-ID で再接続時の取りこぼしなし）

## 1. agent.jsonl 書き出し

### モジュール

- `src/ai_agent_orchestrator/sanitize.py` 【新設】… EventLogger の
  SENSITIVE_KEYS / TOKEN_PATTERN / URL_TOKEN_PATTERN とサニタイズ関数を抽出。
  `sanitize_dict(data) -> dict` / `sanitize_text(text) -> str` を公開。
  EventLogger は本モジュールへ**委譲**する（公開挙動・クラス属性は互換維持。
  既存テストを壊さない）
- `src/ai_agent_orchestrator/agents/agent_log.py` 【新設】… `AgentLogWriter`
  - `__init__(log_dir: Path)` … EventLogger と同じ基底 (workspace/logs)
  - `async def write(issue_number: int, record: dict) -> None` …
    `logs/issue-{n}/agent.jsonl` に 1 行 JSON 追記（asyncio.Lock +
    to_thread、EventLogger.track と同方式）。record は書き込み前に sanitize_dict

### runner への配線

- `ClaudeAgentRunner.__init__(tracker, agent_log_writer: AgentLogWriter | None = None)`
- `run(..., issue_number: int | None = None)` を追加。writer と issue_number が
  両方ある場合のみログ出力（None なら従来どおり無出力 = 後方互換）
- `_run_query` のメッセージループ内で各 msg をレコード化して await write。
  **書き込み失敗はフェーズ実行を止めない**（warning ログのみ、握りつぶす）
- 呼び出し側の変更（2箇所）: `phases/base.py:485` / `phases/revise_common.py:171`
  の `self._runner.run(...)` に `issue_number=request.issue_number` を追加
- orchestrator の構築（orchestrator.py:451）で
  `ClaudeAgentRunner(tracker=..., agent_log_writer=AgentLogWriter(workspace/"logs"))`
- conftest の FakeClaudeRunner は `**kwargs` 受けのため変更不要

### レコードスキーマ（1 行 = 1 レコード）

共通: `{"ts": <UTC ISO8601>, "phase": <str>, "type": <下記>}`

| type | 追加フィールド | ソース |
|---|---|---|
| `text` | `text: str` | AssistantMessage の TextBlock |
| `tool_use` | `tool: str, input: dict(サニタイズ済)` | ToolUseBlock |
| `result` | `session_id, cost_usd, duration_ms, usage: dict\|null, is_error: bool, subtype: str\|null` | ResultMessage |

- usage は `ResultMessage.usage`（in/out トークン。UI コスト画面の集計ソース）。
  SDK の属性有無は `getattr(msg, "usage", None)` で防御
- text は長文になり得るが切り詰めない（ライブログビューアの本文）。
  sanitize_text を通す

## 2. GET /api/issues/{n}/logs（過去分・ページング）

- readers に `read_agent_logs(workspace, issue_number, offset=0, limit=200)` を追加
  - offset = 行インデックス（古い順）。壊れ行はスキップ（スキップ行も
    インデックスは消費する: オフセットは「物理行」基準で安定させる）
  - 返却: `AgentLogPage {records: list[AgentLogRecord], next_offset: int, total: int}`
    （`next_offset` は今回読んだ最終物理行+1。SSE の Last-Event-ID と同じ単位）
- `AgentLogRecord` は EventRecord 同様 `extra="ignore"` の寛容モデル
  （ts/phase/type + 任意フィールドは `data` 的にそのまま通す。pydantic で
  全フィールドを列挙せず `model_config extra="allow"` でも可。選定は実装に委ねる
  が **API レスポンスとして安定した形**にすること）
- `limit` は `ge=1, le=1000`（#84 と同様）

## 3. GET /api/stream（SSE）

### 設計

- `src/ai_agent_orchestrator/api/stream.py` 【新設】
  - 核: `async def tail_issue_streams(workspace, issue_number, *, start_events: int, start_agent: int, poll_interval: float = 0.5, max_idle_sec: float | None = None) -> AsyncIterator[SseEvent]`
    - events.jsonl / agent.jsonl の**物理行オフセット**を保持し、新規行を検知したら
      `SseEvent(source="events"|"agent", line_index=int, data=str)` を yield
    - ファイル不在は「まだ 0 行」として扱い、出現したら読み始める
    - poll_interval=0.5s（受け入れ条件「1 秒以内」を満たす）
    - `max_idle_sec` はテスト用の打ち切り（本番 None = 無限）
  - エンドポイント側: `GET /api/stream?issue={n}` →
    `StreamingResponse(..., media_type="text/event-stream")`
    - 各 yield を `event: {source}\nid: events:{e},agent:{a}\ndata: {json行}\n\n` で送出
      （id は**両ファイルの消費済み行数**を常に併記 → どの時点で切れても再開可能）
    - `Last-Event-ID` リクエストヘッダ（または `?last_event_id=` クエリ。
      EventSource polyfill 対応で両方受ける）をパースして start オフセットに使用。
      不正形式は 0,0 から
    - 15 秒ごとにコメント行 `: keep-alive\n\n` を送出（プロキシ切断対策）
- 新規依存は追加しない（sse-starlette 不使用。手書き SSE フォーマット）

### テスト戦略

- tail_issue_streams を**ジェネレータ単位**でテスト（TestClient で無限ストリームを
  読まない）:
  - 追記 → poll_interval 以内に yield される（1 秒以内の受け入れ条件）
  - start オフセット指定 → 既存行の途中から再開して取りこぼしゼロ
  - 壊れ行・ファイル不在・後から出現
- エンドポイントは `max_idle_sec` 相当の仕組み or httpx の stream + 即時
  クローズで「200 / content-type / 先頭イベントの形式 / Last-Event-ID 再開」を検証
- runner のログ出力は FakeWriter 注入で「text/tool_use/result が書かれる・
  サニタイズされる・write 失敗でも run が成功する」を検証

## 受け入れ条件（Issue 由来）

- [ ] 実行中 Issue のログが 1 秒以内に SSE で届く（poll 0.5s + テストで担保）
- [ ] SSE 切断 → 再接続（Last-Event-ID）で取りこぼしがない（テストで検証）
- [ ] agent.jsonl 各 result レコードに usage（in/out トークン）
- [ ] 機密サニタイズ（EventLogger と同一パターンを共有モジュール化）
- [ ] /api/issues/{n}/logs のページング
- [ ] 既存テスト全通過（EventLogger の互換維持）・カバレッジ 80%+
