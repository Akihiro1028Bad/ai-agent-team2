"""認証ミドルウェア (将来の Bearer 認証の差し込み口).

現状は no-op (素通し)。Web UI と orchestrator は同一ホスト (127.0.0.1) 上で動作し、
listen を localhost に固定する前提のため認証は行わない。将来 Bearer トークン認証等を
導入する際は本ミドルウェアの dispatch を差し替える単一の差し込み口とする。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


class AuthMiddleware(BaseHTTPMiddleware):
    """認証ミドルウェア (no-op)。

    将来 Bearer 認証を差し込む際はここで Authorization ヘッダを検証し、
    不正時に 401 を返すよう実装を差し替える。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """リクエストを素通しする (将来の認証フック)。

        Args:
            request: 受信リクエスト。
            call_next: 後続ハンドラ。

        Returns:
            後続ハンドラのレスポンス。
        """
        # TODO(#auth): ここで Authorization ヘッダを検証し、不正時 401 を返す。
        return await call_next(request)
