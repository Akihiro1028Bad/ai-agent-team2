"""git worktree 管理."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig

logger = logging.getLogger(__name__)

# Token pattern for masking in log output
_TOKEN_PATTERN = re.compile(r"(https://x-access-token:)[^@]+(@)")


class WorkspaceError(Exception):
    """worktree の作成・削除に失敗した場合に発生する例外."""


class WorkspaceManager:
    """git worktree の作成・削除を管理する."""

    def __init__(self, base_dir: str = "~/.ai-agent-workspaces") -> None:
        """WorkspaceManager を初期化する.

        Args:
            base_dir: ワークスペースのベースディレクトリ。~ はホームディレクトリに展開される。
        """
        self._base = Path(base_dir).expanduser()
        self._repos_dir = self._base / "repos"
        self._logs_dir = self._base / "logs"

    def _repo_dir_name(self, repo: RepositoryConfig) -> str:
        """リポジトリのディレクトリ名を返す.

        Args:
            repo: リポジトリ設定。

        Returns:
            "{owner}-{repo}" 形式のディレクトリ名。
        """
        return f"{repo.owner}-{repo.repo}"

    def _clone_url(self, repo: RepositoryConfig, token: str | None = None) -> str:
        """clone 用の URL を構築する.

        Args:
            repo: リポジトリ設定。
            token: 認証トークン。None の場合は公開 URL を返す。

        Returns:
            clone 用の HTTPS URL。
        """
        if token:
            return f"https://x-access-token:{token}@github.com/{repo.owner}/{repo.repo}.git"
        return f"https://github.com/{repo.owner}/{repo.repo}.git"

    async def _run_git(
        self,
        *args: str,
        cwd: str | Path | None = None,
    ) -> tuple[int, str, str]:
        """git コマンドを非同期で実行する.

        asyncio.create_subprocess_exec を使用し、stdout/stderr を PIPE でキャプチャする。

        Args:
            *args: git コマンドの引数 (例: "clone", "--all")。
            cwd: 作業ディレクトリ。None の場合はプロセスのカレントディレクトリ。

        Returns:
            (returncode, stdout, stderr) のタプル。
        """
        cwd_str = str(cwd) if cwd is not None else None
        # Mask tokens in log output
        safe_args = [_TOKEN_PATTERN.sub(r"\1***\2", a) for a in args]
        logger.debug("git %s (cwd=%s)", " ".join(safe_args), cwd_str)

        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd_str,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        returncode = proc.returncode if proc.returncode is not None else 1

        stdout_str = stdout_bytes.decode(errors="replace")
        stderr_str = stderr_bytes.decode(errors="replace")

        if returncode != 0:
            safe_stderr = _TOKEN_PATTERN.sub(r"\1***\2", stderr_str)
            logger.warning(
                "git %s failed (rc=%d): %s",
                " ".join(safe_args),
                returncode,
                safe_stderr,
            )

        return returncode, stdout_str, stderr_str

    async def _branch_exists(
        self,
        branch_name: str,
        cwd: str | Path | None = None,
    ) -> bool:
        """ローカルブランチが既に存在するかを確認する.

        ``git rev-parse --verify refs/heads/{branch_name}`` を実行し、
        returncode で判定する。

        Args:
            branch_name: 確認するブランチ名。
            cwd: 作業ディレクトリ。

        Returns:
            ブランチが存在する場合は True、存在しない場合は False。
        """
        rc, _, _ = await self._run_git(
            "rev-parse",
            "--verify",
            f"refs/heads/{branch_name}",
            cwd=cwd,
        )
        return rc == 0

    async def ensure_cloned(
        self,
        repo: RepositoryConfig,
        token: str | None = None,
    ) -> Path:
        """リポジトリが clone 済みであることを保証する.

        未 clone の場合は ``git clone`` を実行する。
        clone 済みの場合は ``git fetch --all`` でリモートの最新を取得する。

        Args:
            repo: リポジトリ設定。
            token: 認証トークン。プライベートリポジトリの場合に指定する。

        Returns:
            リポジトリのディレクトリパス。

        Raises:
            WorkspaceError: clone に失敗した場合。
        """
        repo_dir = self._repos_dir / self._repo_dir_name(repo)

        if repo_dir.exists():
            # Already cloned -- just fetch
            rc, _, stderr = await self._run_git("fetch", "--all", cwd=repo_dir)
            if rc != 0:
                logger.warning("git fetch --all failed for %s: %s", repo_dir, stderr)
            return repo_dir

        # Clone the repository
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        url = self._clone_url(repo, token)
        rc, _, stderr = await self._run_git("clone", url, str(repo_dir))
        if rc != 0:
            safe_stderr = _TOKEN_PATTERN.sub(r"\1***\2", stderr)
            msg = f"Failed to clone {repo.owner}/{repo.repo}: {safe_stderr}"
            raise WorkspaceError(msg)

        return repo_dir

    async def create_worktree(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        branch_prefix: str = "feature",
        token: str | None = None,
    ) -> Path:
        """Issue 用の worktree を作成する.

        既に存在する場合はそのパスを返す (冪等)。
        内部で ensure_cloned() を呼び出し、リポジトリの clone を保証する。

        Args:
            repo: リポジトリ設定。
            issue_number: Issue 番号。
            branch_prefix: ブランチ名のプレフィックス。デフォルトは "feature"。
            token: 認証トークン。

        Returns:
            worktree のディレクトリパス。

        Raises:
            WorkspaceError: worktree の作成に失敗した場合。
        """
        repo_dir = await self.ensure_cloned(repo, token=token)
        worktree_path = repo_dir / "worktrees" / f"issue-{issue_number}"

        if worktree_path.exists():
            logger.info("Worktree already exists: %s", worktree_path)
            return worktree_path

        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        branch_name = f"{branch_prefix}/issue-{issue_number}"
        branch_exists = await self._branch_exists(branch_name, cwd=repo_dir)
        flag = "-B" if branch_exists else "-b"

        rc, _, stderr = await self._run_git(
            "worktree",
            "add",
            flag,
            branch_name,
            str(worktree_path),
            f"origin/{repo.base_branch}",
            cwd=repo_dir,
        )
        if rc != 0:
            msg = f"Failed to create worktree for issue-{issue_number}: {stderr}"
            raise WorkspaceError(msg)

        return worktree_path

    async def remove_worktree(
        self,
        repo: RepositoryConfig,
        issue_number: int,
    ) -> None:
        """Issue 用の worktree を削除する.

        worktree が存在しない場合は何もしない (冪等)。
        ``--force`` オプションで未コミット変更があっても強制削除する。

        Args:
            repo: リポジトリ設定。
            issue_number: Issue 番号。
        """
        repo_dir = self._repos_dir / self._repo_dir_name(repo)
        worktree_path = repo_dir / "worktrees" / f"issue-{issue_number}"

        if not worktree_path.exists():
            logger.debug("Worktree does not exist, skipping removal: %s", worktree_path)
            return

        rc, _, stderr = await self._run_git(
            "worktree",
            "remove",
            str(worktree_path),
            "--force",
            cwd=repo_dir,
        )
        if rc != 0:
            logger.warning(
                "Failed to remove worktree %s: %s",
                worktree_path,
                stderr,
            )

    async def list_worktrees(self, repo: RepositoryConfig) -> list[Path]:
        """リポジトリの全 worktree を一覧取得する.

        ``git worktree list --porcelain`` を実行し、worktree パスを抽出する。
        メインの作業ディレクトリは除外する。

        Args:
            repo: リポジトリ設定。

        Returns:
            worktree のパスリスト。メインの作業ディレクトリは除外する。
        """
        repo_dir = self._repos_dir / self._repo_dir_name(repo)
        if not repo_dir.exists():
            return []

        rc, stdout, _ = await self._run_git(
            "worktree",
            "list",
            "--porcelain",
            cwd=repo_dir,
        )
        if rc != 0:
            return []

        paths: list[Path] = []
        for line in stdout.splitlines():
            if line.startswith("worktree "):
                wt_path = Path(line[len("worktree "):].strip())
                # Exclude the main repo directory itself
                if wt_path != repo_dir:
                    paths.append(wt_path)

        return paths

    def get_log_dir(self, repo: RepositoryConfig, issue_number: int) -> Path:
        """Issue 用のログディレクトリパスを取得する.

        ディレクトリが存在しない場合は自動作成する。

        Args:
            repo: リポジトリ設定。
            issue_number: Issue 番号。

        Returns:
            ログディレクトリパス。
        """
        log_dir = self._logs_dir / self._repo_dir_name(repo) / f"issue-{issue_number}"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
