"""知識ループ MVP のユニットテスト."""

from __future__ import annotations

from pathlib import Path

from ai_agent_orchestrator.knowledge.episode_store import EpisodeStore, make_episode_id
from ai_agent_orchestrator.knowledge.models import Episode, Pattern, Skill
from ai_agent_orchestrator.knowledge.pattern_extractor import extract_patterns
from ai_agent_orchestrator.knowledge.skill_manager import SkillManager

# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------

_NOW = "2026-06-17T00:00:00Z"


def _make_episode(
    issue: int = 1,
    phase: str = "implement",
    outcome: str = "success",
    lesson: str = "テスト先行が有効",
    repo: str = "test-repo",
    created_at: str = _NOW,
) -> Episode:
    ep_id = make_episode_id(issue, phase, created_at)
    return Episode(
        id=ep_id,
        issue=issue,
        repo=repo,
        phase=phase,
        outcome=outcome,  # type: ignore[arg-type]
        summary="テスト要約",
        lesson=lesson,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# models.py: Episode
# ---------------------------------------------------------------------------


class TestEpisodeModel:
    """Episode の to_dict / from_dict ラウンドトリップ."""

    def test_roundtrip(self) -> None:
        ep = _make_episode()
        restored = Episode.from_dict(ep.to_dict())
        assert restored == ep

    def test_to_dict_keys(self) -> None:
        ep = _make_episode()
        d = ep.to_dict()
        assert set(d.keys()) == {"id", "issue", "repo", "phase", "outcome", "summary", "lesson", "created_at"}

    def test_from_dict_missing_keys_defaults(self) -> None:
        ep = Episode.from_dict({})
        assert ep.id == ""
        assert ep.issue == 0
        assert ep.repo == ""
        assert ep.outcome == "failure"  # 既定値
        assert ep.lesson == ""

    def test_from_dict_invalid_outcome_defaults_to_failure(self) -> None:
        ep = Episode.from_dict({"outcome": "unknown"})
        assert ep.outcome == "failure"

    def test_from_dict_success_outcome(self) -> None:
        ep = Episode.from_dict({"outcome": "success"})
        assert ep.outcome == "success"


# ---------------------------------------------------------------------------
# models.py: Pattern
# ---------------------------------------------------------------------------


class TestPatternModel:
    """Pattern の to_dict / from_dict ラウンドトリップ."""

    def _make(self) -> Pattern:
        return Pattern(
            id="pat-abc",
            title="テストパターン",
            description="2回観測。",
            confidence=0.67,
            occurrences=2,
            status="candidate",
        )

    def test_roundtrip(self) -> None:
        p = self._make()
        restored = Pattern.from_dict(p.to_dict())
        assert restored == p

    def test_from_dict_missing_keys_defaults(self) -> None:
        p = Pattern.from_dict({})
        assert p.id == ""
        assert p.confidence == 0.0
        assert p.occurrences == 0
        assert p.status == "candidate"

    def test_from_dict_promoted_status(self) -> None:
        p = Pattern.from_dict({"status": "promoted"})
        assert p.status == "promoted"

    def test_from_dict_invalid_status_defaults_to_candidate(self) -> None:
        p = Pattern.from_dict({"status": "unknown"})
        assert p.status == "candidate"


# ---------------------------------------------------------------------------
# models.py: Skill
# ---------------------------------------------------------------------------


class TestSkillModel:
    """Skill の to_dict / from_dict ラウンドトリップ."""

    def _make(self) -> Skill:
        return Skill(
            id="sk-xyz",
            name="test-skill",
            from_pattern="pat-abc",
            used_count=3,
            success_rate=0.9,
            updated_at=_NOW,
        )

    def test_roundtrip(self) -> None:
        s = self._make()
        restored = Skill.from_dict(s.to_dict())
        assert restored == s

    def test_from_dict_missing_keys_defaults(self) -> None:
        s = Skill.from_dict({})
        assert s.id == ""
        assert s.used_count == 0
        assert s.success_rate == 1.0

    def test_to_dict_keys(self) -> None:
        s = self._make()
        d = s.to_dict()
        assert set(d.keys()) == {"id", "name", "from_pattern", "used_count", "success_rate", "updated_at"}


# ---------------------------------------------------------------------------
# episode_store.py: make_episode_id
# ---------------------------------------------------------------------------


class TestMakeEpisodeId:
    """make_episode_id の安定性テスト."""

    def test_deterministic(self) -> None:
        id1 = make_episode_id(42, "implement", _NOW)
        id2 = make_episode_id(42, "implement", _NOW)
        assert id1 == id2

    def test_format(self) -> None:
        ep_id = make_episode_id(10, "review", _NOW)
        assert ep_id.startswith("ep-10-review-")

    def test_different_inputs_give_different_ids(self) -> None:
        id1 = make_episode_id(1, "implement", _NOW)
        id2 = make_episode_id(2, "implement", _NOW)
        assert id1 != id2


# ---------------------------------------------------------------------------
# episode_store.py: EpisodeStore
# ---------------------------------------------------------------------------


class TestEpisodeStore:
    """EpisodeStore の record / load テスト."""

    def test_record_and_load_roundtrip(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        ep = _make_episode(issue=1)
        store.record(ep)
        loaded = store.load()
        assert len(loaded) == 1
        assert loaded[0] == ep

    def test_load_returns_empty_when_file_absent(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        result = store.load()
        assert result == []

    def test_multiple_episodes_preserved_in_order(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        eps = [_make_episode(issue=i, created_at=f"2026-06-17T0{i}:00:00Z") for i in range(3)]
        for ep in eps:
            store.record(ep)
        loaded = store.load()
        assert len(loaded) == 3
        assert [e.issue for e in loaded] == [0, 1, 2]

    def test_malformed_line_skipped(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        ep = _make_episode(issue=99)
        store.record(ep)
        # ファイルに不正行を挿入
        store._path.open("a", encoding="utf-8").write("NOT JSON\n")
        loaded = store.load()
        # 不正行は読み飛ばし、正常行のみ返る
        assert len(loaded) == 1
        assert loaded[0].issue == 99

    def test_dos_cap_keeps_last_5000(self, tmp_path: Path) -> None:
        store = EpisodeStore(tmp_path)
        # 5001 行書き込む（issue 番号で区別）
        store._path.parent.mkdir(parents=True, exist_ok=True)
        import json

        lines = []
        for i in range(5001):
            ep_id = make_episode_id(i, "implement", _NOW)
            d = Episode(
                id=ep_id,
                issue=i,
                repo="r",
                phase="implement",
                outcome="success",
                summary="s",
                lesson="l",
                created_at=_NOW,
            ).to_dict()
            lines.append(json.dumps(d, ensure_ascii=False))
        store._path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        loaded = store.load()
        assert len(loaded) == 5000
        # 最新 5000 件 (issue 1〜5000) が返る
        assert loaded[0].issue == 1
        assert loaded[-1].issue == 5000

    def test_record_creates_parent_dir(self, tmp_path: Path) -> None:
        deep_root = tmp_path / "nested" / "dir"
        store = EpisodeStore(deep_root)
        ep = _make_episode()
        store.record(ep)
        assert store._path.exists()


# ---------------------------------------------------------------------------
# pattern_extractor.py: extract_patterns
# ---------------------------------------------------------------------------


class TestExtractPatterns:
    """extract_patterns のグループ化・スコア計算テスト."""

    def test_empty_episodes_returns_empty(self) -> None:
        assert extract_patterns([]) == []

    def test_empty_lesson_skipped(self) -> None:
        ep = _make_episode(lesson="")
        result = extract_patterns([ep])
        assert result == []

    def test_whitespace_only_lesson_skipped(self) -> None:
        ep = _make_episode(lesson="   ")
        result = extract_patterns([ep])
        assert result == []

    def test_single_episode_creates_candidate(self) -> None:
        ep = _make_episode(lesson="テスト先行が有効")
        result = extract_patterns([ep])
        assert len(result) == 1
        p = result[0]
        assert p.occurrences == 1
        assert p.status == "candidate"
        assert p.confidence < 1.0

    def test_three_same_lessons_promoted(self) -> None:
        lesson = "テスト先行が有効"
        eps = [_make_episode(issue=i, lesson=lesson) for i in range(3)]
        result = extract_patterns(eps)
        assert len(result) == 1
        p = result[0]
        assert p.occurrences == 3
        assert p.status == "promoted"
        assert p.confidence == 1.0

    def test_two_same_lessons_candidate(self) -> None:
        lesson = "デバウンスを入れる"
        eps = [_make_episode(issue=i, lesson=lesson) for i in range(2)]
        result = extract_patterns(eps)
        assert result[0].status == "candidate"
        assert result[0].occurrences == 2

    def test_confidence_formula(self) -> None:
        lesson = "同じ教訓"
        eps = [_make_episode(issue=i, lesson=lesson) for i in range(2)]
        result = extract_patterns(eps)
        # confidence = min(1.0, 2/3) ≈ 0.6667
        assert abs(result[0].confidence - (2 / 3)) < 0.001

    def test_case_insensitive_grouping(self) -> None:
        eps = [
            _make_episode(issue=1, lesson="テスト先行"),
            _make_episode(issue=2, lesson="テスト先行"),  # 同一（大小文字は関係なし）
        ]
        result = extract_patterns(eps)
        assert len(result) == 1
        assert result[0].occurrences == 2

    def test_different_lessons_create_separate_patterns(self) -> None:
        eps = [
            _make_episode(issue=1, lesson="教訓 A"),
            _make_episode(issue=2, lesson="教訓 B"),
        ]
        result = extract_patterns(eps)
        assert len(result) == 2

    def test_sorted_by_occurrences_desc(self) -> None:
        lesson_a = "教訓 AAA"
        lesson_b = "教訓 BBB"
        eps = [_make_episode(issue=i, lesson=lesson_a) for i in range(5)] + [
            _make_episode(issue=i + 100, lesson=lesson_b) for i in range(2)
        ]
        result = extract_patterns(eps)
        assert result[0].occurrences >= result[1].occurrences

    def test_title_truncated_to_60_chars(self) -> None:
        long_lesson = "あ" * 100
        ep = _make_episode(lesson=long_lesson)
        result = extract_patterns([ep])
        assert len(result[0].title) <= 60

    def test_id_stable_across_calls(self) -> None:
        lesson = "安定した教訓"
        ep = _make_episode(lesson=lesson)
        r1 = extract_patterns([ep])
        r2 = extract_patterns([ep])
        assert r1[0].id == r2[0].id

    def test_description_contains_phase(self) -> None:
        ep = _make_episode(phase="review", lesson="レビュー教訓")
        result = extract_patterns([ep])
        assert "review" in result[0].description


# ---------------------------------------------------------------------------
# skill_manager.py: SkillManager
# ---------------------------------------------------------------------------


def _promoted_pattern(idx: int = 0, title: str = "テスト教訓パターン") -> Pattern:
    return Pattern(
        id=f"pat-{idx:03d}",
        title=title,
        description="テスト",
        confidence=1.0,
        occurrences=3,
        status="promoted",
    )


def _candidate_pattern(idx: int = 0) -> Pattern:
    return Pattern(
        id=f"pat-cand-{idx:03d}",
        title="候補パターン",
        description="テスト",
        confidence=0.5,
        occurrences=1,
        status="candidate",
    )


class TestSkillManager:
    """SkillManager の promote / load_skills / skills_for_phase テスト."""

    def test_promote_creates_skill_for_promoted_pattern(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _promoted_pattern()
        skills = sm.promote([pat], now_iso=_NOW)
        assert len(skills) == 1
        assert skills[0].from_pattern == pat.id
        assert skills[0].updated_at == _NOW

    def test_promote_ignores_candidate_patterns(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _candidate_pattern()
        skills = sm.promote([pat], now_iso=_NOW)
        assert skills == []

    def test_promote_persists_to_file(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _promoted_pattern(title="永続化テスト")
        sm.promote([pat], now_iso=_NOW)
        assert sm._path.exists()

    def test_load_skills_roundtrip(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _promoted_pattern(title="ロードテスト")
        promoted = sm.promote([pat], now_iso=_NOW)
        loaded = sm.load_skills()
        assert loaded == promoted

    def test_load_skills_empty_when_file_absent(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        assert sm.load_skills() == []

    def test_promote_merge_preserves_used_count(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _promoted_pattern(title="使用カウントテスト")

        # 初回プロモート
        skills1 = sm.promote([pat], now_iso=_NOW)
        assert skills1[0].used_count == 0

        # used_count を手動で増やして再保存
        updated = Skill(
            id=skills1[0].id,
            name=skills1[0].name,
            from_pattern=skills1[0].from_pattern,
            used_count=7,
            success_rate=0.85,
            updated_at=_NOW,
        )
        import json

        sm._path.write_text(json.dumps(updated.to_dict(), ensure_ascii=False) + "\n", encoding="utf-8")

        # 再プロモートで used_count が引き継がれる
        skills2 = sm.promote([pat], now_iso="2026-06-18T00:00:00Z")
        assert skills2[0].used_count == 7
        assert abs(skills2[0].success_rate - 0.85) < 0.001

    def test_skills_for_phase_returns_bullet_list(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pat = _promoted_pattern(title="スキルフェーズテスト")
        sm.promote([pat], now_iso=_NOW)
        result = sm.skills_for_phase("implement")
        assert result != ""
        assert "-" in result

    def test_skills_for_phase_empty_when_no_skills(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        assert sm.skills_for_phase("implement") == ""

    def test_promote_multiple_patterns(self, tmp_path: Path) -> None:
        sm = SkillManager(tmp_path)
        pats = [_promoted_pattern(idx=i, title=f"パターン{i:02d}") for i in range(3)]
        skills = sm.promote(pats, now_iso=_NOW)
        assert len(skills) == 3
