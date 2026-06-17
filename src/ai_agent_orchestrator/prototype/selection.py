"""ユーザーが選択した UI プロトタイプ案の永続化 (#145 Phase3).

承認画面で選んだ案 id を ``artifacts/issue-{n}/prototype/selection.json`` に保存し、
PLAN の修正反復・IMPLEMENT の実装土台として読み出す。worktree の外 (artifacts) に
置くため git へ誤コミットされない。例外は送出せず、不在/不正は None を返す。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from ai_agent_orchestrator.prototype.paths import prototype_dir

logger = logging.getLogger(__name__)

_SELECTION_FILE = "selection.json"
# variant id は collector と同じ安全な文字に限定する。
_VARIANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")


def selection_path(workspace_root: Path, issue_number: int) -> Path:
    """selection.json のパスを返す."""
    return prototype_dir(workspace_root, issue_number) / _SELECTION_FILE


def read_selection(workspace_root: Path, issue_number: int) -> str | None:
    """選択された variant id を読む (不在/不正は None)."""
    path = selection_path(workspace_root, issue_number)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    variant_id = raw.get("variant_id")
    if isinstance(variant_id, str) and _VARIANT_ID_RE.match(variant_id):
        return variant_id
    return None


def write_selection(workspace_root: Path, issue_number: int, variant_id: str) -> bool:
    """選択された variant id を書き込む (成功で True)。

    variant_id の妥当性検証 (存在する案か) は呼び出し側で行う。ここでは形式のみ検証する。
    """
    if not _VARIANT_ID_RE.match(variant_id):
        return False
    path = selection_path(workspace_root, issue_number)
    payload = {"variant_id": variant_id, "selected_at": datetime.now(UTC).isoformat()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Issue #%d: prototype selection 書き出しに失敗: %s", issue_number, exc)
        return False
    return True
