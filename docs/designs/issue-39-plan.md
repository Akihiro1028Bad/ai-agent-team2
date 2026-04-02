# 実装計画: Issue #39 メトリクス収集基盤の構築

## 1. 変更ファイル一覧

| # | ファイルパス | 変更種別 | 説明 |
|---|------------|---------|------|
| 1 | `src/ai_agent_orchestrator/models.py` | 変更 | 6つの dataclass 追加 |
| 2 | `src/ai_agent_orchestrator/knowledge/metrics_collector.py` | 新規 | MetricsCollector クラス |
| 3 | `src/ai_agent_orchestrator/knowledge/__init__.py` | 変更 | MetricsCollector エクスポート追加 |
| 4 | `tests/unit/test_metrics_collector.py` | 新規 | ユニットテスト (20ケース) |

## 2. 依存関係と実装順序

```
models.py (Step 1)
    ↓
metrics_collector.py (Step 2〜5)
    ↓
knowledge/__init__.py (Step 5)
    ↓
test_metrics_collector.py (各Stepと並行してTDD)
```

**理由**: `MetricsCollector` は `models.py` の dataclass に依存するため、models.py を先に変更する必要がある。テストは TDD で各 Step と並行して作成する。

## 3. 各ファイルの変更内容

### Step 1: データモデル定義 (`models.py`)

**変更箇所**: ファイル末尾（`PHASE_CONFIG` 辞書の後）に新セクションを追加

```python
# ---------------------------------------------------------------------------
# 5. メトリクス用 Dataclass 定義
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseErrorStats:
    """フェーズ別エラー統計."""

    phase: str
    total_executions: int
    error_count: int
    error_rate: float  # 0.0 〜 1.0
    errors_by_category: dict[str, int]  # ErrorCategory -> count


@dataclass(frozen=True)
class PhaseRetryStats:
    """フェーズ別リトライ統計."""

    phase: str
    total_retries: int
    max_consecutive_retries: int
    avg_retries_per_execution: float


@dataclass(frozen=True)
class PhaseCostEntry:
    """フェーズ別コストエントリ."""

    phase: str
    total_cost_usd: float
    execution_count: int
    avg_cost_usd: float
    max_cost_usd: float


@dataclass(frozen=True)
class CIFailurePattern:
    """CI失敗パターン."""

    error_message: str
    occurrence_count: int
    affected_issues: list[int]
    first_seen: str  # ISO 8601
    last_seen: str  # ISO 8601


@dataclass(frozen=True)
class PhaseTransitionLoop:
    """フェーズ遷移ループ（繰り返し検知）."""

    loop_phases: tuple[str, ...]  # 例: ("ci-fix", "impl-review", "ci-fix")
    occurrence_count: int
    affected_issues: list[int]


@dataclass(frozen=True)
class DetectionMetrics:
    """バグ・改善検知用メトリクス集約結果.

    MetricsCollector が events.jsonl から集約したメトリクスを保持する。
    各フィールドはイミュータブルで、分析・閾値判定に利用される。
    """

    # 集計期間
    collected_at: str  # ISO 8601
    time_range_start: str  # ISO 8601
    time_range_end: str  # ISO 8601
    total_events_processed: int

    # フェーズ別エラー統計
    error_stats: tuple[PhaseErrorStats, ...]

    # フェーズ別コスト推移
    cost_by_phase: tuple[PhaseCostEntry, ...]

    # リトライ統計
    retry_stats: tuple[PhaseRetryStats, ...]

    # CI失敗パターン
    ci_failure_patterns: tuple[CIFailurePattern, ...]

    # フェーズ遷移ループ検知
    transition_loops: tuple[PhaseTransitionLoop, ...]

    # サマリ
    total_cost_usd: float
    total_errors: int
    total_issues_analyzed: int
```

**テスト (TC-MC-19)**: `DetectionMetrics` が frozen であること（`dataclasses.FrozenInstanceError` が発生すること）の検証。

---

### Step 2: イベント読み取り基盤 (`metrics_collector.py`)

**新規ファイル**: `src/ai_agent_orchestrator/knowledge/metrics_collector.py`

実装するメソッド:
- `__init__(self, log_dir: Path)` — ログディレクトリの保持
- `_read_events(self, issue_number: int) -> list[dict[str, Any]]` — JSONL パース。`asyncio.to_thread` でファイル読み取り。不正行はスキップして `logging.warning` で記録
- `_discover_issue_numbers(self) -> list[int]` — `issue-{N}` ディレクトリ名から正規表現 `r"^issue-(\d+)$"` で抽出
- `_filter_events_by_time(self, events, *, since, until) -> list[dict[str, Any]]` — `ts` フィールドを `datetime.fromisoformat()` でパースし範囲比較

**実装の詳細**:

```python
"""events.jsonl からメトリクスを収集・集約する."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ai_agent_orchestrator.models import (
    CIFailurePattern,
    DetectionMetrics,
    PhaseCostEntry,
    PhaseErrorStats,
    PhaseRetryStats,
    PhaseTransitionLoop,
)

logger = logging.getLogger(__name__)

_ISSUE_DIR_PATTERN = re.compile(r"^issue-(\d+)$")
```

`_read_events` の実装方針:
- `asyncio.to_thread` で同期ファイルI/Oをラップ
- 各行を `json.loads` でパース。`json.JSONDecodeError` は `logging.warning` でスキップ
- ファイル未存在時は `FileNotFoundError` をキャッチして空リストを返却

`_discover_issue_numbers` の実装方針:
- `asyncio.to_thread` で `log_dir.iterdir()` を実行
- ディレクトリのみを対象に `_ISSUE_DIR_PATTERN` でマッチ
- マッチしないディレクトリ名は無視

`_filter_events_by_time` の実装方針:
- 同期メソッド（CPU バウンド処理のため）
- `datetime.fromisoformat(event["ts"])` でパース
- `since` が None なら下限チェックなし、`until` が None なら上限チェックなし
- パース失敗時は当該イベントをスキップ

**対応テスト**: TC-MC-02, TC-MC-03, TC-MC-04, TC-MC-05, TC-MC-06, TC-MC-16, TC-MC-17

---

### Step 3: メトリクス計算ロジック

実装するメソッド:
- `_compute_error_stats(self, events) -> list[PhaseErrorStats]`
- `_compute_cost_by_phase(self, events) -> list[PhaseCostEntry]`
- `_compute_retry_stats(self, events) -> list[PhaseRetryStats]`

**`_compute_error_stats` の実装方針**:
1. `defaultdict` で phase ごとに total_executions と error_count を集計
2. エラー判定: `event["event"] == "error"` または `event.get("data", {}).get("error")` が存在
3. 実行回数判定: `event["event"]` が `"phase_start"` のレコードをカウント
4. `errors_by_category`: `data.error_category` でカテゴリ別にカウント。未指定は `"unknown"` として集計
5. `error_rate = error_count / total_executions` (total_executions == 0 の場合は 0.0)

**`_compute_cost_by_phase` の実装方針**:
1. `data.cost_usd` が存在するイベントのみ対象
2. phase ごとに `total_cost_usd`, `execution_count`, `max_cost_usd` を集計
3. `avg_cost_usd = total_cost_usd / execution_count`

**`_compute_retry_stats` の実装方針**:
1. リトライ判定: `event["event"] == "retry"` または `event.get("data", {}).get("retry_count", 0) > 0`
2. phase ごとに `total_retries` を集計
3. 連続リトライ検出: 同一 phase の連続するリトライイベントの最大連続数を `max_consecutive_retries` として記録
4. `avg_retries_per_execution`: phase の `phase_start` イベント数で割る（0 の場合は 0.0）

**対応テスト**: TC-MC-07, TC-MC-08, TC-MC-09, TC-MC-10, TC-MC-11

---

### Step 4: パターン検出ロジック

実装するメソッド:
- `_detect_ci_failure_patterns(self, events) -> list[CIFailurePattern]`
- `_detect_transition_loops(self, events) -> list[PhaseTransitionLoop]`

**`_detect_ci_failure_patterns` の実装方針**:
1. 対象イベント: `phase == "ci-fix"` かつ `data.error` が存在するレコード
2. `error_message` (= `data["error"]`) をキーに `defaultdict` でグルーピング
3. 各グループで `occurrence_count`, `affected_issues` (重複排除), `first_seen`, `last_seen` を集計
4. `occurrence_count` 降順でソート

**`_detect_transition_loops` の実装方針**:
1. Issue 単位で `event == "phase_start"` のイベントから phase シーケンスを構築
2. シーケンスに対してスライディングウィンドウ (window_size = 2, 3, 4):
   ```python
   for window_size in (2, 3, 4):
       subsequences: Counter[tuple[str, ...]] = Counter()
       for i in range(len(sequence) - window_size + 1):
           sub = tuple(sequence[i : i + window_size])
           subsequences[sub] += 1
   ```
3. `count >= 2` のパターンをループとして記録
4. 全 Issue のループをマージ: 同一 `loop_phases` の `occurrence_count` を合算し `affected_issues` を統合
5. 短いパターンが長いパターンの部分列である場合は、長いパターンを優先（重複排除）

**対応テスト**: TC-MC-12, TC-MC-13, TC-MC-14, TC-MC-15

---

### Step 5: 統合 (`collect` メソッド) + エクスポート

**`collect` メソッドの実装方針**:
1. `issue_numbers` が None なら `_discover_issue_numbers()` で全 Issue を取得
2. 各 Issue に対して `_read_events()` でイベントを読み取り、全イベントを結合
3. `_filter_events_by_time()` で期間フィルタリング
4. 各計算メソッドを呼び出してメトリクスを収集
5. `DetectionMetrics` を構築して返却:
   - `collected_at`: `datetime.now(UTC).isoformat()`
   - `time_range_start` / `time_range_end`: フィルタ後イベントの最小/最大 `ts`（イベントなしの場合は空文字列）
   - `total_events_processed`: フィルタ後イベント数
   - `total_cost_usd`: `cost_by_phase` の `total_cost_usd` 合計
   - `total_errors`: `error_stats` の `error_count` 合計
   - `total_issues_analyzed`: ユニークな Issue 数

**`knowledge/__init__.py` の変更**:
```python
"""知識管理パッケージ."""

from ai_agent_orchestrator.knowledge.metrics_collector import MetricsCollector

__all__ = ["MetricsCollector"]
```

**対応テスト**: TC-MC-01, TC-MC-18, TC-MC-19, TC-MC-20

---

## 4. テスト方針

### テストファイル構成

`tests/unit/test_metrics_collector.py` に全 20 テストケースを実装する。

### テストフィクスチャ

```python
@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """テスト用ログディレクトリ."""
    return tmp_path / "logs"


@pytest.fixture
def sample_events() -> list[dict[str, Any]]:
    """サンプルイベントレコード."""
    # 設計書 §7.2 のサンプルデータ


def write_events_jsonl(
    log_dir: Path,
    issue_number: int,
    events: list[dict[str, Any]],
) -> None:
    """テスト用にevents.jsonlを書き出すヘルパー."""
    # 設計書 §7.2 のヘルパー関数
```

### テストケース一覧と実装順序

| Step | テストID | テスト内容 |
|------|---------|-----------|
| 1 | TC-MC-19 | `DetectionMetrics` が frozen であること |
| 2 | TC-MC-02 | `_read_events()` が JSONL を正しくパースすること |
| 2 | TC-MC-03 | `_read_events()` がファイル未存在で空リスト |
| 2 | TC-MC-04 | `_read_events()` が不正JSON行をスキップ |
| 2 | TC-MC-05 | `_discover_issue_numbers()` が正しく抽出 |
| 2 | TC-MC-06 | `_discover_issue_numbers()` が非issueディレクトリを無視 |
| 2 | TC-MC-16 | `_filter_events_by_time()` が since/until でフィルタ |
| 2 | TC-MC-17 | `_filter_events_by_time()` が None で全件返却 |
| 3 | TC-MC-07 | `_compute_error_stats()` が正しくエラー率計算 |
| 3 | TC-MC-08 | `_compute_error_stats()` がエラー無しで rate=0.0 |
| 3 | TC-MC-09 | `_compute_cost_by_phase()` がコスト正しく集計 |
| 3 | TC-MC-10 | `_compute_cost_by_phase()` が cost_usd 未設定を無視 |
| 3 | TC-MC-11 | `_compute_retry_stats()` が連続リトライ最大値を計算 |
| 4 | TC-MC-12 | `_detect_ci_failure_patterns()` がグルーピング |
| 4 | TC-MC-13 | `_detect_ci_failure_patterns()` が出現回数降順 |
| 4 | TC-MC-14 | `_detect_transition_loops()` がループ検出 |
| 4 | TC-MC-15 | `_detect_transition_loops()` がループなしで空リスト |
| 5 | TC-MC-01 | `collect()` が空ディレクトリで空メトリクス |
| 5 | TC-MC-18 | `collect(issue_numbers=[42])` が指定Issueのみ集計 |
| 5 | TC-MC-20 | 複数Issueの統合メトリクスが正しいこと |

### テスト実行コマンド

```bash
# メトリクスコレクターのテストのみ
uv run pytest tests/unit/test_metrics_collector.py -v

# 全テスト
uv run pytest tests/ -v

# 型チェック
uv run mypy src/

# lint
uv run ruff check src/ tests/
```

## 5. 品質チェックリスト

- [ ] 全テスト (20ケース) が PASS
- [ ] `uv run mypy src/` — エラーなし
- [ ] `uv run ruff check src/ tests/` — エラーなし
- [ ] `uv run ruff format src/ tests/` — フォーマット適用済み
- [ ] 全 dataclass に `frozen=True` が設定されている
- [ ] 全メソッドに型アノテーションがある
- [ ] 全クラス・公開メソッドに Google style docstring がある
- [ ] 非同期メソッドは `async def` で定義されている
- [ ] ファイル I/O は `asyncio.to_thread` でラップされている
- [ ] 不正 JSONL 行のスキップが実装されている

## 6. リスク対策

| リスク | 対策 |
|-------|------|
| events.jsonl のサイズ増大 | `since`/`until` パラメータで期間限定収集 |
| JSONL の不正行 | `json.JSONDecodeError` をキャッチしてスキップ + warning ログ |
| 並行アクセス | 読み取り専用のため影響軽微。JSONL は行単位追記で安全 |
| 未知のイベント名 | ハードコードを最小限にし、キー存在チェックで安全に処理 |
