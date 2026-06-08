# feature-m 計画フェーズの設計フェーズ統合 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** feature-m ワークフローから PLANNING / PLAN_VALIDATION フェーズを廃止し、DESIGN フェーズで設計＋実装計画を1本の設計書（`issue-N.md`）に作り込み、生成後に構造を自己検証し、設計PR承認後は直接 IMPLEMENT へ進むようにする。

**Architecture:** 状態機械の遷移を `DESIGN_REVIEW → IMPLEMENT` に付け替え、planning 系の State / 遷移 / enum / executor / テンプレートを削除する。構造検証の純粋関数 `validate_plan` は残し、DESIGN フェーズが生成物を自己検証する。IMPLEMENT は統合設計書 `issue-N.md` を読む。

**Tech Stack:** Python 3.13, python-statemachine, pytest (+pytest-asyncio auto mode), mypy strict, ruff。

**実装順序の原則:** 各タスク完了時点でインポートが壊れないよう、参照を先に消し、enum 削除は最後にする。各タスク末尾でコミットする。

参照スペック: `docs/designs/feature-m-plan-into-design.md`

---

### Task 1: イベントルーター — 設計PR承認後の遷移先を IMPLEMENT に変更

**Files:**
- Modify: `src/ai_agent_orchestrator/poller/event_router.py`（`_handle_design_pr_approved`, line 522-552 付近、ルーティング表コメント line 141）
- Test: `tests/unit/test_event_router.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_event_router.py` に追加（既存の `_make_*` ヘルパー / FakeStateMachine を流用、design_pr_approved の既存テストを参照して同パターンで）:

```python
async def test_design_pr_approved_enqueues_implement():
    """設計PR承認時に IMPLEMENT をエンキューする（PLANNING ではない）。"""
    sm = FakeStateMachine()
    tq = FakeTaskQueue()
    # DESIGN_REVIEW 状態の feature-m Issue を登録
    issue_key = ("org/app", 42)
    sm.register(issue_key, Phase.DESIGN_REVIEW, issue_type="feature-m")
    router = EventRouter(state_machine=sm, task_queue=tq)
    event = _make_event(EventType.DESIGN_PR_APPROVED, issue_number=42)

    await router._handle_design_pr_approved(event)

    assert sm.get_phase(issue_key) == Phase.IMPLEMENT
    assert tq.enqueued[-1].phase == Phase.IMPLEMENT.value
```

> 既存の `test_event_router.py` の FakeStateMachine/FakeTaskQueue の実体に合わせてヘルパー名を調整すること。既存の design_pr_approved 関連テスト（PLANNING を期待しているもの）があれば、この変更に合わせて修正する。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/unit/test_event_router.py -k design_pr_approved -v`
Expected: FAIL（現状は PLANNING に遷移するため）

- [ ] **Step 3: 実装を変更**

`event_router.py` の `_handle_design_pr_approved` 内、`Phase.PLANNING` を `Phase.IMPLEMENT` に置換:

```python
        await self._sm.transition(issue_key, Phase.IMPLEMENT)
        await self._tq.enqueue(
            TaskRequest(
                issue_number=event.issue.number,
                repo=event.repo,
                phase=Phase.IMPLEMENT.value,
                priority=Priority.NORMAL,
            )
        )
```

docstring（line 523 付近「PLANNING へ遷移」）と `route()` のルーティング表コメント（line 141 `DESIGN_PR_APPROVED -> PLANNING ...`）も `IMPLEMENT` に更新する。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/unit/test_event_router.py -k design_pr_approved -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_agent_orchestrator/poller/event_router.py tests/unit/test_event_router.py
git commit -m "feat: 設計PR承認後は PLANNING ではなく IMPLEMENT へ遷移"
```

---

### Task 2: 状態機械 — design_review→implement を追加し planning 系遷移を削除

**Files:**
- Modify: `src/ai_agent_orchestrator/orchestrator/state_machine.py`（`TRANSITION_MAP` line 93-99 付近、`IssueWorkflow` 遷移定義 line 196-211 付近）
- Modify: `src/ai_agent_orchestrator/models.py`（`VALID_TRANSITIONS` line 270-273）
- Test: `tests/unit/test_state_machine.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_state_machine.py` に追加:

```python
async def test_design_review_to_implement_transition():
    """feature-m: DESIGN_REVIEW から IMPLEMENT へ遷移できる。"""
    mgr = StateMachineManager(tracker=FakeTracker())
    key = ("org/app", 7)
    mgr.register_issue(issue_number=7, repo="org/app", initial_phase=Phase.DESIGN_REVIEW)
    mgr.set_issue_type(key, "feature-m")

    await mgr.transition(key, Phase.IMPLEMENT)

    assert mgr.get_phase(key) == Phase.IMPLEMENT


async def test_no_planning_phase_in_workflow():
    """PLANNING / PLAN_VALIDATION への遷移は定義されていない。"""
    mgr = StateMachineManager(tracker=FakeTracker())
    key = ("org/app", 8)
    mgr.register_issue(issue_number=8, repo="org/app", initial_phase=Phase.DESIGN_REVIEW)
    mgr.set_issue_type(key, "feature-m")
    with pytest.raises(InvalidTransitionError):
        await mgr.transition(key, Phase.PLANNING)
```

> `StateMachineManager` のコンストラクタ引数・`FakeTracker` は既存テストの記述に合わせること。`InvalidTransitionError` は `ai_agent_orchestrator.orchestrator.state_machine` からインポート。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/unit/test_state_machine.py -k "design_review_to_implement or no_planning" -v`
Expected: FAIL（design_review→implement 未定義、planning 遷移はまだ存在）

- [ ] **Step 3: 実装を変更**

`state_machine.py` の `TRANSITION_MAP`（Feature-M workflow セクション）:
- 追加: `(Phase.DESIGN_REVIEW, Phase.IMPLEMENT): "design_review_to_implement",`
- 削除: `(Phase.DESIGN_REVIEW, Phase.PLANNING): "design_review_to_planning",`
- 削除: `(Phase.PLANNING, Phase.IMPLEMENT): "planning_to_implement",`
- 削除: `(Phase.PLANNING, Phase.SUSPENDED): "planning_to_suspended",`

`state_machine.py` の `IssueWorkflow`（Feature-M workflow セクション）:
- 追加: `design_review_to_implement = design_review.to(implement)`
- 削除: `design_review_to_planning = design_review.to(planning)`
- 削除: `planning_to_implement = planning.to(implement)`
- 削除: `planning_to_suspended = planning.to(suspended)`
- 削除: `planning = State("Planning")`（State 定義行）

`models.py` の `VALID_TRANSITIONS`:
- 変更: `Phase.DESIGN_REVIEW: [Phase.PLANNING, Phase.DESIGN_REVISE, Phase.SUSPENDED],`
  → `Phase.DESIGN_REVIEW: [Phase.IMPLEMENT, Phase.DESIGN_REVISE, Phase.SUSPENDED],`
- 削除: `Phase.PLANNING: [Phase.PLAN_VALIDATION, Phase.SUSPENDED],`
- 削除: `Phase.PLAN_VALIDATION: [Phase.IMPLEMENT, Phase.PLANNING, Phase.SUSPENDED],`

> この時点では `Phase.PLANNING` / `Phase.PLAN_VALIDATION` enum 値は残す（Task 7 で削除）。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/unit/test_state_machine.py -v`
Expected: PASS（既存の planning 遷移テストがあれば Step 1 で削除/修正済みであること）

- [ ] **Step 5: コミット**

```bash
git add src/ai_agent_orchestrator/orchestrator/state_machine.py src/ai_agent_orchestrator/models.py tests/unit/test_state_machine.py
git commit -m "feat: 状態機械を design_review→implement に付け替え、planning 系遷移を削除"
```

---

### Task 3: コンテキストエンジン — IMPLEMENT が統合設計書 issue-N.md を読む

**Files:**
- Modify: `src/ai_agent_orchestrator/context/engine.py`（`read_impl_plan`, line 188-213）
- Test: `tests/unit/test_context_engine.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
async def test_read_impl_plan_reads_merged_design_doc(tmp_path):
    """read_impl_plan は統合設計書 issue-N.md を読む。"""
    designs = tmp_path / "docs" / "designs"
    designs.mkdir(parents=True)
    (designs / "issue-42.md").write_text("## サブタスク\n### subtask-1: x\n", encoding="utf-8")
    engine = ContextEngine(...)  # 既存テストのコンストラクタに合わせる
    text = await engine.read_impl_plan(str(tmp_path), issue_number=42)
    assert text is not None
    assert "## サブタスク" in text
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/unit/test_context_engine.py -k merged_design -v`
Expected: FAIL（現状は issue-42-plan.md を探すため None）

- [ ] **Step 3: 実装を変更**

`engine.py` の `read_impl_plan` の候補リストを統合設計書優先に変更:

```python
        candidates: list[Path] = []
        if issue_number is not None:
            candidates.extend(
                [
                    docs_dir / "designs" / f"issue-{issue_number}.md",
                    docs_dir / "designs" / f"issue-{issue_number}-plan.md",  # 後方互換
                    docs_dir / f"impl-plan-issue-{issue_number}.md",
                ]
            )
        candidates.append(docs_dir / "impl-plan.md")
```

docstring の「`issue-{N}-plan.md` も検索対象」を「統合設計書 `issue-{N}.md` を優先」に更新。

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/unit/test_context_engine.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_agent_orchestrator/context/engine.py tests/unit/test_context_engine.py
git commit -m "feat: IMPLEMENT が読む計画を統合設計書 issue-N.md に変更"
```

---

### Task 4: 検証関数を design から再利用可能にする（PlanValidationExecutor から関数を分離維持）

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/plan_validation.py`（`PlanValidationExecutor` クラスは Task 7 で削除予定。`validate_plan` 純粋関数とヘルパーは残す）
- Test: `tests/unit/test_plan_validation.py`（既存の validate_plan テストを維持）

- [ ] **Step 1: validate_plan の既存テストが通ることを確認**

Run: `uv run pytest tests/unit/test_plan_validation.py -k validate_plan -v`
Expected: PASS（純粋関数は無変更。クラスを使うテストがあれば Task 7 で対応）

- [ ] **Step 2: 確認のみ（変更なし）**

`validate_plan(plan_text, worktree_path) -> list[str]` をそのまま design から呼ぶ。このタスクは「関数が独立して使えること」の確認のみ。コミット不要。

---

### Task 5: prompt_enhancer — design にテスト要件を追加

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/prompt_enhancer.py`（ENHANCER マップ line 79）
- Test: `tests/unit/test_prompt_enhancer.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_design_enhancer_includes_test_requirements():
    """design フェーズのプロンプトにテスト要件が含まれる。"""
    out = enhance_prompt("base", "design")
    assert "テスト" in out  # _TEST_REQUIREMENTS の代表語に合わせる
```

> `_TEST_REQUIREMENTS` の実テキストを確認し、確実に含まれる語でアサートすること。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/unit/test_prompt_enhancer.py -k design_enhancer_includes_test -v`
Expected: FAIL

- [ ] **Step 3: 実装を変更**

`prompt_enhancer.py` の ENHANCER マップ:

```python
    "design": [_DESIGN_TEST_STRATEGY, _DESIGN_SECURITY, _CODING_STANDARDS, _TEST_REQUIREMENTS],
```

- [ ] **Step 4: テストを実行して成功を確認**

Run: `uv run pytest tests/unit/test_prompt_enhancer.py -v`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/ai_agent_orchestrator/phases/prompt_enhancer.py tests/unit/test_prompt_enhancer.py
git commit -m "feat: design プロンプトにテスト要件を追加"
```

---

### Task 6: 設計テンプレートにサブタスク計画を統合

**Files:**
- Modify: `docs/templates/02_design.md`（サブタスク構造を追記）
- Delete: `docs/templates/04_planning.md`（Task 7 で削除）

- [ ] **Step 1: 02_design.md に「## サブタスク」セクション仕様を追記**

`02_design.md` の末尾に、`04_planning.md` 由来の以下を追記する（design.py のプロンプトでも明示するが、テンプレートにも記載して一貫させる）:

````markdown
## 実装計画（設計書に必須）

設計書には実装計画として以下の `## サブタスク` セクションを必ず含めること。
このセクションは実装フェーズが自動的に読み取るため、フォーマットを正確に守ること。

```markdown
## サブタスク

### subtask-1: <タイトル>
- files: [`path/to/a.py`, `path/to/b.py`]
- depends_on: []
- description: このサブタスクで行う作業の説明

### subtask-2: <タイトル>
- files: [`path/to/c.py`, `path/to/d.py`]
- depends_on: [1]
- description: このサブタスクで行う作業の説明
```

### サブタスク分割の原則
- 1サブタスクに含めるファイルは 2〜4ファイルを目安にする
- 依存する型・インターフェースを先のサブタスクで定義する
- テストファイルを必ずいずれかのサブタスクに含める
- `depends_on` には依存するサブタスクの番号（整数）を列挙する（連番・循環なし）
````

- [ ] **Step 2: 確認**

Run: `grep -c "## サブタスク" docs/templates/02_design.md`
Expected: 1 以上

- [ ] **Step 3: コミット**

```bash
git add docs/templates/02_design.md
git commit -m "docs: 設計テンプレートにサブタスク実装計画を統合"
```

---

### Task 7: 設計フェーズに計画生成指示と自己検証ループを実装

**Files:**
- Modify: `src/ai_agent_orchestrator/phases/design.py`（`build_prompt` と `process_result`）
- Test: `tests/unit/test_phases.py`（design 用テスト群）

- [ ] **Step 1: 失敗するテストを書く（検証OK経路）**

```python
async def test_design_process_result_creates_pr_when_plan_valid(tmp_path, ...):
    """設計書が構造検証OKなら PR 作成し design-review へ遷移する。"""
    # issue-42.md に有効なサブタスク構造を含むworktreeを用意
    # design.process_result を実行
    # → replace_phase_label("phase:design-review"), transition("design-review") が呼ばれる
    ...
    assert sm.get_phase(key) == Phase.DESIGN_REVIEW
```

```python
async def test_design_process_result_regenerates_when_plan_invalid(...):
    """設計書がサブタスク欠如など検証NGなら再生成を試みる（上限内）。"""
    # issue-42.md に「## サブタスク」が無い設計書を用意
    # _runner.run をスパイし、再生成が呼ばれることを確認
    # 上限到達後は警告コメント付きで design-review へ進む
    ...
```

> 既存 `tests/unit/test_phases.py` の design テストの fixture（FakeRunner/FakeWorkspace/FakeGitHub/FakeStateMachine）に合わせて記述する。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `uv run pytest tests/unit/test_phases.py -k "design_process_result" -v`
Expected: FAIL

- [ ] **Step 3: 実装 — build_prompt にサブタスク計画指示を追加**

`design.py` の `build_prompt` の `raw` 指示部に、計画生成を追記（既存の「設計書のみ作成」制約は維持しつつ、設計書内にサブタスク計画を含めるよう変更）:

```python
        raw = (
            f"以下のIssueの設計書を作成してください。設計書には実装計画"
            f"（## サブタスク セクション）まで含めてください。\n\n"
            f"## Issue #{request.issue_number}: {issue.title}\n"
            f"{getattr(issue, 'body', '') or ''}\n\n"
            f"## ヒアリング記録\n{hearing_log}\n\n"
            f"## コンテキスト\n{context}\n\n"
            f"## 指示\n"
            f"1. docs/designs/issue-{request.issue_number}.md に設計書を作成\n"
            f"   設計内容に加え、末尾に `## サブタスク` セクションを含めること:\n"
            f"   - 各サブタスク `### subtask-N:` に files / depends_on / description\n"
            f"   - サブタスク番号は連番、依存は循環なし、テストファイルを必ず含める\n"
            f"2. git commit して Push (コミットメッセージは日本語で)\n"
            f"3. PRを作成 (タイトル・本文は日本語で、Closes #{request.issue_number} を含める)\n"
            f"4. PRのURLを出力\n\n"
            f"## 重要な制約\n"
            f"- **設計書 (`docs/designs/` 配下の `.md` ファイル) のみ**を作成してください\n"
            f"- ソースコード・テストコードの作成は禁止です（実装は後続の implement フェーズ）\n"
        )
        return enhance_prompt(raw, "design")
```

- [ ] **Step 4: 実装 — process_result に自己検証ループを追加**

`design.py` 冒頭に定数とインポート追加:

```python
from pathlib import Path
from ai_agent_orchestrator.phases.plan_validation import validate_plan

_MAX_DESIGN_REVALIDATE = 2
```

`process_result` の `_recover_uncommitted_work` の後、`_ensure_pr_created` の前に検証ループを挿入:

```python
        await self._recover_uncommitted_work(request, branch_prefix="feature")
        await self._warn_if_source_files_added(request)

        # 構造自己検証ループ: NG なら再生成（上限到達で警告付き続行）
        await self._revalidate_design(request)
        # 以降は既存の PR 作成・design-review 遷移
        pr_number = await self._ensure_pr_created(...)
        ...
```

ヘルパー `_revalidate_design` を追加:

```python
    async def _revalidate_design(self, request: TaskRequest) -> None:
        """生成された設計書の ## サブタスク構造を検証し、NG なら再生成する。"""
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature"
        )
        design_path = (
            Path(str(worktree)) / "docs" / "designs" / f"issue-{request.issue_number}.md"
        )
        for attempt in range(_MAX_DESIGN_REVALIDATE):
            errors = self._validate_design_doc(design_path, str(worktree))
            if not errors:
                return
            logger.info(
                "Issue #%d: 設計書の計画検証NG (%d/%d) → 再生成",
                request.issue_number, attempt + 1, _MAX_DESIGN_REVALIDATE,
            )
            fix_prompt = (
                f"docs/designs/issue-{request.issue_number}.md の ## サブタスク"
                f" セクションに以下の問題があります。修正して commit/push してください:\n"
                + "\n".join(f"- {e}" for e in errors)
            )
            await self._runner.run(fix_prompt, cwd=str(worktree))
            await self._recover_uncommitted_work(request, branch_prefix="feature")
        # 上限到達: 警告コメントを残して続行
        remaining = self._validate_design_doc(design_path, str(worktree))
        if remaining:
            client = await self._get_client(request.repo)
            await client.create_comment(
                request.repo, request.issue_number,
                "⚠️ 設計書の実装計画に検証警告がありますが、上限到達のため続行します。\n\n"
                + "\n".join(f"- {e}" for e in remaining),
            )

    @staticmethod
    def _validate_design_doc(design_path: Path, worktree: str) -> list[str]:
        if not design_path.exists():
            return ["設計書 issue-N.md が見つかりません"]
        return validate_plan(design_path.read_text(encoding="utf-8"), worktree)
```

> `self._runner.run(prompt, cwd=...)` の引数は base.py の `run_agent`（line 432 `self._runner.run(...)`）の実シグネチャに合わせて調整すること。セッション継続が必要なら `session_id` を渡す。

- [ ] **Step 5: テストを実行して成功を確認**

Run: `uv run pytest tests/unit/test_phases.py -k "design" -v`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add src/ai_agent_orchestrator/phases/design.py tests/unit/test_phases.py
git commit -m "feat: 設計フェーズで実装計画を生成し構造を自己検証する"
```

---

### Task 8: 旧コードの完全削除（planning / plan_validation）

**Files:**
- Delete: `src/ai_agent_orchestrator/phases/planning.py`
- Modify: `src/ai_agent_orchestrator/phases/plan_validation.py`（`PlanValidationExecutor` クラス削除、`validate_plan` 等の純粋関数は残す。ファイル名は `validate_plan.py` 等にリネームしてもよい）
- Modify: `src/ai_agent_orchestrator/phases/__init__.py`（`PlanningExecutor` / `PlanValidationExecutor` のエクスポート削除）
- Modify: `src/ai_agent_orchestrator/orchestrator/orchestrator.py`（import と executor 登録 `"planning"` / `"plan-validation"` 削除、line 298/321 付近）
- Delete: `docs/templates/04_planning.md`
- Modify: `src/ai_agent_orchestrator/models.py`（`Phase.PLANNING` / `Phase.PLAN_VALIDATION` enum 削除、line 79-80）
- Test: `tests/unit/`（planning / plan_validation を参照する既存テストの削除・修正）

- [ ] **Step 1: 参照箇所を洗い出す**

Run: `grep -rn "PLANNING\|PlanningExecutor\|PLAN_VALIDATION\|PlanValidationExecutor\|planning\.py\|plan-validation" src/ tests/`
Expected: 一覧を確認し、以下 Step で順に潰す。

- [ ] **Step 2: orchestrator / __init__ から登録・エクスポートを削除**

`orchestrator.py`: import の `PlanningExecutor` 行を削除、`"planning": PlanningExecutor(...)` 行を削除、`"plan-validation"` 登録があれば削除。
`phases/__init__.py`: `PlanningExecutor`, `PlanValidationExecutor` のエクスポートを削除。

- [ ] **Step 3: ファイル削除・クラス削除**

```bash
git rm src/ai_agent_orchestrator/phases/planning.py docs/templates/04_planning.md
```
`plan_validation.py` から `PlanValidationExecutor` クラスを削除し、`validate_plan` / `_detect_cycle` / 正規表現定数のみ残す。

- [ ] **Step 4: enum 削除**

`models.py` の `PLANNING = "planning"` と `PLAN_VALIDATION = "plan-validation"` を削除。

- [ ] **Step 5: 参照テストを削除・修正**

planning フェーズ・plan_validation フェーズクラスをテストしていた既存テストを削除/修正。`validate_plan` 純粋関数のテストは残す。

- [ ] **Step 6: 静的チェックと全体テスト**

Run:
```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/unit/ -v
```
Expected: すべてパス（PLANNING / PLAN_VALIDATION への未解決参照が無いこと）

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "refactor: PLANNING / PLAN_VALIDATION フェーズを完全削除"
```

---

### Task 9: 統合確認と後片付け

**Files:** （変更なし、確認のみ）

- [ ] **Step 1: 全テスト・型・lint**

Run:
```bash
uv run pytest tests/unit/ -v
uv run mypy src/
uv run ruff check src/ tests/
```
Expected: すべてパス。

- [ ] **Step 2: 永続化 state の移行確認**

Run: `grep -rn "Phase(" src/ai_agent_orchestrator/orchestrator/state_persistence.py src/ai_agent_orchestrator/orchestrator/state_machine.py`
ロード時に未知フェーズ（`"planning"`/`"plan-validation"`）が `Phase(...)` で `ValueError` になる箇所がないか確認。あれば、ロード時に未知フェーズを `SUSPENDED` へフォールバックする処理を追加（既存の `contextlib.suppress(ValueError)` パターンを踏襲）。テスト追加。

- [ ] **Step 3: テスト用 Issue #127 のクリーンアップ**

`Akihiro1028Bad/ai-agent-team2-test` の #127（SUSPENDED）をクローズ、または `phase:*` ラベルを除去して再投入可能にする。コード変更ではないため手動 or `gh` で実施。

- [ ] **Step 4: 最終コミット（必要なら）**

```bash
git add -A
git commit -m "test: state 移行フォールバックを追加し全体を緑化"
```

---

## 自己レビュー結果

- **スペック網羅**: §3.1→Task5-7, §3.2→Task4/7, §3.3→Task2, §3.4→Task1, §3.5→Task3, §3.6→Task8, §4テスト→各Task, §5移行→Task9。全項目にタスクあり。
- **プレースホルダ**: 検証ループの `self._runner.run` シグネチャと各テストの Fake 名は「実コードに合わせる」旨を明記（実装時に確定）。
- **型整合**: `validate_plan(text, worktree) -> list[str]` を Task4/7 で一貫使用。`_validate_design_doc` / `_revalidate_design` の戻り値・引数を Task7 内で一貫定義。
