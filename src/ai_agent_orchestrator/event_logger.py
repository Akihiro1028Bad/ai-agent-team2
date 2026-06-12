"""イベントログ記録 + トークンサニタイズ."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_agent_orchestrator import sanitize
from ai_agent_orchestrator.io_safety import ensure_private_file


class EventLogger:
    """構造化イベントログの記録.

    Issue単位で events.jsonl ファイルにイベントを追記する。
    Tracker Protocol に適合し、プラグインとして差し替え可能。

    ログ出力先:
        {log_dir}/issue-{issue_number}/events.jsonl

    フェーズログ出力先:
        {log_dir}/issue-{issue_number}/{timestamp}_{phase}.log

    Attributes:
        _log_dir: ログの基底ディレクトリ。
        _lock: 並行書き込みを防ぐための asyncio.Lock。
        SENSITIVE_KEYS: マスク対象のキー名パターン。
        TOKEN_PATTERN: トークン文字列にマッチする正規表現。
    """

    # サニタイズパターンは sanitize モジュールへ抽出済み (#85)。
    # 公開クラス属性は後方互換のため同一オブジェクトを参照する。
    SENSITIVE_KEYS: frozenset[str] = sanitize.SENSITIVE_KEYS

    TOKEN_PATTERN: re.Pattern[str] = sanitize.TOKEN_PATTERN

    URL_TOKEN_PATTERN: re.Pattern[str] = sanitize.URL_TOKEN_PATTERN

    def __init__(self, log_dir: Path) -> None:
        """初期化.

        Args:
            log_dir: ログの基底ディレクトリ。存在しない場合は自動作成。
        """
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    @property
    def log_dir(self) -> Path:
        """イベントログの基底ディレクトリ。"""
        return self._log_dir

    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """イベントをJSONLファイルに記録."""
        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "issue": issue_number,
            "phase": phase,
            "event": event,
        }
        if data:
            record["data"] = self._sanitize_for_log(data)

        events_file = self._log_dir / f"issue-{issue_number}" / "events.jsonl"

        line = json.dumps(record, ensure_ascii=False) + "\n"

        def _write() -> None:
            # 初回作成時に 0o600 で用意 (他ローカルユーザー不可読, #115)。
            ensure_private_file(events_file)
            with events_file.open("a", encoding="utf-8") as f:
                f.write(line)

        async with self._lock:
            await asyncio.to_thread(_write)

    async def write_phase_log(
        self,
        issue_number: int,
        phase: str,
        content: str,
    ) -> None:
        """フェーズログをファイルに書き出す."""
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        log_file = self._log_dir / f"issue-{issue_number}" / f"{ts}_{phase}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        # 文字列内のトークンパターンをマスク
        sanitized_content = self.TOKEN_PATTERN.sub("***REDACTED***", content)

        def _write() -> None:
            log_file.write_text(sanitized_content, encoding="utf-8")

        async with self._lock:
            await asyncio.to_thread(_write)

    def _sanitize_for_log(self, data: dict[str, Any]) -> dict[str, Any]:
        """ログ出力前にセンシティブ情報をマスク (sanitize モジュールへ委譲)."""
        return sanitize.sanitize_dict(data)
