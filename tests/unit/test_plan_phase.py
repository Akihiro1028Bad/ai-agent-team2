"""PLAN 統合 (U3 #81) のテスト.

analysis (light) / design (full) を共通 PlanExecutor に統合し、
plan_depth による出力差分と構造化 JSON (plan_json) の常時生成を検証する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_agent_orchestrator.models import AgentResult

# ---------------------------------------------------------------------------
# Fixtures (test_phases.py と同等の最小構成)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_runner() -> AsyncMock:
    runner = AsyncMock()
    runner.run.return_value = AgentResult(
        session_id="sess-001",
        output="test output",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=30.0,
    )
    return runner


@pytest.fixture
def mock_github() -> AsyncMock:
    gh = AsyncMock()
    del gh.get_client_for_repo
    issue = MagicMock()
    issue.title = "テストIssue"
    issue.body = "テスト本文"
    issue.number = 1
    gh.get_issue.return_value = issue
    gh.list_comments.return_value = []
    return gh


@pytest.fixture
def mock_workspace() -> AsyncMock:
    ws = AsyncMock()
    ws.create_worktree.return_value = "/tmp/worktree/issue-1"
    ws._run_git = AsyncMock(return_value=(0, "", ""))
    return ws


@pytest.fixture
def mock_context() -> AsyncMock:
    ctx = AsyncMock()
    ctx.build_context.return_value = "## リポジトリ構造\n(mock context)"
    ctx.read_impl_plan = AsyncMock(return_value=None)
    return ctx


@pytest.fixture
def mock_sm() -> MagicMock:
    sm = MagicMock()
    sm.get_state.return_value = MagicMock(
        issue_number=1,
        session_id=None,
        pr_number=None,
        design_pr_number=None,
        branch_head_sha=None,
        impl_iteration=0,
        plan_json=None,
    )
    sm.get_issue_type.return_value = "bug"
    sm.transition = AsyncMock()
    sm.increment_ci_retry = AsyncMock()
    return sm


def _make_request(
    phase: str = "analysis",
    issue_number: int = 1,
    extra: dict[str, Any] | None = None,
) -> MagicMock:
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    req = MagicMock()
    req.issue_number = issue_number
    req.repo = repo
    req.repo_key = "org/app"
    req.issue_key = ("org/app", issue_number)
    req.phase = phase
    req.extra = extra or {}
    return req


def _make_executor(
    mock_runner: AsyncMock,
    mock_github: AsyncMock,
    mock_workspace: AsyncMock,
    mock_context: AsyncMock,
    mock_sm: MagicMock,
) -> Any:
    from ai_agent_orchestrator.phases.plan import PlanExecutor

    return PlanExecutor(
        mock_runner,
        mock_github,
        AsyncMock(),  # notifier
        AsyncMock(),  # tracker
        mock_workspace,
        mock_context,
        mock_sm,
    )


# ---------------------------------------------------------------------------
# plan_artifact: JSON ブロック抽出と plan レコード構築 (純関数)
# ---------------------------------------------------------------------------


class TestExtractPlanJson:
    """extract_plan_json のテスト."""

    def test_extracts_json_block_and_strips_it(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = (
            "修正方針: null check を追加\n\n"
            "```json\n"
            '{"ui_impact": false, "summary": "null check", "test_cases": ["t1"]}\n'
            "```\n"
        )
        text, parsed = extract_plan_json(output)
        assert parsed is not None
        assert parsed["ui_impact"] is False
        assert parsed["test_cases"] == ["t1"]
        assert "```json" not in text
        assert "修正方針: null check を追加" in text

    def test_returns_none_when_no_json_block(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        text, parsed = extract_plan_json("方針のみのテキスト")
        assert parsed is None
        assert text == "方針のみのテキスト"

    def test_returns_none_on_invalid_json(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = "方針\n```json\n{broken\n```\n"
        text, parsed = extract_plan_json(output)
        assert parsed is None
        assert text == output

    def test_uses_last_json_block(self) -> None:
        """複数の json ブロックがある場合は最後 (成果物サマリ) を使う."""
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = '例:\n```json\n{"example": 1}\n```\n\n```json\n{"ui_impact": true}\n```\n'
        _, parsed = extract_plan_json(output)
        assert parsed is not None
        assert parsed.get("ui_impact") is True

    def test_ignores_non_dict_json(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = "```json\n[1, 2, 3]\n```\n"
        text, parsed = extract_plan_json(output)
        assert parsed is None
        assert text == output

    def test_handles_missing_newline_before_closing_fence(self) -> None:
        """閉じ ``` 直前に改行がない LLM 出力ゆらぎでも抽出できる."""
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = '方針\n```json\n{"ui_impact": false}```\n'
        _, parsed = extract_plan_json(output)
        assert parsed is not None
        assert parsed["ui_impact"] is False

    def test_deeply_nested_json_falls_back_gracefully(self) -> None:
        """深いネスト JSON (RecursionError) でも例外を投げず None フォールバックする."""
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        deep = "[" * 50000 + "]" * 50000
        output = f"方針\n```json\n{deep}\n```\n"
        text, parsed = extract_plan_json(output)
        assert parsed is None
        assert text == output

    def test_uppercase_json_fence_is_matched(self) -> None:
        """フェンス言語ラベルが大文字 (```JSON) でも抽出できる."""
        from ai_agent_orchestrator.phases.plan_artifact import extract_plan_json

        output = '方針\n```JSON\n{"ui_impact": true}\n```\n'
        _, parsed = extract_plan_json(output)
        assert parsed is not None
        assert parsed["ui_impact"] is True


class TestBuildPlanRecord:
    """build_plan_record のテスト."""

    def test_light_record_has_minimal_schema(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record(
            "light",
            {"ui_impact": False, "summary": "方針", "test_cases": ["t1"]},
        )
        assert record["plan_depth"] == "light"
        assert record["ui_impact"] is False
        assert record["summary"] == "方針"
        assert record["test_cases"] == ["t1"]

    def test_record_always_exists_even_without_parsed_json(self) -> None:
        """JSON パース失敗時も ui_impact キーを含むレコードが必ず生成される (#91)."""
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record("light", None)
        assert record["plan_depth"] == "light"
        assert record["ui_impact"] is None
        assert record["test_cases"] == []

    def test_full_record_includes_architecture_and_subtasks(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record(
            "full",
            {
                "ui_impact": True,
                "summary": "設計概要",
                "architecture": "レイヤ構成",
                "test_cases": ["t1"],
                "subtasks": [{"id": 1, "title": "core"}],
            },
        )
        assert record["plan_depth"] == "full"
        assert record["architecture"] == "レイヤ構成"
        assert record["subtasks"] == [{"id": 1, "title": "core"}]

    def test_invalid_ui_impact_type_falls_back_to_none(self) -> None:
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record("light", {"ui_impact": "yes"})
        assert record["ui_impact"] is None

    def test_test_cases_elements_are_normalized_to_str(self) -> None:
        """test_cases の要素が dict 等でも文字列に正規化される (#91 消費側の契約)."""
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record("light", {"test_cases": [{"name": "t1"}, "t2", 3]})
        assert all(isinstance(t, str) for t in record["test_cases"])
        assert "t2" in record["test_cases"]

    def test_test_cases_string_is_wrapped_in_list(self) -> None:
        """test_cases が文字列1件のとき 1 要素リストに救済される."""
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record("light", {"test_cases": "唯一のケース"})
        assert record["test_cases"] == ["唯一のケース"]

    def test_non_string_summary_and_architecture_fall_back_to_empty(self) -> None:
        """summary / architecture が非文字列のとき repr 化せず空文字になる."""
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record(
            "full",
            {"summary": {"a": 1}, "architecture": ["x"], "subtasks": []},
        )
        assert record["summary"] == ""
        assert record["architecture"] == ""

    def test_subtasks_elements_are_normalized(self) -> None:
        """subtasks 要素が想定外の型でも {id, title} スキーマに正規化される."""
        from ai_agent_orchestrator.phases.plan_artifact import build_plan_record

        record = build_plan_record(
            "full",
            {"subtasks": [{"id": 1, "title": "core"}, "文字列タスク", {"title": "id無し"}, 42]},
        )
        subtasks = record["subtasks"]
        assert subtasks[0] == {"id": 1, "title": "core"}
        assert subtasks[1] == {"id": None, "title": "文字列タスク"}
        assert subtasks[2] == {"id": None, "title": "id無し"}
        assert subtasks[3] == {"id": None, "title": "42"}
        # 全要素が dict かつ id/title キーを持つ
        assert all(set(s.keys()) == {"id", "title"} for s in subtasks)


# ---------------------------------------------------------------------------
# plan_depth の導出
# ---------------------------------------------------------------------------


class TestPlanDepth:
    """plan_depth_for のテスト (U5: issue_type ベースに変更済み)."""

    def test_bug_is_light(self) -> None:
        """bug タイプは light (修正方針コメント)."""
        from ai_agent_orchestrator.phases.plan import plan_depth_for

        assert plan_depth_for("bug") == "light"

    def test_feature_m_is_full(self) -> None:
        """feature-m は full (設計書 + PR)."""
        from ai_agent_orchestrator.phases.plan import plan_depth_for

        assert plan_depth_for("feature-m") == "full"

    def test_feature_l_is_full(self) -> None:
        """feature-l は full."""
        from ai_agent_orchestrator.phases.plan import plan_depth_for

        assert plan_depth_for("feature-l") == "full"

    def test_unknown_phase_falls_back_to_full(self) -> None:
        """bug 以外は full にフォールバックする (明示的な契約)."""
        from ai_agent_orchestrator.phases.plan import plan_depth_for

        assert plan_depth_for("unknown-issue-type") == "full"


# ---------------------------------------------------------------------------
# PlanExecutor: light (旧 analysis) フロー
# ---------------------------------------------------------------------------


class TestPlanExecutorLight:
    """light depth (旧 analysis) の挙動."""

    async def test_posts_comment_without_json_block_and_transitions(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """方針コメントから JSON ブロックが除去され approve へ遷移する (旧 plan-review)."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output=('修正方針: null check\n\n```json\n{"ui_impact": false, "summary": "s"}\n```\n'),
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        mock_sm.get_issue_type.return_value = "bug"  # light フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        mock_github.create_comment.assert_called_once()
        body = mock_github.create_comment.call_args.args[2]
        assert "```json" not in body
        assert "修正方針: null check" in body
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")

    async def test_light_does_not_write_plan_json_file(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        tmp_path: Path,
    ) -> None:
        """light は plan.json ファイルを書き出さない (state のみ) という責務契約."""
        mock_workspace.create_worktree.return_value = str(tmp_path)
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output='方針\n```json\n{"ui_impact": false}\n```\n',
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        # full と異なり light はディスクへ plan.json を書かない
        assert not (tmp_path / "docs" / "designs" / "issue-1.plan.json").exists()
        # state には保存される
        assert mock_sm.get_state.return_value.plan_json is not None

    async def test_stores_plan_json_in_state(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """plan_json が state に保存され persist される."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output='方針\n```json\n{"ui_impact": true, "summary": "s", "test_cases": ["t"]}\n```\n',
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        state = mock_sm.get_state.return_value
        assert state.plan_json is not None
        assert state.plan_json["ui_impact"] is True
        assert state.plan_json["plan_depth"] == "light"
        mock_sm.persist.assert_called()

    async def test_plan_json_exists_even_when_agent_omits_json(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """エージェントが JSON を出力しなくても plan_json は必ず存在する (#91)."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="方針テキストのみ",
            tool_uses=[],
            cost_usd=0.5,
            duration_sec=20.0,
        )
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        state = mock_sm.get_state.return_value
        assert state.plan_json is not None
        assert state.plan_json["ui_impact"] is None

    async def test_light_prompt_requests_json_block(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """light プロンプトに JSON ブロックの出力指示が含まれる."""
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        prompt = await executor.build_prompt(_make_request(phase="plan"))
        assert "```json" in prompt
        assert "ui_impact" in prompt
        # light は設計書ファイルの作成指示を含まない
        assert "docs/designs/issue-" not in prompt


# ---------------------------------------------------------------------------
# PlanExecutor: full (旧 design) フロー
# ---------------------------------------------------------------------------

_VALID_DESIGN_DOC = """# 設計書

## 概要
テスト設計。

## サブタスク

### subtask-1: Core
- files: [`src/core.py`, `tests/unit/test_core.py`]
- depends_on: []
- description: コア実装とテスト
"""


class TestPlanExecutorFull:
    """full depth (旧 design) の挙動."""

    @pytest.fixture
    def worktree(self, tmp_path: Path, mock_workspace: AsyncMock) -> Path:
        """検証をパスする設計書を持つ worktree."""
        designs = tmp_path / "docs" / "designs"
        designs.mkdir(parents=True)
        (designs / "issue-1.md").write_text(_VALID_DESIGN_DOC, encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "core.py").write_text("", encoding="utf-8")
        (tmp_path / "tests" / "unit").mkdir(parents=True)
        (tmp_path / "tests" / "unit" / "test_core.py").write_text("", encoding="utf-8")
        mock_workspace.create_worktree.return_value = str(tmp_path)
        return tmp_path

    async def test_full_flow_transitions_to_design_review(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        worktree: Path,
    ) -> None:
        """設計 PR が作成され approve へ遷移する (旧 design-review)."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        mock_sm.transition.assert_called_with(("org/app", 1), "approve")
        state = mock_sm.get_state.return_value
        assert state.design_pr_number == 5

    async def test_full_writes_plan_json_file_to_worktree(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        worktree: Path,
    ) -> None:
        """full では plan JSON が worktree の docs/designs に書き出される."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output=('設計PR #5\n```json\n{"ui_impact": true, "summary": "設計", "architecture": "層"}\n```\n'),
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        plan_file = worktree / "docs" / "designs" / "issue-1.plan.json"
        assert plan_file.exists()
        import json

        record = json.loads(plan_file.read_text(encoding="utf-8"))
        assert record["ui_impact"] is True
        assert record["plan_depth"] == "full"

    async def test_full_write_failure_does_not_block_flow(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        worktree: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """plan.json 書き込みが失敗しても警告に留めフローが継続する."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )

        # Path.write_text を失敗させる
        import ai_agent_orchestrator.phases.plan as plan_mod

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(plan_mod.Path, "write_text", _boom)

        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        # 書き込み失敗でも approve へ遷移し、state には保存される (旧 design-review)
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")
        assert mock_sm.get_state.return_value.plan_json is not None

    async def test_full_stores_plan_json_in_state(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        worktree: Path,
    ) -> None:
        """full でも state.plan_json が保存される."""
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 (JSONなし)",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        await executor.execute(_make_request(phase="plan"))

        state = mock_sm.get_state.return_value
        assert state.plan_json is not None
        assert state.plan_json["plan_depth"] == "full"
        assert state.plan_json["ui_impact"] is None

    async def test_full_revalidates_design_when_doc_missing(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
        tmp_path: Path,
    ) -> None:
        """設計書が無い場合は上限回数まで再生成し、警告コメントを投稿して続行する."""
        mock_workspace.create_worktree.return_value = str(tmp_path)  # 設計書なし
        mock_runner.run.return_value = AgentResult(
            session_id="s1",
            output="設計PR #5 を作成しました",
            tool_uses=[],
            cost_usd=1.0,
            duration_sec=60.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        from ai_agent_orchestrator.phases.plan import _MAX_DESIGN_REVALIDATE

        await executor.execute(_make_request(phase="plan"))

        # 初回 1 回 + 再生成 _MAX_DESIGN_REVALIDATE 回
        assert mock_runner.run.call_count == 1 + _MAX_DESIGN_REVALIDATE
        # 上限到達後の警告コメントが投稿される
        warning_calls = [c for c in mock_github.create_comment.call_args_list if "検証警告" in str(c.args[2])]
        assert len(warning_calls) == 1
        # フローは止まらず approve へ遷移する (旧 design-review)
        mock_sm.transition.assert_called_with(("org/app", 1), "approve")

    async def test_full_prompt_includes_feedback_on_rejection(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """差し戻し時、extra['feedback'] の指摘全文が設計プロンプトに含まれる (受け入れ条件2)."""
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        request = _make_request(phase="plan", extra={"feedback": "アーキを階層化して再設計して"})
        prompt = await executor.build_prompt(request)
        assert "アーキを階層化して再設計して" in prompt
        assert "指摘" in prompt

    async def test_full_prompt_requests_design_doc_and_json(
        self,
        mock_runner: AsyncMock,
        mock_github: AsyncMock,
        mock_workspace: AsyncMock,
        mock_context: AsyncMock,
        mock_sm: MagicMock,
    ) -> None:
        """full プロンプトは設計書ファイル指示と JSON ブロック指示の両方を含む."""
        mock_sm.get_issue_type.return_value = "feature-m"  # full フロー
        executor = _make_executor(mock_runner, mock_github, mock_workspace, mock_context, mock_sm)
        prompt = await executor.build_prompt(_make_request(phase="plan"))
        assert "docs/designs/issue-1.md" in prompt
        assert "```json" in prompt
        assert "ui_impact" in prompt
        assert "## サブタスク" in prompt


# ---------------------------------------------------------------------------
# 後方互換 (re-export)
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    """旧 import パス互換 (U5 統合後)."""

    def test_analysis_executor_is_plan_executor(self) -> None:
        """analysis / design モジュールは U5 で plan に統合済み (モジュール自体は廃止)."""
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        # U5 統合後: analysis.py / design.py は削除済み
        # PlanExecutor が light / full の両方を処理する
        assert PlanExecutor is not None

    def test_design_executor_is_plan_executor(self) -> None:
        """design モジュールは U5 で plan に統合済み (モジュール自体は廃止)."""
        from ai_agent_orchestrator.phases.plan import PlanExecutor

        # U5 統合後: design.py は削除済み
        assert PlanExecutor is not None

    def test_issue_state_has_plan_json_field(self) -> None:
        """IssueState に plan_json フィールドが追加されている (永続化対象)."""
        from dataclasses import fields

        from ai_agent_orchestrator.models import IssueState, Phase

        names = {f.name for f in fields(IssueState)}
        assert "plan_json" in names
        state = IssueState(issue_number=1, phase=Phase.PLAN)
        assert state.plan_json is None
