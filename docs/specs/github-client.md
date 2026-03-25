# GitHubClient / AccountManager 実装仕様書

## 概要

`githubkit` をラップした非同期 GitHub API クライアントと、マルチアカウント管理クラスの実装仕様。
Issue 操作、PR 操作、ラベル管理、リアクション取得など、オーケストレーターが必要とする全 GitHub 操作を提供する。

## メソッド名対応表

| spec のメソッド名 | 設計書のメソッド名 | 採用 |
|---|---|---|
| create_comment | post_comment | create_comment (GitHub API に合わせる) |
| list_comments | get_issue_comments | list_comments (GitHub API に合わせる) |
| merge_pull_request | merge_pr | merge_pull_request (明確) |
| create_label | create_labels | create_label (単体操作、一括はループで) |

> **Note:** メソッド名は GitHub API の命名規則に合わせる。設計書側を修正予定。

## 対象ファイル

- `src/ai_agent_orchestrator/github/client.py`

## 依存パッケージ

```python
from __future__ import annotations

import os
from typing import Any

from githubkit import GitHub, TokenAuthStrategy
from githubkit.versions.latest.models import (
    FullRepository,
    Issue,
    IssueComment,
    Label,
    PullRequest,
    PullRequestReview,
    Reaction,
)

from ai_agent_orchestrator.config.settings import AccountConfig, RepositoryConfig
from ai_agent_orchestrator.github.credential_resolver import CredentialResolver
```

---

## クラス: `GitHubClient`

### 説明

`githubkit.GitHub` の非同期クライアントをラップし、オーケストレーターが必要とする GitHub API 操作を提供する。
全メソッドは `async` であり、内部で `githubkit` の REST API を呼び出す。

### コンストラクタ

```python
class GitHubClient:
    """githubkit をラップした非同期 GitHub API クライアント."""

    def __init__(self, token: str) -> None:
        """GitHubClient を初期化する。

        Args:
            token: GitHub Personal Access Token または OAuth トークン。
        """
        self._github = GitHub(TokenAuthStrategy(token))
```

### 公開メソッド

#### `get_issue`

```python
async def get_issue(
    self,
    repo: RepositoryConfig,
    issue_number: int,
) -> Issue:
    """特定の Issue を取得する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。

    Returns:
        Issue オブジェクト。

    Raises:
        githubkit.exception.RequestFailed: API リクエスト失敗時。
    """
```

#### `create_comment`

```python
async def create_comment(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    body: str,
) -> IssueComment:
    """Issue にコメントを投稿する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        body: コメント本文 (Markdown)。

    Returns:
        作成された IssueComment オブジェクト。
    """
```

#### `list_comments`

```python
async def list_comments(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    since: str | None = None,
) -> list[IssueComment]:
    """Issue のコメント一覧を取得する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        since: この日時以降のコメントのみ取得 (ISO 8601 形式)。None の場合は全件。

    Returns:
        IssueComment のリスト (作成日時昇順)。
    """
```

#### `get_reactions`

```python
async def get_reactions(
    self,
    repo: RepositoryConfig,
    comment_id: int,
) -> list[Reaction]:
    """Issue コメントのリアクション一覧を取得する。

    Args:
        repo: リポジトリ設定。
        comment_id: コメント ID。

    Returns:
        Reaction のリスト。👍 (+1) の検出に使用する。
    """
```

#### `add_label`

```python
async def add_label(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    label: str,
) -> None:
    """Issue にラベルを追加する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        label: 追加するラベル名。
    """
```

#### `remove_label`

```python
async def remove_label(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    label: str,
) -> None:
    """Issue からラベルを削除する。存在しないラベルの場合は無視する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        label: 削除するラベル名。
    """
```

#### `replace_phase_label`

```python
async def replace_phase_label(
    self,
    repo: RepositoryConfig,
    issue_number: int,
    new_label: str,
) -> None:
    """既存の phase:* ラベルを全て削除し、新しいフェーズラベルを追加する。

    StateMachine のフェーズ遷移時に呼び出される。
    既存の "phase:" で始まるラベルを全て検索・削除した後、new_label を追加する。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
        new_label: 新しいフェーズラベル (例: "phase:implement")。
    """
```

#### `create_pull_request`

```python
async def create_pull_request(
    self,
    repo: RepositoryConfig,
    title: str,
    body: str,
    head: str,
    base: str | None = None,
) -> PullRequest:
    """Pull Request を作成する。

    Args:
        repo: リポジトリ設定。
        title: PR タイトル。
        body: PR 本文 (Markdown)。
        head: ソースブランチ名。
        base: ターゲットブランチ名。None の場合は repo.base_branch を使用。

    Returns:
        作成された PullRequest オブジェクト。
    """
```

#### `list_pull_requests`

```python
async def list_pull_requests(
    self,
    repo: RepositoryConfig,
    state: str = "open",
    head: str | None = None,
) -> list[PullRequest]:
    """Pull Request の一覧を取得する。

    Args:
        repo: リポジトリ設定。
        state: PR の状態フィルタ ("open" | "closed" | "all")。
        head: ソースブランチでフィルタ (例: "owner:feature/issue-42")。

    Returns:
        PullRequest のリスト。
    """
```

#### `approve_pull_request`

```python
async def approve_pull_request(
    self,
    repo: RepositoryConfig,
    pr_number: int,
) -> PullRequestReview:
    """Pull Request を approve する。

    Args:
        repo: リポジトリ設定。
        pr_number: PR 番号。

    Returns:
        作成された PullRequestReview オブジェクト。
    """
```

#### `merge_pull_request`

```python
async def merge_pull_request(
    self,
    repo: RepositoryConfig,
    pr_number: int,
    merge_method: str = "squash",
) -> None:
    """Pull Request をマージする。

    Args:
        repo: リポジトリ設定。
        pr_number: PR 番号。
        merge_method: マージ方法 ("merge" | "squash" | "rebase")。デフォルトは "squash"。

    Raises:
        githubkit.exception.RequestFailed: マージ不可 (コンフリクト等) の場合。
    """
```

#### `create_label`

```python
async def create_label(
    self,
    repo: RepositoryConfig,
    name: str,
    color: str = "ededed",
    description: str = "",
) -> Label:
    """リポジトリにラベルを作成する。既に存在する場合は更新する。

    Args:
        repo: リポジトリ設定。
        name: ラベル名。
        color: ラベル色 (6桁16進数、# なし)。
        description: ラベルの説明。

    Returns:
        作成または更新された Label オブジェクト。
    """
```

#### `get_pr_reviews`

```python
async def get_pr_reviews(
    self,
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict[str, Any]]:
    """Pull Request のレビュー一覧を取得する。

    GitHub API: GET /repos/{owner}/{repo}/pulls/{pr_number}/reviews
    ページネーション対応: 全件取得するまで繰り返す。

    Args:
        owner: リポジトリオーナー。
        repo: リポジトリ名。
        pr_number: PR 番号。

    Returns:
        レビューの辞書リスト。各辞書は id, user, state, body, submitted_at を含む。
        state は "APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED", "PENDING" のいずれか。

    Raises:
        githubkit.exception.RequestFailed: API リクエスト失敗時。

    実装メモ:
        - githubkit の rest.pulls.async_list_reviews() を使用
        - state でフィルタが必要な場合は呼び出し側で行う
    """
```

#### `get_pr_comments`

```python
async def get_pr_comments(
    self,
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict[str, Any]]:
    """Pull Request のレビューコメント一覧を取得する。

    GitHub API: GET /repos/{owner}/{repo}/pulls/{pr_number}/comments
    Issue コメントとは異なり、コード行に紐づくレビューコメントを取得する。

    Args:
        owner: リポジトリオーナー。
        repo: リポジトリ名。
        pr_number: PR 番号。

    Returns:
        レビューコメントの辞書リスト。各辞書は id, user, body, path, line, side, created_at を含む。

    Raises:
        githubkit.exception.RequestFailed: API リクエスト失敗時。

    実装メモ:
        - githubkit の rest.pulls.async_list_review_comments() を使用
        - diff_hunk フィールドでコード差分のコンテキストも取得可能
    """
```

### テストケース: `get_pr_reviews` / `get_pr_comments`

#### TC-GH-09: `get_pr_reviews` -- 正常系

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_pr_reviews_returns_reviews(client: GitHubClient) -> None:
    """PR のレビュー一覧を取得できることを検証する。"""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/reviews").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "user": {"login": "reviewer1"}, "state": "APPROVED", "body": "LGTM"},
            {"id": 2, "user": {"login": "reviewer2"}, "state": "CHANGES_REQUESTED", "body": "修正お願いします"},
        ])
    )

    reviews = await client.get_pr_reviews("test-org", "test-repo", 10)

    assert len(reviews) == 2
    assert reviews[0]["state"] == "APPROVED"
    assert reviews[1]["state"] == "CHANGES_REQUESTED"
```

#### TC-GH-10: `get_pr_comments` -- 正常系

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_pr_comments_returns_comments(client: GitHubClient) -> None:
    """PR のレビューコメント一覧を取得できることを検証する。"""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/comments").mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "user": {"login": "reviewer1"}, "body": "この行を修正してください", "path": "src/main.py", "line": 42},
        ])
    )

    comments = await client.get_pr_comments("test-org", "test-repo", 10)

    assert len(comments) == 1
    assert comments[0]["path"] == "src/main.py"
    assert comments[0]["line"] == 42
```

#### `close_issue`

```python
async def close_issue(
    self,
    repo: RepositoryConfig,
    issue_number: int,
) -> None:
    """Issue をクローズする。

    Args:
        repo: リポジトリ設定。
        issue_number: Issue 番号。
    """
```

#### `get_issues_with_label`

```python
async def get_issues_with_label(
    self,
    repo: RepositoryConfig,
    label: str,
    state: str = "open",
) -> list[Issue]:
    """指定ラベルが付いた Issue の一覧を取得する。

    Args:
        repo: リポジトリ設定。
        label: フィルタするラベル名。
        state: Issue の状態 ("open" | "closed" | "all")。

    Returns:
        Issue のリスト。
    """
```

#### `get_check_runs`

```python
async def get_check_runs(
    self,
    repo: RepositoryConfig,
    ref: str,
) -> list[dict[str, Any]]:
    """指定 ref の CI/CD チェック結果を取得する。

    Args:
        repo: リポジトリ設定。
        ref: ブランチ名、タグ名、または SHA。

    Returns:
        チェック結果の辞書リスト。各辞書は name, status, conclusion を含む。
    """
```

---

## クラス: `AccountManager`

### 説明

複数 GitHub アカウントの管理を行う。アカウントごとの `GitHubClient` インスタンスをキャッシュし、
リポジトリ設定からアカウントを解決して適切なクライアントを返す。

### コンストラクタ

```python
class AccountManager:
    """複数 GitHub アカウントの管理."""

    def __init__(
        self,
        accounts: dict[str, AccountConfig],
        resolver: CredentialResolver,
        repo_configs: list[RepositoryConfig] | None = None,
    ) -> None:
        """AccountManager を初期化する。

        Args:
            accounts: アカウント名をキー、AccountConfig を値とする辞書。
            resolver: トークン解決に使用する CredentialResolver。
            repo_configs: リポジトリ設定のリスト。get_client_for_repo() で
                owner/repo からアカウントを解決するために使用する。
                None の場合は get_client_for_repo() で ConfigError が発生する。
        """
        self._accounts = accounts
        self._resolver = resolver
        self._repo_configs: list[RepositoryConfig] = repo_configs or []
        self._clients: dict[str, GitHubClient] = {}
```

### 公開メソッド

#### `get_client`

```python
async def get_client(self, account_name: str) -> GitHubClient:
    """指定アカウントの GitHubClient を取得する (キャッシュ付き)。

    同一アカウントへの 2 回目以降の呼び出しではキャッシュされたインスタンスを返す。

    Args:
        account_name: アカウント名 (accounts のキー)。

    Returns:
        認証済みの GitHubClient。

    Raises:
        KeyError: アカウントが未定義の場合。
        AuthError: トークン解決に失敗した場合。
    """
```

#### `get_client_for_repo`

```python
async def get_client_for_repo(
    self,
    owner: str,
    repo: str,
) -> GitHubClient:
    """リポジトリに紐づくアカウントの GitHubClient を取得する。

    内部で _repo_configs から owner/repo に一致する RepositoryConfig を検索し、
    resolve_account() を使用してアカウントを特定し、get_client() で
    クライアントを取得する。

    実装メモ:
        _repo_configs リストを走査して owner/repo が一致する RepositoryConfig を取得する。
        一致するものがない場合は ConfigError を発生させる。
        ```python
        repo_config = next(
            (rc for rc in self._repo_configs if rc.owner == owner and rc.repo == repo),
            None,
        )
        if repo_config is None:
            raise ConfigError(f"Repository {owner}/{repo} not found in config")
        account = self.resolve_account(repo_config)
        return await self.get_client(account.name)
        ```

    Args:
        owner: リポジトリオーナー。
        repo: リポジトリ名。

    Returns:
        認証済みの GitHubClient。

    Raises:
        ConfigError: _repo_configs に該当リポジトリが存在しない場合。
    """
```

#### `resolve_account`

```python
def resolve_account(self, repo_config: RepositoryConfig) -> AccountConfig:
    """リポジトリ設定からアカウントを解決する。

    解決優先順位:
    1. repo_config.account が指定されている場合はそのアカウント
    2. default: true のアカウント
    3. アカウントが 1 つのみの場合はそれを使用
    4. いずれにも該当しない場合は ConfigError を発生

    Args:
        repo_config: リポジトリ設定。

    Returns:
        解決された AccountConfig。

    Raises:
        ConfigError: アカウントを解決できない場合。
    """
```

#### `verify_all`

```python
async def verify_all(self) -> dict[str, bool]:
    """全アカウントの認証を検証する。

    全アカウントのトークンを解決し、GitHub API で有効性を確認する。

    Returns:
        アカウント名をキー、認証成否を値とする辞書。
    """
```

---

## テストケース

テストファイル: `tests/unit/github/test_client.py`

`respx` で GitHub API レスポンスをモックし、`pytest-asyncio` で非同期テストを実行する。

### テスト用の共通フィクスチャ

```python
import pytest
import respx
import httpx
from githubkit import GitHub, TokenAuthStrategy

from ai_agent_orchestrator.github.client import GitHubClient, AccountManager
from ai_agent_orchestrator.config.settings import AccountConfig, RepositoryConfig
from ai_agent_orchestrator.github.credential_resolver import CredentialResolver


@pytest.fixture
def repo_config() -> RepositoryConfig:
    return RepositoryConfig(owner="test-org", repo="test-repo", base_branch="main")


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(token="ghp_test_token_123")
```

### テストケース一覧

#### TC-GH-01: `get_issue` -- 正常系

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_issue_returns_issue(client: GitHubClient, repo_config: RepositoryConfig) -> None:
    """Issue を正常に取得できることを検証する。"""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/42").mock(
        return_value=httpx.Response(200, json={
            "number": 42,
            "title": "テスト Issue",
            "body": "Issue の本文",
            "state": "open",
            "labels": [{"name": "ai-agent"}],
            "user": {"login": "testuser"},
        })
    )

    issue = await client.get_issue(repo_config, 42)

    assert issue.number == 42
    assert issue.title == "テスト Issue"
```

#### TC-GH-02: `create_comment` -- 正常系

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_comment_posts_body(client: GitHubClient, repo_config: RepositoryConfig) -> None:
    """Issue コメントが正しい本文で投稿されることを検証する。"""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/issues/42/comments").mock(
        return_value=httpx.Response(201, json={
            "id": 100,
            "body": "テストコメント",
            "user": {"login": "ai-bot"},
        })
    )

    comment = await client.create_comment(repo_config, 42, "テストコメント")

    assert route.called
    assert comment.body == "テストコメント"
    request_body = route.calls[0].request.content
    assert b"テストコメント" in request_body
```

#### TC-GH-03: `replace_phase_label` -- 既存ラベル置換

```python
@pytest.mark.asyncio
@respx.mock
async def test_replace_phase_label_removes_old_and_adds_new(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """既存の phase:* ラベルが削除され、新しいラベルが追加されることを検証する。"""
    # Issue 取得 (既存ラベル付き)
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/42").mock(
        return_value=httpx.Response(200, json={
            "number": 42,
            "labels": [
                {"name": "ai-agent"},
                {"name": "phase:hearing"},
            ],
        })
    )
    # ラベル削除
    remove_route = respx.delete(
        "https://api.github.com/repos/test-org/test-repo/issues/42/labels/phase%3Ahearing"
    ).mock(return_value=httpx.Response(200, json=[]))
    # ラベル追加
    add_route = respx.post(
        "https://api.github.com/repos/test-org/test-repo/issues/42/labels"
    ).mock(return_value=httpx.Response(200, json=[{"name": "phase:design"}]))

    await client.replace_phase_label(repo_config, 42, "phase:design")

    assert remove_route.called
    assert add_route.called
```

#### TC-GH-04: `create_pull_request` -- 正常系

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_pull_request_with_correct_params(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """PR が正しいパラメータで作成されることを検証する。"""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/pulls").mock(
        return_value=httpx.Response(201, json={
            "number": 10,
            "title": "feat: Issue #42 の実装",
            "html_url": "https://github.com/test-org/test-repo/pull/10",
            "state": "open",
            "head": {"ref": "feature/issue-42"},
            "base": {"ref": "main"},
        })
    )

    pr = await client.create_pull_request(
        repo_config,
        title="feat: Issue #42 の実装",
        body="## 概要\nIssue #42 の実装です",
        head="feature/issue-42",
    )

    assert pr.number == 10
    assert route.called
```

#### TC-GH-05: `merge_pull_request` -- squash マージ

```python
@pytest.mark.asyncio
@respx.mock
async def test_merge_pull_request_squash(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """PR が squash マージされることを検証する。"""
    route = respx.put("https://api.github.com/repos/test-org/test-repo/pulls/10/merge").mock(
        return_value=httpx.Response(200, json={"merged": True, "sha": "abc123"})
    )

    await client.merge_pull_request(repo_config, 10, merge_method="squash")

    assert route.called
    request_body = route.calls[0].request.content
    assert b"squash" in request_body
```

#### TC-GH-06: `get_reactions` -- リアクション取得

```python
@pytest.mark.asyncio
@respx.mock
async def test_get_reactions_returns_thumbsup(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """コメントのリアクション一覧を取得し、thumbsup を検出できることを検証する。"""
    respx.get(
        "https://api.github.com/repos/test-org/test-repo/issues/comments/100/reactions"
    ).mock(
        return_value=httpx.Response(200, json=[
            {"id": 1, "content": "+1", "user": {"login": "reviewer"}},
            {"id": 2, "content": "heart", "user": {"login": "other"}},
        ])
    )

    reactions = await client.get_reactions(repo_config, comment_id=100)

    assert len(reactions) == 2
    thumbsup = [r for r in reactions if r.content == "+1"]
    assert len(thumbsup) == 1
```

#### TC-GH-07: `remove_label` -- 存在しないラベルの削除は無視

```python
@pytest.mark.asyncio
@respx.mock
async def test_remove_label_ignores_not_found(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """存在しないラベルの削除が例外を発生させないことを検証する。"""
    respx.delete(
        "https://api.github.com/repos/test-org/test-repo/issues/42/labels/nonexistent"
    ).mock(return_value=httpx.Response(404, json={"message": "Label does not exist"}))

    # 例外が発生しないことを確認
    await client.remove_label(repo_config, 42, "nonexistent")
```

#### TC-GH-08: `create_label` -- 既存ラベルの更新

```python
@pytest.mark.asyncio
@respx.mock
async def test_create_label_updates_existing(
    client: GitHubClient, repo_config: RepositoryConfig,
) -> None:
    """ラベルが既に存在する場合は 422 を受けて PATCH で更新することを検証する。"""
    # POST で 422 (既に存在)
    respx.post("https://api.github.com/repos/test-org/test-repo/labels").mock(
        return_value=httpx.Response(422, json={"errors": [{"code": "already_exists"}]})
    )
    # PATCH で更新
    patch_route = respx.patch(
        "https://api.github.com/repos/test-org/test-repo/labels/phase%3Ahearing"
    ).mock(
        return_value=httpx.Response(200, json={"name": "phase:hearing", "color": "0e8a16"})
    )

    label = await client.create_label(repo_config, "phase:hearing", color="0e8a16")

    assert patch_route.called
```

### AccountManager テストケース

テストファイル: `tests/unit/github/test_account_manager.py`

#### TC-AM-01: `get_client` -- キャッシュ動作

```python
@pytest.mark.asyncio
async def test_get_client_caches_instance() -> None:
    """同じアカウント名で 2 回呼び出すと同一インスタンスが返ることを検証する。"""
    accounts = {"work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK")}
    resolver = MockCredentialResolver(token="ghp_test")
    manager = AccountManager(accounts, resolver)

    client1 = await manager.get_client("work")
    client2 = await manager.get_client("work")

    assert client1 is client2
```

#### TC-AM-02: `get_client` -- 未定義アカウントで KeyError

```python
@pytest.mark.asyncio
async def test_get_client_raises_key_error_for_unknown_account() -> None:
    """未定義のアカウント名で KeyError が発生することを検証する。"""
    accounts = {"work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK")}
    resolver = MockCredentialResolver(token="ghp_test")
    manager = AccountManager(accounts, resolver)

    with pytest.raises(KeyError):
        await manager.get_client("personal")
```

#### TC-AM-03: `verify_all` -- 全アカウント検証

```python
@pytest.mark.asyncio
async def test_verify_all_returns_status_for_all_accounts() -> None:
    """全アカウントの検証結果が返ることを検証する。"""
    accounts = {
        "work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK"),
        "oss": AccountConfig(name="oss", token_env="GITHUB_TOKEN_OSS"),
    }
    resolver = MockCredentialResolver(token="ghp_test")
    manager = AccountManager(accounts, resolver)

    result = await manager.verify_all()

    assert "work" in result
    assert "oss" in result
    assert isinstance(result["work"], bool)
```

#### TC-AM-04: `resolve_account` -- デフォルトアカウント解決

```python
def test_resolve_account_uses_default() -> None:
    """repo_config.account が未指定の場合に default アカウントが使われることを検証する。"""
    accounts = {
        "work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK", default=True),
        "oss": AccountConfig(name="oss", token_env="GITHUB_TOKEN_OSS"),
    }
    resolver = MockCredentialResolver(token="ghp_test")
    manager = AccountManager(accounts, resolver)
    repo_config = RepositoryConfig(owner="test-org", repo="test-repo")

    account = manager.resolve_account(repo_config)

    assert account.name == "work"
```

#### TC-AM-05: `resolve_account` -- 明示的アカウント指定

```python
def test_resolve_account_uses_explicit_account() -> None:
    """repo_config.account が指定されている場合にそのアカウントが使われることを検証する。"""
    accounts = {
        "work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK", default=True),
        "oss": AccountConfig(name="oss", token_env="GITHUB_TOKEN_OSS"),
    }
    resolver = MockCredentialResolver(token="ghp_test")
    manager = AccountManager(accounts, resolver)
    repo_config = RepositoryConfig(owner="test-org", repo="test-repo", account="oss")

    account = manager.resolve_account(repo_config)

    assert account.name == "oss"
```
