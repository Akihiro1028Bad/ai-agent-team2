"""API レスポンスの pydantic モデル (web/lib/types.ts と整合).

orchestrator のファイル成果物 (state.json / events.jsonl) を Web UI 向けの
安定した JSON 形状へ変換するための DTO 群。pydantic v2 スタイルで定義する。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
