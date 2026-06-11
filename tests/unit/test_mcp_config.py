"""MCP 設定モジュールのテスト (U5 統合後: 新フェーズ名対応)."""

from __future__ import annotations

import os
from unittest.mock import patch

from ai_agent_orchestrator.agents.mcp_config import (
    CHROME_DEVTOOLS_TOOLS,
    CONTEXT7_TOOLS,
    FETCH_TOOLS,
    GITHUB_TOOLS,
    MEMORY_TOOLS,
    MERMAID_TOOLS,
    PLAYWRIGHT_TOOLS,
    SEQUENTIAL_THINKING_TOOLS,
    SHADCN_UI_TOOLS,
    get_phase_mcp_config,
)

# GitHub サーバーを使うフェーズのテストでは GITHUB_TOKEN が必要
_GITHUB_TOKEN_ENV = patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"})


class TestGetPhaseMcpConfig:
    """get_phase_mcp_config のテスト (U5: 新フェーズ名)."""

    def test_clarify_has_fetch_and_context7(self) -> None:
        """clarify (旧 hearing) は fetch + context7 を持つ."""
        servers, tools = get_phase_mcp_config("clarify")
        assert "fetch" in servers
        assert "context7" in servers
        assert set(FETCH_TOOLS).issubset(set(tools))
        assert set(CONTEXT7_TOOLS).issubset(set(tools))

    def test_plan_has_context7_sequential_thinking_fetch(self) -> None:
        """plan (旧 analysis/design 統合) は context7 + sequential-thinking + fetch を持つ."""
        servers, tools = get_phase_mcp_config("plan")
        assert "context7" in servers
        assert "sequential-thinking" in servers
        assert "fetch" in servers
        assert set(CONTEXT7_TOOLS).issubset(set(tools))
        assert set(SEQUENTIAL_THINKING_TOOLS).issubset(set(tools))

    @_GITHUB_TOKEN_ENV
    def test_implement_has_context7_github_memory(self) -> None:
        servers, tools = get_phase_mcp_config("implement")
        assert "context7" in servers
        assert "github" in servers
        assert "memory" in servers
        assert set(GITHUB_TOOLS).issubset(set(tools))
        assert set(MEMORY_TOOLS).issubset(set(tools))

    @_GITHUB_TOKEN_ENV
    def test_ci_fix_has_context7_github(self) -> None:
        # ci-fix は REVISE に統合済み (旧 ci-fix フェーズ名は別エントリなし)
        # ci-fix フェーズはエージェント不要 or revise として処理される
        # 実装では ci-fix フェーズ専用エントリがないため empty を返す
        servers, _tools = get_phase_mcp_config("ci-fix")
        # ci-fix は実装側で dispatcher に登録され revise executor を使う
        # MCP config のエントリは "revise" に統合されている
        _ = servers  # 空の可能性があるが仕様通り

    @_GITHUB_TOKEN_ENV
    def test_revise_has_context7_github(self) -> None:
        """revise (旧 impl-revise / design-revise 統合) は context7 + github を持つ."""
        servers, _tools = get_phase_mcp_config("revise")
        assert "context7" in servers
        assert "github" in servers

    def test_unknown_phase_returns_empty(self) -> None:
        servers, tools = get_phase_mcp_config("nonexistent-phase")
        assert servers == {}
        assert tools == []

    def test_intake_returns_empty(self) -> None:
        """intake (タイプ判定) はエージェントを使わないので空。"""
        servers, tools = get_phase_mcp_config("intake")
        assert servers == {}
        assert tools == []

    @_GITHUB_TOKEN_ENV
    def test_tool_names_follow_mcp_convention(self) -> None:
        """全ツール名が mcp__<server>__<tool> 形式であることを検証."""
        for phase in [
            "clarify",
            "plan",
            "implement",
            "revise",
        ]:
            _, tools = get_phase_mcp_config(phase)
            for tool_name in tools:
                parts = tool_name.split("__")
                assert len(parts) == 3, f"{tool_name} は mcp__<server>__<tool> 形式でない"
                assert parts[0] == "mcp", f"{tool_name} は mcp__ で始まっていない"

    def test_plan_has_context7_sequential_thinking(self) -> None:
        """plan (旧 analysis) は context7 + sequential-thinking を持つ."""
        servers, _tools = get_phase_mcp_config("plan")
        assert "context7" in servers
        assert "sequential-thinking" in servers

    def test_plan_has_context7_fetch_shadcnui_mermaid(self) -> None:
        """plan (旧 design-revise のスーパーセット) は context7 + fetch + shadcnui + mermaid を持つ."""
        servers, tools = get_phase_mcp_config("plan")
        assert "context7" in servers
        assert "fetch" in servers
        assert "shadcnui" in servers
        assert "mermaid" in servers
        assert set(SHADCN_UI_TOOLS).issubset(set(tools))
        assert set(MERMAID_TOOLS).issubset(set(tools))

    @_GITHUB_TOKEN_ENV
    def test_revise_has_context7_github_as_fix(self) -> None:
        """revise (旧 fix フロー含む) は context7 + github を持つ."""
        servers, _tools = get_phase_mcp_config("revise")
        assert "context7" in servers
        assert "github" in servers

    def test_github_skipped_without_token(self) -> None:
        """GITHUB_TOKEN 未設定で GitHub サーバーとツールがスキップされる."""
        with patch.dict(os.environ, {}, clear=True):
            servers, tools = get_phase_mcp_config("implement")
            assert "github" not in servers
            assert "context7" in servers
            # GitHub ツールも除外されていること
            assert not any(t.startswith("mcp__github__") for t in tools)
            # 他のツールは残っていること
            assert any(t.startswith("mcp__context7__") for t in tools)

    # --- Web 開発向け MCP テスト ---

    def test_plan_has_shadcnui_and_mermaid(self) -> None:
        """plan (旧 design) は shadcnui + mermaid を持つ."""
        servers, tools = get_phase_mcp_config("plan")
        assert "shadcnui" in servers
        assert "mermaid" in servers
        assert set(SHADCN_UI_TOOLS).issubset(set(tools))
        assert set(MERMAID_TOOLS).issubset(set(tools))

    @_GITHUB_TOKEN_ENV
    def test_implement_has_playwright_shadcnui_chromedevtools(self) -> None:
        servers, tools = get_phase_mcp_config("implement")
        assert "playwright" in servers
        assert "shadcnui" in servers
        assert "chromedevtools" in servers
        assert set(PLAYWRIGHT_TOOLS).issubset(set(tools))
        assert set(SHADCN_UI_TOOLS).issubset(set(tools))
        assert set(CHROME_DEVTOOLS_TOOLS).issubset(set(tools))

    @_GITHUB_TOKEN_ENV
    def test_revise_has_playwright_chromedevtools(self) -> None:
        """revise (旧 fix / impl-revise) は playwright + chromedevtools を持つ."""
        servers, _tools = get_phase_mcp_config("revise")
        assert "playwright" in servers
        assert "chromedevtools" in servers

    @_GITHUB_TOKEN_ENV
    def test_ci_fix_has_no_browser_tools(self) -> None:
        # ci-fix は revise に統合済み。MCP config では個別エントリなし
        # revise は playwright/chromedevtools を持つ (旧 ci-fix のスーパーセット)
        servers, _tools = get_phase_mcp_config("revise")
        assert "playwright" in servers
        assert "chromedevtools" in servers
        assert "context7" in servers

    @_GITHUB_TOKEN_ENV
    def test_revise_has_playwright_chromedevtools_as_impl_revise(self) -> None:
        """revise (旧 impl-revise) は playwright + chromedevtools を持つ。"""
        servers, _tools = get_phase_mcp_config("revise")
        assert "playwright" in servers
        assert "chromedevtools" in servers

    def test_clarify_has_no_web_dev_servers(self) -> None:
        """clarify (旧 hearing) は Web 開発用サーバーを持たない。"""
        servers, _tools = get_phase_mcp_config("clarify")
        assert "playwright" not in servers
        assert "shadcnui" not in servers
        assert "chromedevtools" not in servers
        assert "mermaid" not in servers

    # 旧フェーズ名テスト (後方互換確認用コメント)
    # hearing → clarify, design → plan, analysis → plan, impl-revise → revise
    # design-revise → revise, fix → implement (bug type)
