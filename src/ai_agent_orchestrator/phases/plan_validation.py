"""実装計画の妥当性チェックフェーズ.

PLANNING → PLAN_VALIDATION → IMPLEMENT のフローで、
計画の構造的妥当性を検証してから実装に進む。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ai_agent_orchestrator.models import AgentResult, TaskRequest
from ai_agent_orchestrator.phases.base import PhaseExecutor

logger = logging.getLogger(__name__)

# 差し戻し上限 (無限ループ防止)
_MAX_REPLAN_COUNT = 2


class PlanValidationExecutor(PhaseExecutor):
    """実装計画の妥当性をチェックするフェーズ.

    Claude を使わず、構造的な検証のみを行う軽量フェーズ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """このフェーズでは Claude を実行しないため空文字を返す."""
        return ""

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """Claude を実行せず、計画ファイルを直接検証する."""
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="feature",
        )

        plan_path = Path(str(worktree)) / "docs" / "designs" / f"issue-{request.issue_number}-plan.md"
        if not plan_path.exists():
            msg = f"計画ファイルが見つかりません: {plan_path}. PLANNING フェーズが正常完了していない可能性があります。"
            raise RuntimeError(msg)

        plan_text = plan_path.read_text(encoding="utf-8")
        errors = validate_plan(plan_text, str(worktree))

        output = "OK" if not errors else "\n".join(errors)
        return AgentResult(
            session_id="",
            output=output,
            tool_uses=[],
            cost_usd=0.0,
            duration_sec=0.0,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """検証結果に基づいて IMPLEMENT or PLANNING に遷移する."""
        client = await self._get_client(request.repo)

        if result.output == "OK":
            logger.info("Issue #%d: 計画検証OK → IMPLEMENT へ遷移", request.issue_number)
            await client.replace_phase_label(request.repo, request.issue_number, "phase:implement")
            await self._sm.transition(self._issue_key(request), "implement")
            return

        # 検証失敗: 差し戻し回数チェック
        state = self._sm.get_state(self._issue_key(request))
        replan_count = 0
        if state:
            replan_count = getattr(state, "replan_count", 0)

        if replan_count >= _MAX_REPLAN_COUNT:
            logger.warning(
                "Issue #%d: 計画検証失敗 (%d回目) → 上限到達、警告付きで IMPLEMENT へ",
                request.issue_number,
                replan_count + 1,
            )
            await client.create_comment(
                request.repo,
                request.issue_number,
                f"⚠️ 計画の検証に問題がありますが、差し戻し上限 ({_MAX_REPLAN_COUNT}回) に達したため実装に進みます。\n\n"
                f"**検証結果:**\n{result.output}",
            )
            await client.replace_phase_label(request.repo, request.issue_number, "phase:implement")
            await self._sm.transition(self._issue_key(request), "implement")
            return

        # 差し戻し: PLANNING へ (カウンターをインクリメント)
        if state:
            state.replan_count = replan_count + 1
        logger.info(
            "Issue #%d: 計画検証失敗 → PLANNING へ差し戻し (%d/%d)",
            request.issue_number,
            replan_count + 1,
            _MAX_REPLAN_COUNT,
        )
        await client.create_comment(
            request.repo,
            request.issue_number,
            f"📋 計画の検証で問題が見つかりました。再計画します。\n\n**検証結果:**\n{result.output}",
        )
        await client.replace_phase_label(request.repo, request.issue_number, "phase:planning")
        await self._sm.transition(self._issue_key(request), "planning")


# ---------------------------------------------------------------------------
# 計画検証ロジック (純粋関数)
# ---------------------------------------------------------------------------

# subtask ヘッダー: ### subtask-N: <title>
_SUBTASK_HEADER = re.compile(r"^###\s+subtask-(\d+):", re.MULTILINE)

# depends_on: [1, 2] or depends_on: []
_DEPENDS_ON = re.compile(r"-\s*depends_on:\s*\[([^\]]*)\]")

# files: [`path/to/a.py`, `path/to/b.py`]
_FILES = re.compile(r"-\s*files:\s*\[([^\]]*)\]")


def validate_plan(plan_text: str, worktree_path: str) -> list[str]:
    """実装計画テキストの妥当性を検証する.

    Args:
        plan_text: 実装計画のマークダウンテキスト。
        worktree_path: worktree のルートパス。

    Returns:
        エラーメッセージのリスト。空リストなら検証OK。
    """
    errors: list[str] = []

    # 1. サブタスクのパース
    subtask_ids = [int(m.group(1)) for m in _SUBTASK_HEADER.finditer(plan_text)]
    if not subtask_ids:
        errors.append("サブタスクが見つかりません。`### subtask-N:` 形式のヘッダーが必要です。")
        return errors

    # 2. 連番チェック
    expected = list(range(1, len(subtask_ids) + 1))
    if subtask_ids != expected:
        errors.append(f"サブタスク番号が連番ではありません: {subtask_ids} (期待: {expected})")

    # 3. 依存関係の循環チェック
    deps: dict[int, list[int]] = {}
    for m in _DEPENDS_ON.finditer(plan_text):
        # 直前の subtask ヘッダーを探す
        before_text = plan_text[: m.start()]
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

    # 5. テストファイルの存在チェック (警告のみ)
    all_files: list[str] = []
    for m in _FILES.finditer(plan_text):
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
