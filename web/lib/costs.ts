// コスト・トークン使用量ダッシュボード用モック

export interface DayCost {
  day: string; // "6/01" 形式
  usd: number;
  tokensM: number; // 百万トークン
}

export const dailyCosts: DayCost[] = [
  { day: "5/28", usd: 3.1, tokensM: 2.4 },
  { day: "5/29", usd: 4.6, tokensM: 3.6 },
  { day: "5/30", usd: 1.2, tokensM: 0.9 },
  { day: "5/31", usd: 0.4, tokensM: 0.3 },
  { day: "6/01", usd: 5.8, tokensM: 4.5 },
  { day: "6/02", usd: 7.2, tokensM: 5.7 },
  { day: "6/03", usd: 4.9, tokensM: 3.8 },
  { day: "6/04", usd: 6.4, tokensM: 5.1 },
  { day: "6/05", usd: 8.9, tokensM: 7.0 },
  { day: "6/06", usd: 5.5, tokensM: 4.2 },
  { day: "6/07", usd: 2.1, tokensM: 1.6 },
  { day: "6/08", usd: 6.8, tokensM: 5.3 },
  { day: "6/09", usd: 9.4, tokensM: 7.4 },
  { day: "6/10", usd: 8.2, tokensM: 6.3 },
];

export interface PhaseCost {
  phase: string;
  label: string;
  usd: number;
  color: string;
}

/** フェーズ別の内訳（今月） */
export const phaseCosts: PhaseCost[] = [
  { phase: "implement", label: "実装", usd: 38.2, color: "var(--color-signal)" },
  { phase: "plan", label: "計画", usd: 14.6, color: "var(--color-cyan)" },
  { phase: "revise", label: "修正", usd: 9.8, color: "var(--color-rose)" },
  { phase: "clarify", label: "ヒアリング", usd: 4.1, color: "var(--color-amber)" },
  { phase: "intake", label: "受付ほか", usd: 2.4, color: "var(--color-violet)" },
];

export interface IssueCostRow {
  issue: number;
  repo: string;
  title: string;
  usd: number;
  inTokensK: number;
  outTokensK: number;
  turns: number;
}

export const issueCosts: IssueCostRow[] = [
  { issue: 124, repo: "ai-agent-team2-test", title: "ユーザー検索機能の追加", usd: 2.93, inTokensK: 1840, outTokensK: 92, turns: 31 },
  { issue: 120, repo: "tsutsu-site", title: "ダークモード切り替えボタン", usd: 1.62, inTokensK: 1100, outTokensK: 48, turns: 18 },
  { issue: 129, repo: "ai-agent-team2-test", title: "ユーザープロフィール画面の追加", usd: 1.04, inTokensK: 720, outTokensK: 35, turns: 14 },
  { issue: 118, repo: "bigban", title: "決済 Webhook の署名検証", usd: 0.94, inTokensK: 610, outTokensK: 27, turns: 12 },
  { issue: 126, repo: "tsutsu-site", title: "ダッシュボードの全面リニューアル", usd: 0.71, inTokensK: 530, outTokensK: 19, turns: 8 },
  { issue: 128, repo: "bigban", title: "通知設定のエクスポート機能", usd: 0.26, inTokensK: 190, outTokensK: 8, turns: 4 },
  { issue: 131, repo: "ai-agent-team2-test", title: "ログイン時の不正なリダイレクトを修正", usd: 0.18, inTokensK: 120, outTokensK: 6, turns: 3 },
];

export const costSummary = {
  monthUsd: dailyCosts.reduce((s, d) => s + d.usd, 0),
  monthBudgetUsd: 120,
  avgPerIssueUsd: 1.1,
  avgPerDoneIssueUsd: 1.9,
};
