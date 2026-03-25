# パターン抽出テンプレート

フェーズ: PATTERN_EXTRACTION (定期実行・N件蓄積時)

## 用途
蓄積されたエピソード群からセマンティックパターンを抽出する

## プロンプト

```
蓄積されたエピソード記録を分析し、再利用可能なパターンを抽出してください。

## エピソード記録
{{episodes_json}}

## 既存パターン（重複回避用）
{{existing_patterns_yaml}}

## 指示
以下のYAML形式で新規パターンを抽出してください:

patterns:
  - id: パターンID（kebab-case）
    description: パターンの説明（1文）
    frequency: 観測回数
    source_episodes: [issue番号のリスト]
    category: code_pattern | review_pattern | architecture_pattern | test_pattern
    action: プロンプトに追加すべき指示（具体的に）

抽出の観点:
- コードパターン（nullチェック、エラーハンドリング等）
- レビューで繰り返し指摘されること
- ファイル配置のルール
- テストのパターン
- 2回以上観測されたパターンを優先
```

## SDK設定
- max_budget_usd: 1.0
- timeout_sec: 300
