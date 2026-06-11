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
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)

from ai_agent_orchestrator.agents.mcp_config import get_phase_mcp_config
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

_IMPL_PHASES = frozenset({"implement", "revise"})

_SUBAGENTS: list[SubAgentDefinition] = [CODE_ANALYZER, TEST_WRITER]


# ---------------------------------------------------------------------------
# PHASE_CONFIG
# ---------------------------------------------------------------------------

PHASE_CONFIG: dict[str, PhaseConfig] = {
    # キーは Phase enum の .value と一致させる (ハイフン区切り)。U5 (#83) 統一パイプライン
    "intake": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="bypassPermissions"),
    "clarify": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="bypassPermissions"),
    # PLAN は light (旧 analysis) / full (旧 design) を包含するため上限は旧 design 相当
    "plan": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "split": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="bypassPermissions"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    # REVISE はレビュー対応 (旧 impl-revise) と CI 修正 (旧 ci-fix) を包含
    "revise": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
        resume=True,
    ),
}

_DEFAULT_PHASE_CONFIG = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="bypassPermissions")

_BYPASS_ALLOWED_TOOLS = [
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Bash",
    "TodoWrite",
]


# ---------------------------------------------------------------------------
# 権限絞り込み (#101)
# ---------------------------------------------------------------------------
#
# SDK 実機検証の結果:
# - bypassPermissions / default (headless) とも allowed_tools の specifier に
#   よる「許可リスト」制限は強制されない
# - disallowed_tools の deny ルールは bypassPermissions 下でも specifier 単位で
#   強制される
# よって deny ルール + env 遮断の多層防御を採る。deny は `bash -c` 等で迂回
# され得る抑止層であり、秘密保護の本丸は sanitized_env_overrides による遮断。

_NO_BASH_PHASES = frozenset({"intake", "clarify", "split"})
"""Bash 不要フェーズ。分析・対話のみで shell 実行を要しない。"""

_BASH_DENY_SPECIFIERS = [
    # gh: keyring から `gh auth token` で token を再取得できるため必須 deny
    "Bash(gh:*)",
    # ネットワーク持ち出し系
    "Bash(curl:*)",
    "Bash(wget:*)",
    "Bash(nc:*)",
    "Bash(ncat:*)",
    "Bash(ssh:*)",
    "Bash(scp:*)",
    "Bash(rsync:*)",
    # commit/push 一本化 (U1): commit/push は orchestrator が行う
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git remote:*)",
    # 環境変数の一括読み出し
    "Bash(printenv:*)",
    "Bash(env:*)",
    # インタプリタ直接実行 (one-liner での env 読み出し→外部送信を抑止)
    "Bash(python:*)",
    "Bash(python3:*)",
    "Bash(node:*)",
    "Bash(ruby:*)",
    "Bash(perl:*)",
    # uv run 経由のインタプリタ脱出 (keyring 直叩き・env 一括読み出し対策)。
    # 検証系 (uv run pytest / mypy / ruff) は許可のまま
    "Bash(uv run python:*)",
    "Bash(uv run python3:*)",
]
"""実装系フェーズで deny する Bash コマンド (ビルド・テストは許可)。"""

_SENSITIVE_ENV_VARS = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_PAT",
    "SLACK_WEBHOOK_URL",
    # Claude アカウントのフル権限トークン。現運用 (macOS keychain 認証) では
    # 未設定のため遮断は無害。fail-closed: ヘッドレス運用がこの env に依存する
    # 場合はエージェントが認証失敗で即顕在化する
    "CLAUDE_CODE_OAUTH_TOKEN",
)
"""子プロセスへの継承を遮断する機微環境変数。

ANTHROPIC_API_KEY は CLI 自体の認証に必要なため対象外。
TODO(#101): ANTHROPIC_API_KEY はエージェントの Bash からも読める状態が残る
ため、CLI へのトークン注入手段が整い次第、遮断対象への追加を再評価する。
TODO(#92): ヘッドレス運用 (WSL2) で CLAUDE_CODE_OAUTH_TOKEN による CLI 認証を
採る場合は、遮断との両立 (keychain 相当の注入手段) を設計してから外すこと。
"""


def tool_policy_for(phase: str) -> list[str]:
    """フェーズに応じた disallowed_tools ポリシーを返す (#101).

    Bash 不要フェーズと未知フェーズは Bash 全面 deny、実装系フェーズは
    持ち出し・ネットワーク系コマンドの specifier deny を返す。

    Args:
        phase: フェーズ名 (Phase enum の .value)。

    Returns:
        disallowed_tools に渡す deny ルールのリスト (毎回新規生成)。
    """
    if phase in _NO_BASH_PHASES or phase not in PHASE_CONFIG:
        return ["Bash"]
    return list(_BASH_DENY_SPECIFIERS)


def sanitized_env_overrides() -> dict[str, str]:
    """機微環境変数を空文字で上書きする env マップを返す (#101).

    ClaudeAgentOptions.env に渡すことで、エージェント子プロセスへの
    機微変数の継承を遮断する。deny ルールが迂回された場合の本丸対策。

    Returns:
        {変数名: ""} のマップ (毎回新規生成)。
    """
    return dict.fromkeys(_SENSITIVE_ENV_VARS, "")


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

        # NOTE(#101): 旧「アクティブクライアント経由の resume」分岐は撤去した。
        # _active_sessions は populate されない死にコードで、もし将来復活させると
        # 下記のポリシー配線 (disallowed_tools / env 遮断) を素通りする経路になる。
        # resume を実装する場合は必ず options 構築パスを通すこと。

        # Build options (max_turns はSDKデフォルトに委任)
        mcp_servers, mcp_tools = get_phase_mcp_config(phase)
        options = ClaudeAgentOptions(
            cwd=cwd,
            permission_mode=cfg.permission_mode,  # type: ignore[arg-type]
            hooks=hooks,  # type: ignore[arg-type]
            max_budget_usd=budget,
            model=cfg.model,
            # 権限絞り込み (#101): deny ルールは bypassPermissions 下でも強制される
            disallowed_tools=tool_policy_for(phase),
            # 機微 env の継承遮断 (#101)
            env=sanitized_env_overrides(),
        )
        # MCP サーバーを設定
        if mcp_servers:
            options.mcp_servers = mcp_servers
        # 実装系フェーズでは allowed_tools を明示的に設定
        if cfg.permission_mode == "bypassPermissions":
            all_tools = list(_BYPASS_ALLOWED_TOOLS)
            if mcp_tools:
                all_tools.extend(mcp_tools)
            options.allowed_tools = all_tools
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
                    # Claude SDK が未知のメッセージタイプを受信した場合のリトライ
                    # (Claude API のオーバーロード時にストリームが不完全な形で終了することがある)
                    has_text = any(
                        isinstance(m, AssistantMessage) and any(isinstance(b, TextBlock) for b in m.content)
                        for m in all_messages
                    )
                    if has_text:
                        logger.info(
                            "sdk_unknown_message on attempt %d/%d: TextBlock found, proceeding (error=%s, messages=%d)",
                            attempt + 1,
                            max_retries,
                            str(e)[:200],
                            len(all_messages),
                        )
                        break

                    if attempt < max_retries - 1:
                        wait = 60.0 * (2**attempt)  # 60s, 120s exponential backoff
                        logger.warning(
                            "sdk_unknown_message on attempt %d/%d: no TextBlock yet,"
                            " retrying in %.0fs (error=%s, messages=%d)",
                            attempt + 1,
                            max_retries,
                            wait,
                            str(e)[:200],
                            len(all_messages),
                        )
                        await asyncio.sleep(wait)
                    else:
                        logger.error(
                            "sdk_unknown_message on attempt %d/%d: max retries reached"
                            " with no TextBlock (error=%s, messages=%d)",
                            attempt + 1,
                            max_retries,
                            str(e)[:200],
                            len(all_messages),
                        )
                else:
                    raise  # re-raise non-sdk-unknown-message errors

        elapsed = time.monotonic() - start
        logger.info(
            "SDK query complete: %d messages collected in %.1fs",
            len(all_messages),
            elapsed,
        )

        result = self._parse_messages(
            all_messages,
            elapsed=elapsed,
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
