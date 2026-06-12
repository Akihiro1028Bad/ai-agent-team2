# Issue #112 — 共有サニタイザの秘密パターン拡充

> #85 セキュリティレビュー LOW(L1) のフォローアップ

`agent.jsonl`（assistant テキスト + ツール入力）の永続シンク追加に伴い、
`sanitize.py` の `TOKEN_PATTERN` が **GitHub トークンのみ**な点を補強する。
Anthropic / OpenAI / AWS / Slack / Google の秘密が平文で残る経路を塞ぐ。

## 方針

**プレフィックス固定・高エントロピーな高信頼パターンに限定**する。過度に広い
パターン（例: 裸の `sk-`、長い英数字列）は正当なテキストを壊す（false positive）
ため採用しない。`TOKEN_PATTERN` を単一の alternation に拡張し、`sanitize_text`
のロジックは不変に保つ（events.jsonl 側にも自動で効く）。

## 追加パターン

| プロバイダ | パターン | 備考 |
|-----------|---------|------|
| GitHub PAT/OAuth/fine-grained | `ghp_…{36}` / `gho_…{36}` / `github_pat_…{82}` | 既存 |
| Anthropic | `sk-ant-[A-Za-z0-9_-]{20,}` | `sk-ant-` 固定 |
| OpenAI (project) | `sk-proj-[A-Za-z0-9_-]{20,}` | `sk-proj-` 固定 |
| OpenAI (legacy) | `sk-[A-Za-z0-9]{48}` | 48 文字固定長 |
| AWS Access Key ID | `(?:AKIA|ASIA)[0-9A-Z]{16}` | 20 文字固定 |
| Slack | `xox[baprs]-[A-Za-z0-9-]{10,}` | `xox?-` 固定 |
| Google API key | `AIza[0-9A-Za-z_-]{35}` | `AIza` 固定 |

alternation の順序は `sk-ant-` / `sk-proj-` を legacy `sk-…{48}` より前に置く
（先頭一致で正しく分岐させる）。

## 非対象（false positive 回避）

- 裸の `sk-<短い文字列>`、一般的な英単語・ハイフン語（`task-management` 等）
- プレフィックス長未満の断片（例: `xoxb-123`）

## テスト

- `tests/unit/test_sanitize.py` に各プロバイダの伏字化テストを追加。
- false positive ガード（通常文・短い擬似トークンが**マスクされない**こと）。
- 既存の GitHub トークン / URL 機微パラメータ / dict・list 再帰が回帰しないこと。

## 参照
- `src/ai_agent_orchestrator/sanitize.py`
- #101（env 遮断・`ANTHROPIC_API_KEY` の TODO）
