"""StatePersistence のユニットテスト."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ai_agent_orchestrator.models import IssueKey, IssueState, Phase
from ai_agent_orchestrator.state_persistence import StatePersistence


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state" / "issues.json"


@pytest.fixture
def persistence(state_file: Path) -> StatePersistence:
    return StatePersistence(state_file)


@pytest.fixture
def sample_states() -> dict[IssueKey, IssueState]:
    return {
        ("myorg/myapp", 42): IssueState(
            issue_number=42,
            phase=Phase.HEARING,
            issue_type="feature-m",
            repo="myorg/myapp",
            created_at="2026-03-24T10:00:00",
            updated_at="2026-03-24T10:00:00",
        ),
        ("myorg/myapp", 55): IssueState(
            issue_number=55,
            phase=Phase.IMPLEMENT,
            issue_type="bug",
            repo="myorg/myapp",
            session_id="sess_abc",
            pr_number=101,
            retry_count=1,
            created_at="2026-03-24T09:00:00",
            updated_at="2026-03-24T11:00:00",
        ),
    }


def test_save_load_roundtrip(
    persistence: StatePersistence,
    sample_states: dict[IssueKey, IssueState],
) -> None:
    """save()で保存した状態がload()で正しく復元されること."""
    persistence.save(sample_states)
    loaded = persistence.load()

    assert len(loaded) == 2
    assert loaded[("myorg/myapp", 42)].issue_number == 42
    assert loaded[("myorg/myapp", 42)].phase == Phase.HEARING
    assert loaded[("myorg/myapp", 42)].issue_type == "feature-m"
    assert loaded[("myorg/myapp", 42)].repo == "myorg/myapp"
    assert loaded[("myorg/myapp", 55)].phase == Phase.IMPLEMENT
    assert loaded[("myorg/myapp", 55)].session_id == "sess_abc"
    assert loaded[("myorg/myapp", 55)].pr_number == 101
    assert loaded[("myorg/myapp", 55)].retry_count == 1


def test_save_load_empty_states(persistence: StatePersistence) -> None:
    """空のdict を save/load してもエラーにならないこと."""
    persistence.save({})
    loaded = persistence.load()
    assert loaded == {}


def test_load_nonexistent_file(persistence: StatePersistence) -> None:
    """状態ファイルが存在しない場合、空辞書が返されること."""
    loaded = persistence.load()
    assert loaded == {}


def test_load_corrupted_file_recovers(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """破損したJSONファイルの場合、バックアップが作成され空辞書が返されること."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text("{invalid json content!!!", encoding="utf-8")

    loaded = persistence.load()

    assert loaded == {}
    # バックアップファイルが作成される
    backup_file = state_file.with_suffix(".json.corrupted")
    assert backup_file.exists()
    assert backup_file.read_text() == "{invalid json content!!!"


def test_save_atomic_write(
    persistence: StatePersistence,
    sample_states: dict[IssueKey, IssueState],
    state_file: Path,
) -> None:
    """save()がatomic writeで書き込むこと（.tmpファイルが残らない）."""
    persistence.save(sample_states)

    tmp_file = state_file.with_suffix(".tmp")
    assert not tmp_file.exists()  # 一時ファイルが残らない
    assert state_file.exists()  # 正式ファイルが存在する

    # ファイル内容がvalid JSONであること
    content = json.loads(state_file.read_text(encoding="utf-8"))
    assert "myorg/myapp:42" in content
    assert "myorg/myapp:55" in content


def test_load_unknown_phase_falls_back_to_suspended(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """不正なPhase値を持つエントリが SUSPENDED にフォールバックされること."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "org/repo:42": {
            "issue_number": 42,
            "phase": "hearing",
            "issue_type": "bug",
            "repo": "org/repo",
        },
        "org/repo:99": {
            "issue_number": 99,
            "phase": "nonexistent-phase",  # 不正な値 → SUSPENDED へフォールバック
            "issue_type": "bug",
            "repo": "org/repo",
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = persistence.load()

    assert ("org/repo", 42) in loaded
    assert loaded[("org/repo", 42)].phase == Phase.HEARING
    assert ("org/repo", 99) in loaded  # スキップではなく SUSPENDED でロード
    assert loaded[("org/repo", 99)].phase == Phase.SUSPENDED


def test_load_planning_phase_falls_back_to_suspended(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """廃止された planning / plan-validation フェーズが SUSPENDED にフォールバックされること."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "org/repo:10": {
            "issue_number": 10,
            "phase": "planning",  # 廃止済みフェーズ
            "issue_type": "feature-m",
            "repo": "org/repo",
            "replan_count": 0,  # 旧バージョンが書き出した削除済みフィールド
        },
        "org/repo:11": {
            "issue_number": 11,
            "phase": "plan-validation",  # 廃止済みフェーズ
            "issue_type": "feature-m",
            "repo": "org/repo",
            "replan_count": 1,  # 旧バージョンが書き出した削除済みフィールド
        },
        "org/repo:12": {
            "issue_number": 12,
            "phase": "design",  # 有効なフェーズ
            "issue_type": "feature-m",
            "repo": "org/repo",
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = persistence.load()

    # 廃止済みフェーズは SUSPENDED にフォールバック（例外を投げない）
    assert ("org/repo", 10) in loaded
    assert loaded[("org/repo", 10)].phase == Phase.SUSPENDED
    assert ("org/repo", 11) in loaded
    assert loaded[("org/repo", 11)].phase == Phase.SUSPENDED
    # 有効なフェーズはそのまま
    assert ("org/repo", 12) in loaded
    assert loaded[("org/repo", 12)].phase == Phase.DESIGN


def test_load_drops_removed_fields_without_dropping_entry(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """削除済みフィールド (replan_count) を含む旧 state.json が drop されず復元されること.

    旧バージョンは asdict で全フィールドを書き出すため、state.json に削除済みの
    replan_count が残る。新コードの IssueState(**v) が TypeError を投げて
    エントリごと drop される回帰を防ぐ。
    """
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "org/repo:42": {
            "issue_number": 42,
            "phase": "implement",  # 有効なフェーズ
            "issue_type": "feature-m",
            "repo": "org/repo",
            "replan_count": 2,  # 削除済みフィールド
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = persistence.load()

    # エントリは drop されず、有効なフェーズのまま復元される (SUSPENDED ではない)
    assert ("org/repo", 42) in loaded
    assert loaded[("org/repo", 42)].phase == Phase.IMPLEMENT
    assert loaded[("org/repo", 42)].issue_type == "feature-m"
    assert not hasattr(loaded[("org/repo", 42)], "replan_count")


@pytest.mark.asyncio
async def test_auto_save_debounce(
    state_file: Path,
    sample_states: dict[IssueKey, IssueState],
) -> None:
    """auto_save()が短期間の複数回呼び出しをデバウンスすること."""
    persistence = StatePersistence(state_file, debounce_sec=0.1)

    # 3回連続で呼び出し
    await persistence.auto_save(sample_states)
    await persistence.auto_save(sample_states)
    await persistence.auto_save(sample_states)

    # まだ保存されていない（デバウンス中）
    assert not state_file.exists()

    # デバウンス完了を待つ
    await asyncio.sleep(0.2)

    # 1回だけ保存される
    assert state_file.exists()
    loaded = persistence.load()
    assert len(loaded) == 2


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    """save()が親ディレクトリを自動作成すること."""
    deep_path = tmp_path / "a" / "b" / "c" / "state.json"
    persistence = StatePersistence(deep_path)

    persistence.save(
        {
            ("org/repo", 1): IssueState(issue_number=1, phase=Phase.HEARING, repo="org/repo"),
        }
    )

    assert deep_path.exists()


def test_save_json_format(
    persistence: StatePersistence,
    sample_states: dict[IssueKey, IssueState],
    state_file: Path,
) -> None:
    """保存されたJSONがインデント付きで、日本語がエスケープされないこと."""
    persistence.save(sample_states)
    content = state_file.read_text(encoding="utf-8")

    # インデント付き
    assert "  " in content
    # ensure_ascii=False
    parsed = json.loads(content)
    assert isinstance(parsed, dict)


def test_save_overwrites_existing(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """save()が既存ファイルを上書きすること."""
    state1: dict[IssueKey, IssueState] = {
        ("org/repo", 42): IssueState(issue_number=42, phase=Phase.HEARING, repo="org/repo"),
    }
    state2: dict[IssueKey, IssueState] = {
        ("org/repo", 99): IssueState(issue_number=99, phase=Phase.DONE, repo="org/repo"),
    }

    persistence.save(state1)
    persistence.save(state2)

    loaded = persistence.load()
    assert ("org/repo", 42) not in loaded
    assert ("org/repo", 99) in loaded
    assert loaded[("org/repo", 99)].phase == Phase.DONE


@pytest.mark.asyncio
async def test_flush_saves_immediately(
    state_file: Path,
    sample_states: dict[IssueKey, IssueState],
) -> None:
    """flush()が保留中のデバウンスをキャンセルし即座に保存すること."""
    persistence = StatePersistence(state_file, debounce_sec=10.0)

    await persistence.auto_save(sample_states)
    assert not state_file.exists()  # デバウンス中

    await persistence.flush(sample_states)
    assert state_file.exists()  # 即座に保存

    loaded = persistence.load()
    assert len(loaded) == 2
