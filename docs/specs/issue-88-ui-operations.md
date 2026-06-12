# #88 実装仕様: Web UI 操作系の実接続（pause/abort/rewind/queue/Issue投入）

参照: docs/designs/web-ui-architecture.md §3.3 ／ 基盤: #87（ControlBus）+ #96（拡張コマンド + queue.json）

## スコープ（#88）

UI の操作ボタン（Issue 操作パネル・実行キュー・Issue 投入・⌘K）を ControlBus に接続する。

- **POST /api/control の全語彙対応**（#96 で消費側は完成済み。発行側の API がまだ
  pause/resume/abort/shutdown のみ → 本 Issue の前提ブロッカー）
- 承認待ち一覧の表示（state.json + events から導出）
- ヒアリング回答の送信（POST /api/issues/{n}/reply → GitHub Issue コメント投稿）
- フロント操作配線（pending → applied の状態表示・エラー表示）

承認/差し戻しの書き込みは **#89 の POST /api/issues/{n}/review に一本化**（本 Issue では扱わない）。

## 設計判断

### 1. POST /api/control の語彙拡張（Unit A）
`ControlRequest` を ControlBus の 11 action 全てに拡張し、`parse_operational_line`
と**対称の per-action 検証**を pydantic で行う（API で 422 を返し、orchestrator 側の
読み飛ばしによるサイレント無視を防ぐ）。

| 分類 | action | 必須フィールド |
|---|---|---|
| global | shutdown / poll_now / worktree_gc | なし（issue 不要） |
| issue-scoped 単純 | pause / resume / abort / enqueue_issue / retry_with_analysis | issue（正整数） |
| set_priority | set_priority | issue + phase（非空）+ priority（int） |
| rewind | rewind | issue + target（resume 可能な Phase 値） |
| reorder | reorder | order（非空リスト、各要素 {issue, phase}） |

- rewind の **target 妥当性は control_bus.py の共有定数 `REWIND_TARGETS`** で検証
  （orchestrator `_REWIND_TARGETS` を control_bus へ移し、API/orchestrator 両方が参照。
  語彙の所有権を control_bus に一本化し drift を防ぐ）
- control.jsonl への追記行は action に応じて必要フィールドのみ含める
  （`parse_operational_line` が読める形と一致させる）
- actor の権限検証は従来どおり orchestrator 側（API は形式検証と追記のみ）

### 2. 承認待ち一覧（Unit B）
- `GET /api/approvals`: state.json から `phase == "approve"`（および REVIEW で人間待ち）の
  Issue を抽出して返す。読み取りは既存 readers パターン（常に 200・不在は空）
- 表示に必要な情報: repo / issue_number / phase / 待ち開始時刻（updated_at）

### 3. ヒアリング回答送信（Unit B）
- `POST /api/issues/{n}/reply`: body のテキストを GitHubClient で Issue コメントとして投稿
- **control.jsonl は経由しない**（既存の「コメント → poller 検知」フローに乗せる）
- bot マーカーは付けない（人間の回答として検知されるのが目的）
- GitHub 障害は 502（detail に内部例外文字列を含めない）

### 4. フロント操作配線（Unit C）
- IssueControls（pause/resume/abort/rewind/retry）・queue 画面（set_priority/reorder）・
  AddIssueButton（enqueue_issue）・CommandPalette（poll_now/worktree_gc 等）を
  `POST /api/control` に接続
- 受理 → 消費の状態表示: 202 受理直後は "pending"、以後のポーリングで状態反映を確認
  （control.jsonl 消費は ~2s 周期。楽観表示 + 次回ポーリングで実状態に収束）
- 失敗時: ApiError をトースト/インライン表示（既存 ConnectionBanner パターン踏襲)

## 実装ユニット

- **Unit A**: POST /api/control 全語彙対応（schema 拡張 + per-action 検証 + 追記形）
- **Unit B**: GET /api/approvals + POST /api/issues/{n}/reply
- **Unit C**: フロント操作配線（IssueControls / queue / AddIssue / CommandPalette / 承認待ち画面）

## テスト（TDD・80%+）
- `test_api_endpoints.py`: 11 action の受理（202 + control.jsonl 行形）/ 必須欠落・型不正の 422 /
  rewind target 不正の 422 / reorder の order 形
- `test_control_bus.py`: REWIND_TARGETS 移設後も既存パースが不変
- Unit B: approvals 導出（approve 相のみ）/ reply 投稿（FakeGitHub）/ GitHub 障害 502
- Unit C: 既存 vitest（純関数）+ 手動ブラウザ確認（フィクスチャ駆動・レベル3）

## 受け入れ条件（Issue 由来）
- [ ] UI から一時停止 → 再開 → 中止の一連が実 Issue で動作する
- [ ] 承認待ち一覧が実データで表示される
- [ ] ヒアリング回答が UI から送信でき、既存検知フローに乗る

## 非スコープ
- 承認/差し戻しの書き込み API → #89
- 認証 → #115 ／ SSE・ポーリング最適化 → #118 ／ フロントテスト基盤 → #120
