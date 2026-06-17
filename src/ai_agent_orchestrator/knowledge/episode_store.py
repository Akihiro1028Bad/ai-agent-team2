"""エピソード記憶の保存・検索."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from ai_agent_orchestrator.knowledge.models import Episode

logger = logging.getLogger(__name__)

_MAX_EPISODES = 5000


def make_episode_id(issue: int, phase: str, created_at: str) -> str:
    """エピソードの安定した識別子を生成する.

    引数をハッシュ化して短いサフィックスを作る。
    呼び出し元が created_at を渡すため、関数内で時刻を参照しない。

    Args:
        issue: GitHub Issue 番号。
        phase: フェーズ名。
        created_at: ISO8601 形式の生成時刻。呼び出し元が供給する。

    Returns:
        "ep-{issue}-{phase}-{8桁ハッシュ}" 形式の識別子。
    """
    raw = f"{issue}:{phase}:{created_at}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:8]
    return f"ep-{issue}-{phase}-{short_hash}"


class EpisodeStore:
    """エピソードの JSONL ファイルへの永続化と読み込みを担う.

    Attributes:
        _path: 永続化先ファイルパス。
    """

    def __init__(self, workspace_root: Path) -> None:
        """初期化する.

        Args:
            workspace_root: ワークスペースのルートディレクトリ。
                episodes.jsonl は {workspace_root}/knowledge/episodes.jsonl に保存される。
        """
        self._path: Path = workspace_root / "knowledge" / "episodes.jsonl"

    def record(self, episode: Episode) -> None:
        """エピソードを JSONL ファイルへ追記する.

        親ディレクトリが存在しない場合は作成する。
        OSError は握り潰してログ警告を出すのみ（best-effort）。

        Args:
            episode: 記録するエピソード。
        """
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(episode.to_dict(), ensure_ascii=False)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            logger.warning("エピソード記録に失敗しました: %s", exc)

    def load(self) -> list[Episode]:
        """永続化されたエピソードをすべて読み込む.

        ファイルが存在しない場合は空リストを返す。
        行がパースできない場合はデバッグログを出して読み飛ばす。
        DoS 対策として最新 5,000 件のみを保持する。

        Returns:
            エピソードのリスト（古い順）。
        """
        if not self._path.exists():
            return []

        try:
            raw_lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("エピソード読み込みに失敗しました: %s", exc)
            return []

        # DoS キャップ: 末尾 _MAX_EPISODES 行のみ処理
        if len(raw_lines) > _MAX_EPISODES:
            raw_lines = raw_lines[-_MAX_EPISODES:]

        episodes: list[Episode] = []
        for idx, line in enumerate(raw_lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                episodes.append(Episode.from_dict(data))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.debug("不正な行 %d を読み飛ばします: %s", idx, exc)

        return episodes
