"""CI 自動修正フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class CiFixExecutor(PhaseExecutor):
    """CI 失敗自動修正フェーズ (最大 3 回)。

    CI_FIX 完了後のフロー:
    1. CiFixExecutor がコード修正 + git push
    2. CI が自動実行される (GitHub Actions 等)
    3. Poller が CI 結果を検知
    4. CI_PASSED -> EventRouter が IMPL_REVIEW に遷移
    5. CI_FAILED -> EventRouter が CI_FIX に再遷移 (リトライカウント確認)

    このフェーズ自身は遷移を行わず、CI 結果のポーリングに任せる。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """CI 修正プロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            プロンプト文字列。
        """
        extra = getattr(request, "extra", {}) or {}
        ci_logs = extra.get("ci_logs", "")
        retry_count = extra.get("retry_count", 1)

        return (
            f"CIが失敗しました ({retry_count}/3回目)。修正してください。\n\n"
            f"## CI失敗ログ\n{ci_logs}\n\n"
            f"## 指示\n"
            f"1. CI失敗ログを分析して原因を特定\n"
            f"2. コードを修正\n"
            f"3. テスト・lint・ビルドをローカルで再実行して確認\n"
            f"4. git commit して Push"
        )

    async def process_result(
        self, request: TaskRequest, result: AgentResult
    ) -> None:
        """CI 修正結果を処理。リトライカウンタをインクリメント。

        遷移は行わない。CI 結果は次回ポーリングで検知される。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.increment_ci_retry(request.issue_number)
        # CI 結果は次回ポーリングで検知
