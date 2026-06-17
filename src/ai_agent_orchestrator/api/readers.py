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
    ApprovalEntry,
    CostsResponse,
    EventRecord,
    EvidenceItemResponse,
    EvidenceResponse,
    HealthResponse,
    IssueCost,
    IssueDetailResponse,
    IssueSummaryResponse,
    PrototypeItemResponse,
    PrototypeResponse,
    QueueResponse,
    phase_to_status,
)
from ai_agent_orchestrator.evidence.paths import evidence_dir
from ai_agent_orchestrator.io_safety import (
    MAX_LOG_FILE_BYTES,
    MAX_STATUS_FILE_BYTES,
    FileTooLargeError,
    read_text_capped,
)
from ai_agent_orchestrator.models import Phase
from ai_agent_orchestrator.prototype.paths import prototype_dir
from ai_agent_orchestrator.prototype.selection import read_selection
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
# ファイルは存在するが中身が壊れている (壊れ JSON / 非 dict / 型不正)。
# 「未起動」と区別し、運用者の切り分けを助ける。
_HEALTH_CORRUPT_REASON = "health.json が壊れている (型/内容不正)"
# サイズ上限超過 (異常に肥大した health.json)。読み込まず停止中に倒す (#115)。
_HEALTH_TOO_LARGE_REASON = "health.json がサイズ上限を超過 (異常)"


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
        raw = json.loads(read_text_capped(path, MAX_STATUS_FILE_BYTES))
    except FileTooLargeError:
        logger.warning("health.json がサイズ上限を超過: %s", path)
        return HealthResponse(running=False, stale=False, reason=_HEALTH_TOO_LARGE_REASON)
    except (OSError, json.JSONDecodeError):
        logger.warning("health.json の読み取り/パースに失敗: %s", path, exc_info=True)
        return HealthResponse(running=False, stale=False, reason=_HEALTH_CORRUPT_REASON)

    if not isinstance(raw, dict):
        return HealthResponse(running=False, stale=False, reason=_HEALTH_CORRUPT_REASON)

    parsed_ts = _parse_health_ts(raw)
    is_stale = parsed_ts is None or (datetime.now(UTC) - parsed_ts).total_seconds() > stale_after_sec

    try:
        response = HealthResponse.model_validate(raw)
    except ValidationError:
        # 有効な JSON dict だが型が壊れている (running 欠落・queue が dict でない等)。
        # file content は信頼しない方針に従い、500 ではなく「停止中」に倒す。
        logger.warning("health.json の型検証に失敗: %s", path, exc_info=True)
        return HealthResponse(running=False, stale=False, reason=_HEALTH_CORRUPT_REASON)
    if is_stale:
        # 統計値はファイル内容を引き継ぎつつ、running=False / stale=True に倒す。
        return response.model_copy(update={"running": False, "stale": True, "reason": _HEALTH_STALE_REASON})
    return response.model_copy(update={"stale": False})


_QUEUE_ABSENT_REASON = "queue.json が無い (orchestrator 未起動)"
_QUEUE_CORRUPT_REASON = "queue.json が壊れている (型/内容不正)"


def read_queue(workspace: Path) -> QueueResponse:
    """queue.json を読み、実行キューの状態を返す (#96).

    不在/壊れでも例外を投げず、空キュー + reason の停止中扱いで返す。

    Args:
        workspace: ワークスペースのルートパス。

    Returns:
        QueueResponse。
    """
    path = workspace / "queue.json"
    if not path.exists():
        return QueueResponse(running=False, reason=_QUEUE_ABSENT_REASON)
    try:
        # FileTooLargeError は OSError 派生なので下の except が捕捉 (#115)。
        raw = json.loads(read_text_capped(path, MAX_STATUS_FILE_BYTES))
    except (OSError, json.JSONDecodeError):
        logger.warning("queue.json の読み取り/パースに失敗: %s", path, exc_info=True)
        return QueueResponse(running=False, reason=_QUEUE_CORRUPT_REASON)
    if not isinstance(raw, dict):
        return QueueResponse(running=False, reason=_QUEUE_CORRUPT_REASON)
    try:
        return QueueResponse.model_validate(raw)
    except ValidationError:
        logger.warning("queue.json の型検証に失敗: %s", path, exc_info=True)
        return QueueResponse(running=False, reason=_QUEUE_CORRUPT_REASON)


def read_evidence(workspace: Path, issue_number: int) -> EvidenceResponse:
    """Issue の evidence manifest.json を読み EvidenceResponse へ変換する (#91).

    manifest が不在/壊れでも例外を投げず、空の EvidenceResponse を返す。各
    item には配信エンドポイント (/api/issues/{n}/evidence/{file}) への url を組む。

    Args:
        workspace: ワークスペースのルートパス。
        issue_number: Issue 番号。

    Returns:
        EvidenceResponse。
    """
    manifest_path = evidence_dir(workspace, issue_number) / "manifest.json"
    if not manifest_path.exists():
        return EvidenceResponse()
    try:
        raw = json.loads(read_text_capped(manifest_path, MAX_STATUS_FILE_BYTES))
    except (OSError, json.JSONDecodeError):
        logger.warning("evidence manifest の読み取り/パースに失敗: %s", manifest_path, exc_info=True)
        return EvidenceResponse()
    if not isinstance(raw, dict):
        return EvidenceResponse()

    items: list[EvidenceItemResponse] = []
    for entry in raw.get("items", []):
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file", ""))
        if not file:
            continue
        items.append(
            EvidenceItemResponse(
                id=str(entry.get("id", "")),
                kind=str(entry.get("kind", "")),
                title=str(entry.get("title", "")),
                url=f"/api/issues/{issue_number}/evidence/{file}",
                viewport=entry.get("viewport"),
                created_at=entry.get("created_at") or None,
            )
        )
    notes = [str(n) for n in raw.get("notes", []) if isinstance(n, str)]
    generated_at = raw.get("generated_at")
    return EvidenceResponse(
        generated_at=generated_at if isinstance(generated_at, str) else None,
        items=items,
        notes=notes,
    )


def read_prototypes(workspace: Path, issue_number: int) -> PrototypeResponse:
    """Issue の prototype manifest.json を読み PrototypeResponse へ変換する (#145).

    manifest が不在/壊れでも例外を投げず、空の PrototypeResponse を返す。各 item には
    HTML 配信エンドポイント (/api/issues/{n}/prototypes/{file}) への url を組む。

    Args:
        workspace: ワークスペースのルートパス。
        issue_number: Issue 番号。

    Returns:
        PrototypeResponse。
    """
    manifest_path = prototype_dir(workspace, issue_number) / "manifest.json"
    if not manifest_path.exists():
        return PrototypeResponse()
    try:
        raw = json.loads(read_text_capped(manifest_path, MAX_STATUS_FILE_BYTES))
    except (OSError, json.JSONDecodeError):
        logger.warning("prototype manifest の読み取り/パースに失敗: %s", manifest_path, exc_info=True)
        return PrototypeResponse()
    if not isinstance(raw, dict):
        return PrototypeResponse()

    items: list[PrototypeItemResponse] = []
    for entry in raw.get("items", []):
        if not isinstance(entry, dict):
            continue
        file = str(entry.get("file", ""))
        if not file:
            continue
        items.append(
            PrototypeItemResponse(
                id=str(entry.get("id", "")),
                title=str(entry.get("title", "")),
                url=f"/api/issues/{issue_number}/prototypes/{file}",
                description=str(entry.get("description", "")),
            )
        )
    notes = [str(n) for n in raw.get("notes", []) if isinstance(n, str)]
    generated_at = raw.get("generated_at")
    # iteration (#145 Phase2): bool は int のサブクラスなので除外。
    raw_iteration = raw.get("iteration")
    iteration = (
        raw_iteration
        if isinstance(raw_iteration, int) and not isinstance(raw_iteration, bool) and raw_iteration > 0
        else 0
    )
    # 選択された案 (#145 Phase3)。存在しない案を指していたら無視する。
    selected = read_selection(workspace, issue_number)
    if selected is not None and not any(it.id == selected for it in items):
        selected = None
    return PrototypeResponse(
        generated_at=generated_at if isinstance(generated_at, str) else None,
        iteration=iteration,
        selected=selected,
        items=items,
        notes=notes,
    )


# 人間の承認/レビュー待ちとして扱うフェーズ (#88 承認待ち一覧)。
_APPROVAL_WAIT_PHASES: frozenset[str] = frozenset({"approve", "review"})


def read_approvals(workspace: Path) -> list[ApprovalEntry]:
    """state.json から人間の承認/レビュー待ち Issue を導出する (#88).

    approve (計画承認待ち) と review (PR レビュー待ち) の Issue を
    updated_at 降順で返す。state.json 不在は空リスト。

    Args:
        workspace: ワークスペースのルートパス。

    Returns:
        ApprovalEntry のリスト (updated_at 降順)。
    """
    entries = [
        ApprovalEntry(
            repo=repo,
            issue_number=state.issue_number,
            phase=state.phase.value,
            pr_number=state.pr_number,
            updated_at=state.updated_at,
        )
        for (repo, _number), state in load_states(workspace).items()
        if state.phase.value in _APPROVAL_WAIT_PHASES
        # SPLIT は承認待ちフラグで判定する (#150)。
        or (state.phase is Phase.SPLIT and state.awaiting_split_approval)
    ]
    entries.sort(key=lambda e: e.updated_at, reverse=True)
    return entries


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
        # サイズ上限超過 (FileTooLargeError) も OSError として安全側に倒す (#115)。
        text = read_text_capped(path, MAX_LOG_FILE_BYTES)
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
        # サイズ上限超過 (FileTooLargeError) も OSError として安全側に倒す (#115)。
        text = read_text_capped(path, MAX_LOG_FILE_BYTES)
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


# カードに出す本文抜粋の最大文字数 (#142)。レイアウトを崩さない短さに保つ。
_BODY_EXCERPT_CHARS = 120


def _make_excerpt(body: str) -> str | None:
    """本文から表示用の短い抜粋を作る (#142).

    連続する空白・改行を 1 つの空白へ畳み、先頭 ``_BODY_EXCERPT_CHARS`` 文字に
    切り詰める。超過時は末尾に省略記号 (…) を付ける。空・空白のみは None。

    Args:
        body: state に保存された Issue 本文 (既に長さ制限済み)。

    Returns:
        表示用の抜粋文字列。内容が無ければ None。
    """
    collapsed = " ".join(body.split())
    if not collapsed:
        return None
    if len(collapsed) <= _BODY_EXCERPT_CHARS:
        return collapsed
    return collapsed[:_BODY_EXCERPT_CHARS].rstrip() + "…"


def _summary_from_state(state: IssueState, repo: str, cost_usd: float) -> IssueSummaryResponse:
    """IssueState から IssueSummaryResponse を構築する."""
    # SPLIT は提案生成/承認待ち/実行を同一フェーズで通るため、承認待ちは
    # フェーズではなくフラグで表す (#150)。フラグが立っていれば waiting に倒す。
    status = "waiting" if state.awaiting_split_approval else phase_to_status(state.phase)
    return IssueSummaryResponse(
        number=state.issue_number,
        repo=repo,
        title=state.title or None,
        body_excerpt=_make_excerpt(state.body),
        issue_type=state.issue_type,
        phase=state.phase.value,
        status=status,
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
