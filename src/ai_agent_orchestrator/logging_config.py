"""ロギングの一元設定.

コンソール出力とローテーション付きファイル出力を一括設定する。
デバッグ時にログレベルを切り替えられ、発生箇所 (ファイル名・行番号・関数名)
を含む詳細なフォーマットで出力する。

設計方針:
    - コンソール: 指定レベル (デフォルト INFO)。`--verbose` や環境変数で DEBUG 可
    - ファイル: 常に DEBUG を記録 (ローテーションで上限管理) → あとから見返せる
    - 外部ライブラリ (httpx 等) は WARNING に下げてノイズを抑制
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Mapping, Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path

# 発生箇所を特定できるよう name:lineno funcName を含める
_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(funcName)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: ログレベルを指定する環境変数名 (例: AI_AGENT_LOG_LEVEL=DEBUG)
ENV_LOG_LEVEL = "AI_AGENT_LOG_LEVEL"

#: DEBUG 時に大量のログを出してノイズになる外部ライブラリ
_DEFAULT_QUIET_LOGGERS: tuple[str, ...] = ("httpx", "httpcore", "githubkit", "urllib3")

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MiB
_DEFAULT_BACKUP_COUNT = 5
_DEFAULT_LOG_FILENAME = "orchestrator.log"


def _to_level(level: int | str | None, default: int = logging.INFO) -> int:
    """レベル指定 (int または文字列) を logging のレベル値に変換する.

    Args:
        level: ログレベル。int、"DEBUG" 等の文字列、または None。
        default: 解決できない場合のフォールバック。

    Returns:
        logging のレベル値 (int)。
    """
    if level is None:
        return default
    if isinstance(level, int):
        return level
    return logging.getLevelNamesMapping().get(level.strip().upper(), default)


def resolve_level(
    *,
    verbose: bool = False,
    log_level: str | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """複数の指定元からログレベルを決定する.

    優先順位 (高い順):
        1. 明示的な log_level 引数 (例: "DEBUG")
        2. 環境変数 AI_AGENT_LOG_LEVEL
        3. verbose フラグ (True なら DEBUG)
        4. デフォルト INFO

    Args:
        verbose: True なら DEBUG を意味する (CLI の --verbose 想定)。
        log_level: 明示的なレベル文字列。
        env: 環境変数のマッピング (省略時は os.environ)。

    Returns:
        決定された logging のレベル値。
    """
    env_map = env if env is not None else os.environ
    if log_level:
        return _to_level(log_level)
    env_value = env_map.get(ENV_LOG_LEVEL)
    if env_value:
        return _to_level(env_value)
    if verbose:
        return logging.DEBUG
    return logging.INFO


def configure_logging(
    level: int | str = logging.INFO,
    log_dir: Path | None = None,
    *,
    file_level: int | str = logging.DEBUG,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
    quiet_loggers: Sequence[str] = _DEFAULT_QUIET_LOGGERS,
    log_filename: str = _DEFAULT_LOG_FILENAME,
) -> None:
    """ルートロガーにコンソール + ファイルハンドラを設定する.

    冪等: 複数回呼んでもハンドラは重複しない (既存ハンドラを置換する)。

    Args:
        level: コンソール出力のレベル (int または文字列)。
        log_dir: ファイル出力先ディレクトリ。None ならファイル出力しない。
            存在しない場合は自動作成する。
        file_level: ファイル出力のレベル。デフォルト DEBUG (常に詳細を記録)。
        max_bytes: ローテーション 1 ファイルあたりの最大バイト数。
        backup_count: 保持する世代数。
        quiet_loggers: WARNING に下げる外部ロガー名。
        log_filename: ログファイル名。
    """
    console_level = _to_level(level)
    resolved_file_level = _to_level(file_level, default=logging.DEBUG)

    root = logging.getLogger()
    # 既存ハンドラを除去 (冪等性確保)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    effective_level = console_level
    if log_dir is not None:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path / log_filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(resolved_file_level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        # ルートは最も詳細なレベルにしないとファイルに DEBUG が届かない
        effective_level = min(console_level, resolved_file_level)

    root.setLevel(effective_level)

    # 外部ライブラリのノイズを抑制
    for name in quiet_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)
