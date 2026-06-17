"""PLAN 生成プロトタイプ HTML の収集 (#145).

worktree にエージェントが生成した自己完結 HTML を ``artifacts/issue-{n}/prototype/``
へコピーし manifest.json を書き出す。例外は外に出さず、失敗は manifest の notes に
記録する (収集失敗が PLAN フェーズ全体を落とさないようにする)。
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from ai_agent_orchestrator.prototype.paths import prototype_dir, worktree_prototype_file

logger = logging.getLogger(__name__)

# 配信ファイル名 (sandbox iframe の src になる)。
PROTOTYPE_FILE = "index.html"
# DoS / 誤生成対策: 収集するプロトタイプ HTML の上限サイズ (2 MiB)。
_MAX_PROTOTYPE_BYTES = 2 * 1024 * 1024


def collect_prototype(workspace_root: Path, issue_number: int, worktree_path: Path) -> bool:
    """worktree のプロトタイプ HTML を artifacts へ収集し manifest を書き出す.

    例外は送出しない。プロトタイプが無い/大きすぎる/コピー失敗は notes に記録した
    manifest を書き、False を返す。成功時は True。

    Args:
        workspace_root: ワークスペースのベースディレクトリ。
        issue_number: Issue 番号。
        worktree_path: 対象 Issue の worktree ルート。

    Returns:
        プロトタイプを収集できたら True、そうでなければ False。
    """
    dest_dir = prototype_dir(workspace_root, issue_number)
    src = worktree_prototype_file(worktree_path, issue_number)
    notes: list[str] = []
    collected = False
    # 反復回数 (#145 Phase2): 既存 manifest の iteration を引き継ぎ、収集成功でインクリメント。
    prev_iteration = _read_prev_iteration(dest_dir)

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not src.is_file():
            notes.append("プロトタイプ HTML が生成されませんでした。")
        elif src.stat().st_size > _MAX_PROTOTYPE_BYTES:
            notes.append("プロトタイプ HTML がサイズ上限 (2MiB) を超えたため収集をスキップしました。")
        else:
            shutil.copy2(src, dest_dir / PROTOTYPE_FILE)
            collected = True
    except OSError as exc:
        logger.warning("Issue #%d: プロトタイプ収集に失敗: %s", issue_number, exc)
        notes.append("プロトタイプの収集に失敗しました。")

    # 収集成功時のみ反復をインクリメント。失敗時は前回値を維持する。
    iteration = prev_iteration + 1 if collected else prev_iteration
    _write_manifest(dest_dir, issue_number, collected, notes, iteration)
    return collected


def _read_prev_iteration(dest_dir: Path) -> int:
    """既存 manifest.json の iteration を読む (不在/不正は 0)."""
    manifest_path = dest_dir / "manifest.json"
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(raw, dict):
        return 0
    value = raw.get("iteration")
    # bool は int のサブクラスなので除外する。
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


def _write_manifest(
    dest_dir: Path,
    issue_number: int,
    collected: bool,
    notes: list[str],
    iteration: int,
) -> None:
    """prototype/manifest.json を書き出す (失敗は握り潰す)."""
    items = (
        [
            {
                "id": "prototype",
                "title": "UI プロトタイプ",
                "file": PROTOTYPE_FILE,
            }
        ]
        if collected
        else []
    )
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "iteration": iteration,
        "items": items,
        "notes": notes,
    }
    try:
        (dest_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("Issue #%d: prototype manifest 書き出しに失敗: %s", issue_number, exc)
