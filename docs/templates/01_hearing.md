# Hearing (ヒアリング) フェーズ

## プロンプトテンプレート

```
以下のIssueについて要件ヒアリングを行ってください。

## Issue #{{issue_number}}: {{issue_title}}
{{issue_body}}

## コンテキスト
{{context}}

## 指示
1. Issueの内容を分析し、実装に必要な情報が十分か判断してください
2. 不明点がある場合は、具体的な質問をリストアップしてください
3. Issueが大きすぎる場合は分割を提案してください
4. 情報が十分な場合は "READY_FOR_DESIGN" と出力してください

出力形式:
- 質問がある場合: Issueコメントとして投稿する質問テキスト
- 分割提案の場合: 分割案のリスト
- 準備完了: "READY_FOR_DESIGN"
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{issue_number}}` | Issue番号 | GitHub API (`get_issue`) |
| `{{issue_title}}` | Issueタイトル | GitHub API (`get_issue`) |
| `{{issue_body}}` | Issue本文 | GitHub API (`get_issue`) |
| `{{context}}` | 自動収集コンテキスト | `ContextEngine.build_context()` |

`{{context}}` に含まれる要素:
- **リポジトリ構造**: `tree` コマンド + 主要ファイルの1行サマリ (AST解析)
- **CLAUDE.md**: プロジェクト規約 (存在する場合)
- **関連ファイル**: Issue本文のキーワードから `ripgrep` で検索した関連コード

## 期待する出力形式

- 質問がある場合: Issueコメントとして投稿可能なMarkdownテキスト
- 分割提案の場合: 分割案のリスト形式テキスト
- 準備完了の場合: 文字列 `READY_FOR_DESIGN` を含む出力

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `1.0` |
| `timeout_sec` | `600` |
| `permission_mode` | `acceptEdits` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | なし |
| `session` | 新規 (`query()` で実行) |
