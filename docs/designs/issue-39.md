# 設計書: Issue #39 メトリクス収集基盤の構築

## 1. 概要

フェーズ実行結果から生成される `events.jsonl` を解析し、バグ・改善検知に必要なメトリクスを収集・集約するモジュール `MetricsCollector` を構築する。
本モジュールは親 Issue #38（AIエージェント起動中に自動でバグ・改善点を検知してissue起票）の基盤となり、エラー発生率・コスト推移・CI失敗パターン・フェーズ遷移の繰り返し検知などの統計情報を提供する。

## 2. 現状分析

### 2.1 既存のイベントログ構造

`EventLogger` は Issue 単位で `{log_dir}/issue-{issue_number}/events.jsonl` にイベントを記録する。

各レコードの構造:
```json
{
    "ts": "2026-04-01T12:00:00+00:00",
    "issue": 42,
    "phase": "implement",
    "event": "phase_start",
    "data": {
        "cost_usd": 1.23,
        "duration_sec": 300,
        "error": "...",
        "retry_count": 2
    }
}
```

### 2.2 既存の関連モデル

| モデル | 用途 |
|-------|------|
| `AgentResult` | エージェント実行結果（`cost_usd`, `duration_sec`） |
| `PhaseResult` | フェーズ実行結果（`cost_usd`, `duration_sec`, `review_comments`） |
| `IssueState` | Issue状態（`phase`, `retry_count`, `issue_type`） |
| `Phase` (Enum) | 19種のフェーズ定義 |
| `EventType` (Enum) | 13種のイベント種別 |
| `ErrorCategory` (Enum) | 5種のエラー分類 |

### 2.3 既存のknowledgeパッケージ

`knowledge/` パッケージには `episode_store.py`、`pattern_extractor.py`、`skill_manager.py` が存在するが、いずれもスタブ状態。`MetricsCollector` はこれらと並行して実装される独立モジュールとなる。

### 2.4 課題

1. **メトリクスの集約手段がない** - events.jsonl は生ログであり、分析可能な形で集約する仕組みがない
2. **異常検知の基盤がない** - エラー率やリトライ回数の閾値判定ができない
3. **コスト監視ができない** - フェーズ別コスト推移を把握する手段がない
4. **繰り返しパターンの検知ができない** - 同じフェーズ遷移の繰り返し（例: CI_FIX → IMPL_REVIEW → CI_FIX のループ）を検出できない

## 3. 設計方針

### 3.1 基本原則

| 項目 | 方針 |
|------|------|
| 読み取り専用 | EventLogger のログを読み取るのみ。ログへの書き込みは行わない |
| 非同期対応 | `async def` で統一。ファイルI/Oは `asyncio.to_thread` でブロッキング回避 |
| Protocol準拠 | 将来的に Protocol として抽象化可能な設計 |
| 既存構造の尊重 | EventLogger の JSONL フォーマットをそのまま利用。新たなログ形式は導入しない |
| イミュータブル結果 | 集約結果は `frozen=True` の dataclass で返却 |
| 単一責任 | MetricsCollector はメトリクス収集のみ。検知ロジックは別モジュール（Issue #38-2 以降）で実装 |

### 3.2 配置

```
src/ai_agent_orchestrator/knowledge/
├── __init__.py              # MetricsCollector をエクスポート
├── metrics_collector.py     # 新規: MetricsCollector クラス
├── episode_store.py         # 既存スタブ
├── pattern_extractor.py     # 既存スタブ
└── skill_manager.py         # 既存
```

## 4. 詳細設計

### 4.1 `DetectionMetrics` dataclass（`models.py` に追加）

```python
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
    last_seen: str   # ISO 8601


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

### 4.2 `MetricsCollector` クラス（`knowledge/metrics_collector.py`）

```python
class MetricsCollector:
    """events.jsonl からメトリクスを収集・集約する.

    EventLogger が出力した JSONL ファイルを読み取り、
    バグ・改善検知に必要な統計情報を DetectionMetrics に集約する。

    Attributes:
        _log_dir: EventLogger と同じログ基底ディレクトリ。
    """

    def __init__(self, log_dir: Path) -> None:
        """初期化.

        Args:
            log_dir: EventLogger のログ基底ディレクトリ。
        """
        ...

    async def collect(
        self,
        *,
        issue_numbers: list[int] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> DetectionMetrics:
        """メトリクスを収集・集約する.

        Args:
            issue_numbers: 対象Issue番号リスト。None の場合は全Issue。
            since: 集計開始日時。None の場合は全期間。
            until: 集計終了日時。None の場合は現在時刻。

        Returns:
            集約されたメトリクス。
        """
        ...

    async def _read_events(
        self,
        issue_number: int,
    ) -> list[dict[str, Any]]:
        """指定Issueの events.jsonl を読み取る.

        Args:
            issue_number: 対象Issue番号。

        Returns:
            イベントレコードのリスト。ファイルが存在しない場合は空リスト。
        """
        ...

    async def _discover_issue_numbers(self) -> list[int]:
        """ログディレクトリから全Issue番号を検出する.

        ディレクトリ名 `issue-{N}` からIssue番号を抽出する。

        Returns:
            検出されたIssue番号のリスト。
        """
        ...

    def _compute_error_stats(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseErrorStats]:
        """フェーズ別エラー統計を計算する.

        events 内の phase ごとにエラー発生率・カテゴリ別カウントを集計する。
        エラーイベントは event フィールドが 'error' または
        data 内に 'error' キーを持つレコードで識別する。

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別エラー統計のリスト。
        """
        ...

    def _compute_cost_by_phase(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseCostEntry]:
        """フェーズ別コスト推移を計算する.

        events 内の data.cost_usd をフェーズ別に集計する。

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別コストエントリのリスト。
        """
        ...

    def _compute_retry_stats(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseRetryStats]:
        """フェーズ別リトライ統計を計算する.

        events 内の retry 関連イベントをフェーズ別に集計する。
        連続リトライ数の最大値、平均リトライ数を算出する。

        Args:
            events: 全イベントレコード。

        Returns:
            フェーズ別リトライ統計のリスト。
        """
        ...

    def _detect_ci_failure_patterns(
        self,
        events: list[dict[str, Any]],
    ) -> list[CIFailurePattern]:
        """CI失敗パターンを検出する.

        CI失敗イベント（phase='ci-fix' または event='ci_failure'）の
        エラーメッセージをグルーピングし、頻出パターンを抽出する。

        Args:
            events: 全イベントレコード。

        Returns:
            CI失敗パターンのリスト（出現回数降順）。
        """
        ...

    def _detect_transition_loops(
        self,
        events: list[dict[str, Any]],
    ) -> list[PhaseTransitionLoop]:
        """フェーズ遷移ループを検出する.

        同一Issue内で同じフェーズ遷移パターンが繰り返されるケースを検出する。
        例: ci-fix → impl-review → ci-fix のような修正ループ。

        検出アルゴリズム:
        1. Issue単位でフェーズ遷移シーケンスを構築
        2. 長さ2〜4のスライディングウィンドウで部分列を抽出
        3. 同一部分列が2回以上出現するものをループとして報告

        Args:
            events: 全イベントレコード。

        Returns:
            検出されたフェーズ遷移ループのリスト。
        """
        ...

    def _filter_events_by_time(
        self,
        events: list[dict[str, Any]],
        *,
        since: datetime | None,
        until: datetime | None,
    ) -> list[dict[str, Any]]:
        """イベントを時刻範囲でフィルタリングする.

        Args:
            events: フィルタ対象のイベントリスト。
            since: 開始日時（含む）。
            until: 終了日時（含む）。

        Returns:
            フィルタ後のイベントリスト。
        """
        ...
```

### 4.3 イベント識別ルール

events.jsonl のレコードから各メトリクスを抽出するためのルール:

| メトリクス | イベント識別条件 | 抽出フィールド |
|-----------|-----------------|---------------|
| エラー発生 | `event == "error"` または `data.error` が存在 | `phase`, `data.error_category`, `data.error` |
| コスト | `data.cost_usd` が存在 | `phase`, `data.cost_usd` |
| リトライ | `event == "retry"` または `data.retry_count > 0` | `phase`, `data.retry_count` |
| CI失敗 | `phase == "ci-fix"` かつ `event` に失敗を示す値 | `data.error`, `issue`, `ts` |
| フェーズ遷移 | `event == "phase_start"` または `event == "phase_complete"` | `phase`, `issue`, `ts` |

### 4.4 フェーズ遷移ループ検出アルゴリズム

```
入力: イベントリスト（時系列順）
出力: PhaseTransitionLoop のリスト

1. Issue ごとにフェーズ遷移シーケンスを構築
   sequence = [phase_1, phase_2, phase_3, ...]

2. 各 Issue のシーケンスに対してスライディングウィンドウ検査
   for window_size in [2, 3, 4]:
       subsequences = Counter()
       for i in range(len(sequence) - window_size + 1):
           sub = tuple(sequence[i:i+window_size])
           subsequences[sub] += 1

       loops = {sub: count for sub, count in subsequences.items() if count >= 2}

3. 全 Issue のループをマージ
   同一パターンは affected_issues を統合
```

### 4.5 `knowledge/__init__.py` の更新

```python
"""知識管理パッケージ."""

from ai_agent_orchestrator.knowledge.metrics_collector import MetricsCollector

__all__ = ["MetricsCollector"]
```

## 5. 変更対象ファイル

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `src/ai_agent_orchestrator/models.py` | 変更 | `PhaseErrorStats`, `PhaseRetryStats`, `PhaseCostEntry`, `CIFailurePattern`, `PhaseTransitionLoop`, `DetectionMetrics` の 6 dataclass を追加 |
| `src/ai_agent_orchestrator/knowledge/__init__.py` | 変更 | `MetricsCollector` のエクスポートを追加 |
| `src/ai_agent_orchestrator/knowledge/metrics_collector.py` | 新規 | `MetricsCollector` クラス |
| `tests/unit/test_metrics_collector.py` | 新規 | ユニットテスト |

## 6. データフロー

```
events.jsonl (入力)
    │
    ▼
MetricsCollector.collect()
    │
    ├─ _discover_issue_numbers()    ← log_dir から issue-{N} ディレクトリ列挙
    │
    ├─ _read_events(issue_number)   ← JSONL パース
    │
    ├─ _filter_events_by_time()     ← since/until でフィルタ
    │
    ├─ _compute_error_stats()       ← フェーズ別エラー率計算
    │
    ├─ _compute_cost_by_phase()     ← フェーズ別コスト集計
    │
    ├─ _compute_retry_stats()       ← リトライ統計計算
    │
    ├─ _detect_ci_failure_patterns() ← CI失敗パターンのグルーピング
    │
    └─ _detect_transition_loops()   ← フェーズ遷移ループ検出
    │
    ▼
DetectionMetrics (出力, frozen dataclass)
    │
    ▼
(Issue #38-2 以降) 異常検知モジュールが閾値判定・Issue起票
```

## 7. テスト計画

### 7.1 テストケース一覧

| テストID | テスト内容 | 分類 |
|---------|-----------|------|
| TC-MC-01 | `collect()` が空のログディレクトリで空の `DetectionMetrics` を返すこと | 正常系 |
| TC-MC-02 | `_read_events()` が存在するJSONLファイルを正しくパースすること | 正常系 |
| TC-MC-03 | `_read_events()` がファイル未存在時に空リストを返すこと | 異常系 |
| TC-MC-04 | `_read_events()` が不正なJSONL行をスキップすること | 異常系 |
| TC-MC-05 | `_discover_issue_numbers()` がディレクトリ名からIssue番号を正しく抽出すること | 正常系 |
| TC-MC-06 | `_discover_issue_numbers()` が `issue-` 以外のディレクトリを無視すること | 異常系 |
| TC-MC-07 | `_compute_error_stats()` がフェーズ別エラー率を正しく計算すること | 正常系 |
| TC-MC-08 | `_compute_error_stats()` がエラー無しの場合に error_rate=0.0 を返すこと | 境界値 |
| TC-MC-09 | `_compute_cost_by_phase()` がフェーズ別コストを正しく集計すること | 正常系 |
| TC-MC-10 | `_compute_cost_by_phase()` が cost_usd 未設定のイベントを無視すること | 異常系 |
| TC-MC-11 | `_compute_retry_stats()` が連続リトライ数の最大値を正しく計算すること | 正常系 |
| TC-MC-12 | `_detect_ci_failure_patterns()` が同一エラーメッセージをグルーピングすること | 正常系 |
| TC-MC-13 | `_detect_ci_failure_patterns()` が出現回数降順でソートされること | 正常系 |
| TC-MC-14 | `_detect_transition_loops()` が ci-fix → impl-review ループを検出すること | 正常系 |
| TC-MC-15 | `_detect_transition_loops()` がループなしの場合に空リストを返すこと | 境界値 |
| TC-MC-16 | `_filter_events_by_time()` が since/until で正しくフィルタすること | 正常系 |
| TC-MC-17 | `_filter_events_by_time()` が since=None, until=None で全件返すこと | 境界値 |
| TC-MC-18 | `collect(issue_numbers=[42])` が指定Issueのみ集計すること | 正常系 |
| TC-MC-19 | `DetectionMetrics` が frozen であること（変更不可） | モデル |
| TC-MC-20 | 複数Issueにまたがるメトリクスが正しく統合されること | 正常系 |

### 7.2 テスト用フィクスチャ

```python
@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    """テスト用ログディレクトリ."""
    return tmp_path / "logs"


@pytest.fixture
def sample_events() -> list[dict[str, Any]]:
    """サンプルイベントレコード."""
    return [
        {
            "ts": "2026-04-01T10:00:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_start",
            "data": {},
        },
        {
            "ts": "2026-04-01T10:05:00+00:00",
            "issue": 42,
            "phase": "implement",
            "event": "phase_complete",
            "data": {"cost_usd": 1.5, "duration_sec": 300},
        },
        {
            "ts": "2026-04-01T10:06:00+00:00",
            "issue": 42,
            "phase": "ci-fix",
            "event": "error",
            "data": {
                "error": "lint failed",
                "error_category": "ci_failure",
                "retry_count": 1,
            },
        },
    ]


def write_events_jsonl(
    log_dir: Path,
    issue_number: int,
    events: list[dict[str, Any]],
) -> None:
    """テスト用にevents.jsonlを書き出すヘルパー."""
    issue_dir = log_dir / f"issue-{issue_number}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    events_file = issue_dir / "events.jsonl"
    with events_file.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
```

## 8. 実装順序

1. **Step 1: データモデル定義**
   - `models.py` に `PhaseErrorStats`, `PhaseRetryStats`, `PhaseCostEntry`, `CIFailurePattern`, `PhaseTransitionLoop`, `DetectionMetrics` を追加
   - `DetectionMetrics` が frozen であることのテスト

2. **Step 2: イベント読み取り基盤**
   - `MetricsCollector.__init__()`, `_read_events()`, `_discover_issue_numbers()`, `_filter_events_by_time()` を実装
   - TC-MC-02 〜 TC-MC-06, TC-MC-16, TC-MC-17 のテスト

3. **Step 3: メトリクス計算ロジック**
   - `_compute_error_stats()`, `_compute_cost_by_phase()`, `_compute_retry_stats()` を実装
   - TC-MC-07 〜 TC-MC-11 のテスト

4. **Step 4: パターン検出ロジック**
   - `_detect_ci_failure_patterns()`, `_detect_transition_loops()` を実装
   - TC-MC-12 〜 TC-MC-15 のテスト

5. **Step 5: 統合 (`collect` メソッド)**
   - `collect()` で全メトリクスを統合し `DetectionMetrics` を返却
   - `knowledge/__init__.py` のエクスポート更新
   - TC-MC-01, TC-MC-18, TC-MC-19, TC-MC-20 のテスト

## 9. リスク・考慮事項

| リスク | 影響 | 対策 |
|-------|------|------|
| events.jsonl のサイズ増大 | メモリ使用量の増加 | `since`/`until` パラメータによる期間限定収集。将来的にはストリーミング処理への移行 |
| JSONL のフォーマット変更 | パース失敗 | 不正行のスキップ + ログ出力。既存フォーマットに依存せず、キーの存在チェックで安全に処理 |
| EventLogger のイベント名追加・変更 | 未知イベントの取りこぼし | 既知イベント名のハードコードを最小限に。フォールバックでunknownとして処理 |
| 並行実行時のファイルロック | 読み取り中の書き込み | 読み取り専用のため影響は軽微。JSONL は行単位で追記のため部分読み取りも安全 |
| CI失敗パターンのグルーピング精度 | 類似エラーが別パターンとして認識される | 初期実装では完全一致。将来的にはファジーマッチングを導入可能 |

## 10. 将来の拡張

- **Issue #38-2**: 閾値ベースの異常検知モジュールが `DetectionMetrics` を入力として判定
- **Issue #38-3**: 検知結果から GitHub Issue を自動起票
- **メトリクス永続化**: 集約結果をJSON/SQLiteに保存し、時系列比較を可能にする
- **ダッシュボード連携**: メトリクスを外部監視ツール（Grafana等）にエクスポート
