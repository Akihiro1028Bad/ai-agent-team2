"""design.json 導出 (anchor 付与) のテスト (#89 Unit A)."""

from __future__ import annotations

from ai_agent_orchestrator.api.design import build_design_response


def test_absent_plan_returns_not_present() -> None:
    r = build_design_response(None)
    assert r.present is False
    assert r.reason
    assert r.summary is None
    assert r.test_cases == []
    assert r.architecture == []
    assert r.subtasks == []


def test_light_plan_has_anchors_and_no_architecture() -> None:
    plan = {
        "schema_version": 1,
        "plan_depth": "light",
        "ui_impact": True,
        "summary": "概要テキスト",
        "test_cases": ["ケース1", "ケース2"],
    }
    r = build_design_response(plan)
    assert r.present is True
    assert r.plan_depth == "light"
    assert r.ui_impact is True
    assert r.summary is not None
    assert r.summary.anchor == "sum-1"
    assert r.summary.text == "概要テキスト"
    assert [tc.anchor for tc in r.test_cases] == ["tc-01", "tc-02"]
    assert [tc.text for tc in r.test_cases] == ["ケース1", "ケース2"]
    assert r.architecture == []
    assert r.subtasks == []
    assert r.reason is None


def test_full_plan_splits_architecture_into_paragraphs() -> None:
    plan = {
        "schema_version": 1,
        "plan_depth": "full",
        "ui_impact": False,
        "summary": "s",
        "test_cases": ["t"],
        "architecture": "段落その1\n\n段落その2\n\n段落その3",
        "subtasks": [{"id": 3, "title": "サブA"}, {"id": None, "title": "サブB"}],
    }
    r = build_design_response(plan)
    assert r.ui_impact is False
    assert [a.anchor for a in r.architecture] == ["arch-1", "arch-2", "arch-3"]
    assert [a.text for a in r.architecture] == ["段落その1", "段落その2", "段落その3"]
    assert [s.anchor for s in r.subtasks] == ["st-1", "st-2"]
    assert r.subtasks[0].id == 3
    assert r.subtasks[0].title == "サブA"
    assert r.subtasks[1].id is None
    assert r.subtasks[1].title == "サブB"


def test_empty_summary_becomes_none() -> None:
    r = build_design_response({"plan_depth": "light", "summary": "", "test_cases": []})
    assert r.present is True
    assert r.summary is None
    assert r.test_cases == []


def test_malformed_plan_fields_are_coerced_safely() -> None:
    # state.json 由来で型が壊れていても例外を出さず安全側へ倒す
    plan = {
        "plan_depth": "full",
        "ui_impact": "yes",  # bool でない → None
        "summary": ["not", "a", "string"],  # str でない → None 扱い (空)
        "test_cases": "単一文字列",  # str → 1 要素へ救済
        "architecture": 123,  # str でない → 空
        "subtasks": "bad",  # list でない → 空
    }
    r = build_design_response(plan)
    assert r.ui_impact is None
    assert r.summary is None
    assert [tc.text for tc in r.test_cases] == ["単一文字列"]
    assert r.architecture == []
    assert r.subtasks == []
