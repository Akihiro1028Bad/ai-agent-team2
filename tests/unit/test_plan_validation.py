"""計画妥当性チェックのテスト."""

from __future__ import annotations

from ai_agent_orchestrator.phases.plan_validation import validate_plan


class TestValidatePlan:
    """validate_plan のテスト."""

    VALID_PLAN = """\
# 実装計画

## サブタスク

### subtask-1: モデル定義
- files: [`src/models.py`, `src/types.py`]
- depends_on: []
- description: データモデルの作成

### subtask-2: サービス層
- files: [`src/service.py`]
- depends_on: [1]
- description: ビジネスロジックの実装

### subtask-3: テスト
- files: [`tests/test_models.py`, `tests/test_service.py`]
- depends_on: [1, 2]
- description: ユニットテストの作成
"""

    def test_valid_plan_returns_no_errors(self) -> None:
        errors = validate_plan(self.VALID_PLAN, "/tmp/worktree")
        assert errors == []

    def test_no_subtask_section_returns_error(self) -> None:
        """## サブタスク セクション自体がない場合はセクション未検出エラーを返す。"""
        errors = validate_plan("# 計画\nただのテキスト", "/tmp/worktree")
        assert len(errors) == 1
        assert "## サブタスク セクションが見つかりません" in errors[0]

    def test_subtask_section_present_but_empty_returns_error(self) -> None:
        """## サブタスク セクションはあるが subtask-N ヘッダーが一つもない場合。"""
        plan = "# 設計書\n\n本文。\n\n## サブタスク\n\n(内容なし)\n"
        errors = validate_plan(plan, "/tmp/worktree")
        assert any("サブタスクが見つかりません" in e for e in errors)

    def test_non_sequential_ids_returns_error(self) -> None:
        plan = """\
## サブタスク

### subtask-1: A
- files: [`a.py`]
- depends_on: []

### subtask-3: B
- files: [`b.py`]
- depends_on: []
"""
        errors = validate_plan(plan, "/tmp/worktree")
        assert any("連番" in e for e in errors)

    def test_circular_dependency_detected(self) -> None:
        plan = """\
## サブタスク

### subtask-1: A
- files: [`a.py`]
- depends_on: [2]

### subtask-2: B
- files: [`b.py`]
- depends_on: [1]
"""
        errors = validate_plan(plan, "/tmp/worktree")
        assert any("循環" in e for e in errors)

    def test_undefined_dependency_detected(self) -> None:
        plan = """\
## サブタスク

### subtask-1: A
- files: [`a.py`]
- depends_on: [99]
"""
        errors = validate_plan(plan, "/tmp/worktree")
        assert any("未定義" in e for e in errors)

    def test_no_test_files_returns_error(self) -> None:
        plan = """\
## サブタスク

### subtask-1: A
- files: [`src/a.py`, `src/b.py`]
- depends_on: []
- description: 実装のみ
"""
        errors = validate_plan(plan, "/tmp/worktree")
        assert any("テストファイル" in e for e in errors)

    def test_empty_depends_on_is_valid(self) -> None:
        plan = """\
## サブタスク

### subtask-1: A
- files: [`src/a.py`, `tests/test_a.py`]
- depends_on: []
- description: 実装とテスト
"""
        errors = validate_plan(plan, "/tmp/worktree")
        assert errors == []

    def test_design_body_hash_headings_do_not_pollute_subtask_detection(self) -> None:
        """設計書本文の ### 見出しがサブタスク検証に混入しないことを確認する。"""
        plan = """\
# 設計書

## アーキテクチャ

### コンポーネント概要
詳細説明。

### データフロー
フロー説明。

## サブタスク

### subtask-1: 実装
- files: [`src/impl.py`, `tests/test_impl.py`]
- depends_on: []
- description: 実装とテスト
"""
        errors = validate_plan(plan, "/tmp/worktree")
        # 設計書本文の ### 見出しが混入しなければ subtask-1 のみが検出されエラーなし
        assert errors == []
