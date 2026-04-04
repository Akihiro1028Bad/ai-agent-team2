"""MCP 設定モジュールのテスト."""

from __future__ import annotations

from ai_agent_orchestrator.agents.mcp_config import (
    CONTEXT7_TOOLS,
    FETCH_TOOLS,
    GITHUB_TOOLS,
    MEMORY_TOOLS,
    SEQUENTIAL_THINKING_TOOLS,
    get_phase_mcp_config,
)


class TestGetPhaseMcpConfig:
    """get_phase_mcp_config のテスト."""

    def test_hearing_has_fetch_and_context7(self) -> None:
        servers, tools = get_phase_mcp_config("hearing")
        assert "fetch" in servers
        assert "context7" in servers
        assert set(FETCH_TOOLS).issubset(set(tools))
        assert set(CONTEXT7_TOOLS).issubset(set(tools))

    def test_design_has_context7_sequential_thinking_fetch(self) -> None:
        servers, tools = get_phase_mcp_config("design")
        assert "context7" in servers
        assert "sequential-thinking" in servers
        assert "fetch" in servers
        assert set(CONTEXT7_TOOLS).issubset(set(tools))
        assert set(SEQUENTIAL_THINKING_TOOLS).issubset(set(tools))

    def test_planning_has_context7_sequential_thinking(self) -> None:
        servers, _tools = get_phase_mcp_config("planning")
        assert "context7" in servers
        assert "sequential-thinking" in servers
        assert "github" not in servers

    def test_implement_has_context7_github_memory(self) -> None:
        servers, tools = get_phase_mcp_config("implement")
        assert "context7" in servers
        assert "github" in servers
        assert "memory" in servers
        assert set(GITHUB_TOOLS).issubset(set(tools))
        assert set(MEMORY_TOOLS).issubset(set(tools))

    def test_ci_fix_has_context7_github(self) -> None:
        servers, _tools = get_phase_mcp_config("ci-fix")
        assert "context7" in servers
        assert "github" in servers
        assert "memory" not in servers

    def test_impl_revise_has_context7_github(self) -> None:
        servers, _tools = get_phase_mcp_config("impl-revise")
        assert "context7" in servers
        assert "github" in servers

    def test_unknown_phase_returns_empty(self) -> None:
        servers, tools = get_phase_mcp_config("nonexistent-phase")
        assert servers == {}
        assert tools == []

    def test_type_detection_returns_empty(self) -> None:
        servers, tools = get_phase_mcp_config("type-detection")
        assert servers == {}
        assert tools == []

    def test_tool_names_follow_mcp_convention(self) -> None:
        """全ツール名が mcp__<server>__<tool> 形式であることを検証."""
        for phase in [
            "hearing",
            "design",
            "planning",
            "implement",
            "ci-fix",
            "impl-revise",
        ]:
            _, tools = get_phase_mcp_config(phase)
            for tool_name in tools:
                parts = tool_name.split("__")
                assert len(parts) == 3, f"{tool_name} は mcp__<server>__<tool> 形式でない"
                assert parts[0] == "mcp", f"{tool_name} は mcp__ で始まっていない"

    def test_analysis_has_context7_sequential_thinking(self) -> None:
        servers, _tools = get_phase_mcp_config("analysis")
        assert "context7" in servers
        assert "sequential-thinking" in servers

    def test_design_revise_has_context7_fetch(self) -> None:
        servers, _tools = get_phase_mcp_config("design-revise")
        assert "context7" in servers
        assert "fetch" in servers

    def test_fix_has_context7_github(self) -> None:
        servers, _tools = get_phase_mcp_config("fix")
        assert "context7" in servers
        assert "github" in servers
