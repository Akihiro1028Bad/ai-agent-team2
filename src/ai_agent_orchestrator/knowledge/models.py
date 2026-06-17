"""知識ループ用データモデル (Episode / Pattern / Skill)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Episode:
    """1 回のフェーズ実行結果を表すイミュータブルなレコード.

    Attributes:
        id: エピソードの識別子 (例 "ep-42-implement-abc123")。
        issue: GitHub Issue 番号。
        repo: リポジトリ名。
        phase: フェーズ名 (例 "implement", "review")。
        outcome: 結果。"success" または "failure"。
        summary: 実行内容の要約。
        lesson: 得られた教訓。
        created_at: 生成時刻 (ISO8601 UTC)。
    """

    id: str
    issue: int
    repo: str
    phase: str
    outcome: Literal["success", "failure"]
    summary: str
    lesson: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        """JSONL 永続化用の dict へ変換する.

        Returns:
            エピソードのフィールドを格納した dict。
        """
        return {
            "id": self.id,
            "issue": self.issue,
            "repo": self.repo,
            "phase": self.phase,
            "outcome": self.outcome,
            "summary": self.summary,
            "lesson": self.lesson,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Episode:
        """dict から Episode を復元する.

        欠損キーは既定値で補う（壊れにくさを優先）。

        Args:
            data: JSONL の 1 行をパースした dict。

        Returns:
            復元した Episode。
        """
        outcome_raw = str(data.get("outcome", "failure"))
        outcome: Literal["success", "failure"] = "success" if outcome_raw == "success" else "failure"
        return cls(
            id=str(data.get("id", "")),
            issue=int(data.get("issue", 0)),
            repo=str(data.get("repo", "")),
            phase=str(data.get("phase", "")),
            outcome=outcome,
            summary=str(data.get("summary", "")),
            lesson=str(data.get("lesson", "")),
            created_at=str(data.get("created_at", "")),
        )


@dataclass(frozen=True)
class Pattern:
    """複数エピソードから抽出された繰り返しパターン.

    Attributes:
        id: パターンの識別子 (例 "pat-abc123")。
        title: パターンのタイトル（教訓テキスト由来）。
        description: 日本語の短い説明。
        confidence: 確信度 (0.0〜1.0)。
        occurrences: 観測回数。
        status: ステータス。"candidate" または "promoted"。
    """

    id: str
    title: str
    description: str
    confidence: float
    occurrences: int
    status: Literal["candidate", "promoted"]

    def to_dict(self) -> dict[str, Any]:
        """JSONL 永続化用の dict へ変換する.

        Returns:
            パターンのフィールドを格納した dict。
        """
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pattern:
        """dict から Pattern を復元する.

        欠損キーは既定値で補う（壊れにくさを優先）。

        Args:
            data: JSONL の 1 行をパースした dict。

        Returns:
            復元した Pattern。
        """
        status_raw = str(data.get("status", "candidate"))
        status: Literal["candidate", "promoted"] = "promoted" if status_raw == "promoted" else "candidate"
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            confidence=float(data.get("confidence", 0.0)),
            occurrences=int(data.get("occurrences", 0)),
            status=status,
        )


@dataclass(frozen=True)
class Skill:
    """promoted パターンから生成されたスキル.

    Attributes:
        id: スキルの識別子 (例 "sk-abc123")。
        name: スラッグ化されたスキル名。
        from_pattern: 元となったパターンの id。
        used_count: 使用回数。
        success_rate: 成功率 (0.0〜1.0)。
        updated_at: 最終更新時刻 (ISO8601 UTC)。
    """

    id: str
    name: str
    from_pattern: str
    used_count: int
    success_rate: float
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        """JSONL 永続化用の dict へ変換する.

        Returns:
            スキルのフィールドを格納した dict。
        """
        return {
            "id": self.id,
            "name": self.name,
            "from_pattern": self.from_pattern,
            "used_count": self.used_count,
            "success_rate": self.success_rate,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        """dict から Skill を復元する.

        欠損キーは既定値で補う（壊れにくさを優先）。

        Args:
            data: JSONL の 1 行をパースした dict。

        Returns:
            復元した Skill。
        """
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            from_pattern=str(data.get("from_pattern", "")),
            used_count=int(data.get("used_count", 0)),
            success_rate=float(data.get("success_rate", 1.0)),
            updated_at=str(data.get("updated_at", "")),
        )
