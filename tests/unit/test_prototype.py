"""UI プロトタイプ (#145) の収集・読取・配信エンドポイントの単体テスト."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_agent_orchestrator.api.app import create_app
from ai_agent_orchestrator.api.readers import read_prototypes
from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig
from ai_agent_orchestrator.prototype.collector import collect_prototype
from ai_agent_orchestrator.prototype.paths import prototype_dir, worktree_prototype_file


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


def _write_worktree_prototype(worktree: Path, issue_number: int, html: str) -> None:
    target = worktree_prototype_file(worktree, issue_number)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


# ──────────────────────────────────────
# collector
# ──────────────────────────────────────
def test_collect_prototype_copies_and_writes_manifest(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<!doctype html><h1>proto</h1>")

    assert collect_prototype(workspace, 145, worktree) is True

    pdir = prototype_dir(workspace, 145)
    assert (pdir / "index.html").read_text(encoding="utf-8") == "<!doctype html><h1>proto</h1>"
    manifest = json.loads((pdir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"] == [
        {"id": "prototype", "title": "UI プロトタイプ", "description": "", "file": "index.html"}
    ]


def test_collect_prototype_absent_writes_empty_manifest(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()

    assert collect_prototype(workspace, 145, worktree) is False

    manifest = json.loads((prototype_dir(workspace, 145) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["items"] == []
    assert manifest["notes"]  # 未生成の note が入る


def test_collect_prototype_too_large_is_skipped(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "x" * (2 * 1024 * 1024 + 1))

    assert collect_prototype(workspace, 145, worktree) is False
    assert not (prototype_dir(workspace, 145) / "index.html").exists()


def test_collect_prototype_iteration_increments(workspace: Path, tmp_path: Path) -> None:
    """#145 Phase2: 収集成功のたびに manifest の iteration が増える."""
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>v1</h1>")
    collect_prototype(workspace, 145, worktree)
    manifest1 = json.loads((prototype_dir(workspace, 145) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest1["iteration"] == 1

    # 再生成 (修正依頼後の PLAN 再実行相当)
    _write_worktree_prototype(worktree, 145, "<h1>v2</h1>")
    collect_prototype(workspace, 145, worktree)
    manifest2 = json.loads((prototype_dir(workspace, 145) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest2["iteration"] == 2


def test_collect_prototype_iteration_kept_on_failure(workspace: Path, tmp_path: Path) -> None:
    """#145 Phase2: 収集失敗時は iteration を据え置く (前回値を維持)."""
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>v1</h1>")
    collect_prototype(workspace, 145, worktree)

    # 2 回目はプロトタイプ未生成 (収集失敗)
    (worktree_prototype_file(worktree, 145)).unlink()
    assert collect_prototype(workspace, 145, worktree) is False
    manifest = json.loads((prototype_dir(workspace, 145) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["iteration"] == 1


# ──────────────────────────────────────
# read_prototypes
# ──────────────────────────────────────
def test_read_prototypes_absent_returns_empty(workspace: Path) -> None:
    res = read_prototypes(workspace, 999)
    assert res.items == []
    assert res.generated_at is None


def test_read_prototypes_builds_url(workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>p</h1>")
    collect_prototype(workspace, 145, worktree)

    res = read_prototypes(workspace, 145)
    assert len(res.items) == 1
    assert res.items[0].url == "/api/issues/145/prototypes/index.html"


def test_read_prototypes_exposes_iteration(workspace: Path, tmp_path: Path) -> None:
    """#145 Phase2: manifest の iteration がレスポンスに反映される."""
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>p</h1>")
    collect_prototype(workspace, 145, worktree)

    assert read_prototypes(workspace, 145).iteration == 1


# ──────────────────────────────────────
# collector 多案 (#145 Phase3)
# ──────────────────────────────────────
def _write_variants(worktree: Path, issue_number: int, variants: list[dict[str, str]]) -> None:
    """サイドカー JSON と各 variant HTML を worktree に書く."""
    from ai_agent_orchestrator.prototype.paths import worktree_prototypes_manifest

    designs = worktree / "docs" / "designs"
    designs.mkdir(parents=True, exist_ok=True)
    for v in variants:
        (designs / v["file"]).write_text(f"<h1>{v['id']}</h1>", encoding="utf-8")
    worktree_prototypes_manifest(worktree, issue_number).write_text(
        json.dumps(variants, ensure_ascii=False), encoding="utf-8"
    )


def test_collect_multi_variants(workspace: Path, tmp_path: Path) -> None:
    """サイドカーがあれば複数案を id/title/description 付きで収集する."""
    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [
            {
                "id": "simple",
                "title": "シンプル案",
                "description": "最小操作",
                "file": "issue-145.prototype.simple.html",
            },
            {"id": "rich", "title": "リッチ案", "description": "情報量多め", "file": "issue-145.prototype.rich.html"},
        ],
    )

    assert collect_prototype(workspace, 145, worktree) is True
    res = read_prototypes(workspace, 145)
    assert [it.id for it in res.items] == ["simple", "rich"]
    assert res.items[0].title == "シンプル案"
    assert res.items[0].description == "最小操作"
    assert res.items[0].url == "/api/issues/145/prototypes/simple.html"
    # 各案の HTML が <id>.html として配信ディレクトリへコピーされる
    assert (prototype_dir(workspace, 145) / "simple.html").is_file()
    assert (prototype_dir(workspace, 145) / "rich.html").is_file()


def test_collect_multi_variants_skips_invalid_id(workspace: Path, tmp_path: Path) -> None:
    """不正な id / パストラバーサルの file はスキップされる."""
    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [
            {"id": "ok", "title": "OK", "description": "", "file": "issue-145.prototype.ok.html"},
            {"id": "../evil", "title": "X", "description": "", "file": "issue-145.prototype.ok.html"},
        ],
    )
    assert collect_prototype(workspace, 145, worktree) is True
    res = read_prototypes(workspace, 145)
    assert [it.id for it in res.items] == ["ok"]


def test_collect_caps_variants_to_three(workspace: Path, tmp_path: Path) -> None:
    """案数は 3 を上限に収集する."""
    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [
            {"id": f"v{i}", "title": f"案{i}", "description": "", "file": f"issue-145.prototype.v{i}.html"}
            for i in range(5)
        ],
    )
    collect_prototype(workspace, 145, worktree)
    assert len(read_prototypes(workspace, 145).items) == 3


# ──────────────────────────────────────
# selection (#145 Phase3)
# ──────────────────────────────────────
def test_selection_round_trip(workspace: Path) -> None:
    from ai_agent_orchestrator.prototype.selection import read_selection, write_selection

    assert read_selection(workspace, 145) is None
    assert write_selection(workspace, 145, "simple") is True
    assert read_selection(workspace, 145) == "simple"


def test_selection_rejects_invalid_id(workspace: Path) -> None:
    from ai_agent_orchestrator.prototype.selection import write_selection

    assert write_selection(workspace, 145, "../evil") is False


def test_read_prototypes_exposes_selected(workspace: Path, tmp_path: Path) -> None:
    from ai_agent_orchestrator.prototype.selection import write_selection

    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [{"id": "simple", "title": "S", "description": "", "file": "issue-145.prototype.simple.html"}],
    )
    collect_prototype(workspace, 145, worktree)
    write_selection(workspace, 145, "simple")

    assert read_prototypes(workspace, 145).selected == "simple"


def test_read_prototypes_ignores_stale_selection(workspace: Path, tmp_path: Path) -> None:
    """存在しない案を指す selection は無視される."""
    from ai_agent_orchestrator.prototype.selection import write_selection

    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [{"id": "simple", "title": "S", "description": "", "file": "issue-145.prototype.simple.html"}],
    )
    collect_prototype(workspace, 145, worktree)
    write_selection(workspace, 145, "ghost")

    assert read_prototypes(workspace, 145).selected is None


# ──────────────────────────────────────
# POST /api/issues/{n}/prototypes/select (#145 Phase3)
# ──────────────────────────────────────
def test_select_endpoint_persists_choice(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [
            {"id": "simple", "title": "S", "description": "", "file": "issue-145.prototype.simple.html"},
            {"id": "rich", "title": "R", "description": "", "file": "issue-145.prototype.rich.html"},
        ],
    )
    collect_prototype(workspace, 145, worktree)

    r = client.post("/api/issues/145/prototypes/select", json={"variant_id": "rich"})
    assert r.status_code == 200
    assert r.json() == {"accepted": True, "selected": "rich"}
    assert read_prototypes(workspace, 145).selected == "rich"


def test_select_endpoint_unknown_variant_404(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_variants(
        worktree,
        145,
        [{"id": "simple", "title": "S", "description": "", "file": "issue-145.prototype.simple.html"}],
    )
    collect_prototype(workspace, 145, worktree)

    r = client.post("/api/issues/145/prototypes/select", json={"variant_id": "ghost"})
    assert r.status_code == 404


def test_select_endpoint_invalid_id_422(client: TestClient) -> None:
    r = client.post("/api/issues/145/prototypes/select", json={"variant_id": "../evil"})
    assert r.status_code == 422


def test_select_endpoint_rejects_unknown_field_422(client: TestClient) -> None:
    r = client.post("/api/issues/145/prototypes/select", json={"variant_id": "simple", "token": "x"})
    assert r.status_code == 422


# ──────────────────────────────────────
# endpoints
# ──────────────────────────────────────
def test_get_prototypes_endpoint(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<h1>p</h1>")
    collect_prototype(workspace, 145, worktree)

    r = client.get("/api/issues/145/prototypes")
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["url"] == "/api/issues/145/prototypes/index.html"


def test_serve_prototype_html_with_sandbox_headers(client: TestClient, workspace: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _write_worktree_prototype(worktree, 145, "<!doctype html><h1>proto</h1>")
    collect_prototype(workspace, 145, worktree)

    r = client.get("/api/issues/145/prototypes/index.html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    # エージェント生成 HTML の隔離ヘッダ
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<h1>proto</h1>" in r.text


def test_serve_prototype_path_traversal_blocked(client: TestClient, workspace: Path) -> None:
    prototype_dir(workspace, 145).mkdir(parents=True, exist_ok=True)
    r = client.get("/api/issues/145/prototypes/..%2F..%2Fstate.json")
    assert r.status_code == 404


def test_serve_prototype_missing_file_404(client: TestClient, workspace: Path) -> None:
    r = client.get("/api/issues/145/prototypes/index.html")
    assert r.status_code == 404


# ──────────────────────────────────────
# POST /api/issues/{n}/prototypes/feedback (#145 Phase2)
# ──────────────────────────────────────
def _write_state(workspace: Path, key: str, number: int, repo: str, phase: str) -> None:
    entry = {
        "issue_number": number,
        "phase": phase,
        "issue_type": "feature-m",
        "repo": repo,
        "pr_number": None,
        "design_pr_number": None,
        "retry_count": 0,
        "branch_head_sha": None,
        "impl_iteration": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    (workspace / "state.json").write_text(json.dumps({key: entry}, ensure_ascii=False), encoding="utf-8")


def test_prototype_feedback_writes_prototype_revise(client: TestClient, workspace: Path) -> None:
    """修正依頼 → control.jsonl に prototype_revise + feedback 行を書く."""
    _write_state(workspace, "o/r:145", 145, "o/r", "approve")
    r = client.post("/api/issues/145/prototypes/feedback", json={"feedback": "色を変えて", "actor": "o"})
    assert r.status_code == 200
    assert r.json() == {"accepted": True}
    record = json.loads((workspace / "control.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert record == {"issue": 145, "action": "prototype_revise", "approver": "o", "feedback": "色を変えて"}


def test_prototype_feedback_unknown_issue_404(client: TestClient) -> None:
    r = client.post("/api/issues/999/prototypes/feedback", json={"feedback": "x", "actor": "o"})
    assert r.status_code == 404


def test_prototype_feedback_empty_feedback_422(client: TestClient, workspace: Path) -> None:
    """空フィードバックは 422 (min_length=1)."""
    _write_state(workspace, "o/r:145", 145, "o/r", "approve")
    r = client.post("/api/issues/145/prototypes/feedback", json={"feedback": "", "actor": "o"})
    assert r.status_code == 422


def test_prototype_feedback_rejects_unknown_field_422(client: TestClient, workspace: Path) -> None:
    """秘密情報の混入を防ぐ: 未知フィールドは 422 (extra=forbid)."""
    _write_state(workspace, "o/r:145", 145, "o/r", "approve")
    r = client.post(
        "/api/issues/145/prototypes/feedback",
        json={"feedback": "x", "actor": "o", "token": "ghp_secret"},
    )
    assert r.status_code == 422
