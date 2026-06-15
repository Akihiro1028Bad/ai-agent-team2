"""API レスポンスの pydantic モデル (web/lib/types.ts と整合).

orchestrator のファイル成果物 (state.json / events.jsonl) を Web UI 向けの
安定した JSON 形状へ変換するための DTO 群。pydantic v2 スタイルで定義する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_agent_orchestrator.models import Phase

RunStatus = Literal["running", "waiting", "done", "blocked", "suspended"]
"""Web UI が表示する実行ステータス。Phase から phase_to_status で導出する。"""


# フェーズ → ステータスの導出表 (仕様 §設計判断4)。
# done / blocked / suspended はそのまま。承認・回答待ち系は waiting。
# それ以外 (INTAKE/CLARIFY/SPLIT/PLAN/IMPLEMENT/REVISE) は running。
_WAITING_PHASES: frozenset[Phase] = frozenset({Phase.CLARIFY_WAIT, Phase.APPROVE, Phase.REVIEW})


def phase_to_status(phase: Phase) -> RunStatus:
    """Phase を Web UI 用の RunStatus へ変換する.

    Args:
        phase: Issue の現在フェーズ。

    Returns:
        導出された RunStatus。
    """
    if phase is Phase.DONE:
        return "done"
    if phase is Phase.BLOCKED:
        return "blocked"
    if phase is Phase.SUSPENDED:
        return "suspended"
    if phase in _WAITING_PHASES:
        return "waiting"
    return "running"


class IssueSummaryResponse(BaseModel):
    """Issue 一覧の 1 件分 (state.json 由来 + コスト集計)."""

    model_config = ConfigDict(extra="forbid")

    number: int
    repo: str
    title: str | None = None
    # 本文の先頭抜粋 (#142)。カードに 1〜2 行の概要を出すための短い文字列。
    # 本文未保存 (旧データ等) は None。
    body_excerpt: str | None = None
    issue_type: str
    phase: str
    status: RunStatus
    cost_usd: float
    pr_number: int | None = None
    design_pr_number: int | None = None
    branch_head_sha: str | None = None
    retry_count: int
    created_at: str
    updated_at: str


class IssueDetailResponse(IssueSummaryResponse):
    """Issue 詳細 (一覧フィールド + 計画 JSON 等)."""

    plan_json: dict[str, Any] | None = None
    session_id: str | None = None
    impl_iteration: int


class EventRecord(BaseModel):
    """events.jsonl の 1 行を表すレコード."""

    model_config = ConfigDict(extra="ignore")

    ts: str = ""
    issue: int | None = None
    phase: str = ""
    event: str = ""
    data: dict[str, Any] | None = None


class AgentLogRecord(BaseModel):
    """agent.jsonl の 1 行を表すレコード (#85).

    ts/phase/type は安定フィールド。それ以外 (text/tool/input/usage 等) は
    レコード種別ごとに異なるため extra="allow" でそのまま通す。
    """

    model_config = ConfigDict(extra="allow")

    ts: str = ""
    phase: str = ""
    type: str = ""


class AgentLogPage(BaseModel):
    """agent.jsonl のページング応答 (#85)."""

    records: list[AgentLogRecord] = Field(default_factory=list)
    next_offset: int
    total: int


class IssueCost(BaseModel):
    """Issue 単位のコスト集計."""

    repo: str
    issue_number: int
    cost_usd: float
    phases: dict[str, float] = Field(default_factory=dict)


class CostsResponse(BaseModel):
    """コスト集計 (総額 + Issue 別 + フェーズ別)."""

    total_usd: float
    issues: list[IssueCost] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """orchestrator の稼働状態 (health.json 由来) (#97).

    health.json の不在/古い/壊れに対しても、API は常に「停止中である」という
    事実を返せるよう running/stale/reason を持つ。health.json の追加キーには
    寛容 (extra="ignore")。
    """

    model_config = ConfigDict(extra="ignore")

    running: bool
    stale: bool = False
    reason: str | None = None
    ts: str | None = None
    queue: dict[str, int] | None = None
    repositories: list[str] = Field(default_factory=list)
    rate_limit: dict[str, int] | None = None
    worktrees: int | None = None
    last_poll: dict[str, str] = Field(default_factory=dict)
    accounts: dict[str, bool] = Field(default_factory=dict)


class DiffFile(BaseModel):
    """PR の 1 ファイル分の差分メタ情報."""

    model_config = ConfigDict(extra="ignore")

    filename: str
    status: str = ""
    additions: int = 0
    deletions: int = 0
    patch: str | None = None


class DiffResponse(BaseModel):
    """PR 差分レスポンス."""

    pr_number: int
    files: list[DiffFile] = Field(default_factory=list)


class QueueEntry(BaseModel):
    """実行キューの 1 件 (待ち / 実行中 / pause)."""

    model_config = ConfigDict(extra="ignore")

    repo: str = ""
    issue_number: int = 0
    phase: str = ""
    priority: int = 0
    enqueued_at: str = ""
    wait_reason: str = ""


class QueueResponse(BaseModel):
    """実行キューの状態 (queue.json 由来) (#96).

    不在/壊れでも 200 で「停止中で空のキュー」を返せるよう reason を持つ。
    """

    model_config = ConfigDict(extra="ignore")

    running: bool = False
    ts: str | None = None
    reason: str | None = None
    queued: list[QueueEntry] = Field(default_factory=list)
    active: list[QueueEntry] = Field(default_factory=list)
    paused: list[QueueEntry] = Field(default_factory=list)
    max_total: int = 0
    max_per_repo: int = 0


class ControlOrderEntry(BaseModel):
    """reorder の order 要素 (希望順の 1 エントリ)."""

    model_config = ConfigDict(extra="forbid")

    issue: int = Field(gt=0)
    phase: str = Field(min_length=1, max_length=64)


# issue を必要としない全体コマンド (control_bus._GLOBAL_ACTIONS + reorder と整合)。
_CONTROL_GLOBAL_ACTIONS: frozenset[str] = frozenset({"shutdown", "poll_now", "worktree_gc", "reorder"})


class ControlRequest(BaseModel):
    """POST /api/control のリクエストボディ (#87 基盤 + #88 で全語彙対応).

    ControlBus の ``parse_operational_line`` と対称の per-action 検証を行い、
    orchestrator 側の読み飛ばし (サイレント無視) ではなく API の 422 で弾く。

    - global (shutdown/poll_now/worktree_gc): issue 不要 (指定しても無視)
    - issue-scoped (pause/resume/abort/enqueue_issue/retry_with_analysis): issue 必須
    - set_priority: issue + phase + priority 必須
    - rewind: issue + target (resume 可能な Phase 値) 必須
    - reorder: order (非空リスト) 必須・issue 不要
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        "pause",
        "resume",
        "abort",
        "shutdown",
        "poll_now",
        "worktree_gc",
        "enqueue_issue",
        "retry_with_analysis",
        "set_priority",
        "rewind",
        "reorder",
    ]
    issue: int | None = None
    # 文字列長/件数の上限は control.jsonl の読み取り上限 (10MiB) を巨大入力で
    # 越えさせない DoS 対策 (認証導入 #115 までの暫定ハードニング)。
    actor: str = Field(default="", max_length=200)
    phase: str | None = Field(default=None, max_length=64)
    priority: int | None = None
    target: str | None = Field(default=None, max_length=64)
    order: list[ControlOrderEntry] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_per_action(self) -> ControlRequest:
        """action ごとの必須フィールドを検証する (parse_operational_line と対称)."""
        if self.action not in _CONTROL_GLOBAL_ACTIONS and (self.issue is None or self.issue <= 0):
            raise ValueError(f"action='{self.action}' requires a positive integer 'issue'")
        if self.action == "set_priority":
            if not self.phase:
                raise ValueError("action='set_priority' requires a non-empty 'phase'")
            if self.priority is None:
                raise ValueError("action='set_priority' requires an integer 'priority'")
        if self.action == "rewind":
            from ai_agent_orchestrator.orchestrator.control_bus import REWIND_TARGETS

            if self.target not in REWIND_TARGETS:
                raise ValueError(f"action='rewind' requires 'target' in {sorted(REWIND_TARGETS)}")
        if self.action == "reorder" and not self.order:
            raise ValueError("action='reorder' requires a non-empty 'order' list")
        return self

    def to_control_record(self) -> dict[str, object]:
        """control.jsonl へ追記する行 (parse_operational_line が読める形) を返す."""
        record: dict[str, object] = {"action": self.action, "actor": self.actor}
        if self.action not in _CONTROL_GLOBAL_ACTIONS:
            record["issue"] = self.issue
        if self.action == "set_priority":
            record["phase"] = self.phase
            record["priority"] = self.priority
        if self.action == "rewind":
            record["target"] = self.target
        if self.action == "reorder" and self.order is not None:
            record["order"] = [{"issue": e.issue, "phase": e.phase} for e in self.order]
        return record


class ControlAcceptedResponse(BaseModel):
    """POST /api/control のレスポンスボディ."""

    accepted: bool


class ApprovalEntry(BaseModel):
    """GET /api/approvals の 1 エントリ (人間の承認/レビュー待ち Issue)."""

    repo: str
    issue_number: int
    phase: str
    pr_number: int | None = None
    updated_at: str = ""


class ReplyRequest(BaseModel):
    """POST /api/issues/{n}/reply のリクエストボディ (ヒアリング回答)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=65536)


class ReplyResponse(BaseModel):
    """POST /api/issues/{n}/reply のレスポンスボディ."""

    posted: bool


class DesignAnchor(BaseModel):
    """design.json の anchor 付きテキスト要素 (#89)."""

    anchor: str
    text: str


class DesignSubtask(BaseModel):
    """design.json の anchor 付きサブタスク要素 (#89)."""

    anchor: str
    id: int | None = None
    title: str


class ReviewComment(BaseModel):
    """設計レビューのインラインコメント 1 件 (#89)."""

    model_config = ConfigDict(extra="forbid")

    anchor: str = Field(min_length=1, max_length=128)
    anchor_label: str = Field(default="", max_length=256)
    tag: Literal["指摘", "質問"]
    body: str = Field(min_length=1, max_length=8192)


class ReviewRequest(BaseModel):
    """POST /api/issues/{n}/review のリクエストボディ (#89).

    インラインレビュー提出。comments が空なら承認、指摘があれば差し戻し、
    質問のみなら質問として扱う (分類は api.review.classify_review)。
    """

    model_config = ConfigDict(extra="forbid")

    comments: list[ReviewComment] = Field(default_factory=list, max_length=500)
    actor: str = Field(default="", max_length=200)


class ReviewResponse(BaseModel):
    """POST /api/issues/{n}/review のレスポンスボディ (#89)."""

    outcome: Literal["approved", "changes_requested", "questions"]
    accepted: bool


class DesignResponse(BaseModel):
    """GET /api/issues/{n}/design のレスポンスボディ (#89).

    plan_json から導出した構造化設計。各要素に安定 anchor ID を持たせ、
    インラインレビューの指摘を該当要素へ紐づけられるようにする。
    PLAN 未完了 (plan_json 不在) は present=false + reason で返す (常に 200)。
    """

    present: bool
    plan_depth: str | None = None
    ui_impact: bool | None = None
    summary: DesignAnchor | None = None
    test_cases: list[DesignAnchor] = Field(default_factory=list)
    architecture: list[DesignAnchor] = Field(default_factory=list)
    subtasks: list[DesignSubtask] = Field(default_factory=list)
    reason: str | None = None


class PhaseModelRow(BaseModel):
    """GET /api/config/phase-models の 1 行 (#90).

    max_turns は既定 (上書きなし) では None になり得る (SDK デフォルト委任)。
    """

    model_config = ConfigDict(protected_namespaces=())

    phase: str
    model: str
    thinking: bool
    max_turns: int | None = None


class PhaseModelsResponse(BaseModel):
    """GET/PUT /api/config/phase-models のレスポンス (#90)."""

    phases: list[PhaseModelRow] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)


class PhaseModelInput(BaseModel):
    """PUT /api/config/phase-models の 1 行 (#90).

    max_turns は None 許容で「上書きなし (SDK デフォルト)」を表す。GET レスポンス
    (PhaseModelRow) と対称で、GET 値をそのまま PUT へ往復できる。
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    phase: str
    model: str
    thinking: bool
    max_turns: int | None = None


class PhaseModelsRequest(BaseModel):
    """PUT /api/config/phase-models のリクエストボディ (#90)."""

    model_config = ConfigDict(extra="forbid")

    phases: list[PhaseModelInput] = Field(default_factory=list, max_length=50)


class EvidenceItemResponse(BaseModel):
    """GET /api/issues/{n}/evidence の 1 アイテム (#91).

    url はファイル配信エンドポイントへの相対 URL。
    """

    id: str
    kind: str
    title: str
    url: str
    viewport: str | None = None
    created_at: str | None = None


class EvidenceResponse(BaseModel):
    """GET /api/issues/{n}/evidence のレスポンス (#91)."""

    generated_at: str | None = None
    items: list[EvidenceItemResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PrototypeItemResponse(BaseModel):
    """GET /api/issues/{n}/prototypes の 1 アイテム (#145).

    url は HTML 配信エンドポイントへの相対 URL。sandbox iframe の src に使う。
    """

    id: str
    title: str
    url: str


class PrototypeResponse(BaseModel):
    """GET /api/issues/{n}/prototypes のレスポンス (#145)."""

    generated_at: str | None = None
    items: list[PrototypeItemResponse] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
