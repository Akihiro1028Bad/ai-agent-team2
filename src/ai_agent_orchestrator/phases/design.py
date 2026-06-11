"""設計書作成フェーズ (後方互換 re-export).

U3 (#81) で design の実行ロジックは PlanExecutor (plan_depth=full) に
統合された。旧 import パス互換のため DesignExecutor 名を re-export する
(fix.py / revise.py と同方式)。
"""

from __future__ import annotations

from ai_agent_orchestrator.phases.plan import _MAX_DESIGN_REVALIDATE
from ai_agent_orchestrator.phases.plan import PlanExecutor as DesignExecutor

__all__ = ["_MAX_DESIGN_REVALIDATE", "DesignExecutor"]
