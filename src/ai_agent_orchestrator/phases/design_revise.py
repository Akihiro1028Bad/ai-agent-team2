"""設計修正フェーズ (REVISE 共通基底のサブクラス)."""

from __future__ import annotations

from ai_agent_orchestrator.phases.revise_common import ReviseExecutorBase


class DesignReviseExecutor(ReviseExecutorBase):
    """設計書のレビュー指摘対応フェーズ (セッション継続)。

    レビューコメントを「修正要求 / 質問」として処理し、
    修正要求には設計書修正、質問には回答を返して DESIGN_REVIEW に再遷移する。
    共通ロジックは ReviseExecutorBase を参照。
    """

    phase_name = "design-revise"
    next_phase = "design-review"
    target_description = "設計書 (docs/designs/ 配下)"
    commit_summary = "設計レビュー指摘に対応"
    commit_type = "docs"
    notification_type = "design_revised"
    notification_message = "の設計書を修正しました"
    next_action = "→ 設計PRを再レビューしてください"
