# Impl Revise (実装修正) フェーズ

## プロンプトテンプレート

```
以下のレビュー指摘に対応してください:
{{review_comments}}
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{review_comments}}` | PRのレビューコメント全文 | GitHub API (`get_pr_reviews`, `get_pr_comments`) |

セッション継続により、AIは実装時の文脈を保持している。追加のコンテキスト注入は不要。

レビューコメントの取得方法:
- PRに複数人がコメントした場合、全コメントをまとめて渡す
- AIがコメントの温度感 (LGTM, nit, 必須修正等) を判断して対応

## 期待する出力形式

- レビュー指摘への対応が完了し、コードが更新されていること
- ローカルでテスト・lint・ビルドが成功していること
- git commit + push が完了していること
- PRが更新されていること

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `5.0` |
| `timeout_sec` | `1800` |
| `permission_mode` | `bypassPermissions` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | `code-analyzer`, `test-writer` |
| `session` | 前回セッション継続 (`ClaudeSDKClient` + `resume=session_id`) |
