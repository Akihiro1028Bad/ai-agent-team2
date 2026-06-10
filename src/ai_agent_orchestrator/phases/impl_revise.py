"""実装修正フェーズ (REVISE 共通基底のサブクラス)."""

from __future__ import annotations

from ai_agent_orchestrator.phases.revise_common import ReviseExecutorBase


class ImplReviseExecutor(ReviseExecutorBase):
    """実装のレビュー指摘対応フェーズ (セッション継続)。

    レビューコメントを「修正要求 / 質問」として処理し、
    修正要求にはコード修正、質問には回答を返して IMPL_REVIEW に再遷移する。
    共通ロジックは ReviseExecutorBase を参照。
    """

    phase_name = "impl-revise"
    next_phase = "impl-review"
    target_description = "コード"
    commit_summary = "実装レビュー指摘に対応"
    commit_type = "fix"
    notification_type = "impl_revised"
    notification_message = "の実装を修正しました"
    next_action = "→ 実装PRを再レビューしてください"
