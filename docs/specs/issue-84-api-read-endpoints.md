# #84 実装仕様: FastAPI 基盤と読み取りエンドポイント

参照: docs/designs/web-ui-architecture.md §3.1, §7 G1/G2（feat/web-ui-prototype ブランチ）

## スコープ

API プロセス側のみ（orchestrator 本体は変更しない）。health は #97、SSE/agent.jsonl は #85。

## モジュール構成

```
src/ai_agent_orchestrator/api/
├── __init__.py      # create_app re-export
├── app.py           # create_app(settings) ファクトリ + ルート定義
├── schemas.py       # pydantic レスポンスモデル（web/lib/types.ts と整合）
├── readers.py       # state.json / events.jsonl の読み取り純関数
└── middleware.py    # AuthMiddleware (no-op、将来の差し込み口)
src/ai_agent_orchestrator/commands/api.py  # ai-agent api コマンド
```

## エンドポイント

| Method/Path | ソース | 備考 |
|---|---|---|
| GET /api/issues | `{workspace}/state.json` | 全 Issue の IssueSummary 一覧。updated_at 降順 |
| GET /api/issues/{n} | 同上 | `?repo=owner/repo` で曖昧性解消。複数一致+repo 未指定→400、不在→404 |
| GET /api/issues/{n}/events | `{workspace}/logs/issue-{n}/events.jsonl` | `?limit=`（既定 200、新しい順）。壊れた行はスキップ |
| GET /api/activity | 全 Issue の events.jsonl をマージ | ts 降順、`?limit=`（既定 100） |
| GET /api/costs | events.jsonl の `phase_completed` の `data.cost_usd` を集計 | 総額 + Issue 別 + フェーズ別 |
| GET /api/issues/{n}/diff | GitHubClient（新メソッド） | state の pr_number から PR files+patch。pr_number 無し→404 |

## 設計判断

1. **読み取りはファイル経由で疎結合**: orchestrator のプロセス状態に触れない。
   state.json のパースは `StatePersistence.load()` を再利用（read-only）。
2. **diff の GitHub 認証**: orchestrator と同一の `AccountManager`（CredentialResolver
   4段階解決: keyring → 環境変数 → token_command → gh auth token）を API プロセスでも
   そのまま使う。新しい秘密の保管場所・受け渡し経路は作らない。テストでは
   `app.state.github_client_factory` を差し替えて Fake を注入する。
3. **title は nullable**: IssueState にタイトルが無い。GitHub API を読み取り経路に
   持ち込まない（停止中応答の保証を優先）。UI 側のフォールバックは #86 で対応。
4. **status の導出**: Phase → RunStatus のマッピング関数を schemas に置く。
   done→done / blocked→blocked / suspended→suspended /
   clarify-wait・approve・review→waiting / その他→running
5. **listen は 127.0.0.1 固定**: `ai-agent api` コマンドで host をハードコード。
   `--port`（既定 8000）と `--config` のみオプション。
6. **AuthMiddleware**: BaseHTTPMiddleware 継承の素通し実装。将来 Bearer 認証を
   差し替えるための単一の差し込み口としてコメントを残す。

## レスポンスモデル（web/lib/types.ts との対応）

- `IssueSummaryResponse`: number, repo, title(null可), issue_type, phase, status,
  cost_usd, pr_number, design_pr_number, branch_head_sha, retry_count,
  created_at, updated_at
- `IssueDetailResponse`: IssueSummary + plan_json, session_id, impl_iteration
- `EventRecord`: ts, issue, phase, event, data(dict|None)
- `CostsResponse`: total_usd, issues: [{repo, issue_number, cost_usd, phases: {phase: usd}}]
- `DiffResponse`: pr_number, files: [{filename, status, additions, deletions, patch(null可)}]

cost_usd（Issue別）は events.jsonl 集計値を使用。

## GitHubClient 追加メソッド

```python
async def get_pull_request_files(self, owner: str, repo: str, pr_number: int)
    -> list[dict[str, Any]]
```
githubkit `rest.pulls.async_list_files`（per_page=100、ページング）。

## テスト（TDD・カバレッジ 80%+）

- tests/unit/test_api_readers.py … tmp_path に state.json / events.jsonl を作って検証
  （壊れ行スキップ・マージ順・コスト集計・空ワークスペース）
- tests/unit/test_api_endpoints.py … `fastapi.testclient.TestClient` で全 GET を検証
  （200 / 400 曖昧 / 404 不在 / costs / diff は Fake client 注入 / orchestrator 停止中
  相当 = ファイルが無くても 200 で空リスト）
- 既存 conftest の FakeGitHubClient を拡張 or ローカル Fake

## 受け入れ条件（Issue 由来）

- [ ] uvicorn 起動でオーケストレーター停止中でも全 GET が応答
- [ ] pytest 単体テスト（カバレッジ 80%）
- [ ] pyproject に fastapi / uvicorn 追加
- [ ] `ai-agent api` で起動（127.0.0.1 固定）
