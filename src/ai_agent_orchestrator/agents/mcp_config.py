"""MCP サーバー設定定義.

フェーズ別に使用する MCP サーバーとツールを一元管理する。
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP サーバー定義
# ---------------------------------------------------------------------------

CONTEXT7_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp@latest"],
}


def _build_github_server() -> dict[str, Any] | None:
    """GitHub MCP サーバー設定を返す。GITHUB_TOKEN を実行時に解決する。

    Returns:
        サーバー設定辞書。GITHUB_TOKEN 未設定時は None (スキップ)。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        logger.warning("GITHUB_TOKEN が未設定のため GitHub MCP サーバーをスキップします")
        return None
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
    }


SEQUENTIAL_THINKING_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
}

MEMORY_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-memory"],
}

FETCH_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-fetch"],
}

PLAYWRIGHT_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@playwright/mcp@latest"],
}

# TODO: npm パッケージ名を実環境で検証すること (npx 失敗時はサーバー単体がスキップされる)
SHADCN_UI_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@anthropic-ai/shadcn-ui-mcp@latest"],
}

CHROME_DEVTOOLS_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@anthropic-ai/chrome-devtools-mcp@latest"],
}

MERMAID_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "mermaid-mcp-server"],
}

# ---------------------------------------------------------------------------
# MCP ツール名定義
# ---------------------------------------------------------------------------

CONTEXT7_TOOLS: list[str] = [
    "mcp__context7__resolve-library-id",
    "mcp__context7__query-docs",
]

GITHUB_TOOLS: list[str] = [
    "mcp__github__search_code",
    "mcp__github__search_issues",
    "mcp__github__get_file_contents",
    "mcp__github__list_commits",
    "mcp__github__get_issue",
    "mcp__github__list_issues",
    "mcp__github__get_pull_request",
    "mcp__github__get_pull_request_files",
    "mcp__github__get_pull_request_comments",
]

SEQUENTIAL_THINKING_TOOLS: list[str] = [
    "mcp__sequentialthinking__sequentialthinking",
]

MEMORY_TOOLS: list[str] = [
    "mcp__memory__create_entities",
    "mcp__memory__search_nodes",
    "mcp__memory__open_nodes",
    "mcp__memory__create_relations",
    "mcp__memory__add_observations",
]

FETCH_TOOLS: list[str] = [
    "mcp__fetch__fetch",
]

PLAYWRIGHT_TOOLS: list[str] = [
    "mcp__playwright__browser_navigate",
    "mcp__playwright__browser_take_screenshot",
    "mcp__playwright__browser_snapshot",
    "mcp__playwright__browser_click",
    "mcp__playwright__browser_fill",
    "mcp__playwright__browser_hover",
    "mcp__playwright__browser_press_key",
    "mcp__playwright__browser_close",
    "mcp__playwright__browser_evaluate",
    "mcp__playwright__browser_wait_for",
]

SHADCN_UI_TOOLS: list[str] = [
    "mcp__shadcnui__get_component",
    "mcp__shadcnui__list_components",
    "mcp__shadcnui__get_block",
    "mcp__shadcnui__list_blocks",
    "mcp__shadcnui__get_theme",
]

CHROME_DEVTOOLS_TOOLS: list[str] = [
    "mcp__chromedevtools__take_screenshot",
    "mcp__chromedevtools__navigate_page",
    "mcp__chromedevtools__lighthouse_audit",
    "mcp__chromedevtools__evaluate_script",
    "mcp__chromedevtools__click",
    "mcp__chromedevtools__list_network_requests",
    "mcp__chromedevtools__take_snapshot",
]

MERMAID_TOOLS: list[str] = [
    "mcp__mermaid__mermaid_preview",
    "mcp__mermaid__mermaid_save",
]

# ---------------------------------------------------------------------------
# フェーズ別 MCP 設定マッピング
# ---------------------------------------------------------------------------

_PHASE_MCP_MAP: dict[str, dict[str, Any]] = {
    "hearing": {
        "servers": {"fetch": FETCH_SERVER, "context7": CONTEXT7_SERVER},
        "tools": [*FETCH_TOOLS, *CONTEXT7_TOOLS],
    },
    "analysis": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "sequential-thinking": SEQUENTIAL_THINKING_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *SEQUENTIAL_THINKING_TOOLS],
    },
    "design": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "sequential-thinking": SEQUENTIAL_THINKING_SERVER,
            "fetch": FETCH_SERVER,
            "shadcnui": SHADCN_UI_SERVER,
            "mermaid": MERMAID_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *SEQUENTIAL_THINKING_TOOLS, *FETCH_TOOLS, *SHADCN_UI_TOOLS, *MERMAID_TOOLS],
    },
    "planning": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "sequential-thinking": SEQUENTIAL_THINKING_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *SEQUENTIAL_THINKING_TOOLS],
    },
    "implement": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "github": None,  # _build_github_server() で実行時に解決
            "memory": MEMORY_SERVER,
            "playwright": PLAYWRIGHT_SERVER,
            "shadcnui": SHADCN_UI_SERVER,
            "chromedevtools": CHROME_DEVTOOLS_SERVER,
        },
        "tools": [
            *CONTEXT7_TOOLS,
            *GITHUB_TOOLS,
            *MEMORY_TOOLS,
            *PLAYWRIGHT_TOOLS,
            *SHADCN_UI_TOOLS,
            *CHROME_DEVTOOLS_TOOLS,
        ],
    },
    "fix": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "github": None,
            "playwright": PLAYWRIGHT_SERVER,
            "chromedevtools": CHROME_DEVTOOLS_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS, *PLAYWRIGHT_TOOLS, *CHROME_DEVTOOLS_TOOLS],
    },
    "ci-fix": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "github": None,
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS],
    },
    "impl-revise": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "github": None,
            "playwright": PLAYWRIGHT_SERVER,
            "chromedevtools": CHROME_DEVTOOLS_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS, *PLAYWRIGHT_TOOLS, *CHROME_DEVTOOLS_TOOLS],
    },
    "design-revise": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "fetch": FETCH_SERVER,
            "shadcnui": SHADCN_UI_SERVER,
            "mermaid": MERMAID_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *FETCH_TOOLS, *SHADCN_UI_TOOLS, *MERMAID_TOOLS],
    },
}


def get_phase_mcp_config(phase: str) -> tuple[dict[str, Any], list[str]]:
    """フェーズに応じた MCP サーバー設定と allowed_tools を返す.

    Args:
        phase: フェーズ名 (Phase enum の .value と一致)。

    Returns:
        (mcp_servers, mcp_tools) のタプル。
        MCP 未設定のフェーズでは ({}, []) を返す。

    """
    config = _PHASE_MCP_MAP.get(phase, {})
    if not config:
        return {}, []
    raw_servers: dict[str, Any] = config.get("servers", {})
    # None プレースホルダーを実行時に解決する (GITHUB_TOKEN の遅延評価)
    resolved: dict[str, Any] = {}
    for name, server in raw_servers.items():
        if server is None:
            built = _build_github_server()
            if built is not None:
                resolved[name] = built
            # None の場合はスキップ (トークン未設定)
        else:
            resolved[name] = copy.deepcopy(server)
    all_tools: list[str] = config.get("tools", [])
    # スキップされたサーバーのツールを除外する
    resolved_names = set(resolved.keys())
    skipped_names = set(raw_servers.keys()) - resolved_names
    if skipped_names:
        skipped_prefixes = tuple(f"mcp__{n.replace('-', '')}__" for n in skipped_names)
        tools = [t for t in all_tools if not t.startswith(skipped_prefixes)]
    else:
        tools = list(all_tools)
    return resolved, tools
