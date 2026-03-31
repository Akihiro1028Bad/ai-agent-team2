# Hearing Wait Phase Design

## Problem

hearing フェーズで質問投稿後、ユーザーが回答を書いている途中でも AI が再度 hearing を実行し、質問を畳み掛けてしまう。

### 根本原因

1. `HearingExecutor` が質問投稿後もフェーズを `hearing` のまま維持する
2. `hearing` は `active_phases` に含まれるため、起動時の再エンキューや自動エンキューの対象になる
3. ポーラーが Bot 自身のコメント投稿をきっかけに hearing を再トリガーする経路がある

## Solution

`hearing-wait` フェーズを新設し、質問投稿後は「回答待ち」状態に遷移させる。

### State Transitions

```
hearing -> hearing-wait     # 質問投稿後 (HearingExecutor.process_result)
hearing-wait -> hearing     # ユーザー回答検知 (EventRouter._handle_hearing_reply)
hearing-wait -> suspended   # タイムアウト (EventRouter._handle_hearing_timeout)
```

`hearing-wait` は `active_phases` に含めない。`plan-review` と同じ設計パターン。

## Changes

### 1. models.py - Phase enum

`HEARING_WAIT = "hearing-wait"` を追加。

### 2. state_machine.py - 遷移定義

以下の遷移を追加:

- `hearing -> hearing-wait` (`hearing_to_hearing_wait`)
- `hearing-wait -> hearing` (`hearing_wait_to_hearing`)
- `hearing-wait -> suspended` (`hearing_wait_to_suspended`)

StateMachine クラスに `hearing_wait` state を追加し、遷移メソッドを定義。

### 3. hearing.py - HearingExecutor.process_result

質問投稿後 (`READY` / `NEEDS_SPLIT` でない場合) の処理を変更:

```python
else:
    # 質問を Issue コメントとして投稿
    await client.create_comment(request.repo, request.issue_number, comment_body)
    # hearing-wait へ遷移
    await client.replace_phase_label(request.repo, request.issue_number, "phase:hearing-wait")
    await self._sm.transition(request.issue_number, "hearing-wait")
    await self._notifier.notify(...)
```

### 4. github_poller.py - 監視対象ラベル変更

`_detect_hearing_replies()`:

```python
# Before
issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
# After
issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
```

`_detect_hearing_timeouts()`:

```python
# Before
issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing")
# After
issues = await client.get_issues_with_label(repo, f"{repo.label},phase:hearing-wait")
```

### 5. event_router.py - _handle_hearing_reply

```python
if current_phase == Phase.HEARING_WAIT:
    await self._sm.transition(issue_number, Phase.HEARING)
    # ラベル更新
    client = await self._get_client(event.repo)
    if client:
        await client.replace_phase_label(event.repo, issue_number, "phase:hearing")
    await self._tq.enqueue(TaskRequest(..., phase=Phase.HEARING.value, priority=Priority.HIGH))
elif current_phase == Phase.HEARING:
    # AI実行中にユーザーが回答 → キューイング
    await self._tq.enqueue(TaskRequest(..., phase=Phase.HEARING.value, priority=Priority.HIGH))
elif current_phase == Phase.SUSPENDED:
    await self._sm.transition(issue_number, Phase.HEARING)
    await self._tq.enqueue(...)
else:
    return  # 他のフェーズでは無視
```

### 6. 変更不要のファイル

- `orchestrator.py`: `active_phases` はそのまま。`hearing` は含まれるが `hearing-wait` は含まれない
- `claude_runner.py`: `PHASE_CONFIG` に `hearing-wait` エントリ不要 (AI 実行しない待機フェーズ)
- `state_persistence.py`: Phase enum から自動対応

---

## Bug #2: branch_prefix 不一致による PR 検索失敗

### Problem

`DesignExecutor` が `_ensure_pr_created(branch_prefix="design")` を呼ぶが、
実際の worktree ブランチは `feature/issue-XX`（最初に `type_detection.py` が
デフォルトの `feature` で作成し、以降は冪等で同じパスを返すため）。

フォールバック PR 検索が `design/issue-XX` ブランチで検索 → マッチせず → 
PR 新規作成も 422 エラー（既に `feature/issue-XX` で PR が存在するため）。

### Root Cause

`workspace_manager.create_worktree()` は冪等で、既存の worktree があればそのまま返す。
`branch_prefix` は初回作成時のみ有効で、2回目以降は無視される。
しかし `_ensure_pr_created()` は渡された `branch_prefix` でブランチ名を構築するため、
実際のブランチ名と乖離する。

### Solution

`_ensure_pr_created()` に渡す `branch_prefix` を、実際に使われたブランチ名と一致させる。

具体的には:
- `hearing.py`: `branch_prefix="design"` を削除（デフォルトの `"feature"` を使用）
- `design.py`: `_ensure_pr_created` の `branch_prefix` を `"feature"` に変更
- `_ensure_pr_created` の Step 2 を強化: `branch_prefix` でマッチしない場合に
  `feature/issue-XX` でもフォールバック検索する

### Changes

#### hearing.py - build_prompt

```python
# Before
worktree = await self._workspace.create_worktree(request.repo, request.issue_number, branch_prefix="design")
# After
worktree = await self._workspace.create_worktree(request.repo, request.issue_number)
```

#### design.py - build_prompt + process_result

```python
# build_prompt: branch_prefix を削除
worktree = await self._workspace.create_worktree(request.repo, request.issue_number)

# process_result: branch_prefix を "feature" に変更
pr_number = await self._ensure_pr_created(request, result.output, branch_prefix="feature", title_prefix="docs: ")
```

#### base.py - _ensure_pr_created Step 2 強化

Step 2 で `branch_prefix/issue-XX` でマッチしない場合、`feature/issue-XX` でもフォールバック検索:

```python
# Step 2: ブランチ名で既存PRを検索
branch_name = f"{branch_prefix}/issue-{request.issue_number}"
pr = search_by_branch(branch_name)
if not pr and branch_prefix != "feature":
    pr = search_by_branch(f"feature/issue-{request.issue_number}")
```

---

## Testing

### hearing-wait
- hearing executor が質問投稿後に `hearing-wait` へ遷移することを確認
- `hearing-wait` 状態の Issue にユーザーがコメントすると `hearing` に戻ることを確認
- `hearing-wait` が `active_phases` に含まれないことを確認 (再起動時に自動再エンキューされない)
- `hearing-wait` のタイムアウトで `suspended` に遷移することを確認
- `hearing` 中に orchestrator が停止 → 再起動後に `hearing` が再実行されることを確認

### branch_prefix fix
- design フェーズで PR 作成後、`_ensure_pr_created` が正しく PR 番号を取得できることを確認
- `feature/issue-XX` ブランチで作成された PR が Step 2 のフォールバック検索で見つかることを確認
