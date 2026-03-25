"""レビュー対応フェーズ (後方互換性のためのエイリアス)."""

from ai_agent_orchestrator.phases.design_revise import (
    DesignReviseExecutor,
)
from ai_agent_orchestrator.phases.impl_revise import (
    ImplReviseExecutor,
)

__all__ = ["DesignReviseExecutor", "ImplReviseExecutor"]
