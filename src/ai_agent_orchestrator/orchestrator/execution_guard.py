"""フェーズ実行中の外部状態遷移を防止するガード。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import IssueKey

logger = logging.getLogger(__name__)


class ExecutionGuard:
    """フェーズ実行中に EventRouter の状態遷移を遅延させるガード。

    Executor が acquire() でガードを取得している間、EventRouter は
    当該 Issue への遷移を実行せず defer_event() で保留する。
    Executor が解放した後、保留イベントは呼び出し元でリプレイされる。
    """

    def __init__(self) -> None:
        self._executing: set[IssueKey] = set()
        self._deferred: dict[IssueKey, list[object]] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def guard(self, issue_key: IssueKey) -> AsyncGenerator[None]:
        """Issue のフェーズ実行を保護するコンテキストマネージャ。

        Args:
            issue_key: 保護する IssueKey (repo, issue_number)。

        Yields:
            None
        """
        async with self._lock:
            self._executing.add(issue_key)
            self._deferred.setdefault(issue_key, [])
        try:
            yield
        finally:
            async with self._lock:
                self._executing.discard(issue_key)

    async def is_executing(self, issue_key: IssueKey) -> bool:
        """Issue が現在実行中かどうかを返す。

        Args:
            issue_key: 確認する IssueKey (repo, issue_number)。

        Returns:
            実行中なら True。
        """
        async with self._lock:
            return issue_key in self._executing

    async def defer_event(self, issue_key: IssueKey, event: object) -> None:
        """実行完了後にリプレイするイベントを保留する。

        Args:
            issue_key: IssueKey (repo, issue_number)。
            event: 保留するイベントオブジェクト。
        """
        async with self._lock:
            self._deferred.setdefault(issue_key, []).append(event)
        logger.info(
            "Issue #%d (%s): deferred event %s (currently executing)",
            issue_key[1],
            issue_key[0],
            type(event).__name__,
        )

    async def drain_deferred(self, issue_key: IssueKey) -> list[object]:
        """保留イベントを全て取り出して返す。

        Args:
            issue_key: IssueKey (repo, issue_number)。

        Returns:
            保留イベントのリスト (順序保持)。
        """
        async with self._lock:
            return self._deferred.pop(issue_key, [])
