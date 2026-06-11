"""sanitize モジュールの単体テスト + EventLogger 互換確認."""

from __future__ import annotations

from pathlib import Path

from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.sanitize import (
    SENSITIVE_KEYS,
    TOKEN_PATTERN,
    URL_TOKEN_PATTERN,
    sanitize_dict,
    sanitize_text,
)


# ──────────────────────────────────────
# sanitize_text
# ──────────────────────────────────────
def test_sanitize_text_masks_github_token() -> None:
    token = "ghp_" + "a" * 36
    assert sanitize_text(f"my token is {token}") == "my token is ***REDACTED***"


def test_sanitize_text_no_match_passthrough() -> None:
    assert sanitize_text("plain text") == "plain text"


# ──────────────────────────────────────
# sanitize_dict
# ──────────────────────────────────────
def test_sanitize_dict_masks_sensitive_key() -> None:
    out = sanitize_dict({"token": "abc", "name": "ok"})
    assert out == {"token": "***REDACTED***", "name": "ok"}


def test_sanitize_dict_masks_nested() -> None:
    out = sanitize_dict({"outer": {"password": "p", "v": 1}})
    assert out == {"outer": {"password": "***REDACTED***", "v": 1}}


def test_sanitize_dict_masks_url_token_in_value() -> None:
    out = sanitize_dict({"url": "https://x?access_token=secret123&a=1"})
    assert out == {"url": "https://x?access_token=***REDACTED***&a=1"}


def test_sanitize_dict_masks_list_of_strings() -> None:
    token = "gho_" + "b" * 36
    out = sanitize_dict({"items": [token, "plain", {"secret": "s"}]})
    assert out == {"items": ["***REDACTED***", "plain", {"secret": "***REDACTED***"}]}


def test_sanitize_dict_returns_new_object() -> None:
    original = {"name": "ok", "nested": {"v": 1}}
    out = sanitize_dict(original)
    assert out is not original
    assert out["nested"] is not original["nested"]


# ──────────────────────────────────────
# EventLogger 互換 (委譲後もクラス属性 / 挙動が同一)
# ──────────────────────────────────────
def test_event_logger_class_attrs_preserved() -> None:
    assert EventLogger.SENSITIVE_KEYS == SENSITIVE_KEYS
    assert EventLogger.TOKEN_PATTERN is TOKEN_PATTERN
    assert EventLogger.URL_TOKEN_PATTERN is URL_TOKEN_PATTERN


def test_event_logger_sanitize_delegates(tmp_path: Path) -> None:
    logger = EventLogger(log_dir=tmp_path / "logs")
    data = {"token": "x", "msg": "ghp_" + "c" * 36}
    out = logger._sanitize_for_log(data)
    assert out == {"token": "***REDACTED***", "msg": "***REDACTED***"}
