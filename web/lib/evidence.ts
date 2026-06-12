// レビュー用エビデンス（スクリーンショット・動作デモ・テスト結果）のモック

export type EvidenceKind = "screenshot" | "video" | "terminal";

export interface Evidence {
  id: string;
  kind: EvidenceKind;
  title: string;
  caption: string;
  /** screenshot / video: iframe srcDoc HTML。terminal: テキスト */
  payload: string;
  /** screenshot のビューポート幅 (mobile=390) */
  viewport?: "desktop" | "mobile";
  durationSec?: number;
}

const baseCss = `*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans JP',system-ui,sans-serif;background:#f5f6f8;color:#1c2024}
.top{background:#fff;border-bottom:1px solid #e6e8ec;padding:12px 18px;display:flex;align-items:center;gap:12px}
.brand{font-weight:700}
.nav{margin-left:auto;display:flex;gap:16px;font-size:13px;color:#5c636f}
.nav .active{color:#1c2024;font-weight:600}
.wrap{max-width:840px;margin:0 auto;padding:20px 18px}
.card{background:#fff;border:1px solid #e6e8ec;border-radius:14px;display:flex;gap:18px;align-items:center;padding:20px}
.avatar{width:72px;height:72px;border-radius:50%;background:linear-gradient(135deg,#6ee7b7,#3b82f6);flex:none}
.card h1{font-size:19px}
.card p{color:#5c636f;font-size:13px;margin-top:3px}
.btn{margin-left:auto;border:1px solid #d0d4da;background:#111419;color:#fff;border-radius:9px;padding:8px 15px;font-size:13px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}
.field{background:#fff;border:1px solid #e6e8ec;border-radius:12px;padding:14px}
.field label{display:block;font-size:11px;color:#8a909a;text-transform:uppercase;letter-spacing:.04em}
.field .v{margin-top:5px;font-size:14px}
@media(max-width:560px){.card{flex-wrap:wrap}.btn{margin-left:0;width:100%}.grid{grid-template-columns:1fr}.nav{display:none}}`;

const profileScreen = (extra = "") => `<!doctype html><html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/><style>${baseCss}${extra}</style></head>
<body>
  <div class="top"><span class="brand">Sample App</span>
    <nav class="nav"><span>Home</span><span class="active">Profile</span><span>Settings</span></nav></div>
  <div class="wrap">
    <div class="card"><div class="avatar"></div>
      <div><h1>サンプルユーザー</h1><p>sample@example.com ・ Tokyo</p></div>
      <button class="btn" id="edit">編集</button></div>
    <div class="grid">
      <div class="field"><label>名前</label><div class="v">サンプルユーザー</div></div>
      <div class="field"><label>メール</label><div class="v">sample@example.com</div></div>
      <div class="field"><label>自己紹介</label><div class="v" id="bio">プロフィール画面のサンプルです。</div></div>
      <div class="field"><label>Web サイト</label><div class="v">https://example.com</div></div>
    </div>
  </div>
</body></html>`;

/** 編集フローを 9 秒ループで自動再生するデモ（録画の代替） */
const editFlowDemo = profileScreen(`
.cursor{position:fixed;width:18px;height:18px;border-radius:50%;border:2px solid #f25c6e;background:rgba(242,92,110,.25);z-index:50;pointer-events:none;
  animation:move 9s ease-in-out infinite}
@keyframes move{
  0%{top:40%;left:30%}
  14%{top:11%;left:86%}
  18%{top:11%;left:86%;transform:scale(.7)}
  22%{top:11%;left:86%;transform:scale(1)}
  40%{top:58%;left:40%}
  44%{top:58%;left:40%;transform:scale(.7)}
  62%{top:58%;left:40%;transform:scale(1)}
  74%{top:11%;left:86%}
  78%{top:11%;left:86%;transform:scale(.7)}
  100%{top:40%;left:30%}}
#edit{animation:btnflash 9s infinite}
@keyframes btnflash{16%,20%{background:#3b82f6}17%{transform:scale(.96)}74%,80%{background:#16a34a}0%,14%,24%,70%,84%,100%{background:#111419}}
#bio{position:relative;animation:editfield 9s infinite}
@keyframes editfield{22%,76%{box-shadow:0 0 0 2px #3b82f6 inset;border-radius:6px}0%,18%,84%,100%{box-shadow:none}}
#bio::after{content:"フロントエンドが好きです。";color:#3b82f6;display:inline-block;overflow:hidden;white-space:nowrap;vertical-align:bottom;
  animation:typing 9s steps(12) infinite}
@keyframes typing{0%,44%{max-width:0}66%,98%{max-width:200px}100%{max-width:0}}
body::after{content:"✓ プロフィールを保存しました";position:fixed;left:50%;bottom:18px;transform:translateX(-50%) translateY(80px);
  background:#16a34a;color:#fff;font-size:13px;padding:9px 16px;border-radius:99px;animation:toast 9s infinite}
@keyframes toast{0%,78%{transform:translateX(-50%) translateY(80px);opacity:0}82%,94%{transform:translateX(-50%) translateY(0);opacity:1}100%{transform:translateX(-50%) translateY(80px);opacity:0}}
`);

const testRun129 = `$ npm test -- profile --coverage

 PASS  app/api/users/[id]/profile/route.test.ts
  GET /api/users/[id]/profile
    ✓ 既存ユーザーのプロフィールを返す (12 ms)
    ✓ 存在しない ID で 404 (4 ms)
  PATCH /api/users/[id]/profile
    ✓ name / bio / location / website を更新できる (9 ms)
    ✓ name が空文字で 400 (3 ms)
    ✓ bio ちょうど 200 文字は許容 (5 ms)
    ✓ location ちょうど 100 文字は許容 (4 ms)
    ✓ website が https:// で始まらないと 400 (3 ms)
    ✓ id/email/createdAt は更新されない（allowlist） (6 ms)

 PASS  components/Header.test.tsx
  ✓ Profile リンクが表示される (18 ms)

----------------------|---------|----------|---------|---------
File                  | % Stmts | % Branch | % Funcs | % Lines
----------------------|---------|----------|---------|---------
All files             |   87.40 |    84.21 |   90.00 |   87.40
 route.ts             |   95.10 |    91.66 |  100.00 |   95.10
 ProfileClient.tsx    |   82.35 |    78.57 |   85.71 |   82.35
 Header.tsx           |  100.00 |   100.00 |  100.00 |  100.00
----------------------|---------|----------|---------|---------

Test Suites: 2 passed, 2 total
Tests:       9 passed, 9 total
Time:        2.84 s`;

const testRun131 = `$ pytest tests/auth/test_redirect.py -v

tests/auth/test_redirect.py::test_same_origin_relative_path_allowed PASSED   [ 25%]
tests/auth/test_redirect.py::test_external_origin_falls_back_to_root PASSED  [ 50%]
tests/auth/test_redirect.py::test_protocol_relative_evil_rejected PASSED     [ 75%]
tests/auth/test_redirect.py::test_missing_next_falls_back_to_root PASSED     [100%]

---------- coverage: platform darwin, python 3.13 ----------
Name               Stmts   Miss  Cover
--------------------------------------
auth/redirect.py      18      1    94%
--------------------------------------

============== 4 passed in 0.31s ==============`;

export const evidences: Record<number, Evidence[]> = {
  129: [
    {
      id: "ev-1",
      kind: "video",
      title: "編集フローの動作デモ",
      caption: "編集 → 自己紹介を入力 → 保存 → トースト表示まで。実装ブランチ feature/issue-129 上で記録。",
      payload: editFlowDemo,
      durationSec: 9,
    },
    {
      id: "ev-2",
      kind: "screenshot",
      title: "プロフィール画面（デスクトップ）",
      caption: "GET /api/users/1/profile のレスポンスを表示した状態。",
      payload: profileScreen(),
      viewport: "desktop",
    },
    {
      id: "ev-3",
      kind: "screenshot",
      title: "プロフィール画面（モバイル 390px）",
      caption: "レスポンシブ確認。ナビ折りたたみ・1 カラム化。",
      payload: profileScreen(),
      viewport: "mobile",
    },
    {
      id: "ev-4",
      kind: "terminal",
      title: "テスト実行結果（9 passed / coverage 87.4%）",
      caption: "TC-01〜TC-08 + Header テスト。カバレッジ 80% 基準クリア。",
      payload: testRun129,
    },
  ],
  131: [
    {
      id: "ev-5",
      kind: "terminal",
      title: "テスト実行結果（4 passed）",
      caption: "safeRedirect の許可/拒否 4 ケース。//evil.com の拒否を確認。",
      payload: testRun131,
    },
  ],
};

export function getEvidences(n: number): Evidence[] {
  return evidences[n] ?? [];
}
