"""GitHubClient / AccountManager 単体テスト."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from ai_agent_orchestrator.config.settings import AccountConfig, RepositoryConfig
from ai_agent_orchestrator.credential import CredentialResolver
from ai_agent_orchestrator.github.client import (
    AccountManager,
    ConfigError,
    GitHubClient,
)

# ──────────────────────────────────────
# Helper: complete mock JSON builders
# ──────────────────────────────────────


def _user(login: str = "testuser") -> dict[str, Any]:
    """Build a valid SimpleUser JSON."""
    return {
        "login": login,
        "id": 1,
        "node_id": "U_1",
        "avatar_url": "",
        "gravatar_id": "",
        "url": "",
        "html_url": "",
        "followers_url": "",
        "following_url": "",
        "gists_url": "",
        "starred_url": "",
        "subscriptions_url": "",
        "organizations_url": "",
        "repos_url": "",
        "events_url": "",
        "received_events_url": "",
        "type": "User",
        "site_admin": False,
    }


def _reactions(url: str = "") -> dict[str, Any]:
    return {
        "url": url,
        "total_count": 0,
        "+1": 0,
        "-1": 0,
        "laugh": 0,
        "hooray": 0,
        "confused": 0,
        "heart": 0,
        "rocket": 0,
        "eyes": 0,
    }


def _label(name: str, color: str = "ededed") -> dict[str, Any]:
    return {
        "name": name,
        "id": 1,
        "node_id": "L_1",
        "url": "",
        "color": color,
        "default": False,
        "description": "",
    }


def _issue(
    number: int = 42,
    title: str = "test",
    body: str = "body",
    state: str = "open",
    labels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a valid Issue JSON."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "labels": labels or [],
        "user": _user(),
        "url": f"https://api.github.com/repos/o/r/issues/{number}",
        "repository_url": "https://api.github.com/repos/o/r",
        "labels_url": "",
        "comments_url": "",
        "events_url": "",
        "html_url": "",
        "id": number,
        "node_id": f"I_{number}",
        "locked": False,
        "milestone": None,
        "comments": 0,
        "closed_at": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "author_association": "OWNER",
        "reactions": _reactions(),
        "timeline_url": "",
    }


def _comment(comment_id: int = 100, body: str = "comment") -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "user": _user("ai-bot"),
        "node_id": f"C_{comment_id}",
        "url": "",
        "html_url": "",
        "issue_url": "",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "author_association": "OWNER",
        "reactions": _reactions(),
    }


def _repo_json() -> dict[str, Any]:
    """Full Repository JSON."""
    return {
        "id": 1,
        "node_id": "R_1",
        "name": "test-repo",
        "full_name": "test-org/test-repo",
        "license_": None,
        "license": None,
        "forks": 0,
        "owner": _user("test-org"),
        "private": False,
        "html_url": "https://github.com/test-org/test-repo",
        "description": None,
        "fork": False,
        "url": "https://api.github.com/repos/test-org/test-repo",
        "archive_url": "",
        "assignees_url": "",
        "blobs_url": "",
        "branches_url": "",
        "collaborators_url": "",
        "comments_url": "",
        "commits_url": "",
        "compare_url": "",
        "contents_url": "",
        "contributors_url": "",
        "deployments_url": "",
        "downloads_url": "",
        "events_url": "",
        "forks_url": "",
        "git_commits_url": "",
        "git_refs_url": "",
        "git_tags_url": "",
        "git_url": "",
        "issue_comment_url": "",
        "issue_events_url": "",
        "issues_url": "",
        "keys_url": "",
        "labels_url": "",
        "languages_url": "",
        "merges_url": "",
        "milestones_url": "",
        "notifications_url": "",
        "pulls_url": "",
        "releases_url": "",
        "ssh_url": "",
        "stargazers_url": "",
        "statuses_url": "",
        "subscribers_url": "",
        "subscription_url": "",
        "tags_url": "",
        "teams_url": "",
        "trees_url": "",
        "clone_url": "",
        "mirror_url": None,
        "hooks_url": "",
        "svn_url": "",
        "homepage": None,
        "language": None,
        "forks_count": 0,
        "stargazers_count": 0,
        "watchers_count": 0,
        "size": 0,
        "default_branch": "main",
        "open_issues_count": 0,
        "has_pages": False,
        "disabled": False,
        "pushed_at": "2024-01-01T00:00:00Z",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "open_issues": 0,
        "watchers": 0,
    }


def _pr_json(
    number: int = 10,
    title: str = "PR",
    state: str = "open",
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": state,
        "body": "",
        "labels": [],
        "milestone": None,
        "html_url": f"https://github.com/test-org/test-repo/pull/{number}",
        "head": {
            "ref": "feature/issue-42",
            "label": "test-org:feature/issue-42",
            "sha": "abc123",
            "user": _user(),
            "repo": _repo_json(),
        },
        "base": {
            "ref": "main",
            "label": "test-org:main",
            "sha": "def456",
            "user": _user("test-org"),
            "repo": _repo_json(),
        },
        "url": f"https://api.github.com/repos/test-org/test-repo/pulls/{number}",
        "id": number,
        "node_id": f"PR_{number}",
        "diff_url": "",
        "patch_url": "",
        "issue_url": "",
        "commits_url": "",
        "review_comments_url": "",
        "review_comment_url": "",
        "comments_url": "",
        "statuses_url": "",
        "locked": False,
        "closed_at": None,
        "merged_at": None,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "merge_commit_sha": None,
        "user": _user(),
        "author_association": "OWNER",
        "_links": {
            "self": {"href": ""},
            "html": {"href": ""},
            "issue": {"href": ""},
            "comments": {"href": ""},
            "review_comments": {"href": ""},
            "review_comment": {"href": ""},
            "commits": {"href": ""},
            "statuses": {"href": ""},
        },
        "auto_merge": None,
        "merged": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "merged_by": None,
        "comments": 0,
        "review_comments": 0,
        "maintainer_can_modify": False,
        "commits": 1,
        "additions": 10,
        "deletions": 2,
        "changed_files": 1,
    }


# ──────────────────────────────────────
# Fixtures
# ──────────────────────────────────────


@pytest.fixture
def repo_config() -> RepositoryConfig:
    """テスト用 RepositoryConfig."""
    return RepositoryConfig(owner="test-org", repo="test-repo", base_branch="main")


@pytest.fixture
def client() -> GitHubClient:
    """テスト用 GitHubClient."""
    return GitHubClient(token="ghp_test_token_123")


# ──────────────────────────────────────
# Mock CredentialResolver
# ──────────────────────────────────────


class MockCredentialResolver(CredentialResolver):
    """テスト用の CredentialResolver."""

    def __init__(self, token: str = "ghp_test") -> None:
        self._token = token

    async def resolve(self, account: AccountConfig) -> str:  # type: ignore[override]
        """固定トークンを返す."""
        return self._token

    async def verify(self, token: str) -> dict[str, Any]:
        """常に成功する検証."""
        return {"login": "test-user", "scopes": ["repo"]}


class FailingCredentialResolver(CredentialResolver):
    """常に失敗する CredentialResolver."""

    async def resolve(self, account: AccountConfig) -> str:  # type: ignore[override]
        """常に例外を送出する."""
        msg = "Token resolution failed"
        raise Exception(msg)

    async def verify(self, token: str) -> dict[str, Any]:
        """常に例外を送出する."""
        msg = "Verification failed"
        raise Exception(msg)


# ──────────────────────────────────────
# GitHubClient テスト
# ──────────────────────────────────────


@respx.mock
async def test_get_issue_returns_issue(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-01: Issue を正常に取得できることを検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/42").mock(
        return_value=httpx.Response(200, json=_issue(42, title="Test Issue"))
    )

    issue = await client.get_issue(repo_config, 42)

    assert issue.number == 42
    assert issue.title == "Test Issue"


@respx.mock
async def test_create_comment_posts_body(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-02: Issue コメントが正しい本文で投稿されることを検証する."""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/issues/42/comments").mock(
        return_value=httpx.Response(201, json=_comment(100, body="test body"))
    )

    comment = await client.create_comment(repo_config, 42, "test body")

    assert route.called
    assert comment.body == "test body"
    request_body = route.calls[0].request.content
    assert b"test body" in request_body


@respx.mock
async def test_replace_phase_label_removes_old_and_adds_new(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-03: 既存の phase:* ラベルが削除され新しいラベルが追加されること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/42").mock(
        return_value=httpx.Response(
            200,
            json=_issue(42, labels=[_label("ai-agent"), _label("phase:hearing")]),
        )
    )
    remove_route = respx.delete(
        "https://api.github.com/repos/test-org/test-repo/issues/42/labels/phase%3Ahearing"
    ).mock(return_value=httpx.Response(200, json=[]))
    add_route = respx.post("https://api.github.com/repos/test-org/test-repo/issues/42/labels").mock(
        return_value=httpx.Response(200, json=[_label("phase:design")])
    )

    await client.replace_phase_label(repo_config, 42, "phase:design")

    assert remove_route.called
    assert add_route.called


@respx.mock
async def test_create_pull_request_with_correct_params(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-04: PR が正しいパラメータで作成されることを検証する."""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/pulls").mock(
        return_value=httpx.Response(201, json=_pr_json(10, title="feat: #42"))
    )

    pr = await client.create_pull_request(
        repo_config,
        title="feat: Issue #42",
        body="Implementation",
        head="feature/issue-42",
    )

    assert pr.number == 10
    assert route.called


@respx.mock
async def test_merge_pull_request_squash(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-05: PR が squash マージされることを検証する."""
    route = respx.put("https://api.github.com/repos/test-org/test-repo/pulls/10/merge").mock(
        return_value=httpx.Response(200, json={"merged": True, "sha": "abc123", "message": "merged"})
    )

    await client.merge_pull_request(repo_config, 10, merge_method="squash")

    assert route.called
    assert b"squash" in route.calls[0].request.content


@respx.mock
async def test_get_reactions_returns_thumbsup(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-06: リアクション一覧を取得し thumbsup を検出できること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/comments/100/reactions").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "content": "+1",
                    "user": _user("reviewer"),
                    "node_id": "R_1",
                    "created_at": "2024-01-01T00:00:00Z",
                },
                {
                    "id": 2,
                    "content": "heart",
                    "user": _user("other"),
                    "node_id": "R_2",
                    "created_at": "2024-01-01T00:00:00Z",
                },
            ],
        )
    )

    reactions = await client.get_reactions(repo_config, comment_id=100)

    assert len(reactions) == 2
    thumbsup = [r for r in reactions if r.content == "+1"]
    assert len(thumbsup) == 1


@respx.mock
async def test_remove_label_ignores_not_found(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-07: 存在しないラベルの削除が例外を発生させないこと."""
    respx.delete("https://api.github.com/repos/test-org/test-repo/issues/42/labels/nonexistent").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )

    await client.remove_label(repo_config, 42, "nonexistent")


@respx.mock
async def test_create_label_updates_existing(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-08: 既存ラベルは PATCH で更新されること."""
    respx.post("https://api.github.com/repos/test-org/test-repo/labels").mock(
        return_value=httpx.Response(422, json={"errors": [{"code": "already_exists"}]})
    )
    patch_route = respx.patch("https://api.github.com/repos/test-org/test-repo/labels/phase%3Ahearing").mock(
        return_value=httpx.Response(200, json=_label("phase:hearing", "0e8a16"))
    )

    label = await client.create_label(repo_config, "phase:hearing", color="0e8a16")

    assert patch_route.called
    assert label.name == "phase:hearing"


@respx.mock
async def test_get_pr_reviews_returns_reviews(client: GitHubClient) -> None:
    """TC-GH-09: PR のレビュー一覧を取得できること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/reviews").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "user": _user("reviewer1"),
                    "state": "APPROVED",
                    "body": "LGTM",
                    "submitted_at": "2024-01-01T00:00:00Z",
                    "node_id": "PRR_1",
                    "html_url": "",
                    "pull_request_url": "",
                    "commit_id": "abc123",
                    "author_association": "COLLABORATOR",
                    "_links": {"html": {"href": ""}, "pull_request": {"href": ""}},
                },
                {
                    "id": 2,
                    "user": _user("reviewer2"),
                    "state": "CHANGES_REQUESTED",
                    "body": "fix please",
                    "submitted_at": "2024-01-02T00:00:00Z",
                    "node_id": "PRR_2",
                    "html_url": "",
                    "pull_request_url": "",
                    "commit_id": "def456",
                    "author_association": "COLLABORATOR",
                    "_links": {"html": {"href": ""}, "pull_request": {"href": ""}},
                },
            ],
        )
    )

    reviews = await client.get_pr_reviews("test-org", "test-repo", 10)

    assert len(reviews) == 2
    assert reviews[0]["state"] == "APPROVED"
    assert reviews[1]["state"] == "CHANGES_REQUESTED"


@respx.mock
async def test_get_pr_comments_returns_comments(client: GitHubClient) -> None:
    """TC-GH-10: PR のレビューコメント一覧を取得できること."""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "user": _user("reviewer1"),
                    "body": "fix this line",
                    "path": "src/main.py",
                    "line": 42,
                    "side": "RIGHT",
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-01T00:00:00Z",
                    "node_id": "PRC_1",
                    "url": "",
                    "html_url": "",
                    "pull_request_url": "",
                    "diff_hunk": "@@ -40,5 +40,5 @@",
                    "commit_id": "abc123",
                    "original_commit_id": "abc123",
                    "pull_request_review_id": 1,
                    "author_association": "COLLABORATOR",
                    "_links": {
                        "self": {"href": ""},
                        "html": {"href": ""},
                        "pull_request": {"href": ""},
                    },
                    "reactions": _reactions(),
                },
            ],
        )
    )

    comments = await client.get_pr_comments("test-org", "test-repo", 10)

    assert len(comments) == 1
    assert comments[0]["path"] == "src/main.py"
    assert comments[0]["line"] == 42


@respx.mock
async def test_close_issue(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """Issue のクローズが正しく呼ばれることを検証する."""
    route = respx.patch("https://api.github.com/repos/test-org/test-repo/issues/42").mock(
        return_value=httpx.Response(200, json=_issue(42, state="closed"))
    )

    await client.close_issue(repo_config, 42)

    assert route.called
    assert b"closed" in route.calls[0].request.content


@respx.mock
async def test_get_issues_with_label(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """指定ラベル付き Issue の一覧取得を検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues").mock(
        return_value=httpx.Response(
            200,
            json=[_issue(1, labels=[_label("ai-agent")])],
        )
    )

    issues = await client.get_issues_with_label(repo_config, "ai-agent")

    assert len(issues) == 1
    assert issues[0].number == 1


@respx.mock
async def test_get_check_runs(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """CI/CD チェック結果の取得を検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/commits/abc123/check-runs").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_count": 1,
                "check_runs": [
                    {
                        "id": 1,
                        "name": "CI",
                        "status": "completed",
                        "conclusion": "success",
                        "head_sha": "abc123",
                        "node_id": "CR_1",
                        "html_url": "",
                        "details_url": "",
                        "url": "",
                        "external_id": "",
                        "started_at": "2024-01-01T00:00:00Z",
                        "completed_at": "2024-01-01T00:00:00Z",
                        "app": {
                            "id": 1,
                            "slug": "github-actions",
                            "node_id": "",
                            "owner": _user("github"),
                            "name": "GitHub Actions",
                            "description": "",
                            "events": [],
                            "permissions": {},
                            "html_url": "",
                            "external_url": "",
                            "created_at": "2024-01-01T00:00:00Z",
                            "updated_at": "2024-01-01T00:00:00Z",
                        },
                        "pull_requests": [],
                        "output": {
                            "title": None,
                            "summary": None,
                            "text": None,
                            "annotations_count": 0,
                            "annotations_url": "",
                        },
                        "check_suite": {"id": 1},
                    },
                ],
            },
        )
    )

    runs = await client.get_check_runs(repo_config, "abc123")

    assert len(runs) == 1
    assert runs[0]["name"] == "CI"
    assert runs[0]["conclusion"] == "success"


@respx.mock
async def test_list_comments(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """Issue コメント一覧の取得を検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/issues/42/comments").mock(
        return_value=httpx.Response(200, json=[_comment(1, body="Hello")])
    )

    comments = await client.list_comments(repo_config, 42)

    assert len(comments) == 1
    assert comments[0].body == "Hello"


@respx.mock
async def test_add_label(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """ラベル追加が正しく呼ばれることを検証する."""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/issues/42/labels").mock(
        return_value=httpx.Response(200, json=[_label("bug")])
    )

    await client.add_label(repo_config, 42, "bug")

    assert route.called


# ──────────────────────────────────────
# AccountManager テスト
# ──────────────────────────────────────


async def test_get_client_caches_instance() -> None:
    """TC-AM-01: 同じアカウント名で 2 回呼ぶと同一インスタンスが返る."""
    accounts = {"work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK")}
    manager = AccountManager(accounts, MockCredentialResolver(token="ghp_test"))

    client1 = await manager.get_client("work")
    client2 = await manager.get_client("work")

    assert client1 is client2


async def test_get_client_raises_key_error_for_unknown_account() -> None:
    """TC-AM-02: 未定義アカウントで KeyError."""
    accounts = {"work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK")}
    manager = AccountManager(accounts, MockCredentialResolver(token="ghp_test"))

    with pytest.raises(KeyError):
        await manager.get_client("personal")


async def test_verify_all_returns_status_for_all_accounts() -> None:
    """TC-AM-03: 全アカウントの検証結果が返る."""
    accounts = {
        "work": AccountConfig(name="work", token_env="GITHUB_TOKEN_WORK"),
        "oss": AccountConfig(name="oss", token_env="GITHUB_TOKEN_OSS"),
    }
    manager = AccountManager(accounts, MockCredentialResolver(token="ghp_test"))

    result = await manager.verify_all()

    assert "work" in result
    assert "oss" in result
    assert isinstance(result["work"], bool)


def test_resolve_account_uses_default() -> None:
    """TC-AM-04: default アカウントが使われる."""
    accounts = {
        "work": AccountConfig(name="work", token_env="T", default=True),
        "oss": AccountConfig(name="oss", token_env="T"),
    }
    manager = AccountManager(accounts, MockCredentialResolver())
    rc = RepositoryConfig(owner="o", repo="r")

    assert manager.resolve_account(rc).name == "work"


def test_resolve_account_uses_explicit_account() -> None:
    """TC-AM-05: 明示的アカウントが使われる."""
    accounts = {
        "work": AccountConfig(name="work", token_env="T", default=True),
        "oss": AccountConfig(name="oss", token_env="T"),
    }
    manager = AccountManager(accounts, MockCredentialResolver())
    rc = RepositoryConfig(owner="o", repo="r", account="oss")

    assert manager.resolve_account(rc).name == "oss"


def test_resolve_account_single_account_fallback() -> None:
    """1アカウントのみの場合そのアカウントが使われる."""
    accounts = {"solo": AccountConfig(name="solo", token_env="T")}
    manager = AccountManager(accounts, MockCredentialResolver())
    rc = RepositoryConfig(owner="o", repo="r")

    assert manager.resolve_account(rc).name == "solo"


def test_resolve_account_raises_config_error_when_ambiguous() -> None:
    """複数アカウントで指定なしは ConfigError."""
    accounts = {
        "work": AccountConfig(name="work", token_env="T"),
        "oss": AccountConfig(name="oss", token_env="T"),
    }
    manager = AccountManager(accounts, MockCredentialResolver())
    rc = RepositoryConfig(owner="o", repo="r")

    with pytest.raises(ConfigError):
        manager.resolve_account(rc)


async def test_get_client_for_repo_raises_config_error() -> None:
    """未登録リポジトリで ConfigError."""
    accounts = {"work": AccountConfig(name="work", token_env="T", default=True)}
    manager = AccountManager(accounts, MockCredentialResolver(), repo_configs=[])

    with pytest.raises(ConfigError):
        await manager.get_client_for_repo("unknown", "repo")


async def test_get_client_for_repo_resolves_correctly() -> None:
    """リポジトリからアカウントが正しく解決される."""
    accounts = {"work": AccountConfig(name="work", token_env="T", default=True)}
    repo_configs = [RepositoryConfig(owner="o", repo="r", account="work")]
    manager = AccountManager(accounts, MockCredentialResolver(), repo_configs=repo_configs)

    result = await manager.get_client_for_repo("o", "r")

    assert isinstance(result, GitHubClient)


async def test_verify_all_reports_failure() -> None:
    """認証失敗時に False が返る."""
    accounts = {"bad": AccountConfig(name="bad", token_env="X")}
    manager = AccountManager(accounts, FailingCredentialResolver())

    result = await manager.verify_all()

    assert result["bad"] is False


# ──────────────────────────────────────
# reply_to_review_comment / get_pr_review_comments テスト
# ──────────────────────────────────────


def _review_comment_json(
    comment_id: int = 1,
    body: str = "fix this",
    login: str = "reviewer",
    path: str = "src/main.py",
    line: int = 10,
) -> dict[str, Any]:
    """テスト用レビューコメント JSON を生成する."""
    return {
        "id": comment_id,
        "user": _user(login),
        "body": body,
        "path": path,
        "line": line,
        "side": "RIGHT",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "node_id": f"PRC_{comment_id}",
        "url": "",
        "html_url": "",
        "pull_request_url": "",
        "diff_hunk": "@@ -8,5 +8,5 @@",
        "commit_id": "abc123",
        "original_commit_id": "abc123",
        "pull_request_review_id": 1,
        "author_association": "COLLABORATOR",
        "_links": {
            "self": {"href": ""},
            "html": {"href": ""},
            "pull_request": {"href": ""},
        },
        "reactions": _reactions(),
    }


@respx.mock
async def test_reply_to_review_comment_calls_api(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-11: reply_to_review_comment が正しい API エンドポイントを呼び出すことを検証する."""
    route = respx.post("https://api.github.com/repos/test-org/test-repo/pulls/10/comments/200/replies").mock(
        return_value=httpx.Response(
            201,
            json=_review_comment_json(comment_id=300, body="修正します\n\n<!-- ai-agent-bot -->"),
        )
    )

    await client.reply_to_review_comment(repo_config, pr_number=10, comment_id=200, body="修正します")

    assert route.called
    request_body = route.calls[0].request.content
    assert b"ai-agent-bot" in request_body


@respx.mock
async def test_get_pr_review_comments_excludes_bot_comments(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-12: get_pr_review_comments がボットコメントを除外することを検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                _review_comment_json(comment_id=1, body="レビュー指摘です", login="reviewer1"),
                _review_comment_json(
                    comment_id=2,
                    body="修正が完了しました。コードをご確認ください。\n\n<!-- ai-agent-bot -->",
                    login="ai-bot",
                ),
                _review_comment_json(comment_id=3, body="別の指摘です", login="reviewer2"),
            ],
        )
    )

    comments = await client.get_pr_review_comments(repo_config, pr_number=10)

    # ボットコメント (id=2) は除外される
    assert len(comments) == 2
    comment_ids = [c["id"] for c in comments]
    assert 1 in comment_ids
    assert 3 in comment_ids
    assert 2 not in comment_ids


@respx.mock
async def test_get_pr_review_comments_returns_expected_fields(
    client: GitHubClient,
    repo_config: RepositoryConfig,
) -> None:
    """TC-GH-13: get_pr_review_comments が期待フィールドを含む辞書を返すことを検証する."""
    respx.get("https://api.github.com/repos/test-org/test-repo/pulls/10/comments").mock(
        return_value=httpx.Response(
            200,
            json=[
                _review_comment_json(
                    comment_id=42,
                    body="変数名を修正してください",
                    login="reviewer1",
                    path="src/foo.py",
                    line=99,
                ),
            ],
        )
    )

    comments = await client.get_pr_review_comments(repo_config, pr_number=10)

    assert len(comments) == 1
    c = comments[0]
    assert c["id"] == 42
    assert c["body"] == "変数名を修正してください"
    assert c["user"] == {"login": "reviewer1"}
    assert c["path"] == "src/foo.py"
    assert c["line"] == 99
    assert "created_at" in c
    # U2: インラインのみレビュー検知用フィールド。
    # in_reply_to_id は JSON に存在しない場合 githubkit が UNSET を返すため
    # None に正規化されること（is None 判定が成立すること）を検証する
    assert c["pull_request_review_id"] == 1
    assert c["in_reply_to_id"] is None


# ──────────────────────────────────────
# get_rate_limit テスト
# ──────────────────────────────────────


@respx.mock
async def test_get_rate_limit_returns_status(
    client: GitHubClient,
) -> None:
    """TC-GH-14: get_rate_limit が core リソースの残量を返すことを検証する."""
    full = {"limit": 5000, "remaining": 5000, "reset": 1700000000, "used": 0}
    core = {"limit": 5000, "remaining": 1234, "reset": 1700000000, "used": 3766}
    respx.get("https://api.github.com/rate_limit").mock(
        return_value=httpx.Response(
            200,
            json={
                "resources": {
                    "core": core,
                    "search": full,
                    "graphql": full,
                    "integration_manifest": full,
                    "code_scanning_upload": full,
                },
                "rate": core,
            },
        )
    )

    status = await client.get_rate_limit()

    assert status.remaining == 1234
    assert status.limit == 5000
    assert status.reset == 1700000000
