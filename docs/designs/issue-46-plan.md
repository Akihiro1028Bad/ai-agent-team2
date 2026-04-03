# Issue #46 実装計画 — README.md リニューアル

## 概要

現行の `README.md` を設計書（`docs/designs/issue-46.md`）に基づいて全面リニューアルする。
変更対象は `README.md` の 1 ファイルのみ。

---

## 実装方針

### 変更ファイル一覧

| ファイル | 種別 | 変更内容 |
|---------|------|---------|
| `README.md` | 更新 | デザイン重視のビジュアル系 README に全面リニューアル |

### 作業内容

1. **ヘッダー領域の刷新**
   - ASCII アートバナー（罫線ブロック `╔══╗` スタイル）を追加
   - キャッチコピー 3 行を配置
   - shields.io バッジ群（CI / Python 3.13+ / License MIT / uv / ruff）を拡充

2. **全セクション見出しに絵文字を付与**
   - `## 🌟 概要`, `## 🏛️ アーキテクチャ`, `## 🔀 ワークフロー` 等

3. **概要セクションの特徴リストを更新**
   - 絵文字アイコン付きリスト形式に変更
   - `knowledge/` 自己改善ループの記述を強化

4. **アーキテクチャ図を拡充**
   - `knowledge/` コンポーネント（Episode Store → Pattern Extractor → Skill Mgr）を追記

5. **ワークフローテーブルを更新**
   - `PLAN_BRIEF` フェーズ表記の統一
   - コスト目安列の整形

6. **プロジェクト構成ツリーを更新**
   - `phases/` 配下に `type_detection.py`, `dispatcher.py`, `split.py`, `impl_revise.py`, `design_revise.py` を追記

7. **技術スタックのバージョン情報を更新**
   - `pyproject.toml` の値に準拠（claude-agent-sdk>=0.1.50 等）

8. **CLI コマンドをカテゴリ別にグループ化**
   - 📦 アカウント管理 / ⚙️ リポジトリ設定 / 🚀 稼働操作

9. **設計原則に絵文字アイコンを追加**

---

## サブタスク

### subtask-1: README.md 全面リニューアル
- files: [`README.md`]
- depends_on: []
- description: |
    設計書（docs/designs/issue-46.md）に従い README.md を全面リニューアルする。
    具体的な作業内容：
    1. ヘッダー領域：ASCII アートバナー（╔══╗ 罫線スタイル）＋キャッチコピー 3 行＋バッジ群
       （CI / Python 3.13+ / License MIT / uv / ruff の 5 バッジ）
    2. 全セクション見出しに絵文字を付与
       （🌟 概要 / 🏛️ アーキテクチャ / 🔀 ワークフロー / 🚀 クイックスタート /
        🛠️ CLI コマンド / ⚙️ 設定 / 🧰 技術スタック / 💻 開発 /
        📚 ドキュメント / 🏷️ GitHub Labels / ✅ 検証結果 / 📄 ライセンス）
    3. 概要の特徴リストを絵文字アイコン付きに更新
       （🤖 🔀 🤝 ⚡ 🏢 🔑 🧠 の 7 項目）
    4. アーキテクチャ ASCII 図に knowledge/ ブロックを追記
    5. ワークフローテーブルを設計書の内容に合わせて更新
    6. プロジェクト構成ツリーに新モジュール
       （type_detection.py / dispatcher.py / split.py / impl_revise.py / design_revise.py）を追記
    7. 技術スタックのバージョン情報を pyproject.toml の値に準拠して更新
    8. CLI コマンドテーブルをカテゴリ別（アカウント管理 / リポジトリ設定 / 稼働操作）にグループ化
    9. 設計原則の 5 項目に絵文字アイコンを追加
    10. 検証結果テーブルの合計行を太字で強調
