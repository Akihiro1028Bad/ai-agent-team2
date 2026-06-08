"""ContextEngine の単体テスト."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_agent_orchestrator.context.engine import ContextEngine


@pytest.fixture
def engine() -> ContextEngine:
    """ContextEngine インスタンスを返す."""
    return ContextEngine()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """テスト用のリポジトリ構造を作成."""
    # CLAUDE.md
    (tmp_path / "CLAUDE.md").write_text("# Project Rules\n- Use Python 3.13\n")

    # src ディレクトリ
    src = tmp_path / "src" / "myapp"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (src / "main.py").write_text("def main() -> None:\n    print('hello')\n")
    (src / "utils.py").write_text("def validate_email(addr: str) -> bool:\n    return '@' in addr\n")

    # tests ディレクトリ
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_main.py").write_text("def test_main() -> None:\n    pass\n")

    # docs ディレクトリ
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "design.md").write_text("# Design Document\nArchitecture overview.\n")
    (docs / "impl-plan.md").write_text("# Implementation Plan\nStep 1: ...\n")

    # .git ディレクトリ（除外されるべき）
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("bare = false\n")

    # __pycache__（除外されるべき）
    cache = src / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-313.pyc").write_text("bytecode")

    return tmp_path


# ──────────────────────────────────────
# build_context テスト
# ──────────────────────────────────────


async def test_build_context_hearing_phase(engine: ContextEngine, repo: Path) -> None:
    """hearing フェーズでは repo 構造、CLAUDE.md、関連ファイルを含む."""
    result = await engine.build_context(str(repo), "Fix `validate_email` function", "hearing")

    assert "## リポジトリ構造" in result
    assert "## プロジェクト規約" in result
    assert "Project Rules" in result
    # 設計書と実装計画は含まれない
    assert "## 設計書" not in result
    assert "## 実装計画" not in result


async def test_build_context_implement_phase(engine: ContextEngine, repo: Path) -> None:
    """implement フェーズでは設計書と実装計画を両方含む."""
    result = await engine.build_context(str(repo), "Implement the feature", "implement")

    assert "## リポジトリ構造" in result
    assert "## 設計書" in result
    assert "## 実装計画" in result
    assert "Implementation Plan" in result


async def test_build_context_ci_fix_phase(engine: ContextEngine, repo: Path) -> None:
    """ci_fix フェーズでも設計書と実装計画を含む."""
    result = await engine.build_context(str(repo), "Fix CI", "ci-fix")

    assert "## 設計書" in result
    assert "## 実装計画" in result


async def test_build_context_sections_separated_by_divider(engine: ContextEngine, repo: Path) -> None:
    """各セクションは --- で区切られる."""
    result = await engine.build_context(str(repo), "Some issue", "hearing")
    assert "\n\n---\n\n" in result


# ──────────────────────────────────────
# _read_claude_md テスト
# ──────────────────────────────────────


async def test_read_claude_md_exists(engine: ContextEngine, repo: Path) -> None:
    """CLAUDE.md が存在する場合に内容を返す."""
    result = await engine._read_claude_md(str(repo))
    assert result is not None
    assert "Project Rules" in result


async def test_read_claude_md_missing(engine: ContextEngine, tmp_path: Path) -> None:
    """CLAUDE.md がない場合は None を返す."""
    result = await engine._read_claude_md(str(tmp_path))
    assert result is None


# ──────────────────────────────────────
# _read_design_doc テスト
# ──────────────────────────────────────


async def test_read_design_doc_generic(engine: ContextEngine, repo: Path) -> None:
    """汎用の design.md を読む."""
    result = await engine._read_design_doc(str(repo))
    assert result is not None
    assert "Design Document" in result


async def test_read_design_doc_issue_specific(engine: ContextEngine, repo: Path) -> None:
    """Issue固有の設計書を優先する."""
    (repo / "docs" / "design-issue-42.md").write_text("# Issue 42 Design\n")
    result = await engine._read_design_doc(str(repo), issue_number=42)
    assert result is not None
    assert "Issue 42 Design" in result


async def test_read_design_doc_missing(engine: ContextEngine, tmp_path: Path) -> None:
    """設計書がない場合は None を返す."""
    result = await engine._read_design_doc(str(tmp_path))
    assert result is None


# ──────────────────────────────────────
# _read_impl_plan テスト
# ──────────────────────────────────────


async def test_read_impl_plan_exists(engine: ContextEngine, repo: Path) -> None:
    """impl-plan.md を読む."""
    result = await engine.read_impl_plan(str(repo))
    assert result is not None
    assert "Implementation Plan" in result


async def test_read_impl_plan_missing(engine: ContextEngine, tmp_path: Path) -> None:
    """実装計画がない場合は None を返す."""
    result = await engine.read_impl_plan(str(tmp_path))
    assert result is None


async def test_read_impl_plan_unified_design_doc_priority(engine: ContextEngine, tmp_path: Path) -> None:
    """統合設計書 docs/designs/issue-N.md を最優先で読む."""
    designs_dir = tmp_path / "docs" / "designs"
    designs_dir.mkdir(parents=True)
    (designs_dir / "issue-42.md").write_text("# Issue 42 設計書\n\n## サブタスク\n- [ ] タスク1\n- [ ] タスク2\n")
    result = await engine.read_impl_plan(str(tmp_path), issue_number=42)
    assert result is not None
    assert "## サブタスク" in result
    assert "タスク1" in result


async def test_read_impl_plan_fallback_to_plan_md(engine: ContextEngine, tmp_path: Path) -> None:
    """統合設計書がない場合は issue-N-plan.md にフォールバックする."""
    designs_dir = tmp_path / "docs" / "designs"
    designs_dir.mkdir(parents=True)
    (designs_dir / "issue-42-plan.md").write_text("# Issue 42 実装計画\nStep 1: ...\n")
    result = await engine.read_impl_plan(str(tmp_path), issue_number=42)
    assert result is not None
    assert "Issue 42 実装計画" in result


async def test_read_impl_plan_unified_design_takes_priority_over_plan(engine: ContextEngine, tmp_path: Path) -> None:
    """統合設計書と issue-N-plan.md が両方ある場合は統合設計書を優先する."""
    designs_dir = tmp_path / "docs" / "designs"
    designs_dir.mkdir(parents=True)
    (designs_dir / "issue-42.md").write_text("# 統合設計書\n## サブタスク\n- [ ] 統合タスク\n")
    (designs_dir / "issue-42-plan.md").write_text("# 計画書\nStep 1: ...\n")
    result = await engine.read_impl_plan(str(tmp_path), issue_number=42)
    assert result is not None
    assert "統合設計書" in result
    assert "計画書" not in result


# ──────────────────────────────────────
# _get_repo_structure テスト
# ──────────────────────────────────────


async def test_repo_structure_includes_src(engine: ContextEngine, repo: Path) -> None:
    """ディレクトリツリーに src/ が含まれる."""
    result = await engine._get_repo_structure(str(repo))
    assert "src/" in result


async def test_repo_structure_excludes_git(engine: ContextEngine, repo: Path) -> None:
    """.git ディレクトリは除外される."""
    result = await engine._get_repo_structure(str(repo))
    assert ".git" not in result


async def test_repo_structure_excludes_pycache(engine: ContextEngine, repo: Path) -> None:
    """__pycache__ ディレクトリは除外される."""
    result = await engine._get_repo_structure(str(repo))
    assert "__pycache__" not in result


async def test_repo_structure_max_depth(engine: ContextEngine, repo: Path) -> None:
    """max_depth=1 で深い階層は含まない."""
    result = await engine._get_repo_structure(str(repo), max_depth=1)
    # depth=1 では src/ は見えるが src/myapp/ の中身は見えない
    assert "src/" in result


async def test_repo_structure_nonexistent(engine: ContextEngine, tmp_path: Path) -> None:
    """存在しないディレクトリの場合."""
    result = await engine._get_repo_structure(str(tmp_path / "nonexistent"))
    assert result == "(directory not found)"


# ──────────────────────────────────────
# _find_related_files テスト
# ──────────────────────────────────────


async def test_find_related_files(engine: ContextEngine, repo: Path) -> None:
    """キーワードに基づいてファイルを検索."""
    files = await engine._find_related_files(str(repo), ["validate_email"])
    assert any("utils.py" in f for f in files)


async def test_find_related_files_no_keywords(engine: ContextEngine, repo: Path) -> None:
    """キーワードが空なら空リストを返す."""
    files = await engine._find_related_files(str(repo), [])
    assert files == []


async def test_find_related_files_no_match(engine: ContextEngine, repo: Path) -> None:
    """マッチしない場合は空リストを返す."""
    files = await engine._find_related_files(str(repo), ["nonexistent_xyz_func"])
    assert files == []


async def test_find_related_files_max_results(engine: ContextEngine, tmp_path: Path) -> None:
    """結果が20件に制限される."""
    # 25個のファイルを作成
    for i in range(25):
        (tmp_path / f"file_{i}.py").write_text(f"# keyword_target_{i}\nkeyword_target\n")

    files = await engine._find_related_files(str(tmp_path), ["keyword_target"])
    assert len(files) <= 20


# ──────────────────────────────────────
# _extract_keywords テスト
# ──────────────────────────────────────


def test_extract_keywords_backtick() -> None:
    """バッククォート内のトークンを抽出."""
    keywords = ContextEngine._extract_keywords("Fix `validate_email` in module")
    assert "validate_email" in keywords


def test_extract_keywords_file_path() -> None:
    """ファイルパスを抽出."""
    keywords = ContextEngine._extract_keywords("Check src/utils.py for bugs")
    assert "src/utils.py" in keywords


def test_extract_keywords_empty() -> None:
    """空文字列ならからリストを返す."""
    keywords = ContextEngine._extract_keywords("")
    assert keywords == []


def test_extract_keywords_stop_words_excluded() -> None:
    """ストップワードは除外される."""
    keywords = ContextEngine._extract_keywords("the class should return None")
    assert "the" not in keywords
    assert "class" not in keywords
    assert "return" not in keywords
    assert "None" not in keywords


# ──────────────────────────────────────
# 異常系テスト
# ──────────────────────────────────────


async def test_build_context_empty_repo(engine: ContextEngine, tmp_path: Path) -> None:
    """空のディレクトリでもエラーにならない."""
    result = await engine.build_context(str(tmp_path), "", "hearing")
    assert "## リポジトリ構造" in result
    # CLAUDE.md がないので規約セクションはない
    assert "## プロジェクト規約" not in result


async def test_build_context_nonexistent_path(engine: ContextEngine, tmp_path: Path) -> None:
    """存在しないパスでもエラーにならない."""
    result = await engine.build_context(str(tmp_path / "nonexistent"), "", "hearing")
    assert "## リポジトリ構造" in result
    assert "(directory not found)" in result


async def test_build_context_implement_no_design_doc_duplication(engine: ContextEngine, tmp_path: Path) -> None:
    """統合設計書(issue-N.md)を implement で読む際、設計書全文が二重掲載されないこと.

    設計書と実装計画が同一ファイルに統合されたため、## 設計書 と ## 実装計画 の
    両セクションに同じ全文が載るとトークンが肥大する。## 実装計画 側は
    ## サブタスク セクションのみを載せる。
    """
    designs = tmp_path / "docs" / "designs"
    designs.mkdir(parents=True)
    body = (
        "# 設計書\n\n## 概要\nプロフィール画面を追加する。\n\n"
        "## アーキテクチャ\nServer/Client 分割。\n\n"
        "## サブタスク\n\n"
        "### subtask-1: Route Handler\n"
        "- files: [`route.ts`, `route.test.ts`]\n"
        "- depends_on: []\n"
    )
    (designs / "issue-42.md").write_text(body, encoding="utf-8")

    result = await engine.build_context(str(tmp_path), "Implement", "implement", issue_number=42)

    # 設計書見出しは1回だけ（## 設計書 として全文、## 実装計画 はサブタスクのみ）
    assert result.count("## アーキテクチャ") == 1, "設計書本文が二重掲載されている"
    assert "## 設計書" in result
    assert "## 実装計画" in result
    # 実装計画セクションにはサブタスク構造が含まれる
    assert "### subtask-1: Route Handler" in result


async def test_build_context_implement_separate_plan_file_included_in_full(
    engine: ContextEngine, tmp_path: Path
) -> None:
    """後方互換: 設計書と実装計画が別ファイルの場合は実装計画を全文掲載する.

    統合設計書 issue-N.md が無く、設計書(design.md)と計画(issue-N-plan.md)が
    別ファイルで存在する旧構成では、impl_plan != design_doc となり else 分岐で
    実装計画が全文掲載される。
    """
    docs = tmp_path / "docs"
    designs = docs / "designs"
    designs.mkdir(parents=True)
    # 統合設計書(issue-42.md)は作らない。設計書は別ファイル design.md。
    (docs / "design.md").write_text("# 設計書\n## 概要\n設計のみ。\n", encoding="utf-8")
    plan_body = "# 実装計画\n## サブタスク\n### subtask-1: x\n- files: [`a.py`]\n- depends_on: []\n"
    (designs / "issue-42-plan.md").write_text(plan_body, encoding="utf-8")

    result = await engine.build_context(str(tmp_path), "Implement", "implement", issue_number=42)

    # 設計書と実装計画は別ファイル → 実装計画は全文掲載される
    assert "## 設計書" in result
    assert "## 実装計画" in result
    assert "### subtask-1: x" in result
    assert "# 実装計画" in result  # plan.md の全文が載っている
