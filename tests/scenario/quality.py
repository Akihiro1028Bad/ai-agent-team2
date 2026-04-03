"""Per-phase quality assertion functions for scenario tests."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityResult:
    """Result of a quality check."""

    passed: bool
    phase: str
    checks: list[str]
    failures: list[str]

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        details = "\n".join(f"  - {f}" for f in self.failures) if self.failures else "  (all checks passed)"
        return f"[{status}] {self.phase}:\n{details}"


def _get_body(comment: Any) -> str:
    """Extract body from a comment object."""
    return getattr(comment, "body", "") or ""


# ---------------------------------------------------------------------------
# TYPE_DETECTION
# ---------------------------------------------------------------------------


def assert_type_detection_quality(
    issue_type: str,
    expected_type: str,
    bot_comment: Any | None = None,
) -> QualityResult:
    """Verify TYPE_DETECTION produced a correct classification."""
    checks = []
    failures = []

    # Check type classification
    checks.append(f"issue_type == '{expected_type}'")
    if issue_type != expected_type:
        failures.append(f"Expected type '{expected_type}', got '{issue_type}'")

    # Check bot comment exists
    if bot_comment is not None:
        body = _get_body(bot_comment)
        checks.append("bot comment is non-empty")
        if len(body) < 20:
            failures.append(f"Bot comment too short ({len(body)} chars)")
    else:
        checks.append("bot comment exists")
        failures.append("No bot comment found")

    return QualityResult(
        passed=len(failures) == 0,
        phase="type-detection",
        checks=checks,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# ANALYSIS (Bug)
# ---------------------------------------------------------------------------

_ANALYSIS_KEYWORDS = ["原因", "修正", "方針", "analysis", "cause", "fix", "plan", "approach"]


def assert_analysis_quality(bot_comment: Any | None) -> QualityResult:
    """Verify ANALYSIS produced a meaningful analysis comment."""
    checks = []
    failures = []

    if bot_comment is None:
        return QualityResult(passed=False, phase="analysis", checks=["bot comment exists"], failures=["No bot comment"])

    body = _get_body(bot_comment)

    checks.append("comment length > 200")
    if len(body) < 200:
        failures.append(f"Comment too short ({len(body)} chars, want > 200)")

    checks.append("contains analysis keywords")
    body_lower = body.lower()
    found = [kw for kw in _ANALYSIS_KEYWORDS if kw.lower() in body_lower]
    if not found:
        failures.append(f"No analysis keywords found (expected any of: {_ANALYSIS_KEYWORDS})")

    return QualityResult(passed=len(failures) == 0, phase="analysis", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# HEARING (Feature)
# ---------------------------------------------------------------------------


def assert_hearing_quality(bot_comment: Any | None) -> QualityResult:
    """Verify HEARING produced a meaningful comment (questions or READY)."""
    checks = []
    failures = []

    if bot_comment is None:
        return QualityResult(passed=False, phase="hearing", checks=["bot comment exists"], failures=["No bot comment"])

    body = _get_body(bot_comment)

    checks.append("comment length > 100")
    if len(body) < 100:
        failures.append(f"Comment too short ({len(body)} chars, want > 100)")

    checks.append("contains question or READY indicator")
    has_question = "?" in body or "？" in body
    has_ready = "READY" in body.upper() or "準備" in body or "十分" in body
    if not has_question and not has_ready:
        failures.append("Comment has neither questions (?) nor READY indicator")

    return QualityResult(passed=len(failures) == 0, phase="hearing", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# DESIGN (Feature-M)
# ---------------------------------------------------------------------------


def assert_design_quality(
    pr: Any | None,
    issue_number: int,
    diff_files: list[str] | None = None,
) -> QualityResult:
    """Verify DESIGN created a PR with design docs."""
    checks = []
    failures = []

    if pr is None:
        return QualityResult(passed=False, phase="design", checks=["design PR exists"], failures=["No design PR"])

    # PR body quality
    pr_body = getattr(pr, "body", "") or ""
    checks.append("PR body length > 50")
    if len(pr_body) < 50:
        failures.append(f"PR body too short ({len(pr_body)} chars)")

    # PR references issue
    checks.append(f"PR references issue #{issue_number}")
    if f"#{issue_number}" not in pr_body:
        failures.append(f"PR body does not reference #{issue_number}")

    # Design docs in diff
    if diff_files is not None:
        checks.append("design doc files in diff")
        doc_files = [f for f in diff_files if "docs/" in f or "design" in f.lower()]
        if not doc_files:
            failures.append("No design doc files found in PR diff")

    return QualityResult(passed=len(failures) == 0, phase="design", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# IMPLEMENTATION (FIX / IMPLEMENT)
# ---------------------------------------------------------------------------


def assert_implementation_quality(
    build_rc: int,
    build_stderr: str,
    test_rc: int,
    test_stderr: str,
    diff_files: list[str] | None = None,
) -> QualityResult:
    """Verify implementation quality: build, tests, test files added."""
    checks = []
    failures = []

    checks.append("npm run build succeeds")
    if build_rc != 0:
        failures.append(f"Build failed (exit={build_rc}): {build_stderr[:300]}")

    checks.append("npm test succeeds")
    if test_rc != 0:
        failures.append(f"Tests failed (exit={test_rc}): {test_stderr[:300]}")

    if diff_files is not None:
        checks.append("test files added/modified")
        test_files = [f for f in diff_files if ".test." in f or "__tests__" in f or ".spec." in f]
        if not test_files:
            failures.append("No test files added or modified")

    return QualityResult(passed=len(failures) == 0, phase="implementation", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# PR quality (generic)
# ---------------------------------------------------------------------------


def assert_pr_quality(
    pr: Any,
    issue_number: int,
) -> QualityResult:
    """Verify PR quality: body, issue reference, title."""
    checks = []
    failures = []

    pr_body = getattr(pr, "body", "") or ""
    pr_title = getattr(pr, "title", "") or ""

    checks.append("PR title is substantive (> 10 chars)")
    if len(pr_title) < 10:
        failures.append(f"PR title too short: '{pr_title}'")

    checks.append("PR body length > 50")
    if len(pr_body) < 50:
        failures.append(f"PR body too short ({len(pr_body)} chars)")

    checks.append(f"PR references issue #{issue_number}")
    if f"#{issue_number}" not in pr_body and f"#{issue_number}" not in pr_title:
        failures.append(f"PR does not reference #{issue_number}")

    return QualityResult(passed=len(failures) == 0, phase="pr-quality", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# DONE
# ---------------------------------------------------------------------------


def assert_done_quality(
    issue_state: str,
    has_summary_comment: bool,
    has_done_label: bool,
) -> QualityResult:
    """Verify DONE phase: issue closed, summary comment, label."""
    checks = []
    failures = []

    checks.append("issue is closed")
    if issue_state != "closed":
        failures.append(f"Issue state is '{issue_state}', expected 'closed'")

    checks.append("summary comment exists")
    if not has_summary_comment:
        failures.append("No summary/done bot comment found")

    checks.append("phase:done label present")
    if not has_done_label:
        failures.append("No 'phase:done' label found")

    return QualityResult(passed=len(failures) == 0, phase="done", checks=checks, failures=failures)


# ---------------------------------------------------------------------------
# SPLIT_PROPOSAL (Feature-L)
# ---------------------------------------------------------------------------

_SPLIT_KEYWORDS = ["分割", "split", "sub-issue", "サブ", "child", "子issue"]


def assert_split_proposal_quality(bot_comment: Any | None) -> QualityResult:
    """Verify SPLIT_PROPOSAL produced a meaningful split proposal."""
    checks = []
    failures = []

    if bot_comment is None:
        return QualityResult(
            passed=False, phase="split-proposal", checks=["bot comment exists"], failures=["No bot comment"]
        )

    body = _get_body(bot_comment)

    checks.append("comment length > 200")
    if len(body) < 200:
        failures.append(f"Comment too short ({len(body)} chars, want > 200)")

    checks.append("contains split keywords")
    body_lower = body.lower()
    found = [kw for kw in _SPLIT_KEYWORDS if kw.lower() in body_lower]
    if not found:
        failures.append(f"No split keywords found (expected any of: {_SPLIT_KEYWORDS})")

    checks.append("proposes multiple items")
    # Check for numbered list or bullet points (at least 2)
    import re

    numbered = re.findall(r"^\s*\d+[\.\)]\s", body, re.MULTILINE)
    bulleted = re.findall(r"^\s*[-*]\s", body, re.MULTILINE)
    if len(numbered) < 2 and len(bulleted) < 2:
        failures.append("Split proposal doesn't contain multiple items (< 2 list items)")

    return QualityResult(passed=len(failures) == 0, phase="split-proposal", checks=checks, failures=failures)
