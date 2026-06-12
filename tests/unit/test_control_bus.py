"""ControlBus 運用コマンドのパース/読み取りテスト (#87)."""

from __future__ import annotations

import json
from pathlib import Path

from ai_agent_orchestrator.orchestrator.control_bus import (
    OperationalCommand,
    parse_operational_line,
    read_new_operational_commands,
)


def _write(path: Path, *lines: dict[str, object]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


class TestParseOperationalLine:
    def test_issue_scoped_actions(self) -> None:
        for action in ("pause", "resume", "abort"):
            cmd = parse_operational_line(json.dumps({"action": action, "issue": 5, "actor": "alice"}))
            assert cmd == OperationalCommand(action=action, issue_number=5, actor="alice")

    def test_global_shutdown_needs_no_issue(self) -> None:
        cmd = parse_operational_line(json.dumps({"action": "shutdown", "actor": "alice"}))
        assert cmd == OperationalCommand(action="shutdown", issue_number=None, actor="alice")

    def test_approve_reject_are_ignored(self) -> None:
        # 承認系は ControlBus(運用) の対象外 → None
        assert parse_operational_line(json.dumps({"action": "approve", "issue": 1, "approver": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "reject", "issue": 1, "approver": "a"})) is None

    def test_issue_scoped_requires_positive_int(self) -> None:
        assert parse_operational_line(json.dumps({"action": "pause", "actor": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "pause", "issue": 0, "actor": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "pause", "issue": -1, "actor": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "pause", "issue": True, "actor": "a"})) is None

    def test_invalid_inputs_return_none(self) -> None:
        assert parse_operational_line("") is None
        assert parse_operational_line("not json") is None
        assert parse_operational_line(json.dumps([1, 2])) is None
        assert parse_operational_line(json.dumps({"action": "unknown", "issue": 1})) is None

    def test_actor_defaults_to_empty(self) -> None:
        cmd = parse_operational_line(json.dumps({"action": "shutdown"}))
        assert cmd is not None
        assert cmd.actor == ""

    def test_global_simple_commands(self) -> None:
        # poll_now / worktree_gc は issue 不要の全体コマンド (#96)
        for action in ("poll_now", "worktree_gc"):
            cmd = parse_operational_line(json.dumps({"action": action, "actor": "alice"}))
            assert cmd == OperationalCommand(action=action, issue_number=None, actor="alice")

    def test_enqueue_issue_is_issue_scoped(self) -> None:
        # enqueue_issue は issue 番号必須 (#96)
        cmd = parse_operational_line(json.dumps({"action": "enqueue_issue", "issue": 9, "actor": "alice"}))
        assert cmd == OperationalCommand(action="enqueue_issue", issue_number=9, actor="alice")
        assert parse_operational_line(json.dumps({"action": "enqueue_issue", "actor": "alice"})) is None
        assert parse_operational_line(json.dumps({"action": "enqueue_issue", "issue": 0, "actor": "alice"})) is None

    def test_set_priority_requires_phase_and_priority(self) -> None:
        cmd = parse_operational_line(
            json.dumps({"action": "set_priority", "issue": 5, "phase": "implement", "priority": 1, "actor": "a"})
        )
        assert cmd == OperationalCommand(
            action="set_priority", issue_number=5, actor="a", phase="implement", priority=1
        )
        # phase 欠落 / priority 欠落 / 型不正 は None
        assert parse_operational_line(json.dumps({"action": "set_priority", "issue": 5, "priority": 1})) is None
        assert parse_operational_line(json.dumps({"action": "set_priority", "issue": 5, "phase": "x"})) is None
        assert (
            parse_operational_line(json.dumps({"action": "set_priority", "issue": 5, "phase": "x", "priority": True}))
            is None
        )

    def test_reorder_parses_order_entries(self) -> None:
        cmd = parse_operational_line(
            json.dumps(
                {
                    "action": "reorder",
                    "order": [{"issue": 3, "phase": "plan"}, {"issue": 1, "phase": "implement"}],
                    "actor": "a",
                }
            )
        )
        assert cmd == OperationalCommand(
            action="reorder",
            issue_number=None,
            actor="a",
            order=((3, "plan"), (1, "implement")),
        )

    def test_reorder_invalid_order_returns_none(self) -> None:
        assert parse_operational_line(json.dumps({"action": "reorder", "actor": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "reorder", "order": [], "actor": "a"})) is None
        assert parse_operational_line(json.dumps({"action": "reorder", "order": [{"issue": 0, "phase": "p"}]})) is None
        assert parse_operational_line(json.dumps({"action": "reorder", "order": [{"issue": 1}]})) is None


class TestReadNewOperationalCommands:
    def test_returns_only_authorized_new_commands(self, tmp_path: Path) -> None:
        path = tmp_path / "control.jsonl"
        _write(
            path,
            {"action": "approve", "issue": 1, "approver": "alice"},  # 承認系は無視
            {"action": "pause", "issue": 5, "actor": "alice"},  # 認可済み
            {"action": "abort", "issue": 6, "actor": "mallory"},  # 認可外 → 無視
        )
        cmds, offset = read_new_operational_commands(path, 0, ["alice"])
        assert cmds == [OperationalCommand(action="pause", issue_number=5, actor="alice")]
        assert offset == 3  # 全行を消費済みに数える

    def test_offset_skips_processed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "control.jsonl"
        _write(
            path,
            {"action": "pause", "issue": 5, "actor": "alice"},
            {"action": "resume", "issue": 5, "actor": "alice"},
        )
        cmds, offset = read_new_operational_commands(path, 1, ["alice"])
        assert cmds == [OperationalCommand(action="resume", issue_number=5, actor="alice")]
        assert offset == 2

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        cmds, offset = read_new_operational_commands(tmp_path / "nope.jsonl", 0, ["alice"])
        assert cmds == []
        assert offset == 0

    def test_global_command_authorized_by_any_actor(self, tmp_path: Path) -> None:
        path = tmp_path / "control.jsonl"
        _write(path, {"action": "shutdown", "actor": "alice"})
        cmds, _ = read_new_operational_commands(path, 0, ["alice", "bob"])
        assert cmds == [OperationalCommand(action="shutdown", issue_number=None, actor="alice")]
