# Skill自動検出テンプレート

フェーズ: SKILL_DETECTION (定期実行・N件蓄積時)

## 用途
エピソード群から再利用可能なSkill（タスクテンプレート）を検出する

## プロンプト

```
エピソード記録を分析し、再利用可能なSkillを検出してください。

## エピソード記録
{{episodes_json}}

## 既存Skill（重複回避用）
{{existing_skills_yaml}}

## Skillの定義
同じパターンのタスクが2回以上観測された場合、Skillとして抽出する。

## 指示
検出したSkillをYAML形式で出力してください:

skills:
  - name: skill-name (kebab-case)
    description: 説明（1文）
    created_from_episodes: [issue番号]
    trigger:
      keywords: [マッチするキーワード]
      file_patterns: [マッチするファイルパターン]
    variables:
      - name: 変数名
        description: 説明
        example: 例
    phases:
      design:
        prompt_additions: |
          このSkillではこうする
      implement:
        prompt_additions: |
          このSkillではこうする
        expected_files:
          - ファイルパス（{{variable}}形式で変数を使用可）
```

## SDK設定
- max_budget_usd: 2.0
- timeout_sec: 300
