"""ワークフロー検証 A1-A5: 各フェーズを実際に実行して動作確認."""

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── 設定 ──
REPO_OWNER = "Akihiro1028Bad"
REPO_NAME = "ai-agent-team2-test"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

RESULTS: list[dict] = []


def log(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def record(name: str, success: bool, detail: str = "") -> None:
    status = "PASS" if success else "FAIL"
    RESULTS.append({"name": name, "status": status, "detail": detail})
    icon = "✅" if success else "❌"
    print(f"  {icon} [{status}] {name}")
    if detail:
        for line in detail.split("\n")[:5]:
            print(f"         {line}")


@dataclass
class WorkflowState:
    """ワークフロー全体で共有する状態."""
    issue_number: int = 0
    worktree_path: str = ""
    repo_dir: str = ""
    tmp_dir: str = ""
    hearing_session_id: str = ""
    design_session_id: str = ""
    design_pr_number: int = 0
    impl_session_id: str = ""
    impl_pr_number: int = 0


# ──────────────────────────────────────
# ヘルパー
# ──────────────────────────────────────
async def run_git(*args: str, cwd: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    output = stdout.decode() + stderr.decode()
    return proc.returncode == 0, output.strip()


async def sdk_query(
    prompt: str,
    *,
    cwd: str | None = None,
    resume: str | None = None,
    max_budget: float = 0.5,
    permission_mode: str = "acceptEdits",
    timeout: int = 300,
) -> dict:
    """Claude Agent SDK の query() を実行して結果を返す."""
    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        max_budget_usd=max_budget,
        permission_mode=permission_mode,
    )
    if cwd:
        options.cwd = cwd
    if resume:
        options.resume = resume

    session_id = None
    result_text = ""
    cost = 0.0
    tool_uses = []

    async def _consume():
        nonlocal session_id, result_text, cost, tool_uses
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "session_id"):
                session_id = message.session_id
            if hasattr(message, "result") and message.result:
                result_text = message.result
            if hasattr(message, "total_cost_usd") and message.total_cost_usd:
                cost = message.total_cost_usd
            if hasattr(message, "content"):
                for block in getattr(message, "content", []):
                    if hasattr(block, "name"):
                        tool_uses.append(block.name)

    await asyncio.wait_for(_consume(), timeout=timeout)

    return {
        "session_id": session_id,
        "result": result_text,
        "cost": cost,
        "tool_uses": tool_uses,
    }


async def setup_worktree(state: WorkflowState) -> None:
    """テスト用 worktree を準備."""
    state.tmp_dir = tempfile.mkdtemp(prefix="ai-agent-wf-")
    repo_dir = Path(state.tmp_dir) / "repo"

    # clone
    ok, _ = await run_git(
        "clone",
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git",
        str(repo_dir),
        cwd=state.tmp_dir,
    )
    assert ok, "clone failed"
    state.repo_dir = str(repo_dir)

    # worktree作成
    wt_path = Path(state.tmp_dir) / "worktrees" / f"issue-{state.issue_number}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    ok, output = await run_git(
        "worktree", "add",
        "-b", f"feature/issue-{state.issue_number}",
        str(wt_path),
        "origin/main",
        cwd=str(repo_dir),
    )
    assert ok, f"worktree add failed: {output}"
    state.worktree_path = str(wt_path)


async def cleanup(state: WorkflowState) -> None:
    """テスト後のクリーンアップ."""
    if state.tmp_dir:
        shutil.rmtree(state.tmp_dir, ignore_errors=True)


# ──────────────────────────────────────
# A1: ヒアリング → 質問投稿
# ──────────────────────────────────────
async def verify_a1_hearing(state: WorkflowState) -> None:
    log("A1: ヒアリング → 質問投稿")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # テスト用Issue作成（曖昧な要件）
    issue = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="ユーザープロフィール画面を追加したい",
        body="""
ユーザーのプロフィール画面が欲しいです。
いい感じにお願いします。
""",
        labels=["ai-agent"],
    )
    state.issue_number = issue.parsed_data.number
    record("テストIssue作成", True, f"Issue #{state.issue_number}")

    # ヒアリングプロンプト実行
    prompt = f"""以下のIssueについて要件ヒアリングを行ってください。

## Issue #{state.issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## コンテキスト
このリポジトリはテスト用の空リポジトリです。TypeScriptプロジェクトを想定しています。

## 指示
1. Issueの内容を分析し、実装に必要な情報が十分か判断してください
2. 不明点がある場合は、具体的な質問をリストアップしてください
3. Issueが大きすぎる場合は分割を提案してください
4. 情報が十分な場合は "READY_FOR_DESIGN" と出力してください

質問がある場合は、Issueコメントとして投稿する質問テキストをそのまま出力してください。
マークダウン形式で、丁寧な日本語でお願いします。"""

    result = await sdk_query(prompt, max_budget=1.0)
    state.hearing_session_id = result["session_id"]

    has_questions = len(result["result"]) > 50
    has_ready = "READY_FOR_DESIGN" in result["result"]

    record(
        "ヒアリング実行",
        has_questions or has_ready,
        f"session_id={result['session_id']}, cost=${result['cost']:.4f}\n"
        f"response_len={len(result['result'])}",
    )

    # 質問がある場合、Issueコメントとして投稿
    if has_questions and not has_ready:
        comment = await gh.rest.issues.async_create_comment(
            REPO_OWNER, REPO_NAME,
            state.issue_number,
            body=result["result"],
        )
        record(
            "質問をIssueコメントに投稿",
            comment.parsed_data.id > 0,
            f"comment_id={comment.parsed_data.id}",
        )

        # 人間の回答をシミュレート
        answer = await gh.rest.issues.async_create_comment(
            REPO_OWNER, REPO_NAME,
            state.issue_number,
            body="""回答します:
- 表示する情報: ユーザー名、メールアドレス、アバター画像、自己紹介文
- 編集機能: 不要（表示のみ）
- API: GET /api/users/:id で取得する想定
- デザイン: シンプルなカードレイアウト
- レスポンシブ: モバイル対応必要""",
        )
        record(
            "人間の回答をシミュレート",
            answer.parsed_data.id > 0,
        )
    else:
        record("ヒアリング結果", has_ready, "READY_FOR_DESIGN (質問なし)")

    print(f"\n  --- ヒアリング結果 (先頭500文字) ---")
    print(f"  {result['result'][:500]}")


# ──────────────────────────────────────
# A2: 設計書PR作成
# ──────────────────────────────────────
async def verify_a2_design(state: WorkflowState) -> None:
    log("A2: 設計書PR作成")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # worktree準備
    await setup_worktree(state)

    # 設計書テンプレート
    design_template = """# 設計書: Issue #{{issue_number}} - {{issue_title}}

## 1. 概要
## 2. 背景・動機
## 3. 影響範囲
### 変更するファイル
| ファイル | 変更内容 |
|---------|---------|
### 影響を受ける既存機能
## 4. 実装方針
### アプローチ
### 代替案
## 5. データ構造の変更
## 6. API変更
## 7. テスト方針
## 8. リスク・懸念事項
## 9. 見積もり"""

    # Issueコメント取得（ヒアリング結果）
    comments_resp = await gh.rest.issues.async_list_comments(
        REPO_OWNER, REPO_NAME, state.issue_number,
    )
    hearing_log = "\n\n".join([
        f"[{c.user.login}]: {c.body}"
        for c in comments_resp.parsed_data
    ])

    prompt = f"""以下のIssueの設計書を作成してください。

## Issue #{state.issue_number}: ユーザープロフィール画面を追加したい

ユーザーのプロフィール画面が欲しいです。いい感じにお願いします。

## ヒアリング記録
{hearing_log}

## コンテキスト
TypeScriptプロジェクト。テスト用の空リポジトリです。

## 指示
1. docs/designs/issue-{state.issue_number}.md に設計書を作成してください
2. 以下のテンプレートに従って全セクションを埋めてください
3. git add, commit, push してください
4. ブランチ名は現在のブランチ (feature/issue-{state.issue_number}) を使ってください
5. 最後に作成したファイルパスを出力してください

設計書テンプレート:
{design_template}"""

    result = await sdk_query(
        prompt,
        cwd=state.worktree_path,
        max_budget=3.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )
    state.design_session_id = result["session_id"]

    # 設計書が作成されたか確認
    design_path = Path(state.worktree_path) / "docs" / "designs" / f"issue-{state.issue_number}.md"
    design_exists = design_path.exists()
    record(
        "設計書ファイル作成",
        design_exists,
        f"path={design_path}" if design_exists else "ファイルが見つからない",
    )

    if design_exists:
        content = design_path.read_text()
        has_sections = all(s in content for s in ["概要", "実装方針", "テスト方針"])
        record(
            "設計書テンプレート準拠",
            has_sections,
            f"content_len={len(content)}",
        )
        print(f"\n  --- 設計書 (先頭800文字) ---")
        print(f"  {content[:800]}")

    # git pushされたか確認
    ok, output = await run_git("log", "--oneline", "-3", cwd=state.worktree_path)
    has_commit = ok and "issue" in output.lower() or "設計" in output or "design" in output
    record(
        "git commit",
        ok and len(output) > 0,
        output[:200],
    )

    # PR作成（SDKが作っていない場合は手動で）
    try:
        # pushされているか確認
        ok, _ = await run_git(
            "push", "origin", f"feature/issue-{state.issue_number}",
            cwd=state.worktree_path,
        )
        if ok:
            pr = await gh.rest.pulls.async_create(
                REPO_OWNER, REPO_NAME,
                title=f"[設計書] Issue #{state.issue_number} ユーザープロフィール画面",
                body=f"Issue #{state.issue_number} の設計書です。\n\nAI Agent が自動作成しました。",
                head=f"feature/issue-{state.issue_number}",
                base="main",
            )
            state.design_pr_number = pr.parsed_data.number
            record("設計PR作成", True, f"PR #{state.design_pr_number}")
        else:
            record("git push", False, "pushに失敗")
    except Exception as e:
        record("設計PR作成", False, str(e)[:200])

    record(
        "A2全体",
        design_exists and state.design_pr_number > 0,
        f"cost=${result['cost']:.4f}, session_id={result['session_id']}",
    )


# ──────────────────────────────────────
# A3: 実装計画 → 実装 → PR
# ──────────────────────────────────────
async def verify_a3_implement(state: WorkflowState) -> None:
    log("A3: 実装計画 → 実装 → PR")

    if not state.worktree_path:
        record("A3スキップ", False, "worktreeが未準備")
        return

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # まず設計書を読む
    design_path = Path(state.worktree_path) / "docs" / "designs" / f"issue-{state.issue_number}.md"
    design_doc = design_path.read_text() if design_path.exists() else "設計書なし"

    # 実装計画 + 実装を一度に実行（検証を効率化）
    prompt = f"""以下の設計書に基づいて、実装計画を立てて実装してください。

## 設計書
{design_doc}

## 指示
1. まず docs/designs/issue-{state.issue_number}-plan.md に実装計画を作成
   - 変更ファイル一覧（実装順）
   - 各ファイルの変更内容
   - テスト方針
2. 実装計画に沿ってコードを実装（シンプルなTypeScriptファイルでOK）
   - src/components/UserProfile.tsx (React コンポーネント)
   - src/api/user.ts (APIクライアント)
   - src/types/user.ts (型定義)
3. テストファイルも作成
   - tests/UserProfile.test.tsx
4. git add, commit, push してください
5. 最後に作成したファイル一覧を出力してください

注意: テスト用の空リポなのでpackage.jsonやtsconfig.jsonがなくても構いません。ファイル作成だけで十分です。"""

    result = await sdk_query(
        prompt,
        cwd=state.worktree_path,
        max_budget=5.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )
    state.impl_session_id = result["session_id"]

    # 実装計画が作成されたか
    plan_path = Path(state.worktree_path) / "docs" / "designs" / f"issue-{state.issue_number}-plan.md"
    record(
        "実装計画作成",
        plan_path.exists(),
        f"path={plan_path}" if plan_path.exists() else "ファイルなし",
    )

    # コードファイルが作成されたか
    src_dir = Path(state.worktree_path) / "src"
    created_files = list(src_dir.rglob("*")) if src_dir.exists() else []
    record(
        "コードファイル作成",
        len(created_files) > 0,
        f"files={[str(f.relative_to(state.worktree_path)) for f in created_files[:10]]}",
    )

    # テストファイルが作成されたか
    test_dir = Path(state.worktree_path) / "tests"
    test_files = list(test_dir.rglob("*")) if test_dir.exists() else []
    # srcの中にテストがある場合もチェック
    if not test_files and src_dir.exists():
        test_files = list(src_dir.rglob("*.test.*")) + list(src_dir.rglob("*.spec.*"))
    record(
        "テストファイル作成",
        len(test_files) > 0,
        f"files={[str(f.relative_to(state.worktree_path)) for f in test_files[:5]]}",
    )

    # git push + PR作成
    ok, _ = await run_git(
        "push", "origin", f"feature/issue-{state.issue_number}",
        cwd=state.worktree_path,
    )
    record("git push (実装)", ok)

    record(
        "A3全体",
        len(created_files) > 0,
        f"cost=${result['cost']:.4f}, session_id={result['session_id']}",
    )


# ──────────────────────────────────────
# A4: レビュー指摘対応 (resume)
# ──────────────────────────────────────
async def verify_a4_review(state: WorkflowState) -> None:
    log("A4: レビュー指摘対応 (resume)")

    if not state.impl_session_id:
        record("A4スキップ", False, "実装セッションIDがない")
        return

    # レビュー指摘をシミュレート
    review_comments = """レビュー指摘:
1. UserProfile コンポーネントにローディング状態の処理がありません。APIレスポンス待ちの間にスピナーを表示してください。
2. エラーハンドリングを追加してください。APIエラー時にユーザーフレンドリーなメッセージを表示するようにしてください。"""

    prompt = f"""以下のレビュー指摘に対応してください:

{review_comments}

修正後、git add, commit, push してください。"""

    result = await sdk_query(
        prompt,
        cwd=state.worktree_path,
        resume=state.impl_session_id,
        max_budget=3.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )

    # resumeが機能したか（前回の実装を理解しているか）
    has_meaningful_response = len(result["result"]) > 30
    record(
        "セッション継続 (resume)",
        has_meaningful_response,
        f"response_len={len(result['result'])}, cost=${result['cost']:.4f}",
    )

    # git logで修正コミットがあるか
    ok, output = await run_git("log", "--oneline", "-5", cwd=state.worktree_path)
    record(
        "修正コミット",
        ok and len(output.splitlines()) > 1,
        output[:300],
    )

    print(f"\n  --- レビュー対応結果 (先頭500文字) ---")
    print(f"  {result['result'][:500]}")


# ──────────────────────────────────────
# A5: CI失敗 → 自動修正
# ──────────────────────────────────────
async def verify_a5_ci_fix(state: WorkflowState) -> None:
    log("A5: CI失敗 → 自動修正")

    if not state.worktree_path:
        record("A5スキップ", False, "worktreeが未準備")
        return

    # 模擬CIログ
    ci_logs = """=== CI FAILED ===

FAIL tests/UserProfile.test.tsx
  ● UserProfile > renders user name

    TypeError: Cannot read property 'name' of undefined

      at UserProfile (src/components/UserProfile.tsx:12:25)
      at Object.<anonymous> (tests/UserProfile.test.tsx:15:5)

  ● UserProfile > shows loading spinner

    Expected element to have class "spinner" but received ""

Test Suites: 1 failed, 1 total
Tests:       2 failed, 2 passed, 4 total

=== ESLint ===
src/api/user.ts:8:5 warning: Unexpected 'any'. Specify a different type. (@typescript-eslint/no-explicit-any)
"""

    prompt = f"""CIが失敗しました（1/3回目）。修正してください。

## CI失敗ログ
{ci_logs}

## 指示
1. CI失敗ログを分析して原因を特定してください
2. コードを修正してください
3. 修正内容を説明してください
4. git add, commit, push してください"""

    result = await sdk_query(
        prompt,
        cwd=state.worktree_path,
        max_budget=3.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )

    has_fix = len(result["result"]) > 50
    record(
        "CI失敗分析 + 修正",
        has_fix,
        f"cost=${result['cost']:.4f}",
    )

    print(f"\n  --- CI修正結果 (先頭500文字) ---")
    print(f"  {result['result'][:500]}")


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  ワークフロー検証 A1-A5")
    print("=" * 60)

    state = WorkflowState()

    try:
        await verify_a1_hearing(state)
        await verify_a2_design(state)
        await verify_a3_implement(state)
        await verify_a4_review(state)
        await verify_a5_ci_fix(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cleanup(state)

    # サマリ
    log("ワークフロー検証サマリ")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    total_cost = sum(
        float(r["detail"].split("cost=$")[1].split(",")[0].split("\n")[0])
        for r in RESULTS
        if "cost=$" in r.get("detail", "")
    )

    for r in RESULTS:
        mark = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {mark} {r['name']}")

    print(f"\n  合計: {passed} PASS / {failed} FAIL / {len(RESULTS)} total")
    print(f"  推定総コスト: ${total_cost:.4f}")

    # 結果保存
    result_path = Path(__file__).parent / "a_workflow_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
