"""PhaseDispatcher (タスク振り分け)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import TaskRequest
    from ai_agent_orchestrator.phases.base import PhaseExecutor

logger = logging.getLogger(__name__)


class PhaseDispatcher:
    """タスクリクエストを適切な PhaseExecutor に振り分ける。

    TaskQueue の worker_loop から呼び出される execute() メソッドを提供し、
    request.phase に応じた具象 PhaseExecutor を選択して実行する。
    """

    def __init__(
        self,
        executors: dict[str, PhaseExecutor],
    ) -> None:
        """PhaseDispatcher を初期化する。

        Args:
            executors: フェーズ名 -> PhaseExecutor のマッピング。
                       例: {"type_detection": TypeDetectionExecutor(...), ...}
        """
        self._executors = executors

    async def execute(self, request: TaskRequest) -> None:
        """タスクリクエストに応じたフェーズを実行する。

        Args:
            request: タスクリクエスト。

        Raises:
            KeyError: 未登録のフェーズ。
        """
        phase_key = str(request.phase).replace("-", "_")
        executor = self._executors.get(phase_key)
        if executor is None:
            msg = f"No executor registered for phase: {request.phase}"
            raise KeyError(msg)
        await executor.execute(request)
