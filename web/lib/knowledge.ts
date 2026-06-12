// 自己改善ループ（episode_store / pattern_extractor / skill_manager）の可視化用モック

export interface Episode {
  id: string;
  issue: number;
  repo: string;
  phase: string;
  outcome: "success" | "failure";
  summary: string;
  lesson: string;
  at: string;
}

export const episodes: Episode[] = [
  {
    id: "ep-24",
    issue: 129,
    repo: "ai-agent-team2-test",
    phase: "implement",
    outcome: "success",
    summary: "Server/Client 分割を 3 サブタスクで実装。テスト先行で 1 発 CI パス。",
    lesson: "Next.js App Router では Route Handler のテストを先に書くと手戻りが少ない",
    at: "30分前",
  },
  {
    id: "ep-23",
    issue: 118,
    repo: "bigban",
    phase: "implement",
    outcome: "failure",
    summary: "Webhook 署名検証の timestamp 許容範囲をハードコードし CI 失敗 ×3。",
    lesson: "時刻依存のテストは freezegun / 固定クロック注入を最初から使う",
    at: "5時間前",
  },
  {
    id: "ep-22",
    issue: 120,
    repo: "tsutsu-site",
    phase: "review",
    outcome: "success",
    summary: "レビュー指摘 2 件（a11y / 色コントラスト）に 1 ターンで対応完了。",
    lesson: "UI 変更時は prefers-color-scheme と aria 属性を最初からチェックリスト化",
    at: "2時間前",
  },
  {
    id: "ep-21",
    issue: 124,
    repo: "ai-agent-team2-test",
    phase: "implement",
    outcome: "failure",
    summary: "検索 API にデバウンスなしで実装 → レビューで指摘。",
    lesson: "入力連動のネットワーク呼び出しには必ずデバウンス/キャンセルを入れる",
    at: "1日前",
  },
];

export interface ExtractedPattern {
  id: string;
  title: string;
  description: string;
  confidence: number; // 0-1
  occurrences: number;
  status: "candidate" | "promoted";
}

export const patterns: ExtractedPattern[] = [
  {
    id: "pat-7",
    title: "入力連動フェッチにはデバウンス必須",
    description: "検索・サジェスト等、入力イベントに連動する API 呼び出しでデバウンス漏れの指摘が 3 回発生。実装プロンプトのチェックリストに追加候補。",
    confidence: 0.92,
    occurrences: 3,
    status: "promoted",
  },
  {
    id: "pat-6",
    title: "時刻依存テストには固定クロック",
    description: "timestamp / TTL / 有効期限まわりの CI 失敗が 2 リポジトリで発生。クロック注入のパターンを skill 化候補。",
    confidence: 0.81,
    occurrences: 2,
    status: "candidate",
  },
  {
    id: "pat-5",
    title: "App Router は Route Handler テスト先行",
    description: "route.ts → page.tsx の順で実装した Issue は CI 一発パス率が高い (4/4)。",
    confidence: 0.74,
    occurrences: 4,
    status: "candidate",
  },
];

export interface GeneratedSkill {
  id: string;
  name: string;
  fromPattern: string;
  usedCount: number;
  successRate: number;
  updated: string;
}

export const skills: GeneratedSkill[] = [
  { id: "sk-3", name: "debounced-fetch-checklist", fromPattern: "pat-7", usedCount: 5, successRate: 1.0, updated: "1日前" },
  { id: "sk-2", name: "nextjs-route-handler-tdd", fromPattern: "pat-5", usedCount: 9, successRate: 0.89, updated: "3日前" },
  { id: "sk-1", name: "design-doc-subtask-format", fromPattern: "—", usedCount: 21, successRate: 0.95, updated: "6日前" },
];

export const knowledgeStats = {
  episodes: 24,
  successRate: 0.79,
  patterns: patterns.length,
  skills: skills.length,
};
