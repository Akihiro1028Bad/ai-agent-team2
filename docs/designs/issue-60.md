# 設計書: Issue #60 プッシュ時 Claude コードレビュー自動実行

## 1. 概要

プッシュ（プルリクエスト作成・更新）時に、Claude が自動でコードレビューを実施する GitHub Actions ワークフローを追加する。
レビュー観点は「バグ検出」と「シニアエンジニアレベルのコーディング規約チェック」の2本立てとし、
レビュー結果は PR コメントとして自動投稿される。

---

## 2. ゴール

| # | 目標 |
|---|------|
| 1 | PR 作成・更新時に Claude が差分コードを自動レビューする |
| 2 | バグ・ロジックエラー・エッジケースを検出して報告する |
| 3 | シニアエンジニア観点でコーディング規約・設計品質・パフォーマンス・セキュリティを指摘する |
| 4 | レビュー結果を PR コメントとして見やすい形式で投稿する |
| 5 | ANTHROPIC_API_KEY を GitHub Secrets で安全に管理する |

---

## 3. 変更ファイル

```
.github/workflows/claude-review.yml   (新規: GitHub Actions ワークフロー)
scripts/claude_review.py              (新規: Claude レビュースクリプト)
```

---

## 4. トリガー設計

### 4.1 イベントトリガー

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main]
```

**選定理由:**
- `pull_request` イベントを使用することで、差分（base branch との diff）を明確に取得できる
- `push` 単体だと差分の起点が曖昧になるため、PR ベースに統一する
- `synchronize` により、force push や追加コミット時も再レビューされる

### 4.2 対象ブランチ

- `main` へのプルリクエストのみを対象とする
- feature ブランチ同士のマージ等には不要なため限定する

---

## 5. ワークフロー設計 (`.github/workflows/claude-review.yml`)

### 5.1 ジョブ構成

```
claude-review job
  ├── actions/checkout@v4
  ├── actions/setup-python@v5 (Python 3.13)
  ├── pip install anthropic httpx
  ├── git diff 取得 (base..head)
  └── scripts/claude_review.py 実行
       ├── 差分をClaudeに送信
       └── PR コメント投稿
```

### 5.2 環境変数・シークレット

| 変数名 | 種別 | 説明 |
|--------|------|------|
| `ANTHROPIC_API_KEY` | GitHub Secret | Claude API 認証キー |
| `GITHUB_TOKEN` | 自動付与 | PR コメント投稿用 |
| `PR_NUMBER` | 実行時環境変数 | `github.event.pull_request.number` |
| `REPO` | 実行時環境変数 | `github.repository` |
| `BASE_SHA` | 実行時環境変数 | `github.event.pull_request.base.sha` |
| `HEAD_SHA` | 実行時環境変数 | `github.event.pull_request.head.sha` |

### 5.3 ワークフロー YAML 詳細設計

```yaml
name: Claude Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]
    branches: [main]

permissions:
  pull-requests: write
  contents: read

jobs:
  claude-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: pip install anthropic httpx

      - name: Run Claude Review
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          REPO: ${{ github.repository }}
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: python scripts/claude_review.py
```

**差分取得:** スクリプト内で `git diff BASE_SHA...HEAD_SHA` を実行して差分を取得する。

---

## 6. レビュースクリプト設計 (`scripts/claude_review.py`)

### 6.1 処理フロー

```
1. 環境変数読み込み (ANTHROPIC_API_KEY, GITHUB_TOKEN, PR_NUMBER, REPO, BASE_SHA, HEAD_SHA)
2. git diff BASE_SHA...HEAD_SHA を実行して差分取得
3. 差分サイズチェック (大きすぎる場合はファイル単位で分割)
4. Claude API 呼び出し (レビュープロンプト + 差分)
5. レビュー結果を整形
6. GitHub PR コメント投稿 (GitHub REST API)
```

### 6.2 差分取得ロジック

```python
import subprocess

def get_diff(base_sha: str, head_sha: str) -> str:
    """git diff でベースから HEAD の差分を取得する。"""
    result = subprocess.run(
        ["git", "diff", f"{base_sha}...{head_sha}",
         "--", "*.py", "*.yml", "*.yaml"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout
```

**対象ファイル拡張子:** `.py`, `.yml`, `.yaml`（テストコード・設定ファイルも含む）

### 6.3 差分サイズ制限

| 閾値 | 動作 |
|------|------|
| 差分 ≤ 30,000 文字 | そのまま全体を1回で送信 |
| 差分 > 30,000 文字 | 先頭 30,000 文字に切り詰め + 警告を付記 |

Claude のコンテキストウィンドウを考慮し、過大な差分によるエラーを防ぐ。

### 6.4 Claude API 呼び出し

```python
import anthropic

client = anthropic.Anthropic(api_key=api_key)

message = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=4096,
    messages=[
        {"role": "user", "content": build_review_prompt(diff)},
    ],
)
```

**モデル:** `claude-opus-4-5`（高品質レビューのため最上位モデルを使用）

### 6.5 PR コメント投稿

```python
import httpx

def post_pr_comment(token: str, repo: str, pr_number: int, body: str) -> None:
    """GitHub API で PR にコメントを投稿する。"""
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = httpx.post(url, headers=headers, json={"body": body})
    response.raise_for_status()
```

---

## 7. レビュープロンプト設計

### 7.1 プロンプト構成

```
[システムコンテキスト]
あなたはシニアエンジニアとして、以下のコード差分をレビューしてください。

[レビュー観点]
1. バグ・ロジックエラー検出
2. コーディング規約チェック
3. パフォーマンス・セキュリティ

[プロジェクト規約]
(CLAUDE.md の主要内容をインライン)

[出力フォーマット]
(マークダウンテーブル形式の指定)

[差分]
{diff}
```

### 7.2 プロンプト全文

```python
REVIEW_PROMPT_TEMPLATE = """\
あなたはシニアソフトウェアエンジニアです。
以下の Git 差分を精査し、**バグ検出**と**コードレビュー**を行ってください。

## プロジェクト規約

- 言語: Python 3.13+
- 型アノテーション: mypy strict モード準拠（全関数に型アノテーション必須）
- 非同期: `async def` + `await` 基本。ブロッキング呼び出し禁止
- インターフェース: `typing.Protocol` で定義。具象クラスは Protocol を実装
- エラー処理: 具体的な例外クラスを使用。裸の `except:` 禁止
- テスト: TDD 推奨。pytest-asyncio auto mode。モックは respx + FakeClass
- 命名: snake_case（変数・関数）、PascalCase（クラス）、UPPER_CASE（定数）
- docstring: クラスと公開メソッドに必須（Google style）
- インポート順: stdlib → 外部ライブラリ → 内部モジュール

## レビュー観点

### 🐛 バグ・ロジックエラー検出
- ヌル参照・KeyError・IndexError・AttributeError が発生しうる箇所
- 非同期処理の await 漏れ・競合状態
- 例外処理の不備（握りつぶし・reraise 忘れ）
- 境界値・エッジケースの未考慮
- 型の不一致・暗黙の型変換
- 無限ループ・再帰の深さ問題

### 📏 コーディング規約
- 型アノテーションの欠如・不正確
- 命名規約の違反
- docstring の欠如（クラス・公開メソッド）
- Protocol 定義を使わない直接依存
- 裸の `except:` の使用

### ⚡ パフォーマンス・設計品質
- N+1 クエリ相当の非効率な API 呼び出し
- 不要な同期ブロッキング（`time.sleep` 等）
- 重複コード・DRY 原則違反
- 単一責任原則（SRP）の違反
- マジックナンバー・ハードコード値

### 🔒 セキュリティ
- 機密情報のハードコード（APIキー、パスワード等）
- インジェクション脆弱性（シェルインジェクション等）
- 安全でないデシリアライズ

## 出力フォーマット

以下のマークダウン形式で出力してください：

```markdown
## 🤖 Claude Code Review

### 📊 サマリー
| 重要度 | 件数 |
|--------|------|
| 🔴 Critical（バグ・セキュリティ） | N |
| 🟡 Warning（規約違反・設計問題） | N |
| 🔵 Info（改善提案） | N |

---

### 🔴 Critical（対応必須）

#### [ファイル名:行番号] 問題タイトル
**問題:** 問題の説明
**影響:** どのような影響があるか
**修正案:**
```python
# 修正後のコード例
```

---

### 🟡 Warning（対応推奨）

（同様の形式）

---

### 🔵 Info（改善提案）

（同様の形式）

---

### ✅ 良い点
- 良かった点を箇条書きで記載

---
*Reviewed by Claude claude-opus-4-5 | {timestamp}*
```

## 差分

```diff
{diff}
```

差分がない場合や、レビュー対象のコード変更が存在しない場合は
「レビュー対象のコード変更がありません。」とのみ返答してください。
"""
```

---

## 8. エラーハンドリング

| エラーケース | 対処 |
|-------------|------|
| 差分が空（ドキュメントのみ変更等） | 「レビュー対象なし」コメントを投稿してスキップ |
| ANTHROPIC_API_KEY 未設定 | エラーメッセージを出力してワークフロー失敗 |
| Claude API タイムアウト | リトライ1回、失敗時は PR コメントにエラーを投稿 |
| GitHub コメント投稿失敗 | エラーログを出力。ワークフロー自体はエラー終了 |
| 差分取得失敗（git diff エラー） | エラーメッセージを出力してワークフロー失敗 |

---

## 9. PR コメント出力例

```markdown
## 🤖 Claude Code Review

### 📊 サマリー
| 重要度 | 件数 |
|--------|------|
| 🔴 Critical（バグ・セキュリティ） | 1 |
| 🟡 Warning（規約違反・設計問題） | 2 |
| 🔵 Info（改善提案） | 3 |

---

### 🔴 Critical（対応必須）

#### [src/ai_agent_orchestrator/phases/implement.py:142] await 漏れによる非同期バグ
**問題:** `github_client.create_pr()` が非同期メソッドであるにもかかわらず `await` なしで呼び出されています。
**影響:** コルーチンオブジェクトが返され、PR が実際には作成されません。
**修正案:**
```python
# 修正前
pr = github_client.create_pr(title, body)

# 修正後
pr = await github_client.create_pr(title, body)
```

---

### 🟡 Warning（対応推奨）

#### [src/ai_agent_orchestrator/github/client.py:85] 型アノテーションの欠如
**問題:** `fetch_issue` メソッドに戻り値の型アノテーションがありません。
**影響:** mypy strict モードでエラーとなります。
**修正案:**
```python
async def fetch_issue(self, issue_number: int) -> IssueData:
```

---

### ✅ 良い点
- Protocol ベースの設計が一貫して守られています
- エラー処理が具体的な例外クラスで適切に実装されています

---
*Reviewed by Claude claude-opus-4-5 | 2026-04-03T10:00:00Z*
```

---

## 10. セキュリティ考慮事項

### 10.1 シークレット管理

- `ANTHROPIC_API_KEY` は GitHub Secrets に保存し、ワークフローログには出力しない
- `GITHUB_TOKEN` は GitHub Actions が自動付与する最小権限トークンを使用する
- PR コメント投稿には `pull-requests: write` 権限のみ付与（最小権限原則）

### 10.2 fork PR への対応

- fork からの PR では `ANTHROPIC_API_KEY` などのシークレットが利用できない制約がある
- `pull_request_target` は使用しない（セキュリティリスクのため）
- 外部コントリビューターからの fork PR ではレビューが実行されない旨をドキュメントに記載する

---

## 11. 作業チェックリスト

- [ ] `.github/workflows/claude-review.yml` 新規作成
  - [ ] `pull_request` トリガー設定
  - [ ] `permissions: pull-requests: write` 設定
  - [ ] 環境変数の受け渡し設定
- [ ] `scripts/claude_review.py` 新規作成
  - [ ] `get_diff()` 関数実装
  - [ ] `build_review_prompt()` 関数実装
  - [ ] Claude API 呼び出し実装
  - [ ] `post_pr_comment()` 関数実装
  - [ ] エラーハンドリング実装
  - [ ] 差分サイズ制限実装
- [ ] GitHub Secrets に `ANTHROPIC_API_KEY` を追加（手動作業・ドキュメント化）

---

## 12. 前提条件・環境設定

実装後、リポジトリ設定で以下の GitHub Secret を追加する必要がある:

| Secret 名 | 取得方法 |
|-----------|---------|
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) の API Keys ページ |

設定手順:
1. GitHub リポジトリ → Settings → Secrets and variables → Actions
2. "New repository secret" をクリック
3. Name: `ANTHROPIC_API_KEY`, Secret: APIキーの値を入力

---

## 13. 参考

- 既存 CI ワークフロー: `.github/workflows/ci.yml`
- プロジェクト規約: `CLAUDE.md`
- Anthropic Python SDK: https://github.com/anthropics/anthropic-sdk-python
- GitHub Actions permissions: https://docs.github.com/en/actions/using-workflows/workflow-syntax-for-github-actions#permissions
