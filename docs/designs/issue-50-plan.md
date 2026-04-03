# Issue #50 実装計画 — FastAPIサーバー基盤構築

## 概要

`fastapi` + `uvicorn` を使ったWebサーバー基盤を構築する。
既存の Typer CLI に `web` サブコマンドを追加し、`GET /api/health` が200を返すことを完了条件とする。

## 変更ファイル一覧

| ファイル | 種別 |
|---------|------|
| `pyproject.toml` | 更新 |
| `src/ai_agent_orchestrator/web/__init__.py` | 新規 |
| `src/ai_agent_orchestrator/web/app.py` | 新規 |
| `src/ai_agent_orchestrator/web/routers/__init__.py` | 新規 |
| `src/ai_agent_orchestrator/commands/web.py` | 新規 |
| `src/ai_agent_orchestrator/commands/__init__.py` | 更新 |
| `src/ai_agent_orchestrator/cli.py` | 更新 |
| `tests/unit/test_web.py` | 新規 |

## サブタスク

### subtask-1: 依存関係追加とFastAPIアプリ本体実装
- files: [`pyproject.toml`, `src/ai_agent_orchestrator/web/__init__.py`, `src/ai_agent_orchestrator/web/app.py`, `src/ai_agent_orchestrator/web/routers/__init__.py`]
- depends_on: []
- description: |
    `pyproject.toml` の `[project].dependencies` に `fastapi>=0.115` と `uvicorn[standard]>=0.34` を追加する。
    `src/ai_agent_orchestrator/web/` ディレクトリを新設し、以下を実装する。
    - `web/routers/__init__.py`: 将来のルーター追加用の空パッケージ
    - `web/app.py`: ファクトリ関数 `create_app()` を定義。CORS ミドルウェア（全オリジン許可）を設定し、`GET /api/health` エンドポイントを登録する。レスポンスは `HealthResponse(status="ok", version="0.1.0")` を返す pydantic モデルとして定義。
    - `web/__init__.py`: `create_app` をパッケージ公開エクスポートする。

### subtask-2: webコマンドとCLI登録
- files: [`src/ai_agent_orchestrator/commands/web.py`, `src/ai_agent_orchestrator/commands/__init__.py`, `src/ai_agent_orchestrator/cli.py`]
- depends_on: [1]
- description: |
    `commands/web.py` を新設し、`web_command` 関数を実装する。
    - `--host`（デフォルト `0.0.0.0`）、`--port`（デフォルト `8080`）、`--reload`（デフォルト `False`）オプションを Typer で定義する。
    - 起動前に Rich console でサーバーURL・ヘルスチェックURLを表示する。
    - `uvicorn.run()` を `app="ai_agent_orchestrator.web.app:create_app"`, `factory=True` で呼び出す。
    `commands/__init__.py` に `web_command` のインポートと `__all__` への追加を行う。
    `cli.py` に `web_command` インポートを追加し、`app.command("web")(web_command)` でコマンド登録する。

### subtask-3: テスト実装
- files: [`tests/unit/test_web.py`]
- depends_on: [1]
- description: |
    `fastapi.testclient.TestClient` を使った同期テストを実装する。
    以下の5テストケースを含める。
    - `test_health_returns_200`: `GET /api/health` がステータスコード 200 を返すこと
    - `test_health_response_body`: レスポンス JSON の `status` フィールドが `"ok"` であること
    - `test_health_response_version`: レスポンス JSON の `version` フィールドが `"0.1.0"` であること
    - `test_cors_header_present`: `Origin` ヘッダー付きリクエストに対して `Access-Control-Allow-Origin` ヘッダーが返ること
    - `test_unknown_route_returns_404`: `GET /api/unknown` がステータスコード 404 を返すこと
    フィクスチャ `client` は `create_app()` から `TestClient` を生成する。
