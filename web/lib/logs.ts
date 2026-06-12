// エージェント実行ログ（ライブログビューア用モック）

export type LogLevel = "info" | "tool" | "agent" | "warn" | "error" | "ok";

export interface LogLine {
  t: string; // 時刻
  level: LogLevel;
  source: string; // phase / tool 名
  text: string;
}

/** #129 実装フェーズのストリーミング風ログ */
export const liveLogs: Record<number, LogLine[]> = {
  129: [
    { t: "12:20:01", level: "info", source: "orchestrator", text: "phase=implement を開始 (subtask 3/3)" },
    { t: "12:20:02", level: "agent", source: "claude", text: "ProfilePage の Server/Client 分割を実装します" },
    { t: "12:20:04", level: "tool", source: "Read", text: "app/profile/page.tsx (84 lines)" },
    { t: "12:20:05", level: "tool", source: "Read", text: "lib/api/users.ts (132 lines)" },
    { t: "12:20:09", level: "agent", source: "claude", text: "既存 page.tsx を Server Component 化し、編集状態を ProfileClient へ移動" },
    { t: "12:20:11", level: "tool", source: "Write", text: "app/profile/ProfileClient.tsx (+118)" },
    { t: "12:20:13", level: "tool", source: "Edit", text: "app/profile/page.tsx (-61 +24)" },
    { t: "12:20:15", level: "tool", source: "Bash", text: "npm test -- profile  → 12 passed" },
    { t: "12:20:15", level: "ok", source: "test", text: "TC-01〜TC-08 すべて PASS（coverage 87.4%）" },
    { t: "12:20:18", level: "tool", source: "Bash", text: "git commit -m 'feat: ProfilePage を Server/Client に分割'" },
    { t: "12:20:21", level: "info", source: "github", text: "PR #130 へ push (3/3 subtask 完了)" },
    { t: "12:20:24", level: "info", source: "ci", text: "build-and-test を起動 → 実行中…" },
    { t: "12:20:31", level: "warn", source: "ci", text: "node_modules キャッシュ miss（初回 4m 見込み）" },
    { t: "12:21:02", level: "agent", source: "claude", text: "CI 完了を待機中。完了後 review フェーズへ遷移します" },
  ],
  118: [
    { t: "07:11:40", level: "info", source: "orchestrator", text: "phase=implement / ci_fix (2回目)" },
    { t: "07:11:52", level: "tool", source: "Bash", text: "pytest tests/webhook → 3 failed" },
    { t: "07:12:30", level: "error", source: "ci", text: "署名検証テストが3件失敗（timestamp 許容範囲）" },
    { t: "07:13:11", level: "error", source: "orchestrator", text: "CI 失敗が上限 (2) を超過 → suspended に遷移" },
    { t: "07:13:11", level: "warn", source: "notify", text: "Slack へ手動対応を依頼しました" },
  ],
};

export function getLogs(n: number): LogLine[] {
  return liveLogs[n] ?? [];
}
