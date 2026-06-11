"""state.json / events.jsonl の読み取り純関数.

orchestrator のプロセス状態には一切触れず、ワークスペース配下のファイルだけを
読み取って API レスポンスモデルへ変換する (仕様 §設計判断1)。ファイル不在・空・
壊れた行に対しても例外を投げず、空リストやスキップで安全側に倒す。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ai_agent_orchestrator.api.schemas import (
    CostsResponse,
    EventRecord,
    IssueCost,
    IssueDetailResponse,
    IssueSummaryResponse,
    phase_to_status,
)
from ai_agent_orchestrator.state_persistence import StatePersistence

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import IssueState

logger = logging.getLogger(__name__)

_PHASE_COMPLETED_EVENT = "phase_completed"


def _state_file(workspace: Path) -> Path:
    """state.json のパスを返す."""
    return workspace / "state.json"


def _events_file(workspace: Path, issue_number: int) -> Path:
    """指定 Issue の events.jsonl のパスを返す."""
    return workspace / "logs" / f"issue-{issue_number}" / "events.jsonl"


def load_states(workspace: Path) -> dict[tuple[str, int], IssueState]:
    """state.json を読み込み IssueState の辞書を返す.

    StatePersistence.load() を read-only で再利用する。ファイル不在時は空辞書。

    Args:
        workspace: ワークスペースのルートパス。

    Returns:
        (repo, issue_number) をキーとする IssueState 辞書。
    """
    persistence = StatePersistence(state_file=_state_file(workspace))
    return persistence.load()


def _iter_event_lines(path: Path) -> list[EventRecord]:
    """events.jsonl を 1 行ずつパースし EventRecord のリストを返す.

    壊れた JSON 行は警告ログを出してスキップする。

    Args:
        path: events.jsonl のパス。

    Returns:
        ファイル順 (古い順) の EventRecord リスト。
    """
    if not path.exists():
        return []

    records: list[EventRecord] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("events.jsonl の読み取りに失敗: %s", path, exc_info=True)
        return []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning("壊れた events.jsonl 行をスキップ: %s", path)
            continue
        if isinstance(raw, dict):
            records.append(EventRecord.model_validate(raw))
    return records


def _issue_cost(workspace: Path, issue_number: int) -> float:
    """指定 Issue の phase_completed イベントから総コストを集計する."""
    total = 0.0
    for record in _iter_event_lines(_events_file(workspace, issue_number)):
        if record.event != _PHASE_COMPLETED_EVENT or record.data is None:
            continue
        cost = record.data.get("cost_usd")
        if isinstance(cost, (int, float)):
            total += float(cost)
    return total


def _summary_from_state(state: IssueState, repo: str, cost_usd: float) -> IssueSummaryResponse:
    """IssueState から IssueSummaryResponse を構築する."""
    return IssueSummaryResponse(
        number=state.issue_number,
        repo=repo,
        title=None,
        issue_type=state.issue_type,
        phase=state.phase.value,
        status=phase_to_status(state.phase),
        cost_usd=cost_usd,
        pr_number=state.pr_number,
        design_pr_number=state.design_pr_number,
        branch_head_sha=state.branch_head_sha,
        retry_count=state.retry_count,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


def read_issue_summaries(workspace: Path) -> list[IssueSummaryResponse]:
    """全 Issue の IssueSummary を updated_at 降順で返す.

    Args:
        workspace: ワークスペースのルートパス。

    Returns:
        IssueSummaryResponse のリスト (updated_at 降順)。
    """
    states = load_states(workspace)
    summaries = [
        _summary_from_state(state, repo, _issue_cost(workspace, state.issue_number))
        for (repo, _number), state in states.items()
    ]
    summaries.sort(key=lambda s: s.updated_at, reverse=True)
    return summaries


def detail_from_state(workspace: Path, state: IssueState, repo: str) -> IssueDetailResponse:
    """IssueState から IssueDetailResponse を構築する.

    Args:
        workspace: ワークスペースのルートパス。
        state: 対象 Issue の状態。
        repo: "owner/repo" 形式のリポジトリ識別子。

    Returns:
        IssueDetailResponse。
    """
    summary = _summary_from_state(state, repo, _issue_cost(workspace, state.issue_number))
    return IssueDetailResponse(
        **summary.model_dump(),
        plan_json=state.plan_json,
        session_id=state.session_id,
        impl_iteration=state.impl_iteration,
    )


def read_issue_events(workspace: Path, issue_number: int, limit: int = 200) -> list[EventRecord]:
    """指定 Issue の events.jsonl を新しい順で返す.

    Args:
        workspace: ワークスペースのルートパス。
        issue_number: Issue 番号。
        limit: 返す最大件数 (新しい順)。

    Returns:
        EventRecord のリスト (新しい順、最大 limit 件)。
    """
    records = _iter_event_lines(_events_file(workspace, issue_number))
    records.reverse()  # ファイルは古い順なので反転して新しい順にする
    return records[:limit]


def _all_event_files(workspace: Path) -> list[Path]:
    """ワークスペース配下の全 events.jsonl パスを返す."""
    logs_dir = workspace / "logs"
    if not logs_dir.exists():
        return []
    return sorted(logs_dir.glob("issue-*/events.jsonl"))


def merge_activity(workspace: Path, limit: int = 100) -> list[EventRecord]:
    """全 Issue の events.jsonl をマージし ts 降順で返す.

    Args:
        workspace: ワークスペースのルートパス。
        limit: 返す最大件数。

    Returns:
        EventRecord のリスト (ts 降順、最大 limit 件)。
    """
    merged: list[EventRecord] = []
    for path in _all_event_files(workspace):
        merged.extend(_iter_event_lines(path))
    merged.sort(key=lambda e: e.ts, reverse=True)
    return merged[:limit]


def aggregate_costs(workspace: Path) -> CostsResponse:
    """phase_completed の cost_usd を総額・Issue 別・フェーズ別に集計する.

    Args:
        workspace: ワークスペースのルートパス。

    Returns:
        CostsResponse。
    """
    states = load_states(workspace)
    repo_by_number: dict[int, str] = {state.issue_number: repo for (repo, _number), state in states.items()}

    issues: list[IssueCost] = []
    total = 0.0
    for path in _all_event_files(workspace):
        issue_number = _issue_number_from_path(path)
        if issue_number is None:
            continue
        phases: dict[str, float] = {}
        issue_total = 0.0
        for record in _iter_event_lines(path):
            if record.event != _PHASE_COMPLETED_EVENT or record.data is None:
                continue
            cost = record.data.get("cost_usd")
            if not isinstance(cost, (int, float)):
                continue
            phases[record.phase] = phases.get(record.phase, 0.0) + float(cost)
            issue_total += float(cost)
        if issue_total == 0.0 and not phases:
            continue
        issues.append(
            IssueCost(
                repo=repo_by_number.get(issue_number, ""),
                issue_number=issue_number,
                cost_usd=issue_total,
                phases=phases,
            )
        )
        total += issue_total

    issues.sort(key=lambda c: c.cost_usd, reverse=True)
    return CostsResponse(total_usd=total, issues=issues)


def _issue_number_from_path(path: Path) -> int | None:
    """logs/issue-{n}/events.jsonl のパスから Issue 番号を抽出する."""
    name = path.parent.name  # "issue-42"
    prefix = "issue-"
    if not name.startswith(prefix):
        return None
    try:
        return int(name[len(prefix) :])
    except ValueError:
        return None
