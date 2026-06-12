"""evidence.models / evidence.paths のユニットテスト."""

from __future__ import annotations

from pathlib import Path

from ai_agent_orchestrator.evidence.models import EvidenceItem
from ai_agent_orchestrator.evidence.paths import evidence_dir


def test_evidence_item_to_from_dict_roundtrip() -> None:
    """to_dict / from_dict が往復で一致する。"""
    item = EvidenceItem(
        id="screenshot-desktop",
        kind="screenshot",
        title="デスクトップ表示",
        file="screenshot-desktop.png",
        viewport="desktop",
        created_at="2026-06-12T00:00:00+00:00",
    )
    restored = EvidenceItem.from_dict(item.to_dict())
    assert restored == item


def test_evidence_item_to_dict_keys() -> None:
    """to_dict が manifest 用のキーを持つ。"""
    item = EvidenceItem(id="terminal", kind="terminal", title="テスト結果", file="test-log.txt")
    d = item.to_dict()
    assert d["id"] == "terminal"
    assert d["kind"] == "terminal"
    assert d["file"] == "test-log.txt"
    assert d["viewport"] is None


def test_evidence_item_from_dict_defaults() -> None:
    """from_dict が欠損キーを既定値で補う。"""
    item = EvidenceItem.from_dict({"id": "x", "kind": "video", "title": "録画", "file": "recording.webm"})
    assert item.viewport is None
    assert item.created_at == ""


def test_evidence_dir_path() -> None:
    """evidence_dir が artifacts/issue-N/evidence を返す。"""
    root = Path("/tmp/ws")
    assert evidence_dir(root, 91) == root / "artifacts" / "issue-91" / "evidence"
