"""MCP サーバー設定定義.

フェーズ別に使用する MCP サーバーとツールを一元管理する。
"""

from __future__ import annotations

import os
from typing import Any

# ---------------------------------------------------------------------------
# MCP サーバー定義
# ---------------------------------------------------------------------------

CONTEXT7_SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp@latest"],
}


def _build_github_server() -> dict[str, Any]:
    """GitHub MCP サーバー設定を返す。GITHUB_TOKEN を実行時に解決する。"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise ValueError("GITHUB_TOKEN environment variable is not set. GitHub MCP server requires a valid token.")
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
        },
        "tools": [*CONTEXT7_TOOLS, *SEQUENTIAL_THINKING_TOOLS, *FETCH_TOOLS],
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
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS, *MEMORY_TOOLS],
    },
    "fix": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "github": None,
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS],
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
        },
        "tools": [*CONTEXT7_TOOLS, *GITHUB_TOOLS],
    },
    "design-revise": {
        "servers": {
            "context7": CONTEXT7_SERVER,
            "fetch": FETCH_SERVER,
        },
        "tools": [*CONTEXT7_TOOLS, *FETCH_TOOLS],
    },
}


def get_phase_mcp_config(phase: str) -> tuple[dict[str, Any], list[str]]:
    """フェーズに応じた MCP サーバー設定と allowed_tools を返す.

    Args:
        phase: フェーズ名 (Phase enum の .value と一致)。

    Returns:
        (mcp_servers, mcp_tools) のタプル。
        MCP 未設定のフェーズでは ({}, []) を返す。

    Raises:
        ValueError: GitHub サーバーが必要なフェーズで GITHUB_TOKEN が未設定の場合。
    """
    config = _PHASE_MCP_MAP.get(phase, {})
    if not config:
        return {}, []
    raw_servers: dict[str, Any] = config.get("servers", {})
    # None プレースホルダーを実行時に解決する (GITHUB_TOKEN の遅延評価)
    servers: dict[str, Any] = {
        name: (_build_github_server() if server is None else server) for name, server in raw_servers.items()
    }
    tools: list[str] = config.get("tools", [])
    return servers, tools
