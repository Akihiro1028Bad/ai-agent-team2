"""CI ログ構造化パーサー.

CI の生ログを解析してエラーを分類し、構造化されたサマリーを生成する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CiErrorCategory(StrEnum):
    """CI エラーのカテゴリ."""

    TEST_FAILURE = "test_failure"
    LINT_ERROR = "lint_error"
    TYPE_ERROR = "type_error"
    BUILD_ERROR = "build_error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CiError:
    """CI エラーの構造化表現."""

    category: CiErrorCategory
    file: str | None
    line: int | None
    message: str


@dataclass(frozen=True)
class CiLogSummary:
    """CI ログの構造化サマリー."""

    errors: tuple[CiError, ...]
    total_tests: int | None
    failed_tests: int | None
    raw_log: str


# ---------------------------------------------------------------------------
# パースパターン
# ---------------------------------------------------------------------------

# pytest: FAILED tests/unit/test_xxx.py::test_name - AssertionError: ...
_PYTEST_FAILURE = re.compile(
    r"FAILED\s+([\w/.\-]+\.py)::(\S+)\s*[-–]\s*(.*)",
)

# pytest summary: "3 failed, 10 passed"
_PYTEST_SUMMARY = re.compile(
    r"(\d+)\s+failed.*?(\d+)\s+passed",
)

# ruff 出力: src/xxx.py:10:5: E501 Line too long
_RUFF_ERROR = re.compile(
    r"([\w/.\-]+\.py):(\d+):\d+:\s+([A-Z]\d+\s+.*)",
)

# mypy 出力: src/xxx.py:10: error: Incompatible types ...
_MYPY_ERROR = re.compile(
    r"([\w/.\-]+\.py):(\d+):\s+error:\s+(.*)",
)

# ModuleNotFoundError / ImportError / SyntaxError
_BUILD_ERROR = re.compile(
    r"(ModuleNotFoundError|ImportError|SyntaxError):\s+(.*)",
)


def parse_ci_log(raw_log: str) -> CiLogSummary:
    """CI ログを解析してエラーを分類する.

    Args:
        raw_log: CI の生ログ文字列。

    Returns:
        構造化された CiLogSummary。
    """
    errors: list[CiError] = []
    total_tests: int | None = None
    failed_tests: int | None = None

    for line in raw_log.splitlines():
        # pytest failures
        m = _PYTEST_FAILURE.search(line)
        if m:
            errors.append(
                CiError(
                    category=CiErrorCategory.TEST_FAILURE,
                    file=m.group(1),
                    line=None,
                    message=f"{m.group(2)}: {m.group(3).strip()}",
                )
            )
            continue

        # ruff errors
        m = _RUFF_ERROR.search(line)
        if m:
            errors.append(
                CiError(
                    category=CiErrorCategory.LINT_ERROR,
                    file=m.group(1),
                    line=int(m.group(2)),
                    message=m.group(3).strip(),
                )
            )
            continue

        # mypy errors
        m = _MYPY_ERROR.search(line)
        if m:
            errors.append(
                CiError(
                    category=CiErrorCategory.TYPE_ERROR,
                    file=m.group(1),
                    line=int(m.group(2)),
                    message=m.group(3).strip(),
                )
            )
            continue

        # build errors
        m = _BUILD_ERROR.search(line)
        if m:
            errors.append(
                CiError(
                    category=CiErrorCategory.BUILD_ERROR,
                    file=None,
                    line=None,
                    message=f"{m.group(1)}: {m.group(2).strip()}",
                )
            )
            continue

    # pytest summary
    for line in raw_log.splitlines():
        m = _PYTEST_SUMMARY.search(line)
        if m:
            failed_tests = int(m.group(1))
            total_tests = failed_tests + int(m.group(2))
            break

    return CiLogSummary(
        errors=tuple(errors),
        total_tests=total_tests,
        failed_tests=failed_tests,
        raw_log=raw_log,
    )


def format_ci_summary(summary: CiLogSummary) -> str:
    """CiLogSummary をプロンプト用のフォーマット済み文字列に変換する.

    Args:
        summary: 構造化された CI ログサマリー。

    Returns:
        フォーマット済みのエラーサマリー文字列。
    """
    if not summary.errors:
        return "エラー詳細を解析できませんでした。生ログを参照してください。"

    # カテゴリ別にグループ化
    grouped: dict[CiErrorCategory, list[CiError]] = {}
    for err in summary.errors:
        grouped.setdefault(err.category, []).append(err)

    category_labels = {
        CiErrorCategory.TEST_FAILURE: "テスト失敗",
        CiErrorCategory.LINT_ERROR: "Lint エラー",
        CiErrorCategory.TYPE_ERROR: "型エラー",
        CiErrorCategory.BUILD_ERROR: "ビルドエラー",
        CiErrorCategory.UNKNOWN: "その他",
    }

    sections: list[str] = []

    # サマリー行
    test_info = ""
    if summary.failed_tests is not None and summary.total_tests is not None:
        test_info = f"- テスト: {summary.failed_tests} 件失敗 / {summary.total_tests} 件中\n"
    counts = ", ".join(f"{category_labels[cat]}: {len(errs)}件" for cat, errs in grouped.items())
    sections.append(f"## エラーサマリー\n{test_info}- エラー種別: {counts}")

    # カテゴリ別詳細
    for cat, errs in grouped.items():
        lines: list[str] = []
        for e in errs:
            loc = f"{e.file}:{e.line}" if e.file and e.line else (e.file or "不明")
            lines.append(f"  - {loc}: {e.message}")
        sections.append(f"### {category_labels[cat]}\n" + "\n".join(lines))

    return "\n\n".join(sections)
