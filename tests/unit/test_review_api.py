"""設計レビュー提出の分類と control 行生成のテスト (#89 Unit B1)."""

from __future__ import annotations

from ai_agent_orchestrator.api.review import (
    build_review_control_record,
    classify_review,
)
from ai_agent_orchestrator.api.schemas import ReviewComment


def _c(tag: str, body: str = "本文", anchor: str = "tc-01") -> ReviewComment:
    return ReviewComment(anchor=anchor, anchor_label="ラベル", tag=tag, body=body)  # type: ignore[arg-type]


class TestClassifyReview:
    def test_empty_is_approved(self) -> None:
        assert classify_review([]) == "approved"

    def test_any_correction_is_changes_requested(self) -> None:
        assert classify_review([_c("質問"), _c("指摘")]) == "changes_requested"

    def test_questions_only(self) -> None:
        assert classify_review([_c("質問"), _c("質問")]) == "questions"


class TestBuildReviewControlRecord:
    def test_approved_writes_approve_command(self) -> None:
        rec = build_review_control_record(5, "alice", [])
        assert rec == {"issue": 5, "action": "approve", "approver": "alice"}

    def test_changes_requested_writes_reject_with_feedback(self) -> None:
        rec = build_review_control_record(
            5,
            "alice",
            [_c("指摘", "ここが誤り", "arch-1")],
        )
        assert rec["issue"] == 5
        assert rec["action"] == "reject"
        assert rec["approver"] == "alice"
        # feedback は anchor ラベルと本文を含む
        assert "ここが誤り" in rec["feedback"]
        assert "arch-1" in rec["feedback"]

    def test_questions_write_reject_with_feedback(self) -> None:
        # 質問のみでも (既存 infra に合わせ) reject + feedback で再計画を促す
        rec = build_review_control_record(7, "bob", [_c("質問", "なぜこの設計?", "sum-1")])
        assert rec["action"] == "reject"
        assert "なぜこの設計?" in rec["feedback"]

    def test_feedback_includes_all_comments(self) -> None:
        rec = build_review_control_record(
            5,
            "alice",
            [_c("指摘", "A", "tc-01"), _c("質問", "B", "tc-02")],
        )
        assert "A" in rec["feedback"]
        assert "B" in rec["feedback"]
