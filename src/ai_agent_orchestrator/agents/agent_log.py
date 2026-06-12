"""エージェント実行ログのファイル出力 (#85).

claude_runner の SDK メッセージを ``logs/issue-{n}/agent.jsonl`` に逐次追記する。
EventLogger と同じ基底ディレクトリ (workspace/logs) / 同方式 (asyncio.Lock +
to_thread) を用い、書き込み前に sanitize_dict で機微情報をマスクする。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from ai_agent_orchestrator.io_safety import ensure_private_file
from ai_agent_orchestrator.sanitize import sanitize_dict


class AgentLogWriter:
    """agent.jsonl への 1 行 JSON 追記ライター.

    出力先:
        {log_dir}/issue-{issue_number}/agent.jsonl

    Attributes:
        _log_dir: ログの基底ディレクトリ (EventLogger と共通の workspace/logs)。
        _lock: 並行書き込みを防ぐための asyncio.Lock。
    """

    def __init__(self, log_dir: Path) -> None:
        """初期化する.

        Args:
            log_dir: ログの基底ディレクトリ。存在しない場合は自動作成。
        """
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def write(self, issue_number: int, record: dict[str, Any]) -> None:
        """レコードを agent.jsonl に 1 行 JSON として追記する.

        record は書き込み前に sanitize_dict でサニタイズする。

        Args:
            issue_number: Issue 番号 (出力ディレクトリの決定に使用)。
            record: 書き込むレコード (dict)。
        """
        sanitized = sanitize_dict(record)
        agent_file = self._log_dir / f"issue-{issue_number}" / "agent.jsonl"
        # default=str: 非 JSON シリアライズ値 (将来 SDK の usage が非 dict 等) でも
        # 例外で record 丸ごと欠落させない。UI コスト集計ソースを取りこぼさない (#85)。
        line = json.dumps(sanitized, ensure_ascii=False, default=str) + "\n"

        def _write() -> None:
            # 初回作成時に 0o600 で用意 (他ローカルユーザー不可読, #115)。
            ensure_private_file(agent_file)
            with agent_file.open("a", encoding="utf-8") as f:
                f.write(line)

        async with self._lock:
            await asyncio.to_thread(_write)
