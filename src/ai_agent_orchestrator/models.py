"""データモデル定義 (Enum, dataclass)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any, Literal

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


# ---------------------------------------------------------------------------
# 1.5 ワークフローパラメータ (U5c #95)
# ---------------------------------------------------------------------------

PlanDepth = Literal["light", "full"]
"""PLAN フェーズの深さ。light = 旧 bug 相当、full = 旧 feature 相当。"""

ApprovalStyle = Literal["reaction", "pr"]
"""承認ゲートの方式。reaction = Issue への 👍 承認、pr = PR approve。"""


@dataclass(frozen=True)
class WorkflowParams:
    """タイプ別差分を表す統一パラメータ集合 (U5c #95).

    INTAKE が Issue の規模・性質から決定し、以降は全タイプが同一コードパスを
    流れる。下流フェーズはタイプ文字列ではなく本パラメータで振る舞いを切り替える。

    Attributes:
        plan_depth: PLAN の深さ ("light" / "full")。
        needs_split: SPLIT フェーズを通過するか (旧 feature-l)。
        approval_style: 承認ゲートの方式 ("reaction" / "pr")。
    """

    plan_depth: PlanDepth
    needs_split: bool
    approval_style: ApprovalStyle


def derive_workflow_params(issue_type: str) -> WorkflowParams:
    """issue_type からワークフローパラメータを導出する (U5c #95).

    INTAKE が付与したタイプ分類を、下流が消費するパラメータ集合へ変換する
    単一の真実点。タイプ別の `== "bug"` 分岐を全て本関数経由に集約することで
    「全タイプが同一コードパス・パラメータ差のみ」を実現する。

    未判定 ("") / 未知タイプは安全側 (full / 分割なし / PR 承認) にフォールバック
    し、例外は投げない。

    Args:
        issue_type: "bug" | "feature-m" | "feature-l" | その他。

    Returns:
        導出された WorkflowParams。
    """
    if issue_type == IssueType.BUG:
        return WorkflowParams(plan_depth="light", needs_split=False, approval_style="reaction")
    if issue_type == IssueType.FEATURE_L:
        return WorkflowParams(plan_depth="full", needs_split=True, approval_style="pr")
    # feature-m / 未判定 / 未知タイプ → full・分割なし・PR 承認
    return WorkflowParams(plan_depth="full", needs_split=False, approval_style="pr")


class Phase(str, Enum):  # noqa: UP042
    """Issueのフェーズ (U5 #83: 9 フェーズ統一パイプライン).

    タイプ別分岐 (Bug/Feature-M/L) はフェーズではなくパラメータ
    (plan_depth / needs_split / approval_style) で表現する。
    全タイプが INTAKE → CLARIFY → (SPLIT) → PLAN → APPROVE →
    IMPLEMENT → REVIEW → (REVISE) → DONE の 1 本道を流れる。
    """

    # 統一パイプライン (9 フェーズ)
    INTAKE = "intake"  # 規模・性質の判定とパラメータ付与 (旧 type-detection)
    CLARIFY = "clarify"  # 要件ヒアリング (旧 hearing)
    SPLIT = "split"  # 分割提案→承認→実行 (旧 split-proposal/split-execute)
    PLAN = "plan"  # 計画/設計書の生成 (旧 analysis/design)
    APPROVE = "approve"  # 計画承認ゲート (旧 plan-review/design-review)
    IMPLEMENT = "implement"  # 実装 (旧 fix/implement)
    REVIEW = "review"  # CI + 人間レビューゲート (旧 impl-review)
    REVISE = "revise"  # 修正対応 (旧 design-revise/impl-revise/ci-fix)
    DONE = "done"  # 完了

    # 補助状態
    CLARIFY_WAIT = "clarify-wait"  # ヒアリング回答待ち (旧 hearing-wait)
    BLOCKED = "blocked"  # 依存待ち
    SUSPENDED = "suspended"  # 失敗時の手動復帰待ち


# 旧フェーズ名 → 新フェーズの読み替え表 (state.json マイグレーション用)。
# 旧 18 値すべてを網羅し、稼働中 Issue を取りこぼさない。
PHASE_MIGRATION: dict[str, Phase] = {
    "type-detection": Phase.INTAKE,
    "hearing": Phase.CLARIFY,
    "hearing-wait": Phase.CLARIFY_WAIT,
    "analysis": Phase.PLAN,
    "design": Phase.PLAN,
    "design-revise": Phase.PLAN,  # 設計修正中 = 再設計 (U4 で PLAN 差し戻しに統一済み)
    "plan-review": Phase.APPROVE,
    "design-review": Phase.APPROVE,
    "fix": Phase.IMPLEMENT,
    "implement": Phase.IMPLEMENT,
    "ci-fix": Phase.REVISE,
    "impl-review": Phase.REVIEW,
    "impl-revise": Phase.REVISE,
    "split-proposal": Phase.SPLIT,
    "split-execute": Phase.SPLIT,
    "blocked": Phase.BLOCKED,
    "done": Phase.DONE,
    "suspended": Phase.SUSPENDED,
}


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
    LGTM = "lgtm"


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
    """タスク実行リクエスト (U5 #83 で task_queue.TaskRequest と一本化).

    asyncio.PriorityQueue で比較可能にするため __lt__ を実装。
    phase は Phase enum の .value (str)。repo は RepositoryConfig 相当
    (.owner / .repo を持つオブジェクト)。
    """

    issue_number: int
    repo: Any  # RepositoryConfig 相当 (.owner / .repo を持つ)
    phase: str
    priority: int = 5
    # フェーズ実行に必要な付帯情報 (feedback / review_comment_ids / ci_logs 等)
    extra: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: TaskRequest) -> bool:
        """PriorityQueue での優先度比較。値が小さいほど優先。"""
        return self.priority < other.priority

    @property
    def repo_key(self) -> str:
        """リポジトリを一意に識別するキー."""
        return f"{self.repo.owner}/{self.repo.repo}"

    @property
    def issue_key(self) -> IssueKey:
        """リポジトリ横断で Issue を一意に識別するキー."""
        return (self.repo_key, self.issue_number)


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
    # トップレベル本文 (review submission) への応答済み review id
    answered_review_ids: list[int] = field(default_factory=list)
    # PLAN フェーズの構造化成果物 (U3 #81)。ui_impact を常に含む (#91 の判定ソース)
    plan_json: dict[str, Any] | None = None


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
    # 拡張思考の有効化 (#90)。True なら既定 budget で ClaudeAgentOptions.thinking を有効化。
    thinking: bool = False
    # 1 実行あたりの最大ターン数 (#90)。None は SDK デフォルトに委任。
    max_turns: int | None = None


# ---------------------------------------------------------------------------
# 3. VALID_TRANSITIONS 辞書
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    # 入口: 情報十分なら PLAN へ直行、曖昧なら CLARIFY
    Phase.INTAKE: [Phase.CLARIFY, Phase.PLAN, Phase.SUSPENDED],
    # ヒアリング: 明確→PLAN / 大規模→SPLIT / 質問→回答待ち
    Phase.CLARIFY: [Phase.PLAN, Phase.SPLIT, Phase.CLARIFY_WAIT, Phase.SUSPENDED],
    Phase.CLARIFY_WAIT: [Phase.CLARIFY, Phase.SUSPENDED],
    # 分割: 提案→承認→実行はフェーズ内で完結。修正指示は CLARIFY へ戻る
    Phase.SPLIT: [Phase.DONE, Phase.CLARIFY, Phase.BLOCKED, Phase.SUSPENDED],
    # 計画: 生成後は承認ゲートへ
    Phase.PLAN: [Phase.APPROVE, Phase.SUSPENDED],
    # 承認ゲート: 承認→IMPLEMENT / 差し戻し→PLAN (指摘全文を feedback で渡す)
    Phase.APPROVE: [Phase.IMPLEMENT, Phase.PLAN, Phase.SUSPENDED],
    # 実装: 完了→REVIEW / CI失敗→REVISE(ci)
    Phase.IMPLEMENT: [Phase.REVIEW, Phase.REVISE, Phase.SUSPENDED],
    # レビューゲート: マージ→DONE / 指摘・CI失敗→REVISE
    Phase.REVIEW: [Phase.DONE, Phase.REVISE, Phase.SUSPENDED],
    # 修正: 対応後 REVIEW へ戻る (連続 CI 失敗等の自己ループを許可)
    Phase.REVISE: [Phase.REVIEW, Phase.REVISE, Phase.SUSPENDED],
    # 特殊
    Phase.BLOCKED: [Phase.CLARIFY, Phase.PLAN, Phase.IMPLEMENT],
    # SUSPENDED からの復帰先 (DONE/BLOCKED/自身は復帰対象外。state machine の
    # resume_to_* と完全一致させる)
    Phase.SUSPENDED: [
        Phase.INTAKE,
        Phase.CLARIFY,
        Phase.CLARIFY_WAIT,
        Phase.SPLIT,
        Phase.PLAN,
        Phase.APPROVE,
        Phase.IMPLEMENT,
        Phase.REVIEW,
        Phase.REVISE,
    ],
}
