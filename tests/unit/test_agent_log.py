"""AgentLogWriter + claude_runner ログフックの単体テスト."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_agent_orchestrator.agents.agent_log import AgentLogWriter


# ──────────────────────────────────────
# AgentLogWriter
# ──────────────────────────────────────
async def test_write_appends_jsonl(tmp_path: Path) -> None:
    writer = AgentLogWriter(log_dir=tmp_path / "logs")
    await writer.write(42, {"type": "text", "text": "hello"})
    await writer.write(42, {"type": "text", "text": "world"})

    path = tmp_path / "logs" / "issue-42" / "agent.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["text"] == "hello"
    assert json.loads(lines[1])["text"] == "world"


async def test_write_sanitizes_record(tmp_path: Path) -> None:
    writer = AgentLogWriter(log_dir=tmp_path / "logs")
    token = "ghp_" + "a" * 36
    await writer.write(7, {"type": "tool_use", "tool": "Bash", "input": {"token": "x", "cmd": token}})

    path = tmp_path / "logs" / "issue-7" / "agent.jsonl"
    rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert rec["input"]["token"] == "***REDACTED***"
    assert rec["input"]["cmd"] == "***REDACTED***"


# ──────────────────────────────────────
# claude_runner のログフック (FakeWriter 注入)
# ──────────────────────────────────────
class _RecordingWriter:
    """write 呼び出しを記録する Fake。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.records: list[tuple[int, dict[str, Any]]] = []
        self._fail = fail

    async def write(self, issue_number: int, record: dict[str, Any]) -> None:
        if self._fail:
            raise OSError("disk full")
        self.records.append((issue_number, record))


class _NullTracker:
    async def track(self, event: str, data: dict[str, Any]) -> None:
        return None


def _make_runner(writer: Any) -> Any:
    from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner

    return ClaudeAgentRunner(tracker=_NullTracker(), agent_log_writer=writer)


def _fake_messages() -> list[Any]:
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
    )

    assistant = AssistantMessage(
        content=[
            TextBlock(text="ghp_" + "z" * 36),
            ToolUseBlock(id="t1", name="Bash", input={"command": "ls", "secret": "s"}),
        ],
        model="claude",
    )
    result = ResultMessage(
        subtype="success",
        duration_ms=1200,
        duration_api_ms=1000,
        is_error=False,
        num_turns=1,
        session_id="sess-1",
        total_cost_usd=0.05,
        usage={"input_tokens": 10, "output_tokens": 20},
    )
    return [assistant, result]


async def test_log_messages_writes_text_tool_result(tmp_path: Path) -> None:
    writer = _RecordingWriter()
    runner = _make_runner(writer)
    await runner._log_messages(_fake_messages(), issue_number=42, phase="plan")

    types = [r["type"] for _, r in writer.records]
    assert types == ["text", "tool_use", "result"]

    text_rec = writer.records[0][1]
    assert text_rec["text"] == "***REDACTED***"  # トークンがサニタイズされる
    assert text_rec["phase"] == "plan"
    assert "ts" in text_rec

    tool_rec = writer.records[1][1]
    assert tool_rec["tool"] == "Bash"
    assert tool_rec["input"]["secret"] == "***REDACTED***"

    result_rec = writer.records[2][1]
    assert result_rec["session_id"] == "sess-1"
    assert result_rec["cost_usd"] == 0.05
    assert result_rec["duration_ms"] == 1200
    assert result_rec["usage"] == {"input_tokens": 10, "output_tokens": 20}
    assert result_rec["is_error"] is False
    assert result_rec["subtype"] == "success"


async def test_log_messages_swallows_write_failure(tmp_path: Path) -> None:
    writer = _RecordingWriter(fail=True)
    runner = _make_runner(writer)
    # 書き込み失敗してもフェーズ実行を止めない (例外を投げない)
    await runner._log_messages(_fake_messages(), issue_number=42, phase="plan")


async def test_log_messages_noop_without_writer_or_issue(tmp_path: Path) -> None:
    runner = _make_runner(None)
    # writer が None なら何も起きない (後方互換)
    await runner._log_messages(_fake_messages(), issue_number=42, phase="plan")


async def test_log_messages_noop_without_issue_number() -> None:
    writer = _RecordingWriter()
    runner = _make_runner(writer)
    await runner._log_messages(_fake_messages(), issue_number=None, phase="plan")
    assert writer.records == []
