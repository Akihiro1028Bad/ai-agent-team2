"""PhaseDispatcher (タスク振り分け)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import TaskRequest

logger = logging.getLogger(__name__)


class PhaseExecutorLike(Protocol):
    """execute(request) を持つフェーズ実行体の Protocol。

    具象 PhaseExecutor と、U5 のブリッジ (RevisePhaseExecutor 等) の両方を受ける。
    """

    async def execute(self, request: TaskRequest) -> None:
        """フェーズを実行する。"""
        ...


class RevisePhaseExecutor:
    """REVISE フェーズのトリガー別振り分け (U5 #83)。

    レビュー指摘 (既定) は ReviseExecutor、CI 失敗 (extra["trigger"]=="ci")
    は CiFixExecutor へ委譲する。提案書 §3.1「REVISE はトリガー別に処理」に対応。
    """

    def __init__(self, review_revise: PhaseExecutorLike, ci_fix: PhaseExecutorLike) -> None:
        """振り分け先の executor を受け取る。"""
        self._review_revise = review_revise
        self._ci_fix = ci_fix

    async def execute(self, request: TaskRequest) -> None:
        """trigger に応じて委譲先を切り替える。"""
        if (request.extra or {}).get("trigger") == "ci":
            await self._ci_fix.execute(request)
        else:
            await self._review_revise.execute(request)


class SplitPhaseExecutor:
    """SPLIT フェーズのステップ別振り分け (U5 #83)。

    提案 (既定) は SplitProposalExecutor、承認後の実行
    (extra["step"]=="execute") は SplitExecuteExecutor へ委譲する。
    提案→承認→実行は SPLIT フェーズ内で完結する。
    """

    def __init__(self, proposal: PhaseExecutorLike, execute_step: PhaseExecutorLike) -> None:
        """振り分け先の executor を受け取る。"""
        self._proposal = proposal
        self._execute_step = execute_step

    async def execute(self, request: TaskRequest) -> None:
        """step に応じて委譲先を切り替える。"""
        if (request.extra or {}).get("step") == "execute":
            await self._execute_step.execute(request)
        else:
            await self._proposal.execute(request)


class PhaseDispatcher:
    """タスクリクエストを適切な PhaseExecutor に振り分ける。

    TaskQueue の worker_loop から呼び出される execute() メソッドを提供し、
    request.phase に応じた具象 PhaseExecutor を選択して実行する。
    """

    def __init__(
        self,
        executors: dict[str, PhaseExecutorLike],
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
        # request.phase は Phase enum の .value (例: "type-detection") または str
        raw = request.phase.value if hasattr(request.phase, "value") else str(request.phase)
        phase_key = raw.replace("-", "_")
        executor = self._executors.get(phase_key)
        if executor is None:
            msg = f"No executor registered for phase: {request.phase}"
            raise KeyError(msg)
        await executor.execute(request)
