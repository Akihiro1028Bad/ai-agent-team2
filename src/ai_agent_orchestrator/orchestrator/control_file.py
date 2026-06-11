"""control.jsonl 受け口 (U4 #82 Phase4).

将来の Web UI からの承認/差し戻しを受け付ける最小スタブ。設定された
JSONL ファイルを行単位で読み、未処理分のみを ControlCommand に変換する。
ライブのポーリングループへの配線は U5 / Web UI 実装時に行う。本モジュールは
「口」とパースロジックのみを提供する。

JSONL の 1 行フォーマット例::

    {"issue": 5, "action": "approve", "approver": "alice"}
    {"issue": 7, "action": "reject", "approver": "bob", "feedback": "再設計して"}
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset({"approve", "reject"})


@dataclass(frozen=True)
class ControlCommand:
    """Web UI 等から受け取る承認/差し戻し制御コマンド."""

    issue_number: int
    action: str  # "approve" | "reject"
    approver: str = ""
    feedback: str = ""


def parse_control_line(line: str) -> ControlCommand | None:
    """control.jsonl の 1 行を ControlCommand にパースする。

    不正な JSON・必須フィールド欠落・未知の action は None を返す
    (呼び出し側で読み飛ばす)。

    Args:
        line: JSONL の 1 行。

    Returns:
        ControlCommand または None。
    """
    text = line.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        logger.warning("control line is not valid JSON, skipping")
        return None
    if not isinstance(data, dict):
        return None

    issue = data.get("issue")
    action = data.get("action")
    if not isinstance(issue, int) or action not in _VALID_ACTIONS:
        logger.warning("control line missing/invalid issue or action, skipping")
        return None

    return ControlCommand(
        issue_number=issue,
        action=action,
        approver=str(data.get("approver", "")),
        feedback=str(data.get("feedback", "")),
    )


def read_new_control_commands(path: Path, offset: int) -> tuple[list[ControlCommand], int]:
    """control.jsonl から未処理行のみを読み取る。

    offset は「既に処理した行数」。それ以降の行のみを対象とし、新しい
    offset (= 読み終えた総行数) を返す。不正行はコマンド化せず読み飛ばすが
    offset には数える (再処理しないため)。ファイルがなければ空で返す。

    Args:
        path: control.jsonl のパス。
        offset: 既に処理した行数。

    Returns:
        (新規 ControlCommand のリスト, 更新後の offset)。
    """
    if not path.exists():
        return [], offset

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("failed to read control file %s", path, exc_info=True)
        return [], offset

    commands: list[ControlCommand] = []
    for line in lines[offset:]:
        cmd = parse_control_line(line)
        if cmd is not None:
            commands.append(cmd)
    return commands, len(lines)
