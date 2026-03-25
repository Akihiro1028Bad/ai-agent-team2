# ClaudeAgentRunner 実装仕様書

## 概要

Claude Agent SDK (Python) を使用した `AgentRunner` Protocol の実装。
フェーズごとに予算・タイムアウト・権限モードを自動設定し、ワンショット実行 (`query()`) とマルチターン実行 (`ClaudeSDKClient` + `resume`) の両方をサポートする。

## 対象ファイル

- `src/ai_agent_orchestrator/agents/claude_runner.py`

## 依存パッケージ

> **Note:** 設計書では `claude_agent_sdk` を使用しているが、正しいパッケージ名は `claude_code_sdk`。

```python
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from claude_code_sdk import ClaudeCodeSDKError, ClaudeSDKClient, query
from claude_code_sdk.types import (
    AgentDefinition,
    AssistantMessage,
    HookMatcher,
    Message,
    ResultMessage,
)

from ai_agent_orchestrator.models import AgentResult
from ai_agent_orchestrator.protocols import Tracker

logger = logging.getLogger(__name__)
```

---

## データクラス: `PhaseConfig`

フェーズごとの実行設定を保持するデータクラス。

```python
@dataclass
class PhaseConfig:
    """フェーズごとの実行設定."""

    max_budget_usd: float
    timeout_sec: int
    permission_mode: str  # "plan" | "acceptEdits" | "bypassPermissions"
    resume: bool = False  # True の場合はセッション継続が可能
```

---

## 定数: `PHASE_CONFIG`

12 フェーズの設定を保持する辞書。設計書の「4.2 フェーズごとの設定」に基づく。

```python
PHASE_CONFIG: dict[str, PhaseConfig] = {
    "type_detection": PhaseConfig(
        max_budget_usd=0.3,
        timeout_sec=120,
        permission_mode="plan",
    ),
    "hearing": PhaseConfig(
        max_budget_usd=1.0,
        timeout_sec=600,
        permission_mode="plan",
    ),
    "analysis": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=600,
        permission_mode="plan",
    ),
    "plan_brief": PhaseConfig(
        max_budget_usd=1.0,
        timeout_sec=300,
        permission_mode="plan",
    ),
    "design": PhaseConfig(
        max_budget_usd=3.0,
        timeout_sec=1800,
        permission_mode="plan",
    ),
    "design_revise": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
        resume=True,
    ),
    "planning": PhaseConfig(
        max_budget_usd=1.0,
        timeout_sec=600,
        permission_mode="plan",
    ),
    "split_proposal": PhaseConfig(
        max_budget_usd=2.0,
        timeout_sec=600,
        permission_mode="plan",
    ),
    "implement": PhaseConfig(
        max_budget_usd=10.0,
        timeout_sec=3600,
        permission_mode="bypassPermissions",
    ),
    "fix": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
    ),
    "ci_fix": PhaseConfig(
        max_budget_usd=3.0,
        timeout_sec=1200,
        permission_mode="bypassPermissions",
    ),
    "impl_revise": PhaseConfig(
        max_budget_usd=5.0,
        timeout_sec=1800,
        permission_mode="bypassPermissions",
        resume=True,
    ),
}
```

---

## サブエージェント定義

実装フェーズ (`implement`, `fix`, `ci_fix`, `impl_revise`) で使用するサブエージェント。

```python
CODE_ANALYZER = AgentDefinition(
    name="code-analyzer",
    description="既存コードベースの構造分析とリポマップ生成",
    instructions="リポジトリのファイル構造、主要モジュール、依存関係を分析して要約する。",
)

TEST_WRITER = AgentDefinition(
    name="test-writer",
    description="テストコード作成の専門エージェント",
    instructions="既存テストのパターンに従い、ユニットテストと統合テストを作成する。",
)
```

---

## クラス: `ClaudeAgentRunner`

### 説明

`AgentRunner` Protocol を実装する。Claude Agent SDK の `query()` (ワンショット) と
`ClaudeSDKClient` (マルチターン/セッション継続) を使い分けてエージェントを実行する。

### コンストラクタ

```python
class ClaudeAgentRunner:
    """Claude Agent SDK を使用した AgentRunner 実装."""

    def __init__(self, tracker: Tracker) -> None:
        """ClaudeAgentRunner を初期化する。

        Args:
            tracker: ツール使用ログの記録に使用する Tracker。
        """
        self._tracker = tracker
        self._active_sessions: dict[str, ClaudeSDKClient] = {}
```

### 公開メソッド

#### `run`

```python
async def run(
    self,
    prompt: str,
    *,
    cwd: str,
    phase: str,
    max_budget_usd: float | None = None,
    resume_session_id: str | None = None,
    timeout_sec: int = 600,
) -> AgentResult:
    """AI エージェントを実行し、結果を返す。

    フェーズに応じた設定 (PHASE_CONFIG) を適用し、ワンショットまたはマルチターンで実行する。

    処理フロー:
    1. PHASE_CONFIG からフェーズ設定を取得 (未定義フェーズはデフォルト値を使用)
    2. max_budget_usd が None の場合はフェーズ設定の値を使用
    3. PreToolUse / PostToolUse フックを設定
    4. 実装フェーズ (`implement`, `fix`, `ci_fix`, `impl_revise`) の場合はサブエージェント (code-analyzer, test-writer) を追加
    5. resume_session_id が指定され、かつ _active_sessions に存在する場合:
       → ClaudeSDKClient.send() でセッション継続
    6. それ以外の場合:
       → query() でワンショット実行
    7. asyncio.wait_for() でタイムアウトを適用
    8. 結果を AgentResult に変換して返す

    Args:
        prompt: エージェントに渡すプロンプト。
        cwd: 作業ディレクトリ (worktree パス)。
        phase: 実行フェーズ名。PHASE_CONFIG のキーと一致する必要がある。
        max_budget_usd: コスト上限 (USD)。None の場合はフェーズ設定のデフォルト値。
        resume_session_id: 継続するセッション ID。指定時はマルチターン実行。
        timeout_sec: タイムアウト (秒)。0 の場合はフェーズ設定の値を使用。

    Returns:
        AgentResult: session_id, output, tool_uses, cost_usd, duration_sec を含む。

    Raises:
        asyncio.TimeoutError: タイムアウト時。呼び出し元 (PhaseExecutor) で処理される。
        ClaudeCodeSDKError: SDK レベルのエラー (認証失敗、max_turns 到達等)。
    """
```

#### `interrupt`

```python
async def interrupt(self, session_id: str) -> None:
    """実行中のセッションを安全に中断する。

    _active_sessions から対象のクライアントを検索し、interrupt() を呼び出す。
    セッションが存在しない場合は何もしない。

    Args:
        session_id: 中断するセッション ID。
    """
```

### 内部メソッド

#### `_on_pre_tool_use`

```python
async def _on_pre_tool_use(self, event: Any) -> None:
    """PreToolUse フックコールバック。ツール使用開始をログに記録する。

    Tracker.track() に "tool_use_start" イベントを送信する。
    data には tool 名と tool_input を含む。
    """
```

#### `_on_post_tool_use`

```python
async def _on_post_tool_use(self, event: Any) -> None:
    """PostToolUse フックコールバック。ツール使用完了をログに記録する。

    Tracker.track() に "tool_use_end" イベントを送信する。
    data には tool 名と output_size を含む。
    """
```

---

## セッション管理の設計

### ワンショット実行 (新規セッション)

ヒアリング、設計、実装、CI修正など、1回完結のフェーズで使用する。

```
query() → ResultMessage → AgentResult に変換
```

### `query()` 戻り値のパースロジック

`query()` は非同期イテレータとして `Message` を返す。最終的な `AgentResult` を構築するために、
全メッセージを収集し、テキスト・セッション ID・コストを抽出する。

```python
async def run(self, prompt: str, ...) -> AgentResult:
    messages: list[Message] = []
    async for msg in query(prompt=prompt, options=options):
        messages.append(msg)

    # 最後の AssistantMessage からテキストを抽出
    result_text = ""
    session_id = None
    cost = 0.0
    for msg in messages:
        if hasattr(msg, "content"):
            for block in msg.content:
                if hasattr(block, "text"):
                    result_text += block.text
        if hasattr(msg, "session_id"):
            session_id = msg.session_id
        if hasattr(msg, "cost_usd"):
            cost += msg.cost_usd

    return AgentResult(
        session_id=session_id or "",
        result=result_text,
        cost_usd=cost,
        ...
    )
```

### マルチターン実行 (セッション継続)

設計修正 (`design_revise`) と実装修正 (`impl_revise`) で使用する。
レビュー指摘対応時に、前回のセッションコンテキスト (設計/実装内容) を保持した状態で修正を行う。

```
_active_sessions[session_id] から ClaudeSDKClient を取得
  → client.send(prompt) → ResultMessage → AgentResult に変換
```

### セッションID の流れ

1. `run()` の戻り値 `AgentResult.session_id` を `IssueState.session_id` に保存
2. レビュー対応時に `IssueState.session_id` を `resume_session_id` として `run()` に渡す
3. `run()` 内で `_active_sessions` から対応する `ClaudeSDKClient` を取得して継続

---

## エラーハンドリング

| エラー種別 | 対応 |
|-----------|------|
| `asyncio.TimeoutError` | `run()` から再送出。PhaseExecutor が SUSPENDED 遷移 + Slack 通知を行う |
| `ClaudeCodeSDKError` (max_turns 到達) | `run()` から再送出。PhaseExecutor がエラーハンドリング。検出方法は以下参照 |
| `ClaudeCodeSDKError` (認証失敗) | `run()` から再送出。HealthChecker が検知して通知 |
| `ClaudeCodeSDKError` (その他) | `run()` から再送出。PhaseExecutor が SUSPENDED 遷移 |

### `max_turns` 到達の検出

`query()` が `StopReason.MAX_TURNS` で終了した場合の検出コード:

```python
# query() が StopReason.MAX_TURNS で終了した場合
if any(hasattr(msg, "stop_reason") and msg.stop_reason == "max_turns" for msg in messages):
    raise MaxTurnsExceededError(session_id=session_id)
```

`MaxTurnsExceededError` は `ClaudeCodeSDKError` のサブクラスとして定義し、
PhaseExecutor 側で `max_turns` 到達時の専用ハンドリング (リトライ or SUSPENDED 遷移) を行う。

---

## テストケース

テストファイル: `tests/unit/agents/test_claude_runner.py`

`claude_code_sdk` をモックし、`pytest-asyncio` で非同期テストを実行する。

### テスト用の共通フィクスチャ

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_agent_orchestrator.agents.claude_runner import (
    PHASE_CONFIG,
    ClaudeAgentRunner,
    PhaseConfig,
)
from ai_agent_orchestrator.models import AgentResult


@pytest.fixture
def mock_tracker() -> AsyncMock:
    tracker = AsyncMock()
    tracker.track = AsyncMock()
    return tracker


@pytest.fixture
def runner(mock_tracker: AsyncMock) -> ClaudeAgentRunner:
    return ClaudeAgentRunner(tracker=mock_tracker)


def make_mock_result(
    session_id: str = "sess-001",
    text: str = "output text",
    tool_uses: list | None = None,
    cost_usd: float = 0.5,
    duration_sec: float = 30.0,
) -> MagicMock:
    result = MagicMock()
    result.session_id = session_id
    result.text = text
    result.tool_uses = tool_uses or []
    result.cost_usd = cost_usd
    result.duration_sec = duration_sec
    return result
```

### テストケース一覧

#### TC-CR-01: `run` -- ワンショット実行 (hearing フェーズ)

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_oneshot_hearing(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """hearing フェーズでワンショット実行され、正しい AgentResult が返ることを検証する。"""
    mock_query.return_value = make_mock_result(session_id="sess-hearing-001")

    result = await runner.run(
        prompt="Issue を分析してください",
        cwd="/tmp/worktree/issue-42",
        phase="hearing",
    )

    assert isinstance(result, AgentResult)
    assert result.session_id == "sess-hearing-001"
    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args
    assert call_kwargs.kwargs["max_budget_usd"] == 1.0  # PHASE_CONFIG の値
    assert call_kwargs.kwargs["permission_mode"] == "plan"
```

#### TC-CR-02: `run` -- マルチターン実行 (impl_revise フェーズ)

```python
@pytest.mark.asyncio
async def test_run_multiturn_resume(runner: ClaudeAgentRunner) -> None:
    """resume_session_id 指定時にセッション継続が行われることを検証する。"""
    mock_client = AsyncMock()
    mock_client.send.return_value = make_mock_result(session_id="sess-revise-001")
    runner._active_sessions["sess-impl-001"] = mock_client

    result = await runner.run(
        prompt="レビュー指摘に対応してください",
        cwd="/tmp/worktree/issue-42",
        phase="impl_revise",
        resume_session_id="sess-impl-001",
    )

    assert result.session_id == "sess-revise-001"
    mock_client.send.assert_called_once()
```

#### TC-CR-03: `run` -- タイムアウト発生

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_raises_timeout_error(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """タイムアウト時に asyncio.TimeoutError が送出されることを検証する。"""
    mock_query.side_effect = asyncio.TimeoutError()

    with pytest.raises(asyncio.TimeoutError):
        await runner.run(
            prompt="実装してください",
            cwd="/tmp/worktree/issue-42",
            phase="implement",
            timeout_sec=1,
        )
```

#### TC-CR-04: `run` -- max_budget_usd の明示的指定がフェーズ設定を上書き

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_explicit_budget_overrides_phase_config(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """max_budget_usd を明示的に指定した場合、PHASE_CONFIG の値が上書きされることを検証する。"""
    mock_query.return_value = make_mock_result()

    await runner.run(
        prompt="テスト",
        cwd="/tmp/worktree",
        phase="implement",
        max_budget_usd=20.0,
    )

    call_kwargs = mock_query.call_args
    assert call_kwargs.kwargs["max_budget_usd"] == 20.0  # 明示値が使われる (PHASE_CONFIG は 10.0)
```

#### TC-CR-05: `run` -- 実装フェーズでサブエージェントが追加される

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_adds_subagents_for_implement_phase(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """implement フェーズでサブエージェント (code-analyzer, test-writer) が追加されることを検証する。"""
    mock_query.return_value = make_mock_result()

    await runner.run(
        prompt="実装してください",
        cwd="/tmp/worktree",
        phase="implement",
    )

    call_kwargs = mock_query.call_args
    subagents = call_kwargs.kwargs.get("subagents", [])
    assert len(subagents) == 2
    names = {s.name for s in subagents}
    assert "code-analyzer" in names
    assert "test-writer" in names
```

#### TC-CR-06: `run` -- hearing フェーズではサブエージェントなし

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_no_subagents_for_hearing_phase(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
) -> None:
    """hearing フェーズではサブエージェントが追加されないことを検証する。"""
    mock_query.return_value = make_mock_result()

    await runner.run(
        prompt="ヒアリングしてください",
        cwd="/tmp/worktree",
        phase="hearing",
    )

    call_kwargs = mock_query.call_args
    subagents = call_kwargs.kwargs.get("subagents", [])
    assert len(subagents) == 0
```

#### TC-CR-07: `interrupt` -- アクティブセッションの中断

```python
@pytest.mark.asyncio
async def test_interrupt_stops_active_session(runner: ClaudeAgentRunner) -> None:
    """アクティブなセッションが interrupt() で中断され、辞書から削除されることを検証する。"""
    mock_client = AsyncMock()
    runner._active_sessions["sess-001"] = mock_client

    await runner.interrupt("sess-001")

    mock_client.interrupt.assert_called_once()
    assert "sess-001" not in runner._active_sessions
```

#### TC-CR-08: `interrupt` -- 存在しないセッションは無視

```python
@pytest.mark.asyncio
async def test_interrupt_ignores_unknown_session(runner: ClaudeAgentRunner) -> None:
    """存在しないセッション ID で interrupt() を呼んでも例外が発生しないことを検証する。"""
    await runner.interrupt("nonexistent-session")
    # 例外が発生しなければ OK
```

#### TC-CR-09: PHASE_CONFIG -- 全 12 フェーズの定義確認

```python
def test_phase_config_has_all_phases() -> None:
    """PHASE_CONFIG に全 12 フェーズが定義されていることを検証する。"""
    expected_phases = {
        "type_detection", "hearing", "analysis", "plan_brief",
        "design", "design_revise", "planning", "split_proposal",
        "implement", "fix", "ci_fix", "impl_revise",
    }
    assert set(PHASE_CONFIG.keys()) == expected_phases

    for phase_name, config in PHASE_CONFIG.items():
        assert isinstance(config, PhaseConfig)
        assert config.max_budget_usd > 0
        assert config.timeout_sec > 0
        assert config.permission_mode in ("plan", "acceptEdits", "bypassPermissions")
```

#### TC-CR-10: `run` -- フックコールバックが Tracker に記録を送信

```python
@pytest.mark.asyncio
@patch("ai_agent_orchestrator.agents.claude_runner.query")
async def test_run_hooks_call_tracker(
    mock_query: AsyncMock,
    runner: ClaudeAgentRunner,
    mock_tracker: AsyncMock,
) -> None:
    """PreToolUse/PostToolUse フックが Tracker.track() を呼び出すことを検証する。"""
    mock_query.return_value = make_mock_result()

    await runner.run(prompt="テスト", cwd="/tmp", phase="hearing")

    # フックが設定されていることを確認
    call_kwargs = mock_query.call_args
    hooks = call_kwargs.kwargs.get("hooks", [])
    assert len(hooks) == 2
    assert hooks[0].event == "PreToolUse"
    assert hooks[1].event == "PostToolUse"
```
