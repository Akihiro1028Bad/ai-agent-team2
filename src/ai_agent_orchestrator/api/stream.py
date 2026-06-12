"""events.jsonl + agent.jsonl の tail を SSE 配信する (#85).

新規依存を追加せず、StreamingResponse + 手書き SSE フォーマットで配信する。
物理行オフセットを保持し、新規行を検知したら yield する。Last-Event-ID で
再接続時の取りこぼしを防ぐ。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

KEEPALIVE_INTERVAL_SEC = 15.0
"""SSE keep-alive コメント行の送出間隔 (秒)。プロキシ切断対策。"""

MAX_SSE_CONNECTIONS_TOTAL = 50
"""SSE の全体同時接続上限 (#113 DoS 対策)。"""

MAX_SSE_CONNECTIONS_PER_ISSUE = 5
"""1 Issue あたりの SSE 同時接続上限 (#113 DoS 対策)。"""


class SseConnectionLimiter:
    """SSE 同時接続数を全体 / Issue 単位で制限する (#113 L2)。

    クリティカルセクションはカウンタの増減のみと小さく、SSE 接続は高頻度では
    ないため ``threading.Lock`` で同期する (async ループに依存せずテストからも
    同期的に検証できる)。

    Attributes:
        max_total: 全体の同時接続上限。
        max_per_issue: 1 Issue あたりの同時接続上限。
    """

    def __init__(self, *, max_total: int, max_per_issue: int) -> None:
        self.max_total = max_total
        self.max_per_issue = max_per_issue
        self._lock = threading.Lock()
        self._total = 0
        self._per_issue: dict[int, int] = {}

    def try_acquire(self, issue: int) -> bool:
        """接続枠を 1 つ確保する。上限超過なら False を返す (取得しない)。"""
        with self._lock:
            if self._total >= self.max_total:
                return False
            if self._per_issue.get(issue, 0) >= self.max_per_issue:
                return False
            self._total += 1
            self._per_issue[issue] = self._per_issue.get(issue, 0) + 1
            return True

    def release(self, issue: int) -> None:
        """確保済みの接続枠を 1 つ解放する。未取得の Issue でも安全 (負にしない)。"""
        with self._lock:
            current = self._per_issue.get(issue, 0)
            if current <= 0:
                return
            self._total = max(0, self._total - 1)
            if current == 1:
                self._per_issue.pop(issue, None)
            else:
                self._per_issue[issue] = current - 1


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


@dataclass
class _TailState:
    """1 ファイルの tail 読み出し状態 (#113 seek ベース増分読み)。

    Attributes:
        path: 対象ファイル。
        start_line: 再開時に読み飛ばす物理行数 (Last-Event-ID 由来)。
        byte_offset: 消費済みバイト位置 (最後の完全な行の直後)。
        primed: start_line までの位置決め (priming) が済んだか。
    """

    path: Path
    start_line: int
    byte_offset: int = field(default=0)
    primed: bool = field(default=False)


def _byte_offset_after_lines(data: bytes, n: int) -> int:
    """data 内で n 本の改行を読み飛ばした直後のバイト位置を返す。

    改行が n 本に満たない場合は ``len(data)`` を返す (それ以上は読まない)。
    """
    if n <= 0:
        return 0
    idx = 0
    for _ in range(n):
        nl = data.find(b"\n", idx)
        if nl == -1:
            return len(data)
        idx = nl + 1
    return idx


def _read_new_lines(state: _TailState) -> list[str]:
    """state のファイルから未消費の完全な物理行を返し、byte_offset を進める。

    seek ベースの増分読み: byte_offset 以降のみ読むため、毎 poll の計算量は
    追記バイト量に比例する (#113。従来は O(ファイルサイズ))。初回は start_line
    本の改行まで走査して位置決め (priming) する。末尾が改行で終端されていない
    行は書き込み途中の可能性があるため消費しない (torn read 防止)。縮退
    (切り詰め/ローテーションで size < byte_offset) 時のみ先頭から読み直す。

    壊れ行の判定はしない (SSE は生行を流し、UI 側でパースする)。

    Args:
        state: 対象ファイルの tail 状態 (in-place で byte_offset/primed を更新)。

    Returns:
        新規の完全な物理行 (古い順、空行も含む)。ファイル不在なら空。
    """
    path = state.path
    if not path.exists():
        return []
    try:
        with path.open("rb") as f:
            if not state.primed:
                data = f.read()
                state.byte_offset = _byte_offset_after_lines(data, state.start_line)
                state.primed = True
                chunk = data[state.byte_offset :]
            else:
                size = f.seek(0, os.SEEK_END)
                if size < state.byte_offset:
                    # 縮退 (切り詰め/ローテーション): 先頭から読み直す。
                    state.byte_offset = 0
                f.seek(state.byte_offset)
                chunk = f.read()
    except OSError:
        logger.warning("SSE tail の読み取りに失敗: %s", path, exc_info=True)
        return []

    last_nl = chunk.rfind(b"\n")
    if last_nl == -1:
        return []  # 完全な新規行なし (末尾未終端のみ)。
    complete = chunk[: last_nl + 1]
    state.byte_offset += len(complete)
    return complete.decode("utf-8", errors="replace").splitlines()


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
    events_state = _TailState(path=log_dir / "events.jsonl", start_line=start_events)
    agent_state = _TailState(path=log_dir / "agent.jsonl", start_line=start_agent)

    events_consumed = start_events
    agent_consumed = start_agent
    last_activity = time.monotonic()
    last_emit = last_activity

    while True:
        emitted = False

        for source, state in (("events", events_state), ("agent", agent_state)):
            new_lines = await asyncio.to_thread(_read_new_lines, state)
            for line in new_lines:
                # 空行も物理行として消費数 (SSE id) をカウントするが yield はしない。
                if source == "events":
                    events_consumed += 1
                else:
                    agent_consumed += 1
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
