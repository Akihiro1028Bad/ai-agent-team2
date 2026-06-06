"""logging_config モジュールのテスト."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from ai_agent_orchestrator.logging_config import (
    ENV_LOG_LEVEL,
    configure_logging,
    resolve_level,
)


@pytest.fixture(autouse=True)
def _restore_root_logger() -> Iterator[None]:
    """各テストの前後でルートロガーの状態を保存・復元する."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    quiet_names = ("httpx", "httpcore", "githubkit", "urllib3")
    saved_quiet = {name: logging.getLogger(name).level for name in quiet_names}
    root.handlers = []
    try:
        yield
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        for name, lvl in saved_quiet.items():
            logging.getLogger(name).setLevel(lvl)


# ---------------------------------------------------------------------------
# resolve_level
# ---------------------------------------------------------------------------


def test_resolve_level_defaults_to_info() -> None:
    assert resolve_level(env={}) == logging.INFO


def test_resolve_level_verbose_means_debug() -> None:
    assert resolve_level(verbose=True, env={}) == logging.DEBUG


def test_resolve_level_explicit_log_level_string() -> None:
    assert resolve_level(log_level="WARNING", env={}) == logging.WARNING


def test_resolve_level_explicit_is_case_insensitive() -> None:
    assert resolve_level(log_level="debug", env={}) == logging.DEBUG


def test_resolve_level_env_var_used() -> None:
    assert resolve_level(env={ENV_LOG_LEVEL: "ERROR"}) == logging.ERROR


def test_resolve_level_explicit_overrides_env_and_verbose() -> None:
    # 明示 log_level が最優先
    assert resolve_level(verbose=True, log_level="WARNING", env={ENV_LOG_LEVEL: "ERROR"}) == logging.WARNING


def test_resolve_level_env_overrides_verbose() -> None:
    assert resolve_level(verbose=True, env={ENV_LOG_LEVEL: "ERROR"}) == logging.ERROR


def test_resolve_level_invalid_falls_back_to_info() -> None:
    assert resolve_level(log_level="NONSENSE", env={}) == logging.INFO


# ---------------------------------------------------------------------------
# configure_logging
# ---------------------------------------------------------------------------


def test_console_handler_is_added() -> None:
    configure_logging(level=logging.INFO)
    root = logging.getLogger()
    stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) >= 1


def test_rotating_file_handler_added_with_path(tmp_path: Path) -> None:
    configure_logging(level=logging.INFO, log_dir=tmp_path)
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == (tmp_path / "orchestrator.log")


def test_no_file_handler_without_log_dir() -> None:
    configure_logging(level=logging.INFO)
    root = logging.getLogger()
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert not file_handlers


def test_file_captures_debug_even_when_console_info(tmp_path: Path) -> None:
    """コンソール INFO でもファイルは DEBUG を記録する (root が DEBUG になる)."""
    configure_logging(level=logging.INFO, log_dir=tmp_path)
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    # コンソールハンドラは INFO、ファイルハンドラは DEBUG
    console = next(
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
    )
    file_handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
    assert console.level == logging.INFO
    assert file_handler.level == logging.DEBUG


def test_debug_message_written_to_file(tmp_path: Path) -> None:
    configure_logging(level=logging.INFO, log_dir=tmp_path)
    logging.getLogger("ai_agent_orchestrator.test").debug("hidden-debug-marker")
    for h in logging.getLogger().handlers:
        h.flush()
    content = (tmp_path / "orchestrator.log").read_text(encoding="utf-8")
    assert "hidden-debug-marker" in content


def test_format_includes_funcname_and_lineno(tmp_path: Path) -> None:
    configure_logging(level=logging.DEBUG, log_dir=tmp_path)
    for h in logging.getLogger().handlers:
        fmt = h.formatter._fmt if h.formatter else ""
        assert "%(funcName)s" in fmt
        assert "%(lineno)d" in fmt


def test_quiet_loggers_set_to_warning() -> None:
    for name in ("httpx", "httpcore", "githubkit"):
        logging.getLogger(name).setLevel(logging.DEBUG)
    configure_logging(level=logging.DEBUG)
    for name in ("httpx", "httpcore", "githubkit"):
        assert logging.getLogger(name).level == logging.WARNING


def test_idempotent_no_duplicate_handlers(tmp_path: Path) -> None:
    """複数回呼んでもハンドラが重複しない."""
    configure_logging(level=logging.INFO, log_dir=tmp_path)
    configure_logging(level=logging.DEBUG, log_dir=tmp_path)
    root = logging.getLogger()
    stream_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
    ]
    file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(stream_handlers) == 1
    assert len(file_handlers) == 1


def test_string_level_accepted() -> None:
    configure_logging(level="DEBUG")
    console = next(h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler))
    assert console.level == logging.DEBUG
