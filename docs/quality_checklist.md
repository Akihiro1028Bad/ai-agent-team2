# 最終品質チェックリスト（Fable5 が担保）

> サブエージェントに中間作業を委譲しても、最終品質は必ず Fable5 が確認する。
> マージ前にこのチェックリストを通す。詳細方針は [ai_model_routing.md](ai_model_routing.md)。

## 設計・整合性

- [ ] 受け入れ条件をすべて満たしている
- [ ] 既存アーキテクチャ・Protocol ベース設計と整合
- [ ] フェーズ遷移・状態の整合（VALID_TRANSITIONS と state_machine 定義の両方）
- [ ] 後方互換（旧 state.json ロード、re-export パス）を壊していない

## 実装品質

- [ ] mypy strict 通過（`uv run mypy src/`）
- [ ] ruff check + format 通過（`uv run ruff check . && uv run ruff format --check .`）
- [ ] pytest 通過（`uv run pytest tests/`）。ゲートは**完全出力**で確認（truncate しない）
- [ ] 新規/変更コードにテストがある（境界値・異常系・回帰）
- [ ] 無関係な変更が混ざっていない（最小差分）

## UX・挙動

- [ ] ユーザー向け文言・通知が適切（日本語）
- [ ] エラー処理が明示的（裸の except なし、サイレント失敗なし）
- [ ] 必要なら実機 E2E で挙動確認（mock では出ない遷移・配線のズレを検出）

## セキュリティ

- [ ] 秘密情報の混入なし（config.yaml/config.test.yaml は staged しない、`git add -A` をルートで使わない）
- [ ] 入力検証（外部入力・デシリアライズ・認可）に抜けがない
- [ ] security-reviewer の Critical/High が解消済み

## レビュー

- [ ] code-reviewer / 該当言語 reviewer の指摘を反映（CRITICAL/HIGH は必須）
- [ ] マージ前に PR 上で `@claude /review` とセキュリティレビューを実行し、マージ可能相当まで反復
- [ ] レビュー修正後は `@claude /review` で再依頼（報告のみで終えない）

## 委譲結果の検証

- [ ] サブエージェントの結論を未検証で採用していない
- [ ] 「Fable5 が判断すべきこと」を実際に Fable5 が判断した
