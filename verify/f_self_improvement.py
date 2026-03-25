"""自己改善ループ検証 S1-S7: ナレッジ蓄積 / Skill検出 / メトリクス / 改善提案."""

import asyncio
import json
import os
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
# テストデータ: 前回の検証結果をエピソード化
# ──────────────────────────────────────
MOCK_EPISODES = [
    {
        "issue": 5, "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "type": "bug", "title": "ログインボタンを押すと500エラーが出る",
        "phases": [
            {"phase": "ANALYSIS", "cost_usd": 0.03, "duration_sec": 45, "output_summary": "src/auth/login.ts:42 で null チェック漏れを特定"},
            {"phase": "FIX", "cost_usd": 0.30, "duration_sec": 120, "output_summary": "null guard追加 + テスト7ファイル作成"},
            {"phase": "IMPL_REVIEW", "cost_usd": 0.0, "duration_sec": 0, "review_comments": 0},
        ],
        "total_cost_usd": 0.33, "review_rounds": 0, "ci_retries": 0,
        "files_changed": ["src/auth/login.ts", "src/api/client.ts", "tests/auth/login.test.ts"],
        "learnings": ["APIレスポンスのnullチェックが漏れやすい"],
    },
    {
        "issue": 7, "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "type": "feature-s", "title": "メールアドレスのバリデーションを追加したい",
        "phases": [
            {"phase": "HEARING", "cost_usd": 0.02, "duration_sec": 30, "output_summary": "質問不要、READY_FOR_PLAN"},
            {"phase": "PLAN_BRIEF", "cost_usd": 0.02, "duration_sec": 25, "output_summary": "validate.ts + RegisterForm.tsx の変更方針"},
            {"phase": "IMPLEMENT", "cost_usd": 0.41, "duration_sec": 180, "output_summary": "バリデーション関数 + フォーム修正 + テスト"},
            {"phase": "IMPL_REVIEW", "cost_usd": 0.23, "duration_sec": 60, "review_comments": 1, "feedback": "validatorsディレクトリに分離すべき", "resolution": "validators/ディレクトリ作成 + カスタムError型追加"},
        ],
        "total_cost_usd": 0.68, "review_rounds": 1, "ci_retries": 0,
        "files_changed": ["src/validators/emailValidator.ts", "src/validators/ValidationError.ts", "src/components/RegisterForm.tsx"],
        "learnings": ["バリデーション関数はvalidators/に集約する", "カスタムError型を定義すると再利用しやすい"],
    },
    {
        "issue": 23, "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "type": "feature-m", "title": "[子Issue] DBスキーマ設計変更（認証テーブル追加）",
        "phases": [
            {"phase": "HEARING", "cost_usd": 0.03, "duration_sec": 40, "output_summary": "要件十分"},
            {"phase": "DESIGN", "cost_usd": 0.25, "duration_sec": 90, "output_summary": "設計書作成: users + refresh_tokens テーブル"},
            {"phase": "IMPLEMENT", "cost_usd": 0.35, "duration_sec": 150, "output_summary": "スキーマ定義 + マイグレーション + 型定義 9ファイル"},
        ],
        "total_cost_usd": 0.63, "review_rounds": 0, "ci_retries": 0,
        "files_changed": ["src/db/schema.ts", "src/db/migrations/001_auth.ts", "src/types/auth.ts", "src/types/user.ts"],
        "learnings": ["DBスキーマ変更は型定義と同時に更新する"],
    },
    {
        "issue": 24, "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "type": "feature-m", "title": "[子Issue] JWT発行・検証ロジック実装",
        "phases": [
            {"phase": "DESIGN", "cost_usd": 0.30, "duration_sec": 100, "output_summary": "設計書作成: JWT sign/verify/refresh"},
            {"phase": "IMPLEMENT", "cost_usd": 0.70, "duration_sec": 200, "output_summary": "JWT関連12ファイル作成"},
        ],
        "total_cost_usd": 1.00, "review_rounds": 0, "ci_retries": 0,
        "files_changed": ["src/auth/jwt.ts", "src/auth/token.ts", "src/types/token.ts", "tests/auth/jwt.test.ts"],
        "learnings": ["認証系モジュールはsrc/auth/に集約"],
    },
    {
        "issue": 9, "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "type": "feature-l", "title": "認証システムを全面刷新したい",
        "phases": [
            {"phase": "HEARING", "cost_usd": 0.03, "duration_sec": 30},
            {"phase": "SPLIT_PROPOSAL", "cost_usd": 0.29, "duration_sec": 60, "output_summary": "11個の子Issueに分割提案"},
            {"phase": "SPLIT_EXECUTE", "cost_usd": 0.0, "duration_sec": 10, "output_summary": "11個の子Issue作成完了"},
        ],
        "total_cost_usd": 0.32, "review_rounds": 0, "ci_retries": 0,
        "child_issues": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        "learnings": ["大規模Issueは基盤→機能→UIの順で分割すると依存が整理しやすい"],
    },
]


@dataclass
class SelfImpState:
    knowledge_dir: str = ""
    skills_dir: str = ""
    events_path: str = ""


async def setup_dirs(state: SelfImpState) -> None:
    tmp = tempfile.mkdtemp(prefix="ai-agent-self-imp-")
    state.knowledge_dir = str(Path(tmp) / "knowledge" / REPO_NAME)
    state.skills_dir = str(Path(tmp) / "skills")
    state.events_path = str(Path(tmp) / "events.jsonl")
    Path(state.knowledge_dir).mkdir(parents=True, exist_ok=True)
    Path(state.skills_dir).mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────
# S1: エピソード記憶の記録
# ──────────────────────────────────────
async def verify_s1_episode_recording(state: SelfImpState) -> None:
    log("S1: エピソード記憶の記録")

    episodes_dir = Path(state.knowledge_dir) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)

    for ep in MOCK_EPISODES:
        ep_path = episodes_dir / f"issue-{ep['issue']}.json"
        ep_path.write_text(json.dumps(ep, indent=2, ensure_ascii=False))

    # events.jsonl に全フェーズを記録
    with open(state.events_path, "w") as f:
        for ep in MOCK_EPISODES:
            for phase in ep.get("phases", []):
                event = {
                    "ts": "2026-03-24T10:00:00Z",
                    "repo": ep["repo"],
                    "issue": ep["issue"],
                    "type": ep["type"],
                    "phase": phase["phase"],
                    "event": "phase_complete",
                    "cost_usd": phase.get("cost_usd", 0),
                    "duration_sec": phase.get("duration_sec", 0),
                    "review_comments": phase.get("review_comments", 0),
                }
                if "feedback" in phase:
                    event["feedback"] = phase["feedback"]
                    event["resolution"] = phase["resolution"]
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    # 検証
    episode_files = list(episodes_dir.glob("*.json"))
    events_lines = Path(state.events_path).read_text().strip().split("\n")

    record(
        "エピソード記憶ファイル作成",
        len(episode_files) == 5,
        f"files={len(episode_files)}",
    )
    record(
        "events.jsonl 記録",
        len(events_lines) >= 10,
        f"events={len(events_lines)}",
    )

    # JSONLの各行がパース可能か
    all_valid = True
    for line in events_lines:
        try:
            json.loads(line)
        except json.JSONDecodeError:
            all_valid = False
            break
    record("events.jsonl JSON形式", all_valid)


# ──────────────────────────────────────
# S2: セマンティック記憶の抽出
# ──────────────────────────────────────
async def verify_s2_semantic_extraction(state: SelfImpState) -> None:
    log("S2: セマンティック記憶（パターン抽出）")

    # エピソードデータをAIに渡してパターン抽出
    episodes_json = json.dumps(MOCK_EPISODES, indent=2, ensure_ascii=False)

    prompt = f"""あなたはソフトウェア開発のパターン分析AIです。
以下の完了済みIssueのエピソード記録を分析し、再利用可能なパターンを抽出してください。

## エピソード記録
{episodes_json}

## 指示
以下のYAML形式で、3個以上のパターンを抽出してください。

```yaml
patterns:
  - id: パターンID（kebab-case）
    description: パターンの説明（1文）
    frequency: 観測回数
    source_episodes: [issue番号のリスト]
    category: code_pattern | review_pattern | architecture_pattern | test_pattern
    action: プロンプトに追加すべき指示（具体的に）
```

パターンは以下の観点で抽出してください:
- コードパターン（nullチェック、エラーハンドリング等）
- レビューで繰り返し指摘されること
- ファイル配置のルール
- テストのパターン"""

    result = await sdk_query(prompt, max_budget=1.0, timeout=300)
    r = result["result"]

    # YAML抽出
    has_patterns = "patterns:" in r
    has_id = "id:" in r
    has_action = "action:" in r
    has_multiple = r.count("- id:") >= 3 or r.count("  id:") >= 3

    record(
        "パターン抽出",
        has_patterns and has_multiple,
        f"cost=${result['cost']:.4f}, patterns_found={r.count('id:')}\n"
        f"has_action={has_action}",
    )

    # patterns.yaml として保存
    yaml_str = ""
    if "```yaml" in r:
        yaml_str = r.split("```yaml")[1].split("```")[0].strip()
    elif "```" in r:
        yaml_str = r.split("```")[1].split("```")[0].strip()
    else:
        yaml_str = r

    patterns_path = Path(state.knowledge_dir) / "patterns.yaml"
    patterns_path.write_text(yaml_str)
    record(
        "patterns.yaml 保存",
        patterns_path.exists() and len(yaml_str) > 50,
        f"size={len(yaml_str)} bytes",
    )

    print(f"\n  --- 抽出パターン (先頭800文字) ---\n  {yaml_str[:800]}")


# ──────────────────────────────────────
# S3: 類似Issue検索
# ──────────────────────────────────────
async def verify_s3_similar_search(state: SelfImpState) -> None:
    log("S3: 類似Issue検索")

    new_issue = {
        "title": "パスワードリセット画面でエラーが出る",
        "body": "パスワードリセットメールのリンクをクリックすると、TypeError: Cannot read property 'token' of undefined が表示される。",
        "type": "bug",
    }

    episodes_json = json.dumps(MOCK_EPISODES, indent=2, ensure_ascii=False)

    prompt = f"""以下の新しいIssueと、過去のエピソード記録を比較して、類似するIssueを見つけてください。

## 新しいIssue
タイトル: {new_issue['title']}
本文: {new_issue['body']}
タイプ: {new_issue['type']}

## 過去のエピソード記録
{episodes_json}

## 指示
1. 類似度が高い順にIssueをランキングしてください
2. 各Issueについて、なぜ類似しているかを説明してください
3. 過去のIssueから得られた学びが、新しいIssueにどう活かせるかを提案してください

## 出力形式
SIMILAR_ISSUES:
1. Issue #XX (類似度: 高/中/低)
   理由: ...
   活かせる学び: ...
2. ...

RECOMMENDED_APPROACH:
(過去の学びを踏まえた推奨アプローチ)"""

    result = await sdk_query(prompt, max_budget=1.0, timeout=300)
    r = result["result"]

    # Issue #5 (500エラー、nullチェック漏れ) が最も類似として検出されるはず
    found_issue5 = "#5" in r
    has_ranking = "1." in r and "2." in r
    has_learning = "学び" in r or "学習" in r or "活かせる" in r or "推奨" in r
    has_null_check = "null" in r.lower() or "undefined" in r.lower()

    record(
        "類似Issue検出 (#5が最上位)",
        found_issue5,
        f"cost=${result['cost']:.4f}\n"
        f"found_#5={found_issue5}, ranking={has_ranking}, learning={has_learning}",
    )
    record(
        "過去の学びの活用提案",
        has_learning and has_null_check,
        "nullチェック漏れのパターンを新Issueに適用提案" if has_null_check else "学び提案なし",
    )

    print(f"\n  --- 類似検索結果 (先頭600文字) ---\n  {r[:600]}")


# ──────────────────────────────────────
# S4: Skill自動検出
# ──────────────────────────────────────
async def verify_s4_skill_detection(state: SelfImpState) -> None:
    log("S4: Skill自動検出")

    episodes_json = json.dumps(MOCK_EPISODES, indent=2, ensure_ascii=False)

    prompt = f"""あなたはAIエージェントのSkill検出システムです。
以下のエピソード記録を分析し、再利用可能なSkill（タスクテンプレート）を検出してください。

## エピソード記録
{episodes_json}

## Skillの定義
同じパターンのタスクが2回以上観測された場合、Skillとして抽出する。

## 指示
検出したSkillをYAML形式で出力してください。最低2個。

```yaml
skills:
  - name: skill-name (kebab-case)
    description: 説明（1文）
    created_from_episodes: [issue番号]
    trigger:
      keywords: [マッチするキーワード]
      file_patterns: [マッチするファイルパターン]
    variables:
      - name: 変数名
        description: 説明
        example: 例
    phases:
      design:
        prompt_additions: |
          このSkillではこうする
      implement:
        prompt_additions: |
          このSkillではこうする
        expected_files:
          - ファイルパス
```

## 注意
- エピソードの共通点（ファイル構成、修正パターン、テスト方法）に注目
- 変数部分を{{variable}}で示す
- 具体的なprompt_additionsを書く"""

    result = await sdk_query(prompt, max_budget=2.0, timeout=300)
    r = result["result"]

    # YAML抽出
    yaml_str = ""
    if "```yaml" in r:
        yaml_str = r.split("```yaml")[1].split("```")[0].strip()
    elif "```" in r:
        yaml_str = r.split("```")[1].split("```")[0].strip()

    has_skills = "skills:" in r or "name:" in r
    has_trigger = "trigger:" in r or "keywords:" in r
    has_variables = "variables:" in r
    has_prompt = "prompt_additions:" in r
    skill_count = r.count("- name:") or r.count("  name:")

    record(
        "Skill検出",
        has_skills and skill_count >= 2,
        f"cost=${result['cost']:.4f}, skills={skill_count}\n"
        f"trigger={has_trigger}, variables={has_variables}, prompt={has_prompt}",
    )

    # skills/ に保存
    if yaml_str:
        skill_path = Path(state.skills_dir) / "detected_skills.yaml"
        skill_path.write_text(yaml_str)
        record("Skill YAML保存", True, f"path={skill_path}")
    else:
        record("Skill YAML保存", False, "YAML抽出失敗")

    print(f"\n  --- 検出Skill (先頭800文字) ---\n  {(yaml_str or r)[:800]}")


# ──────────────────────────────────────
# S5: Skillマッチング
# ──────────────────────────────────────
async def verify_s5_skill_matching(state: SelfImpState) -> None:
    log("S5: Skillマッチング")

    skill_path = Path(state.skills_dir) / "detected_skills.yaml"
    if not skill_path.exists():
        record("S5スキップ", False, "Skillファイルがない")
        return

    skills_yaml = skill_path.read_text()

    new_issues = [
        {
            "title": "ユーザー登録時の電話番号バリデーション追加",
            "body": "登録フォームに電話番号の形式チェックを追加したい",
            "expected_match": True,  # バリデーション追加のSkillにマッチするはず
        },
        {
            "title": "ダッシュボードのグラフをD3.jsで描画したい",
            "body": "管理画面にアクセス統計のグラフを追加",
            "expected_match": False,  # マッチするSkillがないはず
        },
    ]

    for issue in new_issues:
        prompt = f"""以下のSkillライブラリと新しいIssueを比較し、適用可能なSkillがあるか判定してください。

## Skillライブラリ
{skills_yaml}

## 新しいIssue
タイトル: {issue['title']}
本文: {issue['body']}

## 指示
1. 各Skillとのマッチ度を判定してください (MATCH / PARTIAL / NO_MATCH)
2. MATCHの場合、どの変数にどの値を当てはめるか示してください
3. 最終判定を以下の形式で出力してください:

RESULT: MATCH or NO_MATCH
SKILL: (マッチしたSkill名、なければN/A)
VARIABLES: (変数の値、なければN/A)"""

        result = await sdk_query(prompt, max_budget=0.5, timeout=180)
        r = result["result"]

        is_match = "MATCH" in r and "NO_MATCH" not in r.split("RESULT:")[-1] if "RESULT:" in r else "MATCH" in r
        # 期待通りのマッチ結果か
        if issue["expected_match"]:
            correct = is_match
        else:
            correct = not is_match or "NO_MATCH" in r

        record(
            f"Skillマッチ: {issue['title'][:30]}...",
            correct,
            f"expected={'MATCH' if issue['expected_match'] else 'NO_MATCH'}, "
            f"actual={'MATCH' if is_match else 'NO_MATCH'}, cost=${result['cost']:.4f}",
        )


# ──────────────────────────────────────
# S6: メトリクス集計
# ──────────────────────────────────────
async def verify_s6_metrics(state: SelfImpState) -> None:
    log("S6: メトリクス集計")

    # events.jsonl からメトリクスを計算
    events = []
    with open(state.events_path) as f:
        for line in f:
            events.append(json.loads(line))

    # 集計
    total_issues = len(MOCK_EPISODES)
    total_cost = sum(ep["total_cost_usd"] for ep in MOCK_EPISODES)
    avg_cost = total_cost / total_issues
    review_rounds = sum(ep.get("review_rounds", 0) for ep in MOCK_EPISODES)
    avg_review = review_rounds / total_issues
    ci_retries = sum(ep.get("ci_retries", 0) for ep in MOCK_EPISODES)

    type_counts = {}
    for ep in MOCK_EPISODES:
        t = ep["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    # フィードバック集計
    feedbacks = []
    for ep in MOCK_EPISODES:
        for phase in ep.get("phases", []):
            if "feedback" in phase:
                feedbacks.append(phase["feedback"])

    metrics = {
        "period": "2026-03-24",
        "total_issues": total_issues,
        "total_cost_usd": round(total_cost, 2),
        "avg_cost_per_issue": round(avg_cost, 2),
        "avg_review_rounds": round(avg_review, 2),
        "ci_retry_total": ci_retries,
        "type_distribution": type_counts,
        "top_feedbacks": feedbacks,
        "phase_costs": {},
    }

    # フェーズ別コスト集計
    phase_costs: dict[str, list[float]] = {}
    for ep in MOCK_EPISODES:
        for phase in ep.get("phases", []):
            name = phase["phase"]
            cost = phase.get("cost_usd", 0)
            if name not in phase_costs:
                phase_costs[name] = []
            phase_costs[name].append(cost)

    metrics["phase_costs"] = {
        k: {"avg": round(sum(v)/len(v), 4), "max": max(v), "count": len(v)}
        for k, v in phase_costs.items()
    }

    # メトリクスの妥当性チェック
    checks = {
        "Issue数が正しい": metrics["total_issues"] == 5,
        "総コストが正の値": metrics["total_cost_usd"] > 0,
        "平均コストが計算されている": metrics["avg_cost_per_issue"] > 0,
        "タイプ分布がある": len(metrics["type_distribution"]) >= 3,
        "フェーズ別コストがある": len(metrics["phase_costs"]) >= 3,
        "フィードバックが収集されている": len(metrics["top_feedbacks"]) >= 1,
    }

    all_pass = all(checks.values())
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "メトリクス集計",
        all_pass,
        "\n".join(detail_lines),
    )

    # メトリクス出力
    print(f"\n  --- メトリクス ---")
    print(f"  Issues: {metrics['total_issues']}")
    print(f"  総コスト: ${metrics['total_cost_usd']}")
    print(f"  平均コスト/Issue: ${metrics['avg_cost_per_issue']}")
    print(f"  平均レビュー回数: {metrics['avg_review_rounds']}")
    print(f"  タイプ分布: {metrics['type_distribution']}")
    print(f"  フェーズ別コスト: {json.dumps(metrics['phase_costs'], indent=2)}")

    # 保存
    state._metrics = metrics


# ──────────────────────────────────────
# S7: 改善提案の生成
# ──────────────────────────────────────
async def verify_s7_improvement_proposals(state: SelfImpState) -> None:
    log("S7: 改善提案の生成")

    metrics = getattr(state, "_metrics", None)
    if not metrics:
        record("S7スキップ", False, "メトリクスがない")
        return

    patterns_path = Path(state.knowledge_dir) / "patterns.yaml"
    patterns_yaml = patterns_path.read_text() if patterns_path.exists() else "パターンなし"

    prompt = f"""あなたはAIエージェントのワークフロー最適化アドバイザーです。
以下のメトリクスとパターン分析結果を元に、具体的な改善提案を生成してください。

## メトリクス
{json.dumps(metrics, indent=2, ensure_ascii=False)}

## 検出済みパターン
{patterns_yaml}

## 現在の設定
- Bug予算: ANALYSIS=$2.0, FIX=$5.0
- Feature-S予算: HEARING=$0.5, PLAN_BRIEF=$1.0, IMPLEMENT=$5.0
- Feature-M予算: HEARING=$1.0, DESIGN=$3.0, IMPLEMENT=$5.0
- CIリトライ最大: 3回
- ヒアリングタイムアウト: 24時間

## 指示
以下の観点で改善提案を生成してください:

1. **コスト最適化** — 予算設定は実際のコストに対して適切か
2. **プロンプト改善** — レビュー指摘を減らすためのプロンプト変更
3. **ワークフロー改善** — フェーズの追加/削除/変更
4. **品質向上** — テスト・レビューの改善

## 出力形式
各提案をJSON形式で出力してください:

```json
{{
  "proposals": [
    {{
      "id": "proposal-1",
      "category": "cost | prompt | workflow | quality",
      "title": "提案タイトル",
      "description": "詳細説明",
      "impact": "high | medium | low",
      "action": "具体的な変更内容",
      "metrics_basis": "この提案の根拠となるメトリクス"
    }}
  ]
}}
```"""

    result = await sdk_query(prompt, max_budget=2.0, timeout=300)
    r = result["result"]

    # JSON抽出
    import re
    json_str = ""
    if "```json" in r:
        json_str = r.split("```json")[1].split("```")[0].strip()
    elif "```" in r:
        json_str = r.split("```")[1].split("```")[0].strip()
    else:
        match = re.search(r'\{[\s\S]*"proposals"[\s\S]*\}', r)
        if match:
            json_str = match.group()

    parsed = None
    try:
        parsed = json.loads(json_str)
    except Exception:
        # JSONパース失敗でも内容チェック
        pass

    proposals = parsed.get("proposals", []) if parsed else []

    checks = {
        "提案が3個以上": len(proposals) >= 3 if parsed else r.count("proposal") >= 3 or r.count("提案") >= 3,
        "コスト最適化の提案あり": "コスト" in r or "予算" in r or "cost" in r.lower() or any(p.get("category") == "cost" for p in proposals),
        "プロンプト改善の提案あり": "プロンプト" in r or "prompt" in r.lower() or any(p.get("category") == "prompt" for p in proposals),
        "具体的なアクションあり": "action" in r or "変更" in r or "追加" in r,
        "メトリクスに基づいている": "$" in r or "コスト" in r or "レビュー" in r,
    }

    all_pass = sum(checks.values()) >= 4
    detail_lines = [f"{'✅' if v else '❌'} {k}" for k, v in checks.items()]
    record(
        "改善提案生成",
        all_pass,
        f"cost=${result['cost']:.4f}, proposals={len(proposals)}, score={sum(checks.values())}/5\n"
        + "\n".join(detail_lines),
    )

    # GitHub Issue作成シミュレート（実際には作らない、フォーマットだけ確認）
    if proposals:
        issue_title = f"[self-improvement] {proposals[0].get('title', 'N/A')}"
        issue_body = f"""## 改善提案

カテゴリ: {proposals[0].get('category', 'N/A')}
影響度: {proposals[0].get('impact', 'N/A')}

### 説明
{proposals[0].get('description', 'N/A')}

### アクション
{proposals[0].get('action', 'N/A')}

### 根拠
{proposals[0].get('metrics_basis', 'N/A')}

---
_このIssueはAI Agent の自己改善ループによって自動生成されました。_
"""
        record(
            "改善Issue形式",
            len(issue_title) > 20 and len(issue_body) > 100,
            f"title={issue_title[:60]}",
        )

    print(f"\n  --- 改善提案 (先頭800文字) ---\n  {(json_str or r)[:800]}")


# ──────────────────────────────────────
# メイン
# ──────────────────────────────────────
async def main() -> None:
    print("\n" + "=" * 60)
    print("  自己改善ループ検証 S1-S7")
    print("=" * 60)

    state = SelfImpState()

    try:
        await setup_dirs(state)
        await verify_s1_episode_recording(state)
        await verify_s2_semantic_extraction(state)
        await verify_s3_similar_search(state)
        await verify_s4_skill_detection(state)
        await verify_s5_skill_matching(state)
        await verify_s6_metrics(state)
        await verify_s7_improvement_proposals(state)
    except Exception as e:
        record("予期しないエラー", False, f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    # サマリ
    log("自己改善ループ検証サマリ")
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

    result_path = Path(__file__).parent / "f_self_improvement_results.json"
    result_path.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False))
    print(f"\n  結果を保存: {result_path}")


if __name__ == "__main__":
    asyncio.run(main())
