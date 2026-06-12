// 設計レビュー（PLAN フェーズ成果物）のモック

export type TestCategory = "正常" | "異常" | "境界";

export interface TestCase {
  id: string;
  category: TestCategory;
  target: string;
  title: string;
}

export interface DesignReview {
  issue: number;
  repo: string;
  title: string;
  /** アーキテクチャ説明（Markdown） */
  architecture: string;
  /** アーキテクチャ図（Mermaid） */
  diagram: string;
  /** テスト方針（Markdown） */
  testStrategy: string;
  /** テストケース一覧 */
  testCases: TestCase[];
  /** 実装計画 サブタスク */
  subtasks: { id: number; title: string; files: string[]; dependsOn: number[] }[];
  /** 画面プロトタイプ（レスポンシブ HTML, UI 影響時のみ） */
  prototypeHtml?: string;
}

const profilePrototype = `<!doctype html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Noto Sans JP',system-ui,sans-serif;background:#f5f6f8;color:#1c2024}
  .top{background:#fff;border-bottom:1px solid #e6e8ec;padding:14px 20px;display:flex;align-items:center;gap:12px}
  .top .brand{font-weight:700;letter-spacing:-.01em}
  .top .nav{margin-left:auto;display:flex;gap:18px;font-size:14px;color:#5c636f}
  .top .nav a.active{color:#1c2024;font-weight:600}
  .wrap{max-width:880px;margin:0 auto;padding:24px 20px}
  .card{background:#fff;border:1px solid #e6e8ec;border-radius:16px;overflow:hidden}
  .hero{display:flex;gap:20px;align-items:center;padding:24px}
  .avatar{width:84px;height:84px;border-radius:50%;background:linear-gradient(135deg,#6ee7b7,#3b82f6);flex:none}
  .hero h1{font-size:22px}
  .hero p{color:#5c636f;font-size:14px;margin-top:4px}
  .btn{margin-left:auto;border:1px solid #d0d4da;background:#fff;border-radius:10px;padding:9px 16px;font-size:14px;cursor:pointer}
  .btn.primary{background:#111419;color:#fff;border-color:#111419}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}
  .field{background:#fff;border:1px solid #e6e8ec;border-radius:14px;padding:16px}
  .field label{display:block;font-size:12px;color:#8a909a;letter-spacing:.04em;text-transform:uppercase}
  .field .v{margin-top:6px;font-size:15px}
  @media(max-width:560px){.hero{flex-wrap:wrap}.btn{margin-left:0;width:100%}.grid{grid-template-columns:1fr}.top .nav{display:none}}
</style></head>
<body>
  <div class="top"><span class="brand">Sample App</span>
    <nav class="nav"><a>Home</a><a class="active">Profile</a><a>Settings</a></nav>
  </div>
  <div class="wrap">
    <div class="card hero">
      <div class="avatar"></div>
      <div><h1>サンプルユーザー</h1><p>sample@example.com ・ Tokyo</p></div>
      <button class="btn primary">編集</button>
    </div>
    <div class="grid">
      <div class="field"><label>名前</label><div class="v">サンプルユーザー</div></div>
      <div class="field"><label>メール</label><div class="v">sample@example.com</div></div>
      <div class="field"><label>自己紹介</label><div class="v">プロフィール画面のサンプルです。</div></div>
      <div class="field"><label>Web サイト</label><div class="v">https://example.com</div></div>
    </div>
  </div>
</body></html>`;

export const designReviews: Record<number, DesignReview> = {
  129: {
    issue: 129,
    repo: "ai-agent-team2-test",
    title: "ユーザープロフィール画面の追加",
    architecture: `## アーキテクチャ

プロフィール画面を **Server / Client コンポーネント分割** で実装する。
データ取得は API クライアント経由のモック対応（ヒアリングで「APIはモックで可」と確認済み）。

- **page.tsx (Server)** — メタデータ付与・認証から userId を解決し \`ProfileClient\` へ委譲
- **ProfileClient.tsx (Client)** — \`useUserProfile\` フックで取得・編集状態を管理
- **route.ts (Route Handler)** — \`GET / PATCH /api/users/[id]/profile\`。メモリ内モックストア＋入力バリデーション
- 認証連携（動的 userId）は **今回スコープ外**（TODO で残す）

### データフロー
ユーザー操作 → ProfileClient → API クライアント → Route Handler（モックストア）→ レスポンス → 再描画。`,
    diagram: `flowchart LR
  U([ユーザー]) --> PC[ProfileClient<br/>Client]
  PC -->|GET / PATCH| API[API クライアント]
  API --> RH[Route Handler<br/>route.ts]
  RH --> MS[(モックストア)]
  MS --> RH --> API --> PC
  SP[page.tsx<br/>Server] -. userId .-> PC`,
    testStrategy: `## テスト方針

- **単体（Vitest/Jest）**: Route Handler のバリデーション・分岐、フックの状態遷移を網羅。
- **カバレッジ目標 80%**（CLAUDE.md 準拠）。境界値・異常系を必須。
- **セキュリティ観点**: 更新可能フィールドの allowlist（id/email/createdAt は不変）をテストで固定。
- E2E は本 Issue ではスコープ外（UI 確認はプロトタイプで代替）。`,
    testCases: [
      { id: "TC-01", category: "正常", target: "GET", title: "既存ユーザーのプロフィールを返す" },
      { id: "TC-02", category: "正常", target: "PATCH", title: "name / bio / location / website を更新できる" },
      { id: "TC-03", category: "異常", target: "GET", title: "存在しない ID で 404" },
      { id: "TC-04", category: "異常", target: "PATCH", title: "name が空文字で 400" },
      { id: "TC-05", category: "境界", target: "PATCH", title: "bio ちょうど 200 文字は許容" },
      { id: "TC-06", category: "境界", target: "PATCH", title: "location ちょうど 100 文字は許容" },
      { id: "TC-07", category: "異常", target: "PATCH", title: "website が https:// で始まらないと 400" },
      { id: "TC-08", category: "正常", target: "security", title: "id/email/createdAt は更新されない（allowlist）" },
    ],
    subtasks: [
      { id: 1, title: "Route Handler の実装", files: ["route.ts", "route.test.ts"], dependsOn: [] },
      { id: 2, title: "Header ナビゲーションにリンク追加", files: ["Header.tsx", "Header.test.tsx"], dependsOn: [] },
      { id: 3, title: "ProfilePage の Server/Client 分割", files: ["page.tsx", "ProfileClient.tsx", "page.test.tsx"], dependsOn: [1] },
    ],
    prototypeHtml: profilePrototype,
  },
};

designReviews[131] = {
  issue: 131,
  repo: "ai-agent-team2-test",
  title: "ログイン時の不正なリダイレクトを修正",
  architecture: `## 修正方針（原因と対策）

ログイン後のリダイレクト先に、未検証の \`next\` クエリパラメータをそのまま使用していたため、
**オープンリダイレクト**（外部サイトへの誘導）が可能だった。

- **対策**: リダイレクト先を **同一オリジンの許可リスト**で検証し、不正な場合は既定の \`/\` へフォールバック。
- 影響範囲は \`auth/redirect.ts\` の1関数に限定。UI 変更なし（plan_depth=light）。`,
  diagram: `flowchart TD
  A[ログイン成功] --> B{next を検証}
  B -->|同一オリジン/許可| C[next へ遷移]
  B -->|不正/外部| D[/ へフォールバック/]`,
  testStrategy: `## テスト方針
- **単体**: \`safeRedirect\` の許可/拒否分岐を網羅。境界（相対パス・プロトコル相対 \`//evil\`・別オリジン）を必須。
- 既存のログインフローのリグレッションを確認。`,
  testCases: [
    { id: "TC-01", category: "正常", target: "safeRedirect", title: "同一オリジンの相対パスは許可" },
    { id: "TC-02", category: "異常", target: "safeRedirect", title: "別オリジン URL は / へフォールバック" },
    { id: "TC-03", category: "境界", target: "safeRedirect", title: "プロトコル相対 //evil.com を拒否" },
    { id: "TC-04", category: "境界", target: "safeRedirect", title: "next 未指定時は / へ" },
  ],
  subtasks: [
    { id: 1, title: "safeRedirect の実装と適用", files: ["auth/redirect.ts", "auth/redirect.test.ts"], dependsOn: [] },
  ],
  // plan_depth=light のため画面プロトタイプなし（UI 変更なし）
};

export function getDesignReview(n: number): DesignReview | null {
  return designReviews[n] ?? null;
}
