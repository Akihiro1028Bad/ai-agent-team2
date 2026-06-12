"""io_safety モジュールの単体テスト (#115 Unit C1)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ai_agent_orchestrator.io_safety import (
    FileTooLargeError,
    atomic_write_text,
    ensure_private_file,
    read_text_capped,
)


def _mode(path: Path) -> int:
    """ファイルのパーミッションビット (0o777 マスク) を返す."""
    return stat.S_IMODE(path.stat().st_mode)


class TestAtomicWriteText:
    def test_writes_content(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        atomic_write_text(target, '{"a": 1}')
        assert target.read_text(encoding="utf-8") == '{"a": 1}'

    def test_file_is_owner_only(self, tmp_path: Path) -> None:
        """書き出したファイルは 0o600 (所有者のみ rw)."""
        target = tmp_path / "out.json"
        atomic_write_text(target, "x")
        assert _mode(target) == 0o600

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "out.json"
        atomic_write_text(target, "x")
        assert target.exists()

    def test_leaves_no_tmp_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        atomic_write_text(target, "x")
        assert not (tmp_path / "out.tmp").exists()

    def test_overwrite_resets_mode(self, tmp_path: Path) -> None:
        """既存の広い権限ファイルを上書きしても 0o600 になる."""
        target = tmp_path / "out.json"
        target.write_text("old", encoding="utf-8")
        target.chmod(0o644)
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"
        assert _mode(target) == 0o600


class TestEnsurePrivateFile:
    def test_creates_owner_only_file(self, tmp_path: Path) -> None:
        target = tmp_path / "logs" / "agent.jsonl"
        ensure_private_file(target)
        assert target.exists()
        assert _mode(target) == 0o600

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "agent.jsonl"
        ensure_private_file(target)
        assert target.exists()

    def test_preserves_existing_content(self, tmp_path: Path) -> None:
        """既存ファイルの中身は破壊しない (追記ログ前提)."""
        target = tmp_path / "agent.jsonl"
        target.write_text("line1\n", encoding="utf-8")
        ensure_private_file(target)
        assert target.read_text(encoding="utf-8") == "line1\n"


class TestReadTextCapped:
    def test_reads_under_limit(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("hello", encoding="utf-8")
        assert read_text_capped(target, max_bytes=100) == "hello"

    def test_reads_at_limit(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("abcde", encoding="utf-8")
        assert read_text_capped(target, max_bytes=5) == "abcde"

    def test_raises_over_limit(self, tmp_path: Path) -> None:
        target = tmp_path / "f.txt"
        target.write_text("abcdef", encoding="utf-8")
        with pytest.raises(FileTooLargeError):
            read_text_capped(target, max_bytes=5)

    def test_too_large_is_oserror(self, tmp_path: Path) -> None:
        """FileTooLargeError は OSError 派生 (既存の except OSError で捕捉できる)."""
        assert issubclass(FileTooLargeError, OSError)


# --- 各層への配線テスト (#115): 書き出し 0o600 / 読み取り上限の安全側フォールバック ---


class TestStatePersistenceHardening:
    def test_saved_state_is_owner_only(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.models import IssueState, Phase
        from ai_agent_orchestrator.state_persistence import StatePersistence

        state_file = tmp_path / "state.json"
        persistence = StatePersistence(state_file=state_file)
        persistence.save({("owner/repo", 1): IssueState(issue_number=1, repo="owner/repo", phase=Phase.PLAN)})
        assert _mode(state_file) == 0o600

    def test_load_over_limit_returns_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from ai_agent_orchestrator import state_persistence
        from ai_agent_orchestrator.state_persistence import StatePersistence

        state_file = tmp_path / "state.json"
        state_file.write_text('{"owner/repo:1": {}}', encoding="utf-8")
        monkeypatch.setattr(state_persistence, "MAX_STATUS_FILE_BYTES", 5)
        # 上限超過は backup を作らず空 dict に倒す。
        assert StatePersistence(state_file=state_file).load() == {}
        assert not (tmp_path / "state.json.corrupted").exists()


class TestReadersHardening:
    def test_read_health_over_limit_is_stopped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from ai_agent_orchestrator.api import readers

        (tmp_path / "health.json").write_text('{"running": true, "ts": "x"}', encoding="utf-8")
        monkeypatch.setattr(readers, "MAX_STATUS_FILE_BYTES", 5)
        result = readers.read_health(tmp_path)
        assert result.running is False
        assert result.reason is not None

    def test_read_queue_over_limit_is_stopped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from ai_agent_orchestrator.api import readers

        (tmp_path / "queue.json").write_text('{"active": [], "queued": []}', encoding="utf-8")
        monkeypatch.setattr(readers, "MAX_STATUS_FILE_BYTES", 5)
        result = readers.read_queue(tmp_path)
        assert result.running is False
        assert result.reason is not None

    def test_read_agent_logs_over_limit_is_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from ai_agent_orchestrator.api import readers

        log = tmp_path / "logs" / "issue-1" / "agent.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('{"type": "x"}\n', encoding="utf-8")
        monkeypatch.setattr(readers, "MAX_LOG_FILE_BYTES", 5)
        page = readers.read_agent_logs(tmp_path, 1)
        assert page.records == []
        assert page.total == 0


class TestLogWriterHardening:
    async def test_event_log_file_is_owner_only(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.event_logger import EventLogger

        logger_obj = EventLogger(log_dir=tmp_path)
        await logger_obj.track("test_event", issue_number=7, phase="plan")
        assert _mode(tmp_path / "issue-7" / "events.jsonl") == 0o600

    async def test_agent_log_file_is_owner_only(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.agents.agent_log import AgentLogWriter

        writer = AgentLogWriter(log_dir=tmp_path)
        await writer.write(7, {"type": "assistant"})
        assert _mode(tmp_path / "issue-7" / "agent.jsonl") == 0o600
