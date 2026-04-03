"""Scenario test helpers: GitHub operations, polling, build verification."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.github.client import GitHubClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCENARIO_PREFIX = "[SCENARIO-TEST]"
BOT_MARKER = "<!-- ai-agent-bot -->"
DEFAULT_POLL_INTERVAL = 15
DEFAULT_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Issue operations
# ---------------------------------------------------------------------------


async def create_test_issue(
    client: GitHubClient,
    repo: RepositoryConfig,
    title: str,
    body: str,
    labels: list[str] | None = None,
) -> Any:
    """Create a GitHub issue with SCENARIO_PREFIX in the title.

    Uses githubkit directly since GitHubClient doesn't expose create_issue.
    """
    full_title = f"{SCENARIO_PREFIX} {title}"
    response = await client._github.rest.issues.async_create(
        owner=repo.owner,
        repo=repo.repo,
        title=full_title,
        body=body,
        labels=labels or ["ai-agent"],
    )
    issue = response.parsed_data
    logger.info("Created issue #%s: %s", issue.number, full_title)
    return issue


async def wait_for_bot_comment(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    since: datetime | None = None,
    min_length: int = 10,
) -> Any:
    """Poll until a bot comment appears on the issue."""
    deadline = asyncio.get_event_loop().time() + timeout_sec
    since_str = since.isoformat() if since else None

    while asyncio.get_event_loop().time() < deadline:
        comments = await client.list_comments(repo, issue_number, since=since_str)
        for comment in comments:
            body = getattr(comment, "body", "") or ""
            user = getattr(comment, "user", None)
            user_type = getattr(user, "type", "")
            is_bot = user_type == "Bot" or BOT_MARKER in body
            if is_bot and len(body) >= min_length:
                logger.info(
                    "Found bot comment on #%d (id=%s, len=%d)",
                    issue_number,
                    getattr(comment, "id", "?"),
                    len(body),
                )
                return comment
        await asyncio.sleep(poll_interval)

    msg = f"Timeout waiting for bot comment on issue #{issue_number}"
    raise TimeoutError(msg)


async def wait_for_label(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
    label_prefix: str,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> str:
    """Poll until the issue has a label matching the given prefix."""
    deadline = asyncio.get_event_loop().time() + timeout_sec

    while asyncio.get_event_loop().time() < deadline:
        issue = await client.get_issue(repo, issue_number)
        labels = getattr(issue, "labels", []) or []
        for label in labels:
            name = getattr(label, "name", "") if hasattr(label, "name") else str(label)
            if name.startswith(label_prefix):
                logger.info("Found label '%s' on issue #%d", name, issue_number)
                return name
        await asyncio.sleep(poll_interval)

    msg = f"Timeout waiting for label '{label_prefix}*' on issue #{issue_number}"
    raise TimeoutError(msg)


async def wait_for_pr(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
    *,
    branch_prefix: str = "feature",
    timeout_sec: int = 600,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> Any:
    """Poll for an open PR on the issue's branch."""
    deadline = asyncio.get_event_loop().time() + timeout_sec
    owner = repo.owner
    branch_name = f"{branch_prefix}/issue-{issue_number}"
    head_filter = f"{owner}:{branch_name}"

    while asyncio.get_event_loop().time() < deadline:
        prs = await client.list_pull_requests(repo, state="open", head=head_filter)
        if prs:
            pr = prs[0]
            logger.info("Found PR #%s for issue #%d", getattr(pr, "number", "?"), issue_number)
            return pr
        await asyncio.sleep(poll_interval)

    msg = f"Timeout waiting for PR on branch '{branch_name}' for issue #{issue_number}"
    raise TimeoutError(msg)


async def add_thumbsup_to_latest_bot_comment(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
) -> int:
    """Find the latest bot comment and add a thumbsup reaction."""
    comments = await client.list_comments(repo, issue_number)
    bot_comments = []
    for comment in reversed(comments):
        body = getattr(comment, "body", "") or ""
        user = getattr(comment, "user", None)
        user_type = getattr(user, "type", "")
        if user_type == "Bot" or BOT_MARKER in body:
            bot_comments.append(comment)
            break

    if not bot_comments:
        msg = f"No bot comment found on issue #{issue_number}"
        raise ValueError(msg)

    comment = bot_comments[0]
    comment_id = getattr(comment, "id", None)
    await client.add_comment_reaction(repo, comment_id, "+1")
    logger.info("Added thumbsup to comment %s on issue #%d", comment_id, issue_number)
    return comment_id


async def approve_pr(
    client: GitHubClient,
    repo: RepositoryConfig,
    pr_number: int,
) -> None:
    """Approve a PR via GitHub review API."""
    await client.approve_pull_request(repo, pr_number)
    logger.info("Approved PR #%d", pr_number)


async def merge_pr(
    client: GitHubClient,
    repo: RepositoryConfig,
    pr_number: int,
) -> None:
    """Merge a PR (squash)."""
    await client.merge_pull_request(repo, pr_number, merge_method="squash")
    logger.info("Merged PR #%d", pr_number)


async def wait_for_issue_closed(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
    *,
    timeout_sec: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
) -> None:
    """Poll until the issue is closed."""
    deadline = asyncio.get_event_loop().time() + timeout_sec

    while asyncio.get_event_loop().time() < deadline:
        issue = await client.get_issue(repo, issue_number)
        state = getattr(issue, "state", "")
        if state == "closed":
            logger.info("Issue #%d is closed", issue_number)
            return
        await asyncio.sleep(poll_interval)

    msg = f"Timeout waiting for issue #{issue_number} to close"
    raise TimeoutError(msg)


async def wait_for_ci_status(
    client: GitHubClient,
    repo: RepositoryConfig,
    ref: str,
    *,
    expected: str = "success",
    timeout_sec: int = 600,
    poll_interval: int = 30,
) -> str:
    """Poll check runs until all complete with expected conclusion."""
    deadline = asyncio.get_event_loop().time() + timeout_sec

    while asyncio.get_event_loop().time() < deadline:
        check_runs = await client.get_check_runs(repo, ref)
        if check_runs:
            all_complete = all(cr.get("status") == "completed" for cr in check_runs)
            if all_complete:
                conclusions = [cr.get("conclusion", "") for cr in check_runs]
                overall = "success" if all(c == "success" for c in conclusions) else "failure"
                logger.info("CI status for %s: %s (runs: %s)", ref, overall, conclusions)
                return overall
        await asyncio.sleep(poll_interval)

    msg = f"Timeout waiting for CI on ref '{ref}'"
    raise TimeoutError(msg)


# ---------------------------------------------------------------------------
# Build / test verification in worktree
# ---------------------------------------------------------------------------


async def run_npm_in_worktree(
    worktree_path: str,
    command: str,
) -> tuple[int, str, str]:
    """Run an npm command in the worktree via subprocess."""
    full_cmd = f"cd {worktree_path} && npm ci --silent 2>/dev/null && npm run {command}"
    proc = await asyncio.create_subprocess_shell(
        full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    logger.info("npm %s in %s: exit=%d", command, worktree_path, proc.returncode or 0)
    return proc.returncode or 0, stdout, stderr


async def get_branch_diff_files(
    worktree_path: str,
    base_branch: str = "main",
) -> list[str]:
    """Get list of changed files compared to base branch."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "diff",
        f"origin/{base_branch}",
        "--name-only",
        cwd=worktree_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, _ = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    return [f for f in stdout.strip().split("\n") if f]


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


async def cleanup_issue(
    client: GitHubClient,
    repo: RepositoryConfig,
    issue_number: int,
) -> None:
    """Close an issue (best-effort)."""
    try:
        await client.close_issue(repo, issue_number)
        logger.info("Closed issue #%d", issue_number)
    except Exception:
        logger.warning("Failed to close issue #%d", issue_number, exc_info=True)


async def cleanup_pr(
    client: GitHubClient,
    repo: RepositoryConfig,
    pr_number: int,
) -> None:
    """Close a PR (best-effort) by updating its state."""
    try:
        owner = repo.owner
        repo_name = repo.repo
        await client._github.rest.pulls.async_update(
            owner=owner,
            repo=repo_name,
            pull_number=pr_number,
            state="closed",
        )
        logger.info("Closed PR #%d", pr_number)
    except Exception:
        logger.warning("Failed to close PR #%d", pr_number, exc_info=True)


async def cleanup_branch(
    client: GitHubClient,
    repo: RepositoryConfig,
    branch_name: str,
) -> None:
    """Delete a remote branch (best-effort)."""
    try:
        owner = repo.owner
        repo_name = repo.repo
        await client._github.rest.git.async_delete_ref(
            owner=owner,
            repo=repo_name,
            ref=f"heads/{branch_name}",
        )
        logger.info("Deleted branch %s", branch_name)
    except Exception:
        logger.warning("Failed to delete branch %s", branch_name, exc_info=True)


def get_current_timestamp() -> datetime:
    """Get current UTC timestamp for filtering comments."""
    return datetime.now(UTC)
