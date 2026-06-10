"""データモデル定義 (Enum, dataclass)."""

from __future__ import annotations

from dataclasses import dataclass, field
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
# 0. IssueKey 型エイリアス
# ---------------------------------------------------------------------------

IssueKey = tuple[str, int]
"""リポジトリ横断で Issue を一意に識別するキー。("owner/repo", issue_number) 形式。"""


def make_issue_key(repo: str, issue_number: int) -> IssueKey:
    """IssueKey を生成する.

    Args:
        repo: "owner/repo" 形式のリポジトリ識別子。
        issue_number: Issue 番号。

    Returns:
        (repo, issue_number) のタプル。

    Raises:
        ValueError: repo が "owner/repo" 形式でない場合。
    """
    if "/" not in repo:
        msg = f"repo must be 'owner/repo' format, got: {repo!r}"
        raise ValueError(msg)
    return (repo, issue_number)


# ---------------------------------------------------------------------------
# 1. Enum 定義
# ---------------------------------------------------------------------------


class IssueType(StrEnum):
    """Issueのタスクタイプ."""

    BUG = "bug"
    FEATURE_M = "feature-m"
    FEATURE_L = "feature-l"


class Phase(str, Enum):  # noqa: UP042
    """Issueのフェーズ."""

    # タイプ判定
    TYPE_DETECTION = "type-detection"

    # Bug専用
    ANALYSIS = "analysis"
    FIX = "fix"

    # Bug: 方針レビュー
    PLAN_REVIEW = "plan-review"

    # Feature-M/L共通
    HEARING = "hearing"
    HEARING_WAIT = "hearing-wait"
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"

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
class Subtask:
    """実装計画のサブタスク。

    design フェーズが出力した ## サブタスク セクションを
    parse_subtasks() でパースした結果を保持する。
    """

    id: int
    title: str
    files: tuple[str, ...]
    description: str
    depends_on: tuple[int, ...] = ()


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
    # フェーズ実行に必要な付帯情報 (review_comment_ids / ci_logs 等)。
    # task_queue.TaskRequest.extra から dispatch 経由で透過される
    extra: dict[str, Any] = field(default_factory=dict)

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
    # レビュー返信の重複防止 (#103)。再起動を跨いで効くよう永続化する
    acknowledged_review_comment_ids: list[int] = field(default_factory=list)
    answered_review_comment_ids: list[int] = field(default_factory=list)


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
    model: str = "sonnet"
    mcp_servers: dict[str, Any] | None = None
    mcp_allowed_tools: list[str] | None = None


# ---------------------------------------------------------------------------
# 3. VALID_TRANSITIONS 辞書
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    # 共通: 初期
    Phase.TYPE_DETECTION: [Phase.HEARING, Phase.ANALYSIS, Phase.SUSPENDED],
    # Bug ワークフロー
    Phase.ANALYSIS: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.FIX: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],
    # Bug: 方針レビュー
    Phase.PLAN_REVIEW: [Phase.FIX, Phase.ANALYSIS],
    # Feature-M ワークフロー
    Phase.HEARING: [
        Phase.DESIGN,
        Phase.SPLIT_PROPOSAL,
        Phase.ANALYSIS,
        Phase.SUSPENDED,
    ],
    Phase.DESIGN: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.DESIGN_REVIEW: [Phase.IMPLEMENT, Phase.DESIGN_REVISE, Phase.SUSPENDED],
    Phase.DESIGN_REVISE: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
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
