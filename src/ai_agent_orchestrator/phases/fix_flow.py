"""Bug 修正フローのヘルパ (U5a: fix の IMPLEMENT 統合).

ImplementExecutor から呼ばれる fix フェーズ固有の処理
（修正方針コメントの参照・修正 PR の作成と通知）を提供する。
旧 fix.py の FixExecutor から移植し、挙動は維持している。

注意: 循環 import 回避のため executor を引数で受け、そのプライベート
メソッド（_get_client / _ensure_pr_created 等）に依存する。
PhaseExecutor 側のシグネチャ変更時は本モジュールも追従が必要。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.models import AgentResult, TaskRequest
    from ai_agent_orchestrator.phases.base import PhaseExecutor

logger = logging.getLogger(__name__)


def is_fix_phase(request: TaskRequest) -> bool:
    """リクエストが旧 FIX フェーズかどうかを判定する。

    request.phase は Phase enum / 文字列の両方があり得るため正規化して比較する。

    Args:
        request: タスクリクエスト。

    Returns:
        fix フェーズなら True。
    """
    from ai_agent_orchestrator.models import Phase

    value = request.phase.value if isinstance(request.phase, Phase) else str(request.phase)
    return value.replace("_", "-").lower() == "fix"


async def build_fix_prompt(executor: PhaseExecutor, request: TaskRequest) -> str:
    """Bug 修正プロンプトを構築する（承認された修正方針コメントを参照）。

    Args:
        executor: 呼び出し元の executor（依存の取得に使用）。
        request: タスクリクエスト。

    Returns:
        プロンプト文字列。
    """
    from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt

    client = await executor._get_client(request.repo)
    issue = await client.get_issue(request.repo, request.issue_number)
    worktree = await executor._workspace.create_worktree(request.repo, request.issue_number)
    context = await executor._context.build_context(
        str(worktree),
        getattr(issue, "body", "") or "",
        "fix",
        issue_number=request.issue_number,
    )

    # 方針コメントを取得（直近の「修正方針」を含むコメント）
    comments = await client.list_comments(request.repo, request.issue_number)
    plan_comment = ""
    for c in reversed(comments):
        body = getattr(c, "body", "")
        if "修正方針" in body:
            plan_comment = body
            break

    raw = (
        f"承認された修正方針に基づいてバグを修正してください。\n\n"
        f"## Issue #{request.issue_number}: {issue.title}\n"
        f"{getattr(issue, 'body', '') or ''}\n\n"
        f"## 承認された修正方針\n{plan_comment}\n\n"
        f"## コンテキスト\n{context}\n\n"
        f"## 指示\n"
        f"1. 修正方針に従ってコードを修正\n"
        f"2. 再現テスト・リグレッションテストを作成\n"
        f"3. テスト・lint を実行して確認\n"
        f"4. **git commit / push / PR 作成は不要です** (システムが行います)"
    )
    return enhance_prompt(raw, "fix")


async def finalize_fix(
    executor: PhaseExecutor,
    request: TaskRequest,
    result: AgentResult,
) -> None:
    """修正 PR を作成し IMPL_REVIEW に遷移する。

    コミットは呼び出し元（ImplementExecutor._execute_fix）が
    _finalize_phase_commit で実施済みであることを前提とする。

    Args:
        executor: 呼び出し元の executor。
        request: タスクリクエスト。
        result: エージェント実行結果。
    """
    # PR番号を確実に取得 (エージェント出力 → 既存PR検索 → API作成)
    pr_number = await executor._ensure_pr_created(
        request,
        result.output,
        branch_prefix="feature",
        title_prefix="修正: ",
    )

    state = executor._sm.get_state(executor._issue_key(request))
    if state:
        state.pr_number = pr_number
        state.session_id = result.session_id

    client = await executor._get_client(request.repo)
    await client.replace_phase_label(request.repo, request.issue_number, "phase:review")
    await executor._sm.transition(executor._issue_key(request), "review")
    await executor._tracker.track(
        "fix_complete",
        issue_number=request.issue_number,
        phase="fix",
        data={"note": "impl-review に遷移", "pr_number": pr_number},
    )
    repo_full_name = executor._get_repo_full_name(request)
    pr_url = executor._build_pr_url(request, pr_number)
    issue = await client.get_issue(request.repo, request.issue_number)
    await executor._notifier.notify(
        f"Issue #{request.issue_number} の修正PR #{pr_number} を作成しました",
        metadata={
            "notification_type": "fix_pr_created",
            "issue": request.issue_number,
            "issue_title": issue.title,
            "pr": pr_number,
            "pr_url": pr_url,
            "repo": repo_full_name,
            "next_action": "→ 修正PRをレビューしてください",
        },
    )
