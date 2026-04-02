"""データモデル定義 (Enum, dataclass)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from githubkit.versions.latest.models import (
        Issue,
        IssueComment,
        PullRequest,
    )

    from ai_agent_orchestrator.config.settings import RepositoryConfig


# ---------------------------------------------------------------------------
# 1. Enum 定義
# ---------------------------------------------------------------------------


class IssueType(StrEnum):
    """Issueのタスクタイプ."""

    BUG = "bug"
    FEATURE_S = "feature-s"
    FEATURE_M = "feature-m"
    FEATURE_L = "feature-l"


class Phase(str, Enum):  # noqa: UP042
    """Issueのフェーズ."""

    # タイプ判定
    TYPE_DETECTION = "type-detection"

    # Bug専用
    ANALYSIS = "analysis"
    FIX = "fix"

    # Feature-S専用
    PLAN_BRIEF = "plan-brief"
    PLAN_REVIEW = "plan-review"

    # Feature-M/L共通
    HEARING = "hearing"
    HEARING_WAIT = "hearing-wait"
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"
    PLANNING = "planning"

    # Feature-L専用
    SPLIT_PROPOSAL = "split-proposal"
    SPLIT_EXECUTE = "split-execute"

    # 依存待ち
    BLOCKED = "blocked"

    # 共通フェーズ
    IMPLEMENT = "implement"
    CI_FIX = "ci-fix"
    IMPL_REVIEW = "impl-review"
    IMPL_REVISE = "impl-revise"

    # 終了状態
    DONE = "done"
    SUSPENDED = "suspended"


class EventType(str, Enum):  # noqa: UP042
    """ポーリングイベント種別."""

    NEW_ISSUE = "new_issue"
    ISSUE_COMMENT = "issue_comment"
    DESIGN_PR_APPROVED = "design_pr_approved"
    DESIGN_PR_COMMENTED = "design_pr_commented"
    IMPL_PR_APPROVED = "impl_pr_approved"
    IMPL_PR_COMMENTED = "impl_pr_commented"
    IMPL_PR_MERGED = "impl_pr_merged"
    CI_RESULT = "ci_result"
    PLAN_REACTION_ADDED = "plan_reaction_added"
    PLAN_COMMENT_ADDED = "plan_comment_added"
    SPLIT_APPROVED = "split_approved"
    SPLIT_MODIFIED = "split_modified"
    HEARING_TIMEOUT = "hearing_timeout"


class ErrorCategory(StrEnum):
    """エラー分類."""

    TRANSIENT = "transient"
    AUTH = "auth"
    GIT_CONFLICT = "git_conflict"
    OUTPUT_INVALID = "output_invalid"
    CI_FAILURE = "ci_failure"


class ApprovalMethod(StrEnum):
    """方針承認方法."""

    REACTION = "reaction"
    PR_APPROVE = "pr-approve"


# ---------------------------------------------------------------------------
# 2. Dataclass 定義
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentResult:
    """エージェント実行結果."""

    session_id: str
    output: str
    tool_uses: list[dict[str, Any]]
    cost_usd: float
    duration_sec: float


@dataclass(frozen=True)
class PhaseContext:
    """フェーズ実行に必要なコンテキスト."""

    issue_number: int
    repo_owner: str
    repo_name: str
    phase: str
    worktree_path: str
    resume_session_id: str | None = None
    extra: dict[str, Any] | None = None


@dataclass
class TaskRequest:
    """タスク実行リクエスト."""

    issue_number: int
    repo: str
    phase: Phase
    priority: int = 5

    def __lt__(self, other: TaskRequest) -> bool:
        """PriorityQueue での優先度比較。値が小さいほど優先。"""
        return self.priority < other.priority


@dataclass
class IssueState:
    """Issue単位の状態."""

    issue_number: int
    phase: Phase
    issue_type: str = ""
    repo: str = ""
    session_id: str | None = None
    pr_number: int | None = None
    design_pr_number: int | None = None
    retry_count: int = 0
    branch_head_sha: str | None = None
    impl_iteration: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class PhaseResult:
    """各フェーズの実行結果."""

    phase: str
    cost_usd: float
    duration_sec: int
    output_summary: str
    review_comments: int = 0
    feedback: str | None = None
    resolution: str | None = None


@dataclass(frozen=True)
class PollEvent:
    """ポーリングで検知されたイベント."""

    type: str
    repo: RepositoryConfig
    issue: Issue | None = None
    comment: IssueComment | None = None
    pr: PullRequest | None = None
    extra: dict[str, Any] | None = None
    error: Exception | None = None


@dataclass
class PhaseConfig:
    """フェーズごとの実行設定."""

    max_budget_usd: float
    timeout_sec: int
    permission_mode: str
    resume: bool = False


# ---------------------------------------------------------------------------
# 3. VALID_TRANSITIONS 辞書
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    # 共通: 初期
    Phase.TYPE_DETECTION: [Phase.HEARING, Phase.ANALYSIS, Phase.SUSPENDED],
    # Bug ワークフロー
    Phase.ANALYSIS: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.FIX: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],
    # Feature-S ワークフロー
    Phase.PLAN_BRIEF: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.PLAN_REVIEW: [Phase.FIX, Phase.IMPLEMENT, Phase.PLAN_BRIEF, Phase.ANALYSIS],
    # Feature-M ワークフロー
    Phase.HEARING: [
        Phase.DESIGN,
        Phase.PLAN_BRIEF,
        Phase.SPLIT_PROPOSAL,
        Phase.ANALYSIS,
        Phase.SUSPENDED,
    ],
    Phase.DESIGN: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.DESIGN_REVIEW: [Phase.PLANNING, Phase.DESIGN_REVISE, Phase.SUSPENDED],
    Phase.DESIGN_REVISE: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.PLANNING: [Phase.IMPLEMENT, Phase.SUSPENDED],
    # Feature-L ワークフロー
    Phase.SPLIT_PROPOSAL: [Phase.SPLIT_EXECUTE, Phase.HEARING, Phase.SUSPENDED],
    Phase.SPLIT_EXECUTE: [Phase.DONE, Phase.SUSPENDED],
    # 共通: 実装・レビュー
    Phase.IMPLEMENT: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],
    Phase.CI_FIX: [Phase.IMPL_REVIEW, Phase.CI_FIX, Phase.SUSPENDED],
    Phase.IMPL_REVIEW: [Phase.DONE, Phase.IMPL_REVISE, Phase.SUSPENDED],
    Phase.IMPL_REVISE: [Phase.IMPL_REVIEW, Phase.SUSPENDED],
    # 特殊
    Phase.BLOCKED: [Phase.HEARING, Phase.ANALYSIS, Phase.IMPLEMENT],
    Phase.SUSPENDED: list(Phase),  # どのフェーズにも復帰可能
}


# ---------------------------------------------------------------------------
# 4. PHASE_CONFIG 辞書
# ---------------------------------------------------------------------------

PHASE_CONFIG: dict[str, PhaseConfig] = {
    "type_detection": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="plan"),
    "hearing": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "analysis": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "plan_brief": PhaseConfig(max_budget_usd=1.0, timeout_sec=300, permission_mode="plan"),
    "design": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="plan"),
    "design_revise": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
        resume=True,
    ),
    "planning": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "split_proposal": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    "fix": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "ci_fix": PhaseConfig(max_budget_usd=3.0, timeout_sec=1200, permission_mode="bypassPermissions"),
    "impl_revise": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
        resume=True,
    ),
}


# ---------------------------------------------------------------------------
# 5. メトリクス用 Dataclass 定義
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseErrorStats:
    """フェーズ別エラー統計."""

    phase: str
    total_executions: int
    error_count: int
    error_rate: float  # 0.0 〜 1.0
    errors_by_category: dict[str, int]  # ErrorCategory -> count


@dataclass(frozen=True)
class PhaseRetryStats:
    """フェーズ別リトライ統計."""

    phase: str
    total_retries: int
    max_consecutive_retries: int
    avg_retries_per_execution: float


@dataclass(frozen=True)
class PhaseCostEntry:
    """フェーズ別コストエントリ."""

    phase: str
    total_cost_usd: float
    execution_count: int
    avg_cost_usd: float
    max_cost_usd: float


@dataclass(frozen=True)
class CIFailurePattern:
    """CI失敗パターン."""

    error_message: str
    occurrence_count: int
    affected_issues: list[int]
    first_seen: str  # ISO 8601
    last_seen: str  # ISO 8601


@dataclass(frozen=True)
class PhaseTransitionLoop:
    """フェーズ遷移ループ(繰り返し検知)."""

    loop_phases: tuple[str, ...]  # 例: ("ci-fix", "impl-review", "ci-fix")
    occurrence_count: int
    affected_issues: list[int]


@dataclass(frozen=True)
class DetectionMetrics:
    """バグ・改善検知用メトリクス集約結果.

    MetricsCollector が events.jsonl から集約したメトリクスを保持する。
    各フィールドはイミュータブルで、分析・閾値判定に利用される。
    """

    # 集計期間
    collected_at: str  # ISO 8601
    time_range_start: str  # ISO 8601
    time_range_end: str  # ISO 8601
    total_events_processed: int

    # フェーズ別エラー統計
    error_stats: tuple[PhaseErrorStats, ...]

    # フェーズ別コスト推移
    cost_by_phase: tuple[PhaseCostEntry, ...]

    # リトライ統計
    retry_stats: tuple[PhaseRetryStats, ...]

    # CI失敗パターン
    ci_failure_patterns: tuple[CIFailurePattern, ...]

    # フェーズ遷移ループ検知
    transition_loops: tuple[PhaseTransitionLoop, ...]

    # サマリ
    total_cost_usd: float
    total_errors: int
    total_issues_analyzed: int
