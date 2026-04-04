"""CI ログパーサーのテスト."""

from __future__ import annotations

from ai_agent_orchestrator.phases.ci_log_parser import (
    CiErrorCategory,
    format_ci_summary,
    parse_ci_log,
)


class TestParseCiLog:
    """parse_ci_log のテスト."""

    def test_pytest_failure(self) -> None:
        log = "FAILED tests/unit/test_foo.py::test_bar - AssertionError: expected 1"
        summary = parse_ci_log(log)
        assert len(summary.errors) == 1
        assert summary.errors[0].category == CiErrorCategory.TEST_FAILURE
        assert summary.errors[0].file == "tests/unit/test_foo.py"
        assert "test_bar" in summary.errors[0].message

    def test_pytest_summary(self) -> None:
        log = "3 failed, 10 passed in 5.2s"
        summary = parse_ci_log(log)
        assert summary.failed_tests == 3
        assert summary.total_tests == 13

    def test_ruff_error(self) -> None:
        log = "src/foo.py:10:5: E501 Line too long (120 > 88)"
        summary = parse_ci_log(log)
        assert len(summary.errors) == 1
        assert summary.errors[0].category == CiErrorCategory.LINT_ERROR
        assert summary.errors[0].file == "src/foo.py"
        assert summary.errors[0].line == 10

    def test_mypy_error(self) -> None:
        log = "src/bar.py:42: error: Incompatible types in assignment"
        summary = parse_ci_log(log)
        assert len(summary.errors) == 1
        assert summary.errors[0].category == CiErrorCategory.TYPE_ERROR
        assert summary.errors[0].file == "src/bar.py"
        assert summary.errors[0].line == 42

    def test_build_error(self) -> None:
        log = "ModuleNotFoundError: No module named 'missing_lib'"
        summary = parse_ci_log(log)
        assert len(summary.errors) == 1
        assert summary.errors[0].category == CiErrorCategory.BUILD_ERROR
        assert "ModuleNotFoundError" in summary.errors[0].message

    def test_mixed_errors(self) -> None:
        log = (
            "FAILED tests/unit/test_a.py::test_x - AssertionError\n"
            "src/foo.py:5:1: E302 Expected 2 blank lines\n"
            "src/bar.py:10: error: Missing return statement\n"
            "2 failed, 5 passed\n"
        )
        summary = parse_ci_log(log)
        assert len(summary.errors) == 3
        categories = {e.category for e in summary.errors}
        assert CiErrorCategory.TEST_FAILURE in categories
        assert CiErrorCategory.LINT_ERROR in categories
        assert CiErrorCategory.TYPE_ERROR in categories
        assert summary.failed_tests == 2
        assert summary.total_tests == 7

    def test_empty_log(self) -> None:
        summary = parse_ci_log("")
        assert len(summary.errors) == 0
        assert summary.total_tests is None
        assert summary.failed_tests is None

    def test_no_matches(self) -> None:
        log = "Some random output\nAnother line\n"
        summary = parse_ci_log(log)
        assert len(summary.errors) == 0


class TestFormatCiSummary:
    """format_ci_summary のテスト."""

    def test_empty_errors_returns_fallback(self) -> None:
        summary = parse_ci_log("")
        result = format_ci_summary(summary)
        assert "解析できませんでした" in result

    def test_structured_output_contains_category(self) -> None:
        log = "FAILED tests/unit/test_a.py::test_x - AssertionError\n"
        summary = parse_ci_log(log)
        result = format_ci_summary(summary)
        assert "テスト失敗" in result

    def test_structured_output_contains_test_count(self) -> None:
        log = "FAILED tests/unit/test_a.py::test_x - AssertionError\n3 failed, 7 passed\n"
        summary = parse_ci_log(log)
        result = format_ci_summary(summary)
        assert "3 件失敗" in result
        assert "10 件中" in result
