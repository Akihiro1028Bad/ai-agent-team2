"""FastAPI アプリケーション本体."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

APP_VERSION = "0.1.0"


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンスモデル."""

    status: str
    version: str


def create_app() -> FastAPI:
    """FastAPI アプリケーションインスタンスを生成するファクトリ関数.

    Returns:
        設定済みの FastAPI インスタンス。
    """
    app = FastAPI(
        title="AI Agent Orchestrator API",
        version=APP_VERSION,
    )

    # CORS ミドルウェア設定 (開発フェーズは全オリジン許可)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """ヘルスチェックエンドポイント."""
        return HealthResponse(status="ok", version=APP_VERSION)

    return app
