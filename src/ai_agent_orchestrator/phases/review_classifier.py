"""レビューコメント優先度分類.

レビューコメントをキーワードベースで優先度分類し、
Claude に構造化されたフィードバックを提供する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ReviewPriority(StrEnum):
    """レビューコメントの優先度."""

    BLOCKING = "blocking"
    MUST_FIX = "must-fix"
    NIT = "nit"
    QUESTION = "question"
    PRAISE = "praise"


@dataclass(frozen=True)
class ClassifiedComment:
    """優先度分類されたレビューコメント."""

    priority: ReviewPriority
    body: str
    author: str
    file: str | None = None
    line: int | None = None


# ---------------------------------------------------------------------------
# 分類キーワード (大文字小文字無視)
# ---------------------------------------------------------------------------

_BLOCKING_PATTERNS: list[re.Pattern[str]] = [
    *[
        re.compile(p, re.IGNORECASE)
        for p in [
            r"\bblocking\b",
            r"\bcritical\b",
            r"\bsecurity\b",
            r"\bvulnerability\b",
            r"必須",
            r"セキュリティ",
            r"脆弱性",
        ]
    ],
    re.compile(r"\bMUST\b"),  # 大文字のみ (小文字 "must" は一般的すぎるため除外)
]

_NIT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bnit\b",
        r"\bnitpick\b",
        r"\bminor\b",
        r"\boptional\b",
        r"好み",
        r"些細",
        r"細かい",
    ]
]

_QUESTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\?$",
        r"\bquestion\b",
        r"\bwhy\b",
        r"なぜ",
        r"どうして",
        r"質問",
    ]
]

_PRAISE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bLGTM\b",
        r"\bnice\b",
        r"\bgreat\b",
        r"\bgood job\b",
        r"素晴らしい",
        r"いいね",
        r"👍",
    ]
]


def _classify_body(body: str) -> ReviewPriority:
    """コメント本文からキーワードベースで優先度を判定する."""
    for p in _BLOCKING_PATTERNS:
        if p.search(body):
            return ReviewPriority.BLOCKING
    for p in _PRAISE_PATTERNS:
        if p.search(body):
            return ReviewPriority.PRAISE
    for p in _NIT_PATTERNS:
        if p.search(body):
            return ReviewPriority.NIT
    for p in _QUESTION_PATTERNS:
        if p.search(body):
            return ReviewPriority.QUESTION
    return ReviewPriority.MUST_FIX


def classify_review_comments(
    comments: list[dict[str, str]],
) -> list[ClassifiedComment]:
    """レビューコメントを優先度分類する.

    Args:
        comments: コメント辞書のリスト。
            各辞書は "body", "author" を必須キー、
            "file", "line" をオプショナルキーとして持つ。

    Returns:
        優先度分類された ClassifiedComment のリスト。
    """
    result: list[ClassifiedComment] = []
    for c in comments:
        body = c.get("body", "")
        author = c.get("author", "unknown")
        file = c.get("file")
        line_str = c.get("line")
        line = int(line_str) if line_str and str(line_str).isdigit() else None

        priority = _classify_body(body)
        result.append(
            ClassifiedComment(
                priority=priority,
                body=body,
                author=author,
                file=file,
                line=line,
            )
        )
    return result


def format_classified_comments(comments: list[ClassifiedComment]) -> str:
    """分類済みコメントをプロンプト用のフォーマットに変換する.

    Args:
        comments: 分類済みコメントのリスト。

    Returns:
        優先度別にフォーマットされた文字列。
    """
    if not comments:
        return "レビュー指摘はありません。"

    grouped: dict[ReviewPriority, list[ClassifiedComment]] = {}
    for c in comments:
        grouped.setdefault(c.priority, []).append(c)

    priority_labels = {
        ReviewPriority.BLOCKING: "BLOCKING (必ず修正)",
        ReviewPriority.MUST_FIX: "MUST-FIX (修正推奨)",
        ReviewPriority.NIT: "NIT (対応任意)",
        ReviewPriority.QUESTION: "QUESTION (回答のみ)",
        ReviewPriority.PRAISE: "PRAISE (対応不要)",
    }

    priority_order = [
        ReviewPriority.BLOCKING,
        ReviewPriority.MUST_FIX,
        ReviewPriority.NIT,
        ReviewPriority.QUESTION,
        ReviewPriority.PRAISE,
    ]

    sections: list[str] = []
    for pri in priority_order:
        group = grouped.get(pri, [])
        if not group:
            continue
        lines: list[str] = []
        for c in group:
            loc = f" ({c.file}:{c.line})" if c.file else ""
            lines.append(f"  - [{c.author}]{loc}: {c.body}")
        sections.append(f"### {priority_labels[pri]}\n" + "\n".join(lines))

    header = "## レビュー指摘 (優先度順)\n"
    instructions = (
        "\n\n## 修正方針\n"
        "1. BLOCKING コメントを最優先で対応\n"
        "2. MUST-FIX コメントに対応\n"
        "3. NIT は時間に余裕があれば対応\n"
        "4. QUESTION は回答をコメントで返す\n"
    )
    return header + "\n\n".join(sections) + instructions
