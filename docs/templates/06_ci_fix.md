# CI Fix (CI修正) フェーズ

## プロンプトテンプレート

```
CIが失敗しました（{{retry_count}}/3回目）。修正してください。

## CI失敗ログ
{{ci_logs}}

## 指示
1. CI失敗ログを分析して原因を特定
2. コードを修正
3. テスト・lint・ビルドをローカルで再実行して確認
4. git commit して Push
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{retry_count}}` | 現在のリトライ回数 (1-3) | `TaskRequest.extra["retry_count"]` |
| `{{ci_logs}}` | CI失敗ログ全文 | GitHub API (`get_check_runs`) + ログ取得 |

CI失敗ログには以下が含まれる:
- テスト失敗の詳細 (失敗テスト名、アサーションエラー)
- lint エラーの詳細 (ファイル名、行番号、ルール違反)
- ビルドエラーの詳細 (コンパイルエラー、型エラー)

## 期待する出力形式

- CI失敗の原因が特定され、修正されていること
- ローカルでテスト・lint・ビルドが成功していること
- git commit + push が完了していること

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `3.0` |
| `timeout_sec` | `1200` |
| `permission_mode` | `bypassPermissions` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | `code-analyzer`, `test-writer` |
| `session` | 新規 (`query()` で実行) |
