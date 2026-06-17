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
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)

ControlAction = Literal["approve", "reject", "prototype_revise"]
# prototype_revise (#145 Phase2): 設計承認段階で UI プロトタイプの修正を依頼する。
# 承認ではなく差し戻し系 (指摘) なので、reject と同じ feedback 経路に載せる。
_VALID_ACTIONS: frozenset[str] = frozenset({"approve", "reject", "prototype_revise"})
# DoS 対策: control.jsonl の最大サイズ (10 MiB)
_MAX_CONTROL_FILE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ControlCommand:
    """Web UI 等から受け取る承認/差し戻し制御コマンド."""

    issue_number: int
    action: ControlAction
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
    # bool は int のサブクラスなので除外する。issue は 1 以上の正整数のみ許可
    if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0 or action not in _VALID_ACTIONS:
        logger.warning("control line missing/invalid issue or action, skipping")
        return None

    # action は _VALID_ACTIONS で検証済み (approve/reject のいずれか)
    validated_action: ControlAction = action
    return ControlCommand(
        issue_number=issue,
        action=validated_action,
        approver=str(data.get("approver", "")),
        feedback=str(data.get("feedback", "")),
    )


def read_new_control_commands(
    path: Path,
    offset: int,
    approvers: Iterable[str],
) -> tuple[list[ControlCommand], int]:
    """control.jsonl から未処理かつ承認者検証を通過したコマンドのみを読み取る。

    offset は「既に処理した行数」。それ以降の行のみを対象とし、新しい
    offset (= 読み終えた総行数) を返す。不正行・許可外 approver のコマンドは
    読み飛ばすが offset には数える (再処理しないため)。

    #102 と同じ承認者検証を intake 境界で必須化する: approver が許可リストに
    含まれないコマンドは承認シグナルとして扱わない (Web UI 等からの
    なりすまし承認を防ぐ)。

    DoS 対策としてファイルサイズ上限 (_MAX_CONTROL_FILE_BYTES) を超える
    ファイルはスキップする。

    Args:
        path: control.jsonl のパス。
        offset: 既に処理した行数。
        approvers: 許可された承認者 login の集合 (resolve_approvers の結果)。

    Returns:
        (新規 ControlCommand のリスト, 更新後の offset)。
    """
    from ai_agent_orchestrator.orchestrator.approval import is_authorized_approver

    path = path.expanduser()
    if not path.exists():
        return [], offset

    try:
        if path.stat().st_size > _MAX_CONTROL_FILE_BYTES:
            logger.warning("control file %s exceeds size limit, skipping", path)
            return [], offset
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("failed to read control file %s", path, exc_info=True)
        return [], offset

    approver_list = list(approvers)
    commands: list[ControlCommand] = []
    for line in lines[offset:]:
        cmd = parse_control_line(line)
        if cmd is None:
            continue
        if not is_authorized_approver(cmd.approver, approver_list):
            logger.info(
                "control command for #%d from unauthorized approver '%s' ignored",
                cmd.issue_number,
                cmd.approver,
            )
            continue
        commands.append(cmd)
    return commands, len(lines)
