"""認証・アクセス制御ミドルウェア (#115 Unit C2).

読み取り/書き込み API は **localhost 同居・単一ユーザー前提** で設計されている
(CLAUDE.md 設計判断・docs/designs/web-ui-architecture.md §2)。サーバーの listen は
``ai-agent api`` が 127.0.0.1 に固定するが、本ミドルウェアはその前提に対する
**多層防御 (defense-in-depth)** として、実ネットワーク経由の非 loopback 接続を 403 で
拒否する。これにより万一 API が外部公開された場合 (bind 変更 / リバースプロキシ誤設定 /
ポートフォワード) でも、health.json の詳細や write/control 系 (pause/abort/shutdown) を
外部から直接叩けない。read/write/control を区別せず全エンドポイントへ一律適用する。

設計上の判断 (#115 項目1):
  - 起動バインドは 127.0.0.1 固定済みのため「localhost バインド強制」(対応案 A) を採用。
  - 公開/認証プロファイル分離や Bearer トークン (対応案 B) は単一ユーザー localhost
    ツールには運用過剰のため非採用。将来多人数化する場合に本ミドルウェアへ差し込む。

ガードの境界:
  - 同一ホスト上のリバースプロキシ / SSH ポートフォワードは peer が 127.0.0.1 と
    なるため通過する (= 意図的公開はプロキシ側が認証責任を負う)。
  - ``X-Forwarded-For`` 等の転送ヘッダは信用しない。TCP peer (ソケットの実 peername)
    のみで判定する。本番 uvicorn は peer を必ず数値 IP に設定する。
"""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger(__name__)

_FORBIDDEN_DETAIL = "Forbidden: this API only accepts loopback (localhost) connections."


def is_external_peer(host: str | None) -> bool:
    """実ネットワーク経由の非 loopback peer か (= 拒否対象) を判定する.

    本番 uvicorn は TCP peer を必ず数値 IP 文字列に設定する。したがって数値 IP として
    解釈でき、かつ loopback でないものだけが「外部からの実ネットワーク接続」であり拒否
    対象となる。以下はいずれもネットワークを経由しておらず信頼する (= 非拒否):

      - ``host`` が None / 空 (ASGI in-process 呼び出し、Unix ソケット等で peer 情報なし)。
      - ``host`` が数値 IP として解釈できない (TestClient の in-process sentinel 等。
        実ソケット peer は常に数値 IP のため、この分岐は実ネットワークでは発生しない)。

    Args:
        host: ``request.client.host`` の値 (TCP peer のホスト文字列)、または None。

    Returns:
        外部 (非 loopback) からの実ネットワーク接続なら True。
    """
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 数値 IP でない → 実ネットワーク peer ではない (in-process 呼び出し)。
        return False
    # 注: 0.0.0.0 は is_loopback=False のため外部扱いだが、127.0.0.1 バインドの本番では
    # peer に現れない (バインドアドレスであって peer アドレスではない)。
    return not ip.is_loopback


class AuthMiddleware(BaseHTTPMiddleware):
    """非 loopback 接続を拒否するアクセス制御ミドルウェア (#115 Unit C2).

    将来 Bearer 認証等を導入する際も、本ミドルウェアの dispatch を単一の差し込み口と
    する。現状は localhost 前提に対する多層防御として loopback ガードのみを行う。
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """非 loopback の実ネットワーク接続を 403 で拒否し、それ以外は素通しする.

        Args:
            request: 受信リクエスト。
            call_next: 後続ハンドラ。

        Returns:
            loopback/in-process なら後続ハンドラのレスポンス、非 loopback なら 403。
        """
        host = request.client.host if request.client is not None else None
        if is_external_peer(host):
            logger.warning("非 loopback 接続を拒否しました: peer=%s path=%s", host, request.url.path)
            return JSONResponse(status_code=403, content={"detail": _FORBIDDEN_DETAIL})
        return await call_next(request)
