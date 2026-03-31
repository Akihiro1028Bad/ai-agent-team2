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

## Testing

- hearing executor が質問投稿後に `hearing-wait` へ遷移することを確認
- `hearing-wait` 状態の Issue にユーザーがコメントすると `hearing` に戻ることを確認
- `hearing-wait` が `active_phases` に含まれないことを確認 (再起動時に自動再エンキューされない)
- `hearing-wait` のタイムアウトで `suspended` に遷移することを確認
- `hearing` 中に orchestrator が停止 → 再起動後に `hearing` が再実行されることを確認
