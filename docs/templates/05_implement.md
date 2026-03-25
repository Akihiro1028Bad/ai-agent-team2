# Implement (実装) フェーズ

## プロンプトテンプレート

```
実装計画に基づいてコードを実装してください。

## Issue #{{issue_number}}: {{issue_title}}

## コンテキスト
{{context}}

## 指示
1. 実装計画の順序に従ってコードを実装
2. テストコードも作成
3. テスト・lint・ビルドを実行して結果を確認
4. git commit して Push
5. PRを作成（タイトル: "feat: Issue #{{issue_number}} {{短い説明}}"）
6. PR descriptionに以下を含める:
   - 変更の概要
   - 実行したコマンドとその結果
   - AI Agent ログ（実行時間、変更判断根拠）
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{issue_number}}` | Issue番号 | GitHub API |
| `{{issue_title}}` | Issueタイトル | GitHub API |
| `{{context}}` | 自動収集コンテキスト | `ContextEngine.build_context()` |

`{{context}}` に含まれる要素 (`phase="implement"`):
- リポジトリ構造
- CLAUDE.md (存在する場合)
- 関連ファイル
- **設計書** (`docs/designs/issue-{{issue_number}}.md`)
- **実装計画** (`docs/designs/issue-{{issue_number}}-plan.md`)

## 期待する出力形式

- コード + テストコードが実装されていること
- テスト・lint・ビルドがローカルで成功していること
- git commit + push が完了していること
- PRが作成され、PRのURL が出力に含まれること
- PR descriptionに変更概要・実行コマンド結果・AIログが含まれること

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `10.0` |
| `timeout_sec` | `3600` |
| `permission_mode` | `bypassPermissions` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | `code-analyzer`, `test-writer` |
| `session` | 新規 (`query()` で実行) |

## サブエージェント定義

### code-analyzer

```python
AgentDefinition(
    name="code-analyzer",
    description="既存コードベースの構造分析とリポマップ生成",
    instructions="リポジトリのファイル構造、主要モジュール、依存関係を分析して要約する。",
)
```

### test-writer

```python
AgentDefinition(
    name="test-writer",
    description="テストコード作成の専門エージェント",
    instructions="既存テストのパターンに従い、ユニットテストと統合テストを作成する。",
)
```
