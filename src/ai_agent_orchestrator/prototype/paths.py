"""プロトタイプ出力先パスの解決 (#145)."""

from __future__ import annotations

from pathlib import Path


def prototype_dir(workspace_root: Path, issue_number: int) -> Path:
    """Issue 用のプロトタイプディレクトリパスを返す.

    エビデンス (#91) と同じ ``artifacts/`` 配下に置く。worktree の外にあるため
    git への誤コミットの心配がない。

    Args:
        workspace_root: ワークスペースのベースディレクトリ。
        issue_number: Issue 番号。

    Returns:
        ``{workspace_root}/artifacts/issue-{n}/prototype`` のパス。
    """
    return workspace_root / "artifacts" / f"issue-{issue_number}" / "prototype"


def worktree_prototype_file(worktree_path: Path, issue_number: int) -> Path:
    """worktree 内でエージェントが生成するプロトタイプ HTML のパスを返す.

    PLAN プロンプトが指示する保存先と一致させる単一の真実点。

    Args:
        worktree_path: worktree のルートパス。
        issue_number: Issue 番号。

    Returns:
        ``{worktree}/docs/designs/issue-{n}.prototype.html`` のパス。
    """
    return worktree_path / "docs" / "designs" / f"issue-{issue_number}.prototype.html"
