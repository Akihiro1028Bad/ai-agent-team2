# Hearing Wait Phase + Branch Prefix Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the hearing phase loop (questions fired before user replies) and the branch_prefix mismatch causing PR lookup failures.

**Architecture:** Add `HEARING_WAIT` phase as a waiting state after hearing questions are posted. Fix branch_prefix inconsistency by standardizing on `feature` prefix and adding fallback PR search.

**Tech Stack:** Python 3.13+, pytest-asyncio, python-statemachine

**Spec:** `docs/superpowers/specs/2026-03-31-hearing-wait-phase-design.md`

---

### Task 1: Add HEARING_WAIT to Phase enum and TRANSITION_MAP

**Files:**
- Modify: `src/ai_agent_orchestrator/models.py:48` (Phase enum)
- Modify: `src/ai_agent_orchestrator/orchestrator/state_machine.py:65-130` (TRANSITION_MAP)
- Modify: `src/ai_agent_orchestrator/orchestrator/state_machine.py:138-244` (IssueWorkflow states & transitions)
- Test: `tests/unit/test_state_machine.py`

- [ ] **Step 1: Write failing test for HEARING_WAIT transitions**

In `tests/unit/test_state_machine.py`, add:

```python
class TestHearingWaitWorkflow:
    """hearing-wait フェーズの遷移テスト."""

    @pytest.fixture()
    def sm(self, mock_persistence, mock_tracker):
        return StateMachineManager(persistence=mock_persistence, tracker=mock_tracker)

    async def test_hearing_to_hearing_wait(self, sm):
        sm.register_issue(1, "owner/repo")
        sm.set_issue_type(1, "feature-m")
        await sm.transition(1, Phase.HEARING)
        await sm.transition(1, Phase.HEARING_WAIT)
        assert sm.get_phase(1) == Phase.HEARING_WAIT

    async def test_hearing_wait_to_hearing(self, sm):
        sm.register_issue(1, "owner/repo")
        sm.set_issue_type(1, "feature-m")
        await sm.transition(1, Phase.HEARING)
        await sm.transition(1, Phase.HEARING_WAIT)
        await sm.transition(1, Phase.HEARING)
        assert sm.get_phase(1) == Phase.HEARING

    async def test_hearing_wait_to_suspended(self, sm):
        sm.register_issue(1, "owner/repo")
        sm.set_issue_type(1, "feature-m")
        await sm.transition(1, Phase.HEARING)
        await sm.transition(1, Phase.HEARING_WAIT)
        await sm.transition(1, Phase.SUSPENDED)
        assert sm.get_phase(1) == Phase.SUSPENDED
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_state_machine.py::TestHearingWaitWorkflow -v`
Expected: FAIL — `Phase` has no attribute `HEARING_WAIT`

- [ ] **Step 3: Add HEARING_WAIT to Phase enum**

In `src/ai_agent_orchestrator/models.py`, after line 48 (`HEARING = "hearing"`):

```python
    HEARING_WAIT = "hearing-wait"
```

- [ ] **Step 4: Add transitions to TRANSITION_MAP and IssueWorkflow**

In `src/ai_agent_orchestrator/orchestrator/state_machine.py`:

Add to `TRANSITION_MAP` (after line 88, the HEARING section):

```python
    (Phase.HEARING, Phase.HEARING_WAIT): "hearing_to_hearing_wait",
    (Phase.HEARING_WAIT, Phase.HEARING): "hearing_wait_to_hearing",
    (Phase.HEARING_WAIT, Phase.SUSPENDED): "hearing_wait_to_suspended",
```

Add to `IssueWorkflow` class (after line 194, `hearing_to_suspended`):

```python
    # --- HEARING_WAIT (waiting for user reply) ---
    hearing_wait = State("Hearing wait")
    hearing_to_hearing_wait = hearing.to(hearing_wait)
    hearing_wait_to_hearing = hearing_wait.to(hearing)
    hearing_wait_to_suspended = hearing_wait.to(suspended)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_state_machine.py::TestHearingWaitWorkflow -v`
Expected: PASS

- [ ] **Step 6: Run full test suite to check for regressions**

Run: `uv run pytest tests/unit/test_state_machine.py -v`
Expected: All existing tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/ai_agent_orchestrator/models.py src/ai_agent_orchestrator/orchestrator/state_machine.py tests/unit/test_state_machine.py
git commit -m "feat: add HEARING_WAIT phase to state machine"
```

---

### Task 2: Update HearingExecutor to transition to hearing-wait

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/hearing.py:103-116`
- Test: `tests/unit/test_phases.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_phases.py`, add a test for hearing-wait transition. Use existing fixtures (`mock_runner`, `mock_github`, `mock_notifier`, `mock_tracker`, `mock_workspace`, `mock_context`, `mock_sm`):

```python
class TestHearingWaitTransition:
    """hearing 質問投稿後に hearing-wait へ遷移するテスト."""

    async def test_hearing_question_transitions_to_hearing_wait(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """質問投稿後に hearing-wait へ遷移する."""
        from ai_agent_orchestrator.models import AgentResult
        from ai_agent_orchestrator.phases.hearing import HearingExecutor

        mock_runner.run = AsyncMock(
            return_value=AgentResult(
                session_id="sess-001",
                output="以下の点を確認させてください:\n1. 対象ユーザーは？",
                tool_uses=[],
                cost_usd=0.1,
                duration_sec=10.0,
            )
        )
        mock_sm.get_state.return_value = MagicMock(session_id=None)
        mock_sm.get_issue_type.return_value = "feature-m"

        executor = HearingExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("hearing", issue_number=42)
        result = AgentResult(
            session_id="sess-001",
            output="以下の点を確認させてください:\n1. 対象ユーザーは？",
            tool_uses=[],
            cost_usd=0.1,
            duration_sec=10.0,
        )
        await executor.process_result(request, result)

        # hearing-wait へ遷移したことを確認
        mock_sm.transition.assert_called_once_with(42, "hearing-wait")
        # ラベルが hearing-wait に更新されたことを確認
        mock_github.replace_phase_label.assert_called_once()
        label_args = mock_github.replace_phase_label.call_args
        assert "phase:hearing-wait" in str(label_args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phases.py::TestHearingWaitTransition -v`
Expected: FAIL — `transition` called with `"hearing"` or not at all (current code doesn't transition)

- [ ] **Step 3: Update HearingExecutor.process_result**

In `src/ai_agent_orchestrator/phases/hearing.py`, replace lines 103-116 (the `else` block):

```python
        else:
            # 質問を Issue コメントとして投稿
            comment_body = (
                result.output.strip()
                if result.output.strip()
                else ("ヒアリングを実行しましたが、出力が空でした。再実行が必要です。")
            )
            await client.create_comment(request.repo, request.issue_number, comment_body)
            # hearing-wait へ遷移（ユーザー回答待ち）
            await client.replace_phase_label(request.repo, request.issue_number, "phase:hearing-wait")
            await self._sm.transition(request.issue_number, "hearing-wait")
            await self._notifier.notify(
                f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
                metadata={
                    "issue": request.issue_number,
                },
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phases.py::TestHearingWaitTransition -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_agent_orchestrator/phases/hearing.py tests/unit/test_phases.py
git commit -m "feat: hearing transitions to hearing-wait after posting question"
```

---

### Task 3: Update GitHubPoller to watch hearing-wait

**Files:**
- Modify: `src/ai_agent_orchestrator/poller/github_poller.py:210,234`
- Test: `tests/unit/test_github_poller.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_github_poller.py`, add/update tests in `TestDetectHearingReplies`:

```python
    async def test_detect_hearing_replies_watches_hearing_wait_label(self):
        """hearing-wait ラベルの Issue を監視する."""
        client = _make_client()
        comment = _make_comment(101, "回答です", "User", issue_url="https://api.github.com/repos/o/r/issues/42")
        issue = _make_issue(42, labels=["ai-agent", "phase:hearing-wait"])
        client.get_issues_with_label = AsyncMock(side_effect=lambda repo, labels, **kw: [issue] if "hearing-wait" in labels else [])
        client.list_comments = AsyncMock(return_value=[comment])

        repo = _make_repo()
        am = _make_account_manager(client)
        poller = GitHubPoller(account_manager=am, repos=[repo], interval_sec=60)

        result = await poller._detect_hearing_replies(client, repo, None)
        assert len(result) == 1

        # phase:hearing (not hearing-wait) の Issue は監視しない
        client.get_issues_with_label.assert_called()
        call_labels = client.get_issues_with_label.call_args[0][1]
        assert "hearing-wait" in call_labels
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_github_poller.py::TestDetectHearingReplies::test_detect_hearing_replies_watches_hearing_wait_label -v`
Expected: FAIL — current code uses `phase:hearing` not `phase:hearing-wait`

- [ ] **Step 3: Update GitHubPoller**

In `src/ai_agent_orchestrator/poller/github_poller.py`:

Line 210, in `_detect_hearing_replies()`:
```python
        # Before
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
        # After
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
```

Line 234, in `_detect_hearing_timeouts()`:
```python
        # Before
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
        # After
        issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_github_poller.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/ai_agent_orchestrator/poller/github_poller.py tests/unit/test_github_poller.py
git commit -m "fix: poller watches hearing-wait instead of hearing for replies/timeouts"
```

---

### Task 4: Update EventRouter to handle HEARING_WAIT

**Files:**
- Modify: `src/ai_agent_orchestrator/poller/event_router.py:199-228`
- Test: `tests/unit/test_event_router.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_event_router.py`, add:

```python
class TestEventRouterHearingWait:
    """hearing-wait フェーズのイベントルーティングテスト."""

    @pytest.fixture()
    def mock_sm(self):
        sm = MagicMock()
        sm.transition = AsyncMock()
        sm.register_issue = MagicMock()
        sm.get_phase = MagicMock(return_value=Phase.HEARING_WAIT)
        sm.get_issue_type = MagicMock(return_value="feature-m")
        sm.set_issue_type = MagicMock()
        sm.get_ci_retry_count = AsyncMock(return_value=0)
        return sm

    @pytest.fixture()
    def mock_tq(self):
        tq = AsyncMock()
        return tq

    @pytest.fixture()
    def router(self, mock_sm, mock_tq):
        return EventRouter(state_machine=mock_sm, task_queue=mock_tq)

    async def test_hearing_reply_from_hearing_wait_transitions_to_hearing(self, router, mock_sm, mock_tq):
        """hearing-wait 中にユーザーコメント → hearing に遷移."""
        event = _make_event(EventType.ISSUE_COMMENT, issue_number=42)
        event.comment = MagicMock()
        event.comment.issue_url = "https://api.github.com/repos/o/r/issues/42"
        event.comment.body = "回答です"

        await router.route(event)

        mock_sm.transition.assert_called_once()
        assert mock_sm.transition.call_args[0][1] == Phase.HEARING
        mock_tq.enqueue.assert_called_once()

    async def test_hearing_reply_during_hearing_enqueues_without_transition(self, router, mock_sm, mock_tq):
        """hearing 実行中にユーザーコメント → 遷移せずエンキューのみ."""
        mock_sm.get_phase.return_value = Phase.HEARING

        event = _make_event(EventType.ISSUE_COMMENT, issue_number=42)
        event.comment = MagicMock()
        event.comment.issue_url = "https://api.github.com/repos/o/r/issues/42"
        event.comment.body = "回答です"

        await router.route(event)

        mock_sm.transition.assert_not_called()
        mock_tq.enqueue.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_event_router.py::TestEventRouterHearingWait -v`
Expected: FAIL — current code doesn't handle HEARING_WAIT

- [ ] **Step 3: Update EventRouter._handle_hearing_reply**

In `src/ai_agent_orchestrator/poller/event_router.py`, replace `_handle_hearing_reply` (lines 199-228):

```python
    async def _handle_hearing_reply(self, event: PollEvent) -> None:
        """ヒアリング回答: HEARING_WAIT → HEARING 遷移して再実行."""
        assert event.comment is not None
        issue_number = int(str(event.comment.issue_url).split("/")[-1])

        # 現在のフェーズを確認
        try:
            current_phase = self._sm.get_phase(issue_number)
        except KeyError:
            logger.warning("Issue #%d is not registered, skipping hearing reply", issue_number)
            return

        if current_phase == Phase.HEARING_WAIT:
            # 回答待ち → hearing に遷移して再実行
            await self._sm.transition(issue_number, Phase.HEARING)
            # ラベル更新
            try:
                client = await self._get_client(event.repo)
                if client:
                    await client.replace_phase_label(event.repo, issue_number, "phase:hearing")
            except Exception:
                logger.warning("Failed to update phase label to hearing for issue #%d", issue_number)
        elif current_phase == Phase.HEARING:
            # AI 実行中にユーザーが回答 → 遷移せずキューイングのみ
            pass
        elif current_phase == Phase.SUSPENDED:
            # SUSPENDED → HEARING に復帰
            await self._sm.transition(issue_number, Phase.HEARING)
            logger.info("Issue #%d resumed from SUSPENDED to HEARING", issue_number)
        else:
            # HEARING/HEARING_WAIT 以外のフェーズなら無視
            logger.info("Issue #%d is in phase %s, ignoring hearing reply", issue_number, current_phase)
            return

        await self._tq.enqueue(
            TaskRequest(
                issue_number=issue_number,
                repo=event.repo,
                phase=Phase.HEARING.value,
                priority=Priority.HIGH,
                extra={"comment": event.comment.body},
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_event_router.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_agent_orchestrator/poller/event_router.py tests/unit/test_event_router.py
git commit -m "feat: EventRouter handles HEARING_WAIT -> HEARING transition on user reply"
```

---

### Task 5: Fix branch_prefix mismatch in hearing.py and design.py

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/hearing.py:34`
- Modify: `src/ai_agent_orchestrator/phases/design.py:33,78`
- Test: `tests/unit/test_phases.py`

- [ ] **Step 1: Write failing test for design PR lookup**

In `tests/unit/test_phases.py`, add:

```python
class TestDesignPrLookup:
    """design フェーズの PR 検索テスト."""

    async def test_ensure_pr_created_finds_feature_branch_pr(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """feature/issue-XX ブランチの PR を正しく検索できる."""
        from ai_agent_orchestrator.phases.design import DesignExecutor

        mock_sm.get_state.return_value = MagicMock(session_id=None, design_pr_number=None)

        # PR が feature/issue-42 ブランチで存在する
        mock_pr = MagicMock()
        mock_pr.number = 99
        mock_github.list_pull_requests = AsyncMock(return_value=[mock_pr])
        mock_github.get_issue = AsyncMock(return_value=MagicMock(title="Test", body="body"))
        mock_github.replace_phase_label = AsyncMock()
        mock_sm.transition = AsyncMock()

        executor = DesignExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("design", issue_number=42)

        # output に PR 番号なし → フォールバック検索で feature/issue-42 を使う
        result = AgentResult(
            session_id="sess-001",
            output="設計書を作成しました。",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=100.0,
        )
        await executor.process_result(request, result)

        # list_pull_requests が feature/issue-42 で検索されたことを確認
        call_args = mock_github.list_pull_requests.call_args
        assert "feature/issue-42" in str(call_args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phases.py::TestDesignPrLookup -v`
Expected: FAIL — current code uses `design/issue-42`

- [ ] **Step 3: Fix hearing.py — remove branch_prefix="design"**

In `src/ai_agent_orchestrator/phases/hearing.py`, line 34:

```python
        # Before
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="design",
        )
        # After
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
        )
```

- [ ] **Step 4: Fix design.py — use feature prefix**

In `src/ai_agent_orchestrator/phases/design.py`:

Line 33, `build_prompt`:
```python
        # Before
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
            branch_prefix="design",
        )
        # After
        worktree = await self._workspace.create_worktree(
            request.repo,
            request.issue_number,
        )
```

Line 78, `process_result`:
```python
        # Before
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="design",
            title_prefix="docs: ",
        )
        # After
        pr_number = await self._ensure_pr_created(
            request,
            result.output,
            branch_prefix="feature",
            title_prefix="docs: ",
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phases.py::TestDesignPrLookup -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/ai_agent_orchestrator/phases/hearing.py src/ai_agent_orchestrator/phases/design.py tests/unit/test_phases.py
git commit -m "fix: standardize branch_prefix to feature for PR lookup"
```

---

### Task 6: Add fallback PR search in _ensure_pr_created

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/base.py:404-425`
- Test: `tests/unit/test_phases.py`

- [ ] **Step 1: Write failing test**

In `tests/unit/test_phases.py`, add:

```python
class TestEnsurePrCreatedFallback:
    """_ensure_pr_created の feature ブランチフォールバック検索テスト."""

    async def test_fallback_to_feature_branch_when_prefix_differs(
        self, mock_runner, mock_github, mock_notifier, mock_tracker, mock_workspace, mock_context, mock_sm
    ):
        """branch_prefix が feature 以外のとき、feature/issue-XX でもフォールバック検索する."""
        from ai_agent_orchestrator.phases.base import PhaseExecutor

        mock_pr = MagicMock()
        mock_pr.number = 55

        # 1回目 (design/issue-42): 見つからない → []
        # 2回目 (feature/issue-42): 見つかる → [mock_pr]
        mock_github.list_pull_requests = AsyncMock(side_effect=[[], [mock_pr]])
        mock_github.get_issue = AsyncMock(return_value=MagicMock(title="Test"))

        # PhaseExecutor は ABC なので具象サブクラスで呼ぶ
        from ai_agent_orchestrator.phases.design import DesignExecutor

        executor = DesignExecutor(
            runner=mock_runner,
            account_manager=mock_github,
            notifier=mock_notifier,
            tracker=mock_tracker,
            workspace=mock_workspace,
            context_engine=mock_context,
            state_machine=mock_sm,
        )

        request = _make_request("design", issue_number=42)
        pr_number = await executor._ensure_pr_created(
            request,
            "no PR number here",
            branch_prefix="design",
            title_prefix="docs: ",
        )
        assert pr_number == 55
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_phases.py::TestEnsurePrCreatedFallback -v`
Expected: FAIL — no fallback search for `feature/issue-XX`

- [ ] **Step 3: Add fallback search in _ensure_pr_created**

In `src/ai_agent_orchestrator/phases/base.py`, replace Step 2 section (lines 404-425):

```python
        # Step 2: ブランチ名で既存PRを検索
        branch_name = f"{branch_prefix}/issue-{request.issue_number}"
        search_branches = [branch_name]
        # branch_prefix が "feature" 以外の場合、feature/issue-XX でもフォールバック検索
        if branch_prefix != "feature":
            search_branches.append(f"feature/issue-{request.issue_number}")

        owner = getattr(request.repo, "owner", "")
        for search_branch in search_branches:
            head_filter = f"{owner}:{search_branch}"
            try:
                existing_prs = await client.list_pull_requests(
                    request.repo,
                    state="open",
                    head=head_filter,
                )
                if existing_prs:
                    found_pr = getattr(existing_prs[0], "number", None)
                    if found_pr is not None:
                        logger.info(
                            "Found existing PR #%d for branch %s (issue #%d)",
                            found_pr,
                            search_branch,
                            request.issue_number,
                        )
                        return int(found_pr)
            except Exception:
                logger.warning(
                    "Failed to search existing PRs for branch %s (issue #%d)",
                    search_branch,
                    request.issue_number,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_phases.py::TestEnsurePrCreatedFallback -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/unit/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/ai_agent_orchestrator/phases/base.py tests/unit/test_phases.py
git commit -m "fix: add feature branch fallback in _ensure_pr_created"
```

---

### Task 7: Full integration test run and final commit

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/`
Expected: No errors (or pre-existing errors only)

- [ ] **Step 3: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No new violations

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: lint/type fixes for hearing-wait and branch-prefix changes"
```
