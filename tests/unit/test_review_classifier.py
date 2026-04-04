"""レビューコメント優先度分類のテスト."""

from __future__ import annotations

from ai_agent_orchestrator.phases.review_classifier import (
    ReviewPriority,
    classify_review_comments,
    format_classified_comments,
)


class TestClassifyReviewComments:
    """classify_review_comments のテスト."""

    def test_blocking_keyword(self) -> None:
        comments = [{"body": "This is a critical security issue", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert len(result) == 1
        assert result[0].priority == ReviewPriority.BLOCKING

    def test_blocking_japanese(self) -> None:
        comments = [{"body": "この部分はセキュリティの問題があります", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert result[0].priority == ReviewPriority.BLOCKING

    def test_must_fix_default(self) -> None:
        comments = [{"body": "この変数名をもっとわかりやすくしてください", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert result[0].priority == ReviewPriority.MUST_FIX

    def test_nit_keyword(self) -> None:
        comments = [{"body": "nit: spacing issue here", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert result[0].priority == ReviewPriority.NIT

    def test_question_keyword(self) -> None:
        comments = [{"body": "why did you choose this approach?", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert result[0].priority == ReviewPriority.QUESTION

    def test_praise_keyword(self) -> None:
        comments = [{"body": "LGTM! Great work", "author": "reviewer"}]
        result = classify_review_comments(comments)
        assert result[0].priority == ReviewPriority.PRAISE

    def test_empty_list(self) -> None:
        result = classify_review_comments([])
        assert result == []

    def test_multiple_comments_classified(self) -> None:
        comments = [
            {"body": "critical: fix this vulnerability", "author": "sec-reviewer"},
            {"body": "nit: add a blank line", "author": "reviewer"},
            {"body": "Looks good!", "author": "lead"},
        ]
        result = classify_review_comments(comments)
        assert len(result) == 3
        assert result[0].priority == ReviewPriority.BLOCKING
        assert result[1].priority == ReviewPriority.NIT
        assert result[2].priority == ReviewPriority.MUST_FIX  # "Looks" doesn't match praise

    def test_file_and_line_preserved(self) -> None:
        comments = [{"body": "fix this", "author": "r", "file": "src/foo.py", "line": "42"}]
        result = classify_review_comments(comments)
        assert result[0].file == "src/foo.py"
        assert result[0].line == 42

    def test_line_non_digit_ignored(self) -> None:
        comments = [{"body": "fix", "author": "r", "line": "abc"}]
        result = classify_review_comments(comments)
        assert result[0].line is None


class TestFormatClassifiedComments:
    """format_classified_comments のテスト."""

    def test_empty_returns_no_comments(self) -> None:
        result = format_classified_comments([])
        assert "ありません" in result

    def test_blocking_section_present(self) -> None:
        comments = [{"body": "critical bug", "author": "reviewer"}]
        classified = classify_review_comments(comments)
        result = format_classified_comments(classified)
        assert "BLOCKING" in result

    def test_priority_order(self) -> None:
        comments = [
            {"body": "nit: small fix", "author": "r"},
            {"body": "MUST fix this security issue", "author": "r"},
        ]
        classified = classify_review_comments(comments)
        result = format_classified_comments(classified)
        # BLOCKING should appear before NIT
        blocking_pos = result.find("BLOCKING")
        nit_pos = result.find("NIT")
        assert blocking_pos < nit_pos

    def test_instructions_included(self) -> None:
        comments = [{"body": "fix this", "author": "r"}]
        classified = classify_review_comments(comments)
        result = format_classified_comments(classified)
        assert "修正方針" in result
