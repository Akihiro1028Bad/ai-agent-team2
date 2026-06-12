// 通知センター用モック

export type NotificationKind = "gate" | "error" | "done" | "info";

/**
 * 既読 ID セットに新しい ID を加算的にマージし、上限 cap 件に収める。
 *
 * - 重複は Set 化で除去される。
 * - cap を超えた場合は「マージ配列の末尾 cap 件」を保持（新しい ID 優先）。
 * - 最終 Set サイズは cap 以下になることが保証される。
 */
export function addReadIds(current: Set<string>, ids: string[], cap = 200): Set<string> {
  const merged = [...current, ...ids];
  return new Set(merged.slice(Math.max(0, merged.length - cap)));
}

export interface AppNotification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  at: string;
  read: boolean;
  href?: string;
}

export const notifications: AppNotification[] = [
  {
    id: "n1",
    kind: "gate",
    title: "#131 修正方針の承認待ち",
    body: "オープンリダイレクト対策の方針が提出されました。承認すると実装に進みます。",
    at: "3分前",
    read: false,
    href: "/approvals",
  },
  {
    id: "n2",
    kind: "gate",
    title: "#128 ヒアリング回答待ち（4問）",
    body: "エクスポート形式・対象範囲・認証スコープ・ファイル名規則の確認。",
    at: "12分前",
    read: false,
    href: "/approvals",
  },
  {
    id: "n3",
    kind: "info",
    title: "#129 実装が 3/3 サブタスクまで進行",
    body: "CI 完了後にレビューへ遷移します。",
    at: "18分前",
    read: false,
    href: "/issues/129",
  },
  {
    id: "n4",
    kind: "gate",
    title: "#124 レビュー指摘に応答が必要",
    body: "「検索のデバウンスは入っていますか？」への回答待ち。",
    at: "27分前",
    read: true,
    href: "/approvals",
  },
  {
    id: "n5",
    kind: "error",
    title: "#118 CI 失敗が上限超過 → 中断",
    body: "署名検証テスト3件が失敗。手動対応が必要です。",
    at: "1時間前",
    read: true,
    href: "/issues/118",
  },
  {
    id: "n6",
    kind: "done",
    title: "#120 完了：ダークモード切り替えボタン",
    body: "PR #111 がマージされました（コスト $1.62）。",
    at: "2時間前",
    read: true,
    href: "/issues/120",
  },
];
