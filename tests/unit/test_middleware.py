"""AuthMiddleware (loopback ガード) の単体テスト (#115 Unit C2).

実ネットワーク経由の非 loopback 接続のみ 403 で拒否し、loopback / in-process
呼び出しは通過することを検証する。純関数 is_external_peer と、ミドルウェアを
組み込んだ最小アプリ (TestClient の client= で peer を差し替え) の双方で確認する。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.middleware import AuthMiddleware, is_external_peer


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", False),  # IPv4 loopback
        ("127.0.0.5", False),  # 127.0.0.0/8 全体が loopback
        ("::1", False),  # IPv6 loopback
        ("10.0.0.5", True),  # プライベート LAN (外部)
        ("203.0.113.7", True),  # グローバル (外部)
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback (dual-stack 由来) は通過
        ("::ffff:10.0.0.5", True),  # IPv4-mapped IPv6 LAN (外部)
        (None, False),  # peer 情報なし (in-process / Unix socket)
        ("", False),  # 空文字
        ("testclient", False),  # 数値 IP でない = in-process sentinel
    ],
)
def test_is_external_peer(host: str | None, expected: bool) -> None:
    assert is_external_peer(host) is expected


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.add_middleware(AuthMiddleware)

    @application.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    return application


def test_loopback_ipv4_allowed(app: FastAPI) -> None:
    with TestClient(app, client=("127.0.0.1", 12345)) as c:
        res = c.get("/ping")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_loopback_ipv6_allowed(app: FastAPI) -> None:
    with TestClient(app, client=("::1", 12345)) as c:
        res = c.get("/ping")
    assert res.status_code == 200


def test_in_process_default_client_allowed(app: FastAPI) -> None:
    # 既定の TestClient は client.host="testclient" (数値 IP でない) → 通過。
    with TestClient(app) as c:
        res = c.get("/ping")
    assert res.status_code == 200


def test_external_lan_peer_forbidden(app: FastAPI) -> None:
    with TestClient(app, client=("10.0.0.5", 12345)) as c:
        res = c.get("/ping")
    assert res.status_code == 403
    assert res.json()["detail"].startswith("Forbidden")


def test_external_global_peer_forbidden(app: FastAPI) -> None:
    with TestClient(app, client=("203.0.113.7", 12345)) as c:
        res = c.get("/ping")
    assert res.status_code == 403
