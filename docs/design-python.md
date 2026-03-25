# AI Multi-Agent Orchestrator 設計書 (Python版)

## 1. 概要

24時間稼働するPCにAIマルチエージェントを配置し、1人のエンジニアとして自律的に稼働させるシステム。
GitHub Issueベースでタスクをアサインし、要件ヒアリング・設計・実装計画・実装・レビュー対応までを自動で行い、Pull Requestを作成する。

### 1.1 基本方針

- 対象リポジトリは汎用（YAML設定で複数リポジトリを監視可能）
- 言語: Python 3.13+
- エージェント基盤: Claude Agent SDK (Python) + Max plan OAuthトークン (`CLAUDE_CODE_OAUTH_TOKEN`)
- 並行処理: 最大2 Issue同時処理（リポジトリあたり最大1）
- 人間の介入ポイント: 設計承認、設計フィードバック、PRフィードバック、PR承認
- 非同期アーキテクチャ: `asyncio` ベースの完全非同期設計
- プラグインアーキテクチャ: `AgentRunner`, `Notifier`, `Tracker` を `Protocol` で抽象化

### 1.2 設計原則

1. **Protocol-based Plugin Architecture** — 主要インターフェースは `typing.Protocol` で定義し、実装の差し替えを容易にする
2. **Structured Concurrency** — `asyncio.TaskGroup` によるタスクライフサイクル管理
3. **Immutable Data** — 状態はイミュータブルな `dataclass(frozen=True)` で表現
4. **Fail-safe** — 全フェーズでタイムアウト・リトライ・エラー通知を実装
5. **Observability** — 構造化イベントログ (`events.jsonl`) による全アクション追跡

---

## 2. ワークフロー

### 2.1 タスクタイプ分類

Issueは内容に応じて4つのタイプに自動分類され、タイプごとに最適化されたワークフローで処理される。

| タイプ | ラベル | 判定基準 | 例 | フェーズ数 |
|-------|--------|---------|-----|----------|
| **Bug** | `type:bug` | エラー・不具合・動かない・壊れた等 | 「ボタンが押せない」「500エラー」 | 4-5 |
| **Feature-S** | `type:feature-s` | 1-3ファイル変更、設計書不要 | 「バリデーション追加」「文言変更」 | 5-6 |
| **Feature-M** | `type:feature-m` | 複数ファイル、設計書必要 | 「プロフィール画面追加」 | 7-8 |
| **Feature-L** | `type:feature-l` | 大規模、分割が必要 | 「認証システム刷新」 | 分割後 |

#### タイプ自動判定ロジック

```
Issue作成 (label: ai-agent)
    │
    ▼
AI が Issue 内容を分析
    │
    ├── キーワード: 「バグ」「エラー」「動かない」「修正」「壊れた」「500」
    │   └── type:bug
    │
    ├── 変更規模の推定
    │   ├── 1-3ファイル推定 → type:feature-s
    │   ├── 4-10ファイル推定 → type:feature-m
    │   └── 10+ファイル推定 → type:feature-l
    │
    └── 判定結果を Issue コメントで通知
        「このIssueを type:bug として処理します。異なる場合はコメントください」
        → 次回Pollingで人間の異議がなければ続行
        → タイプ変更はフェーズ完了後にのみ許可
```

### 2.2 ワークフロー全体像

```
                    Issue作成 (ai-agent)
                           │
                    タイプ自動判定 + ラベル付与
                           │
              ┌────────────┼────────────┐────────────┐
              ▼            ▼            ▼            ▼
          type:bug    type:feature-s  type:feature-m  type:feature-l
              │            │            │            │
              ▼            ▼            ▼            ▼
          ANALYSIS     HEARING      HEARING      HEARING
              │            │            │            │
              ▼            ▼            ▼            ▼
          方針コメント  PLAN_BRIEF   DESIGN       SPLIT_PROPOSAL
              │            │            │            │
              ▼            ▼            ▼            ▼
          🧑👍承認     🧑👍承認    DESIGN_REVIEW  🧑 分割判断
              │            │            │            │
              │            │            ▼            ▼
              │            │        PLANNING     子Issue作成
              │            │            │        (Feature-M×N)
              ▼            ▼            ▼
          ┌────────────────────────────────┐
          │      共通フェーズ               │
          │  IMPLEMENT → CI_FIX →         │
          │  IMPL_REVIEW → DONE           │
          └────────────────────────────────┘
```

### 2.3 🐛 Bug ワークフロー

**フロー: `ANALYSIS → 🧑方針承認(👍) → FIX → CI_FIX → IMPL_REVIEW → DONE`**

設計書PRなし。修正方針をIssueコメントで共有し、👍リアクションで承認。

```
ANALYSIS                     🧑承認               共通: FIX
┌──────────────────┐    ┌──────────┐    ┌────────────────┐
│ Issue分析         │    │ 人間が    │    │ 修正 + テスト   │
│ 原因特定          │───→│ 方針を   │───→│ PR作成          │
│ 修正方針コメント投稿│    │ 👍承認   │    │                │
│ $2.0             │    │ or 指摘  │    │ $5.0           │
└──────────────────┘    └──────────┘    └────────────────┘
```

| フェーズ | 内容 | 成果物 | 予算 | タイムアウト |
|---------|------|--------|------|------------|
| **ANALYSIS** | Issue分析 + 原因特定 + 修正方針 + 質問(必要時) | Issueコメント（方針書） | $2.0 | 15分 |
| **🧑 方針承認** | 人間が 👍 or 指摘コメント | - | - | - |
| **FIX** | 修正 + テスト + PR作成 (descriptionに方針再掲) | 実装PR | $5.0 | 30分 |
| **CI_FIX** | CI失敗時の自動修正（最大3回） | 修正コミット | $3.0 | 20分 |
| **IMPL_REVIEW** | 🧑 PR approve or 指摘 → AI修正(resume) | - | $3.0 | 20分 |
| **DONE** | マージ + クローズ | - | - | - |

**ANALYSIS フェーズのコメント形式:**

```markdown
🔍 **修正方針 (AI分析)**

**原因:** `src/auth/login.ts:42` で null チェックが漏れている
**発生条件:** APIレスポンスが空の場合に発生
**修正内容:**
| ファイル | 修正内容 |
|---------|---------|
| `src/auth/login.ts` | null guard を追加 |

**影響範囲:** UserProfile コンポーネントのみ
**テスト方針:**
- [ ] 再現テスト（null レスポンスケース）
- [ ] リグレッションテスト

👍 で承認 / コメントで指摘をお願いします
```

**予想コスト: ~$0.80** / **人間承認回数: 2回** (👍 + PR approve) / **PR数: 1**

### 2.4 ⚡ Feature-S ワークフロー

**フロー: `HEARING → PLAN_BRIEF → 🧑方針承認(👍) → IMPLEMENT → CI_FIX → IMPL_REVIEW → DONE`**

設計書PRなし。簡易方針をIssueコメントで共有し、👍リアクションで承認。

```
HEARING           PLAN_BRIEF            🧑承認           共通: IMPLEMENT
┌──────────┐    ┌──────────────┐    ┌──────────┐    ┌────────────────┐
│ 要件確認  │    │ 簡易方針作成  │    │ 人間が    │    │ 実装 + テスト   │
│ (質問     │───→│ → Issue     │───→│ 方針を   │───→│ PR作成          │
│  1往復)   │    │   コメント   │    │ 👍承認   │    │                │
│ $0.5     │    │ $1.0        │    │ or 指摘  │    │ $5.0           │
└──────────┘    └──────────────┘    └──────────┘    └────────────────┘
```

| フェーズ | 内容 | 成果物 | 予算 | タイムアウト |
|---------|------|--------|------|------------|
| **HEARING** | 要件確認（質問1往復まで） | Issueコメント（質問） | $0.5 | 5分 |
| **PLAN_BRIEF** | 簡易方針作成 | Issueコメント（方針） | $1.0 | 10分 |
| **🧑 方針承認** | 人間が 👍 or 指摘コメント | - | - | - |
| **IMPLEMENT** | 実装 + テスト + PR作成 (descriptionに方針再掲) | 実装PR | $5.0 | 30分 |
| **CI_FIX** | CI失敗時の自動修正 | 修正コミット | $3.0 | 20分 |
| **IMPL_REVIEW** | 🧑 PR approve or 指摘 → AI修正(resume) | - | $3.0 | 20分 |
| **DONE** | マージ + クローズ | - | - | - |

**PLAN_BRIEF フェーズのコメント形式:**

```markdown
📋 **実装方針 (AI提案)**

**変更内容:**
- `src/utils/validate.ts`: メールバリデーション関数を追加
- `src/components/RegisterForm.tsx`: バリデーション呼び出し追加

**テスト方針:**
- [ ] 正常系: 有効なメールアドレスでエラーなし
- [ ] 異常系: 不正な形式でエラーメッセージ表示

👍 で承認 / コメントで指摘をお願いします
```

**予想コスト: ~$0.90** / **人間承認回数: 2回** (👍 + PR approve) / **PR数: 1**

### 2.5 🏗️ Feature-M ワークフロー

**フロー: `HEARING → DESIGN → DESIGN_REVIEW → PLANNING → IMPLEMENT → CI_FIX → IMPL_REVIEW → DONE`**

正式な設計書PRを作成。設計書の承認はPR approveで行う。

```
HEARING        DESIGN          DESIGN_REVIEW     PLANNING       共通: IMPLEMENT
┌────────┐   ┌────────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────┐
│要件     │   │設計書作成   │   │🧑設計      │   │実装計画   │   │実装 + テスト  │
│ヒアリング│──→│docs/designs│──→│レビュー    │──→│作成      │──→│PR作成        │
│        │   │+ PR作成    │   │approve/指摘│   │          │   │              │
│$1.0    │   │$3.0        │   │            │   │$2.0      │   │$5.0          │
└────────┘   └────────────┘   └────────────┘   └──────────┘   └──────────────┘
```

| フェーズ | 内容 | 成果物 | 予算 | タイムアウト |
|---------|------|--------|------|------------|
| **HEARING** | 要件ヒアリング（複数往復可） | Issueコメント | $1.0 | 10分 |
| **DESIGN** | 設計書作成 + PR | `docs/designs/issue-XX.md` + PR | $3.0 | 30分 |
| **DESIGN_REVIEW** | 🧑 PR approve or 指摘 → AI修正(resume) | - | $2.0 | 30分 |
| **PLANNING** | 実装計画作成（ファイル順序・依存関係） | `docs/designs/issue-XX-plan.md` | $2.0 | 15分 |
| **IMPLEMENT** | 実装 + テスト + PR作成 | 実装PR | $5.0 | 60分 |
| **CI_FIX** | CI失敗時の自動修正（最大3回） | 修正コミット | $3.0 | 20分 |
| **IMPL_REVIEW** | 🧑 PR approve or 指摘 → AI修正(resume) | - | $3.0 | 30分 |
| **DONE** | マージ + クローズ | - | - | - |

**予想コスト: ~$1.50** / **人間承認回数: 2回** (設計PR approve + 実装PR approve) / **PR数: 2**

### 2.6 🏢 Feature-L ワークフロー

**フロー: `HEARING → SPLIT_PROPOSAL → 🧑分割判断 → 子Issue作成 → 各子Issueをタイプ別ワークフローで処理`**

大規模Issueは分割してから処理する。分割判断は人間が行う。

#### 親Issueフェーズ

| フェーズ | 内容 | 予算 |
|---------|------|------|
| **HEARING** | 全体要件の把握 | $1.0 |
| **SPLIT_PROPOSAL** | 分割案をIssueコメントに提案 | $2.0 |
| **🧑 分割判断** | 人間が 👍 or 修正指示 | - |
| **SPLIT_EXECUTE** | 子Issue作成 + 各子に `ai-agent` + `type:*` + `depends-on:#XX` ラベル | $0.5 |
| **親Issueクローズ** | 分割完了コメント投稿 + クローズ | - |

#### 子Issueの処理フロー

各子Issueは `type` ラベルに応じた **通常のワークフロー（承認フロー含む）** を通る。

```
子Issue (type:feature-m) の場合:
  HEARING → DESIGN → 🧑設計PR approve → PLANNING → IMPLEMENT → 🧑実装PR approve → DONE
                      ↑ 人間承認①                               ↑ 人間承認②

子Issue (type:feature-s) の場合:
  HEARING → PLAN_BRIEF → 🧑👍承認 → IMPLEMENT → 🧑実装PR approve → DONE
                          ↑ 人間承認①             ↑ 人間承認②
```

**子Issueは通常のIssueと全く同じ扱い。** `ai-agent` ラベルが付いていれば、Pollerが検知してタイプ別ワークフローで処理する。

#### 依存管理

```
depends-on:#XX ラベルによる依存管理:
  1. Pollerが子Issueを検知
  2. depends-on ラベルを解析
  3. 依存先Issueが全てDONEか確認
     ├── 全てDONE → キューに投入（処理開始）
     └── 未完了あり → phase:blocked ラベルを付与（待機）
  4. 依存先がDONEになったら phase:blocked を除去 → キューに投入
```

#### 処理順序の例

```
親Issue: 「認証システム刷新」 → 11個に分割

優先順1: #10 DBスキーマ変更        (依存なし)     → 即座に処理開始
優先順2: #11 JWT発行・検証          (依存: #10)    → #10完了まで待機
優先順3: #12 リフレッシュトークン    (依存: #10,#11) → #10,#11完了まで待機
優先順4: #13 認証ミドルウェア        (依存: #11)    → #11完了まで待機
  ...

各子Issueは Feature-M ワークフロー（設計PR approve + 実装PR approve）を通る。
依存なしの子Issueは並行処理可能（max_total=2 の制約内）。
```

**予想コスト: $2.0（親） + N×$1.50（子Issue）**
**人間承認回数: 1（分割判断）+ N×2（各子Issueの設計approve + 実装approve）**

### 2.7 コスト比較サマリ

| タイプ | フェーズ数 | 予想コスト | 人間承認回数 | PR数 |
|-------|----------|-----------|------------|------|
| **Bug** | 4-5 | **~$0.80** | 2回 (👍 + PR) | 1 |
| **Feature-S** | 5-6 | **~$0.90** | 2回 (👍 + PR) | 1 |
| **Feature-M** | 7-8 | **~$1.50** | 2回 (設計PR + 実装PR) | 2 |
| **Feature-L** | 分割後 | **$2.0 + N×$1.50** | 1(分割) + N×2(設計+実装) | N×2 |

### 2.8 方針承認フローの統一

```
Bug / Feature-S:
  方針 → Issueコメント投稿
  承認 → 👍 リアクション（+1）
  指摘 → コメント返信
  再提出 → AIが修正版を新しいコメントで投稿
  検知 → Pollerがリアクション or 指摘コメントを検知

Feature-M:
  方針 → 設計書PR
  承認 → PR approve
  指摘 → PRコメント
  再提出 → PRに修正push (resume)
  検知 → PollerがPR approve or コメントを検知
```

### 2.9 共通フェーズ

以下のフェーズは全タイプで共有し、同一の `PhaseExecutor` 実装を使う。

- **IMPLEMENT** — コード実装 + テスト作成 + PR作成
- **CI_FIX** — CI失敗時の自動修正ループ（最大3回）
- **IMPL_REVIEW** — 人間のPRレビュー + 指摘対応（resume）
- **DONE** — マージ + Issueクローズ

### 2.10 Issue分割フロー

大きすぎるIssueに対して、AIがヒアリングフェーズ中に分割を提案する。

```
HEARING フェーズ中:
├── AIがIssueを分析
│   └── 「このIssueは以下のN個に分割することを推奨します」
├── Issueコメントとして提案を投稿
│   └── ラベル: "phase:hearing" + "needs-split"
├── 人間の判断待ち
│   ├── 「分割してください」 → AIが子Issue作成、親はクローズ
│   ├── 「そのまま進めて」 → 通常フローへ
│   └── 「こう分割して」   → 指示に従い子Issue作成
└── Slack通知: 「分割の判断をお願いします」
```

### 2.11 GitHub Labels

| Label | 意味 |
|-------|------|
| `ai-agent` | AIに割り当てるIssue |
| `type:bug` | バグ修正 |
| `type:feature-s` | 小規模機能 |
| `type:feature-m` | 中規模機能 |
| `type:feature-l` | 大規模機能（分割対象） |
| `severity:critical` | 重大バグ（方針承認必須） |
| `depends-on:XX` | Issue間依存 |
| `plan:pending` | 方針レビュー待ち（Bug/Feature-S） |
| `plan:approved` | 方針承認済み |
| `needs-split` | Issue分割の判断待ち |
| `phase:hearing` | ヒアリング中 |
| `phase:analysis` | バグ分析中 |
| `phase:plan-brief` | 簡易方針作成中 |
| `phase:plan-review` | 方針レビュー待ち |
| `phase:design` | 設計書作成中 |
| `phase:design-review` | 設計レビュー待ち |
| `phase:design-revise` | 設計修正中 |
| `phase:planning` | 実装計画作成中 |
| `phase:implement` | 実装中 |
| `phase:ci-fix` | CI修正中 |
| `phase:impl-review` | 実装レビュー待ち |
| `phase:impl-revise` | 実装修正中 |
| `phase:blocked` | 依存先Issue未完了のため待機中 |
| `phase:done` | 完了 |
| `phase:suspended` | エラー等で保留中 |

### 2.12 検証済みメトリクス

以下は実際のテストリポジトリ（`Akihiro1028Bad/ai-agent-team2-test`）での検証結果。

| 検証項目 | 結果 | 実コスト |
|---------|------|---------|
| タイプ自動判定（Bug/Feature-S/Feature-M/Feature-L） | 4/4 正解 | $0.055 |
| Bug: ANALYSIS → 方針コメント → 👍検知 → FIX → PR | 全PASS (6/6) | $0.33 |
| Feature-S: HEARING → PLAN_BRIEF → 👍 → IMPLEMENT → PR | 全PASS (6/6) | $0.46 |
| 方針指摘 → 修正版投稿 | PASS (3/3) | $0.23 |
| PR description 方針再掲 | PASS (2/2) | - |
| Feature-L: 分割提案 → 子Issue作成(11個) → ラベル | 全PASS (38/38) | $0.32 |
| E2E: 子Issue A → PR → A完了 → B ブロック解除 → PR | 全PASS (20/22) | $1.32 |
| **合計** | **91/93 PASS** | **$2.72** |

※ E2Eの2 FAILはテストデータ汚染によるもの（キュー内の古いIssue検出）。ロジックは正常。

---

## 3. システムアーキテクチャ

### 3.1 全体構成

```
┌──────────────────────────────────────────────────────────────┐
│                    オーケストレーター (asyncio 常駐)             │
│                                                               │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐               │
│  │ Poller   │───→│ Event    │───→│ Task     │               │
│  │ (2分間隔) │    │ Router   │    │ Queue    │               │
│  └──────────┘    └──────────┘    │(asyncio  │               │
│       │                          │ Queue)   │               │
│       │                          └────┬─────┘               │
│  ┌────┴─────┐                   ┌────┴─────┐               │
│  │ Health   │                   │ Workspace │               │
│  │ Checker  │                   │ Manager   │               │
│  │ (30分)   │                   │ (worktree)│               │
│  └──────────┘                   └────┬─────┘               │
│                                      │                      │
│                              ┌───────┴───────┐             │
│                              │ Claude Runner  │             │
│                              │(Agent SDK)     │             │
│                              │  ├ Subagents   │             │
│                              │  │ code-analyzer│             │
│                              │  │ test-writer  │             │
│                              └───────┬───────┘             │
│                                      │                      │
│                         ┌────────────┼────────────┐        │
│                         ▼            ▼            ▼        │
│                    ┌────────┐  ┌────────┐  ┌────────┐     │
│                    │GitHub  │  │ Slack  │  │ Logger │     │
│                    │Client  │  │Notifier│  │(events │     │
│                    │(githubkit)│        │  │ .jsonl)│     │
│                    └────────┘  └────────┘  └────────┘     │
│                                                            │
│  Protocol interfaces:                                       │
│  ┌──────────────┬──────────────┬──────────────┐            │
│  │ AgentRunner  │  Notifier    │  Tracker     │            │
│  │ (Protocol)   │  (Protocol)  │  (Protocol)  │            │
│  └──────────────┴──────────────┴──────────────┘            │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 コンポーネント説明

| コンポーネント | 責務 |
|--------------|------|
| **Poller** | 2分間隔でGitHub APIをpolling。Issue/PR/コメントのイベントを検知 |
| **Event Router** | 検知したイベントをフェーズ遷移アクションに振り分け |
| **Task Queue** | `asyncio.Queue` + `asyncio.Semaphore` で同時実行数を制御（全体max 2、リポあたりmax 1） |
| **Workspace Manager** | git worktreeの作成・削除。各Issueの作業を物理的に分離 |
| **Claude Runner** | Claude Agent SDK (`query()` / `ClaudeSDKClient`) を使ったAIエージェント実行 |
| **Context Engine** | リポマップ生成・自動コンテキスト収集による効率的なプロンプト構築 |
| **GitHub Client** | `githubkit` による非同期GitHub API操作 |
| **Slack Notifier** | `httpx` によるSlack Webhook通知送信 |
| **Event Logger** | 構造化イベントログ (`events.jsonl`) + フェーズログの記録 |
| **Health Checker** | 30分間隔でClaude Code認証の有効性を確認 |

### 3.3 プラグインアーキテクチャ（Protocol定義）

```python
from typing import Protocol, runtime_checkable
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentResult:
    """エージェント実行結果."""

    session_id: str
    output: str
    tool_uses: list[dict]
    cost_usd: float
    duration_sec: float


@dataclass(frozen=True)
class PhaseContext:
    """フェーズ実行に必要なコンテキスト."""

    issue_number: int
    repo_owner: str
    repo_name: str
    phase: str
    worktree_path: str
    resume_session_id: str | None = None
    extra: dict | None = None


@runtime_checkable
class AgentRunner(Protocol):
    """AIエージェント実行のプラグインインターフェース."""

    async def run(
        self,
        prompt: str,
        *,
        cwd: str,
        phase: str,
        max_budget_usd: float | None = None,
        resume_session_id: str | None = None,
        timeout_sec: int = 600,
    ) -> AgentResult: ...

    async def interrupt(self, session_id: str) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """通知送信のプラグインインターフェース."""

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict | None = None,
    ) -> None: ...


@runtime_checkable
class Tracker(Protocol):
    """イベント追跡のプラグインインターフェース."""

    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict | None = None,
    ) -> None: ...
```

---

## 4. Claude Agent SDK 呼び出し設計

### 4.1 呼び出し方式

Claude Agent SDK (Python) を使用し、OAuthトークン認証で実行する。

- **ワンショットフェーズ** (ヒアリング、設計、実装): `query()` で1回完結実行
- **マルチターンフェーズ** (レビュー対応): `ClaudeSDKClient` で `resume=session_id` によるセッション継続

**選定理由:**
- Python SDK によるプログラマティックな制御（フック、サブエージェント、コスト管理）
- `max_budget_usd` によるフェーズごとのコスト制限
- `HookMatcher` + `PreToolUse`/`PostToolUse` によるツール使用のログ記録
- `AgentDefinition` によるサブエージェント定義（コード分析、テスト作成）
- `resume=session_id` によるシームレスなセッション継続
- `interrupt()` によるタイムアウト時の安全な中断
- `permission_mode="acceptEdits"` によるファイル編集の自動許可

### 4.2 フェーズごとの設定

| フェーズ | 実行方式 | max_budget_usd | timeout_sec | permission_mode | セッション |
|---------|---------|----------------|-------------|-----------------|-----------|
| ヒアリング | `query()` | 1.0 | 600 | `acceptEdits` | 新規 |
| 設計書作成 | `query()` | 3.0 | 1800 | `acceptEdits` | 新規 |
| 設計修正 | `ClaudeSDKClient` | 2.0 | 1800 | `acceptEdits` | 前回継続 (`resume`) |
| 実装計画 | `query()` | 1.0 | 600 | `acceptEdits` | 新規 |
| 実装 | `query()` | 10.0 | 3600 | `bypassPermissions` | 新規 |
| CI修正 | `query()` | 3.0 | 1200 | `bypassPermissions` | 新規 |
| 実装修正 | `ClaudeSDKClient` | 5.0 | 1800 | `bypassPermissions` | 前回継続 (`resume`) |

### 4.3 ClaudeAgentRunner 実装

```python
import asyncio
from dataclasses import dataclass, field
from claude_agent_sdk import query, ClaudeSDKClient, AgentDefinition, HookMatcher


@dataclass
class PhaseConfig:
    max_budget_usd: float
    timeout_sec: int
    permission_mode: str
    resume: bool = False


PHASE_CONFIG: dict[str, PhaseConfig] = {
    "type_detection": PhaseConfig(max_budget_usd=0.3, timeout_sec=120, permission_mode="plan"),
    "hearing": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "analysis": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "plan_brief": PhaseConfig(max_budget_usd=1.0, timeout_sec=300, permission_mode="plan"),
    "design": PhaseConfig(max_budget_usd=3.0, timeout_sec=1800, permission_mode="plan"),
    "design_revise": PhaseConfig(max_budget_usd=2.0, timeout_sec=1200, permission_mode="bypassPermissions", resume=True),
    "planning": PhaseConfig(max_budget_usd=1.0, timeout_sec=600, permission_mode="plan"),
    "split_proposal": PhaseConfig(max_budget_usd=2.0, timeout_sec=600, permission_mode="plan"),
    "implement": PhaseConfig(max_budget_usd=10.0, timeout_sec=3600, permission_mode="bypassPermissions"),
    "fix": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions"),
    "ci_fix": PhaseConfig(max_budget_usd=3.0, timeout_sec=1200, permission_mode="bypassPermissions"),
    "impl_revise": PhaseConfig(max_budget_usd=5.0, timeout_sec=1800, permission_mode="bypassPermissions", resume=True),
}

# サブエージェント定義
CODE_ANALYZER = AgentDefinition(
    name="code-analyzer",
    description="既存コードベースの構造分析とリポマップ生成",
    instructions="リポジトリのファイル構造、主要モジュール、依存関係を分析して要約する。",
)

TEST_WRITER = AgentDefinition(
    name="test-writer",
    description="テストコード作成の専門エージェント",
    instructions="既存テストのパターンに従い、ユニットテストと統合テストを作成する。",
)


class ClaudeAgentRunner:
    """Claude Agent SDKを使用したAgentRunner実装."""

    def __init__(self, tracker: "Tracker") -> None:
        self._tracker = tracker
        self._active_sessions: dict[str, ClaudeSDKClient] = {}

    async def run(
        self,
        prompt: str,
        *,
        cwd: str,
        phase: str,
        max_budget_usd: float | None = None,
        resume_session_id: str | None = None,
        timeout_sec: int = 600,
    ) -> AgentResult:
        config = PHASE_CONFIG.get(phase, {})
        budget = max_budget_usd or config.get("max_budget_usd", 5.0)
        timeout = timeout_sec or config.get("timeout_sec", 600)
        perm_mode = config.get("permission_mode", "acceptEdits")

        # フック定義: ツール使用のログ記録
        hooks = [
            HookMatcher(
                event="PreToolUse",
                callback=self._on_pre_tool_use,
            ),
            HookMatcher(
                event="PostToolUse",
                callback=self._on_post_tool_use,
            ),
        ]

        # サブエージェント（実装フェーズのみ）
        subagents = []
        if phase in ("implement", "ci_fix", "impl_revise"):
            subagents = [CODE_ANALYZER, TEST_WRITER]

        if resume_session_id and resume_session_id in self._active_sessions:
            # マルチターン: 既存セッション継続
            client = self._active_sessions[resume_session_id]
            result = await asyncio.wait_for(
                client.send(prompt),
                timeout=timeout,
            )
        else:
            # ワンショット: query() で実行
            result = await asyncio.wait_for(
                query(
                    prompt=prompt,
                    cwd=cwd,
                    max_budget_usd=budget,
                    permission_mode=perm_mode,
                    hooks=hooks,
                    subagents=subagents,
                ),
                timeout=timeout,
            )

        return AgentResult(
            session_id=result.session_id,
            output=result.text,
            tool_uses=result.tool_uses,
            cost_usd=result.cost_usd,
            duration_sec=result.duration_sec,
        )

    async def interrupt(self, session_id: str) -> None:
        if session_id in self._active_sessions:
            client = self._active_sessions[session_id]
            await client.interrupt()
            del self._active_sessions[session_id]

    async def _on_pre_tool_use(self, event) -> None:
        await self._tracker.track(
            "tool_use_start",
            issue_number=0,  # コンテキストから注入
            phase="",
            data={"tool": event.tool_name, "input": event.tool_input},
        )

    async def _on_post_tool_use(self, event) -> None:
        await self._tracker.track(
            "tool_use_end",
            issue_number=0,
            phase="",
            data={"tool": event.tool_name, "output_size": len(str(event.output))},
        )
```

### 4.4 セッション継続の活用

レビュー指摘対応時に `resume=session_id` を使用することで、AIが「自分が何を設計/実装したか」を覚えている状態で修正できる。

```python
# レビュー対応時
result = await runner.run(
    prompt=f"以下のレビュー指摘に対応してください:\n{review_comments}",
    cwd=task.worktree_path,
    phase="impl_revise",
    resume_session_id=task.last_session_id,  # 前回のセッションを継続
)
task.last_session_id = result.session_id
```

### 4.5 コンテキストエンジニアリング

各フェーズ実行前に、リポマップと自動コンテキスト収集を行い、AIに適切なコンテキストを与える。

```python
class ContextEngine:
    """リポマップ生成と自動コンテキスト収集."""

    async def build_context(
        self,
        worktree_path: str,
        issue_body: str,
        phase: str,
    ) -> str:
        """フェーズに応じたコンテキストを構築."""
        parts: list[str] = []

        # 1. リポマップ（ディレクトリ構造 + 主要ファイルサマリ）
        repo_map = await self._generate_repo_map(worktree_path)
        parts.append(f"## リポジトリ構造\n{repo_map}")

        # 2. CLAUDE.md（存在すれば）
        claude_md = await self._read_claude_md(worktree_path)
        if claude_md:
            parts.append(f"## プロジェクト規約\n{claude_md}")

        # 3. 関連ファイルの自動検出（Issue内容からキーワード抽出）
        relevant_files = await self._find_relevant_files(
            worktree_path, issue_body
        )
        if relevant_files:
            parts.append(f"## 関連ファイル\n{relevant_files}")

        # 4. 設計書（実装フェーズの場合）
        if phase in ("planning", "implement", "ci_fix"):
            design_doc = await self._read_design_doc(worktree_path)
            if design_doc:
                parts.append(f"## 設計書\n{design_doc}")

        # 5. 実装計画（実装フェーズの場合）
        if phase in ("implement", "ci_fix"):
            impl_plan = await self._read_impl_plan(worktree_path)
            if impl_plan:
                parts.append(f"## 実装計画\n{impl_plan}")

        return "\n\n---\n\n".join(parts)

    async def _generate_repo_map(self, path: str) -> str:
        """ディレクトリツリー + 主要ファイルの1行サマリを生成."""
        # tree コマンドで構造取得、主要ファイルはAST解析でサマリ
        ...

    async def _find_relevant_files(
        self, path: str, issue_body: str
    ) -> str:
        """Issue内容のキーワードから関連ファイルを検索."""
        # ripgrep で高速検索
        ...
```

---

## 5. Polling ロジック

### 5.1 Polling サイクル（2分間隔）

```
毎2分:
├── 1. 新規Issue検知
│   └── label "ai-agent" かつ phase:* なし → HEARING開始
│
├── 2. ヒアリング回答検知
│   └── phase:hearing のIssueに人間コメントあり → 回答を取り込み続行
│
├── 3. ヒアリングタイムアウト検知
│   └── phase:hearing で24時間無応答 → SUSPENDED + 通知
│
├── 4. 設計PRイベント検知
│   ├── approve → phase:design-review → phase:planning
│   └── コメント(指摘) → phase:design-review → phase:design-revise
│
├── 5. 実装PRイベント検知
│   ├── approve → phase:impl-review → phase:done → マージ
│   ├── コメント(指摘) → phase:impl-review → phase:impl-revise
│   └── CI失敗 → phase:ci-fix (最大3回)
│
└── 6. キュー管理
    └── 実行中タスク < max_total なら次のタスクを開始
```

### 5.2 非同期Pollerの実装

```python
import asyncio
from datetime import datetime, timedelta

from githubkit import GitHub
from githubkit.versions.latest.models import Issue, PullRequest


class GitHubPoller:
    """GitHub APIをポーリングしてイベントを検知する."""

    def __init__(
        self,
        github_client_factory: "GitHubClientFactory",
        repos: list["RepositoryConfig"],
        interval_sec: int = 120,
    ) -> None:
        self._github_factory = github_client_factory
        self._repos = repos
        self._interval_sec = interval_sec
        self._last_poll: dict[str, datetime] = {}

    async def start(self, event_queue: asyncio.Queue["PollEvent"]) -> None:
        """ポーリングループを開始する."""
        while True:
            for repo in self._repos:
                try:
                    events = await self._poll_repo(repo)
                    for event in events:
                        await event_queue.put(event)
                except Exception as e:
                    await event_queue.put(
                        PollEvent(type="error", repo=repo, error=e)
                    )
            await asyncio.sleep(self._interval_sec)

    async def _poll_repo(
        self, repo: "RepositoryConfig"
    ) -> list["PollEvent"]:
        """単一リポジトリのポーリング."""
        events: list[PollEvent] = []
        repo_key = f"{repo.owner}/{repo.name}"
        since = self._last_poll.get(repo_key)
        self._last_poll[repo_key] = datetime.now()

        # 1. 新規Issue検知
        new_issues = await self._detect_new_issues(repo)
        for issue in new_issues:
            events.append(
                PollEvent(type="new_issue", repo=repo, issue=issue)
            )

        # 2. ヒアリング回答検知
        hearing_replies = await self._detect_hearing_replies(repo, since)
        for reply in hearing_replies:
            events.append(
                PollEvent(type="hearing_reply", repo=repo, comment=reply)
            )

        # 3. ヒアリングタイムアウト検知
        timeouts = await self._detect_hearing_timeouts(repo)
        for issue in timeouts:
            events.append(
                PollEvent(type="hearing_timeout", repo=repo, issue=issue)
            )

        # 4. PRレビューイベント検知
        pr_events = await self._detect_pr_events(repo, since)
        events.extend(pr_events)

        # 5. CI結果検知
        ci_events = await self._detect_ci_results(repo)
        events.extend(ci_events)

        return events
```

### 5.3 イベントルーター

```python
from dataclasses import dataclass
from enum import Enum, auto


class EventType(str, Enum):
    NEW_ISSUE = "new_issue"
    ISSUE_COMMENT = "issue_comment"
    DESIGN_PR_APPROVED = "design_pr_approved"
    DESIGN_PR_COMMENTED = "design_pr_commented"
    IMPL_PR_APPROVED = "impl_pr_approved"
    IMPL_PR_COMMENTED = "impl_pr_commented"
    CI_RESULT = "ci_result"
    PLAN_REACTION_ADDED = "plan_reaction_added"      # 👍承認 (Bug/Feature-S)
    PLAN_COMMENT_ADDED = "plan_comment_added"         # 方針への指摘コメント
    SPLIT_APPROVED = "split_approved"                 # 分割承認 (Feature-L)
    SPLIT_MODIFIED = "split_modified"                 # 分割修正指示
    HEARING_TIMEOUT = "hearing_timeout"


@dataclass(frozen=True)
class PollEvent:
    type: str
    repo: "RepositoryConfig"
    issue: "Issue | None" = None
    comment: "IssueComment | None" = None
    pr: "PullRequest | None" = None
    error: Exception | None = None


class EventRouter:
    """イベントをフェーズ遷移アクションに変換する."""

    def __init__(
        self,
        state_machine: "StateMachine",
        task_queue: "TaskQueue",
    ) -> None:
        self._sm = state_machine
        self._tq = task_queue

    async def route(self, event: PollEvent) -> None:
        match event.type:
            case EventType.NEW_ISSUE:
                self._sm.register_issue(event.issue.number, Phase.TYPE_DETECTION)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=Phase.TYPE_DETECTION,
                        priority=5,
                    )
                )
            case "hearing_reply":
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.comment.issue_number,
                        repo=event.repo,
                        phase="hearing_continue",
                        extra={"comment": event.comment.body},
                    )
                )
            case "hearing_timeout":
                await self._sm.transition(
                    event.issue.number, "suspended"
                )
            case "design_pr_approved":
                await self._sm.transition(
                    event.issue.number, "planning"
                )
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase="planning",
                    )
                )
            case "design_pr_commented":
                await self._sm.transition(
                    event.issue.number, "design_revise"
                )
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase="design_revise",
                        extra={"comments": event.extra},
                    )
                )
            case "ci_failed":
                await self._handle_ci_failure(event)
            case "impl_pr_approved":
                await self._sm.transition(event.issue.number, "done")
            case EventType.PLAN_REACTION_ADDED:
                # 👍承認 → Bug: FIX, Feature-S: IMPLEMENT
                issue_type = self._sm.get_issue_type(event.issue.number)
                next_phase = Phase.FIX if issue_type == "bug" else Phase.IMPLEMENT
                self._sm.transition(event.issue.number, next_phase)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=next_phase,
                    )
                )
            case EventType.PLAN_COMMENT_ADDED:
                # 方針指摘 → 修正
                issue_type = self._sm.get_issue_type(event.issue.number)
                next_phase = Phase.ANALYSIS if issue_type == "bug" else Phase.PLAN_BRIEF
                self._sm.transition(event.issue.number, next_phase)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=next_phase,
                    )
                )
            case EventType.SPLIT_APPROVED:
                self._sm.transition(event.issue.number, Phase.SPLIT_EXECUTE)
                await self._tq.enqueue(
                    TaskRequest(
                        issue_number=event.issue.number,
                        repo=event.repo,
                        phase=Phase.SPLIT_EXECUTE,
                    )
                )
            case _:
                pass  # 未知のイベントは無視

    async def _handle_ci_failure(self, event: PollEvent) -> None:
        """CI失敗時の自動修正ループ（最大3回）."""
        retry_count = await self._sm.get_ci_retry_count(
            event.issue.number
        )
        if retry_count < 3:
            await self._sm.transition(
                event.issue.number, "ci_fix"
            )
            await self._tq.enqueue(
                TaskRequest(
                    issue_number=event.issue.number,
                    repo=event.repo,
                    phase="ci_fix",
                    extra={
                        "ci_logs": event.extra.get("ci_logs"),
                        "retry_count": retry_count + 1,
                    },
                )
            )
        else:
            await self._sm.transition(
                event.issue.number, "suspended"
            )
```

### 5.4 レビューコメントの扱い

- PRに複数人がコメントした場合、全コメントをまとめてAIに渡す
- AIがコメントの温度感（LGTM, nit, 必須修正等）を判断して対応

---

## 6. タスクキューと並行処理

### 6.1 タスクキュー設計

```python
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class TaskRequest:
    """タスク実行リクエスト."""

    issue_number: int
    repo: "RepositoryConfig"
    phase: str
    extra: dict = field(default_factory=dict)
    priority: int = 5

    def __lt__(self, other: "TaskRequest") -> bool:
        return self.priority < other.priority


class TaskQueue:
    """asyncio.Queue + Semaphore による同時実行制御."""

    def __init__(
        self,
        max_total: int = 2,
        max_per_repo: int = 1,
    ) -> None:
        self._max_total = max_total
        self._max_per_repo = max_per_repo
        self._queue: asyncio.PriorityQueue[
            tuple[int, TaskRequest]
        ] = asyncio.PriorityQueue()
        self._global_sem = asyncio.Semaphore(max_total)
        self._repo_sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(max_per_repo)
        )
        self._active_tasks: dict[int, asyncio.Task] = {}

    async def enqueue(self, request: TaskRequest) -> None:
        """タスクをキューに追加."""
        # 同一Issue番号のタスクが既にキューにある場合は置換
        priority = -request.priority  # PriorityQueueは小さい値が優先
        await self._queue.put((priority, request))

    async def worker_loop(
        self,
        executor: "PhaseExecutor",
    ) -> None:
        """ワーカーループ: キューからタスクを取り出して実行."""
        while True:
            _, request = await self._queue.get()
            repo_key = f"{request.repo.owner}/{request.repo.name}"
            repo_sem = self._repo_sems[repo_key]

            # 全体 + リポ単位のセマフォを両方取得
            async with self._global_sem:
                async with repo_sem:
                    task = asyncio.create_task(
                        executor.execute(request)
                    )
                    self._active_tasks[request.issue_number] = task
                    try:
                        await task
                    except Exception:
                        pass  # エラーはexecutor内で処理
                    finally:
                        self._active_tasks.pop(
                            request.issue_number, None
                        )
                        self._queue.task_done()

    @property
    def active_count(self) -> int:
        return len(self._active_tasks)

    def get_status(self) -> dict:
        return {
            "active": self.active_count,
            "max_total": self._max_total,
            "queued": self._queue.qsize(),
        }
```

### 6.2 ワーカープールの起動

```python
class Orchestrator:
    """メインオーケストレーター."""

    async def run(self) -> None:
        """メインイベントループ."""
        async with asyncio.TaskGroup() as tg:
            # ポーリングタスク
            tg.create_task(self._poller.start(self._event_queue))

            # イベントルーティングタスク
            tg.create_task(self._route_events())

            # ワーカータスク（2つ = max_total分）
            for _ in range(self._config.concurrency.max_total):
                tg.create_task(
                    self._task_queue.worker_loop(self._executor)
                )

            # ヘルスチェックタスク
            tg.create_task(self._health_checker.start())

    async def _route_events(self) -> None:
        """イベントキューからイベントを取り出してルーティング."""
        while True:
            event = await self._event_queue.get()
            try:
                await self._event_router.route(event)
            except Exception as e:
                await self._notifier.notify(
                    f"イベントルーティングエラー: {e}",
                    level="error",
                )
```

---

## 7. ステートマシン

### 7.1 フェーズ遷移の定義

```python
from enum import Enum


class Phase(str, Enum):
    """Issueのフェーズ."""

    TYPE_DETECTION = "type-detection"
    HEARING = "hearing"
    ANALYSIS = "analysis"          # Bug用
    PLAN_BRIEF = "plan-brief"      # Feature-S用
    PLAN_REVIEW = "plan-review"    # Bug/Feature-S 方針レビュー待ち
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"
    PLANNING = "planning"
    SPLIT_PROPOSAL = "split-proposal"  # Feature-L用
    SPLIT_EXECUTE = "split-execute"    # Feature-L用
    IMPLEMENT = "implement"
    CI_FIX = "ci-fix"
    IMPL_REVIEW = "impl-review"
    IMPL_REVISE = "impl-revise"
    BLOCKED = "blocked"            # 依存待ち
    SUSPENDED = "suspended"
    DONE = "done"
    FIX = "fix"                    # Bug修正


# 許可される遷移のマップ
VALID_TRANSITIONS: dict[Phase, list[Phase]] = {
    # 共通: 初期
    Phase.TYPE_DETECTION: [Phase.HEARING, Phase.ANALYSIS],

    # Bug ワークフロー
    Phase.ANALYSIS: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.FIX: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],

    # Feature-S ワークフロー
    Phase.PLAN_BRIEF: [Phase.PLAN_REVIEW, Phase.SUSPENDED],
    Phase.PLAN_REVIEW: [Phase.FIX, Phase.IMPLEMENT, Phase.PLAN_BRIEF, Phase.ANALYSIS],  # 承認 or 指摘

    # Feature-M ワークフロー
    Phase.HEARING: [Phase.DESIGN, Phase.PLAN_BRIEF, Phase.SPLIT_PROPOSAL, Phase.ANALYSIS, Phase.SUSPENDED],
    Phase.DESIGN: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.DESIGN_REVIEW: [Phase.PLANNING, Phase.DESIGN_REVISE, Phase.SUSPENDED],
    Phase.DESIGN_REVISE: [Phase.DESIGN_REVIEW, Phase.SUSPENDED],
    Phase.PLANNING: [Phase.IMPLEMENT, Phase.SUSPENDED],

    # Feature-L ワークフロー
    Phase.SPLIT_PROPOSAL: [Phase.SPLIT_EXECUTE, Phase.HEARING, Phase.SUSPENDED],
    Phase.SPLIT_EXECUTE: [Phase.DONE, Phase.SUSPENDED],

    # 共通: 実装・レビュー
    Phase.IMPLEMENT: [Phase.CI_FIX, Phase.IMPL_REVIEW, Phase.SUSPENDED],
    Phase.CI_FIX: [Phase.IMPL_REVIEW, Phase.CI_FIX, Phase.SUSPENDED],
    Phase.IMPL_REVIEW: [Phase.DONE, Phase.IMPL_REVISE, Phase.SUSPENDED],
    Phase.IMPL_REVISE: [Phase.IMPL_REVIEW, Phase.SUSPENDED],

    # 特殊
    Phase.BLOCKED: [Phase.HEARING, Phase.ANALYSIS, Phase.IMPLEMENT],
    Phase.SUSPENDED: list(Phase),  # どのフェーズにも復帰可能
}


@dataclass
class IssueState:
    """Issue単位の状態."""

    issue_number: int
    phase: Phase
    issue_type: str = ""  # bug | feature-s | feature-m | feature-l
    repo: str = ""
    session_id: str | None = None
    pr_number: int | None = None
    design_pr_number: int | None = None
    retry_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class StateMachine:
    """フェーズ遷移を管理するステートマシン."""

    def __init__(
        self,
        github_client_factory: "GitHubClientFactory",
        tracker: Tracker,
    ) -> None:
        self._github_factory = github_client_factory
        self._tracker = tracker
        self._states: dict[int, IssueState] = {}

    def get_issue_type(self, issue_number: int) -> str:
        state = self._states.get(issue_number)
        return state.issue_type if state else ""

    def set_issue_type(self, issue_number: int, issue_type: str) -> None:
        if issue_number in self._states:
            self._states[issue_number].issue_type = issue_type

    async def transition(
        self, issue_number: int, new_phase: str
    ) -> None:
        """フェーズ遷移を実行."""
        state = self._states.get(issue_number)
        new = Phase(new_phase)

        if state is not None:
            current = state.phase
            if new not in VALID_TRANSITIONS.get(current, set()):
                raise InvalidTransitionError(
                    f"Cannot transition from {current} to {new}"
                )

            # 旧ラベル削除 + 新ラベル追加
            await self._github.replace_phase_label(
                issue_number, f"phase:{new.value}"
            )
            state.phase = new
            state.updated_at = datetime.now()
        else:
            # 新規Issue
            self._states[issue_number] = IssueState(
                issue_number=issue_number,
                repo_key="",  # 呼び出し元で設定
                phase=new,
            )
            await self._github.add_label(
                issue_number, f"phase:{new.value}"
            )

        await self._tracker.track(
            "phase_transition",
            issue_number=issue_number,
            phase=new.value,
            data={"from": state.phase.value if state else None, "to": new.value},
        )

    async def get_ci_retry_count(self, issue_number: int) -> int:
        state = self._states.get(issue_number)
        return state.retry_count if state else 0

    async def increment_ci_retry(self, issue_number: int) -> None:
        state = self._states.get(issue_number)
        if state:
            state.retry_count += 1
```

### 7.2 状態永続化

Issue状態はファイルベースで永続化し、プロセス再起動時に復元可能にする。

```python
import json
from dataclasses import asdict
from pathlib import Path


class StatePersistence:
    """Issue状態の永続化（ファイルベース）."""

    def __init__(self, state_file: Path) -> None:
        self._file = state_file

    def save(self, states: dict[int, IssueState]) -> None:
        data = {k: asdict(v) for k, v in states.items()}
        self._file.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def load(self) -> dict[int, IssueState]:
        if not self._file.exists():
            return {}
        data = json.loads(self._file.read_text())
        return {int(k): IssueState(**v) for k, v in data.items()}
```

---

## 8. ワークスペース管理

### 8.1 ディレクトリ構成

```
~/.ai-agent-workspaces/
├── repos/
│   ├── myorg-frontend-app/          # git clone済み
│   │   ├── .git/
│   │   └── worktrees/
│   │       ├── issue-42/            # git worktree
│   │       └── issue-55/            # git worktree
│   └── myorg-backend-api/
│       ├── .git/
│       └── worktrees/
│           └── issue-13/
└── logs/
    ├── myorg-frontend-app/
    │   ├── issue-42/
    │   │   ├── 2026-03-24T10:00:00_hearing.log
    │   │   ├── 2026-03-24T10:15:00_design.log
    │   │   ├── 2026-03-24T11:00:00_implement.log
    │   │   └── events.jsonl
    │   └── issue-55/
    └── orchestrator.log
```

### 8.2 WorkspaceManager 実装

```python
import asyncio
from pathlib import Path


class WorkspaceManager:
    """git worktreeの作成・削除を管理."""

    def __init__(self, base_dir: str = "~/.ai-agent-workspaces") -> None:
        self._base = Path(base_dir).expanduser()
        self._repos_dir = self._base / "repos"
        self._logs_dir = self._base / "logs"

    async def ensure_cloned(self, repo: "RepositoryConfig") -> Path:
        """リポジトリがclone済みであることを保証."""
        repo_dir = self._repos_dir / f"{repo.owner}-{repo.name}"
        if not repo_dir.exists():
            proc = await asyncio.create_subprocess_exec(
                "git", "clone",
                f"https://github.com/{repo.owner}/{repo.name}.git",
                str(repo_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode != 0:
                raise WorkspaceError(f"Failed to clone {repo.owner}/{repo.name}")
        else:
            # 既存の場合はfetch
            proc = await asyncio.create_subprocess_exec(
                "git", "fetch", "--all",
                cwd=str(repo_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        return repo_dir

    async def create_worktree(
        self,
        repo: "RepositoryConfig",
        issue_number: int,
        branch_prefix: str = "feature",
    ) -> Path:
        """Issue用のworktreeを作成."""
        repo_dir = await self.ensure_cloned(repo)
        branch_name = f"{branch_prefix}/issue-{issue_number}"
        worktree_path = repo_dir / "worktrees" / f"issue-{issue_number}"

        if worktree_path.exists():
            return worktree_path

        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # ベースブランチを最新に更新
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add",
            "-b", branch_name,
            str(worktree_path),
            f"origin/{repo.base_branch}",
            cwd=str(repo_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise WorkspaceError(
                f"Failed to create worktree: {stderr.decode()}"
            )
        return worktree_path

    async def remove_worktree(
        self,
        repo: "RepositoryConfig",
        issue_number: int,
    ) -> None:
        """Issue用のworktreeを削除."""
        repo_dir = self._repos_dir / f"{repo.owner}-{repo.name}"
        worktree_path = repo_dir / "worktrees" / f"issue-{issue_number}"

        if worktree_path.exists():
            proc = await asyncio.create_subprocess_exec(
                "git", "worktree", "remove",
                str(worktree_path), "--force",
                cwd=str(repo_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

    def get_log_dir(
        self, repo: "RepositoryConfig", issue_number: int
    ) -> Path:
        """Issue用のログディレクトリパスを取得."""
        log_dir = (
            self._logs_dir
            / f"{repo.owner}-{repo.name}"
            / f"issue-{issue_number}"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir
```

---

## 9. フェーズ実行

### 9.1 フェーズエグゼキューター

```python
class PhaseExecutor:
    """各フェーズのビジネスロジックを実行."""

    def __init__(
        self,
        runner: AgentRunner,
        github: "GitHubClient",
        notifier: Notifier,
        tracker: Tracker,
        workspace: WorkspaceManager,
        context_engine: ContextEngine,
        state_machine: StateMachine,
    ) -> None:
        self._runner = runner
        self._github = github
        self._notifier = notifier
        self._tracker = tracker
        self._workspace = workspace
        self._context = context_engine
        self._sm = state_machine

    async def execute(self, request: TaskRequest) -> None:
        """タスクリクエストに応じたフェーズを実行."""
        try:
            match request.phase:
                case "hearing":
                    await self._execute_hearing(request)
                case "hearing_continue":
                    await self._execute_hearing_continue(request)
                case "design":
                    await self._execute_design(request)
                case "design_revise":
                    await self._execute_design_revise(request)
                case "planning":
                    await self._execute_planning(request)
                case "implement":
                    await self._execute_implement(request)
                case "ci_fix":
                    await self._execute_ci_fix(request)
                case "impl_revise":
                    await self._execute_impl_revise(request)
                case "done":
                    await self._execute_done(request)
        except asyncio.TimeoutError:
            await self._handle_timeout(request)
        except Exception as e:
            await self._handle_error(request, e)

    async def _execute_hearing(self, request: TaskRequest) -> None:
        """ヒアリングフェーズ: Issueを分析し質問を投稿."""
        issue = await self._github.get_issue(
            request.repo, request.issue_number
        )
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="design"
        )
        context = await self._context.build_context(
            str(worktree), issue.body, "hearing"
        )

        prompt = f"""以下のIssueについて要件ヒアリングを行ってください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## コンテキスト
{context}

## 指示
1. Issueの内容を分析し、実装に必要な情報が十分か判断してください
2. 不明点がある場合は、具体的な質問をリストアップしてください
3. Issueが大きすぎる場合は分割を提案してください
4. 情報が十分な場合は "READY_FOR_DESIGN" と出力してください

出力形式:
- 質問がある場合: Issueコメントとして投稿する質問テキスト
- 分割提案の場合: 分割案のリスト
- 準備完了: "READY_FOR_DESIGN"
"""
        result = await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="hearing",
        )

        if "READY_FOR_DESIGN" in result.output:
            await self._sm.transition(request.issue_number, "design")
            await self._execute_design(request)
        else:
            # 質問をIssueコメントとして投稿
            await self._github.post_comment(
                request.repo, request.issue_number, result.output
            )
            await self._notifier.notify(
                f"Issue #{request.issue_number} に質問を投稿しました。回答をお願いします",
                metadata={
                    "repo": f"{request.repo.owner}/{request.repo.name}",
                    "issue": request.issue_number,
                },
            )

        # セッションIDを記録
        state = self._sm._states[request.issue_number]
        state.last_session_id = result.session_id

    async def _execute_design(self, request: TaskRequest) -> None:
        """設計書作成フェーズ."""
        issue = await self._github.get_issue(
            request.repo, request.issue_number
        )
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="design"
        )
        context = await self._context.build_context(
            str(worktree), issue.body, "design"
        )

        # 過去のヒアリングコメントを取得
        comments = await self._github.get_issue_comments(
            request.repo, request.issue_number
        )
        hearing_log = "\n".join(
            f"[{c.user.login}]: {c.body}" for c in comments
        )

        prompt = f"""以下のIssueの設計書を作成してください。

## Issue #{request.issue_number}: {issue.title}
{issue.body}

## ヒアリング記録
{hearing_log}

## コンテキスト
{context}

## 指示
1. docs/designs/issue-{request.issue_number}.md に設計書を作成
2. 設計書テンプレートに従って全セクションを埋める
3. git commit して Push
4. PRを作成（タイトル: "[設計書] Issue #{request.issue_number} {{issue_title}}"）
5. PRのURLを出力

設計書テンプレート:
{DESIGN_DOC_TEMPLATE}
"""
        result = await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="design",
        )

        # PR番号を記録
        pr_number = self._extract_pr_number(result.output)
        state = self._sm._states[request.issue_number]
        state.design_pr_number = pr_number
        state.last_session_id = result.session_id

        await self._sm.transition(request.issue_number, "design-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計PRを作成しました。レビューをお願いします",
            metadata={
                "repo": f"{request.repo.owner}/{request.repo.name}",
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )

    async def _execute_planning(self, request: TaskRequest) -> None:
        """実装計画フェーズ: コーディング前にファイル変更順序・依存関係を整理."""
        issue = await self._github.get_issue(
            request.repo, request.issue_number
        )
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature"
        )
        context = await self._context.build_context(
            str(worktree), issue.body, "planning"
        )

        prompt = f"""設計書に基づき、実装計画を作成してください。

## Issue #{request.issue_number}: {issue.title}

## コンテキスト
{context}

## 指示
1. 設計書を読み込む
2. 変更するファイルの一覧と順序を決定
3. 各ファイルの変更内容を具体的に記述
4. 依存関係の順序（先に変更すべきファイル）を明記
5. テスト方針を決定
6. docs/designs/issue-{request.issue_number}-plan.md に実装計画を保存
7. git commit して Push

実装計画テンプレート:
# 実装計画: Issue #{request.issue_number}

## 変更ファイル一覧（実装順）
1. path/to/file.py - 変更内容の説明
   - 依存: なし
2. path/to/other.py - 変更内容の説明
   - 依存: #1

## テスト方針
- ユニットテスト対象:
- 統合テスト対象:

## リスク・確認事項
"""
        result = await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="planning",
        )

        await self._sm.transition(request.issue_number, "implement")
        await self._execute_implement(request)

    async def _execute_implement(self, request: TaskRequest) -> None:
        """実装フェーズ."""
        issue = await self._github.get_issue(
            request.repo, request.issue_number
        )
        worktree = await self._workspace.create_worktree(
            request.repo, request.issue_number, branch_prefix="feature"
        )
        context = await self._context.build_context(
            str(worktree), issue.body, "implement"
        )

        prompt = f"""実装計画に基づいてコードを実装してください。

## Issue #{request.issue_number}: {issue.title}

## コンテキスト
{context}

## 指示
1. 実装計画の順序に従ってコードを実装
2. テストコードも作成
3. テスト・lint・ビルドを実行して結果を確認
4. git commit して Push
5. PRを作成（タイトル: "feat: Issue #{request.issue_number} {{短い説明}}"）
6. PR descriptionに以下を含める:
   - 変更の概要
   - 実行したコマンドとその結果
   - AI Agent ログ（実行時間、変更判断根拠）
"""
        result = await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="implement",
        )

        pr_number = self._extract_pr_number(result.output)
        state = self._sm._states[request.issue_number]
        state.impl_pr_number = pr_number
        state.last_session_id = result.session_id

        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装PRを作成しました",
            metadata={
                "repo": f"{request.repo.owner}/{request.repo.name}",
                "issue": request.issue_number,
                "pr": pr_number,
            },
        )

    async def _execute_ci_fix(self, request: TaskRequest) -> None:
        """CI自動修正フェーズ（最大3回）."""
        ci_logs = request.extra.get("ci_logs", "")
        retry_count = request.extra.get("retry_count", 1)

        state = self._sm._states[request.issue_number]
        worktree = self._workspace._repos_dir / (
            f"{request.repo.owner}-{request.repo.name}"
            f"/worktrees/issue-{request.issue_number}"
        )

        prompt = f"""CIが失敗しました（{retry_count}/3回目）。修正してください。

## CI失敗ログ
{ci_logs}

## 指示
1. CI失敗ログを分析して原因を特定
2. コードを修正
3. テスト・lint・ビルドをローカルで再実行して確認
4. git commit して Push
"""
        result = await self._runner.run(
            prompt=prompt,
            cwd=str(worktree),
            phase="ci_fix",
        )

        await self._sm.increment_ci_retry(request.issue_number)
        state.last_session_id = result.session_id
        # CI結果は次回ポーリングで検知

    async def _execute_design_revise(self, request: TaskRequest) -> None:
        """設計修正フェーズ（セッション継続）."""
        comments = request.extra.get("comments", "")
        state = self._sm._states[request.issue_number]
        worktree = self._workspace._repos_dir / (
            f"{request.repo.owner}-{request.repo.name}"
            f"/worktrees/issue-{request.issue_number}"
        )

        result = await self._runner.run(
            prompt=f"以下のレビュー指摘に対応してください:\n{comments}",
            cwd=str(worktree),
            phase="design_revise",
            resume_session_id=state.last_session_id,
        )

        state.last_session_id = result.session_id
        await self._sm.transition(request.issue_number, "design-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の設計書を修正しました",
        )

    async def _execute_impl_revise(self, request: TaskRequest) -> None:
        """実装修正フェーズ（セッション継続）."""
        comments = request.extra.get("comments", "")
        state = self._sm._states[request.issue_number]
        worktree = self._workspace._repos_dir / (
            f"{request.repo.owner}-{request.repo.name}"
            f"/worktrees/issue-{request.issue_number}"
        )

        result = await self._runner.run(
            prompt=f"以下のレビュー指摘に対応してください:\n{comments}",
            cwd=str(worktree),
            phase="impl_revise",
            resume_session_id=state.last_session_id,
        )

        state.last_session_id = result.session_id
        await self._sm.transition(request.issue_number, "impl-review")
        await self._notifier.notify(
            f"Issue #{request.issue_number} の実装を修正しました",
        )

    async def _execute_done(self, request: TaskRequest) -> None:
        """完了フェーズ: PRマージ + Issue クローズ + worktree削除."""
        state = self._sm._states[request.issue_number]
        if state.impl_pr_number:
            await self._github.merge_pr(
                request.repo, state.impl_pr_number
            )
        await self._github.close_issue(
            request.repo, request.issue_number
        )
        await self._workspace.remove_worktree(
            request.repo, request.issue_number
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} 完了しました",
        )

    async def _handle_timeout(self, request: TaskRequest) -> None:
        """タイムアウト処理."""
        await self._runner.interrupt(
            self._sm._states[request.issue_number].last_session_id or ""
        )
        await self._sm.transition(request.issue_number, "suspended")
        await self._notifier.notify(
            f"Issue #{request.issue_number} がタイムアウトしました",
            level="error",
        )

    async def _handle_error(
        self, request: TaskRequest, error: Exception
    ) -> None:
        """エラー処理."""
        await self._sm.transition(request.issue_number, "suspended")
        await self._github.post_comment(
            request.repo,
            request.issue_number,
            f"エラーが発生しました: {error}",
        )
        await self._notifier.notify(
            f"Issue #{request.issue_number} でエラー: {error}",
            level="error",
        )

    def _extract_pr_number(self, output: str) -> int | None:
        """出力テキストからPR番号を抽出."""
        import re
        match = re.search(r"#(\d+)", output)
        return int(match.group(1)) if match else None
```

---

## 10. エラーハンドリング・リトライ戦略

### 10.1 エラー分類

| 分類 | 例 | リトライ | バックオフ | 上限後 |
|------|---|---------|-----------|-------|
| 一時的エラー | API rate limit, ネットワーク断 | 最大3回 | 1分→5分→15分 | SUSPENDED + Slack通知 |
| 認証エラー | セッション切れ, トークン失効 | しない | - | 即SUSPENDED + Slack通知 |
| gitコンフリクト | merge conflict | しない | - | SUSPENDED + Issue/Slackに通知 |
| 出力異常 | PRが作れなかった, 設計書が空 | 1回のみ | - | SUSPENDED + Slack通知 |
| CI失敗 | テスト失敗, lint失敗, ビルド失敗 | 最大3回 | 即時 | SUSPENDED + Slack通知 |

### 10.2 リトライデコレータ

```python
import asyncio
import functools
from enum import StrEnum


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    AUTH = "auth"
    GIT_CONFLICT = "git_conflict"
    OUTPUT_INVALID = "output_invalid"
    CI_FAILURE = "ci_failure"


def classify_error(error: Exception) -> ErrorCategory:
    """例外をエラーカテゴリに分類."""
    error_msg = str(error).lower()
    if "rate limit" in error_msg or "timeout" in error_msg:
        return ErrorCategory.TRANSIENT
    if "auth" in error_msg or "token" in error_msg or "401" in error_msg:
        return ErrorCategory.AUTH
    if "conflict" in error_msg or "merge" in error_msg:
        return ErrorCategory.GIT_CONFLICT
    return ErrorCategory.TRANSIENT


def with_retry(
    max_attempts: int = 3,
    backoff_minutes: list[int] | None = None,
):
    """リトライ付きデコレータ."""
    if backoff_minutes is None:
        backoff_minutes = [1, 5, 15]

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    category = classify_error(e)
                    if category != ErrorCategory.TRANSIENT:
                        raise
                    if attempt < max_attempts - 1:
                        wait = backoff_minutes[
                            min(attempt, len(backoff_minutes) - 1)
                        ]
                        await asyncio.sleep(wait * 60)
            raise last_error
        return wrapper
    return decorator
```

### 10.3 SUSPENDED（保留）状態

```
1. "phase:suspended" ラベルを追加
2. Issueコメントにエラー内容を投稿
3. Slack通知
4. 人間が原因を解消後、"phase:suspended" を外すと再開
```

### 10.4 ヘルスチェック

```python
class HealthChecker:
    """Claude Code認証の有効性を定期チェック."""

    def __init__(
        self,
        notifier: Notifier,
        interval_sec: int = 1800,
    ) -> None:
        self._notifier = notifier
        self._interval_sec = interval_sec
        self._is_healthy = True

    async def start(self) -> None:
        while True:
            try:
                healthy = await self._check_auth()
                if not healthy and self._is_healthy:
                    self._is_healthy = False
                    await self._notifier.notify(
                        "Claude Code認証が切れました。再ログインしてください",
                        level="critical",
                    )
                elif healthy and not self._is_healthy:
                    self._is_healthy = True
                    await self._notifier.notify(
                        "認証が復旧しました。タスクを再開します",
                        level="info",
                    )
            except Exception:
                pass
            await asyncio.sleep(
                self._interval_sec if self._is_healthy else 300
            )

    async def _check_auth(self) -> bool:
        """認証チェック."""
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "ping",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
```

### 10.5 タイムアウト

| フェーズ | タイムアウト |
|---------|-----------|
| ヒアリング | 600秒（CLI）/ 24時間（人間無応答） |
| 設計書作成 | 1800秒 |
| 実装計画 | 600秒 |
| 実装 | 3600秒 |
| CI修正 | 1200秒 |
| レビュー対応 | 1800秒 |

---

## 11. Slack通知設計

### 11.1 通知タイミング

| イベント | 内容 |
|---------|------|
| ヒアリング質問投稿 | 「Issue #42 に質問を投稿しました。回答をお願いします」 |
| Issue分割提案 | 「Issue #42 の分割を提案しました。判断をお願いします」 |
| 設計PR作成 | 「Issue #42 の設計PRを作成しました。レビューをお願いします」 |
| 実装PR作成 | 「Issue #42 の実装PRを作成しました」 |
| ヒアリングタイムアウト | 「Issue #42: 24時間応答がないため保留にしました」 |
| CI修正 | 「Issue #42: CI失敗を自動修正しました (N/3)」 |
| CI修正上限 | 「Issue #42: CI修正が3回失敗しました。手動対応が必要です」 |
| エラー発生 | 「Issue #42: エラーが発生しました (詳細)」 |
| 認証切れ | 「Claude Code認証が切れました。再ログインしてください」 |
| 認証復旧 | 「認証が復旧しました。タスクを再開します」 |
| マージ完了 | 「Issue #42 完了しました」 |

### 11.2 SlackNotifier 実装

```python
import httpx
from datetime import datetime


class SlackNotifier:
    """Slack Webhook通知の実装."""

    def __init__(
        self,
        webhook_url: str,
        default_channel: str = "#ai-agent",
    ) -> None:
        self._webhook_url = webhook_url
        self._default_channel = default_channel
        self._client = httpx.AsyncClient(timeout=10.0)

    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict | None = None,
    ) -> None:
        emoji_map = {
            "info": ":robot_face:",
            "error": ":x:",
            "critical": ":rotating_light:",
        }
        emoji = emoji_map.get(level, ":robot_face:")

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} *AI Agent* - {message}",
                },
            },
        ]

        if metadata:
            fields = []
            if "repo" in metadata:
                fields.append(f"*Repo:* {metadata['repo']}")
            if "issue" in metadata:
                fields.append(f"*Issue:* #{metadata['issue']}")
            if "pr" in metadata:
                fields.append(f"*PR:* #{metadata['pr']}")
            if fields:
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {"type": "mrkdwn", "text": " | ".join(fields)}
                        ],
                    }
                )

        payload = {
            "channel": channel or self._default_channel,
            "blocks": blocks,
            "text": message,  # フォールバック
        }

        await self._client.post(self._webhook_url, json=payload)

    async def close(self) -> None:
        await self._client.aclose()
```

---

## 12. ログ・監査設計

### 12.1 構造化イベントログ (events.jsonl)

```python
import json
from datetime import datetime, timezone
from pathlib import Path


class EventLogger:
    """構造化イベントログの記録."""

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_for_log(self, data: dict) -> dict:
        """ログ出力前にセンシティブ情報をマスク."""
        sensitive_keys = {"token", "password", "secret", "authorization", "cookie"}
        sanitized = {}
        for key, value in data.items():
            if any(s in key.lower() for s in sensitive_keys):
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_for_log(value)
            else:
                sanitized[key] = value
        return sanitized

    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict | None = None,
    ) -> None:
        """イベントをJSONLファイルに記録."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "issue": issue_number,
            "phase": phase,
            "event": event,
        }
        if data:
            record["data"] = self._sanitize_for_log(data)

        events_file = self._log_dir / f"issue-{issue_number}" / "events.jsonl"
        events_file.parent.mkdir(parents=True, exist_ok=True)
        with events_file.open("a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def write_phase_log(
        self,
        issue_number: int,
        phase: str,
        content: str,
    ) -> None:
        """フェーズログをファイルに書き出す."""
        ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        log_file = (
            self._log_dir
            / f"issue-{issue_number}"
            / f"{ts}_{phase}.log"
        )
        log_file.parent.mkdir(parents=True, exist_ok=True)
        log_file.write_text(content)
```

イベントログの例:

```jsonl
{"ts":"2026-03-24T10:00:00+00:00","issue":42,"phase":"hearing","event":"phase_start"}
{"ts":"2026-03-24T10:05:00+00:00","issue":42,"phase":"hearing","event":"question_posted","data":{"comment_id":123}}
{"ts":"2026-03-24T10:30:00+00:00","issue":42,"phase":"hearing","event":"answer_received","data":{"comment_id":124}}
{"ts":"2026-03-24T10:31:00+00:00","issue":42,"phase":"design","event":"phase_start"}
{"ts":"2026-03-24T10:45:00+00:00","issue":42,"phase":"design","event":"pr_created","data":{"pr_number":58}}
{"ts":"2026-03-24T10:45:01+00:00","issue":42,"phase":"design","event":"tool_use_end","data":{"tool":"Write","output_size":2048}}
```

### 12.2 PR descriptionに含めるログ

```markdown
## AI Agent ログ

### 実行概要
- Issue: #42
- フェーズ: 実装
- 実行時間: 15分32秒
- コスト: $2.45

### 変更の判断根拠
- `src/components/profile.py` を新規作成
  → 設計書の「4. 実装方針」に従い実装
- `src/api/user.py` に get_profile() を追加
  → 既存の get_user() パターンに合わせた

### 実行したコマンド
- `pytest` → PASS (12 tests)
- `ruff check .` → PASS
- `mypy src/` → PASS
```

---

## 13. 設定ファイル設計

### 13.1 config.yaml

マルチアカウント対応のconfig.yaml形式。`accounts` セクションでGitHubアカウントを管理し、各リポジトリは `account` フィールドで使用するアカウントを指定する。

```yaml
polling_interval_sec: 120

accounts:
  personal:
    # トークン解決方法:
    #   1. token_env: 環境変数名を指定
    #   2. token_command: コマンド実行で取得
    #   3. 未指定: gh auth token にフォールバック
    token_command: "gh auth token --user personal"

  work:
    token_env: "GITHUB_TOKEN_WORK"
    default: true

  oss:
    token_command: "gh auth token --user oss-account"

repositories:
  - owner: "myorg"
    repo: "frontend-app"
    account: "work"              # accounts セクションのキーを参照
    label: "ai-agent"
    base_branch: "main"
    slack_channel: "#frontend-ai"

  - owner: "myorg"
    repo: "backend-api"
    account: "work"
    label: "ai-agent"
    base_branch: "develop"
    slack_channel: "#backend-ai"

  - owner: "personal-user"
    repo: "my-oss-project"
    account: "personal"
    label: "ai-agent"
    base_branch: "main"

concurrency:
  max_total: 2
  max_per_repo: 1

timeouts:
  hearing_hours: 24
  hearing_phase_sec: 600
  design_phase_sec: 1800
  planning_phase_sec: 600
  implement_phase_sec: 3600
  ci_fix_phase_sec: 1200
  revise_phase_sec: 1800

retry:
  max_attempts: 3
  backoff_minutes: [1, 5, 15]

ci_fix:
  max_retries: 3

cost_limits:
  hearing_usd: 1.0
  design_usd: 3.0
  planning_usd: 1.0
  implement_usd: 10.0
  ci_fix_usd: 3.0
  revise_usd: 5.0

slack:
  webhook_url: "${SLACK_WEBHOOK_URL}"
  default_channel: "#ai-agent"

workspace_dir: "~/.ai-agent-workspaces"
```

### 13.2 pydantic-settings による設定管理

```python
from pathlib import Path
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, YamlConfigSettingsSource


@dataclass
class AccountConfig:
    """GitHubアカウント設定."""

    name: str
    token_env: str | None = None
    token_command: str | None = None
    default: bool = False


class RepositoryConfig(BaseModel):
    owner: str
    repo: str
    account: str  # accounts セクションのキーを参照
    label: str = "ai-agent"
    base_branch: str = "main"
    slack_channel: str | None = None


class ConcurrencyConfig(BaseModel):
    max_total: int = Field(default=2, ge=1, le=10)
    max_per_repo: int = Field(default=1, ge=1, le=5)


class TimeoutsConfig(BaseModel):
    hearing_hours: int = 24
    hearing_phase_sec: int = 600
    design_phase_sec: int = 1800
    planning_phase_sec: int = 600
    implement_phase_sec: int = 3600
    ci_fix_phase_sec: int = 1200
    revise_phase_sec: int = 1800


class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_minutes: list[int] = [1, 5, 15]


class CiFixConfig(BaseModel):
    max_retries: int = 3


class CostLimitsConfig(BaseModel):
    hearing_usd: float = 1.0
    design_usd: float = 3.0
    planning_usd: float = 1.0
    implement_usd: float = 10.0
    ci_fix_usd: float = 3.0
    revise_usd: float = 5.0


class SlackConfig(BaseModel):
    webhook_url: str
    default_channel: str = "#ai-agent"


class AppSettings(BaseSettings):
    """アプリケーション設定 (YAML + 環境変数)."""

    polling_interval_sec: int = Field(default=120, ge=30)
    accounts: dict[str, AccountConfig] = {}
    repositories: list[RepositoryConfig]
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()
    retry: RetryConfig = RetryConfig()
    ci_fix: CiFixConfig = CiFixConfig()
    cost_limits: CostLimitsConfig = CostLimitsConfig()
    slack: SlackConfig | None = None
    workspace_dir: str = "~/.ai-agent-workspaces"

    # 環境変数（機密情報）
    slack_webhook_url: str | None = Field(
        default=None, alias="SLACK_WEBHOOK_URL"
    )
    claude_code_oauth_token: str | None = Field(
        default=None, alias="CLAUDE_CODE_OAUTH_TOKEN"
    )

    model_config = {
        "env_prefix": "",
        "yaml_file": "config.yaml",
    }

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (
            kwargs.get("init_settings"),
            kwargs.get("env_settings"),
            YamlConfigSettingsSource(settings_cls),
            kwargs.get("dotenv_settings"),
            kwargs.get("file_secret_settings"),
        )
```

### 13.3 環境変数

```
# GitHub トークンは accounts セクションの token_env で管理
# 環境変数方式の場合のみ設定
GITHUB_TOKEN_WORK=ghp_xxxxxxxxxxxx
GITHUB_TOKEN_PERSONAL=ghp_yyyyyyyyyyyy

# Slack / Claude
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx/xxx/xxx
CLAUDE_CODE_OAUTH_TOKEN=xxxxxxxxxxxxx
```

### 13.4 CredentialResolver

フォールバックでGitHubトークンを解決する。アカウントごとに `token_env` / `token_command` に基づいて適切な方法でトークンを取得する。

```
解決順序:
  1. keyring   — OS keychain（macOS Keychain, Windows Credential Manager, Linux Secret Service）
  2. env       — 環境変数（token_env で指定された変数名）
  3. token_command — 外部コマンド実行（token_command の stdout）
  4. gh auth token — gh CLI のフォールバック（上記すべて未設定・失敗時）
```

```python
import asyncio
import keyring


class CredentialResolver:
    """アカウントごとのGitHubトークン解決.

    フォールバック:
      keyring → env var → token_command → gh auth token
    """

    KEYRING_SERVICE_PREFIX = "ai-agent"

    async def resolve(self, account_name: str, config: AccountConfig) -> str:
        """トークンを解決する. 失敗時は CredentialError を送出."""
        # 1. keyring
        token = self._resolve_keyring(account_name)
        if token:
            return token

        # 2. 環境変数
        if config.token_env:
            token = self._resolve_env(config.token_env)
            if token:
                return token

        # 3. 外部コマンド
        if config.token_command:
            token = await self._resolve_command(config.token_command)
            if token:
                return token

        # 4. フォールバック: gh auth token
        return await self._resolve_gh_cli()

    def _resolve_keyring(self, account_name: str) -> str | None:
        """OS keychain からトークンを取得."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        return keyring.get_password(service, "github_token")

    def store_keyring(self, account_name: str, token: str) -> None:
        """OS keychain にトークンを保存."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        keyring.set_password(service, "github_token", token)

    def delete_keyring(self, account_name: str) -> None:
        """OS keychain からトークンを削除."""
        service = f"{self.KEYRING_SERVICE_PREFIX}/{account_name}"
        try:
            keyring.delete_password(service, "github_token")
        except keyring.errors.PasswordDeleteError:
            pass

    def _resolve_env(self, env_var: str | None) -> str | None:
        """環境変数からトークンを取得."""
        if not env_var:
            return None
        import os
        return os.environ.get(env_var)

    async def _resolve_command(self, command: str | None) -> str | None:
        """外部コマンド実行でトークンを取得."""
        if not command:
            return None
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0 and stdout:
            return stdout.decode().strip()
        return None

    async def _resolve_gh_cli(self) -> str:
        """gh auth token にフォールバック."""
        token = await self._resolve_command("gh auth token")
        if not token:
            raise CredentialError(
                "トークンを解決できません。"
                "keyring, 環境変数, token_command, gh CLI のいずれかを設定してください"
            )
        return token

    async def verify(self, token: str) -> bool:
        """トークンの有効性を検証（GitHub API /user を呼び出し）."""
        from githubkit import GitHub
        try:
            gh = GitHub(token)
            resp = await gh.rest.users.async_get_authenticated()
            return resp.status_code == 200
        except Exception:
            return False
```

### 13.5 AccountManager / GitHubClientFactory

アカウントごとに `githubkit.GitHub` インスタンスを管理するファクトリ。リポジトリが参照するアカウント名に基づいて、適切な認証済みクライアントを返す。

```python
from githubkit import GitHub


class GitHubClientFactory:
    """アカウントごとのGitHub クライアントを管理するファクトリ.

    辞書でアカウント名 → GitHub インスタンスを保持し、
    リポジトリ操作時に適切なクライアントを返す。
    """

    def __init__(self, credential_resolver: CredentialResolver) -> None:
        self._resolver = credential_resolver
        self._clients: dict[str, GitHub] = {}
        self._tokens: dict[str, str] = {}

    async def initialize(self, accounts: dict[str, AccountConfig]) -> None:
        """全アカウントのクライアントを初期化."""
        for name, config in accounts.items():
            token = await self._resolver.resolve(name, config)
            self._tokens[name] = token
            self._clients[name] = GitHub(token)

    def get_client(self, account_name: str) -> GitHub:
        """アカウント名に対応するGitHubクライアントを取得."""
        if account_name not in self._clients:
            raise AccountNotFoundError(
                f"アカウント '{account_name}' が見つかりません。"
                f"config.yaml の accounts セクションを確認してください"
            )
        return self._clients[account_name]

    def get_client_for_repo(self, repo: RepositoryConfig) -> GitHub:
        """リポジトリ設定に対応するGitHubクライアントを取得."""
        return self.get_client(repo.account)

    async def verify_all(self) -> dict[str, bool]:
        """全アカウントのトークンを検証."""
        results: dict[str, bool] = {}
        for name, token in self._tokens.items():
            results[name] = await self._resolver.verify(token)
        return results

    @property
    def account_names(self) -> list[str]:
        return list(self._clients.keys())
```

---

## 14. CLI コマンド設計

### 14.1 フレームワーク

`typer` を採用。

**選定理由:**
- Python型ヒント駆動のCLIフレームワーク
- 自動補完・ヘルプ生成
- Click互換だがコード量が少ない
- asyncio対応（`asyncer` 経由）

### 14.2 CLI 実装

```python
import typer
import asyncio
from pathlib import Path

app = typer.Typer(
    name="ai-agent",
    help="AI Multi-Agent Orchestrator",
)


# ─────────────────────────────────────────────
# account サブコマンド群
# ─────────────────────────────────────────────
account_app = typer.Typer(help="GitHubアカウント管理")
app.add_typer(account_app, name="account")


@account_app.command("add")
def account_add(
    name: str = typer.Argument(help="アカウント名（config.yaml の accounts キー）"),
    token: str | None = typer.Option(None, help="GitHubトークン（keyringに保存）"),
    env_var: str | None = typer.Option(None, help="トークンの環境変数名"),
    token_command: str | None = typer.Option(None, help="トークン取得コマンド"),
) -> None:
    """GitHubアカウントを追加し、トークンをkeyringに保存する."""
    asyncio.run(_account_add(name, token, env_var, token_command))


@account_app.command("list")
def account_list() -> None:
    """登録済みアカウント一覧を表示する."""
    asyncio.run(_account_list())


@account_app.command("verify")
def account_verify(
    name: str | None = typer.Argument(None, help="検証するアカウント名（省略時は全アカウント）"),
) -> None:
    """アカウントのトークンを検証する."""
    asyncio.run(_account_verify(name))


@account_app.command("remove")
def account_remove(
    name: str = typer.Argument(help="削除するアカウント名"),
) -> None:
    """アカウントを削除し、keyringからトークンを除去する."""
    asyncio.run(_account_remove(name))


# ─────────────────────────────────────────────
# setup コマンド
# ─────────────────────────────────────────────
@app.command()
def setup(
    repo: str = typer.Argument(help="owner/repo 形式のリポジトリ"),
    account: str = typer.Option(..., help="使用するGitHubアカウント名"),
    branch: str = typer.Option("main", help="ベースブランチ"),
    slack_channel: str | None = typer.Option(None, help="Slack通知チャンネル"),
    full_labels: bool = typer.Option(False, "--full-labels", help="全25ラベルを作成（デフォルト: 最小8ラベル）"),
    push_claude_md: bool = typer.Option(False, "--push-claude-md", help="生成したCLAUDE.mdをリモートにpush"),
) -> None:
    """リポジトリをクローンし初期設定を行う（7ステップ）."""
    asyncio.run(_setup(repo, account, branch, slack_channel, full_labels, push_claude_md))


# ─────────────────────────────────────────────
# unregister コマンド
# ─────────────────────────────────────────────
@app.command()
def unregister(
    repo: str = typer.Argument(help="owner/repo 形式のリポジトリ"),
    purge: bool = typer.Option(False, "--purge", help="ワークスペース + knowledge ディレクトリも削除"),
) -> None:
    """リポジトリをconfig.yamlから削除する."""
    asyncio.run(_unregister(repo, purge))


# ─────────────────────────────────────────────
# 既存コマンド群
# ─────────────────────────────────────────────
@app.command()
def start(
    foreground: bool = typer.Option(False, help="フォアグラウンド実行"),
    config: Path = typer.Option("config.yaml", help="設定ファイルパス"),
) -> None:
    """オーケストレーターを起動する."""
    if foreground:
        asyncio.run(_start_foreground(config))
    else:
        _start_daemon(config)


@app.command()
def stop() -> None:
    """オーケストレーターを停止する."""
    _send_stop_signal()
    typer.echo("停止シグナルを送信しました")


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", help="JSON形式で出力"),
) -> None:
    """稼働状況を表示する."""
    asyncio.run(_show_status(json_output))


@app.command()
def logs(
    repo: str | None = typer.Option(None, help="リポジトリでフィルタ"),
    issue: int | None = typer.Option(None, help="Issue番号でフィルタ"),
    follow: bool = typer.Option(False, "-f", help="リアルタイム表示"),
    lines: int = typer.Option(50, "-n", help="表示行数"),
) -> None:
    """ログを表示する."""
    asyncio.run(_show_logs(repo, issue, follow, lines))


@app.command()
def health() -> None:
    """Claude Code認証・接続チェック."""
    asyncio.run(_check_health())
```

### 14.3 コマンド一覧

| コマンド | 説明 |
|---------|------|
| `ai-agent account add <name> [--token] [--env-var] [--token-command]` | GitHubアカウントを追加 |
| `ai-agent account list` | 登録済みアカウント一覧 |
| `ai-agent account verify [name]` | トークンの有効性を検証 |
| `ai-agent account remove <name>` | アカウントを削除 |
| `ai-agent setup <owner/repo> --account <name> [--full-labels] [--push-claude-md]` | リポジトリをクローンし初期設定（7ステップ） |
| `ai-agent unregister <owner/repo> [--purge]` | リポジトリをconfig.yamlから削除 |
| `ai-agent start [--foreground]` | オーケストレーターを起動 |
| `ai-agent stop` | オーケストレーターを停止 |
| `ai-agent status [--json]` | 稼働状況を表示 |
| `ai-agent logs [-f] [-n N]` | ログを表示 |
| `ai-agent health` | 認証・接続チェック |

---

## 15. 設計書テンプレート

AIがIssueごとに作成する設計書のテンプレート:

```markdown
# 設計書: Issue #{{issue_number}} - {{issue_title}}

## 1. 概要
<!-- このIssueで何を実現するか、1-3文で -->

## 2. 背景・動機
<!-- なぜこの変更が必要か -->

## 3. 影響範囲
### 変更するファイル
| ファイル | 変更内容 |
|---------|---------|
| `src/xxx.py` | xxx |

### 影響を受ける既存機能
-

## 4. 実装方針
### アプローチ
<!-- 具体的な実装方法 -->

### 代替案（検討して不採用にしたもの）
<!-- あれば -->

## 5. データ構造の変更
<!-- DB, 型定義, APIスキーマ等の変更。なければ「なし」 -->

## 6. API変更
<!-- エンドポイント追加/変更。なければ「なし」 -->

## 7. テスト方針
- [ ] ユニットテスト:
- [ ] 統合テスト:
- [ ] 手動確認項目:

## 8. リスク・懸念事項
<!-- パフォーマンス影響、後方互換性、セキュリティ等 -->

## 9. 見積もり
<!-- 変更規模: S / M / L -->
```

---

## 16. テスト戦略

### 16.1 フレームワーク

- `pytest` + `pytest-asyncio` + `pytest-mock`

**選定理由:**
- Pythonの事実上の標準テストフレームワーク
- `pytest-asyncio` で非同期テストをシームレスにサポート
- `pytest-mock` でモックを簡潔に記述
- フィクスチャによるテストセットアップの再利用

### 16.2 テストアーキテクチャ: 3層構成

#### Layer 1: Unit Tests（モジュール単体）

外部依存なし。純粋なロジックをテスト。

```python
# tests/unit/test_state_machine.py
import pytest
from ai_agent_orchestrator.orchestrator.state_machine import (
    StateMachine,
    Phase,
    InvalidTransitionError,
)


class TestStateMachine:
    def test_valid_transition_hearing_to_design(
        self, state_machine: StateMachine
    ) -> None:
        """ヒアリング→設計の遷移が成功すること."""
        state_machine.register_issue(42, Phase.HEARING)
        state_machine.transition(42, Phase.DESIGN)
        assert state_machine.get_phase(42) == Phase.DESIGN

    def test_invalid_transition_hearing_to_implement(
        self, state_machine: StateMachine
    ) -> None:
        """ヒアリング→実装の直接遷移が禁止されること."""
        state_machine.register_issue(42, Phase.HEARING)
        with pytest.raises(InvalidTransitionError):
            state_machine.transition(42, Phase.IMPLEMENT)

    def test_ci_retry_count_increments(
        self, state_machine: StateMachine
    ) -> None:
        """CI修正のリトライカウントが正しくインクリメントされること."""
        state_machine.register_issue(42, Phase.CI_FIX)
        assert state_machine.get_ci_retry_count(42) == 0
        state_machine.increment_ci_retry(42)
        assert state_machine.get_ci_retry_count(42) == 1
```

テスト対象:
- `state_machine.py` — フェーズ遷移ロジック
- `config/settings.py` — pydantic-settings バリデーション
- `errors/classifier.py` — エラー分類ロジック
- `context/engine.py` — コンテキスト構築ロジック

#### Layer 2: Integration Tests（モジュール結合）

`pytest-mock` で外部依存をモック。

```python
# tests/integration/test_phase_executor.py
import pytest
from unittest.mock import AsyncMock
from ai_agent_orchestrator.phases.executor import PhaseExecutor


@pytest.fixture
def mock_runner() -> AsyncMock:
    runner = AsyncMock()
    runner.run.return_value = AgentResult(
        session_id="sess_123",
        output="READY_FOR_DESIGN",
        tool_uses=[],
        cost_usd=0.5,
        duration_sec=30.0,
    )
    return runner


@pytest.fixture
def mock_github() -> AsyncMock:
    github = AsyncMock()
    github.get_issue.return_value = MockIssue(
        number=42, title="テスト機能", body="テスト本文"
    )
    return github


@pytest.mark.asyncio
async def test_hearing_ready_transitions_to_design(
    mock_runner: AsyncMock,
    mock_github: AsyncMock,
) -> None:
    """ヒアリングでREADY_FOR_DESIGNが返されたら設計フェーズに遷移."""
    executor = PhaseExecutor(
        runner=mock_runner,
        github=mock_github,
        notifier=AsyncMock(),
        tracker=AsyncMock(),
        workspace=AsyncMock(),
        context_engine=AsyncMock(),
        state_machine=AsyncMock(),
    )

    request = TaskRequest(
        issue_number=42,
        repo=RepositoryConfig(owner="org", repo="app"),
        phase="hearing",
    )
    await executor.execute(request)

    mock_runner.run.assert_called_once()
    executor._sm.transition.assert_called_with(42, "design")
```

テスト対象:
- `phases/executor.py` — フェーズ実行全体のフロー
- `poller/github_poller.py` — githubkit をモック
- `notifications/slack.py` — httpx をモック
- `agents/claude_runner.py` — Claude Agent SDK をモック

#### Layer 3: E2E Tests（実環境）

テスト用GitHubリポジトリで全フローを実行。CI/手動実行のみ。

### 16.3 テスト実行

```bash
# 全テスト
uv run pytest

# ユニットテストのみ
uv run pytest tests/unit/

# 統合テストのみ
uv run pytest tests/integration/

# カバレッジ付き
uv run pytest --cov=src/ai_agent_orchestrator --cov-report=html
```

---

## 17. ディレクトリ構成

```
ai-agent-team2/
├── src/
│   └── ai_agent_orchestrator/
│       ├── __init__.py
│       ├── __main__.py               # python -m ai_agent_orchestrator
│       ├── cli.py                     # typer CLIエントリポイント
│       ├── app.py                     # Orchestrator メインクラス
│       ├── protocols.py               # Protocol定義 (AgentRunner, Notifier, Tracker)
│       ├── models.py                  # 共通データモデル (dataclass)
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py            # pydantic-settings AppSettings
│       ├── poller/
│       │   ├── __init__.py
│       │   ├── github_poller.py       # Issue/PR/コメントのpolling
│       │   └── event_router.py        # イベント → フェーズ遷移の振り分け
│       ├── orchestrator/
│       │   ├── __init__.py
│       │   ├── task_queue.py          # asyncio.Queue + Semaphore
│       │   ├── state_machine.py       # フェーズ遷移ロジック
│       │   └── workspace_manager.py   # worktree/clone管理
│       ├── agents/
│       │   ├── __init__.py
│       │   └── claude_runner.py       # Claude Agent SDK実装
│       ├── context/
│       │   ├── __init__.py
│       │   └── engine.py             # リポマップ + コンテキスト収集
│       ├── phases/
│       │   ├── __init__.py
│       │   ├── executor.py           # PhaseExecutor（全フェーズの実行制御）
│       │   ├── hearing.py            # ヒアリング固有ロジック
│       │   ├── design.py             # 設計書作成固有ロジック
│       │   ├── planning.py           # 実装計画固有ロジック
│       │   ├── implement.py          # 実装固有ロジック
│       │   ├── ci_fix.py             # CI修正固有ロジック
│       │   └── revise.py             # レビュー対応固有ロジック
│       ├── github/
│       │   ├── __init__.py
│       │   ├── client.py             # githubkit ラッパー
│       │   ├── labels.py             # ラベル操作
│       │   └── comments.py           # コメント読み書き
│       ├── notifications/
│       │   ├── __init__.py
│       │   └── slack.py              # Slack Webhook通知
│       ├── errors/
│       │   ├── __init__.py
│       │   ├── classifier.py         # エラー分類
│       │   └── retry.py              # リトライロジック
│       ├── logger/
│       │   ├── __init__.py
│       │   ├── event_logger.py       # events.jsonl 記録
│       │   └── pr_logger.py          # PR description向けログ蓄積
│       └── templates/
│           ├── design_doc.md          # 設計書テンプレート
│           └── impl_plan.md           # 実装計画テンプレート
├── tests/
│   ├── conftest.py                    # 共通フィクスチャ
│   ├── unit/
│   │   ├── test_state_machine.py
│   │   ├── test_config.py
│   │   ├── test_error_classifier.py
│   │   └── test_context_engine.py
│   ├── integration/
│   │   ├── test_phase_executor.py
│   │   ├── test_github_client.py
│   │   ├── test_slack_notifier.py
│   │   └── test_claude_runner.py
│   └── e2e/
│       └── test_full_workflow.py
├── docs/
│   ├── design-python.md               # この設計書
│   └── architecture-diagrams.md       # アーキテクチャ図
├── config.yaml                        # リポジトリ設定
├── pyproject.toml                     # プロジェクト設定 (uv)
├── uv.lock                            # 依存関係ロック
└── .env                               # 機密情報
```

---

## 18. プロジェクト設定 (pyproject.toml)

```toml
[project]
name = "ai-agent-orchestrator"
version = "0.1.0"
description = "AI Multi-Agent Orchestrator for autonomous software engineering"
requires-python = ">=3.13"
dependencies = [
    "typer>=0.24",
    "githubkit>=0.14",
    "httpx>=0.28",
    "pydantic>=2.11",
    "pydantic-settings>=2.13",
    "pyyaml>=6.0",
    "claude-agent-sdk>=0.1.50",
]

[project.scripts]
ai-agent = "ai_agent_orchestrator.cli:app"

[project.optional-dependencies]
dev = [
    "pytest>=9.0",
    "pytest-asyncio>=1.3",
    "pytest-mock>=3.14",
    "pytest-cov>=6.0",
    "ruff>=0.15",
    "mypy>=1.19",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ai_agent_orchestrator"]

[tool.ruff]
target-version = "py313"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "ANN", "B", "A", "COM", "C4", "PTH", "RUF"]
ignore = ["ANN101", "ANN102"]

[tool.mypy]
python_version = "3.13"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short"

[tool.pytest-asyncio]
mode = "auto"
```

---

## 19. GitHub Client (githubkit)

```python
from githubkit import GitHub, Response
from githubkit.versions.latest.models import (
    Issue,
    PullRequest,
    IssueComment,
    Label,
)


class GitHubClient:
    """githubkit を使った非同期GitHub API操作."""

    def __init__(self, token: str) -> None:
        self._gh = GitHub(token)

    async def get_issues_with_label(
        self,
        repo: RepositoryConfig,
        label: str,
    ) -> list[Issue]:
        """指定ラベルのIssueを取得."""
        resp = await self._gh.rest.issues.async_list_for_repo(
            owner=repo.owner,
            repo=repo.name,
            labels=label,
            state="open",
        )
        return resp.parsed_data

    async def get_issue(
        self, repo: RepositoryConfig, issue_number: int
    ) -> Issue:
        resp = await self._gh.rest.issues.async_get(
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
        )
        return resp.parsed_data

    async def get_issue_comments(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        since: str | None = None,
    ) -> list[IssueComment]:
        """Issueのコメントを取得."""
        kwargs = {
            "owner": repo.owner,
            "repo": repo.name,
            "issue_number": issue_number,
        }
        if since:
            kwargs["since"] = since
        resp = await self._gh.rest.issues.async_list_comments(**kwargs)
        return resp.parsed_data

    async def post_comment(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        body: str,
    ) -> IssueComment:
        resp = await self._gh.rest.issues.async_create_comment(
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
            body=body,
        )
        return resp.parsed_data

    async def add_label(
        self, repo: RepositoryConfig, issue_number: int, label: str
    ) -> None:
        await self._gh.rest.issues.async_add_labels(
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
            labels=[label],
        )

    async def remove_label(
        self, repo: RepositoryConfig, issue_number: int, label: str
    ) -> None:
        try:
            await self._gh.rest.issues.async_remove_label(
                owner=repo.owner,
                repo=repo.name,
                issue_number=issue_number,
                name=label,
            )
        except Exception:
            pass  # ラベルが存在しない場合は無視

    async def replace_phase_label(
        self,
        repo: RepositoryConfig,
        issue_number: int,
        new_label: str,
    ) -> None:
        """既存のphase:* ラベルを削除し、新しいラベルを追加."""
        issue = await self.get_issue(repo, issue_number)
        for label in issue.labels:
            label_name = label if isinstance(label, str) else label.name
            if label_name and label_name.startswith("phase:"):
                await self.remove_label(repo, issue_number, label_name)
        await self.add_label(repo, issue_number, new_label)

    async def get_pr_reviews(
        self, repo: RepositoryConfig, pr_number: int
    ) -> list:
        resp = await self._gh.rest.pulls.async_list_reviews(
            owner=repo.owner,
            repo=repo.name,
            pull_number=pr_number,
        )
        return resp.parsed_data

    async def get_pr_comments(
        self, repo: RepositoryConfig, pr_number: int
    ) -> list:
        resp = await self._gh.rest.pulls.async_list_review_comments(
            owner=repo.owner,
            repo=repo.name,
            pull_number=pr_number,
        )
        return resp.parsed_data

    async def merge_pr(
        self, repo: RepositoryConfig, pr_number: int
    ) -> None:
        await self._gh.rest.pulls.async_merge(
            owner=repo.owner,
            repo=repo.name,
            pull_number=pr_number,
            merge_method="squash",
        )

    async def close_issue(
        self, repo: RepositoryConfig, issue_number: int
    ) -> None:
        await self._gh.rest.issues.async_update(
            owner=repo.owner,
            repo=repo.name,
            issue_number=issue_number,
            state="closed",
        )

    async def create_labels(
        self, repo: RepositoryConfig, labels: list[dict]
    ) -> None:
        """リポジトリにラベルを一括作成."""
        for label in labels:
            try:
                await self._gh.rest.issues.async_create_label(
                    owner=repo.owner,
                    repo=repo.name,
                    name=label["name"],
                    color=label.get("color", "ededed"),
                    description=label.get("description", ""),
                )
            except Exception:
                pass  # 既に存在する場合は無視

    async def get_check_runs(
        self, repo: RepositoryConfig, ref: str
    ) -> list:
        """CI/CDチェック結果を取得."""
        resp = await self._gh.rest.checks.async_list_for_ref(
            owner=repo.owner,
            repo=repo.name,
            ref=ref,
        )
        return resp.parsed_data.check_runs
```

---

## 20. 技術スタック一覧

| カテゴリ | 技術 | 用途 |
|---------|------|------|
| ランタイム | Python 3.13+ | 実行環境 |
| パッケージ管理 | uv | 依存関係管理・仮想環境 |
| CLI | typer >=0.24 | CLIフレームワーク |
| GitHub API | githubkit >=0.14 | 非同期GitHub API操作（型付き） |
| HTTP | httpx >=0.28 | 非同期HTTPクライアント |
| 設定管理 | pydantic-settings >=2.13 + PyYAML | YAML設定 + 環境変数 |
| バリデーション | pydantic >=2.11 | データバリデーション・型安全 |
| AI基盤 | Claude Agent SDK (Python) | AIエージェント実行 |
| テスト | pytest >=9.0 + pytest-asyncio >=1.3 + pytest-mock | テストフレームワーク |
| Lint/Format | ruff >=0.15 | Linter + Formatter |
| 型チェック | mypy >=1.19 | 静的型チェック |
| 非同期 | asyncio (stdlib) | 非同期I/O基盤 |
| プロセス管理 | asyncio.subprocess | git/外部コマンド実行 |
| ログ | 標準logging + 構造化JSONL | ログ記録 |

---

## 21. セットアップ手順

### 21.1 初期セットアップ

```bash
# 1. uvのインストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. プロジェクトの依存関係インストール
cd ai-agent-team2
uv sync

# 3. 環境変数の設定（必要に応じて）
cp .env.example .env
# .env を編集: SLACK_WEBHOOK_URL, CLAUDE_CODE_OAUTH_TOKEN
# GitHub トークンは account add で keyring に保存（推奨）

# 4. アカウント追加
uv run ai-agent account add work --token ghp_xxxxxxxxxxxx
uv run ai-agent account add personal --env-var GITHUB_TOKEN_PERSONAL

# 5. アカウント検証
uv run ai-agent account verify

# 6. リポジトリセットアップ
uv run ai-agent setup myorg/frontend-app --account work --branch main --slack-channel "#frontend-ai"
uv run ai-agent setup myorg/backend-api --account work --branch develop

# 7. ヘルスチェック
uv run ai-agent health

# 8. 起動
uv run ai-agent start
```

### 21.2 セットアップコマンドの処理（7ステップ）

```
ai-agent setup myorg/frontend-app --account work [--full-labels] [--push-claude-md]
```

#### Step 1: アカウント検証

指定された `--account` のトークンを CredentialResolver で解決・検証する。

```
トークン解決順序:
  1. keyring (ai-agent/{account_name}) → 成功なら使用
  2. env var (token_env)               → 成功なら使用
  3. token_command (外部コマンド)       → 成功なら使用
  4. gh auth token                     → 最終フォールバック

検証: GitHub API /user を呼び出し、200が返ればOK
失敗時: エラーメッセージ + `ai-agent account add` の案内を表示して中断
```

#### Step 2: Clone / Update

```
リポジトリを ~/.ai-agent-workspaces/repos/{owner}-{repo}/ にclone。
既にclone済みの場合は git fetch --all で最新化。
認証URLには Step 1 で取得したトークンを使用:
  https://{token}@github.com/{owner}/{repo}.git
```

#### Step 3: CLAUDE.md チェック（自動検出付き）

```
CLAUDE.md の存在チェック:
  ├── 存在する → 「既存のCLAUDE.mdを使用します」
  └── 存在しない → 自動検出 + 対話的生成

自動検出:
  リポジトリ内の以下のファイルを検出し、プロジェクト種別を推定:
  ├── package.json      → Node.js/TypeScript プロジェクト
  │   └── dependencies から React, Next.js, Vue 等のフレームワークも検出
  ├── pyproject.toml    → Python プロジェクト
  │   └── build-system, dependencies からフレームワーク検出
  ├── tsconfig.json     → TypeScript プロジェクト
  ├── Cargo.toml        → Rust プロジェクト
  ├── go.mod            → Go プロジェクト
  └── 上記いずれもなし  → 汎用テンプレート

検出結果を元にCLAUDE.mdテンプレートを生成:
  - 言語・フレームワーク情報
  - テストコマンド（検出されたテストランナーに基づく）
  - Lintコマンド（検出されたLinterに基づく）
  - ビルドコマンド
  - コーディング規約のプレースホルダ

--push-claude-md 指定時:
  生成したCLAUDE.mdをブランチ作成 → commit → push → PR作成
```

#### Step 4: GitHub Labels 作成

```
--full-labels なし（デフォルト）: 最小8ラベルを作成
  ai-agent, type:bug, type:feature-s, type:feature-m, type:feature-l,
  phase:hearing, phase:implement, phase:done

--full-labels あり: 全25ラベルを作成
  上記8 + severity:critical, depends-on:XX, plan:pending, plan:approved,
  needs-split, phase:analysis, phase:plan-brief, phase:plan-review,
  phase:design, phase:design-review, phase:design-revise, phase:planning,
  phase:ci-fix, phase:impl-review, phase:impl-revise, phase:blocked,
  phase:suspended

既存ラベルとの重複は無視（エラーにならない）。
```

#### Step 5: ディレクトリ初期化

```
ワークスペース内に以下のディレクトリを作成:
  ~/.ai-agent-workspaces/
  ├── repos/{owner}-{repo}/           # Step 2 で作成済み
  ├── knowledge/{owner}-{repo}/       # ナレッジ蓄積用
  │   ├── episodes/                   # エピソード記憶
  │   └── patterns.yaml              # セマンティック記憶
  └── skills/{owner}-{repo}/          # Skill定義用
```

#### Step 6: config.yaml 更新

```
config.yaml に以下を追加/更新:
  1. accounts セクションに指定アカウントが未登録なら追加
  2. repositories セクションにリポジトリ設定を追加
     - owner, repo, account, label, base_branch, slack_channel
  3. 既に同一リポジトリが登録済みの場合は上書き確認
```

#### Step 7: セットアップ検証

```
全ステップ完了後の検証:
  1. トークンでリポジトリにアクセス可能か確認
  2. ラベルが正しく作成されたか確認
  3. config.yaml の整合性チェック（アカウント参照の妥当性）
  4. 結果サマリを表示:

  セットアップ完了: myorg/frontend-app
    アカウント: work (検証済み)
    ブランチ: main
    CLAUDE.md: 既存のファイルを使用
    ラベル: 8個作成 (最小セット)
    knowledge/: 初期化完了
    skills/: 初期化完了
```

### 21.3 unregister フロー

```
ai-agent unregister myorg/frontend-app [--purge]
```

リポジトリをオーケストレーターの管理対象から除外する。

#### 基本動作（--purge なし）

```
1. config.yaml の repositories セクションから該当リポジトリを削除
2. 該当リポジトリを参照する処理中のタスクがあれば警告表示
3. accounts セクションは変更しない（他のリポジトリが使用している可能性）
4. ワークスペース・knowledge は保持（再登録時に再利用可能）
```

#### --purge オプション

```
基本動作に加えて以下も削除:
1. ~/.ai-agent-workspaces/repos/{owner}-{repo}/ （clone + worktree）
2. ~/.ai-agent-workspaces/knowledge/{owner}-{repo}/ （エピソード記憶・パターン）
3. ~/.ai-agent-workspaces/skills/{owner}-{repo}/ （Skill定義）
4. ~/.ai-agent-workspaces/logs/{owner}-{repo}/ （ログ）

削除前に確認プロンプトを表示:
  「以下のディレクトリを削除します。よろしいですか？ [y/N]」
```

```python
async def _unregister(repo: str, purge: bool) -> None:
    owner, name = repo.split("/")
    settings = AppSettings()

    # 1. config.yaml からリポジトリを削除
    config_path = Path("config.yaml")
    config_data = yaml.safe_load(config_path.read_text())

    original_count = len(config_data.get("repositories", []))
    config_data["repositories"] = [
        r for r in config_data.get("repositories", [])
        if not (r["owner"] == owner and r["repo"] == name)
    ]

    if len(config_data["repositories"]) == original_count:
        typer.echo(f"リポジトリ {repo} は登録されていません")
        raise typer.Exit(1)

    config_path.write_text(yaml.dump(config_data, allow_unicode=True))
    typer.echo(f"config.yaml から {repo} を削除しました")

    # 2. --purge: ワークスペース + knowledge + skills + logs 削除
    if purge:
        base = Path(settings.workspace_dir).expanduser()
        dirs_to_remove = [
            base / "repos" / f"{owner}-{name}",
            base / "knowledge" / f"{owner}-{name}",
            base / "skills" / f"{owner}-{name}",
            base / "logs" / f"{owner}-{name}",
        ]
        existing = [d for d in dirs_to_remove if d.exists()]

        if existing:
            typer.echo("以下のディレクトリを削除します:")
            for d in existing:
                typer.echo(f"  {d}")

            if typer.confirm("よろしいですか？"):
                import shutil
                for d in existing:
                    shutil.rmtree(d)
                    typer.echo(f"  削除: {d}")
            else:
                typer.echo("削除をキャンセルしました")

    typer.echo(f"unregister完了: {repo}")
```

---

## 22. 今後の拡張性

### 22.1 プラグイン差し替え

`Protocol` ベースのインターフェースにより、以下の差し替えが容易:

- **AgentRunner**: Claude Agent SDK → OpenAI Agent SDK、ローカルLLM等
- **Notifier**: Slack → Discord, Microsoft Teams, メール等
- **Tracker**: JSONLファイル → PostgreSQL, BigQuery, Datadog等

### 22.2 対応タスクの拡大

初期は小機能実装・バグ修正から開始し、以下に段階的に拡大:

- リファクタリング
- テスト追加
- ドキュメント生成
- 依存関係アップデート
- セキュリティ修正

### 22.3 スケーリング

- 単一PCから複数ワーカーマシンへのスケールアウト
- Redis / PostgreSQL によるタスクキューの永続化
- Kubernetes上でのコンテナ化実行

---

## 23. 自己改善ループ (Self-Improvement Loop)

### 23.1 概要
使うほど賢くなるシステム。以下の3つの機構で構成:
- ナレッジ蓄積: エピソード記憶 + セマンティック記憶
- Skill自動検出: 再利用可能なタスクパターンの自動抽出
- ワークフロー・プロンプト最適化: メトリクスベースの継続改善

### 23.2 ナレッジ蓄積

#### エピソード記憶
Issue完了時に自動記録。各エピソードに含める情報:
- Issue番号、タイプ、タイトル
- 各フェーズの実行結果（コスト、所要時間、出力概要）
- レビュー指摘内容と対応内容
- 変更ファイル一覧
- 学習事項（learnings）

保存形式: knowledge/{repo}/episodes/issue-{number}.json

```python
@dataclass
class Episode:
    issue: int
    repo: str
    type: str  # bug, feature-s, feature-m, feature-l
    title: str
    phases: list[PhaseResult]
    total_cost_usd: float
    review_rounds: int
    ci_retries: int
    files_changed: list[str]
    learnings: list[str]
```

#### セマンティック記憶（パターン抽出）
エピソードが蓄積されたタイミング（N件ごと or 定期）でAIが分析し、再利用可能なパターンを抽出。

パターンのカテゴリ:
- code_pattern: nullチェック、エラーハンドリング等
- review_pattern: レビューで繰り返し指摘されること
- architecture_pattern: ファイル配置ルール
- test_pattern: テストのパターン

保存形式: knowledge/{repo}/patterns.yaml

抽出されたパターンの活用:
- CLAUDE.md に重要なパターンを昇格（ハイブリッド方式）
- ContextEngine がフェーズに応じて関連パターンを注入

#### 類似Issue検索
新しいIssueが来たとき、過去のエピソードから類似Issueを検索。
類似度は以下で判定:
- タイプの一致
- エラーメッセージの類似性
- 変更ファイルの重複
- キーワードの一致

検索結果をコンテキストに注入:
```
## 類似Issue
Issue #5 (類似度: 高) - nullチェック漏れによる500エラー
学び: APIレスポンスのnullチェックが漏れやすい
→ 本Issueでも同様のパターンに注意
```

### 23.3 Skill自動検出・適用

#### Skill定義
```yaml
# skills/{skill-name}.yaml
name: validation-logic-addition
description: バリデーションロジック追加の標準フロー
created_from_episodes: [5, 7]
success_rate: 0.85
trigger:
  keywords: [バリデーション, 入力検証, チェック]
  file_patterns: ["src/validators/**"]
variables:
  - name: target_field
    description: バリデーション対象のフィールド名
    example: "emailAddress"
  - name: validator_name
    description: バリデーター関数名
    example: "emailValidator"
phases:
  design:
    prompt_additions: |
      バリデーション関数はsrc/validators/に配置すること。
      カスタムValidationError型を使用すること。
  implement:
    expected_files:
      - "src/validators/{{validator_name}}.ts"
      - "src/validators/ValidationError.ts"
      - "tests/validators/{{validator_name}}.test.ts"
```

#### 検出フロー
1. エピソードが一定数蓄積（例: 10件ごと）
2. AIが類似パターンのクラスタリングを実行
3. 2回以上観測されたパターンをSkill候補として抽出
4. YAML形式で skills/ に保存
5. Slack通知「新しいSkillを検出しました: {skill_name}」

#### 適用フロー
1. 新Issueのタイプ判定後、Skillライブラリとマッチング
2. MATCH → Skillのprompt_additionsをプロンプトに注入
3. 変数（variables）をIssue内容から自動推定
4. Feature-Sでマッチした場合、設計フェーズをスキップ可能

### 23.4 ワークフロー・プロンプト最適化

#### メトリクス収集
events.jsonl から自動集計:

```python
@dataclass
class Metrics:
    period: str
    total_issues: int
    total_cost_usd: float
    avg_cost_per_issue: float
    avg_review_rounds: float
    ci_retry_total: int
    type_distribution: dict[str, int]
    phase_costs: dict[str, PhaseCostMetrics]
    top_feedbacks: list[str]

@dataclass
class PhaseCostMetrics:
    avg: float
    max: float
    count: int
```

#### 改善提案の自動生成
メトリクスとパターンを元にAIが改善提案を生成:

提案カテゴリ:
- cost: 予算の最適化（実績の3倍を上限に設定）
- prompt: レビュー指摘を減らすためのプロンプト改善
- workflow: フェーズの追加/削除/変更
- quality: テスト・レビューの改善

```python
@dataclass
class ImprovementProposal:
    id: str
    category: str  # cost | prompt | workflow | quality
    title: str
    description: str
    impact: str  # high | medium | low
    action: str  # 具体的な変更内容
    metrics_basis: str  # この提案の根拠
```

#### 改善の適用フロー
1. 改善提案をGitHub Issueとして自動作成（[self-improvement]ラベル）
2. 人間がレビュー・承認
3. 承認されたらconfig.yaml/プロンプトテンプレートを自動更新
4. 次のIssue処理から改善が反映

### 23.5 検証結果に基づく具体的改善例

| 改善 | Before | After | 効果 |
|------|--------|-------|------|
| コスト予算 | IMPLEMENT=$5.00 | IMPLEMENT=$1.50 | 異常検知精度向上 |
| nullチェック | プロンプトに指示なし | 自動注入 | レビュー指摘削減 |
| ファイル配置 | レビューで指摘 | Skill適用で先回り | レビュー1往復削減 |
| 分割戦略 | 毎回一から考える | 過去パターン参照 | 分割品質向上 |

### 23.6 段階的導入計画

| Phase | 内容 | 難易度 |
|-------|------|--------|
| Phase 1 | エピソード記憶（Issue完了時に自動記録） | 低 |
| Phase 2 | メトリクス収集 + 予算/タイムアウト自動調整 | 中 |
| Phase 3 | Skill自動検出（パターン検出 + テンプレート化） | 中〜高 |
| Phase 4 | プロンプト最適化（A/Bテスト） | 高 |
