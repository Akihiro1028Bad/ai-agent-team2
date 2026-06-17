"""GET /api/knowledge と read_knowledge の単体テスト (#93)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.api.readers import read_knowledge
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.knowledge.episode_store import EpisodeStore, make_episode_id
from ai_agent_orchestrator.knowledge.models import Episode
from ai_agent_orchestrator.knowledge.pattern_extractor import extract_patterns
from ai_agent_orchestrator.knowledge.skill_manager import SkillManager


def _make_settings(workspace: Path) -> AppSettings:
    return AppSettings(
        repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
        workspace_dir=str(workspace),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def client(workspace: Path) -> Iterator[TestClient]:
    app = create_app(_make_settings(workspace))
    with TestClient(app) as c:
        yield c


def _episode(n: int, lesson: str, outcome: str = "success") -> Episode:
    created = f"2026-06-17T0{n}:00:00+00:00"
    return Episode(
        id=make_episode_id(n, "implement", created),
        issue=n,
        repo="o/r",
        phase="implement",
        outcome=outcome,
        summary=f"episode {n}",
        lesson=lesson,
        created_at=created,
    )


def test_knowledge_empty_returns_200(client: TestClient) -> None:
    """エピソード未蓄積でも 200 で空の集計を返す。"""
    r = client.get("/api/knowledge")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["episodes"] == 0
    assert body["episodes"] == []
    assert body["patterns"] == []
    assert body["skills"] == []


def test_knowledge_aggregates_episodes_and_patterns(workspace: Path) -> None:
    """同一 lesson が 3 回で promoted パターンになり、stats に反映される。"""
    store = EpisodeStore(workspace)
    for i in range(3):
        store.record(_episode(i + 1, "テストを先に書く"))
    store.record(_episode(4, "", outcome="failure"))  # lesson 空 → パターン対象外

    res = read_knowledge(workspace)
    assert res.stats.episodes == 4
    assert res.stats.success_rate == 0.75
    assert len(res.patterns) == 1
    assert res.patterns[0].occurrences == 3
    assert res.patterns[0].status == "promoted"
    # 新しい順
    assert res.episodes[0].issue == 4


def test_knowledge_exposes_persisted_skills(workspace: Path) -> None:
    """昇格済み Skill (skills.jsonl) がレスポンスに現れる。"""
    store = EpisodeStore(workspace)
    for i in range(3):
        store.record(_episode(i + 1, "入力連動にはデバウンス"))
    patterns = extract_patterns(store.load())
    SkillManager(workspace).promote(patterns, "2026-06-17T09:00:00+00:00")

    res = read_knowledge(workspace)
    assert res.stats.skills == 1
    assert len(res.skills) == 1
    assert res.skills[0].from_pattern == res.patterns[0].id


def test_knowledge_endpoint_returns_payload(client: TestClient, workspace: Path) -> None:
    """GET /api/knowledge が集計済みペイロードを返す。"""
    store = EpisodeStore(workspace)
    store.record(_episode(1, "教訓A"))

    r = client.get("/api/knowledge")
    assert r.status_code == 200
    body = r.json()
    assert body["stats"]["episodes"] == 1
    assert body["episodes"][0]["issue"] == 1
    assert body["episodes"][0]["created_at"]


# ──────────────────────────────────────
# PhaseExecutor の記録配線 (#93)
# ──────────────────────────────────────
def _make_executor(workspace: Path) -> object:
    from types import SimpleNamespace

    from ai_agent_orchestrator.phases.base import PhaseExecutor

    class _E(PhaseExecutor):
        async def build_prompt(self, request: object) -> str:  # type: ignore[override]
            return ""

        async def process_result(self, request: object, result: object) -> None:  # type: ignore[override]
            return None

    return _E(
        runner=None,  # type: ignore[arg-type]
        account_manager=None,
        notifier=None,  # type: ignore[arg-type]
        tracker=None,  # type: ignore[arg-type]
        workspace=SimpleNamespace(base_dir=workspace),  # type: ignore[arg-type]
        context_engine=None,  # type: ignore[arg-type]
        state_machine=None,  # type: ignore[arg-type]
        episode_store=EpisodeStore(workspace),
    )


def test_record_episode_persists_and_promotes(workspace: Path) -> None:
    """_record_episode がエピソードを保存し、繰り返しで Skill が昇格される。"""
    from types import SimpleNamespace

    executor = _make_executor(workspace)
    request = SimpleNamespace(issue_number=7, phase="implement", repo=SimpleNamespace(owner="o", repo="r"))

    for _ in range(3):
        executor._record_episode(request, outcome="failure", summary="失敗", lesson="同じ教訓")  # type: ignore[attr-defined]

    res = read_knowledge(workspace)
    assert res.stats.episodes == 3
    assert len(res.patterns) == 1
    # 3 回で promoted → Skill が永続化される
    assert res.stats.skills == 1


def test_record_episode_noop_without_store(workspace: Path) -> None:
    """episode_store 未注入なら記録しない (例外も出さない)。"""
    from types import SimpleNamespace

    from ai_agent_orchestrator.phases.base import PhaseExecutor

    class _E(PhaseExecutor):
        async def build_prompt(self, request: object) -> str:  # type: ignore[override]
            return ""

        async def process_result(self, request: object, result: object) -> None:  # type: ignore[override]
            return None

    executor = _E(
        runner=None,  # type: ignore[arg-type]
        account_manager=None,
        notifier=None,  # type: ignore[arg-type]
        tracker=None,  # type: ignore[arg-type]
        workspace=SimpleNamespace(base_dir=workspace),  # type: ignore[arg-type]
        context_engine=None,  # type: ignore[arg-type]
        state_machine=None,  # type: ignore[arg-type]
    )
    request = SimpleNamespace(issue_number=7, phase="implement", repo=SimpleNamespace(owner="o", repo="r"))
    executor._record_episode(request, outcome="success", summary="ok", lesson="x")
    assert read_knowledge(workspace).stats.episodes == 0
