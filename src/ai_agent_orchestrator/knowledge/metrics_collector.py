"""events.jsonl からメトリクスを収集・集約する."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_agent_orchestrator.models import (
    CIFailurePattern,
    DetectionMetrics,
    PhaseCostEntry,
    PhaseErrorStats,
    PhaseRetryStats,
    PhaseTransitionLoop,
)

logger = logging.getLogger(__name__)

_ISSUE_DIR_PATTERN = re.compile(r"^issue-(\d+)$")


class MetricsCollector:
    """events.jsonl からメトリクスを収集・集約する.

    EventLogger が出力した JSONL ファイルを読み取り、
    バグ・改善検知に必要な統計情報を DetectionMetrics に集約する。

    Attributes:
        _log_dir: EventLogger と同じログ基底ディレクトリ。
    """

    def __init__(self, log_dir: Path) -> None:
        """初期化.

        Args:
            log_dir: EventLogger のログ基底ディレクトリ。
        """
        self._log_dir = log_dir

    async def collect(
        self,
        *,
        issue_numbers: list[int] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> DetectionMetrics:
        """メトリクスを収集・集約する.

        Args:
            issue_numbers: 対象Issue番号リスト。None の場合は全Issue。
            since: 集計開始日時。None の場合は全期間。
            until: 集計終了日時。None の場合は現在時刻。

        Returns:
            集約されたメトリクス。
        """
        if issue_numbers is None:
            issue_numbers = await self._discover_issue_numbers()

        all_events: list[dict[str, Any]] = []
        for issue_number in issue_numbers:
            events = await self._read_events(issue_number)
            all_events.extend(events)

        filtered = self._filter_events_by_time(all_events, since=since, until=until)

        error_stats = self._compute_error_stats(filtered)
        cost_by_phase = self._compute_cost_by_phase(filtered)
        retry_stats = self._compute_retry_stats(filtered)
        ci_failure_patterns = self._detect_ci_failure_patterns(filtered)
        transition_loops = self._detect_transition_loops(filtered)

        # time range
        timestamps = [e.get("ts", "") for e in filtered if e.get("ts")]
        time_range_start = min(timestamps) if timestamps else ""
        time_range_end = max(timestamps) if timestamps else ""

        total_cost = sum(c.total_cost_usd for c in cost_by_phase)
        total_errors = sum(e.error_count for e in error_stats)
        unique_issues = {e.get("issue") for e in filtered if e.get("issue") is not None}

        return DetectionMetrics(
            collected_at=datetime.now(UTC).isoformat(),
            time_range_start=time_range_start,
            time_range_end=time_range_end,
            total_events_processed=len(filtered),
            error_stats=tuple(error_stats),
            cost_by_phase=tuple(cost_by_phase),
            retry_stats=tuple(retry_stats),
            ci_failure_patterns=tuple(ci_failure_patterns),
            transition_loops=tuple(transition_loops),
            total_cost_usd=total_cost,
            total_errors=total_errors,
            total_issues_analyzed=len(unique_issues),
        )

    async def _read_events(
        self,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        """指定Issueの events.jsonl を読み取る.

        Args:
            issue_number: 対象Issue番号。

        Returns:
            イベントレコードのリスト。ファイルが存在しない場合は空リスト。
        """
        events_file = self._log_dir / f"issue-{issue_number}" / "events.jsonl"

        def _read() -> list[dict[str, Any]]:
            try:
                text = events_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                return []

            records: list[dict[str, Any]] = []
            for line_num, line in enumerate(text.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning(
                        "Skipping invalid JSON at line %d in issue-%d/events.jsonl",
                        line_num,
                        issue_number,
                    )
            return records

        return await asyncio.to_thread(_read)

    async def _discover_issue_numbers(self) -> list[int]:
        """ログディレクトリから全Issue番号を検出する.

        ディレクトリ名 ``issue-{N}`` からIssue番号を抽出する。

        Returns:
            検出されたIssue番号のリスト。
        """

        def _discover() -> list[int]:
            if not self._log_dir.exists():
                return []
            numbers: list[int] = []
            for entry in self._log_dir.iterdir():
                if not entry.is_dir():
                    continue
                match = _ISSUE_DIR_PATTERN.match(entry.name)
                if match:
                    numbers.append(int(match.group(1)))
            return sorted(numbers)

        return await asyncio.to_thread(_discover)

    def _compute_error_stats(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseErrorStats]:
        """フェーズ別エラー統計を計算する.

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別エラー統計のリスト。
        """
        phase_executions: Counter[str] = Counter()
        phase_errors: Counter[str] = Counter()
        phase_error_categories: dict[str, Counter[str]] = defaultdict(Counter)

        for ev in events:
            phase = ev.get("phase", "")
            event_type = ev.get("event", "")
            data = ev.get("data") or {}

            if event_type == "phase_start":
                phase_executions[phase] += 1

            is_error = event_type == "error" or "error" in data
            if is_error:
                phase_errors[phase] += 1
                category = data.get("error_category", "unknown")
                phase_error_categories[phase][category] += 1

        all_phases = set(phase_executions.keys()) | set(phase_errors.keys())
        results: list[PhaseErrorStats] = []
        for phase in sorted(all_phases):
            total = phase_executions[phase]
            errors = phase_errors[phase]
            rate = errors / total if total > 0 else 0.0
            results.append(
                PhaseErrorStats(
                    phase=phase,
                    total_executions=total,
                    error_count=errors,
                    error_rate=rate,
                    errors_by_category=dict(phase_error_categories.get(phase, {})),
                )
            )
        return results

    def _compute_cost_by_phase(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseCostEntry]:
        """フェーズ別コスト推移を計算する.

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別コストエントリのリスト。
        """
        phase_costs: dict[str, list[float]] = defaultdict(list)

        for ev in events:
            data = ev.get("data") or {}
            cost = data.get("cost_usd")
            if cost is not None:
                phase = ev.get("phase", "")
                phase_costs[phase].append(float(cost))

        results: list[PhaseCostEntry] = []
        for phase in sorted(phase_costs.keys()):
            costs = phase_costs[phase]
            total = sum(costs)
            count = len(costs)
            results.append(
                PhaseCostEntry(
                    phase=phase,
                    total_cost_usd=total,
                    execution_count=count,
                    avg_cost_usd=total / count if count > 0 else 0.0,
                    max_cost_usd=max(costs),
                )
            )
        return results

    def _compute_retry_stats(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseRetryStats]:
        """フェーズ別リトライ統計を計算する.

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別リトライ統計のリスト。
        """
        phase_executions: Counter[str] = Counter()
        phase_retries: Counter[str] = Counter()
        # Track consecutive retries per phase
        phase_max_consecutive: dict[str, int] = defaultdict(int)
        current_consecutive: dict[str, int] = defaultdict(int)
        last_event_was_retry: dict[str, bool] = defaultdict(bool)

        for ev in events:
            phase = ev.get("phase", "")
            event_type = ev.get("event", "")
            data = ev.get("data") or {}

            if event_type == "phase_start":
                phase_executions[phase] += 1
                # Reset consecutive counter on new execution
                current_consecutive[phase] = 0
                last_event_was_retry[phase] = False

            is_retry = event_type == "retry" or data.get("retry_count", 0) > 0
            if is_retry:
                phase_retries[phase] += 1
                if last_event_was_retry[phase]:
                    current_consecutive[phase] += 1
                else:
                    current_consecutive[phase] = 1
                    last_event_was_retry[phase] = True
                phase_max_consecutive[phase] = max(
                    phase_max_consecutive[phase],
                    current_consecutive[phase],
                )
            else:
                if event_type != "phase_start":
                    last_event_was_retry[phase] = False
                    current_consecutive[phase] = 0

        all_phases = set(phase_retries.keys())
        results: list[PhaseRetryStats] = []
        for phase in sorted(all_phases):
            total = phase_retries[phase]
            execs = phase_executions[phase]
            results.append(
                PhaseRetryStats(
                    phase=phase,
                    total_retries=total,
                    max_consecutive_retries=phase_max_consecutive.get(phase, 0),
                    avg_retries_per_execution=total / execs if execs > 0 else 0.0,
                )
            )
        return results

    def _detect_ci_failure_patterns(
        self,
        events: list[dict[str, Any]],
    ) -> list[CIFailurePattern]:
        """CI失敗パターンを検出する.

        Args:
            events: 全イベントレコード。

        Returns:
            CI失敗パターンのリスト(出現回数降順)。
        """
        pattern_data: dict[str, dict[str, Any]] = {}

        for ev in events:
            phase = ev.get("phase", "")
            data = ev.get("data") or {}
            error_msg = data.get("error")

            if phase != "ci-fix" or not error_msg:
                continue

            issue = ev.get("issue", 0)
            ts = ev.get("ts", "")

            if error_msg not in pattern_data:
                pattern_data[error_msg] = {
                    "count": 0,
                    "issues": set(),
                    "first_seen": ts,
                    "last_seen": ts,
                }

            entry = pattern_data[error_msg]
            entry["count"] += 1
            entry["issues"].add(issue)
            if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
                entry["first_seen"] = ts
            if ts and (not entry["last_seen"] or ts > entry["last_seen"]):
                entry["last_seen"] = ts

        results: list[CIFailurePattern] = []
        for msg, info in pattern_data.items():
            results.append(
                CIFailurePattern(
                    error_message=msg,
                    occurrence_count=info["count"],
                    affected_issues=sorted(info["issues"]),
                    first_seen=info["first_seen"],
                    last_seen=info["last_seen"],
                )
            )

        results.sort(key=lambda p: p.occurrence_count, reverse=True)
        return results

    def _detect_transition_loops(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseTransitionLoop]:
        """フェーズ遷移ループを検出する.

        同一Issue内で同じフェーズ遷移パターンが繰り返されるケースを検出する。

        Args:
            events: 全イベントレコード。

        Returns:
            検出されたフェーズ遷移ループのリスト。
        """
        # Build per-issue phase sequences from phase_start events
        issue_sequences: dict[int, list[str]] = defaultdict(list)
        for ev in events:
            if ev.get("event") == "phase_start":
                issue = ev.get("issue", 0)
                phase = ev.get("phase", "")
                issue_sequences[issue].append(phase)

        # Detect loops with sliding window
        loop_data: dict[tuple[str, ...], dict[str, Any]] = {}

        for issue, sequence in issue_sequences.items():
            for window_size in (2, 3, 4):
                if len(sequence) < window_size:
                    continue
                subsequences: Counter[tuple[str, ...]] = Counter()
                for i in range(len(sequence) - window_size + 1):
                    sub = tuple(sequence[i : i + window_size])
                    subsequences[sub] += 1

                for sub, count in subsequences.items():
                    if count < 2:
                        continue
                    if sub not in loop_data:
                        loop_data[sub] = {"count": 0, "issues": set()}
                    loop_data[sub]["count"] += count
                    loop_data[sub]["issues"].add(issue)

        # Remove shorter patterns that are subsets of longer ones
        all_patterns = sorted(loop_data.keys(), key=len, reverse=True)
        to_remove: set[tuple[str, ...]] = set()
        for i, longer in enumerate(all_patterns):
            for shorter in all_patterns[i + 1 :]:
                if len(shorter) >= len(longer):
                    continue
                # Check if shorter is a contiguous subsequence of longer
                longer_str = " ".join(longer)
                shorter_str = " ".join(shorter)
                if shorter_str in longer_str:
                    to_remove.add(shorter)

        results: list[PhaseTransitionLoop] = []
        for sub, info in loop_data.items():
            if sub in to_remove:
                continue
            results.append(
                PhaseTransitionLoop(
                    loop_phases=sub,
                    occurrence_count=info["count"],
                    affected_issues=sorted(info["issues"]),
                )
            )

        return results

    def _filter_events_by_time(
        self,
        events: list[dict[str, Any]],
        *,
        since: datetime | None,
        until: datetime | None,
    ) -> list[dict[str, Any]]:
        """イベントを時刻範囲でフィルタリングする.

        Args:
            events: フィルタ対象のイベントリスト。
            since: 開始日時(含む)。
            until: 終了日時(含む)。

        Returns:
            フィルタ後のイベントリスト。
        """
        if since is None and until is None:
            return events

        filtered: list[dict[str, Any]] = []
        for ev in events:
            ts_str = ev.get("ts")
            if not ts_str:
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue

            if since is not None and ts < since:
                continue
            if until is not None and ts > until:
                continue
            filtered.append(ev)

        return filtered
