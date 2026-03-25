# Feature-S 簡易方針プロンプトテンプレート

## フェーズ: PLAN_BRIEF (Feature-S専用)

### プロンプト

```
あなたはソフトウェアエンジニアです。
以下のIssueの簡易実装方針を作成してください。

## Issue #{{issue_number}}: {{issue_title}}
{{issue_body}}

## ヒアリング記録
{{comments}}

## リポジトリ情報
{{repo_map}}

## CLAUDE.md
{{claude_md}}

## 指示
以下のフォーマットで方針をIssueコメント用に作成してください。
マークダウン形式で出力してください。

---
📋 **実装方針 (AI提案)**

**変更内容:**
- `ファイルパス`: 変更内容の説明
- `ファイルパス`: 変更内容の説明

**テスト方針:**
- [ ] テスト内容1
- [ ] テスト内容2

👍 で承認 / コメントで指摘をお願いします
---

方針は簡潔に。Feature-Sは小規模変更なので、過度に詳細にする必要はありません。
```

### Claude Agent SDK オプション

| 項目 | 値 |
|------|-----|
| max_budget_usd | 1.0 |
| timeout_sec | 600 (10分) |
| permission_mode | plan |
| session | 新規 (one-shot) |

### コンテキスト注入

| コンテキスト | 注入方法 |
|-------------|---------|
| リポマップ | ContextEngine.get_repo_map() |
| CLAUDE.md | ContextEngine.get_claude_md() |
| Issue本文 | GitHub API |
| ヒアリング結果 | GitHub API (コメント) |
| 関連ファイル | ContextEngine.get_relevant_files() |

### 期待する出力

- 簡易方針コメント（マークダウン形式）
- 変更ファイル一覧（パス + 変更内容）
- テスト方針
- 👍承認案内

### 品質チェック

- [ ] 「変更内容」にファイルパスが含まれるか
- [ ] 変更ファイル数が1-3の範囲か（Feature-Sの想定範囲）
- [ ] 「テスト方針」に具体的なテスト内容があるか
- [ ] 「👍」承認案内が含まれるか
