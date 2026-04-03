"""フェーズ実行中の外部状態遷移を防止するガード。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class ExecutionGuard:
    """フェーズ実行中に EventRouter の状態遷移を遅延させるガード。

    Executor が acquire() でガードを取得している間、EventRouter は
    当該 Issue への遷移を実行せず defer_event() で保留する。
    Executor が解放した後、保留イベントは呼び出し元でリプレイされる。
    """

    def __init__(self) -> None:
        self._executing: set[int] = set()
        self._deferred: dict[int, list[object]] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def guard(self, issue_number: int) -> AsyncGenerator[None]:
        """Issue のフェーズ実行を保護するコンテキストマネージャ。

        Args:
            issue_number: 保護する Issue 番号。

        Yields:
            None
        """
        async with self._lock:
            self._executing.add(issue_number)
            self._deferred.setdefault(issue_number, [])
        try:
            yield
        finally:
            async with self._lock:
                self._executing.discard(issue_number)

    async def is_executing(self, issue_number: int) -> bool:
        """Issue が現在実行中かどうかを返す。

        Args:
            issue_number: 確認する Issue 番号。

        Returns:
            実行中なら True。
        """
        async with self._lock:
            return issue_number in self._executing

    async def defer_event(self, issue_number: int, event: object) -> None:
        """実行完了後にリプレイするイベントを保留する。

        Args:
            issue_number: Issue 番号。
            event: 保留するイベントオブジェクト。
        """
        async with self._lock:
            self._deferred.setdefault(issue_number, []).append(event)
        logger.info(
            "Issue #%d: deferred event %s (currently executing)",
            issue_number,
            type(event).__name__,
        )

    async def drain_deferred(self, issue_number: int) -> list[object]:
        """保留イベントを全て取り出して返す。

        Args:
            issue_number: Issue 番号。

        Returns:
            保留イベントのリスト (順序保持)。
        """
        async with self._lock:
            return self._deferred.pop(issue_number, [])
