# Design Revise (設計修正) フェーズ

## プロンプトテンプレート

```
以下のレビュー指摘に対応してください:
{{review_comments}}
```

## 注入コンテキスト

| プレースホルダ | 内容 | 取得元 |
|---------------|------|--------|
| `{{review_comments}}` | PRのレビューコメント全文 | GitHub API (`get_pr_reviews`, `get_pr_comments`) |

レビューコメントは全コメントをまとめて渡す。AIがコメントの温度感 (LGTM, nit, 必須修正等) を判断して対応する。

セッション継続により、AIは設計書を作成した時の文脈を保持している。追加のコンテキスト注入は不要。

## 期待する出力形式

- レビュー指摘への対応が完了し、設計書が更新されていること
- git commit + push が完了していること
- PRが更新されていること (force push またはコミット追加)

## Claude Agent SDK オプション

| オプション | 値 |
|-----------|-----|
| `max_budget_usd` | `2.0` |
| `timeout_sec` | `1800` |
| `permission_mode` | `acceptEdits` |
| `allowed_tools` | デフォルト (制限なし) |
| `subagents` | なし |
| `session` | 前回セッション継続 (`ClaudeSDKClient` + `resume=session_id`) |
