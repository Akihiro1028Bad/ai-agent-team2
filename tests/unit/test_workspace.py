"""WorkspaceManager 単体テスト."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ai_agent_orchestrator.config.settings import RepositoryConfig
from ai_agent_orchestrator.workspace_manager import WorkspaceError, WorkspaceManager


@pytest.fixture
def repo_config() -> RepositoryConfig:
    """テスト用のリポジトリ設定."""
    return RepositoryConfig(owner="test-org", repo="test-repo", base_branch="main")


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceManager:
    """テスト用の WorkspaceManager."""
    return WorkspaceManager(base_dir=str(tmp_path / "workspaces"))


# ── TC-WS-01: ensure_cloned -- 新規 clone ──


async def test_ensure_cloned_clones_new_repo(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """未 clone のリポジトリで git clone が実行されることを検証する."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await workspace.ensure_cloned(repo_config)

        assert result == workspace._repos_dir / "test-org-test-repo"
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "git" in args
        assert "clone" in args
        assert "https://github.com/test-org/test-repo.git" in args


# ── TC-WS-02: ensure_cloned -- 既存リポジトリで fetch ──


async def test_ensure_cloned_fetches_existing_repo(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """clone 済みリポジトリで git fetch --all が実行されることを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await workspace.ensure_cloned(repo_config)

        assert result == repo_dir
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "fetch" in args
        assert "--all" in args


# ── TC-WS-03: ensure_cloned -- clone 失敗時に WorkspaceError ──


async def test_ensure_cloned_raises_on_clone_failure(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git clone が失敗した場合に WorkspaceError が発生することを検証する."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 128
    mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: repository not found"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(WorkspaceError, match="Failed to clone"):
            await workspace.ensure_cloned(repo_config)


# ── TC-WS-04: create_worktree -- 新規作成 ──


async def test_create_worktree_creates_new(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """worktree が新規作成され、正しいパスが返ることを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    call_count = 0

    async def mock_exec(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        mock_proc = AsyncMock()
        # call 1 = fetch, call 2 = rev-parse (branch check -- not found), call 3 = worktree add
        if call_count == 2:
            # branch does not exist
            mock_proc.returncode = 128
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec) as mock_exec_patch:
        result = await workspace.create_worktree(repo_config, issue_number=42)

        expected_path = repo_dir / "worktrees" / "issue-42"
        assert result == expected_path

        # git worktree add コマンドの確認 (args[0]="git", args[1]=subcommand)
        worktree_call = [c for c in mock_exec_patch.call_args_list if len(c[0]) > 1 and c[0][1] == "worktree"]
        assert len(worktree_call) > 0
        args = worktree_call[0][0]
        assert "worktree" in args
        assert "add" in args
        assert "-b" in args
        assert "feature/issue-42" in args


# ── TC-WS-05: create_worktree -- 既存の場合はそのまま返す (冪等性) ──


async def test_create_worktree_returns_existing(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """worktree が既に存在する場合、git worktree add を実行せずにパスを返すことを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    worktree_path = repo_dir / "worktrees" / "issue-42"
    worktree_path.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await workspace.create_worktree(repo_config, issue_number=42)

        assert result == worktree_path
        # fetch は呼ばれるが worktree add は呼ばれない
        worktree_calls = [c for c in mock_exec.call_args_list if "worktree" in str(c) and "add" in str(c)]
        assert len(worktree_calls) == 0


# ── TC-WS-06: create_worktree -- 失敗時に WorkspaceError ──


async def test_create_worktree_raises_on_failure(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git worktree add が失敗した場合に WorkspaceError が発生することを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    call_count = 0

    async def mock_exec(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal call_count
        call_count += 1
        mock_proc = AsyncMock()
        if call_count == 1:
            # fetch は成功
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            # worktree add (or branch check) -- fail on worktree add
            mock_proc.returncode = 128
            mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: branch already exists"))
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        with pytest.raises(WorkspaceError, match="Failed to create worktree"):
            await workspace.create_worktree(repo_config, issue_number=42)


# ── TC-WS-07: remove_worktree -- 正常削除 ──


async def test_remove_worktree_removes_existing(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """既存の worktree が削除されることを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    worktree_path = repo_dir / "worktrees" / "issue-42"
    worktree_path.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await workspace.remove_worktree(repo_config, issue_number=42)

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "worktree" in args
        assert "remove" in args
        assert "--force" in args


# ── TC-WS-08: remove_worktree -- 存在しない場合は何もしない ──


async def test_remove_worktree_ignores_nonexistent(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """存在しない worktree の削除が何もしないことを検証する."""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await workspace.remove_worktree(repo_config, issue_number=999)

        mock_exec.assert_not_called()


# ── TC-WS-09: list_worktrees -- worktree 一覧取得 ──


async def test_list_worktrees_returns_paths(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git worktree list の結果から worktree パスが抽出されることを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    porcelain_output = (
        f"worktree {repo_dir}\n"
        f"HEAD abc123\n"
        f"branch refs/heads/main\n"
        f"\n"
        f"worktree {repo_dir}/worktrees/issue-42\n"
        f"HEAD def456\n"
        f"branch refs/heads/feature/issue-42\n"
        f"\n"
        f"worktree {repo_dir}/worktrees/issue-55\n"
        f"HEAD ghi789\n"
        f"branch refs/heads/feature/issue-55\n"
    )

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(porcelain_output.encode(), b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await workspace.list_worktrees(repo_config)

        # メインリポジトリは除外され、worktree のみ
        assert len(result) == 2
        assert repo_dir / "worktrees" / "issue-42" in result
        assert repo_dir / "worktrees" / "issue-55" in result


# ── TC-WS-10: list_worktrees -- リポジトリ未 clone の場合は空リスト ──


async def test_list_worktrees_empty_when_not_cloned(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """リポジトリが clone されていない場合に空リストが返ることを検証する."""
    result = await workspace.list_worktrees(repo_config)

    assert result == []


# ── TC-WS-11: get_log_dir -- ログディレクトリの自動作成 ──


def test_get_log_dir_creates_directory(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """get_log_dir が存在しないディレクトリを自動作成することを検証する."""
    log_dir = workspace.get_log_dir(repo_config, issue_number=42)

    expected = workspace._logs_dir / "test-org-test-repo" / "issue-42"
    assert log_dir == expected
    assert log_dir.exists()
    assert log_dir.is_dir()


# ── TC-WS-12: create_worktree -- カスタム branch_prefix ──


async def test_create_worktree_custom_prefix(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """branch_prefix が "design" の場合に "design/issue-42" ブランチで作成されることを検証する."""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await workspace.create_worktree(repo_config, issue_number=42, branch_prefix="design")

        worktree_call = [c for c in mock_exec.call_args_list if len(c[0]) > 1 and c[0][1] == "worktree"]
        assert len(worktree_call) > 0
        args_str = " ".join(str(a) for a in worktree_call[0][0])
        assert "design/issue-42" in args_str


# ── TC-WS-13: ensure_cloned -- 認証付き clone URL ──


async def test_ensure_cloned_with_token(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """トークン指定時に認証付き clone URL が使用されることを検証する."""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await workspace.ensure_cloned(repo_config, token="ghp_test123")

        args = mock_exec.call_args[0]
        assert "clone" in args
        assert "https://x-access-token:ghp_test123@github.com/test-org/test-repo.git" in args
