"""ClaudeAgentRunner (Claude Agent SDK 実行)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    HookMatcher,
    Message,
    query,
)
from claude_agent_sdk.types import (
    AssistantMessage,
    HookContext,
    HookEvent,
    HookJSONOutput,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from ai_agent_orchestrator.models import AgentResult, PhaseConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tracker Protocol (minimal, avoids circular import with protocols.py)
# ---------------------------------------------------------------------------


class Tracker(Protocol):
    """Tracker protocol for tool-use logging."""

    async def track(self, event: str, data: dict[str, Any]) -> None:
        """Record an event."""
        ...


# ---------------------------------------------------------------------------
# Sub-agent definitions (informational; SDK has no native subagent support)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SubAgentDefinition:
    """Sub-agent definition for implementation phases."""

    name: str
    description: str
    instructions: str


CODE_ANALYZER = SubAgentDefinition(
    name="code-analyzer",
    description="既存コードベースの構造分析とリポマップ生成",
    instructions=("リポジトリのファイル構造、主要モジュール、依存関係を分析して要約する。"),
)

TEST_WRITER = SubAgentDefinition(
    name="test-writer",
    description="テストコード作成の専門エージェント",
    instructions=("既存テストのパターンに従い、ユニットテストと統合テストを作成する。"),
)

_IMPL_PHASES = frozenset({"implement", "fix", "ci-fix", "impl-revise"})

_SUBAGENTS: list[SubAgentDefinition] = [CODE_ANALYZER, TEST_WRITER]


# ---------------------------------------------------------------------------
# PHASE_CONFIG
# ---------------------------------------------------------------------------

PHASE_CONFIG: dict[str, PhaseConfig] = {
    # キーは Phase enum の .value と一致させる (ハイフン区切り)
    "type-detection": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="bypassPermissions"),
    "hearing": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="bypassPermissions"),
    "analysis": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="bypassPermissions"),
    "plan-brief": PhaseConfig(max_budget_usd=1.0, timeout_sec=300, permission_mode="bypassPermissions"),
    "design": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "design-revise": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
        resume=True,
    ),
    "planning": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="bypassPermissions"),
    "split-proposal": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="bypassPermissions"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    "fix": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "ci-fix": PhaseConfig(max_budget_usd=3.0, timeout_sec=1200, permission_mode="bypassPermissions"),
    "impl-revise": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
        resume=True,
    ),
}

_DEFAULT_PHASE_CONFIG = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="bypassPermissions")


# ---------------------------------------------------------------------------
# Custom errors
# ---------------------------------------------------------------------------


class MaxTurnsExceededError(ClaudeSDKError):
    """Raised when query() ends with stop_reason == max_turns."""

    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id
        super().__init__(f"Max turns exceeded (session_id={session_id})")


# ---------------------------------------------------------------------------
# ClaudeAgentRunner
# ---------------------------------------------------------------------------


class ClaudeAgentRunner:
    """Claude Agent SDK を使用した AgentRunner 実装."""

    def __init__(self, tracker: Tracker) -> None:
        """ClaudeAgentRunner を初期化する.

        Args:
            tracker: ツール使用ログの記録に使用する Tracker。
        """
        self._tracker = tracker
        self._active_sessions: dict[str, ClaudeSDKClient] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(
        self,
        prompt: str,
        *,
        cwd: str,
        phase: str,
        max_budget_usd: float | None = None,
        resume_session_id: str | None = None,
        timeout_sec: int = 0,
    ) -> AgentResult:
        """AI エージェントを実行し、結果を返す.

        Args:
            prompt: エージェントに渡すプロンプト。
            cwd: 作業ディレクトリ (worktree パス)。
            phase: 実行フェーズ名。PHASE_CONFIG のキーと一致する必要がある。
            max_budget_usd: コスト上限 (USD)。None の場合はフェーズ設定のデフォルト値。
            resume_session_id: 継続するセッション ID。指定時はマルチターン実行。
            timeout_sec: タイムアウト (秒)。0 の場合はフェーズ設定の値を使用。

        Returns:
            AgentResult: session_id, output, tool_uses, cost_usd, duration_sec を含む。

        Raises:
            asyncio.TimeoutError: タイムアウト時。
            ClaudeSDKError: SDK レベルのエラー。
            MaxTurnsExceededError: max_turns 到達時。
        """
        cfg = PHASE_CONFIG.get(phase, _DEFAULT_PHASE_CONFIG)
        budget = max_budget_usd if max_budget_usd is not None else cfg.max_budget_usd
        effective_timeout = timeout_sec if timeout_sec > 0 else cfg.timeout_sec

        # Build hooks (disabled: hook callbacks cause Stream closed errors in SDK)
        hooks: dict[str, list[HookMatcher]] = {}

        # Build subagent instructions for implementation phases
        subagents: list[SubAgentDefinition] = []
        append_prompt = ""
        if phase in _IMPL_PHASES:
            subagents = list(_SUBAGENTS)
            append_prompt = self._build_subagent_prompt(subagents)

        # Session resume via active client
        if resume_session_id and resume_session_id in self._active_sessions:
            client = self._active_sessions[resume_session_id]
            return await asyncio.wait_for(
                self._run_with_client(client, prompt),
                timeout=effective_timeout,
            )

        # Build options (max_turns はSDKデフォルトに委任)
        options = ClaudeAgentOptions(
            cwd=cwd,
            permission_mode=cfg.permission_mode,  # type: ignore[arg-type]
            hooks=hooks,  # type: ignore[arg-type]
            max_budget_usd=budget,
        )
        # 実装系フェーズでは allowed_tools を明示的に設定
        if cfg.permission_mode == "bypassPermissions":
            options.allowed_tools = [
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "Bash",
                "TodoWrite",
            ]
        if append_prompt:
            options.system_prompt = {
                "type": "preset",
                "preset": "claude_code",
                "append": append_prompt,
            }

        return await asyncio.wait_for(
            self._run_query(
                prompt=prompt,
                options=options,
                budget=budget,
                subagents=subagents,
                phase=phase,
            ),
            timeout=effective_timeout,
        )

    async def interrupt(self, session_id: str) -> None:
        """実行中のセッションを安全に中断する.

        Args:
            session_id: 中断するセッション ID。
        """
        client = self._active_sessions.pop(session_id, None)
        if client is not None:
            await client.interrupt()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_query(
        self,
        *,
        prompt: str,
        options: ClaudeAgentOptions,
        budget: float,
        subagents: list[SubAgentDefinition],
        phase: str,
    ) -> AgentResult:
        """query() を実行してメッセージを収集し AgentResult を返す."""
        start = time.monotonic()

        all_messages: list[Message] = []  # accumulate across ALL attempts
        max_retries = 3

        for attempt in range(max_retries):
            attempt_messages: list[Message] = []
            try:
                async for msg in query(prompt=prompt, options=options):
                    if msg is not None:  # claude-agent-sdk may return None for unknown types
                        attempt_messages.append(msg)
                        logger.debug(
                            "SDK message: type=%s, has_content=%s",
                            type(msg).__name__,
                            hasattr(msg, "content"),
                        )
                all_messages.extend(attempt_messages)
                break  # success - got through without exception
            except Exception as e:
                all_messages.extend(attempt_messages)  # PRESERVE partial messages

                if "Unknown message type" in str(e):
                    # Check if we already have useful TextBlock content
                    has_text = any(
                        isinstance(m, AssistantMessage) and any(isinstance(b, TextBlock) for b in m.content)
                        for m in all_messages
                    )
                    if has_text:
                        logger.info("TextBlock found in accumulated messages, proceeding")
                        break

                    if attempt < max_retries - 1:
                        wait = 60.0 * (2**attempt)  # 60s, 120s exponential backoff
                        logger.warning(
                            "rate_limit_event on attempt %d/%d (collected %d messages total). Retrying in %.0fs...",
                            attempt + 1,
                            max_retries,
                            len(all_messages),
                            wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "Max retries reached with no TextBlock (total messages: %d)",
                            len(all_messages),
                        )
                else:
                    raise  # re-raise non-rate-limit errors

        elapsed = time.monotonic() - start
        logger.info(
            "SDK query complete: %d messages collected in %.1fs",
            len(all_messages),
            elapsed,
        )

        result = self._parse_messages(
            all_messages,
            elapsed=elapsed,
            budget=budget,
            subagents=subagents,
            phase=phase,
        )

        # ResultMessage が欠落した場合のフォールバック
        if not result.output and not result.session_id:
            logger.warning(
                "SDK returned no output and no session_id. Messages: %s",
                [type(m).__name__ for m in all_messages],
            )

        # AssistantMessage のテキストがなく ResultMessage にテキストがある場合
        if not result.output:
            for msg in all_messages:
                if isinstance(msg, ResultMessage) and msg.result:
                    logger.info(
                        "Falling back to ResultMessage.result (len=%d)",
                        len(msg.result),
                    )
                    result = AgentResult(
                        session_id=result.session_id,
                        output=msg.result,
                        tool_uses=result.tool_uses,
                        cost_usd=result.cost_usd,
                        duration_sec=result.duration_sec,
                    )
                    break

        return result

    def _build_hooks(self) -> dict[HookEvent, list[HookMatcher]]:
        """PreToolUse / PostToolUse フックを構成する."""
        pre_hook = HookMatcher(hooks=[self._on_pre_tool_use])  # type: ignore[list-item]
        post_hook = HookMatcher(hooks=[self._on_post_tool_use])  # type: ignore[list-item]
        return {
            "PreToolUse": [pre_hook],
            "PostToolUse": [post_hook],
        }

    async def _on_pre_tool_use(
        self,
        event: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        """PreToolUse フックコールバック。ツール使用開始をログに記録する."""
        tool_name = event.get("tool_name", "unknown")
        await self._tracker.track(
            "tool_use_start",
            {"tool": tool_name, "tool_input": event.get("tool_input", {})},
        )
        return {}

    async def _on_post_tool_use(
        self,
        event: dict[str, Any],
        tool_use_id: str | None,
        context: HookContext,
    ) -> HookJSONOutput:
        """PostToolUse フックコールバック。ツール使用完了をログに記録する."""
        tool_name = event.get("tool_name", "unknown")
        output = event.get("tool_output", "")
        await self._tracker.track(
            "tool_use_end",
            {
                "tool": tool_name,
                "output_size": len(str(output)),
            },
        )
        return {}

    @staticmethod
    def _build_subagent_prompt(subagents: list[SubAgentDefinition]) -> str:
        """サブエージェント情報をシステムプロンプト文字列に変換する."""
        lines = ["Available sub-agent roles:"]
        for sa in subagents:
            lines.append(f"- {sa.name}: {sa.description}")
            lines.append(f"  Instructions: {sa.instructions}")
        return "\n".join(lines)

    def _parse_messages(
        self,
        messages: list[Message],
        *,
        elapsed: float,
        budget: float,
        subagents: list[SubAgentDefinition],
        phase: str,
    ) -> AgentResult:
        """query() の返却メッセージ群を AgentResult に変換する.

        出力テキストは AssistantMessage の TextBlock から取得する。
        ResultMessage.result は重複するため無視し、メタデータ(session_id,
        cost, duration)のみ ResultMessage から取得する。
        rate_limit_event 等で ResultMessage が欠落した場合に備え、
        session_id は AssistantMessage からも fallback で取得する。
        """
        assistant_text = ""
        session_id: str | None = None
        cost: float = 0.0
        tool_uses: list[dict[str, Any]] = []
        duration_ms: int = 0

        for msg in messages:
            # ResultMessage: メタデータのみ取得(テキストは重複するので無視)
            if isinstance(msg, ResultMessage):
                session_id = msg.session_id
                if msg.total_cost_usd is not None:
                    cost += msg.total_cost_usd
                duration_ms = msg.duration_ms
                # Check max_turns
                if msg.is_error and msg.subtype == "max_turns":
                    raise MaxTurnsExceededError(session_id=session_id)

            # AssistantMessage: テキストとツール使用を取得
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        assistant_text += block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_uses.append({"tool": block.name, "input": block.input})

        # If no TextBlock found, try ThinkingBlock as degraded fallback
        if not assistant_text:
            thinking_texts: list[str] = [
                block.thinking
                for msg in messages
                if isinstance(msg, AssistantMessage)
                for block in msg.content
                if hasattr(block, "thinking") and block.thinking
            ]
            if thinking_texts:
                logger.warning("No TextBlock found, using ThinkingBlock content as fallback")
                assistant_text = "\n".join(thinking_texts)

        # Use SDK-reported duration if available, fall back to wall clock
        final_duration = duration_ms / 1000.0 if duration_ms > 0 else elapsed

        return AgentResult(
            session_id=session_id or "",
            output=assistant_text,
            tool_uses=tool_uses,
            cost_usd=cost,
            duration_sec=final_duration,
        )

    async def _run_with_client(
        self,
        client: ClaudeSDKClient,
        prompt: str,
    ) -> AgentResult:
        """ClaudeSDKClient を使用したマルチターン実行."""
        start = time.monotonic()
        result = await client.send(prompt)  # type: ignore[attr-defined]
        elapsed = time.monotonic() - start

        # client.send returns a result-like object
        session_id = getattr(result, "session_id", "")
        cost = getattr(result, "total_cost_usd", 0.0) or 0.0
        text = getattr(result, "result", "") or ""
        duration_ms = getattr(result, "duration_ms", 0)

        return AgentResult(
            session_id=session_id,
            output=text,
            tool_uses=[],
            cost_usd=cost,
            duration_sec=duration_ms / 1000.0 if duration_ms > 0 else elapsed,
        )
