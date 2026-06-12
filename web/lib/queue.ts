// 実行キュー（優先度並べ替え）用モック

import type { IssueType } from "./types";

export interface QueueEntry {
  issue: number;
  repo: string;
  title: string;
  type: IssueType;
  priority: "high" | "normal" | "low";
  enqueued: string;
  reason: string; // キュー待ちの理由
}

export const queueEntries: QueueEntry[] = [
  {
    issue: 127,
    repo: "bigban",
    title: "CSV インポートのバリデーション強化",
    type: "feature-m",
    priority: "high",
    enqueued: "10分前",
    reason: "実行枠待ち（3/4 使用中）",
  },
  {
    issue: 125,
    repo: "tsutsu-site",
    title: "OGP 画像の自動生成",
    type: "feature-m",
    priority: "normal",
    enqueued: "25分前",
    reason: "実行枠待ち",
  },
  {
    issue: 123,
    repo: "ai-agent-team2-test",
    title: "README のセットアップ手順更新",
    type: "bug",
    priority: "low",
    enqueued: "1時間前",
    reason: "実行枠待ち",
  },
  {
    issue: 122,
    repo: "bigban",
    title: "監査ログのエクスポート",
    type: "feature-l",
    priority: "normal",
    enqueued: "2時間前",
    reason: "依存 Issue #121 の完了待ち",
  },
];

export const PRIORITY_META: Record<QueueEntry["priority"], { label: string; color: string; weight: number }> = {
  high: { label: "高", color: "var(--color-rose)", weight: 0 },
  normal: { label: "中", color: "var(--color-amber)", weight: 1 },
  low: { label: "低", color: "var(--color-ink-faint)", weight: 2 },
};
