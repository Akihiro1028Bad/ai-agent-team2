"""設計レビュー提出の分類と control.jsonl 行生成 (#89 Unit B).

インラインレビュー (ReviewComment のリスト) を承認/差し戻し/質問へ分類し、
既存の承認・差し戻し口 (control_file.py の approve/reject + feedback) に載る
control.jsonl 行へ変換する。新たな ControlBus 語彙は導入せず、U4 の承認経路へ合流する。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ai_agent_orchestrator.api.schemas import ReviewComment

ReviewOutcome = Literal["approved", "changes_requested", "questions"]


def classify_review(comments: Sequence[ReviewComment]) -> ReviewOutcome:
    """インラインレビューを 3 値に分類する (#89).

    - 指摘が 1 件でもある → changes_requested (PLAN 差し戻し)
    - 指摘 0 件 かつ 質問あり → questions
    - コメント 0 件 → approved (承認)

    Args:
        comments: レビューコメントのリスト。

    Returns:
        分類結果。
    """
    if not comments:
        return "approved"
    if any(c.tag == "指摘" for c in comments):
        return "changes_requested"
    return "questions"


def format_review_feedback(comments: Sequence[ReviewComment]) -> str:
    """コメント群を差し戻し feedback テキストへ整形する (#89).

    各コメントを ``[tag/anchor(ラベル)] 本文`` の 1 行にし、PLAN 再実行時に
    「どの要素へのどんな指摘/質問か」を agent へ正確に渡す。
    """
    lines: list[str] = []
    for c in comments:
        label = f"{c.anchor}" if not c.anchor_label else f"{c.anchor} {c.anchor_label}"
        lines.append(f"[{c.tag}/{label}] {c.body}")
    return "\n".join(lines)


def build_review_control_record(
    issue_number: int,
    actor: str,
    comments: Sequence[ReviewComment],
) -> dict[str, object]:
    """レビュー提出を control.jsonl の承認/差し戻し行へ変換する (#89).

    - approved → ``{issue, action:"approve", approver}``
    - それ以外 (指摘 or 質問) → ``{issue, action:"reject", approver, feedback}``
      (control_file.py の reject + feedback 経路に載せ、PLAN 差し戻しを促す)。

    Args:
        issue_number: 対象 Issue 番号。
        actor: レビュア (承認者検証に使う login)。
        comments: レビューコメント。

    Returns:
        control.jsonl へ追記する 1 行分の dict。
    """
    outcome = classify_review(comments)
    if outcome == "approved":
        return {"issue": issue_number, "action": "approve", "approver": actor}
    return {
        "issue": issue_number,
        "action": "reject",
        "approver": actor,
        "feedback": format_review_feedback(comments),
    }
