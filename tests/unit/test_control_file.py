"""control.jsonl 受け口 (U4 Phase4 #82) のテスト.

将来の Web UI からの承認/差し戻しを受け付ける最小スタブ。設定された
JSONL ファイルから制御コマンドを読み、未処理行のみを返す。
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestParseControlLine:
    """1 行の制御コマンドのパース."""

    def test_parses_approve_command(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        cmd = parse_control_line('{"issue": 5, "action": "approve", "approver": "alice"}')
        assert cmd is not None
        assert cmd.issue_number == 5
        assert cmd.action == "approve"
        assert cmd.approver == "alice"
        assert cmd.feedback == ""

    def test_parses_reject_command_with_feedback(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        cmd = parse_control_line('{"issue": 7, "action": "reject", "approver": "bob", "feedback": "直して"}')
        assert cmd is not None
        assert cmd.action == "reject"
        assert cmd.feedback == "直して"

    def test_returns_none_on_invalid_json(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line("{壊れた") is None

    def test_returns_none_on_missing_fields(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line('{"action": "approve"}') is None  # issue 欠落
        assert parse_control_line('{"issue": 5}') is None  # action 欠落

    def test_returns_none_on_non_positive_issue(self) -> None:
        """issue が 0 以下なら不正として None を返す."""
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line('{"issue": 0, "action": "approve"}') is None
        assert parse_control_line('{"issue": -1, "action": "approve"}') is None

    def test_returns_none_on_unknown_action(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line('{"issue": 5, "action": "explode"}') is None

    def test_returns_none_on_bool_issue(self) -> None:
        """issue が bool (int サブクラス) の場合は不正として None を返す."""
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line('{"issue": true, "action": "approve"}') is None

    def test_returns_none_on_non_dict_json(self) -> None:
        """有効な JSON でも dict でなければ None を返す (配列・文字列・数値)."""
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line("[1, 2]") is None
        assert parse_control_line('"x"') is None
        assert parse_control_line("42") is None

    def test_blank_line_is_none(self) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import parse_control_line

        assert parse_control_line("") is None
        assert parse_control_line("   ") is None


class TestReadNewControlCommands:
    """ファイルからの未処理コマンド読み取り (オフセット管理)."""

    def test_reads_authorized_lines_from_zero_offset(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        f = tmp_path / "control.jsonl"
        f.write_text(
            '{"issue": 1, "action": "approve", "approver": "alice"}\n'
            '{"issue": 2, "action": "reject", "approver": "alice", "feedback": "x"}\n',
            encoding="utf-8",
        )
        commands, new_offset = read_new_control_commands(f, 0, ["alice"])
        assert [c.issue_number for c in commands] == [1, 2]
        assert new_offset == 2

    def test_unauthorized_approver_command_is_filtered(self, tmp_path: Path) -> None:
        """許可外 approver のコマンドは承認シグナルとして扱わない (#102 intake)."""
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        f = tmp_path / "control.jsonl"
        f.write_text(
            '{"issue": 1, "action": "approve", "approver": "mallory"}\n'
            '{"issue": 2, "action": "approve", "approver": "alice"}\n',
            encoding="utf-8",
        )
        commands, new_offset = read_new_control_commands(f, 0, ["alice"])
        assert [c.issue_number for c in commands] == [2]
        # 不正/許可外行も offset には数える (再処理しない)
        assert new_offset == 2

    def test_skips_already_processed_lines(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        f = tmp_path / "control.jsonl"
        f.write_text(
            '{"issue": 1, "action": "approve", "approver": "alice"}\n'
            '{"issue": 2, "action": "approve", "approver": "alice"}\n',
            encoding="utf-8",
        )
        commands, new_offset = read_new_control_commands(f, 1, ["alice"])
        assert [c.issue_number for c in commands] == [2]
        assert new_offset == 2

    def test_malformed_lines_are_skipped_but_counted(self, tmp_path: Path) -> None:
        """不正行は読み飛ばすがオフセットは進める (再処理しない)."""
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        f = tmp_path / "control.jsonl"
        f.write_text('{壊れた\n{"issue": 9, "action": "approve", "approver": "alice"}\n', encoding="utf-8")
        commands, new_offset = read_new_control_commands(f, 0, ["alice"])
        assert [c.issue_number for c in commands] == [9]
        assert new_offset == 2

    def test_oversized_file_is_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """サイズ上限を超える control ファイルは読まずにスキップする (DoS 対策)."""
        import ai_agent_orchestrator.orchestrator.control_file as mod
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        monkeypatch.setattr(mod, "_MAX_CONTROL_FILE_BYTES", 10)
        f = tmp_path / "control.jsonl"
        f.write_text('{"issue": 1, "action": "approve", "approver": "alice"}\n', encoding="utf-8")
        commands, new_offset = read_new_control_commands(f, 0, ["alice"])
        assert commands == []
        assert new_offset == 0

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        commands, new_offset = read_new_control_commands(tmp_path / "nope.jsonl", 0, ["alice"])
        assert commands == []
        assert new_offset == 0

    def test_expanduser_path_is_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~ を含むパスが home 展開されて読まれる."""
        from ai_agent_orchestrator.orchestrator.control_file import read_new_control_commands

        monkeypatch.setenv("HOME", str(tmp_path))
        f = tmp_path / "control.jsonl"
        f.write_text('{"issue": 3, "action": "approve", "approver": "alice"}\n', encoding="utf-8")
        commands, new_offset = read_new_control_commands(Path("~/control.jsonl"), 0, ["alice"])
        assert [c.issue_number for c in commands] == [3]
        assert new_offset == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
