"""PLAN 生成プロトタイプ HTML の収集 (#145).

worktree にエージェントが生成した自己完結 HTML を ``artifacts/issue-{n}/prototype/``
へコピーし manifest.json を書き出す。例外は外に出さず、失敗は manifest の notes に
記録する (収集失敗が PLAN フェーズ全体を落とさないようにする)。

Phase3 (#145): 2〜3 案を生成する場合、worktree のサイドカー JSON
(``issue-{n}.prototypes.json``) に各案の id/title/description/file を記述する。
サイドカーが無ければ単一 HTML (``issue-{n}.prototype.html``) へフォールバックする。
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from ai_agent_orchestrator.prototype.paths import (
    prototype_dir,
    worktree_prototype_file,
    worktree_prototypes_manifest,
)

logger = logging.getLogger(__name__)

# 単一案フォールバック時の配信ファイル名 (sandbox iframe の src になる)。
PROTOTYPE_FILE = "index.html"
# DoS / 誤生成対策: 収集するプロトタイプ HTML の上限サイズ (2 MiB)。
_MAX_PROTOTYPE_BYTES = 2 * 1024 * 1024
# 1 Issue あたりの案数上限 (コスト・誤生成対策)。
_MAX_VARIANTS = 3
# variant id は配信ファイル名 (<id>.html) と URL に使うため安全な文字に限定する。
_VARIANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")


def collect_prototype(workspace_root: Path, issue_number: int, worktree_path: Path) -> bool:
    """worktree のプロトタイプ HTML を artifacts へ収集し manifest を書き出す.

    例外は送出しない。プロトタイプが無い/大きすぎる/コピー失敗は notes に記録した
    manifest を書き、False を返す。1 案でも収集できれば True。

    サイドカー JSON があれば複数案を収集し、無ければ単一 HTML へフォールバックする。

    Args:
        workspace_root: ワークスペースのベースディレクトリ。
        issue_number: Issue 番号。
        worktree_path: 対象 Issue の worktree ルート。

    Returns:
        プロトタイプを 1 案以上収集できたら True、そうでなければ False。
    """
    dest_dir = prototype_dir(workspace_root, issue_number)
    notes: list[str] = []
    # 反復回数 (#145 Phase2): 既存 manifest の iteration を引き継ぎ、収集成功でインクリメント。
    prev_iteration = _read_prev_iteration(dest_dir)
    items: list[dict[str, str]] = []

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        sidecar = worktree_prototypes_manifest(worktree_path, issue_number)
        if sidecar.is_file():
            items = _collect_variants(sidecar, dest_dir, issue_number, notes)
        else:
            items = _collect_single(worktree_path, dest_dir, issue_number, notes)
    except OSError as exc:
        logger.warning("Issue #%d: プロトタイプ収集に失敗: %s", issue_number, exc)
        notes.append("プロトタイプの収集に失敗しました。")

    collected = len(items) > 0
    # 収集成功時のみ反復をインクリメント。失敗時は前回値を維持する。
    iteration = prev_iteration + 1 if collected else prev_iteration
    _write_manifest(dest_dir, issue_number, items, notes, iteration)
    return collected


def _collect_single(worktree_path: Path, dest_dir: Path, issue_number: int, notes: list[str]) -> list[dict[str, str]]:
    """単一 HTML を収集する (Phase1/2 後方互換)."""
    src = worktree_prototype_file(worktree_path, issue_number)
    if not src.is_file():
        notes.append("プロトタイプ HTML が生成されませんでした。")
        return []
    if src.stat().st_size > _MAX_PROTOTYPE_BYTES:
        notes.append("プロトタイプ HTML がサイズ上限 (2MiB) を超えたため収集をスキップしました。")
        return []
    shutil.copy2(src, dest_dir / PROTOTYPE_FILE)
    return [{"id": "prototype", "title": "UI プロトタイプ", "description": "", "file": PROTOTYPE_FILE}]


def _collect_variants(sidecar: Path, dest_dir: Path, issue_number: int, notes: list[str]) -> list[dict[str, str]]:
    """サイドカー JSON に基づき複数案を収集する (#145 Phase3)."""
    try:
        raw = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        notes.append("プロトタイプ案の一覧 (prototypes.json) を読めませんでした。")
        return []
    entries = raw if isinstance(raw, list) else raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(entries, list) or not entries:
        notes.append("プロトタイプ案の一覧が空または不正です。")
        return []

    src_dir = sidecar.parent
    items: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for entry in entries[:_MAX_VARIANTS]:
        item = _collect_one_variant(entry, src_dir, dest_dir, seen_ids, notes)
        if item is not None:
            items.append(item)
            seen_ids.add(item["id"])
    return items


def _collect_one_variant(
    entry: object,
    src_dir: Path,
    dest_dir: Path,
    seen_ids: set[str],
    notes: list[str],
) -> dict[str, str] | None:
    """1 案分のエントリを検証してコピーし manifest item を返す (不正は None)."""
    if not isinstance(entry, dict):
        return None
    variant_id = str(entry.get("id", "")).strip()
    file_name = str(entry.get("file", "")).strip()
    if not _VARIANT_ID_RE.match(variant_id) or variant_id in seen_ids:
        notes.append(f"案 id '{variant_id}' が不正または重複のためスキップしました。")
        return None
    # パストラバーサル防止: file は basename のみ許可する。
    if not file_name or file_name != Path(file_name).name or ".." in file_name:
        notes.append(f"案 '{variant_id}' のファイル名が不正のためスキップしました。")
        return None
    src = src_dir / file_name
    if not src.is_file():
        notes.append(f"案 '{variant_id}' の HTML が見つかりませんでした。")
        return None
    if src.stat().st_size > _MAX_PROTOTYPE_BYTES:
        notes.append(f"案 '{variant_id}' の HTML がサイズ上限 (2MiB) を超えたためスキップしました。")
        return None
    dest_name = f"{variant_id}.html"
    shutil.copy2(src, dest_dir / dest_name)
    title = str(entry.get("title", "")).strip() or variant_id
    description = str(entry.get("description", "")).strip()
    return {"id": variant_id, "title": title, "description": description, "file": dest_name}


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
    items: list[dict[str, str]],
    notes: list[str],
    iteration: int,
) -> None:
    """prototype/manifest.json を書き出す (失敗は握り潰す)."""
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
