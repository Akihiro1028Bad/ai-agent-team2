# エピソード記録テンプレート

フェーズ: EPISODE_RECORD (全タイプ共通・Issue完了時)

## 用途
Issue完了時にエピソードを自動記録する際のプロンプトテンプレート

## プロンプト

```
完了したIssueの処理結果を振り返り、エピソード記録を作成してください。

## Issue情報
- Issue: #{{issue_number}}
- タイトル: {{issue_title}}
- タイプ: {{issue_type}}
- リポジトリ: {{repo}}

## 各フェーズの実行ログ
{{phase_logs}}

## レビュー指摘履歴
{{review_comments}}

## 指示
以下のJSON形式でエピソード記録を作成してください:

{
  "issue": {{issue_number}},
  "repo": "{{repo}}",
  "type": "{{issue_type}}",
  "title": "{{issue_title}}",
  "phases": [...],
  "total_cost_usd": ...,
  "review_rounds": ...,
  "ci_retries": ...,
  "files_changed": [...],
  "learnings": [
    "この処理から得られた学び・パターンを記載"
  ]
}

learningsには以下の観点で記載してください:
- コードパターン（よく使った手法）
- レビューで指摘された点
- ファイル配置のルール
- テストの書き方
- 失敗から学んだこと
```

## SDK設定
- max_budget_usd: 0.5
- timeout_sec: 120
