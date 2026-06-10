"""ReviseExecutorBase (U2: REVISE 統合とレビュー質問への回答) のテスト."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import AgentResult
from ai_agent_orchestrator.phases.design_revise import DesignReviseExecutor
from ai_agent_orchestrator.phases.impl_revise import ImplReviseExecutor
from ai_agent_orchestrator.phases.revise_common import ReviseExecutorBase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    phase: str = "impl-revise",
    extra: dict[str, Any] | None = None,
) -> MagicMock:
    req = MagicMock()
    req.repo = MagicMock(owner="org", repo="app")
    req.issue_number = 1
    req.issue_key = ("org/app", 1)
    req.phase = phase
    req.extra = extra or {}
    return req


def _make_executor(
    cls: type[ReviseExecutorBase],
    github: AsyncMock,
    sm: MagicMock,
    runner: AsyncMock | None = None,
) -> ReviseExecutorBase:
    executor = cls(
        runner or AsyncMock(),
        github,
        AsyncMock(),  # notifier
        AsyncMock(),  # tracker
        AsyncMock(),  # workspace
        AsyncMock(),  # context
        sm,
    )
    # コミット処理は U1 でテスト済みのためモック
    executor._finalize_phase_commit = AsyncMock()  # type: ignore[method-assign]
    return executor


def _mock_sm(pr_number: int | None = 42) -> MagicMock:
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(
        pr_number=pr_number,
        design_pr_number=pr_number,
        session_id="prev-session",
        branch_head_sha=None,
    )
    sm.transition = AsyncMock()
    return sm


def _mock_github() -> AsyncMock:
    gh = AsyncMock()
    del gh.get_client_for_repo
    issue = MagicMock()
    issue.title = "テストIssue"
    issue.body = "本文"
    gh.get_issue.return_value = issue
    gh.list_pull_requests.return_value = []
    return gh


def _agent_result(output: str) -> AgentResult:
    return AgentResult(
        session_id="sess-002",
        output=output,
        tool_uses=[],
        cost_usd=0.1,
        duration_sec=5.0,
    )


REPLIES_OUTPUT = """対応しました。

```json
{
  "replies": [
    {"comment_id": 100, "kind": "fixed", "reply": "デバウンスを 300ms で追加しました。"},
    {"comment_id": 101, "kind": "answered", "reply": "はい、キャンセル処理は AbortController で実装済みです。"}
  ],
  "summary": "デバウンス追加とキャンセル実装の説明を行いました。"
}
```
"""


# ---------------------------------------------------------------------------
# 構造化出力のパース
# ---------------------------------------------------------------------------


class TestParseReviseOutput:
    """エージェント出力から返信マップとサマリを抽出する。"""

    def test_parses_replies_and_summary(self) -> None:
        replies, summary = ReviseExecutorBase._parse_revise_output(REPLIES_OUTPUT)
        assert replies[100] == "デバウンスを 300ms で追加しました。"
        assert replies[101].startswith("はい、キャンセル処理は")
        assert summary == "デバウンス追加とキャンセル実装の説明を行いました。"

    def test_missing_json_returns_empty(self) -> None:
        replies, summary = ReviseExecutorBase._parse_revise_output("JSON なしの出力")
        assert replies == {}
        assert summary is None

    def test_malformed_entries_are_skipped(self) -> None:
        output = """```json
{"replies": [{"comment_id": null, "reply": "全体回答"}, {"reply": "ID なし"}, {"comment_id": 7, "reply": "OK"}], "summary": "s"}
```"""
        replies, summary = ReviseExecutorBase._parse_revise_output(output)
        assert replies == {7: "OK"}
        assert summary == "s"


# ---------------------------------------------------------------------------
# 返信ディスパッチ（インライン: 生成文 / 定型文の廃止）
# ---------------------------------------------------------------------------


class TestReplyDispatch:
    """各レビューコメントへ生成された返信が送られる。"""

    async def test_replies_with_generated_text_per_comment(self) -> None:
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        request = _make_request(extra={"comments": "c", "review_comment_ids": [100, 101]})

        await executor.process_result(request, _agent_result(REPLIES_OUTPUT))

        assert gh.reply_to_review_comment.call_count == 2
        bodies = [c.args[3] for c in gh.reply_to_review_comment.call_args_list]
        assert "デバウンスを 300ms で追加しました。" in bodies[0]
        assert any("AbortController" in b for b in bodies)
        # 定型文が使われていない
        assert all("修正が完了しました。コードをご確認ください。" not in b for b in bodies)

    async def test_fallback_to_summary_when_reply_missing(self) -> None:
        """JSON に該当 ID の返信が無いコメントにはサマリで返信する。"""
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        request = _make_request(extra={"comments": "c", "review_comment_ids": [100, 999]})

        await executor.process_result(request, _agent_result(REPLIES_OUTPUT))

        bodies = {c.args[2]: c.args[3] for c in gh.reply_to_review_comment.call_args_list}
        assert "デバウンス" in bodies[100]
        # 999 は JSON に無い → サマリで代替（定型文ではない）
        assert "デバウンス追加とキャンセル実装" in bodies[999]

    async def test_top_level_review_gets_pr_comment(self) -> None:
        """comment ID が無い（トップレベルレビュー）場合は PR コメントで応答する。"""
        gh = _mock_github()
        sm = _mock_sm(pr_number=42)
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        output = """```json
{"replies": [], "summary": "ご質問のキャッシュ戦略について: LRU を採用しています。"}
```"""
        request = _make_request(extra={"comments": "質問テキスト", "review_comment_ids": []})

        await executor.process_result(request, _agent_result(output))

        gh.reply_to_review_comment.assert_not_called()
        gh.create_comment.assert_called_once()
        body = gh.create_comment.call_args.args[2]
        assert "LRU" in body
        # PR 番号宛て
        assert gh.create_comment.call_args.args[1] == 42

    async def test_no_changes_allowed_for_question_only_flow(self) -> None:
        """質問のみ → allow_no_changes=True で finalize（コミット 0 件の受け入れ条件）。"""
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        request = _make_request(extra={"comments": "Q", "review_comment_ids": [100]})

        await executor.process_result(request, _agent_result(REPLIES_OUTPUT))

        kwargs = executor._finalize_phase_commit.call_args.kwargs  # type: ignore[attr-defined]
        assert kwargs["allow_no_changes"] is True


# ---------------------------------------------------------------------------
# サブクラスの遷移・統合
# ---------------------------------------------------------------------------


class TestSubclassIntegration:
    """design_revise / impl_revise が共通基底で動く。"""

    async def test_impl_revise_transitions_to_impl_review(self) -> None:
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        request = _make_request(extra={"comments": "c", "review_comment_ids": []})

        await executor.process_result(request, _agent_result("done"))

        sm.transition.assert_called_with(("org/app", 1), "impl-review")
        gh.replace_phase_label.assert_called_with(request.repo, 1, "phase:impl-review")

    async def test_design_revise_transitions_to_design_review(self) -> None:
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(DesignReviseExecutor, gh, sm)
        request = _make_request(phase="design-revise", extra={"comments": {"comments": "指摘"}})

        await executor.process_result(request, _agent_result("done"))

        sm.transition.assert_called_with(("org/app", 1), "design-review")
        gh.replace_phase_label.assert_called_with(request.repo, 1, "phase:design-review")

    async def test_both_are_revise_base_subclasses(self) -> None:
        assert issubclass(ImplReviseExecutor, ReviseExecutorBase)
        assert issubclass(DesignReviseExecutor, ReviseExecutorBase)

    async def test_resume_session_is_used(self) -> None:
        gh = _mock_github()
        sm = _mock_sm()
        runner = AsyncMock()
        runner.run.return_value = _agent_result("ok")
        executor = _make_executor(ImplReviseExecutor, gh, sm, runner=runner)
        request = _make_request()

        await executor.run_agent(request, "p")

        assert runner.run.call_args.kwargs["resume_session_id"] == "prev-session"


# ---------------------------------------------------------------------------
# プロンプト（質問対応の指示と ID マーカー）
# ---------------------------------------------------------------------------


class TestRevisePrompt:
    """プロンプトに質問回答の指示・ID・出力フォーマットが含まれる。"""

    async def test_prompt_contains_question_instruction_and_ids(self) -> None:
        gh = _mock_github()
        sm = _mock_sm()
        executor = _make_executor(ImplReviseExecutor, gh, sm)
        comments = [
            {"id": 100, "user": {"login": "alice"}, "path": "a.py", "line": 3, "body": "デバウンスは？"},
        ]
        request = _make_request(
            extra={"comments": "fallback", "review_comments": comments, "review_comment_ids": [100]}
        )

        prompt = await executor.build_prompt(request)

        assert "[ID:100]" in prompt
        assert "質問" in prompt
        assert "コードを変更せず" in prompt or "コード変更は不要" in prompt
        assert '"replies"' in prompt  # 出力フォーマット指定
        assert "git commit" not in prompt.lower() or "不要" in prompt
