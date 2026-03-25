# Planning (実装計画) フェーズ

## プロンプトテンプレート

```
設計書に基づき、実装計画を作成してください。

## Issue #{{issue_number}}: {{issue_title}}

## コンテキスト
{{context}}

## 指示
1. 設計書を読み込む
2. 変更するファイルの一覧と順序を決定
3. 各ファイルの変更内容を具体的に記述
4. 依存関係の順序（先に変更すべきファイル）を明記
5. テスト方針を決定
6. docs/designs/issue-{{issue_number}}-plan.md に実装計画を保存
7. git commit して Push

実装計画テンプレート:
{{impl_plan_template}}
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{issue_number}}` | Issue番号 | GitHub API |
| `{{issue_title}}` | Issueタイトル | GitHub API |
| `{{context}}` | 自動収集コンテキスト | `ContextEngine.build_context()` |
| `{{impl_plan_template}}` | 実装計画テンプレート | `templates/impl_plan_template.md` |

`{{context}}` に含まれる要素 (`phase="planning"`):
- リポジトリ構造
- CLAUDE.md (存在する場合)
- 関連ファイル
- **設計書** (`docs/designs/issue-{{issue_number}}.md`)

## 期待する出力形式

- 実装計画ファイルが `docs/designs/issue-{{issue_number}}-plan.md` に作成されること
- git commit + push が完了していること
- 変更ファイル一覧が依存関係順に並んでいること

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `1.0` |
| `timeout_sec` | `600` |
| `permission_mode` | `acceptEdits` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | なし |
| `session` | 新規 (`query()` で実行) |
