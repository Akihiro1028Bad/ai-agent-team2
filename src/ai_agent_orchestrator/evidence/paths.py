"""エビデンス出力先パスの解決 (#91)."""

from __future__ import annotations

from pathlib import Path


def evidence_dir(workspace_root: Path, issue_number: int) -> Path:
    """Issue 用のエビデンスディレクトリパスを返す.

    state.json と同じ workspace 直下に ``artifacts/`` を新設する。worktree の
    外にあるため git への誤コミットの心配がない。

    Args:
        workspace_root: ワークスペースのベースディレクトリ。
        issue_number: Issue 番号。

    Returns:
        ``{workspace_root}/artifacts/issue-{n}/evidence`` のパス。
    """
    return workspace_root / "artifacts" / f"issue-{issue_number}" / "evidence"
