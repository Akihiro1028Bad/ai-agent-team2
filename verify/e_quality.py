"""品質検証 B1-B3: プロンプト出力品質 / コンテキストエンジン / Issue分割品質."""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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
class QualityState:
    tmp_dir: str = ""
    repo_dir: str = ""
    worktree_path: str = ""


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
    max_budget: float = 0.5,
    permission_mode: str = "plan",
    timeout: int = 300,
) -> dict:
    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        max_budget_usd=max_budget,
        permission_mode=permission_mode,
    )
    if cwd:
        options.cwd = cwd

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


async def setup_repo_with_code(state: QualityState) -> None:
    """テストリポにサンプルコードを配置してclone."""
    state.tmp_dir = tempfile.mkdtemp(prefix="ai-agent-quality-")
    repo_dir = Path(state.tmp_dir) / "repo"
    ok, _ = await run_git(
        "clone",
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}.git",
        str(repo_dir),
        cwd=state.tmp_dir,
    )
    assert ok, "clone failed"
    state.repo_dir = str(repo_dir)

    # サンプルコードを配置（品質検証用のコンテキスト）
    src = Path(state.repo_dir) / "src"
    src.mkdir(parents=True, exist_ok=True)

    # package.json
    (Path(state.repo_dir) / "package.json").write_text(json.dumps({
        "name": "sample-app",
        "version": "1.0.0",
        "scripts": {"dev": "next dev", "build": "next build", "test": "jest"},
        "dependencies": {"next": "^14.0.0", "react": "^18.0.0"},
        "devDependencies": {"jest": "^29.0.0", "typescript": "^5.0.0"},
    }, indent=2))

    # tsconfig.json
    (Path(state.repo_dir) / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {
            "target": "ES2022",
            "module": "ESNext",
            "strict": True,
            "jsx": "react-jsx",
            "outDir": "./dist",
        },
    }, indent=2))

    # src/types/user.ts
    types_dir = src / "types"
    types_dir.mkdir(parents=True, exist_ok=True)
    (types_dir / "user.ts").write_text("""export interface User {
  id: string;
  name: string;
  email: string;
  avatarUrl?: string;
  createdAt: Date;
}

export interface UserProfile extends User {
  bio?: string;
  location?: string;
  website?: string;
}
""")

    # src/api/client.ts
    api_dir = src / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "client.ts").write_text("""import { User, UserProfile } from '../types/user';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:3000/api';

export async function getUser(id: string): Promise<User> {
  const res = await fetch(`${API_BASE}/users/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch user: ${res.status}`);
  return res.json();
}

export async function getUserProfile(id: string): Promise<UserProfile> {
  const res = await fetch(`${API_BASE}/users/${id}/profile`);
  if (!res.ok) throw new Error(`Failed to fetch profile: ${res.status}`);
  return res.json();
}

export async function updateUser(id: string, data: Partial<User>): Promise<User> {
  const res = await fetch(`${API_BASE}/users/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to update user: ${res.status}`);
  return res.json();
}
""")

    # src/components/UserCard.tsx
    comp_dir = src / "components"
    comp_dir.mkdir(parents=True, exist_ok=True)
    (comp_dir / "UserCard.tsx").write_text("""import React from 'react';
import { User } from '../types/user';

interface UserCardProps {
  user: User;
  onClick?: (user: User) => void;
}

export const UserCard: React.FC<UserCardProps> = ({ user, onClick }) => {
  return (
    <div className="user-card" onClick={() => onClick?.(user)}>
      <img src={user.avatarUrl || '/default-avatar.png'} alt={user.name} />
      <h3>{user.name}</h3>
      <p>{user.email}</p>
    </div>
  );
};
""")

    # src/hooks/useUser.ts
    hooks_dir = src / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "useUser.ts").write_text("""import { useState, useEffect } from 'react';
import { User } from '../types/user';
import { getUser } from '../api/client';

export function useUser(id: string) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    setLoading(true);
    getUser(id)
      .then(setUser)
      .catch(setError)
      .finally(() => setLoading(false));
  }, [id]);

  return { user, loading, error };
}
""")

    # CLAUDE.md
    (Path(state.repo_dir) / "CLAUDE.md").write_text("""# CLAUDE.md

## プロジェクト概要
Next.js + TypeScript のサンプルWebアプリケーション。

## コマンド
- 開発サーバー: `npm run dev`
- ビルド: `npm run build`
- テスト: `npm test`

## コーディング規約
- 関数コンポーネント + hooks パターン
- 型定義は src/types/ に集約
- APIクライアントは src/api/ に集約
- コンポーネントは src/components/ に配置
""")

    # git commit
    await run_git("add", ".", cwd=state.repo_dir)
    await run_git("commit", "-m", "chore: add sample code for quality testing", cwd=state.repo_dir)
    await run_git("push", "origin", "main", cwd=state.repo_dir)


async def cleanup(state: QualityState) -> None:
    if state.tmp_dir:
        shutil.rmtree(state.tmp_dir, ignore_errors=True)


# ──────────────────────────────────────
# B1: プロンプトの出力品質
# ──────────────────────────────────────
async def verify_b1_prompt_quality(state: QualityState) -> None:
    log("B1: プロンプトの出力品質")

    # ── B1-1: Bug分析の品質 ──
    bug_prompt = """あなたはバグ修正を担当するエンジニアです。以下のバグを分析して修正方針を作成してください。

## Issue: useUser hookでユーザー情報を取得するとTypeErrorが発生する

### 不具合の内容
```
TypeError: Cannot read properties of undefined (reading 'name')
    at UserCard (src/components/UserCard.tsx:12)
```

ユーザー一覧画面でUserCardコンポーネントがレンダリングされる際にエラーが発生する。

### 再現手順
1. /users ページにアクセス
2. ユーザーIDが存在しないユーザーのカードを表示しようとする
3. TypeErrorが発生

## リポジトリ構成
- src/types/user.ts (User型定義)
- src/api/client.ts (APIクライアント)
- src/components/UserCard.tsx (ユーザーカードコンポーネント)
- src/hooks/useUser.ts (ユーザー取得hook)

## 出力形式
🔍 **修正方針 (AI分析)** のフォーマットで出力してください。
原因、発生条件、修正内容(ファイル+修正内容のテーブル)、影響範囲、テスト方針を含めてください。"""

    bug_result = await sdk_query(bug_prompt, cwd=state.repo_dir, max_budget=1.0, timeout=180)
    r = bug_result["result"]

    # 品質チェック項目
    checks = {
        "原因にファイルパス含む": "src/" in r and ("UserCard" in r or "useUser" in r or "client" in r),
        "修正対象ファイルが具体的": "UserCard.tsx" in r or "useUser.ts" in r or "client.ts" in r,
        "nullチェック言及": "null" in r.lower() or "undefined" in r.lower() or "optional" in r.lower(),
        "テスト方針がある": "テスト" in r,
        "承認案内(👍)がある": "👍" in r,
        "表形式(テーブル)がある": "|" in r and "---" in r,
    }

    all_pass = all(checks.values())
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B1-1: Bug分析品質",
        all_pass,
        f"cost=${bug_result['cost']:.4f}\n" + "\n".join(detail_lines),
    )
    print(f"\n  --- Bug分析出力 (先頭600文字) ---\n  {r[:600]}")

    # ── B1-2: Feature-S 方針の品質 ──
    plan_prompt = """あなたはソフトウェアエンジニアです。以下のIssueの簡易実装方針を作成してください。

## Issue: UserCardコンポーネントにローディングスケルトンを追加したい

UserCardコンポーネントでユーザー情報取得中にスケルトンUIを表示したい。

## リポジトリ構成
- src/types/user.ts
- src/api/client.ts
- src/components/UserCard.tsx
- src/hooks/useUser.ts

## 出力形式
📋 **実装方針 (AI提案)** のフォーマットで出力してください。
変更内容（ファイル + 変更内容）とテスト方針を含めてください。"""

    plan_result = await sdk_query(plan_prompt, cwd=state.repo_dir, max_budget=1.0, timeout=180)
    r = plan_result["result"]

    checks = {
        "変更ファイルが具体的": "UserCard" in r or "Skeleton" in r,
        "変更内容が明確": "変更" in r or "追加" in r or "作成" in r,
        "変更ファイル数が適正(1-3)": r.count("src/") <= 5,
        "テスト方針がある": "テスト" in r,
        "承認案内(👍)がある": "👍" in r,
    }

    all_pass = all(checks.values())
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B1-2: Feature-S方針品質",
        all_pass,
        f"cost=${plan_result['cost']:.4f}\n" + "\n".join(detail_lines),
    )
    print(f"\n  --- Feature-S方針出力 (先頭600文字) ---\n  {r[:600]}")

    # ── B1-3: Feature-M 設計書の品質 ──
    design_prompt = """あなたはソフトウェアアーキテクトです。以下のIssueの設計書を作成してください。

## Issue: ユーザー検索機能を追加したい

ユーザー一覧画面に検索バーを追加し、名前・メールアドレスで検索できるようにしたい。
リアルタイム検索（デバウンス付き）で、検索結果は既存のUserCardコンポーネントで表示。

## リポジトリ構成
- src/types/user.ts (User型定義)
- src/api/client.ts (APIクライアント)
- src/components/UserCard.tsx (ユーザーカード)
- src/hooks/useUser.ts (ユーザー取得hook)
- CLAUDE.md (プロジェクト設定)

## 設計書テンプレート
1. 概要
2. 背景・動機
3. 影響範囲 (変更するファイル一覧テーブル)
4. 実装方針
5. データ構造の変更
6. API変更
7. テスト方針
8. リスク・懸念事項
9. 見積もり (S/M/L)

全セクションを埋めてください。"""

    design_result = await sdk_query(design_prompt, cwd=state.repo_dir, max_budget=2.0, timeout=300)
    r = design_result["result"]

    checks = {
        "概要セクション": "概要" in r,
        "影響範囲テーブル": "|" in r and ("ファイル" in r or "変更" in r),
        "実装方針が具体的": "実装" in r and ("コンポーネント" in r or "hook" in r or "API" in r),
        "API変更の記載": "API" in r,
        "テスト方針": "テスト" in r,
        "見積もり": "S" in r or "M" in r or "L" in r,
        "デバウンス言及": "デバウンス" in r or "debounce" in r.lower(),
        "既存コンポーネント活用": "UserCard" in r,
    }

    all_pass = sum(checks.values()) >= 6  # 8項目中6以上でPASS
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B1-3: Feature-M設計書品質",
        all_pass,
        f"cost=${design_result['cost']:.4f}, score={sum(checks.values())}/8\n" + "\n".join(detail_lines),
    )
    print(f"\n  --- Feature-M設計書出力 (先頭800文字) ---\n  {r[:800]}")


# ──────────────────────────────────────
# B2: コンテキストエンジン（リポマップ + 関連ファイル検索）
# ──────────────────────────────────────
async def verify_b2_context_engine(state: QualityState) -> None:
    log("B2: コンテキストエンジン")

    # ── B2-1: リポマップ生成 ──
    repomap_prompt = """このリポジトリの構成を分析して、以下の形式でリポマップを出力してください。

## 出力形式
```
ディレクトリ構成:
  [ファイルパス]: [役割の1行説明]

主要な型/インターフェース:
  [型名]: [定義場所] - [説明]

主要な関数/コンポーネント:
  [名前]: [定義場所] - [説明]

依存関係:
  [ファイルA] → [ファイルB] (import関係)
```

リポジトリ内のファイルを実際に読んで分析してください。"""

    repomap_result = await sdk_query(
        repomap_prompt,
        cwd=state.repo_dir,
        max_budget=1.0,
        permission_mode="acceptEdits",
        timeout=300,
    )
    r = repomap_result["result"]

    checks = {
        "ファイル一覧含む": "user.ts" in r or "client.ts" in r or "UserCard" in r,
        "型定義を検出": "User" in r and ("interface" in r or "型" in r),
        "API関数を検出": "getUser" in r or "getUserProfile" in r,
        "コンポーネントを検出": "UserCard" in r,
        "hookを検出": "useUser" in r,
        "依存関係を検出": "import" in r or "→" in r or "依存" in r,
    }

    all_pass = sum(checks.values()) >= 4
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B2-1: リポマップ生成",
        all_pass,
        f"cost=${repomap_result['cost']:.4f}, score={sum(checks.values())}/6\n" + "\n".join(detail_lines),
    )

    # ── B2-2: 関連ファイル検索 ──
    search_prompt = """以下のIssueに関連するファイルをこのリポジトリから特定してください。

## Issue: UserCardコンポーネントでアバター画像が表示されないバグ

リポジトリ内のファイルを実際に読んで、このバグに関連するファイルをリストアップしてください。

## 出力形式
関連度が高い順に:
1. [ファイルパス] - [関連理由]
2. [ファイルパス] - [関連理由]
..."""

    search_result = await sdk_query(
        search_prompt,
        cwd=state.repo_dir,
        max_budget=1.0,
        permission_mode="acceptEdits",
        timeout=300,
    )
    r = search_result["result"]

    checks = {
        "UserCard.tsx を検出": "UserCard.tsx" in r or "UserCard" in r,
        "user.ts (型) を検出": "user.ts" in r,
        "avatarUrl に言及": "avatar" in r.lower(),
        "関連度順": "1." in r and "2." in r,
    }

    all_pass = sum(checks.values()) >= 3
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B2-2: 関連ファイル検索",
        all_pass,
        f"cost=${search_result['cost']:.4f}, score={sum(checks.values())}/4\n" + "\n".join(detail_lines),
    )

    # ── B2-3: CLAUDE.md 活用 ──
    claude_md_prompt = """このリポジトリのCLAUDE.mdを読んで、その内容に基づいてコーディング規約に従ったコンポーネントの雛形を出力してください。

コンポーネント名: SearchBar
目的: ユーザー検索用の入力欄

CLAUDE.mdの規約に従って出力してください。"""

    claudemd_result = await sdk_query(
        claude_md_prompt,
        cwd=state.repo_dir,
        max_budget=1.0,
        permission_mode="acceptEdits",
        timeout=300,
    )
    r = claudemd_result["result"]

    checks = {
        "関数コンポーネント": "React.FC" in r or "const SearchBar" in r or "function SearchBar" in r,
        "TypeScript型あり": "interface" in r or "type " in r or "Props" in r,
        "hooks使用": "useState" in r or "useEffect" in r or "use" in r,
    }

    all_pass = sum(checks.values()) >= 2
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B2-3: CLAUDE.md規約準拠",
        all_pass,
        f"cost=${claudemd_result['cost']:.4f}, score={sum(checks.values())}/3\n" + "\n".join(detail_lines),
    )


# ──────────────────────────────────────
# B3: Issue分割提案の品質
# ──────────────────────────────────────
async def verify_b3_split_quality(state: QualityState) -> None:
    log("B3: Issue分割提案の品質")

    split_prompt = """あなたはソフトウェアアーキテクトです。以下の大規模Issueを分割してください。

## Issue: ユーザー管理システムの全面リニューアル

### やりたいこと
1. ユーザー一覧画面のリデザイン（グリッド/リスト切り替え、ソート、ページネーション）
2. ユーザー検索機能（リアルタイム検索、フィルター）
3. ユーザープロフィール編集画面（アバターアップロード、フォームバリデーション）
4. ユーザー招待機能（メール送信、招待リンク生成）
5. ユーザーロール管理（管理者/一般ユーザー/閲覧者）
6. アクティビティログ表示
7. ユーザーCSVエクスポート/インポート

## リポジトリ構成
- src/types/user.ts
- src/api/client.ts
- src/components/UserCard.tsx
- src/hooks/useUser.ts

## 分割ルール
1. 各子Issueは独立して実装・テスト可能
2. 依存関係を明示
3. feature-m サイズ以下
4. 優先順序を示す

## 出力形式（JSON）
```json
{
  "children": [
    {
      "title": "タイトル",
      "body": "詳細説明",
      "depends_on": [],
      "priority": 1,
      "estimated_type": "feature-m",
      "estimated_files": ["src/..."]
    }
  ]
}
```"""

    result = await sdk_query(split_prompt, max_budget=2.0, timeout=300)
    r = result["result"]

    # JSON抽出
    import re
    json_str = ""
    if "```json" in r:
        json_str = r.split("```json")[1].split("```")[0].strip()
    elif "```" in r:
        json_str = r.split("```")[1].split("```")[0].strip()
    else:
        match = re.search(r'\{[\s\S]*"children"[\s\S]*\}', r)
        if match:
            json_str = match.group()

    parsed = None
    try:
        parsed = json.loads(json_str)
    except Exception as e:
        record("B3: JSON解析", False, f"JSONパース失敗: {e}")
        return

    children = parsed.get("children", [])

    # 品質チェック
    checks = {
        "3個以上に分割": len(children) >= 3,
        "7個以下に分割（過度に細かくない）": len(children) <= 7,
        "全てにタイトルあり": all("title" in c for c in children),
        "全てにbodyあり": all("body" in c and len(c["body"]) > 20 for c in children),
        "依存関係が設定されている": any(c.get("depends_on") for c in children),
        "優先順序がある": all("priority" in c for c in children),
        "estimated_filesがある": any("estimated_files" in c for c in children),
        "最初のIssueは依存なし": children[0].get("depends_on", []) == [] if children else False,
        "循環依存なし": _check_no_circular_deps(children),
    }

    all_pass = sum(checks.values()) >= 7
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "B3: Issue分割品質",
        all_pass,
        f"cost=${result['cost']:.4f}, 分割数={len(children)}, score={sum(checks.values())}/9\n"
        + "\n".join(detail_lines),
    )

    print(f"\n  --- 分割結果 ---")
    for i, c in enumerate(children):
        deps = c.get("depends_on", [])
        print(f"  {c.get('priority', i+1)}. {c['title']} (deps={deps})")


def _check_no_circular_deps(children: list[dict]) -> bool:
    """循環依存がないか確認."""
    # priority -> deps のグラフ
    graph: dict[int, list[int]] = {}
    for c in children:
        p = c.get("priority", 0)
        graph[p] = c.get("depends_on", [])

    visited: set[int] = set()
    path: set[int] = set()

    def dfs(node: int) -> bool:
        if node in path:
            return True  # 循環検出
        if node in visited:
            return False
        visited.add(node)
        path.add(node)
        for dep in graph.get(node, []):
            if dfs(dep):
                return True
        path.discard(node)
        return False

    for node in graph:
        if dfs(node):
            return False
    return True


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  品質検証 B1-B3")
    print("=" * 60)

    state = QualityState()

    try:
        await setup_repo_with_code(state)
        await verify_b1_prompt_quality(state)
        await verify_b2_context_engine(state)
        await verify_b3_split_quality(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await cleanup(state)

    # サマリ
    log("品質検証サマリ")
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

    result_path = Path(__file__).parent / "e_quality_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
