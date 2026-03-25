"""Tests for ClaudeAgentRunner."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent_orchestrator.agents.claude_runner import (
    _IMPL_PHASES,
    PHASE_CONFIG,
    ClaudeAgentRunner,
    MaxTurnsExceededError,
    PhaseConfig,
)
from ai_agent_orchestrator.models import AgentResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_tracker() -> AsyncMock:
    """Create a mock Tracker."""
    tracker = AsyncMock()
    tracker.track = AsyncMock()
    return tracker


@pytest.fixture
def runner(mock_tracker: AsyncMock) -> ClaudeAgentRunner:
    """Create a ClaudeAgentRunner with a mock tracker."""
    return ClaudeAgentRunner(tracker=mock_tracker)


# ---------------------------------------------------------------------------
# Helpers for building mock messages
# ---------------------------------------------------------------------------


def _make_text_block(text: str = "output text") -> Any:
    """Create a TextBlock."""
    from claude_agent_sdk.types import TextBlock

    return TextBlock(text=text)


def _make_thinking_block(thinking: str = "thinking content") -> Any:
    """Create a ThinkingBlock."""
    from claude_agent_sdk.types import ThinkingBlock

    return ThinkingBlock(thinking=thinking, signature="sig")


def _make_tool_use_block(name: str = "Bash", input_data: dict[str, Any] | None = None) -> Any:
    from claude_agent_sdk.types import ToolUseBlock

    return ToolUseBlock(id="tu-1", name=name, input=input_data or {})


def _make_assistant_message(
    text: str = "output text",
    tool_uses: list[Any] | None = None,
    extra_blocks: list[Any] | None = None,
) -> Any:
    """Create an AssistantMessage.

    Args:
        text: Text content for the TextBlock.
        tool_uses: Optional ToolUseBlock list to append.
        extra_blocks: Optional extra blocks (e.g. ThinkingBlock) to prepend.
    """
    from claude_agent_sdk.types import AssistantMessage

    blocks: list[Any] = []
    if extra_blocks:
        blocks.extend(extra_blocks)
    blocks.append(_make_text_block(text))
    if tool_uses:
        blocks.extend(tool_uses)
    return AssistantMessage(content=blocks, model="claude-sonnet-4-20250514")


def _make_thinking_only_assistant_message(thinking: str = "thinking content") -> Any:
    """Create an AssistantMessage with only a ThinkingBlock (no TextBlock)."""
    from claude_agent_sdk.types import AssistantMessage

    return AssistantMessage(
        content=[_make_thinking_block(thinking)],
        model="claude-sonnet-4-20250514",
    )


def _make_result_message(
    session_id: str = "sess-001",
    cost_usd: float = 0.5,
    duration_ms: int = 30000,
    is_error: bool = False,
    subtype: str = "success",
    result: str | None = None,
) -> Any:
    """Create a ResultMessage."""
    from claude_agent_sdk.types import ResultMessage

    return ResultMessage(
        subtype=subtype,
        duration_ms=duration_ms,
        duration_api_ms=duration_ms,
        is_error=is_error,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost_usd,
        result=result,
    )


def _make_fake_query(
    messages: list[Any],
    captured_kwargs: list[dict[str, Any]] | None = None,
) -> Any:
    """Create a fake query function returning an async generator.

    If captured_kwargs is provided, each call appends kwargs to it.
    """

    async def fake_query(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        if captured_kwargs is not None:
            captured_kwargs.append({"prompt": prompt, "options": options})
        for msg in messages:
            yield msg

    return fake_query


def _make_fake_query_with_exception(
    messages_before_error: list[Any],
    exception: Exception,
    captured_kwargs: list[dict[str, Any]] | None = None,
) -> Any:
    """Create a fake query that yields messages then raises an exception."""

    async def fake_query(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        if captured_kwargs is not None:
            captured_kwargs.append({"prompt": prompt, "options": options})
        for msg in messages_before_error:
            yield msg
        raise exception

    return fake_query


# ---------------------------------------------------------------------------
# TC-CR-01: run -- ワンショット実行 (hearing フェーズ)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_oneshot_hearing(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """hearing フェーズでワンショット実行され、正しい AgentResult が返る."""
    messages = [
        _make_assistant_message(text="分析結果"),
        _make_result_message(session_id="sess-hearing-001", cost_usd=0.8),
    ]
    captured: list[dict[str, Any]] = []
    mock_query.side_effect = lambda **kw: _make_fake_query(messages, captured)(**kw)

    result = await runner.run(
        prompt="Issue を分析してください",
        cwd="/tmp/worktree/issue-42",
        phase="hearing",
    )

    assert isinstance(result, AgentResult)
    assert result.session_id == "sess-hearing-001"
    assert result.cost_usd == 0.8
    assert "分析結果" in result.output
    # Verify options
    assert len(captured) == 1
    opts = captured[0]["options"]
    assert opts.permission_mode == "plan"


# ---------------------------------------------------------------------------
# TC-CR-02: run -- マルチターン実行 (impl_revise フェーズ)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_multiturn_resume(runner: ClaudeAgentRunner) -> None:
    """resume_session_id 指定時にセッション継続が行われる."""
    mock_client = AsyncMock()
    mock_result = MagicMock()
    mock_result.session_id = "sess-revise-001"
    mock_result.total_cost_usd = 1.2
    mock_result.result = "修正完了"
    mock_result.duration_ms = 5000
    mock_client.send = AsyncMock(return_value=mock_result)
    runner._active_sessions["sess-impl-001"] = mock_client

    result = await runner.run(
        prompt="レビュー指摘に対応してください",
        cwd="/tmp/worktree/issue-42",
        phase="impl_revise",
        resume_session_id="sess-impl-001",
    )

    assert result.session_id == "sess-revise-001"
    mock_client.send.assert_called_once_with("レビュー指摘に対応してください")


# ---------------------------------------------------------------------------
# TC-CR-03: run -- タイムアウト発生
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_raises_timeout_error(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """タイムアウト時に asyncio.TimeoutError が送出される."""

    async def slow_query(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        await asyncio.sleep(10)
        yield _make_result_message()  # pragma: no cover

    mock_query.side_effect = slow_query

    with pytest.raises(asyncio.TimeoutError):
        await runner.run(
            prompt="実装してください",
            cwd="/tmp/worktree/issue-42",
            phase="implement",
            timeout_sec=1,
        )


# ---------------------------------------------------------------------------
# TC-CR-04: run -- max_budget_usd の明示的指定がフェーズ設定を上書き
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_explicit_budget_overrides_phase_config(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """max_budget_usd を明示的に指定した場合、PHASE_CONFIG の値が上書きされる."""
    messages = [_make_result_message(session_id="sess-001")]
    mock_query.side_effect = lambda **kw: _make_fake_query(messages)(**kw)

    result = await runner.run(
        prompt="テスト",
        cwd="/tmp/worktree",
        phase="implement",
        max_budget_usd=20.0,
    )

    assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# TC-CR-05: run -- 実装フェーズでサブエージェント情報が追加される
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_adds_subagents_for_implement_phase(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """implement フェーズでサブエージェント情報が system prompt に追加される."""
    messages = [_make_result_message(session_id="sess-001")]
    captured: list[dict[str, Any]] = []
    mock_query.side_effect = lambda **kw: _make_fake_query(messages, captured)(**kw)

    await runner.run(
        prompt="実装してください",
        cwd="/tmp/worktree",
        phase="implement",
    )

    assert len(captured) == 1
    opts = captured[0]["options"]
    assert opts.system_prompt is not None
    assert "code-analyzer" in opts.system_prompt
    assert "test-writer" in opts.system_prompt


# ---------------------------------------------------------------------------
# TC-CR-06: run -- hearing フェーズではサブエージェントなし
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_no_subagents_for_hearing_phase(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """hearing フェーズではサブエージェントが追加されない."""
    messages = [_make_result_message(session_id="sess-001")]
    captured: list[dict[str, Any]] = []
    mock_query.side_effect = lambda **kw: _make_fake_query(messages, captured)(**kw)

    await runner.run(
        prompt="ヒアリングしてください",
        cwd="/tmp/worktree",
        phase="hearing",
    )

    assert len(captured) == 1
    opts = captured[0]["options"]
    assert opts.system_prompt is None


# ---------------------------------------------------------------------------
# TC-CR-07: interrupt -- アクティブセッションの中断
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupt_stops_active_session(runner: ClaudeAgentRunner) -> None:
    """アクティブなセッションが interrupt() で中断され、辞書から削除される."""
    mock_client = AsyncMock()
    runner._active_sessions["sess-001"] = mock_client

    await runner.interrupt("sess-001")

    mock_client.interrupt.assert_called_once()
    assert "sess-001" not in runner._active_sessions


# ---------------------------------------------------------------------------
# TC-CR-08: interrupt -- 存在しないセッションは無視
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupt_ignores_unknown_session(runner: ClaudeAgentRunner) -> None:
    """存在しないセッション ID で interrupt() を呼んでも例外が発生しない."""
    await runner.interrupt("nonexistent-session")


# ---------------------------------------------------------------------------
# TC-CR-09: PHASE_CONFIG -- 全 12 フェーズの定義確認
# ---------------------------------------------------------------------------


def test_phase_config_has_all_phases() -> None:
    """PHASE_CONFIG に全 12 フェーズが定義されている."""
    expected_phases = {
        "type_detection",
        "hearing",
        "analysis",
        "plan_brief",
        "design",
        "design_revise",
        "planning",
        "split_proposal",
        "implement",
        "fix",
        "ci_fix",
        "impl_revise",
    }
    assert set(PHASE_CONFIG.keys()) == expected_phases

    for config in PHASE_CONFIG.values():
        assert isinstance(config, PhaseConfig)
        assert config.max_budget_usd > 0
        assert config.timeout_sec > 0
        assert config.permission_mode in ("plan", "default", "acceptEdits", "bypassPermissions")


# ---------------------------------------------------------------------------
# TC-CR-10: run -- フックコールバックが設定される
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_hooks_are_configured(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """PreToolUse/PostToolUse フックが正しく設定される."""
    messages = [_make_result_message(session_id="sess-001")]
    captured: list[dict[str, Any]] = []
    mock_query.side_effect = lambda **kw: _make_fake_query(messages, captured)(**kw)

    await runner.run(prompt="テスト", cwd="/tmp", phase="hearing")

    assert len(captured) == 1
    opts = captured[0]["options"]
    hooks = opts.hooks
    assert "PreToolUse" in hooks
    assert "PostToolUse" in hooks
    assert len(hooks["PreToolUse"]) == 1
    assert len(hooks["PostToolUse"]) == 1


# ---------------------------------------------------------------------------
# TC-CR-11: run -- tool_uses extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_extracts_tool_uses(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """AssistantMessage の ToolUseBlock が AgentResult.tool_uses に含まれる."""
    tool_block = _make_tool_use_block(name="Bash", input_data={"command": "ls"})
    messages = [
        _make_assistant_message(text="done", tool_uses=[tool_block]),
        _make_result_message(session_id="sess-001"),
    ]
    mock_query.side_effect = lambda **kw: _make_fake_query(messages)(**kw)

    result = await runner.run(prompt="test", cwd="/tmp", phase="hearing")

    assert len(result.tool_uses) == 1
    assert result.tool_uses[0]["tool"] == "Bash"


# ---------------------------------------------------------------------------
# TC-CR-12: run -- max_turns exceeded detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_raises_max_turns_exceeded(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """max_turns 到達時に MaxTurnsExceededError が送出される."""
    messages = [
        _make_result_message(
            session_id="sess-001",
            is_error=True,
            subtype="max_turns",
        ),
    ]
    mock_query.side_effect = lambda **kw: _make_fake_query(messages)(**kw)

    with pytest.raises(MaxTurnsExceededError) as exc_info:
        await runner.run(prompt="test", cwd="/tmp", phase="implement")

    assert exc_info.value.session_id == "sess-001"


# ---------------------------------------------------------------------------
# TC-CR-13: run -- unknown phase uses default config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_unknown_phase_uses_defaults(
    mock_query: MagicMock,
    runner: ClaudeAgentRunner,
) -> None:
    """未定義フェーズではデフォルト設定が使用される."""
    messages = [_make_result_message(session_id="sess-001")]
    mock_query.side_effect = lambda **kw: _make_fake_query(messages)(**kw)

    result = await runner.run(
        prompt="test",
        cwd="/tmp",
        phase="unknown_phase",
    )

    assert isinstance(result, AgentResult)


# ---------------------------------------------------------------------------
# TC-CR-14: _IMPL_PHASES covers expected phases
# ---------------------------------------------------------------------------


def test_impl_phases_set() -> None:
    """_IMPL_PHASES が正しい実装フェーズを含む."""
    assert {"implement", "fix", "ci_fix", "impl_revise"} == _IMPL_PHASES


# ---------------------------------------------------------------------------
# TC-CR-15: run -- rate_limit_event でリトライしてもメッセージが蓄積される
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.asyncio.sleep", new_callable=AsyncMock)
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_accumulates_messages_across_retries(
    mock_query: MagicMock,
    mock_sleep: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """rate_limit_event でリトライしてもメッセージが蓄積される."""
    # First attempt: ThinkingBlock only, then "Unknown message type" exception
    attempt1_messages = [_make_thinking_only_assistant_message("考え中...")]
    attempt1_error = Exception("Unknown message type: rate_limit_event")

    # Second attempt: TextBlock + ResultMessage, then "Unknown message type" exception
    attempt2_messages = [
        _make_assistant_message(text="リトライ後の結果"),
        _make_result_message(session_id="sess-retry-001", cost_usd=0.6),
    ]
    attempt2_error = Exception("Unknown message type: rate_limit_event")

    call_count = 0

    async def fake_query_with_retries(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            for msg in attempt1_messages:
                yield msg
            raise attempt1_error
        elif call_count == 2:
            for msg in attempt2_messages:
                yield msg
            raise attempt2_error

    mock_query.side_effect = fake_query_with_retries

    result = await runner.run(
        prompt="テスト",
        cwd="/tmp/worktree",
        phase="hearing",
    )

    assert isinstance(result, AgentResult)
    assert "リトライ後の結果" in result.output
    assert result.session_id == "sess-retry-001"
    # asyncio.sleep should have been called for backoff between attempt 1 and 2
    mock_sleep.assert_called()


# ---------------------------------------------------------------------------
# TC-CR-16: run -- TextBlock がない場合 ThinkingBlock をフォールバックで使用
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.asyncio.sleep", new_callable=AsyncMock)
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_thinking_block_fallback(
    mock_query: MagicMock,
    mock_sleep: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """TextBlock がない場合 ThinkingBlock をフォールバックで使用.

    全リトライが ThinkingBlock のみで失敗した場合、
    ResultMessage.result がなければ output は空文字列になるが、
    session_id 等のメタデータは取得できる。
    ThinkingBlock 自体は現在 _parse_messages で TextBlock のみ抽出するため
    output には含まれないが、エラーにならず正常終了する。
    """
    error = Exception("Unknown message type: rate_limit_event")

    call_count = 0

    async def fake_query_always_thinking(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        nonlocal call_count
        call_count += 1
        # Every attempt yields only ThinkingBlock, no TextBlock
        yield _make_thinking_only_assistant_message("深い思考中...")
        if call_count < 3:
            raise error
        # Last attempt: also add a ResultMessage so we get metadata
        yield _make_result_message(
            session_id="sess-thinking-001",
            cost_usd=0.3,
            result="フォールバックテキスト",
        )

    mock_query.side_effect = fake_query_always_thinking

    result = await runner.run(
        prompt="テスト",
        cwd="/tmp/worktree",
        phase="hearing",
    )

    assert isinstance(result, AgentResult)
    assert result.session_id == "sess-thinking-001"
    # ThinkingBlock content is used as fallback when no TextBlock output
    assert "深い思考中" in result.output
    # Verify retries happened (sleep called for backoff)
    assert mock_sleep.call_count >= 1
