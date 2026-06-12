# Issue #113 — /api/stream (SSE) の堅牢化

> #85 セキュリティレビュー LOW(L2/L3) のフォローアップ

`GET /api/stream`（events.jsonl + agent.jsonl の tail を SSE 配信）の DoS 面と
API 表面を堅牢化する。localhost 単一利用前提に対する多層防御。

## 対応 3 点

### 1. 接続数セマフォ（L2: DoS）
同時接続数に上限がない問題に対し、**1 Issue あたり N 接続 / 全体上限**を導入。
- `SseConnectionLimiter`（`stream.py`）: `try_acquire(issue)` / `release(issue)`。
  `asyncio.Lock` で global / per-issue カウンタを保護。
- 既定: `MAX_SSE_CONNECTIONS_TOTAL=50` / `MAX_SSE_CONNECTIONS_PER_ISSUE=5`。
- `create_app` で 1 インスタンス生成し `app.state.sse_limiter` に保持（テスト可能性）。
- 上限超過時 `get_stream` は **429**（`Too many concurrent stream connections`）を返す。
- 取得は stream 開始時、解放はジェネレータの `finally`（切断・正常終了の双方）。

### 2. seek ベース増分読み（L2: CPU）
毎 poll で `read_text()` + `splitlines()` の全ファイル読み（O(ファイルサイズ)）を
やめ、**保持バイトオフセットからの増分読み**に変更。
- `_TailState(path, start_line, byte_offset, primed)` を events/agent 各 1 つ保持。
- `_read_new_lines(state)`: `byte_offset` 以降のみ binary read → 計算量は追記バイト量に比例。
- 再開（`start_line` = Last-Event-ID 由来の物理行）は初回 1 度だけファイルを走査して
  バイト位置を確定（priming）。以降は増分。
- 末尾が改行で終端されない行は消費しない（torn read 防止、従来挙動を維持）。
- 縮退（切り詰め/ローテーション: `size < byte_offset`）時のみ先頭から読み直す。

### 3. `max_idle_sec` のエンドポイント露出除去（L3: API 表面）
テスト用ノブ `max_idle_sec` を **公開 Query から外す**。
- `tail_issue_streams` の `max_idle_sec` 引数は**維持**（テストはジェネレータ単体で使用）。
- `get_stream` は `max_idle_sec` を受け取らず、常に無限 tail（クライアント切断で終端）。
- 既存のエンドポイントテスト 2 件は「期待データ受信後にストリームを close」して終端する
  方式へ改修。

## 不変条件（回帰させない）
- `tail_issue_streams` のシグネチャ（`max_idle_sec` / `keepalive_interval` kwarg）。
- SSE id（`events:{e},agent:{a}` 物理行）と Last-Event-ID 再開。
- 壊れ行の生 yield + 物理行消費、空行スキップ（だが消費はカウント）、keepalive。

## テスト
- `SseConnectionLimiter`: per-issue / global 上限・解放のセマンティクス。
- `_TailState` 増分読み: state 再利用で追記分のみ返す・priming・torn read・縮退リセット。
- エンドポイント: 上限到達で 429 / 正常 200（close-on-read で終端）。

## 参照
- `src/ai_agent_orchestrator/api/stream.py` / `api/app.py`（get_stream）
- 将来の外部公開（Tailscale / Vercel）時は AuthMiddleware(#115 C2) と合わせて再評価。
