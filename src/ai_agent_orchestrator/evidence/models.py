"""エビデンス (スクショ・録画・端末ログ) のデータモデル (#91)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    """エビデンス 1 件を表すイミュータブルなレコード.

    Attributes:
        id: アイテムの識別子 (例 "screenshot-desktop")。
        kind: 種別 ("screenshot" | "video" | "terminal")。
        title: 表示用タイトル。
        file: evidence ディレクトリ内の相対ファイル名 (フラット)。
        viewport: ビューポート ("desktop" | "mobile")。該当しない場合は None。
        created_at: 生成時刻 (ISO8601 UTC)。未設定は空文字列。
    """

    id: str
    kind: str
    title: str
    file: str
    viewport: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """manifest 用の dict 表現へ変換する.

        Returns:
            manifest items に格納する dict。
        """
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "file": self.file,
            "viewport": self.viewport,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceItem:
        """manifest の dict から EvidenceItem を復元する.

        欠損キーは既定値で補う (壊れにくさを優先)。

        Args:
            data: manifest items の 1 要素。

        Returns:
            復元した EvidenceItem。
        """
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "")),
            title=str(data.get("title", "")),
            file=str(data.get("file", "")),
            viewport=data.get("viewport"),
            created_at=str(data.get("created_at", "")),
        )
