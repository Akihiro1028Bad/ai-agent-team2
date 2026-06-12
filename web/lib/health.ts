// ヘルスモニタ用モック

export interface HealthItem {
  key: string;
  label: string;
  status: "ok" | "warn" | "error";
  value: string;
  detail: string;
}

export const healthItems: HealthItem[] = [
  { key: "poller", label: "GitHub ポーラー", status: "ok", value: "稼働中", detail: "最終ポーリング 42 秒前 / 間隔 300s" },
  { key: "rate", label: "API レート制限", status: "ok", value: "4,998 / 5,000", detail: "リセットまで 31 分" },
  { key: "agents", label: "エージェント実行枠", status: "warn", value: "3 / 4 使用中", detail: "#129 #126 #116 が実行中" },
  { key: "worktrees", label: "git worktree", status: "ok", value: "5 個", detail: "孤児 worktree なし（最終 GC 2 時間前）" },
  { key: "slack", label: "Slack 通知", status: "ok", value: "正常", detail: "直近 24h の送信 18 件 / 失敗 0" },
  { key: "queue", label: "タスクキュー", status: "ok", value: "深さ 2", detail: "待機 #127, #125（優先度順）" },
  { key: "ci", label: "CI 監視", status: "error", value: "1 件異常", detail: "#118 が失敗上限超過で中断中" },
  { key: "disk", label: "ワークスペース容量", status: "ok", value: "61% 使用", detail: "38.2 GB / 62.5 GB（worktree 合計 4.1 GB）" },
];

/** API レイテンシのスパークライン (ms) */
export const latencySeries = [220, 180, 195, 240, 210, 480, 230, 200, 190, 760, 280, 210, 190, 185, 230, 205, 198, 240, 220, 207];

/** ポーリング成功履歴（直近 30 回, true=成功） */
export const pollHistory: boolean[] = Array.from({ length: 30 }, (_, i) => !(i === 7 || i === 8));
