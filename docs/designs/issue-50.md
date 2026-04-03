# Issue #50 設計書 — FastAPIサーバー基盤構築

## 概要

`fastapi` + `uvicorn` を使ったWebサーバー基盤を構築する。
既存の Typer CLI に `web` サブコマンドを追加し、`uv run ai-agent web` でサーバーが起動、
`GET /api/health` が200を返すことを完了条件とする。

---

## ゴール

| # | 目標 |
|---|------|
| 1 | `pyproject.toml` に `fastapi`, `uvicorn[standard]` を依存関係として追加する |
| 2 | `src/ai_agent_orchestrator/web/` ディレクトリを新設し、FastAPIアプリ本体を実装する |
| 3 | `GET /api/health` ヘルスチェックエンドポイントを実装する |
| 4 | `commands/web.py` を新設し、`uv run ai-agent web --host --port` コマンドを追加する |
| 5 | `cli.py` に `web` サブコマンドを登録する |

---

## 変更ファイル

```
pyproject.toml                                   (更新)
src/ai_agent_orchestrator/web/__init__.py        (新規)
src/ai_agent_orchestrator/web/app.py             (新規)
src/ai_agent_orchestrator/web/routers/__init__.py (新規)
src/ai_agent_orchestrator/commands/web.py        (新規)
src/ai_agent_orchestrator/commands/__init__.py   (更新)
src/ai_agent_orchestrator/cli.py                 (更新)
tests/unit/test_web.py                           (新規)
```

合計: 8ファイル（新規6、更新3）

---

## 設計詳細

### 1. 依存関係追加（`pyproject.toml`）

`[project].dependencies` に以下を追加する。

```toml
"fastapi>=0.115",
"uvicorn[standard]>=0.34",
```

`uvicorn[standard]` を選択する理由は、`websockets` や `httptools` など高性能オプションを
一括で有効化できるため。

---

### 2. ディレクトリ構成

```
src/ai_agent_orchestrator/web/
├── __init__.py          # パッケージ公開 (create_app をエクスポート)
├── app.py               # FastAPIアプリ本体・CORS設定・ルーター登録
└── routers/
    └── __init__.py      # ルーターパッケージ（将来の拡張用）
```

#### 2-1. `web/app.py`

FastAPIインスタンスを生成するファクトリ関数 `create_app()` を定義する。
ファクトリ関数パターンを採用することで、テスト時に独立したアプリインスタンスを
生成できる（`TestClient` との組み合わせを容易にする）。

```
create_app() → FastAPI
  - title: "AI Agent Orchestrator API"
  - version: "0.1.0"
  - CORS ミドルウェアを追加（開発時は全オリジン許可、本番は設定値から読む）
  - /api/health ルートを登録
```

**CORS 設定方針**

| 設定項目 | 値 |
|---------|-----|
| `allow_origins` | `["*"]`（開発フェーズ。将来は設定から読む） |
| `allow_methods` | `["*"]` |
| `allow_headers` | `["*"]` |
| `allow_credentials` | `False` |

**ヘルスチェックエンドポイント**

```
GET /api/health
→ 200 OK
→ {"status": "ok", "version": "0.1.0"}
```

レスポンスモデルは `pydantic.BaseModel` を継承した `HealthResponse` として定義し、
型安全性を確保する。

```python
class HealthResponse(BaseModel):
    status: str      # 常に "ok"
    version: str     # アプリバージョン
```

#### 2-2. `web/routers/__init__.py`

現時点では空の `__init__.py`。
将来の Issue（WebSocket, タスク管理API等）でルーターを追加する際の受け皿として設置する。

---

### 3. `commands/web.py`（新規）

既存の `commands/run.py` と同じ設計パターンに従う。

```python
def web_command(
    host: str = typer.Option("0.0.0.0", "--host", "-H", help="バインドホスト"),
    port: int = typer.Option(8080, "--port", "-p", help="ポート番号"),
    reload: bool = typer.Option(False, "--reload", help="ホットリロード（開発用）"),
) -> None:
    """Web UIサーバーを起動する."""
```

実装方針:
- `uvicorn.run()` を呼び出してサーバーを起動する
- `app` 引数には `"ai_agent_orchestrator.web.app:create_app"` を渡す
  （`factory=True` オプションを有効化することでファクトリ関数として呼び出す）
- `--reload` オプションは開発時のホットリロード用。デフォルト `False`
- 起動前に Rich console で起動URLを表示する

**起動時の出力イメージ**

```
╭────────────────────────────────────────────╮
│   🌐  AI Agent Web Server                  │
│   URL: http://0.0.0.0:8080                 │
│   Health: http://0.0.0.0:8080/api/health   │
╰────────────────────────────────────────────╯
```

---

### 4. `commands/__init__.py`（更新）

`web_command` を既存エクスポートリストに追加する。

```python
from ai_agent_orchestrator.commands.web import web_command

__all__ = [
    ...,
    "web_command",
]
```

---

### 5. `cli.py`（更新）

```python
from ai_agent_orchestrator.commands import (
    ...,
    web_command,
)

app.command("web")(web_command)
```

登録後のコマンド一覧:

| コマンド | 説明 |
|---------|------|
| `setup` | リポジトリを登録する |
| `unregister` | リポジトリ登録を解除する |
| `start` | オーケストレーターを起動する |
| `stop` | オーケストレーターを停止する |
| `status` | 稼働状況を表示する |
| `health` | ヘルスチェックを実行する |
| `logs` | ログを表示する |
| **`web`** | **Web UIサーバーを起動する** ← 今回追加 |
| `account` | アカウント管理サブコマンド |

---

## テスト設計

### `tests/unit/test_web.py`

`fastapi.testclient.TestClient` を使った同期テスト。
pytest-asyncio は不要（TestClient は同期APIを提供する）。

| テストID | テスト内容 | 期待値 |
|---------|-----------|-------|
| `test_health_returns_200` | `GET /api/health` | ステータスコード 200 |
| `test_health_response_body` | レスポンスJSONの `status` フィールド | `"ok"` |
| `test_health_response_version` | レスポンスJSONの `version` フィールド | `"0.1.0"` |
| `test_cors_header_present` | `Origin` ヘッダー付きリクエストへのレスポンス | `Access-Control-Allow-Origin` ヘッダーあり |
| `test_unknown_route_returns_404` | `GET /api/unknown` | ステータスコード 404 |

テストフィクスチャ:

```python
@pytest.fixture
def client() -> TestClient:
    from ai_agent_orchestrator.web.app import create_app
    return TestClient(create_app())
```

---

## モジュール依存関係

```
cli.py
  └── commands/web.py
        └── web/app.py
              ├── fastapi.FastAPI
              ├── fastapi.middleware.cors.CORSMiddleware
              └── web/routers/__init__.py  (将来のルーター)
```

既存モジュールへの依存は最小限に抑え、`config/settings.py` への依存は
将来のCORS設定取得時まで持ち込まない。

---

## 非機能要件

| 項目 | 方針 |
|------|------|
| 型安全性 | `mypy --strict` に準拠。全関数に型アノテーション |
| コーディング規約 | `ruff check` / `ruff format` に準拠 |
| 非同期 | FastAPIは非同期エンドポイントを基本とする（`async def`） |
| ポート競合 | `--port` オプションで変更可能。競合時はuvicornがエラーを出す |

---

## 将来の拡張ポイント

- `web/routers/` 配下にルーターを追加していく（タスク一覧API、WebSocketなど）
- CORS `allow_origins` を `AppSettings` から読み込む
- `--workers` オプションで本番用マルチワーカー起動に対応

---

## 作業チェックリスト

- [ ] `pyproject.toml` に `fastapi>=0.115`, `uvicorn[standard]>=0.34` を追加
- [ ] `src/ai_agent_orchestrator/web/__init__.py` を作成
- [ ] `src/ai_agent_orchestrator/web/app.py` を作成（`create_app`, `HealthResponse`, `/api/health`）
- [ ] `src/ai_agent_orchestrator/web/routers/__init__.py` を作成
- [ ] `src/ai_agent_orchestrator/commands/web.py` を作成（`web_command`）
- [ ] `src/ai_agent_orchestrator/commands/__init__.py` に `web_command` を追加
- [ ] `src/ai_agent_orchestrator/cli.py` に `web` コマンドを登録
- [ ] `tests/unit/test_web.py` を作成（5テストケース）
- [ ] `uv run ai-agent web` でサーバーが起動することを確認
- [ ] `curl http://localhost:8080/api/health` が `{"status":"ok","version":"0.1.0"}` を返すことを確認
- [ ] `uv run pytest tests/unit/test_web.py` がすべてパスすることを確認
- [ ] `uv run mypy src/` がエラーなしで通ることを確認
- [ ] `uv run ruff check src/` がエラーなしで通ることを確認
