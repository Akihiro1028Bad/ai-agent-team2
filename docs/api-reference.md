# 内部APIリファレンス

AI Multi-Agent Orchestrator の Protocol インターフェース、データモデル、主要クラスの公開メソッドを網羅的に記載する。

---

## 1. Protocol インターフェース

### 1.1 AgentRunner Protocol

AIエージェント実行のプラグインインターフェース。Claude Agent SDK 以外の実装への差し替えを可能にする。

**モジュール**: `ai_agent_orchestrator.protocols`

```python
@runtime_checkable
class AgentRunner(Protocol):
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
```

#### メソッド

##### `run()`

AIエージェントを実行し、結果を返す。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `prompt` | `str` | (必須) | エージェントに渡すプロンプト |
| `cwd` | `str` | (必須) | 作業ディレクトリ (worktree パス) |
| `phase` | `str` | (必須) | 実行フェーズ名 (`hearing`, `design`, `implement` 等) |
| `max_budget_usd` | `float \| None` | `None` | コスト上限 (USD)。`None` の場合はフェーズ設定のデフォルト値を使用 |
| `resume_session_id` | `str \| None` | `None` | 継続するセッションID。指定時はマルチターン実行 |
| `timeout_sec` | `int` | `600` | タイムアウト (秒) |

**戻り値**: `AgentResult`

**例外**: `asyncio.TimeoutError` (タイムアウト時)

##### `interrupt()`

実行中のセッションを安全に中断する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `session_id` | `str` | 中断するセッションID |

**戻り値**: `None`

---

### 1.2 Notifier Protocol

通知送信のプラグインインターフェース。Slack 以外の通知先への差し替えを可能にする。

**モジュール**: `ai_agent_orchestrator.protocols`

```python
@runtime_checkable
class Notifier(Protocol):
    async def notify(
        self,
        message: str,
        *,
        channel: str | None = None,
        level: str = "info",
        metadata: dict | None = None,
    ) -> None: ...
```

#### メソッド

##### `notify()`

通知メッセージを送信する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `message` | `str` | (必須) | 通知メッセージ本文 |
| `channel` | `str \| None` | `None` | 送信先チャンネル。`None` の場合はデフォルトチャンネル |
| `level` | `str` | `"info"` | 通知レベル: `"info"`, `"error"`, `"critical"` |
| `metadata` | `dict \| None` | `None` | 付加情報 (`repo`, `issue`, `pr` 等のキーを含む) |

**戻り値**: `None`

---

### 1.3 Tracker Protocol

イベント追跡のプラグインインターフェース。JSONLファイル以外の記録先への差し替えを可能にする。

**モジュール**: `ai_agent_orchestrator.protocols`

```python
@runtime_checkable
class Tracker(Protocol):
    async def track(
        self,
        event: str,
        *,
        issue_number: int,
        phase: str,
        data: dict | None = None,
    ) -> None: ...
```

#### メソッド

##### `track()`

イベントを記録する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `event` | `str` | (必須) | イベント名 (`phase_start`, `phase_transition`, `tool_use_start`, `tool_use_end`, `question_posted`, `pr_created` 等) |
| `issue_number` | `int` | (必須) | 対象Issue番号 |
| `phase` | `str` | (必須) | 現在のフェーズ名 |
| `data` | `dict \| None` | `None` | イベント固有のデータ |

**戻り値**: `None`

---

## 2. データモデル

### 2.1 AgentResult

エージェント実行結果を表すイミュータブルなデータクラス。

**モジュール**: `ai_agent_orchestrator.models`

```python
@dataclass(frozen=True)
class AgentResult:
    session_id: str
    output: str
    tool_uses: list[dict]
    cost_usd: float
    duration_sec: float
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `session_id` | `str` | セッション識別子。レビュー対応時の `resume` に使用 |
| `output` | `str` | エージェントの出力テキスト |
| `tool_uses` | `list[dict]` | 使用されたツールのリスト |
| `cost_usd` | `float` | 実行コスト (USD) |
| `duration_sec` | `float` | 実行時間 (秒) |

---

### 2.2 PhaseContext

フェーズ実行に必要なコンテキストを表すイミュータブルなデータクラス。

**モジュール**: `ai_agent_orchestrator.models`

```python
@dataclass(frozen=True)
class PhaseContext:
    issue_number: int
    repo_owner: str
    repo_name: str
    phase: str
    worktree_path: str
    resume_session_id: str | None = None
    extra: dict | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `repo_owner` | `str` | (必須) | リポジトリオーナー |
| `repo_name` | `str` | (必須) | リポジトリ名 |
| `phase` | `str` | (必須) | フェーズ名 |
| `worktree_path` | `str` | (必須) | worktree のファイルシステムパス |
| `resume_session_id` | `str \| None` | `None` | 継続するセッションID |
| `extra` | `dict \| None` | `None` | フェーズ固有の追加データ |

---

### 2.3 TaskRequest

タスク実行リクエストを表すデータクラス。

**モジュール**: `ai_agent_orchestrator.models`

```python
@dataclass
class TaskRequest:
    issue_number: int
    repo: str
    phase: Phase
    priority: int = 5

    def __lt__(self, other: "TaskRequest") -> bool:
        return self.priority < other.priority
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `repo` | `str` | (必須) | `"owner/repo"` 形式のリポジトリキー |
| `phase` | `Phase` | (必須) | 実行するフェーズ |
| `priority` | `int` | `5` | 優先度。値が小さいほど優先。`asyncio.PriorityQueue` での比較に使用 |

`__lt__` メソッドにより `asyncio.PriorityQueue` での優先度比較が可能。

---

### 2.4 IssueState

Issue単位の状態を管理するデータクラス。

**モジュール**: `ai_agent_orchestrator.orchestrator.state_machine`

```python
@dataclass
class IssueState:
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
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_number` | `int` | (必須) | Issue番号 |
| `phase` | `Phase` | (必須) | 現在のフェーズ |
| `issue_type` | `str` | `""` | Issueタイプ (`bug` \| `feature-s` \| `feature-m` \| `feature-l`) |
| `repo` | `str` | `""` | `"owner/repo"` 形式のリポジトリキー |
| `session_id` | `str \| None` | `None` | 最後に実行したセッションID |
| `pr_number` | `int \| None` | `None` | 実装PR番号 |
| `design_pr_number` | `int \| None` | `None` | 設計PR番号 |
| `retry_count` | `int` | `0` | リトライ回数 |
| `created_at` | `str` | `""` | 状態作成日時 (ISO 8601) |
| `updated_at` | `str` | `""` | 最終更新日時 (ISO 8601) |

---

### 2.5 PollEvent

ポーリングで検知されたイベントを表すイミュータブルなデータクラス。

**モジュール**: `ai_agent_orchestrator.poller.event_router`

```python
@dataclass(frozen=True)
class PollEvent:
    type: str
    repo: RepositoryConfig
    issue: Issue | None = None
    comment: IssueComment | None = None
    pr: PullRequest | None = None
    error: Exception | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `type` | `str` | (必須) | イベント種別 (`new_issue`, `hearing_reply`, `hearing_timeout`, `design_pr_approved`, `design_pr_commented`, `impl_pr_approved`, `impl_pr_commented`, `ci_failed`, `ci_passed`, `error`) |
| `repo` | `RepositoryConfig` | (必須) | 対象リポジトリ設定 |
| `issue` | `Issue \| None` | `None` | 関連するIssue (githubkit型) |
| `comment` | `IssueComment \| None` | `None` | 関連するコメント (githubkit型) |
| `pr` | `PullRequest \| None` | `None` | 関連するPR (githubkit型) |
| `error` | `Exception \| None` | `None` | エラー情報 |

---

## 3. Enum

### 3.1 IssueType

Issueのタスクタイプを表す列挙型。タイプごとに異なるワークフローが適用される。

**モジュール**: `ai_agent_orchestrator.models`

```python
class IssueType(StrEnum):
    BUG = "bug"                # バグ修正: ANALYSIS → FIX → IMPL_REVIEW
    FEATURE_S = "feature-s"    # 小機能: HEARING → PLAN_BRIEF → IMPLEMENT → IMPL_REVIEW
    FEATURE_M = "feature-m"    # 中機能: HEARING → DESIGN → PLANNING → IMPLEMENT → IMPL_REVIEW
    FEATURE_L = "feature-l"    # 大機能: HEARING → SPLIT → 子Issue(Feature-M × N)
```

| 値 | GitHub Label | ワークフロー | 予想コスト |
|----|-------------|-------------|-----------|
| `BUG` | `type:bug` | ANALYSIS → 👍承認 → FIX → CI_FIX → IMPL_REVIEW → DONE | ~$0.80 |
| `FEATURE_S` | `type:feature-s` | HEARING → PLAN_BRIEF → 👍承認 → IMPLEMENT → CI_FIX → IMPL_REVIEW → DONE | ~$0.90 |
| `FEATURE_M` | `type:feature-m` | HEARING → DESIGN → DESIGN_REVIEW → PLANNING → IMPLEMENT → CI_FIX → IMPL_REVIEW → DONE | ~$1.50 |
| `FEATURE_L` | `type:feature-l` | HEARING → SPLIT_PROPOSAL → 分割判断 → 子Issue(Feature-M × N) | $2.0 + N×$1.50 |

### 3.2 Phase

Issueのフェーズを表す列挙型。タイプによって通過するフェーズが異なる。

**モジュール**: `ai_agent_orchestrator.orchestrator.state_machine`

```python
class Phase(StrEnum):
    # タイプ判定
    TYPE_DETECTION = "type-detection"
    # Bug専用
    ANALYSIS = "analysis"
    FIX = "fix"
    # Feature-S専用
    PLAN_BRIEF = "plan-brief"
    PLAN_REVIEW = "plan-review"
    # Feature-M/L共通
    HEARING = "hearing"
    DESIGN = "design"
    DESIGN_REVIEW = "design-review"
    DESIGN_REVISE = "design-revise"
    PLANNING = "planning"
    # Feature-L専用
    SPLIT_PROPOSAL = "split-proposal"
    SPLIT_EXECUTE = "split-execute"
    # 依存待ち
    BLOCKED = "blocked"
    # 共通フェーズ
    IMPLEMENT = "implement"
    CI_FIX = "ci-fix"
    IMPL_REVIEW = "impl-review"
    IMPL_REVISE = "impl-revise"
    DONE = "done"
    SUSPENDED = "suspended"
```

**タイプ別フェーズマッピング:**

| フェーズ | Bug | Feature-S | Feature-M | Feature-L |
|---------|-----|-----------|-----------|-----------|
| TYPE_DETECTION | ✅ | ✅ | ✅ | ✅ |
| ANALYSIS | ✅ | - | - | - |
| FIX | ✅ | - | - | - |
| PLAN_BRIEF | - | ✅ | - | - |
| PLAN_REVIEW | - | ✅ | - | - |
| HEARING | - | ✅ | ✅ | ✅ |
| DESIGN | - | - | ✅ | - |
| DESIGN_REVIEW | - | - | ✅ | - |
| DESIGN_REVISE | - | - | ✅ | - |
| PLANNING | - | - | ✅ | - |
| SPLIT_PROPOSAL | - | - | - | ✅ |
| SPLIT_EXECUTE | - | - | - | ✅ |
| BLOCKED | - | - | - | ✅ (子Issue) |
| IMPLEMENT | ✅ | ✅ | ✅ | - |
| CI_FIX | ✅ | ✅ | ✅ | - |
| IMPL_REVIEW | ✅ | ✅ | ✅ | - |
| IMPL_REVISE | ✅ | ✅ | ✅ | - |
| DONE | ✅ | ✅ | ✅ | ✅ |
| SUSPENDED | ✅ | ✅ | ✅ | ✅ |

### 3.3 ApprovalMethod

方針承認の方法を表す列挙型。タイプによって承認方法が異なる。

**モジュール**: `ai_agent_orchestrator.models`

```python
class ApprovalMethod(StrEnum):
    REACTION = "reaction"    # Bug/Feature-S: Issueコメントへの👍リアクション
    PR_APPROVE = "pr-approve"  # Feature-M: 設計PRのapprove
```

### 3.4 EventType

ポーリングイベントの種別を表す列挙型。

**モジュール**: `ai_agent_orchestrator.poller.event_router`

```python
class EventType(Enum):
    NEW_ISSUE = auto()
    HEARING_REPLY = auto()
    HEARING_TIMEOUT = auto()
    # Bug/Feature-S 方針承認
    PLAN_REACTION_ADDED = auto()     # 👍リアクション検知
    PLAN_COMMENT_ADDED = auto()      # 方針への指摘コメント
    # Feature-M 設計PR
    DESIGN_PR_APPROVED = auto()
    DESIGN_PR_COMMENTED = auto()
    # 共通: 実装PR
    IMPL_PR_APPROVED = auto()
    IMPL_PR_COMMENTED = auto()
    CI_FAILED = auto()
    CI_PASSED = auto()
    # Feature-L
    SPLIT_APPROVED = auto()
    SPLIT_MODIFIED = auto()
    # エラー
    ERROR = auto()
```

### 3.5 ErrorCategory

エラー分類を表す列挙型。

**モジュール**: `ai_agent_orchestrator.errors.classifier`

```python
class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    AUTH = "auth"
    GIT_CONFLICT = "git_conflict"
    OUTPUT_INVALID = "output_invalid"
    CI_FAILURE = "ci_failure"
```

---

## 4. 設定モデル (pydantic-settings)

### 4.1 AppSettings

アプリケーション全体の設定。YAML設定ファイル + 環境変数から読み込む。

**モジュール**: `ai_agent_orchestrator.config.settings`

```python
class AppSettings(BaseSettings):
    polling_interval_sec: int = Field(default=120, ge=30)
    accounts: dict[str, AccountConfig] = {}   # マルチアカウント設定
    repositories: list[RepositoryConfig]
    concurrency: ConcurrencyConfig = ConcurrencyConfig()
    timeouts: TimeoutsConfig = TimeoutsConfig()
    retry: RetryConfig = RetryConfig()
    ci_fix: CiFixConfig = CiFixConfig()
    cost_limits: CostLimitsConfig = CostLimitsConfig()
    slack: SlackConfig | None = None
    workspace_dir: str = "~/.ai-agent-workspaces"

    # 環境変数
    slack_webhook_url: str | None = Field(default=None, alias="SLACK_WEBHOOK_URL")
    claude_code_oauth_token: str | None = Field(default=None, alias="CLAUDE_CODE_OAUTH_TOKEN")
```

設定ソースの優先順位 (上が高):
1. コンストラクタ引数 (`init_settings`)
2. 環境変数 (`env_settings`)
3. YAMLファイル (`YamlConfigSettingsSource`)
4. .env ファイル (`dotenv_settings`)
5. ファイルシークレット (`file_secret_settings`)

### 4.2 RepositoryConfig

リポジトリ単位の設定。

```python
class RepositoryConfig(BaseModel):
    owner: str
    repo: str
    label: str = "ai-agent"
    base_branch: str = "main"
    slack_channel: str | None = None
    account: str | None = None          # 使用するアカウント名 (accounts のキー)
```

### 4.3 ConcurrencyConfig

並行処理の設定。

```python
class ConcurrencyConfig(BaseModel):
    max_total: int = Field(default=2, ge=1, le=10)
    max_per_repo: int = Field(default=1, ge=1, le=5)
```

### 4.4 TimeoutsConfig

タイムアウトの設定。

```python
class TimeoutsConfig(BaseModel):
    hearing_hours: int = 24
    hearing_phase_sec: int = 600
    design_phase_sec: int = 1800
    planning_phase_sec: int = 600
    implement_phase_sec: int = 3600
    ci_fix_phase_sec: int = 1200
    revise_phase_sec: int = 1800
```

### 4.5 RetryConfig

リトライの設定。

```python
class RetryConfig(BaseModel):
    max_attempts: int = 3
    backoff_minutes: list[int] = [1, 5, 15]
```

### 4.6 CiFixConfig

CI修正の設定。

```python
class CiFixConfig(BaseModel):
    max_retries: int = 3
```

### 4.7 CostLimitsConfig

フェーズごとのコスト上限の設定。

```python
class CostLimitsConfig(BaseModel):
    hearing_usd: float = 1.0
    design_usd: float = 3.0
    planning_usd: float = 1.0
    implement_usd: float = 10.0
    ci_fix_usd: float = 3.0
    revise_usd: float = 5.0
```

### 4.8 SlackConfig

Slack通知の設定。

```python
class SlackConfig(BaseModel):
    webhook_url: str
    default_channel: str = "#ai-agent"
```

### 4.9 AccountConfig

GitHubアカウント設定。マルチアカウント運用時にアカウントごとのトークン取得方法を定義する。

**モジュール**: `ai_agent_orchestrator.config.settings`

```python
@dataclass
class AccountConfig:
    """GitHubアカウント設定."""
    name: str
    token_env: str | None = None       # 環境変数名 (例: GITHUB_TOKEN_WORK)
    token_command: str | None = None    # トークン取得コマンド
    default: bool = False              # デフォルトアカウント
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `name` | `str` | (必須) | アカウント名 (設定キーと一致) |
| `token_env` | `str \| None` | `None` | トークンを格納する環境変数名 (例: `GITHUB_TOKEN_WORK`) |
| `token_command` | `str \| None` | `None` | トークン取得用の外部コマンド |
| `default` | `bool` | `False` | デフォルトアカウントとして使用するかどうか |

### 4.10 SetupResult

セットアップの実行結果を表すデータクラス。

**モジュール**: `ai_agent_orchestrator.setup.manager`

```python
@dataclass
class SetupResult:
    """セットアップの実行結果."""
    account_verified: bool
    repo_access: str  # "read" | "read+write"
    labels_created: int
    labels_total: int
    claude_md_status: str  # "existing" | "created" | "updated"
    workspace_initialized: bool
    config_updated: bool
    warnings: list[str]
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `account_verified` | `bool` | アカウント認証が成功したかどうか |
| `repo_access` | `str` | リポジトリへのアクセスレベル (`"read"` \| `"read+write"`) |
| `labels_created` | `int` | 新規作成されたラベル数 |
| `labels_total` | `int` | ラベルの合計数 |
| `claude_md_status` | `str` | CLAUDE.mdの状態 (`"existing"` \| `"created"` \| `"updated"`) |
| `workspace_initialized` | `bool` | ワークスペースが初期化されたかどうか |
| `config_updated` | `bool` | 設定ファイルが更新されたかどうか |
| `warnings` | `list[str]` | 警告メッセージリスト |

### 4.11 ProjectInfo

自動検出されたプロジェクト情報を表すデータクラス。リポジトリのファイル構成から言語・フレームワーク・コマンドを推定する。

**モジュール**: `ai_agent_orchestrator.setup.manager`

```python
@dataclass
class ProjectInfo:
    """自動検出されたプロジェクト情報."""
    language: str | None = None
    package_manager: str | None = None
    test_cmd: str | None = None
    lint_cmd: str | None = None
    build_cmd: str | None = None
    framework: str | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `language` | `str \| None` | `None` | 主要プログラミング言語 (例: `"python"`, `"typescript"`) |
| `package_manager` | `str \| None` | `None` | パッケージマネージャ (例: `"uv"`, `"npm"`, `"pnpm"`) |
| `test_cmd` | `str \| None` | `None` | テスト実行コマンド (例: `"pytest"`, `"npm test"`) |
| `lint_cmd` | `str \| None` | `None` | リント実行コマンド (例: `"ruff check"`, `"eslint"`) |
| `build_cmd` | `str \| None` | `None` | ビルドコマンド (例: `"npm run build"`) |
| `framework` | `str \| None` | `None` | 検出されたフレームワーク (例: `"fastapi"`, `"next.js"`) |

---

## 5. マルチアカウント・セットアップ管理

### 5.1 CredentialResolver

4段階フォールバックでGitHubトークンを解決するクラス。

**モジュール**: `ai_agent_orchestrator.github.credential_resolver`

```python
class CredentialResolver:
    """4段階フォールバックでGitHubトークンを解決."""

    async def resolve(self, account: AccountConfig) -> str:
        """トークンを解決. 優先順位: keyring → env → token_command → gh auth token."""
        ...

    async def store(self, account_name: str, token: str) -> None:
        """トークンをkeyringに保存."""
        ...

    async def verify(self, token: str) -> dict:
        """トークンの有効性を確認. ユーザー情報を返す."""
        ...
```

#### メソッド

##### `resolve()`

トークンを4段階のフォールバックで解決する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account` | `AccountConfig` | アカウント設定 |

**戻り値**: `str` - 解決されたトークン

**解決順序**:
1. **keyring**: OS のセキュアストレージから取得
2. **env**: `account.token_env` で指定された環境変数から取得
3. **token_command**: `account.token_command` を実行して取得
4. **gh auth token**: GitHub CLI のトークンを使用

**例外**: `AuthError` (全段階で解決できなかった場合)

##### `store()`

トークンをkeyringに保存する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account_name` | `str` | アカウント名 |
| `token` | `str` | 保存するトークン |

**戻り値**: `None`

##### `verify()`

トークンの有効性を確認し、ユーザー情報を返す。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `token` | `str` | 検証するトークン |

**戻り値**: `dict` - ユーザー情報 (`login`, `id`, `scopes` 等を含む)

**例外**: `AuthError` (トークンが無効な場合)

---

### 5.2 AccountManager

複数GitHubアカウントの管理を行うクラス。アカウントごとの `GitHubClient` のキャッシュとリポジトリからアカウントへの解決を担う。

**モジュール**: `ai_agent_orchestrator.github.account_manager`

```python
class AccountManager:
    """複数GitHubアカウントの管理."""

    def __init__(self, accounts: dict[str, AccountConfig], resolver: CredentialResolver) -> None: ...

    async def get_client(self, account_name: str) -> "GitHubClient":
        """指定アカウントのGitHubClientを取得（キャッシュ付き）."""
        ...

    async def get_client_for_repo(self, owner: str, repo: str) -> "GitHubClient":
        """リポジトリに紐づくアカウントのClientを取得."""
        ...

    def resolve_account(self, repo_config: "RepositoryConfig") -> AccountConfig:
        """リポジトリ設定からアカウントを解決.
        優先順位: repo.account指定 → default:true → 唯一のアカウント → エラー."""
        ...

    async def verify_all(self) -> dict[str, bool]:
        """全アカウントの認証を検証."""
        ...
```

#### メソッド

##### `get_client()`

指定アカウントの `GitHubClient` を取得する。同一アカウントへの2回目以降の呼び出しではキャッシュされたインスタンスを返す。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `account_name` | `str` | アカウント名 |

**戻り値**: `GitHubClient` - 認証済みのGitHubクライアント

**例外**: `KeyError` (アカウントが未定義の場合), `AuthError` (トークン解決に失敗した場合)

##### `get_client_for_repo()`

リポジトリに紐づくアカウントの `GitHubClient` を取得する。内部で `resolve_account()` を使用してアカウントを特定する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `owner` | `str` | リポジトリオーナー |
| `repo` | `str` | リポジトリ名 |

**戻り値**: `GitHubClient` - 認証済みのGitHubクライアント

##### `resolve_account()`

リポジトリ設定からアカウントを解決する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `repo_config` | `RepositoryConfig` | リポジトリ設定 |

**戻り値**: `AccountConfig` - 解決されたアカウント設定

**解決順序**:
1. `repo_config.account` が指定されている場合はそのアカウントを使用
2. `default: true` のアカウントを使用
3. アカウントが1つのみの場合はそれを使用
4. いずれにも該当しない場合は `ConfigError` を発生

##### `verify_all()`

全アカウントの認証を検証する。

**戻り値**: `dict[str, bool]` - アカウント名をキー、認証成否を値とする辞書

---

### 5.3 SetupManager

リポジトリセットアップの統括を行うクラス。アカウント検証からラベル作成、CLAUDE.md配置までの一連のセットアップを実行する。

**モジュール**: `ai_agent_orchestrator.setup.manager`

```python
class SetupManager:
    """リポジトリセットアップの統括."""

    async def setup(self, owner: str, repo: str, account: str, branch: str,
                    slack_channel: str | None, full_labels: bool, push_claude_md: bool) -> SetupResult:
        """7ステップのセットアップを実行."""
        ...

    async def unregister(self, owner: str, repo: str, purge: bool = False) -> None:
        """リポジトリの登録解除."""
        ...

    async def detect_project_info(self, repo_path: str) -> ProjectInfo:
        """リポジトリのファイルからプロジェクト情報を自動検出."""
        ...
```

#### メソッド

##### `setup()`

7ステップのリポジトリセットアップを実行する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `owner` | `str` | (必須) | リポジトリオーナー |
| `repo` | `str` | (必須) | リポジトリ名 |
| `account` | `str` | (必須) | 使用するアカウント名 |
| `branch` | `str` | (必須) | ベースブランチ名 |
| `slack_channel` | `str \| None` | (必須) | Slack通知チャンネル |
| `full_labels` | `bool` | (必須) | 全ラベルを作成するかどうか |
| `push_claude_md` | `bool` | (必須) | CLAUDE.mdをリポジトリにプッシュするかどうか |

**戻り値**: `SetupResult` - セットアップの実行結果

**セットアップ手順**:
1. アカウント認証の検証
2. リポジトリアクセス権限の確認
3. ラベルの作成
4. プロジェクト情報の自動検出
5. CLAUDE.mdの生成・配置
6. ワークスペースの初期化
7. 設定ファイルの更新

##### `unregister()`

リポジトリの登録を解除する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `owner` | `str` | (必須) | リポジトリオーナー |
| `repo` | `str` | (必須) | リポジトリ名 |
| `purge` | `bool` | `False` | `True` の場合、ワークスペースとログも削除する |

**戻り値**: `None`

##### `detect_project_info()`

リポジトリのファイル構成からプロジェクト情報を自動検出する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `repo_path` | `str` | リポジトリのファイルシステムパス |

**戻り値**: `ProjectInfo` - 検出されたプロジェクト情報

**検出対象ファイル**:
- `pyproject.toml` / `setup.py` → Python プロジェクト
- `package.json` → Node.js プロジェクト
- `go.mod` → Go プロジェクト
- `Cargo.toml` → Rust プロジェクト

---

## 6. 主要クラスの公開メソッド

### 6.1 Orchestrator

メインオーケストレーター。全コンポーネントを統合し、イベントループを管理する。

**モジュール**: `ai_agent_orchestrator.app`

#### `async run() -> None`

メインイベントループを開始する。`asyncio.TaskGroup` を使用して以下のタスクを並行実行する:
- ポーリングタスク
- イベントルーティングタスク
- ワーカータスク (max_total 個)
- ヘルスチェックタスク

このメソッドはブロッキングであり、`Ctrl+C` またはシグナルで終了する。

---

### 6.2 TaskQueue

非同期タスクキュー。`asyncio.PriorityQueue` と `asyncio.Semaphore` による同時実行制御を行う。

**モジュール**: `ai_agent_orchestrator.orchestrator.task_queue`

#### `async enqueue(request: TaskRequest) -> None`

タスクをキューに追加する。同一Issue番号のタスクが既にキューにある場合は置換する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `request` | `TaskRequest` | 実行するタスクリクエスト |

#### `async worker_loop(executor: PhaseExecutor) -> None`

ワーカーループ。キューからタスクを取り出して `PhaseExecutor.execute()` を呼び出す。全体セマフォとリポジトリ単位セマフォの両方を取得してから実行する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `executor` | `PhaseExecutor` | フェーズ実行エンジン |

#### `active_count: int` (property)

現在実行中のタスク数を返す。

#### `get_status() -> dict`

キューの状態を辞書形式で返す。

**戻り値**:
```python
{
    "active": int,      # 実行中タスク数
    "max_total": int,   # 最大同時実行数
    "queued": int,      # キュー待ちタスク数
}
```

---

### 6.3 StateMachine

フェーズ遷移を管理するステートマシン。許可された遷移のみを受け付け、GitHub Labels とイベントログを更新する。

**モジュール**: `ai_agent_orchestrator.orchestrator.state_machine`

#### `async transition(issue_number: int, new_phase: str) -> None`

フェーズ遷移を実行する。遷移が不正な場合は `InvalidTransitionError` を発生させる。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `issue_number` | `int` | Issue番号 |
| `new_phase` | `str` | 遷移先のフェーズ名 |

**例外**: `InvalidTransitionError` (不正な遷移)

**副作用**:
- GitHub の `phase:*` ラベルを更新
- `Tracker.track()` でフェーズ遷移イベントを記録

#### `async get_ci_retry_count(issue_number: int) -> int`

指定Issueの CI修正リトライ回数を返す。

#### `async increment_ci_retry(issue_number: int) -> None`

指定Issueの CI修正リトライ回数をインクリメントする。

#### 許可される遷移

| 現在のフェーズ | 遷移可能なフェーズ |
|-------------|-----------------|
| `HEARING` | `DESIGN`, `SUSPENDED` |
| `DESIGN` | `DESIGN_REVIEW`, `SUSPENDED` |
| `DESIGN_REVIEW` | `DESIGN_REVISE`, `PLANNING`, `SUSPENDED` |
| `DESIGN_REVISE` | `DESIGN_REVIEW`, `SUSPENDED` |
| `PLANNING` | `IMPLEMENT`, `SUSPENDED` |
| `IMPLEMENT` | `IMPL_REVIEW`, `CI_FIX`, `SUSPENDED` |
| `CI_FIX` | `IMPL_REVIEW`, `CI_FIX`, `SUSPENDED` |
| `IMPL_REVIEW` | `IMPL_REVISE`, `DONE`, `SUSPENDED` |
| `IMPL_REVISE` | `IMPL_REVIEW`, `SUSPENDED` |
| `SUSPENDED` | `HEARING`, `DESIGN`, `IMPLEMENT` |

---

### 6.4 StatePersistence

Issue状態のファイルベース永続化。JSON ファイルに `IssueState` を保存・復元し、プロセス再起動時の状態ロストを防止する。

**モジュール**: `ai_agent_orchestrator.orchestrator.state_persistence`

```python
class StatePersistence:
    """Issue状態のファイルベース永続化."""

    def save(self, states: dict[int, IssueState]) -> None:
        """全Issue状態をJSONファイルに保存."""
        ...

    def load(self) -> dict[int, IssueState]:
        """JSONファイルからIssue状態を復元."""
        ...
```

#### メソッド

##### `save()`

全 Issue 状態を JSON ファイルに保存する。`StateMachine` のフェーズ遷移時に自動的に呼び出される。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `states` | `dict[int, IssueState]` | Issue番号をキー、`IssueState` を値とする辞書 |

**戻り値**: `None`

##### `load()`

JSON ファイルから Issue 状態を復元する。アプリケーション起動時に呼び出され、前回の状態を復元する。

**戻り値**: `dict[int, IssueState]` - 復元された Issue 状態の辞書

---

### 6.5 WorkspaceManager

git worktree の作成・削除を管理する。各Issueの作業を物理的に分離する。

**モジュール**: `ai_agent_orchestrator.orchestrator.workspace_manager`

#### `async ensure_cloned(repo: RepositoryConfig) -> Path`

リポジトリが clone 済みであることを保証する。未 clone の場合は clone し、clone 済みの場合は `git fetch --all` を実行する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `repo` | `RepositoryConfig` | リポジトリ設定 |

**戻り値**: `Path` - リポジトリのディレクトリパス

**例外**: `WorkspaceError` (clone 失敗時)

#### `async create_worktree(repo: RepositoryConfig, issue_number: int, branch_prefix: str = "feature") -> Path`

Issue用の worktree を作成する。既に存在する場合はそのパスを返す。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `repo` | `RepositoryConfig` | (必須) | リポジトリ設定 |
| `issue_number` | `int` | (必須) | Issue番号 |
| `branch_prefix` | `str` | `"feature"` | ブランチ名のプレフィックス |

**戻り値**: `Path` - worktree のディレクトリパス (`~/.ai-agent-workspaces/repos/{owner}-{repo}/worktrees/issue-{number}`)

**ブランチ名**: `{branch_prefix}/issue-{issue_number}` (例: `feature/issue-42`)

**例外**: `WorkspaceError` (worktree 作成失敗時)

#### `async remove_worktree(repo: RepositoryConfig, issue_number: int) -> None`

Issue用の worktree を削除する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `repo` | `RepositoryConfig` | リポジトリ設定 |
| `issue_number` | `int` | Issue番号 |

#### `get_log_dir(repo: RepositoryConfig, issue_number: int) -> Path`

Issue用のログディレクトリパスを取得する。ディレクトリが存在しない場合は自動作成する。

**戻り値**: `Path` - ログディレクトリパス (`~/.ai-agent-workspaces/logs/{owner}-{repo}/issue-{number}`)

---

### 6.6 ContextEngine

リポマップ生成と自動コンテキスト収集を行い、AIに渡す効率的なプロンプトを構築する。

**モジュール**: `ai_agent_orchestrator.context.engine`

#### `async build_context(worktree_path: str, issue_body: str, phase: str) -> str`

フェーズに応じたコンテキストを構築する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `worktree_path` | `str` | worktree のファイルシステムパス |
| `issue_body` | `str` | Issue本文 (キーワード抽出に使用) |
| `phase` | `str` | 現在のフェーズ名 |

**戻り値**: `str` - コンテキスト文字列 (Markdown形式、セクション区切り `---`)

コンテキストの構成要素 (フェーズ別):

| 要素 | hearing | design | planning | implement | ci_fix |
|-----|---------|--------|----------|-----------|--------|
| リポマップ | o | o | o | o | o |
| CLAUDE.md | o | o | o | o | o |
| 関連ファイル | o | o | o | o | o |
| 設計書 | - | - | o | o | o |
| 実装計画 | - | - | - | o | o |

---

### 6.7 PhaseExecutor

各フェーズのビジネスロジックを実行する。`TaskRequest` を受け取り、対応するフェーズの処理を実行する。

**モジュール**: `ai_agent_orchestrator.phases.executor`

#### `async execute(request: TaskRequest) -> None`

タスクリクエストに応じたフェーズを実行する。内部で `match request.phase` により適切なフェーズ処理に振り分ける。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `request` | `TaskRequest` | 実行するタスクリクエスト |

**エラーハンドリング**:
- `asyncio.TimeoutError`: セッション中断 + SUSPENDED遷移 + Slack通知
- その他の例外: SUSPENDED遷移 + Issueコメント投稿 + Slack通知

#### 内部メソッド (フェーズ別)

| メソッド | 対応フェーズ | 概要 |
|---------|-----------|------|
| `_execute_hearing()` | `hearing` | Issue分析・質問投稿 |
| `_execute_hearing_continue()` | `hearing_continue` | ヒアリング回答取り込み後の続行 |
| `_execute_design()` | `design` | 設計書作成・設計PR作成 |
| `_execute_design_revise()` | `design_revise` | 設計書のレビュー指摘対応 (セッション継続) |
| `_execute_planning()` | `planning` | 実装計画作成 |
| `_execute_implement()` | `implement` | コード実装・実装PR作成 |
| `_execute_ci_fix()` | `ci_fix` | CI失敗の自動修正 |
| `_execute_impl_revise()` | `impl_revise` | 実装のレビュー指摘対応 (セッション継続) |
| `_execute_done()` | `done` | PRマージ・Issueクローズ・worktree削除 |

---

### 6.8 GitHubPoller

GitHub APIをポーリングしてイベントを検知する。

**モジュール**: `ai_agent_orchestrator.poller.github_poller`

#### `async start(event_queue: asyncio.Queue[PollEvent]) -> None`

ポーリングループを開始する。設定された間隔 (`interval_sec`) でリポジトリを巡回し、検知したイベントをキューに追加する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `event_queue` | `asyncio.Queue[PollEvent]` | イベントを追加するキュー |

このメソッドは無限ループであり、通常は `asyncio.TaskGroup` 内で実行される。

#### 検知するイベント

| イベント | 検知条件 |
|---------|---------|
| `new_issue` | `ai-agent` ラベルあり、`phase:*` ラベルなし |
| `hearing_reply` | `phase:hearing` のIssueに人間コメントが追加 |
| `hearing_timeout` | `phase:hearing` で24時間無応答 |
| `design_pr_approved` | 設計PRが approve |
| `design_pr_commented` | 設計PRにレビューコメント |
| `impl_pr_approved` | 実装PRが approve |
| `impl_pr_commented` | 実装PRにレビューコメント |
| `ci_failed` | 実装PRのCIが失敗 |
| `ci_passed` | 実装PRのCIが成功 |

---

### 6.9 EventRouter

ポーリングで検知されたイベントをフェーズ遷移アクションに変換する。

**モジュール**: `ai_agent_orchestrator.poller.event_router`

#### `async route(event: PollEvent) -> None`

イベントを処理し、ステートマシンの遷移とタスクキューへのエンキューを行う。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `event` | `PollEvent` | 処理するイベント |

イベントとアクションの対応:

| イベント | ステート遷移 | タスクキュー |
|---------|------------|------------|
| `new_issue` | `-> hearing` | `hearing` をエンキュー |
| `hearing_reply` | (なし) | `hearing_continue` をエンキュー |
| `hearing_timeout` | `-> suspended` | (なし) |
| `design_pr_approved` | `-> planning` | `planning` をエンキュー |
| `design_pr_commented` | `-> design_revise` | `design_revise` をエンキュー |
| `impl_pr_approved` | `-> done` | (なし) |
| `impl_pr_commented` | `-> impl_revise` | `impl_revise` をエンキュー |
| `ci_failed` | `-> ci_fix` (3回以内) / `-> suspended` | `ci_fix` をエンキュー |

---

## 7. 実装クラス

### 7.1 ClaudeAgentRunner

`AgentRunner` Protocol の Claude Agent SDK 実装。

**モジュール**: `ai_agent_orchestrator.agents.claude_runner`

`AgentRunner` の全メソッドを実装する。詳細は Protocol の定義を参照。

追加の内部動作:
- フェーズごとの設定 (`PHASE_CONFIG`) に基づき、`max_budget_usd`, `timeout_sec`, `permission_mode` を自動設定
- `PreToolUse` / `PostToolUse` フックでツール使用をログに記録
- 実装フェーズ (`implement`, `ci_fix`, `impl_revise`) ではサブエージェント (`code-analyzer`, `test-writer`) を使用
- `resume_session_id` 指定時は `ClaudeSDKClient` でセッションを継続

### 7.2 SlackNotifier

`Notifier` Protocol の Slack Webhook 実装。

**モジュール**: `ai_agent_orchestrator.notifications.slack`

#### `async notify(message, *, channel, level, metadata) -> None`

Slack Block Kit 形式でメッセージを送信する。

- `level` に応じた絵文字を付与 (info: `:robot_face:`, error: `:x:`, critical: `:rotating_light:`)
- `metadata` に `repo`, `issue`, `pr` が含まれる場合、コンテキストブロックに表示

#### `async close() -> None`

内部の `httpx.AsyncClient` を閉じる。

### 7.3 EventLogger

`Tracker` Protocol の JSONL ファイル実装。

**モジュール**: `ai_agent_orchestrator.logger.event_logger`

#### `async track(event, *, issue_number, phase, data) -> None`

イベントを `events.jsonl` ファイルに追記する。

レコード形式:
```json
{"ts": "2026-03-24T10:00:00+00:00", "issue": 42, "phase": "hearing", "event": "phase_start", "data": {...}}
```

#### `async write_phase_log(issue_number: int, phase: str, content: str) -> None`

フェーズログをファイルに書き出す。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `issue_number` | `int` | Issue番号 |
| `phase` | `str` | フェーズ名 |
| `content` | `str` | ログ内容 |

ファイル名形式: `{timestamp}_{phase}.log` (例: `2026-03-24T10:00:00_hearing.log`)

#### `_sanitize_for_log(data: dict) -> dict`

ログ出力前にデータをサニタイズし、トークン等の機密情報の漏洩を防止する内部メソッド。

`track()` および `write_phase_log()` の内部で自動的に呼び出される。

**サニタイズ対象**:
- `token`, `secret`, `password`, `credential` を含むキーの値を `"***"` にマスク
- 環境変数 `GITHUB_TOKEN*` の値パターンに一致する文字列をマスク
- URL 中のトークンパラメータをマスク

### 7.4 GitHubClient

`githubkit` を使った非同期 GitHub API 操作のラッパー。

**モジュール**: `ai_agent_orchestrator.github.client`

#### 公開メソッド一覧

| メソッド | 戻り値 | 説明 |
|---------|--------|------|
| `get_issues_with_label(repo, label)` | `list[Issue]` | 指定ラベルのIssueを取得 |
| `get_issue(repo, issue_number)` | `Issue` | 特定のIssueを取得 |
| `get_issue_comments(repo, issue_number, since?)` | `list[IssueComment]` | Issueのコメントを取得 |
| `post_comment(repo, issue_number, body)` | `IssueComment` | Issueにコメントを投稿 |
| `add_label(repo, issue_number, label)` | `None` | ラベルを追加 |
| `remove_label(repo, issue_number, label)` | `None` | ラベルを削除 |
| `replace_phase_label(repo, issue_number, new_label)` | `None` | 既存の `phase:*` ラベルを置換 |
| `get_pr_reviews(repo, pr_number)` | `list` | PRのレビューを取得 |
| `get_pr_comments(repo, pr_number)` | `list` | PRのレビューコメントを取得 |
| `merge_pr(repo, pr_number)` | `None` | PRを squash マージ |
| `close_issue(repo, issue_number)` | `None` | Issueをクローズ |
| `create_labels(repo, labels)` | `None` | ラベルを一括作成 |
| `get_check_runs(repo, ref)` | `list` | CI/CDチェック結果を取得 |

### 7.5 HealthChecker

Claude Code 認証の有効性を定期的にチェックする。

**モジュール**: `ai_agent_orchestrator.app` (内部クラス)

#### `async start() -> None`

ヘルスチェックループを開始する。

- 正常時: 30分間隔でチェック
- 異常時: 5分間隔でチェック
- 認証切れ検知時: `Notifier` で critical レベル通知
- 認証復旧時: `Notifier` で info レベル通知

---

## 8. エラー型

### 8.1 InvalidTransitionError

不正なフェーズ遷移が試みられた場合に発生する例外。

**モジュール**: `ai_agent_orchestrator.orchestrator.state_machine`

### 8.2 WorkspaceError

worktree の作成・削除に失敗した場合に発生する例外。

**モジュール**: `ai_agent_orchestrator.orchestrator.workspace_manager`

---

## 9. ユーティリティ関数

### 9.1 classify_error()

例外をエラーカテゴリに分類する。

**モジュール**: `ai_agent_orchestrator.errors.classifier`

```python
def classify_error(error: Exception) -> ErrorCategory
```

分類ルール:
- `rate limit`, `timeout` を含む -> `TRANSIENT`
- `auth`, `token`, `401` を含む -> `AUTH`
- `conflict`, `merge` を含む -> `GIT_CONFLICT`
- その他 -> `TRANSIENT`

### 9.2 with_retry()

リトライ付きデコレータ。一時的エラーのみリトライし、認証エラー・コンフリクト等は即座に再送出する。

**モジュール**: `ai_agent_orchestrator.errors.retry`

```python
def with_retry(
    max_attempts: int = 3,
    backoff_minutes: list[int] | None = None,
) -> Callable
```

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `max_attempts` | `int` | `3` | 最大試行回数 |
| `backoff_minutes` | `list[int] \| None` | `[1, 5, 15]` | リトライ間隔 (分) |

---

## 10. 自己改善ループ関連

### 10.1 データクラス

#### Episode

Issue完了時のエピソード記録。

**モジュール**: `ai_agent_orchestrator.knowledge.models`

```python
@dataclass
class Episode:
    """Issue完了時のエピソード記録."""
    issue: int
    repo: str
    type: str  # bug | feature-s | feature-m | feature-l
    title: str
    phases: list[PhaseResult]
    total_cost_usd: float
    review_rounds: int
    ci_retries: int
    files_changed: list[str]
    learnings: list[str]
    created_at: str  # ISO 8601
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `issue` | `int` | Issue番号 |
| `repo` | `str` | `"owner/repo"` 形式のリポジトリキー |
| `type` | `str` | Issueタイプ (`bug`, `feature-s`, `feature-m`, `feature-l`) |
| `title` | `str` | Issueタイトル |
| `phases` | `list[PhaseResult]` | 各フェーズの実行結果リスト |
| `total_cost_usd` | `float` | 合計コスト (USD) |
| `review_rounds` | `int` | レビューラウンド数 |
| `ci_retries` | `int` | CIリトライ回数 |
| `files_changed` | `list[str]` | 変更ファイル一覧 |
| `learnings` | `list[str]` | 学習事項リスト |
| `created_at` | `str` | 作成日時 (ISO 8601) |

#### PhaseResult

各フェーズの実行結果。

```python
@dataclass
class PhaseResult:
    """各フェーズの実行結果."""
    phase: str
    cost_usd: float
    duration_sec: int
    output_summary: str
    review_comments: int = 0
    feedback: str | None = None
    resolution: str | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `phase` | `str` | (必須) | フェーズ名 |
| `cost_usd` | `float` | (必須) | フェーズのコスト (USD) |
| `duration_sec` | `int` | (必須) | 実行時間 (秒) |
| `output_summary` | `str` | (必須) | 出力の要約 |
| `review_comments` | `int` | `0` | レビューコメント数 |
| `feedback` | `str \| None` | `None` | レビューからのフィードバック |
| `resolution` | `str \| None` | `None` | フィードバックへの対応内容 |

#### SemanticPattern

セマンティック記憶のパターン。エピソード群から抽出された再利用可能な知見。

```python
@dataclass
class SemanticPattern:
    """セマンティック記憶のパターン."""
    id: str  # kebab-case
    description: str
    frequency: int
    source_episodes: list[int]
    category: str  # code_pattern | review_pattern | architecture_pattern | test_pattern
    action: str  # プロンプトに追加すべき指示
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `id` | `str` | パターンID (kebab-case) |
| `description` | `str` | パターンの説明 |
| `frequency` | `int` | 出現頻度 |
| `source_episodes` | `list[int]` | 抽出元エピソードのIssue番号リスト |
| `category` | `str` | カテゴリ (`code_pattern`, `review_pattern`, `architecture_pattern`, `test_pattern`) |
| `action` | `str` | プロンプトに追加すべき指示 |

#### Skill

再利用可能なタスクパターン。過去のエピソードから検出される。

```python
@dataclass
class Skill:
    """再利用可能なタスクパターン."""
    name: str  # kebab-case
    description: str
    created_from_episodes: list[int]
    success_rate: float
    trigger: SkillTrigger
    variables: list[SkillVariable]
    phases: dict[str, SkillPhaseConfig]
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `name` | `str` | Skill名 (kebab-case) |
| `description` | `str` | Skillの説明 |
| `created_from_episodes` | `list[int]` | 作成元エピソードのIssue番号リスト |
| `success_rate` | `float` | 成功率 (0.0〜1.0) |
| `trigger` | `SkillTrigger` | マッチング条件 |
| `variables` | `list[SkillVariable]` | 変数定義リスト |
| `phases` | `dict[str, SkillPhaseConfig]` | フェーズ別設定 |

#### SkillTrigger

Skillのマッチング条件。

```python
@dataclass
class SkillTrigger:
    """Skillのマッチング条件."""
    keywords: list[str]
    file_patterns: list[str]
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `keywords` | `list[str]` | マッチングキーワードリスト |
| `file_patterns` | `list[str]` | マッチングファイルパターンリスト (glob形式) |

#### SkillVariable

Skillの変数定義。

```python
@dataclass
class SkillVariable:
    """Skillの変数定義."""
    name: str
    description: str
    example: str
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `name` | `str` | 変数名 |
| `description` | `str` | 変数の説明 |
| `example` | `str` | 値の例 |

#### SkillPhaseConfig

Skill適用時のフェーズ設定。

```python
@dataclass
class SkillPhaseConfig:
    """Skill適用時のフェーズ設定."""
    prompt_additions: str
    expected_files: list[str] | None = None
```

| フィールド | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `prompt_additions` | `str` | (必須) | プロンプトに追加する指示 |
| `expected_files` | `list[str] \| None` | `None` | 期待される生成ファイルパターン |

#### Metrics

メトリクス集計結果。

```python
@dataclass
class Metrics:
    """メトリクス集計結果."""
    period: str
    total_issues: int
    total_cost_usd: float
    avg_cost_per_issue: float
    avg_review_rounds: float
    ci_retry_total: int
    type_distribution: dict[str, int]
    phase_costs: dict[str, PhaseCostMetrics]
    top_feedbacks: list[str]
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `period` | `str` | 集計期間 |
| `total_issues` | `int` | 合計Issue数 |
| `total_cost_usd` | `float` | 合計コスト (USD) |
| `avg_cost_per_issue` | `float` | Issue あたり平均コスト (USD) |
| `avg_review_rounds` | `float` | 平均レビューラウンド数 |
| `ci_retry_total` | `int` | CIリトライ合計回数 |
| `type_distribution` | `dict[str, int]` | タイプ別Issue数 |
| `phase_costs` | `dict[str, PhaseCostMetrics]` | フェーズ別コストメトリクス |
| `top_feedbacks` | `list[str]` | 頻出フィードバックリスト |

#### PhaseCostMetrics

フェーズ別コストメトリクス。

```python
@dataclass
class PhaseCostMetrics:
    """フェーズ別コストメトリクス."""
    avg: float
    max: float
    count: int
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `avg` | `float` | 平均コスト (USD) |
| `max` | `float` | 最大コスト (USD) |
| `count` | `int` | 実行回数 |

#### ImprovementProposal

改善提案。メトリクスとパターン分析に基づいて生成される。

```python
@dataclass
class ImprovementProposal:
    """改善提案."""
    id: str
    category: str  # cost | prompt | workflow | quality
    title: str
    description: str
    impact: str  # high | medium | low
    action: str
    metrics_basis: str
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| `id` | `str` | 提案ID |
| `category` | `str` | カテゴリ (`cost`, `prompt`, `workflow`, `quality`) |
| `title` | `str` | 提案タイトル |
| `description` | `str` | 提案の詳細説明 |
| `impact` | `str` | 影響度 (`high`, `medium`, `low`) |
| `action` | `str` | 具体的なアクション |
| `metrics_basis` | `str` | 提案の根拠となるメトリクス |

---

### 10.2 Protocol インターフェース

#### KnowledgeStore Protocol

ナレッジ蓄積のインターフェース。エピソードの保存・検索・パターン抽出を担う。

```python
class KnowledgeStore(Protocol):
    """ナレッジ蓄積のインターフェース."""

    async def save_episode(self, episode: Episode) -> None:
        """エピソードを保存."""
        ...

    async def search_similar(self, issue_title: str, issue_body: str, limit: int = 3) -> list[Episode]:
        """類似Issueを検索."""
        ...

    async def extract_patterns(self) -> list[SemanticPattern]:
        """エピソード群からパターンを抽出."""
        ...

    async def get_patterns(self) -> list[SemanticPattern]:
        """既存パターンを取得."""
        ...
```

##### `save_episode()`

エピソードを保存する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `episode` | `Episode` | 保存するエピソード |

**戻り値**: `None`

##### `search_similar()`

類似Issueを検索する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `issue_title` | `str` | (必須) | 検索対象のIssueタイトル |
| `issue_body` | `str` | (必須) | 検索対象のIssue本文 |
| `limit` | `int` | `3` | 返却する最大件数 |

**戻り値**: `list[Episode]` - 類似度の高い順にソートされたエピソードリスト

##### `extract_patterns()`

蓄積されたエピソード群からセマンティックパターンを抽出する。

**戻り値**: `list[SemanticPattern]` - 抽出されたパターンリスト

##### `get_patterns()`

既存のパターンを取得する。

**戻り値**: `list[SemanticPattern]` - 保存済みパターンリスト

#### SkillManager Protocol

Skill管理のインターフェース。Skillの検出・マッチング・成功率管理を担う。

```python
class SkillManager(Protocol):
    """Skill管理のインターフェース."""

    async def detect_skills(self, episodes: list[Episode]) -> list[Skill]:
        """エピソード群からSkillを検出."""
        ...

    async def match_skill(self, issue_title: str, issue_body: str) -> Skill | None:
        """Issueに適用可能なSkillを検索."""
        ...

    async def update_success_rate(self, skill_name: str, success: bool) -> None:
        """Skillの成功率を更新."""
        ...
```

##### `detect_skills()`

エピソード群から再利用可能なSkillを検出する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `episodes` | `list[Episode]` | 分析対象のエピソードリスト |

**戻り値**: `list[Skill]` - 検出されたSkillリスト

##### `match_skill()`

Issueに適用可能なSkillを検索する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `issue_title` | `str` | IssueタイトルI |
| `issue_body` | `str` | Issue本文 |

**戻り値**: `Skill | None` - マッチしたSkill。マッチなしの場合は `None`

##### `update_success_rate()`

Skillの成功率を更新する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `skill_name` | `str` | Skill名 |
| `success` | `bool` | 成功したかどうか |

**戻り値**: `None`

#### MetricsCollector Protocol

メトリクス収集のインターフェース。イベントログからの集計と改善提案生成を担う。

```python
class MetricsCollector(Protocol):
    """メトリクス収集のインターフェース."""

    async def collect(self, events_path: str) -> Metrics:
        """events.jsonlからメトリクスを集計."""
        ...

    async def generate_proposals(self, metrics: Metrics, patterns: list[SemanticPattern]) -> list[ImprovementProposal]:
        """改善提案を生成."""
        ...
```

##### `collect()`

`events.jsonl` からメトリクスを集計する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `events_path` | `str` | `events.jsonl` のファイルパス |

**戻り値**: `Metrics` - 集計結果

##### `generate_proposals()`

メトリクスとパターンに基づいて改善提案を生成する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `metrics` | `Metrics` | 集計されたメトリクス |
| `patterns` | `list[SemanticPattern]` | 抽出済みパターンリスト |

**戻り値**: `list[ImprovementProposal]` - 改善提案リスト

---

### 10.3 主要クラス

#### KnowledgeEngine

ナレッジ蓄積・検索・パターン抽出を統括するクラス。`KnowledgeStore` の具象実装を内部に持ち、エピソード管理とフェーズ別コンテキスト生成を行う。

**モジュール**: `ai_agent_orchestrator.knowledge.engine`

##### `async save_episode(episode: Episode) -> None`

エピソードを保存し、蓄積数に応じてパターン抽出をトリガーする。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `episode` | `Episode` | 保存するエピソード |

##### `async search_similar(title: str, body: str, limit: int = 3) -> list[Episode]`

類似Issueのエピソードを検索する。

| パラメータ | 型 | デフォルト | 説明 |
|-----------|---|---------|------|
| `title` | `str` | (必須) | Issueタイトル |
| `body` | `str` | (必須) | Issue本文 |
| `limit` | `int` | `3` | 返却する最大件数 |

**戻り値**: `list[Episode]`

##### `async get_context_for_phase(phase: Phase, issue: IssueState) -> str`

フェーズに応じたナレッジコンテキストを生成する。類似エピソードの学習事項やパターンをMarkdown形式で返す。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `phase` | `Phase` | 現在のフェーズ |
| `issue` | `IssueState` | Issue状態 |

**戻り値**: `str` - ナレッジコンテキスト (Markdown形式)

##### `async sync_to_claude_md(repo_path: str) -> None`

高頻度パターンを `CLAUDE.md` に昇格する。頻度閾値を超えたパターンを自動的に `CLAUDE.md` のルールセクションに追記する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `repo_path` | `str` | リポジトリのファイルシステムパス |

#### SkillEngine

Skill検出・マッチング・管理を統括するクラス。`SkillManager` の具象実装を内部に持ち、Skillのライフサイクル全体を管理する。

**モジュール**: `ai_agent_orchestrator.knowledge.skill_engine`

##### `async detect_new_skills() -> list[Skill]`

蓄積されたエピソードから新しいSkillを検出する。

**戻り値**: `list[Skill]` - 新規検出されたSkillリスト

##### `async match(title: str, body: str) -> SkillMatchResult`

IssueにマッチするSkillを検索する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `title` | `str` | Issueタイトル |
| `body` | `str` | Issue本文 |

**戻り値**: `SkillMatchResult` - マッチ結果 (Skillと変数バインディングを含む)

##### `async apply(skill: Skill, variables: dict) -> dict[str, str]`

Skillを適用し、フェーズ別の `prompt_additions` を生成する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `skill` | `Skill` | 適用するSkill |
| `variables` | `dict` | 変数バインディング |

**戻り値**: `dict[str, str]` - フェーズ名をキー、追加プロンプトを値とする辞書

##### `async record_result(skill_name: str, success: bool) -> None`

Skill適用の結果を記録し、成功率を更新する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `skill_name` | `str` | Skill名 |
| `success` | `bool` | 成功したかどうか |

#### SelfImprovementEngine

メトリクス収集・改善提案・自動適用を統括するクラス。定期的にメトリクスを集計し、改善提案を生成・適用する。

**モジュール**: `ai_agent_orchestrator.knowledge.improvement_engine`

##### `async collect_metrics() -> Metrics`

`events.jsonl` からメトリクスを集計する。

**戻り値**: `Metrics` - 集計結果

##### `async generate_proposals() -> list[ImprovementProposal]`

メトリクスとパターンに基づいて改善提案を生成する。

**戻り値**: `list[ImprovementProposal]` - 改善提案リスト

##### `async create_improvement_issue(proposal: ImprovementProposal) -> int`

改善提案からGitHub Issueを作成する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `proposal` | `ImprovementProposal` | 作成元の改善提案 |

**戻り値**: `int` - 作成されたIssue番号

##### `async apply_approved_proposal(proposal_id: str) -> None`

承認済みの改善提案を適用する。プロンプト修正やワークフロー変更を自動的に反映する。

| パラメータ | 型 | 説明 |
|-----------|---|------|
| `proposal_id` | `str` | 適用する提案ID |
