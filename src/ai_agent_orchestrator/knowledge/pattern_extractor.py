"""セマンティックパターン抽出."""

from __future__ import annotations

import hashlib
import re

from ai_agent_orchestrator.knowledge.models import Episode, Pattern

_MAX_TITLE_LEN = 60


def _stable_id(key: str) -> str:
    """キー文字列から安定した短いハッシュ ID を生成する.

    Args:
        key: ハッシュの元となる文字列。

    Returns:
        "pat-{8桁ハッシュ}" 形式の識別子。
    """
    short_hash = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"pat-{short_hash}"


def _dominant_phase(phases: list[str]) -> str:
    """フェーズリストから最も出現頻度が高いフェーズを返す.

    Args:
        phases: フェーズ名のリスト（空可）。

    Returns:
        最頻フェーズ名。空の場合は空文字列。
    """
    if not phases:
        return ""
    return max(set(phases), key=phases.count)


def extract_patterns(episodes: list[Episode]) -> list[Pattern]:
    """エピソードリストから繰り返しパターンを抽出する.

    教訓テキストを正規化してグループ化し、グループごとに Pattern を生成する。
    lesson が空のエピソードはスキップする。

    ルール:
    - confidence = min(1.0, occurrences / 3) （3 回以上で確信度 1.0 に到達）
    - occurrences >= 3 なら status = "promoted"、それ以外は "candidate"
    - title は教訓の最初の出現（原文のまま）を 60 文字以内に切り詰める
    - description は日本語の短い説明（観測回数と支配的フェーズを含む）
    - 出現回数降順、タイトル昇順でソート

    Args:
        episodes: 処理対象のエピソードリスト。

    Returns:
        抽出されたパターンのリスト。
    """
    # lesson をキー（正規化）でグループ化
    groups: dict[str, list[Episode]] = {}
    for ep in episodes:
        lesson = ep.lesson.strip()
        if not lesson:
            continue
        key = lesson.lower()
        if key not in groups:
            groups[key] = []
        groups[key].append(ep)

    patterns: list[Pattern] = []
    for key, group in groups.items():
        occurrences = len(group)
        confidence = min(1.0, occurrences / 3)
        status: str = "promoted" if occurrences >= 3 else "candidate"

        # タイトル: 最初に出現した教訓（原文）を 60 文字以内に切り詰める
        first_lesson = group[0].lesson.strip()
        title = first_lesson[:_MAX_TITLE_LEN]

        # 説明: 支配的フェーズを含む日本語短文
        phases = [ep.phase for ep in group]
        dom_phase = _dominant_phase(phases)
        description = f"{occurrences}回観測（フェーズ: {dom_phase}）。"

        pat_id = _stable_id(key)

        patterns.append(
            Pattern(
                id=pat_id,
                title=title,
                description=description,
                confidence=round(confidence, 4),
                occurrences=occurrences,
                status=status,  # type: ignore[arg-type]
            )
        )

    # 出現回数降順、タイトル昇順
    patterns.sort(key=lambda p: (-p.occurrences, p.title))
    return patterns


def _slugify(text: str, max_len: int = 40) -> str:
    """テキストをスラッグ形式（小文字・ハイフン区切り）に変換する.

    パターン管理の内部ユーティリティ。

    Args:
        text: 変換元テキスト。
        max_len: 最大文字数。

    Returns:
        スラッグ文字列。空になった場合は "skill"。
    """
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    # 連続ハイフンを折り畳む
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:max_len].rstrip("-")
    return slug or "skill"
