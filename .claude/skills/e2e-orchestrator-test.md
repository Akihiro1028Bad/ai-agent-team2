---
name: e2e-orchestrator-test
description: |
  AI マルチエージェントオーケストレーターの完全自動E2Eテスト。
  実際のGitHub Issue/PRを使ってオーケストレーターの動作を検証し、
  ワークフロー正常性・コード品質・設計品質・効率性をスコアカード形式で評価する。
---

# E2E Orchestrator Test

AI マルチエージェントオーケストレーターの完全自動E2Eテスト。
Bug / Feature-M / Feature-L の3種のIssueを作成し、オーケストレーターが
正しく処理できるかを検証する。

**対象リポジトリ**: `Akihiro1028Bad/ai-agent-team2-test`
**テスト方式**: 逐次実行 (Bug → Feature-M → Feature-L)

---

## Phase 1: Pre-flight Check

### 1.1 認証確認

```bash
# GitHub CLI 認証
gh auth status

# テストリポジトリへのアクセス確認
gh api repos/Akihiro1028Bad/ai-agent-team2-test --jq '.full_name'

# Claude API トークン確認
echo "CLAUDE_CODE_OAUTH_TOKEN: ${CLAUDE_CODE_OAUTH_TOKEN:+set}"
```

認証に失敗した場合はユーザーに通知して中断する。

### 1.2 既存テストIssue/PRクリーンアップ

```bash
# [e2e-test] プレフィクスの既存Issueを検索して閉じる
gh issue list --repo Akihiro1028Bad/ai-agent-team2-test \
  --search "[e2e-test]" --state open --json number \
  --jq '.[].number' | while read num; do
    gh issue close "$num" --repo Akihiro1028Bad/ai-agent-team2-test \
      --comment "E2Eテスト再実行のためクローズ"
  done

# [e2e-test] プレフィクスの既存PRを検索して閉じる
gh pr list --repo Akihiro1028Bad/ai-agent-team2-test \
  --search "[e2e-test]" --state open --json number \
  --jq '.[].number' | while read num; do
    gh pr close "$num" --repo Akihiro1028Bad/ai-agent-team2-test \
      --comment "E2Eテスト再実行のためクローズ"
  done
```

### 1.3 テスト用 config.yaml 生成

```bash
# テスト用設定をプロジェクトルートに作成
cat > /tmp/e2e-test-config.yaml << 'YAML'
accounts:
  default:
    name: default
    token_command: "gh auth token"
    default: true

repositories:
  - owner: "Akihiro1028Bad"
    repo: "ai-agent-team2-test"
    account: "default"
    label: "ai-agent"
    base_branch: "main"

polling_interval_sec: 30
concurrency:
  max_total: 1
  max_per_repo: 1

approve_comment: "LGTM"
YAML
```

### 1.4 オーケストレーターワークスペースのクリーンアップ

```bash
# 既存の状態をクリア (前回テストの残留状態を除去)
rm -f ~/.ai-agent-workspaces/state.json
```

**判定基準**: 全チェックがパスしたらPhase 2へ進む。1つでも失敗したらユーザーに通知して中断。

---

## Phase 2: Orchestrator Start

### 2.1 オーケストレーター起動

オーケストレーターをバックグラウンドで起動する。

```bash
cd /Users/tsutsumi.akihiro/dev/ai-agent-team2
nohup uv run ai-agent start --foreground --config /tmp/e2e-test-config.yaml \
  > /tmp/e2e-orchestrator.log 2>&1 &
ORCHESTRATOR_PID=$!
echo "Orchestrator PID: $ORCHESTRATOR_PID"
```

### 2.2 起動確認

```bash
sleep 5
# プロセスが生存しているか確認
kill -0 $ORCHESTRATOR_PID 2>/dev/null && echo "OK: running" || echo "FAIL: not running"
# ログの先頭確認
head -20 /tmp/e2e-orchestrator.log
```

起動失敗時: ログを確認してエラー原因を特定し、ユーザーに報告して中断。

---

## Phase 3: Bug Test Cycle

### 3.1 テストIssue作成

テストリポジトリのコードを読み、実際に意味のあるバグ修正Issueを作成する。

**Issue作成前の準備**:
1. テストリポジトリの `src/` 以下のコードを `gh api` で読む
2. 実際に存在する問題や改善点を特定する
3. 具体的で再現可能なバグレポートを作成する

**Issue例** (リポジトリの実際のコードを見て調整すること):

```bash
gh issue create --repo Akihiro1028Bad/ai-agent-team2-test \
  --title "[e2e-test] UserCard: ユーザー名が空文字の場合に表示が崩れる" \
  --body "## バグ概要
UserCard コンポーネントで name が空文字('')の場合、空の要素が描画される。

## 再現手順
1. User オブジェクトの name に空文字を渡す
2. UserCard を描画する

## 期待する動作
name が空文字の場合は「名前未設定」等のフォールバック表示をする。

## 実際の動作
空の要素が表示される。" \
  --label "ai-agent"
```

**記録する情報**:
- Issue番号
- 作成タイムスタンプ

### 3.2 フェーズ監視ループ

Issue作成後、フェーズ遷移を監視する。

```bash
# 30秒間隔でラベルを確認
ISSUE_NUM=<作成したIssue番号>
REPO="Akihiro1028Bad/ai-agent-team2-test"
TIMEOUT=900  # 15分タイムアウト
START_TIME=$(date +%s)

while true; do
  LABELS=$(gh issue view $ISSUE_NUM --repo $REPO --json labels --jq '.labels[].name' 2>/dev/null)
  PHASE=$(echo "$LABELS" | grep "^phase:" | sed 's/phase://')
  TYPE=$(echo "$LABELS" | grep "^type:" | sed 's/type://')
  
  echo "[$(date +%H:%M:%S)] Issue #$ISSUE_NUM - phase=$PHASE type=$TYPE"
  
  # 各フェーズの遷移タイムスタンプを記録
  # → レポート用のデータ収集
  
  # 終了条件
  if [ "$PHASE" = "done" ] || [ "$PHASE" = "suspended" ]; then
    echo "Terminal state reached: $PHASE"
    break
  fi
  
  # 承認が必要なフェーズの自動承認 (3.3参照)
  # ...
  
  # タイムアウトチェック
  NOW=$(date +%s)
  ELAPSED=$((NOW - START_TIME))
  if [ $ELAPSED -gt $TIMEOUT ]; then
    echo "TIMEOUT after ${ELAPSED}s"
    break
  fi
  
  sleep 30
done
```

### 3.3 自動承認

Bugワークフローの承認ポイント:

**plan-review フェーズ検出時 → 👍 リアクション追加**:

```bash
# bot コメント (<!-- ai-agent-bot --> マーカー付き) の最新コメントIDを取得
COMMENTS=$(gh api repos/$REPO/issues/$ISSUE_NUM/comments --jq '.[] | select(.body | contains("ai-agent-bot")) | .id' | tail -1)
if [ -n "$COMMENTS" ]; then
  gh api repos/$REPO/issues/comments/$COMMENTS/reactions \
    -X POST -f content="+1"
  echo "Added thumbsup reaction to comment $COMMENTS"
fi
```

**impl-review フェーズ検出時 → PR approve + merge**:

```bash
# PRを検索
PR_NUM=$(gh pr list --repo $REPO --search "issue-$ISSUE_NUM" --json number --jq '.[0].number')
if [ -n "$PR_NUM" ]; then
  # approve
  gh pr review $PR_NUM --repo $REPO --approve --body "E2Eテスト: 自動承認"
  sleep 5
  # merge
  gh pr merge $PR_NUM --repo $REPO --merge --delete-branch
  echo "PR #$PR_NUM approved and merged"
fi
```

### 3.4 Bug結果収集

テスト完了後に以下のデータを収集:

```bash
# PR差分の取得
gh pr view $PR_NUM --repo $REPO --json files,additions,deletions,title,body

# コミットメッセージの取得
gh pr view $PR_NUM --repo $REPO --json commits --jq '.commits[].messageHeadline'

# CI結果の確認
gh pr checks $PR_NUM --repo $REPO

# events.jsonl からフェーズ遷移履歴を取得
cat ~/.ai-agent-workspaces/logs/issue-$ISSUE_NUM/events.jsonl 2>/dev/null
```

---

## Phase 4: Feature-M Test Cycle

### 4.1 テストIssue作成

Feature-M は設計が必要な中規模機能。テストリポジトリに実際に意味のある機能追加Issueを作成する。

**Issue作成前の準備**:
1. テストリポジトリの現在の機能を把握
2. 既存コードベースを拡張する中規模機能を考案
3. 設計ドキュメントが必要な複雑さの機能にする

**Issue例**:

```bash
gh issue create --repo Akihiro1028Bad/ai-agent-team2-test \
  --title "[e2e-test] ユーザー検索機能の追加" \
  --body "## 概要
ユーザー一覧から名前・メールアドレスで検索できる機能を追加する。

## 要件
- 検索入力フィールドをユーザー一覧ページに追加
- 名前またはメールアドレスの部分一致で検索
- 検索結果をリアルタイムでフィルタリング（debounce付き）
- 検索結果が0件の場合は適切なメッセージを表示
- カスタムhook (useUserSearch) で検索ロジックを分離

## 技術的な考慮事項
- 既存の useUser hook との整合性
- 型定義の拡張 (SearchParams 等)
- テストの追加" \
  --label "ai-agent"
```

### 4.2 Feature-M フェーズ監視ループ

Feature-M の承認ポイントは多い:

1. **hearing フェーズ**: 通常は自動で READY 判定される (待機のみ)
2. **design-review フェーズ**: 設計PR の approve が必要

```bash
# design-review 検出時 → 設計PRをapprove
# ただし設計PRはマージしない (設計と実装は同一ブランチ)
DESIGN_PR=$(gh pr list --repo $REPO --search "issue-$ISSUE_NUM" --json number --jq '.[0].number')
if [ -n "$DESIGN_PR" ]; then
  gh pr review $DESIGN_PR --repo $REPO --approve --body "E2Eテスト: 設計承認"
  echo "Design PR #$DESIGN_PR approved"
fi
```

3. **impl-review フェーズ**: 実装PR の approve + merge

```bash
# impl-review 検出時 → PRをapprove + merge
# Feature-M では設計PRと実装PRが同一の場合がある
IMPL_PR=$(gh pr list --repo $REPO --search "issue-$ISSUE_NUM" --json number --jq '.[0].number')
if [ -n "$IMPL_PR" ]; then
  gh pr review $IMPL_PR --repo $REPO --approve --body "E2Eテスト: 実装承認"
  sleep 5
  gh pr merge $IMPL_PR --repo $REPO --merge --delete-branch
  echo "Impl PR #$IMPL_PR approved and merged"
fi
```

### 4.3 Feature-M 追加の品質チェック

```bash
# 設計書の存在確認
gh api "repos/$REPO/contents/docs/designs" --jq '.[].name' | grep "issue-$ISSUE_NUM"

# 設計書の内容取得・構成チェック
DESIGN_FILE="docs/designs/issue-${ISSUE_NUM}.md"
gh api "repos/$REPO/contents/$DESIGN_FILE" --jq '.content' | base64 -d
# 必須セクション: 概要, アーキテクチャ/設計, API/インターフェース, テスト方針
```

---

## Phase 5: Feature-L Test Cycle

### 5.1 テストIssue作成

Feature-L は分割が必要な大規模機能。

**Issue例**:

```bash
gh issue create --repo Akihiro1028Bad/ai-agent-team2-test \
  --title "[e2e-test] 管理用ダッシュボード機能の追加" \
  --body "## 概要
管理者がユーザーの活動状況を把握できるダッシュボード機能を追加する。

## 要件
- ダッシュボードページ (/dashboard)
- ユーザー統計カード (総ユーザー数、アクティブユーザー数、新規登録数)
- ユーザーアクティビティグラフ (直近7日間の登録数推移)
- 最近のユーザー活動ログ一覧
- レスポンシブデザイン対応
- ダッシュボード用APIエンドポイント
- ダッシュボード用カスタムhooks
- 各コンポーネントのユニットテスト

## 規模感
10ファイル以上の変更が見込まれる大規模機能。" \
  --label "ai-agent"
```

### 5.2 Feature-L フェーズ監視

Feature-L の承認ポイント:

1. **split-proposal フェーズ検出時 → 👍 リアクション追加**:

```bash
# split-proposal の bot コメントに 👍 を追加
COMMENTS=$(gh api repos/$REPO/issues/$ISSUE_NUM/comments \
  --jq '.[] | select(.body | contains("ai-agent-bot")) | .id' | tail -1)
if [ -n "$COMMENTS" ]; then
  gh api repos/$REPO/issues/comments/$COMMENTS/reactions \
    -X POST -f content="+1"
  echo "Approved split proposal"
fi
```

2. **split-execute 完了後**: 子Issueの確認

```bash
# 子Issueの一覧取得
gh issue list --repo $REPO --label "ai-agent" --state open \
  --json number,title,labels --jq '.[] | select(.title | contains("e2e-test") | not)'
```

### 5.3 Feature-L 品質チェック

Feature-L は分割提案の質を評価:
- 子Issue数の妥当性 (2-5個が適切)
- 各子Issueに type: ラベルが付いているか
- 子Issue間の依存関係が明示されているか
- 各子Issueが独立して実装可能か

---

## Phase 6: Quality Evaluation

各テストサイクル完了後、以下の観点で品質評価を行う。

### 6.1 ワークフロー正常性 (0-100)

- **フェーズ遷移の正しさ** (40点):
  - 期待されるフェーズ順序で遷移したか
  - 不要な遷移 (SUSPENDED→復帰等) が発生していないか
  - 最終的に DONE に到達したか

- **エラーハンドリング** (30点):
  - CI_FIX のリトライが3回以内か
  - SUSPENDED にならなかったか
  - タイムアウトしなかったか

- **イベント検知** (30点):
  - ポーラーが全イベントを正しく検知したか
  - 重複イベントを適切にフィルタしたか

### 6.2 コード品質 (0-100)

PRのブランチをチェックアウトして品質チェック:

```bash
# テストリポジトリをクローン
git clone https://github.com/Akihiro1028Bad/ai-agent-team2-test.git /tmp/e2e-quality-check
cd /tmp/e2e-quality-check

# PR差分のファイル一覧
gh pr diff $PR_NUM --name-only

# ビルド確認 (テストリポジトリはNext.js/TypeScript)
npm ci && npm run build

# テスト実行
npm test -- --passWithNoTests

# TypeScript型チェック (tsconfig.json がある場合)
npx tsc --noEmit 2>/dev/null || true
```

**コード品質の評価基準** (各項目の配点):
- ビルド成功 (20点)
- テスト追加あり (20点)
- テスト全パス (20点)
- 型エラーなし (15点)
- コミットメッセージが conventional commits 形式 (10点)
- 不要ファイルが含まれていない (15点)

### 6.3 設計品質 (0-100, Feature-M のみ)

```bash
# 設計書の構成チェック
DESIGN_CONTENT=$(gh api "repos/$REPO/contents/docs/designs/issue-${ISSUE_NUM}.md" \
  --jq '.content' | base64 -d)
```

**設計品質の評価基準**:
- 設計書が存在する (20点)
- 概要セクションがある (15点)
- アーキテクチャ/設計セクションがある (20点)
- API/インターフェースの記述がある (15点)
- テスト方針の記述がある (15点)
- 実装コードとの整合性がある (15点)

### 6.4 ワークフロー効率 (0-100)

```bash
# events.jsonl からタイミングデータを抽出
cat ~/.ai-agent-workspaces/logs/issue-$ISSUE_NUM/events.jsonl
```

**効率性の評価基準**:
- **各フェーズの所要時間** (40点):
  - Bug: 全体15分以内 → 40点, 30分以内 → 25点, それ以上 → 10点
  - Feature-M: 全体35分以内 → 40点, 60分以内 → 25点, それ以上 → 10点
  - Feature-L: Split完了まで10分以内 → 40点, 20分以内 → 25点, それ以上 → 10点

- **リトライ回数** (30点):
  - CI_FIX: 0回 → 30点, 1回 → 20点, 2回 → 10点, 3回 → 0点
  - マルチパス (implement): 1パス → 30点, 2パス → 20点, 3パス以上 → 10点

- **コスト** (30点):
  - events.jsonl の cost_usd フィールドから合算
  - Bug: $1以下 → 30点, $2以下 → 20点, それ以上 → 10点
  - Feature-M: $3以下 → 30点, $5以下 → 20点, それ以上 → 10点

### 6.5 PR品質 (0-100)

```bash
gh pr view $PR_NUM --repo $REPO --json title,body,files,additions,deletions
```

**PR品質の評価基準**:
- タイトルが conventional commits 形式 (20点)
- 本文に変更概要がある (20点)
- 差分行数が妥当 (Bug: <200行, Feature-M: <500行) (20点)
- 関連Issue番号がリンクされている (20点)
- 不要ファイル (.env, node_modules等) が含まれていない (20点)

---

## Phase 7: Report Generation

全テストサイクル完了後、スコアカードを生成する。

### レポートフォーマット

```
===============================================
  E2E Orchestrator Test Report
  Date: YYYY-MM-DD HH:MM
  Repo: Akihiro1028Bad/ai-agent-team2-test
===============================================

--- Bug Issue #XX ---
Status: [PASS/WARN/FAIL]

  Workflow (XX/100):
    Phase transitions: TYPE_DETECTION → ANALYSIS → PLAN_REVIEW → FIX → IMPL_REVIEW → DONE [OK]
    Total time: XXm XXs
    CI retries: 0
    Suspended: No

  Code Quality (XX/100):
    Build:           [PASS]
    Tests added:     [YES]
    Tests passing:   [PASS]
    Type check:      [PASS]
    Commit format:   [PASS]
    Clean diff:      [PASS]

  PR Quality (XX/100):
    Title format:    [PASS]
    Description:     [PASS]
    Diff size:       +XX/-XX [OK]
    Issue link:      [PASS]
    No junk files:   [PASS]

  Efficiency (XX/100):
    Duration:        XXm (target: <15m)
    Cost:            $X.XX (target: <$1.00)
    CI retries:      0 (target: 0)
    Impl passes:     1 (target: 1)

--- Feature-M Issue #YY ---
Status: [PASS/WARN/FAIL]

  Workflow (XX/100):
    Phase transitions: TYPE_DETECTION → HEARING → DESIGN → DESIGN_REVIEW
      → PLANNING → IMPLEMENT → IMPL_REVIEW → DONE [OK]
    Total time: XXm XXs

  Code Quality (XX/100):
    (same as above)

  Design Quality (XX/100):
    Design doc exists:    [YES]
    Overview section:     [YES]
    Architecture section: [YES]
    API section:          [YES]
    Test strategy:        [YES]
    Code alignment:       [XX/100]

  PR Quality (XX/100):
    (same as above)

  Efficiency (XX/100):
    (same as above)

--- Feature-L Issue #ZZ ---
Status: [PASS/WARN/FAIL]

  Workflow (XX/100):
    Phase transitions: TYPE_DETECTION → HEARING → SPLIT_PROPOSAL
      → SPLIT_EXECUTE → DONE [OK]
    Total time: XXm XXs

  Split Quality (XX/100):
    Child issues created: X (target: 2-5)
    All typed:            [YES/NO]
    Dependencies clear:   [YES/NO]
    Independent impl:     [YES/NO]

  Efficiency (XX/100):
    (same as above)

===============================================
  OVERALL SCORES
===============================================
  Workflow Correctness:  XX/100
  Code Quality:          XX/100
  Design Quality:        XX/100  (Feature-M only)
  Efficiency:            XX/100
  PR Quality:            XX/100
  ─────────────────────────────
  TOTAL:                 XX/100

  Verdict: [PASS / WARN / FAIL]
    PASS:  Total >= 70 and no FAIL items
    WARN:  Total >= 50 or has WARN items
    FAIL:  Total < 50 or has critical failures

===============================================
  RECOMMENDATIONS
===============================================
  - (改善推奨事項を箇条書きで列挙)
===============================================
```

---

## Phase 8: Cleanup

### 8.1 オーケストレーター停止

```bash
# PIDファイルからプロセスを停止
kill $ORCHESTRATOR_PID 2>/dev/null || true
# または
uv run ai-agent stop --config /tmp/e2e-test-config.yaml 2>/dev/null || true

# プロセスが停止したことを確認
sleep 3
kill -0 $ORCHESTRATOR_PID 2>/dev/null && echo "WARN: still running" || echo "OK: stopped"
```

### 8.2 テストIssue/PRクリーンアップ

```bash
# テスト用Issueを閉じる ([e2e-test] プレフィクス)
gh issue list --repo $REPO --search "[e2e-test]" --state open \
  --json number --jq '.[].number' | while read num; do
    gh issue close "$num" --repo $REPO --comment "E2Eテスト完了"
  done

# Feature-L で作成された子Issueも閉じる
# (子Issueは [e2e-test] プレフィクスがないため、直近作成分を確認)
```

### 8.3 ワークスペースクリーンアップ

```bash
# テスト用の一時ファイル削除
rm -f /tmp/e2e-test-config.yaml
rm -rf /tmp/e2e-quality-check
rm -f /tmp/e2e-orchestrator.log

# worktree の残留確認・削除
ls ~/.ai-agent-workspaces/worktrees/ 2>/dev/null
```

---

## 実行上の注意

### タイミング

- ポーリング間隔: 30秒 (テスト用に短縮)
- 各フェーズの実行時間: 1-10分
- 承認タイミング: フェーズラベル検出後、次のポーリングサイクルで検知されるよう少し待つ (10秒程度)
- 全体所要時間: 50-90分 (3種のIssue合計)

### エラーハンドリング

- **SUSPENDED到達**: そのIssueのテストはFAILとしてマーク。オーケストレーターのログから原因を収集してレポートに含める
- **タイムアウト**: 15分 (Bug) / 35分 (Feature-M) / 15分 (Feature-L) で打ち切り。FAIL としてマーク
- **オーケストレータークラッシュ**: ログを収集してレポートに含め、テスト全体を中断
- **CI失敗**: CI_FIXフェーズに遷移するのを待つ。3回失敗でSUSPENDED → レポート

### 承認のタイミング

承認アクションは、対応するフェーズラベルを検出してから実行する:

| フェーズラベル | 承認アクション | 待機時間 |
|---|---|---|
| `phase:plan-review` | bot コメントに 👍 リアクション | 10秒 |
| `phase:design-review` | 設計PR に approve | 10秒 |
| `phase:impl-review` | 実装PR に approve + merge | 10秒 |
| `phase:split-proposal` | bot コメントに 👍 リアクション (split-proposal待ち) | 10秒 |

### SUSPENDED時のデバッグ情報収集

```bash
# オーケストレーターログの末尾
tail -100 /tmp/e2e-orchestrator.log

# Issue のイベントログ
cat ~/.ai-agent-workspaces/logs/issue-$ISSUE_NUM/events.jsonl

# state.json の現在状態
cat ~/.ai-agent-workspaces/state.json

# GitHub Issue のラベル・コメント
gh issue view $ISSUE_NUM --repo $REPO --json labels,comments
```
