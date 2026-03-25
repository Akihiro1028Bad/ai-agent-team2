# 改善提案生成テンプレート

フェーズ: IMPROVEMENT_PROPOSAL (定期実行)

## 用途
メトリクスとパターン分析結果から具体的な改善提案を生成する

## プロンプト

```
メトリクスとパターン分析結果を元に、具体的な改善提案を生成してください。

## メトリクス
{{metrics_json}}

## 検出済みパターン
{{patterns_yaml}}

## 現在の設定
{{current_config}}

## 指示
以下の観点で改善提案を生成してください:

1. コスト最適化 — 予算設定は実績に対して適切か
2. プロンプト改善 — レビュー指摘を減らすためのプロンプト変更
3. ワークフロー改善 — フェーズの追加/削除/変更
4. 品質向上 — テスト・レビューの改善

## 出力形式（JSON）
{
  "proposals": [
    {
      "id": "proposal-N",
      "category": "cost | prompt | workflow | quality",
      "title": "提案タイトル",
      "description": "詳細説明",
      "impact": "high | medium | low",
      "action": "具体的な変更内容",
      "metrics_basis": "根拠となるメトリクス"
    }
  ]
}
```

## SDK設定
- max_budget_usd: 2.0
- timeout_sec: 300
