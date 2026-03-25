"""EventLogger のユニットテスト."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ai_agent_orchestrator.event_logger import EventLogger


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


@pytest.fixture
def logger(log_dir: Path) -> EventLogger:
    return EventLogger(log_dir)


@pytest.mark.asyncio
async def test_track_writes_jsonl(logger: EventLogger, log_dir: Path) -> None:
    """track()がevents.jsonlに1行のJSONレコードを書き込むこと."""
    await logger.track(
        "phase_start",
        issue_number=42,
        phase="hearing",
        data={"comment_id": 123},
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    assert events_file.exists()

    lines = events_file.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["issue"] == 42
    assert record["phase"] == "hearing"
    assert record["event"] == "phase_start"
    assert record["data"]["comment_id"] == 123
    assert "ts" in record


@pytest.mark.asyncio
async def test_sanitize_sensitive_keys(logger: EventLogger, log_dir: Path) -> None:
    """token, password, secret 等のキーの値がマスクされること."""
    await logger.track(
        "api_call",
        issue_number=42,
        phase="implement",
        data={
            "url": "https://api.github.com/repos",
            "auth_token": "ghp_secret123456789",
            "password": "mysecretpass",
            "api_secret": "very_secret_value",
            "authorization": "Bearer ghp_xxxxx",
            "cookie": "session=abc123",
            "normal_field": "safe_value",
        },
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    record = json.loads(events_file.read_text().strip())

    assert record["data"]["auth_token"] == "***REDACTED***"
    assert record["data"]["password"] == "***REDACTED***"
    assert record["data"]["api_secret"] == "***REDACTED***"
    assert record["data"]["authorization"] == "***REDACTED***"
    assert record["data"]["cookie"] == "***REDACTED***"
    assert record["data"]["normal_field"] == "safe_value"
    assert record["data"]["url"] == "https://api.github.com/repos"


def test_sanitize_nested_dict(logger: EventLogger) -> None:
    """ネストされた辞書内のセンシティブキーもマスクされること."""
    data = {
        "headers": {
            "Authorization": "Bearer ghp_xxx",
            "Content-Type": "application/json",
        },
        "body": {
            "nested": {
                "secret_key": "should_be_masked",
            },
        },
    }

    result = logger._sanitize_for_log(data)

    assert result["headers"]["Authorization"] == "***REDACTED***"
    assert result["headers"]["Content-Type"] == "application/json"
    assert result["body"]["nested"]["secret_key"] == "***REDACTED***"


def test_sanitize_token_pattern_in_string(logger: EventLogger) -> None:
    """文字列値内のGitHubトークンパターンがマスクされること."""
    data = {
        "message": "Using token ghp_abcdefghijklmnopqrstuvwxyz1234567890 for auth",
        "url": "https://github.com?access_token=ghp_abcdefghijklmnopqrstuvwxyz1234567890",
        "safe": "no tokens here",
    }

    result = logger._sanitize_for_log(data)

    assert "ghp_" not in result["message"]
    assert "***REDACTED***" in result["message"]
    assert "ghp_" not in result["url"]
    assert result["safe"] == "no tokens here"


@pytest.mark.asyncio
async def test_concurrent_writes(logger: EventLogger, log_dir: Path) -> None:
    """複数の並行タスクからの同時書き込みでデータが欠損しないこと."""

    async def write_event(i: int) -> None:
        await logger.track(
            f"event_{i}",
            issue_number=42,
            phase="implement",
            data={"index": i},
        )

    tasks = [write_event(i) for i in range(20)]
    await asyncio.gather(*tasks)

    events_file = log_dir / "issue-42" / "events.jsonl"
    lines = events_file.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines) == 20

    events = set()
    for line in lines:
        record = json.loads(line)
        events.add(record["event"])

    for i in range(20):
        assert f"event_{i}" in events


@pytest.mark.asyncio
async def test_track_without_data(logger: EventLogger, log_dir: Path) -> None:
    """data=None の場合、recordに 'data' キーが含まれないこと."""
    await logger.track(
        "phase_start",
        issue_number=42,
        phase="hearing",
    )

    events_file = log_dir / "issue-42" / "events.jsonl"
    record = json.loads(events_file.read_text().strip())

    assert "data" not in record
    assert record["event"] == "phase_start"


@pytest.mark.asyncio
async def test_write_phase_log(logger: EventLogger, log_dir: Path) -> None:
    """write_phase_log()がタイムスタンプ付きファイル名でログを書き出すこと."""
    content = "=== Hearing Phase ===\nQuestion: What is the expected behavior?"

    await logger.write_phase_log(
        issue_number=42,
        phase="hearing",
        content=content,
    )

    issue_dir = log_dir / "issue-42"
    log_files = list(issue_dir.glob("*_hearing.log"))
    assert len(log_files) == 1

    written = log_files[0].read_text(encoding="utf-8")
    assert "What is the expected behavior?" in written


@pytest.mark.asyncio
async def test_write_phase_log_masks_tokens(logger: EventLogger, log_dir: Path) -> None:
    """write_phase_log()が文字列内のトークンをマスクすること."""
    content = "Auth with ghp_abcdefghijklmnopqrstuvwxyz1234567890 succeeded"

    await logger.write_phase_log(
        issue_number=42,
        phase="implement",
        content=content,
    )

    issue_dir = log_dir / "issue-42"
    log_files = list(issue_dir.glob("*_implement.log"))
    written = log_files[0].read_text(encoding="utf-8")

    assert "ghp_" not in written
    assert "***REDACTED***" in written


@pytest.mark.asyncio
async def test_events_separated_by_issue(logger: EventLogger, log_dir: Path) -> None:
    """異なるIssue番号のイベントが別ファイルに記録されること."""
    await logger.track("start", issue_number=42, phase="hearing")
    await logger.track("start", issue_number=55, phase="implement")

    file_42 = log_dir / "issue-42" / "events.jsonl"
    file_55 = log_dir / "issue-55" / "events.jsonl"

    assert file_42.exists()
    assert file_55.exists()

    record_42 = json.loads(file_42.read_text().strip())
    record_55 = json.loads(file_55.read_text().strip())

    assert record_42["issue"] == 42
    assert record_55["issue"] == 55


@pytest.mark.asyncio
async def test_track_appends_to_existing(logger: EventLogger, log_dir: Path) -> None:
    """track()が既存ファイルに追記すること（上書きしない）."""
    await logger.track("event_1", issue_number=42, phase="hearing")
    await logger.track("event_2", issue_number=42, phase="hearing")
    await logger.track("event_3", issue_number=42, phase="design")

    events_file = log_dir / "issue-42" / "events.jsonl"
    lines = events_file.read_text(encoding="utf-8").strip().split("\n")

    assert len(lines) == 3
    assert json.loads(lines[0])["event"] == "event_1"
    assert json.loads(lines[1])["event"] == "event_2"
    assert json.loads(lines[2])["event"] == "event_3"


def test_sanitize_list_values(logger: EventLogger) -> None:
    """リスト値内のセンシティブデータもマスクされること."""
    data = {
        "commands": [
            "git push",
            "curl -H 'Authorization: Bearer ghp_abcdefghijklmnopqrstuvwxyz1234567890'",
        ],
        "configs": [
            {"password": "secret123"},
            {"name": "safe"},
        ],
    }

    result = logger._sanitize_for_log(data)

    assert "ghp_" not in result["commands"][1]
    assert result["configs"][0]["password"] == "***REDACTED***"
    assert result["configs"][1]["name"] == "safe"
