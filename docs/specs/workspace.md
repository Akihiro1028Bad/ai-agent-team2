# WorkspaceManager 実装仕様書

## 概要

git worktree の作成・削除を管理し、各 Issue の作業を物理的に分離するクラスの実装仕様。
全ての git 操作は `asyncio.create_subprocess_exec` で非同期に実行し、オーケストレーターのイベントループをブロックしない。

## 対象ファイル

- `src/ai_agent_orchestrator/workspace_manager.py`

## 依存パッケージ

```python
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ai_agent_orchestrator.config.settings import RepositoryConfig

logger = logging.getLogger(__name__)
```

---

## 例外クラス

```python
class WorkspaceError(Exception):
    """worktree の作成・削除に失敗した場合に発生する例外."""
```

---

## ディレクトリ構成

```
{base_dir}/                              # デフォルト: ~/.ai-agent-workspaces
├── repos/
│   ├── {owner}-{repo}/                  # git clone 済みリポジトリ
│   │   ├── .git/
│   │   └── worktrees/
│   │       ├── issue-{number}/          # git worktree (Issue ごと)
│   │       └── issue-{number}/
│   └── {owner}-{repo}/
└── logs/
    ├── {owner}-{repo}/
    │   ├── issue-{number}/
    │   │   ├── {timestamp}_{phase}.log
    │   │   └── events.jsonl
    │   └── issue-{number}/
    └── orchestrator.log
```

---

## クラス: `WorkspaceManager`

### 説明

git worktree の作成・削除を管理する。各 Issue の作業を物理的に分離し、
複数 Issue の並行処理時にファイルシステムの競合を防ぐ。

### コンストラクタ

```python
class WorkspaceManager:
    """git worktree の作成・削除を管理する."""

    def __init__(self, base_dir: str = "~/.ai-agent-workspaces") -> None:
        """WorkspaceManager を初期化する。

        Args:
            base_dir: ワークスペースのベースディレクトリ。~ はホームディレクトリに展開される。
        """
        self._base = Path(base_dir).expanduser()
        self._repos_dir = self._base / "repos"
        self._logs_dir = self._base / "logs"
```

### 公開メソッド

#### `ensure_cloned` (旧名: `setup_repo`)

```python
async def ensure_cloned(self, repo: RepositoryConfig) -> Path:
    """リポジトリが clone 済みであることを保証する。

    未 clone の場合は `git clone` を実行する。
    clone 済みの場合は `git fetch --all` でリモートの最新を取得する。

    処理フロー:
    1. repos_dir / "{owner}-{repo}" の存在を確認
    2. 存在しない場合:
       - 親ディレクトリを作成
       - `git clone https://github.com/{owner}/{repo}.git {path}` を実行
       - returncode != 0 の場合は WorkspaceError を送出
    3. 存在する場合:
       - `git fetch --all` を実行 (失敗してもログのみ)

    Args:
        repo: リポジトリ設定。

    Returns:
        リポジトリのディレクトリパス。

    Raises:
        WorkspaceError: clone に失敗した場合。
    """
```

### プライベートリポジトリの認証付き clone

プライベートリポジトリの場合、`git clone` 時にトークンを URL に含める必要がある。
`ensure_cloned()` 内で `AccountManager` から取得したトークンを使用する。

```python
# プライベートリポジトリの場合、トークンをURLに含める
clone_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
```

実装メモ:
- `WorkspaceManager` のコンストラクタまたは `ensure_cloned()` の引数でトークンを受け取る
- トークンが指定されていない場合は通常の HTTPS URL (`https://github.com/{owner}/{repo}.git`) を使用
- トークンがログに出力されないよう、`_run_git` のログ出力ではマスクする

#### `create_worktree`

```python
async def create_worktree(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    branch_prefix: str = "feature",
) -> Path:
    """Issue 用の worktree を作成する。

    既に存在する場合はそのパスを返す (冪等)。
    内部で ensure_cloned() を呼び出し、リポジトリの clone を保証する。

    処理フロー:
    1. ensure_cloned(repo) でリポジトリを準備
    2. worktree パスが既に存在する場合はそのまま返す
    3. 親ディレクトリを作成
    4. ブランチが既に存在するか確認し、フラグを切り替える:
       ```python
       # ブランチが既に存在する場合は -B (強制作成) を使用
       branch_exists = await self._branch_exists(branch_name)
       flag = "-B" if branch_exists else "-b"
       ```
    5. `git worktree add {flag} {branch_prefix}/issue-{issue_number} {worktree_path} origin/{base_branch}` を実行
    6. returncode != 0 の場合は WorkspaceError を送出

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        branch_prefix: ブランチ名のプレフィックス。デフォルトは "feature"。

    Returns:
        worktree のディレクトリパス。
        パス形式: {repos_dir}/{owner}-{repo}/worktrees/issue-{number}

    Raises:
        WorkspaceError: worktree の作成に失敗した場合。

    ブランチ名形式:
        {branch_prefix}/issue-{issue_number} (例: "feature/issue-42")
    """
```

#### `remove_worktree`

```python
async def remove_worktree(
    self,
    repo: RepositoryConfig,
    issue_number: int,
) -> None:
    """Issue 用の worktree を削除する。

    worktree が存在しない場合は何もしない (冪等)。
    `--force` オプションで未コミット変更があっても強制削除する。

    処理フロー:
    1. worktree パスの存在を確認
    2. 存在する場合:
       - `git worktree remove {worktree_path} --force` を実行
       - 失敗してもログのみ (例外は送出しない)

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
    """
```

#### `list_worktrees`

```python
async def list_worktrees(self, repo: RepositoryConfig) -> list[Path]:
    """リポジトリの全 worktree を一覧取得する。

    `git worktree list --porcelain` を実行し、worktree パスを抽出する。

    処理フロー:
    1. リポジトリディレクトリの存在を確認
    2. 存在しない場合は空リストを返す
    3. `git worktree list --porcelain` を実行
    4. 出力から "worktree " で始まる行を抽出し、パスをリストにして返す

    Args:
        repo: リポジトリ設定。

    Returns:
        worktree のパスリスト。メインの作業ディレクトリは除外する。
    """
```

#### `get_log_dir`

```python
def get_log_dir(self, repo: RepositoryConfig, issue_number: int) -> Path:
    """Issue 用のログディレクトリパスを取得する。

    ディレクトリが存在しない場合は自動作成する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。

    Returns:
        ログディレクトリパス。
        パス形式: {logs_dir}/{owner}-{repo}/issue-{number}
    """
```

### 内部メソッド

#### `_branch_exists`

```python
async def _branch_exists(
    self,
    branch_name: str,
    cwd: str | Path | None = None,
) -> bool:
    """ローカルブランチが既に存在するかを確認する。

    `git rev-parse --verify refs/heads/{branch_name}` を実行し、returncode で判定する。

    Args:
        branch_name: 確認するブランチ名。
        cwd: 作業ディレクトリ。

    Returns:
        ブランチが存在する場合は True、存在しない場合は False。
    """
```

#### `_run_git`

```python
async def _run_git(
    self,
    *args: str,
    cwd: str | Path | None = None,
) -> tuple[int, str, str]:
    """git コマンドを非同期で実行する。

    asyncio.create_subprocess_exec を使用し、stdout/stderr を PIPE でキャプチャする。

    Args:
        *args: git コマンドの引数 (例: "clone", "--all")。
        cwd: 作業ディレクトリ。None の場合はプロセスのカレントディレクトリ。

    Returns:
        (returncode, stdout, stderr) のタプル。
    """
```

---

## テストケース

テストファイル: `tests/unit/test_workspace_manager.py`

`tmp_path` フィクスチャで一時ディレクトリを使用し、実際の git コマンド実行を `AsyncMock` でモックする。

### テスト用の共通フィクスチャ

```python
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent_orchestrator.config.settings import RepositoryConfig
from ai_agent_orchestrator.workspace_manager import WorkspaceError, WorkspaceManager


@pytest.fixture
def repo_config() -> RepositoryConfig:
    return RepositoryConfig(owner="test-org", repo="test-repo", base_branch="main")


@pytest.fixture
def workspace(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(base_dir=str(tmp_path / "workspaces"))
```

### テストケース一覧

#### TC-WS-01: `ensure_cloned` -- 新規 clone

```python
@pytest.mark.asyncio
async def test_ensure_cloned_clones_new_repo(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
    tmp_path: Path,
) -> None:
    """未 clone のリポジトリで git clone が実行されることを検証する。"""
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
```

#### TC-WS-02: `ensure_cloned` -- 既存リポジトリで fetch

```python
@pytest.mark.asyncio
async def test_ensure_cloned_fetches_existing_repo(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """clone 済みリポジトリで git fetch --all が実行されることを検証する。"""
    # リポジトリディレクトリを事前作成
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
```

#### TC-WS-03: `ensure_cloned` -- clone 失敗時に WorkspaceError

```python
@pytest.mark.asyncio
async def test_ensure_cloned_raises_on_clone_failure(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git clone が失敗した場合に WorkspaceError が発生することを検証する。"""
    mock_proc = AsyncMock()
    mock_proc.returncode = 128
    mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: repository not found"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(WorkspaceError, match="Failed to clone"):
            await workspace.ensure_cloned(repo_config)
```

#### TC-WS-04: `create_worktree` -- 新規作成

```python
@pytest.mark.asyncio
async def test_create_worktree_creates_new(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """worktree が新規作成され、正しいパスが返ることを検証する。"""
    # ensure_cloned のモック
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await workspace.create_worktree(repo_config, issue_number=42)

        expected_path = repo_dir / "worktrees" / "issue-42"
        assert result == expected_path

        # git worktree add コマンドの確認
        worktree_call = [c for c in mock_exec.call_args_list if "worktree" in str(c)]
        assert len(worktree_call) > 0
        args = worktree_call[0][0]
        assert "worktree" in args
        assert "add" in args
        assert "-b" in args
        assert "feature/issue-42" in args
```

#### TC-WS-05: `create_worktree` -- 既存の場合はそのまま返す (冪等性)

```python
@pytest.mark.asyncio
async def test_create_worktree_returns_existing(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """worktree が既に存在する場合、git コマンドを実行せずにパスを返すことを検証する。"""
    # リポジトリ & worktree ディレクトリを事前作成
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
```

#### TC-WS-06: `create_worktree` -- 失敗時に WorkspaceError

```python
@pytest.mark.asyncio
async def test_create_worktree_raises_on_failure(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git worktree add が失敗した場合に WorkspaceError が発生することを検証する。"""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    call_count = 0

    async def mock_exec(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        mock_proc = AsyncMock()
        if call_count == 1:
            # fetch は成功
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            # worktree add は失敗
            mock_proc.returncode = 128
            mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: branch already exists"))
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        with pytest.raises(WorkspaceError, match="Failed to create worktree"):
            await workspace.create_worktree(repo_config, issue_number=42)
```

#### TC-WS-07: `remove_worktree` -- 正常削除

```python
@pytest.mark.asyncio
async def test_remove_worktree_removes_existing(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """既存の worktree が削除されることを検証する。"""
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
```

#### TC-WS-08: `remove_worktree` -- 存在しない場合は何もしない

```python
@pytest.mark.asyncio
async def test_remove_worktree_ignores_nonexistent(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """存在しない worktree の削除が何もしないことを検証する。"""
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await workspace.remove_worktree(repo_config, issue_number=999)

        mock_exec.assert_not_called()
```

#### TC-WS-09: `list_worktrees` -- worktree 一覧取得

```python
@pytest.mark.asyncio
async def test_list_worktrees_returns_paths(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """git worktree list の結果から worktree パスが抽出されることを検証する。"""
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
    mock_proc.communicate = AsyncMock(
        return_value=(porcelain_output.encode(), b"")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await workspace.list_worktrees(repo_config)

        # メインリポジトリは除外され、worktree のみ
        assert len(result) == 2
        assert repo_dir / "worktrees" / "issue-42" in result
        assert repo_dir / "worktrees" / "issue-55" in result
```

#### TC-WS-10: `list_worktrees` -- リポジトリ未 clone の場合は空リスト

```python
@pytest.mark.asyncio
async def test_list_worktrees_empty_when_not_cloned(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """リポジトリが clone されていない場合に空リストが返ることを検証する。"""
    result = await workspace.list_worktrees(repo_config)

    assert result == []
```

#### TC-WS-11: `get_log_dir` -- ログディレクトリの自動作成

```python
def test_get_log_dir_creates_directory(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """get_log_dir が存在しないディレクトリを自動作成することを検証する。"""
    log_dir = workspace.get_log_dir(repo_config, issue_number=42)

    expected = workspace._logs_dir / "test-org-test-repo" / "issue-42"
    assert log_dir == expected
    assert log_dir.exists()
    assert log_dir.is_dir()
```

#### TC-WS-12: `create_worktree` -- カスタム branch_prefix

```python
@pytest.mark.asyncio
async def test_create_worktree_custom_prefix(
    workspace: WorkspaceManager,
    repo_config: RepositoryConfig,
) -> None:
    """branch_prefix が "design" の場合に "design/issue-42" ブランチで作成されることを検証する。"""
    repo_dir = workspace._repos_dir / "test-org-test-repo"
    repo_dir.mkdir(parents=True)

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await workspace.create_worktree(repo_config, issue_number=42, branch_prefix="design")

        worktree_call = [c for c in mock_exec.call_args_list if "worktree" in str(c)]
        assert len(worktree_call) > 0
        args_str = " ".join(str(a) for a in worktree_call[0][0])
        assert "design/issue-42" in args_str
```
