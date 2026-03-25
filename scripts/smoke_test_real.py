"""実環境スモークテスト: 各コンポーネントが実APIで動作するか段階的に検証."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

REPO_OWNER = "Akihiro1028Bad"
REPO_NAME = "ai-agent-team2-test"
RESULTS: list[tuple[str, bool, str]] = []


def get_token() -> str:
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    return result.stdout.strip()


def record(name: str, success: bool, detail: str = "") -> None:
    RESULTS.append((name, success, detail))
    icon = "\u2705" if success else "\u274c"
    print(f"  {icon} {name}")
    if detail:
        print(f"       {detail[:200]}")


async def test_config_loading() -> None:
    """Step 1: config.yaml の読み込み."""
    print("\n=== Step 1: Config Loading ===")
    try:
        from ai_agent_orchestrator.config.settings import AppSettings, RepositoryConfig

        settings = AppSettings(
            polling_interval_sec=30,
            accounts={
                "default": {"name": "default", "token_command": "gh auth token", "default": True},
            },
            repositories=[
                RepositoryConfig(
                    owner=REPO_OWNER,
                    repo=REPO_NAME,
                    account="default",
                    label="ai-agent",
                    base_branch="main",
                ),
            ],
        )
        record("設定オブジェクト作成", True, f"repos={len(settings.repositories)}")
        record("アカウント設定", len(settings.accounts) > 0, f"accounts={list(settings.accounts.keys())}")
        record(
            "リポジトリ設定",
            len(settings.repositories) > 0,
            f"repo={settings.repositories[0].owner}/{settings.repositories[0].repo}",
        )
        return settings
    except Exception as e:
        record("設定オブジェクト作成", False, str(e))
        return None


async def test_credential_resolution() -> None:
    """Step 2: トークン解決."""
    print("\n=== Step 2: Credential Resolution ===")
    try:
        from ai_agent_orchestrator.config.settings import AccountConfig
        from ai_agent_orchestrator.credential import CredentialResolver

        resolver = CredentialResolver()
        account = AccountConfig(name="default", token_command="gh auth token")
        token = await resolver.resolve(account)
        record("トークン解決", len(token) > 10, f"token={token[:10]}...")

        user_info = await resolver.verify(token)
        record("トークン検証", "login" in user_info, f"user={user_info.get('login', 'unknown')}")
    except Exception as e:
        record("トークン解決", False, str(e))


async def test_github_client() -> None:
    """Step 3: GitHub API 操作."""
    print("\n=== Step 3: GitHub Client ===")
    try:
        from ai_agent_orchestrator.config.settings import RepositoryConfig
        from ai_agent_orchestrator.github.client import GitHubClient

        token = get_token()
        client = GitHubClient(token=token)
        repo = RepositoryConfig(
            owner=REPO_OWNER,
            repo=REPO_NAME,
            account="default",
            label="ai-agent",
            base_branch="main",
        )

        # Issue一覧取得
        issues = await client.get_issues_with_label(repo, "ai-agent")
        record("Issue一覧取得", True, f"count={len(issues)}")

        # ラベル一覧確認
        record("GitHub API接続", True, "GitHubClient 正常動作")

    except Exception as e:
        record("GitHub Client", False, f"{type(e).__name__}: {e}")


async def test_workspace_manager() -> None:
    """Step 4: ワークスペース管理."""
    print("\n=== Step 4: Workspace Manager ===")
    try:
        from ai_agent_orchestrator.config.settings import RepositoryConfig
        from ai_agent_orchestrator.workspace_manager import WorkspaceManager

        wm = WorkspaceManager(base_dir=Path("/tmp/ai-agent-smoke-test"))
        token = get_token()
        repo = RepositoryConfig(
            owner=REPO_OWNER,
            repo=REPO_NAME,
            account="default",
            label="ai-agent",
            base_branch="main",
        )

        # clone
        repo_path = await wm.ensure_cloned(repo, token=token)
        record("リポジトリ clone", repo_path.exists(), f"path={repo_path}")

        # worktree作成
        wt_path = await wm.create_worktree(repo, issue_number=9999, token=token)
        record("worktree 作成", wt_path.exists(), f"path={wt_path}")

        # worktree一覧
        worktrees = await wm.list_worktrees(repo)
        record("worktree 一覧", len(worktrees) > 0, f"count={len(worktrees)}")

        # worktree削除
        await wm.remove_worktree(repo, issue_number=9999)
        record("worktree 削除", not wt_path.exists(), "cleanup OK")

    except Exception as e:
        record("Workspace Manager", False, f"{type(e).__name__}: {e}")


async def test_claude_runner() -> None:
    """Step 5: Claude Agent SDK 実行."""
    print("\n=== Step 5: Claude Agent Runner ===")
    try:
        from ai_agent_orchestrator.agents.claude_runner import ClaudeAgentRunner
        from ai_agent_orchestrator.event_logger import EventLogger
        from ai_agent_orchestrator.models import AgentResult

        logger = EventLogger(log_dir=Path("/tmp/ai-agent-smoke-test/logs"))
        runner = ClaudeAgentRunner(tracker=logger)
        result: AgentResult = await runner.run(
            prompt='Reply with exactly: "SMOKE_TEST_OK"',
            phase="type_detection",
            cwd=str(Path.cwd()),
        )
        has_response = len(result.output) > 0
        record("Claude SDK 実行", has_response, f"output={result.output[:100]}")
        record(
            "セッションID取得",
            bool(result.session_id),
            f"session_id={result.session_id[:20] if result.session_id else 'none'}...",
        )
        record("コスト記録", result.cost_usd >= 0, f"cost=${result.cost_usd:.4f}")

    except Exception as e:
        record("Claude Agent Runner", False, f"{type(e).__name__}: {e}")


async def test_state_machine() -> None:
    """Step 6: 状態管理."""
    print("\n=== Step 6: State Machine ===")
    try:
        from ai_agent_orchestrator.event_logger import EventLogger
        from ai_agent_orchestrator.models import Phase
        from ai_agent_orchestrator.orchestrator.state_machine import StateMachineManager
        from ai_agent_orchestrator.state_persistence import StatePersistence

        persistence = StatePersistence(Path("/tmp/ai-agent-smoke-test/state.json"))
        logger = EventLogger(log_dir=Path("/tmp/ai-agent-smoke-test/logs"))
        sm = StateMachineManager(persistence=persistence, tracker=logger)

        # Issue登録 + タイプ設定
        sm.register_issue(9999, f"{REPO_OWNER}/{REPO_NAME}")
        sm.set_issue_type(9999, "bug")
        record("Issue登録", sm.get_phase(9999) == Phase.TYPE_DETECTION, f"phase={sm.get_phase(9999)}")
        record("タイプ設定", sm.get_issue_type(9999) == "bug", f"type={sm.get_issue_type(9999)}")

        # Bug ワークフロー遷移
        await sm.transition(9999, Phase.ANALYSIS)
        record("遷移 (TYPE_DETECTION→ANALYSIS)", sm.get_phase(9999) == Phase.ANALYSIS)

        await sm.transition(9999, Phase.PLAN_REVIEW)
        record("遷移 (ANALYSIS→PLAN_REVIEW)", sm.get_phase(9999) == Phase.PLAN_REVIEW)

        await sm.transition(9999, Phase.FIX)
        record("遷移 (PLAN_REVIEW→FIX)", sm.get_phase(9999) == Phase.FIX)

        # 永続化
        persistence.save(sm._states)
        loaded = persistence.load()
        record("状態永続化", 9999 in loaded, f"saved_phase={loaded[9999].phase if 9999 in loaded else 'none'}")

    except Exception as e:
        record("State Machine", False, f"{type(e).__name__}: {e}")


async def main() -> None:
    print("=" * 60)
    print("  実環境スモークテスト")
    print("=" * 60)

    await test_config_loading()
    await test_credential_resolution()
    await test_github_client()
    await test_workspace_manager()
    await test_claude_runner()
    await test_state_machine()

    # サマリ
    print("\n" + "=" * 60)
    print("  サマリ")
    print("=" * 60)
    passed = sum(1 for _, s, _ in RESULTS if s)
    failed = sum(1 for _, s, _ in RESULTS if not s)
    for name, success, _ in RESULTS:
        icon = "\u2705" if success else "\u274c"
        print(f"  {icon} {name}")
    print(f"\n  合計: {passed} PASS / {failed} FAIL / {len(RESULTS)} total")

    if failed > 0:
        print("\n  ❌ 失敗あり。修正が必要です。")
        sys.exit(1)
    else:
        print("\n  ✅ 全テスト通過。ai-agent start の実行準備完了。")


if __name__ == "__main__":
    asyncio.run(main())
