"""U5 (#83): 9 フェーズ統一パイプラインのテスト.

Phase enum の刷新・旧→新マイグレーション表・VALID_TRANSITIONS・
TaskRequest 一本化・state.json マイグレーションを検証する。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_agent_orchestrator.models import (
    PHASE_MIGRATION,
    VALID_TRANSITIONS,
    Phase,
    TaskRequest,
)

# ---------------------------------------------------------------------------
# Phase enum (9 フェーズ + 補助状態)
# ---------------------------------------------------------------------------


class TestUnifiedPhaseEnum:
    """統一パイプラインの Phase enum."""

    def test_nine_pipeline_phases_exist(self) -> None:
        """提案書 §3.1 の 9 フェーズが定義されている."""
        assert Phase.INTAKE.value == "intake"
        assert Phase.CLARIFY.value == "clarify"
        assert Phase.SPLIT.value == "split"
        assert Phase.PLAN.value == "plan"
        assert Phase.APPROVE.value == "approve"
        assert Phase.IMPLEMENT.value == "implement"
        assert Phase.REVIEW.value == "review"
        assert Phase.REVISE.value == "revise"
        assert Phase.DONE.value == "done"

    def test_auxiliary_states_exist(self) -> None:
        """補助状態 (回答待ち / 依存待ち / 失敗) が維持されている."""
        assert Phase.CLARIFY_WAIT.value == "clarify-wait"
        assert Phase.BLOCKED.value == "blocked"
        assert Phase.SUSPENDED.value == "suspended"

    def test_old_phases_are_removed(self) -> None:
        """旧フェーズ名は enum から削除されている."""
        values = {p.value for p in Phase}
        removed = {
            "type-detection",
            "analysis",
            "fix",
            "plan-review",
            "hearing",
            "hearing-wait",
            "design",
            "design-review",
            "design-revise",
            "split-proposal",
            "split-execute",
            "ci-fix",
            "impl-review",
            "impl-revise",
        }
        assert values & removed == set()

    def test_phase_count(self) -> None:
        """9 パイプライン + 3 補助 = 12 値."""
        assert len(Phase) == 12


# ---------------------------------------------------------------------------
# 旧→新マイグレーション表
# ---------------------------------------------------------------------------


class TestPhaseMigration:
    """PHASE_MIGRATION (旧 state.json の読み替え表)."""

    @pytest.mark.parametrize(
        ("old", "new"),
        [
            ("type-detection", Phase.INTAKE),
            ("hearing", Phase.CLARIFY),
            ("hearing-wait", Phase.CLARIFY_WAIT),
            ("analysis", Phase.PLAN),
            ("design", Phase.PLAN),
            ("design-revise", Phase.PLAN),
            ("plan-review", Phase.APPROVE),
            ("design-review", Phase.APPROVE),
            ("fix", Phase.IMPLEMENT),
            ("implement", Phase.IMPLEMENT),
            ("ci-fix", Phase.REVISE),
            ("impl-review", Phase.REVIEW),
            ("impl-revise", Phase.REVISE),
            ("split-proposal", Phase.SPLIT),
            ("split-execute", Phase.SPLIT),
            ("blocked", Phase.BLOCKED),
            ("done", Phase.DONE),
            ("suspended", Phase.SUSPENDED),
        ],
    )
    def test_all_old_phases_map(self, old: str, new: Phase) -> None:
        assert PHASE_MIGRATION[old] is new

    def test_migration_covers_all_18_old_values(self) -> None:
        """旧 18 値すべてに対応がある (取りこぼしゼロの保証)."""
        assert len(PHASE_MIGRATION) >= 18


# ---------------------------------------------------------------------------
# VALID_TRANSITIONS (統一パイプライン §3.2)
# ---------------------------------------------------------------------------


class TestUnifiedTransitions:
    """統一遷移表."""

    def test_intake_routes(self) -> None:
        """INTAKE → CLARIFY (feature) / PLAN (情報十分な bug)."""
        targets = VALID_TRANSITIONS[Phase.INTAKE]
        assert Phase.CLARIFY in targets
        assert Phase.PLAN in targets

    def test_clarify_routes(self) -> None:
        """CLARIFY → PLAN / SPLIT / 回答待ち."""
        targets = VALID_TRANSITIONS[Phase.CLARIFY]
        assert Phase.PLAN in targets
        assert Phase.SPLIT in targets
        assert Phase.CLARIFY_WAIT in targets

    def test_approve_gate_routes(self) -> None:
        """APPROVE → IMPLEMENT (承認) / PLAN (差し戻し)."""
        targets = VALID_TRANSITIONS[Phase.APPROVE]
        assert Phase.IMPLEMENT in targets
        assert Phase.PLAN in targets

    def test_plan_to_approve(self) -> None:
        assert Phase.APPROVE in VALID_TRANSITIONS[Phase.PLAN]

    def test_implement_routes(self) -> None:
        """IMPLEMENT → REVIEW (完了) / REVISE (CI失敗)."""
        targets = VALID_TRANSITIONS[Phase.IMPLEMENT]
        assert Phase.REVIEW in targets
        assert Phase.REVISE in targets

    def test_review_gate_routes(self) -> None:
        """REVIEW → DONE (マージ) / REVISE (指摘)."""
        targets = VALID_TRANSITIONS[Phase.REVIEW]
        assert Phase.DONE in targets
        assert Phase.REVISE in targets

    def test_revise_routes_back_to_review(self) -> None:
        assert Phase.REVIEW in VALID_TRANSITIONS[Phase.REVISE]

    def test_no_old_phases_in_transitions(self) -> None:
        """遷移表に旧フェーズが残っていない (キー・値とも新 enum のみ)."""
        for src, targets in VALID_TRANSITIONS.items():
            assert isinstance(src, Phase)
            for t in targets:
                assert isinstance(t, Phase)

    def test_suspended_resume_targets_match_state_machine(self) -> None:
        """SUSPENDED の復帰先が state machine の resume_to_* と完全一致する."""
        from ai_agent_orchestrator.orchestrator.state_machine import TRANSITION_MAP

        valid = set(VALID_TRANSITIONS[Phase.SUSPENDED])
        mapped = {dst for (src, dst) in TRANSITION_MAP if src is Phase.SUSPENDED}
        assert valid == mapped

    def test_valid_transitions_all_exist_in_transition_map(self) -> None:
        """VALID_TRANSITIONS の全 (src, dst) が TRANSITION_MAP に存在する (乖離防止)."""
        from ai_agent_orchestrator.orchestrator.state_machine import TRANSITION_MAP

        missing = [
            (src.value, dst.value)
            for src, targets in VALID_TRANSITIONS.items()
            for dst in targets
            if src is not dst and (src, dst) not in TRANSITION_MAP
        ]
        assert missing == []

    def test_transition_map_all_exist_in_valid_transitions(self) -> None:
        """TRANSITION_MAP の全 (src, dst) が VALID_TRANSITIONS に存在する (逆方向)."""
        from ai_agent_orchestrator.orchestrator.state_machine import TRANSITION_MAP

        missing = [(src.value, dst.value) for (src, dst) in TRANSITION_MAP if dst not in VALID_TRANSITIONS.get(src, [])]
        assert missing == []


# ---------------------------------------------------------------------------
# TaskRequest 一本化
# ---------------------------------------------------------------------------


class TestUnifiedTaskRequest:
    """models.TaskRequest が唯一の定義であること."""

    def test_task_queue_reexports_models_taskrequest(self) -> None:
        """task_queue.TaskRequest は models.TaskRequest と同一."""
        from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest as TQRequest

        assert TQRequest is TaskRequest

    def test_has_extra_and_str_phase(self) -> None:
        """extra フィールドと str phase (enum .value 互換) を持つ."""

        class _Repo:
            owner = "org"
            repo = "app"

        req = TaskRequest(issue_number=1, repo=_Repo(), phase=Phase.PLAN.value, extra={"feedback": "x"})
        assert req.extra == {"feedback": "x"}
        assert req.phase == "plan"

    def test_repo_key_and_issue_key(self) -> None:
        class _Repo:
            owner = "org"
            repo = "app"

        req = TaskRequest(issue_number=7, repo=_Repo(), phase="plan")
        assert req.repo_key == "org/app"
        assert req.issue_key == ("org/app", 7)

    def test_priority_comparison(self) -> None:
        class _Repo:
            owner = "org"
            repo = "app"

        hi = TaskRequest(issue_number=1, repo=_Repo(), phase="plan", priority=1)
        lo = TaskRequest(issue_number=2, repo=_Repo(), phase="plan", priority=5)
        assert hi < lo


# ---------------------------------------------------------------------------
# state.json マイグレーション (受け入れ条件: 旧形式でもエントリが落ちない)
# ---------------------------------------------------------------------------


class TestStateJsonMigration:
    """旧フェーズ名を含む state.json のロード."""

    def _load(self, tmp_path: Path, entries: dict[str, dict[str, object]]) -> dict[object, object]:
        from ai_agent_orchestrator.state_persistence import StatePersistence

        f = tmp_path / "state" / "issues.json"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(entries), encoding="utf-8")
        return StatePersistence(f).load()

    def test_all_18_old_phases_load_without_loss(self, tmp_path: Path) -> None:
        """旧 18 フェーズ全てのエントリが 1 件も落ちずにロードされる."""
        old_phases = [
            "type-detection",
            "analysis",
            "fix",
            "plan-review",
            "hearing",
            "hearing-wait",
            "design",
            "design-review",
            "design-revise",
            "split-proposal",
            "split-execute",
            "blocked",
            "implement",
            "ci-fix",
            "impl-review",
            "impl-revise",
            "done",
            "suspended",
        ]
        entries = {
            f"org/app:{i}": {"issue_number": i, "phase": p, "repo": "org/app"}
            for i, p in enumerate(old_phases, start=1)
        }
        loaded = self._load(tmp_path, entries)
        assert len(loaded) == 18

    @pytest.mark.parametrize(
        ("old", "expected"),
        [
            ("analysis", Phase.PLAN),
            ("design-review", Phase.APPROVE),
            ("fix", Phase.IMPLEMENT),
            ("ci-fix", Phase.REVISE),
            ("impl-review", Phase.REVIEW),
            ("hearing-wait", Phase.CLARIFY_WAIT),
            ("split-execute", Phase.SPLIT),
        ],
    )
    def test_old_phase_is_migrated(self, tmp_path: Path, old: str, expected: Phase) -> None:
        loaded = self._load(
            tmp_path,
            {"org/app:1": {"issue_number": 1, "phase": old, "repo": "org/app"}},
        )
        state = loaded[("org/app", 1)]
        assert state.phase is expected  # type: ignore[union-attr]

    def test_new_phase_loads_as_is(self, tmp_path: Path) -> None:
        loaded = self._load(
            tmp_path,
            {"org/app:1": {"issue_number": 1, "phase": "plan", "repo": "org/app"}},
        )
        assert loaded[("org/app", 1)].phase is Phase.PLAN  # type: ignore[union-attr]

    def test_feature_s_issue_type_is_migrated_without_crash(self, tmp_path: Path) -> None:
        """feature-s の旧 state は issue_type のみ feature-m に読み替えられ、クラッシュしない."""
        from unittest.mock import AsyncMock

        from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
        from ai_agent_orchestrator.state_persistence import StatePersistence

        f = tmp_path / "state" / "issues.json"
        f.parent.mkdir(parents=True)
        f.write_text(
            json.dumps(
                {
                    "org/app:1": {
                        "issue_number": 1,
                        "phase": "plan-review",
                        "issue_type": "feature-s",
                        "repo": "org/app",
                    }
                }
            ),
            encoding="utf-8",
        )
        sm = StateMachineManager(persistence=StatePersistence(f), tracker=AsyncMock())
        sm.load_from_persistence()  # Phase("hearing") 等で ValueError にならないこと
        state = sm.get_state(("org/app", 1))
        assert state is not None
        assert state.issue_type == "feature-m"
        assert state.phase is Phase.APPROVE  # plan-review は persistence 層で読み替え済み

    def test_ancient_unknown_phase_falls_back_to_suspended(self, tmp_path: Path) -> None:
        """太古の廃止フェーズ (planning 等) は従来どおり SUSPENDED."""
        loaded = self._load(
            tmp_path,
            {"org/app:1": {"issue_number": 1, "phase": "planning", "repo": "org/app"}},
        )
        assert loaded[("org/app", 1)].phase is Phase.SUSPENDED  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# dispatcher ブリッジ (REVISE / SPLIT の振り分け)
# ---------------------------------------------------------------------------


class TestDispatcherBridges:
    """RevisePhaseExecutor / SplitPhaseExecutor の委譲条件."""

    def _request(self, extra: dict[str, object] | None) -> TaskRequest:
        class _Repo:
            owner = "org"
            repo = "app"

        return TaskRequest(issue_number=1, repo=_Repo(), phase="revise", extra=extra or {})

    async def test_revise_routes_ci_trigger_to_ci_fix(self) -> None:
        from unittest.mock import AsyncMock

        from ai_agent_orchestrator.phases.dispatcher import RevisePhaseExecutor

        review_revise, ci_fix = AsyncMock(), AsyncMock()
        bridge = RevisePhaseExecutor(review_revise=review_revise, ci_fix=ci_fix)
        await bridge.execute(self._request({"trigger": "ci"}))
        ci_fix.execute.assert_awaited_once()
        review_revise.execute.assert_not_awaited()

    async def test_revise_routes_default_to_review_revise(self) -> None:
        from unittest.mock import AsyncMock

        from ai_agent_orchestrator.phases.dispatcher import RevisePhaseExecutor

        review_revise, ci_fix = AsyncMock(), AsyncMock()
        bridge = RevisePhaseExecutor(review_revise=review_revise, ci_fix=ci_fix)
        await bridge.execute(self._request({"comments": "指摘"}))
        review_revise.execute.assert_awaited_once()
        ci_fix.execute.assert_not_awaited()

    async def test_split_routes_execute_step(self) -> None:
        from unittest.mock import AsyncMock

        from ai_agent_orchestrator.phases.dispatcher import SplitPhaseExecutor

        proposal, execute_step = AsyncMock(), AsyncMock()
        bridge = SplitPhaseExecutor(proposal=proposal, execute_step=execute_step)
        await bridge.execute(self._request({"step": "execute"}))
        execute_step.execute.assert_awaited_once()
        proposal.execute.assert_not_awaited()

    async def test_split_routes_default_to_proposal(self) -> None:
        from unittest.mock import AsyncMock

        from ai_agent_orchestrator.phases.dispatcher import SplitPhaseExecutor

        proposal, execute_step = AsyncMock(), AsyncMock()
        bridge = SplitPhaseExecutor(proposal=proposal, execute_step=execute_step)
        await bridge.execute(self._request(None))
        proposal.execute.assert_awaited_once()
        execute_step.execute.assert_not_awaited()
