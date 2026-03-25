# 実装仕様書: Phase Executors

**対象モジュール**: `src/ai_agent_orchestrator/phases/`

---

## 1. 概要

各フェーズのビジネスロジックを実行するモジュール群。
`PhaseExecutor` 基底クラスと、フェーズごとの具象クラスで構成する。
各フェーズは「プロンプト構築 → ClaudeAgentRunner 実行 → 結果処理 → 状態更新」のパイプラインに従う。

---

## 2. ディレクトリ構成

```
src/ai_agent_orchestrator/phases/
    __init__.py
    base.py                 # PhaseExecutor 基底クラス
    dispatcher.py           # PhaseDispatcher (タスク振り分け)
    type_detection.py       # タイプ自動判定
    hearing.py              # 要件ヒアリング
    analysis.py             # Bug 分析 (Bug 専用)
    plan_brief.py           # 簡易方針作成 (Feature-S 専用)
    design.py               # 設計書作成 (Feature-M)
    design_revise.py        # 設計書修正 (Feature-M)
    planning.py             # 実装計画作成 (Feature-M)
    implement.py            # コード実装 (共通)
    fix.py                  # Bug 修正 (Bug 専用)
    ci_fix.py               # CI 自動修正 (共通)
    impl_revise.py          # 実装修正 (共通)
    split_proposal.py       # 分割提案 (Feature-L)
    split_execute.py        # 分割実行 (Feature-L)
    done.py                 # 完了処理 (共通)
```

---

## 3. 共通 Imports

```python
from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
    from ai_agent_orchestrator.config.settings import RepositoryConfig
    from ai_agent_orchestrator.context.engine import ContextEngine
    from ai_agent_orchestrator.github.client import GitHubClient
    from ai_agent_orchestrator.models import AgentResult, PhaseContext
    from ai_agent_orchestrator.orchestrator.state_machine import (
        Phase,
        StateMachineManager,
    )
    from ai_agent_orchestrator.orchestrator.task_queue import TaskRequest
    from ai_agent_orchestrator.orchestrator.workspace_manager import WorkspaceManager
    from ai_agent_orchestrator.protocols import Notifier, Tracker

logger = logging.getLogger(__name__)
```

---

## 4. PhaseExecutor 基底クラス

**ファイル**: `src/ai_agent_orchestrator/phases/base.py`

```python
class PhaseExecutor(ABC):
    """フェーズ実行の基底クラス。

    全フェーズ共通の依存オブジェクト保持と、
    「プロンプト構築 → エージェント実行 → 結果処理」のテンプレートメソッドを提供する。
    """

    def __init__(
        self,
        runner: ClaudeAgentRunner,
        github: GitHubClient,
        notifier: Notifier,
        tracker: Tracker,
        workspace: WorkspaceManager,
        context_engine: ContextEngine,
        state_machine: StateMachineManager,
    ) -> None:
        """共通依存オブジェクトを注入する。

        Args:
            runner: Claude Agent SDK ランナー
            github: GitHub API クライアント
            notifier: 通知送信 (Slack 等)
            tracker: イベントログ追跡
            workspace: ワークスペース (worktree) 管理
            context_engine: コンテキスト構築エンジン
            state_machine: ステートマシンマネージャ
        """
        self._runner = runner
        self._github = github
        self._notifier = notifier
        self._tracker = tracker
        self._workspace = workspace
        self._context = context_engine
        self._sm = state_machine

    async def execute(self, request: TaskRequest) -> None:
        """フェーズを実行する (テンプレートメソッド)。

        1. build_prompt() でプロンプトを構築
        2. run_agent() でエージェントを実行
        3. process_result() で結果を処理・状態更新

        エラー時は handle_error() で SUSPENDED 遷移 + 通知。
        タイムアウト時は handle_timeout() でセッション中断 + 通知。

        Args:
            request: タスクリクエスト
        """
        try:
            await self._tracker.track(
                "phase_start",
                issue_number=request.issue_number,
                phase=str(request.phase),
            )

            prompt = await self.build_prompt(request)
            result = await self.run_agent(request, prompt)
            await self.process_result(request, result)

            await self._tracker.track(
                "phase_end",
                issue_number=request.issue_number,
                phase=str(request.phase),
                data={"cost_usd": result.cost_usd, "duration_sec": result.duration_sec},
            )
        except asyncio.TimeoutError:
            await self._handle_timeout(request)
        except Exception as e:
            await self._handle_error(request, e)

    @abstractmethod
    async def build_prompt(self, request: TaskRequest) -> str:
        """フェーズ固有のプロンプトを構築する。

        ContextEngine から取得したコンテキストと、Issue 情報を組み合わせる。

        Args:
            request: タスクリクエスト

        Returns:
            エージェントに渡すプロンプト文字列
        """
        ...

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """エージェントを実行する。

        サブクラスでオーバーライド可能 (セッション継続が必要な場合等)。

        Args:
            request: タスクリクエスト
            prompt: 構築されたプロンプト

        Returns:
            エージェント実行結果
        """
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number,
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase=str(request.phase),
        )

    @abstractmethod
    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """実行結果を処理する。

        Issue コメント投稿、PR 作成確認、状態遷移等のフェーズ固有ロジック。

        Args:
            request: タスクリクエスト
            result: エージェント実行結果
        """
        ...

    async def _handle_timeout(self, request: TaskRequest) -> None:
        """タイムアウト処理: セッション中断 + SUSPENDED 遷移 + 通知。"""
        state = self._sm.get_state(request.issue_number)
        if state and state.session_id:
            await self._runner.interrupt(state.session_id)

        await self._sm.transition(request.issue_number, "suspended")
        await self._notifier.notify(
            f"Issue #{request.issue_number} がタイムアウトしました "
            f"(phase: {request.phase})",
            level="error",
            metadata={"issue": request.issue_number, "phase": str(request.phase)},
        )

    async def _handle_error(self, request: TaskRequest, error: Exception) -> None:
        """エラー処理: SUSPENDED 遷移 + Issue コメント + 通知。"""
        await self._sm.transition(request.issue_number, "suspended")
        await self._github.post_comment(
            request.repo,
            request.issue_number,
            f"エラーが発生しました: {error}",
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} でエラー: {error} "
            f"(phase: {request.phase})",
            level="error",
            metadata={"issue": request.issue_number, "phase": str(request.phase)},
        )

    def _extract_pr_number(self, output: str) -> int | None:
        """エージェント出力テキストから PR 番号を抽出する。"""
        match = re.search(r"#(\d+)", output)
        return int(match.group(1)) if match else None
```

---

## 5. PhaseDispatcher

**ファイル**: `src/ai_agent_orchestrator/phases/dispatcher.py`

```python
class PhaseDispatcher:
    """タスクリクエストを適切な PhaseExecutor に振り分ける。

    TaskQueue の worker_loop から呼び出される execute() メソッドを提供し、
    request.phase に応じた具象 PhaseExecutor を選択して実行する。
    """

    def __init__(
        self,
        executors: dict[str, PhaseExecutor],
    ) -> None:
        """PhaseDispatcher を初期化する。

        Args:
            executors: フェーズ名 → PhaseExecutor のマッピング。
                       例: {"type_detection": TypeDetectionExecutor(...), ...}
        """
        self._executors = executors

    async def execute(self, request: TaskRequest) -> None:
        """タスクリクエストに応じたフェーズを実行する。

        Args:
            request: タスクリクエスト

        Raises:
            KeyError: 未登録のフェーズ
        """
        phase_key = str(request.phase).replace("-", "_")
        executor = self._executors.get(phase_key)
        if executor is None:
            raise KeyError(f"No executor registered for phase: {request.phase}")
        await executor.execute(request)
```

---

## 6. 具象フェーズ実装

### 6.1 TypeDetectionExecutor (タイプ自動判定)

**ファイル**: `src/ai_agent_orchestrator/phases/type_detection.py`

```python
class TypeDetectionExecutor(PhaseExecutor):
    """Issue のタイプを自動判定するフェーズ。

    Issue 内容を AI が分析し、bug / feature-s / feature-m / feature-l のいずれかに分類する。
    判定結果を Issue コメントとラベルで通知し、タイプ別の次フェーズへ遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        """タイプ判定用プロンプトを構築する。"""
        issue = await self._github.get_issue(request.repo, request.issue_number)
        context = await self._context.build_context(
            str(await self._workspace.create_worktree(request.repo, request.issue_number)),
            issue.body or "",
            "type_detection",
        )

        return f"""以下のIssueのタイプを判定してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## コンテキスト
{context}

## 判定基準
- bug: エラー・不具合・動かない・壊れた等のキーワード、バグ修正の依頼
- feature-s: 1-3ファイル変更で済む小規模な機能追加・変更
- feature-m: 4-10ファイルの変更が必要な中規模の機能追加
- feature-l: 10ファイル以上の変更が見込まれる大規模な機能追加・刷新

## 出力形式 (JSON)
{{"type": "bug|feature-s|feature-m|feature-l", "reason": "判定理由"}}
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """判定結果を処理: ラベル付与 → コメント投稿 → 次フェーズ遷移。"""
        import json

        try:
            parsed = json.loads(result.output.strip())
            issue_type = parsed["type"]
            reason = parsed["reason"]
        except (json.JSONDecodeError, KeyError):
            issue_type = self._fallback_detection(result.output)
            reason = "AI出力のパースに失敗、フォールバック判定"

        # ステートマシンにタイプを設定
        self._sm.set_issue_type(request.issue_number, issue_type)

        # GitHub ラベル付与
        await self._github.add_label(
            request.repo, request.issue_number, f"type:{issue_type}"
        )

        # Issue コメント投稿
        await self._github.post_comment(
            request.repo,
            request.issue_number,
            f"このIssueを **type:{issue_type}** として処理します。\n\n"
            f"**判定理由:** {reason}\n\n"
            f"異なる場合はコメントでお知らせください。",
        )

        # タイプ別次フェーズへ遷移
        next_phase_map = {
            "bug": "analysis",
            "feature-s": "hearing",
            "feature-m": "hearing",
            "feature-l": "hearing",
        }
        next_phase = next_phase_map[issue_type]
        await self._sm.transition(request.issue_number, next_phase)

    def _fallback_detection(self, output: str) -> str:
        """AI 出力パース失敗時のフォールバック判定。"""
        output_lower = output.lower()
        if any(kw in output_lower for kw in ["bug", "バグ", "エラー", "修正"]):
            return "bug"
        if any(kw in output_lower for kw in ["feature-l", "大規模", "分割"]):
            return "feature-l"
        if any(kw in output_lower for kw in ["feature-m", "中規模", "設計"]):
            return "feature-m"
        return "feature-s"
```

### 6.2 HearingExecutor (要件ヒアリング)

**ファイル**: `src/ai_agent_orchestrator/phases/hearing.py`

```python
class HearingExecutor(PhaseExecutor):
    """要件ヒアリングフェーズ。

    Issue 内容を分析し、不明点があれば質問を投稿する。
    情報が十分であれば、タイプに応じた次フェーズへ自動遷移する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="design",
        )
        context = await self._context.build_context(str(worktree), issue.body or "", "hearing")

        # 過去のコメント (ヒアリング回答) も含める
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)
        hearing_log = "\n".join(
            f"[{c.user.login}]: {c.body}" for c in comments
        ) if comments else "(なし)"

        return f"""以下のIssueについて要件ヒアリングを行ってください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## これまでのやりとり
{hearing_log}

## コンテキスト
{context}

## 指示
1. Issueの内容を分析し、実装に必要な情報が十分か判断
2. 不明点がある場合は具体的な質問をリストアップ
3. 情報が十分な場合は "READY" と出力
4. Issueが大きすぎて分割すべき場合は "NEEDS_SPLIT" と出力

出力形式:
- 質問がある場合: Issueコメントとして投稿する質問テキスト
- 準備完了: "READY"
- 分割推奨: "NEEDS_SPLIT"
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """ヒアリング結果を処理: 質問投稿 or 次フェーズ遷移。"""
        # セッションID を記録
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        issue_type = self._sm.get_issue_type(request.issue_number)

        if "READY" in result.output:
            # タイプ別の次フェーズへ遷移
            next_phase_map = {
                "bug": "analysis",
                "feature-s": "plan-brief",
                "feature-m": "design",
                "feature-l": "split-proposal",
            }
            next_phase = next_phase_map.get(issue_type, "design")
            await self._sm.transition(request.issue_number, next_phase)
        elif "NEEDS_SPLIT" in result.output:
            await self._sm.transition(request.issue_number, "split-proposal")
        else:
            # 質問を Issue コメントとして投稿
            await self._github.post_comment(
                request.repo, request.issue_number, result.output,
            )
            await self._notifier.notify(
                f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
                metadata={
                    "repo": f"{request.repo.owner}/{request.repo.repo}",
                    "issue": request.issue_number,
                },
            )
```

### 6.3 AnalysisExecutor (Bug 分析)

**ファイル**: `src/ai_agent_orchestrator/phases/analysis.py`

```python
class AnalysisExecutor(PhaseExecutor):
    """Bug 分析フェーズ。

    Issue 内容からバグの原因を特定し、修正方針をコメントとして投稿する。
    方針に対する 👍 リアクションで承認を待つ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(str(worktree), issue.body or "", "analysis")

        feedback = request.extra.get("feedback", "")
        feedback_section = f"\n## 前回の方針に対する指摘\n{feedback}" if feedback else ""

        return f"""以下のバグIssueを分析し、修正方針を作成してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}
{feedback_section}

## コンテキスト
{context}

## 出力形式 (Markdownテキスト)
以下の形式で修正方針を出力してください:

🔍 **修正方針 (AI分析)**

**原因:** (具体的なファイルパスと行番号)
**発生条件:** (再現条件)
**修正内容:**
| ファイル | 修正内容 |
|---------|---------|
| `path/to/file` | 修正の説明 |

**影響範囲:** (影響を受けるコンポーネント)
**テスト方針:**
- [ ] 再現テスト
- [ ] リグレッションテスト

👍 で承認 / コメントで指摘をお願いします
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        """分析結果を Issue コメント投稿 → PLAN_REVIEW 遷移。"""
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._github.post_comment(
            request.repo, request.issue_number, result.output,
        )
        await self._sm.transition(request.issue_number, "plan-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正方針を投稿しました。👍 で承認をお願いします",
            metadata={"issue": request.issue_number},
        )
```

### 6.4 PlanBriefExecutor (簡易方針作成 - Feature-S)

**ファイル**: `src/ai_agent_orchestrator/phases/plan_brief.py`

```python
class PlanBriefExecutor(PhaseExecutor):
    """Feature-S 簡易方針作成フェーズ。

    変更内容とテスト方針を Issue コメントで共有し、👍 リアクションで承認を待つ。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(str(worktree), issue.body or "", "plan_brief")
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)
        hearing_log = "\n".join(f"[{c.user.login}]: {c.body}" for c in comments) if comments else ""

        feedback = request.extra.get("feedback", "")
        feedback_section = f"\n## 前回の方針に対する指摘\n{feedback}" if feedback else ""

        return f"""以下のIssueの簡易実装方針を作成してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## ヒアリング記録
{hearing_log}
{feedback_section}

## コンテキスト
{context}

## 出力形式 (Markdownテキスト)
📋 **実装方針 (AI提案)**

**変更内容:**
- `path/to/file`: 変更の説明

**テスト方針:**
- [ ] 正常系テスト
- [ ] 異常系テスト

👍 で承認 / コメントで指摘をお願いします
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._github.post_comment(request.repo, request.issue_number, result.output)
        await self._sm.transition(request.issue_number, "plan-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装方針を投稿しました。👍 で承認をお願いします",
            metadata={"issue": request.issue_number},
        )
```

### 6.5 DesignExecutor (設計書作成 - Feature-M)

**ファイル**: `src/ai_agent_orchestrator/phases/design.py`

```python
class DesignExecutor(PhaseExecutor):
    """Feature-M 設計書作成フェーズ。

    設計書を docs/designs/issue-XX.md に作成し、設計 PR を作成する。
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="design",
        )
        context = await self._context.build_context(str(worktree), issue.body or "", "design")
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)
        hearing_log = "\n".join(f"[{c.user.login}]: {c.body}" for c in comments) if comments else ""

        return f"""以下のIssueの設計書を作成してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## ヒアリング記録
{hearing_log}

## コンテキスト
{context}

## 指示
1. docs/designs/issue-{request.issue_number}.md に設計書を作成
2. git commit して Push
3. PRを作成 (タイトル: "[設計書] Issue #{request.issue_number} {{issue_title}}")
4. PRのURLを出力
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.design_pr_number = pr_number
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "design-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計PRを作成しました。レビューをお願いします",
            metadata={"issue": request.issue_number, "pr": pr_number},
        )
```

### 6.6 DesignReviseExecutor (設計修正 - Feature-M)

**ファイル**: `src/ai_agent_orchestrator/phases/design_revise.py`

```python
class DesignReviseExecutor(PhaseExecutor):
    """設計書のレビュー指摘対応フェーズ (セッション継続)。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        comments = request.extra.get("comments", "")
        return f"以下のレビュー指摘に対応してください:\n{comments}"

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """セッション継続で実行する。"""
        state = self._sm.get_state(request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="design",
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="design_revise",
            resume_session_id=state.session_id if state else None,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "design-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計書を修正しました",
            metadata={"issue": request.issue_number},
        )
```

### 6.7 PlanningExecutor (実装計画作成 - Feature-M)

**ファイル**: `src/ai_agent_orchestrator/phases/planning.py`

```python
class PlanningExecutor(PhaseExecutor):
    """実装計画作成フェーズ。ファイル変更順序と依存関係を整理する。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature",
        )
        context = await self._context.build_context(str(worktree), issue.body or "", "planning")

        return f"""設計書に基づき、実装計画を作成してください。

## Issue #{request.issue_number}: {issue.title}

## コンテキスト
{context}

## 指示
1. 設計書を読み込む
2. 変更するファイルの一覧と順序を決定
3. 各ファイルの変更内容を具体的に記述
4. 依存関係の順序 (先に変更すべきファイル) を明記
5. テスト方針を決定
6. docs/designs/issue-{request.issue_number}-plan.md に実装計画を保存
7. git commit して Push
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "implement")
```

### 6.8 ImplementExecutor (コード実装 - 共通)

**ファイル**: `src/ai_agent_orchestrator/phases/implement.py`

```python
class ImplementExecutor(PhaseExecutor):
    """コード実装フェーズ。実装 + テスト + PR 作成。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature",
        )
        context = await self._context.build_context(str(worktree), issue.body or "", "implement")

        return f"""実装計画に基づいてコードを実装してください。

## Issue #{request.issue_number}: {issue.title}

## コンテキスト
{context}

## 指示
1. 実装計画の順序に従ってコードを実装
2. テストコードも作成
3. テスト・lint・ビルドを実行して確認
4. git commit して Push
5. PRを作成 (タイトル: "feat: Issue #{request.issue_number} {{短い説明}}")
6. PR descriptionに変更概要を含める
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PRを作成しました",
            metadata={"issue": request.issue_number, "pr": pr_number},
        )
```

### 6.9 FixExecutor (Bug 修正 - Bug 専用)

**ファイル**: `src/ai_agent_orchestrator/phases/fix.py`

```python
class FixExecutor(PhaseExecutor):
    """Bug 修正フェーズ。承認された方針に基づいて修正 + テスト + PR 作成。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(str(worktree), issue.body or "", "fix")

        # 方針コメントを取得
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)
        plan_comment = ""
        for c in reversed(comments):
            if c.user and c.user.type == "Bot" and "修正方針" in c.body:
                plan_comment = c.body
                break

        return f"""承認された修正方針に基づいてバグを修正してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## 承認された修正方針
{plan_comment}

## コンテキスト
{context}

## 指示
1. 修正方針に従ってコードを修正
2. 再現テスト・リグレッションテストを作成
3. テスト・lint を実行して確認
4. git commit して Push
5. PRを作成 (タイトル: "fix: Issue #{request.issue_number} {{短い説明}}")
6. PR descriptionに修正方針を再掲
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        pr_number = self._extract_pr_number(result.output)
        state = self._sm.get_state(request.issue_number)
        if state:
            state.pr_number = pr_number
            state.session_id = result.session_id

        # git push は実行済み（ClaudeAgentRunner内で）
        # 遷移は行わない。CI結果をPollerが検知して IMPL_REVIEW or CI_FIX に遷移する
        await self._tracker.track({
            "event": "fix_complete",
            "issue": request.issue_number,
            "note": "CI結果待ち",
        })
        await self._notifier.notify(
            f"Issue #{request.issue_number} の修正PRを作成しました。CI結果待ちです",
            metadata={"issue": request.issue_number, "pr": pr_number},
        )
```

### 6.10 CiFixExecutor (CI 自動修正 - 共通)

**ファイル**: `src/ai_agent_orchestrator/phases/ci_fix.py`

```python
class CiFixExecutor(PhaseExecutor):
    """CI 失敗自動修正フェーズ (最大 3 回)。

    CI_FIX 完了後のフロー:
    1. CiFixExecutor がコード修正 + git push
    2. CI が自動実行される（GitHub Actions等）
    3. Poller が CI 結果を検知
    4. CI_PASSED → EventRouter が IMPL_REVIEW に遷移
    5. CI_FAILED → EventRouter が CI_FIX に再遷移（リトライカウント確認）
    """

    async def build_prompt(self, request: TaskRequest) -> str:
        ci_logs = request.extra.get("ci_logs", "")
        retry_count = request.extra.get("retry_count", 1)

        return f"""CIが失敗しました ({retry_count}/3回目)。修正してください。

## CI失敗ログ
{ci_logs}

## 指示
1. CI失敗ログを分析して原因を特定
2. コードを修正
3. テスト・lint・ビルドをローカルで再実行して確認
4. git commit して Push
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.increment_ci_retry(request.issue_number)
        # CI 結果は次回ポーリングで検知
```

### 6.11 ImplReviseExecutor (実装修正 - 共通)

**ファイル**: `src/ai_agent_orchestrator/phases/impl_revise.py`

```python
class ImplReviseExecutor(PhaseExecutor):
    """実装のレビュー指摘対応フェーズ (セッション継続)。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        comments = request.extra.get("comments", "")
        return f"以下のレビュー指摘に対応してください:\n{comments}"

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        state = self._sm.get_state(request.issue_number)
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature",
        )
        return await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="impl_revise",
            resume_session_id=state.session_id if state else None,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装を修正しました",
            metadata={"issue": request.issue_number},
        )
```

### 6.12 SplitProposalExecutor (分割提案 - Feature-L)

**ファイル**: `src/ai_agent_orchestrator/phases/split_proposal.py`

```python
class SplitProposalExecutor(PhaseExecutor):
    """Feature-L 分割提案フェーズ。大規模 Issue を複数の子 Issue に分割する提案を作成。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
        context = await self._context.build_context(str(worktree), issue.body or "", "split_proposal")
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)
        hearing_log = "\n".join(f"[{c.user.login}]: {c.body}" for c in comments) if comments else ""

        return f"""以下の大規模Issueを複数の子Issueに分割する提案を作成してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## ヒアリング記録
{hearing_log}

## コンテキスト
{context}

## 指示
1. 機能を論理的に分割可能なサブタスクに分解
2. 各サブタスクの依存関係を明記
3. 各サブタスクのタイプ (feature-s / feature-m) を判定
4. 実装順序を決定

## 出力形式 (Markdownテキスト)
📦 **Issue分割提案**

| # | タイトル | タイプ | 依存先 | 概要 |
|---|---------|--------|-------|------|
| 1 | ... | feature-m | なし | ... |
| 2 | ... | feature-s | #1 | ... |

👍 で承認 / コメントで修正指示をお願いします
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)
        if state:
            state.session_id = result.session_id

        await self._github.post_comment(
            request.repo, request.issue_number, result.output,
        )
        # 承認待ち (SPLIT_PROPOSAL フェーズのまま)
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割を提案しました。判断をお願いします",
            metadata={"issue": request.issue_number},
        )
```

### 6.13 SplitExecuteExecutor (分割実行 - Feature-L)

**ファイル**: `src/ai_agent_orchestrator/phases/split_execute.py`

```python
class SplitExecuteExecutor(PhaseExecutor):
    """Feature-L 分割実行フェーズ。承認された分割案に基づいて子 Issue を作成。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        issue = await self._github.get_issue(request.repo, request.issue_number)
        comments = await self._github.get_issue_comments(request.repo, request.issue_number)

        # 分割提案コメントを取得
        split_proposal = ""
        for c in reversed(comments):
            if c.user and c.user.type == "Bot" and "Issue分割提案" in c.body:
                split_proposal = c.body
                break

        return f"""承認された分割案に基づいて子Issueを作成してください。

## 親Issue #{request.issue_number}: {issue.title}
{issue.body}

## 承認された分割案
{split_proposal}

## 指示
1. 分割案の各サブタスクについて子Issueを作成
2. 各子Issueに以下のラベルを付与:
   - ai-agent
   - type:{{feature-s|feature-m}}
   - depends-on:#XX (依存先がある場合)
3. 親Issueに分割完了コメントを投稿
4. 作成した子Issue番号のリストを出力
"""

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        # 分割完了 → DONE 遷移
        await self._github.post_comment(
            request.repo,
            request.issue_number,
            f"分割が完了しました。子Issueが作成されています。\n\n{result.output}",
        )
        await self._sm.transition(request.issue_number, "done")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の分割が完了しました",
            metadata={"issue": request.issue_number},
        )
```

### 6.14 DoneExecutor (完了処理 - 共通)

**ファイル**: `src/ai_agent_orchestrator/phases/done.py`

```python
class DoneExecutor(PhaseExecutor):
    """完了フェーズ。PR マージ + Issue クローズ + worktree 削除。"""

    async def build_prompt(self, request: TaskRequest) -> str:
        return ""  # エージェント実行不要

    async def run_agent(self, request: TaskRequest, prompt: str) -> AgentResult:
        """エージェント実行は不要。ダミーの AgentResult を返す。"""
        from ai_agent_orchestrator.models import AgentResult
        return AgentResult(
            session_id="", output="", tool_uses=[], cost_usd=0.0, duration_sec=0.0,
        )

    async def process_result(self, request: TaskRequest, result: AgentResult) -> None:
        state = self._sm.get_state(request.issue_number)

        # PR マージ
        if state and state.pr_number:
            await self._github.merge_pr(request.repo, state.pr_number)

        # Issue クローズ
        await self._github.close_issue(request.repo, request.issue_number)

        # worktree 削除
        await self._workspace.remove_worktree(request.repo, request.issue_number)

        await self._notifier.notify(
            f"Issue #{request.issue_number} 完了しました",
            metadata={"issue": request.issue_number},
        )
```

---

## 7. テストケース

**テストファイル**: `tests/unit/phases/test_*.py`

### 7.1 共通フィクスチャ

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

from ai_agent_orchestrator.models import AgentResult


@pytest.fixture
def mock_runner():
    runner = AsyncMock()
    runner.run.return_value = AgentResult(
        session_id="sess-001",
        output="test output",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=30.0,
    )
    return runner


@pytest.fixture
def mock_github():
    gh = AsyncMock()
    issue = MagicMock()
    issue.title = "テストIssue"
    issue.body = "テスト本文"
    issue.number = 1
    gh.get_issue.return_value = issue
    gh.get_issue_comments.return_value = []
    return gh


@pytest.fixture
def mock_notifier():
    return AsyncMock()


@pytest.fixture
def mock_tracker():
    return AsyncMock()


@pytest.fixture
def mock_workspace():
    ws = AsyncMock()
    ws.create_worktree.return_value = "/tmp/worktree/issue-1"
    return ws


@pytest.fixture
def mock_context():
    ctx = AsyncMock()
    ctx.build_context.return_value = "## リポジトリ構造\n(mock context)"
    return ctx


@pytest.fixture
def mock_sm():
    sm = AsyncMock()
    sm.get_state.return_value = MagicMock(
        issue_number=1, session_id=None, pr_number=None, design_pr_number=None,
    )
    sm.get_issue_type.return_value = "feature-m"
    return sm


def _make_request(phase="hearing", issue_number=1, extra=None):
    repo = MagicMock()
    repo.owner = "org"
    repo.repo = "app"
    req = MagicMock()
    req.issue_number = issue_number
    req.repo = repo
    req.phase = phase
    req.extra = extra or {}
    return req
```

### 7.2 TypeDetectionExecutor テスト

```python
class TestTypeDetectionExecutor:

    @pytest.mark.asyncio
    async def test_detects_bug_type(self, mock_runner, mock_github, mock_notifier,
                                     mock_tracker, mock_workspace, mock_context, mock_sm):
        """Bug タイプが正しく判定されラベルが付与される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output='{"type": "bug", "reason": "エラーキーワードあり"}',
            tool_uses=[], cost_usd=0.1, duration_sec=5.0,
        )
        from ai_agent_orchestrator.phases.type_detection import TypeDetectionExecutor
        executor = TypeDetectionExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="type-detection")
        await executor.execute(request)

        mock_sm.set_issue_type.assert_called_with(1, "bug")
        mock_github.add_label.assert_called_once()
        mock_sm.transition.assert_called_with(1, "analysis")
```

### 7.3 HearingExecutor テスト

```python
class TestHearingExecutor:

    @pytest.mark.asyncio
    async def test_posts_question_when_not_ready(self, mock_runner, mock_github,
                                                   mock_notifier, mock_tracker,
                                                   mock_workspace, mock_context, mock_sm):
        """情報不足時に質問がコメント投稿される。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output="確認したいのですが、認証方式はOAuth2ですか？",
            tool_uses=[], cost_usd=0.3, duration_sec=10.0,
        )
        from ai_agent_orchestrator.phases.hearing import HearingExecutor
        executor = HearingExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_github.post_comment.assert_called_once()
        mock_notifier.notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_transitions_to_design_when_ready(self, mock_runner, mock_github,
                                                      mock_notifier, mock_tracker,
                                                      mock_workspace, mock_context, mock_sm):
        """情報十分時に DESIGN へ遷移する (Feature-M)。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output="READY",
            tool_uses=[], cost_usd=0.2, duration_sec=8.0,
        )
        mock_sm.get_issue_type.return_value = "feature-m"
        from ai_agent_orchestrator.phases.hearing import HearingExecutor
        executor = HearingExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "design")
```

### 7.4 AnalysisExecutor テスト

```python
class TestAnalysisExecutor:

    @pytest.mark.asyncio
    async def test_posts_plan_and_transitions_to_plan_review(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """修正方針がコメント投稿され PLAN_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output="🔍 **修正方針**\n原因: null check漏れ",
            tool_uses=[], cost_usd=0.5, duration_sec=20.0,
        )
        from ai_agent_orchestrator.phases.analysis import AnalysisExecutor
        executor = AnalysisExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="analysis")
        await executor.execute(request)

        mock_github.post_comment.assert_called_once()
        mock_sm.transition.assert_called_with(1, "plan-review")
```

### 7.5 ImplementExecutor テスト

```python
class TestImplementExecutor:

    @pytest.mark.asyncio
    async def test_creates_pr_and_transitions_to_impl_review(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """PR が作成され IMPL_REVIEW に遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output="PR #42 を作成しました",
            tool_uses=[], cost_usd=3.0, duration_sec=120.0,
        )
        from ai_agent_orchestrator.phases.implement import ImplementExecutor
        executor = ImplementExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="implement")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "impl-review")
        # PR 番号が state に記録される
        state = mock_sm.get_state(1)
        assert state.pr_number == 42
```

### 7.6 CiFixExecutor テスト

```python
class TestCiFixExecutor:

    @pytest.mark.asyncio
    async def test_increments_retry_count(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """CI 修正後にリトライカウンタがインクリメントされる。"""
        from ai_agent_orchestrator.phases.ci_fix import CiFixExecutor
        executor = CiFixExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="ci-fix", extra={"ci_logs": "Error", "retry_count": 2})
        await executor.execute(request)

        mock_sm.increment_ci_retry.assert_called_with(1)
```

### 7.7 DesignReviseExecutor テスト

```python
class TestDesignReviseExecutor:

    @pytest.mark.asyncio
    async def test_uses_resume_session(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """セッション継続で実行される。"""
        mock_sm.get_state.return_value = MagicMock(session_id="prev-session")
        from ai_agent_orchestrator.phases.design_revise import DesignReviseExecutor
        executor = DesignReviseExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="design-revise", extra={"comments": "要修正"})
        await executor.execute(request)

        mock_runner.run.assert_called_once()
        call_kwargs = mock_runner.run.call_args.kwargs
        assert call_kwargs["resume_session_id"] == "prev-session"
```

### 7.8 SplitExecuteExecutor テスト

```python
class TestSplitExecuteExecutor:

    @pytest.mark.asyncio
    async def test_transitions_to_done_after_split(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """分割実行後に DONE へ遷移する。"""
        mock_runner.run.return_value = AgentResult(
            session_id="s1", output="子Issue #10, #11, #12 を作成しました",
            tool_uses=[], cost_usd=0.3, duration_sec=15.0,
        )
        from ai_agent_orchestrator.phases.split_execute import SplitExecuteExecutor
        executor = SplitExecuteExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="split-execute")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "done")
        mock_github.post_comment.assert_called_once()
```

### 7.9 DoneExecutor テスト

```python
class TestDoneExecutor:

    @pytest.mark.asyncio
    async def test_merges_pr_closes_issue_removes_worktree(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """PR マージ、Issue クローズ、worktree 削除が全て実行される。"""
        mock_sm.get_state.return_value = MagicMock(pr_number=42)
        from ai_agent_orchestrator.phases.done import DoneExecutor
        executor = DoneExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="done")
        await executor.execute(request)

        mock_github.merge_pr.assert_called_once()
        mock_github.close_issue.assert_called_once()
        mock_workspace.remove_worktree.assert_called_once()
```

### 7.10 エラーハンドリングテスト

```python
class TestPhaseExecutorErrorHandling:

    @pytest.mark.asyncio
    async def test_timeout_transitions_to_suspended(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """タイムアウト時に SUSPENDED へ遷移し通知される。"""
        mock_runner.run.side_effect = asyncio.TimeoutError()
        from ai_agent_orchestrator.phases.hearing import HearingExecutor
        executor = HearingExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="hearing")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "suspended")
        mock_notifier.notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_generic_error_transitions_to_suspended(
        self, mock_runner, mock_github, mock_notifier, mock_tracker,
        mock_workspace, mock_context, mock_sm,
    ):
        """一般エラー時に SUSPENDED へ遷移し Issue コメント + 通知される。"""
        mock_runner.run.side_effect = RuntimeError("Unexpected error")
        from ai_agent_orchestrator.phases.implement import ImplementExecutor
        executor = ImplementExecutor(
            mock_runner, mock_github, mock_notifier, mock_tracker,
            mock_workspace, mock_context, mock_sm,
        )
        request = _make_request(phase="implement")
        await executor.execute(request)

        mock_sm.transition.assert_called_with(1, "suspended")
        mock_github.post_comment.assert_called_once()
        mock_notifier.notify.assert_called_once()
```

### 7.11 PhaseDispatcher テスト

```python
class TestPhaseDispatcher:

    @pytest.mark.asyncio
    async def test_dispatches_to_correct_executor(self):
        """phase に対応する executor が呼び出される。"""
        from ai_agent_orchestrator.phases.dispatcher import PhaseDispatcher

        mock_executor = AsyncMock()
        dispatcher = PhaseDispatcher(executors={"hearing": mock_executor})

        request = _make_request(phase="hearing")
        await dispatcher.execute(request)
        mock_executor.execute.assert_called_once_with(request)

    @pytest.mark.asyncio
    async def test_unknown_phase_raises_key_error(self):
        """未登録フェーズは KeyError を発生させる。"""
        from ai_agent_orchestrator.phases.dispatcher import PhaseDispatcher

        dispatcher = PhaseDispatcher(executors={})
        request = _make_request(phase="unknown")

        with pytest.raises(KeyError):
            await dispatcher.execute(request)
```
