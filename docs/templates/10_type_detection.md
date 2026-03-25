# タイプ自動判定プロンプトテンプレート

## フェーズ: TYPE_DETECTION (全タイプ共通・最初に実行)

### プロンプト

```
あなたはIssueのタイプを判定するAIです。
以下のIssueを分析し、最も適切なタイプを1つだけ回答してください。

## タイプ定義
- bug: バグ修正（エラー、不具合、動かない、壊れた、500エラー等）
- feature-s: 小規模機能（1-3ファイル変更、設計書不要レベル）
- feature-m: 中規模機能（複数ファイル、設計書が必要なレベル）
- feature-l: 大規模機能（分割が必要なレベル）

## Issue #{{issue_number}}: {{issue_title}}
{{issue_body}}

## リポジトリ情報
{{repo_map}}

## 回答形式
TYPE: <タイプ名>
REASON: <判定理由を1文で>
```

### Claude Agent SDK オプション

| 項目 | 値 |
|------|-----|
| max_budget_usd | 0.3 |
| timeout_sec | 120 (2分) |
| permission_mode | plan |
| session | 新規 (one-shot) |

### コンテキスト注入

| コンテキスト | 注入方法 |
|-------------|---------|
| リポマップ | ContextEngine.get_repo_map() |
| Issue本文 | GitHub API |

### 期待する出力

- `TYPE: bug` or `TYPE: feature-s` or `TYPE: feature-m` or `TYPE: feature-l`
- `REASON: 判定理由`

### パース方法

```python
def parse_type_detection(response: str) -> str:
    for line in response.splitlines():
        if line.strip().startswith("TYPE:"):
            detected = line.split(":", 1)[1].strip().lower()
            if detected in ("bug", "feature-s", "feature-m", "feature-l"):
                return detected
    return "feature-m"  # デフォルト（安全側に倒す）
```

### 検証結果

| テストケース | 期待 | 判定 | コスト |
|-------------|------|------|-------|
| 「500エラーが出る」 | bug | ✅ bug | $0.011 |
| 「バリデーション追加」 | feature-s | ✅ feature-s | $0.007 |
| 「ダッシュボード新規作成」 | feature-m | ✅ feature-m | $0.007 |
