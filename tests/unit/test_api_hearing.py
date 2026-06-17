"""ヒアリング (clarify) Q&A 構造化とエンドポイントの単体テスト (#139)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.api.hearing import build_hearing
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.phases.hearing import HEARING_QUESTION_MARKER


@dataclass
class _User:
    login: str = ""
    type: str = "User"


@dataclass
class _Comment:
    body: str = ""
    user: _User = field(default_factory=_User)
    created_at: str | None = None


def _q(body: str, login: str = "bot") -> _Comment:
    return _Comment(body=f"{body}\n\n{HEARING_QUESTION_MARKER}", user=_User(login, "Bot"))


def _a(body: str, login: str = "alice") -> _Comment:
    return _Comment(body=body, user=_User(login, "User"))


# ── classifier ──
def test_build_hearing_classifies_qa_in_order() -> None:
    comments: list[Any] = [
        _Comment(body="intake メモ", user=_User("bot", "Bot")),  # 質問前 = 除外
        _q("仕様を教えてください"),
        _a("こうしたいです"),
        _q("追加でこの点は？"),
    ]
    res = build_hearing(comments, "clarify-wait")
    assert res.state == "waiting"
    assert res.rounds == 2
    assert [(t.role, t.body) for t in res.turns] == [
        ("question", "仕様を教えてください"),
        ("answer", "こうしたいです"),
        ("question", "追加でこの点は？"),
    ]


def test_build_hearing_none_when_no_questions() -> None:
    res = build_hearing([_Comment(body="ただのコメント", user=_User("x", "User"))], "plan")
    assert res.state == "none"
    assert res.turns == []


def test_build_hearing_state_in_progress_for_clarify() -> None:
    assert build_hearing([_q("q")], "clarify").state == "in_progress"


def test_build_hearing_done_after_clarify() -> None:
    assert build_hearing([_q("q"), _a("a")], "plan").state == "done"


def test_build_hearing_legacy_without_marker() -> None:
    """マーカー導入前の Bot 質問（フッター文言）も拾う."""
    legacy = _Comment(body="質問です。このコメントで回答してください", user=_User("bot", "Bot"))
    res = build_hearing([legacy, _a("回答")], "clarify-wait")
    assert res.rounds == 1
    assert res.turns[0].role == "question"


# ── endpoint ──
class _FakeClient:
    def __init__(self, comments: list[Any]) -> None:
        self._comments = comments

    async def list_comments(self, repo: object, issue_number: int) -> list[Any]:
        return self._comments


@pytest.fixture
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "state.json").write_text(
        '{"o/r:5": {"issue_number": 5, "phase": "clarify-wait", "repo": "o/r",'
        ' "issue_type": "feature-m", "created_at": "2026-01-01T00:00:00+00:00",'
        ' "updated_at": "2026-01-01T00:00:00+00:00"}}',
        encoding="utf-8",
    )
    return ws


@pytest.fixture
def client(workspace) -> Iterator[TestClient]:
    settings = AppSettings(
        workspace_dir=str(workspace),
        repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
    )
    app = create_app(settings)

    async def _factory(owner: str, name: str) -> _FakeClient:
        return _FakeClient([_q("仕様は？"), _a("これです")])

    app.state.github_client_factory = _factory
    with TestClient(app) as c:
        yield c


def test_hearing_endpoint_returns_qa(client: TestClient) -> None:
    r = client.get("/api/issues/5/hearing")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "waiting"
    assert body["rounds"] == 1
    assert body["turns"][0]["role"] == "question"
    assert body["turns"][1]["role"] == "answer"


def test_hearing_endpoint_unknown_issue_404(client: TestClient) -> None:
    assert client.get("/api/issues/999/hearing").status_code == 404
