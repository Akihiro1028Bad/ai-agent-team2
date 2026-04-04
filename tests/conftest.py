"""共通テストフィクスチャ."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


# ──────────────────────────────────────
# Fake GitHub Client
# ──────────────────────────────────────
@dataclass
class FakeIssue:
    """テスト用 Issue."""

    number: int = 1
    title: str = "Test Issue"
    body: str = "Test body"
    labels: list[str] = field(default_factory=list)
    state: str = "open"


@dataclass
class FakeComment:
    """テスト用コメント."""

    id: int = 1
    body: str = ""
    reactions: dict[str, int] = field(default_factory=dict)


@dataclass
class FakePullRequest:
    """テスト用 PR."""

    number: int = 1
    title: str = "Test PR"
    state: str = "open"
    body: str = ""
    merged: bool = False


class FakeGitHubClient:
    """GitHubClient の Fake 実装."""

    def __init__(self) -> None:
        self.issues: dict[int, FakeIssue] = {}
        self.comments: dict[int, list[FakeComment]] = {}
        self.pull_requests: dict[int, FakePullRequest] = {}
        self.labels: dict[int, list[str]] = {}
        self.reactions: dict[int, list[str]] = {}
        self.replied_comments: list[tuple[int, str]] = []
        self.review_comments_data: list[dict[str, Any]] = []

    async def get_issue(self, owner: str, repo: str, number: int) -> FakeIssue:
        return self.issues[number]

    async def create_comment(self, owner: str, repo: str, issue_number: int, body: str) -> FakeComment:
        comment = FakeComment(id=len(self.comments.get(issue_number, [])) + 1, body=body)
        self.comments.setdefault(issue_number, []).append(comment)
        return comment

    async def add_label(self, owner: str, repo: str, issue_number: int, label: str) -> None:
        self.labels.setdefault(issue_number, []).append(label)

    async def remove_label(self, owner: str, repo: str, issue_number: int, label: str) -> None:
        if issue_number in self.labels:
            self.labels[issue_number] = [la for la in self.labels[issue_number] if la != label]

    async def replace_phase_label(self, owner: str, repo: str, issue_number: int, new_label: str) -> None:
        if issue_number in self.labels:
            self.labels[issue_number] = [la for la in self.labels[issue_number] if not la.startswith("phase:")]
        self.labels.setdefault(issue_number, []).append(new_label)

    async def reply_to_review_comment(
        self,
        repo: Any,
        pr_number: int,
        comment_id: int,
        body: str,
    ) -> None:
        """PRレビューコメントのスレッドに返信する (Fake 実装)."""
        self.replied_comments.append((comment_id, body))

    async def get_pr_review_comments(
        self,
        repo: Any,
        pr_number: int,
    ) -> list[dict[str, Any]]:
        """PRのレビューコメント一覧を返す (Fake 実装)."""
        return list(self.review_comments_data)


# ──────────────────────────────────────
# Fake Claude Agent Runner
# ──────────────────────────────────────
class FakeClaudeRunner:
    """ClaudeAgentRunner の Fake 実装."""

    def __init__(self) -> None:
        self.responses: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    async def run(self, prompt: str, *, cwd: str | None = None, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"prompt": prompt, "cwd": cwd, **kwargs})
        # プロンプトのキーワードに基づいてレスポンスを返す
        for key, response in self.responses.items():
            if key in prompt:
                return {"session_id": "fake-session", "result": response, "cost": 0.01}
        return {"session_id": "fake-session", "result": "OK", "cost": 0.01}


# ──────────────────────────────────────
# Fixtures
# ──────────────────────────────────────
@pytest.fixture
def fake_github() -> FakeGitHubClient:
    """FakeGitHubClient を返す."""
    return FakeGitHubClient()


@pytest.fixture
def fake_claude() -> FakeClaudeRunner:
    """FakeClaudeRunner を返す."""
    return FakeClaudeRunner()


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """テスト用の一時ワークスペースを返す."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """テスト用のconfig.yamlを返す."""
    config = tmp_path / "config.yaml"
    config.write_text("""
repositories:
  - owner: "test-owner"
    repo: "test-repo"
    account: "default"
    base_branch: "main"

accounts:
  default:
    token_env: "GITHUB_TOKEN_TEST"
    default: true

concurrency:
  max_total: 2
  max_per_repo: 1
""")
    return config
