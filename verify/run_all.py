"""アーキテクチャ検証スクリプト - 全検証を順番に実行."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

# ── 設定 ──
REPO_OWNER = "Akihiro1028Bad"
REPO_NAME = "ai-agent-team2-test"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
OAUTH_TOKEN = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")

RESULTS: list[dict] = []


def log(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def record(name: str, success: bool, detail: str = "") -> None:
    status = "PASS" if success else "FAIL"
    RESULTS.append({"name": name, "status": status, "detail": detail})
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")


# ──────────────────────────────────────
# 検証1: Claude Agent SDK + OAuth Token
# ──────────────────────────────────────
async def verify_sdk_connection() -> None:
    log("検証1: Claude Agent SDK + OAuth Token 接続")

    if not OAUTH_TOKEN:
        record("SDK OAuth Token", False, "CLAUDE_CODE_OAUTH_TOKEN が未設定")
        return

    try:
        from claude_agent_sdk import query, ClaudeAgentOptions

        session_id = None
        result_text = ""
        cost = 0.0

        async for message in query(
            prompt="Hello. Reply with exactly: VERIFICATION_OK",
            options=ClaudeAgentOptions(
                max_budget_usd=0.1,
                permission_mode="plan",  # 読み取り専用で安全
            ),
        ):
            if hasattr(message, "session_id"):
                session_id = message.session_id
            if hasattr(message, "result"):
                result_text = message.result or ""
            if hasattr(message, "total_cost_usd") and message.total_cost_usd:
                cost = message.total_cost_usd

        has_response = len(result_text) > 0
        record(
            "SDK接続 (query)",
            has_response,
            f"session_id={session_id}, response_len={len(result_text)}, cost=${cost:.4f}",
        )
        record(
            "session_id取得",
            session_id is not None,
            f"session_id={session_id}",
        )

        # セッション継続テスト
        if session_id:
            resume_result = ""
            async for message in query(
                prompt="What was my previous message? Reply briefly.",
                options=ClaudeAgentOptions(
                    resume=session_id,
                    max_budget_usd=0.1,
                    permission_mode="plan",
                ),
            ):
                if hasattr(message, "result"):
                    resume_result = message.result or ""

            record(
                "セッション継続 (resume)",
                len(resume_result) > 0,
                f"response_len={len(resume_result)}",
            )

    except ImportError:
        record("SDK接続", False, "claude-agent-sdk がインストールされていない")
    except Exception as e:
        record("SDK接続", False, f"エラー: {type(e).__name__}: {e}")


# ──────────────────────────────────────
# 検証2: githubkit で Issue/Label 操作
# ──────────────────────────────────────
async def verify_github_api() -> None:
    log("検証2: githubkit で GitHub API 操作")

    if not GITHUB_TOKEN:
        record("GitHub Token", False, "GITHUB_TOKEN が未設定")
        return

    try:
        from githubkit import GitHub

        gh = GitHub(GITHUB_TOKEN)

        # リポジトリ取得
        repo = await gh.rest.repos.async_get(REPO_OWNER, REPO_NAME)
        record(
            "リポジトリ取得",
            repo.parsed_data.full_name == f"{REPO_OWNER}/{REPO_NAME}",
            f"repo={repo.parsed_data.full_name}",
        )

        # ラベル作成
        test_label_name = "test:verify-architecture"
        try:
            await gh.rest.issues.async_create_label(
                REPO_OWNER,
                REPO_NAME,
                name=test_label_name,
                color="0e8a16",
                description="アーキテクチャ検証用テストラベル",
            )
            record("ラベル作成", True, f"label={test_label_name}")
        except Exception as e:
            if "already_exists" in str(e):
                record("ラベル作成", True, "既に存在 (OK)")
            else:
                record("ラベル作成", False, str(e))

        # Issue作成
        issue = await gh.rest.issues.async_create(
            REPO_OWNER,
            REPO_NAME,
            title="[検証] アーキテクチャ検証テスト",
            body="この Issue はアーキテクチャ検証スクリプトが自動作成しました。検証完了後に自動クローズされます。",
            labels=[test_label_name],
        )
        issue_number = issue.parsed_data.number
        record(
            "Issue作成",
            issue_number > 0,
            f"issue_number={issue_number}",
        )

        # Issueコメント投稿
        comment = await gh.rest.issues.async_create_comment(
            REPO_OWNER,
            REPO_NAME,
            issue_number,
            body="検証コメント: githubkit からの自動投稿テスト",
        )
        record(
            "Issueコメント投稿",
            comment.parsed_data.id > 0,
            f"comment_id={comment.parsed_data.id}",
        )

        # ラベル追加
        await gh.rest.issues.async_add_labels(
            REPO_OWNER,
            REPO_NAME,
            issue_number,
            labels=["test:verify-architecture"],
        )
        record("ラベル追加", True)

        # Issueクローズ
        await gh.rest.issues.async_update(
            REPO_OWNER,
            REPO_NAME,
            issue_number,
            state="closed",
        )
        record("Issueクローズ", True)

        # クリーンアップ: テストラベル削除
        try:
            await gh.rest.issues.async_delete_label(
                REPO_OWNER, REPO_NAME, test_label_name
            )
        except Exception:
            pass

    except ImportError:
        record("GitHub API", False, "githubkit がインストールされていない")
    except Exception as e:
        record("GitHub API", False, f"エラー: {type(e).__name__}: {e}")


# ──────────────────────────────────────
# 検証3: git worktree 作成・削除
# ──────────────────────────────────────
async def verify_worktree() -> None:
    log("検証3: git worktree 作成・削除")

    tmp_dir = Path(tempfile.mkdtemp(prefix="ai-agent-verify-"))

    try:
        # クローン
        proc = await asyncio.create_subprocess_exec(
            "git", "clone",
            f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git",
            str(tmp_dir / "repo"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        clone_ok = proc.returncode == 0
        record("git clone", clone_ok, str(tmp_dir / "repo") if clone_ok else stderr.decode()[:200])

        if not clone_ok:
            return

        repo_dir = tmp_dir / "repo"

        # デフォルトブランチ取得
        # リモートのデフォルトブランチ取得
        proc = await asyncio.create_subprocess_exec(
            "git", "remote", "show", "origin",
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        default_branch = "main"
        for line in stdout.decode().splitlines():
            if "HEAD branch" in line:
                default_branch = line.split(":")[-1].strip()
                break
        record("デフォルトブランチ検出", bool(default_branch), f"branch={default_branch}")

        # worktree作成
        worktree_path = tmp_dir / "worktrees" / "issue-999"
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add",
            "-b", "feature/issue-999",
            str(worktree_path),
            f"origin/{default_branch}",
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        wt_ok = proc.returncode == 0
        record(
            "worktree作成",
            wt_ok,
            f"path={worktree_path}" if wt_ok else stderr.decode()[:200],
        )

        # worktree内でファイル操作
        if wt_ok:
            test_file = worktree_path / "verify_test.txt"
            test_file.write_text("worktree verification test")
            record("worktree内ファイル操作", test_file.exists())

        # worktree削除
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "remove",
            str(worktree_path), "--force",
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        wt_removed = not worktree_path.exists()
        record("worktree削除", wt_removed)

    except Exception as e:
        record("worktree操作", False, f"エラー: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ──────────────────────────────────────
# 検証4: Slack Webhook (httpx)
# ──────────────────────────────────────
async def verify_slack() -> None:
    log("検証4: httpx HTTP クライアント")

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            # httpxの基本動作確認 (実際のSlack webhookは使わない)
            resp = await client.get("https://httpbin.org/get")
            record(
                "httpx GET",
                resp.status_code == 200,
                f"status={resp.status_code}",
            )

            # POST (Slack webhook形式のペイロード)
            resp = await client.post(
                "https://httpbin.org/post",
                json={"text": "検証テスト from AI Agent Orchestrator"},
            )
            record(
                "httpx POST (Slack形式)",
                resp.status_code == 200,
                f"status={resp.status_code}",
            )

    except ImportError:
        record("httpx", False, "httpx がインストールされていない")
    except Exception as e:
        record("httpx", False, f"エラー: {type(e).__name__}: {e}")


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  AI Multi-Agent Orchestrator アーキテクチャ検証")
    print("=" * 60)

    await verify_sdk_connection()
    await verify_github_api()
    await verify_worktree()
    await verify_slack()

    # サマリ
    log("検証結果サマリ")
    passed = sum(1 for r in RESULTS if r["status"] == "PASS")
    failed = sum(1 for r in RESULTS if r["status"] == "FAIL")

    for r in RESULTS:
        mark = "✅" if r["status"] == "PASS" else "❌"
        print(f"  {mark} {r['name']}")
        if r["detail"] and r["status"] == "FAIL":
            print(f"     → {r['detail']}")

    print(f"\n  合計: {passed} PASS / {failed} FAIL / {len(RESULTS)} total")

    if failed > 0:
        print("\n  ⚠️  一部の検証が失敗しました。上記の詳細を確認してください。")
    else:
        print("\n  🎉 全検証パス！このアーキテクチャで実装を進められます。")

    # 結果をJSONで保存
    result_path = Path(__file__).parent / "results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
