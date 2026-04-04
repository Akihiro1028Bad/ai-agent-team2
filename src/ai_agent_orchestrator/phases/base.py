"""PhaseExecutor 基底クラス."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ai_agent_orchestrator.models import Phase

if TYPE_CHECKING:
    from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
    from ai_agent_orchestrator.context.engine import ContextEngine
    from ai_agent_orchestrator.models import AgentResult, IssueKey, TaskRequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Next action footer for bot comments
# ---------------------------------------------------------------------------

_APPROVE_ACTION = (
    "👍 **次のアクション**: この方針でよければ**コメントに👍リアクション**、修正があれば**コメントで指摘**してください"
)
_SPLIT_APPROVE_ACTION = (
    "👍 **次のアクション**: この分割案でよければ"
    "**コメントに👍リアクション**、修正があれば**コメントで修正指示**してください"
)

_NEXT_ACTION: dict[str, str] = {
    "type-detection": "",
    "hearing": "📝 **次のアクション**: このコメントに**コメントで回答**してください",
    "analysis": _APPROVE_ACTION,
    "design": "",
    "design-review": "",
    "design-revise": "📋 **次のアクション**: 設計PRで**再レビュー**をお願いします",
    "planning": "",
    "implement": "",
    "impl-review": "",
    "impl-revise": "📋 **次のアクション**: 実装PRで**再レビュー**をお願いします",
    "ci-fix": "",
    "split-proposal": _SPLIT_APPROVE_ACTION,
    "split-execute": "",
    "done": "",
}


def next_action_footer(phase: str) -> str:
    """フェーズに応じた次アクションフッターを返す.

    Args:
        phase: フェーズ名.

    Returns:
        フッター文字列。該当なしの場合は空文字列。
    """
    action = _NEXT_ACTION.get(phase, "")
    if not action:
        return ""
    return f"\n\n---\n{action}"


# ---------------------------------------------------------------------------
# Protocol stubs for dependencies (avoid circular imports)
# ---------------------------------------------------------------------------


@runtime_checkable
class IssueData(Protocol):
    """Protocol for issue data returned by GitHub client."""

    title: str
    body: str | None


@runtime_checkable
class IssueStateData(Protocol):
    """Protocol for issue state returned by state machine."""

    session_id: str | None
    pr_number: int | None
    design_pr_number: int | None
    branch_head_sha: str | None
    impl_iteration: int
    retry_count: int
    replan_count: int


@runtime_checkable
class CommentData(Protocol):
    """Protocol for comment data returned by GitHub client."""

    body: str
    user: object


class GitHubClientProtocol:
    """Minimal GitHub client protocol used by phase executors."""

    async def get_issue(self, repo: object, issue_number: int) -> IssueData:
        """Get an issue."""
        raise NotImplementedError  # pragma: no cover

    async def create_comment(self, repo: object, issue_number: int, body: str) -> object:
        """Create a comment on an issue."""
        ...  # pragma: no cover

    async def list_comments(self, repo: object, issue_number: int, since: str | None = None) -> list[CommentData]:
        """List comments on an issue."""
        return []  # pragma: no cover

    async def add_label(self, repo: object, issue_number: int, label: str) -> None:
        """Add a label to an issue."""
        ...  # pragma: no cover

    async def replace_phase_label(self, repo: object, issue_number: int, new_label: str) -> None:
        """Replace phase:* labels with a new phase label."""
        ...  # pragma: no cover

    async def close_issue(self, repo: object, issue_number: int) -> None:
        """Close an issue."""
        ...  # pragma: no cover

    async def merge_pull_request(self, repo: object, pr_number: int, merge_method: str = "squash") -> None:
        """Merge a pull request."""
        ...  # pragma: no cover

    async def create_pull_request(
        self,
        repo: object,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> object:
        """Create a pull request."""
        raise NotImplementedError  # pragma: no cover

    async def list_pull_requests(
        self,
        repo: object,
        state: str = "open",
        head: str | None = None,
    ) -> list[object]:
        """List pull requests."""
        return []  # pragma: no cover

    async def reply_to_review_comment(
        self,
        repo: object,
        pr_number: int,
        comment_id: int,
        body: str,
    ) -> None:
        """Reply to a PR review comment thread."""
        ...  # pragma: no cover


class NotifierProtocol:
    """Minimal notifier protocol."""

    async def notify(
        self,
        message: str,
        *,
        level: str = "info",
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Send a notification."""
        ...  # pragma: no cover


class TrackerProtocol:
    """Minimal tracker protocol."""

    async def track(self, event: str, **kwargs: object) -> None:
        """Record an event."""
        ...  # pragma: no cover


class StateMachineProtocol:
    """Minimal state machine protocol."""

    def get_state(self, issue_key: IssueKey) -> IssueStateData | None:
        """Get state for an issue."""
        ...  # pragma: no cover

    def get_phase(self, issue_key: IssueKey) -> Phase | None:
        """Get the current phase for an issue."""
        ...  # pragma: no cover

    def get_issue_type(self, issue_key: IssueKey) -> str:
        """Get the issue type."""
        return ""  # pragma: no cover

    def set_issue_type(self, issue_key: IssueKey, issue_type: str) -> None:
        """Set the issue type."""
        ...  # pragma: no cover

    async def transition(self, issue_key: IssueKey, phase: str) -> None:
        """Transition to a new phase."""
        ...  # pragma: no cover

    async def increment_ci_retry(self, issue_key: IssueKey) -> None:
        """Increment CI retry counter."""
        ...  # pragma: no cover


class WorkspaceProtocol:
    """Minimal workspace protocol."""

    async def create_worktree(
        self,
        repo: object,
        issue_number: int,
        *,
        branch_prefix: str = "feature",
    ) -> str:
        """Create or get a worktree path."""
        return ""  # pragma: no cover

    async def _run_git(
        self,
        *args: str,
        cwd: str | Path | None = None,
    ) -> tuple[int, str, str]:
        """Run a git command."""
        return (0, "", "")  # pragma: no cover

    async def remove_worktree(self, repo: object, issue_number: int) -> None:
        """Remove a worktree."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# PhaseExecutor ABC
# ---------------------------------------------------------------------------


class PhaseExecutor(ABC):
    """フェーズ実行の基底クラス。

    全フェーズ共通の依存オブジェクト保持と、
    「プロンプト構築 -> エージェント実行 -> 結果処理」のテンプレートメソッドを提供する。
    """

    def __init__(
        self,
        runner: ClaudeAgentRunner,
        account_manager: GitHubClientProtocol | object,
        notifier: NotifierProtocol,
        tracker: TrackerProtocol,
        workspace: WorkspaceProtocol,
        context_engine: ContextEngine,
        state_machine: StateMachineProtocol,
    ) -> None:
        """共通依存オブジェクトを注入する。

        Args:
            runner: Claude Agent SDK ランナー。
            account_manager: AccountManager またはGitHub API クライアント。
                AccountManager の場合は _get_client() でリポジトリに
                紐づく GitHubClient を動的に解決する。
            notifier: 通知送信 (Slack 等)。
            tracker: イベントログ追跡。
            workspace: ワークスペース (worktree) 管理。
            context_engine: コンテキスト構築エンジン。
            state_machine: ステートマシンマネージャ。
        """
        self._runner = runner
        self._account_manager = account_manager
        self._notifier = notifier
        self._tracker = tracker
        self._workspace = workspace
        self._context = context_engine
        self._sm = state_machine

    async def _get_client(self, repo: object) -> GitHubClientProtocol:
        """リポジトリに対応する GitHubClient を取得する。

        AccountManager が渡されている場合はリポジトリ設定から
        対応アカウントの GitHubClient を動的に解決する。
        テスト等で直接 GitHubClient (またはモック) が渡されている場合は
        そのまま返す。

        Args:
            repo: リポジトリ設定オブジェクト。

        Returns:
            GitHubClientProtocol 互換のクライアント。
        """
        if hasattr(self._account_manager, "get_client_for_repo"):
            owner = getattr(repo, "owner", "")
            repo_name = getattr(repo, "repo", "")
            result: GitHubClientProtocol = await self._account_manager.get_client_for_repo(owner, repo_name)
            return result
        return self._account_manager  # type: ignore[return-value]

    def _issue_key(self, request: TaskRequest) -> IssueKey:
        """TaskRequest から IssueKey を生成する.

        Args:
            request: タスクリクエスト。

        Returns:
            IssueKey タプル。
        """
        repo_key = self._get_repo_full_name(request)
        return (repo_key, request.issue_number)

    def _get_repo_full_name(self, request: TaskRequest) -> str:
        """リポジトリのフルネーム (owner/repo) を取得する.

        Args:
            request: タスクリクエスト。

        Returns:
            "owner/repo" 形式の文字列。
        """
        owner = getattr(request.repo, "owner", "")
        repo_name = getattr(request.repo, "repo", "")
        if owner and repo_name:
            return f"{owner}/{repo_name}"
        return ""

    def _build_pr_url(self, request: TaskRequest, pr_number: int) -> str | None:
        """GitHub PR URL を構築する.

        Args:
            request: タスクリクエスト。
            pr_number: PR番号。

        Returns:
            GitHub PR URL。owner または repo_name が取得できない場合は None。
        """
        repo_full = self._get_repo_full_name(request)
        if not repo_full:
            return None
        return f"https://github.com/{repo_full}/pull/{pr_number}"

    async def execute(self, request: TaskRequest) -> None:
        """フェーズを実行する (テンプレートメソッド)。

        1. build_prompt() でプロンプトを構築
        2. run_agent() でエージェントを実行
        3. process_result() で結果を処理・状態更新

        エラー時は _handle_error() で SUSPENDED 遷移 + 通知。
        タイムアウト時は _handle_timeout() でセッション中断 + 通知。

        Args:
            request: タスクリクエスト。
        """
        try:
            await self._tracker.track(
                "phase_start",
                issue_number=request.issue_number,
                phase=str(request.phase),
            )

            prompt = await self.build_prompt(request)
            await self._record_branch_baseline(request)
            result = await self.run_agent(request, prompt)
            await self.process_result(request, result)

            await self._tracker.track(
                "phase_end",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={
                    "cost_usd": result.cost_usd,
                    "duration_sec": result.duration_sec,
                },
            )
        except TimeoutError:
            await self._handle_timeout(request)
        except Exception as exc:
            await self._handle_error(request, exc)

    @abstractmethod
    async def build_prompt(self, request: TaskRequest) -> str:
        """フェーズ固有のプロンプトを構築する。

        Args:
            request: タスクリクエスト。

        Returns:
            エージェントに渡すプロンプト文字列。
        """
        ...

    @property
    def _branch_prefix(self) -> str:
        """worktree のブランチプレフィックス。サブクラスでオーバーライド可能。"""
        return "feature"

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """エージェントを実行する。

        サブクラスでオーバーライド可能 (セッション継続が必要な場合等)。

        Args:
            request: タスクリクエスト。
            prompt: 構築されたプロンプト。

        Returns:
            エージェント実行結果。
        """
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix=self._branch_prefix,
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase=str(request.phase),
        )

    @abstractmethod
    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """実行結果を処理する。

        Issue コメント投稿、PR 作成確認、状態遷移等のフェーズ固有ロジック。

        Args:
            request: タスクリクエスト。
            result: エージェント実行結果。
        """
        ...

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    async def _handle_timeout(self, request: TaskRequest) -> None:
        """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + 通知。

        既に DONE に到達している場合は suspended にしない (重複実行の残留タスク対策)。
        """
        current = self._sm.get_phase(self._issue_key(request))
        if current == Phase.DONE:
            logger.warning(
                "Issue #%d: timeout in stale task (phase=%s) but already DONE, skipping suspend",
                request.issue_number,
                request.phase,
            )
            return
        state = self._sm.get_state(self._issue_key(request))
        if state and state.session_id:
            await self._runner.interrupt(state.session_id)

        await self._sm.transition(self._issue_key(request), "suspended")

        # events.jsonl にタイムアウト情報を記録
        try:
            await self._tracker.track(
                "phase_suspended",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={"suspend_reason": "timeout"},
            )
        except Exception:
            logger.warning("Failed to track phase_suspended event for issue #%d", request.issue_number)

        try:
            client = await self._get_client(request.repo)
            await client.replace_phase_label(request.repo, request.issue_number, "phase:suspended")
            # Issue にタイムアウト理由をコメント
            try:
                await client.create_comment(
                    request.repo,
                    request.issue_number,
                    f"⏱ タイムアウトしました (phase: {request.phase})。手動での確認をお願いします。",
                )
            except Exception:
                logger.warning("Failed to post timeout comment for issue #%d", request.issue_number)
        except Exception:
            logger.warning("Failed to update phase label to suspended for issue #%d", request.issue_number)
        repo_full_name = self._get_repo_full_name(request)
        try:
            await self._notifier.notify(
                f"Issue #{request.issue_number} がタイムアウトしました (phase: {request.phase})",
                level="error",
                metadata={
                    "notification_type": "timeout",
                    "issue": request.issue_number,
                    "phase": str(request.phase),
                    "repo": repo_full_name,
                    "next_action": "→ 手動での確認をお願いします",
                },
            )
        except Exception:
            logger.warning("Failed to send timeout notification for issue #%d", request.issue_number)

    async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
        """エラー処理: SUSPENDED 遷移 + Issue コメント + 通知。

        既に DONE に到達している場合は suspended にしない (重複実行の残留タスク対策)。
        """
        current = self._sm.get_phase(self._issue_key(request))
        if current == Phase.DONE:
            logger.warning(
                "Issue #%d: error in stale task (phase=%s) but already DONE, skipping suspend",
                request.issue_number,
                request.phase,
            )
            return
        await self._sm.transition(self._issue_key(request), "suspended")

        # events.jsonl にエラー情報を記録 (最優先: 以降の処理が失敗しても残す)
        try:
            await self._tracker.track(
                "phase_suspended",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={
                    "suspend_reason": "exception",
                    "error_type": type(error).__name__,
                    "error_message": str(error)[:500],
                },
            )
        except Exception:
            logger.warning("Failed to track phase_suspended event for issue #%d", request.issue_number)

        try:
            client = await self._get_client(request.repo)
            try:
                await client.replace_phase_label(request.repo, request.issue_number, "phase:suspended")
            except Exception:
                logger.warning("Failed to update phase label to suspended for issue #%d", request.issue_number)
            try:
                await client.create_comment(
                    request.repo,
                    request.issue_number,
                    f"エラーが発生しました: {error}",
                )
            except Exception:
                logger.error(
                    "Failed to post error comment for issue #%d (original error: %s)",
                    request.issue_number,
                    error,
                )
        except Exception:
            logger.error(
                "Failed to get GitHub client for issue #%d (original error: %s)",
                request.issue_number,
                error,
            )

        repo_full_name = self._get_repo_full_name(request)
        try:
            await self._notifier.notify(
                f"Issue #{request.issue_number} でエラー: {error} (phase: {request.phase})",
                level="error",
                metadata={
                    "notification_type": "error",
                    "issue": request.issue_number,
                    "phase": str(request.phase),
                    "repo": repo_full_name,
                    "next_action": "→ 手動での確認をお願いします",
                },
            )
        except Exception:
            logger.warning("Failed to send error notification for issue #%d", request.issue_number)

    # ------------------------------------------------------------------
    # Git state validation & recovery
    # ------------------------------------------------------------------

    async def _record_branch_baseline(self, request: TaskRequest) -> None:
        """エージェント実行前のブランチ HEAD SHA を記録する。

        設計コミットと実装コミットを区別するための基準点。
        build_prompt() 後に呼ばれる (worktree 作成済みを保証)。

        Args:
            request: タスクリクエスト。
        """
        state = self._sm.get_state(self._issue_key(request))
        if state is None:
            return
        try:
            worktree = await self._workspace.create_worktree(
                request.repo,
                request.issue_number,
                branch_prefix=self._branch_prefix,
            )
            rc, stdout, _ = await self._workspace._run_git(
                "rev-parse",
                "HEAD",
                cwd=str(worktree),
            )
            if rc == 0 and stdout.strip():
                state.branch_head_sha = stdout.strip()
        except Exception:
            logger.debug("Failed to record branch baseline for issue #%d", request.issue_number)

    async def _recover_uncommitted_work(
        self,
        request: TaskRequest,
        *,
        branch_prefix: str = "feature",
    ) -> None:
        """未コミット・未プッシュの作業を自動回復する。

        エージェントがコミット・プッシュを完了せずに終了した場合に、
        システムが代わりに実行する。feature ブランチへのプッシュなので
        main は汚染されず、impl-review / CI が品質ゲートとして機能する。

        失敗時は RuntimeError を送出し、呼び出し元の execute() が
        _handle_error() 経由で SUSPENDED に遷移する。

        Args:
            request: タスクリクエスト。
            branch_prefix: ブランチプレフィックス。
        """
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix=branch_prefix,
        )
        wt = str(worktree)
        branch_name = f"{branch_prefix}/issue-{request.issue_number}"

        # 1. 未コミットファイルの確認
        rc, stdout, _ = await self._workspace._run_git("status", "--porcelain", cwd=wt)
        has_uncommitted = rc == 0 and stdout.strip() != ""

        # 2. 未プッシュコミットの確認
        rc, stdout, _ = await self._workspace._run_git(
            "log",
            f"origin/{branch_name}..HEAD",
            "--oneline",
            cwd=wt,
        )
        has_unpushed = rc == 0 and stdout.strip() != ""

        if not has_uncommitted and not has_unpushed:
            # 3. baseline SHA があれば、新コミットが remote に存在するか確認
            state = self._sm.get_state(self._issue_key(request))
            baseline = state.branch_head_sha if state else None
            if baseline:
                rc, stdout, _ = await self._workspace._run_git(
                    "log",
                    f"{baseline}..origin/{branch_name}",
                    "--oneline",
                    cwd=wt,
                )
                new_commits = rc == 0 and stdout.strip() != ""
                if not new_commits:
                    # フェーズが外部変更されていた場合は RuntimeError を抑制
                    current_phase = self._sm.get_phase(self._issue_key(request))
                    req_phase_str = str(request.phase).replace("Phase.", "").replace("_", "-").lower()
                    if isinstance(current_phase, Phase) and current_phase.value != req_phase_str:
                        logger.warning(
                            "Issue #%d: phase changed externally (%s → %s) "
                            "during recovery check, skipping no-commit error",
                            request.issue_number,
                            req_phase_str,
                            current_phase.value,
                        )
                        return
                    msg = (
                        f"Issue #{request.issue_number}: "
                        "エージェントがコードの変更・コミット・プッシュを行いませんでした。"
                    )
                    raise RuntimeError(msg)
            return  # 正常: コミット・プッシュ済み

        # --- 自動回復 ---
        recovered_actions: list[str] = []

        if has_uncommitted:
            logger.warning(
                "Issue #%d: uncommitted files detected, auto-committing",
                request.issue_number,
            )
            # git add -A
            rc, _, stderr = await self._workspace._run_git("add", "-A", cwd=wt)
            if rc != 0:
                msg = f"Issue #{request.issue_number}: git add 失敗: {stderr}"
                raise RuntimeError(msg)

            # git commit
            commit_msg = f"feat: #{request.issue_number} 自動コミット (エージェント未コミット分)"
            rc, _, stderr = await self._workspace._run_git("commit", "-m", commit_msg, cwd=wt)
            if rc != 0:
                msg = f"Issue #{request.issue_number}: git commit 失敗: {stderr}"
                raise RuntimeError(msg)
            recovered_actions.append("auto-commit")

        # push
        rc_push, _, stderr = await self._workspace._run_git(
            "push",
            "origin",
            branch_name,
            cwd=wt,
        )
        if rc_push != 0:
            msg = f"Issue #{request.issue_number}: git push 失敗: {stderr}"
            raise RuntimeError(msg)
        recovered_actions.append("auto-push")

        # 回復ログ
        actions_str = " + ".join(recovered_actions)
        logger.info(
            "Issue #%d: auto-recovery succeeded (%s)",
            request.issue_number,
            actions_str,
        )
        await self._tracker.track(
            "uncommitted_work_recovered",
            issue_number=request.issue_number,
            phase=str(request.phase),
            data={"actions": recovered_actions},
        )

        # Issue コメントで通知
        try:
            client = await self._get_client(request.repo)
            await client.create_comment(
                request.repo,
                request.issue_number,
                f"⚠️ エージェントが変更をコミット/プッシュせずに終了したため、"
                f"システムが自動回復しました ({actions_str})。",
            )
        except Exception:
            logger.debug("Failed to post recovery comment for issue #%d", request.issue_number)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    async def _ensure_pr_created(
        self,
        request: TaskRequest,
        agent_output: str,
        *,
        branch_prefix: str = "feature",
        title_prefix: str = "",
    ) -> int:
        """エージェント出力からPR番号を取得し、無ければAPI経由で作成する。

        フォールバック手順:
        1. エージェント出力からPR番号を正規表現で抽出
        2. 失敗: ブランチ名で GitHub API から既存PRを検索
        3. 失敗: GitHub API で新規PR作成

        Args:
            request: タスクリクエスト。
            agent_output: エージェントの出力テキスト。
            branch_prefix: worktreeブランチのプレフィックス。
            title_prefix: PRタイトルのプレフィックス (例: "修正:", "機能:")。

        Returns:
            PR 番号。

        Raises:
            RuntimeError: PR作成に失敗した場合。
        """
        client = await self._get_client(request.repo)

        # Step 1: エージェント出力からPR番号を抽出
        logger.info(
            "Issue #%d: _ensure_pr_created step1 (extract from output) output_len=%d",
            request.issue_number,
            len(agent_output),
        )
        pr_number = self._extract_pr_number(agent_output)
        if pr_number is not None:
            logger.info(
                "Issue #%d: _ensure_pr_created step1 succeeded PR #%d",
                request.issue_number,
                pr_number,
            )
            return pr_number

        logger.warning(
            "Issue #%d: _ensure_pr_created step1 failed (no PR number in output), trying step2",
            request.issue_number,
        )

        # Step 2: ブランチ名で既存PRを検索
        branch_name = f"{branch_prefix}/issue-{request.issue_number}"
        search_branches = [branch_name]
        # branch_prefix が "feature" 以外の場合、feature/issue-XX でもフォールバック検索
        if branch_prefix != "feature":
            search_branches.append(f"feature/issue-{request.issue_number}")

        owner = getattr(request.repo, "owner", "")
        logger.info(
            "Issue #%d: _ensure_pr_created step2 (search by branch) owner=%r branches=%s",
            request.issue_number,
            owner,
            search_branches,
        )
        for search_branch in search_branches:
            head_filter = f"{owner}:{search_branch}"
            try:
                existing_prs = await client.list_pull_requests(
                    request.repo,
                    state="open",
                    head=head_filter,
                )
                if existing_prs:
                    found_pr = getattr(existing_prs[0], "number", None)
                    if found_pr is not None:
                        logger.info(
                            "Issue #%d: _ensure_pr_created step2 succeeded PR #%d (branch=%s)",
                            request.issue_number,
                            found_pr,
                            search_branch,
                        )
                        return int(found_pr)
                else:
                    logger.warning(
                        "Issue #%d: _ensure_pr_created step2 no PRs found for head=%r",
                        request.issue_number,
                        head_filter,
                    )
            except Exception as search_err:
                logger.warning(
                    "Issue #%d: _ensure_pr_created step2 search failed for branch %s: %s",
                    request.issue_number,
                    search_branch,
                    search_err,
                )

        # Step 3: GitHub API で新規PR作成
        logger.warning(
            "Issue #%d: _ensure_pr_created step2 failed for all branches, trying step3 (create PR)",
            request.issue_number,
        )
        try:
            issue = await client.get_issue(request.repo, request.issue_number)
            title = f"{title_prefix}#{request.issue_number} {issue.title}".strip()
            body = (
                f"Closes #{request.issue_number}\n\n## 概要\nIssue #{request.issue_number} に対する自動生成PRです。\n"
            )
            base_branch = getattr(request.repo, "base_branch", "main")

            # pushされているか確認するためPR作成を試行
            pr = await client.create_pull_request(
                request.repo,
                title=title,
                body=body,
                head=branch_name,
                base=base_branch,
            )
            created_number = getattr(pr, "number", None)
            if created_number is not None:
                logger.info(
                    "Issue #%d: _ensure_pr_created step3 succeeded PR #%d",
                    request.issue_number,
                    created_number,
                )
                return int(created_number)
        except Exception as exc:
            logger.error(
                "Issue #%d: _ensure_pr_created step3 failed: %s",
                request.issue_number,
                exc,
            )

        msg = (
            f"Issue #{request.issue_number}: PR作成に失敗しました。"
            f"エージェント出力にPR番号がなく、ブランチ '{branch_name}' の"
            f"PRも見つからず、API経由のPR作成も失敗しました。"
        )
        raise RuntimeError(msg)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """AI出力からJSONを抽出する。

        以下の順序で試行:
        1. ```json ... ``` ブロック内のJSON
        2. { ... } の最外マッチ
        3. 全体をjson.loadsで直接パース

        Args:
            text: AI の出力テキスト。

        Returns:
            パースされた辞書。失敗時は None。
        """
        # Try ```json block first
        json_block = re.search(r"```json\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_block:
            try:
                return json.loads(json_block.group(1).strip())  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass

        # Try finding { ... } pattern
        brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text)
        if brace_match:
            try:
                return json.loads(brace_match.group())  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass

        # Try direct parse
        try:
            return json.loads(text.strip())  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_pr_number(output: str) -> int | None:
        """エージェント出力テキストから PR 番号を抽出する。

        PR URL パターンを優先的に検索し、見つからなければ
        ``PR #N`` / ``Pull Request #N`` パターンにフォールバックする。
        単純な ``#N`` は Issue 番号と混同するため最終手段とする。

        Args:
            output: エージェント出力テキスト。

        Returns:
            PR 番号。見つからなければ None。
        """
        # 1. GitHub PR URL (最も信頼性が高い)
        url_match = re.search(r"github\.com/[^/]+/[^/]+/pull/(\d+)", output)
        if url_match:
            return int(url_match.group(1))

        # 2. "PR #N" / "Pull Request #N" パターン
        pr_match = re.search(r"(?:PR|Pull Request)\s*#(\d+)", output, re.IGNORECASE)
        if pr_match:
            return int(pr_match.group(1))

        # 3. 出力末尾付近の #N (エージェントは最後にPR番号を出力しがち)
        tail = output[-500:] if len(output) > 500 else output
        tail_matches = list(re.finditer(r"#(\d+)", tail))
        if tail_matches:
            return int(tail_matches[-1].group(1))

        return None
