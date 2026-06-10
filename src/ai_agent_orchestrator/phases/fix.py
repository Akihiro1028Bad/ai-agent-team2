"""Bug 修正フェーズ (後方互換 re-export).

U5a (#94) で fix の実行ロジックは ImplementExecutor に統合された。
旧 import パス互換のため FixExecutor 名を re-export する（revise.py と同方式）。
fix 固有のプロンプト・PR 作成処理は phases/fix_flow.py を参照。
"""

from __future__ import annotations

from ai_agent_orchestrator.phases.implement import ImplementExecutor as FixExecutor

__all__ = ["FixExecutor"]
