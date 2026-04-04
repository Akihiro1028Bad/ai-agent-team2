"""Tests for ai_agent_orchestrator.models (TC-M01 through TC-M10)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from ai_agent_orchestrator.models import (
    PHASE_CONFIG,
    VALID_TRANSITIONS,
    AgentResult,
    ApprovalMethod,
    ErrorCategory,
    EventType,
    IssueState,
    IssueType,
    Phase,
    PhaseConfig,
    PhaseContext,
    PhaseResult,
    PollEvent,
    TaskRequest,
)

# ---------------------------------------------------------------------------
# TC-M01: Phase Enum 値の完全性
# ---------------------------------------------------------------------------


def test_phase_has_19_values() -> None:
    assert len(Phase) == 20


def test_phase_values() -> None:
    expected = {
        "type-detection",
        "hearing",
        "hearing-wait",
        "analysis",
        "plan-review",
        "design",
        "design-review",
        "design-revise",
        "planning",
        "plan-validation",
        "split-proposal",
        "split-execute",
        "blocked",
        "implement",
        "ci-fix",
        "impl-review",
        "impl-revise",
        "done",
        "suspended",
        "fix",
    }
    assert {p.value for p in Phase} == expected


# ---------------------------------------------------------------------------
# TC-M02: EventType Enum 値の完全性
# ---------------------------------------------------------------------------


def test_event_type_has_13_values() -> None:
    assert len(EventType) == 13


def test_event_type_values() -> None:
    expected = {
        "new_issue",
        "issue_comment",
        "design_pr_approved",
        "design_pr_commented",
        "impl_pr_approved",
        "impl_pr_commented",
        "impl_pr_merged",
        "ci_result",
        "plan_reaction_added",
        "plan_comment_added",
        "split_approved",
        "split_modified",
        "hearing_timeout",
    }
    assert {e.value for e in EventType} == expected


# ---------------------------------------------------------------------------
# TC-M03: IssueType / ErrorCategory / ApprovalMethod の値検証
# ---------------------------------------------------------------------------


def test_issue_type_values() -> None:
    assert IssueType.BUG == "bug"
    assert IssueType.FEATURE_M == "feature-m"
    assert IssueType.FEATURE_L == "feature-l"
    assert len(IssueType) == 3


def test_error_category_values() -> None:
    assert ErrorCategory.TRANSIENT == "transient"
    assert ErrorCategory.AUTH == "auth"
    assert ErrorCategory.GIT_CONFLICT == "git_conflict"
    assert ErrorCategory.OUTPUT_INVALID == "output_invalid"
    assert ErrorCategory.CI_FAILURE == "ci_failure"
    assert len(ErrorCategory) == 5


def test_approval_method_values() -> None:
    assert ApprovalMethod.REACTION == "reaction"
    assert ApprovalMethod.PR_APPROVE == "pr-approve"
    assert len(ApprovalMethod) == 2


# ---------------------------------------------------------------------------
# TC-M04: TaskRequest の生成と優先度比較
# ---------------------------------------------------------------------------


def test_task_request_creation() -> None:
    tr = TaskRequest(issue_number=42, repo="owner/repo", phase=Phase.IMPLEMENT)
    assert tr.issue_number == 42
    assert tr.repo == "owner/repo"
    assert tr.phase == Phase.IMPLEMENT
    assert tr.priority == 5  # デフォルト値


def test_task_request_lt_lower_priority_wins() -> None:
    high = TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=1)
    low = TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=10)
    assert high < low
    assert not low < high


def test_task_request_lt_equal_priority() -> None:
    a = TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=5)
    b = TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=5)
    assert not a < b
    assert not b < a


def test_task_request_sorting() -> None:
    tasks = [
        TaskRequest(issue_number=3, repo="o/r", phase=Phase.IMPLEMENT, priority=10),
        TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=1),
        TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=5),
    ]
    sorted_tasks = sorted(tasks)
    assert [t.issue_number for t in sorted_tasks] == [1, 2, 3]


# ---------------------------------------------------------------------------
# TC-M05: IssueState の生成と issue_type フィールド
# ---------------------------------------------------------------------------


def test_issue_state_creation_minimal() -> None:
    state = IssueState(issue_number=10, phase=Phase.HEARING)
    assert state.issue_number == 10
    assert state.phase == Phase.HEARING
    assert state.issue_type == ""
    assert state.repo == ""
    assert state.session_id is None
    assert state.pr_number is None
    assert state.design_pr_number is None
    assert state.retry_count == 0
    assert state.created_at == ""
    assert state.updated_at == ""


def test_issue_state_with_issue_type() -> None:
    state = IssueState(
        issue_number=20,
        phase=Phase.ANALYSIS,
        issue_type="bug",
        repo="owner/repo",
    )
    assert state.issue_type == "bug"
    assert state.repo == "owner/repo"


def test_issue_state_is_mutable() -> None:
    state = IssueState(issue_number=1, phase=Phase.HEARING)
    state.phase = Phase.DESIGN
    assert state.phase == Phase.DESIGN


# ---------------------------------------------------------------------------
# TC-M06: VALID_TRANSITIONS の検証
# ---------------------------------------------------------------------------


def test_valid_transitions_type_detection() -> None:
    """TYPE_DETECTION から HEARING と ANALYSIS への遷移が許可される."""
    assert Phase.HEARING in VALID_TRANSITIONS[Phase.TYPE_DETECTION]
    assert Phase.ANALYSIS in VALID_TRANSITIONS[Phase.TYPE_DETECTION]
    assert Phase.IMPLEMENT not in VALID_TRANSITIONS[Phase.TYPE_DETECTION]


def test_valid_transitions_implement() -> None:
    """IMPLEMENT から CI_FIX, IMPL_REVIEW, SUSPENDED への遷移が許可される."""
    allowed = VALID_TRANSITIONS[Phase.IMPLEMENT]
    assert Phase.CI_FIX in allowed
    assert Phase.IMPL_REVIEW in allowed
    assert Phase.SUSPENDED in allowed
    assert Phase.DONE not in allowed  # IMPLEMENT -> DONE は不正


def test_valid_transitions_suspended_allows_all() -> None:
    """SUSPENDED からは全フェーズへの遷移が可能."""
    suspended_targets = VALID_TRANSITIONS[Phase.SUSPENDED]
    for phase in Phase:
        assert phase in suspended_targets


def test_valid_transitions_all_active_phases_can_suspend() -> None:
    """全ての実行フェーズから SUSPENDED への遷移が可能."""
    for phase, targets in VALID_TRANSITIONS.items():
        if phase not in (Phase.DONE, Phase.BLOCKED, Phase.PLAN_REVIEW):
            assert Phase.SUSPENDED in targets, f"{phase} cannot transition to SUSPENDED"


def test_valid_transitions_blocked() -> None:
    """BLOCKED からはワークフロー開始フェーズのみ許可."""
    allowed = VALID_TRANSITIONS[Phase.BLOCKED]
    assert Phase.HEARING in allowed
    assert Phase.ANALYSIS in allowed
    assert Phase.IMPLEMENT in allowed
    assert Phase.SUSPENDED not in allowed


# ---------------------------------------------------------------------------
# TC-M07: AgentResult / PhaseResult のイミュータブル性
# ---------------------------------------------------------------------------


def test_agent_result_is_frozen() -> None:
    result = AgentResult(
        session_id="sess-1",
        output="done",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=10.0,
    )
    with pytest.raises(FrozenInstanceError):
        result.output = "changed"  # type: ignore[misc]


def test_phase_result_creation() -> None:
    pr = PhaseResult(
        phase="hearing",
        cost_usd=0.3,
        duration_sec=60,
        output_summary="Requirements gathered",
    )
    assert pr.review_comments == 0
    assert pr.feedback is None
    assert pr.resolution is None


# ---------------------------------------------------------------------------
# TC-M08: PhaseConfig と PHASE_CONFIG 辞書の検証
# ---------------------------------------------------------------------------


def test_phase_config_creation() -> None:
    pc = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan")
    assert pc.max_budget_usd == 1.0
    assert pc.timeout_sec == 600
    assert pc.permission_mode == "plan"
    assert pc.resume is False
    assert pc.model == "sonnet"


def test_phase_config_with_resume() -> None:
    pc = PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
        resume=True,
    )
    assert pc.resume is True


def test_phase_config_model_default_is_sonnet() -> None:
    pc = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan")
    assert pc.model == "sonnet"


def test_phase_config_model_can_be_overridden() -> None:
    pc = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan", model="opus")
    assert pc.model == "opus"


def test_phase_config_dict_has_all_phases() -> None:
    expected_keys = {
        "type_detection",
        "hearing",
        "analysis",
        "design",
        "design_revise",
        "planning",
        "split_proposal",
        "implement",
        "fix",
        "ci_fix",
        "impl_revise",
    }
    assert set(PHASE_CONFIG.keys()) == expected_keys


def test_phase_config_implement_budget() -> None:
    assert PHASE_CONFIG["implement"].max_budget_usd == 10.0
    assert PHASE_CONFIG["implement"].timeout_sec == 3600
    assert PHASE_CONFIG["implement"].permission_mode == "bypassPermissions"


# ---------------------------------------------------------------------------
# TC-M09: PollEvent の frozen 検証 + フィールドデフォルト値
# ---------------------------------------------------------------------------


def test_poll_event_is_frozen() -> None:
    repo_mock = MagicMock()
    event = PollEvent(type="new_issue", repo=repo_mock)
    with pytest.raises(FrozenInstanceError):
        event.type = "changed"  # type: ignore[misc]


def test_poll_event_defaults() -> None:
    repo_mock = MagicMock()
    event = PollEvent(type="new_issue", repo=repo_mock)
    assert event.type == "new_issue"
    assert event.repo is repo_mock
    assert event.issue is None
    assert event.comment is None
    assert event.pr is None
    assert event.error is None


# ---------------------------------------------------------------------------
# TC-M10: PhaseContext の frozen 検証 + フィールドデフォルト値
# ---------------------------------------------------------------------------


def test_phase_context_is_frozen() -> None:
    ctx = PhaseContext(
        issue_number=1,
        repo_owner="owner",
        repo_name="repo",
        phase="hearing",
        worktree_path="/tmp/wt",
    )
    with pytest.raises(FrozenInstanceError):
        ctx.phase = "design"  # type: ignore[misc]


def test_phase_context_defaults() -> None:
    ctx = PhaseContext(
        issue_number=42,
        repo_owner="myorg",
        repo_name="myapp",
        phase="implement",
        worktree_path="/workspace/wt-42",
    )
    assert ctx.issue_number == 42
    assert ctx.repo_owner == "myorg"
    assert ctx.repo_name == "myapp"
    assert ctx.phase == "implement"
    assert ctx.worktree_path == "/workspace/wt-42"
    assert ctx.resume_session_id is None
    assert ctx.extra is None
