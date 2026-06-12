"""Issue状態のファイルベース永続化."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import asdict, fields
from pathlib import Path

from ai_agent_orchestrator.io_safety import (
    MAX_STATUS_FILE_BYTES,
    FileTooLargeError,
    atomic_write_text,
    read_text_capped,
)
from ai_agent_orchestrator.models import PHASE_MIGRATION, IssueKey, IssueState, Phase

logger = logging.getLogger(__name__)

# IssueState の既知フィールド名。旧バージョンが書き出した state.json に
# 削除済みフィールド (例: replan_count) が残っていても TypeError でエントリが
# drop されないよう、復元時に未知キーを除去するために使用する。
_KNOWN_ISSUE_STATE_FIELDS: frozenset[str] = frozenset(f.name for f in fields(IssueState))


class StatePersistence:
    """Issue状態のファイルベース永続化.

    JSONファイルに IssueState を保存・復元する。
    save() は atomic write (一時ファイル + rename) で安全に書き込む。
    auto_save() はデバウンス付きで頻繁な状態変更時の書き込み回数を抑制する。

    Attributes:
        _file: 状態ファイルのパス。
        _debounce_sec: auto_save のデバウンス間隔 (秒)。
        _pending_task: デバウンス用の pending asyncio.Task。
    """

    def __init__(self, state_file: Path, debounce_sec: float = 2.0) -> None:
        """初期化.

        Args:
            state_file: 状態を保存するJSONファイルのパス。
                親ディレクトリが存在しない場合は自動作成する。
            debounce_sec: auto_save のデバウンス間隔 (秒)。デフォルト2.0秒。
        """
        self._file = state_file
        self._debounce_sec = debounce_sec
        self._pending_task: asyncio.Task[None] | None = None

    def save(self, states: dict[IssueKey, IssueState]) -> None:
        """全Issue状態をJSONファイルに保存."""
        data = {f"{k[0]}:{k[1]}": asdict(v) for k, v in states.items()}
        # atomic write + 0o600 (他ローカルユーザー不可読, #115)。
        atomic_write_text(self._file, json.dumps(data, ensure_ascii=False, indent=2))

    def load(self) -> dict[IssueKey, IssueState]:
        """JSONファイルからIssue状態を復元."""
        if not self._file.exists():
            return {}

        try:
            raw = read_text_capped(self._file, MAX_STATUS_FILE_BYTES)
            data = json.loads(raw)
        except FileTooLargeError:
            # サイズ上限超過 (#115)。巨大ファイルはバックアップせず安全側に倒す。
            logger.warning("state.json がサイズ上限を超過: %s", self._file)
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 破損ファイルのバックアップ
            backup = self._file.with_suffix(".json.corrupted")
            shutil.copy2(self._file, backup)
            return {}

        states: dict[IssueKey, IssueState] = {}
        for k, v in data.items():
            try:
                # Phase enum の復元 (U5 #83)。
                # 1. 現行の enum 値ならそのまま
                # 2. 旧 18 フェーズ名なら PHASE_MIGRATION で新フェーズへ読み替え
                # 3. それ以外 (太古の "planning" 等) は SUSPENDED にフォールバック
                raw_phase = v.get("phase", "")
                try:
                    v["phase"] = Phase(raw_phase)
                except ValueError:
                    migrated = PHASE_MIGRATION.get(raw_phase)
                    if migrated is not None:
                        logger.info(
                            "旧フェーズ値 '%s' を '%s' へマイグレーション (key=%s)",
                            raw_phase,
                            migrated.value,
                            k,
                        )
                        v["phase"] = migrated
                    else:
                        logger.warning(
                            "未知のフェーズ値 '%s' を SUSPENDED にフォールバック (key=%s)",
                            raw_phase,
                            k,
                        )
                        v["phase"] = Phase.SUSPENDED
                # 新フォーマット "owner/repo:42" と旧フォーマット "42" の両方をサポート
                if ":" in k and "/" in k.rsplit(":", 1)[0]:
                    # 新フォーマット: "owner/repo:42"
                    repo_part, num_part = k.rsplit(":", 1)
                    issue_key: IssueKey = (repo_part, int(num_part))
                else:
                    # 旧フォーマット: "42" — IssueState.repo から復元
                    issue_number = int(k)
                    repo = v.get("repo", "")
                    if not repo or "/" not in repo:
                        logger.warning("旧形式エントリをスキップ (repo 情報なし): key=%s", k)
                        continue
                    issue_key = (repo, issue_number)
                # 削除済みフィールド等の未知キーを除去してから復元
                # (旧 state.json の replan_count などで TypeError → drop を防ぐ)
                known = {key: val for key, val in v.items() if key in _KNOWN_ISSUE_STATE_FIELDS}
                states[issue_key] = IssueState(**known)
            except (ValueError, TypeError, KeyError):
                continue  # 不正なエントリはスキップ

        return states

    async def auto_save(self, states: dict[IssueKey, IssueState]) -> None:
        """デバウンス付き自動保存. 最後の呼び出しから debounce_sec 後に save() を実行."""
        if self._pending_task is not None:
            self._pending_task.cancel()

        async def _deferred_save() -> None:
            await asyncio.sleep(self._debounce_sec)
            self.save(states)

        self._pending_task = asyncio.create_task(_deferred_save())

    async def flush(self, states: dict[IssueKey, IssueState]) -> None:
        """保留中の自動保存があれば即座に実行."""
        if self._pending_task is not None:
            self._pending_task.cancel()
            self._pending_task = None
        self.save(states)
