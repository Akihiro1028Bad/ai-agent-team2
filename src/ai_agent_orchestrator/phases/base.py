"""PhaseExecutor 基底クラス."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
    from ai_agent_orchestrator.context.engine import ContextEngine
    from ai_agent_orchestrator.models import AgentResult, TaskRequest

logger = logging.getLogger(__name__)


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

    async def close_issue(self, repo: object, issue_number: int) -> None:
        """Close an issue."""
        ...  # pragma: no cover

    async def merge_pull_request(self, repo: object, pr_number: int, merge_method: str = "squash") -> None:
        """Merge a pull request."""
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

    def get_state(self, issue_number: int) -> IssueStateData | None:
        """Get state for an issue."""
        ...  # pragma: no cover

    def get_issue_type(self, issue_number: int) -> str:
        """Get the issue type."""
        return ""  # pragma: no cover

    def set_issue_type(self, issue_number: int, issue_type: str) -> None:
        """Set the issue type."""
        ...  # pragma: no cover

    async def transition(self, issue_number: int, phase: str) -> None:
        """Transition to a new phase."""
        ...  # pragma: no cover

    async def increment_ci_retry(self, issue_number: int) -> None:
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
        github: GitHubClientProtocol,
        notifier: NotifierProtocol,
        tracker: TrackerProtocol,
        workspace: WorkspaceProtocol,
        context_engine: ContextEngine,
        state_machine: StateMachineProtocol,
    ) -> None:
        """共通依存オブジェクトを注入する。

        Args:
            runner: Claude Agent SDK ランナー。
            github: GitHub API クライアント。
            notifier: 通知送信 (Slack 等)。
            tracker: イベントログ追跡。
            workspace: ワークスペース (worktree) 管理。
            context_engine: コンテキスト構築エンジン。
            state_machine: ステートマシンマネージャ。
        """
        self._runner = runner
        self._github = github
        self._notifier = notifier
        self._tracker = tracker
        self._workspace = workspace
        self._context = context_engine
        self._sm = state_machine

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
        """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + 通知。"""
        state = self._sm.get_state(request.issue_number)
        if state and state.session_id:
            await self._runner.interrupt(state.session_id)

        await self._sm.transition(request.issue_number, "suspended")
        await self._notifier.notify(
            f"Issue #{request.issue_number} がタイムアウトしました (phase: {request.phase})",
            level="error",
            metadata={
                "issue": request.issue_number,
                "phase": str(request.phase),
            },
        )

    async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
        """エラー処理: SUSPENDED 遷移 + Issue コメント + 通知。"""
        await self._sm.transition(request.issue_number, "suspended")
        await self._github.create_comment(
            request.repo,
            request.issue_number,
            f"エラーが発生しました: {error}",
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} でエラー: {error} (phase: {request.phase})",
            level="error",
            metadata={
                "issue": request.issue_number,
                "phase": str(request.phase),
            },
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_pr_number(output: str) -> int | None:
        """エージェント出力テキストから PR 番号を抽出する。

        Args:
            output: エージェント出力テキスト。

        Returns:
            PR 番号。見つからなければ None。
        """
        match = re.search(r"#(\d+)", output)
        return int(match.group(1)) if match else None
