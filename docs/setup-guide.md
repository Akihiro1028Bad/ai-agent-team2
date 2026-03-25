# セットアップガイド

AI Multi-Agent Orchestrator のインストールから初回実行までの手順を説明する。

---

## 1. 前提条件

### 1.1 必須ソフトウェア

| ソフトウェア | バージョン | 用途 |
|------------|-----------|------|
| Python | 3.13 以上 | 実行環境 |
| uv | 最新版 | パッケージ管理・仮想環境 |
| git | 2.20 以上 | バージョン管理・worktree |
| gh (GitHub CLI) | 2.0 以上 | GitHub操作の補助 |
| Claude Code | 最新版 | AIエージェント実行基盤 |

### 1.2 必須アカウント・トークン

| 項目 | 説明 |
|-----|------|
| GitHub Personal Access Token | `repo` スコープ付きトークン (アカウントごとに必要) |
| Claude Max Plan | Claude Code の OAuth トークン取得に必要 |
| Slack Webhook URL (任意) | 通知送信用 |

### 1.3 バージョン確認コマンド

```bash
python3 --version    # Python 3.13.x 以上
uv --version         # uv がインストール済みであること
git --version        # git 2.20 以上
gh --version         # gh 2.x 以上
claude --version     # Claude Code がインストール済みであること
```

---

## 2. インストール

### 2.1 uv のインストール (未インストールの場合)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2.2 リポジトリのクローン

```bash
git clone https://github.com/your-org/ai-agent-team2.git
cd ai-agent-team2
```

### 2.3 依存関係のインストール

```bash
uv sync
```

開発用依存関係も含める場合:

```bash
uv sync --all-extras
```

### 2.4 インストール確認

```bash
uv run ai-agent --help
```

以下のようなヘルプメッセージが表示されれば成功:

```
 Usage: ai-agent [OPTIONS] COMMAND [ARGS]...

 AI Multi-Agent Orchestrator

Options:
  --help  Show this message and exit.

Commands:
  account    GitHubアカウントの管理
  setup      リポジトリをクローンし初期設定を行う
  unregister リポジトリの登録を解除する
  start      オーケストレーターを起動する
  stop       オーケストレーターを停止する
  status     稼働状況を表示する
  logs       ログを表示する
  health     Claude Code認証・接続チェック
```

---

## 3. クレデンシャルの管理

マルチアカウント運用に対応するため、GitHub トークンは以下の優先順位で解決される。

### 3.1 トークン解決の優先順位

| 優先度 | 方法 | 説明 |
|-------|------|------|
| 1 (最優先) | keyring (`ai-agent account add`) | OS のセキュアストレージに保存。推奨 |
| 2 | 環境変数 `GITHUB_TOKEN_{NAME}` | アカウント名を大文字にした環境変数 |
| 3 | `token_command` (config.yaml) | 外部コマンドでトークンを取得 |
| 4 (フォールバック) | `gh auth token` | gh CLI のログイン済みトークン |

### 3.2 GitHub Token の取得

GitHub Personal Access Token を取得する:

1. GitHub の Settings > Developer settings > Personal access tokens > Tokens (classic) にアクセス
2. "Generate new token (classic)" をクリック
3. 以下のスコープを選択:
   - `repo` (Full control of private repositories)
4. トークンを生成し、コピー

**複数アカウントを使う場合は、アカウントごとにトークンを取得する。**

### 3.3 keyring によるトークン登録 (推奨)

```bash
# アカウントを登録 (対話的にトークンを入力)
uv run ai-agent account add my-org
# Token for my-org: ghp_xxxx...  (入力は非表示)

# 複数アカウントの登録例
uv run ai-agent account add my-org
uv run ai-agent account add my-personal
uv run ai-agent account add client-a

# 登録済みアカウントの一覧
uv run ai-agent account list
```

出力例:

```
登録済みアカウント:
  my-org        (keyring)  ✓ 有効
  my-personal   (keyring)  ✓ 有効
  client-a      (keyring)  ✓ 有効
```

### 3.4 環境変数によるトークン設定 (代替)

keyring が利用できない環境 (CI/CD 等) では、環境変数を使用する。
アカウント名を大文字に変換し、ハイフンをアンダースコアに置換した名前で設定する。

```bash
# アカウント名 "my-org" → 環境変数 "GITHUB_TOKEN_MY_ORG"
export GITHUB_TOKEN_MY_ORG=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# アカウント名 "my-personal" → 環境変数 "GITHUB_TOKEN_MY_PERSONAL"
export GITHUB_TOKEN_MY_PERSONAL=ghp_yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
```

### 3.5 token_command による取得 (代替)

`config.yaml` の `accounts` セクションで `token_command` を指定すると、外部コマンドの出力をトークンとして使用する。1Password CLI や AWS Secrets Manager 等との連携に便利。

```yaml
accounts:
  my-org:
    token_command: "op read op://Private/github-my-org/token"
  client-a:
    token_command: "aws secretsmanager get-secret-value --secret-id github/client-a --query SecretString --output text"
```

### 3.6 CLAUDE_CODE_OAUTH_TOKEN の設定

Claude Code の Max Plan OAuthトークンを取得する:

**方法1: setup-token コマンド (推奨)**

```bash
claude setup-token
```

表示されたトークンを環境変数に設定:

```bash
export CLAUDE_CODE_OAUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxx
```

永続化するには `.env` に追記:

```bash
CLAUDE_CODE_OAUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxx
```

> **警告**: `.env` ファイルは必ず `.gitignore` に追加してください:
> ```bash
> echo ".env" >> .gitignore
> ```

**方法2: 手動取得**

1. `claude` コマンドでログイン済みであることを確認
2. 認証情報ファイルからトークンを取得:
   ```bash
   # macOS の場合
   cat ~/.claude/credentials.json
   ```
3. `oauth_token` フィールドの値を `.env` に設定

### 3.7 Slack Webhook URL の設定 (任意)

Slack 通知を有効にする場合:

1. Slack App を作成するか、既存の App に Incoming Webhook を追加
   - https://api.slack.com/apps にアクセス
   - "Create New App" > "From scratch"
   - "Incoming Webhooks" を有効化
   - "Add New Webhook to Workspace" でチャンネルを選択
2. Webhook URL をコピー

`.env` に設定:

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX
```

---

## 4. config.yaml の設定

プロジェクトルートに `config.yaml` を作成する。

### 4.1 最小構成

```yaml
accounts:
  my-org: {}

repositories:
  - owner: "myorg"
    repo: "my-app"
    account: "my-org"
```

### 4.2 推奨構成

```yaml
accounts:
  my-org: {}
  my-personal:
    token_command: "op read op://Private/github-personal/token"
  client-a: {}

polling_interval_sec: 120

repositories:
  - owner: "myorg"
    repo: "frontend-app"
    account: "my-org"
    label: "ai-agent"
    base_branch: "main"
    slack_channel: "#frontend-ai"

  - owner: "myorg"
    repo: "backend-api"
    account: "my-org"
    label: "ai-agent"
    base_branch: "develop"
    slack_channel: "#backend-ai"

  - owner: "personal-user"
    repo: "side-project"
    account: "my-personal"

  - owner: "client-a-org"
    repo: "client-app"
    account: "client-a"
    label: "ai-agent"
    slack_channel: "#client-a-ai"

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

### 4.3 設定項目の説明

| セクション | キー | デフォルト値 | 説明 |
|-----------|------|------------|------|
| `accounts` | `{name}` | (必須) | GitHubアカウント定義。名前をキーとする |
| `accounts.{name}` | `token_command` | `null` | トークン取得用の外部コマンド |
| (root) | `polling_interval_sec` | `120` | GitHub APIポーリング間隔 (秒) |
| `repositories[]` | `owner` | (必須) | リポジトリオーナー |
| `repositories[]` | `repo` | (必須) | リポジトリ名 |
| `repositories[]` | `account` | (必須) | 使用するアカウント名 (`accounts` のキー) |
| `repositories[]` | `label` | `ai-agent` | AIに割り当てるIssueのラベル |
| `repositories[]` | `base_branch` | `main` | ベースブランチ |
| `repositories[]` | `slack_channel` | `null` | リポジトリ固有のSlackチャンネル |
| `concurrency` | `max_total` | `2` | 全体の最大同時実行数 |
| `concurrency` | `max_per_repo` | `1` | リポジトリあたりの最大同時実行数 |
| `timeouts` | `hearing_hours` | `24` | ヒアリング人間回答待ちタイムアウト (時間) |
| `cost_limits` | `implement_usd` | `10.0` | 実装フェーズのコスト上限 (USD) |
| (root) | `workspace_dir` | `~/.ai-agent-workspaces` | ワークスペースのベースディレクトリ |

---

## 5. リポジトリの初期セットアップ

### 5.1 アカウントの登録 (初回のみ)

リポジトリをセットアップする前に、使用する GitHub アカウントを登録する。

```bash
uv run ai-agent account add my-org
# Token for my-org: (トークンを入力)
```

### 5.2 setup コマンドの実行

```bash
uv run ai-agent setup myorg/frontend-app \
  --account my-org \
  --branch main \
  --slack-channel "#frontend-ai"
```

`--account` フラグで、このリポジトリに使用する GitHub アカウントを指定する。

### 5.3 setup コマンドの処理内容

このコマンドは以下を実行する:

1. **リポジトリの clone**: `~/.ai-agent-workspaces/repos/myorg-frontend-app/` にクローン
2. **CLAUDE.md の自動検出**: 対象リポジトリの CLAUDE.md を自動検出する
   - リポジトリルートに CLAUDE.md が存在する場合 → そのまま使用
   - 存在しない場合 → テンプレートから対話的に生成するか、スキップを選択
3. **GitHub Labels の作成**: デフォルトで 9 個の基本ラベルを作成

**デフォルトラベル (9個)**:

| ラベル名 | 色 | 説明 |
|---------|-----|------|
| `ai-agent` | `0e8a16` | AIに割り当てるIssue |
| `type:bug` | `d73a4a` | バグ修正 |
| `type:feature-s` | `0075ca` | 小規模機能追加 |
| `type:feature-m` | `0075ca` | 中規模機能追加 |
| `type:feature-l` | `0075ca` | 大規模機能追加 |
| `phase:hearing` | `c5def5` | ヒアリング中 |
| `phase:implement` | `c5def5` | 実装中 |
| `phase:impl-review` | `fbca04` | 実装レビュー待ち |
| `phase:done` | `0e8a16` | 完了 |

**`--full-labels` オプションを指定すると、全 28 ラベルを作成する**:

```bash
uv run ai-agent setup myorg/frontend-app \
  --account my-org \
  --full-labels
```

追加されるラベル (デフォルト 9 個に加えて):

| ラベル名 | 色 | 説明 |
|---------|-----|------|
| `phase:type-detection` | `c5def5` | タイプ検出中 |
| `phase:analysis` | `c5def5` | 分析中 |
| `phase:plan-brief` | `c5def5` | 計画概要作成中 |
| `phase:plan-review` | `fbca04` | 計画レビュー待ち |
| `phase:design` | `c5def5` | 設計書作成中 |
| `phase:design-review` | `fbca04` | 設計レビュー待ち |
| `phase:design-revise` | `c5def5` | 設計修正中 |
| `phase:planning` | `c5def5` | 実装計画作成中 |
| `phase:split-proposal` | `c5def5` | Issue分割提案中 |
| `phase:split-execute` | `c5def5` | Issue分割実行中 |
| `phase:fix` | `c5def5` | 修正中 |
| `phase:ci-fix` | `c5def5` | CI修正中 |
| `phase:impl-revise` | `c5def5` | 実装修正中 |
| `phase:suspended` | `e4e669` | エラー等で保留中 |
| `phase:blocked` | `e4e669` | ブロック中 |
| `plan:pending` | `fbca04` | 計画承認待ち |
| `plan:approved` | `0e8a16` | 計画承認済み |
| `needs-split` | `d93f0b` | Issue分割の判断待ち |
| `severity:critical` | `b60205` | 重大度: クリティカル |
| `self-improvement` | `5319e7` | 自己改善 |

4. **config.yaml の更新**: リポジトリ設定を `config.yaml` に自動追加

### 5.4 セットアップの確認

```bash
uv run ai-agent setup myorg/frontend-app --account my-org
```

出力例:

```
リポジトリ myorg/frontend-app をセットアップ中...
  アカウント: my-org (トークン: keyring)
  clone完了: ~/.ai-agent-workspaces/repos/myorg-frontend-app/
  CLAUDE.md: 検出済み (リポジトリルート)
  GitHub Labels: 9個作成完了
  config.yaml: 更新完了

セットアップ完了: myorg/frontend-app
  オーナー:    myorg
  リポジトリ:  frontend-app
  アカウント:  my-org
  ブランチ:    main
  ラベル数:    9 (--full-labels で28個に拡張可能)
```

---

## 6. リポジトリの登録解除

不要になったリポジトリの登録を解除する場合は `unregister` コマンドを使用する。

### 6.1 基本的な登録解除

```bash
uv run ai-agent unregister myorg/frontend-app
```

このコマンドは以下を実行する:

1. `config.yaml` からリポジトリ設定を削除
2. ローカルのクローンディレクトリを削除 (確認プロンプトあり)

### 6.2 オプション

```bash
# ワークスペース + ナレッジ + スキル + ログも削除
uv run ai-agent unregister myorg/frontend-app --purge
```

| オプション | 説明 |
|-----------|------|
| `--purge` | ワークスペース + ナレッジ + スキル + ログも削除 |

オプションなしの場合は `config.yaml` からの設定削除のみ行う。

### 6.3 出力例

```
リポジトリ myorg/frontend-app の登録を解除します。
  config.yaml から削除: 完了

登録解除完了: myorg/frontend-app
```

`--purge` を指定した場合:

```
リポジトリ myorg/frontend-app の登録を解除します。
  config.yaml から削除: 完了
  ワークスペース削除: ~/.ai-agent-workspaces/repos/myorg-frontend-app/ (削除済み)
  ナレッジ削除: 完了
  スキル削除: 完了
  ログ削除: 完了

登録解除完了: myorg/frontend-app (--purge: 全関連データ削除済み)
```

---

## 7. オーケストレーターの起動

### 7.1 ヘルスチェック

起動前に認証・接続の確認を行う:

```bash
uv run ai-agent health
```

成功時の出力:

```
Claude Code 認証: OK
GitHub API 接続:
  my-org:      OK (rate limit: 4850/5000)
  my-personal: OK (rate limit: 4990/5000)
  client-a:    OK (rate limit: 4999/5000)
Slack Webhook: OK
ワークスペース: OK (~/.ai-agent-workspaces)
```

### 7.2 フォアグラウンド起動 (推奨: 初回テスト時)

```bash
uv run ai-agent start --foreground
```

ログがターミナルに直接出力される。`Ctrl+C` で停止。

### 7.3 バックグラウンド起動 (推奨: 本番運用時)

```bash
uv run ai-agent start
```

### 7.4 稼働状況の確認

```bash
uv run ai-agent status
```

出力例:

```
AI Agent Orchestrator: 稼働中
  アクティブタスク: 1/2
  キュー待ち: 0
  監視リポジトリ: 2
    - myorg/frontend-app [my-org] (最終ポーリング: 2分前)
    - myorg/backend-api [my-org] (最終ポーリング: 2分前)
```

JSON形式で取得:

```bash
uv run ai-agent status --json
```

### 7.5 ログの確認

```bash
# 全ログ (最新50行)
uv run ai-agent logs

# 特定リポジトリのログ
uv run ai-agent logs --repo myorg/frontend-app

# 特定Issueのログ
uv run ai-agent logs --issue 42

# リアルタイム表示
uv run ai-agent logs -f

# 行数指定
uv run ai-agent logs -n 100
```

### 7.6 停止

```bash
uv run ai-agent stop
```

---

## 8. 動作確認

### 8.1 テスト用Issueの作成

対象リポジトリに以下の条件でIssueを作成する:

1. ラベル `ai-agent` を付与
2. 明確なタスク内容を本文に記載

例:

```
タイトル: ヘルスチェックエンドポイントの追加

本文:
/health エンドポイントを追加してください。
- GET /health でステータスコード 200 と {"status": "ok"} を返す
- テストも追加
```

### 8.2 フローの確認

Issue作成後、以下の順序でイベントが発生する:

1. **2分以内**: ポーリングが新規Issueを検知
2. **ラベル変更**: `phase:hearing` ラベルが付与される
3. **Issueコメント**: AIからの質問コメントが投稿される (または即座に設計フェーズへ移行)
4. **Slack通知**: 「Issue #XX に質問を投稿しました」(Slack設定済みの場合)

### 8.3 ログでの確認

```bash
uv run ai-agent logs -f --issue <issue_number>
```

`events.jsonl` でイベントの流れを確認:

```bash
cat ~/.ai-agent-workspaces/logs/myorg-frontend-app/issue-XX/events.jsonl | jq .
```

---

## 9. トラブルシューティング

### 9.1 Claude Code 認証エラー

**症状**: `health` コマンドで「Claude Code 認証: NG」

**原因と対処**:

```bash
# Claude Code に再ログイン
claude login

# OAuthトークンを再取得
claude setup-token
export CLAUDE_CODE_OAUTH_TOKEN=<新しいトークン>

# .env ファイルも更新
```

### 9.2 GitHub API レートリミット

**症状**: ログに `rate limit exceeded` エラー

**対処**:
- ポーリング間隔を広げる (`config.yaml` の `polling_interval_sec` を増やす)
- GitHub Token のレートリミット残量を確認:
  ```bash
  gh api rate_limit
  ```

### 9.3 worktree 作成エラー

**症状**: `Failed to create worktree` エラー

**対処**:

```bash
# 既存の壊れた worktree をクリーンアップ
cd ~/.ai-agent-workspaces/repos/myorg-frontend-app
git worktree prune

# 手動で worktree ディレクトリを削除
rm -rf worktrees/issue-XX
```

### 9.4 Slack 通知が届かない

**症状**: Issueの処理は進むが、Slack通知が来ない

**確認事項**:
1. `SLACK_WEBHOOK_URL` が正しく設定されているか
2. Webhook URL が有効か (curl でテスト):
   ```bash
   curl -X POST -H 'Content-Type: application/json' \
     -d '{"text":"テスト通知"}' \
     $SLACK_WEBHOOK_URL
   ```
3. `config.yaml` の `slack` セクションが設定されているか

### 9.5 Issue が処理されない

**症状**: `ai-agent` ラベルを付けたが処理が始まらない

**確認事項**:
1. オーケストレーターが稼働中か: `uv run ai-agent status`
2. `config.yaml` にリポジトリが登録されているか
3. ラベル名が一致しているか (デフォルト: `ai-agent`)
4. 同時実行数の上限に達していないか
5. Issueに既に `phase:*` ラベルが付いていないか (付いている場合は既に処理中/処理済み)

### 9.6 オーケストレーターが起動しない

**症状**: `start` コマンドがエラーで終了

**確認事項**:

```bash
# 設定ファイルの構文チェック
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"

# 環境変数の確認
echo $CLAUDE_CODE_OAUTH_TOKEN

# アカウント状態の確認
uv run ai-agent account list

# フォアグラウンドで起動してエラーを確認
uv run ai-agent start --foreground
```

### 9.7 SUSPENDED 状態の解除

Issueが `phase:suspended` になった場合:

1. Issueコメントでエラー内容を確認
2. 原因を解消 (認証復旧、コンフリクト解決等)
3. `phase:suspended` ラベルを手動で外す
4. 次回ポーリングで処理が再開される

### 9.8 誤ったアカウントがリポジトリに使用される

**症状**: リポジトリへの操作が `403 Forbidden` や `404 Not Found` で失敗する

**原因**: `config.yaml` の `repositories[].account` が誤っている

**対処**:

```bash
# 現在の設定を確認
uv run ai-agent status --json | jq '.repositories[] | {repo, account}'

# config.yaml を修正して正しいアカウントを指定
# repositories:
#   - owner: "myorg"
#     repo: "frontend-app"
#     account: "my-org"    # ← 正しいアカウント名に修正
```

### 9.9 keyring が利用できない (CI 環境)

**症状**: `ai-agent account add` で `keyring backend not available` エラー

**原因**: ヘッドレス環境 (CI/CD, Docker, SSH) では OS の keyring サービスが利用できない

**対処**: 環境変数でトークンを設定する

```bash
# CI環境では環境変数を使用
export GITHUB_TOKEN_MY_ORG=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# または config.yaml で token_command を使用
# accounts:
#   my-org:
#     token_command: "vault kv get -field=token secret/github/my-org"
```

`config.yaml` の `accounts` セクションに定義があれば、keyring になくても環境変数またはコマンドから取得を試みる。

### 9.10 特定アカウントのトークンが期限切れ

**症状**: 一部のリポジトリのみ `401 Bad credentials` エラーが発生する

**対処**:

```bash
# どのアカウントが失敗しているか確認
uv run ai-agent health

# 出力例:
# GitHub API 接続:
#   my-org:      OK (rate limit: 4850/5000)
#   my-personal: NG (401 Bad credentials)  ← このアカウント
#   client-a:    OK (rate limit: 4999/5000)

# トークンを再登録
uv run ai-agent account add my-personal
# Token for my-personal: (新しいトークンを入力)

# 再度確認
uv run ai-agent health
```

他のアカウントで管理されているリポジトリは影響を受けず、正常に動作し続ける。
