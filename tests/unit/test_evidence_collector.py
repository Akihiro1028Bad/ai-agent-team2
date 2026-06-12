"""evidence.collector.EvidenceCollector のユニットテスト."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ai_agent_orchestrator.evidence.capture import CaptureUnavailableError
from ai_agent_orchestrator.evidence.collector import EvidenceCollector
from ai_agent_orchestrator.evidence.models import EvidenceItem
from ai_agent_orchestrator.evidence.paths import evidence_dir


# ──────────────────────────────────────
# Fake 実装
# ──────────────────────────────────────
@dataclass
class _FakeRepo:
    """RepositoryConfig 互換の最小 Fake。"""

    dev_command: str | None = None
    dev_url: str | None = None
    dev_ready_timeout_sec: int = 5
    test_command: str | None = None


class _FakeCapture:
    """固定 EvidenceItem を返し、ファイルも書く Fake キャプチャ。"""

    def __init__(self) -> None:
        self.called_with: str | None = None

    async def capture(self, url: str, out_dir: Path) -> list[EvidenceItem]:
        self.called_with = url
        (out_dir / "screenshot-desktop.png").write_bytes(b"png")
        (out_dir / "recording.webm").write_bytes(b"webm")
        return [
            EvidenceItem(id="screenshot-desktop", kind="screenshot", title="desktop", file="screenshot-desktop.png"),
            EvidenceItem(id="video", kind="video", title="録画", file="recording.webm"),
        ]


class _UnavailableCapture:
    """playwright 未インストールを模した Fake。"""

    async def capture(self, url: str, out_dir: Path) -> list[EvidenceItem]:
        raise CaptureUnavailableError("playwright 未インストール")


class _FakeReadyProbe:
    """常に ready を返す Fake。"""

    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready

    async def wait_ready(self, url: str, timeout_sec: int) -> bool:
        return self._ready


def _read_manifest(workspace: Path, issue_number: int) -> dict[str, object]:
    path = evidence_dir(workspace, issue_number) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ──────────────────────────────────────
# テスト
# ──────────────────────────────────────
async def test_ui_capture_when_ui_impact_and_dev_configured(tmp_path: Path) -> None:
    """ui_impact=True かつ dev 設定済みで UI キャプチャを実施し dev server を停止する。"""
    (tmp_path / "wt").mkdir()
    capture = _FakeCapture()
    collector = EvidenceCollector(tmp_path, capture=capture, ready_probe=_FakeReadyProbe())
    repo = _FakeRepo(dev_command="sleep 5", dev_url="http://localhost:3000")

    manifest = await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=True)

    kinds = {item["kind"] for item in manifest["items"]}
    assert "screenshot" in kinds
    assert "video" in kinds
    assert capture.called_with == "http://localhost:3000"
    ev_dir = evidence_dir(tmp_path, 91)
    assert (ev_dir / "screenshot-desktop.png").exists()
    assert (ev_dir / "recording.webm").exists()
    # dev server プロセスは collect 終了時点で停止している
    assert collector._dev_proc is None or collector._dev_proc.returncode is not None


async def test_no_capture_when_ui_impact_false(tmp_path: Path) -> None:
    """ui_impact=False のときスクショは取らず notes に理由を記録する。"""
    capture = _FakeCapture()
    collector = EvidenceCollector(tmp_path, capture=capture, ready_probe=_FakeReadyProbe())
    repo = _FakeRepo(dev_command="sleep 5", dev_url="http://localhost:3000")

    manifest = await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=False)

    assert capture.called_with is None
    assert not manifest["items"]
    assert any("スキップ" in note for note in manifest["notes"])


async def test_test_command_only_writes_terminal_item(tmp_path: Path) -> None:
    """dev_command 未設定 + test_command 設定で terminal item のみ生成する。"""
    wt = tmp_path / "wt"
    wt.mkdir()
    collector = EvidenceCollector(tmp_path, capture=_FakeCapture(), ready_probe=_FakeReadyProbe())
    repo = _FakeRepo(test_command="echo hello")

    manifest = await collector.collect(repo, 91, str(wt), ui_impact=None)

    items = manifest["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "terminal"
    log = (evidence_dir(tmp_path, 91) / "test-log.txt").read_text(encoding="utf-8")
    assert "hello" in log


async def test_capture_unavailable_is_swallowed(tmp_path: Path) -> None:
    """playwright 未インストール時は notes に記録し例外を外に出さない。"""
    (tmp_path / "wt").mkdir()
    collector = EvidenceCollector(tmp_path, capture=_UnavailableCapture(), ready_probe=_FakeReadyProbe())
    repo = _FakeRepo(dev_command="sleep 5", dev_url="http://localhost:3000")

    manifest = await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=True)

    assert not manifest["items"]
    assert any("playwright" in note.lower() for note in manifest["notes"])


async def test_ready_probe_false_skips_capture(tmp_path: Path) -> None:
    """dev server が ready にならない場合 capture を呼ばず notes に記録する。"""
    (tmp_path / "wt").mkdir()
    capture = _FakeCapture()
    collector = EvidenceCollector(tmp_path, capture=capture, ready_probe=_FakeReadyProbe(ready=False))
    repo = _FakeRepo(dev_command="sleep 5", dev_url="http://localhost:3000")

    manifest = await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=True)

    assert capture.called_with is None
    assert not manifest["items"]
    assert manifest["notes"]


async def test_manifest_regeneration_clears_stale_files(tmp_path: Path) -> None:
    """2 回 collect すると古いファイルが残らない。"""
    collector = EvidenceCollector(tmp_path, capture=_FakeCapture(), ready_probe=_FakeReadyProbe())
    repo = _FakeRepo(test_command="echo hello")
    ev_dir = evidence_dir(tmp_path, 91)

    await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=None)
    # 古い残骸ファイルを置く
    stale = ev_dir / "stale.txt"
    stale.write_text("old", encoding="utf-8")

    await collector.collect(repo, 91, str(tmp_path / "wt"), ui_impact=None)

    assert not stale.exists()
    assert (ev_dir / "manifest.json").exists()
