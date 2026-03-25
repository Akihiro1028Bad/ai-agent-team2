"""Feature-L ワークフロー検証: 分割提案 → 子Issue作成 → 依存管理."""

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
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
class FeatureLState:
    parent_issue_number: int = 0
    split_comment_id: int = 0
    child_issue_numbers: list[int] = None
    session_id: str = ""

    def __post_init__(self):
        if self.child_issue_numbers is None:
            self.child_issue_numbers = []


async def sdk_query(
    prompt: str,
    *,
    max_budget: float = 0.5,
    timeout: int = 300,
) -> dict:
    from claude_agent_sdk import query, ClaudeAgentOptions

    options = ClaudeAgentOptions(
        max_budget_usd=max_budget,
        permission_mode="plan",
    )

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


# ──────────────────────────────────────
# L1: 大規模Issue作成 + タイプ判定
# ──────────────────────────────────────
async def verify_l1_type_detection(state: FeatureLState) -> None:
    log("L1: 大規模Issue → Feature-L タイプ判定")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # 大規模Issue作成
    issue = await gh.rest.issues.async_create(
        REPO_OWNER, REPO_NAME,
        title="認証システムを全面刷新したい",
        body="""## 概要
現在のセッションベース認証をJWT + OAuth2.0に全面移行したい。

## やりたいこと
- JWT発行・検証ロジックの実装
- OAuth2.0プロバイダー連携（Google, GitHub）
- リフレッシュトークンの管理
- 既存APIエンドポイントの認証ミドルウェア置き換え
- ユーザーセッション管理のDB設計変更
- フロントエンドのログインフロー刷新（ソーシャルログインボタン追加）
- 権限管理（RBAC）の導入
- 管理者ダッシュボードのアクセス制御
- APIレート制限の実装
- セキュリティ監査ログの追加

## 備考
既存ユーザーの移行も考慮が必要。段階的に移行できるようにしたい。""",
        labels=["ai-agent"],
    )
    state.parent_issue_number = issue.parsed_data.number
    record("大規模Issue作成", True, f"Issue #{state.parent_issue_number}")

    # タイプ判定
    type_prompt = f"""あなたはIssueのタイプを判定するAIです。

## タイプ定義
- bug: バグ修正
- feature-s: 小規模機能（1-3ファイル変更）
- feature-m: 中規模機能（複数ファイル、設計書必要）
- feature-l: 大規模機能（分割が必要）

## Issue #{state.parent_issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## 回答形式
TYPE: <タイプ名>
REASON: <判定理由を1文で>"""

    result = await sdk_query(type_prompt, max_budget=0.3, timeout=120)
    state.session_id = result["session_id"]

    detected = "unknown"
    for t in ["bug", "feature-s", "feature-m", "feature-l"]:
        if t in result["result"].lower():
            detected = t
            break

    record(
        "タイプ判定 → feature-l",
        detected == "feature-l",
        f"判定={detected}, cost=${result['cost']:.4f}\n{result['result'][:200]}",
    )

    # ラベル付与
    await gh.rest.issues.async_add_labels(
        REPO_OWNER, REPO_NAME,
        state.parent_issue_number,
        labels=["type:feature-l"],
    )
    record("type:feature-l ラベル付与", True)


# ──────────────────────────────────────
# L2: 分割提案の生成
# ──────────────────────────────────────
async def verify_l2_split_proposal(state: FeatureLState) -> None:
    log("L2: 分割提案の生成")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    issue = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, state.parent_issue_number,
    )

    split_prompt = f"""あなたはソフトウェアアーキテクトです。
以下の大規模Issueを、独立して実装可能な小さなIssueに分割してください。

## Issue #{state.parent_issue_number}: {issue.parsed_data.title}
{issue.parsed_data.body}

## 分割のルール
1. 各子Issueは独立して実装・テスト可能であること
2. 依存関係がある場合は明示すること
3. 各子Issueはfeature-mサイズ（4-10ファイル変更）以下であること
4. 実装の優先順序を示すこと

## 出力形式（厳密に従ってください）
以下のJSON形式で出力してください。JSONのみを出力し、他のテキストは含めないでください。

```json
{{
  "split_reason": "分割理由",
  "children": [
    {{
      "title": "子Issueのタイトル",
      "body": "子Issueの詳細説明",
      "depends_on": [],
      "priority": 1,
      "estimated_type": "feature-m"
    }},
    {{
      "title": "子Issueのタイトル2",
      "body": "子Issueの詳細説明2",
      "depends_on": [1],
      "priority": 2,
      "estimated_type": "feature-m"
    }}
  ]
}}
```

depends_on は priority番号のリストです（例: [1] は priority 1 の子Issueに依存）。"""

    result = await sdk_query(split_prompt, max_budget=2.0, timeout=300)
    state.session_id = result["session_id"]

    # JSON抽出
    response = result["result"]
    json_str = ""
    if "```json" in response:
        json_str = response.split("```json")[1].split("```")[0].strip()
    elif "```" in response:
        json_str = response.split("```")[1].split("```")[0].strip()
    else:
        # JSONを直接探す
        import re
        match = re.search(r'\{[\s\S]*"children"[\s\S]*\}', response)
        if match:
            json_str = match.group()

    parsed = None
    try:
        parsed = json.loads(json_str)
    except (json.JSONDecodeError, Exception) as e:
        record("分割提案JSON解析", False, f"JSONパース失敗: {e}\nraw: {json_str[:300]}")
        return

    children = parsed.get("children", [])
    has_children = len(children) >= 3  # 大規模Issueなので3つ以上に分割されるはず
    has_deps = any(c.get("depends_on") for c in children)
    has_priority = all("priority" in c for c in children)

    record(
        "分割提案生成",
        has_children,
        f"子Issue数={len(children)}, 依存関係あり={has_deps}, 優先順あり={has_priority}\n"
        f"cost=${result['cost']:.4f}",
    )

    # 分割提案をIssueコメントとして投稿
    comment_body = f"""🔀 **分割提案 (AI分析)**

このIssueは大規模なため、以下の **{len(children)}個** の子Issueに分割することを提案します。

**分割理由:** {parsed.get('split_reason', 'N/A')}

| # | タイトル | 依存 | タイプ |
|---|---------|------|-------|
"""
    for i, c in enumerate(children, 1):
        deps = ", ".join([f"#{d}" for d in c.get("depends_on", [])]) or "なし"
        comment_body += f"| {i} | {c['title']} | {deps} | {c.get('estimated_type', 'feature-m')} |\n"

    comment_body += "\n👍 で承認 / コメントで修正指示をお願いします"

    comment = await gh.rest.issues.async_create_comment(
        REPO_OWNER, REPO_NAME,
        state.parent_issue_number,
        body=comment_body,
    )
    state.split_comment_id = comment.parsed_data.id
    record(
        "分割提案コメント投稿",
        comment.parsed_data.id > 0,
        f"comment_id={comment.parsed_data.id}",
    )

    # needs-split ラベル付与
    await gh.rest.issues.async_add_labels(
        REPO_OWNER, REPO_NAME,
        state.parent_issue_number,
        labels=["needs-split"],
    )
    record("needs-split ラベル付与", True)

    # 後続で使うためにparsed dataを保存
    state._parsed_split = parsed

    print(f"\n  --- 分割提案 ---")
    for i, c in enumerate(children, 1):
        print(f"  {i}. {c['title']} (deps={c.get('depends_on', [])})")


# ──────────────────────────────────────
# L3: 人間承認シミュレート + 子Issue作成
# ──────────────────────────────────────
async def verify_l3_child_issue_creation(state: FeatureLState) -> None:
    log("L3: 👍承認 → 子Issue自動作成")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    parsed = getattr(state, "_parsed_split", None)
    if not parsed:
        record("L3スキップ", False, "分割提案データがない")
        return

    children = parsed.get("children", [])

    # 👍リアクション承認シミュレート
    try:
        await gh.rest.reactions.async_create_for_issue_comment(
            REPO_OWNER, REPO_NAME,
            state.split_comment_id,
            content="+1",
        )
        record("👍 分割承認", True)
    except Exception as e:
        record("👍 分割承認", False, str(e)[:200])

    # 👍検知テスト
    reactions = await gh.rest.reactions.async_list_for_issue_comment(
        REPO_OWNER, REPO_NAME,
        state.split_comment_id,
    )
    has_thumbsup = any(r.content == "+1" for r in reactions.parsed_data)
    record("👍 検知", has_thumbsup)

    # 子Issue作成
    # priority → issue_number のマッピング（depends-on用）
    priority_to_issue: dict[int, int] = {}

    for i, child in enumerate(children):
        priority = child.get("priority", i + 1)
        deps = child.get("depends_on", [])

        # 依存ラベル生成
        labels = ["ai-agent", f"type:{child.get('estimated_type', 'feature-m')}"]
        for dep_priority in deps:
            dep_issue = priority_to_issue.get(dep_priority)
            if dep_issue:
                labels.append(f"depends-on:#{dep_issue}")

        # 子Issue本文
        body = f"""{child['body']}

---
**親Issue:** #{state.parent_issue_number}
**優先順位:** {priority}
**依存:** {', '.join([f'#{priority_to_issue[d]}' for d in deps if d in priority_to_issue]) or 'なし'}

_このIssueは AI Agent が自動分割して作成しました。_"""

        try:
            new_issue = await gh.rest.issues.async_create(
                REPO_OWNER, REPO_NAME,
                title=child["title"],
                body=body,
                labels=labels,
            )
            issue_num = new_issue.parsed_data.number
            state.child_issue_numbers.append(issue_num)
            priority_to_issue[priority] = issue_num
            record(
                f"子Issue #{issue_num} 作成",
                True,
                f"title={child['title'][:50]}, labels={labels}",
            )
        except Exception as e:
            record(f"子Issue作成失敗", False, str(e)[:200])

    # 最低3つの子Issueが作成されたか
    record(
        "子Issue作成(全体)",
        len(state.child_issue_numbers) >= 3,
        f"作成数={len(state.child_issue_numbers)}, issues={state.child_issue_numbers}",
    )


# ──────────────────────────────────────
# L4: ai-agent ラベル確認 + 依存ラベル確認
# ──────────────────────────────────────
async def verify_l4_labels(state: FeatureLState) -> None:
    log("L4: ラベル確認（ai-agent + depends-on）")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    if not state.child_issue_numbers:
        record("L4スキップ", False, "子Issueがない")
        return

    all_have_ai_agent = True
    has_depends_on = False

    for issue_num in state.child_issue_numbers:
        issue = await gh.rest.issues.async_get(
            REPO_OWNER, REPO_NAME, issue_num,
        )
        label_names = [l.name for l in issue.parsed_data.labels]

        has_ai = "ai-agent" in label_names
        if not has_ai:
            all_have_ai_agent = False

        has_dep = any(l.startswith("depends-on:") for l in label_names)
        if has_dep:
            has_depends_on = True

        record(
            f"子Issue #{issue_num} ラベル",
            has_ai,
            f"labels={label_names}",
        )

    record(
        "全子Issueに ai-agent ラベル",
        all_have_ai_agent,
    )
    record(
        "依存ラベル(depends-on)が存在",
        has_depends_on,
        "依存関係のある子Issueに depends-on ラベルが付いている" if has_depends_on else "依存ラベルなし",
    )


# ──────────────────────────────────────
# L5: 親Issueクローズ
# ──────────────────────────────────────
async def verify_l5_parent_close(state: FeatureLState) -> None:
    log("L5: 親Issueクローズ + 子Issueリンク")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    # 親Issueに完了コメント投稿
    child_links = "\n".join([f"- #{n}" for n in state.child_issue_numbers])
    close_comment = f"""✅ **分割完了**

このIssueは以下の子Issueに分割しました:

{child_links}

各子Issueは `ai-agent` ラベル付きで、自動的に処理されます。
このIssueをクローズします。"""

    comment = await gh.rest.issues.async_create_comment(
        REPO_OWNER, REPO_NAME,
        state.parent_issue_number,
        body=close_comment,
    )
    record(
        "親Issue完了コメント",
        comment.parsed_data.id > 0,
    )

    # 親Issueクローズ
    await gh.rest.issues.async_update(
        REPO_OWNER, REPO_NAME,
        state.parent_issue_number,
        state="closed",
        state_reason="completed",
    )

    # クローズ確認
    parent = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, state.parent_issue_number,
    )
    record(
        "親Issueクローズ",
        parent.parsed_data.state == "closed",
        f"state={parent.parsed_data.state}",
    )

    # needs-split ラベル除去
    try:
        await gh.rest.issues.async_remove_label(
            REPO_OWNER, REPO_NAME,
            state.parent_issue_number,
            "needs-split",
        )
        record("needs-split ラベル除去", True)
    except Exception:
        record("needs-split ラベル除去", False, "ラベルが存在しない可能性")


# ──────────────────────────────────────
# L6: 依存管理の検証
# ──────────────────────────────────────
async def verify_l6_dependency_check(state: FeatureLState) -> None:
    log("L6: 依存管理（depends-on Issueが未完了なら待機）")

    from githubkit import GitHub
    gh = GitHub(GITHUB_TOKEN)

    if len(state.child_issue_numbers) < 2:
        record("L6スキップ", False, "子Issueが2つ未満")
        return

    # 依存関係のある子Issueを探す
    dep_issue_num = None
    dep_target_num = None

    for issue_num in state.child_issue_numbers:
        issue = await gh.rest.issues.async_get(
            REPO_OWNER, REPO_NAME, issue_num,
        )
        label_names = [l.name for l in issue.parsed_data.labels]
        for label in label_names:
            if label.startswith("depends-on:#"):
                dep_issue_num = issue_num
                dep_target_num = int(label.split("#")[1])
                break
        if dep_issue_num:
            break

    if not dep_issue_num:
        record("依存関係チェック", True, "依存ラベルなし（全Issueが独立）→ 待機不要")
        return

    # 依存先がオープンかチェック
    dep_target = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, dep_target_num,
    )
    is_open = dep_target.parsed_data.state == "open"
    record(
        "依存先がオープン → 待機判定",
        is_open,
        f"Issue #{dep_issue_num} は #{dep_target_num} に依存, "
        f"dep_state={dep_target.parsed_data.state}",
    )

    # シミュレート: 依存先を完了（close）
    await gh.rest.issues.async_update(
        REPO_OWNER, REPO_NAME,
        dep_target_num,
        state="closed",
        state_reason="completed",
    )

    dep_target_after = await gh.rest.issues.async_get(
        REPO_OWNER, REPO_NAME, dep_target_num,
    )
    record(
        "依存先クローズ → 待機解除",
        dep_target_after.parsed_data.state == "closed",
        f"#{dep_target_num} closed → #{dep_issue_num} 処理可能",
    )

    # 元に戻す（reopen）
    await gh.rest.issues.async_update(
        REPO_OWNER, REPO_NAME,
        dep_target_num,
        state="open",
    )


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  Feature-L ワークフロー検証 L1-L6")
    print("=" * 60)

    state = FeatureLState()

    try:
        await verify_l1_type_detection(state)
        await verify_l2_split_proposal(state)
        await verify_l3_child_issue_creation(state)
        await verify_l4_labels(state)
        await verify_l5_parent_close(state)
        await verify_l6_dependency_check(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # サマリ
    log("Feature-L ワークフロー検証サマリ")
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

    result_path = Path(__file__).parent / "c_feature_l_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
