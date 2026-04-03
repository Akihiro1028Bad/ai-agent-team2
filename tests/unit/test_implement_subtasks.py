"""implement.py のサブタスク機能のユニットテスト."""

from __future__ import annotations

from ai_agent_orchestrator.models import Subtask
from ai_agent_orchestrator.phases.implement import parse_subtasks

# ---------------------------------------------------------------------------
# parse_subtasks のテスト
# ---------------------------------------------------------------------------

_VALID_PLAN = """
# 実装計画

## 概要
ユーザー検索機能の実装計画。

## サブタスク

### subtask-1: Core Types
- files: [`src/types.py`, `src/protocols.py`]
- depends_on: []
- description: 型定義とプロトコルを追加する

### subtask-2: Repository Layer
- files: [`src/repository.py`, `src/schema.sql`]
- depends_on: [1]
- description: リポジトリクラスとスキーマを実装する

### subtask-3: Service Layer
- files: [`src/service.py`]
- depends_on: [1, 2]
- description: サービスクラスを実装する

### subtask-4: Tests
- files: [`tests/test_types.py`, `tests/test_repository.py`, `tests/test_service.py`]
- depends_on: [3]
- description: 全レイヤーのテストを追加する

## その他のメモ
詳細は設計書を参照。
"""

_LEGACY_PLAN = """
# 実装計画

## 変更ファイル一覧

| # | ファイル | 種別 |
|---|---------|------|
| 1 | src/types.py | 新規 |
| 2 | src/repository.py | 新規 |
| 3 | tests/test_types.py | 新規 |
"""

_EMPTY_SUBTASK_SECTION = """
## サブタスク

(サブタスクなし)
"""

_PARTIAL_PLAN = """
## サブタスク

### subtask-1: Types Only
- files: [`src/types.py`]
- depends_on: []
- description: 型定義のみ

### subtask-2: Missing Files
- depends_on: [1]
- description: filesフィールドがない
"""


def test_parse_subtasks_valid_format() -> None:
    """正しいフォーマットのサブタスクセクションをパースできる。"""
    result = parse_subtasks(_VALID_PLAN)

    assert len(result) == 4

    st1 = result[0]
    assert st1.id == 1
    assert st1.title == "Core Types"
    assert "src/types.py" in st1.files
    assert "src/protocols.py" in st1.files
    assert st1.depends_on == ()
    assert "型定義" in st1.description

    st2 = result[1]
    assert st2.id == 2
    assert st2.depends_on == (1,)
    assert "src/repository.py" in st2.files

    st3 = result[2]
    assert st3.depends_on == (1, 2)

    st4 = result[3]
    assert len(st4.files) == 3
    assert st4.depends_on == (3,)


def test_parse_subtasks_legacy_plan_returns_empty() -> None:
    """## サブタスク セクションがない旧フォーマットは空リストを返す。"""
    result = parse_subtasks(_LEGACY_PLAN)
    assert result == []


def test_parse_subtasks_empty_plan_returns_empty() -> None:
    """空文字列は空リストを返す。"""
    result = parse_subtasks("")
    assert result == []


def test_parse_subtasks_no_files_subtask_skipped() -> None:
    """files フィールドがないサブタスクはスキップされる。"""
    result = parse_subtasks(_PARTIAL_PLAN)
    # subtask-1 のみ (files あり)、subtask-2 はスキップ
    assert len(result) == 1
    assert result[0].id == 1


def test_parse_subtasks_empty_section_returns_empty() -> None:
    """## サブタスク セクションはあるが subtask-N 見出しがない場合は空リスト。"""
    result = parse_subtasks(_EMPTY_SUBTASK_SECTION)
    assert result == []


def test_parse_subtasks_returns_subtask_instances() -> None:
    """戻り値が Subtask インスタンスのリストであること。"""
    result = parse_subtasks(_VALID_PLAN)
    assert all(isinstance(st, Subtask) for st in result)


def test_parse_subtasks_files_are_tuples() -> None:
    """files と depends_on が tuple (frozen dataclass 互換) であること。"""
    result = parse_subtasks(_VALID_PLAN)
    for st in result:
        assert isinstance(st.files, tuple)
        assert isinstance(st.depends_on, tuple)


def test_parse_subtasks_backtick_stripped() -> None:
    """ファイルパスのバッククォートが除去されること。"""
    result = parse_subtasks(_VALID_PLAN)
    for st in result:
        for f in st.files:
            assert "`" not in f


def test_parse_subtasks_multiline_files() -> None:
    """箇条書き形式の files もパースできる。"""
    plan = """
## サブタスク

### subtask-1: Bullet Files
- files:
  - `src/a.py`
  - `src/b.py`
- depends_on: []
- description: 箇条書きテスト
"""
    result = parse_subtasks(plan)
    assert len(result) == 1
    assert "src/a.py" in result[0].files
    assert "src/b.py" in result[0].files


def test_parse_subtasks_section_stops_at_next_h2() -> None:
    """## サブタスク セクションの後に別の ## セクションがあっても正しくパースできる。"""
    plan = """
## サブタスク

### subtask-1: Only One
- files: [`src/main.py`]
- depends_on: []
- description: 1つだけ

## 備考
この計画は簡略版です。
"""
    result = parse_subtasks(plan)
    assert len(result) == 1
    assert result[0].title == "Only One"
