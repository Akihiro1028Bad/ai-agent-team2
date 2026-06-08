"""実装計画の妥当性チェックロジック (純粋関数).

design.py が実装計画を生成後、その構造的妥当性を検証するために使用する。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 計画検証ロジック (純粋関数)
# ---------------------------------------------------------------------------

# ## サブタスク セクション抽出パターン (implement.py の parse_subtasks と同一スコープ)
_SUBTASK_SECTION = re.compile(r"##\s+サブタスク(.+?)(?=\n##\s|\Z)", re.DOTALL)

# subtask ヘッダー: ### subtask-N: <title>
_SUBTASK_HEADER = re.compile(r"^###\s+subtask-(\d+):", re.MULTILINE)

# depends_on: [1, 2] or depends_on: []
_DEPENDS_ON = re.compile(r"-\s*depends_on:\s*\[([^\]]*)\]")

# files: [`path/to/a.py`, `path/to/b.py`]
_FILES = re.compile(r"-\s*files:\s*\[([^\]]*)\]")


def validate_plan(plan_text: str, worktree_path: str) -> list[str]:
    """実装計画テキストの妥当性を検証する.

    ``## サブタスク`` セクション内のみを対象に検証する。
    これは implement.py の ``parse_subtasks`` と同一スコープにすることで、
    設計書本文の他の ``###`` 見出しとの衝突を防ぐ。

    Args:
        plan_text: 実装計画のマークダウンテキスト。
        worktree_path: worktree のルートパス。

    Returns:
        エラーメッセージのリスト。空リストなら検証OK。
    """
    errors: list[str] = []

    # 0. ## サブタスク セクションを抽出
    section_match = _SUBTASK_SECTION.search(plan_text)
    if not section_match:
        errors.append(
            "## サブタスク セクションが見つかりません。"
            "設計書末尾に `## サブタスク` セクションを追加してください。"
        )
        return errors

    section_text = section_match.group(1)

    # 1. サブタスクのパース (セクション内のみ)
    subtask_ids = [int(m.group(1)) for m in _SUBTASK_HEADER.finditer(section_text)]
    if not subtask_ids:
        errors.append("サブタスクが見つかりません。`### subtask-N:` 形式のヘッダーが必要です。")
        return errors

    # 2. 連番チェック
    expected = list(range(1, len(subtask_ids) + 1))
    if subtask_ids != expected:
        errors.append(f"サブタスク番号が連番ではありません: {subtask_ids} (期待: {expected})")

    # 3. 依存関係の循環チェック (セクション内のみ)
    deps: dict[int, list[int]] = {}
    for m in _DEPENDS_ON.finditer(section_text):
        # 直前の subtask ヘッダーを探す
        before_text = section_text[: m.start()]
        headers_before = list(_SUBTASK_HEADER.finditer(before_text))
        if headers_before:
            task_id = int(headers_before[-1].group(1))
            dep_str = m.group(1).strip()
            dep_ids = [int(d.strip()) for d in dep_str.split(",") if d.strip().isdigit()]
            deps[task_id] = dep_ids

    cycle = _detect_cycle(deps, set(subtask_ids))
    if cycle:
        errors.append(f"依存関係に循環があります: {cycle}")

    # 4. 未定義の依存先チェック
    all_ids = set(subtask_ids)
    for task_id, dep_list in deps.items():
        errors.extend(
            f"subtask-{task_id} が未定義の subtask-{dep} に依存しています" for dep in dep_list if dep not in all_ids
        )

    # 5. テストファイルの存在チェック (セクション内のみ)
    all_files: list[str] = []
    for m in _FILES.finditer(section_text):
        file_str = m.group(1)
        files = [f.strip().strip("`").strip("'").strip('"') for f in file_str.split(",")]
        all_files.extend(f for f in files if f)

    has_test_file = any("test" in f.lower() for f in all_files)
    if not has_test_file:
        errors.append("テストファイルがサブタスクに含まれていません (テスト作成を計画に含めてください)")

    return errors


def _detect_cycle(deps: dict[int, list[int]], all_ids: set[int]) -> list[int] | None:
    """依存グラフの循環を検出する.

    Args:
        deps: タスクID → 依存先IDリストの辞書。
        all_ids: 全タスクIDの集合。

    Returns:
        循環が見つかった場合はそのパスのリスト。なければ None。
    """
    visited: set[int] = set()
    in_stack: set[int] = set()
    path: list[int] = []

    def dfs(node: int) -> bool:
        visited.add(node)
        in_stack.add(node)
        path.append(node)
        for dep in deps.get(node, []):
            if dep in in_stack:
                path.append(dep)
                return True
            if dep not in visited and dfs(dep):
                return True
        path.pop()
        in_stack.remove(node)
        return False

    for node in all_ids:
        if node not in visited and dfs(node):
            return path
    return None
