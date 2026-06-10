"""_finalize_phase_commit (U1: コミット一本化) のテスト.

実 git リポジトリ（bare origin + clone）を使った回帰テストと、
無変更時のフェーズ別ポリシーのテストを含む。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.phases.base import NoChangesError
from ai_agent_orchestrator.phases.fix import FixExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _git(*args: str, cwd: Path) -> tuple[int, str, str]:
    """テスト用に実 git を実行する。"""
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


class _RealGitWorkspace:
    """実 git を叩く最小限の WorkspaceManager 代替。"""

    def __init__(self, worktree: Path) -> None:
        self._worktree = worktree

    async def create_worktree(
        self,
        repo: str,
        issue_number: int,
        branch_prefix: str = "feature",
    ) -> Path:
        return self._worktree

    async def _run_git(self, *args: str, cwd: str) -> tuple[int, str, str]:
        return await _git(*args, cwd=Path(cwd))


def _make_request(issue_number: int = 1, phase: str = "fix") -> MagicMock:
    req = MagicMock()
    req.repo = "org/app"
    req.issue_number = issue_number
    req.issue_key = ("org/app", issue_number)
    req.phase = phase
    req.extra = {}
    return req


def _make_executor(workspace: Any, sm: Any) -> FixExecutor:
    return FixExecutor(
        AsyncMock(),  # runner
        AsyncMock(),  # github
        AsyncMock(),  # notifier
        AsyncMock(),  # tracker
        workspace,
        AsyncMock(),  # context
        sm,
    )


@pytest.fixture
async def git_repo(tmp_path: Path) -> Path:
    """bare origin + feature ブランチ済み clone を作る。clone パスを返す。"""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    await _git("init", "--bare", "--initial-branch=main", ".", cwd=origin)

    work = tmp_path / "work"
    await _git("clone", str(origin), str(work), cwd=tmp_path)
    await _git("config", "user.email", "test@example.com", cwd=work)
    await _git("config", "user.name", "test", cwd=work)
    (work / "README.md").write_text("init\n")
    await _git("add", ".", cwd=work)
    await _git("commit", "-m", "init", cwd=work)
    await _git("push", "origin", "main", cwd=work)
    await _git("checkout", "-b", "feature/issue-1", cwd=work)
    await _git("push", "-u", "origin", "feature/issue-1", cwd=work)
    return work


def _mock_sm(branch_head_sha: str | None = None) -> MagicMock:
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(branch_head_sha=branch_head_sha)
    sm.get_phase.return_value = None
    return sm


# ---------------------------------------------------------------------------
# 実 git による回帰テスト
# ---------------------------------------------------------------------------


class TestFinalizeCommitRealGit:
    """実 git リポでのコミット内容・メッセージ・push の検証。"""

    async def test_commits_changes_with_phase_message_and_pushes(self, git_repo: Path) -> None:
        """変更がフェーズ文脈のメッセージでコミットされ push される。"""
        (git_repo / "src.py").write_text("print('hi')\n")
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm())

        await executor._finalize_phase_commit(
            _make_request(),
            summary="バグ修正を実装",
            commit_type="fix",
        )

        rc, log, _ = await _git("log", "-1", "--format=%s", cwd=git_repo)
        assert rc == 0
        assert log.strip() == "fix: #1 バグ修正を実装"
        assert "自動コミット" not in log

        # push 済み（origin と HEAD が一致）
        _, local, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        _, remote, _ = await _git("rev-parse", "origin/feature/issue-1", cwd=git_repo)
        assert local == remote

    async def test_excludes_generated_artifacts_from_commit(self, git_repo: Path) -> None:
        """coverage/ 等の生成物はコミットに含まれない（回帰テスト）。"""
        (git_repo / "src.py").write_text("code\n")
        (git_repo / "coverage").mkdir()
        (git_repo / "coverage" / "lcov.info").write_text("data\n")
        (git_repo / ".coverage").write_text("db\n")
        (git_repo / "htmlcov").mkdir()
        (git_repo / "htmlcov" / "index.html").write_text("<html>\n")
        (git_repo / "__pycache__").mkdir()
        (git_repo / "__pycache__" / "m.pyc").write_text("x")
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm())

        await executor._finalize_phase_commit(
            _make_request(),
            summary="実装",
            commit_type="feat",
        )

        rc, files, _ = await _git("show", "--name-only", "--format=", "HEAD", cwd=git_repo)
        assert rc == 0
        committed = {f for f in files.strip().splitlines() if f}
        assert committed == {"src.py"}

    async def test_only_artifacts_with_allow_no_changes_commits_nothing(self, git_repo: Path) -> None:
        """生成物だけが残った場合、allow_no_changes=True ならコミットなしで正常終了。"""
        (git_repo / "coverage").mkdir()
        (git_repo / "coverage" / "lcov.info").write_text("data\n")
        _, before, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm())

        await executor._finalize_phase_commit(
            _make_request(),
            summary="レビュー対応",
            commit_type="fix",
            allow_no_changes=True,
        )

        _, after, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        assert before == after  # コミットが増えていない

    async def test_unpushed_commit_is_pushed(self, git_repo: Path) -> None:
        """未プッシュコミットがあれば push される（回復機能の維持）。"""
        (git_repo / "manual.py").write_text("x\n")
        await _git("add", "manual.py", cwd=git_repo)
        await _git("commit", "-m", "feat: 手動コミット", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm())

        await executor._finalize_phase_commit(
            _make_request(),
            summary="実装",
            commit_type="feat",
        )

        _, local, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        _, remote, _ = await _git("rev-parse", "origin/feature/issue-1", cwd=git_repo)
        assert local == remote


# ---------------------------------------------------------------------------
# 無変更時のフェーズ別ポリシー
# ---------------------------------------------------------------------------


class TestNoChangePolicy:
    """変更ゼロ時の allow_no_changes による分岐。"""

    async def test_no_changes_raises_when_not_allowed(self, git_repo: Path) -> None:
        """IMPLEMENT/FIX 系: 変更ゼロは無作業として RuntimeError（検知の維持）。"""
        _, baseline, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm(branch_head_sha=baseline.strip()))

        with pytest.raises(NoChangesError, match="変更"):
            await executor._finalize_phase_commit(
                _make_request(),
                summary="実装",
                commit_type="feat",
                allow_no_changes=False,
            )

    async def test_no_changes_ok_when_allowed(self, git_repo: Path) -> None:
        """REVISE 系: 変更ゼロ（質問回答のみ等）は正常終了。"""
        _, baseline, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm(branch_head_sha=baseline.strip()))

        await executor._finalize_phase_commit(
            _make_request(),
            summary="レビュー対応",
            commit_type="fix",
            allow_no_changes=True,
        )  # 例外が出ないこと

    async def test_no_changes_with_new_remote_commits_is_ok(self, git_repo: Path) -> None:
        """baseline 以降に remote へ新コミットがあれば無変更でも正常（既存挙動の維持）。"""
        _, baseline, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        # baseline の後に1コミット積んで push 済みの状態を作る
        (git_repo / "pushed.py").write_text("y\n")
        await _git("add", "pushed.py", cwd=git_repo)
        await _git("commit", "-m", "feat: pushed", cwd=git_repo)
        await _git("push", "origin", "feature/issue-1", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm(branch_head_sha=baseline.strip()))

        await executor._finalize_phase_commit(
            _make_request(),
            summary="実装",
            commit_type="feat",
            allow_no_changes=False,
        )  # 例外が出ないこと

    async def test_externally_changed_phase_suppresses_error(self, git_repo: Path) -> None:
        """フェーズが外部変更されていた場合は RuntimeError を抑制（既存挙動の維持）。"""
        from ai_agent_orchestrator.models import Phase

        _, baseline, _ = await _git("rev-parse", "HEAD", cwd=git_repo)
        sm = _mock_sm(branch_head_sha=baseline.strip())
        sm.get_phase.return_value = Phase.DONE  # request.phase="fix" と不一致
        executor = _make_executor(_RealGitWorkspace(git_repo), sm)

        await executor._finalize_phase_commit(
            _make_request(phase="fix"),
            summary="実装",
            commit_type="feat",
            allow_no_changes=False,
        )  # 例外が出ないこと


# ---------------------------------------------------------------------------
# 例外型の分離（NoChangesError vs RuntimeError）
# ---------------------------------------------------------------------------


class TestErrorTypeSeparation:
    """git 操作失敗は RuntimeError、無作業は NoChangesError で区別される。"""

    async def test_push_failure_is_not_no_changes_error(self, git_repo: Path) -> None:
        """push 失敗は NoChangesError ではない（呼び出し側で飲み込まれない）。"""
        (git_repo / "src.py").write_text("code\n")
        # origin を壊して push を失敗させる
        await _git("remote", "set-url", "origin", "/nonexistent/origin.git", cwd=git_repo)
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm())

        with pytest.raises(RuntimeError, match="push") as exc_info:
            await executor._finalize_phase_commit(
                _make_request(),
                summary="実装",
                commit_type="feat",
            )
        assert not isinstance(exc_info.value, NoChangesError)

    async def test_no_baseline_returns_with_warning(self, git_repo: Path) -> None:
        """baseline 未記録時は無作業判定不可のため警告のみで正常終了。"""
        executor = _make_executor(_RealGitWorkspace(git_repo), _mock_sm(branch_head_sha=None))

        await executor._finalize_phase_commit(
            _make_request(),
            summary="実装",
            commit_type="feat",
            allow_no_changes=False,
        )  # 例外が出ないこと


# ---------------------------------------------------------------------------
# 旧メソッドの廃止
# ---------------------------------------------------------------------------


class TestOldMethodRemoved:
    """_recover_uncommitted_work が存在しないこと。"""

    def test_recover_uncommitted_work_is_removed(self) -> None:
        from ai_agent_orchestrator.phases.base import PhaseExecutor

        assert not hasattr(PhaseExecutor, "_recover_uncommitted_work")
