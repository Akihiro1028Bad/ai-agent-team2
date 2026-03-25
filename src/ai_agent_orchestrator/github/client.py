"""GitHubClient (githubkit wrapper) and AccountManager."""

from __future__ import annotations

import logging
import urllib.parse
from typing import TYPE_CHECKING, Any

from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed

if TYPE_CHECKING:
    from githubkit.versions.latest.models import (
        Issue,
        IssueComment,
        Label,
        PullRequest,
        PullRequestReview,
        PullRequestSimple,
        Reaction,
    )

    from ai_agent_orchestrator.config.settings import AccountConfig, RepositoryConfig
    from ai_agent_orchestrator.credential import CredentialResolver

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """設定エラー."""


class GitHubClient:
    """githubkit をラップした非同期 GitHub API クライアント."""

    def __init__(self, token: str) -> None:
        """GitHubClient を初期化する.

        Args:
            token: GitHub Personal Access Token または OAuth トークン.
        """
        self._github = GitHub(TokenAuthStrategy(token))

    # ── Issue 操作 ──────────────────────────────────────

    async def get_issue(
        self,
        repo: RepositoryConfig,
        issue_number: int,
    ) -> Issue:
        """特定の Issue を取得する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.

        Returns:
            Issue オブジェクト.

        Raises:
            githubkit.exception.RequestFailed: API リクエスト失敗時.
        """
        response = await self._github.rest.issues.async_get(
            owner=repo.owner,
            repo=repo.repo,
            issue_number=issue_number,
        )
        return response.parsed_data

    async def create_comment(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        body: str,
    ) -> IssueComment:
        """Issue にコメントを投稿する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
            body: コメント本文 (Markdown).

        Returns:
            作成された IssueComment オブジェクト.
        """
        response = await self._github.rest.issues.async_create_comment(
            owner=repo.owner,
            repo=repo.repo,
            issue_number=issue_number,
            data={"body": body},
        )
        return response.parsed_data

    async def list_comments(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        since: str | None = None,
    ) -> list[IssueComment]:
        """Issue のコメント一覧を取得する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
            since: この日時以降のコメントのみ取得 (ISO 8601 形式). None の場合は全件.

        Returns:
            IssueComment のリスト (作成日時昇順).
        """
        from datetime import UTC, datetime

        kwargs: dict[str, Any] = {
            "owner": repo.owner,
            "repo": repo.repo,
            "issue_number": issue_number,
            "per_page": 100,
        }
        if since is not None:
            kwargs["since"] = datetime.fromisoformat(since).replace(tzinfo=UTC)

        response = await self._github.rest.issues.async_list_comments(**kwargs)
        return list(response.parsed_data)

    async def get_reactions(
        self,
        repo: RepositoryConfig,
        comment_id: int,
    ) -> list[Reaction]:
        """Issue コメントのリアクション一覧を取得する.

        Args:
            repo: リポジトリ設定.
            comment_id: コメント ID.

        Returns:
            Reaction のリスト.
        """
        response = await self._github.rest.reactions.async_list_for_issue_comment(
            owner=repo.owner,
            repo=repo.repo,
            comment_id=comment_id,
            per_page=100,
        )
        return list(response.parsed_data)

    # ── ラベル操作 ──────────────────────────────────────

    async def add_label(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        label: str,
    ) -> None:
        """Issue にラベルを追加する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
            label: 追加するラベル名.
        """
        await self._github.rest.issues.async_add_labels(
            owner=repo.owner,
            repo=repo.repo,
            issue_number=issue_number,
            data=[label],
        )

    async def remove_label(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        label: str,
    ) -> None:
        """Issue からラベルを削除する. 存在しないラベルの場合は無視する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
            label: 削除するラベル名.
        """
        try:
            await self._github.rest.issues.async_remove_label(
                owner=repo.owner,
                repo=repo.repo,
                issue_number=issue_number,
                name=label,
            )
        except RequestFailed as exc:
            if exc.response.status_code == 404:
                logger.debug(
                    "Label '%s' not found on issue #%d, ignoring",
                    label,
                    issue_number,
                )
            else:
                raise

    async def replace_phase_label(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        new_label: str,
    ) -> None:
        """既存の phase:* ラベルを全て削除し、新しいフェーズラベルを追加する.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
            new_label: 新しいフェーズラベル (例: "phase:implement").
        """
        issue = await self.get_issue(repo, issue_number)
        if issue.labels:
            for lbl in issue.labels:
                label_name: str | None = None
                if isinstance(lbl, str):
                    label_name = lbl
                elif hasattr(lbl, "name"):
                    name_val = getattr(lbl, "name", None)
                    if isinstance(name_val, str):
                        label_name = name_val
                if label_name and label_name.startswith("phase:"):
                    await self.remove_label(repo, issue_number, label_name)

        await self.add_label(repo, issue_number, new_label)

    async def create_label(
        self,
        repo: RepositoryConfig,
        name: str,
        color: str = "ededed",
        description: str = "",
    ) -> Label:
        """リポジトリにラベルを作成する. 既に存在する場合は更新する.

        Args:
            repo: リポジトリ設定.
            name: ラベル名.
            color: ラベル色 (6桁16進数、# なし).
            description: ラベルの説明.

        Returns:
            作成または更新された Label オブジェクト.
        """
        try:
            response = await self._github.rest.issues.async_create_label(
                owner=repo.owner,
                repo=repo.repo,
                data={"name": name, "color": color, "description": description},
            )
            return response.parsed_data
        except RequestFailed as exc:
            if exc.response.status_code == 422:
                # Already exists -- update via PATCH
                encoded_name = urllib.parse.quote(name, safe="")
                response = await self._github.rest.issues.async_update_label(
                    owner=repo.owner,
                    repo=repo.repo,
                    name=encoded_name,
                    data={
                        "new_name": name,
                        "color": color,
                        "description": description,
                    },
                )
                return response.parsed_data
            raise

    # ── Pull Request 操作 ──────────────────────────────

    async def create_pull_request(
        self,
        repo: RepositoryConfig,
        title: str,
        body: str,
        head: str,
        base: str | None = None,
    ) -> PullRequest:
        """Pull Request を作成する.

        Args:
            repo: リポジトリ設定.
            title: PR タイトル.
            body: PR 本文 (Markdown).
            head: ソースブランチ名.
            base: ターゲットブランチ名. None の場合は repo.base_branch を使用.

        Returns:
            作成された PullRequest オブジェクト.
        """
        response = await self._github.rest.pulls.async_create(
            owner=repo.owner,
            repo=repo.repo,
            data={
                "title": title,
                "body": body,
                "head": head,
                "base": base or repo.base_branch,
            },
        )
        return response.parsed_data

    async def list_pull_requests(
        self,
        repo: RepositoryConfig,
        state: str = "open",
        head: str | None = None,
    ) -> list[PullRequestSimple]:
        """Pull Request の一覧を取得する.

        Args:
            repo: リポジトリ設定.
            state: PR の状態フィルタ ("open" | "closed" | "all").
            head: ソースブランチでフィルタ (例: "owner:feature/issue-42").

        Returns:
            PullRequestSimple のリスト.
        """
        kwargs: dict[str, Any] = {
            "owner": repo.owner,
            "repo": repo.repo,
            "state": state,
            "per_page": 100,
        }
        if head is not None:
            kwargs["head"] = head

        response = await self._github.rest.pulls.async_list(**kwargs)
        return list(response.parsed_data)

    async def approve_pull_request(
        self,
        repo: RepositoryConfig,
        pr_number: int,
    ) -> PullRequestReview:
        """Pull Request を approve する.

        Args:
            repo: リポジトリ設定.
            pr_number: PR 番号.

        Returns:
            作成された PullRequestReview オブジェクト.
        """
        response = await self._github.rest.pulls.async_create_review(
            owner=repo.owner,
            repo=repo.repo,
            pull_number=pr_number,
            data={"event": "APPROVE"},
        )
        return response.parsed_data

    async def get_pr_reviews(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """Pull Request のレビュー一覧を取得する.

        Args:
            owner: リポジトリオーナー.
            repo: リポジトリ名.
            pr_number: PR 番号.

        Returns:
            レビューの辞書リスト.
        """
        response = await self._github.rest.pulls.async_list_reviews(
            owner=owner,
            repo=repo,
            pull_number=pr_number,
            per_page=100,
        )
        reviews_list: list[Any] = list(response.parsed_data)
        return [
            {
                "id": review.id,
                "user": ({"login": review.user.login} if review.user else None),
                "state": review.state,
                "body": review.body,
                "submitted_at": (review.submitted_at.isoformat() if review.submitted_at else None),
            }
            for review in reviews_list
        ]

    async def get_pr_comments(
        self,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """Pull Request のレビューコメント一覧を取得する.

        Args:
            owner: リポジトリオーナー.
            repo: リポジトリ名.
            pr_number: PR 番号.

        Returns:
            レビューコメントの辞書リスト.
        """
        response = await self._github.rest.pulls.async_list_review_comments(
            owner=owner,
            repo=repo,
            pull_number=pr_number,
            per_page=100,
        )
        comments_list: list[Any] = list(response.parsed_data)
        return [
            {
                "id": comment.id,
                "user": ({"login": comment.user.login} if comment.user else None),
                "body": comment.body,
                "path": comment.path,
                "line": comment.line,
                "side": comment.side,
                "created_at": comment.created_at.isoformat(),
            }
            for comment in comments_list
        ]

    async def merge_pull_request(
        self,
        repo: RepositoryConfig,
        pr_number: int,
        merge_method: str = "squash",
    ) -> None:
        """Pull Request をマージする.

        Args:
            repo: リポジトリ設定.
            pr_number: PR 番号.
            merge_method: マージ方法 ("merge" | "squash" | "rebase").

        Raises:
            githubkit.exception.RequestFailed: マージ不可の場合.
        """
        await self._github.rest.pulls.async_merge(  # type: ignore[call-overload]
            owner=repo.owner,
            repo=repo.repo,
            pull_number=pr_number,
            merge_method=merge_method,
        )

    # ── Issue 状態操作 ────────────────────────────────

    async def close_issue(
        self,
        repo: RepositoryConfig,
        issue_number: int,
    ) -> None:
        """Issue をクローズする.

        Args:
            repo: リポジトリ設定.
            issue_number: Issue 番号.
        """
        await self._github.rest.issues.async_update(
            owner=repo.owner,
            repo=repo.repo,
            issue_number=issue_number,
            data={"state": "closed"},
        )

    async def get_issues_with_label(
        self,
        repo: RepositoryConfig,
        label: str,
        state: str = "open",
    ) -> list[Issue]:
        """指定ラベルが付いた Issue の一覧を取得する.

        Args:
            repo: リポジトリ設定.
            label: フィルタするラベル名.
            state: Issue の状態 ("open" | "closed" | "all").

        Returns:
            Issue のリスト.
        """
        response = await self._github.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.repo,
            labels=label,
            state=state,  # type: ignore[arg-type]
            per_page=100,
        )
        return list(response.parsed_data)

    # ── CI/CD 操作 ─────────────────────────────────────

    async def get_check_runs(
        self,
        repo: RepositoryConfig,
        ref: str,
    ) -> list[dict[str, Any]]:
        """指定 ref の CI/CD チェック結果を取得する.

        Args:
            repo: リポジトリ設定.
            ref: ブランチ名、タグ名、または SHA.

        Returns:
            チェック結果の辞書リスト.
        """
        response = await self._github.rest.checks.async_list_for_ref(
            owner=repo.owner,
            repo=repo.repo,
            ref=ref,
            per_page=100,
        )
        return [
            {
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
            }
            for run in response.parsed_data.check_runs
        ]


class AccountManager:
    """複数 GitHub アカウントの管理."""

    def __init__(
        self,
        accounts: dict[str, AccountConfig],
        resolver: CredentialResolver,
        repo_configs: list[RepositoryConfig] | None = None,
    ) -> None:
        """AccountManager を初期化する.

        Args:
            accounts: アカウント名をキー、AccountConfig を値とする辞書.
            resolver: トークン解決に使用する CredentialResolver.
            repo_configs: リポジトリ設定のリスト.
        """
        self._accounts = accounts
        self._resolver = resolver
        self._repo_configs: list[RepositoryConfig] = repo_configs or []
        self._clients: dict[str, GitHubClient] = {}

    async def get_client(self, account_name: str) -> GitHubClient:
        """指定アカウントの GitHubClient を取得する (キャッシュ付き).

        Args:
            account_name: アカウント名 (accounts のキー).

        Returns:
            認証済みの GitHubClient.

        Raises:
            KeyError: アカウントが未定義の場合.
            CredentialError: トークン解決に失敗した場合.
        """
        if account_name in self._clients:
            return self._clients[account_name]

        if account_name not in self._accounts:
            msg = f"Account '{account_name}' is not defined"
            raise KeyError(msg)

        account = self._accounts[account_name]
        token = await self._resolver.resolve(account)
        client = GitHubClient(token=token)
        self._clients[account_name] = client
        return client

    async def get_client_for_repo(
        self,
        owner: str,
        repo: str,
    ) -> GitHubClient:
        """リポジトリに紐づくアカウントの GitHubClient を取得する.

        Args:
            owner: リポジトリオーナー.
            repo: リポジトリ名.

        Returns:
            認証済みの GitHubClient.

        Raises:
            ConfigError: 該当リポジトリが config に存在しない場合.
        """
        repo_config = next(
            (rc for rc in self._repo_configs if rc.owner == owner and rc.repo == repo),
            None,
        )
        if repo_config is None:
            raise ConfigError(f"Repository {owner}/{repo} not found in config")

        account = self.resolve_account(repo_config)
        return await self.get_client(account.name)

    def resolve_account(self, repo_config: RepositoryConfig) -> AccountConfig:
        """リポジトリ設定からアカウントを解決する.

        解決優先順位:
        1. repo_config.account が指定されている場合はそのアカウント
        2. default: true のアカウント
        3. アカウントが 1 つのみの場合はそれを使用
        4. いずれにも該当しない場合は ConfigError を発生

        Args:
            repo_config: リポジトリ設定.

        Returns:
            解決された AccountConfig.

        Raises:
            ConfigError: アカウントを解決できない場合.
        """
        # 1. Explicit account
        if repo_config.account:
            if repo_config.account not in self._accounts:
                raise ConfigError(f"Account '{repo_config.account}' not found in accounts")
            return self._accounts[repo_config.account]

        # 2. Default account
        for account in self._accounts.values():
            if account.default:
                return account

        # 3. Single account
        if len(self._accounts) == 1:
            return next(iter(self._accounts.values()))

        # 4. Cannot resolve
        raise ConfigError(
            f"Cannot resolve account: no explicit account, no default, and {len(self._accounts)} accounts configured"
        )

    async def verify_all(self) -> dict[str, bool]:
        """全アカウントの認証を検証する.

        Returns:
            アカウント名をキー、認証成否を値とする辞書.
        """
        results: dict[str, bool] = {}
        for name, account in self._accounts.items():
            try:
                token = await self._resolver.resolve(account)
                await self._resolver.verify(token)
                results[name] = True
            except Exception:
                logger.warning("Account '%s' verification failed", name)
                results[name] = False
        return results
