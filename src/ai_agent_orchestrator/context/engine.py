"""ContextEngine (リポマップ + 関連ファイル検索).

フェーズに応じたコンテキストを構築し、AIに渡す効率的なプロンプトを生成する。
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 設計書・実装計画を参照するフェーズ
_DESIGN_DOC_PHASES = frozenset({"planning", "implement", "ci_fix"})
_IMPL_PLAN_PHASES = frozenset({"implement", "ci_fix"})

# ディレクトリツリーで除外するパターン
_IGNORE_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".venv",
        "venv",
        ".tox",
        ".eggs",
        "*.egg-info",
        "dist",
        "build",
        ".claude",
    }
)

# grep 対象の拡張子
_SOURCE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".md",
        ".rst",
        ".sql",
        ".sh",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".rb",
    }
)


class ContextEngine:
    """リポマップ生成と自動コンテキスト収集.

    worktree のファイルシステムを走査し、フェーズに応じたコンテキスト文字列を構築する。
    """

    async def build_context(
        self,
        worktree_path: str,
        issue_body: str,
        phase: str,
    ) -> str:
        """フェーズに応じたコンテキストを構築.

        Args:
            worktree_path: worktree のファイルシステムパス.
            issue_body: Issue本文 (キーワード抽出に使用).
            phase: 現在のフェーズ名.

        Returns:
            コンテキスト文字列 (Markdown形式、セクション区切り ``---``).
        """
        parts: list[str] = []

        # 1. リポマップ (ディレクトリ構造)
        repo_map = await self._get_repo_structure(worktree_path)
        parts.append(f"## リポジトリ構造\n```\n{repo_map}\n```")

        # 2. CLAUDE.md (存在すれば)
        claude_md = await self._read_claude_md(worktree_path)
        if claude_md:
            parts.append(f"## プロジェクト規約\n{claude_md}")

        # 3. 関連ファイルの自動検出 (Issue内容からキーワード抽出)
        keywords = self._extract_keywords(issue_body)
        if keywords:
            relevant_files = await self._find_related_files(worktree_path, keywords)
            if relevant_files:
                file_list = "\n".join(f"- `{f}`" for f in relevant_files)
                parts.append(f"## 関連ファイル\n{file_list}")

        # 4. 設計書 (planning / implement / ci_fix フェーズ)
        if phase in _DESIGN_DOC_PHASES:
            design_doc = await self._read_design_doc(worktree_path)
            if design_doc:
                parts.append(f"## 設計書\n{design_doc}")

        # 5. 実装計画 (implement / ci_fix フェーズ)
        if phase in _IMPL_PLAN_PHASES:
            impl_plan = await self._read_impl_plan(worktree_path)
            if impl_plan:
                parts.append(f"## 実装計画\n{impl_plan}")

        return "\n\n---\n\n".join(parts)

    async def _read_claude_md(self, repo_path: str) -> str | None:
        """リポジトリの CLAUDE.md を読み込む.

        Args:
            repo_path: リポジトリのルートパス.

        Returns:
            CLAUDE.md の内容。存在しなければ None。
        """
        return await self._read_file_if_exists(Path(repo_path) / "CLAUDE.md")

    async def _read_design_doc(self, repo_path: str, issue_number: int | None = None) -> str | None:
        """設計書を読み込む.

        docs/design.md または docs/design-*.md を探す。
        issue_number が指定されている場合は issue 固有の設計書も探す。

        Args:
            repo_path: リポジトリのルートパス.
            issue_number: Issue番号 (オプション).

        Returns:
            設計書の内容。存在しなければ None。
        """
        docs_dir = Path(repo_path) / "docs"

        # issue 固有の設計書を優先
        if issue_number is not None:
            issue_doc = docs_dir / f"design-issue-{issue_number}.md"
            content = await self._read_file_if_exists(issue_doc)
            if content:
                return content

        # 汎用設計書
        for candidate in [
            docs_dir / "design.md",
            docs_dir / "design-python.md",
        ]:
            content = await self._read_file_if_exists(candidate)
            if content:
                return content

        return None

    async def _read_impl_plan(self, repo_path: str, issue_number: int | None = None) -> str | None:
        """実装計画を読み込む.

        Args:
            repo_path: リポジトリのルートパス.
            issue_number: Issue番号 (オプション).

        Returns:
            実装計画の内容。存在しなければ None。
        """
        docs_dir = Path(repo_path) / "docs"

        # issue 固有の実装計画を優先
        if issue_number is not None:
            issue_plan = docs_dir / f"impl-plan-issue-{issue_number}.md"
            content = await self._read_file_if_exists(issue_plan)
            if content:
                return content

        # 汎用実装計画
        plan_path = docs_dir / "impl-plan.md"
        return await self._read_file_if_exists(plan_path)

    async def _get_repo_structure(self, repo_path: str, max_depth: int = 3) -> str:
        """リポジトリのディレクトリツリーを生成.

        Args:
            repo_path: リポジトリのルートパス.
            max_depth: 探索する最大深さ.

        Returns:
            ツリー形式の文字列.
        """
        root = Path(repo_path)
        if not root.is_dir():
            return "(directory not found)"

        lines: list[str] = []
        await asyncio.to_thread(self._walk_tree, root, root, lines, max_depth, 0)
        return "\n".join(lines) if lines else "(empty)"

    def _walk_tree(
        self,
        root: Path,
        current: Path,
        lines: list[str],
        max_depth: int,
        depth: int,
    ) -> None:
        """ディレクトリツリーを再帰的に構築 (同期ヘルパー).

        Args:
            root: リポジトリのルート.
            current: 現在のディレクトリ.
            lines: 出力行リスト (破壊的に追加).
            max_depth: 最大深さ.
            depth: 現在の深さ.
        """
        if depth > max_depth:
            return

        try:
            entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
        except PermissionError:
            return

        for entry in entries:
            if entry.name in _IGNORE_DIRS:
                continue
            # egg-info パターンのマッチ
            if entry.name.endswith(".egg-info"):
                continue

            indent = "  " * depth
            relative = entry.relative_to(root)

            if entry.is_dir():
                lines.append(f"{indent}{relative}/")
                self._walk_tree(root, entry, lines, max_depth, depth + 1)
            else:
                lines.append(f"{indent}{relative}")

    async def _find_related_files(self, repo_path: str, keywords: list[str]) -> list[str]:
        """キーワードに基づいて関連ファイルを検索.

        Args:
            repo_path: リポジトリのルートパス.
            keywords: 検索キーワードのリスト.

        Returns:
            関連ファイルの相対パスリスト (重複なし、最大20件).
        """
        if not keywords:
            return []

        root = Path(repo_path)
        if not root.is_dir():
            return []

        found: dict[str, int] = {}  # path -> hit count
        await asyncio.to_thread(self._grep_files, root, keywords, found)

        # ヒット数の多い順にソートし、上位20件を返す
        sorted_files = sorted(found.items(), key=lambda x: x[1], reverse=True)
        return [path for path, _ in sorted_files[:20]]

    def _grep_files(
        self,
        root: Path,
        keywords: list[str],
        found: dict[str, int],
    ) -> None:
        """ファイル内容をキーワードで検索 (同期ヘルパー).

        Args:
            root: リポジトリのルート.
            keywords: 検索キーワード.
            found: 結果辞書 (破壊的に追加).
        """
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in _SOURCE_EXTENSIONS:
                continue
            # 除外ディレクトリ内のファイルをスキップ
            parts = path.relative_to(root).parts
            if any(part in _IGNORE_DIRS or part.endswith(".egg-info") for part in parts):
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except (OSError, UnicodeDecodeError):
                continue

            relative = str(path.relative_to(root))
            for kw in keywords:
                count = content.lower().count(kw.lower())
                if count > 0:
                    found[relative] = found.get(relative, 0) + count

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        """テキストからキーワードを抽出.

        バッククォート内のコード片、キャメルケース/スネークケースの識別子を抽出する。

        Args:
            text: 入力テキスト (Issue本文など).

        Returns:
            キーワードのリスト (重複なし).
        """
        if not text:
            return []

        keywords: set[str] = set()

        # バッククォート内のコード片
        for match in re.finditer(r"`([^`]+)`", text):
            token = match.group(1).strip()
            if len(token) >= 2:
                keywords.add(token)

        # ファイルパスっぽいもの
        for match in re.finditer(r"[\w./\\-]+\.\w{1,5}", text):
            token = match.group(0)
            if "/" in token or "\\" in token:
                keywords.add(token)

        # snake_case や CamelCase の識別子 (3文字以上)
        for match in re.finditer(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text):
            token = match.group(0)
            # ストップワードを除外
            if token.lower() not in _STOP_WORDS:
                keywords.add(token)

        return list(keywords)

    @staticmethod
    async def _read_file_if_exists(path: Path) -> str | None:
        """ファイルが存在すれば内容を返す.

        Args:
            path: ファイルパス.

        Returns:
            ファイルの内容。存在しなければ None。
        """
        try:
            if path.is_file():
                return await asyncio.to_thread(path.read_text, encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
        return None


# 検索キーワードから除外する一般的な単語
_STOP_WORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "from",
        "not",
        "but",
        "are",
        "was",
        "were",
        "been",
        "have",
        "has",
        "had",
        "will",
        "can",
        "should",
        "would",
        "could",
        "may",
        "might",
        "shall",
        "does",
        "did",
        "also",
        "into",
        "when",
        "where",
        "which",
        "what",
        "how",
        "who",
        "all",
        "each",
        "every",
        "both",
        "few",
        "more",
        "most",
        "some",
        "any",
        "other",
        "than",
        "then",
        "now",
        "just",
        "only",
        "very",
        "use",
        "using",
        "used",
        "new",
        "old",
        "add",
        "get",
        "set",
        "def",
        "class",
        "import",
        "return",
        "none",
        "true",
        "false",
        "str",
        "int",
        "bool",
        "list",
        "dict",
        "tuple",
        "float",
        "self",
        "cls",
        "args",
        "kwargs",
    }
)
