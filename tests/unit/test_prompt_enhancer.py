"""プロンプト強化モジュールのテスト."""

from __future__ import annotations

from ai_agent_orchestrator.phases.prompt_enhancer import enhance_prompt


class TestEnhancePrompt:
    """enhance_prompt のテスト."""

    BASE = "ベースプロンプト"

    def test_implement_includes_all_sections(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "テスト要件" in result
        assert "セキュリティ要件" in result
        assert "コーディング規約" in result

    def test_implement_includes_coverage_target(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "80%" in result

    def test_implement_includes_bandit(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "bandit" in result

    def test_implement_includes_mypy_strict(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "mypy strict" in result

    def test_ci_fix_includes_coding_standards_only(self) -> None:
        result = enhance_prompt(self.BASE, "ci-fix")
        assert "コーディング規約" in result
        assert "テスト要件" not in result
        assert "セキュリティ要件" not in result

    def test_design_includes_test_strategy_and_security(self) -> None:
        result = enhance_prompt(self.BASE, "design")
        assert "テスト戦略" in result
        assert "セキュリティ考慮事項" in result
        assert "コーディング規約" in result

    def test_impl_revise_includes_test_and_coding(self) -> None:
        # U5 統合後: impl-revise → revise
        result = enhance_prompt(self.BASE, "revise")
        assert "テスト要件" in result
        assert "コーディング規約" in result
        assert "セキュリティ要件" not in result

    def test_hearing_returns_base_unchanged(self) -> None:
        result = enhance_prompt(self.BASE, "hearing")
        assert result == self.BASE

    def test_type_detection_returns_base_unchanged(self) -> None:
        result = enhance_prompt(self.BASE, "type-detection")
        assert result == self.BASE

    def test_unknown_phase_returns_base_unchanged(self) -> None:
        result = enhance_prompt(self.BASE, "nonexistent")
        assert result == self.BASE

    def test_base_prompt_preserved(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert result.startswith(self.BASE)

    def test_fix_includes_all_sections(self) -> None:
        result = enhance_prompt(self.BASE, "fix")
        assert "テスト要件" in result
        assert "セキュリティ要件" in result
        assert "コーディング規約" in result

    def test_design_revise_includes_test_strategy(self) -> None:
        # U5 統合後: design-revise → revise
        result = enhance_prompt(self.BASE, "revise")
        assert "テスト要件" in result  # revise は _TEST_REQUIREMENTS を含む
        assert "コーディング規約" in result

    # --- ブラウザ検証セクション ---

    def test_implement_includes_browser_verification(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "ブラウザ検証" in result

    def test_fix_includes_browser_verification(self) -> None:
        result = enhance_prompt(self.BASE, "fix")
        assert "ブラウザ検証" in result

    def test_ci_fix_no_browser_verification(self) -> None:
        result = enhance_prompt(self.BASE, "ci-fix")
        assert "ブラウザ検証" not in result

    def test_impl_revise_includes_browser_verification(self) -> None:
        # U5 統合後: impl-revise → revise
        result = enhance_prompt(self.BASE, "revise")
        assert "ブラウザ検証" in result

    def test_browser_verification_mentions_evidence(self) -> None:
        result = enhance_prompt(self.BASE, "implement")
        assert "エビデンス" in result

    def test_design_no_browser_verification(self) -> None:
        result = enhance_prompt(self.BASE, "design")
        assert "ブラウザ検証" not in result

    def test_hearing_no_browser_verification(self) -> None:
        result = enhance_prompt(self.BASE, "hearing")
        assert "ブラウザ検証" not in result

    def test_design_includes_test_requirements(self) -> None:
        """design フェーズに _TEST_REQUIREMENTS が含まれること."""
        result = enhance_prompt(self.BASE, "design")
        assert "テスト要件" in result
        assert "80%" in result
        assert "pytest-asyncio" in result
