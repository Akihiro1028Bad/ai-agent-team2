"""機密情報サニタイズ.

EventLogger から抽出した共有モジュール。トークン・パスワード等の機微情報を
ログ出力前にマスクする。EventLogger / AgentLogWriter / API の各層から
``sanitize_dict`` / ``sanitize_text`` を共有する。

公開シンボル:
    SENSITIVE_KEYS: マスク対象のキー名パターン (部分一致)。
    TOKEN_PATTERN: 秘密トークン文字列 (GitHub/Anthropic/OpenAI/AWS/Slack/Google) にマッチする正規表現。
    URL_TOKEN_PATTERN: URL クエリ中の機微パラメータにマッチする正規表現。
    sanitize_dict(data): dict を再帰的にサニタイズして新しい dict を返す。
    sanitize_text(text): 文字列内のトークン・URL 機微パラメータをマスクする。
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "password",
        "secret",
        "authorization",
        "cookie",
        "credential",
    }
)
"""マスク対象のキー名パターン (キー名に部分一致したら値を伏字化)。"""

# 高信頼 (プレフィックス固定・高エントロピー) な秘密トークンのパターン (#112)。
# 過度に広いパターンは正当なテキストを壊す (false positive) ため、必ず固有の
# プレフィックスで固定する。sk-ant- / sk-proj- は legacy sk-…{48} より前に置き、
# 先頭一致で正しく分岐させる。
_SECRET_PATTERNS: tuple[str, ...] = (
    r"ghp_[A-Za-z0-9]{36}",  # GitHub personal access token
    r"gho_[A-Za-z0-9]{36}",  # GitHub OAuth token
    r"github_pat_[A-Za-z0-9_]{82}",  # GitHub fine-grained PAT
    r"sk-ant-[A-Za-z0-9_-]{20,}",  # Anthropic API key
    r"sk-proj-[A-Za-z0-9_-]{20,}",  # OpenAI project key
    r"sk-[A-Za-z0-9]{48}",  # OpenAI legacy key (48 文字固定)
    r"(?:AKIA|ASIA)[0-9A-Z]{16}",  # AWS access key ID
    r"xox[baprs]-[A-Za-z0-9-]{10,}",  # Slack token
    r"AIza[0-9A-Za-z_-]{35}",  # Google API key
)

TOKEN_PATTERN: re.Pattern[str] = re.compile("(" + "|".join(_SECRET_PATTERNS) + ")")
"""秘密トークン文字列にマッチする正規表現 (GitHub / Anthropic / OpenAI / AWS / Slack / Google)。"""

URL_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"([?&])(access_token|token|key|secret|password|credential)=([^&\s]+)")
"""URL クエリ中の機微パラメータにマッチする正規表現。"""

_REDACTED = "***REDACTED***"


def sanitize_text(text: str) -> str:
    """文字列内のトークン・URL 機微パラメータをマスクする.

    Args:
        text: サニタイズ対象の文字列。

    Returns:
        マスク済みの新しい文字列。
    """
    masked = TOKEN_PATTERN.sub(_REDACTED, text)
    return URL_TOKEN_PATTERN.sub(rf"\1\2={_REDACTED}", masked)


def sanitize_dict(data: dict[str, Any]) -> dict[str, Any]:
    """dict を再帰的にサニタイズして新しい dict を返す.

    機微キー名 (SENSITIVE_KEYS に部分一致) の値は伏字化し、文字列値内の
    トークン / URL 機微パラメータもマスクする。元の dict は変更しない
    (イミュータブル方針)。

    Args:
        data: サニタイズ対象の辞書。

    Returns:
        マスク済みの新しい辞書。
    """
    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if any(s in key.lower() for s in SENSITIVE_KEYS):
            sanitized[key] = _REDACTED
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, str):
            sanitized[key] = sanitize_text(value)
        elif isinstance(value, list):
            sanitized[key] = _sanitize_list(value)
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_list(values: list[Any]) -> list[Any]:
    """list 内の dict / str 要素を再帰的にサニタイズする."""
    result: list[Any] = []
    for item in values:
        if isinstance(item, dict):
            result.append(sanitize_dict(item))
        elif isinstance(item, str):
            result.append(sanitize_text(item))
        else:
            result.append(item)
    return result
