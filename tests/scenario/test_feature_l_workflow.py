"""Scenario test: Feature-L workflow (real GitHub API + real Claude SDK).

Flow: Issue → TYPE_DETECTION → HEARING → SPLIT_PROPOSAL → 👍
     → SPLIT_EXECUTE → DONE
"""

from __future__ import annotations

import logging

import pytest

from ai_agent_orchestrator.models import EventType, Phase, PollEvent, TaskRequest
from ai_agent_orchestrator.orchestrator.task_queue import Priority

from .helpers import (
    add_thumbsup_to_latest_bot_comment,
    create_test_issue,
    get_current_timestamp,
    wait_for_bot_comment,
)
from .quality import (
    assert_done_quality,
    assert_hearing_quality,
    assert_split_proposal_quality,
    assert_type_detection_quality,
)

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.scenario, pytest.mark.slow]

FEATURE_L_TITLE = "[Feature] Implement dark mode across the application"
FEATURE_L_BODY = """\
## Feature Request

### 概要
アプリケーション全体にダークモード対応を実装したい。
現在のライトモードのみの UI を、ユーザーの好みに応じてダーク/ライトを切り替えられるようにする。

### 要件
1. システムの設定に応じた自動切り替え (`prefers-color-scheme`)
2. ユーザーが手動で切り替えるトグルボタン
3. 選択状態を LocalStorage に保存
4. 全コンポーネント（UserCard, ProfileEditForm, NotificationSettingsForm 等）の対応
5. CSS 変数を使ったテーマ管理
6. アニメーション付きのスムーズな切り替え

### 技術的な補足
- CSS Custom Properties (CSS変数) で色を管理
- `ThemeProvider` コンテキストで状態管理
- 既存の `.module.css` ファイル全てにダークモード変数を適用
- テスト: テーマ切り替えの動作確認テスト

### 影響範囲
これは大規模な変更で、以下の全ファイルに影響する:
- `src/components/*.tsx` — 全コンポーネント
- `src/components/*.module.css` — 全スタイル
- `app/layout.tsx` — ThemeProvider の追加
- 新規: `src/hooks/useTheme.ts`
- 新規: `src/components/ThemeToggle.tsx`
- 新規: `src/styles/themes.css`
"""

# User reply to hearing questions
HEARING_REPLY_L = """\
ダークモードの追加情報:

1. デザインシステムは特になく、CSS Modules を直接使っています
2. カラーパレットはまだ定義されていないので、一般的なダーク/ライトカラーで OK です
3. 優先度は全コンポーネントのスタイル対応が一番高い
4. 段階的にリリースして構いません。まずは基盤(ThemeProvider + CSS変数)を作り、
   その後各コンポーネントを順次対応する形がよいです
5. テストは各コンポーネントのスナップショットテストで十分です
"""


class TestFeatureLWorkflow:
    """Feature-L ワークフロー: 実 GitHub API + 実 Claude SDK のフルフロー."""

    async def test_feature_l_full_workflow(
        self,
        github_client,
        repo_config,
        state_machine,
        task_queue,
        event_router,
        phase_executors,
        cleanup_tracker,
    ):
        """Feature-L 正常系: Issue → HEARING → SPLIT_PROPOSAL → 👍 → SPLIT_EXECUTE → DONE."""
        quality_results = []

        # ---------------------------------------------------------------
        # 1. Create Issue
        # ---------------------------------------------------------------
        timestamp = get_current_timestamp()
        issue = await create_test_issue(
            github_client,
            repo_config,
            FEATURE_L_TITLE,
            FEATURE_L_BODY,
        )
        issue_number = issue.number
        cleanup_tracker.track_issue(issue_number)
        logger.info("=== Feature-L workflow started: issue #%d ===", issue_number)

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
        qr = assert_type_detection_quality(issue_type, "feature-l", bot_comment)
        quality_results.append(qr)
        logger.info("TYPE_DETECTION quality: %s", qr)

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
            await github_client.create_comment(repo_config, issue_number, HEARING_REPLY_L)
            logger.info("Posted hearing reply")

            # Route the comment event
            reply_comment_data = type(
                "Comment",
                (),
                {
                    "id": 0,
                    "body": HEARING_REPLY_L,
                    "issue_url": f"https://api.github.com/repos/{repo_config.owner}/{repo_config.repo}/issues/{issue_number}",
                },
            )()
            comment_event = PollEvent(
                type=EventType.ISSUE_COMMENT,
                repo=repo_config,
                comment=reply_comment_data,
            )
            await event_router.route(comment_event)

            # Re-execute hearing
            hearing_request2 = TaskRequest(
                issue_number=issue_number,
                repo=repo_config,
                phase=Phase.HEARING.value,
                priority=Priority.NORMAL,
                extra={"comment": HEARING_REPLY_L},
            )
            await phase_executors["hearing"].execute(hearing_request2)

        current_phase = state_machine.get_phase(issue_number)
        logger.info("After HEARING (final): phase=%s", current_phase)

        # Feature-L should go to SPLIT_PROPOSAL
        assert current_phase == Phase.SPLIT_PROPOSAL, (
            f"Expected SPLIT_PROPOSAL after hearing for feature-l, got {current_phase}"
        )

        # ---------------------------------------------------------------
        # 4. SPLIT_PROPOSAL
        # ---------------------------------------------------------------
        split_timestamp = get_current_timestamp()
        split_request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.SPLIT_PROPOSAL.value,
            priority=Priority.NORMAL,
        )
        await phase_executors["split_proposal"].execute(split_request)

        # Should stay in SPLIT_PROPOSAL (waiting for approval)
        assert state_machine.get_phase(issue_number) == Phase.SPLIT_PROPOSAL

        # Quality: split proposal comment
        split_comment = await wait_for_bot_comment(
            github_client,
            repo_config,
            issue_number,
            since=split_timestamp,
        )
        qr = assert_split_proposal_quality(split_comment)
        quality_results.append(qr)
        logger.info("SPLIT_PROPOSAL quality: %s", qr)

        # ---------------------------------------------------------------
        # 5. 👍 approve → SPLIT_EXECUTE
        # ---------------------------------------------------------------
        comment_id = await add_thumbsup_to_latest_bot_comment(
            github_client,
            repo_config,
            issue_number,
        )
        logger.info("Added thumbsup to split proposal comment %s", comment_id)

        approve_event = PollEvent(
            type=EventType.SPLIT_APPROVED,
            repo=repo_config,
            issue=issue,
        )
        await event_router.route(approve_event)
        assert state_machine.get_phase(issue_number) == Phase.SPLIT_EXECUTE

        # ---------------------------------------------------------------
        # 6. SPLIT_EXECUTE → DONE
        # ---------------------------------------------------------------
        execute_request = TaskRequest(
            issue_number=issue_number,
            repo=repo_config,
            phase=Phase.SPLIT_EXECUTE.value,
            priority=Priority.NORMAL,
        )
        await phase_executors["split_execute"].execute(execute_request)

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
        # 7. Quality: DONE
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

        # Check child issues were created
        child_comments = [
            c
            for c in comments
            if "子issue" in (getattr(c, "body", "") or "").lower()
            or "child" in (getattr(c, "body", "") or "").lower()
            or "作成" in (getattr(c, "body", "") or "")
        ]
        if child_comments:
            logger.info("Child issues appear to have been created")
        else:
            logger.warning("No child issue creation comments found")

        # Cleanup: close any child issues that were created
        try:
            child_issues = await github_client.get_issues_with_label(
                repo_config,
                "ai-agent",
                state="open",
            )
            for child in child_issues:
                child_number = getattr(child, "number", None)
                child_title = getattr(child, "title", "") or ""
                if child_number and child_number != issue_number and f"(#{issue_number}" in child_title:
                    cleanup_tracker.track_issue(child_number)
                    logger.info("Tracking child issue #%d for cleanup", child_number)
        except Exception:
            logger.warning("Failed to find child issues for cleanup", exc_info=True)

        # ---------------------------------------------------------------
        # Final report
        # ---------------------------------------------------------------
        logger.info("=" * 60)
        logger.info("FEATURE-L WORKFLOW QUALITY REPORT")
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
