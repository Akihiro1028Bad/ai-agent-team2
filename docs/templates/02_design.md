# Design (設計書作成) フェーズ

## プロンプトテンプレート

```
以下のIssueの設計書を作成してください。

## Issue #{{issue_number}}: {{issue_title}}
{{issue_body}}

## ヒアリング記録
{{hearing_log}}

## コンテキスト
{{context}}

## 指示
1. docs/designs/issue-{{issue_number}}.md に設計書を作成
2. 設計書テンプレートに従って全セクションを埋める
3. git commit して Push
4. PRを作成（タイトル: "[設計書] Issue #{{issue_number}} {{issue_title}}"）
5. PRのURLを出力

設計書テンプレート:
{{design_doc_template}}
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{issue_number}}` | Issue番号 | GitHub API |
| `{{issue_title}}` | Issueタイトル | GitHub API |
| `{{issue_body}}` | Issue本文 | GitHub API |
| `{{hearing_log}}` | ヒアリングコメント全文 | GitHub API (`get_issue_comments`) |
| `{{context}}` | 自動収集コンテキスト | `ContextEngine.build_context()` |
| `{{design_doc_template}}` | 設計書テンプレート | `templates/design_doc_template.md` |

`{{context}}` に含まれる要素:
- リポジトリ構造
- CLAUDE.md (存在する場合)
- 関連ファイル

`{{hearing_log}}` の形式:
```
[username1]: コメント本文1
[username2]: コメント本文2
...
```

## 期待する出力形式

- 設計書ファイルが `docs/designs/issue-{{issue_number}}.md` に作成されること
- git commit + push が完了していること
- PR が作成され、PRのURL が出力に含まれること

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `3.0` |
| `timeout_sec` | `1800` |
| `permission_mode` | `acceptEdits` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | なし |
| `session` | 新規 (`query()` で実行) |
