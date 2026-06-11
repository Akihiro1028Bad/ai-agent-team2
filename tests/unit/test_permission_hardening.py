"""権限絞り込み (#101) のテスト.

実装系フェーズの bypassPermissions + 無制限 Bash を多層防御で絞る:

1. ツールポリシー: Bash 不要フェーズは Bash 全面 deny、実装系は
   持ち出し・ネットワーク系コマンドの specifier deny
   (SDK 検証で deny ルールは bypassPermissions 下でも強制されることを確認済み)
2. env 遮断: GITHUB_TOKEN 等の機微変数を空文字で上書きし子プロセスへの
   継承を遮断 (denylist 迂回時の本丸対策)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from ai_agent_orchestrator.agents.claude_runner import (
    _SHELL_ALLOWED_PHASES,
    PHASE_CONFIG,
    ClaudeAgentRunner,
    sanitized_env_overrides,
    tool_policy_for,
)

# ---------------------------------------------------------------------------
# tool_policy_for: フェーズ別 disallowed_tools
# ---------------------------------------------------------------------------


class TestToolPolicyFor:
    """フェーズ別ツールポリシーの導出."""

    @pytest.mark.parametrize("phase", ["intake", "clarify", "split"])
    def test_no_bash_phases_deny_bash_entirely(self, phase: str) -> None:
        """Bash 不要フェーズは Bash を全面 deny する (specifier ではなく完全 deny)."""
        assert tool_policy_for(phase) == ["Bash"]

    @pytest.mark.parametrize("phase", ["plan", "implement", "revise"])
    def test_impl_phases_deny_exfil_commands(self, phase: str) -> None:
        """実装系フェーズは持ち出し・ネットワーク系コマンドを deny する."""
        policy = tool_policy_for(phase)
        # Bash 全面 deny ではない (ビルド・テストは実行できる)
        assert "Bash" not in policy
        # gh: keyring から token を再取得できるため必須 deny
        assert "Bash(gh:*)" in policy
        # ネットワーク持ち出し系
        for cmd in ("curl", "wget", "nc", "ssh", "scp"):
            assert f"Bash({cmd}:*)" in policy
        # commit 一本化 (U1): エージェントは push しない
        assert "Bash(git push:*)" in policy
        # 環境変数の一括読み出し
        assert "Bash(printenv:*)" in policy
        assert "Bash(env:*)" in policy

    def test_unknown_phase_falls_back_to_full_bash_deny(self) -> None:
        """未知フェーズは安全側 (Bash 全面 deny) にフォールバックする."""
        assert tool_policy_for("unknown-phase") == ["Bash"]

    def test_new_phase_added_to_config_is_fail_safe(self) -> None:
        """allowlist 方式: PHASE_CONFIG に新フェーズを足しても全面 deny に倒れる.

        _SHELL_ALLOWED_PHASES へ明示追記しない限り shell は開かない (fail-safe)。
        """
        # PHASE_CONFIG にあるが shell 許可集合に入っていないフェーズは全面 deny
        non_shell_config_phases = set(PHASE_CONFIG) - _SHELL_ALLOWED_PHASES
        for phase in non_shell_config_phases:
            assert tool_policy_for(phase) == ["Bash"], phase

    def test_shell_allowed_phases_are_real_phases(self) -> None:
        """許可集合は実在フェーズのみ (タイポで許可が無効化される事故を検知)."""
        assert set(PHASE_CONFIG) >= _SHELL_ALLOWED_PHASES

    @pytest.mark.parametrize("phase", ["plan", "implement", "revise"])
    def test_impl_phases_deny_interpreters_and_git_commit(self, phase: str) -> None:
        """インタプリタ直接実行と git commit (U1 一本化) も deny する."""
        policy = tool_policy_for(phase)
        for cmd in ("python", "python3", "node", "ruby", "perl"):
            assert f"Bash({cmd}:*)" in policy
        assert "Bash(git commit:*)" in policy

    @pytest.mark.parametrize("phase", ["plan", "implement", "revise"])
    def test_impl_phases_deny_uv_run_interpreter_escape(self, phase: str) -> None:
        """uv run 経由のインタプリタ脱出 (env 読み出し・keyring 直叩き) も deny する.

        uv run pytest / mypy / ruff は許可のまま (deny は uv run python のみ)。
        """
        policy = tool_policy_for(phase)
        assert "Bash(uv run python:*)" in policy
        assert "Bash(uv run python3:*)" in policy
        # 検証系コマンドまで巻き込んでいないこと
        assert "Bash(uv:*)" not in policy
        assert "Bash(uv run pytest:*)" not in policy

    @pytest.mark.parametrize("phase", ["intake", "clarify", "split", "plan", "implement", "revise"])
    def test_policy_is_immutable_per_call(self, phase: str) -> None:
        """呼び出しごとに独立したリストを返す (共有ミューテーション防止)."""
        a = tool_policy_for(phase)
        b = tool_policy_for(phase)
        assert a == b
        assert a is not b


# ---------------------------------------------------------------------------
# sanitized_env_overrides: 機微 env の継承遮断
# ---------------------------------------------------------------------------


class TestSanitizedEnvOverrides:
    """機微環境変数の空文字上書き."""

    def test_blanks_github_tokens(self) -> None:
        overrides = sanitized_env_overrides()
        for var in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
            assert overrides[var] == ""

    def test_blanks_slack_webhook(self) -> None:
        assert sanitized_env_overrides()["SLACK_WEBHOOK_URL"] == ""

    def test_blanks_claude_code_oauth_token(self) -> None:
        """Claude アカウントのフル権限トークンも遮断する (現運用は keychain 認証)."""
        assert sanitized_env_overrides()["CLAUDE_CODE_OAUTH_TOKEN"] == ""

    def test_does_not_touch_anthropic_auth(self) -> None:
        """ANTHROPIC_API_KEY は CLI 自体の認証に必要なため遮断しない."""
        assert "ANTHROPIC_API_KEY" not in sanitized_env_overrides()

    def test_returns_fresh_dict(self) -> None:
        a = sanitized_env_overrides()
        b = sanitized_env_overrides()
        assert a == b
        assert a is not b


# ---------------------------------------------------------------------------
# run() がオプションへポリシーを配線すること
# ---------------------------------------------------------------------------


def _fake_result_message() -> Any:
    from claude_agent_sdk.types import ResultMessage

    return ResultMessage(
        subtype="success",
        duration_ms=10,
        duration_api_ms=10,
        is_error=False,
        num_turns=1,
        session_id="sess-hardening",
        total_cost_usd=0.01,
        usage={},
        result="done",
    )


@pytest.fixture
def runner() -> ClaudeAgentRunner:
    return ClaudeAgentRunner(tracker=AsyncMock())


async def test_run_wires_policy_for_no_bash_phase(
    runner: ClaudeAgentRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """intake 実行時: Bash 全面 deny + env 遮断がオプションに載る."""
    captured: list[Any] = []

    async def fake_query(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        captured.append(options)
        yield _fake_result_message()

    monkeypatch.setattr("ai_agent_orchestrator.agents.claude_runner.query", fake_query)

    await runner.run(prompt="analyze", cwd="/tmp/wt", phase="intake")

    opts = captured[0]
    assert "Bash" in opts.disallowed_tools
    assert opts.env["GITHUB_TOKEN"] == ""


async def test_run_wires_policy_for_implement_phase(
    runner: ClaudeAgentRunner,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """implement 実行時: specifier deny + env 遮断がオプションに載る."""
    captured: list[Any] = []

    async def fake_query(*, prompt: str, options: Any = None, transport: Any = None) -> Any:
        captured.append(options)
        yield _fake_result_message()

    monkeypatch.setattr("ai_agent_orchestrator.agents.claude_runner.query", fake_query)

    await runner.run(prompt="implement", cwd="/tmp/wt", phase="implement")

    opts = captured[0]
    assert "Bash" not in opts.disallowed_tools
    assert "Bash(gh:*)" in opts.disallowed_tools
    assert "Bash(git push:*)" in opts.disallowed_tools
    assert opts.env["GITHUB_TOKEN"] == ""
    assert opts.env["SLACK_WEBHOOK_URL"] == ""
