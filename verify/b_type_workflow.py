"""タイプ別ワークフロー検証: Bug / Feature-S / Feature-M の分岐を検証."""

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
def _get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        import subprocess
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        token = result.stdout.strip()
    return token

GITHUB_TOKEN = _get_github_token()

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
class TypeWorkflowState:
    """タイプ別ワークフロー検証で共有する状態."""
    # Bug用
    bug_issue_number: int = 0
    bug_analysis_comment_id: int = 0
    bug_session_id: str = ""
    bug_worktree_path: str = ""
    # Feature-S用
    fs_issue_number: int = 0
    fs_plan_comment_id: int = 0
    fs_session_id: str = ""
    fs_worktree_path: str = ""
    # Feature-M用 (タイプ判定テストのみ)
    fm_issue_number: int = 0
    # 共通
    repo_dir: str = ""
    tmp_dir: str = ""


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

    async def _consume():
        nonlocal session_id, result_text, cost
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "session_id"):
                session_id = message.session_id
            if hasattr(message, "result") and message.result:
                result_text = message.result
            if hasattr(message, "total_cost_usd") and message.total_cost_usd:
                cost = message.total_cost_usd

    await asyncio.wait_for(_consume(), timeout=timeout)

    return {
        "session_id": session_id,
        "result": result_text,
        "cost": cost,
    }


async def setup_repo(state: TypeWorkflowState) -> None:
    """テスト用リポジトリをclone."""
    state.tmp_dir = tempfile.mkdtemp(prefix="ai-agent-type-wf-")
    repo_dir = Path(state.tmp_dir) / "repo"
    ok, _ = await run_git(
        "clone",
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git",
        str(repo_dir),
        cwd=state.tmp_dir,
    )
    assert ok, "clone failed"
    state.repo_dir = str(repo_dir)


async def create_worktree(state: TypeWorkflowState, issue_number: int, branch_prefix: str = "feature") -> str:
    """指定Issue用のworktreeを作成."""
    wt_path = Path(state.tmp_dir) / "worktrees" / f"issue-{issue_number}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    ok, output = await run_git(
        "worktree", "add",
        "-b", f"{branch_prefix}/issue-{issue_number}",
        str(wt_path),
        "origin/main",
        cwd=state.repo_dir,
    )
    assert ok, f"worktree add failed: {output}"
    return str(wt_path)


async def cleanup(state: TypeWorkflowState) -> None:
    if state.tmp_dir:
        shutil.rmtree(state.tmp_dir, ignore_errors=True)


# ──────────────────────────────────────
# T1: タイプ自動判定
# ──────────────────────────────────────
async def verify_t1_type_detection(state: TypeWorkflowState) -> None:
    log("T1: タイプ自動判定")

    test_cases = [
        {
            "title": "ログインボタンを押すと500エラーが出る",
            "body": "ログイン画面で「ログイン」ボタンを押すと、コンソールに500エラーが表示されて進めません。",
            "expected_type": "bug",
        },
        {
            "title": "メールアドレスのバリデーションを追加したい",
            "body": "登録フォームにメールアドレスの形式チェックを追加してほしい。不正な形式の場合はエラーメッセージを表示。",
            "expected_type": "feature-s",
        },
        {
            "title": "ユーザーダッシュボード画面を新規作成",
            "body": "ログイン後に表示されるダッシュボード画面を作りたい。統計情報、最近のアクティビティ、通知一覧を表示。サイドバーナビゲーション付き。",
            "expected_type": "feature-m",
        },
    ]

    prompt_template = """あなたはIssueのタイプを判定するAIです。
以下のIssueを分析し、最も適切なタイプを1つだけ回答してください。

## タイプ定義
- bug: バグ修正（エラー、不具合、動かない、壊れた等）
- feature-s: 小規模機能（1-3ファイル変更、設計書不要レベル）
- feature-m: 中規模機能（複数ファイル、設計書が必要なレベル）
- feature-l: 大規模機能（分割が必要なレベル）

## Issue
タイトル: {title}
本文: {body}

## 回答形式
TYPE: <タイプ名>
REASON: <判定理由を1文で>"""

    for i, tc in enumerate(test_cases):
        prompt = prompt_template.format(title=tc["title"], body=tc["body"])
        result = await sdk_query(prompt, max_budget=0.3, timeout=120)

        response = result["result"].lower()
        detected_type = "unknown"
        for t in ["bug", "feature-s", "feature-m", "feature-l"]:
            if t in response:
                detected_type = t
                break

        is_correct = detected_type == tc["expected_type"]
        record(
            f"タイプ判定 [{tc['expected_type']}]",
            is_correct,
            f"判定={detected_type}, 期待={tc['expected_type']}, cost=${result['cost']:.4f}\n"
            f"response: {result['result'][:200]}",
        )


# ──────────────────────────────────────
# T2: Bug ワークフロー (ANALYSIS → 👍承認 → FIX)
# ──────────────────────────────────────
async def verify_t2_bug_workflow(state: TypeWorkflowState) -> None:
    log("T2: Bug ワークフロー")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # Bug Issue作成
    issue = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="ログインボタンを押すと500エラーが出る",
        body="""## 不具合の内容
ログイン画面で「ログイン」ボタンを押すと、コンソールに以下のエラーが表示されて画面が進みません。

```
TypeError: Cannot read property 'token' of undefined
    at handleLogin (src/auth/login.ts:42)
```

## 再現手順
1. /login にアクセス
2. メールアドレスとパスワードを入力
3. 「ログイン」ボタンをクリック
4. 500エラーが表示される

## 期待する動作
正常にログインしてダッシュボードに遷移する""",
        labels=["ai-agent", "type:bug"],
    )
    state.bug_issue_number = issue.parsed_data.number
    record("Bug Issue作成", True, f"Issue #{state.bug_issue_number}")

    # ── ANALYSIS フェーズ ──
    analysis_prompt = f"""あなたはバグ修正を担当するエンジニアです。
以下のバグIssueを分析して、修正方針を作成してください。

## Issue #{state.bug_issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## コンテキスト
TypeScriptプロジェクト。テスト用リポジトリです。
以下のようなファイル構成を想定:
- src/auth/login.ts (ログイン処理)
- src/api/client.ts (APIクライアント)
- src/types/auth.ts (認証の型定義)

## 指示
以下のフォーマットで修正方針をIssueコメント用に作成してください。
マークダウン形式で出力してください。

---
🔍 **修正方針 (AI分析)**

**原因:** [ファイル名:行番号 で問題の箇所と原因を説明]
**発生条件:** [どういう条件で発生するか]
**修正内容:**
| ファイル | 修正内容 |
|---------|---------|
| xxx | xxx |

**影響範囲:** [他の機能への影響]
**テスト方針:**
- [ ] [再現テスト]
- [ ] [リグレッションテスト]

👍 で承認 / コメントで指摘をお願いします
---"""

    result = await sdk_query(analysis_prompt, max_budget=2.0, timeout=300)
    state.bug_session_id = result["session_id"]

    # 修正方針の品質チェック
    response = result["result"]
    has_cause = "原因" in response
    has_fix = "修正" in response
    has_test = "テスト" in response
    has_approval_prompt = "👍" in response

    record(
        "Bug ANALYSIS (方針作成)",
        has_cause and has_fix,
        f"cost=${result['cost']:.4f}\n"
        f"原因記載={has_cause}, 修正記載={has_fix}, テスト記載={has_test}, 承認案内={has_approval_prompt}",
    )

    # Issueコメントとして投稿
    comment = await gh.rest.issues.async_create_comment(
        REPO_OWNER, REPO_NAME,
        state.bug_issue_number,
        body=response,
    )
    state.bug_analysis_comment_id = comment.parsed_data.id
    record(
        "Bug 方針コメント投稿",
        comment.parsed_data.id > 0,
        f"comment_id={comment.parsed_data.id}",
    )

    # ── 👍 リアクション承認のシミュレート ──
    try:
        await gh.rest.reactions.async_create_for_issue_comment(
            REPO_OWNER, REPO_NAME,
            state.bug_analysis_comment_id,
            content="+1",
        )
        record("👍 リアクション追加", True)
    except Exception as e:
        record("👍 リアクション追加", False, str(e)[:200])

    # 👍 リアクション検知テスト
    try:
        reactions = await gh.rest.reactions.async_list_for_issue_comment(
            REPO_OWNER, REPO_NAME,
            state.bug_analysis_comment_id,
        )
        has_thumbsup = any(
            r.content == "+1"
            for r in reactions.parsed_data
        )
        record(
            "👍 リアクション検知",
            has_thumbsup,
            f"reactions={[r.content for r in reactions.parsed_data]}",
        )
    except Exception as e:
        record("👍 リアクション検知", False, str(e)[:200])

    # ── FIX フェーズ ──
    state.bug_worktree_path = await create_worktree(state, state.bug_issue_number, "fix")

    fix_prompt = f"""承認された修正方針に基づいてバグを修正してください。

## 修正方針
{response}

## 指示
1. 原因箇所のコードを修正してください
2. 再現テストを作成してください
3. git add, commit してください
4. コミットメッセージは "fix: [修正内容]" 形式で

注意: テスト用リポなのでファイル作成だけで十分です。"""

    fix_result = await sdk_query(
        fix_prompt,
        cwd=state.bug_worktree_path,
        max_budget=5.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )

    # 修正ファイルの確認
    src_dir = Path(state.bug_worktree_path) / "src"
    created_files = list(src_dir.rglob("*")) if src_dir.exists() else []
    record(
        "Bug FIX (コード修正)",
        len(created_files) > 0,
        f"cost=${fix_result['cost']:.4f}, files={len(created_files)}",
    )

    # git push + PR作成
    ok, _ = await run_git(
        "push", "origin", f"fix/issue-{state.bug_issue_number}",
        cwd=state.bug_worktree_path,
    )
    if ok:
        try:
            pr = await gh.rest.pulls.async_create(
                REPO_OWNER, REPO_NAME,
                title=f"fix: Issue #{state.bug_issue_number} ログインボタン500エラー修正",
                body=f"""## 修正内容
Issue #{state.bug_issue_number} のバグ修正です。

## 修正方針 (承認済み)
{response[:500]}

AI Agent が自動修正しました。""",
                head=f"fix/issue-{state.bug_issue_number}",
                base="main",
            )
            record("Bug PR作成", True, f"PR #{pr.parsed_data.number}")
        except Exception as e:
            record("Bug PR作成", False, str(e)[:200])
    else:
        record("Bug git push", False)

    print(f"\n  --- Bug方針 (先頭500文字) ---")
    print(f"  {response[:500]}")


# ──────────────────────────────────────
# T3: Feature-S ワークフロー (HEARING → PLAN_BRIEF → 👍 → IMPLEMENT)
# ──────────────────────────────────────
async def verify_t3_feature_s_workflow(state: TypeWorkflowState) -> None:
    log("T3: Feature-S ワークフロー")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # Feature-S Issue作成
    issue = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="メールアドレスのバリデーションを追加したい",
        body="""登録フォームにメールアドレスの形式チェックを追加してほしい。
不正な形式の場合はエラーメッセージを表示する。""",
        labels=["ai-agent", "type:feature-s"],
    )
    state.fs_issue_number = issue.parsed_data.number
    record("Feature-S Issue作成", True, f"Issue #{state.fs_issue_number}")

    # ── HEARING フェーズ (1往復まで) ──
    hearing_prompt = f"""以下のIssueについて要件を確認してください。
Feature-S（小規模機能）として処理します。質問は最大1往復です。

## Issue #{state.fs_issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## コンテキスト
TypeScriptプロジェクト。以下のファイル構成を想定:
- src/utils/validate.ts (バリデーション関数)
- src/components/RegisterForm.tsx (登録フォーム)

## 指示
質問がある場合は質問テキストを出力してください（1往復のみ）。
不明点がなければ "READY_FOR_PLAN" と出力してください。"""

    hearing_result = await sdk_query(hearing_prompt, max_budget=0.5, timeout=120)
    has_ready = "READY_FOR_PLAN" in hearing_result["result"]
    has_questions = len(hearing_result["result"]) > 50 and not has_ready

    record(
        "Feature-S HEARING",
        has_ready or has_questions,
        f"cost=${hearing_result['cost']:.4f}, ready={has_ready}, questions={has_questions}",
    )

    # 質問がある場合、回答をシミュレート
    hearing_context = ""
    if has_questions:
        await gh.rest.issues.async_create_comment(
            REPO_OWNER, REPO_NAME,
            state.fs_issue_number,
            body=hearing_result["result"],
        )
        answer = await gh.rest.issues.async_create_comment(
            REPO_OWNER, REPO_NAME,
            state.fs_issue_number,
            body="RFC 5322準拠のバリデーションでお願いします。エラーメッセージは「正しいメールアドレスを入力してください」で。",
        )
        hearing_context = f"質問: {hearing_result['result'][:200]}\n回答: RFC 5322準拠、エラーメッセージ指定あり"
        record("Feature-S 質問→回答", True)

    # ── PLAN_BRIEF フェーズ ──
    plan_prompt = f"""以下のIssueの簡易実装方針を作成してください。

## Issue #{state.fs_issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

{f"## ヒアリング結果{chr(10)}{hearing_context}" if hearing_context else ""}

## コンテキスト
TypeScript。src/utils/validate.ts と src/components/RegisterForm.tsx が存在する想定。

## 指示
以下のフォーマットで方針をIssueコメント用に作成してください。マークダウン形式で出力。

---
📋 **実装方針 (AI提案)**

**変更内容:**
- [ファイル名]: [変更内容]
- [ファイル名]: [変更内容]

**テスト方針:**
- [ ] [テスト内容]

👍 で承認 / コメントで指摘をお願いします
---"""

    plan_result = await sdk_query(plan_prompt, max_budget=1.0, timeout=180)
    state.fs_session_id = plan_result["session_id"]

    response = plan_result["result"]
    has_plan = "変更内容" in response or "実装方針" in response
    has_approval_prompt = "👍" in response

    record(
        "Feature-S PLAN_BRIEF (方針作成)",
        has_plan,
        f"cost=${plan_result['cost']:.4f}, approval_prompt={has_approval_prompt}",
    )

    # Issueコメントとして投稿
    comment = await gh.rest.issues.async_create_comment(
        REPO_OWNER, REPO_NAME,
        state.fs_issue_number,
        body=response,
    )
    state.fs_plan_comment_id = comment.parsed_data.id
    record(
        "Feature-S 方針コメント投稿",
        comment.parsed_data.id > 0,
        f"comment_id={comment.parsed_data.id}",
    )

    # 👍 リアクション承認シミュレート
    try:
        await gh.rest.reactions.async_create_for_issue_comment(
            REPO_OWNER, REPO_NAME,
            state.fs_plan_comment_id,
            content="+1",
        )
        record("Feature-S 👍 承認", True)
    except Exception as e:
        record("Feature-S 👍 承認", False, str(e)[:200])

    # ── IMPLEMENT フェーズ ──
    state.fs_worktree_path = await create_worktree(state, state.fs_issue_number)

    impl_prompt = f"""承認された方針に基づいて実装してください。

## 方針
{response}

## 指示
1. 方針に沿ってコードを実装してください
2. テストファイルも作成してください
3. git add, commit してください
4. コミットメッセージは "feat: [内容]" 形式で

注意: テスト用リポなのでファイル作成だけで十分です。"""

    impl_result = await sdk_query(
        impl_prompt,
        cwd=state.fs_worktree_path,
        max_budget=5.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )

    src_dir = Path(state.fs_worktree_path) / "src"
    created_files = list(src_dir.rglob("*")) if src_dir.exists() else []
    record(
        "Feature-S IMPLEMENT",
        len(created_files) > 0,
        f"cost=${impl_result['cost']:.4f}, files={len(created_files)}",
    )

    # PR作成
    ok, _ = await run_git(
        "push", "origin", f"feature/issue-{state.fs_issue_number}",
        cwd=state.fs_worktree_path,
    )
    if ok:
        try:
            pr = await gh.rest.pulls.async_create(
                REPO_OWNER, REPO_NAME,
                title=f"feat: Issue #{state.fs_issue_number} メールバリデーション追加",
                body=f"""## 実装内容
Issue #{state.fs_issue_number} の機能追加です。

## 実装方針 (承認済み)
{response[:500]}

AI Agent が自動実装しました。""",
                head=f"feature/issue-{state.fs_issue_number}",
                base="main",
            )
            record("Feature-S PR作成", True, f"PR #{pr.parsed_data.number}")
        except Exception as e:
            record("Feature-S PR作成", False, str(e)[:200])
    else:
        record("Feature-S git push", False)

    print(f"\n  --- Feature-S方針 (先頭500文字) ---")
    print(f"  {response[:500]}")


# ──────────────────────────────────────
# T4: 指摘コメント検知 (方針修正)
# ──────────────────────────────────────
async def verify_t4_plan_revision(state: TypeWorkflowState) -> None:
    log("T4: 方針への指摘コメント → 修正版投稿")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    if not state.fs_issue_number or not state.fs_plan_comment_id:
        record("T4スキップ", False, "Feature-S Issueが未作成")
        return

    # 人間の指摘コメントをシミュレート
    review_comment = await gh.rest.issues.async_create_comment(
        REPO_OWNER, REPO_NAME,
        state.fs_issue_number,
        body="""方針について指摘です。
バリデーション関数はutils/validate.tsではなく、専用のvalidators/ディレクトリを作ってそこに置いてください。
また、バリデーションエラーのカスタムError型も定義してほしいです。""",
    )
    record(
        "指摘コメント投稿 (シミュレート)",
        review_comment.parsed_data.id > 0,
    )

    # 指摘を受けて方針を修正
    revision_prompt = f"""方針に対して指摘がありました。修正版を作成してください。

## 元の方針
(Feature-S Issue #{state.fs_issue_number})

## 指摘内容
{review_comment.parsed_data.body}

## 指示
指摘を反映した修正版の方針を作成してください。
同じフォーマットで出力してください:

📋 **実装方針 (AI提案) [修正版]**

**変更内容:**
- [ファイル名]: [変更内容]

**テスト方針:**
- [ ] [テスト内容]

👍 で承認 / コメントで指摘をお願いします"""

    result = await sdk_query(revision_prompt, max_budget=1.0, timeout=180)

    has_revision = "修正版" in result["result"] or "変更内容" in result["result"]
    has_validators_dir = "validators" in result["result"]
    has_error_type = "Error" in result["result"] or "エラー" in result["result"]

    record(
        "方針修正版作成",
        has_revision,
        f"cost=${result['cost']:.4f}\n"
        f"validators反映={has_validators_dir}, Error型反映={has_error_type}",
    )

    # 修正版をIssueコメントとして投稿
    if has_revision:
        revised_comment = await gh.rest.issues.async_create_comment(
            REPO_OWNER, REPO_NAME,
            state.fs_issue_number,
            body=result["result"],
        )
        record(
            "修正版コメント投稿",
            revised_comment.parsed_data.id > 0,
            f"comment_id={revised_comment.parsed_data.id}",
        )

    print(f"\n  --- 修正版方針 (先頭500文字) ---")
    print(f"  {result['result'][:500]}")


# ──────────────────────────────────────
# T5: PR description に方針を再掲
# ──────────────────────────────────────
async def verify_t5_pr_description(state: TypeWorkflowState) -> None:
    log("T5: PR description に方針再掲を確認")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # Feature-SのPRを取得
    prs = await gh.rest.pulls.async_list(
        REPO_OWNER, REPO_NAME,
        state="open",
        head=f"{REPO_OWNER}:feature/issue-{state.fs_issue_number}",
    )

    if prs.parsed_data:
        pr = prs.parsed_data[0]
        body = pr.body or ""
        has_plan_in_body = "実装方針" in body or "承認済み" in body
        record(
            "PR description に方針再掲",
            has_plan_in_body,
            f"PR #{pr.number}, body_len={len(body)}",
        )
    else:
        record("PR description確認", False, "PRが見つからない")

    # Bug PRも確認
    bug_prs = await gh.rest.pulls.async_list(
        REPO_OWNER, REPO_NAME,
        state="open",
        head=f"{REPO_OWNER}:fix/issue-{state.bug_issue_number}",
    )
    if bug_prs.parsed_data:
        pr = bug_prs.parsed_data[0]
        body = pr.body or ""
        has_plan_in_body = "修正方針" in body or "承認済み" in body
        record(
            "Bug PR description に方針再掲",
            has_plan_in_body,
            f"PR #{pr.number}, body_len={len(body)}",
        )


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  タイプ別ワークフロー検証 T1-T5")
    print("=" * 60)

    state = TypeWorkflowState()

    try:
        await setup_repo(state)
        await verify_t1_type_detection(state)
        await verify_t2_bug_workflow(state)
        await verify_t3_feature_s_workflow(state)
        await verify_t4_plan_revision(state)
        await verify_t5_pr_description(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cleanup(state)

    # サマリ
    log("タイプ別ワークフロー検証サマリ")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")
    total_cost = 0.0
    for r in RESULTS:
        detail = r.get("detail", "")
        if "cost=$" in detail:
            try:
                cost_str = detail.split("cost=$")[1].split(",")[0].split("\n")[0]
                total_cost += float(cost_str)
            except (ValueError, IndexError):
                pass

    for r in RESULTS:
        mark = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {mark} {r['name']}")

    print(f"\n  合計: {passed} PASS / {failed} FAIL / {len(RESULTS)} total")
    print(f"  推定総コスト: ${total_cost:.4f}")

    # 結果保存
    result_path = Path(__file__).parent / "b_type_workflow_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
