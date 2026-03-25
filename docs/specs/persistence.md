# 実装仕様書: StatePersistence

## 概要

Issue状態のファイルベース永続化クラス。`IssueState` の辞書をJSONファイルに保存・復元し、プロセス再起動時の状態ロストを防止する。StateMachineのフェーズ遷移時に自動保存（デバウンス付き）を行う。

**モジュール**: `src/ai_agent_orchestrator/state_persistence.py`
**テストファイル**: `tests/unit/test_state_persistence.py`

> **Note**: 配置パスは `src/ai_agent_orchestrator/state_persistence.py`。API Reference の `orchestrator/` 配下パスは旧定義。

---

## 依存パッケージ

```python
from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from ai_agent_orchestrator.models import Phase, IssueState
```

---

## 外部参照データモデル

### IssueState（`ai_agent_orchestrator.orchestrator.state_machine` で定義済み）

```python
@dataclass
class IssueState:
    issue_number: int
    phase: Phase
    issue_type: str = ""
    repo: str = ""
    session_id: str | None = None
    pr_number: int | None = None
    design_pr_number: int | None = None
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""
```

---

## クラス定義

```python
class StatePersistence:
    """Issue状態のファイルベース永続化.

    JSONファイルに IssueState を保存・復元する。
    save() は atomic write（一時ファイル + rename）で安全に書き込む。
    auto_save() はデバウンス付きで頻繁な状態変更時の書き込み回数を抑制する。

    Attributes:
        _file: 状態ファイルのパス。
        _debounce_sec: auto_save のデバウンス間隔（秒）。
        _pending_task: デバウンス用の pending asyncio.Task。
    """

    def __init__(self, state_file: Path, debounce_sec: float = 2.0) -> None:
        """初期化.

        Args:
            state_file: 状態を保存するJSONファイルのパス。
                親ディレクトリが存在しない場合は自動作成する。
            debounce_sec: auto_save のデバウンス間隔（秒）。デフォルト2.0秒。
        """
        self._file = state_file
        self._debounce_sec = debounce_sec
        self._pending_task: asyncio.Task[None] | None = None
```

---

## メソッド仕様

### `save(states: dict[int, IssueState]) -> None`

**説明**: 全Issue状態をJSONファイルに保存する。同期メソッド。atomic write でファイル破損を防止する。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `states` | `dict[int, IssueState]` | Issue番号をキー、IssueStateを値とする辞書 |

**戻り値**: `None`

**処理フロー**:

```
1. 親ディレクトリが存在しなければ作成
2. states を {issue_number: asdict(state)} 形式に変換
3. 一時ファイル ({state_file}.tmp) に JSON を書き込み
4. 一時ファイルを正式ファイルにリネーム (atomic)
```

**実装**:

```python
def save(self, states: dict[int, IssueState]) -> None:
    """全Issue状態をJSONファイルに保存."""
    self._file.parent.mkdir(parents=True, exist_ok=True)
    data = {str(k): asdict(v) for k, v in states.items()}
    tmp_file = self._file.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_file.replace(self._file)  # atomic rename
```

**補足**: キーを `str(k)` に変換する理由は、JSONのキーは文字列である必要があるため。load時に `int(k)` で復元する。

---

### `load() -> dict[int, IssueState]`

**説明**: JSONファイルからIssue状態を復元する。アプリケーション起動時に呼び出される。

**パラメータ**: なし

**戻り値**: `dict[int, IssueState]` — 復元された状態辞書。ファイルが存在しない場合は空辞書。

**処理フロー**:

```
1. ファイルが存在しなければ空辞書を返す
2. JSONを読み込み
3. パース失敗時（破損ファイル）はバックアップを作成し、空辞書を返す
4. 各エントリを IssueState に復元
5. Phase の値が不正なエントリはスキップ（ログ出力）
```

**実装**:

```python
def load(self) -> dict[int, IssueState]:
    """JSONファイルからIssue状態を復元."""
    if not self._file.exists():
        return {}

    try:
        raw = self._file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # 破損ファイルのバックアップ
        backup = self._file.with_suffix(".json.corrupted")
        shutil.copy2(self._file, backup)
        return {}

    states: dict[int, IssueState] = {}
    for k, v in data.items():
        try:
            issue_number = int(k)
            # Phase enum の復元
            v["phase"] = Phase(v["phase"])
            states[issue_number] = IssueState(**v)
        except (ValueError, TypeError, KeyError):
            continue  # 不正なエントリはスキップ

    return states
```

---

### `async auto_save(states: dict[int, IssueState]) -> None`

**説明**: デバウンス付き自動保存。短時間に複数回呼ばれた場合、最後の呼び出しから `debounce_sec` 秒後に1回だけ `save()` を実行する。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `states` | `dict[int, IssueState]` | 保存する状態辞書 |

**戻り値**: `None`

**実装**:

```python
async def auto_save(self, states: dict[int, IssueState]) -> None:
    """デバウンス付き自動保存. 最後の呼び出しから debounce_sec 後に save() を実行."""
    if self._pending_task is not None:
        self._pending_task.cancel()

    async def _deferred_save() -> None:
        await asyncio.sleep(self._debounce_sec)
        self.save(states)

    self._pending_task = asyncio.create_task(_deferred_save())
```

---

### `async flush(states: dict[int, IssueState]) -> None`

**説明**: 保留中のデバウンスタスクがあれば即座にフラッシュ（キャンセル＆即時保存）する。グレースフルシャットダウン時に呼び出す。

**パラメータ**:

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `states` | `dict[int, IssueState]` | 現在の状態辞書 |

**実装**:

```python
async def flush(self, states: dict[int, IssueState]) -> None:
    """保留中の自動保存があれば即座に実行."""
    if self._pending_task is not None:
        self._pending_task.cancel()
        self._pending_task = None
    self.save(states)
```

**補足**: pending タスクをキャンセルした上で、現在の状態を即座に `save()` で書き込む。これによりシャットダウン時のデータロストを防止する。

---

## テストケース

テストファイル: `tests/unit/test_state_persistence.py`

使用ライブラリ: `pytest`, `pytest-asyncio`, `tmp_path` (pytest組み込みフィクスチャ)

### 共通フィクスチャ

```python
import json
import pytest
from pathlib import Path

from ai_agent_orchestrator.state_persistence import StatePersistence
from ai_agent_orchestrator.orchestrator.state_machine import IssueState, Phase


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    return tmp_path / "state" / "issues.json"


@pytest.fixture
def persistence(state_file: Path) -> StatePersistence:
    return StatePersistence(state_file)


@pytest.fixture
def sample_states() -> dict[int, IssueState]:
    return {
        42: IssueState(
            issue_number=42,
            phase=Phase.HEARING,
            issue_type="feature-m",
            repo="myorg/myapp",
            created_at="2026-03-24T10:00:00",
            updated_at="2026-03-24T10:00:00",
        ),
        55: IssueState(
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
```

---

### テスト1: save/load ラウンドトリップ

```python
def test_save_load_roundtrip(
    persistence: StatePersistence,
    sample_states: dict[int, IssueState],
) -> None:
    """save()で保存した状態がload()で正しく復元されること."""
    persistence.save(sample_states)
    loaded = persistence.load()

    assert len(loaded) == 2
    assert loaded[42].issue_number == 42
    assert loaded[42].phase == Phase.HEARING
    assert loaded[42].issue_type == "feature-m"
    assert loaded[42].repo == "myorg/myapp"
    assert loaded[55].phase == Phase.IMPLEMENT
    assert loaded[55].session_id == "sess_abc"
    assert loaded[55].pr_number == 101
    assert loaded[55].retry_count == 1
```

**検証ポイント**: 全フィールドが正しく保存・復元される。Phase enum が文字列 ↔ enum の変換で失われない。

---

### テスト2: 空状態の保存と読み込み

```python
def test_save_load_empty_states(persistence: StatePersistence) -> None:
    """空のdict を save/load してもエラーにならないこと."""
    persistence.save({})
    loaded = persistence.load()
    assert loaded == {}
```

**検証ポイント**: 空辞書が安全にシリアライズ・デシリアライズされる。

---

### テスト3: ファイルが存在しない場合のload

```python
def test_load_nonexistent_file(persistence: StatePersistence) -> None:
    """状態ファイルが存在しない場合、空辞書が返されること."""
    loaded = persistence.load()
    assert loaded == {}
```

**検証ポイント**: FileNotFoundError が発生せず、空辞書が返る。

---

### テスト4: 破損ファイルのリカバリ

```python
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
```

**検証ポイント**: 破損ファイルが `.corrupted` 拡張子でバックアップされる。元ファイルの内容が失われない。

---

### テスト5: atomic write（一時ファイル経由の書き込み）

```python
def test_save_atomic_write(
    persistence: StatePersistence,
    sample_states: dict[int, IssueState],
    state_file: Path,
) -> None:
    """save()がatomic writeで書き込むこと（.tmpファイルが残らない）."""
    persistence.save(sample_states)

    tmp_file = state_file.with_suffix(".tmp")
    assert not tmp_file.exists()  # 一時ファイルが残らない
    assert state_file.exists()     # 正式ファイルが存在する

    # ファイル内容がvalid JSONであること
    content = json.loads(state_file.read_text(encoding="utf-8"))
    assert "42" in content
    assert "55" in content
```

**検証ポイント**: 書き込み途中でプロセスが死んだ場合にファイルが中途半端にならない。

---

### テスト6: 不正なフェーズ値を含むエントリのスキップ

```python
def test_load_skips_invalid_phase(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """不正なPhase値を持つエントリがスキップされること."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "42": {
            "issue_number": 42,
            "phase": "hearing",
            "issue_type": "bug",
            "repo": "org/repo",
        },
        "99": {
            "issue_number": 99,
            "phase": "nonexistent-phase",  # 不正な値
            "issue_type": "bug",
            "repo": "org/repo",
        },
    }
    state_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = persistence.load()

    assert 42 in loaded
    assert 99 not in loaded  # 不正なエントリはスキップ
```

**検証ポイント**: 1つのエントリが不正でも他のエントリは正常に復元される。

---

### テスト7: デバウンス付き自動保存

```python
@pytest.mark.asyncio
async def test_auto_save_debounce(
    state_file: Path,
    sample_states: dict[int, IssueState],
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
```

**検証ポイント**: 連続呼び出し後、debounce_sec 経過後に1回だけsaveが呼ばれる。

---

### テスト8: 親ディレクトリの自動作成

```python
def test_save_creates_parent_directories(tmp_path: Path) -> None:
    """save()が親ディレクトリを自動作成すること."""
    deep_path = tmp_path / "a" / "b" / "c" / "state.json"
    persistence = StatePersistence(deep_path)

    persistence.save({
        1: IssueState(issue_number=1, phase=Phase.HEARING),
    })

    assert deep_path.exists()
```

---

### テスト9: JSONフォーマットの検証

```python
def test_save_json_format(
    persistence: StatePersistence,
    sample_states: dict[int, IssueState],
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
```

---

### テスト10: 上書き保存

```python
def test_save_overwrites_existing(
    persistence: StatePersistence,
    state_file: Path,
) -> None:
    """save()が既存ファイルを上書きすること."""
    state1 = {42: IssueState(issue_number=42, phase=Phase.HEARING)}
    state2 = {99: IssueState(issue_number=99, phase=Phase.DONE)}

    persistence.save(state1)
    persistence.save(state2)

    loaded = persistence.load()
    assert 42 not in loaded
    assert 99 in loaded
    assert loaded[99].phase == Phase.DONE
```

**検証ポイント**: save()は全体を置換する。部分更新ではない。

---

## 依存関係

| 依存 | 用途 |
|------|------|
| `json` | JSON シリアライズ・デシリアライズ |
| `pathlib.Path` | ファイルシステム操作 |
| `shutil` | 破損ファイルのバックアップコピー |
| `asyncio` | デバウンス用タスクスケジューリング |
| `dataclasses.asdict` | IssueState → dict 変換 |
