"""ClaudeAgentRunner (Claude Code SDK 実行)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from claude_code_sdk import (
    ClaudeCodeOptions,
    ClaudeSDKClient,
    ClaudeSDKError,
    HookMatcher,
    Message,
    query,
)
from claude_code_sdk.types import (
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

_IMPL_PHASES = frozenset({"implement", "fix", "ci_fix", "impl_revise"})

_SUBAGENTS: list[SubAgentDefinition] = [CODE_ANALYZER, TEST_WRITER]


# ---------------------------------------------------------------------------
# PHASE_CONFIG
# ---------------------------------------------------------------------------

PHASE_CONFIG: dict[str, PhaseConfig] = {
    "type_detection": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="plan"),
    "hearing": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "analysis": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "plan_brief": PhaseConfig(max_budget_usd=1.0, timeout_sec=300, permission_mode="plan"),
    "design": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="plan"),
    "design_revise": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
        resume=True,
    ),
    "planning": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "split_proposal": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    "fix": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "ci_fix": PhaseConfig(max_budget_usd=3.0, timeout_sec=1200, permission_mode="bypassPermissions"),
    "impl_revise": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
        resume=True,
    ),
}

_DEFAULT_PHASE_CONFIG = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan")


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
    """Claude Code SDK を使用した AgentRunner 実装."""

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

        # Build hooks
        hooks = self._build_hooks()

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

        # Build options
        options = ClaudeCodeOptions(
            cwd=cwd,
            permission_mode=cfg.permission_mode,  # type: ignore[arg-type]
            hooks=hooks,
        )
        if append_prompt:
            options.append_system_prompt = append_prompt

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
        options: ClaudeCodeOptions,
        budget: float,
        subagents: list[SubAgentDefinition],
        phase: str,
    ) -> AgentResult:
        """query() を実行してメッセージを収集し AgentResult を返す."""
        start = time.monotonic()

        messages: list[Message] = [msg async for msg in query(prompt=prompt, options=options)]

        elapsed = time.monotonic() - start

        return self._parse_messages(
            messages,
            elapsed=elapsed,
            budget=budget,
            subagents=subagents,
            phase=phase,
        )

    def _build_hooks(self) -> dict[HookEvent, list[HookMatcher]]:
        """PreToolUse / PostToolUse フックを構成する."""
        pre_hook = HookMatcher(hooks=[self._on_pre_tool_use])
        post_hook = HookMatcher(hooks=[self._on_post_tool_use])
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
        """query() の返却メッセージ群を AgentResult に変換する."""
        result_text = ""
        session_id: str | None = None
        cost: float = 0.0
        tool_uses: list[dict[str, Any]] = []
        duration_ms: int = 0

        for msg in messages:
            # ResultMessage carries session_id, cost, duration
            if isinstance(msg, ResultMessage):
                session_id = msg.session_id
                if msg.total_cost_usd is not None:
                    cost += msg.total_cost_usd
                duration_ms = msg.duration_ms
                if msg.result:
                    result_text += msg.result
                # Check max_turns
                if msg.is_error and msg.subtype == "max_turns":
                    raise MaxTurnsExceededError(session_id=session_id)

            # AssistantMessage carries text blocks and tool use blocks
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        result_text += block.text
                    elif isinstance(block, ToolUseBlock):
                        tool_uses.append({"tool": block.name, "input": block.input})

        # Use SDK-reported duration if available, fall back to wall clock
        final_duration = duration_ms / 1000.0 if duration_ms > 0 else elapsed

        return AgentResult(
            session_id=session_id or "",
            output=result_text,
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
