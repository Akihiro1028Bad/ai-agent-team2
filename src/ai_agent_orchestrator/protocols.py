"""Protocol インターフェース定義."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig


class GitHubClientProtocol(Protocol):
    """GitHub API クライアントの Protocol 定義."""

    async def reply_to_review_comment(
        self,
        repo: RepositoryConfig,
        pr_number: int,
        comment_id: int,
        body: str,
    ) -> None:
        """PRレビューコメントのスレッドに返信する.

        Args:
            repo: リポジトリ設定.
            pr_number: PR 番号.
            comment_id: 返信先レビューコメント ID.
            body: 返信本文 (Markdown).
        """
        ...

    async def get_pr_review_comments(
        self,
        repo: RepositoryConfig,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """PRのレビューコメント一覧を取得する。ボットコメントを除外して返す。

        Args:
            repo: リポジトリ設定.
            pr_number: PR 番号.

        Returns:
            レビューコメントの辞書リスト (id, body, user.login, path, line を含む).
        """
        ...
