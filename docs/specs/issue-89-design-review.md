# #89 実装仕様: 設計レビュー（design.json 配信 + 承認/差し戻し API）

参照: docs/designs/web-ui-architecture.md §3.4, §7 G10 ／ 基盤: U3（PLAN 統合・plan_json）/ U4（承認統一）/ #87・#88（ControlBus・操作 API）

## スコープ

Web UI の設計レビュー画面に実データを供給し、UI からの承認/差し戻しでパイプラインを動かす。

- **GET /api/issues/{n}/design**: 構造化設計（design.json）を配信
- **POST /api/issues/{n}/review**: インラインレビュー提出を分類 → 指摘=PLAN差し戻し / 質問=回答 / 0件=承認（control.jsonl 経由）
- フロント: review/* を実 API に接続

## 重要な前提（既存資産）

- PLAN フェーズは既に **構造化レコード `plan_json`**（schema_version / plan_depth / ui_impact /
  summary / test_cases / [architecture / subtasks]）を生成し、**state.json に永続化**している
  （`IssueState.plan_json`、読み取り API も通過済み）。
- → **design.json は plan_json から導出できる**。Unit A は agent パイプラインを変更せず、
  API 層で anchor ID を付与して配信する（新たな成果物書き出し経路を作らない）。
- 承認/差し戻しの ControlBus 受け口は #87/#88 で整備済み（control.jsonl + 全語彙 API）。
  ただし「指摘 → PLAN 差し戻し（feedback 付き）」専用の経路は本 Issue で定義する。

## 設計判断

### 1. design.json 導出 + anchor ID（Unit A）
`plan_json` の各要素に **安定した anchor ID** を付与した DesignResponse を API 層で構築する。
inline-review.tsx のコメントはこの anchor を参照して送信し、差し戻し時に「どの要素への指摘か」を
PLAN へ正確に渡す。

- anchor 規則（決定的・並び順安定）:
  - test_cases: `tc-01`, `tc-02`, …（1 始まり・ゼロ詰め 2 桁）
  - subtasks: `st-1`, `st-2`, …（plan_json の subtask.id があれば `st-{id}`、無ければ序数）
  - architecture: 段落（空行区切り）ごとに `arch-1`, `arch-2`, …（1 ブロックなら `arch-1` のみ）
  - summary: `sum-1`（単一）
- `build_design_response(plan_json) -> DesignResponse`（純関数）。plan_json が None なら
  `present=false` の最小 design（reason 付き、200）を返す（読み取り API の「停止中でも応答」方針）。
- schema: `DesignResponse`（present, plan_depth, ui_impact, summary{anchor,text},
  test_cases[{anchor,text}], architecture[{anchor,text}], subtasks[{anchor,id,title}], reason）

### 2. GET /api/issues/{n}/design（Unit A）
- `_resolve_issue` で (repo, IssueState) を解決（複数一致は 400、不在は 404）
- `build_design_response(state.plan_json)` を返す（常に 200・plan 未生成は present=false）

### 3. POST /api/issues/{n}/review（Unit B）
インラインレビュー提出（コメント配列）を受け、**分類して 1 つの帰結**に落とす。

- リクエスト: `{ comments: [{anchor, anchor_label, tag: "指摘"|"質問", body}], actor }`
- 分類ロジック（`classify_review`、純関数）:
  - 指摘（tag=指摘）が 1 件でもある → **changes_requested**（PLAN 差し戻し）
  - 指摘 0 件 かつ 質問あり → **questions**（回答生成）
  - コメント 0 件 → **approved**（承認）
- 帰結ごとの control.jsonl 行（既存 ControlBus / 承認経路に接続）:
  - approved → 承認コマンド（U4 の承認口。`{action:"approve", issue, actor}`）
  - changes_requested → 差し戻し。指摘全文（anchor + body を整形した feedback）を載せて
    PLAN へ戻す（`{action:"revise_plan", issue, actor, feedback}` を control_bus に追加、
    consume 側で PLAN へ再エンキュー）
  - questions → 質問への回答生成（`{action:"answer_questions", issue, actor, questions}`）
- レスポンス: `{ outcome: "approved"|"changes_requested"|"questions", accepted: true }`
- GitHub 承認（LGTM/👍）との並存: 本 API は control.jsonl 経由で U4 の承認判定に合流する
  （二重承認は冪等。approval.py 側で吸収）

### 4. design.json の v1→v2 差分（Unit B 付随・任意）
差し戻し後の再生成で `plan_json` が更新されたら、design.json に前版との変更点サマリを含める。
plan_json に版管理が無いため、本 Issue では **changes（前回 summary との差分テキスト）を
best-effort** で付ける（無ければ省略）。本格的な版管理は別途。

### 5. フロント（Unit C）
- `GET /api/issues/{n}/design` を usePolling で取得し ReviewClient / inline-review に供給
- anchor は design.json の anchor を使用（UI 自動採番をやめ、サーバ anchor に一致させる）
- 提出ボタン → `POST /api/issues/{n}/review`。outcome に応じたトースト（承認/差し戻し/質問送信）
- EvidenceGallery は #91 スコープのため本 Issue では繋がない（ui_impact 表示のみ）

## 実装ユニット

- **Unit A**: design.json 導出（anchor 付与・純関数）+ GET /api/issues/{n}/design + schema
- **Unit B**: POST /api/issues/{n}/review（classify_review + control.jsonl 接続）+ control_bus に
  revise_plan / answer_questions を追加 + orchestrator ハンドラ（PLAN 再エンキュー）
- **Unit C**: フロント review/* の実接続（design 取得・提出）

## テスト（TDD・80%+）
- `test_design_artifact.py`: build_design_response（plan 有/無・light/full・anchor 採番・
  architecture 段落分割・subtask id 有無）
- `test_api_endpoints.py`: GET design（present/absent/404/400）、POST review（3 帰結の
  control.jsonl 行・422）
- `test_control_bus.py`: revise_plan/answer_questions のパース
- `test_orchestrator_control.py`: revise_plan → PLAN 再エンキュー（feedback 付き）
- web: design 取得アダプタ・review 提出（カバレッジ対象に追加し 100% 維持）

## 受け入れ条件（Issue 由来）
- [ ] UI のインラインレビュー提出が実際にパイプラインを動かす（差し戻し/承認/質問）
- [ ] design.json の各要素に安定 anchor ID があり、指摘が該当要素に紐づく

## 非スコープ
- エビデンス（スクショ/録画）→ #91 ／ plan_json の本格版管理 → 別途
- 認証 → #115
