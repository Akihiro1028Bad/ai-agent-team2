# Orchestrator — Control Room（Web UI プロトタイプ）

AI マルチエージェント・オーケストレーターを **すべて Web UI から操作する**ための管理画面プロトタイプ。
機能イメージを固める目的で、**モックデータ・配線なし**で作成（バックエンド未接続）。

## 技術スタック
- Next.js 16（App Router）+ React 19 + TypeScript
- Tailwind CSS v4（CSS-first / デザイントークンは `app/globals.css` の `@theme`）
- フォント: Noto Sans JP（日本語）+ JetBrains Mono（データ）
- デザイン方針: ダーク「ops console / mission control」、状態色（稼働=ライム / 人間待ち=アンバー / 中断=レッド / 完了=シアン）

## 画面
| ルート | 画面 | 内容 |
|--------|------|------|
| `/` | ダッシュボード | Issue 一覧（タイプ・フェーズ rail・状態・コスト）＋アクティビティ |
| `/issues/[id]` | Issue 詳細 | フェーズタイムライン・サブタスク・設計書 |
| `/approvals` | 承認待ち | 人間ゲート操作（承認/差し戻し・ヒアリング回答・レビュー応答） |
| `/settings` | 制御・設定 | start/stop・ポーリング間隔・監視リポジトリ・通知 |

フェーズ rail は **再設計後の統一パイプライン**（受付→ヒアリング→計画→承認→実装→レビュー→完了、分割/修正は条件付き）に対応。

## 起動
```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

## 位置づけ・今後
- これは **UX を可視化して機能を固めるための叩き台**。
- 本実装では、UI が叩く **API レイヤー** と、バックエンド側の **人間操作の抽象化（GitHub 今 / Web UI 将来）** が必要
  （`../docs/designs/pipeline-redesign-proposal.md` 参照）。
- モックは `lib/mock.ts`、型は `lib/types.ts`。
