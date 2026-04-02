"""MetricsCollector のユニットテスト."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ai_agent_orchestrator.knowledge.metrics_collector import MetricsCollector
from ai_agent_orchestrator.models import DetectionMetrics

# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def write_events_jsonl(
    log_dir: Path,
    issue_number: int,
    events: list[dict[str, Any]],
) -> None:
    """テスト用にevents.jsonlを書き出すヘルパー."""
    issue_dir = log_dir / f"issue-{issue_number}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    events_file = issue_dir / "events.jsonl"
    with events_file.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """テスト用ログディレクトリ."""
    return tmp_path / "logs"


@pytest.fixture
def sample_events() -> list[dict[str, Any]]:
    """サンプルイベントレコード."""
    return [
        {
            "ts": "2026-04-01T10:00:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_start",
            "data": {},
        },
        {
            "ts": "2026-04-01T10:05:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_complete",
            "data": {"cost_usd": 1.5, "duration_sec": 300},
        },
        {
            "ts": "2026-04-01T10:06:00+00:00",
            "issue": 42,
            "phase": "ci-fix",
            "event": "error",
            "data": {
                "error": "lint failed",
                "error_category": "ci_failure",
                "retry_count": 1,
            },
        },
    ]


# ---------------------------------------------------------------------------
# TC-MC-19: DetectionMetrics が frozen であること
# ---------------------------------------------------------------------------


def test_detection_metrics_is_frozen() -> None:
    """TC-MC-19: DetectionMetrics が frozen であること."""
    metrics = DetectionMetrics(
        collected_at="2026-04-01T12:00:00+00:00",
        time_range_start="",
        time_range_end="",
        total_events_processed=0,
        error_stats=(),
        cost_by_phase=(),
        retry_stats=(),
        ci_failure_patterns=(),
        transition_loops=(),
        total_cost_usd=0.0,
        total_errors=0,
        total_issues_analyzed=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        metrics.total_cost_usd = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TC-MC-02 〜 TC-MC-06: イベント読み取り基盤
# ---------------------------------------------------------------------------


async def test_read_events_parses_jsonl(log_dir: Path, sample_events: list[dict[str, Any]]) -> None:
    """TC-MC-02: _read_events() が JSONL を正しくパースすること."""
    write_events_jsonl(log_dir, 42, sample_events)
    collector = MetricsCollector(log_dir)
    result = await collector._read_events(42)
    assert len(result) == 3
    assert result[0]["event"] == "phase_start"
    assert result[1]["data"]["cost_usd"] == 1.5


async def test_read_events_missing_file(log_dir: Path) -> None:
    """TC-MC-03: _read_events() がファイル未存在時に空リストを返すこと."""
    collector = MetricsCollector(log_dir)
    result = await collector._read_events(999)
    assert result == []


async def test_read_events_skips_invalid_json(log_dir: Path) -> None:
    """TC-MC-04: _read_events() が不正なJSONL行をスキップすること."""
    issue_dir = log_dir / "issue-42"
    issue_dir.mkdir(parents=True)
    events_file = issue_dir / "events.jsonl"
    events_file.write_text(
        '{"ts":"2026-04-01T10:00:00+00:00","issue":42,"phase":"implement","event":"phase_start","data":{}}\n'
        "INVALID JSON LINE\n"
        '{"ts":"2026-04-01T10:01:00+00:00","issue":42,"phase":"implement","event":"phase_complete","data":{}}\n',
        encoding="utf-8",
    )

    collector = MetricsCollector(log_dir)
    result = await collector._read_events(42)
    assert len(result) == 2


async def test_discover_issue_numbers(log_dir: Path) -> None:
    """TC-MC-05: _discover_issue_numbers() が正しく抽出すること."""
    for n in [10, 42, 100]:
        (log_dir / f"issue-{n}").mkdir(parents=True)

    collector = MetricsCollector(log_dir)
    result = await collector._discover_issue_numbers()
    assert result == [10, 42, 100]


async def test_discover_issue_numbers_ignores_non_issue_dirs(log_dir: Path) -> None:
    """TC-MC-06: _discover_issue_numbers() が非issueディレクトリを無視すること."""
    (log_dir / "issue-42").mkdir(parents=True)
    (log_dir / "not-an-issue").mkdir(parents=True)
    (log_dir / "issue-abc").mkdir(parents=True)
    # Create a file (not a directory)
    (log_dir / "issue-99.txt").write_text("", encoding="utf-8")

    collector = MetricsCollector(log_dir)
    result = await collector._discover_issue_numbers()
    assert result == [42]


# ---------------------------------------------------------------------------
# TC-MC-16, TC-MC-17: 時刻フィルタリング
# ---------------------------------------------------------------------------


def test_filter_events_by_time_with_since_until() -> None:
    """TC-MC-16: _filter_events_by_time() が since/until でフィルタすること."""
    events = [
        {"ts": "2026-04-01T09:00:00+00:00", "event": "a"},
        {"ts": "2026-04-01T10:00:00+00:00", "event": "b"},
        {"ts": "2026-04-01T11:00:00+00:00", "event": "c"},
        {"ts": "2026-04-01T12:00:00+00:00", "event": "d"},
    ]
    collector = MetricsCollector(Path("/tmp"))
    since = datetime(2026, 4, 1, 10, 0, 0, tzinfo=UTC)
    until = datetime(2026, 4, 1, 11, 0, 0, tzinfo=UTC)
    result = collector._filter_events_by_time(events, since=since, until=until)
    assert len(result) == 2
    assert result[0]["event"] == "b"
    assert result[1]["event"] == "c"


def test_filter_events_by_time_none_returns_all() -> None:
    """TC-MC-17: _filter_events_by_time() が None で全件返すこと."""
    events = [
        {"ts": "2026-04-01T09:00:00+00:00", "event": "a"},
        {"ts": "2026-04-01T10:00:00+00:00", "event": "b"},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._filter_events_by_time(events, since=None, until=None)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# TC-MC-07 〜 TC-MC-08: エラー統計
# ---------------------------------------------------------------------------


def test_compute_error_stats() -> None:
    """TC-MC-07: _compute_error_stats() がフェーズ別エラー率を正しく計算すること."""
    events = [
        {"phase": "implement", "event": "phase_start", "data": {}},
        {"phase": "implement", "event": "phase_complete", "data": {}},
        {"phase": "implement", "event": "phase_start", "data": {}},
        {
            "phase": "implement",
            "event": "error",
            "data": {"error": "fail", "error_category": "ci_failure"},
        },
        {"phase": "ci-fix", "event": "phase_start", "data": {}},
        {
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "lint", "error_category": "ci_failure"},
        },
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._compute_error_stats(events)

    by_phase = {s.phase: s for s in result}
    assert by_phase["implement"].total_executions == 2
    assert by_phase["implement"].error_count == 1
    assert by_phase["implement"].error_rate == pytest.approx(0.5)
    assert by_phase["implement"].errors_by_category == {"ci_failure": 1}
    assert by_phase["ci-fix"].error_count == 1


def test_compute_error_stats_no_errors() -> None:
    """TC-MC-08: _compute_error_stats() がエラー無しで rate=0.0 を返すこと."""
    events = [
        {"phase": "implement", "event": "phase_start", "data": {}},
        {"phase": "implement", "event": "phase_complete", "data": {}},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._compute_error_stats(events)
    assert len(result) == 1
    assert result[0].error_rate == 0.0
    assert result[0].error_count == 0


# ---------------------------------------------------------------------------
# TC-MC-09 〜 TC-MC-10: コスト統計
# ---------------------------------------------------------------------------


def test_compute_cost_by_phase() -> None:
    """TC-MC-09: _compute_cost_by_phase() がコストを正しく集計すること."""
    events = [
        {"phase": "implement", "event": "phase_complete", "data": {"cost_usd": 1.0}},
        {"phase": "implement", "event": "phase_complete", "data": {"cost_usd": 3.0}},
        {"phase": "ci-fix", "event": "phase_complete", "data": {"cost_usd": 0.5}},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._compute_cost_by_phase(events)

    by_phase = {c.phase: c for c in result}
    assert by_phase["implement"].total_cost_usd == pytest.approx(4.0)
    assert by_phase["implement"].execution_count == 2
    assert by_phase["implement"].avg_cost_usd == pytest.approx(2.0)
    assert by_phase["implement"].max_cost_usd == pytest.approx(3.0)
    assert by_phase["ci-fix"].total_cost_usd == pytest.approx(0.5)


def test_compute_cost_by_phase_ignores_missing_cost() -> None:
    """TC-MC-10: _compute_cost_by_phase() が cost_usd 未設定を無視すること."""
    events = [
        {"phase": "implement", "event": "phase_complete", "data": {"cost_usd": 2.0}},
        {"phase": "implement", "event": "phase_complete", "data": {}},
        {"phase": "implement", "event": "phase_start", "data": {}},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._compute_cost_by_phase(events)
    assert len(result) == 1
    assert result[0].execution_count == 1
    assert result[0].total_cost_usd == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# TC-MC-11: リトライ統計
# ---------------------------------------------------------------------------


def test_compute_retry_stats() -> None:
    """TC-MC-11: _compute_retry_stats() が連続リトライ最大値を計算すること."""
    events = [
        {"phase": "ci-fix", "event": "phase_start", "data": {}},
        {"phase": "ci-fix", "event": "retry", "data": {"retry_count": 1}},
        {"phase": "ci-fix", "event": "retry", "data": {"retry_count": 2}},
        {"phase": "ci-fix", "event": "retry", "data": {"retry_count": 3}},
        {"phase": "ci-fix", "event": "phase_complete", "data": {}},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._compute_retry_stats(events)
    assert len(result) == 1
    assert result[0].phase == "ci-fix"
    assert result[0].total_retries == 3
    assert result[0].max_consecutive_retries == 3
    assert result[0].avg_retries_per_execution == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# TC-MC-12 〜 TC-MC-13: CI失敗パターン
# ---------------------------------------------------------------------------


def test_detect_ci_failure_patterns_grouping() -> None:
    """TC-MC-12: _detect_ci_failure_patterns() がグルーピングすること."""
    events = [
        {
            "ts": "2026-04-01T10:00:00+00:00",
            "issue": 42,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "lint failed"},
        },
        {
            "ts": "2026-04-01T10:05:00+00:00",
            "issue": 43,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "lint failed"},
        },
        {
            "ts": "2026-04-01T10:10:00+00:00",
            "issue": 42,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "type error"},
        },
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._detect_ci_failure_patterns(events)
    assert len(result) == 2
    lint_pattern = next(p for p in result if p.error_message == "lint failed")
    assert lint_pattern.occurrence_count == 2
    assert sorted(lint_pattern.affected_issues) == [42, 43]


def test_detect_ci_failure_patterns_sorted_by_count() -> None:
    """TC-MC-13: _detect_ci_failure_patterns() が出現回数降順でソートされること."""
    events = [
        {
            "ts": "2026-04-01T10:00:00+00:00",
            "issue": 1,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "rare error"},
        },
        {
            "ts": "2026-04-01T10:01:00+00:00",
            "issue": 1,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "common error"},
        },
        {
            "ts": "2026-04-01T10:02:00+00:00",
            "issue": 2,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "common error"},
        },
        {
            "ts": "2026-04-01T10:03:00+00:00",
            "issue": 3,
            "phase": "ci-fix",
            "event": "error",
            "data": {"error": "common error"},
        },
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._detect_ci_failure_patterns(events)
    assert result[0].error_message == "common error"
    assert result[0].occurrence_count == 3
    assert result[1].error_message == "rare error"
    assert result[1].occurrence_count == 1


# ---------------------------------------------------------------------------
# TC-MC-14 〜 TC-MC-15: フェーズ遷移ループ
# ---------------------------------------------------------------------------


def test_detect_transition_loops() -> None:
    """TC-MC-14: _detect_transition_loops() がループを検出すること."""
    events = [
        {"issue": 42, "event": "phase_start", "phase": "implement"},
        {"issue": 42, "event": "phase_start", "phase": "ci-fix"},
        {"issue": 42, "event": "phase_start", "phase": "impl-review"},
        {"issue": 42, "event": "phase_start", "phase": "ci-fix"},
        {"issue": 42, "event": "phase_start", "phase": "impl-review"},
        {"issue": 42, "event": "phase_start", "phase": "ci-fix"},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._detect_transition_loops(events)
    assert len(result) > 0
    # Should detect ci-fix -> impl-review loop
    loop_phases_set = {loop.loop_phases for loop in result}
    assert ("ci-fix", "impl-review") in loop_phases_set or (
        "ci-fix",
        "impl-review",
        "ci-fix",
    ) in loop_phases_set


def test_detect_transition_loops_no_loop() -> None:
    """TC-MC-15: _detect_transition_loops() がループなしで空リストを返すこと."""
    events = [
        {"issue": 42, "event": "phase_start", "phase": "implement"},
        {"issue": 42, "event": "phase_start", "phase": "ci-fix"},
        {"issue": 42, "event": "phase_start", "phase": "impl-review"},
        {"issue": 42, "event": "phase_start", "phase": "done"},
    ]
    collector = MetricsCollector(Path("/tmp"))
    result = collector._detect_transition_loops(events)
    assert result == []


# ---------------------------------------------------------------------------
# TC-MC-01: collect() 統合テスト - 空ディレクトリ
# ---------------------------------------------------------------------------


async def test_collect_empty_directory(log_dir: Path) -> None:
    """TC-MC-01: collect() が空のログディレクトリで空のメトリクスを返すこと."""
    log_dir.mkdir(parents=True)
    collector = MetricsCollector(log_dir)
    metrics = await collector.collect()

    assert metrics.total_events_processed == 0
    assert metrics.total_cost_usd == 0.0
    assert metrics.total_errors == 0
    assert metrics.total_issues_analyzed == 0
    assert metrics.error_stats == ()
    assert metrics.cost_by_phase == ()
    assert metrics.retry_stats == ()
    assert metrics.ci_failure_patterns == ()
    assert metrics.transition_loops == ()


# ---------------------------------------------------------------------------
# TC-MC-18: collect() 指定Issueのみ集計
# ---------------------------------------------------------------------------


async def test_collect_specific_issues(log_dir: Path, sample_events: list[dict[str, Any]]) -> None:
    """TC-MC-18: collect(issue_numbers=[42]) が指定Issueのみ集計すること."""
    write_events_jsonl(log_dir, 42, sample_events)
    write_events_jsonl(
        log_dir,
        99,
        [
            {
                "ts": "2026-04-01T11:00:00+00:00",
                "issue": 99,
                "phase": "design",
                "event": "phase_start",
                "data": {},
            }
        ],
    )

    collector = MetricsCollector(log_dir)
    metrics = await collector.collect(issue_numbers=[42])

    assert metrics.total_issues_analyzed == 1
    assert metrics.total_events_processed == 3


# ---------------------------------------------------------------------------
# TC-MC-20: 複数Issueの統合メトリクス
# ---------------------------------------------------------------------------


async def test_collect_multiple_issues(log_dir: Path) -> None:
    """TC-MC-20: 複数Issueにまたがるメトリクスが正しく統合されること."""
    events_42 = [
        {
            "ts": "2026-04-01T10:00:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_start",
            "data": {},
        },
        {
            "ts": "2026-04-01T10:05:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_complete",
            "data": {"cost_usd": 2.0},
        },
    ]
    events_43 = [
        {
            "ts": "2026-04-01T11:00:00+00:00",
            "issue": 43,
            "phase": "implement",
            "event": "phase_start",
            "data": {},
        },
        {
            "ts": "2026-04-01T11:05:00+00:00",
            "issue": 43,
            "phase": "implement",
            "event": "phase_complete",
            "data": {"cost_usd": 3.0},
        },
    ]
    write_events_jsonl(log_dir, 42, events_42)
    write_events_jsonl(log_dir, 43, events_43)

    collector = MetricsCollector(log_dir)
    metrics = await collector.collect()

    assert metrics.total_issues_analyzed == 2
    assert metrics.total_events_processed == 4
    assert metrics.total_cost_usd == pytest.approx(5.0)
