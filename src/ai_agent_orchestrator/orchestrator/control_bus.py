"""ControlBus: control.jsonl の運用コマンド (#87 基盤 + #96 拡張).

対応 action: pause / resume / abort / shutdown (#87)、
poll_now / worktree_gc / enqueue_issue (#96)。
poll_now / worktree_gc は issue 不要の全体コマンド、それ以外は issue-scoped。

Web UI 等からの介入を、実行中の asyncio タスクに直接触れず安全に適用するための
ファイルベースのコマンドキュー。control.jsonl は承認系 (approve/reject,
``control_file.py``) と同居するが、運用コマンドは本モジュールが**別系統・専用
offset** で消費する (承認系の行は無視する)。

JSONL の 1 行フォーマット::

    {"action": "pause", "issue": 5, "actor": "alice"}
    {"action": "resume", "issue": 5, "actor": "alice"}
    {"action": "abort", "issue": 6, "actor": "alice"}
    {"action": "shutdown", "actor": "alice"}

承認系コマンド (approve/reject) は本パーサでは ``None`` として読み飛ばす。
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

OperationalAction = Literal[
    "pause",
    "resume",
    "abort",
    "shutdown",
    "poll_now",
    "worktree_gc",
    "enqueue_issue",
    "set_priority",
    "reorder",
    "rewind",
    "retry_with_analysis",
]
_OPERATIONAL_ACTIONS: frozenset[str] = frozenset(
    {
        "pause",
        "resume",
        "abort",
        "shutdown",
        "poll_now",
        "worktree_gc",
        "enqueue_issue",
        "set_priority",
        "reorder",
        "rewind",
        "retry_with_analysis",
    }
)
# issue 番号を必要としない全体コマンド (shutdown と #96 の poll_now / worktree_gc)。
# reorder も issue 単独では特定できないが order を取るため別途処理する。
_GLOBAL_ACTIONS: frozenset[str] = frozenset({"shutdown", "poll_now", "worktree_gc"})
# DoS 対策: control.jsonl の最大サイズ (10 MiB)。control_file.py と同値。
_MAX_CONTROL_FILE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class OperationalCommand:
    """ControlBus の運用コマンド (#87 基盤 + #96 拡張).

    issue-scoped でないコマンド (shutdown/poll_now/worktree_gc/reorder) は
    ``issue_number`` が None。``phase``/``priority`` は set_priority、``order`` は
    reorder でのみ使用する。
    """

    action: OperationalAction
    issue_number: int | None
    actor: str = ""
    phase: str | None = None
    priority: int | None = None
    # reorder の希望順: (issue_number, phase) のタプル列 (frozen のため tuple)。
    order: tuple[tuple[int, str], ...] | None = None
    # rewind の巻き戻し先フェーズ (Phase.value 文字列)。
    target: str | None = None


def parse_operational_line(line: str) -> OperationalCommand | None:
    """control.jsonl の 1 行を OperationalCommand にパースする。

    運用コマンド以外 (approve/reject 等)・不正 JSON・必須欠落・型不正は
    ``None`` を返す (呼び出し側で読み飛ばす)。

    Args:
        line: JSONL の 1 行。

    Returns:
        OperationalCommand、または対象外/不正なら None。
    """
    text = line.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    action = data.get("action")
    if action not in _OPERATIONAL_ACTIONS:
        # approve/reject 等の承認系・未知 action は運用 ControlBus の対象外。
        return None

    validated_action: OperationalAction = action
    actor = str(data.get("actor", ""))

    if action in _GLOBAL_ACTIONS:
        return OperationalCommand(action=validated_action, issue_number=None, actor=actor)

    if action == "reorder":
        order = _parse_order(data.get("order"))
        if order is None:
            logger.warning("reorder command missing/invalid order, skipping")
            return None
        return OperationalCommand(action="reorder", issue_number=None, actor=actor, order=order)

    issue = data.get("issue")
    # bool は int のサブクラス。issue は 1 以上の正整数のみ許可。
    if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0:
        logger.warning("operational command '%s' missing/invalid issue, skipping", action)
        return None

    if action == "set_priority":
        phase = data.get("phase")
        priority = data.get("priority")
        if not isinstance(phase, str) or not phase:
            logger.warning("set_priority command missing/invalid phase, skipping")
            return None
        if not isinstance(priority, int) or isinstance(priority, bool):
            logger.warning("set_priority command missing/invalid priority, skipping")
            return None
        return OperationalCommand(
            action="set_priority",
            issue_number=issue,
            actor=actor,
            phase=phase,
            priority=priority,
        )

    if action == "rewind":
        target = data.get("target")
        if not isinstance(target, str) or not target:
            logger.warning("rewind command missing/invalid target, skipping")
            return None
        return OperationalCommand(action="rewind", issue_number=issue, actor=actor, target=target)

    return OperationalCommand(action=validated_action, issue_number=issue, actor=actor)


def _parse_order(raw: object) -> tuple[tuple[int, str], ...] | None:
    """reorder の order フィールドを (issue_number, phase) タプル列にパースする。

    各要素は ``{"issue": <正整数>, "phase": <非空 str>}``。1 つでも不正なら None。
    """
    if not isinstance(raw, list) or not raw:
        return None
    entries: list[tuple[int, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        issue = item.get("issue")
        phase = item.get("phase")
        if not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0:
            return None
        if not isinstance(phase, str) or not phase:
            return None
        entries.append((issue, phase))
    return tuple(entries)


def read_new_operational_commands(
    path: Path,
    offset: int,
    authorized_actors: Iterable[str],
) -> tuple[list[OperationalCommand], int]:
    """control.jsonl から未処理かつ認可済みの運用コマンドのみを読み取る。

    ``offset`` は「既に処理した行数」。それ以降の行のみを対象とし、新しい
    offset (= 読み終えた総行数) を返す。不正行・認可外 actor・承認系の行は
    読み飛ばすが offset には数える (再処理しないため)。

    認可は #102 と同じく ``is_authorized_approver`` で行う: actor が
    許可リストに含まれない運用コマンドは無視する。ただし #102 が GitHub 検証済みの
    送信者を見るのに対し、ここでの actor は POST /api/control の自己申告フィールド
    である。AuthMiddleware が no-op の現状では actor 詐称を防げないため、本検証は
    パース衛生・誤操作防止が主で、なりすまし防止としては実認証導入まで限定的
    (localhost 前提・#115 で対処)。

    DoS 対策としてファイルサイズ上限 (_MAX_CONTROL_FILE_BYTES) を超える
    ファイルはスキップする。

    Args:
        path: control.jsonl のパス。
        offset: 既に処理した行数。
        authorized_actors: 許可された actor login の集合。

    Returns:
        (新規 OperationalCommand のリスト, 更新後の offset)。
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

    actor_list = list(authorized_actors)
    commands: list[OperationalCommand] = []
    for line in lines[offset:]:
        cmd = parse_operational_line(line)
        if cmd is None:
            continue
        if not is_authorized_approver(cmd.actor, actor_list):
            logger.info(
                "operational command '%s' from unauthorized actor '%s' ignored",
                cmd.action,
                cmd.actor,
            )
            continue
        commands.append(cmd)
    return commands, len(lines)
