"""api.readers / api.schemas の単体テスト."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_agent_orchestrator.api.readers import (
    aggregate_costs,
    merge_activity,
    read_agent_logs,
    read_issue_events,
    read_issue_summaries,
)
from ai_agent_orchestrator.api.schemas import phase_to_status
from ai_agent_orchestrator.models import Phase


# ──────────────────────────────────────
# ヘルパ
# ──────────────────────────────────────
def _write_state(workspace: Path, entries: dict[str, dict[str, object]]) -> None:
    (workspace / "state.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _write_events(workspace: Path, issue_number: int, lines: list[str]) -> None:
    issue_dir = workspace / "logs" / f"issue-{issue_number}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _state_entry(
    *,
    number: int,
    repo: str,
    phase: str,
    updated_at: str,
    issue_type: str = "bug",
) -> dict[str, object]:
    return {
        "issue_number": number,
        "phase": phase,
        "issue_type": issue_type,
        "repo": repo,
        "pr_number": None,
        "design_pr_number": None,
        "retry_count": 0,
        "branch_head_sha": None,
        "impl_iteration": 0,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": updated_at,
    }


# ──────────────────────────────────────
# phase_to_status
# ──────────────────────────────────────
@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (Phase.DONE, "done"),
        (Phase.BLOCKED, "blocked"),
        (Phase.SUSPENDED, "suspended"),
        (Phase.CLARIFY_WAIT, "waiting"),
        (Phase.APPROVE, "waiting"),
        (Phase.REVIEW, "waiting"),
        (Phase.INTAKE, "running"),
        (Phase.CLARIFY, "running"),
        (Phase.PLAN, "running"),
        (Phase.IMPLEMENT, "running"),
        (Phase.REVISE, "running"),
        (Phase.SPLIT, "running"),
    ],
)
def test_phase_to_status(phase: Phase, expected: str) -> None:
    assert phase_to_status(phase) == expected


# ──────────────────────────────────────
# read_issue_summaries
# ──────────────────────────────────────
def test_read_issue_summaries_empty_workspace(tmp_path: Path) -> None:
    """state.json が無くても空リストを返し例外を出さない."""
    assert read_issue_summaries(tmp_path) == []


def test_read_issue_summaries_sorted_desc(tmp_path: Path) -> None:
    """updated_at 降順で返す."""
    _write_state(
        tmp_path,
        {
            "o/r:1": _state_entry(number=1, repo="o/r", phase="done", updated_at="2026-01-01T00:00:00+00:00"),
            "o/r:2": _state_entry(number=2, repo="o/r", phase="implement", updated_at="2026-03-01T00:00:00+00:00"),
        },
    )
    summaries = read_issue_summaries(tmp_path)
    assert [s.number for s in summaries] == [2, 1]
    assert summaries[0].status == "running"
    assert summaries[1].status == "done"


def test_read_issue_summaries_includes_cost(tmp_path: Path) -> None:
    """cost_usd は events.jsonl の集計値."""
    _write_state(
        tmp_path,
        {"o/r:1": _state_entry(number=1, repo="o/r", phase="done", updated_at="2026-01-01T00:00:00+00:00")},
    )
    _write_events(
        tmp_path,
        1,
        [
            json.dumps(
                {
                    "ts": "2026-01-01T00:00:01+00:00",
                    "issue": 1,
                    "phase": "plan",
                    "event": "phase_completed",
                    "data": {"cost_usd": 0.5},
                }
            ),
            json.dumps(
                {
                    "ts": "2026-01-01T00:00:02+00:00",
                    "issue": 1,
                    "phase": "implement",
                    "event": "phase_completed",
                    "data": {"cost_usd": 1.25},
                }
            ),
        ],
    )
    summaries = read_issue_summaries(tmp_path)
    assert summaries[0].cost_usd == pytest.approx(1.75)


# ──────────────────────────────────────
# read_issue_events
# ──────────────────────────────────────
def test_read_issue_events_missing_returns_empty(tmp_path: Path) -> None:
    assert read_issue_events(tmp_path, 99) == []


def test_read_issue_events_newest_first_and_limit(tmp_path: Path) -> None:
    _write_events(
        tmp_path,
        1,
        [
            json.dumps({"ts": "2026-01-01T00:00:01+00:00", "issue": 1, "phase": "plan", "event": "a"}),
            json.dumps({"ts": "2026-01-01T00:00:02+00:00", "issue": 1, "phase": "plan", "event": "b"}),
            json.dumps({"ts": "2026-01-01T00:00:03+00:00", "issue": 1, "phase": "plan", "event": "c"}),
        ],
    )
    events = read_issue_events(tmp_path, 1, limit=2)
    assert [e.event for e in events] == ["c", "b"]


def test_read_issue_events_skips_broken_lines(tmp_path: Path) -> None:
    """壊れた JSON 行はスキップする."""
    issue_dir = tmp_path / "logs" / "issue-1"
    issue_dir.mkdir(parents=True)
    (issue_dir / "events.jsonl").write_text(
        json.dumps({"ts": "2026-01-01T00:00:01+00:00", "issue": 1, "phase": "plan", "event": "ok"})
        + "\n{ broken json \n"
        + json.dumps({"ts": "2026-01-01T00:00:02+00:00", "issue": 1, "phase": "plan", "event": "ok2"})
        + "\n",
        encoding="utf-8",
    )
    events = read_issue_events(tmp_path, 1)
    assert {e.event for e in events} == {"ok", "ok2"}


# ──────────────────────────────────────
# merge_activity
# ──────────────────────────────────────
def test_merge_activity_merges_and_sorts(tmp_path: Path) -> None:
    _write_events(
        tmp_path, 1, [json.dumps({"ts": "2026-01-01T00:00:01+00:00", "issue": 1, "phase": "plan", "event": "x"})]
    )
    _write_events(
        tmp_path, 2, [json.dumps({"ts": "2026-01-01T00:00:05+00:00", "issue": 2, "phase": "plan", "event": "y"})]
    )
    activity = merge_activity(tmp_path, limit=100)
    assert [e.issue for e in activity] == [2, 1]


def test_merge_activity_empty_workspace(tmp_path: Path) -> None:
    assert merge_activity(tmp_path) == []


# ──────────────────────────────────────
# aggregate_costs
# ──────────────────────────────────────
def test_aggregate_costs(tmp_path: Path) -> None:
    _write_state(
        tmp_path,
        {
            "o/r:1": _state_entry(number=1, repo="o/r", phase="done", updated_at="2026-01-01T00:00:00+00:00"),
            "o/r:2": _state_entry(number=2, repo="o/r", phase="done", updated_at="2026-01-02T00:00:00+00:00"),
        },
    )
    _write_events(
        tmp_path,
        1,
        [
            json.dumps({"ts": "t", "issue": 1, "phase": "plan", "event": "phase_completed", "data": {"cost_usd": 0.5}}),
            json.dumps(
                {"ts": "t", "issue": 1, "phase": "implement", "event": "phase_completed", "data": {"cost_usd": 1.0}}
            ),
        ],
    )
    _write_events(
        tmp_path,
        2,
        [json.dumps({"ts": "t", "issue": 2, "phase": "plan", "event": "phase_completed", "data": {"cost_usd": 2.0}})],
    )
    costs = aggregate_costs(tmp_path)
    assert costs.total_usd == pytest.approx(3.5)
    by_issue = {c.issue_number: c for c in costs.issues}
    assert by_issue[1].cost_usd == pytest.approx(1.5)
    assert by_issue[1].phases["plan"] == pytest.approx(0.5)
    assert by_issue[1].phases["implement"] == pytest.approx(1.0)
    assert by_issue[2].cost_usd == pytest.approx(2.0)


def test_aggregate_costs_empty(tmp_path: Path) -> None:
    costs = aggregate_costs(tmp_path)
    assert costs.total_usd == 0.0
    assert costs.issues == []


def test_aggregate_costs_ignores_non_completed_events(tmp_path: Path) -> None:
    """phase_completed 以外のイベントは集計しない."""
    _write_state(
        tmp_path,
        {"o/r:1": _state_entry(number=1, repo="o/r", phase="done", updated_at="2026-01-01T00:00:00+00:00")},
    )
    _write_events(
        tmp_path,
        1,
        [
            json.dumps({"ts": "t", "issue": 1, "phase": "plan", "event": "phase_started", "data": {"cost_usd": 9.0}}),
            json.dumps({"ts": "t", "issue": 1, "phase": "plan", "event": "phase_completed", "data": {"cost_usd": 0.5}}),
        ],
    )
    costs = aggregate_costs(tmp_path)
    assert costs.total_usd == pytest.approx(0.5)


# ──────────────────────────────────────
# read_agent_logs (#85)
# ──────────────────────────────────────
def _write_agent_logs(workspace: Path, issue_number: int, lines: list[str]) -> None:
    issue_dir = workspace / "logs" / f"issue-{issue_number}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    (issue_dir / "agent.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_agent_logs_empty_missing_file(tmp_path: Path) -> None:
    page = read_agent_logs(tmp_path, 99)
    assert page.records == []
    assert page.next_offset == 0
    assert page.total == 0


def test_read_agent_logs_paging(tmp_path: Path) -> None:
    lines = [json.dumps({"ts": f"t{i}", "phase": "plan", "type": "text", "text": str(i)}) for i in range(5)]
    _write_agent_logs(tmp_path, 1, lines)

    page = read_agent_logs(tmp_path, 1, offset=1, limit=2)
    assert [r.type for r in page.records] == ["text", "text"]
    assert page.records[0].text == "1"  # type: ignore[attr-defined]
    assert page.next_offset == 3
    assert page.total == 5


def test_read_agent_logs_skips_broken_but_consumes_index(tmp_path: Path) -> None:
    """壊れ行はスキップするが物理行インデックスは消費する."""
    lines = [
        json.dumps({"ts": "t0", "phase": "p", "type": "text", "text": "a"}),
        "{ broken json",
        json.dumps({"ts": "t2", "phase": "p", "type": "text", "text": "c"}),
    ]
    _write_agent_logs(tmp_path, 1, lines)

    page = read_agent_logs(tmp_path, 1, offset=0, limit=10)
    # 壊れ行はレコードから除かれるが、next_offset は物理行 3 を指す
    assert [r.text for r in page.records] == ["a", "c"]  # type: ignore[attr-defined]
    assert page.next_offset == 3
    assert page.total == 3


def test_read_agent_logs_excludes_unterminated_final_line(tmp_path: Path) -> None:
    """末尾未終端行 (書き込み途中) は total/next_offset/records から除外する.

    /logs の next_offset を SSE の start_agent に渡す設計上、torn read 方針を
    tail と揃えないと、完成後の同行を SSE が再読しない取りこぼしが起きうる
    (#85 review #2)。
    """
    issue_dir = tmp_path / "logs" / "issue-1"
    issue_dir.mkdir(parents=True, exist_ok=True)
    complete = json.dumps({"ts": "t0", "phase": "p", "type": "text", "text": "done"})
    # 2 行目は改行で終端されていない (書き込み途中)
    (issue_dir / "agent.jsonl").write_text(complete + "\n" + '{"type": "text", "text": "par', encoding="utf-8")

    page = read_agent_logs(tmp_path, 1, offset=0, limit=10)
    assert [r.text for r in page.records] == ["done"]  # type: ignore[attr-defined]
    assert page.total == 1  # 未終端行は数えない
    assert page.next_offset == 1  # 未終端行は消費しない
