# 実装仕様書: `src/ai_agent_orchestrator/models.py`

## 概要

オーケストレーター全体で使用されるデータモデル、Enum定義、フェーズ遷移マップを集約するモジュール。
全データクラスはイミュータブル (`frozen=True`) を原則とし、状態管理用の `IssueState` のみミュータブルとする。

---

## 依存モジュール

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.config.settings import RepositoryConfig
```

外部パッケージ依存: なし（標準ライブラリのみ）

---

## 1. Enum 定義

### 1.1 IssueType

Issueのタスクタイプ。タイプごとに異なるワークフローが適用される。

```python
class IssueType(StrEnum):
    """Issueのタスクタイプ."""

    BUG = "bug"                # バグ修正: ANALYSIS -> FIX -> IMPL_REVIEW
    FEATURE_S = "feature-s"    # 小機能: HEARING -> PLAN_BRIEF -> IMPLEMENT -> IMPL_REVIEW
    FEATURE_M = "feature-m"    # 中機能: HEARING -> DESIGN -> PLANNING -> IMPLEMENT -> IMPL_REVIEW
    FEATURE_L = "feature-l"    # 大機能: HEARING -> SPLIT -> 子Issue(Feature-M x N)
```

| 値 | GitHub Label | 説明 |
|----|-------------|------|
| `BUG` | `type:bug` | バグ修正ワークフロー |
| `FEATURE_S` | `type:feature-s` | 小規模機能（1-3ファイル変更、設計書不要） |
| `FEATURE_M` | `type:feature-m` | 中規模機能（複数ファイル、設計書必要） |
| `FEATURE_L` | `type:feature-l` | 大規模機能（分割が必要） |

---

### 1.2 Phase

Issueのフェーズ（全19値）。タイプによって通過するフェーズが異なる。

```python
class Phase(str, Enum):
    """Issueのフェーズ."""

    # タイプ判定
    TYPE_DETECTION = "type-detection"

    # Bug専用
    ANALYSIS = "analysis"
    FIX = "fix"

    # Feature-S専用
    PLAN_BRIEF = "plan-brief"
    PLAN_REVIEW = "plan-review"

    # Feature-M/L共通
    HEARING = "hearing"
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"
    PLANNING = "planning"

    # Feature-L専用
    SPLIT_PROPOSAL = "split-proposal"
    SPLIT_EXECUTE = "split-execute"

    # 依存待ち
    BLOCKED = "blocked"

    # 共通フェーズ
    IMPLEMENT = "implement"
    CI_FIX = "ci-fix"
    IMPL_REVIEW = "impl-review"
    IMPL_REVISE = "impl-revise"

    # 終了状態
    DONE = "done"
    SUSPENDED = "suspended"
```

**注意**: `str, Enum` を継承する（`StrEnum` ではなく）。値はハイフン区切りの文字列。

**タイプ別フェーズマッピング:**

| フェーズ | Bug | Feature-S | Feature-M | Feature-L |
|---------|-----|-----------|-----------|-----------|
| TYPE_DETECTION | o | o | o | o |
| ANALYSIS | o | - | - | - |
| FIX | o | - | - | - |
| PLAN_BRIEF | - | o | - | - |
| PLAN_REVIEW | - | o | - | - |
| HEARING | - | o | o | o |
| DESIGN | - | - | o | - |
| DESIGN_REVIEW | - | - | o | - |
| DESIGN_REVISE | - | - | o | - |
| PLANNING | - | - | o | - |
| SPLIT_PROPOSAL | - | - | - | o |
| SPLIT_EXECUTE | - | - | - | o |
| BLOCKED | - | - | - | o (子Issue) |
| IMPLEMENT | o | o | o | - |
| CI_FIX | o | o | o | - |
| IMPL_REVIEW | o | o | o | - |
| IMPL_REVISE | o | o | o | - |
| DONE | o | o | o | o |
| SUSPENDED | o | o | o | o |

---

### 1.3 EventType

ポーリングイベントの種別（全12値）。`str, Enum` を使用し、値は文字列で定義する。

```python
class EventType(str, Enum):
    """ポーリングイベント種別."""

    NEW_ISSUE = "new_issue"
    ISSUE_COMMENT = "issue_comment"
    DESIGN_PR_APPROVED = "design_pr_approved"
    DESIGN_PR_COMMENTED = "design_pr_commented"
    IMPL_PR_APPROVED = "impl_pr_approved"
    IMPL_PR_COMMENTED = "impl_pr_commented"
    CI_RESULT = "ci_result"
    PLAN_REACTION_ADDED = "plan_reaction_added"       # 👍承認 (Bug/Feature-S)
    PLAN_COMMENT_ADDED = "plan_comment_added"          # 方針への指摘コメント
    SPLIT_APPROVED = "split_approved"                  # 分割承認 (Feature-L)
    SPLIT_MODIFIED = "split_modified"                  # 分割修正指示
    HEARING_TIMEOUT = "hearing_timeout"
```

---

### 1.4 ErrorCategory

エラー分類の列挙型。

```python
class ErrorCategory(StrEnum):
    """エラー分類."""

    TRANSIENT = "transient"
    AUTH = "auth"
    GIT_CONFLICT = "git_conflict"
    OUTPUT_INVALID = "output_invalid"
    CI_FAILURE = "ci_failure"
```

---

### 1.5 ApprovalMethod

方針承認の方法。タイプによって承認方法が異なる。

```python
class ApprovalMethod(StrEnum):
    """方針承認方法."""

    REACTION = "reaction"        # Bug/Feature-S: Issueコメントへの👍リアクション
    PR_APPROVE = "pr-approve"    # Feature-M: 設計PRのapprove
```

---

## 2. Dataclass 定義

### 2.1 AgentResult

エージェント実行結果。イミュータブル。

```python
@dataclass(frozen=True)
class AgentResult:
    """エージェント実行結果."""

    session_id: str
    output: str
    tool_uses: list[dict]
    cost_usd: float
    duration_sec: float
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `session_id` | `str` | (必須) | セッション識別子。resume に使用 |
| `output` | `str` | (必須) | エージェントの出力テキスト |
| `tool_uses` | `list[dict]` | (必須) | 使用ツールのリスト |
| `cost_usd` | `float` | (必須) | 実行コスト (USD) |
| `duration_sec` | `float` | (必須) | 実行時間 (秒) |

---

### 2.2 PhaseContext

フェーズ実行に必要なコンテキスト。イミュータブル。

```python
@dataclass(frozen=True)
class PhaseContext:
    """フェーズ実行に必要なコンテキスト."""

    issue_number: int
    repo_owner: str
    repo_name: str
    phase: str
    worktree_path: str
    resume_session_id: str | None = None
    extra: dict | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `repo_owner` | `str` | (必須) | リポジトリオーナー |
| `repo_name` | `str` | (必須) | リポジトリ名 |
| `phase` | `str` | (必須) | フェーズ名 |
| `worktree_path` | `str` | (必須) | worktreeのファイルシステムパス |
| `resume_session_id` | `str \| None` | `None` | 継続するセッションID |
| `extra` | `dict \| None` | `None` | フェーズ固有の追加データ |

---

### 2.3 TaskRequest

タスク実行リクエスト。`asyncio.PriorityQueue` での比較のために `__lt__` を実装する。
**ミュータブル**（`frozen` なし）。

```python
@dataclass
class TaskRequest:
    """タスク実行リクエスト."""

    issue_number: int
    repo: str
    phase: Phase
    priority: int = 5

    def __lt__(self, other: "TaskRequest") -> bool:
        """PriorityQueue での優先度比較。値が小さいほど優先。"""
        return self.priority < other.priority
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `repo` | `str` | (必須) | `"owner/repo"` 形式のリポジトリキー |
| `phase` | `Phase` | (必須) | 実行するフェーズ |
| `priority` | `int` | `5` | 優先度。値が小さいほど優先 |

**`__lt__` メソッド**: `self.priority < other.priority` を返す。`asyncio.PriorityQueue` での比較に使用。

---

### 2.4 IssueState

Issue単位の状態管理。**ミュータブル**（`frozen` なし）。フェーズ遷移時にフィールドを更新する。

```python
@dataclass
class IssueState:
    """Issue単位の状態."""

    issue_number: int
    phase: Phase
    issue_type: str = ""           # "bug" | "feature-s" | "feature-m" | "feature-l"
    repo: str = ""                 # "owner/repo" 形式
    session_id: str | None = None
    pr_number: int | None = None
    design_pr_number: int | None = None
    retry_count: int = 0
    created_at: str = ""           # ISO 8601
    updated_at: str = ""           # ISO 8601
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `phase` | `Phase` | (必須) | 現在のフェーズ |
| `issue_type` | `str` | `""` | Issueタイプ (`bug` / `feature-s` / `feature-m` / `feature-l`) |
| `repo` | `str` | `""` | `"owner/repo"` 形式のリポジトリキー |
| `session_id` | `str \| None` | `None` | 最後に実行したセッションID |
| `pr_number` | `int \| None` | `None` | 実装PR番号 |
| `design_pr_number` | `int \| None` | `None` | 設計PR番号 |
| `retry_count` | `int` | `0` | リトライ回数 |
| `created_at` | `str` | `""` | 状態作成日時 (ISO 8601) |
| `updated_at` | `str` | `""` | 最終更新日時 (ISO 8601) |

---

### 2.5 PhaseResult

各フェーズの実行結果。

```python
@dataclass
class PhaseResult:
    """各フェーズの実行結果."""

    phase: str
    cost_usd: float
    duration_sec: int
    output_summary: str
    review_comments: int = 0
    feedback: str | None = None
    resolution: str | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `phase` | `str` | (必須) | フェーズ名 |
| `cost_usd` | `float` | (必須) | フェーズのコスト (USD) |
| `duration_sec` | `int` | (必須) | 実行時間 (秒) |
| `output_summary` | `str` | (必須) | 出力の要約 |
| `review_comments` | `int` | `0` | レビューコメント数 |
| `feedback` | `str \| None` | `None` | レビューからのフィードバック |
| `resolution` | `str \| None` | `None` | フィードバックへの対応内容 |

---

### 2.6 PollEvent

ポーリングで検知されたイベント。イミュータブル。

```python
@dataclass(frozen=True)
class PollEvent:
    """ポーリングで検知されたイベント."""

    type: str
    repo: "RepositoryConfig"
    issue: "Issue | None" = None
    comment: "IssueComment | None" = None
    pr: "PullRequest | None" = None
    error: Exception | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `type` | `str` | (必須) | イベント種別（`EventType` の値に対応） |
| `repo` | `RepositoryConfig` | (必須) | 対象リポジトリ設定 |
| `issue` | `Issue \| None` | `None` | 関連するIssue (githubkit型) |
| `comment` | `IssueComment \| None` | `None` | 関連するコメント (githubkit型) |
| `pr` | `PullRequest \| None` | `None` | 関連するPR (githubkit型) |
| `error` | `Exception \| None` | `None` | エラー情報 |

---

### 2.7 PhaseConfig

フェーズごとのClaude Agent SDK実行設定。

```python
@dataclass
class PhaseConfig:
    """フェーズごとの実行設定."""

    max_budget_usd: float
    timeout_sec: int
    permission_mode: str
    resume: bool = False
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `max_budget_usd` | `float` | (必須) | コスト上限 (USD) |
| `timeout_sec` | `int` | (必須) | タイムアウト (秒) |
| `permission_mode` | `str` | (必須) | 権限モード (`"plan"` / `"acceptEdits"` / `"bypassPermissions"`) |
| `resume` | `bool` | `False` | セッション継続モードか否か |

---

## 3. VALID_TRANSITIONS 辞書

フェーズ遷移の許可マップ。`StateMachine.transition()` で遷移の合法性検証に使用する。

```python
VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    # 共通: 初期
    Phase.TYPE_DETECTION: [Phase.HEARING, Phase.ANALYSIS],

    # Bug ワークフロー
    Phase.ANALYSIS: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.FIX: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],

    # Feature-S ワークフロー
    Phase.PLAN_BRIEF: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.PLAN_REVIEW: [Phase.FIX, Phase.IMPLEMENT, Phase.PLAN_BRIEF, Phase.ANALYSIS],

    # Feature-M ワークフロー
    Phase.HEARING: [Phase.DESIGN, Phase.PLAN_BRIEF, Phase.SPLIT_PROPOSAL, Phase.ANALYSIS, Phase.SUSPENDED],
    Phase.DESIGN: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.DESIGN_REVIEW: [Phase.PLANNING, Phase.DESIGN_REVISE, Phase.SUSPENDED],
    Phase.DESIGN_REVISE: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.PLANNING: [Phase.IMPLEMENT, Phase.SUSPENDED],

    # Feature-L ワークフロー
    Phase.SPLIT_PROPOSAL: [Phase.SPLIT_EXECUTE, Phase.HEARING, Phase.SUSPENDED],
    Phase.SPLIT_EXECUTE: [Phase.DONE, Phase.SUSPENDED],

    # 共通: 実装・レビュー
    Phase.IMPLEMENT: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],
    Phase.CI_FIX: [Phase.IMPL_REVIEW, Phase.CI_FIX, Phase.SUSPENDED],
    Phase.IMPL_REVIEW: [Phase.DONE, Phase.IMPL_REVISE, Phase.SUSPENDED],
    Phase.IMPL_REVISE: [Phase.IMPL_REVIEW, Phase.SUSPENDED],

    # 特殊
    Phase.BLOCKED: [Phase.HEARING, Phase.ANALYSIS, Phase.IMPLEMENT],
    Phase.SUSPENDED: list(Phase),  # どのフェーズにも復帰可能
}
```

**設計意図:**
- `SUSPENDED` からは全フェーズへの遷移を許可（`list(Phase)` で全値を展開）
- `BLOCKED` からはワークフロー開始フェーズへの遷移のみ許可
- 各ワークフロー内では設計書記載のフロー順に限定
- 全ての実行フェーズから `SUSPENDED` への遷移を許可（エラー時のフォールバック）

---

## 4. PHASE_CONFIG 辞書

フェーズごとのClaude Agent SDK実行設定マップ。`ClaudeAgentRunner` で使用する。

```python
PHASE_CONFIG: dict[str, PhaseConfig] = {
    "type_detection": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="plan"),
    "hearing": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "analysis": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "plan_brief": PhaseConfig(max_budget_usd=1.0, timeout_sec=300, permission_mode="plan"),
    "design": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="plan"),
    "design_revise": PhaseConfig(max_budget_usd=2.0, timeout_sec=1200, permission_mode="bypassPermissions", resume=True),
    "planning": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "split_proposal": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    "fix": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "ci_fix": PhaseConfig(max_budget_usd=3.0, timeout_sec=1200, permission_mode="bypassPermissions"),
    "impl_revise": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions", resume=True),
}
```

---

## 5. テストケース

テストファイル: `tests/unit/test_models.py`

### TC-M01: Phase Enum 値の完全性

**目的**: Phase Enum が全19値を持つことを検証する。

```python
def test_phase_has_19_values():
    assert len(Phase) == 19

def test_phase_values():
    expected = {
        "type-detection", "hearing", "analysis", "plan-brief", "plan-review",
        "design", "design-review", "design-revise", "planning",
        "split-proposal", "split-execute", "blocked",
        "implement", "ci-fix", "impl-review", "impl-revise",
        "done", "suspended", "fix",
    }
    assert {p.value for p in Phase} == expected
```

**期待結果**: 全19値が一致する。

---

### TC-M02: EventType Enum 値の完全性

**目的**: EventType Enum が全12値を持つことを検証する。

```python
def test_event_type_has_12_values():
    assert len(EventType) == 12

def test_event_type_values():
    expected = {
        "new_issue", "issue_comment",
        "design_pr_approved", "design_pr_commented",
        "impl_pr_approved", "impl_pr_commented",
        "ci_result",
        "plan_reaction_added", "plan_comment_added",
        "split_approved", "split_modified",
        "hearing_timeout",
    }
    assert {e.value for e in EventType} == expected
```

**期待結果**: 全12値が一致する。

---

### TC-M03: IssueType / ErrorCategory / ApprovalMethod の値検証

**目的**: 各 StrEnum が正しい値を持つことを検証する。

```python
def test_issue_type_values():
    assert IssueType.BUG == "bug"
    assert IssueType.FEATURE_S == "feature-s"
    assert IssueType.FEATURE_M == "feature-m"
    assert IssueType.FEATURE_L == "feature-l"
    assert len(IssueType) == 4

def test_error_category_values():
    assert ErrorCategory.TRANSIENT == "transient"
    assert ErrorCategory.AUTH == "auth"
    assert ErrorCategory.GIT_CONFLICT == "git_conflict"
    assert ErrorCategory.OUTPUT_INVALID == "output_invalid"
    assert ErrorCategory.CI_FAILURE == "ci_failure"
    assert len(ErrorCategory) == 5

def test_approval_method_values():
    assert ApprovalMethod.REACTION == "reaction"
    assert ApprovalMethod.PR_APPROVE == "pr-approve"
    assert len(ApprovalMethod) == 2
```

**期待結果**: 各値が文字列比較で一致する。

---

### TC-M04: TaskRequest の生成と優先度比較

**目的**: `TaskRequest` の `__lt__` メソッドが `PriorityQueue` 用の比較を正しく行うことを検証する。

```python
def test_task_request_creation():
    tr = TaskRequest(issue_number=42, repo="owner/repo", phase=Phase.IMPLEMENT)
    assert tr.issue_number == 42
    assert tr.repo == "owner/repo"
    assert tr.phase == Phase.IMPLEMENT
    assert tr.priority == 5  # デフォルト値

def test_task_request_lt_lower_priority_wins():
    high = TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=1)
    low = TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=10)
    assert high < low
    assert not low < high

def test_task_request_lt_equal_priority():
    a = TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=5)
    b = TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=5)
    assert not a < b
    assert not b < a

def test_task_request_sorting():
    tasks = [
        TaskRequest(issue_number=3, repo="o/r", phase=Phase.IMPLEMENT, priority=10),
        TaskRequest(issue_number=1, repo="o/r", phase=Phase.IMPLEMENT, priority=1),
        TaskRequest(issue_number=2, repo="o/r", phase=Phase.IMPLEMENT, priority=5),
    ]
    sorted_tasks = sorted(tasks)
    assert [t.issue_number for t in sorted_tasks] == [1, 2, 3]
```

**期待結果**: `priority` の小さい順にソートされる。

---

### TC-M05: IssueState の生成と issue_type フィールド

**目的**: `IssueState` の必須・オプションフィールドが正しく初期化されることを検証する。

```python
def test_issue_state_creation_minimal():
    state = IssueState(issue_number=10, phase=Phase.HEARING)
    assert state.issue_number == 10
    assert state.phase == Phase.HEARING
    assert state.issue_type == ""
    assert state.repo == ""
    assert state.session_id is None
    assert state.pr_number is None
    assert state.design_pr_number is None
    assert state.retry_count == 0
    assert state.created_at == ""
    assert state.updated_at == ""

def test_issue_state_with_issue_type():
    state = IssueState(
        issue_number=20,
        phase=Phase.ANALYSIS,
        issue_type="bug",
        repo="owner/repo",
    )
    assert state.issue_type == "bug"
    assert state.repo == "owner/repo"

def test_issue_state_is_mutable():
    state = IssueState(issue_number=1, phase=Phase.HEARING)
    state.phase = Phase.DESIGN
    assert state.phase == Phase.DESIGN
```

**期待結果**: デフォルト値が仕様通りに設定され、フィールドの更新が可能。

---

### TC-M06: VALID_TRANSITIONS の検証

**目的**: 遷移マップの合法性と不正遷移の排除を検証する。

```python
def test_valid_transitions_type_detection():
    """TYPE_DETECTION から HEARING と ANALYSIS への遷移が許可される."""
    assert Phase.HEARING in VALID_TRANSITIONS[Phase.TYPE_DETECTION]
    assert Phase.ANALYSIS in VALID_TRANSITIONS[Phase.TYPE_DETECTION]
    assert Phase.IMPLEMENT not in VALID_TRANSITIONS[Phase.TYPE_DETECTION]

def test_valid_transitions_implement():
    """IMPLEMENT から CI_FIX, IMPL_REVIEW, SUSPENDED への遷移が許可される."""
    allowed = VALID_TRANSITIONS[Phase.IMPLEMENT]
    assert Phase.CI_FIX in allowed
    assert Phase.IMPL_REVIEW in allowed
    assert Phase.SUSPENDED in allowed
    assert Phase.DONE not in allowed  # IMPLEMENT -> DONE は不正

def test_valid_transitions_suspended_allows_all():
    """SUSPENDED からは全フェーズへの遷移が可能."""
    suspended_targets = VALID_TRANSITIONS[Phase.SUSPENDED]
    for phase in Phase:
        assert phase in suspended_targets

def test_valid_transitions_all_active_phases_can_suspend():
    """全ての実行フェーズから SUSPENDED への遷移が可能."""
    for phase, targets in VALID_TRANSITIONS.items():
        if phase not in (Phase.DONE, Phase.BLOCKED, Phase.PLAN_REVIEW):
            assert Phase.SUSPENDED in targets, f"{phase} cannot transition to SUSPENDED"

def test_valid_transitions_blocked():
    """BLOCKED からはワークフロー開始フェーズのみ許可."""
    allowed = VALID_TRANSITIONS[Phase.BLOCKED]
    assert Phase.HEARING in allowed
    assert Phase.ANALYSIS in allowed
    assert Phase.IMPLEMENT in allowed
    assert Phase.SUSPENDED not in allowed
```

**期待結果**: 各遷移ルールが設計書記載の仕様と一致する。

---

### TC-M07: AgentResult / PhaseResult のイミュータブル性

**目的**: `frozen=True` のデータクラスが変更不可であることを検証する。

```python
import pytest
from dataclasses import FrozenInstanceError

def test_agent_result_is_frozen():
    result = AgentResult(
        session_id="sess-1",
        output="done",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=10.0,
    )
    with pytest.raises(FrozenInstanceError):
        result.output = "changed"

def test_phase_result_creation():
    pr = PhaseResult(
        phase="hearing",
        cost_usd=0.3,
        duration_sec=60,
        output_summary="Requirements gathered",
    )
    assert pr.review_comments == 0
    assert pr.feedback is None
    assert pr.resolution is None
```

**期待結果**: `AgentResult` はフィールド変更時に `FrozenInstanceError` が発生する。`PhaseResult` のデフォルト値が正しい。

---

### TC-M08: PhaseConfig と PHASE_CONFIG 辞書の検証

**目的**: `PHASE_CONFIG` の全エントリが正しい型と値を持つことを検証する。

```python
def test_phase_config_creation():
    pc = PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan")
    assert pc.max_budget_usd == 1.0
    assert pc.timeout_sec == 600
    assert pc.permission_mode == "plan"
    assert pc.resume is False

def test_phase_config_with_resume():
    pc = PhaseConfig(max_budget_usd=2.0, timeout_sec=1200, permission_mode="bypassPermissions", resume=True)
    assert pc.resume is True

def test_phase_config_dict_has_all_phases():
    expected_keys = {
        "type_detection", "hearing", "analysis", "plan_brief",
        "design", "design_revise", "planning", "split_proposal",
        "implement", "fix", "ci_fix", "impl_revise",
    }
    assert set(PHASE_CONFIG.keys()) == expected_keys

def test_phase_config_implement_budget():
    assert PHASE_CONFIG["implement"].max_budget_usd == 10.0
    assert PHASE_CONFIG["implement"].timeout_sec == 3600
    assert PHASE_CONFIG["implement"].permission_mode == "bypassPermissions"
```

**期待結果**: 全12フェーズの設定が存在し、値が設計書と一致する。

---

### TC-M09: PollEvent の frozen 検証 + フィールドデフォルト値

**目的**: `PollEvent` がイミュータブルであり、オプションフィールドのデフォルト値が正しいことを検証する。

```python
import pytest
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

def test_poll_event_is_frozen():
    repo_mock = MagicMock()
    event = PollEvent(type="new_issue", repo=repo_mock)
    with pytest.raises(FrozenInstanceError):
        event.type = "changed"

def test_poll_event_defaults():
    repo_mock = MagicMock()
    event = PollEvent(type="new_issue", repo=repo_mock)
    assert event.type == "new_issue"
    assert event.repo is repo_mock
    assert event.issue is None
    assert event.comment is None
    assert event.pr is None
    assert event.error is None
```

**期待結果**: `PollEvent` はフィールド変更時に `FrozenInstanceError` が発生する。オプションフィールドはすべて `None`。

---

### TC-M10: PhaseContext の frozen 検証 + フィールドデフォルト値

**目的**: `PhaseContext` がイミュータブルであり、オプションフィールドのデフォルト値が正しいことを検証する。

```python
import pytest
from dataclasses import FrozenInstanceError

def test_phase_context_is_frozen():
    ctx = PhaseContext(
        issue_number=1,
        repo_owner="owner",
        repo_name="repo",
        phase="hearing",
        worktree_path="/tmp/wt",
    )
    with pytest.raises(FrozenInstanceError):
        ctx.phase = "design"

def test_phase_context_defaults():
    ctx = PhaseContext(
        issue_number=42,
        repo_owner="myorg",
        repo_name="myapp",
        phase="implement",
        worktree_path="/workspace/wt-42",
    )
    assert ctx.issue_number == 42
    assert ctx.repo_owner == "myorg"
    assert ctx.repo_name == "myapp"
    assert ctx.phase == "implement"
    assert ctx.worktree_path == "/workspace/wt-42"
    assert ctx.resume_session_id is None
    assert ctx.extra is None
```

**期待結果**: `PhaseContext` はフィールド変更時に `FrozenInstanceError` が発生する。`resume_session_id` と `extra` のデフォルト値は `None`。

---

## 6. 実装メモ

- `Phase` は `str, Enum` を使用する（`StrEnum` ではない）。設計書の定義に合わせる。APIリファレンスでは `StrEnum` と記載されているが、設計書のコード例を正とする。
- `EventType` も同様に `str, Enum` を使用する。EventType は設計書 (design-python.md) のコード例を正とする。API Reference の EventType (auto() 使用版) とは値が異なるが、文字列ベースの定義を採用する。
- `IssueType`, `ErrorCategory`, `ApprovalMethod` は `StrEnum` を使用する（APIリファレンスの定義に合わせる）。
- `PollEvent` の `repo` フィールドの型は `RepositoryConfig`（config モジュールからインポート）。TYPE_CHECKING ガードで循環インポートを回避する。
- `PHASE_CONFIG` のキーは Phase の value ではなくアンダースコア区切り文字列を使用する（`"ci_fix"` であり `"ci-fix"` ではない）。
