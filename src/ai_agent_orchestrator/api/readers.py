"""state.json / events.jsonl の読み取り純関数.

orchestrator のプロセス状態には一切触れず、ワークスペース配下のファイルだけを
読み取って API レスポンスモデルへ変換する (仕様 §設計判断1)。ファイル不在・空・
壊れた行に対しても例外を投げず、空リストやスキップで安全側に倒す。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from ai_agent_orchestrator.api.schemas import (
    AgentLogPage,
    AgentLogRecord,
    CostsResponse,
    EventRecord,
    HealthResponse,
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


def _health_file(workspace: Path) -> Path:
    """health.json のパスを返す."""
    return workspace / "health.json"


_HEALTH_ABSENT_REASON = "health.json が無い (orchestrator 未起動)"
_HEALTH_STALE_REASON = "health.json が古い (orchestrator 停止/ハングの可能性)"


def _parse_health_ts(raw: dict[str, Any]) -> datetime | None:
    """health.json の ts を UTC datetime にパースする (失敗時 None)."""
    ts = raw.get("ts")
    if not isinstance(ts, str):
        return None
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return None
    # naive な場合は UTC とみなす (#85 と同じ UTC ISO8601 前提)。
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def read_health(workspace: Path, *, stale_after_sec: float = 900.0) -> HealthResponse:
    """health.json を読み、orchestrator の稼働状態を返す (#97).

    health.json が不在/壊れ/古い場合は「停止中」として返す。常に例外を投げず、
    安全側 (running=False) に倒す。

    Args:
        workspace: ワークスペースのルートパス。
        stale_after_sec: この秒数より古い ts は stale (停止/ハング) とみなす。

    Returns:
        HealthResponse。不在・壊れは reason 付きの running=False。
    """
    path = _health_file(workspace)
    if not path.exists():
        return HealthResponse(running=False, stale=False, reason=_HEALTH_ABSENT_REASON)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("health.json の読み取り/パースに失敗: %s", path, exc_info=True)
        return HealthResponse(running=False, stale=False, reason=_HEALTH_ABSENT_REASON)

    if not isinstance(raw, dict):
        return HealthResponse(running=False, stale=False, reason=_HEALTH_ABSENT_REASON)

    parsed_ts = _parse_health_ts(raw)
    is_stale = parsed_ts is None or (datetime.now(UTC) - parsed_ts).total_seconds() > stale_after_sec

    try:
        response = HealthResponse.model_validate(raw)
    except ValidationError:
        # 有効な JSON dict だが型が壊れている (running 欠落・queue が dict でない等)。
        # file content は信頼しない方針に従い、500 ではなく「停止中」に倒す。
        logger.warning("health.json の型検証に失敗: %s", path, exc_info=True)
        return HealthResponse(running=False, stale=False, reason=_HEALTH_ABSENT_REASON)
    if is_stale:
        # 統計値はファイル内容を引き継ぎつつ、running=False / stale=True に倒す。
        return response.model_copy(update={"running": False, "stale": True, "reason": _HEALTH_STALE_REASON})
    return response.model_copy(update={"stale": False})


def _events_file(workspace: Path, issue_number: int) -> Path:
    """指定 Issue の events.jsonl のパスを返す."""
    return workspace / "logs" / f"issue-{issue_number}" / "events.jsonl"


def _agent_log_file(workspace: Path, issue_number: int) -> Path:
    """指定 Issue の agent.jsonl のパスを返す."""
    return workspace / "logs" / f"issue-{issue_number}" / "agent.jsonl"


def read_agent_logs(
    workspace: Path,
    issue_number: int,
    offset: int = 0,
    limit: int = 200,
) -> AgentLogPage:
    """指定 Issue の agent.jsonl を物理行オフセット基準でページング取得する (#85).

    offset は古い順の物理行インデックス。壊れ行はレコードから除くが、
    インデックスは消費する (オフセットは「物理行」基準で安定する。SSE の
    Last-Event-ID と同じ単位)。

    Args:
        workspace: ワークスペースのルートパス。
        issue_number: Issue 番号。
        offset: 読み出し開始の物理行インデックス (0 始まり、古い順)。
        limit: 返す最大件数。

    Returns:
        AgentLogPage。next_offset は今回読んだ最終物理行+1、total は物理行総数。
    """
    path = _agent_log_file(workspace, issue_number)
    if not path.exists():
        return AgentLogPage(records=[], next_offset=offset, total=0)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("agent.jsonl の読み取りに失敗: %s", path, exc_info=True)
        return AgentLogPage(records=[], next_offset=offset, total=0)

    physical_lines = text.splitlines()
    # 末尾未終端行 (書き込み途中の可能性) は消費しない。SSE の tail
    # (stream._read_new_lines) と torn read 方針を揃え、next_offset を
    # start_agent に渡したときの取りこぼしを防ぐ (#85 review #2)。
    if text and not text.endswith("\n") and physical_lines:
        physical_lines = physical_lines[:-1]
    total = len(physical_lines)

    records: list[AgentLogRecord] = []
    next_offset = offset
    for index in range(offset, total):
        next_offset = index + 1
        stripped = physical_lines[index].strip()
        if stripped:
            record = _parse_agent_log_line(stripped, path)
            if record is not None:
                records.append(record)
        if len(records) >= limit:
            break

    return AgentLogPage(records=records, next_offset=next_offset, total=total)


def _parse_agent_log_line(stripped: str, path: Path) -> AgentLogRecord | None:
    """agent.jsonl の 1 行をパースして AgentLogRecord を返す (壊れ行は None)."""
    try:
        raw = json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("壊れた agent.jsonl 行をスキップ: %s", path)
        return None
    if not isinstance(raw, dict):
        return None
    return AgentLogRecord.model_validate(raw)


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
    """指定 Issue の phase_completed イベントから総コストを集計する.

    注意: events.jsonl の格納先 (logs/issue-{n}/) は Issue 番号のみで分かれて
    おりリポジトリ非分離。複数リポジトリで同一 Issue 番号が稼働した場合、
    コストは番号単位で合算される (ストレージレイアウト由来の既知の制約)。
    """
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
    # ts は EventLogger が UTC (+00:00) の ISO 8601 で固定出力する前提の文字列比較。
    # オフセット混在時は順序が崩れるため、生成側のフォーマットを変える場合は要見直し。
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
