"""events.jsonl + agent.jsonl の tail を SSE 配信する (#85).

新規依存を追加せず、StreamingResponse + 手書き SSE フォーマットで配信する。
物理行オフセットを保持し、新規行を検知したら yield する。Last-Event-ID で
再接続時の取りこぼしを防ぐ。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_SEC = 15.0
"""SSE keep-alive コメント行の送出間隔 (秒)。プロキシ切断対策。"""


@dataclass(frozen=True)
class SseEvent:
    """SSE で送出する 1 イベント.

    Attributes:
        source: 由来ファイル ("events" | "agent")。
        events_consumed: events.jsonl の消費済み物理行数。
        agent_consumed: agent.jsonl の消費済み物理行数。
        data: 送出する JSON 行 (1 物理行の生文字列)。
    """

    source: str
    events_consumed: int
    agent_consumed: int
    data: str


def _issue_log_dir(workspace: Path, issue_number: int) -> Path:
    """指定 Issue のログディレクトリを返す."""
    return workspace / "logs" / f"issue-{issue_number}"


def parse_last_event_id(value: str | None) -> tuple[int, int]:
    """Last-Event-ID 文字列を (events_offset, agent_offset) にパースする.

    形式は ``events:{e},agent:{a}``。不正形式は (0, 0) に倒す。

    Args:
        value: Last-Event-ID ヘッダ / クエリの値。

    Returns:
        (events 物理行オフセット, agent 物理行オフセット)。
    """
    if not value:
        return (0, 0)
    parts = dict(p.split(":", 1) for p in value.split(",") if ":" in p)
    try:
        # 負値は 0 にクランプ (負スライスでの行再送・id ずれ防止)
        return (max(0, int(parts["events"])), max(0, int(parts["agent"])))
    except (KeyError, ValueError):
        return (0, 0)


def format_sse(event: SseEvent) -> str:
    """SseEvent を SSE ワイヤーフォーマット文字列へ整形する.

    id には常に両ファイルの消費済み行数を併記し、どの時点で切れても
    再開可能にする。source="keepalive" はコメント行に整形する
    (ブラウザの EventSource には届かず、id も進めない)。

    Args:
        event: 送出イベント。

    Returns:
        ``event: {source}\\nid: events:{e},agent:{a}\\ndata: {行}\\n\\n``。
        keepalive は ``: keep-alive\\n\\n``。
    """
    if event.source == "keepalive":
        return ": keep-alive\n\n"
    return (
        f"event: {event.source}\n"
        f"id: events:{event.events_consumed},agent:{event.agent_consumed}\n"
        f"data: {event.data}\n\n"
    )


def _read_new_lines(path: Path, consumed: int) -> list[str]:
    """ファイルの consumed 行目以降の物理行 (非空) を返す.

    壊れ行の判定はしない (SSE は生行を流し、UI 側でパースする)。空行は
    スキップするが、返すのは consumed 以降に出現した非空行のみ。

    Args:
        path: 対象ファイル。
        consumed: 既に消費済みの物理行数。

    Returns:
        新規物理行 (古い順)。ファイル不在なら空。
    """
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("SSE tail の読み取りに失敗: %s", path, exc_info=True)
        return []
    lines = text.splitlines()
    # 末尾が改行で終端されていない行は書き込み途中の可能性があるため消費しない
    # (torn read 防止)。改行で閉じられた次の poll で完全な行として読む。
    if text and not text.endswith("\n") and lines:
        lines = lines[:-1]
    return lines[consumed:]


async def tail_issue_streams(
    workspace: Path,
    issue_number: int,
    *,
    start_events: int = 0,
    start_agent: int = 0,
    poll_interval: float = 0.5,
    max_idle_sec: float | None = None,
    keepalive_interval: float | None = KEEPALIVE_INTERVAL_SEC,
) -> AsyncIterator[SseEvent]:
    """events.jsonl / agent.jsonl の tail を SSE イベントとして yield する.

    物理行オフセットを保持し、新規行を検知したら yield する。ファイル不在は
    「まだ 0 行」として扱い、出現したら読み始める。``max_idle_sec`` は
    テスト用の打ち切り (本番 None = 無限)。アイドルが ``keepalive_interval``
    続いたら source="keepalive" のイベントを yield する (イベント待ちで
    ジェネレータが沈黙したままにならないよう、tail ループ内で送出する)。

    Args:
        workspace: ワークスペースのルートパス。
        issue_number: Issue 番号。
        start_events: events.jsonl の開始物理行オフセット。
        start_agent: agent.jsonl の開始物理行オフセット。
        poll_interval: ポーリング間隔 (秒)。
        max_idle_sec: 無出力が継続したら打ち切る秒数 (None で無限)。
        keepalive_interval: keepalive 送出までのアイドル秒数 (None で無効)。

    Yields:
        SseEvent。
    """
    log_dir = _issue_log_dir(workspace, issue_number)
    events_path = log_dir / "events.jsonl"
    agent_path = log_dir / "agent.jsonl"

    events_consumed = start_events
    agent_consumed = start_agent
    last_activity = time.monotonic()
    last_emit = last_activity

    while True:
        emitted = False

        for source, path, consumed in (
            ("events", events_path, events_consumed),
            ("agent", agent_path, agent_consumed),
        ):
            new_lines = await asyncio.to_thread(_read_new_lines, path, consumed)
            for line in new_lines:
                consumed += 1
                if source == "events":
                    events_consumed = consumed
                else:
                    agent_consumed = consumed
                stripped = line.strip()
                if not stripped:
                    continue
                emitted = True
                yield SseEvent(
                    source=source,
                    events_consumed=events_consumed,
                    agent_consumed=agent_consumed,
                    data=stripped,
                )

        now = time.monotonic()
        if emitted:
            last_activity = now
            last_emit = now
        else:
            if max_idle_sec is not None and (now - last_activity) >= max_idle_sec:
                return
            if keepalive_interval is not None and (now - last_emit) >= keepalive_interval:
                last_emit = now
                yield SseEvent(
                    source="keepalive",
                    events_consumed=events_consumed,
                    agent_consumed=agent_consumed,
                    data="",
                )

        await asyncio.sleep(poll_interval)
