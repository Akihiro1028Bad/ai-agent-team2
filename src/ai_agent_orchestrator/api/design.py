"""plan_json から design.json (anchor 付き構造化設計) を導出する純関数 (#89).

PLAN フェーズが生成する ``IssueState.plan_json`` を、Web UI のインラインレビューが
参照できる **安定 anchor ID 付き** の構造へ変換する。state.json 由来で型が壊れて
いても例外を投げず安全側へ倒す (読み取り API の堅牢性方針)。
"""

from __future__ import annotations

from typing import Any

from ai_agent_orchestrator.api.schemas import (
    DesignAnchor,
    DesignResponse,
    DesignSubtask,
)

_ABSENT_REASON = "設計はまだ生成されていません (PLAN フェーズ未完了)。"


def _as_text(value: object) -> str:
    """表示用テキストを安全に文字列へ正規化する (非文字列は空文字)."""
    return value if isinstance(value, str) else ""


def _as_test_cases(value: object) -> list[str]:
    """test_cases を list[str] に正規化する (str は 1 要素へ救済)."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(t) for t in value]
    return []


def _split_paragraphs(text: str) -> list[str]:
    """空行区切りで段落へ分割する (空段落は除去)."""
    return [block.strip() for block in text.split("\n\n") if block.strip()]


def build_design_response(plan_json: dict[str, Any] | None) -> DesignResponse:
    """plan_json から anchor 付き DesignResponse を構築する (#89).

    anchor 規則 (決定的・並び順安定):
      - summary: ``sum-1`` (非空時のみ)
      - test_cases: ``tc-01``, ``tc-02``, … (1 始まり・2 桁ゼロ詰め)
      - architecture: 段落ごとに ``arch-1``, ``arch-2``, …
      - subtasks: ``st-1``, ``st-2``, … (序数ベース。元 id は id フィールドに保持)

    Args:
        plan_json: ``IssueState.plan_json`` (PLAN 未完了なら None)。

    Returns:
        DesignResponse。plan_json が None なら present=false + reason。
    """
    if plan_json is None:
        return DesignResponse(present=False, reason=_ABSENT_REASON)

    plan_depth = _as_text(plan_json.get("plan_depth")) or None
    ui_impact_raw = plan_json.get("ui_impact")
    ui_impact = ui_impact_raw if isinstance(ui_impact_raw, bool) else None

    summary_text = _as_text(plan_json.get("summary"))
    summary = DesignAnchor(anchor="sum-1", text=summary_text) if summary_text else None

    test_cases = [
        DesignAnchor(anchor=f"tc-{i:02d}", text=text)
        for i, text in enumerate(_as_test_cases(plan_json.get("test_cases")), start=1)
    ]

    architecture = [
        DesignAnchor(anchor=f"arch-{i}", text=text)
        for i, text in enumerate(_split_paragraphs(_as_text(plan_json.get("architecture"))), start=1)
    ]

    raw_subtasks = plan_json.get("subtasks")
    subtasks: list[DesignSubtask] = []
    if isinstance(raw_subtasks, list):
        for i, item in enumerate(raw_subtasks, start=1):
            obj = item if isinstance(item, dict) else {}
            raw_id = obj.get("id")
            subtasks.append(
                DesignSubtask(
                    anchor=f"st-{i}",
                    id=raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None,
                    title=str(obj.get("title", "")) if isinstance(item, dict) else str(item),
                )
            )

    return DesignResponse(
        present=True,
        plan_depth=plan_depth,
        ui_impact=ui_impact,
        summary=summary,
        test_cases=test_cases,
        architecture=architecture,
        subtasks=subtasks,
    )
