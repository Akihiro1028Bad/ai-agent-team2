"""REVISE フェーズ (U5 #83: レビュー対応の統一 executor).

旧 ImplReviseExecutor / DesignReviseExecutor を統合した REVISE フェーズの
実装。レビュー指摘の分類 (修正/質問/nit) と対応は ReviseExecutorBase を参照。
CI 失敗トリガー (extra["trigger"]=="ci") は dispatcher のブリッジで
CiFixExecutor 側へ振り分けられるため、本クラスはレビュー指摘のみを扱う。
"""

from __future__ import annotations

from ai_agent_orchestrator.phases.revise_common import ReviseExecutorBase


class ReviseExecutor(ReviseExecutorBase):
    """レビュー指摘対応フェーズ (セッション継続)。

    レビューコメントを「修正要求 / 質問」として処理し、
    対応後に REVIEW へ再遷移する (next_phase は基底の "review")。
    """


__all__ = ["ReviseExecutor"]
