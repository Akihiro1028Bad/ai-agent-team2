"""Skill 検出・マッチング・管理."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from ai_agent_orchestrator.knowledge.models import Pattern, Skill

logger = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 40) -> str:
    """テキストをスラッグ形式（小文字・ハイフン区切り）に変換する.

    Args:
        text: 変換元テキスト。
        max_len: 最大文字数。

    Returns:
        スラッグ文字列。空になった場合は "skill"。
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:max_len].rstrip("-")
    return slug or "skill"


def _skill_id(name: str) -> str:
    """スキル名から安定した識別子を生成する.

    Args:
        name: スラッグ化されたスキル名。

    Returns:
        "sk-{8桁ハッシュ}" 形式の識別子。
    """
    short_hash = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f"sk-{short_hash}"


class SkillManager:
    """Skill の永続化・promoted パターンからの生成・照会を担う.

    Attributes:
        _path: 永続化先ファイルパス。
    """

    def __init__(self, workspace_root: Path) -> None:
        """初期化する.

        Args:
            workspace_root: ワークスペースのルートディレクトリ。
                skills.jsonl は {workspace_root}/knowledge/skills.jsonl に保存される。
        """
        self._path: Path = workspace_root / "knowledge" / "skills.jsonl"

    def load_skills(self) -> list[Skill]:
        """永続化されたスキルをすべて読み込む.

        ファイルが存在しない場合は空リストを返す。
        不正な行はデバッグログを出して読み飛ばす。

        Returns:
            スキルのリスト。
        """
        if not self._path.exists():
            return []

        try:
            raw_lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.warning("スキル読み込みに失敗しました: %s", exc)
            return []

        skills: list[Skill] = []
        for idx, line in enumerate(raw_lines):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                skills.append(Skill.from_dict(data))
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                logger.debug("不正な行 %d を読み飛ばします: %s", idx, exc)

        return skills

    def promote(self, patterns: list[Pattern], now_iso: str) -> list[Skill]:
        """promoted パターンから Skill を生成・マージし永続化する.

        既存スキルと同名のスキルは used_count / success_rate を引き継ぐ。
        新規スキルは used_count=0, success_rate=1.0 で初期化する。
        OSError は握り潰してログ警告を出す（best-effort）。

        Args:
            patterns: 処理対象のパターンリスト。promoted でないものはスキップ。
            now_iso: 更新日時（ISO8601 UTC）。呼び出し元が供給する。

        Returns:
            最終的なスキルリスト（名前順）。
        """
        # 既存スキルを名前でインデックス化
        existing: dict[str, Skill] = {s.name: s for s in self.load_skills()}

        # promoted パターンからスキルを生成
        new_skills: dict[str, Skill] = {}
        for pat in patterns:
            if pat.status != "promoted":
                continue

            name = _slugify(pat.title)
            if name in new_skills:
                # 同名スキルが複数パターンから生成される場合は最初のものを採用
                continue

            # 既存スキルからメトリクスを引き継ぐ
            existing_skill = existing.get(name)
            used_count = existing_skill.used_count if existing_skill else 0
            success_rate = existing_skill.success_rate if existing_skill else 1.0

            new_skills[name] = Skill(
                id=_skill_id(name),
                name=name,
                from_pattern=pat.id,
                used_count=used_count,
                success_rate=success_rate,
                updated_at=now_iso,
            )

        # promoted パターンが無い場合は既存スキルを保持する (空ファイルで上書きしない)。
        # エピソードは追記のみで occurrences は減らないため、一度昇格した Skill は
        # 消えないのが期待挙動。
        if not new_skills:
            return self.load_skills()

        result = sorted(new_skills.values(), key=lambda s: s.name)

        # skills.jsonl を上書き
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(s.to_dict(), ensure_ascii=False) for s in result]
            self._path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        except OSError as exc:
            logger.warning("スキル書き込みに失敗しました: %s", exc)

        return result

    def skills_for_phase(self, phase: str) -> str:
        """フェーズに注入できるスキルテキストブロックを返す.

        MVP: スキルはフェーズを保持しないため、全スキル名を箇条書きで返す。
        スキルが存在しない場合は空文字列を返す。

        Args:
            phase: フェーズ名（MVP では未使用。将来の拡張用）。

        Returns:
            スキル名の箇条書きテキスト。スキルなしなら ""。
        """
        _ = phase  # MVP では未使用
        skills = self.load_skills()
        if not skills:
            return ""
        lines = [f"- {s.name}" for s in skills]
        return "\n".join(lines)
