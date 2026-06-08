"""Scenario test: Feature-M workflow (real GitHub API + real Claude SDK).

Flow: Issue → TYPE_DETECTION → HEARING → DESIGN → DESIGN_REVIEW → approve
     → IMPLEMENT → CI → IMPL_REVIEW → PR merge → DONE
"""

from __future__ import annotations

import logging

import pytest

from ai_agent_orchestrator.models import EventType, Phase, PollEvent, TaskRequest
from ai_agent_orchestrator.orchestrator.task_queue import Priority

from .helpers import (
    approve_pr,
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
    assert_design_quality,
    assert_done_quality,
    assert_hearing_quality,
    assert_implementation_quality,
    assert_pr_quality,
    assert_type_detection_quality,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.scenario, pytest.mark.slow]

FEATURE_M_TITLE = "[Feature] Add search functionality to user list page"
FEATURE_M_BODY = """\
## Feature Request

### 概要
ユーザー一覧ページ (`/users`) にリアルタイム検索機能を追加したい。

### 要件
1. テキスト入力でユーザーを名前またはメールアドレスで検索できる
2. 入力に応じてリストがリアルタイムにフィルタリングされる（デバウンス 300ms）
3. 検索結果が 0 件の場合、「該当するユーザーが見つかりません」と表示
4. 検索をクリアするボタンがある

### 技術的な補足
- クライアントサイドフィルタリングで OK（API 呼び出し不要）
- 既存の `UserCard` コンポーネントを再利用
- アクセシビリティ: 検索入力に `aria-label` を付与

### 該当ファイル
- 新規: `src/components/UserSearchBar.tsx`
- 新規: `src/hooks/useUserSearch.ts`
- 修正: ユーザー一覧ページ（現在は存在しないため新規作成の可能性あり）
"""

# User reply to hearing questions
HEARING_REPLY = """\
追加の情報をお伝えします：

1. 検索対象は `name` と `email` フィールドの両方です
2. 大文字小文字は区別しない（case-insensitive）
3. 部分一致検索でお願いします
4. ユーザーデータは既存の `useUser` フックで取得可能です
5. レスポンシブ対応は不要です（デスクトップのみ）
"""


class TestFeatureMWorkflow:
    """Feature-M ワークフロー: 実 GitHub API + 実 Claude SDK のフルフロー."""

    async def test_feature_m_full_workflow(
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
        """Feature-M 正常系: Issue → ... → DESIGN → approve → IMPLEMENT → merge → DONE."""
        quality_results = []

        # ---------------------------------------------------------------
        # 1. Create Issue
        # ---------------------------------------------------------------
        timestamp = get_current_timestamp()
        issue = await create_test_issue(
            github_client,
            repo_config,
            FEATURE_M_TITLE,
            FEATURE_M_BODY,
        )
        issue_number = issue.number
        cleanup_tracker.track_issue(issue_number)
        cleanup_tracker.track_branch(f"feature/issue-{issue_number}")
        cleanup_tracker.track_branch(f"docs/issue-{issue_number}")
        logger.info("=== Feature-M workflow started: issue #%d ===", issue_number)

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

        request = await task_queue.dequeue()
        await phase_executors["type_detection"].execute(request)

        issue_type = state_machine.get_issue_type(issue_number)
        bot_comment = await wait_for_bot_comment(
            github_client,
            repo_config,
            issue_number,
            since=timestamp,
        )
        qr = assert_type_detection_quality(issue_type, "feature-m", bot_comment)
        quality_results.append(qr)
        logger.info("TYPE_DETECTION quality: %s", qr)

        # Should be in HEARING now
        current_phase = state_machine.get_phase(issue_number)
        assert current_phase == Phase.HEARING, f"Expected HEARING, got {current_phase}"

        # ---------------------------------------------------------------
        # 3. HEARING
        # ---------------------------------------------------------------
        hearing_timestamp = get_current_timestamp()
        hearing_request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.HEARING.value,
            priority=Priority.NORMAL,
        )
        await phase_executors["hearing"].execute(hearing_request)

        current_phase = state_machine.get_phase(issue_number)
        logger.info("After HEARING: phase=%s", current_phase)

        # If HEARING_WAIT, simulate user reply
        if current_phase == Phase.HEARING_WAIT:
            hearing_comment = await wait_for_bot_comment(
                github_client,
                repo_config,
                issue_number,
                since=hearing_timestamp,
            )
            qr = assert_hearing_quality(hearing_comment)
            quality_results.append(qr)
            logger.info("HEARING quality: %s", qr)

            # Post user reply
            await github_client.create_comment(repo_config, issue_number, HEARING_REPLY)
            logger.info("Posted hearing reply")

            # Route the comment event to resume hearing
            reply_comment_data = type(
                "Comment",
                (),
                {
                    "id": 0,
                    "body": HEARING_REPLY,
                    "issue_url": f"https://api.github.com/repos/{repo_config.owner}/{repo_config.repo}/issues/{issue_number}",
                },
            )()
            comment_event = PollEvent(
                type=EventType.ISSUE_COMMENT,
                repo=repo_config,
                comment=reply_comment_data,
            )
            await event_router.route(comment_event)

            # Re-execute hearing with the reply
            hearing_request2 = TaskRequest(
                issue_number=issue_number,
                repo=repo_config,
                phase=Phase.HEARING.value,
                priority=Priority.NORMAL,
                extra={"comment": HEARING_REPLY},
            )
            await phase_executors["hearing"].execute(hearing_request2)

        current_phase = state_machine.get_phase(issue_number)
        logger.info("After HEARING (final): phase=%s", current_phase)

        # Should transition to DESIGN (possibly via split-proposal if misclassified)
        assert current_phase in (Phase.DESIGN, Phase.SPLIT_PROPOSAL), (
            f"Expected DESIGN or SPLIT_PROPOSAL after hearing, got {current_phase}"
        )

        # ---------------------------------------------------------------
        # 4. DESIGN → DESIGN_REVIEW
        # ---------------------------------------------------------------
        if current_phase == Phase.DESIGN:
            design_request = TaskRequest(
                issue_number=issue_number,
                repo=repo_config,
                phase=Phase.DESIGN.value,
                priority=Priority.NORMAL,
            )
            await phase_executors["design"].execute(design_request)

            assert state_machine.get_phase(issue_number) == Phase.DESIGN_REVIEW

            # Quality: design PR
            state = state_machine.get_state(issue_number)
            design_pr_number = state.design_pr_number or state.pr_number
            if design_pr_number:
                cleanup_tracker.track_pr(design_pr_number)
                pr = await wait_for_pr(github_client, repo_config, issue_number)
                worktree_path = str(await workspace_manager.create_worktree(repo_config, issue_number))
                diff_files = await get_branch_diff_files(worktree_path)
                qr = assert_design_quality(pr, issue_number, diff_files)
                quality_results.append(qr)
                logger.info("DESIGN quality: %s", qr)

            # ---------------------------------------------------------------
            # 5. DESIGN_REVIEW → approve → IMPLEMENT (PLANNING フェーズ廃止)
            # ---------------------------------------------------------------
            if design_pr_number:
                await approve_pr(github_client, repo_config, design_pr_number)

            approve_event = PollEvent(
                type=EventType.DESIGN_PR_APPROVED,
                repo=repo_config,
                issue=issue,
            )
            await event_router.route(approve_event)
            assert state_machine.get_phase(issue_number) == Phase.IMPLEMENT

            # ---------------------------------------------------------------
            # 6. IMPLEMENT → IMPL_REVIEW
            # ---------------------------------------------------------------
            impl_request = TaskRequest(
                issue_number=issue_number,
                repo=repo_config,
                phase=Phase.IMPLEMENT.value,
                priority=Priority.NORMAL,
            )
            await phase_executors["implement"].execute(impl_request)
            assert state_machine.get_phase(issue_number) == Phase.IMPL_REVIEW

            # Get impl PR
            state = state_machine.get_state(issue_number)
            impl_pr_number = state.pr_number
            assert impl_pr_number is not None, "Implementation PR not created"
            if impl_pr_number != design_pr_number:
                cleanup_tracker.track_pr(impl_pr_number)

            # Quality: implementation
            worktree_path = str(await workspace_manager.create_worktree(repo_config, issue_number))
            build_rc, _, build_stderr = await run_npm_in_worktree(worktree_path, "build")
            test_rc, _, test_stderr = await run_npm_in_worktree(worktree_path, "test -- --passWithNoTests")
            diff_files = await get_branch_diff_files(worktree_path)

            qr = assert_implementation_quality(
                build_rc,
                build_stderr,
                test_rc,
                test_stderr,
                diff_files,
            )
            quality_results.append(qr)
            logger.info("IMPLEMENTATION quality: %s", qr)

            # Quality: PR
            impl_pr = await wait_for_pr(github_client, repo_config, issue_number)
            qr = assert_pr_quality(impl_pr, issue_number)
            quality_results.append(qr)
            logger.info("PR quality: %s", qr)

            # ---------------------------------------------------------------
            # 8. CI → IMPL_REVIEW
            # ---------------------------------------------------------------
            branch_name = f"feature/issue-{issue_number}"
            try:
                ci_status = await wait_for_ci_status(
                    github_client,
                    repo_config,
                    branch_name,
                    timeout_sec=600,
                )
                ci_event = PollEvent(
                    type=EventType.CI_RESULT,
                    repo=repo_config,
                    issue=issue,
                    extra={"ci_status": ci_status},
                )
                await event_router.route(ci_event)
            except TimeoutError:
                logger.warning("CI timeout — staying in IMPL_REVIEW")

            # ---------------------------------------------------------------
            # 9. Merge → DONE
            # ---------------------------------------------------------------
            await merge_pr(github_client, repo_config, impl_pr_number)

            merge_event = PollEvent(
                type=EventType.IMPL_PR_MERGED,
                repo=repo_config,
                issue=issue,
            )
            await event_router.route(merge_event)
            assert state_machine.get_phase(issue_number) == Phase.DONE

            # Execute DONE
            done_request = TaskRequest(
                issue_number=issue_number,
                repo=repo_config,
                phase=Phase.DONE.value,
                priority=Priority.NORMAL,
            )
            await phase_executors["done"].execute(done_request)

        # ---------------------------------------------------------------
        # 10. Quality: DONE
        # ---------------------------------------------------------------
        final_issue = await github_client.get_issue(repo_config, issue_number)
        issue_state = getattr(final_issue, "state", "")

        comments = await github_client.list_comments(repo_config, issue_number)
        has_summary = any(len(getattr(c, "body", "") or "") > 20 for c in comments[-3:])

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
        logger.info("FEATURE-M WORKFLOW QUALITY REPORT")
        logger.info("=" * 60)
        all_passed = True
        for result in quality_results:
            logger.info("%s", result)
            if not result.passed:
                all_passed = False
        logger.info("=" * 60)
        logger.info("Overall: %s", "PASS" if all_passed else "FAIL")

        failed = [r for r in quality_results if not r.passed]
        if failed:
            details = "\n".join(str(r) for r in failed)
            pytest.fail(f"Quality checks failed:\n{details}")
