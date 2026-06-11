"""Bug 分析フェーズ (後方互換 re-export).

U3 (#81) で analysis の実行ロジックは PlanExecutor (plan_depth=light) に
統合された。旧 import パス互換のため AnalysisExecutor 名を re-export する
(fix.py / revise.py と同方式)。
"""

from __future__ import annotations

from ai_agent_orchestrator.phases.plan import PlanExecutor as AnalysisExecutor

__all__ = ["AnalysisExecutor"]
