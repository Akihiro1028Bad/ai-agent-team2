# Web UI 本実装 設計書

最終更新: 2026-06-10
ステータス: 合意済みドラフト（実装前）

## 1. 決定事項（壁打ち結果）

| 論点 | 決定 | 理由 |
|---|---|---|
| 稼働ホスト | 自宅 Windows デスクトップ + **WSL2 (Ubuntu)** | 既存コードが Unix 前提（worktree / シェル / keyring）。SDK も Linux が安定 |
| UI / API の配置 | **同一マシンに同居**（localhost） | 構成が最小。CORS・認証の実装を初期フェーズで丸ごと省略できる |
| 外部アクセス | **リモートデスクトップで PC ごと操作** | ネットワーク公開ゼロ＝攻撃面ゼロ。UI は localhost のみ listen |
| 利用者 | 当面は本人のみ | ユーザー概念・権限管理は初期実装しない（操作ログだけ残す） |
| 将来の昇格パス | ① Tailscale（端末直結）→ ② Vercel UI + Cloudflare Tunnel + トークン認証 | API に認証ミドルウェアの差し込み口だけ用意しておく |

## 2. 全体構成

```
[自宅 Windows デスクトップ]
 │
 ├─ リモートデスクトップ (外部からの唯一の入口。ネットワーク公開なし)
 │
 └─ WSL2 (Ubuntu)
     ├─ Next.js  (web/)            … localhost:3000
     ├─ FastAPI  (api/)            … localhost:8000  ← 新設
     │    ├─ REST: 状態・履歴・設定の読み書き
     │    ├─ SSE : イベント/ログのリアルタイム配信
     │    └─ ControlBus: オーケストレーターへの介入
     └─ オーケストレーター (既存 Python)
          ├─ GitHubPoller → EventRouter → PhaseExecutor
          ├─ state/  state.json / events.jsonl / control.jsonl
          ├─ git worktree (並行 Issue)
          └─ Claude Agent SDK
```

- UI → API は `localhost:8000` 固定。**0.0.0.0 では listen しない**
- プロセスは 3 つ: `next start` / `uvicorn` / `ai-agent run`。systemd (WSL2 内) で常駐管理

## 3. API とオーケストレーターの結合方式

### 3.1 読み取り（Read Path）— ファイル経由で疎結合

オーケストレーターの内部状態には直接触らず、**既存の永続化ファイルを API が読む**。
プロセス間で共有メモリ・DB を持たないため、片方が落ちてももう片方は動く。

パス・形式はコード検証済み（2026-06-10、§8 参照）。

| データ | ソース（実際のパス） | 提供 API |
|---|---|---|
| Issue 状態・フェーズ | `~/.ai-agent-workspaces/state.json` (state_persistence.py:418) | `GET /api/issues`, `GET /api/issues/{n}` |
| イベント履歴 | `{workspace}/logs/issue-{n}/events.jsonl` ※**Issue 単位に分かれている**。横断ビューは API 側でマージ | `GET /api/issues/{n}/events`, `GET /api/activity` |
| 実行ログ | `{workspace}/logs/issue-{n}/agent.jsonl` ← **新設**。claude_runner は `async for msg in query()` で逐次受信済み（claude_runner.py:263）なので、ここにフックして追記する | `GET /api/issues/{n}/logs` + SSE |
| コスト | `phase_completed` イベントの `data.cost_usd`（orchestrator.py:839 で記録済み）を集計 | `GET /api/costs` |
| ナレッジ | knowledge/ は**現状スタブ**（TODO のみ）。UI のナレッジ画面は episode_store 実装後まで「準備中」表示 | `GET /api/knowledge` |
| ヘルス | poller 統計 + rate limit + worktree 数（オーケストレーターが `{workspace}/health.json` に定期書き出し ← **新設**） | `GET /api/health` |
| 設定 | `config.yaml`。**フェーズ別モデルは現状 claude_runner.py の PHASE_CONFIG にハードコード**（全フェーズ sonnet）→ YAML スキーマ追加が必要。**config.yaml は機密（Slack Webhook 等）を含むため、GET はマスク必須・PUT は非機密設定のみ受付**（#90 参照） | `GET/PUT /api/config` |

### 3.2 リアルタイム（SSE）

- `GET /api/stream` … events.jsonl / logs を tail -f して Server-Sent Events で配信
- WebSocket は使わない（単方向で足りる・実装と運用が軽い）
- UI 側は EventSource で購読。切断時は自動再接続（SSE 標準機能）

### 3.3 操作（Write Path）— control.jsonl によるコマンドキュー

実行中の asyncio タスクに API から直接触るのは危険なので、**ファイルベースのコマンドキュー**を挟む。

```
UI → POST /api/control → state/control.jsonl に追記
                              ↓ (オーケストレーターのメインループが毎 tick 消費)
                         ControlBus が解釈して実行
```

| コマンド | 動作 |
|---|---|
| `pause` / `resume` | Issue 単位。現在のターン完了後に停止 / 再開 |
| `abort` | worktree・ブランチを削除し ai-agent:aborted ラベル付与 |
| `rewind` | 指定フェーズへ巻き戻し（成果物は保持、状態のみ変更） |
| `set_priority` / `reorder` | TaskQueue の優先度変更 |
| `enqueue_issue` | URL 指定で監視対象に追加（ラベル付与） |
| `shutdown` | graceful 停止の予告（現在の Issue 完了後に自プロセス終了） |
| `retry_with_analysis` | エラー詳細の分析をプロンプトに含めて再実行 |

採用理由: ① プロセス分離を保てる ② コマンド自体が監査ログになる ③ オーケストレーター停止中でも受け付けて起動時に消費できる。

**例外 — 起動/停止だけは control.jsonl を使えない**（2回目レビューで判明）:
停止中のオーケストレーターはキューを消費できないため、起動は API プロセスが systemd を直接操作する。

- `POST /api/orchestrator/start` → `systemctl --user start ai-agent-orchestrator`
- `POST /api/orchestrator/stop` → ① control.jsonl に `shutdown` を積む（graceful）→ ② タイムアウト後に `systemctl --user stop`

### 3.4 承認・インラインレビュー

- 設計レビューの成果物（アーキ説明・Mermaid・テスト・計画・プロトタイプ・エビデンス）は
  PLAN フェーズが `state/artifacts/issue-{n}/design.json` に構造化して出力 ← **新設**
- UI の承認/差し戻し/質問は `POST /api/issues/{n}/review` → control.jsonl 経由でパイプラインへ
  - 指摘あり → PLAN へ差し戻し（指摘全文をプロンプトに含める）
  - 質問のみ → エージェントが回答コメントを生成 → 再レビュー待ち
  - 0件 → 承認 → IMPLEMENT へ
- GitHub の PR approve / LGTM コメントによる承認も**並存**させる（どちらでも進む）

### 3.5 エビデンス

- IMPLEMENT 完了時に Playwright でスクショ（desktop/mobile）+ 操作録画（webm）を取得し
  `state/artifacts/issue-{n}/evidence/` に保存
- `GET /api/issues/{n}/evidence` で配信（静的ファイルサーブ）
- UI 影響のない Issue（plan_depth=light 等）はテスト実行ログのみ

## 4. 認証（将来の差し込み口）

- フェーズ1: なし（localhost のみ・リモートデスクトップ経由）
- FastAPI には `AuthMiddleware`(no-op) を最初から入れておき、昇格時に実装を差し替えるだけにする
  - Tailscale 昇格時: listen を tailscale0 インターフェースに拡張（認証は Tailscale 任せ）
  - Vercel 昇格時: Bearer トークン + CORS 設定を有効化

## 5. 常駐・運用（WSL2）

| 項目 | 方式 |
|---|---|
| WSL2 自動起動 | Windows タスクスケジューラ: ログオン時に `wsl -d Ubuntu` を起動 |
| プロセス常駐 | WSL2 内 systemd で 3 unit（next / api / orchestrator）。Restart=always |
| スリープ抑止 | Windows 電源設定でスリープ無効（モニタ電源のみ切る） |
| 再起動復帰 | state.json から自動レジューム（既存機能）。control.jsonl の未消費分も起動時に処理 |
| ログローテーション | events.jsonl / logs を 30 日で世代管理（logrotate） |
| 暴走対策 | 日次コスト上限を config.yaml に追加。超過時は orchestrator_stop を自動発行し Slack 通知 |

## 6. 実装フェーズ計画

| # | 内容 | 見積 | 備考 |
|---|---|---|---|
| 0 | 統一パイプライン U1〜U5（前提） | 3〜5日 | docs/designs/pipeline-redesign-proposal.md |
| 1 | FastAPI 新設 + 読み取り API + SSE + UI 実データ接続 | 2〜3日 | モック (web/lib/*.ts) を API クライアントに差し替え |
| 2 | ControlBus + 操作系（pause/abort/rewind/queue/投入） | 2〜3日 | 一番設計が重い。本書 3.3 |
| 3 | 承認・インラインレビュー・差し戻しの結合 | 2〜3日 | U4 完了が前提 |
| 4 | 設定書き込み（モデル/Skill）+ コスト/ナレッジ/ヘルス実データ | 2日 | claude_runner にフェーズ別モデル注入 |
| 5 | エビデンス自動生成（Playwright スクショ・録画） | 1〜2日 | |
| 6 | WSL2 デプロイ・systemd・運用整備 | 1日 | セットアップスクリプト化 |

合計: フルタイム換算 13〜19 日。1→4 を先行すれば「見える化」だけは 3〜4 日で稼働可能。

## 7. コード検証で判明したギャップ（2026-06-10 実施）

設計書の前提を実コードと突き合わせた結果。**実装フェーズ見積りに織り込み済みの追加作業一覧**。

| # | ギャップ | 影響フェーズ | 対応 |
|---|---|---|---|
| G1 | FastAPI / uvicorn が依存に存在しない（CLI のみ） | 1 | pyproject.toml に追加。`src/ai_agent_orchestrator/api/` を新設 |
| G2 | events.jsonl は Issue 単位に分散。横断アクティビティは存在しない | 1 | API 側で全 Issue の events.jsonl をマージ（mtime 順） |
| G3 | 実行ログのファイル出力が未実装（SDK メッセージはストリーム受信済み） | 1 | claude_runner のメッセージループに logger フックを追加 |
| G4 | **pause が未実装**（cancel_task のみ存在 task_queue.py:352） | 2 | ターン境界チェック方式で新規実装。設計書 3.3 の通り control.jsonl 消費時に判定 |
| G5 | キュー投入済みタスクの優先度変更が未実装 | 2 | PriorityQueue は再構築方式（取り出して積み直す）で対応 |
| G6 | フェーズ別モデル設定が YAML 非対応（PHASE_CONFIG ハードコード・全フェーズ sonnet） | 4 | AppSettings に phase_models スキーマ追加 → PHASE_CONFIG を上書き |
| G7 | thinking（拡張思考）パラメータが claude_runner で未対応 | 4 | ClaudeAgentOptions への受け渡しを追加 |
| G8 | knowledge/ 3 モジュールが全てスタブ（保存先も未定） | 4 | ナレッジ画面は「準備中」で出し、episode_store 実装後に接続（別タスク） |
| G9 | UI は 9 フェーズ統一パイプライン前提、バックエンドは旧 18 フェーズのまま | 全部 | **フェーズ 0（U1〜U5）が前提**であることを再確認。先行必須 |
| G10 | 設計レビュー成果物（design.json）・エビデンスの構造化出力が存在しない | 3, 5 | PLAN / IMPLEMENT フェーズの出力仕様として新設 |

## 8. リスク

- **WSL2 のネットワーク/スリープ挙動**: Windows Update 後に WSL が落ちる事例あり → systemd Restart + 起動時タスクで自衛。ヘルスモニタの Slack 通知で検知
- **介入コマンドと実行中タスクの競合**: pause/abort はターン境界でのみ消費する設計で回避（強制 kill はしない）
- **ファイル tail の取りこぼし**: SSE 再接続時は Last-Event-ID で events.jsonl のオフセットから再送
- **モック → 実データ移行時の型ずれ**: web/lib/types.ts を API のレスポンススキーマ（pydantic → OpenAPI → 型生成）と一致させる

## 9. レビュー由来の追従課題（#118 / #86・PR #117）

PR #117 の @claude レビューで挙がった、M1「見える化」では非発火/軽微だが**本実装フェーズで取りこぼしたくない**課題。
いずれも現状のプロトタイプ（静的モック・Server Components）には**該当コードが存在せず**、Phase 1（モック → API クライアント差し替え）で実装する箇所への要件として記録する。

| # | 課題 | 現状 | 対応フェーズ | 対応方針 |
|---|---|---|---|---|
| F1 | **マルチリポ時の Issue 番号衝突**（中） | フロント `lib/api.ts` は未実装。**バックエンド `app.py` は既に対応済み**: `GET /api/issues/{n}`・`GET /api/issues/{n}/diff` が `repo: str \| None = Query()` を受け、`_resolve_issue` が複数リポジトリで同一番号が一致かつ `repo` 未指定なら 400 を返す（`detail` に `Specify ?repo=owner/repo`） | 1 | `/api/issues` が返す `repo`（`IssueSummary.repo`）を一覧→詳細の導線に乗せ、`getIssue(n, repo)`/`getDiff(n, repo)` から `?repo=owner/repo` を付与。番号衝突に備える |
| F2 | **LogViewer が常に SSE 接続**（低） | `useLogStream`/`EventSource` は未実装。プロトタイプの `LogViewer` は既に `live={status === "running"}` で再生制御済み（components/LogViewer.tsx）。本実装の SSE 購読は status を見ずに張る懸念 | 1 | `useLogStream` は実行中（`running` 等の active 状態）のときのみ `EventSource` を張る。`done`/`suspended` の Issue ではアイドル SSE+keepalive を保持しない |
| F3 | **ポーリングの重複**（低） | プロトタイプの `Shell`/`NotificationBell` は静的 import で `setInterval` 無し（重複は本実装で初めて発生）。本実装では `Shell`(health) + `NotificationBell`(activity) + 各ページ poller が独立し、ダッシュボードで activity が二重取得 | 1 | SWR 的な dedup / 共有キャッシュ層を導入、または activity 購読を 1 箇所に集約して配布。§3.2 の SSE と役割分担を明確化（活動は SSE、ヘルスは軽量ポーリング等） |
| F4 | **通知既読の非対称**（低） | プロトタイプの `NotificationBell` は in-memory の `markAll`（現在分で置換）のみで、`markOne`/localStorage 永続化は未実装 | 1 | 既読 ID の保持方針を統一（**上限付き LRU** 等）。`markOne`（累積）と `markAll`（置換）で localStorage の増減挙動が読みづらくならないよう、単一の保持戦略に揃える |

> 補足: F1 はバックエンド側が既に `?repo=` を実装済みのため、本実装ではフロントの導線整備のみで閉じる。F2〜F4 は Phase 1 の UI 実データ接続時に上記方針で実装する。
