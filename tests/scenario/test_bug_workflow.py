"""Scenario test: Bug workflow (real GitHub API + real Claude SDK).

Flow: Issue → TYPE_DETECTION → ANALYSIS → PLAN_REVIEW → 👍 → FIX
     → CI → IMPL_REVIEW → PR merge → DONE
"""

from __future__ import annotations

import logging

import pytest

from ai_agent_orchestrator.models import EventType, Phase, PollEvent, TaskRequest
from ai_agent_orchestrator.orchestrator.task_queue import Priority

from .helpers import (
    add_thumbsup_to_latest_bot_comment,
    create_test_issue,
    get_branch_diff_files,
    get_current_timestamp,
    merge_pr,
    run_npm_in_worktree,
    wait_for_bot_comment,
    wait_for_ci_status,
    wait_for_pr,
)
from .quality import (
    assert_analysis_quality,
    assert_done_quality,
    assert_implementation_quality,
    assert_pr_quality,
    assert_type_detection_quality,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.scenario, pytest.mark.slow]

BUG_TITLE = "[Bug] UserProfileView component throws TypeError when user is null"
BUG_BODY = """\
## Bug Report

### 概要
`UserProfileView` コンポーネントに `user` prop が `null` または `undefined` の場合、
`TypeError: Cannot read properties of null (reading 'name')` が発生します。

### 再現手順
1. `/users/999` のように存在しないユーザーIDでページにアクセスする
2. コンソールに TypeError が表示される
3. ページが白い画面になる

### 期待する動作
- ユーザーが見つからない場合、「ユーザーが見つかりません」というメッセージを表示する
- エラーバウンダリでクラッシュを防ぐ

### 環境
- Next.js 14
- React 18
- TypeScript 5

### 該当ファイル
- `src/components/UserProfileView.tsx`
- `app/users/[id]/page.tsx`
"""


class TestBugWorkflow:
    """Bug ワークフロー: 実 GitHub API + 実 Claude SDK のフルフロー."""

    async def test_bug_full_workflow(
        self,
        github_client,
        repo_config,
        state_machine,
        task_queue,
        event_router,
        phase_executors,
        workspace_manager,
        cleanup_tracker,
    ):
        """Bug 正常系: Issue → TYPE_DETECTION → ANALYSIS → 👍 → FIX → merge → DONE."""
        quality_results = []

        # ---------------------------------------------------------------
        # 1. Create Issue
        # ---------------------------------------------------------------
        timestamp = get_current_timestamp()
        issue = await create_test_issue(
            github_client,
            repo_config,
            BUG_TITLE,
            BUG_BODY,
        )
        issue_number = issue.number
        cleanup_tracker.track_issue(issue_number)
        cleanup_tracker.track_branch(f"feature/issue-{issue_number}")
        logger.info("=== Bug workflow started: issue #%d ===", issue_number)

        # ---------------------------------------------------------------
        # 2. TYPE_DETECTION
        # ---------------------------------------------------------------
        event = PollEvent(
            type=EventType.NEW_ISSUE,
            repo=repo_config,
            issue=issue,
        )
        await event_router.route(event)
        assert state_machine.get_phase(issue_number) == Phase.TYPE_DETECTION

        # Execute type detection
        request = await task_queue.dequeue()
        executor = phase_executors["type_detection"]
        await executor.execute(request)

        # Quality: correct type classification
        issue_type = state_machine.get_issue_type(issue_number)
        bot_comment = await wait_for_bot_comment(
            github_client,
            repo_config,
            issue_number,
            since=timestamp,
        )
        qr = assert_type_detection_quality(issue_type, "bug", bot_comment)
        quality_results.append(qr)
        logger.info("TYPE_DETECTION quality: %s", qr)

        assert state_machine.get_phase(issue_number) == Phase.ANALYSIS

        # ---------------------------------------------------------------
        # 3. ANALYSIS → PLAN_REVIEW
        # ---------------------------------------------------------------
        analysis_timestamp = get_current_timestamp()
        request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.ANALYSIS.value,
            priority=Priority.NORMAL,
        )
        executor = phase_executors["analysis"]
        await executor.execute(request)

        assert state_machine.get_phase(issue_number) == Phase.PLAN_REVIEW

        # Quality: analysis comment
        analysis_comment = await wait_for_bot_comment(
            github_client,
            repo_config,
            issue_number,
            since=analysis_timestamp,
        )
        qr = assert_analysis_quality(analysis_comment)
        quality_results.append(qr)
        logger.info("ANALYSIS quality: %s", qr)

        # ---------------------------------------------------------------
        # 4. PLAN_REVIEW → 👍 → FIX
        # ---------------------------------------------------------------
        comment_id = await add_thumbsup_to_latest_bot_comment(
            github_client,
            repo_config,
            issue_number,
        )
        logger.info("Added thumbsup to comment %s", comment_id)

        # Route the reaction event
        reaction_event = PollEvent(
            type=EventType.PLAN_REACTION_ADDED,
            repo=repo_config,
            issue=issue,
        )
        await event_router.route(reaction_event)
        assert state_machine.get_phase(issue_number) == Phase.FIX

        # ---------------------------------------------------------------
        # 5. FIX → IMPL_REVIEW
        # ---------------------------------------------------------------
        fix_request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.FIX.value,
            priority=Priority.NORMAL,
        )
        executor = phase_executors["fix"]
        await executor.execute(fix_request)

        assert state_machine.get_phase(issue_number) == Phase.IMPL_REVIEW

        # Get PR info
        state = state_machine.get_state(issue_number)
        pr_number = state.pr_number
        assert pr_number is not None, "PR was not created during FIX phase"
        cleanup_tracker.track_pr(pr_number)

        # Quality: implementation
        worktree_path = str(await workspace_manager.create_worktree(repo_config, issue_number))
        build_rc, _, build_stderr = await run_npm_in_worktree(worktree_path, "build")
        test_rc, _, test_stderr = await run_npm_in_worktree(worktree_path, "test -- --passWithNoTests")
        diff_files = await get_branch_diff_files(worktree_path)

        qr = assert_implementation_quality(build_rc, build_stderr, test_rc, test_stderr, diff_files)
        quality_results.append(qr)
        logger.info("IMPLEMENTATION quality: %s", qr)

        # Quality: PR
        pr = await wait_for_pr(github_client, repo_config, issue_number)
        qr = assert_pr_quality(pr, issue_number)
        quality_results.append(qr)
        logger.info("PR quality: %s", qr)

        # ---------------------------------------------------------------
        # 6. CI → wait for checks
        # ---------------------------------------------------------------
        branch_name = f"feature/issue-{issue_number}"
        try:
            ci_status = await wait_for_ci_status(
                github_client,
                repo_config,
                branch_name,
                timeout_sec=600,
            )
            logger.info("CI status: %s", ci_status)

            ci_event = PollEvent(
                type=EventType.CI_RESULT,
                repo=repo_config,
                issue=issue,
                extra={"ci_status": ci_status},
            )
            await event_router.route(ci_event)
        except TimeoutError:
            logger.warning("CI timeout — skipping CI event, staying in IMPL_REVIEW")

        # ---------------------------------------------------------------
        # 7. IMPL_REVIEW → merge → DONE
        # ---------------------------------------------------------------
        await merge_pr(github_client, repo_config, pr_number)

        merge_event = PollEvent(
            type=EventType.IMPL_PR_MERGED,
            repo=repo_config,
            issue=issue,
        )
        await event_router.route(merge_event)
        assert state_machine.get_phase(issue_number) == Phase.DONE

        # Execute DONE phase (close issue, cleanup)
        done_request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.DONE.value,
            priority=Priority.NORMAL,
        )
        executor = phase_executors["done"]
        await executor.execute(done_request)

        # ---------------------------------------------------------------
        # 8. Quality: DONE
        # ---------------------------------------------------------------
        final_issue = await github_client.get_issue(repo_config, issue_number)
        issue_state = getattr(final_issue, "state", "")

        # Check for summary comment
        comments = await github_client.list_comments(repo_config, issue_number)
        has_summary = any(
            len(getattr(c, "body", "") or "") > 20
            for c in comments[-3:]  # Check last few comments
        )

        # Check for done label
        labels = getattr(final_issue, "labels", []) or []
        has_done_label = any(
            (getattr(lbl, "name", "") if hasattr(lbl, "name") else str(lbl)) == "phase:done" for lbl in labels
        )

        qr = assert_done_quality(issue_state, has_summary, has_done_label)
        quality_results.append(qr)
        logger.info("DONE quality: %s", qr)

        # ---------------------------------------------------------------
        # Final report
        # ---------------------------------------------------------------
        logger.info("=" * 60)
        logger.info("BUG WORKFLOW QUALITY REPORT")
        logger.info("=" * 60)
        all_passed = True
        for result in quality_results:
            logger.info("%s", result)
            if not result.passed:
                all_passed = False
        logger.info("=" * 60)
        logger.info("Overall: %s", "PASS" if all_passed else "FAIL")

        # Assert all quality checks passed
        failed = [r for r in quality_results if not r.passed]
        if failed:
            details = "\n".join(str(r) for r in failed)
            pytest.fail(f"Quality checks failed:\n{details}")
