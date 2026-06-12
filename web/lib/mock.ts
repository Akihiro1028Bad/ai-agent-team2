import type {
  GateItem,
  IssueDetail,
  IssueEvent,
  IssueSummary,
  OrchestratorState,
  PhaseMeta,
  RepoConfig,
} from "./types";

// 統一パイプライン（直線の主経路 + 条件付き split / revise）
export const PHASES: PhaseMeta[] = [
  { key: "intake", label: "受付" },
  { key: "clarify", label: "ヒアリング" },
  { key: "split", label: "分割", conditional: true },
  { key: "plan", label: "計画" },
  { key: "approve", label: "承認" },
  { key: "implement", label: "実装" },
  { key: "review", label: "レビュー" },
  { key: "revise", label: "修正", conditional: true },
  { key: "done", label: "完了" },
];

/** rail に表示する主経路（条件付きを除いた7段） */
export const MAIN_PHASES: PhaseMeta[] = PHASES.filter((p) => !p.conditional);

export const PHASE_LABEL: Record<string, string> = Object.fromEntries(
  PHASES.map((p) => [p.key, p.label]),
);

export const TYPE_LABEL: Record<string, string> = {
  bug: "Bug",
  "feature-m": "Feature-M",
  "feature-l": "Feature-L",
};

export const STATUS_LABEL: Record<string, string> = {
  running: "稼働中",
  waiting: "人間待ち",
  suspended: "中断",
  done: "完了",
  blocked: "依存待ち",
};

export const issues: IssueSummary[] = [
  {
    number: 129,
    repo: "ai-agent-team2-test",
    title: "ユーザープロフィール画面の追加",
    type: "feature-m",
    phase: "implement",
    status: "running",
    costUsd: 1.04,
    prNumber: 130,
    branch: "feature/issue-129",
    updated: "たった今",
    needsHuman: undefined,
  },
  {
    number: 131,
    repo: "ai-agent-team2-test",
    title: "ログイン時の不正なリダイレクトを修正",
    type: "bug",
    phase: "approve",
    status: "waiting",
    costUsd: 0.18,
    updated: "3分前",
    needsHuman: "修正方針の承認待ち",
  },
  {
    number: 128,
    repo: "bigban",
    title: "通知設定のエクスポート機能",
    type: "feature-m",
    phase: "clarify",
    status: "waiting",
    costUsd: 0.26,
    updated: "12分前",
    needsHuman: "ヒアリング回答待ち（4問）",
  },
  {
    number: 126,
    repo: "tsutsu-site",
    title: "ダッシュボードの全面リニューアル",
    type: "feature-l",
    phase: "split",
    status: "running",
    costUsd: 0.71,
    updated: "1分前",
  },
  {
    number: 124,
    repo: "ai-agent-team2-test",
    title: "ユーザー検索機能の追加",
    type: "feature-m",
    phase: "review",
    status: "waiting",
    costUsd: 2.93,
    prNumber: 115,
    branch: "feature/issue-124",
    updated: "27分前",
    needsHuman: "実装レビュー応答待ち（1件）",
  },
  {
    number: 120,
    repo: "tsutsu-site",
    title: "ダークモード切り替えボタン",
    type: "feature-m",
    phase: "done",
    status: "done",
    costUsd: 1.62,
    prNumber: 111,
    updated: "2時間前",
  },
  {
    number: 118,
    repo: "bigban",
    title: "決済 Webhook の署名検証",
    type: "bug",
    phase: "implement",
    status: "suspended",
    costUsd: 0.94,
    updated: "5時間前",
    needsHuman: "CI 失敗が上限超過 → 手動対応",
  },
  {
    number: 116,
    repo: "ai-agent-team2-test",
    title: "型定義・モックデータの整理",
    type: "feature-m",
    phase: "review",
    status: "running",
    costUsd: 0.55,
    prNumber: 117,
    branch: "feature/issue-116",
    updated: "8分前",
  },
];

const events129: IssueEvent[] = [
  { id: "e1", at: "10:29", kind: "phase", title: "受付 → ヒアリング", detail: "feature-m と判定" },
  { id: "e2", at: "10:30", kind: "agent", title: "ヒアリング実行", detail: "要件確認の質問を4問投稿", cost: 0.14 },
  { id: "e3", at: "11:48", kind: "comment", title: "ヒアリング回答を検知", detail: "ユーザーが回答 → 計画へ" },
  { id: "e4", at: "11:52", kind: "agent", title: "計画/設計書を生成", detail: "issue-129.md（サブタスク3件）", cost: 0.29 },
  { id: "e5", at: "11:55", kind: "gate", title: "設計PR #130 を作成", detail: "承認待ち" },
  { id: "e6", at: "12:20", kind: "gate", title: "設計PR を承認", detail: "LGTM を検知 → 実装へ" },
  { id: "e7", at: "12:20", kind: "agent", title: "実装フェーズ開始", detail: "サブタスク 1/3: Route Handler" },
  { id: "e8", at: "12:22", kind: "commit", title: "feat: Route Handler の実装", detail: "GET/PATCH /api/users/[id]/profile" },
  { id: "e9", at: "12:24", kind: "commit", title: "feat: Header にプロフィールリンク追加" },
  { id: "e10", at: "12:27", kind: "ci", title: "CI 実行中…", detail: "build-and-test" },
];

export const issueDetails: Record<number, IssueDetail> = {
  129: {
    ...issues[0],
    body: "プロフィール画面を追加したい。既存の app/profile/page.tsx を完成させる形で、表示と編集に対応する。",
    designDoc:
      "# 設計書: ユーザープロフィール画面の追加\n\n## 概要\nServer/Client コンポーネント分割で実装。API はモック対応（ヒアリングで確認済み）。\n\n## サブタスク\n### subtask-1: Route Handler の実装\n- files: [`route.ts`, `route.test.ts`]\n- depends_on: []\n\n### subtask-2: Header ナビゲーション\n- files: [`Header.tsx`, `Header.test.tsx`]\n- depends_on: []\n\n### subtask-3: ProfilePage の分割\n- files: [`page.tsx`, `ProfileClient.tsx`]\n- depends_on: [1]",
    subtasks: [
      { id: 1, title: "Route Handler の実装", done: true },
      { id: 2, title: "Header ナビゲーション", done: true },
      { id: 3, title: "ProfilePage の Server/Client 分割", done: false },
    ],
    events: events129,
  },
};

export function getIssue(n: number): IssueDetail {
  return (
    issueDetails[n] ?? {
      ...(issues.find((i) => i.number === n) ?? issues[0]),
      body: "（モック）この Issue の本文。",
      events: [
        { id: "x1", at: "—", kind: "phase", title: "受付", detail: "タイプ判定" },
        { id: "x2", at: "—", kind: "agent", title: "処理中", detail: "モックデータ" },
      ],
    }
  );
}

export const gates: GateItem[] = [
  {
    id: "g1",
    kind: "approve-plan",
    issue: 131,
    repo: "ai-agent-team2-test",
    title: "ログイン時の不正なリダイレクトを修正",
    prompt:
      "原因: 未検証の `next` パラメータをそのまま location に使用。対策: 同一オリジンの許可リスト検証を追加する方針。承認しますか？",
    age: "3分前",
    type: "bug",
  },
  {
    id: "g2",
    kind: "hearing",
    issue: 128,
    repo: "bigban",
    title: "通知設定のエクスポート機能",
    prompt:
      "Q1. エクスポート形式は JSON / CSV どちらですか？\nQ2. 対象は本人の設定のみですか？\nQ3. 認証スコープは？\nQ4. ファイル名規則の指定は？",
    age: "12分前",
    type: "feature-m",
  },
  {
    id: "g3",
    kind: "review",
    issue: 124,
    repo: "ai-agent-team2-test",
    title: "ユーザー検索機能の追加",
    prompt: "レビュー指摘: 「検索のデバウンスは入っていますか？大量入力で過剰リクエストになりませんか？」",
    age: "27分前",
    type: "feature-m",
  },
];

export const recentActivity: IssueEvent[] = [
  { id: "a1", at: "たった今", kind: "ci", title: "#129 CI 実行中", detail: "build-and-test" },
  { id: "a2", at: "1分前", kind: "commit", title: "#126 分割案を生成", detail: "5 サブ Issue に分割" },
  { id: "a3", at: "3分前", kind: "gate", title: "#131 承認待ちに遷移", detail: "修正方針レビュー" },
  { id: "a4", at: "8分前", kind: "phase", title: "#116 実装 → レビュー", detail: "CI パス" },
  { id: "a5", at: "12分前", kind: "comment", title: "#128 ヒアリング質問を投稿", detail: "4問" },
  { id: "a6", at: "27分前", kind: "comment", title: "#124 レビュー指摘を検知", detail: "1件（質問）" },
  { id: "a7", at: "1時間前", kind: "error", title: "#118 CI 失敗が上限超過", detail: "中断 → 手動対応" },
];

export const repos: RepoConfig[] = [
  { owner: "Akihiro1028Bad", repo: "ai-agent-team2-test", account: "default", label: "ai-agent", baseBranch: "main" },
  { owner: "Akihiro1028Bad", repo: "bigban", account: "default", label: "ai-agent", baseBranch: "develop" },
  { owner: "Akihiro1028Bad", repo: "ai-agent-team2", account: "default", label: "ai-agent", baseBranch: "main" },
  { owner: "Akihiro1028Bad", repo: "tsutsu-site", account: "default", label: "ai-agent", baseBranch: "main" },
];

export const orchestrator: OrchestratorState = {
  running: true,
  pollingIntervalSec: 300,
  account: "Akihiro1028Bad",
  maxConcurrent: 4,
  rateRemaining: 4998,
  rateLimit: 5000,
};

// ダッシュボードの集計
export const stats = {
  active: issues.filter((i) => i.status === "running").length,
  waiting: issues.filter((i) => i.status === "waiting").length,
  suspended: issues.filter((i) => i.status === "suspended").length,
  doneToday: 3,
  costToday: issues.reduce((s, i) => s + i.costUsd, 0),
};
