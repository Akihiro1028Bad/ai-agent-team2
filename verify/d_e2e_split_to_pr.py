"""E2E検証: Feature-L 子Issue → 優先順にFeature-Mワークフロー → PR作成."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# ── 設定 ──
REPO_OWNER = "Akihiro1028Bad"
REPO_NAME = "ai-agent-team2-test"


def _get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
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
class E2EState:
    """E2E検証状態."""
    tmp_dir: str = ""
    repo_dir: str = ""
    # Issue #10 (依存なし・最優先)
    issue_a_number: int = 0
    issue_a_worktree: str = ""
    issue_a_session_id: str = ""
    issue_a_pr_number: int = 0
    # Issue #11 (#10に依存)
    issue_b_number: int = 0
    issue_b_worktree: str = ""
    issue_b_session_id: str = ""
    issue_b_pr_number: int = 0


async def run_git(*args: str, cwd: str) -> tuple[bool, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode == 0, (stdout.decode() + stderr.decode()).strip()


async def sdk_query(
    prompt: str,
    *,
    cwd: str | None = None,
    resume: str | None = None,
    max_budget: float = 0.5,
    permission_mode: str = "acceptEdits",
    timeout: int = 300,
) -> dict:
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
    return {"session_id": session_id, "result": result_text, "cost": cost}


async def setup_repo(state: E2EState) -> None:
    state.tmp_dir = tempfile.mkdtemp(prefix="ai-agent-e2e-")
    repo_dir = Path(state.tmp_dir) / "repo"
    ok, _ = await run_git(
        "clone",
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git",
        str(repo_dir),
        cwd=state.tmp_dir,
    )
    assert ok, "clone failed"
    state.repo_dir = str(repo_dir)


async def create_worktree(state: E2EState, issue_number: int) -> str:
    wt_path = Path(state.tmp_dir) / "worktrees" / f"issue-{issue_number}"
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    ok, output = await run_git(
        "worktree", "add",
        "-b", f"feature/issue-{issue_number}",
        str(wt_path),
        "origin/main",
        cwd=state.repo_dir,
    )
    assert ok, f"worktree add failed: {output}"
    return str(wt_path)


async def cleanup(state: E2EState) -> None:
    if state.tmp_dir:
        shutil.rmtree(state.tmp_dir, ignore_errors=True)


# ──────────────────────────────────────
# E1: 優先順キューのシミュレート
# ──────────────────────────────────────
async def verify_e1_priority_queue(state: E2EState) -> None:
    log("E1: 依存順にIssueをキューに投入")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # 子Issueを2つ新規作成（前回のテストIssueは使い回さない）
    issue_a = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="[子Issue] DBスキーマ設計変更（認証テーブル追加）",
        body="""## 概要
JWT認証に必要なDBスキーマを設計・実装する。

## やること
- users テーブルに oauth_provider, oauth_id カラム追加
- refresh_tokens テーブル新規作成
- マイグレーションスクリプト作成

親Issue: #9
優先順位: 1
依存: なし""",
        labels=["ai-agent", "type:feature-m"],
    )
    state.issue_a_number = issue_a.parsed_data.number
    record("子Issue A 作成 (依存なし)", True, f"Issue #{state.issue_a_number}")

    # depends-on ラベルを先に作成（存在しない場合）
    dep_label_name = f"depends-on:#{state.issue_a_number}"
    try:
        await gh.rest.issues.async_create_label(
            REPO_OWNER, REPO_NAME,
            name=dep_label_name,
            color="d4c5f9",
            description=f"Issue #{state.issue_a_number} に依存",
        )
    except Exception:
        pass  # 既に存在する場合はスキップ

    issue_b = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="[子Issue] JWT発行・検証ロジック実装",
        body=f"""## 概要
JWT トークンの発行・検証・更新ロジックを実装する。

## やること
- JWT発行関数 (sign)
- JWT検証関数 (verify)
- トークンペイロード型定義
- 有効期限管理

親Issue: #9
優先順位: 2
依存: #{state.issue_a_number}""",
        labels=["ai-agent", "type:feature-m", dep_label_name],
    )
    state.issue_b_number = issue_b.parsed_data.number
    record("子Issue B 作成 (Aに依存)", True, f"Issue #{state.issue_b_number}")

    # 優先順キューのシミュレート
    # Pollerが全ai-agent Issueを取得 → 依存関係を解析 → 処理可能なものだけキューに
    open_issues = await gh.rest.issues.async_list_for_repo(
        REPO_OWNER, REPO_NAME,
        labels="ai-agent",
        state="open",
    )

    queue = []
    blocked = []

    for issue in open_issues.parsed_data:
        label_names = [l.name for l in issue.labels]
        deps = [l for l in label_names if l.startswith("depends-on:#")]

        if not deps:
            queue.append(issue.number)
        else:
            # 依存先がすべてクローズされているかチェック
            all_resolved = True
            for dep_label in deps:
                dep_num = int(dep_label.split("#")[1])
                try:
                    dep_issue = await gh.rest.issues.async_get(
                        REPO_OWNER, REPO_NAME, dep_num,
                    )
                    if dep_issue.parsed_data.state != "closed":
                        all_resolved = False
                        break
                except Exception:
                    all_resolved = False
                    break

            if all_resolved:
                queue.append(issue.number)
            else:
                blocked.append(issue.number)

    a_in_queue = state.issue_a_number in queue
    b_blocked = state.issue_b_number in blocked

    record(
        "Issue A はキューに入る（依存なし）",
        a_in_queue,
        f"queue={queue[:5]}",
    )
    record(
        "Issue B はブロック（A未完了）",
        b_blocked,
        f"blocked={blocked[:5]}",
    )


# ──────────────────────────────────────
# E2: Issue A を Feature-M ワークフローで処理 → PR作成
# ──────────────────────────────────────
async def verify_e2_process_issue_a(state: E2EState) -> None:
    log("E2: Issue A → Feature-M ワークフロー → PR")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    issue = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, state.issue_a_number,
    )

    # ── HEARING (簡略化: 要件は十分なのでスキップ判定) ──
    hearing_result = await sdk_query(
        f"""Issue #{state.issue_a_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

このIssueの要件は十分ですか？質問があれば出力、なければ "READY_FOR_DESIGN" と出力。""",
        max_budget=0.5,
        timeout=120,
    )
    is_ready = "READY" in hearing_result["result"].upper()
    record("Issue A HEARING", True, f"ready={is_ready}, cost=${hearing_result['cost']:.4f}")

    # ── DESIGN (設計書作成) ──
    state.issue_a_worktree = await create_worktree(state, state.issue_a_number)

    design_result = await sdk_query(
        f"""Issue #{state.issue_a_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## 指示
1. docs/designs/issue-{state.issue_a_number}.md に設計書を作成
2. 以下を含めること: 概要、変更ファイル一覧、実装方針、テスト方針
3. git add, commit してください
4. TypeScriptプロジェクト想定。テスト用空リポなのでファイル作成だけでOK。""",
        cwd=state.issue_a_worktree,
        max_budget=3.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )
    state.issue_a_session_id = design_result["session_id"]

    design_path = Path(state.issue_a_worktree) / "docs" / "designs" / f"issue-{state.issue_a_number}.md"
    record(
        "Issue A DESIGN (設計書)",
        design_path.exists(),
        f"cost=${design_result['cost']:.4f}",
    )

    # ── IMPLEMENT (実装) ──
    impl_result = await sdk_query(
        f"""設計書に基づいて実装してください。

## 指示
1. src/ にTypeScriptファイルを作成
2. テストファイルも作成
3. git add, commit してください
4. テスト用リポなのでファイル作成だけでOK""",
        cwd=state.issue_a_worktree,
        resume=state.issue_a_session_id,
        max_budget=5.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )

    src_dir = Path(state.issue_a_worktree) / "src"
    files = list(src_dir.rglob("*")) if src_dir.exists() else []
    record(
        "Issue A IMPLEMENT",
        len(files) > 0,
        f"files={len(files)}, cost=${impl_result['cost']:.4f}",
    )

    # ── PR作成 ──
    ok, _ = await run_git(
        "push", "origin", f"feature/issue-{state.issue_a_number}",
        cwd=state.issue_a_worktree,
    )
    record("Issue A git push", ok)

    if ok:
        try:
            pr = await gh.rest.pulls.async_create(
                REPO_OWNER, REPO_NAME,
                title=f"feat: Issue #{state.issue_a_number} DBスキーマ設計変更",
                body=f"Issue #{state.issue_a_number} の実装PRです。\n\nAI Agent が自動作成。",
                head=f"feature/issue-{state.issue_a_number}",
                base="main",
            )
            state.issue_a_pr_number = pr.parsed_data.number
            record("Issue A PR作成", True, f"PR #{state.issue_a_pr_number}")
        except Exception as e:
            record("Issue A PR作成", False, str(e)[:200])


# ──────────────────────────────────────
# E3: Issue A 完了 → Issue B のブロック解除
# ──────────────────────────────────────
async def verify_e3_unblock_issue_b(state: E2EState) -> None:
    log("E3: Issue A 完了 → Issue B ブロック解除")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # Issue Aをクローズ（マージシミュレート）
    await gh.rest.issues.async_update(
        REPO_OWNER, REPO_NAME,
        state.issue_a_number,
        state="closed",
        state_reason="completed",
    )
    record("Issue A クローズ (マージ完了)", True)

    # Issue B の依存チェック
    issue_b = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, state.issue_b_number,
    )
    label_names = [l.name for l in issue_b.parsed_data.labels]
    deps = [l for l in label_names if l.startswith("depends-on:#")]

    all_resolved = True
    for dep_label in deps:
        dep_num = int(dep_label.split("#")[1])
        dep_issue = await gh.rest.issues.async_get(
            REPO_OWNER, REPO_NAME, dep_num,
        )
        if dep_issue.parsed_data.state != "closed":
            all_resolved = False

    record(
        "Issue B ブロック解除",
        all_resolved,
        f"deps={deps}, all_resolved={all_resolved}",
    )


# ──────────────────────────────────────
# E4: Issue B を処理 → PR作成
# ──────────────────────────────────────
async def verify_e4_process_issue_b(state: E2EState) -> None:
    log("E4: Issue B → Feature-M ワークフロー → PR")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    issue = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, state.issue_b_number,
    )

    state.issue_b_worktree = await create_worktree(state, state.issue_b_number)

    # DESIGN + IMPLEMENT を一度に（検証効率化）
    result = await sdk_query(
        f"""Issue #{state.issue_b_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## コンテキスト
依存先の Issue #{state.issue_a_number}（DBスキーマ設計変更）は完了済みです。
そこで作成された型定義やテーブル構造を前提に実装してください。

## 指示
1. docs/designs/issue-{state.issue_b_number}.md に設計書を作成
2. src/ にJWT関連のTypeScriptファイルを実装
3. テストファイルも作成
4. git add, commit してください
5. テスト用リポなのでファイル作成だけでOK""",
        cwd=state.issue_b_worktree,
        max_budget=5.0,
        permission_mode="bypassPermissions",
        timeout=600,
    )
    state.issue_b_session_id = result["session_id"]

    # ファイル確認
    src_dir = Path(state.issue_b_worktree) / "src"
    files = list(src_dir.rglob("*")) if src_dir.exists() else []
    design_path = Path(state.issue_b_worktree) / "docs" / "designs" / f"issue-{state.issue_b_number}.md"

    record(
        "Issue B 設計書",
        design_path.exists(),
        f"path={design_path}",
    )
    record(
        "Issue B 実装ファイル",
        len(files) > 0,
        f"files={len(files)}, cost=${result['cost']:.4f}",
    )

    # PR作成
    ok, _ = await run_git(
        "push", "origin", f"feature/issue-{state.issue_b_number}",
        cwd=state.issue_b_worktree,
    )
    record("Issue B git push", ok)

    if ok:
        try:
            pr = await gh.rest.pulls.async_create(
                REPO_OWNER, REPO_NAME,
                title=f"feat: Issue #{state.issue_b_number} JWT発行・検証ロジック",
                body=f"""Issue #{state.issue_b_number} の実装PRです。

**依存:** Issue #{state.issue_a_number} (PR #{state.issue_a_pr_number}) ✅ 完了済み

AI Agent が自動作成。""",
                head=f"feature/issue-{state.issue_b_number}",
                base="main",
            )
            state.issue_b_pr_number = pr.parsed_data.number
            record("Issue B PR作成", True, f"PR #{state.issue_b_pr_number}")
        except Exception as e:
            record("Issue B PR作成", False, str(e)[:200])


# ──────────────────────────────────────
# E5: PR内容の品質確認
# ──────────────────────────────────────
async def verify_e5_pr_quality(state: E2EState) -> None:
    log("E5: PR内容の品質確認")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    for label, pr_num, issue_num in [
        ("Issue A", state.issue_a_pr_number, state.issue_a_number),
        ("Issue B", state.issue_b_pr_number, state.issue_b_number),
    ]:
        if not pr_num:
            record(f"{label} PR品質", False, "PRが存在しない")
            continue

        pr = await gh.rest.pulls.async_get(
            REPO_OWNER, REPO_NAME, pr_num,
        )
        # PRにファイル変更があるか
        files = await gh.rest.pulls.async_list_files(
            REPO_OWNER, REPO_NAME, pr_num,
        )
        file_count = len(files.parsed_data)
        has_src = any("src/" in f.filename for f in files.parsed_data)
        has_docs = any("docs/" in f.filename for f in files.parsed_data)

        record(
            f"{label} PR #{pr_num} ファイル変更",
            file_count > 0,
            f"files={file_count}, has_src={has_src}, has_docs={has_docs}",
        )

        # PR descriptionにIssue番号が含まれるか
        body = pr.parsed_data.body or ""
        has_issue_ref = f"#{issue_num}" in body
        record(
            f"{label} PR description にIssue参照",
            has_issue_ref,
        )

    # Issue B のPRに依存情報が含まれるか
    if state.issue_b_pr_number:
        pr_b = await gh.rest.pulls.async_get(
            REPO_OWNER, REPO_NAME, state.issue_b_pr_number,
        )
        body = pr_b.parsed_data.body or ""
        has_dep_ref = f"#{state.issue_a_number}" in body
        record(
            "Issue B PR に依存先Issue参照",
            has_dep_ref,
            f"依存先 Issue #{state.issue_a_number} への参照あり" if has_dep_ref else "参照なし",
        )


# ──────────────────────────────────────
# E6: 処理順序の検証
# ──────────────────────────────────────
async def verify_e6_order(state: E2EState) -> None:
    log("E6: 処理順序の検証")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # Issue A の PR が先に作成されていることを確認
    if state.issue_a_pr_number and state.issue_b_pr_number:
        pr_a = await gh.rest.pulls.async_get(
            REPO_OWNER, REPO_NAME, state.issue_a_pr_number,
        )
        pr_b = await gh.rest.pulls.async_get(
            REPO_OWNER, REPO_NAME, state.issue_b_pr_number,
        )

        a_created = pr_a.parsed_data.created_at
        b_created = pr_b.parsed_data.created_at

        a_before_b = a_created < b_created
        record(
            "PR作成順序: A → B",
            a_before_b,
            f"PR A: {a_created}, PR B: {b_created}",
        )
    else:
        record("PR作成順序", False, "PRが不足")

    # 最終サマリ
    record(
        "E2E完走",
        state.issue_a_pr_number > 0 and state.issue_b_pr_number > 0,
        f"Issue A → PR #{state.issue_a_pr_number}, Issue B → PR #{state.issue_b_pr_number}",
    )


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  E2E検証: Feature-L分割 → 依存順PR作成")
    print("=" * 60)

    state = E2EState()

    try:
        await setup_repo(state)
        await verify_e1_priority_queue(state)
        await verify_e2_process_issue_a(state)
        await verify_e3_unblock_issue_b(state)
        await verify_e4_process_issue_b(state)
        await verify_e5_pr_quality(state)
        await verify_e6_order(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cleanup(state)

    # サマリ
    log("E2E検証サマリ")
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

    result_path = Path(__file__).parent / "d_e2e_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
