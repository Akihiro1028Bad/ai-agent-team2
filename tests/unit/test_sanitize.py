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
# sanitize_text — 追加プロバイダの秘密 (#112)
# ──────────────────────────────────────
def test_sanitize_text_masks_anthropic_key() -> None:
    key = "sk-ant-api03-" + "A1b2C3d4_" * 11  # sk-ant- + 十分長い高エントロピー
    assert sanitize_text(f"key={key} done") == "key=***REDACTED*** done"


def test_sanitize_text_masks_openai_project_key() -> None:
    key = "sk-proj-" + "Xy9_" * 10
    assert sanitize_text(f"use {key}") == "use ***REDACTED***"


def test_sanitize_text_masks_openai_legacy_key() -> None:
    key = "sk-" + "a1B2c3D4" * 6  # sk- + 48 英数字
    assert sanitize_text(key) == "***REDACTED***"


def test_sanitize_text_masks_aws_access_key_id() -> None:
    assert sanitize_text("AKIAIOSFODNN7EXAMPLE here") == "***REDACTED*** here"
    assert sanitize_text("ASIAIOSFODNN7EXAMPLE here") == "***REDACTED*** here"


def test_sanitize_text_masks_slack_token() -> None:
    token = "xoxb-" + "123456789012-" + "abcdefABCDEF0123"
    assert sanitize_text(f"slack {token}") == "slack ***REDACTED***"


def test_sanitize_text_masks_google_api_key() -> None:
    key = "AIza" + "Bc0_-" * 7  # AIza + 35 文字
    assert sanitize_text(f"g={key}") == "g=***REDACTED***"


# ──────────────────────────────────────
# false positive 回避 (#112): 通常文・短い断片はマスクしない
# ──────────────────────────────────────
def test_sanitize_text_does_not_mask_plain_hyphenated_words() -> None:
    text = "task-management sk-helper xoxb-123 plain-english-sentence"
    assert sanitize_text(text) == text


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
