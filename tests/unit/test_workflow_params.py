"""Tests for WorkflowParams and derive_workflow_params (U5c #95).

タイプ別分岐をパラメータ (plan_depth / needs_split / approval_style) に
変換する deriver の検証。INTAKE が決めたタイプから 1 本道のパラメータ集合を
導出し、以降は同一コードパスで処理されることを保証する。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ai_agent_orchestrator.models import (
    WorkflowParams,
    derive_workflow_params,
)

# ---------------------------------------------------------------------------
# WorkflowParams: frozen 値オブジェクト
# ---------------------------------------------------------------------------


def test_workflow_params_is_frozen() -> None:
    params = WorkflowParams(plan_depth="light", needs_split=False, approval_style="reaction")
    with pytest.raises(FrozenInstanceError):
        params.plan_depth = "full"  # type: ignore[misc]


def test_workflow_params_fields() -> None:
    params = WorkflowParams(plan_depth="full", needs_split=True, approval_style="pr")
    assert params.plan_depth == "full"
    assert params.needs_split is True
    assert params.approval_style == "pr"


# ---------------------------------------------------------------------------
# derive_workflow_params: issue_type -> パラメータ集合
# ---------------------------------------------------------------------------


def test_derive_bug_is_light_no_split_reaction() -> None:
    """bug は light / 分割なし / リアクション承認。"""
    params = derive_workflow_params("bug")
    assert params.plan_depth == "light"
    assert params.needs_split is False
    assert params.approval_style == "reaction"


def test_derive_feature_m_is_full_no_split_pr() -> None:
    """feature-m は full / 分割なし / PR 承認。"""
    params = derive_workflow_params("feature-m")
    assert params.plan_depth == "full"
    assert params.needs_split is False
    assert params.approval_style == "pr"


def test_derive_feature_l_is_full_split_pr() -> None:
    """feature-l は full / 分割あり / PR 承認。"""
    params = derive_workflow_params("feature-l")
    assert params.plan_depth == "full"
    assert params.needs_split is True
    assert params.approval_style == "pr"


def test_derive_empty_defaults_to_full() -> None:
    """未判定 ("") は安全側 (full / 分割なし / PR) にフォールバック。"""
    params = derive_workflow_params("")
    assert params.plan_depth == "full"
    assert params.needs_split is False
    assert params.approval_style == "pr"


def test_derive_unknown_defaults_to_full() -> None:
    """未知タイプも安全側にフォールバックし例外を投げない。"""
    params = derive_workflow_params("something-unexpected")
    assert params.plan_depth == "full"
    assert params.needs_split is False


# ---------------------------------------------------------------------------
# 不変条件: light <=> reaction 承認 (現状は plan_depth と co-vary)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("issue_type", ["bug", "feature-m", "feature-l"])
def test_light_iff_reaction(issue_type: str) -> None:
    """light は reaction 承認、full は pr 承認に一意対応する。"""
    params = derive_workflow_params(issue_type)
    if params.plan_depth == "light":
        assert params.approval_style == "reaction"
    else:
        assert params.approval_style == "pr"
