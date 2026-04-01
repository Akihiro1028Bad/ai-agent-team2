# 設計書: Issue #30 イベントログの可視化ダッシュボード機能

## 1. 概要

`events.jsonl` に記録されているイベントログを集計・可視化するターミナルダッシュボード機能を追加する。
`ai-agent dashboard` コマンドとして実装し、Rich Live による自動更新（5秒間隔）で Issue の進捗・コスト・エラー統計をリアルタイム表示する。

### 既存 `logs` コマンドとの棲み分け

| コマンド | 目的 | 表示内容 |
|---------|------|---------|
| `ai-agent logs` | ログ一覧の確認 | events.jsonl の生ログを時系列で表示 |
| `ai-agent dashboard` | 集計・可視化 | Issue ごとの進捗、コスト、エラー統計を集約表示 |

## 2. ヒアリング結果サマリー

| # | 質問 | 回答 |
|---|------|------|
| 1 | 表示モード | **(A)** Rich Live 自動更新、リフレッシュ間隔 **5秒** |
| 2 | 表示スコープ | 全 Issue 横断 + `--issue` オプション。`logs` はログ一覧、`dashboard` は集計・可視化 |
| 3 | コスト集計粒度 | **(c)** 全 Issue 合計サマリー + フェーズごと内訳 |
| 4 | 読み取り API 方針 | `EventLogger` にメソッド追加。書き込みロジックへの影響なし |
| 5 | エラー統計の詳細 | **(b)** `ErrorCategory` 別（transient, auth, git_conflict, output_invalid, ci_failure）の内訳も表示 |
| 6 | プログレスバー | Issue の進捗（全フェーズ中の現在位置）。Type 未判定中は不定として表示 |
| 7 | イベント名パターン | `phase_started` / `phase_completed` / `error` / `suspended` |
| 8 | `--issue` 時のレイアウト | **(b)** フェーズ遷移タイムラインの詳細を追加表示 |

## 3. アーキテクチャ

### 3.1 モジュール構成

```
src/ai_agent_orchestrator/
├── cli.py                          # dashboard コマンド登録を追加
├── commands/
│   ├── __init__.py                 # dashboard_command のエクスポート追加
│   └── dashboard.py                # 【新規】ダッシュボードコマンド実装
├── event_logger.py                 # read_events() メソッド追加
└── models.py                       # ダッシュボード用データモデル追加

tests/unit/
└── test_dashboard.py               # 【新規】ダッシュボードのユニットテスト
```

### 3.2 データフロー

```
events.jsonl (ファイル)
    │
    ▼
EventLogger.read_events()          ← 読み取り API（新規追加）
    │
    ▼
DashboardAggregator                ← イベント集計ロジック
    │
    ▼
DashboardData / IssueDashboardData ← 集計済みデータモデル
    │
    ▼
DashboardRenderer                  ← Rich UI レンダリング
    │
    ▼
Rich Live (ターミナル出力)           ← 5秒間隔で自動更新
```

## 4. データモデル設計 (`models.py` への追加)

### 4.1 フェーズ遷移レコード

```python
@dataclass(frozen=True)
class PhaseTransitionRecord:
    """フェーズ遷移の記録."""

    timestamp: str
    from_phase: str
    to_phase: str
    cost_usd: float
    duration_sec: float
```

### 4.2 エラー統計

```python
@dataclass
class ErrorStats:
    """エラー/サスペンド統計."""

    total_errors: int = 0
    total_suspends: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    # キー: ErrorCategory の値 (transient, auth, git_conflict, output_invalid, ci_failure)
```

### 4.3 Issue 単位のダッシュボードデータ

```python
@dataclass
class IssueDashboardData:
    """Issue 単位のダッシュボード表示データ."""

    issue_number: int
    issue_type: str  # IssueType の値、未判定なら空文字
    current_phase: str
    total_cost_usd: float
    total_duration_sec: float
    phase_costs: dict[str, float]  # フェーズ名 → 累積コスト
    phase_durations: dict[str, float]  # フェーズ名 → 累積処理時間
    transitions: list[PhaseTransitionRecord]
    error_stats: ErrorStats
    started_at: str  # 最初のイベントのタイムスタンプ
    updated_at: str  # 最新のイベントのタイムスタンプ
```

### 4.4 ダッシュボード全体データ

```python
@dataclass
class DashboardData:
    """ダッシュボード全体の集計データ."""

    issues: dict[int, IssueDashboardData]
    total_cost_usd: float
    total_issues: int
    active_issues: int  # Phase が DONE / SUSPENDED 以外
    completed_issues: int  # Phase が DONE
    suspended_issues: int  # Phase が SUSPENDED
    total_errors: int
    total_suspends: int
```

## 5. `EventLogger` 読み取り API 設計

既存の `EventLogger` クラスに以下のメソッドを追加する。書き込みロジック（`track()`, `write_phase_log()`）には一切影響しない。

```python
class EventLogger:
    # ... 既存コード ...

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
            同期メソッドとして実装する（読み取り専用、ロック不要）。
            書き込み中のファイルを読むためパーシャルラインは無視する。
        """

    def _read_single_issue_events(self, issue_number: int) -> list[dict[str, Any]]:
        """単一Issueのイベントファイルを読み取る."""

    def _read_all_events(self) -> list[dict[str, Any]]:
        """全Issueのイベントファイルを読み取る."""
```

### 設計判断

- **同期メソッド**: 読み取りは書き込みロックに参加しないため、`async` にしない。ダッシュボードは `asyncio.to_thread()` 経由で呼び出す
- **戻り値**: `list[dict[str, Any]]` — パース済み JSON 辞書のリスト
- **エラーハンドリング**: 不正な JSON 行はスキップ（パーシャルライン対策）
- **ファイル不存在**: 空リストを返す（例外を投げない）

## 6. 集計ロジック設計 (`commands/dashboard.py`)

### 6.1 `DashboardAggregator` クラス

```python
class DashboardAggregator:
    """イベントログからダッシュボードデータを集計する."""

    # IssueType ごとのフェーズ順序定義
    PHASE_ORDER: ClassVar[dict[str, list[str]]] = {
        "bug": [
            "type-detection", "analysis", "plan-review",
            "fix", "ci-fix", "impl-review", "done",
        ],
        "feature-s": [
            "type-detection", "plan-brief", "plan-review",
            "implement", "ci-fix", "impl-review", "done",
        ],
        "feature-m": [
            "type-detection", "hearing", "hearing-wait",
            "design", "design-review", "design-revise",
            "planning", "implement", "ci-fix",
            "impl-review", "impl-revise", "done",
        ],
        "feature-l": [
            "type-detection", "hearing", "hearing-wait",
            "design", "design-review", "design-revise",
            "planning", "split-proposal", "split-execute", "done",
        ],
    }

    def aggregate(self, events: list[dict[str, Any]]) -> DashboardData:
        """イベントリストからダッシュボードデータを集計する."""

    def aggregate_issue(self, events: list[dict[str, Any]]) -> IssueDashboardData:
        """単一Issueのイベントリストからデータを集計する."""

    @staticmethod
    def get_progress(issue_type: str, current_phase: str) -> tuple[int, int]:
        """プログレスバー用の (現在位置, 全ステップ数) を返す.

        Args:
            issue_type: IssueType の値。空文字の場合は未判定。
            current_phase: 現在のフェーズ名。

        Returns:
            (current_step, total_steps) のタプル。
            未判定の場合は (0, 0) を返す（不定表示用）。
        """
```

### 6.2 イベント集計ルール

| イベント名 | 集計対象 | 抽出データ |
|-----------|---------|-----------|
| `phase_start` / `phase_started` | 現在フェーズ更新 | `phase`, `ts` |
| `phase_end` / `phase_completed` | コスト・時間の加算 | `data.cost_usd`, `data.duration_sec` |
| `phase_transition` | フェーズ遷移履歴 | `data.from`, `data.to` |
| `error` / `phase_error` | エラーカウント | `data.category` (ErrorCategory) |
| `suspended` | サスペンドカウント | — |

### 6.3 Issue Type の判定

events.jsonl には `issue_type` フィールドが直接ないため、以下のロジックで推定する:

1. `phase_start` イベントで `analysis` / `fix` フェーズが出現 → `bug`
2. `phase_start` イベントで `plan-brief` フェーズが出現 → `feature-s`
3. `phase_start` イベントで `hearing` / `design` フェーズが出現 → `feature-m` (暫定)
4. `phase_start` イベントで `split-proposal` / `split-execute` フェーズが出現 → `feature-l`
5. 上記いずれにも該当しない → 空文字（未判定）

> **Note**: `state-{issue_number}.json` に `issue_type` フィールドがある場合はそちらを優先するが、ダッシュボードはイベントログのみで完結する設計とする（状態ファイルへの依存を避ける）。

## 7. UI レイアウト設計

### 7.1 全 Issue 横断表示（デフォルト）

```
┌──────────────────────────────────────────────────────────────┐
│                    AI Agent Dashboard                         │
│                 Last updated: 2026-04-01 12:00:00            │
├──────────────────────────────────────────────────────────────┤
│ Summary                                                       │
│  Total Issues: 5  Active: 2  Completed: 2  Suspended: 1     │
│  Total Cost: $12.50 USD                                       │
│  Total Errors: 3  Total Suspends: 1                          │
├──────────────────────────────────────────────────────────────┤
│ Issues                                                        │
│ ┌────────┬──────────┬───────────┬──────────────┬──────┬──────┐│
│ │ Issue  │ Type     │ Phase     │ Progress     │ Cost │Errors││
│ ├────────┼──────────┼───────────┼──────────────┼──────┼──────┤│
│ │ #42    │ bug      │ ci-fix    │ ████░░ 4/6   │$2.30 │  1   ││
│ │ #43    │feature-m │ implement │ ███████░ 8/12│$5.10 │  0   ││
│ │ #44    │feature-s │ done      │ ██████ 7/7   │$1.80 │  0   ││
│ │ #45    │feature-l │ suspended │ ██░░░░ 3/10  │$3.00 │  2   ││
│ │ #46    │ (未判定) │type-detect│ ━━━ (不定)   │$0.30 │  0   ││
│ └────────┴──────────┴───────────┴──────────────┴──────┴──────┘│
├──────────────────────────────────────────────────────────────┤
│ Error Statistics                                              │
│ ┌─────────────────┬───────┐                                   │
│ │ Category        │ Count │                                   │
│ ├─────────────────┼───────┤                                   │
│ │ transient       │   1   │                                   │
│ │ ci_failure      │   2   │                                   │
│ └─────────────────┴───────┘                                   │
└──────────────────────────────────────────────────────────────┘
```

### 7.2 `--issue` 指定時の詳細表示

全 Issue 横断表示に加えて、以下のフェーズ遷移タイムラインを追加表示する:

```
┌──────────────────────────────────────────────────────────────┐
│              Issue #42 Detail - type: bug                     │
├──────────────────────────────────────────────────────────────┤
│ Phase Timeline                                                │
│                                                               │
│  12:00:00  type-detection ──→ analysis        $0.30  30s     │
│  12:01:00  analysis       ──→ plan-review     $1.20 120s     │
│  12:05:00  plan-review    ──→ fix             $0.00   0s     │
│  12:05:01  fix            ──→ ci-fix          $0.50  60s     │
│  12:06:30  ci-fix         (現在)              $0.30  90s     │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│ Cost Breakdown by Phase                                       │
│ ┌─────────────────┬──────────┬───────────┐                    │
│ │ Phase           │ Cost USD │ Duration  │                    │
│ ├─────────────────┼──────────┼───────────┤                    │
│ │ type-detection  │    $0.30 │      30s  │                    │
│ │ analysis        │    $1.20 │     120s  │                    │
│ │ fix             │    $0.50 │      60s  │                    │
│ │ ci-fix          │    $0.30 │      90s  │                    │
│ ├─────────────────┼──────────┼───────────┤                    │
│ │ TOTAL           │    $2.30 │     300s  │                    │
│ └─────────────────┴──────────┴───────────┘                    │
├──────────────────────────────────────────────────────────────┤
│ Error Details                                                 │
│  [12:06:00] ci_failure: pytest failed with exit code 1       │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 プログレスバーの表示ルール

| 状態 | 表示 |
|------|------|
| Type 判定済み | `████░░ 4/6` のようなバー + 数値 |
| Type 未判定 (TYPE_DETECTION 中) | `━━━ (不定)` パルスアニメーション風 |
| DONE | `██████ N/N` フルバー (緑) |
| SUSPENDED | `██░░░░ X/N` 現在位置 (赤) |

## 8. CLI インターフェース設計

### 8.1 コマンド定義

```python
def dashboard_command(
    issue: int | None = typer.Option(
        None,
        "--issue", "-i",
        help="特定 Issue の詳細を表示",
    ),
    refresh: int = typer.Option(
        5,
        "--refresh", "-r",
        help="リフレッシュ間隔（秒）",
    ),
    no_live: bool = typer.Option(
        False,
        "--no-live",
        help="スナップショット表示（1回表示して終了）",
    ),
    config: str = typer.Option(
        "config.yaml",
        "--config", "-c",
        help="設定ファイルパス",
    ),
) -> None:
    """イベントログの可視化ダッシュボードを表示する."""
```

### 8.2 CLI 登録

```python
# cli.py
app.command("dashboard")(dashboard_command)

# commands/__init__.py
from ai_agent_orchestrator.commands.dashboard import dashboard_command
# __all__ に "dashboard_command" を追加
```

## 9. `DashboardRenderer` クラス設計

```python
class DashboardRenderer:
    """Rich を使ったダッシュボード UI レンダリング."""

    def __init__(self, console: Console) -> None:
        """初期化."""

    def render_overview(self, data: DashboardData) -> Layout:
        """全 Issue 横断のダッシュボードレイアウトを生成する.

        Returns:
            Rich Layout オブジェクト。
        """

    def render_issue_detail(
        self,
        data: DashboardData,
        issue_number: int,
    ) -> Layout:
        """特定 Issue の詳細ダッシュボードレイアウトを生成する.

        全体サマリー + フェーズ遷移タイムライン + コスト内訳 + エラー詳細。

        Returns:
            Rich Layout オブジェクト。
        """

    def _build_summary_panel(self, data: DashboardData) -> Panel:
        """全体サマリーパネルを生成."""

    def _build_issues_table(self, data: DashboardData) -> Table:
        """Issue 一覧テーブルを生成."""

    def _build_progress_bar(
        self,
        issue_type: str,
        current_phase: str,
    ) -> str:
        """プログレスバー文字列を生成.

        Type 未判定の場合は不定表示を返す。
        """

    def _build_error_table(self, data: DashboardData) -> Table:
        """エラー統計テーブルを生成."""

    def _build_timeline(self, issue_data: IssueDashboardData) -> Panel:
        """フェーズ遷移タイムラインパネルを生成."""

    def _build_cost_breakdown_table(self, issue_data: IssueDashboardData) -> Table:
        """フェーズ別コスト内訳テーブルを生成."""
```

## 10. メインループ設計

```python
async def _run_dashboard(
    issue_number: int | None,
    refresh_sec: int,
    no_live: bool,
    config_path: str,
) -> None:
    """ダッシュボードのメインループ.

    1. EventLogger を初期化（読み取り専用）
    2. DashboardAggregator でイベントを集計
    3. DashboardRenderer で UI をレンダリング
    4. Rich Live で自動更新（no_live=True の場合は1回表示して終了）
    """
    settings = load_config(config_path)
    log_dir = Path(settings.workspace_dir).expanduser() / "logs"
    logger = EventLogger(log_dir)
    aggregator = DashboardAggregator()
    renderer = DashboardRenderer(Console())

    if no_live:
        # スナップショット表示
        events = await asyncio.to_thread(logger.read_events, issue_number)
        data = aggregator.aggregate(events)
        if issue_number is not None:
            layout = renderer.render_issue_detail(data, issue_number)
        else:
            layout = renderer.render_overview(data)
        renderer.console.print(layout)
        return

    # Rich Live 自動更新
    with Live(console=renderer.console, refresh_per_second=1) as live:
        while True:
            events = await asyncio.to_thread(logger.read_events, issue_number)
            data = aggregator.aggregate(events)
            if issue_number is not None:
                layout = renderer.render_issue_detail(data, issue_number)
            else:
                layout = renderer.render_overview(data)
            live.update(layout)
            await asyncio.sleep(refresh_sec)
```

## 11. 変更ファイル一覧

| ファイル | 変更種別 | 変更内容 |
|---------|---------|---------|
| `src/ai_agent_orchestrator/models.py` | 修正 | `PhaseTransitionRecord`, `ErrorStats`, `IssueDashboardData`, `DashboardData` の追加 |
| `src/ai_agent_orchestrator/event_logger.py` | 修正 | `read_events()`, `_read_single_issue_events()`, `_read_all_events()` メソッドの追加 |
| `src/ai_agent_orchestrator/commands/dashboard.py` | **新規** | `dashboard_command`, `DashboardAggregator`, `DashboardRenderer`, `_run_dashboard` |
| `src/ai_agent_orchestrator/commands/__init__.py` | 修正 | `dashboard_command` のインポートとエクスポート追加 |
| `src/ai_agent_orchestrator/cli.py` | 修正 | `app.command("dashboard")(dashboard_command)` 追加 |
| `tests/unit/test_dashboard.py` | **新規** | ダッシュボード機能のユニットテスト |

## 12. テスト計画

### 12.1 `EventLogger.read_events()` のテスト

```python
class TestEventLoggerRead:
    """EventLogger の読み取り API テスト."""

    async def test_read_events_single_issue(self, tmp_path: Path) -> None:
        """特定 Issue のイベント読み取り."""

    async def test_read_events_all_issues(self, tmp_path: Path) -> None:
        """全 Issue のイベント読み取り."""

    async def test_read_events_empty(self, tmp_path: Path) -> None:
        """ログが存在しない場合は空リストを返す."""

    async def test_read_events_partial_line(self, tmp_path: Path) -> None:
        """不正な JSON 行をスキップする."""
```

### 12.2 `DashboardAggregator` のテスト

```python
class TestDashboardAggregator:
    """イベント集計ロジックのテスト."""

    def test_aggregate_single_issue(self) -> None:
        """単一 Issue の集計."""

    def test_aggregate_multiple_issues(self) -> None:
        """複数 Issue の集計."""

    def test_aggregate_cost_by_phase(self) -> None:
        """フェーズ別コストの集計."""

    def test_aggregate_error_by_category(self) -> None:
        """ErrorCategory 別エラー集計."""

    def test_aggregate_suspend_count(self) -> None:
        """サスペンドカウントの集計."""

    def test_get_progress_bug(self) -> None:
        """Bug ワークフローの進捗計算."""

    def test_get_progress_feature_m(self) -> None:
        """Feature-M ワークフローの進捗計算."""

    def test_get_progress_unknown_type(self) -> None:
        """Type 未判定の進捗は (0, 0)."""

    def test_aggregate_empty_events(self) -> None:
        """空のイベントリストの集計."""
```

### 12.3 `DashboardRenderer` のテスト

```python
class TestDashboardRenderer:
    """UI レンダリングのテスト."""

    def test_render_overview(self) -> None:
        """全 Issue 横断表示のレンダリング（例外なく完了すること）."""

    def test_render_issue_detail(self) -> None:
        """Issue 詳細表示のレンダリング（例外なく完了すること）."""

    def test_progress_bar_determined(self) -> None:
        """Type 判定済みのプログレスバー表示."""

    def test_progress_bar_undetermined(self) -> None:
        """Type 未判定の不定プログレスバー表示."""

    def test_build_timeline(self) -> None:
        """フェーズ遷移タイムラインの生成."""
```

### 12.4 CLI コマンドのテスト

```python
class TestDashboardCommand:
    """CLI コマンドの統合テスト."""

    def test_dashboard_no_live(self, tmp_path: Path) -> None:
        """--no-live オプションでスナップショット表示."""

    def test_dashboard_with_issue(self, tmp_path: Path) -> None:
        """--issue オプションで特定 Issue の詳細表示."""
```

## 13. 依存関係

### 追加パッケージ: なし

`Rich` は既に `pyproject.toml` に含まれている（Typer の依存として）。
`Rich.live`, `Rich.layout`, `Rich.table`, `Rich.panel`, `Rich.progress` は全て Rich ライブラリに含まれる。

### 既存モジュールへの影響

- `EventLogger`: 読み取りメソッドの追加のみ。既存の `track()`, `write_phase_log()` には変更なし
- `models.py`: 新規 dataclass の追加のみ。既存の定義には変更なし
- `cli.py`: 1行追加（`app.command("dashboard")`）
- `commands/__init__.py`: インポート・エクスポートの追加のみ

## 14. 非機能要件

### パフォーマンス

- events.jsonl の読み取りは `asyncio.to_thread()` でメインループをブロックしない
- 大量のイベント（1万行超）でも 5 秒のリフレッシュ間隔内に集計完了すること
- ファイル全体を毎回読み直す設計（シンプルさ優先。将来的にはシーク位置のキャッシュも検討）

### エラーハンドリング

- ログディレクトリが存在しない → 空のダッシュボードを表示
- events.jsonl が壊れている行がある → その行をスキップ
- `--issue` で指定した Issue のログが存在しない → メッセージを表示して終了
- 設定ファイルが見つからない → デフォルトパス (`~/.ai-agent-workspaces/logs`) を使用

### 操作性

- `Ctrl+C` で Live ダッシュボードを正常終了
- `--no-live` オプションで CI/スクリプトからも利用可能
- `--refresh` オプションでリフレッシュ間隔をカスタマイズ可能
