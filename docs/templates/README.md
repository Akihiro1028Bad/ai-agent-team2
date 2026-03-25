# プロンプトテンプレート一覧

各フェーズで使用されるプロンプトテンプレート、注入コンテキスト、期待する出力形式、Claude Agent SDK オプションを個別ファイルで管理する。

## ファイル一覧

| ファイル | フェーズ | 実行方式 | max_budget_usd | セッション |
|---------|---------|---------|----------------|-----------|
| [01_hearing.md](./01_hearing.md) | ヒアリング | `query()` | 1.0 | 新規 |
| [02_design.md](./02_design.md) | 設計書作成 | `query()` | 3.0 | 新規 |
| [03_design_revise.md](./03_design_revise.md) | 設計修正 | `ClaudeSDKClient` | 2.0 | 継続 |
| [04_planning.md](./04_planning.md) | 実装計画 | `query()` | 1.0 | 新規 |
| [05_implement.md](./05_implement.md) | 実装 | `query()` | 10.0 | 新規 |
| [06_ci_fix.md](./06_ci_fix.md) | CI修正 | `query()` | 3.0 | 新規 |
| [07_impl_revise.md](./07_impl_revise.md) | 実装修正 | `ClaudeSDKClient` | 5.0 | 継続 |
| [08_bug_analysis.md](./08_bug_analysis.md) | Bug分析 | `query()` | 2.0 | 新規 |
| [09_feature_s_plan_brief.md](./09_feature_s_plan_brief.md) | Feature-S簡易方針 | `query()` | 1.0 | 新規 |
| [10_type_detection.md](./10_type_detection.md) | タイプ自動判定 | `query()` | 0.3 | 新規 |
| [11_episode_record.md](./11_episode_record.md) | エピソード記録 | `query()` | 0.5 | 新規 |
| [12_pattern_extraction.md](./12_pattern_extraction.md) | パターン抽出 | `query()` | 1.0 | 新規 |
| [13_skill_detection.md](./13_skill_detection.md) | Skill自動検出 | `query()` | 2.0 | 新規 |
| [14_improvement_proposal.md](./14_improvement_proposal.md) | 改善提案生成 | `query()` | 2.0 | 新規 |

## 補足

- コンテキストエンジンの動作詳細 → `design-python.md` セクション4（4.5 コンテキストエンジニアリング）
- 設計書テンプレート本体 → `02_design.md` 内に統合済み（`design-python.md` セクション15 も参照）
- 実装計画テンプレート本体 → `04_planning.md` 内に統合済み（`design-python.md` セクション9 も参照）
