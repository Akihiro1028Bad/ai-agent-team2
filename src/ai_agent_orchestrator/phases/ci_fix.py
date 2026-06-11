"""CI 自動修正フェーズ (共通)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ai_agent_orchestrator.phases.base import NoChangesError, PhaseExecutor

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


class CiFixExecutor(PhaseExecutor):
    """CI 失敗自動修正フェーズ (最大 3 回)。

    CI_FIX 完了後のフロー:
    1. CiFixExecutor がコード修正 (commit/push はシステムが実行)
    2. CI が自動実行される (GitHub Actions 等)
    3. Poller が CI 結果を検知
    4. CI_PASSED -> EventRouter が REVIEW に遷移
    5. CI_FAILED -> EventRouter が REVISE(trigger=ci) に再遷移 (リトライカウント確認)

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

        from ai_agent_orchestrator.phases.ci_log_parser import format_ci_summary, parse_ci_log
        from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

        summary = parse_ci_log(ci_logs)
        structured = format_ci_summary(summary)

        raw = (
            f"CIが失敗しました ({retry_count}/3回目)。修正してください。\n\n"
            f"{structured}\n\n"
            f"## 生ログ (参考)\n```\n{ci_logs[-3000:]}\n```\n\n"
            f"## 指示\n"
            f"1. 上記エラーサマリーを確認して原因を特定\n"
            f"2. コードを修正\n"
            f"3. テスト・lint・ビルドをローカルで再実行して確認\n"
            f"4. **git commit / push は不要です** (システムが行います)"
        )
        return enhance_prompt(raw, "ci-fix")

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """CI 修正結果を処理。リトライカウンタをインクリメント。

        遷移は行わない。CI 結果は次回ポーリングで検知される。

        エラーハンドリング:
        - エージェントがコミットしなかった場合: リトライ上限未満なら SUSPENDED にせず継続
        - リトライ上限 (3回) に達した場合: RuntimeError を再送出して SUSPENDED に遷移

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        # リトライカウンタを先にインクリメント (例外発生時も確実に更新されるよう先行実行)
        await self._sm.increment_ci_retry(self._issue_key(request))

        state = self._sm.get_state(self._issue_key(request))
        if state:
            state.session_id = result.session_id

        try:
            await self._finalize_phase_commit(
                request,
                summary="CI 失敗を修正",
                commit_type="fix",
                branch_prefix="feature",
            )
        except NoChangesError as exc:
            # エージェントがコードを変更しなかった場合
            retry_count = state.retry_count if state else 0
            logger.warning(
                "Issue #%d: CI_FIX agent did not commit (attempt %d/3): %s",
                request.issue_number,
                retry_count,
                exc,
            )
            if retry_count >= 3:
                # 上限到達: base.execute() の _handle_error() で SUSPENDED に遷移させる
                raise
            # 上限未満: phase:ci-fix ラベルを維持して次のポーリングを待つ
            client = await self._get_client(request.repo)
            try:
                await client.create_comment(
                    request.repo,
                    request.issue_number,
                    f"⚠️ CI修正エージェントがコードを変更できませんでした ({retry_count}/3回目)。次回リトライします。",
                )
            except Exception:
                logger.warning(
                    "Failed to post retry comment for issue #%d",
                    request.issue_number,
                    exc_info=True,
                )
            return

        # CI結果待ち: phase:ci-fix ラベルを維持
        # (ポーラーが ci-fix ラベルの Issue を監視して CI 結果を検知するため)
