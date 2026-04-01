# 実装計画: Issue #30 イベントログの可視化ダッシュボード機能

## 1. 変更ファイル一覧と実装順序

依存関係の順序に基づき、以下の順で実装する。

| 順序 | ファイル | 変更種別 | 理由 |
|------|---------|---------|------|
| 1 | `src/ai_agent_orchestrator/models.py` | 修正 | データモデルは全モジュールの基盤。他の変更が依存する |
| 2 | `src/ai_agent_orchestrator/event_logger.py` | 修正 | 読み取り API は集計ロジックが依存する |
| 3 | `src/ai_agent_orchestrator/commands/dashboard.py` | **新規** | Aggregator / Renderer / メインループの本体 |
| 4 | `src/ai_agent_orchestrator/commands/__init__.py` | 修正 | dashboard_command のエクスポート追加 |
| 5 | `src/ai_agent_orchestrator/cli.py` | 修正 | CLI コマンド登録 |
| 6 | `tests/unit/test_dashboard.py` | **新規** | ユニットテスト |

## 2. 各ファイルの変更内容

---

### Step 1: `src/ai_agent_orchestrator/models.py` — データモデル追加

**変更箇所**: ファイル末尾（既存の `PHASE_CONFIG` 辞書の後）に以下の dataclass を追加。

**インポート追加**: `from dataclasses import field` を既存の `from dataclasses import dataclass` に追加。

```python
# ---------------------------------------------------------------------------
# 5. ダッシュボード用データモデル
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseTransitionRecord:
    """フェーズ遷移の記録."""

    timestamp: str
    from_phase: str
    to_phase: str
    cost_usd: float
    duration_sec: float


@dataclass
class ErrorStats:
    """エラー/サスペンド統計."""

    total_errors: int = 0
    total_suspends: int = 0
    by_category: dict[str, int] = field(default_factory=dict)


@dataclass
class IssueDashboardData:
    """Issue 単位のダッシュボード表示データ."""

    issue_number: int
    issue_type: str
    current_phase: str
    total_cost_usd: float
    total_duration_sec: float
    phase_costs: dict[str, float] = field(default_factory=dict)
    phase_durations: dict[str, float] = field(default_factory=dict)
    transitions: list[PhaseTransitionRecord] = field(default_factory=list)
    error_stats: ErrorStats = field(default_factory=ErrorStats)
    started_at: str = ""
    updated_at: str = ""


@dataclass
class DashboardData:
    """ダッシュボード全体の集計データ."""

    issues: dict[int, IssueDashboardData] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_issues: int = 0
    active_issues: int = 0
    completed_issues: int = 0
    suspended_issues: int = 0
    total_errors: int = 0
    total_suspends: int = 0
```

**既存コードへの影響**: なし（追加のみ）

---

### Step 2: `src/ai_agent_orchestrator/event_logger.py` — 読み取り API 追加

**変更箇所**: `EventLogger` クラスの末尾（`_sanitize_for_log` メソッドの後）に 3 メソッドを追加。

```python
def read_events(
    self,
    issue_number: int | None = None,
) -> list[dict[str, Any]]:
    """events.jsonl からイベントを読み取る.

    Args:
        issue_number: 指定した場合、そのIssueのイベントのみ返す。
                      None の場合は全Issueのイベントを返す。

    Returns:
        イベントレコードのリスト（時系列順）。

    Note:
        同期メソッドとして実装（読み取り専用、ロック不要）。
        書き込み中のパーシャルラインは無視する。
    """
    if issue_number is not None:
        return self._read_single_issue_events(issue_number)
    return self._read_all_events()

def _read_single_issue_events(self, issue_number: int) -> list[dict[str, Any]]:
    """単一Issueのイベントファイルを読み取る."""
    events_file = self._log_dir / f"issue-{issue_number}" / "events.jsonl"
    if not events_file.exists():
        return []
    return self._parse_jsonl(events_file)

def _read_all_events(self) -> list[dict[str, Any]]:
    """全Issueのイベントファイルを読み取る."""
    all_events: list[dict[str, Any]] = []
    if not self._log_dir.exists():
        return []
    for events_file in self._log_dir.glob("issue-*/events.jsonl"):
        all_events.extend(self._parse_jsonl(events_file))
    all_events.sort(key=lambda e: e.get("ts", ""))
    return all_events

def _parse_jsonl(self, file_path: Path) -> list[dict[str, Any]]:
    """JSONLファイルをパースする。不正な行はスキップ."""
    events: list[dict[str, Any]] = []
    try:
        with file_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return events
```

**設計判断**:
- 同期メソッドとして実装。ダッシュボード側が `asyncio.to_thread()` で呼び出す
- `_parse_jsonl` を共通ヘルパーとして切り出し（DRY）
- ファイル不存在・JSON 不正行は例外を投げず空リスト/スキップ

**既存コードへの影響**: なし（メソッド追加のみ。`track()`, `write_phase_log()` は変更しない）

---

### Step 3: `src/ai_agent_orchestrator/commands/dashboard.py` — 新規作成

このファイルが最も大きく、3 つの主要クラスとコマンド関数を含む。

#### 3-1. `DashboardAggregator` クラス

```python
"""ダッシュボードコマンド実装."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import typer
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ai_agent_orchestrator.config.settings import load_config
from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.models import (
    DashboardData,
    ErrorStats,
    IssueDashboardData,
    PhaseTransitionRecord,
)
```

**`DashboardAggregator`** の実装詳細:

- `PHASE_ORDER`: `ClassVar[dict[str, list[str]]]` — IssueType 別のフェーズ順序。設計書 §6.1 のとおり
- `aggregate(events)` メソッド:
  1. イベントを `issue` フィールドでグループ化
  2. 各グループに対して `aggregate_issue()` を呼び出し
  3. 全体の合計値 (total_cost_usd, active/completed/suspended counts, errors) を算出
  4. `DashboardData` を返す
- `aggregate_issue(events)` メソッド:
  1. イベントを時系列順に走査
  2. `phase_start` / `phase_started` → `current_phase` を更新、Issue Type を推定
  3. `phase_end` / `phase_completed` → `cost_usd`, `duration_sec` を `phase_costs` / `phase_durations` に加算
  4. `phase_transition` → `PhaseTransitionRecord` を `transitions` に追加
  5. `error` / `phase_error` → `ErrorStats` を更新（`data.category` で分類）
  6. `suspended` → `ErrorStats.total_suspends` をインクリメント
  7. `started_at` = 最初のイベントの `ts`, `updated_at` = 最後のイベントの `ts`
- `get_progress(issue_type, current_phase)` 静的メソッド:
  - `PHASE_ORDER[issue_type]` からフェーズのインデックスを取得
  - 未判定 → `(0, 0)` を返す
- Issue Type 推定ロジック（§6.3 のとおり）:
  - `analysis` / `fix` → `bug`
  - `plan-brief` → `feature-s`
  - `split-proposal` / `split-execute` → `feature-l`
  - `hearing` / `design` → `feature-m`
  - いずれにも該当しない → `""`

#### 3-2. `DashboardRenderer` クラス

- `render_overview(data: DashboardData) -> Layout`:
  - `_build_summary_panel` でサマリー（Total/Active/Completed/Suspended/Cost/Errors）
  - `_build_issues_table` で Issue 一覧テーブル（Issue番号, Type, Phase, Progress, Cost, Errors）
  - `_build_error_table` でエラーカテゴリ別統計
  - 3つを縦に並べた `Layout` を返す
- `render_issue_detail(data, issue_number) -> Layout`:
  - 上部: `render_overview` と同じサマリー
  - 中部: `_build_timeline` でフェーズ遷移タイムライン
  - 下部: `_build_cost_breakdown_table` でフェーズ別コスト内訳
  - Issue が見つからない場合は「Issue #{n} のログが見つかりません」Panel を返す
- `_build_progress_bar(issue_type, current_phase) -> str`:
  - `DashboardAggregator.get_progress()` を利用
  - `(0, 0)` → `"━━━ (不定)"`
  - DONE → 緑フルバー
  - SUSPENDED → 赤部分バー
  - それ以外 → 通常バー `████░░ 4/6`

#### 3-3. `dashboard_command` 関数とメインループ

```python
def dashboard_command(
    issue: int | None = typer.Option(None, "--issue", "-i", help="特定 Issue の詳細を表示"),
    refresh: int = typer.Option(5, "--refresh", "-r", help="リフレッシュ間隔（秒）"),
    no_live: bool = typer.Option(False, "--no-live", help="スナップショット表示（1回表示して終了）"),
    config: str = typer.Option("config.yaml", "--config", "-c", help="設定ファイルパス"),
) -> None:
    """イベントログの可視化ダッシュボードを表示する."""
    asyncio.run(_run_dashboard(issue, refresh, no_live, config))
```

- `_run_dashboard()` 非同期関数:
  1. `load_config()` で設定読み込み（FileNotFoundError → デフォルトパス使用）
  2. `EventLogger(log_dir)` を初期化
  3. `no_live=True` の場合: 1回集計・レンダリングして終了
  4. `no_live=False` の場合: `Rich Live` ループで `refresh` 秒間隔で更新
  5. `KeyboardInterrupt` / `asyncio.CancelledError` で正常終了

---

### Step 4: `src/ai_agent_orchestrator/commands/__init__.py` — エクスポート追加

**変更内容**:

```python
# 追加するインポート
from ai_agent_orchestrator.commands.dashboard import dashboard_command

# __all__ に追加
"dashboard_command",
```

**変更箇所**: 2箇所（import 文と `__all__` リスト）

---

### Step 5: `src/ai_agent_orchestrator/cli.py` — コマンド登録

**変更内容**: import に `dashboard_command` を追加し、コマンド登録行を追加。

```python
# import に追加
from ai_agent_orchestrator.commands import (
    ...
    dashboard_command,
)

# コマンド登録に追加（logs の後）
app.command("dashboard")(dashboard_command)
```

---

### Step 6: `tests/unit/test_dashboard.py` — ユニットテスト（新規）

#### テストクラスと主要テストケース

```python
"""ダッシュボード機能のユニットテスト."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.console import Console

from ai_agent_orchestrator.event_logger import EventLogger
from ai_agent_orchestrator.commands.dashboard import (
    DashboardAggregator,
    DashboardRenderer,
)
from ai_agent_orchestrator.models import (
    DashboardData,
    ErrorStats,
    IssueDashboardData,
)
```

**テストヘルパー**: イベントレコードを簡単に生成する `_make_event()` ヘルパー関数を用意。

```python
def _make_event(
    event: str,
    issue: int = 42,
    phase: str = "hearing",
    ts: str = "2026-04-01T12:00:00",
    data: dict | None = None,
) -> dict:
    record = {"ts": ts, "issue": issue, "phase": phase, "event": event}
    if data:
        record["data"] = data
    return record
```

#### テストケース一覧（18テスト）

**A. `EventLogger.read_events()` テスト (4件)**

| テスト名 | 検証内容 |
|---------|---------|
| `test_read_events_single_issue` | `read_events(issue_number=42)` が該当 Issue のイベントのみ返す |
| `test_read_events_all_issues` | `read_events()` (引数なし) が全 Issue のイベントを ts 順で返す |
| `test_read_events_empty` | ログファイルが存在しない場合に空リストを返す |
| `test_read_events_partial_line` | 不正な JSON 行をスキップし、正常行のみ返す |

**実装方法**: `tmp_path` に `issue-{N}/events.jsonl` を手動作成し、`EventLogger(tmp_path).read_events()` を呼び出す。

**B. `DashboardAggregator` テスト (9件)**

| テスト名 | 検証内容 |
|---------|---------|
| `test_aggregate_single_issue` | 単一 Issue のイベントから `IssueDashboardData` を正しく集計 |
| `test_aggregate_multiple_issues` | 複数 Issue のイベントから `DashboardData.issues` に正しくマッピング |
| `test_aggregate_cost_by_phase` | `phase_completed` イベントの `cost_usd` がフェーズ別に正しく加算される |
| `test_aggregate_duration_by_phase` | `phase_completed` イベントの `duration_sec` がフェーズ別に正しく加算される |
| `test_aggregate_error_by_category` | `error` イベントの `data.category` 別カウントが正しい |
| `test_aggregate_suspend_count` | `suspended` イベントのカウントが `total_suspends` に反映される |
| `test_get_progress_bug` | Bug タイプ + `ci-fix` フェーズ → `(4, 7)` |
| `test_get_progress_unknown_type` | 空文字 (未判定) → `(0, 0)` |
| `test_aggregate_empty_events` | 空リスト → デフォルト値の `DashboardData` |

**C. `DashboardRenderer` テスト (3件)**

| テスト名 | 検証内容 |
|---------|---------|
| `test_render_overview_no_exception` | `render_overview()` が例外なく `Layout` を返す |
| `test_render_issue_detail_no_exception` | `render_issue_detail()` が例外なく `Layout` を返す |
| `test_progress_bar_undetermined` | Type 未判定時に `"━━━ (不定)"` を含む文字列を返す |

**D. CLI コマンドテスト (2件)**

| テスト名 | 検証内容 |
|---------|---------|
| `test_dashboard_no_live` | `--no-live` でスナップショット表示が例外なく完了する |
| `test_dashboard_with_issue_no_live` | `--no-live --issue 42` で詳細表示が例外なく完了する |

**実装方法**: `tmp_path` にテスト用 events.jsonl を作成し、`_run_dashboard()` を直接呼び出す。または `typer.testing.CliRunner` で `dashboard --no-live --config {tmp_config}` を実行。

## 3. 依存関係グラフ

```
models.py (Step 1)
    ↓
event_logger.py (Step 2)
    ↓
commands/dashboard.py (Step 3)  ← models.py, event_logger.py に依存
    ↓
commands/__init__.py (Step 4)   ← dashboard.py に依存
    ↓
cli.py (Step 5)                 ← __init__.py に依存
    ↓
tests/unit/test_dashboard.py (Step 6) ← 全ての上記に依存
```

**ポイント**: Step 1-2 は独立して実装可能。Step 3 は Step 1-2 完了後。Step 4-5 は Step 3 完了後。Step 6 は全ステップ完了後に実行してグリーン確認。

## 4. テスト方針

### 実行コマンド

```bash
# ダッシュボードテストのみ
uv run pytest tests/unit/test_dashboard.py -v

# 既存テストへのリグレッション確認
uv run pytest tests/unit/ -v

# 型チェック
uv run mypy src/ai_agent_orchestrator/models.py src/ai_agent_orchestrator/event_logger.py src/ai_agent_orchestrator/commands/dashboard.py

# lint
uv run ruff check src/ai_agent_orchestrator/commands/dashboard.py tests/unit/test_dashboard.py
```

### テスト戦略

1. **TDD アプローチ**: テストファイルを Step 6 としているが、実装者は各 Step と並行してテストを書くことを推奨
2. **モック最小化**: `EventLogger` の読み取り API は `tmp_path` に実ファイルを作成してテスト（I/O モック不要）
3. **Renderer テスト**: UI のピクセル一致は検証しない。「例外なく完了すること」を基本とし、重要な文字列（プログレスバー形式など）のみ `assert ... in` で検証
4. **CI 互換**: `--no-live` モードのみテスト対象。`Rich Live` のリアルタイム更新はターミナル依存のため自動テスト対象外

### 既存テストへの影響

- `models.py` への追加は既存テストに影響なし（新規 dataclass のみ）
- `event_logger.py` への追加は既存テストに影響なし（新規メソッドのみ）
- `cli.py` への 1 行追加は既存 CLI テストに影響しない（新規コマンドの登録のみ）

## 5. 実装上の注意事項

1. **`field(default_factory=...)` の活用**: `ErrorStats`, `IssueDashboardData`, `DashboardData` のミュータブルデフォルト値には必ず `field(default_factory=...)` を使用すること
2. **イベント名の揺れ**: 設計書 §6.2 のとおり、`phase_start` / `phase_started` 両方をハンドルする。`phase_end` / `phase_completed` も同様
3. **型アノテーション**: mypy strict モード準拠。全関数に戻り値型を明記
4. **`asyncio.to_thread`**: `read_events()` は同期メソッドだが、`_run_dashboard()` 内では `await asyncio.to_thread(logger.read_events, issue_number)` で呼び出してイベントループをブロックしない
5. **Ctrl+C 対応**: `Live` コンテキスト内での `KeyboardInterrupt` は `Live.__exit__` が正常終了処理を行うため、特別なハンドリングは不要
6. **`--issue` で該当ログなし**: `DashboardData.issues` に該当 Issue がない場合、Renderer 側で「ログが見つかりません」メッセージを Panel で表示する
