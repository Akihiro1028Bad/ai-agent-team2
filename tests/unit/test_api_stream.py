"""api.stream の tail ジェネレータ + SSE エンドポイントの単体テスト."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ai_agent_orchestrator.api.stream import (
    SseConnectionLimiter,
    SseEvent,
    _read_new_lines,
    _TailState,
    format_sse,
    parse_last_event_id,
    tail_issue_streams,
)


# ──────────────────────────────────────
# ヘルパ
# ──────────────────────────────────────
def _issue_dir(workspace: Path, issue_number: int) -> Path:
    d = workspace / "logs" / f"issue-{issue_number}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _append(path: Path, obj: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


async def _collect(workspace: Path, issue: int, **kwargs: object) -> list[SseEvent]:
    return [ev async for ev in tail_issue_streams(workspace, issue, **kwargs)]  # type: ignore[arg-type]


# ──────────────────────────────────────
# parse_last_event_id
# ──────────────────────────────────────
def test_parse_last_event_id_valid() -> None:
    assert parse_last_event_id("events:3,agent:7") == (3, 7)


def test_parse_last_event_id_invalid_returns_zero() -> None:
    assert parse_last_event_id(None) == (0, 0)
    assert parse_last_event_id("garbage") == (0, 0)
    assert parse_last_event_id("events:x,agent:y") == (0, 0)


# ──────────────────────────────────────
# format_sse
# ──────────────────────────────────────
def test_format_sse_shape() -> None:
    ev = SseEvent(source="agent", events_consumed=2, agent_consumed=5, data='{"k":1}')
    out = format_sse(ev)
    assert out == 'event: agent\nid: events:2,agent:5\ndata: {"k":1}\n\n'


# ──────────────────────────────────────
# tail_issue_streams
# ──────────────────────────────────────
async def test_tail_emits_existing_then_idle_terminates(tmp_path: Path) -> None:
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    _append(agent, {"type": "text", "text": "a"})
    _append(agent, {"type": "text", "text": "b"})

    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.05)
    assert [e.source for e in events] == ["agent", "agent"]
    assert events[-1].agent_consumed == 2
    assert json.loads(events[0].data)["text"] == "a"


async def test_tail_detects_appended_line_quickly(tmp_path: Path) -> None:
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    _append(agent, {"type": "text", "text": "first"})

    async def _writer() -> None:
        await asyncio.sleep(0.02)
        _append(agent, {"type": "text", "text": "second"})

    task = asyncio.create_task(_writer())
    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.1)
    await task
    texts = [json.loads(e.data)["text"] for e in events]
    assert texts == ["first", "second"]


async def test_tail_start_offset_resumes_without_loss(tmp_path: Path) -> None:
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    for i in range(4):
        _append(agent, {"type": "text", "text": str(i)})

    # 既存 2 行を消費済みとして再開
    events = await _collect(tmp_path, 1, start_agent=2, poll_interval=0.01, max_idle_sec=0.05)
    texts = [json.loads(e.data)["text"] for e in events]
    assert texts == ["2", "3"]
    # consumed カウンタは絶対物理行数
    assert events[-1].agent_consumed == 4


async def test_tail_handles_both_sources(tmp_path: Path) -> None:
    d = _issue_dir(tmp_path, 1)
    _append(d / "events.jsonl", {"event": "phase_started"})
    _append(d / "agent.jsonl", {"type": "text", "text": "x"})

    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.05)
    sources = {e.source for e in events}
    assert sources == {"events", "agent"}


async def test_tail_file_absent_then_appears(tmp_path: Path) -> None:
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"  # 当初は存在しない

    async def _writer() -> None:
        await asyncio.sleep(0.02)
        _append(agent, {"type": "text", "text": "late"})

    task = asyncio.create_task(_writer())
    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.1)
    await task
    assert [json.loads(e.data)["text"] for e in events] == ["late"]


async def test_tail_streams_broken_line_raw_and_consumes(tmp_path: Path) -> None:
    """SSE は生行を流す (パースは UI 側)。壊れ行も生のまま yield し、物理行を消費する."""
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    with agent.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "text", "text": "a"}) + "\n")
        f.write("{ broken\n")
        f.write(json.dumps({"type": "text", "text": "c"}) + "\n")

    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.05)
    assert [e.data for e in events] == ['{"type": "text", "text": "a"}', "{ broken", '{"type": "text", "text": "c"}']
    # 壊れ行も物理行として消費される
    assert events[-1].agent_consumed == 3


# ──────────────────────────────────────
# SSE エンドポイント (TestClient, 即時クローズ)
# ──────────────────────────────────────
def _make_app(workspace: Path, *, max_idle_sec: float | None = 0.05):  # type: ignore[no-untyped-def]
    from ai_agent_orchestrator.api.app import create_app
    from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig

    app = create_app(
        AppSettings(
            repositories=[RepositoryConfig(owner="o", repo="r", account="default")],
            workspace_dir=str(workspace),
        )
    )
    # max_idle_sec は公開 Query から外したため (#113 L3)、テストは app.state 経由で
    # 短いアイドル打ち切りを設定し、TestClient のストリームを終端させる。
    app.state.sse_max_idle_sec = max_idle_sec
    return app


def test_stream_endpoint_returns_event_stream(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    d = _issue_dir(tmp_path, 1)
    _append(d / "agent.jsonl", {"type": "text", "text": "hello"})

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.stream("GET", "/api/stream?issue=1") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = "".join(chunk for chunk in resp.iter_text())
    assert "event: agent" in body
    assert "id: events:0,agent:1" in body
    assert "hello" in body


def test_stream_endpoint_last_event_id_resume(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    _append(agent, {"type": "text", "text": "one"})
    _append(agent, {"type": "text", "text": "two"})

    app = _make_app(tmp_path)
    with TestClient(app) as client:
        with client.stream(
            "GET",
            "/api/stream?issue=1",
            headers={"Last-Event-ID": "events:0,agent:1"},
        ) as resp:
            assert resp.status_code == 200
            body = "".join(chunk for chunk in resp.iter_text())
    assert "two" in body
    assert "one" not in body


def test_stream_endpoint_429_when_limit_exhausted(tmp_path: Path) -> None:
    """per-issue 接続上限を使い切ると 429 を返す (#113 L2)."""
    from fastapi.testclient import TestClient

    _issue_dir(tmp_path, 1)
    app = _make_app(tmp_path)
    limiter: SseConnectionLimiter = app.state.sse_limiter
    # per-issue 上限まで占有 (テストから直接 acquire)
    for _ in range(limiter.max_per_issue):
        assert limiter.try_acquire(1) is True

    with TestClient(app) as client:
        resp = client.get("/api/stream?issue=1")
    assert resp.status_code == 429


async def test_tail_does_not_consume_unterminated_line(tmp_path: Path) -> None:
    """末尾改行のない (書き込み途中の可能性がある) 行は消費しない (torn read 防止)."""
    d = _issue_dir(tmp_path, 1)
    agent = d / "agent.jsonl"
    _append(agent, {"type": "text", "text": "complete"})
    with agent.open("a", encoding="utf-8") as f:
        f.write('{"type": "text", "text": "par')  # 改行なし = 書き込み途中

    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.05)
    texts = [json.loads(e.data)["text"] for e in events]
    assert texts == ["complete"]
    assert events[-1].agent_consumed == 1  # 途中行は未消費

    # 残りが書かれて改行で閉じたら、次の tail で完全な行として届く
    with agent.open("a", encoding="utf-8") as f:
        f.write('tial"}\n')
    events2 = await _collect(tmp_path, 1, start_agent=1, poll_interval=0.01, max_idle_sec=0.05)
    assert [json.loads(e.data)["text"] for e in events2] == ["partial"]


async def test_tail_emits_keepalive_during_idle(tmp_path: Path) -> None:
    """イベントが来ないアイドル中も keepalive イベントが届く (プロキシ切断対策)."""
    _issue_dir(tmp_path, 1)  # ログファイルなし = 完全アイドル

    events = await _collect(tmp_path, 1, poll_interval=0.01, max_idle_sec=0.2, keepalive_interval=0.05)
    assert len(events) >= 1
    assert all(e.source == "keepalive" for e in events)


def test_format_sse_keepalive_is_comment() -> None:
    """keepalive イベントは SSE コメント行に整形される (id を進めない)."""
    ev = SseEvent(source="keepalive", events_consumed=2, agent_consumed=5, data="")
    assert format_sse(ev) == ": keep-alive\n\n"


def test_parse_last_event_id_negative_clamped_to_zero() -> None:
    """負のオフセットは 0 にクランプする (負スライスでの行再送・id ずれ防止)."""
    assert parse_last_event_id("events:-3,agent:-1") == (0, 0)


# ──────────────────────────────────────
# SseConnectionLimiter (#113 L2)
# ──────────────────────────────────────
def test_limiter_enforces_per_issue_cap() -> None:
    limiter = SseConnectionLimiter(max_total=100, max_per_issue=2)
    assert limiter.try_acquire(1) is True
    assert limiter.try_acquire(1) is True
    assert limiter.try_acquire(1) is False  # 上限到達
    assert limiter.try_acquire(2) is True  # 別 Issue は独立


def test_limiter_enforces_global_cap() -> None:
    limiter = SseConnectionLimiter(max_total=2, max_per_issue=10)
    assert limiter.try_acquire(1) is True
    assert limiter.try_acquire(2) is True
    assert limiter.try_acquire(3) is False  # 全体上限


def test_limiter_release_frees_slot() -> None:
    limiter = SseConnectionLimiter(max_total=1, max_per_issue=1)
    assert limiter.try_acquire(1) is True
    assert limiter.try_acquire(1) is False
    limiter.release(1)
    assert limiter.try_acquire(1) is True


def test_limiter_release_unknown_is_safe() -> None:
    limiter = SseConnectionLimiter(max_total=1, max_per_issue=1)
    limiter.release(99)  # 未取得でも例外を出さず負にもならない
    assert limiter.try_acquire(99) is True


# ──────────────────────────────────────
# _read_new_lines (#113 seek ベース増分読み)
# ──────────────────────────────────────
def test_incremental_read_returns_only_appended(tmp_path: Path) -> None:
    p = tmp_path / "agent.jsonl"
    p.write_text("a\nb\n", encoding="utf-8")
    state = _TailState(path=p, start_line=0)
    assert _read_new_lines(state) == ["a", "b"]
    first_offset = state.byte_offset
    # 追記分のみが返り、byte_offset は前進する
    with p.open("a", encoding="utf-8") as f:
        f.write("c\n")
    assert _read_new_lines(state) == ["c"]
    assert state.byte_offset > first_offset
    # 追記なしなら空
    assert _read_new_lines(state) == []


def test_incremental_read_priming_skips_start_lines(tmp_path: Path) -> None:
    p = tmp_path / "agent.jsonl"
    p.write_text("0\n1\n2\n3\n", encoding="utf-8")
    state = _TailState(path=p, start_line=2)
    assert _read_new_lines(state) == ["2", "3"]


def test_incremental_read_skips_unterminated_tail(tmp_path: Path) -> None:
    p = tmp_path / "agent.jsonl"
    p.write_text("done\npar", encoding="utf-8")  # 末尾未終端
    state = _TailState(path=p, start_line=0)
    assert _read_new_lines(state) == ["done"]
    # 残りが改行で閉じたら次回に完全な行として届く
    with p.open("a", encoding="utf-8") as f:
        f.write("tial\n")
    assert _read_new_lines(state) == ["partial"]


def test_incremental_read_absent_then_appears(tmp_path: Path) -> None:
    p = tmp_path / "agent.jsonl"
    state = _TailState(path=p, start_line=0)
    assert _read_new_lines(state) == []  # 不在
    p.write_text("late\n", encoding="utf-8")
    assert _read_new_lines(state) == ["late"]


def test_incremental_read_resets_on_truncation(tmp_path: Path) -> None:
    p = tmp_path / "agent.jsonl"
    p.write_text("x\ny\n", encoding="utf-8")
    state = _TailState(path=p, start_line=0)
    assert _read_new_lines(state) == ["x", "y"]
    # 縮退 (size < byte_offset): 先頭から読み直す
    p.write_text("z\n", encoding="utf-8")
    assert _read_new_lines(state) == ["z"]
